"""Autonomous human-like Minecraft co-op partner brain - Production hardened."""
import asyncio
import json
import math
import random
import time
from typing import Dict, Any, List, Optional
from utils.logger import get_logger
from ai.progression_tree import (
    get_current_progression_goal,
    resolve_missing_ingredients,
    get_stage_rank,
    get_milestone_by_stage,
    get_optimal_ore_height
)

logger = get_logger("AutonomousCoopBrain")


class AutonomousCoopBrain:
    """Proactive decision engine using Ollama and Minecraft progression tech tree."""

    def __init__(self, ollama_brain, bot_owner: str = "Omer", db=None):
        self.brain = ollama_brain
        self.bot_owner = bot_owner
        self.db = db
        self.last_action_command = None
        self.consecutive_repeats = 0
        self.consecutive_hunt_failures = 0
        self._tried_emergency_farm = False
        self.fallback_consecutive_count = 0
        self.last_llm_failure_time = 0
        self.last_goal_target = None
        self.last_hunt_emergency_time = 0.0
        self.last_eat_emergency_time = 0.0

        self.checkpoint_stage = None
        self.checkpoint_target = None

        # F0.5: Resume from recorded progression checkpoint if available
        if self.db:
            try:
                latest = self.db.get_latest_progression()
                if latest:
                    self.checkpoint_stage = latest.get("stage")
                    self.checkpoint_target = latest.get("target")
                    self.last_goal_target = self.checkpoint_target
                    logger.info(f"💾 [Progression Checkpoint Loaded] Resuming from Era: {self.checkpoint_stage} -> Target: {self.checkpoint_target}")
            except Exception as e:
                logger.warning(f"Failed to load latest progression checkpoint: {e}")

    def parse_inventory(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """Converts inventory item list into a name -> count mapping."""
        inv = {}
        for item in items:
            name = item.get("name", "")
            count = item.get("count", 0)
            inv[name] = inv.get(name, 0) + count
        return inv

    def _should_use_emergency_action(self, state: Dict[str, Any], inv: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
        """Immediate reflex for critical health, imminent starvation, or night danger."""
        health = state.get("health", 20)
        food = state.get("food", 20)
        nearby_hostiles = state.get("nearby_hostiles", [])
        is_day = state.get("is_day", True)
        now = time.time()
        inv_map = inv or {}

        # 0. If currently sheltered inside a bunker: check if it's safe to break out!
        if state.get("is_sheltered"):
            from ai.shelter import should_break_out_of_shelter
            if should_break_out_of_shelter(state):
                logger.info("☀️ [SHELTER] Threat passed, daylight arrived. Breaking out of bunker!")
                return {
                    "text": "The danger has passed and it is safe outside. Breaking out of my shelter!",
                    "tool_calls": [{"name": "break_out_shelter", "arguments": {}}]
                }
            else:
                # Still unsafe - remain safely inside bunker, eat if needed
                if food < 18 and any(f in inv for f in ["bread", "cooked_beef", "cooked_porkchop", "apple"]):
                    return {
                        "text": "Resting safely inside my shelter and eating food to heal.",
                        "tool_calls": [{"name": "eat_food", "arguments": {}}]
                    }
                # Check for bed to skip night
                vis_res = state.get("visible_resources", {})
                if vis_res.get("bed") or any("bed" in i for i in (inv or {})):
                    return {
                        "text": "Sleeping safely inside my shelter to skip the night.",
                        "tool_calls": [{"name": "sleep_in_bed", "arguments": {}}]
                    }
                # Check if hostile mob is inside or touching bunker (< 2.5m)
                for h in nearby_hostiles:
                    if any(d in h for d in ["(1m away)", "(2m away)"]):
                        mob_name = h.split()[0]
                        logger.warning(f"⚔️ Mob {mob_name} within 2m inside bunker! Defending immediately.")
                        return {
                            "text": f"Defending against {mob_name} inside bunker!",
                            "tool_calls": [{"name": "attack_target", "arguments": {"target_name": mob_name}}]
                        }
                # Safe inside shelter: stay sheltered and wait, rate-limit chat to avoid spam
                now = time.time()
                if now - getattr(self, "last_bunker_wait_chat_time", 0.0) >= 30.0:
                    self.last_bunker_wait_chat_time = now
                    return {
                        "text": "Remaining safely inside shelter until hostiles clear and daylight arrives.",
                        "tool_calls": [{"name": "say_chat", "arguments": {"message": "Safe inside bunker. Waiting for threats to pass..."}}]
                    }
                return {
                    "text": "Waiting safely inside bunker until daylight arrives.",
                    "tool_calls": []
                }

        # 1. Critical health (<= 6 HP / 3 hearts) with nearby hostile mobs -> build emergency shelter
        if health <= 6 and nearby_hostiles:
            logger.warning(f"🚨 [EMERGENCY] Critical health ({health}/20) with hostiles nearby! Building emergency bunker.")
            return {
                "text": "I'm in critical danger! Sealing myself in an emergency bunker NOW!",
                "tool_calls": [
                    {"name": "build_shelter", "arguments": {"mode": "auto"}}
                ]
            }

        # 2. Critical starvation (<= 4 hunger)
        if food <= 4:
            inv_summary = state.get("inventory_summary", "").lower()
            food_items = ["cooked_beef", "cooked_porkchop", "bread", "apple", "cooked_chicken", "cooked_mutton", "baked_potato"]
            has_food = any(f in inv for f in food_items) if inv else any(f in inv_summary for f in food_items)

            now = time.time()
            if has_food:
                self.consecutive_hunt_failures = 0
                self._tried_emergency_farm = False
                if now - getattr(self, "last_eat_emergency_time", 0.0) >= 3.0:
                    self.last_eat_emergency_time = now
                    logger.warning(f"🍽️ [EMERGENCY] Starvation ({food}/20)! Eating immediately.")
                    return {
                        "text": "I'm STARVING! Eating immediately!",
                        "tool_calls": [{"name": "eat_food", "arguments": {}}]
                    }
                return None
            else:
                # Check for instant hay bale / farm harvest before roaming for animals
                from ai.farming import should_prioritize_farming, get_farming_action_plan
                if inv and should_prioritize_farming(inv, state):
                    farm_plan = get_farming_action_plan(inv, state)
                    return {
                        "text": "I'm starving! Harvesting nearby crops/hay bales for food!",
                        "tool_calls": [farm_plan]
                    }

                # Check if passives are actually visible nearby
                nearby_passives = state.get("nearby_passives", [])
                has_nearby_animals = any(
                    any(a in p.lower() for a in ["cow", "pig", "sheep", "chicken"])
                    for p in nearby_passives
                )

                # Stuck hunt loop breaker: if 3 consecutive hunts produced no food, switch strategy
                hunt_failures = getattr(self, "consecutive_hunt_failures", 0)
                if hunt_failures >= 3:
                    if not getattr(self, "_tried_emergency_farm", False):
                        self._tried_emergency_farm = True
                        logger.warning(f"⚠️ [STUCK LOOP BREAK] 3 consecutive hunts failed! Shifting to crop harvesting.")
                        return {
                            "text": "No animals found after 3 hunts! Harvesting any available crops for food.",
                            "tool_calls": [{"name": "farm_crops", "arguments": {"crop_type": "all"}}]
                        }
                    else:
                        self._tried_emergency_farm = False
                        self.consecutive_hunt_failures = 0
                        logger.warning(f"⚠️ [STUCK LOOP BREAK] Starvation hunt loop broken! Relocating 45 blocks to find food.")
                        pos = state.get("position", {"x": 0, "y": 64, "z": 0})
                        angle = random.random() * 2 * math.pi
                        target_x = pos.get("x", 0) + math.cos(angle) * 45
                        target_z = pos.get("z", 0) + math.sin(angle) * 45
                        return {
                            "text": "Starvation area exhausted. Relocating to new territory for food.",
                            "tool_calls": [{"name": "go_to_coordinates", "arguments": {"x": round(target_x), "y": pos.get("y", 64), "z": round(target_z)}}]
                        }

                cooldown = 15.0 if not has_nearby_animals else 8.0
                if now - getattr(self, "last_hunt_emergency_time", 0.0) >= cooldown:
                    self.last_hunt_emergency_time = now
                    self.consecutive_hunt_failures = hunt_failures + 1
                    logger.warning(f"🍽️ [EMERGENCY] Starvation ({food}/20)! Hunting for meat (attempt {self.consecutive_hunt_failures}).")
                    return {
                        "text": "I'm STARVING and have NO food! Hunting for meat NOW!",
                        "tool_calls": [{"name": "hunt_food", "arguments": {"animal_type": "any"}}]
                    }
                else:
                    logger.debug("⏳ Starvation hunt cooldown active. Skipping hunt spam.")

        # 3. Night and low health with hostiles
        if not is_day and health < 10 and nearby_hostiles and not state.get("is_guarding"):
            dimension = str(state.get("dimension", "overworld")).lower()
            if "nether" in dimension or "end" in dimension:
                logger.warning("🔥 [EMERGENCY] Hostiles and low health in Nether/End! Guarding player (no beds in Nether/End).")
                return {
                    "text": "Dangerous mobs nearby! Defending and staying alert!",
                    "tool_calls": [
                        {"name": "guard_player", "arguments": {"player_name": self.bot_owner}}
                    ]
                }

            logger.warning("🌙 [EMERGENCY] Night + low health + hostiles! Seeking shelter.")
            vis_res = state.get("visible_resources", {})
            if vis_res.get("bed"):
                return {
                    "text": "Night and surrounded! Sleeping in bed for safety.",
                    "tool_calls": [{"name": "sleep_in_bed", "arguments": {}}]
                }
            else:
                return {
                    "text": "Night and danger! Constructing an emergency shelter/bunker for safety.",
                    "tool_calls": [
                        {"name": "build_shelter", "arguments": {"mode": "auto"}}
                    ]
                }

        # 4. Phantom insomnia prevention & Night sleep routine (F1.6 & F1.7)
        dimension = str(state.get("dimension", "overworld")).lower()
        if "overworld" in dimension and not state.get("is_guarding") and not state.get("active_player_task"):
            phantom_risk = state.get("phantom_risk", False)
            should_sleep = state.get("should_sleep", False)
            if phantom_risk or should_sleep:
                has_bed = any("bed" in k for k in inv_map.keys()) or bool(state.get("visible_resources", {}).get("bed"))
                wool_cnt = sum(cnt for k, cnt in inv_map.items() if "wool" in k)
                plank_cnt = sum(cnt for k, cnt in inv_map.items() if "plank" in k)
                can_craft_bed = (wool_cnt >= 3 and plank_cnt >= 3)

                if has_bed or can_craft_bed:
                    if now - getattr(self, "last_sleep_try_time", 0.0) >= 30.0:
                        self.last_sleep_try_time = now
                        reason = "Insomnia phantom risk" if phantom_risk else "Nighttime safety"
                        logger.info(f"🛏️ [Life Cycle Routine] {reason}! Sleeping in bed to skip night and reset phantoms.")
                        return {
                            "text": f"{reason}! Sleeping in bed to skip night and reset phantoms.",
                            "tool_calls": [{"name": "sleep_in_bed", "arguments": {}}]
                        }

        # 5. Inventory storage management (F1.5)
        items_list = state.get("inventory_items", [])
        if len(items_list) >= 32 and not nearby_hostiles and not state.get("active_player_task"):
            if now - getattr(self, "last_chest_try_time", 0.0) >= 60.0:
                self.last_chest_try_time = now
                logger.info("📦 [Inventory Full] Inventory capacity reached (>32 slots)! Storing surplus materials in chest.")
                return {
                    "text": "Inventory is almost full! Storing surplus materials in chest storage.",
                    "tool_calls": [{"name": "manage_chest", "arguments": {"action_type": "deposit_surplus"}}]
                }

        return None

    async def decide_next_action(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Evaluates world state, partner directives, and tech tree to execute optimal tool calls."""
        if not state:
            return None

        if state.get("is_busy", False):
            logger.debug("⏳ Bot is currently busy executing an action. Skipping decision cycle.")
            return None

        items = state.get("inventory_items", [])
        inv_dict = self.parse_inventory(items)

        # EMERGENCY CHECK - Prioritize before LLM call
        emergency_action = self._should_use_emergency_action(state, inv_dict)
        if emergency_action:
            self.fallback_consecutive_count = 0
            return emergency_action

        owner_info = state.get("owner_info")
        health = state.get("health", 20)
        food = state.get("food", 20)
        hearts = round(health / 2, 1)
        pos = state.get("position", {"x": 0, "y": 0, "z": 0})
        inv_summary = state.get("inventory_summary", "Empty")

        entities_summary = (
            state.get("nearby_entities_summary") or
            ", ".join(state.get("nearby_hostiles", [])) or
            "No entities detected within 32m."
        )

        is_day = state.get("is_day", True)
        time_str = "Daytime (Safe)" if is_day else "Nighttime (Hostile mobs active!)"
        biome = state.get("biome", "Unknown")

        # Retrieve active tech tree milestone from current inventory
        inv_goal = get_current_progression_goal(inv_dict, state)
        inv_rank = get_stage_rank(inv_goal["stage"])
        cp_rank = get_stage_rank(self.checkpoint_stage) if self.checkpoint_stage else -1

        if self.checkpoint_stage and inv_rank < cp_rank:
            # Inventory lacks tools achieved in previous sessions (e.g. death or stored in chest)
            # 1. Check if nearby chest has our needed tools/materials
            if self.db:
                pos = state.get("position", {"x": 0, "y": 0, "z": 0})
                dim = state.get("dimension", "overworld")
                nearby_chests = self.db.get_nearby_chests(dim=dim, x=pos.get("x", 0), y=pos.get("y", 0), z=pos.get("z", 0), max_dist=48.0)
                for chest in nearby_chests:
                    c_items = chest.get("items", [])
                    needed_tools = ["diamond_pickaxe", "iron_pickaxe", "stone_pickaxe", "shield", "bucket"]
                    for it in c_items:
                        it_name = it.get("name", "")
                        if it_name in needed_tools or it_name == self.checkpoint_target:
                            logger.info(f"📦 [Checkpoint Recovery] Found {it_name} in nearby chest! Withdrawing to resume {self.checkpoint_stage}...")
                            return {
                                "text": f"Retrieving {it_name} from nearby chest to resume our {self.checkpoint_stage} progress!",
                                "tool_calls": [{"name": "manage_chest", "arguments": {"action_type": "withdraw", "item_name": it_name, "count": 1}}]
                            }

            # 2. Re-gear toward checkpoint without downgrading database record
            saved_m = get_milestone_by_stage(self.checkpoint_stage)
            goal = saved_m if saved_m else inv_goal
            substep_hint = f"Rebuilding gear toward {self.checkpoint_target} ({self.checkpoint_stage}): currently need {inv_goal['target']}"
        else:
            # Monotonic advancement or first startup
            goal = inv_goal
            if inv_rank > cp_rank or self.checkpoint_stage is None:
                self.checkpoint_stage = goal["stage"]
                self.checkpoint_target = goal["target"]
                if self.db and goal["target"] != self.last_goal_target:
                    self.last_goal_target = goal["target"]
                    logger.info(f"🏆 [Milestone Advanced] Era: {goal['stage']} -> Target: {goal['target']}")
                    self.db.save_progression(goal["stage"], goal["target"], inv_dict)
            else:
                self.last_goal_target = goal["target"]
            substep_hint, milestone_action = self.get_milestone_action(goal, inv_dict, state)

        missing_ingredients = resolve_missing_ingredients(goal["target"], inv_dict)
        missing_str = ", ".join(missing_ingredients) or "All materials ready for crafting!"

        if owner_info:
            dist = owner_info.get("distance", 0)
            owner_summary = f"{self.bot_owner} {dist}m away"
        else:
            owner_summary = f"{self.bot_owner} out of sight"

        active_task = state.get("active_player_task")
        if active_task:
            decision_prompt = (
                f"Directive from {self.bot_owner}: '{active_task.get('instruction')}'. "
                f"Target: {goal['target']}. Sub-Goal: {substep_hint}. Missing: {missing_str}. Decide 1 tool."
            )
        else:
            decision_prompt = (
                f"Milestone: {goal['target']} ({goal['stage']}). Sub-Goal: {substep_hint}. "
                f"Missing: {missing_str}. HP: {health}/20, Food: {food}/20. Decide 1 tool to progress."
            )

        try:
            logger.info(f"🎯 Milestone: {goal['target']} | Evaluating tactical action...")
            raw_response = await self.brain.process_chat(
                sender="System/Autonomous",
                message=decision_prompt,
                state=state
            )
            response = dict(raw_response or {})
            tool_calls = [dict(tc) for tc in response.get("tool_calls", [])]

            # If LLM returned no tool calls, trigger fallback heuristics
            if not tool_calls:
                logger.info("ℹ️ LLM produced 0 tool calls. Using fallback heuristic action.")
                fallback_action = self.generate_fallback_action(goal, inv_dict, owner_info, state)
                if fallback_action:
                    tool_calls = [fallback_action]
                    response["tool_calls"] = tool_calls
                    self.fallback_consecutive_count += 1
                else:
                    self.fallback_consecutive_count = 0
            else:
                self.fallback_consecutive_count = 0

                # Validate tool calls - prevent blind impossible craft loops
                sanitized_calls = []
                for tc in tool_calls:
                    c_name = tc.get("name")
                    c_args = tc.get("arguments", {})
                    if c_name == "collect_block":
                        b_name = str(c_args.get("block_name", "")).lower()
                        if "plank" in b_name:
                            logger.info(f"🔄 Remapping model action collect_block('{b_name}') -> 'log'.")
                            c_args["block_name"] = "log"
                    elif c_name in ("list_saved_locations", "stop_actions") and not state.get("active_player_task"):
                        logger.info(f"ℹ️ Model called idle action '{c_name}' in autonomous mode. Substituting milestone action: {milestone_action.get('name')}.")
                        sanitized_calls.append(milestone_action)
                        continue
                    elif c_name == "give_item_to_player":
                        target_p = str(c_args.get("player_name", "")).strip().lower()
                        if not state.get("active_player_task") or target_p in ("system", "autonomous", "server", "none", "bot", "aiassistant", ""):
                            logger.info(f"ℹ️ Model called give_item_to_player('{target_p}') in autonomous mode. Substituting milestone action: {milestone_action.get('name')}.")
                            sanitized_calls.append(milestone_action)
                            continue
                    elif c_name == "craft_item":
                        target_craft = str(c_args.get("item_name") or goal.get("target") or "").lower()
                        # Intercept smeltable materials mistakenly passed to craft_item
                        if target_craft in ("iron_ingot", "iron"):
                            if inv_dict.get("raw_iron", 0) > 0 or inv_dict.get("iron_ore", 0) > 0:
                                logger.info(f"🔄 Converting craft_item('{target_craft}') -> smelt_item('raw_iron').")
                                sanitized_calls.append({"name": "smelt_item", "arguments": {"input_item": "raw_iron", "count": c_args.get("count", 1)}})
                                continue
                            else:
                                logger.info(f"🔄 Converting craft_item('{target_craft}') -> collect_block('iron').")
                                sanitized_calls.append({"name": "collect_block", "arguments": {"block_name": "iron", "count": max(1, int(c_args.get("count", 3)))}})
                                continue
                        elif target_craft in ("gold_ingot", "gold"):
                            if inv_dict.get("raw_gold", 0) > 0 or inv_dict.get("gold_ore", 0) > 0:
                                sanitized_calls.append({"name": "smelt_item", "arguments": {"input_item": "raw_gold", "count": c_args.get("count", 1)}})
                                continue
                            else:
                                sanitized_calls.append({"name": "collect_block", "arguments": {"block_name": "gold_ore", "count": max(1, int(c_args.get("count", 3)))}})
                                continue
                        elif target_craft in ("copper_ingot", "copper"):
                            if inv_dict.get("raw_copper", 0) > 0 or inv_dict.get("copper_ore", 0) > 0:
                                sanitized_calls.append({"name": "smelt_item", "arguments": {"input_item": "raw_copper", "count": c_args.get("count", 1)}})
                                continue
                            else:
                                sanitized_calls.append({"name": "collect_block", "arguments": {"block_name": "copper_ore", "count": max(1, int(c_args.get("count", 3)))}})
                                continue
                        elif target_craft == "charcoal":
                            sanitized_calls.append({"name": "smelt_item", "arguments": {"input_item": "log", "count": max(1, int(c_args.get("count", 2)))}})
                            continue

                        if target_craft:
                            missing_for_item = resolve_missing_ingredients(target_craft, inv_dict)
                            if missing_for_item:
                                _, item_action = self.get_milestone_action({"target": target_craft}, inv_dict, state)
                                sub_action = item_action if item_action else milestone_action
                                logger.info(
                                    f"ℹ️ Model requested craft_item('{target_craft}') but missing materials "
                                    f"({', '.join(missing_for_item)}). Substituting prerequisite tactical action: {sub_action.get('name')}."
                                )
                                sanitized_calls.append(sub_action)
                                continue
                    sanitized_calls.append(tc)
                tool_calls = sanitized_calls
                response["tool_calls"] = tool_calls

            # If too many consecutive fallbacks occurred, gather baseline resources
            if self.fallback_consecutive_count >= 3:
                logger.info("ℹ️ Consecutive fallbacks: gathering baseline resources (wood).")
                return {
                    "text": "Gathering baseline resources to advance.",
                    "tool_calls": [
                        {"name": "collect_block", "arguments": {"block_name": "log", "count": 2}}
                    ]
                }

            # Anti-repetition loop breaker - only trigger if identical action repeats 3 times without inventory progress
            if tool_calls:
                first_tc = tool_calls[0]
                first_cmd = first_tc.get("name")
                args_str = json.dumps(first_tc.get("arguments", {}), sort_keys=True)
                action_sig = f"{first_cmd}:{args_str}"
                current_inv = str(state.get("inventory_summary", ""))

                # If inventory changed, progress was made - reset counter
                if hasattr(self, "_last_inv_summary") and current_inv != self._last_inv_summary:
                    self.consecutive_repeats = 0
                self._last_inv_summary = current_inv

                last_sig = getattr(self, "_last_action_sig", "")
                if action_sig == last_sig:
                    self.consecutive_repeats += 1
                    if self.consecutive_repeats >= 2:
                        logger.warning(
                            f"⚠️ [Loop Break] Action '{first_cmd}' repeated {self.consecutive_repeats + 1} times without progress. "
                            "Breaking loop by shifting strategy..."
                        )
                        self.consecutive_repeats = 0
                        if first_cmd == "collect_block":
                            target = str(first_tc.get("arguments", {}).get("block_name", ""))
                            alt_target = "stone" if "log" in target else "log"
                            return {
                                "text": f"Cannot collect {target} here. Switching focus to {alt_target}.",
                                "tool_calls": [
                                    {"name": "collect_block", "arguments": {"block_name": alt_target, "count": 2}}
                                ]
                            }
                        elif first_cmd == "hunt_food":
                            return {
                                "text": "Repeated hunting produced no meat. Harvesting crops.",
                                "tool_calls": [
                                    {"name": "farm_crops", "arguments": {"crop_type": "all"}}
                                ]
                            }
                        elif first_cmd == "craft_item":
                            return {
                                "text": "Prerequisites missing for craft. Gathering baseline resources.",
                                "tool_calls": [
                                    {"name": "collect_block", "arguments": {"block_name": "log", "count": 2}}
                                ]
                            }
                        else:
                            pos = state.get("position", {"x": 0, "y": 64, "z": 0})
                            angle = random.random() * 2 * math.pi
                            tx = pos.get("x", 0) + math.cos(angle) * 35
                            tz = pos.get("z", 0) + math.sin(angle) * 35
                            return {
                                "text": "Action stalled. Relocating to a better position.",
                                "tool_calls": [
                                    {"name": "go_to_coordinates", "arguments": {"x": round(tx), "y": pos.get("y", 64), "z": round(tz)}}
                                ]
                            }
                else:
                    self.consecutive_repeats = 0

                self._last_action_sig = action_sig
                self.last_action_command = first_cmd

            return response
        except asyncio.TimeoutError:
            logger.warning("⏱️ LLM reasoning timed out. Using backup strategy.")
            fallback_action = self.generate_fallback_action(goal, inv_dict, owner_info, state)
            return {
                "text": "Thinking timed out. Using backup strategy.",
                "tool_calls": [fallback_action] if fallback_action else []
            }
        except Exception as e:
            logger.error(f"❌ Autonomous decision error: {e}")
            return None

    def generate_fallback_action(
        self,
        goal: Dict[str, Any],
        inv: Dict[str, int],
        owner_info: Optional[Dict[str, Any]],
        state: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Generates proactive fallback action when LLM is unavailable or timed out."""
        if not state:
            state = {}

        # 1. Active teammate directive check
        active_task = state.get("active_player_task")
        if active_task:
            instruction = active_task.get("instruction", "").lower()
            if any(w in instruction for w in ["guard", "koru", "protect"]):
                return {"name": "guard_player", "arguments": {"player_name": self.bot_owner}}
            if any(w in instruction for w in ["follow", "gel", "takip", "come"]):
                return {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
            if any(w in instruction for w in ["hunt", "food", "yemek", "avlan"]):
                return {"name": "hunt_food", "arguments": {"animal_type": "any"}}
            if any(w in instruction for w in ["sleep", "bed", "uyu"]):
                return {"name": "sleep_in_bed", "arguments": {}}

        # 3. Hunger check - consume food if hungry
        food_level = state.get("food", 20)
        has_eatable = any(
            f in inv for f in [
                "cooked_beef", "cooked_porkchop", "bread", "apple",
                "cooked_chicken", "cooked_mutton", "baked_potato"
            ]
        )
        if food_level < 15 and has_eatable:
            return {"name": "eat_food", "arguments": {}}

        # 4. Smelt raw meats if food level dropping and fuel is available
        raw_meats = [
            m for m in [
                "raw_beef", "raw_porkchop", "raw_mutton", "raw_chicken",
                "beef", "porkchop", "mutton", "chicken"
            ]
            if inv.get(m, 0) > 0
        ]
        has_fuel = inv.get("coal", 0) > 0 or any("log" in i or "plank" in i for i in inv)
        if food_level < 18 and raw_meats and has_fuel:
            return {
                "name": "smelt_item",
                "arguments": {
                    "input_item": raw_meats[0],
                    "count": min(inv.get(raw_meats[0], 1), 4)
                }
            }

        # 5. Sustainable farming / hay bale harvesting
        from ai.farming import should_prioritize_farming, get_farming_action_plan
        if should_prioritize_farming(inv, state):
            return get_farming_action_plan(inv, state)

        # 6. Hunt food animals if hungry and out of food
        if food_level < 15 and not has_eatable and not raw_meats:
            return {"name": "hunt_food", "arguments": {"animal_type": "any"}}

        # 7. Night shelter check (Overworld only; beds explode in Nether and End!)
        dimension = str(state.get("dimension", "overworld")).lower()
        is_nether_or_end = "nether" in dimension or "end" in dimension
        if not state.get("is_day", True) and not is_nether_or_end:
            vis_res = state.get("visible_resources", {})
            if vis_res.get("bed"):
                return {"name": "sleep_in_bed", "arguments": {}}
            else:
                return {"name": "build_shelter", "arguments": {"mode": "auto"}}

        # 8. Tech tree progression milestones
        guidance, action = self.get_milestone_action(goal, inv, state)
        return action

    def get_milestone_action(
        self,
        goal: Dict[str, Any],
        inv: Dict[str, int],
        state: Optional[Dict[str, Any]] = None
    ) -> tuple[str, Dict[str, Any]]:
        """Determines the specific sub-step guidance and tactical action for the active milestone."""
        if not state:
            state = {}

        target = goal.get("target")
        dimension = str(state.get("dimension", "overworld")).lower()

        log_count = sum(c for i, c in inv.items() if "log" in i or "stem" in i)
        plank_count = sum(c for i, c in inv.items() if "planks" in i)

        if target == "wooden_pickaxe":
            if (log_count * 4) + plank_count < 4:
                return "Mine 3 logs (wood missing)", {"name": "collect_block", "arguments": {"block_name": "log", "count": 3}}
            return "Craft wooden pickaxe (wood ready)", {"name": "craft_item", "arguments": {"item_name": "wooden_pickaxe", "count": 1}}

        cobble_count = sum(
            c for i, c in inv.items()
            if any(s in i for s in ("cobble", "deepslate", "blackstone"))
        )
        if target == "stone_pickaxe":
            if cobble_count < 3:
                return "Mine 3 stone (cobblestone missing)", {"name": "collect_block", "arguments": {"block_name": "stone", "count": 3}}
            return "Craft stone pickaxe (materials ready)", {"name": "craft_item", "arguments": {"item_name": "stone_pickaxe", "count": 1}}

        if target == "furnace":
            if cobble_count < 8:
                return "Mine 8 stone (cobblestone missing)", {"name": "collect_block", "arguments": {"block_name": "stone", "count": 8}}
            return "Craft furnace (materials ready)", {"name": "craft_item", "arguments": {"item_name": "furnace", "count": 1}}

        raw_iron = inv.get("raw_iron", 0) + inv.get("iron_ore", 0)
        iron_ingots = inv.get("iron_ingot", 0)

        if iron_ingots >= 1 and "shield" not in inv:
            return "Craft shield for protection", {"name": "craft_item", "arguments": {"item_name": "shield", "count": 1}}

        if inv.get("coal", 0) >= 1 and "torch" not in inv:
            return "Craft torches for light", {"name": "craft_item", "arguments": {"item_name": "torch", "count": 4}}

        pos = state.get("position", {"x": 0, "y": 64, "z": 0})
        dim = state.get("dimension", "overworld")

        # Tactical Gear Buff: Enchanting check before dangerous dimensions
        from ai.enchanting import should_prioritize_enchanting
        xp_level = state.get("xp_level", 0)
        if should_prioritize_enchanting(inv, xp_level, dimension):
            return "Enchant gear at enchanting table", {"name": "enchant_gear", "arguments": {"gear_type": "auto", "target_level": 15}}

        # Tactical Gear Buff: Anvil repair check for damaged tools/armor (F2)
        low_durability = state.get("low_durability_gear", False)
        if low_durability:
            if "anvil" in inv or state.get("nearby_anvil", False):
                return "Repair damaged gear at anvil", {"name": "repair_gear_anvil", "arguments": {"target_item": "auto"}}
            elif inv.get("iron_ingot", 0) >= 3 and inv.get("stick", 0) >= 2 and target == "iron_pickaxe":
                return "Craft spare iron pickaxe before tool breaks", {"name": "craft_item", "arguments": {"item_name": "iron_pickaxe", "count": 1}}

        # Tactical Gear Buff: Village trading when villagers are nearby (F2)
        nearby_villagers = state.get("nearby_villagers_count", 0)
        if nearby_villagers > 0 and (inv.get("emerald", 0) > 0 or inv.get("wheat", 0) >= 20 or inv.get("raw_iron", 0) >= 15):
            return "Trade with nearby village villager for provisions and gear", {"name": "trade_with_villager", "arguments": {"trade_item": "auto", "count": 1}}

        # Tactical Gear Buff: Potion brewing before Nether or Dragon (F2)
        has_brewing_stand = "brewing_stand" in inv or state.get("nearby_brewing_stand", False)
        has_nether_wart = inv.get("nether_wart", 0) > 0
        has_bottles = any(b in inv for b in ("glass_bottle", "potion", "water_bottle"))
        if (has_brewing_stand or inv.get("blaze_rod", 0) >= 1) and has_nether_wart and has_bottles:
            if not state.get("fire_resistance_active", False) and inv.get("magma_cream", 0) > 0:
                return "Brew Fire Resistance potion using brewing stand", {"name": "brew_potion", "arguments": {"ingredient": "magma_cream"}}
            elif inv.get("glistering_melon_slice", 0) > 0:
                return "Brew Healing potion using brewing stand", {"name": "brew_potion", "arguments": {"ingredient": "glistering_melon_slice"}}

        if target == "iron_pickaxe":
            if raw_iron < 3 and iron_ingots < 3:
                # F2.4: Query SQLite ore_map for recorded unmined iron veins!
                if self.db:
                    unmined = self.db.get_unmined_ores(dim=dim, block_type="iron", x=pos.get("x", 0), y=pos.get("y", 0), z=pos.get("z", 0), max_dist=256.0)
                    if unmined:
                        closest = unmined[0]
                        logger.info(f"💎 [Ore Map Navigator] Directing bot to known unmined {closest['block']} at ({closest['x']}, {closest['y']}, {closest['z']})!")
                        return f"Navigate to known {closest['block']} deposit from ore map", {
                            "name": "collect_block",
                            "arguments": {
                                "block_name": closest["block"],
                                "count": 3,
                                "target_x": closest["x"],
                                "target_y": closest["y"],
                                "target_z": closest["z"]
                            }
                        }
                return "Mine 3 iron ore (iron missing)", {"name": "collect_block", "arguments": {"block_name": "iron", "count": 3, "optimal_y": 16}}
            if raw_iron >= 3 and iron_ingots < 3:
                return "Smelt 3 raw iron into ingots", {
                    "name": "smelt_item",
                    "arguments": {"input_item": "raw_iron", "count": 3}
                }
            return "Craft iron pickaxe (materials ready)", {"name": "craft_item", "arguments": {"item_name": "iron_pickaxe", "count": 1}}

        diamonds = inv.get("diamond", 0)
        if target == "diamond_pickaxe":
            if diamonds < 3:
                # F2.4: Query SQLite ore_map for recorded unmined diamond veins!
                if self.db:
                    unmined = self.db.get_unmined_ores(dim=dim, block_type="diamond", x=pos.get("x", 0), y=pos.get("y", 0), z=pos.get("z", 0), max_dist=256.0)
                    if unmined:
                        closest = unmined[0]
                        logger.info(f"💎 [Ore Map Navigator] Directing bot to known unmined {closest['block']} at ({closest['x']}, {closest['y']}, {closest['z']})!")
                        return f"Navigate to known {closest['block']} deposit from ore map", {
                            "name": "collect_block",
                            "arguments": {
                                "block_name": closest["block"],
                                "count": 3,
                                "target_x": closest["x"],
                                "target_y": closest["y"],
                                "target_z": closest["z"]
                            }
                        }
                return "Mine 3 diamonds (diamonds missing)", {"name": "collect_block", "arguments": {"block_name": "diamond", "count": 3, "optimal_y": -58}}
            return "Craft diamond pickaxe (materials ready)", {"name": "craft_item", "arguments": {"item_name": "diamond_pickaxe", "count": 1}}

        # Phase 3 & 4: Nether Portal & Nether Progression (F4)
        if target == "nether_portal" or "nether" in dimension:
            if "nether" in dimension:
                # 1. Respawn anchor setup if materials ready
                if ("respawn_anchor" in inv or (inv.get("crying_obsidian", 0) >= 6 and inv.get("glowstone", 0) >= 3)) and not state.get("respawn_anchor_set", False):
                    return "Setup and charge Respawn Anchor for Nether spawn point", {"name": "setup_respawn_anchor", "arguments": {}}

                # 2. Nether Fortress Fortification
                cobble_count = inv.get("cobblestone", 0) + inv.get("cobbled_deepslate", 0) + inv.get("blackstone", 0)
                if cobble_count >= 12 and not state.get("nether_outpost_built", False):
                    return "Build Nether outpost for safety", {"name": "build_nether_outpost", "arguments": {"wall_material": "auto"}}

                # 3. Hoglin food hunt if food is low
                if state.get("food", 20) <= 10 and state.get("nearby_passives", []):
                    return "Hunt Hoglin in Crimson forest for porkchop food", {"name": "hunt_hoglin", "arguments": {}}

                # 4. Piglin bartering for Ender Pearls if gold available and pearls missing
                if inv.get("gold_ingot", 0) >= 1 and inv.get("ender_pearl", 0) < 12 and state.get("nearby_piglins_count", 0) > 0:
                    return "Barter gold ingots with Piglin for Ender Pearls and potions", {"name": "barter_with_piglins", "arguments": {"count": min(inv.get("gold_ingot", 0), 4)}}

                return "Hunt Blazes in fortress", {"name": "attack_target", "arguments": {"target_name": "blaze"}}

            obsidian_count = inv.get("obsidian", 0)
            if obsidian_count < 10:
                return f"Mine {10 - obsidian_count} obsidian for portal", {"name": "collect_block", "arguments": {"block_name": "obsidian", "count": 10 - obsidian_count}}

            has_flint_and_steel = "flint_and_steel" in inv
            if not has_flint_and_steel:
                flint_count = inv.get("flint", 0)
                iron_count = inv.get("iron_ingot", 0)
                if iron_count < 1:
                    raw_iron_count = inv.get("raw_iron", 0) + inv.get("iron_ore", 0)
                    if raw_iron_count >= 1:
                        return "Smelt raw iron for flint and steel", {"name": "smelt_item", "arguments": {"input_item": "raw_iron", "count": 1}}
                    return "Mine 1 iron for flint and steel", {"name": "collect_block", "arguments": {"block_name": "iron", "count": 1}}
                if flint_count < 1:
                    return "Mine gravel for flint", {"name": "collect_block", "arguments": {"block_name": "gravel", "count": 3}}
                return "Craft flint and steel", {"name": "craft_item", "arguments": {"item_name": "flint_and_steel", "count": 1}}

            return "Construct and ignite Nether portal", {"name": "build_nether_portal", "arguments": {}}

        # Phase 3: Eye of Ender & Stronghold Tracking
        if target == "eye_of_ender":
            blaze_rods = inv.get("blaze_rod", 0)
            blaze_powders = inv.get("blaze_powder", 0)
            ender_pearls = inv.get("ender_pearl", 0)
            eyes = inv.get("eye_of_ender", 0)

            if eyes >= 12:
                return "Throw Eye of Ender towards Stronghold", {"name": "throw_eye_of_ender", "arguments": {}}

            if blaze_rods >= 1 and blaze_powders < 2:
                return "Craft blaze powder", {"name": "craft_item", "arguments": {"item_name": "blaze_powder", "count": 2}}

            if blaze_powders >= 1 and ender_pearls >= 1:
                return "Craft Eye of Ender", {"name": "craft_item", "arguments": {"item_name": "eye_of_ender", "count": 1}}

            if ender_pearls < 1:
                if "nether" in dimension and inv.get("gold_ingot", 0) >= 1 and state.get("nearby_piglins_count", 0) > 0:
                    return "Barter gold ingots with Piglin for Ender Pearls", {"name": "barter_with_piglins", "arguments": {"count": min(inv.get("gold_ingot", 0), 4)}}
                return "Hunt Enderman for Ender Pearls", {"name": "attack_target", "arguments": {"target_name": "enderman"}}

            if blaze_rods < 1 and blaze_powders < 1:
                if "nether" in dimension:
                    return "Hunt Blazes for rods", {"name": "attack_target", "arguments": {"target_name": "blaze"}}
                return "Build Nether portal for rods", {"name": "build_nether_portal", "arguments": {}}

        # Phase 3 & 4: The End & Ender Dragon Slaying (F5)
        if target in ("ender_dragon", "fight_ender_dragon", "end_crystal", "enter_exit_portal"):
            if "end" in dimension:
                dragon_defeated = state.get("dragon_defeated", False)
                if dragon_defeated or target == "enter_exit_portal":
                    # F5: Outer End Islands exploration for Elytra & Shulker Boxes
                    if inv.get("ender_pearl", 0) >= 1 and not state.get("elytra_acquired", False):
                        return "Explore End Gateway towards End City for Elytra and Shulker Shells", {"name": "explore_end_city", "arguments": {}}
                    return "Enter exit portal to beat game", {"name": "enter_exit_portal", "arguments": {}}

                crystals_count = state.get("end_crystals_count", 0)
                if crystals_count > 0 or target == "end_crystal":
                    return "Destroy End Crystals atop pillars", {"name": "destroy_end_crystals", "arguments": {}}

                return "Fight Ender Dragon with sword", {"name": "fight_ender_dragon", "arguments": {"tactic": "melee_sword"}}

            vis_res = state.get("visible_resources", {})
            if vis_res.get("end_portal_frame") or inv.get("eye_of_ender", 0) > 0:
                return "Activate End Portal", {"name": "activate_end_portal", "arguments": {}}
            return "Throw Eye of Ender towards Stronghold", {"name": "throw_eye_of_ender", "arguments": {}}

        # Default: Stay near partner
        return "Follow partner", {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
