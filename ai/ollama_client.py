"""Ollama Yerel Yapay Zeka İstemcisi - Qwen 2.5 optimized."""
import asyncio
import json
import time
from typing import Dict, Any, List, Optional
import aiohttp

from utils.logger import get_logger
from ai.tools import MINECRAFT_TOOLS
from ai.prompts import build_system_prompt_for_ollama
from ai.progression_tree import get_current_progression_goal, resolve_missing_ingredients
from ai.knowledge_base import get_relevant_tactic

logger = get_logger("OllamaClient")


class OllamaBrain:
    """Ollama + Qwen 2.5 3B brain for decision making."""
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
        bot_name: str = "AIAssistant",
        bot_owner: str = "Omer"
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.bot_name = bot_name
        self.bot_owner = bot_owner
        self.chat_history: List[Dict[str, Any]] = []
        self.max_history = 8  # Keep shorter for 3B model efficiency
        self.session: Optional[aiohttp.ClientSession] = None
        self._llm_call_latency = []
        self._max_latency_samples = 10

    async def initialize(self):
        """Initialize persistent aiohttp session."""
        if not self.session:
            self.session = aiohttp.ClientSession()
            logger.info("✅ Ollama session initialized.")

    async def shutdown(self):
        """Graceful shutdown of session."""
        if self.session:
            await self.session.close()
            logger.info("🛑 Ollama session closed.")

    async def check_health(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            await self.initialize()
            async with self.session.get(f"{self.base_url}/api/tags", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    logger.info(f"✅ Ollama aktif. Mevcut modeller: {models}")
                    if not any(self.model in m for m in models):
                        logger.warning(
                            f"⚠️ '{self.model}' modeli bulunamadı! "
                            f"Çalıştırın: ollama run {self.model}"
                        )
                    return True
                else:
                    logger.error(f"❌ Ollama HTTP {resp.status} döndürdü.")
                    return False
        except Exception as e:
            logger.error(f"❌ Ollama servisine bağlanılamadı ({self.base_url}): {e}")
            return False

    async def process_chat(
        self,
        sender: str,
        message: str,
        state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Process chat message with optimized prompting."""
        if not state:
            state = {}

        # Build dynamic system prompt with full context
        inv_dict = {}
        for item in state.get("inventory_items", []):
            inv_dict[item.get("name", "")] = item.get("count", 0)
        
        goal = get_current_progression_goal(inv_dict)
        pro_tactic = get_relevant_tactic(state)
        
        state["missing_ingredients"] = resolve_missing_ingredients(goal["target"], inv_dict)
        state["goal_stage"] = goal["stage"]
        state["goal_target"] = goal["target"]
        state["goal_missing"] = state["missing_ingredients"]
        state["goal_hint"] = goal["next_hint"]
        
        system_content = build_system_prompt_for_ollama(
            state=state,
            bot_name=self.bot_name,
            bot_owner=self.bot_owner,
            goal=goal,
            pro_tactic=pro_tactic,
            active_task=state.get("active_player_task")
        )

        user_msg_content = f"[{sender}]: {message}"
        self.chat_history.append({"role": "user", "content": user_msg_content})

        if len(self.chat_history) > self.max_history:
            self.chat_history = self.chat_history[-self.max_history:]

        messages = [{"role": "system", "content": system_content}] + self.chat_history

        # Qwen 2.5 3B optimized parameters
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": MINECRAFT_TOOLS,
            "stream": False,
            "options": {
                "temperature": 0.2,  # Lower for more consistent decisions
                "top_p": 0.8,  # Reduce sampling variance
                "top_k": 40,
                "num_predict": 200  # Limit output tokens for 3B model
            }
        }

        try:
            await self.initialize()
            start_time = time.time()
            
            async with self.session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=20  # Shorter timeout for 3B model
            ) as resp:
                latency = time.time() - start_time
                self._llm_call_latency.append(latency)
                if len(self._llm_call_latency) > self._max_latency_samples:
                    self._llm_call_latency.pop(0)
                
                avg_latency = sum(self._llm_call_latency) / len(self._llm_call_latency)
                logger.debug(f"⏱️ Ollama latency: {latency:.2f}s (avg: {avg_latency:.2f}s)")
                
                if resp.status != 200:
                    err_text = await resp.text()
                    logger.error(f"❌ Ollama API hatası ({resp.status}): {err_text[:200]}")
                    return {"text": "LLM error - using fallback.", "tool_calls": []}

                data = await resp.json()
                msg = data.get("message", {})
                response_text = msg.get("content", "").strip()
                tool_calls = msg.get("tool_calls", [])

                if response_text:
                    self.chat_history.append({"role": "assistant", "content": response_text})

                parsed_tools = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    func_name = func.get("name")
                    args = func.get("arguments", {})
                    
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}

                    if isinstance(args, dict):
                        if "arguments" in args and isinstance(args["arguments"], dict):
                            args = args["arguments"]
                        if "count" in args and isinstance(args["count"], dict):
                            args["count"] = args["count"].get("value", 1)
                        if "item_name" in args and isinstance(args["item_name"], str):
                            args["item_name"] = args["item_name"].lower().strip()

                    if func_name:
                        parsed_tools.append({
                            "name": func_name,
                            "arguments": args
                        })

                logger.info(
                    f"🤖 Response: '{response_text[:60]}...' | "
                    f"Tools: {[t['name'] for t in parsed_tools]} | "
                    f"Latency: {latency:.2f}s"
                )
                return {
                    "text": response_text,
                    "tool_calls": parsed_tools
                }

        except asyncio.TimeoutError:
            logger.error("⏱️ Ollama timeout (20s).")
            return {"text": "LLM timeout.", "tool_calls": []}
        except Exception as e:
            logger.error(f"❌ Ollama error: {e}")
            return {"text": "LLM connection error.", "tool_calls": []}

    def get_average_latency(self) -> float:
        """Get average LLM call latency."""
        if not self._llm_call_latency:
            return 0.0
        return sum(self._llm_call_latency) / len(self._llm_call_latency)
