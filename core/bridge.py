"""Python <-> Mineflayer WebSocket Köprü Sunucusu."""
import asyncio
import json
from typing import Callable, Optional, Dict, Any, Set
import websockets
from websockets.server import WebSocketServerProtocol

from utils.logger import get_logger

logger = get_logger("BridgeServer")

class MinecraftBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Set[WebSocketServerProtocol] = set()
        self.server = None
        self.latest_state: Dict[str, Any] = {}
        
        # Olay Callback'leri
        self.on_chat_callback: Optional[Callable] = None
        self.on_spawn_callback: Optional[Callable] = None
        self.on_death_callback: Optional[Callable] = None
        self.on_action_completed_callback: Optional[Callable] = None
        self.on_action_started_callback: Optional[Callable] = None

        # Eylem Takip ve Bekleme
        self._pending_action_events: Dict[str, asyncio.Event] = {}
        self._last_action_results: Dict[str, Dict[str, Any]] = {}

    async def start(self):
        """WebSocket köprü sunucusunu başlatır."""
        logger.info(f"🌐 WebSocket köprüsü başlatılıyor: ws://{self.host}:{self.port}")
        self.server = await websockets.serve(self._handle_client, self.host, self.port)
        logger.info("✅ WebSocket köprüsü hazır, Mineflayer botunun bağlanması bekleniyor...")

    async def stop(self):
        """Köprü sunucusunu durdurur."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("🛑 WebSocket köprüsü durduruldu.")

    async def _handle_client(self, websocket: WebSocketServerProtocol, path: str = ""):
        """Mineflayer worker istemcisini karşılar ve gelen mesajları işler."""
        self.clients.add(websocket)
        logger.info(f"🤝 Mineflayer bot istemcisi bağlandı: {websocket.remote_address}")

        try:
            async for raw_message in websocket:
                try:
                    data = json.loads(raw_message)
                    await self._dispatch_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"⚠️ Geçersiz JSON alındı: {raw_message}")
                except Exception as e:
                    logger.error(f"❌ Mesaj işleme hatası: {e}", exc_info=True)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("🔌 Mineflayer botunun bağlantısı koptu.")
        finally:
            self.clients.discard(websocket)

    async def _dispatch_message(self, data: Dict[str, Any]):
        """Gelen olayı uygun callback'e yönlendirir."""
        msg_type = data.get("type")
        state = data.get("state", {})
        if state:
            self.latest_state = state

        if msg_type == "chat_message":
            sender = data.get("sender", "")
            message = data.get("message", "")
            if self.on_chat_callback:
                await self.on_chat_callback(sender, message, self.latest_state)

        elif msg_type == "bot_spawned":
            logger.info("🌟 Bot oyuna giriş yaptı!")
            if self.on_spawn_callback:
                await self.on_spawn_callback(self.latest_state)

        elif msg_type == "bot_death":
            logger.warning("💀 Bot öldü!")
            if self.on_death_callback:
                await self.on_death_callback(self.latest_state)

        elif msg_type == "bot_status":
            logger.info(f"ℹ️ Bot durumu: {data.get('status')}")

        elif msg_type == "action_started":
            cmd = data.get("command", "")
            logger.debug(f"▶️ Bot eyleme başladı: {cmd}")
            if self.on_action_started_callback:
                await self.on_action_started_callback(cmd, self.latest_state)

        elif msg_type == "action_completed":
            cmd = data.get("command", "")
            success = data.get("success", True)
            error = data.get("error")
            res = {"success": success, "error": error, "command": cmd}
            self._last_action_results[cmd] = res

            if cmd in self._pending_action_events:
                self._pending_action_events[cmd].set()

            if success:
                logger.debug(f"✅ Bot eylemi tamamlandı: {cmd}")
            else:
                logger.warning(f"⚠️ Bot eylemi başarısız oldu: {cmd} (Hata: {error})")

            if self.on_action_completed_callback:
                await self.on_action_completed_callback(cmd, success, error, self.latest_state)

    async def send_action(self, command: str, args: Optional[Dict[str, Any]] = None):
        """Mineflayer botuna komut gönderir (asenkron / beklemesiz)."""
        if not self.clients:
            logger.warning(f"⚠️ Komut gönderilemedi ({command}): Mineflayer bağlı değil!")
            return

        payload = json.dumps({
            "command": command,
            "args": args or {}
        })

        # Tüm bağlı istemcilere yayınla (genelde 1 adet mineflayer worker bağlı olur)
        for client in list(self.clients):
            try:
                await client.send(payload)
            except Exception as e:
                logger.error(f"❌ Komut gönderme hatası: {e}")

    async def send_action_and_wait(
        self,
        command: str,
        args: Optional[Dict[str, Any]] = None,
        timeout: float = 35.0
    ) -> Dict[str, Any]:
        """Mineflayer botuna komut gönderir ve tamamlanmasını bekler."""
        if not self.clients:
            logger.warning(f"⚠️ Komut gönderilemedi ({command}): Mineflayer bağlı değil!")
            return {"success": False, "error": "Mineflayer worker not connected"}

        # Anlık veya arka plan komutlarında bloklamayı engelle
        if command in ("say_chat", "stop_actions", "guard_player", "follow_player"):
            await self.send_action(command, args)
            return {"success": True, "error": None}

        event = asyncio.Event()
        self._pending_action_events[command] = event
        self._last_action_results.pop(command, None)

        await self.send_action(command, args)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self._last_action_results.get(command, {"success": True, "error": None})
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Komut zaman aşımına uğradı ({command}) [{timeout}s].")
            return {"success": False, "error": f"Action timed out after {timeout}s"}
        finally:
            self._pending_action_events.pop(command, None)
