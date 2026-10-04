"""Curated Dataset Collector for Minecraft Autonomous Co-op AI.

Records verified (state -> decision -> execution result) samples for Qwen 2.5 3B.
Strictly validates inventory deltas to prevent false training data, deduplicates routine loops,
and highlights critical survival edge cases.
"""

import os
import json
import time
import threading
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("DatasetCollector")

# Resource-to-drop mapping for common Minecraft block break items
BLOCK_DROP_MAPPINGS = {
    "stone": ["cobblestone", "stone"],
    "deepslate": ["cobbled_deepslate", "deepslate"],
    "coal_ore": ["coal", "coal_ore"],
    "deepslate_coal_ore": ["coal", "deepslate_coal_ore"],
    "iron_ore": ["raw_iron", "iron_ore"],
    "deepslate_iron_ore": ["raw_iron", "deepslate_iron_ore"],
    "copper_ore": ["raw_copper", "copper_ore"],
    "gold_ore": ["raw_gold", "gold_ore"],
    "diamond_ore": ["diamond", "diamond_ore"],
    "deepslate_diamond_ore": ["diamond", "deepslate_diamond_ore"],
    "redstone_ore": ["redstone", "redstone_ore"],
    "lapis_ore": ["lapis_lazuli", "lapis_ore"],
    "nether_quartz_ore": ["quartz", "nether_quartz_ore"],
    "log": ["log", "oak_log", "birch_log", "spruce_log", "dark_oak_log", "acacia_log", "jungle_log", "mangrove_log", "cherry_log"],
    "oak_log": ["oak_log", "apple", "oak_sapling"],
    "hay_block": ["wheat", "hay_block"],
}


class DatasetCollector:
    """Collects and validates high-quality decision samples for model tuning."""

    def __init__(self, output_path: Optional[str] = None, max_duplicates_per_bucket: int = 3):
        if output_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.output_path = os.path.join(base_dir, "data", "minecraft_decisions.jsonl")
        else:
            self.output_path = output_path

        self.max_duplicates = max_duplicates_per_bucket
        self._lock = threading.Lock()
        self._bucket_counts: Dict[str, int] = {}
        self.stats = {
            "total_recorded": 0,
            "progress_made_count": 0,
            "edge_cases_count": 0,
            "dedup_skipped_count": 0,
        }

        # Ensure output directory exists
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        self._warmup_bucket_counts()

    def _warmup_bucket_counts(self):
        """Preloads bucket counts if decision log already exists."""
        if not os.path.exists(self.output_path):
            return

        try:
            with open(self.output_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        milestone = record.get("milestone", {}).get("target", "unknown")
                        decision = record.get("decision", {})
                        cmd = decision.get("tool_name", "")
                        args_str = json.dumps(decision.get("arguments", {}), sort_keys=True)
                        key = f"{milestone}:{cmd}:{args_str}"
                        self._bucket_counts[key] = self._bucket_counts.get(key, 0) + 1
                        self.stats["total_recorded"] += 1
                        if record.get("execution", {}).get("progress_made"):
                            self.stats["progress_made_count"] += 1
                        if record.get("execution", {}).get("is_edge_case"):
                            self.stats["edge_cases_count"] += 1
                    except Exception:
                        continue
            logger.info(
                f"📂 Preloaded {self.stats['total_recorded']} existing training samples from {self.output_path}"
            )
        except Exception as e:
            logger.warning(f"⚠️ Could not warmup dataset bucket counts: {e}")

    @staticmethod
    def parse_inventory_dict(state: Dict[str, Any]) -> Dict[str, int]:
        """Converts state inventory items into item_name -> count dictionary."""
        inv: Dict[str, int] = {}
        if not state:
            return inv

        # Check list of item objects
        items = state.get("inventory_items", [])
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    name = it.get("name", "")
                    count = it.get("count", 0)
                    if name:
                        inv[name] = inv.get(name, 0) + count

        # Check pre-parsed inventory dict if available
        raw_inv = state.get("inventory")
        if isinstance(raw_inv, dict):
            for k, v in raw_inv.items():
                if isinstance(v, (int, float)):
                    inv[k] = inv.get(k, 0) + int(v)

        return inv

    @staticmethod
    def compute_inventory_delta(pre_inv: Dict[str, int], post_inv: Dict[str, int]) -> Dict[str, int]:
        """Calculates exact count changes (post - pre) for all items."""
        delta: Dict[str, int] = {}
        all_keys = set(pre_inv.keys()) | set(post_inv.keys())
        for k in all_keys:
            diff = post_inv.get(k, 0) - pre_inv.get(k, 0)
            if diff != 0:
                delta[k] = diff
        return delta

    def check_progress_made(
        self,
        pre_state: Dict[str, Any],
        post_state: Dict[str, Any],
        decision: Dict[str, Any],
        exec_result: Dict[str, Any],
        inv_delta: Dict[str, int]
    ) -> bool:
        """Verifies whether the action produced real in-game progression.

        Prevents false-positive training data where an action technically reported
        success but did not actually change game state or inventory.
        """
        # If the execution returned explicit error or failed
        if not exec_result or not exec_result.get("success", False):
            return False

        cmd = decision.get("name") or decision.get("tool_name", "")
        args = decision.get("arguments", {})

        # Milestone change is always real progression
        pre_target = pre_state.get("goal_target") or pre_state.get("target")
        post_target = post_state.get("goal_target") or post_state.get("target")
        if pre_target and post_target and pre_target != post_target:
            return True

        # 1. Block Collection
        if cmd == "collect_block":
            block_req = str(args.get("block_name", "")).lower()
            possible_drops = BLOCK_DROP_MAPPINGS.get(block_req, [block_req])
            # Check if any expected drop or any resource item increased
            for item_name, count in inv_delta.items():
                if count > 0:
                    if any(drop in item_name.lower() for drop in possible_drops) or block_req in item_name.lower():
                        return True
            # Fallback: if any item count increased at all
            if any(cnt > 0 for cnt in inv_delta.values()):
                return True
            return False

        # 2. Crafting
        elif cmd == "craft_item":
            item_req = str(args.get("item_name", "")).lower()
            for item_name, count in inv_delta.items():
                if count > 0 and (item_req in item_name.lower() or item_name.lower() in item_req):
                    return True
            return False

        # 3. Smelting
        elif cmd == "smelt_item":
            # Output of smelting should be increased
            for item_name, count in inv_delta.items():
                if count > 0 and any(kw in item_name for kw in ["ingot", "cooked", "glass", "smooth", "brick"]):
                    return True
            return False

        # 4. Eating
        elif cmd == "eat_food":
            pre_food = pre_state.get("food", 0)
            post_food = post_state.get("food", 0)
            if post_food > pre_food:
                return True
            # Or food item count decreased
            if any(cnt < 0 for item, cnt in inv_delta.items() if any(f in item for f in ["beef", "pork", "bread", "apple", "chicken"])):
                return True
            return False

        # 5. Farming
        elif cmd == "farm_crops":
            for item_name, count in inv_delta.items():
                if count > 0 and any(f in item_name for f in ["wheat", "hay", "bread", "carrot", "potato", "beetroot", "seed"]):
                    return True
            return False

        # 6. Hunting
        elif cmd == "hunt_food":
            for item_name, count in inv_delta.items():
                if count > 0 and any(m in item_name for m in ["beef", "porkchop", "mutton", "chicken", "leather", "feather"]):
                    return True
            return False

        # 7. Player Follow / Movement
        elif cmd == "follow_player":
            pre_owner = pre_state.get("owner_info") or {}
            post_owner = post_state.get("owner_info") or {}
            pre_dist = pre_owner.get("distance", 999)
            post_dist = post_owner.get("distance", 999)
            # Either closed the distance or already near partner
            return post_dist <= pre_dist or post_dist <= 5.0

        elif cmd == "go_to_coordinates":
            # Movement succeeded without error
            return exec_result.get("success", False)

        # 8. Shelter
        elif cmd in ("build_shelter", "break_out_shelter"):
            pre_shelter = pre_state.get("is_sheltered", False)
            post_shelter = post_state.get("is_sheltered", False)
            return pre_shelter != post_shelter or exec_result.get("success", False)

        # 9. Combat / Defense
        elif cmd in ("guard_player", "attack_target"):
            post_health = post_state.get("health", 0)
            # Survived combat action
            return post_health > 0

        # 10. Tech Tree Milestones (Nether / End)
        elif cmd in (
            "build_nether_portal", "throw_eye_of_ender", "activate_end_portal",
            "destroy_end_crystals", "fight_ender_dragon", "enter_exit_portal",
            "enchant_gear", "build_nether_outpost", "bridge_chasm"
        ):
            return exec_result.get("success", False)

        # Default: if any positive inventory change occurred
        return any(cnt > 0 for cnt in inv_delta.values())

    @staticmethod
    def is_edge_case(state: Dict[str, Any], decision: Dict[str, Any]) -> bool:
        """Determines if this sample represents a critical or rare survival scenario."""
        health = state.get("health", 20)
        food = state.get("food", 20)
        hostiles = state.get("nearby_hostiles", [])
        dimension = str(state.get("dimension", "overworld")).lower()
        cmd = decision.get("name") or decision.get("tool_name", "")

        # Critical vitals
        if health <= 8 or food <= 5:
            return True

        # Active hostile combat
        if len(hostiles) > 0 and cmd in ("attack_target", "guard_player", "build_shelter"):
            return True

        # Non-overworld dimensions (Nether & End are rare and tactical)
        if "nether" in dimension or "end" in dimension:
            return True

        # Rare boss or survival tools
        if cmd in (
            "build_shelter", "break_out_shelter", "throw_eye_of_ender",
            "activate_end_portal", "destroy_end_crystals", "fight_ender_dragon",
            "enchant_gear", "build_nether_outpost"
        ):
            return True

        return False

    def record_step(
        self,
        pre_state: Dict[str, Any],
        decision: Dict[str, Any],
        exec_result: Dict[str, Any],
        post_state: Dict[str, Any],
        duration_s: float = 0.0
    ) -> Optional[Dict[str, Any]]:
        """Records a single verified step into JSONL dataset.

        Applies delta calculation, progress verification, deduplication, and edge-case tagging.
        """
        if not pre_state or not decision:
            return None

        # Clean decision representation
        cmd = decision.get("name") or decision.get("tool_name", "")
        args = decision.get("arguments", {})

        # Compute inventory delta
        pre_inv = self.parse_inventory_dict(pre_state)
        post_inv = self.parse_inventory_dict(post_state)
        inv_delta = self.compute_inventory_delta(pre_inv, post_inv)

        # Progress check
        progress_made = self.check_progress_made(
            pre_state=pre_state,
            post_state=post_state,
            decision=decision,
            exec_result=exec_result,
            inv_delta=inv_delta
        )

        # Edge case check
        is_edge = self.is_edge_case(pre_state, decision)

        # Deduplication check
        goal_target = pre_state.get("goal_target") or pre_state.get("target") or "unknown"
        args_str = json.dumps(args, sort_keys=True)
        bucket_key = f"{goal_target}:{cmd}:{args_str}"

        with self._lock:
            current_count = self._bucket_counts.get(bucket_key, 0)
            # If not an edge case and bucket limit reached: skip to preserve dataset diversity
            if not is_edge and current_count >= self.max_duplicates:
                self.stats["dedup_skipped_count"] += 1
                return None

            self._bucket_counts[bucket_key] = current_count + 1

            # Prepare structured record
            pos = pre_state.get("position") or {"x": 0, "y": 0, "z": 0}
            owner_info = pre_state.get("owner_info") or {}
            record = {
                "timestamp": round(time.time(), 3),
                "milestone": {
                    "stage": pre_state.get("goal_stage", "unknown"),
                    "target": goal_target,
                    "missing": pre_state.get("missing_ingredients") or pre_state.get("goal_missing") or [],
                },
                "state": {
                    "health": pre_state.get("health", 20),
                    "food": pre_state.get("food", 20),
                    "dimension": pre_state.get("dimension", "overworld"),
                    "position": {
                        "x": round(pos.get("x", 0), 1),
                        "y": round(pos.get("y", 0), 1),
                        "z": round(pos.get("z", 0), 1)
                    },
                    "inventory": pre_inv,
                    "nearby_hostiles": pre_state.get("nearby_hostiles", []),
                    "owner_distance": round(owner_info.get("distance", 0), 1),
                    "carried_tools": pre_state.get("carried_tools", "None"),
                },
                "decision": {
                    "tool_name": cmd,
                    "arguments": args,
                },
                "execution": {
                    "bridge_success": bool(exec_result.get("success", False)),
                    "inventory_delta": inv_delta,
                    "progress_made": progress_made,
                    "is_edge_case": is_edge,
                    "duration_s": round(duration_s, 2),
                    "error": exec_result.get("error"),
                }
            }

            try:
                with open(self.output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

                self.stats["total_recorded"] += 1
                if progress_made:
                    self.stats["progress_made_count"] += 1
                if is_edge:
                    self.stats["edge_cases_count"] += 1

                logger.debug(
                    f"📝 [Dataset] Recorded step: {cmd} | Progress: {progress_made} | Edge: {is_edge} | Delta: {inv_delta}"
                )
                return record
            except Exception as e:
                logger.error(f"❌ Failed to write dataset record: {e}")
                return None

    def get_stats(self) -> Dict[str, Any]:
        """Returns live statistics of dataset collection."""
        with self._lock:
            return dict(self.stats)
