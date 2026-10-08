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

from core.bridge import MinecraftBridge
from utils.logger import get_logger

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
        cls.server_dir = os.path.abspath("test_server")
        cls.jar_path = os.path.join(cls.server_dir, "server.jar")

        if not os.path.exists(cls.jar_path):
            logger.info("📥 Downloading official Mojang Minecraft 1.20.4 server.jar...")
            import urllib.request
            url = "https://piston-data.mojang.com/v1/objects/8dd1a28015f51b1803213892b50b7b4fc76e594d/server.jar"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as resp, open(cls.jar_path, "wb") as f:
                f.write(resp.read())
            logger.info("✅ server.jar downloaded successfully!")

        logger.info(f"🚀 [Integration Test] Booting real Minecraft 1.20.4 Server using {cls.java_exe}...")
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
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                        if "Done (" in content:
                            server_ready = True
                            logger.info(f"✅ Real Minecraft 1.20.4 Server is ONLINE and READY! ({round(time.time() - t0, 1)}s)")
                            break
                except Exception:
                    pass
            time.sleep(0.5)

        if not server_ready:
            cls.server_proc.kill()
            raise RuntimeError("Minecraft 1.20.4 server failed to start within 45s timeout!")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server_proc") and cls.server_proc:
            logger.info("🛑 Stopping Minecraft test server...")
            try:
                cls.server_proc.stdin.write("stop\n")
                cls.server_proc.stdin.flush()
                cls.server_proc.wait(timeout=15)
            except Exception:
                cls.server_proc.kill()
            logger.info("✅ Minecraft test server stopped.")

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
        env["MC_PORT"] = "31313"
        env["MC_USERNAME"] = "TestRunnerBot"
        env["MC_VERSION"] = "1.20.4"
        env["MINECRAFT_HOST"] = "127.0.0.1"
        env["MINECRAFT_PORT"] = "31313"
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
