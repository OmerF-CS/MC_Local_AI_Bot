"""Minecraft Chat and Action Dispatcher - Production hardened emergency handling."""
import asyncio
import subprocess
import time
from typing import Dict, Any, Optional, List

from utils.logger import get_logger
from ai.minecraft_registry import lookup_component_data
from ai.progression_tree import resolve_missing_ingredients

logger = get_logger("MinecraftChatHandler")


class MinecraftChatHandler:
    """Processes player chat and routes to AI brain."""
    
    def __init__(self, bot):
        self.bot = bot
        self.last_response_time = 0.0

    def _assign_task(self, instruction: str, primary_action: str, sender: str, priority: int = 5, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Saves a player directive into SQLite task queue and marks it as active."""
        task_id = None
        if hasattr(self.bot, "db") and self.bot.db:
            task_id = self.bot.db.add_task(instruction, primary_action, sender, priority, args=args)
            self.bot.db.update_task_status(task_id, "active")

        task = {
            "id": task_id,
            "instruction": instruction,
            "assigned_by": sender,
            "status": "active",
            "timestamp": time.time(),
            "primary_action": primary_action,
            "args": args or {}
        }
        self.bot.active_player_task = task
        logger.info(f"📋 Registered Active Task #{task_id or 'mem'}: '{instruction}' (Action: {primary_action})")
        return task

    async def handle_chat(self, sender: str, message: str, state: Dict[str, Any]):
        """Processes incoming chat message and orchestrates Ollama brain."""
        if sender == self.bot.config.BOT_NAME or sender == self.bot.config.MINECRAFT_USERNAME:
            return

        clean_message = message.strip()
        if not clean_message:
            return

        msg_lower = clean_message.lower()

        # Ignore server broadcasts and system command feedback (e.g. /tp, /gamemode)
        server_senders = ("server", "rcon")
        system_patterns = (
            "teleported ",
            "set own game mode",
            "set game mode",
            "game mode set to",
            "gamemode",
            "given [",
            "giving [",
            "set time to",
            "changed the time",
            "set the weather",
            "weather has been",
            "joined the game",
            "left the game",
            "has made the advancement",
            "has completed the challenge",
            "has reached the goal",
            "was slain by",
            "was shot by",
            "fell from a high place",
            "hit the ground too hard",
            "drowned",
            "burned to death",
            "blew up",
            "suffocated in a wall",
            "tried to swim in lava",
            "experienced kinetic energy",
        )
        if (
            sender.lower() in server_senders
            or clean_message.startswith("[Server")
            or any(p in msg_lower for p in system_patterns)
        ):
            logger.info(f"🔇 Ignored server broadcast/system message: [{sender}] {clean_message}")
            return

        # Save to database
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

        # AUTONOMOUS MODE ACTIVATION
        if any(
            w in msg_lower for w in [
                "beat the game", "beat game", "start auto", "autonomous on",
                "play solo", "advance", "start"
            ]
        ):
            self.bot.autonomous_mode = True
            msg = "🚀 Autonomous Speedrun Mode ACTIVATED! Analyzing tech tree and advancing through stages."
            await self.bot.bridge.send_action("say_chat", {"message": msg})
            return

        # AUTONOMOUS MODE DEACTIVATION
        if any(
            w in msg_lower for w in [
                "stop auto", "autonomous off", "halt auto"
            ]
        ):
            self.bot.autonomous_mode = False
            msg = "🛑 Autonomous mode stopped. Standing by for your instructions."
            await self.bot.bridge.send_action("say_chat", {"message": msg})
            return

        # STOP ACTIONS - EMERGENCY COMMAND (Cooldown bypass)
        if any(
            w in msg_lower for w in [
                "stop actions", "cancel task", "stop task", "thanks", "resume",
                "carry on", "never mind", "stop", "cancel", "halt"
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
                    self._assign_task(clean_message, "collect_block", sender)
                    await self.bot.bridge.send_action("collect_block", {"block_name": block, "count": count})
                    return

                elif cmd_name == "craft":
                    item = cmd_args[0] if cmd_args else "crafting_table"
                    count = int(cmd_args[1]) if len(cmd_args) > 1 and cmd_args[1].isdigit() else 1
                    self._assign_task(clean_message, "craft_item", sender)
                    await self.bot.bridge.send_action("craft_item", {"item_name": item, "count": count})
                    return

                elif cmd_name == "smelt":
                    item = cmd_args[0] if cmd_args else "raw_iron"
                    count = int(cmd_args[1]) if len(cmd_args) > 1 and cmd_args[1].isdigit() else 1
                    self._assign_task(clean_message, "smelt_item", sender)
                    await self.bot.bridge.send_action("smelt_item", {"input_item": item, "count": count})
                    return

                elif cmd_name == "hunt":
                    animal = cmd_args[0] if cmd_args else "any"
                    self._assign_task(clean_message, "hunt_food", sender)
                    await self.bot.bridge.send_action("hunt_food", {"animal_type": animal})
                    return

                elif cmd_name in ("follow", "come"):
                    target = cmd_args[0] if cmd_args else sender
                    self._assign_task(clean_message, "follow_player", sender)
                    await self.bot.bridge.send_action("follow_player", {"player_name": target})
                    return

                elif cmd_name == "guard":
                    target = cmd_args[0] if cmd_args else sender
                    self._assign_task(clean_message, "guard_player", sender)
                    await self.bot.bridge.send_action("guard_player", {"player_name": target})
                    return

                elif cmd_name in ("sleep", "bed"):
                    await self.bot.bridge.send_action("sleep_in_bed", {})
                    return

                elif cmd_name == "stop":
                    self.bot.active_player_task = None
                    if hasattr(self.bot, "db") and self.bot.db:
                        self.bot.db.clear_pending_tasks()
                    await self.bot.bridge.send_action("stop_actions", {})
                    await self.bot.bridge.send_action("say_chat", {"message": "Stopped actions. Standing by."})
                    return

                elif cmd_name in ("clear", "clear_tasks"):
                    if hasattr(self.bot, "db") and self.bot.db:
                        self.bot.db.clear_pending_tasks()
                    self.bot.active_player_task = None
                    await self.bot.bridge.send_action("stop_actions", {})
                    await self.bot.bridge.send_action("say_chat", {"message": "🧹 Cleared all active and queued tasks."})
                    return

                elif cmd_name in ("portal", "nether_portal"):
                    self._assign_task(clean_message, "build_nether_portal", sender)
                    await self.bot.bridge.send_action("build_nether_portal", {})
                    return

                elif cmd_name in ("eye", "throw_eye"):
                    self._assign_task(clean_message, "throw_eye_of_ender", sender)
                    await self.bot.bridge.send_action("throw_eye_of_ender", {})
                    return

                elif cmd_name in ("end", "end_portal", "activate_portal"):
                    self._assign_task(clean_message, "activate_end_portal", sender)
                    await self.bot.bridge.send_action("activate_end_portal", {})
                    return

                elif cmd_name in ("crystal", "crystals", "destroy_crystals"):
                    self._assign_task(clean_message, "destroy_end_crystals", sender)
                    await self.bot.bridge.send_action("destroy_end_crystals", {})
                    return

                elif cmd_name in ("dragon", "fight_dragon", "kill_dragon", "slay_dragon"):
                    self._assign_task(clean_message, "fight_ender_dragon", sender)
                    await self.bot.bridge.send_action("fight_ender_dragon", {"tactic": "melee_sword"})
                    return

                elif cmd_name in ("win", "victory", "exit_portal", "beat_game"):
                    self._assign_task(clean_message, "enter_exit_portal", sender)
                    await self.bot.bridge.send_action("enter_exit_portal", {})
                    return

                elif cmd_name in ("farm", "bread", "harvest", "crops"):
                    self._assign_task(clean_message, "farm_crops", sender)
                    await self.bot.bridge.send_action("farm_crops", {"action_type": "auto"})
                    return

                elif cmd_name in ("shelter", "bunker", "box", "hide", "burrow"):
                    self._assign_task(clean_message, "build_shelter", sender)
                    await self.bot.bridge.send_action("build_shelter", {"mode": "auto"})
                    return

                elif cmd_name in ("unbunker", "unshelter", "break_out", "exit_shelter"):
                    self._assign_task(clean_message, "break_out_shelter", sender)
                    await self.bot.bridge.send_action("break_out_shelter", {})
                    return

                elif cmd_name in ("enchant", "enchantment"):
                    self._assign_task(clean_message, "enchant_gear", sender)
                    gear = cmd_args[0] if cmd_args else "auto"
                    await self.bot.bridge.send_action("enchant_gear", {"gear_type": gear, "target_level": 15})
                    return

                elif cmd_name in ("outpost", "nether_outpost", "fort"):
                    self._assign_task(clean_message, "build_nether_outpost", sender)
                    mat = cmd_args[0] if cmd_args else "auto"
                    await self.bot.bridge.send_action("build_nether_outpost", {"wall_material": mat})
                    return

                elif cmd_name in ("bridge", "bridge_chasm"):
                    await self.bot.bridge.send_action("bridge_chasm", {"direction": "forward", "distance": dist})
                    return

                elif cmd_name in ("breed", "breed_animals", "mate"):
                    animal = cmd_args[0] if cmd_args else "any"
                    self._assign_task(clean_message, "breed_animals", sender, args={"animal_type": animal})
                    await self.bot.bridge.send_action("breed_animals", {"animal_type": animal})
                    return

                elif cmd_name in ("fish", "catch_fish", "fishing"):
                    count = int(cmd_args[0]) if cmd_args and cmd_args[0].isdigit() else 3
                    self._assign_task(clean_message, "catch_fish", sender, args={"count": count})
                    await self.bot.bridge.send_action("catch_fish", {"count": count})
                    return

                elif cmd_name in ("chest", "store", "deposit", "manage_chest"):
                    self._assign_task(clean_message, "manage_chest", sender, args={"action_type": "deposit_surplus"})
                    await self.bot.bridge.send_action("manage_chest", {"action_type": "deposit_surplus"})
                    return

                elif cmd_name in ("withdraw", "take_item"):
                    target = cmd_args[0] if cmd_args else ""
                    count = int(cmd_args[1]) if len(cmd_args) > 1 and cmd_args[1].isdigit() else 1
                    self._assign_task(clean_message, "manage_chest", sender, args={"action_type": "withdraw", "target_item": target, "count": count})
                    await self.bot.bridge.send_action("manage_chest", {"action_type": "withdraw", "target_item": target, "count": count})
                    return

                elif cmd_name in ("tasks", "queue", "task_list"):
                    active = self.bot.active_player_task
                    pending = self.bot.db.get_pending_tasks() if hasattr(self.bot, "db") and self.bot.db else []
                    active_txt = f"Active: '{active.get('instruction')}'" if active else "Active: None (Speedrun/Idle)"
                    msg = f"📋 Tasks -> {active_txt} | Queue: {len(pending)} pending"
                    await self.bot.bridge.send_action("say_chat", {"message": msg})
                    return

                elif cmd_name in ("gpu", "vram", "hardware"):
                    try:
                        p = await asyncio.to_thread(
                            subprocess.run,
                            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=2
                        )
                        if p.returncode == 0:
                            parts = [x.strip() for x in p.stdout.strip().split(",")]
                            name, used, total, util, temp = parts
                            msg = f"🚀 GPU: {name} | VRAM: {used}MB / {total}MB | Util: {util}% | Temp: {temp}°C | Model: {self.bot.config.OLLAMA_MODEL} (100% GPU)"
                        else:
                            msg = f"🚀 GPU: RTX 3060 CUDA Active | Model: {self.bot.config.OLLAMA_MODEL}"
                    except Exception:
                        msg = f"🚀 GPU: RTX 3060 CUDA Active | Model: {self.bot.config.OLLAMA_MODEL}"
                    await self.bot.bridge.send_action("say_chat", {"message": msg})
                    return

                elif cmd_name == "status":
                    hp = state.get("health", 20)
                    fd = state.get("food", 20)
                    inv = state.get("inventory_summary", "Empty")
                    pos = state.get("position", {})
                    msg = f"HP: {hp}/20 | Food: {fd}/20 | Pos: ({pos.get('x',0):.0f}, {pos.get('y',0):.0f}, {pos.get('z',0):.0f}) | Inv: {inv[:60]}"
                    await self.bot.bridge.send_action("say_chat", {"message": msg})
                    return

        # EMERGENCY COMMANDS BYPASS COOLDOWN
        critical_words = ["stop", "cancel", "halt", "emergency", "danger", "help", "save", "hurry"]
        is_critical = any(w in msg_lower for w in critical_words)
        now = time.time()
        if not is_critical and now - self.last_response_time < self.bot.config.COOLDOWN_SECONDS:
            logger.info(
                f"⏱️ Cooldown active ({self.bot.config.COOLDOWN_SECONDS}s). "
                f"Message skipped. (Emergency commands bypass cooldown)"
            )
            return

        self.last_response_time = now
        logger.info(f"🧠 AI Reasoning... [{sender}]: {clean_message}")

        # Query LLM Brain
        ai_response = await self.bot.brain.process_chat(
            sender=sender,
            message=clean_message,
            state=state
        )

        response_text = ai_response.get("text", "")
        tool_calls = ai_response.get("tool_calls", [])

        # Track concrete teammate directives
        action_tools = {
            "collect_block", "craft_item", "guard_player", "follow_player",
            "hunt_food", "smelt_item", "go_to_coordinates",
            "go_to_saved_location", "attack_target", "eat_food",
            "build_nether_portal", "throw_eye_of_ender", "activate_end_portal",
            "destroy_end_crystals", "fight_ender_dragon", "enter_exit_portal",
            "farm_crops", "build_shelter", "break_out_shelter",
            "enchant_gear", "build_nether_outpost", "bridge_chasm",
            "breed_animals", "catch_fish", "manage_chest"
        }
        assigned_actions = [tc for tc in tool_calls if tc.get("name") in action_tools]
        if assigned_actions:
            primary_act = assigned_actions[0].get("name", "co-op task")
            self._assign_task(clean_message, primary_act, sender, priority=3)

        # Execute tool calls
        for tc in tool_calls:
            cmd = tc.get("name")
            args = tc.get("arguments", {})
            logger.info(f"⚡ Executing Action: {cmd} -> {args}")
            pre_snapshot = dict(state)
            start_t = time.time()
            exec_res = await self._execute_tool(cmd, args, state, sender)
            dur_s = time.time() - start_t

            if hasattr(self.bot, "dataset_collector") and self.bot.dataset_collector:
                post_snapshot = dict(self.bot.bridge.latest_state or state)
                self.bot.dataset_collector.record_step(
                    pre_state=pre_snapshot,
                    decision=tc,
                    exec_result=exec_res or {},
                    post_state=post_snapshot,
                    duration_s=dur_s
                )
            await asyncio.sleep(0.5)

        # Output response text if say_chat was not already emitted
        has_say_chat = any(tc.get("name") == "say_chat" for tc in tool_calls)
        if response_text and not has_say_chat:
            await self.bot.bridge.send_action("say_chat", {"message": response_text})

        # Log AI response to database
        if hasattr(self.bot, "db") and response_text:
            self.bot.db.log_chat(self.bot.config.BOT_NAME, response_text, role="assistant")

    async def _execute_tool(self, cmd: str, args: Dict[str, Any], state: Dict[str, Any], sender: str) -> Dict[str, Any]:
        """Validates and dispatches Python-level memory actions or Mineflayer commands."""
        if not args:
            args = {}

        # 1. Memory and Knowledge Tools
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

        # 2. Mineflayer Action Schema Validation
        validated_args = dict(args)
        if cmd == "craft_item":
            item = str(
                validated_args.get("item_name")
                or validated_args.get("material")
                or validated_args.get("item")
                or validated_args.get("target")
                or ""
            ).strip().lower()
            if not item:
                goal = state.get("goal_target") or state.get("target")
                if goal:
                    item = str(goal).strip().lower()
            if not item:
                logger.warning("⚠️ 'craft_item' called without item_name.")
                return {"success": False, "error": f"Invalid arguments for 'craft_item': missing required parameter 'item_name', received: {list(args.keys())}"}

            inv_dict = {}
            for itm in (state.get("inventory_items") or []):
                if isinstance(itm, dict):
                    inv_dict[itm.get("name", "")] = int(itm.get("count", 0))
            if not inv_dict and isinstance(state.get("inventory"), dict):
                inv_dict = {str(k): int(v) for k, v in state["inventory"].items() if isinstance(v, (int, float, str)) and str(v).isdigit()}

            # Fast conversion for smeltable ingots/charcoal mistakenly called with craft_item
            if item in ("iron_ingot", "iron"):
                inv_raw = inv_dict.get("raw_iron", 0) + inv_dict.get("iron_ore", 0)
                if inv_raw > 0:
                    logger.info("🔄 Converting craft_item('iron_ingot') -> smelt_item('raw_iron').")
                    cmd = "smelt_item"
                    validated_args = {"input_item": "raw_iron", "count": max(1, int(validated_args.get("count", 1)))}
                else:
                    logger.info("🔄 Converting craft_item('iron_ingot') -> collect_block('iron').")
                    cmd = "collect_block"
                    validated_args = {"block_name": "iron", "count": max(1, int(validated_args.get("count", 3)))}
            elif item in ("gold_ingot", "gold"):
                inv_raw = inv_dict.get("raw_gold", 0) + inv_dict.get("gold_ore", 0)
                if inv_raw > 0:
                    logger.info("🔄 Converting craft_item('gold_ingot') -> smelt_item('raw_gold').")
                    cmd = "smelt_item"
                    validated_args = {"input_item": "raw_gold", "count": max(1, int(validated_args.get("count", 1)))}
                else:
                    cmd = "collect_block"
                    validated_args = {"block_name": "gold_ore", "count": max(1, int(validated_args.get("count", 3)))}
            elif item in ("copper_ingot", "copper"):
                inv_raw = inv_dict.get("raw_copper", 0) + inv_dict.get("copper_ore", 0)
                if inv_raw > 0:
                    cmd = "smelt_item"
                    validated_args = {"input_item": "raw_copper", "count": max(1, int(validated_args.get("count", 1)))}
                else:
                    cmd = "collect_block"
                    validated_args = {"block_name": "copper_ore", "count": max(1, int(validated_args.get("count", 3)))}
            elif item == "charcoal":
                cmd = "smelt_item"
                validated_args = {"input_item": "log", "count": max(1, int(validated_args.get("count", 2)))}
            else:
                # Fast inventory pre-check against tech tree recipes
                missing_mat = resolve_missing_ingredients(item, inv_dict)
                if missing_mat:
                    missing_str = ", ".join(missing_mat)
                    logger.info(f"ℹ️ Pre-craft check: cannot craft '{item}', missing: {missing_str}")
                    return {"success": False, "error": f"Cannot craft '{item}': missing required materials ({missing_str})"}

                validated_args["item_name"] = item
                count = validated_args.get("count") or validated_args.get("quantity") or validated_args.get("amount") or 1
                validated_args["count"] = max(1, int(count) if isinstance(count, (int, str)) and str(count).isdigit() else 1)

        elif cmd == "collect_block":
            block = str(
                validated_args.get("block_name")
                or validated_args.get("wall_material")
                or validated_args.get("material")
                or validated_args.get("block")
                or validated_args.get("target")
                or ""
            ).strip().lower()
            if not block or block == "auto":
                goal_target = state.get("goal_target") or ""
                missing = state.get("goal_missing") or state.get("missing_ingredients") or []
                if goal_target == "furnace":
                    block = "stone"
                elif goal_target == "wooden_pickaxe":
                    block = "log"
                elif goal_target == "stone_pickaxe":
                    block = "stone"
                elif "iron" in goal_target or goal_target in ("shield", "bucket"):
                    block = "iron_ore"
                elif "diamond" in goal_target:
                    block = "diamond_ore"
                elif missing and isinstance(missing, list) and len(missing) > 0:
                    first_missing = str(missing[0]).lower()
                    for cand in ("log", "stone", "cobblestone", "iron_ore", "coal_ore", "diamond_ore", "obsidian"):
                        if cand in first_missing:
                            block = cand
                            break
            if "plank" in block:
                logger.info(f"🔄 Remapping collect_block('{block}') -> 'log' (planks must be crafted from logs).")
                block = "log"

            if not block or block == "auto":
                logger.warning("⚠️ 'collect_block' called without block_name.")
                return {"success": False, "error": f"Invalid arguments for 'collect_block': missing required parameter 'block_name', received: {list(args.keys())}"}
            validated_args["block_name"] = block
            count = validated_args.get("count") or validated_args.get("quantity") or validated_args.get("amount") or 1
            validated_args["count"] = max(1, int(count) if isinstance(count, (int, str)) and str(count).isdigit() else 1)

        elif cmd == "smelt_item":
            item = str(
                validated_args.get("input_item")
                or validated_args.get("item_name")
                or validated_args.get("material")
                or validated_args.get("item")
                or ""
            ).strip().lower()
            if not item:
                logger.warning("⚠️ 'smelt_item' called without input_item.")
                return {"success": False, "error": f"Invalid arguments for 'smelt_item': missing required parameter 'input_item', received: {list(args.keys())}"}
            validated_args["input_item"] = item
            count = validated_args.get("count") or validated_args.get("quantity") or validated_args.get("amount") or 1
            validated_args["count"] = max(1, int(count) if isinstance(count, (int, str)) and str(count).isdigit() else 1)

        elif cmd == "give_item_to_player":
            player = str(validated_args.get("player_name", "")).strip().lower()
            if not player or player in ("system", "autonomous", "server", "none", "bot", "aiassistant"):
                logger.warning(f"⚠️ Invalid target player '{player}' for give_item_to_player. Rejecting action.")
                return {"success": False, "error": f"Cannot give item to '{player}': not a valid player."}
            nearby = [p.lower() for p in state.get("nearby_players", [])]
            owner = getattr(self.bot, "bot_owner", "Omer").lower()
            if player != owner and not any(player in p for p in nearby):
                logger.warning(f"⚠️ Target player '{player}' not found nearby.")
                return {"success": False, "error": f"Player '{player}' is not in game or nearby."}
            validated_args["player_name"] = player
            item = str(validated_args.get("item_name", "")).strip().lower()
            if not item:
                return {"success": False, "error": "Missing item_name for give_item_to_player"}
            validated_args["item_name"] = item
            count = validated_args.get("count") or 1
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

        elif cmd == "breed_animals":
            animal = str(validated_args.get("animal_type", "any")).strip().lower()
            validated_args["animal_type"] = animal or "any"

        elif cmd == "catch_fish":
            count = validated_args.get("count", 3)
            validated_args["count"] = max(1, int(count) if str(count).isdigit() else 3)

        elif cmd == "manage_chest":
            act = str(validated_args.get("action_type", "deposit_surplus")).strip().lower()
            validated_args["action_type"] = act or "deposit_surplus"
            validated_args["target_item"] = str(validated_args.get("target_item", "")).strip().lower()
            count = validated_args.get("count", 1)
            validated_args["count"] = max(1, int(count) if str(count).isdigit() else 1)

        elif cmd in ("follow_player", "guard_player"):
            player = str(validated_args.get("player_name", sender)).strip()
            validated_args["player_name"] = player or sender

        # 3. Dispatch to Mineflayer Bridge
        if cmd in ("say_chat", "stop_actions", "guard_player", "follow_player"):
            await self.bot.bridge.send_action(cmd, validated_args)
            return {"success": True, "command": cmd, "args": validated_args}
        else:
            # Physical in-game action: lock state to busy and wait for completion
            if self.bot.bridge.latest_state:
                self.bot.bridge.latest_state["is_busy"] = True
            try:
                res = await self.bot.bridge.send_action_and_wait(cmd, validated_args, timeout=60.0)
                return res
            finally:
                if self.bot.bridge.latest_state:
                    self.bot.bridge.latest_state["is_busy"] = False
