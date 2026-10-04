"""Python <-> Mineflayer WebSocket Bridge Server."""
import asyncio
import json
import uuid
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
        
        # Event Callbacks
        self.on_chat_callback: Optional[Callable] = None
        self.on_spawn_callback: Optional[Callable] = None
        self.on_death_callback: Optional[Callable] = None
        self.on_action_completed_callback: Optional[Callable] = None
        self.on_action_started_callback: Optional[Callable] = None
        self.on_game_won_callback: Optional[Callable] = None

        # Action Tracking and Wait Events
        self._pending_action_events: Dict[str, asyncio.Event] = {}
        self._last_action_results: Dict[str, Dict[str, Any]] = {}

    async def start(self):
        """Starts the WebSocket bridge server."""
        logger.info(f"🌐 WebSocket bridge starting at: ws://{self.host}:{self.port}")
        self.server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            ping_interval=None,
            ping_timeout=None
        )
        logger.info("✅ WebSocket bridge ready, waiting for Mineflayer worker to connect...")

    async def stop(self):
        """Stops the bridge server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("🛑 WebSocket bridge server stopped.")

    async def _handle_client(self, websocket: WebSocketServerProtocol, path: str = ""):
        """Handles Mineflayer worker client connection and incoming messages."""
        self.clients.add(websocket)
        logger.info(f"🤝 Mineflayer worker client connected: {websocket.remote_address}")

        try:
            async for raw_message in websocket:
                try:
                    data = json.loads(raw_message)
                    await self._dispatch_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"⚠️ Invalid JSON received: {raw_message}")
                except Exception as e:
                    logger.error(f"❌ Message dispatch error: {e}", exc_info=True)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("🔌 Mineflayer worker disconnected.")
        finally:
            self.clients.discard(websocket)

    async def _dispatch_message(self, data: Dict[str, Any]):
        """Dispatches incoming message to appropriate handler callback."""
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
            logger.info("🌟 Bot spawned in Minecraft world!")
            if self.on_spawn_callback:
                await self.on_spawn_callback(self.latest_state)

        elif msg_type == "bot_death":
            logger.warning("💀 Bot died!")
            if self.on_death_callback:
                await self.on_death_callback(self.latest_state)

        elif msg_type == "bot_status":
            logger.info(f"ℹ️ Bot status: {data.get('status')}")

        elif msg_type == "game_won":
            logger.info("🏆 [VICTORY] The game has been beaten! Ender Dragon defeated and exit portal entered!")
            if self.on_game_won_callback:
                await self.on_game_won_callback(data)

        elif msg_type == "action_started":
            cmd = data.get("command", "")
            logger.debug(f"▶️ Bot started action: {cmd}")
            if self.on_action_started_callback:
                await self.on_action_started_callback(cmd, self.latest_state)

        elif msg_type == "action_completed":
            cmd = data.get("command", "")
            action_id = data.get("action_id", data.get("command", ""))
            success = data.get("success", True)
            error = data.get("error")
            res = {"success": success, "error": error, "command": cmd}
            self._last_action_results[action_id] = res

            if action_id in self._pending_action_events:
                self._pending_action_events[action_id].set()

            if success:
                logger.debug(f"✅ Bot action completed: {cmd}")
            else:
                logger.warning(f"⚠️ Bot action failed: {cmd} (Error: {error})")

            if self.on_action_completed_callback:
                await self.on_action_completed_callback(cmd, success, error, self.latest_state)

    async def send_action(self, command: str, args: Optional[Dict[str, Any]] = None, action_id: Optional[str] = None):
        """Sends an action command to Mineflayer bot (asynchronous / non-blocking)."""
        if not self.clients:
            logger.warning(f"⚠️ Cannot send action ({command}): Mineflayer worker not connected!")
            return

        payload = {
            "command": command,
            "args": args or {}
        }
        if action_id:
            payload["action_id"] = action_id
        
        payload_str = json.dumps(payload)

        for client in list(self.clients):
            try:
                await client.send(payload_str)
            except Exception as e:
                logger.error(f"❌ Error sending action payload: {e}")

    async def send_action_and_wait(
        self,
        command: str,
        args: Optional[Dict[str, Any]] = None,
        timeout: float = 35.0
    ) -> Dict[str, Any]:
        """Sends an action command to Mineflayer bot and waits for completion event."""
        if not self.clients:
            logger.warning(f"⚠️ Cannot send action ({command}): Mineflayer worker not connected!")
            return {"success": False, "error": "Mineflayer worker not connected"}

        # Non-blocking instant actions bypass wait
        if command in ("say_chat", "stop_actions", "guard_player", "follow_player"):
            await self.send_action(command, args)
            return {"success": True, "error": None}

        event = asyncio.Event()
        action_id = str(uuid.uuid4())[:8]
        self._pending_action_events[action_id] = event
        self._last_action_results.pop(action_id, None)

        await self.send_action(command, args, action_id=action_id)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self._last_action_results.get(action_id, {"success": True, "error": None})
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Action timed out ({command}) [{timeout}s].")
            return {"success": False, "error": f"Action timed out after {timeout}s"}
        finally:
            self._pending_action_events.pop(action_id, None)
