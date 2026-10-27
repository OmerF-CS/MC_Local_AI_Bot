"""Autonomous human-like Minecraft co-op partner brain - Production hardened."""
import asyncio
import json
import math
import random
import time
from typing import Dict, Any, List, Optional, Tuple
from utils.logger import get_logger
from ai.progression_tree import (
    get_current_progression_goal,
    resolve_missing_ingredients,
    get_stage_rank,
    get_milestone_by_stage,
    get_optimal_ore_height
)
from ai.security_and_affordance import normalize_item_alias, strip_cjk, AffordanceEngine
from ai.spatial_and_exploration import ExplorationEngine
from ai.opportunistic_radar import OpportunityScanner, Opportunity
from ai.player_styles import PlayerStyle, StyleStrategy
from ai.cortex import CognitiveCortex

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
        self.fallback_consecutive_count = 0
        self.fallback_count = 0
        self.last_llm_failure_time = 0
        self.last_goal_target = None
        self.last_hunt_emergency_time = 0.0
        self.last_eat_emergency_time = 0.0

        # F1-2: Low HP recovery monitor
        self._low_hp_monitor = None

        # F1-6: Consecutive fallback category diversification tracking
        self._last_fallback_key = None
        self._consecutive_same_fallback_count = 0
        self._last_fallback_category_shift = "wait"

        # F1-R11: Action failure history and consecutive repetition category shift tracking
        self.action_failure_history: List[Dict[str, Any]] = []
        self._last_action_failure_key = None
        self._consecutive_action_failure_count = 0
        self._pending_category_shift = False
        self._pending_category_shift_action = None
        self._pending_category_shift_reason = None
        self._pending_category_shift_cat = None
        self._processed_action_ids = set()

        self.checkpoint_stage = None
        self.checkpoint_target = None

        # Affordance, Exploration, History and Cooldown Engines (Phase 2)
        self.affordance_engine = AffordanceEngine()
        self.exploration_engine = ExplorationEngine()
        self.recent_action_history: List[Dict[str, Any]] = []
        self._action_cooldowns: Dict[str, float] = {}

        # Opportunistic Radar & Player Persona Style (Phase 2)
        self.opportunity_scanner = OpportunityScanner()
        self.style_strategy = StyleStrategy()
        self.player_style = PlayerStyle.SPEEDRUNNER

        # Cognitive Cortex (The Mind - Phase 2 Cortex-First)
        cortex_model = getattr(self.brain, "model", "mc-qwen:3b") if self.brain else "mc-qwen:3b"
        self.cortex = CognitiveCortex(
            ollama_brain=self.brain,
            bot_owner=self.bot_owner,
            db=self.db,
            model=cortex_model
        )
        self.last_thought_chat_time = 0.0
        self.last_scout_time = 0.0

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

    def set_player_style(self, style: Any) -> None:
        """Updates the current player persona/style archetype."""
        if isinstance(style, PlayerStyle):
            self.player_style = style
        elif isinstance(style, str):
            self.player_style = PlayerStyle.from_str(style)
        logger.info(f"🎭 [Player Style Set] Changed persona style to: {self.player_style.value}")

    def parse_inventory(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """Converts inventory item list into a name -> count mapping."""
        inv = {}
        for item in items:
            name = item.get("name", "")
            count = item.get("count", 0)
            inv[name] = inv.get(name, 0) + count
        return inv

    def is_action_on_cooldown(self, action: str, target_str: str) -> bool:
        """Checks if a specific action on target is currently on cooldown."""
        key = f"{action}:{target_str}"
        expiry = self._action_cooldowns.get(key, 0.0)
        return time.time() < expiry

    def set_action_cooldown(self, action: str, target_str: str, duration: Optional[float] = None) -> None:
        """Sets action cooldown timestamp (15s default, 45s for go_to_coordinates)."""
        if duration is None:
            duration = 45.0 if action == "go_to_coordinates" else 15.0
        key = f"{action}:{target_str}"
        self._action_cooldowns[key] = time.time() + duration

    def format_recent_actions_context(self) -> str:
        """Formats the last recorded actions (up to 4) into a compact context string."""
        if not self.recent_action_history:
            return ""
        entries = []
        for entry in self.recent_action_history[-4:]:
            action = entry.get("action", "")
            target = entry.get("target_str") or entry.get("target") or ""
            outcome = "OK" if entry.get("status") == "success" else "FAIL"
            entries.append(f"{action}({target})->{outcome}")
        return f"[Recent: {', '.join(entries)}]"

    # ------------------------------------------------------------------
    # F1-R11: Action Failure Reason Mapping & Repetition Tracking
    # ------------------------------------------------------------------
    @property
    def consecutive_failure_repeats(self) -> int:
        """Returns consecutive failure repetitions for the current failure key."""
        return self._consecutive_action_failure_count

    @property
    def failure_history(self) -> List[Dict[str, Any]]:
        """Returns history of recorded action failures."""
        return self.action_failure_history

    @staticmethod
    def normalize_failure_reason(action: str, raw_reason_or_error: Optional[str]) -> str:
        """Normalizes raw worker action error/reason strings to canonical failure reasons (F1-R11)."""
        if not raw_reason_or_error:
            return "unknown_failure"
        err = str(raw_reason_or_error).strip().lower()
        if "no_crop_found" in err:
            return "no_crop_found"
        if "position_unknown" in err:
            return "position_unknown"
        if "did_not_reach_destination" in err:
            return "did_not_reach_destination"
        return str(raw_reason_or_error).strip()

    @staticmethod
    def _normalize_target(target: Any, action: str = "", args: Optional[Dict[str, Any]] = None) -> Tuple[Any, str]:
        """Normalizes action target and produces a stable comparison string (F1-R11)."""
        if target is None and args:
            if action == "farm_crops":
                target = args.get("crop_type") or args.get("crop") or args.get("target")
            elif action == "go_to_coordinates":
                if "x" in args and "z" in args:
                    target = (args.get("x"), args.get("y", 64), args.get("z"))
                elif "target" in args:
                    target = args.get("target")
            elif "target" in args:
                target = args.get("target")

        def _fmt(v: Any) -> str:
            try:
                f = float(v)
                return str(int(f)) if f.is_integer() else f"{f:.1f}"
            except (ValueError, TypeError):
                return str(v)

        if isinstance(target, dict):
            if "x" in target and "z" in target:
                target_str = f"({_fmt(target.get('x'))}, {_fmt(target.get('y', 64))}, {_fmt(target.get('z'))})"
            else:
                target_str = json.dumps(target, sort_keys=True)
        elif isinstance(target, (list, tuple)):
            target_str = f"({', '.join(_fmt(v) for v in target)})"
        elif target is not None:
            target_str = str(target).strip()
        else:
            if action == "farm_crops":
                target = "all"
                target_str = "all"
            elif action == "go_to_coordinates":
                target = "coords"
                target_str = "coords"
            else:
                target = "default"
                target_str = "default"

        return target, target_str

    @staticmethod
    def generate_category_shift_action(
        shift_cat: str,
        state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Generates category shift action purely without side effects or logging (F1-R11)."""
        if shift_cat == "exploration":
            pos = (state or {}).get("position", {"x": 0, "y": 64, "z": 0})
            engine = ExplorationEngine()
            frontier = engine.get_frontier_target(pos)
            return {
                "name": "go_to_coordinates",
                "arguments": {
                    "x": frontier["x"],
                    "z": frontier["z"],
                    "ignore_y": True,
                    "range": frontier.get("range", 3)
                }
            }
        else:
            return {
                "name": "say_chat",
                "arguments": {"message": "Observing surroundings and waiting for opportunities."}
            }

    def trigger_category_shift(
        self,
        state: Optional[Dict[str, Any]] = None,
        reason_label: str = "Repeated action failure",
        action: Optional[Dict[str, Any]] = None,
        shift_cat: Optional[str] = None
    ) -> Dict[str, Any]:
        """Triggers category shift with logging and counter reset (F1-6, F1-R11)."""
        if not shift_cat:
            shift_cat = getattr(self, "_pending_category_shift_cat", None) or (
                "exploration" if getattr(self, "_last_fallback_category_shift", "wait") == "wait" else "waiting"
            )
        if not action:
            action = getattr(self, "_pending_category_shift_action", None) or self.generate_category_shift_action(shift_cat, state)

        logger.warning(
            f"⚠️ [Fallback Category Shift] {reason_label}. "
            f"Shifting planner to category '{shift_cat}'..."
        )
        self._last_fallback_category_shift = shift_cat
        self._pending_category_shift = False
        self._pending_category_shift_action = None
        self._pending_category_shift_reason = None
        self._pending_category_shift_cat = None
        self._consecutive_same_fallback_count = 0
        self._consecutive_action_failure_count = 0
        return action

    def record_action_failure(
        self,
        action: str,
        reason: str,
        target: Any = None,
        args: Optional[Dict[str, Any]] = None,
        raw_error: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
        action_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Records action failure reason into failure history and repetition tracking (F1-R11).

        Single source of truth with action_id deduplication.
        If the same reason + same target repeats 3 consecutive times, prepares category shift
        (exploration or waiting) without side effects or logging until applied in decide_next_action.
        """
        if action_id:
            if not hasattr(self, "_processed_action_ids"):
                self._processed_action_ids = set()
            if action_id in self._processed_action_ids:
                logger.debug(f"ℹ️ Skipping duplicate action failure for action_id={action_id}")
                return self._pending_category_shift_action
            self._processed_action_ids.add(action_id)

        norm_reason = self.normalize_failure_reason(action, reason or raw_error)
        norm_target, target_str = self._normalize_target(target, action, args)

        now = time.time()
        failure_entry = {
            "action": action,
            "reason": norm_reason,
            "raw_error": raw_error or reason,
            "target": norm_target,
            "target_str": target_str,
            "timestamp": now,
            "time": now,
            "action_id": action_id
        }
        self.action_failure_history.append(failure_entry)
        self.recent_action_history.append({
            "action": action,
            "target": norm_target,
            "target_str": target_str,
            "reason": norm_reason,
            "status": "failure",
            "timestamp": now
        })
        if len(self.recent_action_history) > 5:
            self.recent_action_history.pop(0)

        # Mark unreachable in exploration engine
        reason_lower = norm_reason.lower()
        if any(k in reason_lower for k in ("not_found", "no_block", "no_crop_found", "cannot_reach", "unreachable")) or self._consecutive_action_failure_count >= 2:
            self.exploration_engine.mark_unreachable(target_str, duration=90.0)

        failure_key = f"{action}:{norm_reason}:{target_str}"
        if failure_key == getattr(self, "_last_action_failure_key", None):
            self._consecutive_action_failure_count += 1
            self._consecutive_same_fallback_count += 1
        else:
            self._last_action_failure_key = failure_key
            self._consecutive_action_failure_count = 1
            self._consecutive_same_fallback_count = 1

        logger.warning(
            f"⚠️ [Planner Failure Tracking] Action '{action}' failed with reason '{norm_reason}' "
            f"(target={target_str}, consecutive_repeats={self._consecutive_same_fallback_count})"
        )

        shift_action = None
        if self._consecutive_same_fallback_count >= 3 or self._consecutive_action_failure_count >= 3:
            next_cat = "exploration" if getattr(self, "_last_fallback_category_shift", "wait") == "wait" else "waiting"
            shift_action = self.generate_category_shift_action(next_cat, state or {})
            self._pending_category_shift = True
            self._pending_category_shift_action = shift_action
            self._pending_category_shift_reason = f"Action failure '{failure_key}' repeated 3 consecutive times"
            self._pending_category_shift_cat = next_cat

        return shift_action

    def record_action_success(self, action: str, target: Any = None, action_id: Optional[str] = None) -> None:
        """Resets consecutive failure tracking upon successful action execution (F1-R11)."""
        if action_id:
            if not hasattr(self, "_processed_action_ids"):
                self._processed_action_ids = set()
            if action_id in self._processed_action_ids:
                return
            self._processed_action_ids.add(action_id)

        norm_target, target_str = self._normalize_target(target, action, None)
        self.recent_action_history.append({
            "action": action,
            "target": norm_target,
            "target_str": target_str,
            "status": "success",
            "timestamp": time.time()
        })
        if len(self.recent_action_history) > 5:
            self.recent_action_history.pop(0)

        self._consecutive_action_failure_count = 0
        self._consecutive_same_fallback_count = 0
        self._last_action_failure_key = None
        self._pending_category_shift = False
        self._pending_category_shift_action = None
        self._pending_category_shift_reason = None
        self._pending_category_shift_cat = None

    def _should_use_emergency_action(self, state: Dict[str, Any], inv: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
        """Immediate reflex for critical health, imminent starvation, or night danger."""
        health = state.get("health", 20)
        food = state.get("food", 20)
        nearby_hostiles = state.get("nearby_hostiles", [])
        is_day = state.get("is_day", True)
        now = time.time()
        inv_map = inv or {}

        # --- F1 SURVIVAL & LIFE ESSENTIALS ENGINE (F1-1 & F1-2) ---
        inv_summary = state.get("inventory_summary", "").lower()
        edible_food_items = [
            "cooked_beef", "cooked_porkchop", "bread", "apple", "cooked_chicken",
            "cooked_mutton", "baked_potato", "golden_apple", "carrot", "beetroot",
            "sweet_berries", "cooked_salmon", "cooked_cod", "melon_slice",
            "beef", "porkchop", "mutton", "chicken"
        ]
        has_food = any(inv_map.get(f, 0) > 0 for f in edible_food_items) if inv_map else any(f in inv_summary for f in edible_food_items)

        # 1. Low HP Management & HP Tracking Monitor (F1-2: HP < 8)
        if health < 8:
            if not hasattr(self, "_low_hp_monitor") or self._low_hp_monitor is None:
                self._low_hp_monitor = {
                    "start_time": now,
                    "start_hp": health,
                    "last_hp": health,
                    "active_strategy": "priority_recovery"
                }

            mon = self._low_hp_monitor
            # Check HP progression during monitoring
            if health > mon["last_hp"]:
                logger.info(f"❤️ [Health Monitor] HP increased from {mon['last_hp']:.1f} to {health:.1f}! (Recovery active)")
                mon["last_hp"] = health
                mon["start_time"] = now  # Reset 60s timer upon positive progress

            # 60s HP stagnancy check (F1-2)
            elapsed_low_hp = now - mon["start_time"]
            if elapsed_low_hp >= 60.0 and health <= mon["start_hp"]:
                logger.warning(
                    f"⚠️ [Health Monitor] HP did not increase within 60s (initial={mon['start_hp']:.1f}, current={health:.1f}). "
                    "Switching survival recovery strategy..."
                )
                mon["start_time"] = now
                mon["start_hp"] = health

                if has_food and food < 20:
                    strategy = "eat_to_regenerate"
                    mon["active_strategy"] = strategy
                    logger.info("❤️ [Health Strategy Result] Selected strategy: consume food to force health regeneration.")
                    return {
                        "text": "HP stagnant after 60s. Eating food immediately for regeneration.",
                        "tool_calls": [{"name": "eat_food", "arguments": {}}]
                    }
                elif not has_food:
                    strategy = "gather_food"
                    mon["active_strategy"] = strategy
                    food_step = getattr(self, "_stagnant_food_step", 0)
                    self._stagnant_food_step = food_step + 1

                    # F1-R7: Doğal iyileşme için açlık < 14 ve HP stagnant ise yiyecek kaynağı öncelikli;
                    # hayvan avından tarla, balık veya köy/keşif rotasyonuna geç (tekrar eden başarısız aksiyon yok).
                    rotation_choice = food_step % 4
                    if rotation_choice == 0:
                        logger.info("❤️ [Health Strategy Result] (F1-R7) Selected strategy: hunt animals for sustenance.")
                        return {
                            "text": "HP stagnant and no food. Hunting food animals immediately.",
                            "tool_calls": [{"name": "hunt_food", "arguments": {"animal_type": "any"}}]
                        }
                    elif rotation_choice == 1:
                        logger.info("❤️ [Health Strategy Result] (F1-R7) Selected strategy: shift to crop farming/harvesting.")
                        return {
                            "text": "HP stagnant and no animals found. Harvesting crops for nourishment.",
                            "tool_calls": [{"name": "farm_crops", "arguments": {"crop_type": "all"}}]
                        }
                    elif rotation_choice == 2:
                        logger.info("❤️ [Health Strategy Result] (F1-R7) Selected strategy: shift to catching fish.")
                        return {
                            "text": "HP stagnant and crops exhausted. Catching fish for emergency food.",
                            "tool_calls": [{"name": "catch_fish", "arguments": {"count": 2}}]
                        }
                    else:
                        logger.info("❤️ [Health Strategy Result] (F1-R7) Selected strategy: relocate to scout village/food sources.")
                        pos = state.get("position", {"x": 0, "y": 64, "z": 0})
                        angle = random.random() * 2 * math.pi
                        target_x = round(pos.get("x", 0) + math.cos(angle) * 35)
                        target_z = round(pos.get("z", 0) + math.sin(angle) * 35)
                        return {
                            "text": "HP stagnant and area food exhausted. Scouting new territory for sustenance.",
                            "tool_calls": [{"name": "go_to_coordinates", "arguments": {"x": target_x, "z": target_z, "ignore_y": True, "range": 3}}]
                        }
                else:
                    strategy = "relocate"
                    mon["active_strategy"] = strategy
                    logger.info("❤️ [Health Strategy Result] Selected strategy: relocate 30m away to safer zone.")
                    pos = state.get("position", {"x": 0, "y": 64, "z": 0})
                    angle = random.random() * 2 * math.pi
                    target_x = round(pos.get("x", 0) + math.cos(angle) * 30)
                    target_z = round(pos.get("z", 0) + math.sin(angle) * 30)
                    return {
                        "text": "HP stagnant. Relocating away from hazardous area.",
                        "tool_calls": [{"name": "go_to_coordinates", "arguments": {"x": target_x, "z": target_z, "ignore_y": True, "range": 3}}]
                    }

            # F1-2: Pure physical panic shelter ONLY if health <= 4 and nearby_hostiles (Phase 2 Cortex)
            if health <= 4 and nearby_hostiles and not state.get("is_sheltered", False):
                logger.warning(f"🛡️ [Survival Priority] Low HP ({health}/20) with nearby hostiles! Withdrawing to emergency shelter.")
                return {
                    "text": "Critical HP and surrounded! Securing position in emergency bunker.",
                    "tool_calls": [{"name": "build_shelter", "arguments": {"mode": "auto"}}]
                }

            # F1-1: HP < 8 iken öncelikli yeme:
            if has_food and food < 20:
                if now - getattr(self, "last_eat_emergency_time", 0.0) >= 3.0:
                    self.last_eat_emergency_time = now
                    logger.info(f"❤️ [Survival Priority] Low HP ({health}/20) & Hunger ({food}/20). Prioritizing eat action to trigger regen.")
                    return {
                        "text": "Critical health! Eating food immediately to restore HP.",
                        "tool_calls": [{"name": "eat_food", "arguments": {}}]
                    }

            # F1-1: Yiyecek yoksa bunu loga yaz ve yiyecek toplama hedefi ver (sadece tool call ile, sessiz geçme):
            if not has_food and not state.get("is_sheltered"):
                logger.warning(f"🍽️ [Survival Priority] Critical HP ({health}/20) but NO food in inventory! Setting food gathering goal.")
                from ai.farming import should_prioritize_farming, get_farming_action_plan
                if inv_map and should_prioritize_farming(inv_map, state):
                    farm_plan = get_farming_action_plan(inv_map, state)
                    return {
                        "text": "Critical HP and out of food! Harvesting nearby food sources.",
                        "tool_calls": [farm_plan]
                    }
                return {
                    "text": "Critical HP and out of food! Hunting animals for nourishment.",
                    "tool_calls": [{"name": "hunt_food", "arguments": {"animal_type": "any"}}]
                }
        else:
            # Health is healthy (>= 8 HP) - reset low HP monitor
            if hasattr(self, "_low_hp_monitor") and self._low_hp_monitor is not None:
                self._low_hp_monitor = None

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
                if food < 18 and has_food:
                    return {
                        "text": "Resting safely inside my shelter and eating food to heal.",
                        "tool_calls": [{"name": "eat_food", "arguments": {}}]
                    }
                # Check for bed to skip night
                vis_res = state.get("visible_resources", {})
                if vis_res.get("bed") or any("bed" in i for i in inv_map):
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
                if now - getattr(self, "last_bunker_wait_chat_time", 0.0) >= 30.0:
                    self.last_bunker_wait_chat_time = now
                    return {
                        "text": "Remaining safely inside shelter until hostiles clear and daylight arrives.",
                        "tool_calls": [{"name": "say_chat", "arguments": {"message": "Safe inside bunker. Waiting for threats to pass..."}}]
                    }
                return {
                    "text": "",
                    "tool_calls": []
                }

        # 2. Imminent Starvation Reflex: Food < 4 (Phase 2 Cortex: Hunger < 14 handled by Cortex)
        if food < 4:
            if has_food:
                if now - getattr(self, "last_eat_emergency_time", 0.0) >= 3.0:
                    self.last_eat_emergency_time = now
                    logger.info(f"❤️ [Survival Priority] Immediate starvation reflex (Food: {food}/20, HP: {health}/20). Consuming food.")
                    return {
                        "text": "Starvation damage imminent! Eating immediately.",
                        "tool_calls": [{"name": "eat_food", "arguments": {}}]
                    }
            else:
                from ai.farming import should_prioritize_farming, get_farming_action_plan
                if inv_map and should_prioritize_farming(inv_map, state):
                    farm_plan = get_farming_action_plan(inv_map, state)
                    return {
                        "text": "Starving and out of food. Harvesting nearby crops.",
                        "tool_calls": [farm_plan]
                    }

                hunt_failures = getattr(self, "consecutive_hunt_failures", 0)
                if hunt_failures >= 3:
                    if not getattr(self, "_tried_emergency_farm", False):
                        self._tried_emergency_farm = True
                        logger.warning("⚠️ [STUCK LOOP BREAK] 3 consecutive hunts failed! Shifting to crop harvesting.")
                        return {
                            "text": "No animals found after 3 hunts! Harvesting any available crops for food.",
                            "tool_calls": [{"name": "farm_crops", "arguments": {"crop_type": "all"}}]
                        }
                    elif not getattr(self, "_tried_emergency_fish", False):
                        self._tried_emergency_fish = True
                        return {
                            "text": "No crops found! Catching fish for emergency food.",
                            "tool_calls": [{"name": "catch_fish", "arguments": {"count": 2}}]
                        }
                    else:
                        self._tried_emergency_farm = False
                        self._tried_emergency_fish = False
                        self.consecutive_hunt_failures = 0
                        pos = state.get("position", {"x": 0, "y": 64, "z": 0})
                        angle = random.random() * 2 * math.pi
                        target_x = pos.get("x", 0) + math.cos(angle) * 45
                        target_z = pos.get("z", 0) + math.sin(angle) * 45
                        return {
                            "text": "Starvation area exhausted. Relocating to new territory for food.",
                            "tool_calls": [{"name": "go_to_coordinates", "arguments": {"x": round(target_x), "z": round(target_z), "ignore_y": True, "range": 3}}]
                        }

                nearby_passives = state.get("nearby_passives", [])
                has_nearby_animals = any(
                    any(a in p.lower() for a in ["cow", "pig", "sheep", "chicken"])
                    for p in nearby_passives
                )
                cooldown = 15.0 if not has_nearby_animals else 8.0
                if now - getattr(self, "last_hunt_emergency_time", 0.0) >= cooldown:
                    self.last_hunt_emergency_time = now
                    self.consecutive_hunt_failures = hunt_failures + 1
                    return {
                        "text": "Starving and out of food. Hunting nearby animals for meat.",
                        "tool_calls": [{"name": "hunt_food", "arguments": {"animal_type": "any"}}]
                    }
                else:
                    logger.debug("⏳ Starvation hunt cooldown active. Skipping hunt spam.")
                    return None

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

        # F1-R11: Check pending category shift from repeated action failures
        if (
            getattr(self, "_pending_category_shift", False)
            or getattr(self, "_consecutive_action_failure_count", 0) >= 3
            or getattr(self, "_consecutive_same_fallback_count", 0) >= 3
        ):
            reason_lbl = (
                getattr(self, "_pending_category_shift_reason", None)
                or f"Action failure '{getattr(self, '_last_action_failure_key', 'repeated_failure')}' repeated 3 consecutive times"
            )
            shift_act = self.trigger_category_shift(
                state,
                reason_label=reason_lbl
            )
            return {
                "text": f"Repeated action failure detected. Shifting category to {self._last_fallback_category_shift}.",
                "tool_calls": [shift_act]
            }

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
            goal = inv_goal
            substep_hint, milestone_action = self.get_milestone_action(goal, inv_dict, state)
            substep_hint = f"Rebuilding gear toward {self.checkpoint_target} ({self.checkpoint_stage}): currently need {inv_goal['target']} ({substep_hint})"
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

        # Collect sensory alerts and opportunities (Cortex-First)
        edible_food_items = (
            "cooked_beef", "cooked_porkchop", "bread", "apple", "cooked_chicken",
            "cooked_mutton", "baked_potato", "golden_apple", "carrot", "beetroot",
            "sweet_berries", "cooked_salmon", "cooked_cod", "melon_slice",
            "beef", "porkchop", "mutton", "chicken"
        )
        has_food = any(inv_dict.get(f, 0) > 0 for f in edible_food_items) or any(f in inv_summary for f in edible_food_items)

        alerts: List[str] = []
        if food < 14:
            alerts.append(f"Hunger low ({food}/20). Need food soon.")
            if not has_food:
                logger.warning(f"🍽️ [Hunger Alert] Hunger is {food}/20 (< 14) and NO food in inventory! Setting food gathering goal.")
        if food < 6:
            alerts.append(f"STARVATION RISK: Hunger critical ({food}/20)!")
        if health <= 6:
            alerts.append(f"CRITICAL HEALTH: HP {health}/20!")
        if health < 8 and not has_food and not state.get("is_sheltered"):
            logger.warning(f"🍽️ [Survival Priority] Critical HP ({health}/20) but NO food in inventory! Setting food gathering goal.")

        time_of_day = str(state.get("time_of_day", "")).lower()
        if time_of_day in ("night", "dusk") or (not state.get("is_day", True) and not state.get("is_sheltered")):
            alerts.append("Night is falling/present. Phantom/monster risk.")

        # Check carried tools for low durability (< 5 uses)
        tool_base = state.get("tool_base", {})
        if isinstance(tool_base, dict):
            for t_name, t_info in tool_base.items():
                if isinstance(t_info, dict) and t_info.get("durability", 100) < 5:
                    alerts.append(f"Tool {t_name} critically damaged ({t_info.get('durability')} uses left)!")

        # Scan opportunities (pass to Cortex; do NOT hardcode override!)
        opportunities: List[str] = []
        opp = None
        if not state.get("active_player_task") and not state.get("is_busy", False):
            opp = self.opportunity_scanner.evaluate_opportunities(inv_dict, state, goal)
            if opp:
                opportunities.append(f"{opp.name} ({opp.reason})")

        if owner_info:
            dist = owner_info.get("distance", 0)
            owner_summary = f"{self.bot_owner} {dist}m away"
        else:
            owner_summary = f"{self.bot_owner} out of sight"

        surv_summary = self.format_survival_inventory_context(state)
        state["survival_status_summary"] = surv_summary

        # Update spatial exploration tracking and prompt context summaries (Phase 2)
        pos = state.get("position", {"x": 0, "y": 0, "z": 0})
        biome = state.get("biome", "unknown")
        self.exploration_engine.update_position(pos, biome)
        affordances_summary = self.affordance_engine.format_affordances_context(inv_dict)
        state["affordances_summary"] = affordances_summary
        recent_actions = self.format_recent_actions_context()
        state["recent_actions_summary"] = recent_actions
        recent_lessons = []
        if self.db and hasattr(self.db, "get_recent_lessons"):
            lessons = self.db.get_recent_lessons(limit=3)
            if lessons:
                recent_lessons = lessons
                state["learned_lessons_summary"] = "; ".join(lessons)

        try:
            # Compute feasible actions for ultra-compact perception
            feasible_actions = []
            affordances = self.affordance_engine.get_affordances(inv_dict)
            for c in affordances.get("craftable_now", [])[:3]:
                feasible_actions.append(f"craft:{c}")
            for s in affordances.get("smeltable_now", [])[:2]:
                feasible_actions.append(f"smelt:{s}")
            if milestone_action:
                m_name = milestone_action.get("name")
                if m_name == "collect_block":
                    b = milestone_action.get("arguments", {}).get("block_name", "log")
                    feasible_actions.append(f"collect:{b}")
                elif m_name:
                    feasible_actions.append(m_name)

            logger.info(f"🎯 Milestone: {goal['target']} | Evaluating tactical action via Cortex...")
            cortex_decision = await self.cortex.think_and_decide(
                state=state,
                inv_dict=inv_dict,
                alerts=alerts,
                affordances_summary=affordances_summary,
                opportunities=opportunities,
                style=self.player_style.value,
                recent_actions=recent_actions,
                lessons=recent_lessons,
                goal=goal,
                missing_ingredients=state.get("missing_ingredients"),
                feasible_actions=feasible_actions
            )

            tool_calls = []
            response: Dict[str, Any] = {}
            is_fallback = False
            if cortex_decision and cortex_decision.get("tool_calls"):
                is_fallback = False
                response = dict(cortex_decision)
                tool_calls = [dict(tc) for tc in cortex_decision.get("tool_calls", [])]
                self.fallback_consecutive_count = 0
                self._consecutive_same_fallback_count = 0
                self._last_fallback_key = None

                # Broadcast thought periodically (rate-limited to 30s)
                now = time.time()
                if now - getattr(self, "last_thought_chat_time", 0.0) >= 30.0:
                    self.last_thought_chat_time = now
                    thought_text = cortex_decision.get("thought", "")
                    if thought_text:
                        logger.info(f"💭 [Player Thought] {thought_text}")
            else:
                is_fallback = True
                # Cortex returned None or empty tool calls -> Clean fallback heuristics
                if opp and opp.priority >= 7:
                    logger.info(f"✨ [Opportunistic Priority] {opp.reason} -> {opp.action}({opp.arguments})")
                    return {
                        "text": f"Opportunistic priority: {opp.reason}",
                        "tool_calls": [{"name": opp.action, "arguments": opp.arguments}]
                    }

                style_bias = self.style_strategy.get_style_milestone_bias(self.player_style, inv_dict, state)
                if style_bias:
                    b_action = style_bias.get("action")
                    b_args = style_bias.get("arguments", {})
                    b_reason = style_bias.get("reason", "Player style priority")
                    logger.info(f"🎭 [Style Bias Applied] {self.player_style.value} -> {b_action}({b_args}): {b_reason}")
                    return {
                        "text": f"Style priority ({self.player_style.value}): {b_reason}",
                        "tool_calls": [{"name": b_action, "arguments": b_args}]
                    }

                self.fallback_count += 1
                if hasattr(self.brain, "fallback_count"):
                    self.brain.fallback_count = self.fallback_count
                fallback_action = self.generate_fallback_action(goal, inv_dict, owner_info, state)
                rule_name = getattr(self, "last_fallback_rule", "fallback_rule")
                action_name = fallback_action.get("name") if fallback_action else "none"
                action_args = fallback_action.get("arguments") if fallback_action else {}
                logger.info(f"ℹ️ [Fallback Rule] Triggered rule '{rule_name}' -> action '{action_name}' ({action_args}) due to 0 LLM tool calls.")

                if fallback_action:
                    action_sig = f"{action_name}:{json.dumps(action_args, sort_keys=True)}"
                    if action_sig == getattr(self, "_last_fallback_key", None):
                        self._consecutive_same_fallback_count += 1
                    else:
                        self._last_fallback_key = action_sig
                        self._consecutive_same_fallback_count = 1

                    if self._consecutive_same_fallback_count >= 3:
                        fallback_action = self.trigger_category_shift(
                            state,
                            reason_label=f"Fallback '{action_sig}' repeated 3 consecutive times"
                        )

                    tool_calls = [fallback_action]
                    response = {
                        "text": f"Progression fallback: {rule_name}",
                        "tool_calls": tool_calls
                    }
                    self.fallback_consecutive_count += 1
                else:
                    self.fallback_consecutive_count = 0
                    return None

            if not is_fallback:
                # Validate tool calls - prevent blind impossible craft loops
                sanitized_calls = []
                for tc in tool_calls:
                    c_name = tc.get("name")
                    c_args = tc.get("arguments", {})
                    if not isinstance(c_args, dict):
                        c_args = {}

                    # Normalize argument aliases
                    for arg_key in ("block_name", "item_name", "input_item", "target_name"):
                        if arg_key in c_args and isinstance(c_args[arg_key], str):
                            c_args[arg_key] = normalize_item_alias(c_args[arg_key])

                    # Attack-vs-Block Disambiguation
                    if c_name in ("attack", "attack_target"):
                        t_name = str(c_args.get("target_name", "")).lower()
                        if any(k in t_name for k in ("_log", "log", "_ore", "stone", "cobblestone", "deepslate", "dirt", "sand", "gravel", "planks", "crafting_table", "furnace")):
                            logger.info(f"🔄 Disambiguating attack_target('{t_name}') -> collect_block('{t_name}').")
                            sanitized_calls.append({"name": "collect_block", "arguments": {"block_name": t_name, "count": 1}})
                            continue

                    # Scout Obsession Guard (R3 fix): 180s cooldown
                    if c_name == "scout_high_ground":
                        now = time.time()
                        last_scout = getattr(self, "last_scout_time", 0.0)
                        if now - last_scout < 180.0:
                            logger.warning(
                                f"🛡️ [Scout Obsession Guard] scout_high_ground requested within 180s cooldown "
                                f"({round(now - last_scout, 1)}s elapsed). Auto-diverting action."
                            )
                            if milestone_action and milestone_action.get("name") == "collect_block":
                                sanitized_calls.append(milestone_action)
                            else:
                                cur_pos = state.get("position", {"x": 0, "y": 64, "z": 0})
                                target_coord = self.exploration_engine.get_next_exploration_target(cur_pos)
                                sanitized_calls.append({
                                    "name": "go_to_coordinates",
                                    "arguments": {"x": target_coord[0], "y": target_coord[1], "z": target_coord[2], "range": 3}
                                })
                            continue
                        else:
                            self.last_scout_time = now

                    # Stage 0 Priority Guard: Prevent aimless wandering at spawn without wood/tools
                    if c_name == "go_to_coordinates" and not state.get("active_player_task"):
                        has_pickaxe = any("pickaxe" in item for item in inv_dict.keys())
                        wood_count = sum(c for i, c in inv_dict.items() if "log" in i or "plank" in i)
                        has_death_recovery = False
                        if self.db and hasattr(self.db, "get_unrecovered_death_point"):
                            if self.db.get_unrecovered_death_point():
                                has_death_recovery = True
                        if not has_pickaxe and wood_count < 4 and not has_death_recovery:
                            logger.info("🛡️ [Stage 0 Guard] Wandering without pickaxe and <4 wood at spawn! Substituting milestone action: collect_block('log').")
                            sanitized_calls.append(milestone_action if milestone_action else {"name": "collect_block", "arguments": {"block_name": "log", "count": 3}})
                            continue

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
                                if not sub_action or sub_action.get("name") == "craft_item":
                                    first_missing = str(missing_for_item[0]).lower()
                                    if any(w in first_missing for w in ("log", "wood", "plank", "stem")):
                                        sub_action = {"name": "collect_block", "arguments": {"block_name": "log", "count": 3}}
                                    elif any(s in first_missing for s in ("stone", "cobble")):
                                        sub_action = {"name": "collect_block", "arguments": {"block_name": "stone", "count": 3}}
                                    elif "iron" in first_missing:
                                        if inv_dict.get("raw_iron", 0) > 0:
                                            sub_action = {"name": "smelt_item", "arguments": {"input_item": "raw_iron", "count": 3}}
                                        else:
                                            sub_action = {"name": "collect_block", "arguments": {"block_name": "iron", "count": 3}}
                                    elif "gold" in first_missing:
                                        if inv_dict.get("raw_gold", 0) > 0:
                                            sub_action = {"name": "smelt_item", "arguments": {"input_item": "raw_gold", "count": 3}}
                                        else:
                                            sub_action = {"name": "collect_block", "arguments": {"block_name": "gold_ore", "count": 3}}
                                    elif "diamond" in first_missing:
                                        sub_action = {"name": "collect_block", "arguments": {"block_name": "diamond_ore", "count": 3}}
                                    else:
                                        raw_target = first_missing.split()[-1].replace(" ", "_")
                                        sub_action = {"name": "collect_block", "arguments": {"block_name": raw_target, "count": 1}}

                                logger.warning(
                                    f"⚠️ [Crafting Precondition Guard] Intercepted craft_item('{target_craft}') with missing ingredients "
                                    f"({', '.join(missing_for_item)}). Rewriting action to {sub_action.get('name')}({sub_action.get('arguments')})."
                                )
                                sanitized_calls.append(sub_action)
                                continue
                    sanitized_calls.append(tc)
                tool_calls = sanitized_calls
                response["tool_calls"] = tool_calls

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
                                    {"name": "go_to_coordinates", "arguments": {"x": round(tx), "z": round(tz), "ignore_y": True, "range": 3}}
                                ]
                            }
                else:
                    self.consecutive_repeats = 0

                self._last_action_sig = action_sig
                self.last_action_command = first_cmd

            return response
        except asyncio.TimeoutError:
            self.fallback_count += 1
            if hasattr(self.brain, "fallback_count"):
                self.brain.fallback_count = self.fallback_count
            logger.warning("⏱️ LLM reasoning timed out. Using backup strategy.")
            fallback_action = self.generate_fallback_action(goal, inv_dict, owner_info, state)
            rule_name = getattr(self, "last_fallback_rule", "fallback_rule")
            logger.info(f"ℹ️ [Fallback Rule] Triggered rule '{rule_name}' -> action '{fallback_action.get('name') if fallback_action else 'none'}' due to timeout.")
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
        """Generates proactive fallback action when LLM is unavailable or timed out.

        Returns the action dict (backward compatible). The triggered rule name (F1-6)
        is stored in ``self.last_fallback_rule``.
        """
        rule_name, action = self._generate_fallback_action_with_rule(goal, inv, owner_info, state)
        self.last_fallback_rule = rule_name
        return action

    def _generate_fallback_action_with_rule(
        self,
        goal: Dict[str, Any],
        inv: Dict[str, int],
        owner_info: Optional[Dict[str, Any]],
        state: Optional[Dict[str, Any]] = None
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """Returns (rule_name, action) for the fallback decision."""
        if not state:
            state = {}

        # 1. Active teammate directive check
        active_task = state.get("active_player_task")
        if active_task:
            instruction = active_task.get("instruction", "").lower()
            if any(w in instruction for w in ["guard", "koru", "protect"]):
                return "teammate_directive", {"name": "guard_player", "arguments": {"player_name": self.bot_owner}}
            if any(w in instruction for w in ["follow", "gel", "takip", "come"]):
                return "teammate_directive", {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
            if any(w in instruction for w in ["hunt", "food", "yemek", "avlan"]):
                return "teammate_directive", {"name": "hunt_food", "arguments": {"animal_type": "any"}}
            if any(w in instruction for w in ["sleep", "bed", "uyu"]):
                return "teammate_directive", {"name": "sleep_in_bed", "arguments": {}}

        # 2. Emergency tactical Chorus Fruit teleport (F5)
        if inv.get("chorus_fruit", 0) > 0:
            if state.get("is_falling", False) or (state.get("health", 20) <= 6 and state.get("nearby_hostiles_count", 0) >= 2):
                return "emergency_chorus", {"name": "eat_chorus_fruit", "arguments": {}}

        # 2b. Low HP safety rules when Cortex/LLM unavailable
        health_level = state.get("health", 20)
        nearby_hostiles = state.get("nearby_hostiles", [])
        if nearby_hostiles and health_level < 8 and not state.get("is_sheltered", False):
            return "emergency_shelter", {"name": "build_shelter", "arguments": {"mode": "auto"}}
        if health_level < 8 and has_eatable and food_level < 20:
            return "emergency_eat", {"name": "eat_food", "arguments": {}}

        # 3. Hunger check - consume food if hungry
        food_level = state.get("food", 20)
        has_eatable = any(
            f in inv for f in [
                "cooked_beef", "cooked_porkchop", "bread", "apple",
                "cooked_chicken", "cooked_mutton", "baked_potato",
                "golden_apple", "carrot", "beetroot", "sweet_berries"
            ]
        )
        if food_level < 15:
            if has_eatable:
                return "hunger_eat", {"name": "eat_food", "arguments": {}}
            elif inv.get("chorus_fruit", 0) > 0:
                return "emergency_chorus", {"name": "eat_chorus_fruit", "arguments": {}}

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
            return "smelt_food", {
                "name": "smelt_item",
                "arguments": {
                    "input_item": raw_meats[0],
                    "count": min(inv.get(raw_meats[0], 1), 4)
                }
            }

        # 5. Sustainable farming / hay bale harvesting
        from ai.farming import should_prioritize_farming, get_farming_action_plan
        if should_prioritize_farming(inv, state):
            return "farming_harvest", get_farming_action_plan(inv, state)

        # 6. Hunt food animals if hungry and out of food
        if food_level < 15 and not has_eatable and not raw_meats:
            return "hunt_food", {"name": "hunt_food", "arguments": {"animal_type": "any"}}

        # 7. Night shelter check (Overworld only; beds explode in Nether and End!)
        dimension = str(state.get("dimension", "overworld")).lower()
        is_nether_or_end = "nether" in dimension or "end" in dimension
        if not state.get("is_day", True) and not is_nether_or_end:
            vis_res = state.get("visible_resources", {})
            if vis_res.get("bed"):
                return "night_shelter", {"name": "sleep_in_bed", "arguments": {}}
            else:
                return "night_shelter", {"name": "build_shelter", "arguments": {"mode": "auto"}}

        # 8. Tech tree progression milestones
        guidance, action = self.get_milestone_action(goal, inv, state)
        return "milestone_progression", action

    def get_milestone_action(
        self,
        goal: Dict[str, Any],
        inv: Any,
        state: Optional[Dict[str, Any]] = None
    ) -> tuple[str, Dict[str, Any]]:
        """Determines the specific sub-step guidance and tactical action for the active milestone."""
        # Support calling with full state dict as 2nd arg: get_milestone_action(goal, state)
        if state is None and isinstance(inv, dict) and ("survival_inventory" in inv or "nearby_iron_golems_count" in inv or isinstance(inv.get("inventory"), list)):
            state = inv
            inv_items = state.get("inventory", []) or state.get("inventory_items", [])
            inv = self.parse_inventory(inv_items) if isinstance(inv_items, list) else {}
        elif not state:
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
        has_any_pickaxe = any(
            p in inv for p in ("wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe")
        )
        if target in ("stone_pickaxe", "furnace"):
            if not has_any_pickaxe:
                if (log_count * 4) + plank_count < 4:
                    return "Mine 3 logs (need wooden pickaxe for stone)", {"name": "collect_block", "arguments": {"block_name": "log", "count": 3}}
                return "Craft wooden pickaxe (need wooden pickaxe for stone)", {"name": "craft_item", "arguments": {"item_name": "wooden_pickaxe", "count": 1}}

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

        # Tactical Gear Buff: Village trading when villagers are nearby (F2 / GP-1.2)
        nearby_villagers = state.get("nearby_villagers_count", 0)
        surv_inv = state.get("survival_inventory", {}) if isinstance(state.get("survival_inventory"), dict) else {}
        trading_cap = surv_inv.get("trading_capital", {}) if isinstance(surv_inv.get("trading_capital"), dict) else {}
        can_trade_flag = bool(trading_cap.get("can_trade_now", False))
        if nearby_villagers > 0 and (
            can_trade_flag
            or inv.get("emerald", 0) > 0
            or inv.get("wheat", 0) >= 20
            or inv.get("hay_block", 0) >= 3
            or inv.get("raw_iron", 0) >= 15
        ):
            return "Trade with nearby village villager for provisions and gear", {"name": "trade_with_villager", "arguments": {"trade_item": "auto", "count": 1}}

        # Tactical Defense Buff: Autonomous Golem Construction when materials are ready and no golem is nearby (F2 / GP-1.1)
        golem_ready = surv_inv.get("golem_readiness", {}) if isinstance(surv_inv.get("golem_readiness"), dict) else {}
        if golem_ready.get("can_build_iron_golem", False) and state.get("nearby_iron_golems_count", 0) == 0:
            return "Construct Iron Golem for autonomous base and village defense", {"name": "build_golem", "arguments": {"golem_type": "iron_golem", "count": 1}}
        if golem_ready.get("can_build_snow_golem", False) and state.get("nearby_snow_golems_count", 0) == 0 and state.get("nearby_iron_golems_count", 0) == 0:
            return "Construct Snow Golem for perimeter defense", {"name": "build_golem", "arguments": {"golem_type": "snow_golem", "count": 1}}

        # Tactical Tool Base Completion: Craft full survival tool set if tool base completeness < 60% and iron/diamond surplus exists (F2 / GP-1.3)
        tool_base_info = surv_inv.get("tool_base", {}) if isinstance(surv_inv.get("tool_base"), dict) else {}
        if (
            tool_base_info
            and tool_base_info.get("completeness_pct", 100) < 60
            and (inv.get("iron_ingot", 0) >= 6 or inv.get("diamond", 0) >= 5)
            and target not in ("wooden_pickaxe", "stone_pickaxe")
        ):
            return "Complete survival tool base with craft_tool_set", {"name": "craft_tool_set", "arguments": {"tier": "auto"}}

        # Tactical Gear Buff: Spare tool check (F2)
        total_pickaxes = inv.get("iron_pickaxe", 0) + inv.get("diamond_pickaxe", 0)
        has_spare_iron = inv.get("iron_ingot", 0) >= 3 and inv.get("stick", 0) >= 2
        if (low_durability or total_pickaxes < 2) and has_spare_iron and target not in ("wooden_pickaxe", "stone_pickaxe"):
            return "Craft spare iron pickaxe for exploration safety", {"name": "craft_item", "arguments": {"item_name": "iron_pickaxe", "count": 1}}

        has_sword = "iron_sword" in inv or "diamond_sword" in inv
        if not has_sword and inv.get("iron_ingot", 0) >= 2 and inv.get("stick", 0) >= 1 and target not in ("wooden_pickaxe", "stone_pickaxe"):
            return "Craft iron sword for combat readiness", {"name": "craft_item", "arguments": {"item_name": "iron_sword", "count": 1}}

        # Tactical Gear Buff: Potion brewing before Nether or Dragon (F2)
        has_brewing_stand = "brewing_stand" in inv or state.get("nearby_brewing_stand", False)
        has_nether_wart = inv.get("nether_wart", 0) > 0
        has_bottles = any(b in inv for b in ("glass_bottle", "potion", "water_bottle"))
        if (has_brewing_stand or inv.get("blaze_rod", 0) >= 1) and has_nether_wart and has_bottles:
            if not state.get("fire_resistance_active", False) and inv.get("magma_cream", 0) > 0:
                return "Brew Fire Resistance potion using brewing stand", {"name": "brew_potion", "arguments": {"ingredient": "magma_cream"}}
            elif inv.get("glistering_melon_slice", 0) > 0:
                return "Brew Healing potion using brewing stand", {"name": "brew_potion", "arguments": {"ingredient": "glistering_melon_slice"}}

        # GP-5: Universal Special Ore Navigation from SQLite ore_map when target is a special ore
        if target in ("emerald", "gold", "lapis", "redstone", "copper", "quartz", "amethyst", "ancient_debris"):
            nav_act = self.get_recorded_ore_navigation_action(target, 3, dim, pos)
            if nav_act:
                return nav_act

        if target == "iron_pickaxe":
            if raw_iron < 3 and iron_ingots < 3:
                nav_act = self.get_recorded_ore_navigation_action("iron", 3, dim, pos)
                if nav_act:
                    return nav_act
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
                nav_act = self.get_recorded_ore_navigation_action("diamond", 3, dim, pos)
                if nav_act:
                    return nav_act
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

                # 5. Bastion Remnant exploration for ancient debris, gold, and upgrade templates
                if state.get("nearby_bastion", False) or (state.get("nearby_piglins_count", 0) >= 4 and inv.get("crying_obsidian", 0) < 6):
                    return "Explore Bastion Remnant for treasure and upgrade materials", {"name": "explore_bastion", "arguments": {"action_mode": "loot_chests"}}

                # 6. Nether Fortress search if Blaze rods missing (< 7) and no fortress found yet
                blaze_rods = inv.get("blaze_rod", 0)
                if blaze_rods < 7 and not state.get("nearby_blazes_count", 0) and not state.get("fortress_found", False):
                    return "Explore and locate Nether Fortress for Blaze spawners and nether wart", {"name": "explore_nether_fortress", "arguments": {"target_resource": "blaze_spawner"}}

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
                    if not state.get("nearby_blazes_count", 0) and not state.get("fortress_found", False):
                        return "Explore and locate Nether Fortress for Blaze spawners", {"name": "explore_nether_fortress", "arguments": {"target_resource": "blaze_spawner"}}
                    return "Hunt Blazes for rods", {"name": "attack_target", "arguments": {"target_name": "blaze"}}
                return "Build Nether portal for rods", {"name": "build_nether_portal", "arguments": {}}

        # Phase 3 & 4: The End & Ender Dragon Slaying (F5)
        if target in ("ender_dragon", "fight_ender_dragon", "end_crystal", "enter_exit_portal"):
            if "end" in dimension:
                # Emergency Chorus Fruit teleport if falling into void or high altitude
                if inv.get("chorus_fruit", 0) > 0 and state.get("is_falling", False):
                    return "Eat chorus fruit to escape lethal void fall", {"name": "eat_chorus_fruit", "arguments": {}}

                dragon_defeated = state.get("dragon_defeated", False)
                if dragon_defeated or target == "enter_exit_portal":
                    # F5: Outer End Islands exploration for Elytra & Shulker Boxes
                    if inv.get("ender_pearl", 0) >= 1 and not state.get("elytra_acquired", False):
                        return "Explore End Gateway towards End City for Elytra and Shulker Shells", {"name": "explore_end_city", "arguments": {}}
                    if state.get("elytra_acquired", False) and inv.get("firework_rocket", 0) >= 1 and state.get("travel_target"):
                        tt = state["travel_target"]
                        return "Fly with Elytra using rocket boost", {"name": "fly_with_elytra", "arguments": {"x": tt.get("x", 0), "y": tt.get("y", 100), "z": tt.get("z", 0)}}
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

    def format_survival_inventory_context(self, state: Dict[str, Any]) -> str:
        """Builds a compact summary of expanded survival inventory, tool base, trading capital, golem readiness, and special ores."""
        surv = state.get("survival_inventory")
        if not isinstance(surv, dict) or not surv:
            return ""
        parts = []
        tb = surv.get("tool_base", {})
        if isinstance(tb, dict):
            missing_core = tb.get("missing_core_tools", [])
            parts.append(f"ToolBase:{tb.get('completeness_pct', 0)}%(missing:{','.join(missing_core) if missing_core else 'none'})")
        tc = surv.get("trading_capital", {})
        if isinstance(tc, dict) and tc.get("can_trade_now"):
            parts.append(f"TradeReady(emeralds:{tc.get('emeralds', 0)})")
        gr = surv.get("golem_readiness", {})
        if isinstance(gr, dict):
            if gr.get("can_build_iron_golem"):
                parts.append("IronGolemReady")
            elif gr.get("can_build_snow_golem"):
                parts.append("SnowGolemReady")
        ores = surv.get("special_ores_radar", {}) or state.get("special_ores_radar", {})
        if isinstance(ores, dict) and ores:
            found_ores = []
            for entries in ores.values():
                if isinstance(entries, list):
                    for e in entries[:2]:
                        if isinstance(e, dict) and e.get("block"):
                            found_ores.append(f"{e['block']}@{e.get('closest_distance', '?')}m")
            if found_ores:
                parts.append(f"SpecialOres:{','.join(found_ores[:4])}")
        return f"[Survival: {' | '.join(parts)}]" if parts else ""

    def get_recorded_ore_navigation_action(
        self,
        ore_category: str,
        count: int,
        dim: str = "overworld",
        pos: Optional[Dict[str, Any]] = None,
        max_dist: float = 256.0
    ) -> Optional[tuple[str, Dict[str, Any]]]:
        """GP-5: Queries SQLite ore_map for any unmined ore matching ore_category and builds a coordinate-guided collect_block action."""
        if not self.db:
            return None
        p = pos if isinstance(pos, dict) else {"x": 0, "y": 64, "z": 0}
        unmined = self.db.get_unmined_ores(
            dim=dim,
            block_type=ore_category,
            x=p.get("x", 0),
            y=p.get("y", 64),
            z=p.get("z", 0),
            max_dist=max_dist
        )
        if not unmined:
            return None
        closest = unmined[0]
        logger.info(
            f"💎 [Ore Map Navigator] Directing bot to known unmined {closest['block']} "
            f"at ({closest['x']}, {closest['y']}, {closest['z']})!"
        )
        return f"Navigate to known {closest['block']} deposit from ore map", {
            "name": "collect_block",
            "arguments": {
                "block_name": closest["block"],
                "count": count,
                "target_x": closest["x"],
                "target_y": closest["y"],
                "target_z": closest["z"]
            }
        }

    async def close(self) -> None:
        """Closes cortex session and cleans up resources."""
        if hasattr(self, "cortex") and self.cortex:
            await self.cortex.close()
