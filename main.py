import asyncio
import os
import subprocess
import signal
import sys
import time
import threading
from typing import Optional, Dict, Any, List

from utils.config import Config
from utils.logger import setup_logging, get_logger
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
        self.db = Database("minecraft_bot.db")
        self.bridge = MinecraftBridge(host=config.BRIDGE_HOST, port=config.BRIDGE_PORT)

        self.brain = OllamaBrain(
            base_url=config.OLLAMA_BASE_URL,
            model=config.OLLAMA_MODEL,
            bot_name=config.BOT_NAME,
            bot_owner=config.BOT_OWNER
        )

        self.planner = AutonomousCoopBrain(self.brain, bot_owner=config.BOT_OWNER, db=self.db)
        self.dataset_collector = DatasetCollector()
        self.chat_handler = MinecraftChatHandler(self)
        self.node_process: subprocess.Popen | None = None
        self.autonomous_mode = True
        self.active_player_task = None
        self._loop_task: asyncio.Task | None = None
        self._bot_ready = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._loop_wakeup = asyncio.Event()

        # Wire up bridge callbacks
        self.bridge.on_chat_callback = self.chat_handler.handle_chat
        self.bridge.on_spawn_callback = self.on_bot_spawn
        self.bridge.on_death_callback = self.on_bot_death
        self.bridge.on_game_won_callback = self.on_game_won
        self.bridge.on_action_completed_callback = self.on_action_completed
        self.bridge.on_bed_used_callback = self.on_bed_used
        self.bridge.on_chest_used_callback = self.on_chest_used
        self.bridge.on_ore_discovered_callback = self.on_ore_discovered
        self.bridge.on_ore_mined_callback = self.on_ore_mined
        
        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, sig, frame):
        """Signal handler for graceful shutdown."""
        logger.warning(f"⚠️ Received signal {sig}. Initiating graceful shutdown...")
        self._shutdown_event.set()

    async def on_action_completed(self, cmd: str, success: bool, error: Optional[str], state: Dict[str, Any]):
        """Called when an action finishes execution on Mineflayer."""
        logger.info(f"🏁 Action finished: {cmd} (success={success}, error={error})")
        if self.active_player_task:
            task = self.active_player_task
            task_id = task.get("id")
            instruction = task.get("instruction", cmd)
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

        # F0.3: Check if this movement action brought bot close to unrecovered corpse
        if self.db and cmd in ("go_to_coordinates", "walking"):
            unrecovered = self.db.get_unrecovered_death_point()
            if unrecovered and state.get("position"):
                cur_pos = state["position"]
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

        # Check if there are queued pending tasks in SQLite
        if self.db:
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

    async def on_bot_spawn(self, state):
        """Called when the bot successfully spawns into the world."""
        logger.info(f"✨ {self.config.BOT_NAME} spawned into the world! Health: {state.get('health')}")
        self._bot_ready.set()
        await self.bridge.send_action("say_chat", {
            "message": f"Hello {self.config.BOT_OWNER}! I am {self.config.BOT_NAME}, ready to explore and beat the game."
        })

        # F0.3: Check for unrecovered corpse in current dimension
        if hasattr(self, "db") and self.db:
            unrecovered = self.db.get_unrecovered_death_point()
            if unrecovered:
                cur_dim = state.get("dimension", "overworld")
                if unrecovered.get("dim", "overworld") == cur_dim:
                    x, y, z = unrecovered["x"], unrecovered["y"], unrecovered["z"]
                    logger.warning(
                        f"🏃 [Corpse Recovery] Unrecovered death point #{unrecovered['id']} found at ({x}, {y}, {z})! "
                        f"Prioritizing emergency recovery expedition before drops despawn!"
                    )
                    self.db.add_task(
                        instruction=f"Recover items from death site at ({x}, {y}, {z})",
                        primary_action="go_to_coordinates",
                        args={"x": x, "y": y, "z": z},
                        assigned_by="system",
                        priority=10
                    )

    async def on_bot_death(self, data):
        """Called when the bot dies in-game."""
        logger.warning("💀 Bot has fallen! Waiting for respawn...")
        self._bot_ready.clear()

        # F0.3: Record death location and inventory snapshot to database for corpse recovery
        death_pos = data.get("death_pos") if isinstance(data, dict) else None
        dim = data.get("dimension", "overworld") if isinstance(data, dict) else "overworld"
        inv_snapshot = data.get("inventory_snapshot", []) if isinstance(data, dict) else []

        if death_pos and hasattr(self, "db") and self.db:
            death_id = self.db.save_death_point(
                dim=dim,
                x=death_pos.get("x", 0.0),
                y=death_pos.get("y", 0.0),
                z=death_pos.get("z", 0.0),
                inventory=inv_snapshot
            )
            logger.warning(
                f"📍 [Death Recovery] Death point #{death_id} recorded at "
                f"({death_pos.get('x')}, {death_pos.get('y')}, {death_pos.get('z')}) in {dim} with {len(inv_snapshot)} item stacks!"
            )

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
        if self.bridge.latest_state and self.bridge.latest_state.get("health"):
            logger.info("✅ Bot state already available, startup complete.")
            self._bot_ready.set()
            return True

        logger.info(f"⏳ Waiting for bot startup ({timeout}s timeout)...")
        start_t = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_t < timeout:
            if self._bot_ready.is_set() or (self.bridge.latest_state and self.bridge.latest_state.get("health")):
                logger.info("✅ Bot spawned and state available, startup complete.")
                self._bot_ready.set()
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
                # Fast event-driven wakeup upon action completion, or periodic 0.5s check
                try:
                    await asyncio.wait_for(self._loop_wakeup.wait(), timeout=0.5)
                    self._loop_wakeup.clear()
                except asyncio.TimeoutError:
                    pass

                if not self.autonomous_mode:
                    continue

                state = self.bridge.latest_state
                if not state:
                    loop_failures += 1
                    if loop_failures >= max_consecutive_failures:
                        logger.error(
                            f"❌ Did not receive state {max_consecutive_failures} times consecutively. "
                            "Bot connection might be interrupted."
                        )
                        loop_failures = 0
                    continue

                loop_failures = 0

                if state.get("is_busy", False):
                    continue

                state["active_player_task"] = self.active_player_task
                ai_decision = await self.planner.decide_next_action(state)
                
                if not ai_decision:
                    continue

                response_text = ai_decision.get("text", "")
                tool_calls = ai_decision.get("tool_calls", [])

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
                if response_text and not has_say_chat:
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

        try:
            logger.info("🚀 Launching Mineflayer Node.js process...")
            self.node_process = subprocess.Popen(
                ["node", "bot.js"],
                cwd=bot_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
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
        try:
            while not self._shutdown_event.is_set():
                # Check if Mineflayer worker subprocess died unexpectedly
                if self.node_process and self.node_process.poll() is not None:
                    exit_code = self.node_process.poll()
                    consecutive_worker_crashes += 1
                    self._bot_ready.clear()

                    if consecutive_worker_crashes > 5:
                        logger.error("🚨 [Watchdog] Mineflayer worker crashed 5 consecutive times. Terminating.")
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
                    if self._bot_ready.is_set():
                        consecutive_worker_crashes = 0

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
                    logger.info("✅ Node.js process terminated cleanly.")
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

        logger.info("👋 Bot shutdown complete.")


def main():
    """Main entry point."""
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
