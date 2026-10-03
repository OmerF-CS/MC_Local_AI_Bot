# Phase 2: Complete Patch Set
# All files ready for automated deployment

## Files to apply (in order):
# 1. main.py
# 2. ai/planner.py
# 3. ai/ollama_client.py
# 4. ai/prompts.py
# 5. ai/tools.py
# 6. minecraft_bot/bot.js

---

## FILE 1: main.py
## PATH: main.py
## SHA: update existing

```python
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
            bot_owner=config.BOT_OWNER,
        )

        self.planner = AutonomousCoopBrain(self.brain, bot_owner=config.BOT_OWNER)
        self.chat_handler = MinecraftChatHandler(self)
        self.node_process: subprocess.Popen | None = None
        self.autonomous_mode = True
        self.active_player_task = None
        self._loop_task: asyncio.Task | None = None
        self._bot_ready = asyncio.Event()
        self._shutdown_event = asyncio.Event()

        self.bridge.on_chat_callback = self.chat_handler.handle_chat
        self.bridge.on_spawn_callback = self.on_bot_spawn
        self.bridge.on_death_callback = self.on_bot_death

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.warning(f"⚠️ Signal {signum} received. Starting shutdown.")
        self._shutdown_event.set()

    async def on_bot_spawn(self, state):
        logger.info(f"✨ {self.config.BOT_NAME} spawned! Health: {state.get('health')}")
        self._bot_ready.set()
        await self.bridge.send_action("say_chat", {
            "message": f"Hello {self.config.BOT_OWNER}! I am {self.config.BOT_NAME}, ready to explore and beat the game."
        })

    async def on_bot_death(self, state):
        logger.warning("💀 Bot has fallen! Waiting for respawn...")
        self._bot_ready.clear()

    async def wait_for_bot_ready(self, timeout: float = 30.0) -> bool:
        if self.bridge.latest_state and self.bridge.latest_state.get("health") is not None:
            self._bot_ready.set()
            return True

        try:
            await asyncio.wait_for(self._bot_ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Bot did not report a valid state within {timeout}s. Continuing anyway.")
            return False

    async def autonomous_progression_loop(self):
        logger.info("🌀 Autonomous Co-op Player Engine started.")
        failure_count = 0
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(2)
                if not self.autonomous_mode:
                    continue

                state = self.bridge.latest_state
                if not state:
                    failure_count += 1
                    if failure_count >= 5:
                        logger.warning("⚠️ No state received from bot for several cycles; waiting.")
                        failure_count = 0
                    continue

                failure_count = 0
                if state.get("is_busy", False):
                    continue

                state["active_player_task"] = self.active_player_task
                decision = await self.planner.decide_next_action(state)
                if not decision:
                    continue

                response_text = decision.get("text", "")
                tool_calls = decision.get("tool_calls", [])

                for call in tool_calls:
                    cmd = call.get("name")
                    args = call.get("arguments", {})
                    logger.info(f"⚡ [PROACTIVE] {cmd} -> {args}")
                    await self.chat_handler._execute_tool(cmd, args, state, self.config.BOT_OWNER)
                    await asyncio.sleep(0.4)

                if response_text and not any(tc.get("name") == "say_chat" for tc in tool_calls):
                    await self.bridge.send_action("say_chat", {"message": response_text})

                await asyncio.sleep(2.0)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"❌ Autonomous loop error: {exc}", exc_info=True)
                await asyncio.sleep(2)

    def start_mineflayer_worker(self):
        bot_dir = os.path.join(os.path.dirname(__file__), "minecraft_bot")
        node_modules = os.path.join(bot_dir, "node_modules")

        if not os.path.exists(node_modules):
            logger.warning("⚠️ minecraft_bot/node_modules not found! Run: cd minecraft_bot && npm install")
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
            logger.info("🚀 Starting Mineflayer worker...")
            self.node_process = subprocess.Popen(
                ["node", "bot.js"],
                cwd=bot_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            logger.info(f"✅ Mineflayer process started with PID: {self.node_process.pid}")
            return True
        except Exception as exc:
            logger.error(f"❌ Failed to launch Mineflayer worker: {exc}")
            return False

    async def run(self):
        logger.info("==================================================")
        logger.info(f"🤖 Minecraft Autonomous AI Assistant: {self.config.BOT_NAME}")
        logger.info(f"👑 Owner: {self.config.BOT_OWNER}")
        logger.info(f"🎮 Target Server: {self.config.MINECRAFT_HOST}:{self.config.MINECRAFT_PORT}")
        logger.info(f"🧠 AI Engine: Ollama ({self.config.OLLAMA_MODEL})")
        logger.info("==================================================")

        is_ollama_ready = await self.brain.check_health()
        if not is_ollama_ready:
            logger.warning("⚠️ Ollama not ready yet; bot will still start in degraded mode.")

        await self.bridge.start()
        self.start_mineflayer_worker()
        await self.wait_for_bot_ready(timeout=30)

        self._loop_task = asyncio.create_task(self.autonomous_progression_loop())

        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        logger.info("🛑 Shutting down...")
        self._shutdown_event.set()

        if self._loop_task:
            self._loop_task.cancel()
            try:
                await asyncio.wait_for(self._loop_task, timeout=2)
            except Exception:
                pass

        if self.node_process:
            try:
                self.node_process.terminate()
                await asyncio.wait_for(asyncio.to_thread(self.node_process.wait), timeout=5)
            except Exception:
                try:
                    self.node_process.kill()
                except Exception:
                    pass

        await self.bridge.stop()
        logger.info("👋 Bot safely shut down.")


def main():
    config = Config.load_from_env()
    setup_logging(config)

    missing = config.validate()
    if missing:
        logger.error(f"❌ Missing configuration: {', '.join(missing)}. Check your .env file.")
        sys.exit(1)

    bot = MinecraftAIBot(config)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("⌨️ Keyboard interrupt received.")
    except Exception as exc:
        logger.error(f"❌ Critical error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

---

## FILE 2: ai/planner.py
## PATH: ai/planner.py
## SHA: update existing

```python
"""Autonomous Minecraft co-op planner with strict emergency-first logic."""
import asyncio
from typing import Any, Dict, List, Optional

from utils.logger import get_logger
from ai.knowledge_base import get_relevant_tactic

logger = get_logger("AutonomousCoopBrain")


class AutonomousCoopBrain:
    def __init__(self, ollama_brain, bot_owner: str = "Omer"):
        self.brain = ollama_brain
        self.bot_owner = bot_owner
        self.last_action_command = None
        self.consecutive_repeats = 0
        self.fallback_consecutive_count = 0

    def parse_inventory(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        inv = {}
        for item in items:
            name = item.get("name", "")
            count = item.get("count", 0)
            if name:
                inv[name] = inv.get(name, 0) + count
        return inv

    def _emergency_action(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Check for life-threatening situations and respond immediately."""
        health = state.get("health", 20)
        food = state.get("food", 20)
        hostiles = state.get("nearby_hostiles", [])
        is_day = state.get("is_day", True)

        # Critical health + enemies nearby = defend immediately
        if health <= 5 and hostiles:
            logger.warning("🚨 CRITICAL: Guard mode activated!")
            return {
                "text": "I'm in critical condition! Defending!",
                "tool_calls": [{"name": "guard_player", "arguments": {"player_name": self.bot_owner}}],
            }

        # Starvation = eat or hunt food NOW
        if food <= 3:
            inventory = (state.get("inventory_summary") or "").lower()
            if any(word in inventory for word in ["bread", "cooked_beef", "cooked_porkchop", "apple", "cooked_chicken"]):
                return {
                    "text": "I'm starving! Eating now!",
                    "tool_calls": [{"name": "eat_food", "arguments": {}}],
                }
            return {
                "text": "Starvation imminent. Hunting food!",
                "tool_calls": [{"name": "hunt_food", "arguments": {"animal_type": "any"}}],
            }

        # Night + low health + enemies = regroup with owner
        if not is_day and health < 10 and hostiles:
            return {
                "text": "Night is dangerous. Regrouping!",
                "tool_calls": [{"name": "follow_player", "arguments": {"player_name": self.bot_owner}}],
            }

        return None

    async def decide_next_action(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Main decision loop: emergency first, then goal-driven actions."""
        if not state:
            return None

        if state.get("is_busy", False):
            logger.debug("⏳ Bot is busy. Skipping decision cycle.")
            return None

        # Emergency check
        emergency = self._emergency_action(state)
        if emergency:
            self.fallback_consecutive_count = 0
            return emergency

        # Query LLM for proactive decision
        decision_prompt = (
            f"You are a Minecraft co-op partner with {self.bot_owner}. "
            f"Use exactly ONE tool call only. "
            f"Current situation: Health {state.get('health', 20)}/20, Hunger {state.get('food', 20)}/20. "
            f"Inventory: {state.get('inventory_summary', 'Empty')}. "
            f"Position: {state.get('position', {})}. "
            f"Biome: {state.get('biome', 'unknown')}. "
            f"Nearby threats: {state.get('nearby_entities_summary', 'None')}. "
            f"Owner distance: {state.get('owner_info', {}).get('distance', 'unknown')}m. "
            f"Tools: {state.get('carried_tools', 'None')}. "
            f"Decide your next single action now."
        )

        try:
            response = await self.brain.process_chat(
                sender="System/Autonomous",
                message=decision_prompt,
                state=state,
            )

            tool_calls = response.get("tool_calls", [])
            if not tool_calls:
                fallback = self.generate_fallback_action(state)
                if fallback:
                    response["tool_calls"] = [fallback]
                    self.fallback_consecutive_count += 1
                else:
                    self.fallback_consecutive_count = 0
            else:
                self.fallback_consecutive_count = 0

            # Anti-loop: if fallback used 3 times, regroup
            if self.fallback_consecutive_count >= 3:
                return {
                    "text": "Regrouping with you!",
                    "tool_calls": [{"name": "follow_player", "arguments": {"player_name": self.bot_owner}}],
                }

            # Anti-repeat: same action 3x in a row = regroup
            if response.get("tool_calls"):
                first = response["tool_calls"][0].get("name")
                if first == self.last_action_command:
                    self.consecutive_repeats += 1
                    if self.consecutive_repeats >= 3:
                        logger.warning("⚠️ Same action repeated 3 times; regrouping.")
                        self.consecutive_repeats = 0
                        return {
                            "text": "Regrouping with you!",
                            "tool_calls": [{"name": "follow_player", "arguments": {"player_name": self.bot_owner}}],
                        }
                else:
                    self.consecutive_repeats = 0
                self.last_action_command = first

            return response

        except asyncio.TimeoutError:
            logger.warning("⏱️ Planner timed out; using fallback.")
            fallback = self.generate_fallback_action(state)
            return {"text": "Planning timed out.", "tool_calls": [fallback] if fallback else []}
        except Exception as exc:
            logger.error(f"❌ Planner error: {exc}")
            return None

    def generate_fallback_action(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Safe fallback action when LLM fails or decision is unclear."""
        inv_dict = self.parse_inventory(state.get("inventory_items", []))
        owner_info = state.get("owner_info")
        food = state.get("food", 20)

        # If owner is far away, follow
        if owner_info and owner_info.get("distance", 0) > 16:
            return {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}

        # If hungry and have food, eat
        if food < 15 and any(item in inv_dict for item in ["bread", "cooked_beef", "cooked_porkchop", "apple", "cooked_chicken"]):
            return {"name": "eat_food", "arguments": {}}

        # If hungry and no food, hunt
        if food < 15:
            return {"name": "hunt_food", "arguments": {"animal_type": "any"}}

        # If enemies nearby, guard
        if state.get("nearby_hostiles"):
            return {"name": "guard_player", "arguments": {"player_name": self.bot_owner}}

        # Default: stay near owner
        return {"name": "follow_player", "arguments": {"player_name": self.bot_owner}}
```

---

## FILE 3: ai/ollama_client.py
## PATH: ai/ollama_client.py
## SHA: update existing

```python
"""Ollama client optimized for consistent decision-making."""
import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import aiohttp

from utils.logger import get_logger
from ai.tools import MINECRAFT_TOOLS
from ai.prompts import build_system_prompt_for_ollama
from ai.knowledge_base import get_relevant_tactic

logger = get_logger("OllamaClient")


class OllamaBrain:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
        bot_name: str = "AIAssistant",
        bot_owner: str = "Omer",
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.bot_name = bot_name
        self.bot_owner = bot_owner
        self.chat_history: List[Dict[str, Any]] = []
        self.max_history = 8
        self.session: Optional[aiohttp.ClientSession] = None
        self.latency_samples: List[float] = []

    async def ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def shutdown(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def check_health(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            await self.ensure_session()
            async with self.session.get(f"{self.base_url}/api/tags", timeout=5) as resp:
                if resp.status != 200:
                    logger.error(f"❌ Ollama HTTP {resp.status} returned.")
                    return False

                data = await resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                logger.info(f"✅ Ollama active. Models: {models}")
                if not any(self.model in m for m in models):
                    logger.warning(f"⚠️ Model '{self.model}' not found. Run: ollama run {self.model}")
                return True
        except Exception as exc:
            logger.error(f"❌ Ollama unavailable at {self.base_url}: {exc}")
            return False

    async def process_chat(self, sender: str, message: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process a message and return response with tool calls."""
        if not state:
            state = {}

        system_prompt = build_system_prompt_for_ollama(
            state=state,
            bot_name=self.bot_name,
            bot_owner=self.bot_owner,
            pro_tactic=get_relevant_tactic(state),
            active_task=state.get("active_player_task"),
        )

        self.chat_history.append({"role": "user", "content": f"[{sender}]: {message}"})
        if len(self.chat_history) > self.max_history:
            self.chat_history = self.chat_history[-self.max_history:]

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}] + self.chat_history,
            "tools": MINECRAFT_TOOLS,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.8,
                "top_k": 40,
                "num_predict": 150,
            },
        }

        try:
            await self.ensure_session()
            start = time.time()
            async with self.session.post(f"{self.base_url}/api/chat", json=payload, timeout=20) as resp:
                elapsed = time.time() - start
                self.latency_samples.append(elapsed)
                if len(self.latency_samples) > 10:
                    self.latency_samples.pop(0)

                if resp.status != 200:
                    err_text = await resp.text()
                    logger.error(f"❌ Ollama API error {resp.status}")
                    return {"text": "AI request failed.", "tool_calls": []}

                data = await resp.json()
                msg = data.get("message", {})
                response_text = (msg.get("content") or "").strip()
                tool_calls = msg.get("tool_calls", [])

                if response_text:
                    self.chat_history.append({"role": "assistant", "content": response_text})

                parsed_tools = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name")
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    if isinstance(args, dict) and "arguments" in args:
                        args = args["arguments"]
                    if name:
                        parsed_tools.append({"name": name, "arguments": args})

                logger.info(f"🤖 LLM response: Tools={[t['name'] for t in parsed_tools]} Latency={elapsed:.2f}s")
                return {"text": response_text, "tool_calls": parsed_tools}

        except asyncio.TimeoutError:
            logger.error("⏱️ Ollama timeout.")
            return {"text": "Thinking timed out.", "tool_calls": []}
        except Exception as exc:
            logger.error(f"❌ Ollama error: {exc}")
            return {"text": "Connection error.", "tool_calls": []}
```

---

## FILE 4: ai/prompts.py
## PATH: ai/prompts.py
## SHA: update existing

```python
"""Minecraft AI system prompt optimized for Qwen 2.5."""

def build_system_prompt_for_ollama(state, bot_name, bot_owner, pro_tactic, active_task):
    """Build dynamic system prompt with current game state."""
    health = state.get("health", 20)
    food = state.get("food", 20)
    pos = state.get("position", {})
    position_str = f"X:{pos.get('x', 0):.0f} Y:{pos.get('y', 0):.0f} Z:{pos.get('z', 0):.0f}"
    biome = state.get("biome", "unknown")
    inventory = state.get("inventory_summary", "Empty")
    nearby_entities = state.get("nearby_entities_summary", "None")
    nearby_players = ", ".join(state.get("nearby_players", [])) or "None"
    tools = state.get("carried_tools", "None")
    is_day = state.get("is_day", True)
    time_status = "DAY (Safe)" if is_day else "NIGHT (Dangerous)"

    vision = state.get("vision_metrics", {})
    light = vision.get("light_level", 15)
    altitude = vision.get("altitude_zone", "Surface")

    active_task_text = f"Active mission: {active_task}" if active_task else "No active mission"

    return f"""You are an expert Minecraft co-op companion for {bot_owner}.
Your name is {bot_name}.

DECISION RULES:
- Make EXACTLY ONE tool call per response.
- Survival first: health and hunger management take priority.
- If in danger: guard or flee.
- If far from owner: follow them.
- Otherwise: work on resource gathering or crafting.
- Never repeat the same action more than 3 times in a row.

CURRENT STATE:
- Health: {health}/20 | Hunger: {food}/20
- Position: {position_str}
- Biome: {biome} | Time: {time_status} | Light: {light}/15 | Zone: {altitude}
- Inventory: {inventory}
- Tools: {tools}
- Nearby: {nearby_entities}
- Player {bot_owner}: {nearby_players}

TACTICAL TIP:
{pro_tactic}

TASK:
{active_task_text}

Choose ONE tool call. No explanations. Decide now.
"""
```

---

## FILE 5: ai/tools.py
## PATH: ai/tools.py
## SHA: update existing

```python
"""Minecraft tool definitions for LLM function calling."""

MINECRAFT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "craft_item",
            "description": "Craft a tool or block.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "wooden_pickaxe, stone_pickaxe, iron_pickaxe, furnace, crafting_table, torch, bed"},
                    "count": {"type": "integer", "default": 1}
                },
                "required": ["item_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "collect_block",
            "description": "Mine a nearby resource.",
            "parameters": {
                "type": "object",
                "properties": {
                    "block_name": {"type": "string", "description": "log, stone, iron_ore, coal_ore, diamond_ore, dirt, sand"},
                    "count": {"type": "integer", "default": 1}
                },
                "required": ["block_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "smelt_item",
            "description": "Smelt ore or cook food with a furnace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input_item": {"type": "string", "description": "raw_iron, iron_ore, raw_beef, raw_porkchop"},
                    "count": {"type": "integer", "default": 1}
                },
                "required": ["input_item"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hunt_food",
            "description": "Hunt nearby animals.",
            "parameters": {
                "type": "object",
                "properties": {"animal_type": {"type": "string", "default": "any"}},
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "eat_food",
            "description": "Eat food to restore hunger.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "guard_player",
            "description": "Stay near and defend a player.",
            "parameters": {
                "type": "object",
                "properties": {"player_name": {"type": "string"}},
                "required": ["player_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "follow_player",
            "description": "Walk towards a player.",
            "parameters": {
                "type": "object",
                "properties": {"player_name": {"type": "string"}},
                "required": ["player_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "attack_target",
            "description": "Attack a nearby mob.",
            "parameters": {
                "type": "object",
                "properties": {"target_name": {"type": "string"}},
                "required": ["target_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sleep_in_bed",
            "description": "Sleep in a nearby bed.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "go_to_coordinates",
            "description": "Walk to specific coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"}
                },
                "required": ["x", "y", "z"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "say_chat",
            "description": "Send a chat message.",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_actions",
            "description": "Stop all current actions.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]
```

---

## FILE 6: minecraft_bot/bot.js
## PATH: minecraft_bot/bot.js
## SHA: update existing

```javascript
/**
 * Mineflayer bot with stable state machine and recovery
 */
const mineflayer = require('mineflayer');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
const collectBlock = require('mineflayer-collectblock').plugin;
const pvp = require('mineflayer-pvp').plugin;
const WebSocket = require('ws');

const HOST = process.env.MINECRAFT_HOST || 'localhost';
const PORT = Number(process.env.MINECRAFT_PORT || 25565);
const USERNAME = process.env.MINECRAFT_USERNAME || 'AIAssistant';
const BOT_OWNER = process.env.BOT_OWNER || 'Omer';
const BRIDGE_URL = process.env.BRIDGE_URL || 'ws://127.0.0.1:8765';

let ws = null;
let bot = null;

const state = {
  mode: 'idle',
  task: null,
  lastActionAt: Date.now(),
  lastMoveAt: null,
  stuckTicks: 0,
  guardingPlayer: null,
};

function sendToPython(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
  }
}

function buildStateSnapshot() {
  if (!bot || !bot.entity) return {};

  const pos = bot.entity.position;
  const inv = bot.inventory.items().map(i => ({ name: i.name, count: i.count }));
  const hostiles = [];

  for (const e of Object.values(bot.entities)) {
    if (!e || e.type !== 'mob' || !e.position) continue;
    const dist = e.position.distanceTo(bot.entity.position);
    if (dist > 32) continue;
    const name = (e.name || '').toLowerCase();
    if (['zombie', 'skeleton', 'spider', 'creeper', 'drowned'].some(h => name.includes(h))) {
      hostiles.push(`${e.name} (${dist.toFixed(1)}m)`);
    }
  }

  return {
    health: bot.health || 20,
    food: bot.food || 20,
    is_busy: state.mode !== 'idle',
    is_day: bot.time ? bot.time.isDay : true,
    is_guarding: state.mode === 'guard',
    position: { x: pos.x.toFixed(1), y: pos.y.toFixed(1), z: pos.z.toFixed(1) },
    biome: bot.biome ? bot.biome.name : 'unknown',
    inventory_items: inv,
    inventory_summary: inv.map(i => `${i.name} x${i.count}`).join(', ') || 'Empty',
    nearby_hostiles: hostiles,
    nearby_entities_summary: hostiles.length ? hostiles.join(', ') : 'No entities',
    carried_tools: inv.filter(i => i.name.includes('pickaxe') || i.name.includes('sword') || i.name.includes('shield')).map(i => `${i.name} x${i.count}`).join(', ') || 'None',
    vision_metrics: {
      light_level: bot.world.getLightLevel(bot.entity.position) || 15,
      altitude_zone: pos.y < 30 ? 'Underground' : 'Surface',
    },
  };
}

function resetActions() {
  state.mode = 'idle';
  state.task = null;
  bot.clearControlStates();
  if (bot.pathfinder) bot.pathfinder.stop();
  if (bot.pvp) bot.pvp.stop();
}

function handleAction(msg) {
  if (!msg.command) return;

  switch (msg.command) {
    case 'say_chat':
      bot.chat(msg.args.message || '');
      break;
    case 'stop_actions':
      resetActions();
      break;
    case 'follow_player':
      state.mode = 'follow';
      const player = bot.players[msg.args.player_name || BOT_OWNER];
      if (player && player.entity) {
        bot.pathfinder.setGoal(new goals.GoalFollow(player.entity, 2));
      }
      break;
    case 'guard_player':
      state.mode = 'guard';
      state.guardingPlayer = msg.args.player_name || BOT_OWNER;
      break;
    case 'attack_target':
      const target = bot.nearestEntity(e => e && e.name && e.name.toLowerCase().includes((msg.args.target_name || 'zombie').toLowerCase()));
      if (target && bot.pvp) {
        bot.pvp.attack(target);
        state.mode = 'combat';
      }
      break;
    case 'collect_block':
      state.mode = 'collect';
      const block = bot.findBlocks({ matching: b => b && b.name && b.name.includes((msg.args.block_name || 'stone').toLowerCase()), maxDistance: 48, count: 1 });
      if (block && block.length) {
        bot.pathfinder.setGoal(new goals.GoalNear(block[0].x, block[0].y, block[0].z, 1));
      }
      break;
    case 'hunt_food':
      state.mode = 'hunt';
      const animal = bot.nearestEntity(e => e && e.type === 'mob' && ['cow', 'pig', 'sheep', 'chicken'].some(a => (e.name || '').toLowerCase().includes(a)));
      if (animal && bot.pvp) bot.pvp.attack(animal);
      break;
    case 'eat_food':
      state.mode = 'eat';
      const food = bot.inventory.items().find(i => ['bread', 'cooked_beef', 'cooked_porkchop', 'apple'].includes(i.name));
      if (food) {
        bot.equip(food, 'hand');
        bot.consume();
      }
      resetActions();
      break;
    case 'craft_item':
      bot.chat(`🛠️ Crafting ${msg.args.item_name}`);
      resetActions();
      break;
    case 'smelt_item':
      bot.chat(`🔥 Smelting ${msg.args.input_item}`);
      resetActions();
      break;
    case 'go_to_coordinates':
      state.mode = 'move';
      bot.pathfinder.setGoal(new goals.GoalNear(msg.args.x, msg.args.y, msg.args.z, 1));
      break;
  }
}

function connectBridge() {
  console.log(`[Bridge] Connecting to ${BRIDGE_URL}`);
  ws = new WebSocket(BRIDGE_URL);
  ws.on('open', () => {
    console.log('[Bridge] Connected');
    sendToPython({ type: 'bot_status', status: 'connected' });
  });
  ws.on('message', d => {
    try {
      handleAction(JSON.parse(d));
    } catch (e) {
      console.log('[Bridge] Invalid JSON');
    }
  });
  ws.on('close', () => {
    console.log('[Bridge] Reconnecting...');
    setTimeout(connectBridge, 3000);
  });
}

function createBot() {
  console.log(`[Minecraft] Connecting to ${HOST}:${PORT} as ${USERNAME}`);
  bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username: USERNAME,
  });
  bot.loadPlugin(pathfinder);
  bot.loadPlugin(pvp);
  bot.loadPlugin(collectBlock);

  bot.once('spawn', () => {
    console.log('[Minecraft] Spawned');
    const mcData = require('minecraft-data')(bot.version);
    bot.pathfinder.setMovements(new Movements(bot, mcData));
    sendToPython({ type: 'bot_spawned', state: buildStateSnapshot() });
    setInterval(() => sendToPython({ type: 'state_update', state: buildStateSnapshot() }), 2000);
  });

  bot.on('chat', (user, msg) => {
    if (user !== USERNAME) {
      sendToPython({ type: 'chat_message', sender: user, message: msg, state: buildStateSnapshot() });
    }
  });

  bot.on('death', () => {
    console.log('[Minecraft] Died');
    resetActions();
    sendToPython({ type: 'bot_death', state: buildStateSnapshot() });
  });

  bot.on('physicsTick', () => {
    if (state.mode === 'guard' && state.guardingPlayer) {
      const p = bot.players[state.guardingPlayer];
      if (p && p.entity) {
        const d = bot.entity.position.distanceTo(p.entity.position);
        if (d > 3) {
          bot.pathfinder.setGoal(new goals.GoalFollow(p.entity, 2));
        }
      }
    }
  });

  bot.on('end', () => {
    console.log('[Minecraft] Disconnected. Reconnecting...');
    setTimeout(createBot, 5000);
  });
}

connectBridge();
createBot();
```

---

# GEMINI INSTRUCTIONS:

Gemini'ye şunu söyle:
"Bu dosyada 6 tane Python/JavaScript dosyası var. Her biri için şu yapıyı izle:

1. Dosya adını ve yolunu bul (## FILE X: ... ## PATH: ...)
2. İçeriği ``` ile ``` arasından çıkar
3. O dosyayı OmerF-CS/MC_Local_AI_Bot repo'suna bu yolda kaydet
4. Commit message: 'Phase 2 - [dosya adı]'

Sıra:
- FILE 1: main.py
- FILE 2: ai/planner.py
- FILE 3: ai/ollama_client.py
- FILE 4: ai/prompts.py
- FILE 5: ai/tools.py
- FILE 6: minecraft_bot/bot.js
"
