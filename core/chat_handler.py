"""Minecraft Chat ve Action Dispatcher - Production hardened emergency handling."""
import asyncio
import time
from typing import Dict, Any

from utils.logger import get_logger
from ai.minecraft_registry import lookup_component_data

logger = get_logger("MinecraftChatHandler")


class MinecraftChatHandler:
    """Oyuncu chat'ini işle ve AI beynine yönlendir."""
    
    def __init__(self, bot):
        self.bot = bot
        self.last_response_time = 0.0

    async def handle_chat(self, sender: str, message: str, state: Dict[str, Any]):
        """Gelen chat mesajını işle ve Ollama beynini orkestre et."""
        if sender == self.bot.config.BOT_NAME or sender == self.bot.config.MINECRAFT_USERNAME:
            return

        clean_message = message.strip()
        if not clean_message:
            return

        # Database'e kaydet
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

        # OTONOM MOD AÇMA
        if any(
            w in msg_lower for w in [
                "beat the game", "beat game", "start auto", "autonomous on",
                "play solo", "advance", "start", "oyunu bitir", "otonom mod aç"
            ]
        ):
            self.bot.autonomous_mode = True
            msg = "🚀 Autonomous Speedrun Mode ACTIVATED! Analyzing tech tree and advancing through stages."
            await self.bot.bridge.send_action("say_chat", {"message": msg})
            return

        # OTONOM MOD KAPATMA
        if any(
            w in msg_lower for w in [
                "stop auto", "autonomous off", "halt auto", "otonom dur", "otonom mod kapat"
            ]
        ):
            self.bot.autonomous_mode = False
            msg = "🛑 Autonomous mode stopped. Standing by for your instructions."
            await self.bot.bridge.send_action("say_chat", {"message": msg})
            return

        # STOP ACTIONS - ACIL KOMUT (Cooldown bypass)
        if any(
            w in msg_lower for w in [
                "stop actions", "cancel task", "stop task", "dur", "iptal",
                "tamam", "thanks", "devam et", "resume", "carry on", "never mind",
                "stop", "cancel", "halt"
            ]
        ):
            self.bot.active_player_task = None
            if hasattr(self.bot, "db"):
                self.bot.db.clear_pending_tasks()
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
                    if hasattr(self.bot, "db"):
                        self.bot.db.clear_pending_tasks()
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

        # ACIL KOMUTLAR COOLDOWN'U BYPASS EDER
        critical_words = ["stop", "cancel", "halt", "emergency", "danger", "help", "save", "hurry"]
        is_critical = any(w in msg_lower for w in critical_words)
        now = time.time()
        if not is_critical and now - self.last_response_time < self.bot.config.COOLDOWN_SECONDS:
            logger.info(
                f"⏱️ Cooldown aktif ({self.bot.config.COOLDOWN_SECONDS}s). "
                f"Message atlandı. (Acil komutlar bypass eder)"
            )
            return

        self.last_response_time = now
        logger.info(f"🧠 AI Reasoning... [{sender}]: {clean_message}")

        # AI'ya sor
        ai_response = await self.bot.brain.process_chat(
            sender=sender,
            message=clean_message,
            state=state
        )

        response_text = ai_response.get("text", "")
        tool_calls = ai_response.get("tool_calls", [])

        # Oyuncu konkreter bir aksiyon verdiyse, bunu track et
        action_tools = {
            "collect_block", "craft_item", "guard_player", "follow_player",
            "hunt_food", "smelt_item", "go_to_coordinates",
            "go_to_saved_location", "attack_target", "eat_food"
        }
        assigned_actions = [tc for tc in tool_calls if tc.get("name") in action_tools]
        if assigned_actions:
            primary_act = assigned_actions[0].get("name", "co-op task")
            self.bot.active_player_task = {
                "instruction": clean_message,
                "assigned_by": sender,
                "status": "active",
                "timestamp": now,
                "primary_action": primary_act
            }
            if hasattr(self.bot, "db"):
                self.bot.db.add_task(clean_message, primary_act, sender)
            logger.info(
                f"📋 Set Active Teammate Task: '{clean_message}' "
                f"({primary_act})"
            )

        # Eylemleri execute et
        for tc in tool_calls:
            cmd = tc.get("name")
            args = tc.get("arguments", {})
            logger.info(f"⚡ Executing Action: {cmd} -> {args}")
            await self._execute_tool(cmd, args, state, sender)
            await asyncio.sleep(0.5)

        # Response text'i output et (varsa say_chat halihazırda yapılmamışsa)
        has_say_chat = any(tc.get("name") == "say_chat" for tc in tool_calls)
        if response_text and not has_say_chat:
            await self.bot.bridge.send_action("say_chat", {"message": response_text})

        # AI yanıtını database'e kaydet
        if hasattr(self.bot, "db") and response_text:
            self.bot.db.log_chat(self.bot.config.BOT_NAME, response_text, role="assistant")

    async def _execute_tool(self, cmd: str, args: Dict[str, Any], state: Dict[str, Any], sender: str) -> Dict[str, Any]:
        """Python-level memory actions veya Mineflayer commands'ı doğrula ve dispatch et."""
        if not args:
            args = {}

        # 1. Bellek ve Bilgi Araçları
        if cmd == "save_current_location":
            loc_name = str(args.get("location_name", "")).strip().lower()
            if not loc_name:
                logger.warning("⚠️ 'save_current_location' called without location_name.")
                return {"success": False, "error": "Missing location_name"}
            desc = str(args.get("description", ""))
            pos = state.get("position", {})
            x = pos.get("x", 0)
            y = pos.get("y", 0)
            z = pos.get("z", 0)

            if hasattr(self.bot, "db"):
                self.bot.db.save_location(loc_name, x, y, z, desc, created_by=sender)
            msg = f"Saved '{loc_name}' to world memory at ({x:.0f}, {y:.0f}, {z:.0f})!"
            await self.bot.bridge.send_action("say_chat", {"message": msg})
            return {"success": True, "message": msg}

        elif cmd == "go_to_saved_location":
            loc_name = str(args.get("location_name", "")).strip().lower()
            if not loc_name:
                return {"success": False, "error": "Missing location_name"}
            saved = self.bot.db.get_location(loc_name) if hasattr(self.bot, "db") else None
            if saved:
                msg = f"Heading to '{loc_name}' at ({saved['x']:.0f}, {saved['y']:.0f}, {saved['z']:.0f})."
                await self.bot.bridge.send_action("say_chat", {"message": msg})
                await self.bot.bridge.send_action("go_to_coordinates", {
                    "x": saved["x"],
                    "y": saved["y"],
                    "z": saved["z"]
                })
                return {"success": True, "message": msg}
            else:
                msg = f"I do not have '{loc_name}' saved in memory."
                await self.bot.bridge.send_action("say_chat", {"message": msg})
                return {"success": False, "error": msg}

        elif cmd == "list_saved_locations":
            locations = self.bot.db.list_locations() if hasattr(self.bot, "db") else []
            if locations:
                loc_list_str = ", ".join(
                    [f"{l['name']} ({l['x']:.0f}, {l['y']:.0f}, {l['z']:.0f})" for l in locations]
                )
                msg = f"Saved Landmarks: {loc_list_str}"
            else:
                msg = "No landmarks saved in memory yet."
            await self.bot.bridge.send_action("say_chat", {"message": msg})
            return {"success": True, "message": msg}

        elif cmd in ("lookup_recipe", "explain_component"):
            item_name = str(args.get("item_name") or args.get("component_name", "")).strip()
            summary = lookup_component_data(item_name)
            await self.bot.bridge.send_action("say_chat", {"message": summary})
            return {"success": True, "message": summary}

        # 2. Mineflayer Eylem Komutlarının Şema Doğrulaması
        validated_args = dict(args)
        if cmd == "craft_item":
            item = str(validated_args.get("item_name", "")).strip().lower()
            if not item:
                logger.warning("⚠️ 'craft_item' called without item_name.")
                return {"success": False, "error": "Missing item_name"}
            validated_args["item_name"] = item
            count = validated_args.get("count", 1)
            validated_args["count"] = max(1, int(count) if isinstance(count, (int, str)) and str(count).isdigit() else 1)

        elif cmd == "collect_block":
            block = str(validated_args.get("block_name", "")).strip().lower()
            if not block:
                logger.warning("⚠️ 'collect_block' called without block_name.")
                return {"success": False, "error": "Missing block_name"}
            validated_args["block_name"] = block
            count = validated_args.get("count", 1)
            validated_args["count"] = max(1, int(count) if isinstance(count, (int, str)) and str(count).isdigit() else 1)

        elif cmd == "smelt_item":
            item = str(validated_args.get("input_item", "")).strip().lower()
            if not item:
                logger.warning("⚠️ 'smelt_item' called without input_item.")
                return {"success": False, "error": "Missing input_item"}
            validated_args["input_item"] = item
            count = validated_args.get("count", 1)
            validated_args["count"] = max(1, int(count) if isinstance(count, (int, str)) and str(count).isdigit() else 1)

        elif cmd == "go_to_coordinates":
            try:
                validated_args["x"] = float(validated_args["x"])
                validated_args["y"] = float(validated_args["y"])
                validated_args["z"] = float(validated_args["z"])
            except (KeyError, ValueError, TypeError) as err:
                logger.warning(f"⚠️ 'go_to_coordinates' invalid coordinates: {err}")
                return {"success": False, "error": f"Invalid coordinates: {err}"}

        elif cmd == "hunt_food":
            animal = str(validated_args.get("animal_type", "any")).strip().lower()
            validated_args["animal_type"] = animal or "any"

        elif cmd in ("follow_player", "guard_player"):
            player = str(validated_args.get("player_name", sender)).strip()
            validated_args["player_name"] = player or sender

        # 3. Mineflayer'a İlet
        await self.bot.bridge.send_action(cmd, validated_args)
        return {"success": True, "command": cmd, "args": validated_args}
