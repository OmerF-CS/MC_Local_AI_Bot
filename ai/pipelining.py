"""Dual-Thread Anticipatory Pipelining for Zero-Latency Action Execution.

Pre-computes the next AI decision in a background asynchronous task while the current
physical action executes in Mineflayer. Upon action completion, dispatches the pre-computed
decision with near-zero latency (< 5ms), eliminating idle gaps while preserving safety
via strict interrupt guards.
"""
import asyncio
import copy
import math
import re
import time
from typing import Dict, Any, Tuple, Optional, List

from utils.logger import get_logger
from ai.progression_tree import TECH_TREE

logger = get_logger("AnticipatoryPipeline")

SMELT_OUTPUT_MAP: Dict[str, str] = {
    "raw_iron": "iron_ingot",
    "iron_ore": "iron_ingot",
    "deepslate_iron_ore": "iron_ingot",
    "raw_gold": "gold_ingot",
    "gold_ore": "gold_ingot",
    "deepslate_gold_ore": "gold_ingot",
    "raw_copper": "copper_ingot",
    "copper_ore": "copper_ingot",
    "cobblestone": "stone",
    "sand": "glass",
    "clay": "brick",
    "clay_ball": "brick",
    "beef": "cooked_beef",
    "porkchop": "cooked_porkchop",
    "chicken": "cooked_chicken",
    "mutton": "cooked_mutton",
    "salmon": "cooked_salmon",
    "cod": "cooked_cod",
    "potato": "baked_potato",
}


class StatePredictor:
    """Predicts post-action state delta for speculative pre-computation."""

    def predict_post_action_state(
        self,
        current_state: Dict[str, Any],
        command: str,
        args: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Creates a deep copy of current_state and simulates inventory and position changes."""
        if not current_state or not isinstance(current_state, dict):
            return {}

        predicted_state = copy.deepcopy(current_state)
        args = args or {}
        cmd = str(command or "").lower().strip()

        # Extract current inventory into a flexible dict
        inv_dict = self._extract_inventory_dict(predicted_state)

        # 1. collect_block: increment inv_dict[block_name] by count (default 1)
        if cmd == "collect_block":
            block_name = str(
                args.get("block_name")
                or args.get("target")
                or args.get("name")
                or args.get("item")
                or args.get("block")
                or "stone"
            ).lower().strip()
            count = int(args.get("count", 1))
            inv_dict[block_name] = inv_dict.get(block_name, 0) + count

        # 2. craft_item: deduct ingredients required by recipe, increment inv_dict[item_name] by count
        elif cmd == "craft_item":
            item_name = str(
                args.get("item_name")
                or args.get("item")
                or args.get("target")
                or args.get("material")
                or args.get("name")
                or ""
            ).lower().strip()
            count = int(args.get("count", 1))
            if item_name:
                self._deduct_craft_ingredients(inv_dict, item_name, count)
                inv_dict[item_name] = inv_dict.get(item_name, 0) + count

        # 3. smelt_item: deduct raw ore and fuel (coal/wood), increment smelted item
        elif cmd == "smelt_item":
            input_item = str(
                args.get("input_item")
                or args.get("item_name")
                or args.get("item")
                or args.get("target")
                or "raw_iron"
            ).lower().strip()
            count = int(args.get("count", 1))

            output_item = SMELT_OUTPUT_MAP.get(input_item)
            if not output_item:
                if input_item.startswith("raw_"):
                    output_item = input_item[4:] + "_ingot"
                elif "ore" in input_item:
                    base = input_item.replace("_ore", "").replace("ore", "")
                    output_item = f"{base}_ingot"
                else:
                    output_item = f"smelted_{input_item}"

            # Deduct raw ore
            if input_item in inv_dict:
                inv_dict[input_item] = max(0, inv_dict[input_item] - count)
                if inv_dict[input_item] <= 0:
                    del inv_dict[input_item]

            # Deduct fuel (coal/wood)
            self._deduct_fuel(inv_dict, count)

            # Increment smelted item
            inv_dict[output_item] = inv_dict.get(output_item, 0) + count

        # 4. go_to_coordinates: update position to {"x": args["x"], "y": args.get("y", cur_y), "z": args["z"]}
        elif cmd in ("go_to_coordinates", "move_to", "pathfind"):
            cur_pos = predicted_state.get("position") or {}
            cur_y = cur_pos.get("y", 64) if isinstance(cur_pos, dict) else 64
            target_x = args.get("x", cur_pos.get("x", 0) if isinstance(cur_pos, dict) else 0)
            target_y = args.get("y", cur_y)
            target_z = args.get("z", cur_pos.get("z", 0) if isinstance(cur_pos, dict) else 0)
            predicted_state["position"] = {
                "x": target_x,
                "y": target_y,
                "z": target_z
            }

        # 5. eat_food: increment food by 4 (capped at 20)
        elif cmd in ("eat_food", "eat"):
            cur_food = predicted_state.get("food", 20)
            predicted_state["food"] = min(20, cur_food + 4)
            # Deduct one edible food item if available
            edible_foods = (
                "bread", "cooked_beef", "cooked_porkchop", "apple", "cooked_chicken",
                "cooked_mutton", "baked_potato", "carrot", "beef", "porkchop", "sweet_berries"
            )
            for f in edible_foods:
                if f in inv_dict and inv_dict[f] > 0:
                    inv_dict[f] -= 1
                    if inv_dict[f] <= 0:
                        del inv_dict[f]
                    break

        # Synchronize updated inventory back to state
        clean_inv = {k: v for k, v in inv_dict.items() if v > 0}
        predicted_state["inventory"] = dict(clean_inv)
        predicted_state["inventory_items"] = [{"name": k, "count": v} for k, v in clean_inv.items()]
        predicted_state["inventory_summary"] = ", ".join(f"{k} x{v}" for k, v in clean_inv.items()) if clean_inv else "Empty"

        return predicted_state

    def _extract_inventory_dict(self, state: Dict[str, Any]) -> Dict[str, int]:
        """Extracts name -> count dictionary from inventory or inventory_items."""
        inv_dict: Dict[str, int] = {}
        if "inventory_items" in state and isinstance(state["inventory_items"], list):
            for item in state["inventory_items"]:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).lower().strip()
                    if name:
                        try:
                            inv_dict[name] = inv_dict.get(name, 0) + int(item.get("count", 1))
                        except (ValueError, TypeError):
                            pass
        if "inventory" in state and isinstance(state["inventory"], dict):
            for k, v in state["inventory"].items():
                name = str(k).lower().strip()
                if name:
                    try:
                        inv_dict[name] = int(v)
                    except (ValueError, TypeError):
                        pass
        elif "inventory" in state and isinstance(state["inventory"], list) and not inv_dict:
            for item in state["inventory"]:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).lower().strip()
                    if name:
                        inv_dict[name] = inv_dict.get(name, 0) + int(item.get("count", 1))
                elif isinstance(item, str):
                    name = item.lower().strip()
                    if name:
                        inv_dict[name] = inv_dict.get(name, 0) + 1
        return inv_dict

    def _deduct_craft_ingredients(self, inv_dict: Dict[str, int], item_name: str, count: int) -> None:
        """Deducts craft ingredients according to Minecraft Tech Tree and equivalent materials."""
        recipe = TECH_TREE.get(item_name)
        if recipe and "ingredients" in recipe:
            for ing_tag, ing_count in recipe["ingredients"].items():
                needed = ing_count * count
                self._deduct_ingredient(inv_dict, ing_tag, needed)
            return

        # Fallback built-in recipes
        if "plank" in item_name:
            # 1 log -> 4 planks
            logs_needed = max(1, math.ceil(count / 4))
            self._deduct_ingredient(inv_dict, "log", logs_needed)
        elif item_name in ("stick", "sticks"):
            # 2 planks -> 4 sticks
            planks_needed = max(1, math.ceil(count / 2))
            self._deduct_ingredient(inv_dict, "planks", planks_needed)
        elif item_name == "torch":
            self._deduct_ingredient(inv_dict, "coal", count)
            self._deduct_ingredient(inv_dict, "stick", count)

    def _deduct_ingredient(self, inv_dict: Dict[str, int], tag: str, needed: int) -> None:
        """Deducts required ingredients using tag awareness (wood variants, stone variants, sticks)."""
        if needed <= 0:
            return

        # 1. Exact match
        if inv_dict.get(tag, 0) >= needed:
            inv_dict[tag] -= needed
            if inv_dict[tag] <= 0:
                del inv_dict[tag]
            return

        if inv_dict.get(tag, 0) > 0:
            needed -= inv_dict[tag]
            del inv_dict[tag]

        # 2. Tag equivalents
        if tag in ("planks", "wooden_planks"):
            # Deduct from plank variants
            for k in list(inv_dict.keys()):
                if "plank" in k:
                    avail = inv_dict[k]
                    take = min(avail, needed)
                    inv_dict[k] -= take
                    needed -= take
                    if inv_dict[k] <= 0:
                        del inv_dict[k]
                    if needed <= 0:
                        return
            # Deduct from logs (1 log = 4 planks)
            if needed > 0:
                for k in list(inv_dict.keys()):
                    if any(w in k for w in ("log", "wood", "stem")):
                        avail_logs = inv_dict[k]
                        logs_needed = math.ceil(needed / 4)
                        take_logs = min(avail_logs, logs_needed)
                        inv_dict[k] -= take_logs
                        if inv_dict[k] <= 0:
                            del inv_dict[k]
                        excess_planks = (take_logs * 4) - needed
                        if excess_planks > 0:
                            inv_dict["oak_planks"] = inv_dict.get("oak_planks", 0) + excess_planks
                        needed -= take_logs * 4
                        if needed <= 0:
                            return

        elif tag in ("stick", "sticks"):
            if "stick" in inv_dict:
                take = min(inv_dict["stick"], needed)
                inv_dict["stick"] -= take
                needed -= take
                if inv_dict["stick"] <= 0:
                    del inv_dict["stick"]
                if needed <= 0:
                    return
            if needed > 0:
                # Deduct from planks
                for k in list(inv_dict.keys()):
                    if "plank" in k:
                        avail = inv_dict[k]
                        planks_needed = math.ceil(needed / 2)
                        take_planks = min(avail, planks_needed)
                        inv_dict[k] -= take_planks
                        if inv_dict[k] <= 0:
                            del inv_dict[k]
                        excess_sticks = (take_planks * 2) - needed
                        if excess_sticks > 0:
                            inv_dict["stick"] = inv_dict.get("stick", 0) + excess_sticks
                        needed -= take_planks * 2
                        if needed <= 0:
                            return

        elif tag in ("stone", "cobblestone", "stone_tool_materials"):
            for alt in ("cobblestone", "cobbled_deepslate", "blackstone", "stone", "deepslate"):
                if alt in inv_dict:
                    avail = inv_dict[alt]
                    take = min(avail, needed)
                    inv_dict[alt] -= take
                    needed -= take
                    if inv_dict[alt] <= 0:
                        del inv_dict[alt]
                    if needed <= 0:
                        return

        elif tag in ("iron_materials", "iron_ingot"):
            if "iron_ingot" in inv_dict:
                avail = inv_dict["iron_ingot"]
                take = min(avail, needed)
                inv_dict["iron_ingot"] -= take
                needed -= take
                if inv_dict["iron_ingot"] <= 0:
                    del inv_dict["iron_ingot"]

        elif tag in ("fuel", "smelting_fuel"):
            for fuel_item in ("coal", "charcoal"):
                if fuel_item in inv_dict:
                    avail = inv_dict[fuel_item]
                    take = min(avail, needed)
                    inv_dict[fuel_item] -= take
                    needed -= take
                    if inv_dict[fuel_item] <= 0:
                        del inv_dict[fuel_item]
                    if needed <= 0:
                        return

        else:
            # Direct match fallback
            if tag in inv_dict:
                inv_dict[tag] = max(0, inv_dict[tag] - needed)
                if inv_dict[tag] <= 0:
                    del inv_dict[tag]

    def _deduct_fuel(self, inv_dict: Dict[str, int], count: int) -> None:
        """Deducts furnace smelting fuel (coal, charcoal, wood/planks)."""
        fuel_needed = max(1, math.ceil(count / 8))
        for fuel_item in ("coal", "charcoal"):
            if fuel_item in inv_dict:
                deduct = min(inv_dict[fuel_item], fuel_needed)
                inv_dict[fuel_item] -= deduct
                fuel_needed -= deduct
                if inv_dict[fuel_item] <= 0:
                    del inv_dict[fuel_item]
                if fuel_needed <= 0:
                    return

        for k in list(inv_dict.keys()):
            if any(w in k for w in ("plank", "log", "wood")):
                deduct = min(inv_dict[k], fuel_needed)
                inv_dict[k] -= deduct
                fuel_needed -= deduct
                if inv_dict[k] <= 0:
                    del inv_dict[k]
                if fuel_needed <= 0:
                    return


class AnticipatoryPipeline:
    """Zero-latency pipelining engine pre-computing next actions during current action execution."""

    def __init__(self, planner: Any):
        self.planner = planner
        self.predictor = StatePredictor()
        self._precomputed_task: Optional[asyncio.Task] = None
        self._precomputed_start_time: float = 0.0
        self._anticipated_state: Optional[Dict[str, Any]] = None
        self._running_command: Optional[str] = None
        self._running_args: Optional[Dict[str, Any]] = None

    def start_precomputation(
        self,
        current_state: Dict[str, Any],
        running_command: str,
        running_args: Dict[str, Any]
    ) -> None:
        """Predicts post-action state and spawns background decision task."""
        if self._precomputed_task and not self._precomputed_task.done():
            self._precomputed_task.cancel()

        self._anticipated_state = self.predictor.predict_post_action_state(
            current_state,
            running_command,
            running_args
        )
        self._running_command = running_command
        self._running_args = running_args
        self._precomputed_start_time = time.perf_counter()
        self._precomputed_task = asyncio.create_task(
            self.planner.decide_next_action(self._anticipated_state, is_speculative=True)
        )
        logger.debug(
            f"🚀 [Pipeline]: Pre-computation launched in background for '{running_command}'."
        )

    def should_discard_precomputation(
        self,
        current_state: Dict[str, Any],
        pre_snapshot: Dict[str, Any],
        exec_result: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """Evaluates interrupt conditions (action failed, health drop, sudden hostile threat)."""
        # 1. Action failed
        if not (isinstance(exec_result, dict) and exec_result.get("success", False)):
            return True, "action_failed"

        # 2. Health drop > 1.5 HP
        curr_health = current_state.get("health", 20)
        pre_health = pre_snapshot.get("health", 20)
        if isinstance(curr_health, (int, float)) and isinstance(pre_health, (int, float)):
            if curr_health < pre_health - 1.5:
                return True, "health_damage"

        # 3. Sudden hostile threat
        curr_hostiles = current_state.get("nearby_hostiles") or []
        pre_hostiles = pre_snapshot.get("nearby_hostiles") or []
        if len(curr_hostiles) > len(pre_hostiles):
            return True, "hostile_threat"

        if self._has_hostile_within_5m(curr_hostiles):
            return True, "hostile_threat"

        return False, ""

    def _has_hostile_within_5m(self, hostiles: List[Any]) -> bool:
        """Checks if any hostile entity is within 5 blocks distance."""
        for h in hostiles:
            if isinstance(h, dict):
                dist = h.get("distance", 999.0)
                try:
                    if float(dist) <= 5.0:
                        return True
                except (ValueError, TypeError):
                    pass
            elif isinstance(h, str):
                m = re.search(r"\((\d+(?:\.\d+)?)\s*m\b", h, re.IGNORECASE)
                if m:
                    try:
                        if float(m.group(1)) <= 5.0:
                            return True
                    except ValueError:
                        pass
                elif any(f"({d}m" in h for d in (1, 2, 3, 4, 5)):
                    return True
        return False

    async def get_next_decision(
        self,
        current_state: Dict[str, Any],
        pre_snapshot: Dict[str, Any],
        exec_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Returns pre-computed decision if valid, or recalculates fresh decision if interrupted."""
        is_interrupted, reason = self.should_discard_precomputation(
            current_state,
            pre_snapshot,
            exec_result
        )

        if is_interrupted:
            if self._precomputed_task and not self._precomputed_task.done():
                self._precomputed_task.cancel()
            self._precomputed_task = None
            if hasattr(self.planner, "discard_speculative_state"):
                self.planner.discard_speculative_state()
            logger.warning(
                f"⚠️ [Pipeline Interrupt]: Discarded pre-computed decision (reason: {reason}). "
                "Computing fresh decision..."
            )
            return await self.planner.decide_next_action(current_state)

        if self._precomputed_task is None:
            logger.debug(
                "ℹ️ [Pipeline]: No pre-computed decision task available. Computing fresh decision..."
            )
            return await self.planner.decide_next_action(current_state)

        try:
            t0 = time.perf_counter()
            decision = await self._precomputed_task
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            next_action = "none"
            if decision and isinstance(decision, dict) and decision.get("tool_calls"):
                next_action = decision["tool_calls"][0].get("name", "action")

            if hasattr(self.planner, "commit_speculative_state"):
                self.planner.commit_speculative_state()

            logger.info(
                f"⚡ [Pipeline 0ms Dispatch]: Pre-computed {next_action} ready! (waited {elapsed_ms:.2f}ms)"
            )
            return decision
        except asyncio.CancelledError:
            if hasattr(self.planner, "discard_speculative_state"):
                self.planner.discard_speculative_state()
            logger.info("ℹ️ [Pipeline]: Pre-computation task cancelled. Computing fresh decision...")
            return await self.planner.decide_next_action(current_state)
        except Exception as e:
            if hasattr(self.planner, "discard_speculative_state"):
                self.planner.discard_speculative_state()
            logger.warning(
                f"⚠️ [Pipeline Error]: Pre-computation task failed: {e}. Falling back to fresh decision..."
            )
            return await self.planner.decide_next_action(current_state)
        finally:
            self._precomputed_task = None
