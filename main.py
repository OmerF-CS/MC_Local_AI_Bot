import asyncio
import os
import subprocess
import signal
import sys
import time
import threading
import argparse
from typing import Optional, Dict, Any, List

from utils.config import Config
from utils.logger import setup_logging, get_logger
from utils.run_context import (
    get_current_run_id,
    set_current_run_id,
    generate_run_id,
    write_run_metadata,
)
from core.database import Database
from core.bridge import MinecraftBridge
from core.chat_handler import MinecraftChatHandler
from ai.ollama_client import OllamaBrain
from ai.planner import AutonomousCoopBrain
from ai.dataset_collector import DatasetCollector

logger = get_logger("Main")


class MinecraftAIBot:
    """Main orchestration class - coordinates bot lifecycle, AI brain, and worker."""
    
    def __init__(self, config: Config):
        self.config = config
        if config.RUN_ID:
            set_current_run_id(config.RUN_ID)
        self.run_id = get_current_run_id()
        self.db = Database(config.DB_PATH)
        is_test_run = self.run_id.startswith("test_")
        self.db.record_run(self.run_id, is_test=is_test_run, model_name=config.OLLAMA_MODEL)
        write_run_metadata(self.run_id, {
            "status": "starting",
            "model_name": config.OLLAMA_MODEL,
            "db_path": config.DB_PATH,
            "is_test": is_test_run,
            "llm_timeouts": 0,
            "fallback_count": 0,
            "llm_tool_call_count": 0,
            "llm_timeout_rate": 0.0
        })

        self.bridge = MinecraftBridge(host=config.BRIDGE_HOST, port=config.BRIDGE_PORT)

        self.brain = OllamaBrain(
            base_url=config.OLLAMA_BASE_URL,
            model=config.OLLAMA_MODEL,
            bot_name=config.BOT_NAME,
            bot_owner=config.BOT_OWNER
        )

        self.planner = AutonomousCoopBrain(self.brain, bot_owner=config.BOT_OWNER, db=self.db)
        self.dataset_collector = DatasetCollector(run_id=self.run_id)
        self.chat_handler = MinecraftChatHandler(self)
        self.node_process: subprocess.Popen | None = None
        self.autonomous_mode = True
        self.active_player_task = None
        self._loop_task: asyncio.Task | None = None
        self._bot_ready = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._loop_wakeup = asyncio.Event()

        # State tracking and corpse recovery guards
        self.last_known_inventory = []
        self.last_known_position = None
        self.last_known_dimension = "overworld"
        self.active_recovery_task_id = None
        self.active_recovery_death_id = None
        self.active_recovery_start_time = 0.0

        # Wire up bridge callbacks
        self.bridge.on_chat_callback = self.chat_handler.handle_chat
        self.bridge.on_spawn_callback = self.on_bot_spawn
        self.bridge.on_respawn_callback = self.on_bot_respawn
        self.bridge.on_death_callback = self.on_bot_death
        self.bridge.on_game_won_callback = self.on_game_won
        self.bridge.on_action_completed_callback = self.on_action_completed
        self.bridge.on_bed_used_callback = self.on_bed_used
        self.bridge.on_chest_used_callback = self.on_chest_used
        self.bridge.on_ore_discovered_callback = self.on_ore_discovered
        self.bridge.on_ore_mined_callback = self.on_ore_mined
        self.bridge.on_bot_disconnected_callback = self.on_bot_disconnected
        
        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, sig, frame):
        """Signal handler for graceful shutdown."""
        logger.warning(f"⚠️ Received signal {sig}. Initiating graceful shutdown...")
        self._shutdown_event.set()

    def _update_last_known_state(self, state: Dict[str, Any]):
        """Caches last known non-empty inventory, coordinates and dimension."""
        if not state or not isinstance(state, dict):
            return
        inv = state.get("inventory")
        if inv and len(inv) > 0:
            self.last_known_inventory = list(inv)
        pos = state.get("position")
        if pos:
            self.last_known_position = dict(pos)
        dim = state.get("dimension")
        if dim:
            self.last_known_dimension = str(dim)

    async def check_and_trigger_corpse_recovery(self, state: Dict[str, Any]):
        """Checks for unrecovered death point with dropped inventory and queues recovery task."""
        if not hasattr(self, "db") or not self.db:
            return

        unrecovered = self.db.get_unrecovered_death_point()
        if not unrecovered:
            return

        death_id = unrecovered.get("id")
        inv = unrecovered.get("inventory", [])
        if not inv or len(inv) == 0:
            # H4: No items to recover, mark recovered so we don't check again
            self.db.mark_death_point_recovered(death_id)
            logger.info(f"🎒 Death point #{death_id} has empty inventory. No corpse recovery needed.")
            return

        cur_dim = state.get("dimension", "overworld") if isinstance(state, dict) else "overworld"
        death_dim = unrecovered.get("dim", "overworld")
        if death_dim != cur_dim:
            logger.info(f"🎒 Death point #{death_id} is in dimension '{death_dim}' (bot is in '{cur_dim}'). Skipping until dimension reached.")
            return

        # Deduplication check: do we already have an active or pending recovery task for this death_id?
        if getattr(self, "active_recovery_death_id", None) == death_id:
            logger.debug(f"🎒 Corpse recovery task already active for death point #{death_id}.")
            return

        # Check existing pending tasks in DB to prevent duplicate task queueing
        pending_tasks = self.db.get_pending_tasks()
        for t in pending_tasks:
            t_args = t.get("args") or {}
            if t.get("primary_action") == "go_to_coordinates" and t_args.get("death_id") == death_id:
                logger.debug(f"🎒 Corpse recovery task already queued for death point #{death_id}.")
                return

        x, y, z = unrecovered["x"], unrecovered["y"], unrecovered["z"]
        logger.warning(
            f"🏃 [Corpse Recovery] Unrecovered death point #{death_id} found at ({x}, {y}, {z}) in {death_dim}! "
            f"Queueing emergency recovery expedition ({len(inv)} item stacks)."
        )
        task_id = self.db.add_task(
            instruction=f"Recover items from death site at ({x}, {y}, {z})",
            primary_action="go_to_coordinates",
            args={"x": x, "y": y, "z": z, "death_id": death_id, "range": 2},
            assigned_by="system",
            priority=10
        )
        self.active_recovery_death_id = death_id
        self.active_recovery_task_id = task_id
        self.active_recovery_start_time = time.time()

    async def on_action_completed(self, cmd: str, success: bool, error: Optional[str], state: Dict[str, Any]):
        """Called when an action finishes execution on Mineflayer."""
        logger.info(f"🏁 Action finished: {cmd} (success={success}, error={error})")
        self._update_last_known_state(state)

        # Check task completion with STRICT correlation
        if self.active_player_task:
            task = self.active_player_task
            task_id = task.get("id")
            primary_action = task.get("primary_action")
            instruction = task.get("instruction", cmd)

            # Strict correlation: only complete active_player_task if cmd matches primary_action!
            if primary_action and cmd != primary_action:
                logger.debug(f"Ignoring action {cmd} for active task #{task_id} expecting {primary_action}")
            else:
                is_recovery_task = (task_id == getattr(self, "active_recovery_task_id", None)) or (
                    task.get("args") and "death_id" in task.get("args")
                )
                if is_recovery_task:
                    # H5: For corpse recovery task, enforce physical proximity (<= 5m), dimension match, and 120s timeout
                    death_id = task.get("args", {}).get("death_id") or getattr(self, "active_recovery_death_id", None)
                    unrecovered = self.db.get_unrecovered_death_point() if self.db else None
                    elapsed = time.time() - getattr(self, "active_recovery_start_time", time.time())
                    
                    cur_pos = state.get("position") if isinstance(state, dict) else None
                    cur_dim = state.get("dimension", "overworld") if isinstance(state, dict) else "overworld"
                    
                    in_range = False
                    if unrecovered and cur_pos:
                        dx = cur_pos.get("x", 0.0) - unrecovered["x"]
                        dz = cur_pos.get("z", 0.0) - unrecovered["z"]
                        dist = (dx * dx + dz * dz) ** 0.5
                        same_dim = (unrecovered.get("dim", "overworld") == cur_dim)
                        in_range = (dist <= 5.0 and same_dim)

                    if in_range:
                        logger.info(f"🎒 Reached death point #{death_id}! Collecting dropped inventory...")
                        await self.bridge.send_action("collect_nearby_drops", {"radius": 32})
                        if self.db and death_id:
                            self.db.mark_death_point_recovered(death_id)
                            self.db.complete_task(task_id)
                        await self.bridge.send_action("say_chat", {
                            "message": "🎒 Arrived at previous death site and recovered dropped items!"
                        })
                        self.active_player_task = None
                        self.active_recovery_task_id = None
                        self.active_recovery_death_id = None
                    elif elapsed > 120.0 or not success:
                        # Timed out (120s) or pathfinding failed
                        logger.warning(f"⚠️ Corpse recovery #{death_id} timed out or failed (elapsed={elapsed:.1f}s, success={success}, error={error})")
                        if self.db and task_id:
                            self.db.update_task_status(task_id, "failed")
                            if death_id:
                                self.db.mark_death_point_recovered(death_id)
                        self.active_player_task = None
                        self.active_recovery_task_id = None
                        self.active_recovery_death_id = None
                    else:
                        logger.warning(f"⚠️ Bot did not reach death point #{death_id} (not within 5m). Leaving task active.")
                else:
                    # Regular player task
                    if success:
                        logger.info(f"✅ Player task completed successfully: '{instruction}'")
                        if self.db and task_id:
                            self.db.complete_task(task_id)
                        await self.bridge.send_action("say_chat", {
                            "message": f"✅ Completed task: '{instruction}'! Ready for next task."
                        })
                    else:
                        logger.warning(f"⚠️ Player task failed or interrupted: '{instruction}' (Error: {error})")
                        if self.db and task_id:
                            self.db.update_task_status(task_id, "failed")
                        await self.bridge.send_action("say_chat", {
                            "message": f"⚠️ Task '{instruction}' had an issue: {error or 'interrupted'}"
                        })
                    self.active_player_task = None

        # Check if bot naturally arrived close to unrecovered corpse during any movement
        if self.db and cmd in ("go_to_coordinates", "walking"):
            unrecovered = self.db.get_unrecovered_death_point()
            if unrecovered and state.get("position"):
                cur_pos = state["position"]
                cur_dim = state.get("dimension", "overworld") if isinstance(state, dict) else "overworld"
                if unrecovered.get("dim", "overworld") == cur_dim:
                    dx = cur_pos.get("x", 0.0) - unrecovered["x"]
                    dz = cur_pos.get("z", 0.0) - unrecovered["z"]
                    dist = (dx * dx + dz * dz) ** 0.5
                    if dist <= 5.0:
                        logger.info(f"🎒 Reached death point #{unrecovered['id']}! Collecting dropped inventory...")
                        await self.bridge.send_action("collect_nearby_drops", {"radius": 32})
                        self.db.mark_death_point_recovered(unrecovered["id"])
                        await self.bridge.send_action("say_chat", {
                            "message": "🎒 Arrived at previous death site and recovered dropped items!"
                        })

        # Check if there are queued pending tasks in SQLite (only if no active task is running)
        if self.db and not self.active_player_task:
            pending = self.db.get_pending_tasks()
            if pending:
                next_task = pending[0]
                self.db.update_task_status(next_task["id"], "active")
                self.active_player_task = next_task
                logger.info(f"📋 Promoted next queued task to active: #{next_task['id']} '{next_task['instruction']}'")
                await self.bridge.send_action("say_chat", {
                    "message": f"📋 Starting next queued task: '{next_task['instruction']}'"
                })
                if next_task.get('primary_action'):
                    task_args = dict(next_task.get('args') or {})
                    if 'instruction' not in task_args:
                        task_args['instruction'] = next_task['instruction']
                    await self.chat_handler._execute_tool(
                        next_task['primary_action'],
                        task_args,
                        state,
                        self.config.BOT_OWNER
                    )

        # Trigger immediate next decision cycle in autonomous loop
        self._loop_wakeup.set()

    async def on_bot_spawn(self, state: Dict[str, Any]):
        """Called when the bot successfully spawns into the world."""
        logger.info(f"✨ {self.config.BOT_NAME} spawned into the world! Health: {state.get('health')}")
        self._bot_ready.set()
        self._update_last_known_state(state)
        await self.bridge.send_action("say_chat", {
            "message": f"Hello {self.config.BOT_OWNER}! I am {self.config.BOT_NAME}, ready to explore and beat the game."
        })
        await self.check_and_trigger_corpse_recovery(state)

    async def on_bot_respawn(self, state: Dict[str, Any]):
        """Called when the bot respawns after death."""
        logger.info(f"🔄 {self.config.BOT_NAME} respawned into the world! Health: {state.get('health')}")
        self._bot_ready.set()
        self._update_last_known_state(state)
        await self.check_and_trigger_corpse_recovery(state)

    async def on_bot_death(self, data):
        """Called when the bot dies in-game."""
        logger.warning("💀 Bot has fallen! Waiting for respawn...")
        self._bot_ready.clear()

        # F0.3: Record death location and inventory snapshot to database for corpse recovery
        death_pos = data.get("death_pos") if isinstance(data, dict) else None
        dim = data.get("dimension", "overworld") if isinstance(data, dict) else "overworld"
        inv_snapshot = data.get("inventory_snapshot", []) if isinstance(data, dict) else []

        # Fallback to cached last known state if empty (H2)
        if not death_pos:
            cached_pos = self.last_known_position or getattr(self.bridge, "last_known_position", None)
            if isinstance(cached_pos, dict):
                death_pos = cached_pos
        if not dim or dim == "overworld":
            cached_dim = self.last_known_dimension or getattr(self.bridge, "last_known_dimension", None)
            if isinstance(cached_dim, str) and cached_dim:
                dim = cached_dim
        if not inv_snapshot:
            cached_inv = self.last_known_inventory or getattr(self.bridge, "last_known_inventory", None)
            if isinstance(cached_inv, list):
                inv_snapshot = cached_inv
            else:
                inv_snapshot = []

        if death_pos and hasattr(self, "db") and self.db:
            death_id = self.db.save_death_point(
                dim=dim,
                x=death_pos.get("x", 0.0),
                y=death_pos.get("y", 0.0),
                z=death_pos.get("z", 0.0),
                inventory=inv_snapshot
            )
            if not inv_snapshot or len(inv_snapshot) == 0:
                # H4: Mark as recovered immediately so no recovery task is ever opened
                self.db.mark_death_point_recovered(death_id)
                logger.info(
                    f"📍 [Death Recovery] Death point #{death_id} recorded with empty inventory. "
                    "Skipping corpse recovery task."
                )
            else:
                logger.warning(
                    f"📍 [Death Recovery] Death point #{death_id} recorded at "
                    f"({death_pos.get('x')}, {death_pos.get('y')}, {death_pos.get('z')}) in {dim} with {len(inv_snapshot)} item stacks!"
                )

    async def on_bot_disconnected(self, reason: str):
        """Called when Mineflayer bot disconnects or is kicked from Minecraft server."""
        logger.warning(
            f"🔌 [Bot Disconnected] Connection lost (reason: {reason}). "
            "Pausing autonomous progression until reconnect..."
        )
        self._bot_ready.clear()
        self.bridge.latest_state = {}

    async def on_bed_used(self, data: Dict[str, Any]):
        """Called when the bot interacts with a bed to sleep or set spawn."""
        bed_pos = data.get("bed_pos")
        dim = data.get("dimension", "overworld")
        if bed_pos and hasattr(self, "db") and self.db:
            self.db.save_bed_location(
                dim=dim,
                x=bed_pos.get("x", 0.0),
                y=bed_pos.get("y", 0.0),
                z=bed_pos.get("z", 0.0),
                is_spawn=True
            )
            logger.info(f"🛏️ [Bed Memory] Recorded spawn bed at ({bed_pos.get('x')}, {bed_pos.get('y')}, {bed_pos.get('z')}) in {dim} to database!")

    async def on_chest_used(self, data: Dict[str, Any]):
        """Called when the bot interacts with a chest to store or withdraw items."""
        chest_pos = data.get("chest_pos")
        dim = data.get("dimension", "overworld")
        items = data.get("items", [])
        if chest_pos and hasattr(self, "db") and self.db:
            self.db.save_chest_location(
                dim=dim,
                x=chest_pos.get("x", 0.0),
                y=chest_pos.get("y", 0.0),
                z=chest_pos.get("z", 0.0),
                items=items
            )
            logger.info(
                f"📦 [Chest Memory] Recorded chest at ({chest_pos.get('x')}, {chest_pos.get('y')}, {chest_pos.get('z')}) "
                f"in {dim} with {len(items)} stored item types!"
            )

    async def on_ore_discovered(self, data: Dict[str, Any]):
        """Called when Mineflayer spots an ore vein."""
        dim = data.get("dim") or data.get("dimension") or "overworld"
        x = data.get("x")
        y = data.get("y")
        z = data.get("z")
        block = data.get("block", "")
        if hasattr(self, "db") and self.db and x is not None and y is not None and z is not None:
            self.db.save_ore(dim, int(x), int(y), int(z), block)
            logger.info(f"💎 [Ore Map] Discovered {block} at ({x}, {y}, {z}) in {dim}!")

    async def on_ore_mined(self, data: Dict[str, Any]):
        """Called when an ore vein block is harvested."""
        dim = data.get("dim") or data.get("dimension") or "overworld"
        x = data.get("x")
        y = data.get("y")
        z = data.get("z")
        if hasattr(self, "db") and self.db and x is not None and y is not None and z is not None:
            self.db.mark_ore_mined(dim, int(x), int(y), int(z))
            logger.info(f"⛏️ [Ore Map] Marked ore at ({x}, {y}, {z}) in {dim} as mined.")

    async def on_game_won(self, data):
        """Called when the Ender Dragon is defeated and the exit portal is entered."""
        logger.info("🎉🏆 [VICTORY EVENT] THE GAME HAS BEEN BEATEN! CONGRATULATIONS! 🏆🎉")
        if hasattr(self, "db") and self.db:
            self.db.save_progression("VICTORY_BEATEN_GAME", "game_completed", {})

    async def wait_for_bot_ready(self, timeout: float = 30.0) -> bool:
        """Wait for the Mineflayer bot to become online and receive its initial state snapshot."""
        # Only accept existing state if worker client is actively connected AND bot_ready is set
        if bool(self.bridge.clients) and self._bot_ready.is_set() and self.bridge.latest_state and self.bridge.latest_state.get("health"):
            logger.info("✅ Bot state already available from active connection, startup complete.")
            return True

        logger.info(f"⏳ Waiting for bot startup ({timeout}s timeout)...")
        start_t = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_t < timeout:
            if bool(self.bridge.clients) and self._bot_ready.is_set() and self.bridge.latest_state and self.bridge.latest_state.get("health"):
                logger.info("✅ Bot spawned and state available, startup complete.")
                return True
            await asyncio.sleep(0.5)

        logger.warning(
            f"⚠️ Bot did not spawn within {timeout}s. "
            "Verify Minecraft server connection. Continuing anyway..."
        )
        return False

    async def autonomous_progression_loop(self):
        """Player-like autonomous decision and action progression loop."""
        logger.info("🌀 Autonomous Co-op Player Engine started.")
        loop_failures = 0
        max_consecutive_failures = 5

        while not self._shutdown_event.is_set():
            try:
                # Do not progress if bot is disconnected or not yet spawned in world
                if not self._bot_ready.is_set():
                    await asyncio.sleep(0.5)
                    continue

                # Fast event-driven wakeup upon action completion, or periodic 0.5s check
                try:
                    await asyncio.wait_for(self._loop_wakeup.wait(), timeout=0.5)
                    self._loop_wakeup.clear()
                except asyncio.TimeoutError:
                    pass

                if not self.autonomous_mode:
                    continue

                state = self.bridge.latest_state
                if not state or not state.get("health"):
                    loop_failures += 1
                    if loop_failures >= max_consecutive_failures:
                        logger.debug(
                            f"Did not receive valid state snapshot {max_consecutive_failures} times. "
                            "Waiting for bot state sync..."
                        )
                        loop_failures = 0
                    continue

                loop_failures = 0

                # Requirement 2: Log real getBotState values once per minute
                now_state_t = time.time()
                if now_state_t - getattr(self, "_last_minute_state_log_time", 0.0) >= 60.0:
                    self._last_minute_state_log_time = now_state_t
                    raw_hp = state.get("health")
                    raw_food = state.get("food")
                    hp_str = f"{raw_hp:.2f}" if isinstance(raw_hp, (int, float)) else "n/a"
                    food_str = f"{raw_food:.1f}" if isinstance(raw_food, (int, float)) else "n/a"
                    pos = state.get("position")
                    pos_str = (
                        f"({pos.get('x', 0):.1f}, {pos.get('y', 0):.1f}, {pos.get('z', 0):.1f})"
                        if isinstance(pos, dict) and "x" in pos
                        else "n/a"
                    )
                    logger.info(
                        f"📊 [getBotState Minute Monitor] timestamp={now_state_t:.0f} | "
                        f"hp={hp_str} | food={food_str} | "
                        f"pos={pos_str} | "
                        f"is_sheltered={state.get('is_sheltered', False)}"
                    )

                if state.get("is_busy", False):
                    continue

                state["active_player_task"] = self.active_player_task
                ai_decision = await self.planner.decide_next_action(state)
                
                if not ai_decision:
                    continue

                response_text = ai_decision.get("text", "")
                tool_calls = ai_decision.get("tool_calls", [])

                if not tool_calls:
                    # No active action to execute (e.g. resting in bunker or waiting)
                    await asyncio.sleep(2.0)
                    continue

                for tc in tool_calls:
                    if self._shutdown_event.is_set():
                        break
                    cmd = tc.get("name")
                    args = tc.get("arguments", {})
                    logger.info(f"⚡ [PROACTIVE INITIATIVE] Action: {cmd} -> {args}")
                    pre_snapshot = dict(state)
                    start_t = time.time()
                    exec_res = await self.chat_handler._execute_tool(cmd, args, state, self.config.BOT_OWNER)
                    dur_s = time.time() - start_t
                    post_snapshot = dict(self.bridge.latest_state or state)
                    self.dataset_collector.record_step(
                        pre_state=pre_snapshot,
                        decision=tc,
                        exec_result=exec_res or {},
                        post_state=post_snapshot,
                        duration_s=dur_s
                    )
                    await asyncio.sleep(0.1)

                has_say_chat = any(tc.get("name") == "say_chat" for tc in tool_calls)
                now = time.time()
                # Rate limit proactive chat so autonomous thoughts don't flood Minecraft chat
                if (
                    response_text
                    and not has_say_chat
                    and response_text != getattr(self, "_last_autonomous_chat_msg", "")
                    and (now - getattr(self, "_last_autonomous_chat_time", 0.0)) >= 15.0
                ):
                    self._last_autonomous_chat_time = now
                    self._last_autonomous_chat_msg = response_text
                    await self.bridge.send_action("say_chat", {"message": response_text})

                await asyncio.sleep(0.3)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Autonomous player loop error: {e}", exc_info=True)
                await asyncio.sleep(2)

        logger.info("🛑 Autonomous progression loop terminated.")

    def start_mineflayer_worker(self):
        """Spawns Mineflayer Node.js bot process as a managed subprocess."""
        self._bot_ready.clear()
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.latest_state = {}

        bot_dir = os.path.join(os.path.dirname(__file__), "minecraft_bot")
        node_modules = os.path.join(bot_dir, "node_modules")

        if not os.path.exists(node_modules):
            logger.warning("⚠️ 'minecraft_bot/node_modules' not found!")
            logger.warning("👉 Please run 'cd minecraft_bot && npm install' first.")
            logger.info("ℹ️ You can also run the worker manually with 'node minecraft_bot/bot.js'.")
            return False

        env = os.environ.copy()
        env["MINECRAFT_HOST"] = self.config.MINECRAFT_HOST
        env["MINECRAFT_PORT"] = str(self.config.MINECRAFT_PORT)
        env["MINECRAFT_USERNAME"] = self.config.MINECRAFT_USERNAME
        env["BOT_OWNER"] = self.config.BOT_OWNER
        if self.config.MINECRAFT_VERSION:
            env["MINECRAFT_VERSION"] = self.config.MINECRAFT_VERSION
        env["BRIDGE_URL"] = f"ws://{self.config.BRIDGE_HOST}:{self.config.BRIDGE_PORT}"
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            logger.info("🚀 Launching Mineflayer Node.js process...")
            self.node_process = subprocess.Popen(
                ["node", "bot.js"],
                cwd=bot_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            logger.info(f"✅ Mineflayer process spawned with PID: {self.node_process.pid}.")
            
            # Spawn real-time log reader thread (avoids blocking asyncio event loop on Windows)
            threading.Thread(target=self._read_subprocess_logs, daemon=True, name="MineflayerLogReader").start()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to launch Mineflayer: {e}")
            return False

    def _read_subprocess_logs(self):
        """Reads and logs Node.js worker output in real time from a dedicated daemon thread."""
        if not self.node_process or not self.node_process.stdout:
            return
        
        try:
            for line in iter(self.node_process.stdout.readline, ""):
                if not line:
                    break
                logger.info(f"[Node.js] {line.rstrip()}")
        except Exception as e:
            logger.debug(f"Subprocess log reader thread terminated: {e}")

    async def run(self):
        """Runs orchestrator lifecycle."""
        logger.info("="*60)
        logger.info(f"🤖 Minecraft Autonomous AI Assistant: {self.config.BOT_NAME}")
        logger.info(f"👑 Owner / Partner: {self.config.BOT_OWNER}")
        logger.info(f"🎮 Target Server: {self.config.MINECRAFT_HOST}:{self.config.MINECRAFT_PORT}")
        logger.info(f"🧠 AI Engine: Ollama ({self.config.OLLAMA_MODEL})")
        logger.info("="*60)

        # 1. Ollama health check
        is_ollama_ready = await self.brain.check_health()
        if not is_ollama_ready:
            logger.warning(
                "⚠️ Ollama does not appear ready. Bot will launch but reasoning may fall back to heuristics. "
                "Ensure Ollama is running: 'ollama serve'"
            )

        # 2. Start WebSocket bridge
        try:
            await self.bridge.start()
        except Exception as e:
            logger.error(f"❌ Failed to start bridge server: {e}")
            return

        # 3. Start Mineflayer worker
        if not self.start_mineflayer_worker():
            logger.warning("⚠️ Mineflayer worker could not auto-start. Start it manually if needed.")

        # 4. Wait for bot spawn
        await self.wait_for_bot_ready(timeout=30)

        # 5. Start autonomous progression loop
        self._loop_task = asyncio.create_task(self.autonomous_progression_loop())

        logger.info("✅ System initialized and ready!")

        # Main supervisor watchdog loop - monitors health and auto-recovers crashes
        consecutive_worker_crashes = 0
        stable_since: Optional[float] = None
        start_time = time.time()
        max_duration = float(os.getenv("MC_MAX_DURATION_SECONDS", "0"))
        try:
            while not self._shutdown_event.is_set():
                if max_duration > 0 and (time.time() - start_time) >= max_duration:
                    logger.info(f"⏱️ [Timer] Reached configured maximum runtime duration ({round(max_duration)}s / {round(max_duration / 60, 1)}m). Initiating clean shutdown...")
                    self._shutdown_event.set()
                    break

                # Check if Mineflayer worker subprocess died unexpectedly
                if self.node_process and self.node_process.poll() is not None:
                    exit_code = self.node_process.poll()
                    consecutive_worker_crashes += 1
                    self._bot_ready.clear()
                    self.bridge.latest_state = {}
                    stable_since = None

                    if consecutive_worker_crashes >= 5:
                        logger.error(
                            f"🚨 [Watchdog] Mineflayer worker crashed {consecutive_worker_crashes} consecutive times. "
                            "Maximum restart attempts (5) reached. Terminating supervisor to prevent infinite restart loop."
                        )
                        self._shutdown_event.set()
                        break

                    backoff = min(15, 2 * consecutive_worker_crashes)
                    logger.warning(
                        f"🚨 [Worker Watchdog] Mineflayer worker terminated unexpectedly (code {exit_code})! "
                        f"Auto-restarting in {backoff}s (attempt {consecutive_worker_crashes}/5)..."
                    )
                    await asyncio.sleep(backoff)
                    if not self._shutdown_event.is_set():
                        if self.start_mineflayer_worker():
                            logger.info("🔄 [Worker Watchdog] Mineflayer worker restarted. Waiting for bot to spawn...")
                            await self.wait_for_bot_ready(timeout=25)
                else:
                    if self._bot_ready.is_set() and bool(self.bridge.clients):
                        if stable_since is None:
                            stable_since = time.time()
                        elif time.time() - stable_since >= 60.0:
                            if consecutive_worker_crashes > 0:
                                logger.info("✅ [Watchdog] Worker connection has been stable for 60s. Resetting crash counter to 0.")
                                consecutive_worker_crashes = 0
                    else:
                        stable_since = None

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Graceful shutdown and resource cleanup."""
        logger.info("\n🛑 Initiating shutdown...")
        self._shutdown_event.set()

        # Cancel autonomous loop
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await asyncio.wait_for(self._loop_task, timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("⚠️ Progression loop task termination timeout")

        # Stop bridge server
        try:
            await self.bridge.stop()
        except Exception as e:
            logger.error(f"Bridge shutdown error: {e}")

        # Close Ollama brain session
        try:
            await self.brain.close()
        except Exception as e:
            logger.debug(f"Brain session close error: {e}")

        # Terminate Node.js process
        if self.node_process:
            try:
                logger.info("Terminating Mineflayer worker process...")
                self.node_process.terminate()
                
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self.node_process.wait),
                        timeout=5
                    )
                    exit_code = self.node_process.poll()
                    logger.info(f"✅ Node.js process terminated cleanly (exit_code={exit_code}).")
                except asyncio.TimeoutError:
                    logger.warning("⏳ Process terminate timeout; sending SIGKILL...")
                    self.node_process.kill()
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(self.node_process.wait),
                            timeout=2
                        )
                    except asyncio.TimeoutError:
                        logger.error("❌ Process could not be forcefully killed!")
            except Exception as e:
                logger.error(f"Subprocess cleanup error: {e}")

        try:
            llm_timeouts = getattr(self.brain, "llm_timeouts", 0)
            fallback_count = getattr(self.planner, "fallback_count", 0) or getattr(self.brain, "fallback_count", 0)
            llm_tool_call_count = getattr(self.brain, "llm_tool_call_count", 0)
            total_llm_calls = getattr(self.brain, "llm_calls_count", 0)
            timeout_rate = round(llm_timeouts / max(1, total_llm_calls), 3) if total_llm_calls > 0 else 0.0

            write_run_metadata(self.run_id, {
                "status": "completed",
                "summary": "Bot shutdown complete cleanly",
                "llm_timeouts": llm_timeouts,
                "fallback_count": fallback_count,
                "llm_tool_call_count": llm_tool_call_count,
                "llm_timeout_rate": timeout_rate
            })
        except Exception as e:
            logger.debug(f"Failed to record final run metadata: {e}")

        logger.info("👋 Bot shutdown complete.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="MC Local AI Bot Orchestrator")
    parser.add_argument("--run-id", type=str, default="", help="Custom run identifier")
    parser.add_argument("--db-path", type=str, default="", help="Custom SQLite database file path")
    parser.add_argument("--test", action="store_true", help="Flag this session as a test run")
    parser.add_argument("--duration-seconds", type=float, default=0.0, help="Maximum execution duration before clean shutdown")
    args, _ = parser.parse_known_args()

    if args.duration_seconds > 0:
        os.environ["MC_MAX_DURATION_SECONDS"] = str(args.duration_seconds)

    if args.run_id:
        os.environ["MC_RUN_ID"] = args.run_id
    elif args.test and not os.getenv("MC_RUN_ID"):
        os.environ["MC_RUN_ID"] = generate_run_id(is_test=True)

    if args.db_path:
        os.environ["MC_DB_PATH"] = args.db_path

    config = Config.load_from_env()
    setup_logging(config)

    missing = config.validate()
    if missing:
        logger.error(
            f"❌ Missing configuration keys: {', '.join(missing)}. "
            "Please check your .env file or copy from .env.example."
        )
        sys.exit(1)

    bot = MinecraftAIBot(config)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("⌨️ Process interrupted by user (Ctrl+C).")
    except Exception as e:
        logger.error(f"❌ Critical runtime error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
