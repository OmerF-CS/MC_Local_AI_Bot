"""Minecraft Chat and Action Dispatcher in English with Full Encyclopedia Lookup."""
import asyncio
import time
from typing import Dict, Any, Optional

from utils.logger import get_logger
from ai.minecraft_registry import lookup_component_data

logger = get_logger("MinecraftChatHandler")

class MinecraftChatHandler:
    def __init__(self, bot):
        self.bot = bot
        self.last_response_time = 0.0

    async def handle_chat(self, sender: str, message: str, state: Dict[str, Any]):
        """Processes incoming in-game chat and orchestrates the Ollama brain."""
        if sender == self.bot.config.BOT_NAME or sender == self.bot.config.MINECRAFT_USERNAME:
            return

        clean_message = message.strip()
        if not clean_message:
            return

        # Store in database
        if hasattr(self.bot, "db"):
            self.bot.db.log_chat(sender, clean_message, role="player")
            self.bot.db.update_player(sender)

        bot_name_lower = self.bot.config.BOT_NAME.lower()
        is_owner = (sender.lower() == self.bot.config.BOT_OWNER.lower())
        is_mentioned = bot_name_lower in clean_message.lower()
        is_command = clean_message.startswith("!")

        should_respond = is_owner or is_mentioned or is_command

        if not should_respond:
            logger.debug(f"Chat ignored (not targeted): [{sender}] {clean_message}")
            return

        msg_lower = clean_message.lower()

        # Autonomous Speedrun Mode Toggles (English & Turkish aliases)
        if any(w in msg_lower for w in ["beat the game", "beat game", "start auto", "autonomous on", "play solo", "advance", "start", "oyunu bitir", "otonom mod aç"]):
            self.bot.autonomous_mode = True
            msg = "🚀 Autonomous Speedrun Mode ACTIVATED! Analyzing tech tree and advancing through stages."
            await self.bot.bridge.send_action("say_chat", {"message": msg})
            return

        if any(w in msg_lower for w in ["stop auto", "autonomous off", "halt auto", "otonom dur", "otonom mod kapat"]):
            self.bot.autonomous_mode = False
            msg = "🛑 Autonomous mode stopped. Standing by for your instructions."
            await self.bot.bridge.send_action("say_chat", {"message": msg})
            return

        # Stop / Cancellation / Teammate Task Resumption
        if any(w in msg_lower for w in ["stop actions", "cancel task", "stop task", "dur", "iptal", "tamam", "thanks", "devam et", "resume", "carry on", "never mind"]):
            self.bot.active_player_task = None
            await self.bot.bridge.send_action("stop_actions", {})
            msg = "Understood! Resuming my own progression and gear upgrades."
            await self.bot.bridge.send_action("say_chat", {"message": msg})
            return

        # Direct Shortcut Commands (Instant 0ms latency, bypasses LLM cooldown)
        if clean_message.startswith("!"):
            cmd_parts = clean_message[1:].strip().split()
            if cmd_parts:
                cmd_name = cmd_parts[0].lower()
                cmd_args = cmd_parts[1:]

                if cmd_name in ("mine", "collect"):
                    block = cmd_args[0] if cmd_args else "stone"
                    count = int(cmd_args[1]) if len(cmd_args) > 1 and cmd_args[1].isdigit() else 3
                    self.bot.active_player_task = {"instruction": clean_message, "assigned_by": sender, "status": "active", "timestamp": time.time(), "primary_action": "collect_block"}
                    await self.bot.bridge.send_action("collect_block", {"block_name": block, "count": count})
                    return

                elif cmd_name == "craft":
                    item = cmd_args[0] if cmd_args else "crafting_table"
                    count = int(cmd_args[1]) if len(cmd_args) > 1 and cmd_args[1].isdigit() else 1
                    self.bot.active_player_task = {"instruction": clean_message, "assigned_by": sender, "status": "active", "timestamp": time.time(), "primary_action": "craft_item"}
                    await self.bot.bridge.send_action("craft_item", {"item_name": item, "count": count})
                    return

                elif cmd_name == "smelt":
                    item = cmd_args[0] if cmd_args else "raw_iron"
                    count = int(cmd_args[1]) if len(cmd_args) > 1 and cmd_args[1].isdigit() else 1
                    self.bot.active_player_task = {"instruction": clean_message, "assigned_by": sender, "status": "active", "timestamp": time.time(), "primary_action": "smelt_item"}
                    await self.bot.bridge.send_action("smelt_item", {"input_item": item, "count": count})
                    return

                elif cmd_name == "hunt":
                    animal = cmd_args[0] if cmd_args else "any"
                    self.bot.active_player_task = {"instruction": clean_message, "assigned_by": sender, "status": "active", "timestamp": time.time(), "primary_action": "hunt_food"}
                    await self.bot.bridge.send_action("hunt_food", {"animal_type": animal})
                    return

                elif cmd_name in ("follow", "come"):
                    target = cmd_args[0] if cmd_args else sender
                    self.bot.active_player_task = {"instruction": clean_message, "assigned_by": sender, "status": "active", "timestamp": time.time(), "primary_action": "follow_player"}
                    await self.bot.bridge.send_action("follow_player", {"player_name": target})
                    return

                elif cmd_name == "guard":
                    target = cmd_args[0] if cmd_args else sender
                    self.bot.active_player_task = {"instruction": clean_message, "assigned_by": sender, "status": "active", "timestamp": time.time(), "primary_action": "guard_player"}
                    await self.bot.bridge.send_action("guard_player", {"player_name": target})
                    return

                elif cmd_name in ("sleep", "bed"):
                    await self.bot.bridge.send_action("sleep_in_bed", {})
                    return

                elif cmd_name == "stop":
                    self.bot.active_player_task = None
                    await self.bot.bridge.send_action("stop_actions", {})
                    await self.bot.bridge.send_action("say_chat", {"message": "Stopped actions. Standing by."})
                    return

                elif cmd_name == "status":
                    hp = state.get("health", 20)
                    fd = state.get("food", 20)
                    inv = state.get("inventory_summary", "Empty")
                    pos = state.get("position", {})
                    msg = f"HP: {hp}/20 | Food: {fd}/20 | Pos: ({pos.get('x',0):.0f}, {pos.get('y',0):.0f}, {pos.get('z',0):.0f}) | Inv: {inv[:60]}"
                    await self.bot.bridge.send_action("say_chat", {"message": msg})
                    return

        # Cooldown guard
        now = time.time()
        if now - self.last_response_time < self.bot.config.COOLDOWN_SECONDS:
            logger.info("⏱️ Cooldown active, message skipped.")
            return

        self.last_response_time = now
        logger.info(f"🧠 AI Reasoning... [{sender}]: {clean_message}")

        # Process through Ollama
        ai_response = await self.bot.brain.process_chat(
            sender=sender,
            message=clean_message,
            state=state
        )

        response_text = ai_response.get("text", "")
        tool_calls = ai_response.get("tool_calls", [])

        # Track active teammate task if player assigned a concrete physical action
        action_tools = {"collect_block", "craft_item", "guard_player", "follow_player", "hunt_food", "smelt_item", "go_to_coordinates", "go_to_saved_location", "attack_target"}
        assigned_actions = [tc for tc in tool_calls if tc.get("name") in action_tools]
        if assigned_actions:
            self.bot.active_player_task = {
                "instruction": clean_message,
                "assigned_by": sender,
                "status": "active",
                "timestamp": now,
                "primary_action": assigned_actions[0].get("name")
            }
            logger.info(f"📋 Set Active Teammate Task: '{clean_message}' ({assigned_actions[0].get('name')})")

        # Execute actions
        for tc in tool_calls:
            cmd = tc.get("name")
            args = tc.get("arguments", {})
            logger.info(f"⚡ Executing Action: {cmd} -> {args}")
            await self._execute_tool(cmd, args, state, sender)
            await asyncio.sleep(0.5)

        # Output chat message if not already done via say_chat tool
        has_say_chat = any(tc.get("name") == "say_chat" for tc in tool_calls)
        if response_text and not has_say_chat:
            await self.bot.bridge.send_action("say_chat", {"message": response_text})

        if hasattr(self.bot, "db") and response_text:
            self.bot.db.log_chat(self.bot.config.BOT_NAME, response_text, role="assistant")

    async def _execute_tool(self, cmd: str, args: Dict[str, Any], state: Dict[str, Any], sender: str):
        """Dispatches Python-level memory actions or forwards commands to Mineflayer."""
        
        # 1. Save landmark location
        if cmd == "save_current_location":
            loc_name = args.get("location_name", "").lower()
            desc = args.get("description", "")
            pos = state.get("position", {})
            x = pos.get("x", 0)
            y = pos.get("y", 0)
            z = pos.get("z", 0)

            self.bot.db.save_location(loc_name, x, y, z, desc, created_by=sender)
            msg = f"Saved '{loc_name}' to world memory at ({x}, {y}, {z})!"
            await self.bot.bridge.send_action("say_chat", {"message": msg})

        # 2. Return to saved location
        elif cmd == "go_to_saved_location":
            loc_name = args.get("location_name", "").lower()
            saved = self.bot.db.get_location(loc_name)
            if saved:
                msg = f"Heading to '{loc_name}' at ({saved['x']}, {saved['y']}, {saved['z']})."
                await self.bot.bridge.send_action("say_chat", {"message": msg})
                await self.bot.bridge.send_action("go_to_coordinates", {
                    "x": saved["x"],
                    "y": saved["y"],
                    "z": saved["z"]
                })
            else:
                msg = f"I do not have '{loc_name}' saved in memory."
                await self.bot.bridge.send_action("say_chat", {"message": msg})

        # 3. List landmarks
        elif cmd == "list_saved_locations":
            locations = self.bot.db.list_locations()
            if locations:
                loc_list_str = ", ".join([f"{l['name']} ({l['x']}, {l['y']}, {l['z']})" for l in locations])
                msg = f"Saved Landmarks: {loc_list_str}"
            else:
                msg = "No landmarks saved in memory yet."
            await self.bot.bridge.send_action("say_chat", {"message": msg})

        # 4. Comprehensive Encyclopedia Lookup
        elif cmd in ("lookup_recipe", "explain_component"):
            item_name = args.get("item_name") or args.get("component_name", "")
            summary = lookup_component_data(item_name)
            await self.bot.bridge.send_action("say_chat", {"message": summary})

        # 5. Native Mineflayer actions (craft, collect, pvp, follow, etc.)
        else:
            await self.bot.bridge.send_action(cmd, args)
