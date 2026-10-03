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

    async def send_action(self, command: str, args: Optional[Dict[str, Any]] = None):
        """Mineflayer botuna komut gönderir."""
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
