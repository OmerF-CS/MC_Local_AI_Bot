"""Minecraft Otonom AI Asistanı ve Oyun Bitirme Orkestratörü."""
import asyncio
import os
import subprocess
import sys
import signal

from utils.config import Config
from utils.logger import setup_logging, get_logger
from core.database import Database
from core.bridge import MinecraftBridge
from core.chat_handler import MinecraftChatHandler
from ai.ollama_client import OllamaBrain
from ai.planner import AutonomousCoopBrain

logger = get_logger("Main")

class MinecraftAIBot:
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
        
        self.planner = AutonomousCoopBrain(self.brain, bot_owner=config.BOT_OWNER)
        self.chat_handler = MinecraftChatHandler(self)
        self.node_process: subprocess.Popen = None
        self.autonomous_mode = True  # Always active by default!
        self.active_player_task = None
        self._loop_task: asyncio.Task = None

        # Köprü Callback'lerini Bağla
        self.bridge.on_chat_callback = self.chat_handler.handle_chat
        self.bridge.on_spawn_callback = self.on_bot_spawn
        self.bridge.on_death_callback = self.on_bot_death

    async def on_bot_spawn(self, state):
        """Invoked when the bot connects or respawns."""
        logger.info(f"✨ {self.config.BOT_NAME} spawned into the world! Health: {state.get('health')}")
        await self.bridge.send_action("say_chat", {
            "message": f"Hello {self.config.BOT_OWNER}! I am {self.config.BOT_NAME}, ready to explore and beat the game."
        })

    async def on_bot_death(self, state):
        """Invoked when the bot dies."""
        logger.warning("💀 Bot has fallen! Waiting for respawn...")

    async def autonomous_progression_loop(self):
        """Player-like proactive autonomous thought and action loop."""
        logger.info("🌀 Autonomous Co-op Player Engine started.")
        while True:
            try:
                # Fast reactive tick: check every 2 seconds
                await asyncio.sleep(2)
                if not self.autonomous_mode:
                    continue

                state = self.bridge.latest_state
                if not state:
                    continue

                # If bot is currently executing a physical action (walking, mining, crafting), wait
                if state.get("is_busy", False):
                    continue

                # Inject active teammate mission if assigned
                state["active_player_task"] = self.active_player_task

                # Evaluate next player-like proactive decision
                ai_decision = await self.planner.decide_next_action(state)
                if not ai_decision:
                    continue

                response_text = ai_decision.get("text", "")
                tool_calls = ai_decision.get("tool_calls", [])

                # 1. Execute actions
                for tc in tool_calls:
                    cmd = tc.get("name")
                    args = tc.get("arguments", {})
                    logger.info(f"⚡ [PROACTIVE INITIATIVE] Action: {cmd} -> {args}")
                    await self.chat_handler._execute_tool(cmd, args, state, self.config.BOT_OWNER)
                    await asyncio.sleep(0.5)

                # 2. Communicate decisions in natural co-op partner style
                has_say_chat = any(tc.get("name") == "say_chat" for tc in tool_calls)
                if response_text and not has_say_chat:
                    await self.bridge.send_action("say_chat", {"message": response_text})

                # Brief cooldown between initiatives to keep natural player pacing
                await asyncio.sleep(2.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Autonomous player loop error: {e}", exc_info=True)

    def start_mineflayer_worker(self):
        """Mineflayer Node.js bot sürecini alt süreç (subprocess) olarak başlatır."""
        bot_dir = os.path.join(os.path.dirname(__file__), "minecraft_bot")
        node_modules = os.path.join(bot_dir, "node_modules")

        if not os.path.exists(node_modules):
            logger.warning("⚠️ 'minecraft_bot/node_modules' bulunamadı!")
            logger.warning("👉 Lütfen önce 'cd minecraft_bot && npm install' komutunu çalıştırın.")
            logger.info("ℹ️ Node.js botunu manuel olarak da 'node minecraft_bot/bot.js' ile başlatabilirsiniz.")
            return

        env = os.environ.copy()
        env["MINECRAFT_HOST"] = self.config.MINECRAFT_HOST
        env["MINECRAFT_PORT"] = str(self.config.MINECRAFT_PORT)
        env["MINECRAFT_USERNAME"] = self.config.MINECRAFT_USERNAME
        env["BOT_OWNER"] = self.config.BOT_OWNER
        if self.config.MINECRAFT_VERSION:
            env["MINECRAFT_VERSION"] = self.config.MINECRAFT_VERSION
        env["BRIDGE_URL"] = f"ws://{self.config.BRIDGE_HOST}:{self.config.BRIDGE_PORT}"

        try:
            logger.info("🚀 Mineflayer Node.js süreci başlatılıyor...")
            self.node_process = subprocess.Popen(
                ["node", "bot.js"],
                cwd=bot_dir,
                env=env
            )
            logger.info(f"✅ Mineflayer süreci PID: {self.node_process.pid} ile başlatıldı.")
        except Exception as e:
            logger.error(f"❌ Mineflayer başlatılamadı: {e}")

    async def run(self):
        """Orkestratörü çalıştırır."""
        logger.info("==================================================")
        logger.info(f"🤖 Minecraft Otonom AI Asistanı: {self.config.BOT_NAME}")
        logger.info(f"👑 Sahip: {self.config.BOT_OWNER}")
        logger.info(f"🎮 Hedef Sunucu: {self.config.MINECRAFT_HOST}:{self.config.MINECRAFT_PORT}")
        logger.info(f"🧠 AI Motoru: Ollama ({self.config.OLLAMA_MODEL})")
        logger.info("==================================================")

        # 1. Ollama Sağlık Kontrolü
        is_ollama_ready = await self.brain.check_health()
        if not is_ollama_ready:
            logger.warning("⚠️ Ollama hazır görünmüyor. Bot yine de açılacak ancak yanıt vermeyebilir.")

        # 2. WebSocket Köprüsünü Başlat
        await self.bridge.start()

        # 3. Mineflayer Worker'ı Başlat (Varsa)
        self.start_mineflayer_worker()

        # 4. Otonom İlerleme Arka Plan Görevini Başlat
        self._loop_task = asyncio.create_task(self.autonomous_progression_loop())

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Kapanış temizliği."""
        logger.info("🛑 Kapatılıyor...")
        if self._loop_task:
            self._loop_task.cancel()
        if self.node_process:
            self.node_process.terminate()
        await self.bridge.stop()
        logger.info("👋 Bot güvenle sonlandırıldı.")

def main():
    config = Config.load_from_env()
    setup_logging(config)

    missing = config.validate()
    if missing:
        logger.error(f"❌ Eksik yapılandırma: {', '.join(missing)}. Lütfen .env dosyasını kontrol edin.")
        return

    bot = MinecraftAIBot(config)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("İşlem kullanıcı tarafından durduruldu.")

if __name__ == "__main__":
    main()
