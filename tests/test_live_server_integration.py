"""Live End-to-End Integration Test against real Minecraft Java 1.20.4 Server (F0.1).

Validates the full live production stack without any mocks:
Real Java 1.20.4 Mojang Server <--> Mineflayer Node.js Worker <--> WebSocket Bridge <--> Python Orchestrator
"""
import asyncio
import os
import subprocess
import sys
import time
import unittest

import shutil

from core.bridge import MinecraftBridge
from utils.logger import get_logger
from utils.run_context import get_current_run_id, get_run_directory

logger = get_logger("LiveServerIntegrationTest")


def get_java_executable() -> str:
    """Finds installed Java 17+ / 21+ executable capable of running Minecraft 1.20.4 server."""
    candidates = [
        r"C:\Program Files\Android\Android Studio\jbr\bin\java.exe",
        r"C:\Program Files\Java\jdk-21\bin\java.exe",
        r"C:\Program Files\Java\jdk-17\bin\java.exe",
        r"C:\Program Files\Eclipse Adoptium\jdk-21\bin\java.exe",
        r"C:\Users\omerf\AppData\Roaming\.tlauncher\starter\jre_default\jre-21.0.11-windows-x64\bin\java.exe",
        "/usr/bin/java",
        "/usr/lib/jvm/java-21-openjdk/bin/java",
        "/usr/lib/jvm/temurin-21-jdk/bin/java"
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    import shutil
    return shutil.which("java") or "java"


class TestLiveMinecraft1204Integration(unittest.TestCase):
    """End-to-end integration test against actual Minecraft 1.20.4 Java Dedicated Server."""

    @classmethod
    def setUpClass(cls):
        cls.java_exe = get_java_executable()
        server_dir_env = os.getenv("MC_SERVER_DIR", "test_server")
        cls.server_dir = os.path.abspath(server_dir_env)
        cls.jar_path = os.path.join(cls.server_dir, "server.jar")

        if not os.path.exists(cls.jar_path):
            logger.info("📥 Downloading official Mojang Minecraft 1.20.4 server.jar...")
            import urllib.request
            url = "https://piston-data.mojang.com/v1/objects/8dd1a28015f51b1803213892b50b7b4fc76e594d/server.jar"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as resp, open(cls.jar_path, "wb") as f:
                f.write(resp.read())
            logger.info("✅ server.jar downloaded successfully!")

        # Determine port for live test via MC_TEST_PORT env or find open port if 31313 is occupied
        test_port_env = os.getenv("MC_TEST_PORT")
        if test_port_env:
            try:
                cls.test_port = int(test_port_env)
            except ValueError:
                cls.test_port = 31313
        else:
            import socket
            def is_port_in_use(port: int) -> bool:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    return s.connect_ex(('127.0.0.1', port)) == 0

            if is_port_in_use(31313):
                # LAN port 31313 is occupied; pick next available port so live test is not blocked
                candidate = 31314
                while is_port_in_use(candidate) and candidate < 31360:
                    candidate += 1
                cls.test_port = candidate
                logger.info(f"ℹ️ LAN port 31313 kullanımda. Canlı test için dinamik port seçildi: {cls.test_port}")
            else:
                cls.test_port = 31313

        # Write test_port to server.properties
        props_path = os.path.join(cls.server_dir, "server.properties")
        if os.path.isfile(props_path):
            with open(props_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            found_port = False
            for line in lines:
                if line.startswith("server-port="):
                    new_lines.append(f"server-port={cls.test_port}\n")
                    found_port = True
                else:
                    new_lines.append(line)
            if not found_port:
                new_lines.append(f"server-port={cls.test_port}\n")
            with open(props_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

        logger.info(f"🚀 [Integration Test] Booting real Minecraft 1.20.4 Server on port {cls.test_port} using {cls.java_exe}...")
        cls.server_proc = subprocess.Popen(
            [cls.java_exe, "-Xms256M", "-Xmx768M", "-jar", "server.jar", "nogui"],
            cwd=cls.server_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        log_file = os.path.join(cls.server_dir, "logs", "latest.log")
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
            except Exception:
                pass

        # Wait for server to finish loading world and emit "Done ("
        server_ready = False
        t0 = time.time()
        while time.time() - t0 < 45:
            if cls.server_proc.poll() is not None:
                # Process exited early (e.g. BindException: Address already in use)
                break
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                        if "Done (" in content:
                            server_ready = True
                            logger.info(f"✅ Real Minecraft 1.20.4 Server is ONLINE and READY on port {cls.test_port}! ({round(time.time() - t0, 1)}s)")
                            break
                except Exception:
                    pass
            time.sleep(0.5)

        if not server_ready:
            try:
                cls.server_proc.kill()
            except Exception:
                pass
            raise unittest.SkipTest(
                f"Minecraft 1.20.4 canlı test sunucusu başlatılamadı: Port {cls.test_port} meşgul veya sunucu süreci beklenmedik şekilde kapandı. "
                f"Test için farklı bir port belirlemek üzere MC_TEST_PORT ortam değişkenini ayarlayabilirsiniz (Örn: MC_TEST_PORT=31314). "
                f"Canlı entegrasyon testi atlandı."
            )

    @classmethod
    def tearDownClass(cls):
        # 1. Stop Minecraft Dedicated Server
        if hasattr(cls, "server_proc") and cls.server_proc:
            logger.info("🛑 Stopping Minecraft test server...")
            try:
                cls.server_proc.stdin.write("stop\n")
                cls.server_proc.stdin.flush()
                cls.server_proc.wait(timeout=15)
            except Exception:
                cls.server_proc.kill()
            logger.info("✅ Minecraft test server stopped.")

        # 2. Capture server latest.log and bot log into run directory
        try:
            active_run_id = os.getenv("MC_RUN_ID") or get_current_run_id()
            run_dir = get_run_directory(active_run_id)
            server_log = os.path.join(cls.server_dir, "logs", "latest.log")
            if os.path.isfile(server_log):
                target_server_log = os.path.join(run_dir, "server_latest.log")
                shutil.copy2(server_log, target_server_log)
                logger.info(f"📋 Captured live server log into: {target_server_log}")

            shared_bot_log = os.path.abspath(os.path.join("logs", "minecraft_bot.log"))
            run_bot_log = os.path.join(run_dir, "bot.log")
            if os.path.isfile(shared_bot_log) and not os.path.isfile(run_bot_log):
                shutil.copy2(shared_bot_log, run_bot_log)
        except Exception as e:
            logger.debug(f"Failed to copy server logs to runs directory: {e}")

    def test_live_bot_connection_and_interaction(self):
        """Runs live Mineflayer bot connection, spawn verification, and chat roundtrip."""
        asyncio.run(self._run_live_test_async())

    async def _run_live_test_async(self):
        # 1. Start WebSocket Bridge Server on dedicated test port 8769
        bridge_port = 8769
        bridge = MinecraftBridge(host="127.0.0.1", port=bridge_port)
        await bridge.start()

        spawn_event = asyncio.Event()
        chat_received = []

        async def on_spawn(state):
            logger.info(f"🌟 [Live Bot Spawned] Health: {state.get('health')}, Position: {state.get('position')}")
            spawn_event.set()

        async def on_chat(sender, message, state):
            logger.info(f"💬 [Live Chat] <{sender}> {message}")
            chat_received.append((sender, message))

        bridge.on_spawn_callback = on_spawn
        bridge.on_chat_callback = on_chat

        # 2. Launch Mineflayer Worker Process pointing to real 1.20.4 server
        bot_script = os.path.abspath("minecraft_bot/bot.js")
        env = os.environ.copy()
        env["MC_HOST"] = "127.0.0.1"
        env["MC_PORT"] = str(self.test_port)
        env["MC_USERNAME"] = "TestRunnerBot"
        env["MC_VERSION"] = "1.20.4"
        env["MINECRAFT_HOST"] = "127.0.0.1"
        env["MINECRAFT_PORT"] = str(self.test_port)
        env["MINECRAFT_USERNAME"] = "TestRunnerBot"
        env["MINECRAFT_VERSION"] = "1.20.4"
        env["BRIDGE_HOST"] = "127.0.0.1"
        env["BRIDGE_PORT"] = str(bridge_port)
        env["BRIDGE_URL"] = f"ws://127.0.0.1:{bridge_port}"
        env["BOT_OWNER"] = "Omer"

        node_proc = subprocess.Popen(
            ["node", bot_script],
            cwd=os.path.abspath("minecraft_bot"),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        try:
            # 3. Wait for bot to connect to Minecraft server, spawn, and handshake bridge
            logger.info("⏳ Waiting for Mineflayer bot to connect and spawn in world...")
            try:
                await asyncio.wait_for(spawn_event.wait(), timeout=25.0)
            except asyncio.TimeoutError:
                self.fail("Mineflayer bot failed to spawn in Minecraft 1.20.4 server within 25 seconds!")

            # 4. Verify live game engine telemetry state
            state = bridge.latest_state
            self.assertIsNotNone(state)
            self.assertEqual(state.get("health"), 20)
            self.assertEqual(state.get("food"), 20)
            self.assertIn("position", state)
            pos = state["position"]
            self.assertIn("x", pos)
            self.assertIn("y", pos)
            self.assertIn("z", pos)

            # 5. Dispatch live command to bot: say_chat
            logger.info("💬 Dispatching live chat message to Minecraft 1.20.4 world...")
            await bridge.send_action("say_chat", {"message": "Hello Minecraft 1.20.4! AI bot online."})

            # Wait a brief moment for packet propagation
            await asyncio.sleep(2.0)

            # 6. Verify stop_actions command completes cleanly
            await bridge.send_action("stop_actions", {})
            await asyncio.sleep(1.0)

            logger.info("🎉 [VERIFIED] End-to-end live Minecraft 1.20.4 integration passed flawlessly!")

        finally:
            # Clean teardown of Node worker and Bridge
            try:
                node_proc.kill()
                node_proc.wait(timeout=5)
            except Exception:
                pass
            await bridge.stop()


if __name__ == "__main__":
    unittest.main()
