"""Minecraft Otonom AI Asistanı ve Oyun Bitirme Orkestratörü - Production Hardened."""
import asyncio
import os
import subprocess
import signal
import sys

from utils.config import Config
from utils.logger import setup_logging, get_logger
from core.database import Database
from core.bridge import MinecraftBridge
from core.chat_handler import MinecraftChatHandler
from ai.ollama_client import OllamaBrain
from ai.planner import AutonomousCoopBrain

logger = get_logger("Main")


class MinecraftAIBot:
    """Ana orkestrasyon sınıfı - bot lifecycle ve koordinasyon."""
    
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
        self.chat_handler = MinecraftChatHandler(self)
        self.node_process: subprocess.Popen | None = None
        self.autonomous_mode = True
        self.active_player_task = None
        self._loop_task: asyncio.Task | None = None
        self._bot_ready = asyncio.Event()
        self._shutdown_event = asyncio.Event()

        # Köprü Callback'lerini Bağla
        self.bridge.on_chat_callback = self.chat_handler.handle_chat
        self.bridge.on_spawn_callback = self.on_bot_spawn
        self.bridge.on_death_callback = self.on_bot_death
        
        # Signal handler'ları
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, sig, frame):
        """Graceful shutdown için signal handler."""
        logger.warning(f"⚠️ Signal {sig} alındı. Kapanış başlatılıyor...")
        self._shutdown_event.set()

    async def on_bot_spawn(self, state):
        """Bot başarıyla spawn olduğunda çağrılır."""
        logger.info(f"✨ {self.config.BOT_NAME} spawned into the world! Health: {state.get('health')}")
        self._bot_ready.set()
        await self.bridge.send_action("say_chat", {
            "message": f"Hello {self.config.BOT_OWNER}! I am {self.config.BOT_NAME}, ready to explore and beat the game."
        })

    async def on_bot_death(self, state):
        """Bot öldüğünde çağrılır."""
        logger.warning("💀 Bot has fallen! Waiting for respawn...")
        self._bot_ready.clear()

    async def wait_for_bot_ready(self, timeout: float = 30.0) -> bool:
        """Mineflayer botunun online olmasını ve ilk durum snapshots'ını bekle."""
        if self.bridge.latest_state and self.bridge.latest_state.get("health"):
            logger.info("✅ Bot durumu zaten mevcut, startup tamamlandı.")
            self._bot_ready.set()
            return True

        logger.info(f"⏳ Bot startup'ını bekliyorum ({timeout}s timeout)...")
        try:
            await asyncio.wait_for(self._bot_ready.wait(), timeout=timeout)
            logger.info("✅ Bot başarıyla spawn oldu, otonom döngü başlıyor.")
            return True
        except asyncio.TimeoutError:
            logger.warning(
                f"⚠️ Bot {timeout}s içinde spawn olmadı. "
                "Sunucu bağlantısını kontrol edin. Yine de devam ediyorum..."
            )
            return False

    async def autonomous_progression_loop(self):
        """Oyuncu-benzeri otonom karar ve aksiyon döngüsü."""
        logger.info("🌀 Autonomous Co-op Player Engine başlatıldı.")
        loop_failures = 0
        max_consecutive_failures = 5

        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(2)

                if not self.autonomous_mode:
                    continue

                state = self.bridge.latest_state
                if not state:
                    loop_failures += 1
                    if loop_failures >= max_consecutive_failures:
                        logger.error(
                            f"❌ {max_consecutive_failures} kez state alamadım. "
                            "Bot muhtemelen bağlantı kopmuş."
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
                    await self.chat_handler._execute_tool(cmd, args, state, self.config.BOT_OWNER)
                    await asyncio.sleep(0.5)

                has_say_chat = any(tc.get("name") == "say_chat" for tc in tool_calls)
                if response_text and not has_say_chat:
                    await self.bridge.send_action("say_chat", {"message": response_text})

                await asyncio.sleep(2.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Autonomous player loop error: {e}", exc_info=True)
                await asyncio.sleep(2)

        logger.info("🛑 Autonomous progression loop sonlandırıldı.")

    def start_mineflayer_worker(self):
        """Mineflayer Node.js bot sürecini subprocess olarak başlat."""
        bot_dir = os.path.join(os.path.dirname(__file__), "minecraft_bot")
        node_modules = os.path.join(bot_dir, "node_modules")

        if not os.path.exists(node_modules):
            logger.warning("⚠️ 'minecraft_bot/node_modules' bulunamadı!")
            logger.warning("👉 Lütfen önce 'cd minecraft_bot && npm install' komutunu çalıştırın.")
            logger.info("ℹ️ Node.js botunu manuel olarak da 'node minecraft_bot/bot.js' ile başlatabilirsiniz.")
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
            logger.info("🚀 Mineflayer Node.js süreci başlatılıyor...")
            self.node_process = subprocess.Popen(
                ["node", "bot.js"],
                cwd=bot_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            logger.info(f"✅ Mineflayer süreci PID: {self.node_process.pid} ile başlatıldı.")
            
            # Log reader task'ını spawn et
            asyncio.create_task(self._read_subprocess_logs())
            return True
        except Exception as e:
            logger.error(f"❌ Mineflayer başlatılamadı: {e}")
            return False

    async def _read_subprocess_logs(self):
        """Node.js bot output'ını real-time oku ve logla."""
        if not self.node_process:
            return
        
        try:
            while self.node_process and self.node_process.poll() is None:
                try:
                    line = self.node_process.stdout.readline() if self.node_process.stdout else None
                    if line:
                        logger.info(f"[Node.js] {line.rstrip()}")
                    else:
                        await asyncio.sleep(0.1)
                except Exception as e:
                    logger.debug(f"Log read error: {e}")
                    await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"❌ Subprocess log reader error: {e}")

    async def run(self):
        """Orkestratörü çalıştır."""
        logger.info("="*60)
        logger.info(f"🤖 Minecraft Otonom AI Asistanı: {self.config.BOT_NAME}")
        logger.info(f"👑 Sahip: {self.config.BOT_OWNER}")
        logger.info(f"🎮 Hedef Sunucu: {self.config.MINECRAFT_HOST}:{self.config.MINECRAFT_PORT}")
        logger.info(f"🧠 AI Motoru: Ollama ({self.config.OLLAMA_MODEL})")
        logger.info("="*60)

        # 1. Ollama health check
        is_ollama_ready = await self.brain.check_health()
        if not is_ollama_ready:
            logger.warning(
                "⚠️ Ollama hazır görünmüyor. Bot yine de açılacak ancak karar veremeyebilir. "
                "Ollama'yı başlattığınızdan emin olun: ollama serve"
            )

        # 2. WebSocket bridge'i başlat
        try:
            await self.bridge.start()
        except Exception as e:
            logger.error(f"❌ Bridge başlatılamadı: {e}")
            return

        # 3. Mineflayer worker'ı başlat
        if not self.start_mineflayer_worker():
            logger.warning("⚠️ Mineflayer otomatik başlatılamamadı. Manuel olarak başlatın.")

        # 4. Bot spawn'unu bekle
        await self.wait_for_bot_ready(timeout=30)

        # 5. Otonom loop'u başlat
        self._loop_task = asyncio.create_task(self.autonomous_progression_loop())

        logger.info("✅ Sistem hazır!")

        # Ana loop - shutdown event'i bekle
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Graceful shutdown ve resource cleanup."""
        logger.info("\n🛑 Kapatış başlatılıyor...")
        self._shutdown_event.set()

        # Otonom loop'u iptal et
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await asyncio.wait_for(self._loop_task, timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("⚠️ Loop task terminate timeout")

        # Bridge'i kapat
        try:
            await self.bridge.stop()
        except Exception as e:
            logger.error(f"Bridge shutdown error: {e}")

        # Node.js process'ini terminate et
        if self.node_process:
            try:
                logger.info("Mineflayer process'i terminate ediliyor...")
                self.node_process.terminate()
                
                # SIGTERM sonrası bekle
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self.node_process.wait),
                        timeout=5
                    )
                    logger.info("✅ Node.js process başarıyla terminate oldu.")
                except asyncio.TimeoutError:
                    logger.warning("⏳ Process terminate timeout; SIGKILL gönderiliyor...")
                    self.node_process.kill()
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(self.node_process.wait),
                            timeout=2
                        )
                    except asyncio.TimeoutError:
                        logger.error("❌ Process zorla kapatılamadı!")
            except Exception as e:
                logger.error(f"Subprocess cleanup error: {e}")

        logger.info("👋 Bot güvenle sonlandırıldı.")


def main():
    """Entry point."""
    config = Config.load_from_env()
    setup_logging(config)

    missing = config.validate()
    if missing:
        logger.error(
            f"❌ Eksik yapılandırma: {', '.join(missing)}. "
            "Lütfen .env dosyasını kontrol edin veya .env.example'dan kopyalayın."
        )
        sys.exit(1)

    bot = MinecraftAIBot(config)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("⌨️ İşlem kullanıcı tarafından durduruldu (Ctrl+C).")
    except Exception as e:
        logger.error(f"❌ Kritik hata: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
