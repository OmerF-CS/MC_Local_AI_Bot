"""Autonomous human-like Minecraft co-op partner brain - Production hardened."""
import asyncio
import json
import time
from typing import Dict, Any, List, Optional
from utils.logger import get_logger
from ai.progression_tree import get_current_progression_goal, resolve_missing_ingredients

logger = get_logger("AutonomousCoopBrain")


class AutonomousCoopBrain:
    """Proactive decision engine using Ollama and Minecraft progression tech tree."""

    def __init__(self, ollama_brain, bot_owner: str = "Omer", db=None):
        self.brain = ollama_brain
        self.bot_owner = bot_owner
        self.db = db
        self.last_action_command = None
        self.consecutive_repeats = 0
        self.fallback_consecutive_count = 0
        self.last_llm_failure_time = 0
        self.last_goal_target = None
        self.last_hunt_emergency_time = 0.0
        self.last_eat_emergency_time = 0.0

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
                return None

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

                if now - getattr(self, "last_hunt_emergency_time", 0.0) >= 10.0:
                    self.last_hunt_emergency_time = now
                    logger.warning(f"🍽️ [EMERGENCY] Starvation ({food}/20)! Hunting for meat.")
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

        # Retrieve active tech tree milestone
        goal = get_current_progression_goal(inv_dict, state)
        if goal["target"] != self.last_goal_target:
            self.last_goal_target = goal["target"]
            logger.info(f"🏆 [Milestone Checkpoint] Era: {goal['stage']} -> Target: {goal['target']}")
            if self.db:
                self.db.save_progression(goal["stage"], goal["target"], inv_dict)

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
            response = await self.brain.process_chat(
                sender="System/Autonomous",
                message=decision_prompt,
                state=state
            )

            tool_calls = response.get("tool_calls", [])
            
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
                    elif c_name == "craft_item":
                        target_craft = c_args.get("item_name") or goal.get("target")
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

            # Anti-repetition loop breaker - only trigger if identical action repeats 5 times without inventory progress
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
                    if self.consecutive_repeats >= 5:
                        logger.warning(
                            f"⚠️ [Loop Break] Action '{first_cmd}' repeated {self.consecutive_repeats} times without progress. "
                            "Breaking loop by shifting focus..."
                        )
                        self.consecutive_repeats = 0
                        alt_target = "stone" if "log" in str(args_str) else "log"
                        return {
                            "text": "Switching focus to gather different resources.",
                            "tool_calls": [
                                {"name": "collect_block", "arguments": {"block_name": alt_target, "count": 2}}
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

        if target == "iron_pickaxe":
            if raw_iron < 3 and iron_ingots < 3:
                return "Mine 3 iron ore (iron missing)", {"name": "collect_block", "arguments": {"block_name": "iron", "count": 3}}
            if raw_iron >= 3 and iron_ingots < 3:
                return "Smelt 3 raw iron into ingots", {
                    "name": "smelt_item",
                    "arguments": {"input_item": "raw_iron", "count": 3}
                }
            return "Craft iron pickaxe (materials ready)", {"name": "craft_item", "arguments": {"item_name": "iron_pickaxe", "count": 1}}

        diamonds = inv.get("diamond", 0)
        if target == "diamond_pickaxe":
            if diamonds < 3:
                return "Mine 3 diamonds (diamonds missing)", {"name": "collect_block", "arguments": {"block_name": "diamond", "count": 3}}
            return "Craft diamond pickaxe (materials ready)", {"name": "craft_item", "arguments": {"item_name": "diamond_pickaxe", "count": 1}}

        # Tactical Gear Buff: Enchanting check before dangerous dimensions
        from ai.enchanting import should_prioritize_enchanting
        xp_level = state.get("xp_level", 0)
        if should_prioritize_enchanting(inv, xp_level, dimension):
            return "Enchant gear at enchanting table", {"name": "enchant_gear", "arguments": {"gear_type": "auto", "target_level": 15}}

        # Phase 3: Nether Portal Progression
        if target == "nether_portal":
            if "nether" in dimension:
                cobble_count = inv.get("cobblestone", 0) + inv.get("cobbled_deepslate", 0) + inv.get("blackstone", 0)
                if cobble_count >= 12 and not state.get("nether_outpost_built", False):
                    return "Build Nether outpost for safety", {"name": "build_nether_outpost", "arguments": {"wall_material": "auto"}}
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
                return "Hunt Enderman for Ender Pearls", {"name": "attack_target", "arguments": {"target_name": "enderman"}}

            if blaze_rods < 1 and blaze_powders < 1:
                if "nether" in dimension:
                    return "Hunt Blazes for rods", {"name": "attack_target", "arguments": {"target_name": "blaze"}}
                return "Build Nether portal for rods", {"name": "build_nether_portal", "arguments": {}}

        # Phase 3 & 4: The End & Ender Dragon Slaying
        if target in ("ender_dragon", "fight_ender_dragon", "end_crystal", "enter_exit_portal"):
            if "end" in dimension:
                dragon_defeated = state.get("dragon_defeated", False)
                if dragon_defeated or target == "enter_exit_portal":
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
