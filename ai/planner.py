"""Autonomous Human-like Minecraft Co-op Partner Brain with Complete Tech Tree Reasoning."""
import asyncio
from typing import Dict, Any, List, Optional
from utils.logger import get_logger
from ai.knowledge_base import get_relevant_tactic
from ai.progression_tree import get_current_progression_goal, resolve_missing_ingredients

logger = get_logger("AutonomousCoopBrain")

class AutonomousCoopBrain:
    """Proactive reasoning engine using Ollama and the complete Minecraft progression tech tree."""

    def __init__(self, ollama_brain, bot_owner: str = "Omer"):
        self.brain = ollama_brain
        self.bot_owner = bot_owner
        self.last_action_command = None
        self.consecutive_repeats = 0

    def parse_inventory(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """Converts inventory item objects into an item_name -> count mapping."""
        inv = {}
        for item in items:
            name = item.get("name", "")
            count = item.get("count", 0)
            inv[name] = inv.get(name, 0) + count
        return inv

    async def decide_next_action(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyzes real-time world, player actions, tech tree goals, and executes the optimal tool call."""
        if not state:
            return None

        # If bot is currently executing a physical action, do not interrupt
        if state.get("is_busy", False):
            logger.debug("⏳ Bot is currently busy executing an action. Skipping decision cycle.")
            return None

        items = state.get("inventory_items", [])
        inv_dict = self.parse_inventory(items)

        owner_info = state.get("owner_info")
        health = state.get("health", 20)
        food = state.get("food", 20)
        hearts = round(health / 2, 1)
        pos = state.get("position", {"x": 0, "y": 0, "z": 0})
        inv_summary = state.get("inventory_summary", "Empty")
        
        # Comprehensive entities radar (hostiles, animals, dropped loot, players)
        entities_summary = (
            state.get("nearby_entities_summary") or 
            ", ".join(state.get("nearby_hostiles", [])) or 
            "No entities detected within 32m."
        )

        is_day = state.get("is_day", True)
        time_str = "Daytime (Safe)" if is_day else "Nighttime (Hostile mobs active!)"
        biome = state.get("biome", "Unknown")

        # 1. Progression tech tree milestone
        goal = get_current_progression_goal(inv_dict)
        missing_ingredients = resolve_missing_ingredients(goal["target"], inv_dict)
        missing_str = ", ".join(missing_ingredients) or "All materials ready for crafting!"

        # 2. Expert tactical advice
        pro_tactic = get_relevant_tactic(state)

        # 3. Owner status
        if owner_info:
            dist = owner_info.get("distance", 0)
            held = owner_info.get("held_item", "Empty hand")
            owner_summary = f"{self.bot_owner} is {dist} blocks away, currently holding '{held}'."
        else:
            owner_summary = f"{self.bot_owner} is not currently within line of sight."

        # 4. 3D Vision Field & Spatial Environmental Metrics (64-block radius)
        vision = state.get("vision_metrics", {})
        light = vision.get("light_level", 15)
        light_str = f"Pitch Dark ({light}/15 - Mobs will spawn!)" if light < 6 else f"Lit ({light}/15)"
        altitude_zone = vision.get("altitude_zone", "Surface / Overworld")

        vis_res = state.get("visible_resources", {})
        if vis_res:
            res_items = [f"{name} ({data['total_found']}x total, {data['visible_exposed']} exposed to air, {data['closest_distance']}m away)" for name, data in vis_res.items()]
            vision_summary = ", ".join(res_items)
        else:
            vision_summary = "No key resources detected within 64m."

        carried_tools = state.get("carried_tools", "None")

        # 5. Teammate Directive vs Autonomous Initiative
        active_task = state.get("active_player_task")
        if active_task:
            task_header = f"""🎯 ACTIVE TEAMMATE DIRECTIVE (Assigned by {active_task.get('assigned_by', self.bot_owner)}):
- Instruction: "{active_task.get('instruction')}"
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
- Stone / Cobblestone / Coal Ore: Requires WOODEN PICKAXE or higher! (Bare hands or axes drop 0 items!)
- Iron Ore / Lapis / Copper: Requires STONE PICKAXE or higher! (Wooden pickaxe destroys ore with 0 drops!)
- Gold / Diamond / Redstone: Requires IRON PICKAXE or higher! (Stone pickaxe drops 0 diamonds!)
- Obsidian: Requires DIAMOND PICKAXE or higher!
- Wood / Logs: Harvest with AXE for 4x speed.
- Dirt / Sand / Gravel: Harvest with SHOVEL.
- Your Active Tools: {carried_tools}

🐾 SURROUNDING ENTITIES & THREAT RADAR (32m Scan Radius):
- Detected Entities: {entities_summary}

👁️ 3D ENVIRONMENTAL PERCEPTION & VISION FIELD (64-Block Radius):
- Position: X: {pos.get('x', 0):.1f}, Y: {pos.get('y', 0):.1f}, Z: {pos.get('z', 0):.1f}
- Altitude Zone: {altitude_zone}
- Lighting Level: {light_str}
- Biome: {biome} | Time of Day: {time_str}
- Air-Exposed & Reachable Resources (within 64m): {vision_summary}

👥 TEAM & PARTNER STATUS:
- {owner_summary}

💡 VETERAN TACTICAL TIP:
"{pro_tactic}"

YOUR TASK:
Make a decisive, tactical choice to assist {self.bot_owner} and advance towards defeating the Ender Dragon:
- If active teammate directive is present: focus on fulfilling it!
- If hunger is low (< 16) and you have food: invoke `eat_food`.
- If hunger is low (< 15) and you have NO food in inventory: invoke `hunt_food` to hunt nearby livestock (cows, pigs, sheep, chickens).
- If you have raw meat and fuel: invoke `smelt_item` to cook food.
- If threatened by hostile mobs or {self.bot_owner} in danger: invoke `guard_player` or `attack_target`.
- If {self.bot_owner} has moved far ahead (distance > 16 blocks): invoke `follow_player`.
- If night has fallen and a bed is nearby: invoke `sleep_in_bed`.
- If materials are missing for gear ({missing_str}): invoke `collect_block` or `craft_item`.
- Otherwise: stick close, guard your partner, or mine visible resources.

Decide and invoke a SINGLE appropriate tool call now!"""

        try:
            logger.info(f"🎯 Milestone: {goal['target']} | AI is evaluating tactical action in English...")
            response = await self.brain.process_chat(
                sender="System/Autonomous",
                message=decision_prompt,
                state=state
            )

            # Check if LLM failed to invoke a tool (text-only reply)
            tool_calls = response.get("tool_calls", [])
            if not tool_calls:
                logger.info("ℹ️ LLM produced conversational text without tool calls. Generating tactical progression fallback action.")
                fallback_action = self.generate_fallback_action(goal, inv_dict, owner_info, state)
                if fallback_action:
                    tool_calls = [fallback_action]
                    response["tool_calls"] = tool_calls

            # Prevent infinite loop repetition
            if tool_calls:
                first_cmd = tool_calls[0].get("name")
                if first_cmd == self.last_action_command:
                    self.consecutive_repeats += 1
                    if self.consecutive_repeats >= 3:
                        logger.warning(f"⚠️ [Loop Break] '{first_cmd}' repeated 3 times. Regrouping with partner.")
                        self.consecutive_repeats = 0
                        return {"text": "Regrouping with you!", "tool_calls": [{"name": "follow_player", "arguments": {"player_name": self.bot_owner}}]}
                else:
                    self.consecutive_repeats = 0
                self.last_action_command = first_cmd

            return response
        except Exception as e:
            logger.error(f"❌ Autonomous decision error: {e}")
            return None

    def generate_fallback_action(self, goal: Dict[str, Any], inv: Dict[str, int], owner_info: Optional[Dict[str, Any]], state: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Ensures the bot ALWAYS behaves like an intelligent human player advancing gear and team."""
        if not state:
            state = {}

        # 0. Active Teammate Task Priority
        active_task = state.get("active_player_task")
        if active_task:
            instruction = active_task.get("instruction", "").lower()
            if "guard" in instruction or "koru" in instruction:
                return {"name": "guard_player", "arguments": {"player_name": self.bot_owner}}
            if any(w in instruction for w in ["follow", "gel", "takip", "come"]):
                return {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
            if any(w in instruction for w in ["hunt", "food", "yemek", "avlan", "et"]):
                return {"name": "hunt_food", "arguments": {"animal_type": "any"}}
            if any(w in instruction for w in ["sleep", "bed", "uyu", "yat"]):
                return {"name": "sleep_in_bed", "arguments": {}}

        # 1. Regroup if human teammate is moving too far ahead
        if owner_info and owner_info.get("distance", 0) > 16:
            return {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}

        # 2. Vital hunger reflex
        food_level = state.get("food", 20)
        has_eatable = any(f in inv for f in ["cooked_beef", "cooked_porkchop", "bread", "apple", "cooked_chicken", "cooked_mutton", "baked_potato"])
        if food_level < 15 and has_eatable:
            return {"name": "eat_food", "arguments": {}}

        # 3. Cooking raw meat if low on food and has furnace/fuel
        raw_meats = [m for m in ["raw_beef", "raw_porkchop", "raw_mutton", "raw_chicken", "beef", "porkchop", "mutton", "chicken"] if inv.get(m, 0) > 0]
        has_fuel = inv.get("coal", 0) > 0 or any("log" in i or "plank" in i for i in inv)
        if food_level < 18 and raw_meats and has_fuel:
            return {"name": "smelt_item", "arguments": {"input_item": raw_meats[0], "count": min(inv.get(raw_meats[0], 1), 4)}}

        # 4. Hunting for food if hungry and no food in inventory
        if food_level < 15 and not has_eatable and not raw_meats:
            return {"name": "hunt_food", "arguments": {"animal_type": "any"}}

        # 5. Nighttime sleep reflex
        if not state.get("is_day", True):
            vis_res = state.get("visible_resources", {})
            if vis_res.get("bed"):
                return {"name": "sleep_in_bed", "arguments": {}}

        target = goal.get("target")

        # --- WOOD ERA ---
        log_count = sum(c for i, c in inv.items() if "log" in i or "stem" in i)
        plank_count = sum(c for i, c in inv.items() if "planks" in i)

        if target == "wooden_pickaxe":
            if log_count < 3 and plank_count < 4:
                return {"name": "collect_block", "arguments": {"block_name": "log", "count": 3}}
            return {"name": "craft_item", "arguments": {"item_name": "wooden_pickaxe", "count": 1}}

        # --- STONE & DEEPSLATE ERA ---
        cobble_count = sum(c for i, c in inv.items() if any(s in i for s in ("cobble", "deepslate", "blackstone")))
        if target == "stone_pickaxe":
            if cobble_count < 3:
                return {"name": "collect_block", "arguments": {"block_name": "stone", "count": 3}}
            return {"name": "craft_item", "arguments": {"item_name": "stone_pickaxe", "count": 1}}

        # --- FURNACE & SMELTING ERA ---
        if target == "furnace":
            if cobble_count < 8:
                return {"name": "collect_block", "arguments": {"block_name": "stone", "count": 8}}
            return {"name": "craft_item", "arguments": {"item_name": "furnace", "count": 1}}

        # --- IRON GEAR & SHIELD ERA ---
        raw_iron = inv.get("raw_iron", 0) + inv.get("iron_ore", 0)
        iron_ingots = inv.get("iron_ingot", 0)

        # Proactive shield crafting (massive defense against creepers/skeletons)
        if iron_ingots >= 1 and "shield" not in inv:
            return {"name": "craft_item", "arguments": {"item_name": "shield", "count": 1}}

        # Torches crafting if coal available and no torches
        if inv.get("coal", 0) >= 1 and "torch" not in inv:
            return {"name": "craft_item", "arguments": {"item_name": "torch", "count": 4}}

        if target == "iron_pickaxe":
            if raw_iron < 3 and iron_ingots < 3:
                return {"name": "collect_block", "arguments": {"block_name": "iron", "count": 3}}
            if raw_iron >= 3 and iron_ingots < 3:
                return {"name": "smelt_item", "arguments": {"input_item": "raw_iron", "count": 3}}
            return {"name": "craft_item", "arguments": {"item_name": "iron_pickaxe", "count": 1}}

        # --- DIAMOND ERA ---
        diamonds = inv.get("diamond", 0)
        if target == "diamond_pickaxe":
            if diamonds < 3:
                return {"name": "collect_block", "arguments": {"block_name": "diamond", "count": 3}}
            return {"name": "craft_item", "arguments": {"item_name": "diamond_pickaxe", "count": 1}}

        # Default human teammate stance: stick close and observe
        return {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
