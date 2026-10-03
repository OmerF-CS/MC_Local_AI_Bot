"""Otonom insan-benzeri Minecraft co-op partner beyin - Production hardened."""
import asyncio
from typing import Dict, Any, List, Optional
from utils.logger import get_logger
from ai.knowledge_base import get_relevant_tactic
from ai.progression_tree import get_current_progression_goal, resolve_missing_ingredients

logger = get_logger("AutonomousCoopBrain")


class AutonomousCoopBrain:
    """Ollama ve Minecraft progression tech tree kullanan proaktif karar motoru."""

    def __init__(self, ollama_brain, bot_owner: str = "Omer", db=None):
        self.brain = ollama_brain
        self.bot_owner = bot_owner
        self.db = db
        self.last_action_command = None
        self.consecutive_repeats = 0
        self.fallback_consecutive_count = 0
        self.last_llm_failure_time = 0
        self.last_goal_target = None

    def parse_inventory(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """Inventory item listesini name -> count mapping'e çevir."""
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

        # 1. Critical health (<= 6 HP / 3 hearts) with nearby hostile mobs
        if health <= 6 and nearby_hostiles:
            logger.warning(f"🚨 [EMERGENCY] Critical health ({health}/20) with hostiles nearby! Defending.")
            return {
                "text": "I'm in critical danger! Defending myself NOW!",
                "tool_calls": [
                    {"name": "guard_player", "arguments": {"player_name": self.bot_owner}}
                ]
            }

        # 2. Critical starvation (<= 4 hunger)
        if food <= 4:
            logger.warning(f"🍽️ [EMERGENCY] Starvation ({food}/20)! Eating immediately.")
            inv_summary = state.get("inventory_summary", "").lower()
            food_items = ["cooked_beef", "cooked_porkchop", "bread", "apple", "cooked_chicken", "cooked_mutton", "baked_potato"]
            has_food = any(f in inv for f in food_items) if inv else any(f in inv_summary for f in food_items)

            if has_food:
                return {
                    "text": "I'm STARVING! Eating immediately!",
                    "tool_calls": [{"name": "eat_food", "arguments": {}}]
                }
            else:
                return {
                    "text": "I'm STARVING and have NO food! Hunting for meat NOW!",
                    "tool_calls": [{"name": "hunt_food", "arguments": {"animal_type": "any"}}]
                }

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
                    "text": "Night and danger! Regrouping with you for safety.",
                    "tool_calls": [
                        {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
                    ]
                }

        return None

    async def decide_next_action(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Dünya durumu, oyuncu aksiyonları ve tech tree'yi analiz ederek optimal tool call'ı execute et."""
        if not state:
            return None

        if state.get("is_busy", False):
            logger.debug("⏳ Bot şu an bir aksiyon yapıyor. Karar döngüsü geçiliyor.")
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

        # Tech tree milestone'u al
        goal = get_current_progression_goal(inv_dict)
        if goal["target"] != self.last_goal_target:
            self.last_goal_target = goal["target"]
            logger.info(f"🏆 [Milestone Checkpoint] Era: {goal['stage']} -> Target: {goal['target']}")
            if self.db:
                self.db.save_progression(goal["stage"], goal["target"], inv_dict)

        missing_ingredients = resolve_missing_ingredients(goal["target"], inv_dict)
        missing_str = ", ".join(missing_ingredients) or "All materials ready for crafting!"

        pro_tactic = get_relevant_tactic(state)

        if owner_info:
            dist = owner_info.get("distance", 0)
            held = owner_info.get("held_item", "Empty hand")
            owner_summary = f"{self.bot_owner} is {dist} blocks away, currently holding '{held}'."
        else:
            owner_summary = f"{self.bot_owner} is not currently within line of sight."

        vision = state.get("vision_metrics", {})
        light = vision.get("light_level", 15)
        light_str = f"Pitch Dark ({light}/15 - Mobs will spawn!)" if light < 6 else f"Lit ({light}/15)"
        altitude_zone = vision.get("altitude_zone", "Surface / Overworld")

        vis_res = state.get("visible_resources", {})
        if vis_res:
            res_items = [
                f"{name} ({data['total_found']}x total, {data['visible_exposed']} exposed, {data['closest_distance']}m away)"
                for name, data in vis_res.items()
            ]
            vision_summary = ", ".join(res_items)
        else:
            vision_summary = "No key resources detected within 64m."

        carried_tools = state.get("carried_tools", "None")

        active_task = state.get("active_player_task")
        if active_task:
            task_header = f"""🎯 ACTIVE TEAMMATE DIRECTIVE (Assigned by {active_task.get('assigned_by', self.bot_owner)}):
- Instruction: \"{active_task.get('instruction')}\"
- Status: In Progress ({active_task.get('primary_action', 'co-op task')})
- YOUR TOP PRIORITY: Fulfill this mission for your partner immediately!"""
        else:
            task_header = f"""🕹️ PROACTIVE AUTONOMOUS INITIATIVE (No active teammate mission):
- You are free to advance your gear, prepare food, upgrade pickaxes, smelt ores, craft shields/armor, and stick close to {self.bot_owner}."""

        decision_prompt = f"""[AUTONOMOUS CO-OP REASONING CYCLE]:
You are an expert human-like co-op Minecraft partner playing with {self.bot_owner} to beat the game (defeat the Ender Dragon).
Never stand idle like a mindless bot! Take proactive initiative and advance your gear and team.

{task_header}

🏆 STRATEGIC TECH-TREE MILESTONE:
- Current Era: {goal['stage']}
- Primary Progression Target: {goal['target']}
- Missing Ingredients for Target: {missing_str}
- Milestone Advice: {goal['next_hint']}

❤️ BOT HEALTH & VITALS:
- Health: {health}/20 HP ({hearts} Hearts) | Hunger: {food}/20
- Guard Mode: {'Active (Guarding ' + self.bot_owner + ')' if state.get('is_guarding') else 'Autonomous'}

🎒 INVENTORY & BACKPACK ITEMS:
- Current Items: {inv_summary}

⛏️ TOOL MASTERY & HARVESTING RULES:
- Stone / Cobblestone / Coal Ore: Requires WOODEN PICKAXE or higher! (Bare hands drop 0 items!)
- Iron Ore / Lapis / Copper: Requires STONE PICKAXE or higher!
- Gold / Diamond / Redstone: Requires IRON PICKAXE or higher!
- Obsidian: Requires DIAMOND PICKAXE or higher!
- Wood / Logs: Harvest with AXE for 4x speed.
- Your Active Tools: {carried_tools}

🐾 SURROUNDING ENTITIES & THREAT RADAR (32m):
- Detected Entities: {entities_summary}

👁️ 3D ENVIRONMENTAL PERCEPTION (64-Block Radius):
- Position: X: {pos.get('x', 0):.1f}, Y: {pos.get('y', 0):.1f}, Z: {pos.get('z', 0):.1f}
- Altitude Zone: {altitude_zone}
- Lighting Level: {light_str}
- Biome: {biome} | Time of Day: {time_str}
- Air-Exposed & Reachable Resources (within 64m): {vision_summary}

👥 TEAM & PARTNER STATUS:
- {owner_summary}

💡 VETERAN TACTICAL TIP:
\"{pro_tactic}\"

YOUR TASK:
Make a decisive, tactical choice to assist {self.bot_owner} and advance towards defeating the Ender Dragon:
- If active teammate directive is present: focus on fulfilling it!
- If hunger is low (< 16) and you have food: invoke `eat_food`.
- If hunger is low (< 15) and you have NO food: invoke `hunt_food`.
- If you have raw meat and fuel: invoke `smelt_item` to cook food.
- If threatened by hostile mobs or {self.bot_owner} in danger: invoke `guard_player` or `attack_target`.
- If {self.bot_owner} has moved far ahead (distance > 16 blocks): invoke `follow_player`.
- If night has fallen and a bed is nearby: invoke `sleep_in_bed`.
- If materials are missing for gear: invoke `collect_block` or `craft_item`.
- Otherwise: stick close, guard your partner, or mine visible resources.

Decide and invoke a SINGLE appropriate tool call now!"""

        try:
            logger.info(f"🎯 Milestone: {goal['target']} | Evaluating tactical action...")
            response = await self.brain.process_chat(
                sender="System/Autonomous",
                message=decision_prompt,
                state=state
            )

            tool_calls = response.get("tool_calls", [])
            
            # Eğer LLM tool call vermedi ise fallback kullan
            if not tool_calls:
                logger.info("ℹ️ LLM tool call üretmedi. Fallback action kullanılıyor.")
                fallback_action = self.generate_fallback_action(goal, inv_dict, owner_info, state)
                if fallback_action:
                    tool_calls = [fallback_action]
                    response["tool_calls"] = tool_calls
                    self.fallback_consecutive_count += 1
                else:
                    self.fallback_consecutive_count = 0
            else:
                self.fallback_consecutive_count = 0

            # Eğer çok fazla fallback ard arda geldi ise güvenli regroup yap
            if self.fallback_consecutive_count >= 3:
                logger.warning(
                    "⚠️ Çok fazla fallback action gerekli. "
                    "LLM muhtemelen issues'a sahip. Safe regroup modu aktivasyonu."
                )
                return {
                    "text": "I'm regrouping and staying close to you for safety.",
                    "tool_calls": [
                        {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
                    ]
                }

            # Infinite loop koruması - aynı action 3 kez tekrarlandı mı?
            if tool_calls:
                first_cmd = tool_calls[0].get("name")
                if first_cmd == self.last_action_command:
                    self.consecutive_repeats += 1
                    if self.consecutive_repeats >= 3:
                        logger.warning(
                            f"⚠️ [Loop Break] '{first_cmd}' 3 kez tekrarlandı. "
                            "Regrouping..."
                        )
                        self.consecutive_repeats = 0
                        return {
                            "text": "Regrouping with you!",
                            "tool_calls": [
                                {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
                            ]
                        }
                else:
                    self.consecutive_repeats = 0
                self.last_action_command = first_cmd

            return response
        except asyncio.TimeoutError:
            logger.warning("⏱️ LLM timeout. Fallback action kullanılıyor.")
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
        """Bot'un insan oyuncu gibi davranmasını sağla - fallback aksiyon."""
        if not state:
            state = {}

        # 1. Aktif oyuncu görevi kontrolü
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

        # 2. Oyuncu çok uzakta mı? Takip et
        if owner_info and owner_info.get("distance", 0) > 16:
            return {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}

        # 3. Açlık tükenmi? Ye veya avla
        food_level = state.get("food", 20)
        has_eatable = any(
            f in inv for f in [
                "cooked_beef", "cooked_porkchop", "bread", "apple",
                "cooked_chicken", "cooked_mutton", "baked_potato"
            ]
        )
        if food_level < 15 and has_eatable:
            return {"name": "eat_food", "arguments": {}}

        # 4. Çiğ et ve yakıt varsa pişir
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

        # 5. Açlıktan ölmek üzereymişiz ve yemek yok? Avla
        if food_level < 15 and not has_eatable and not raw_meats:
            return {"name": "hunt_food", "arguments": {"animal_type": "any"}}

        # 6. Gece mi? Yatak ara (Yalnızca Overworld'de! Nether/End'de yataklar patlar)
        dimension = str(state.get("dimension", "overworld")).lower()
        is_nether_or_end = "nether" in dimension or "end" in dimension
        if not state.get("is_day", True) and not is_nether_or_end:
            vis_res = state.get("visible_resources", {})
            if vis_res.get("bed"):
                return {"name": "sleep_in_bed", "arguments": {}}

        # 7. Tech tree progression
        target = goal.get("target")
        log_count = sum(c for i, c in inv.items() if "log" in i or "stem" in i)
        plank_count = sum(c for i, c in inv.items() if "planks" in i)

        if target == "wooden_pickaxe":
            if log_count < 3 and plank_count < 4:
                return {"name": "collect_block", "arguments": {"block_name": "log", "count": 3}}
            return {"name": "craft_item", "arguments": {"item_name": "wooden_pickaxe", "count": 1}}

        cobble_count = sum(
            c for i, c in inv.items()
            if any(s in i for s in ("cobble", "deepslate", "blackstone"))
        )
        if target == "stone_pickaxe":
            if cobble_count < 3:
                return {"name": "collect_block", "arguments": {"block_name": "stone", "count": 3}}
            return {"name": "craft_item", "arguments": {"item_name": "stone_pickaxe", "count": 1}}

        if target == "furnace":
            if cobble_count < 8:
                return {"name": "collect_block", "arguments": {"block_name": "stone", "count": 8}}
            return {"name": "craft_item", "arguments": {"item_name": "furnace", "count": 1}}

        raw_iron = inv.get("raw_iron", 0) + inv.get("iron_ore", 0)
        iron_ingots = inv.get("iron_ingot", 0)

        if iron_ingots >= 1 and "shield" not in inv:
            return {"name": "craft_item", "arguments": {"item_name": "shield", "count": 1}}

        if inv.get("coal", 0) >= 1 and "torch" not in inv:
            return {"name": "craft_item", "arguments": {"item_name": "torch", "count": 4}}

        if target == "iron_pickaxe":
            if raw_iron < 3 and iron_ingots < 3:
                return {"name": "collect_block", "arguments": {"block_name": "iron", "count": 3}}
            if raw_iron >= 3 and iron_ingots < 3:
                return {
                    "name": "smelt_item",
                    "arguments": {"input_item": "raw_iron", "count": 3}
                }
            return {"name": "craft_item", "arguments": {"item_name": "iron_pickaxe", "count": 1}}

        diamonds = inv.get("diamond", 0)
        if target == "diamond_pickaxe":
            if diamonds < 3:
                return {"name": "collect_block", "arguments": {"block_name": "diamond", "count": 3}}
            return {"name": "craft_item", "arguments": {"item_name": "diamond_pickaxe", "count": 1}}

        # Phase 3: Nether Portal Progression
        if target == "nether_portal":
            if "nether" in dimension:
                return {"name": "attack_target", "arguments": {"target_name": "blaze"}}

            obsidian_count = inv.get("obsidian", 0)
            if obsidian_count < 10:
                return {"name": "collect_block", "arguments": {"block_name": "obsidian", "count": 10 - obsidian_count}}

            has_flint_and_steel = "flint_and_steel" in inv
            if not has_flint_and_steel:
                flint_count = inv.get("flint", 0)
                iron_count = inv.get("iron_ingot", 0)
                if iron_count < 1:
                    raw_iron_count = inv.get("raw_iron", 0) + inv.get("iron_ore", 0)
                    if raw_iron_count >= 1:
                        return {"name": "smelt_item", "arguments": {"input_item": "raw_iron", "count": 1}}
                    return {"name": "collect_block", "arguments": {"block_name": "iron", "count": 1}}
                if flint_count < 1:
                    return {"name": "collect_block", "arguments": {"block_name": "gravel", "count": 3}}
                return {"name": "craft_item", "arguments": {"item_name": "flint_and_steel", "count": 1}}

            return {"name": "build_nether_portal", "arguments": {}}

        # Phase 3: Eye of Ender & Stronghold Tracking
        if target == "eye_of_ender":
            blaze_rods = inv.get("blaze_rod", 0)
            blaze_powders = inv.get("blaze_powder", 0)
            ender_pearls = inv.get("ender_pearl", 0)
            eyes = inv.get("eye_of_ender", 0)

            if eyes >= 12:
                return {"name": "throw_eye_of_ender", "arguments": {}}

            if blaze_rods >= 1 and blaze_powders < 2:
                return {"name": "craft_item", "arguments": {"item_name": "blaze_powder", "count": 2}}

            if blaze_powders >= 1 and ender_pearls >= 1:
                return {"name": "craft_item", "arguments": {"item_name": "eye_of_ender", "count": 1}}

            if ender_pearls < 1:
                return {"name": "attack_target", "arguments": {"target_name": "enderman"}}

            if blaze_rods < 1 and blaze_powders < 1:
                if "nether" in dimension:
                    return {"name": "attack_target", "arguments": {"target_name": "blaze"}}
                return {"name": "build_nether_portal", "arguments": {}}

        # Phase 3: The End & Ender Dragon Slaying
        if target == "ender_dragon":
            if "end" in dimension:
                return {"name": "attack_target", "arguments": {"target_name": "ender_dragon"}}
            vis_res = state.get("visible_resources", {})
            if vis_res.get("end_portal_frame") or inv.get("eye_of_ender", 0) > 0:
                return {"name": "activate_end_portal", "arguments": {}}
            return {"name": "throw_eye_of_ender", "arguments": {}}

        # Default: Oyuncu yanında kal
        return {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
