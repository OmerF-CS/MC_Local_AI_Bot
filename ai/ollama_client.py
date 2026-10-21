"""Ollama Local AI Client - Qwen 2.5 optimized with robust JSON recovery and CJK sanitization."""
import asyncio
import json
import re
import time
from typing import Dict, Any, List, Optional
import aiohttp

from utils.logger import get_logger
from ai.tools import MINECRAFT_TOOLS
from ai.prompts import build_system_prompt_for_ollama
from ai.progression_tree import get_current_progression_goal, resolve_missing_ingredients
from ai.knowledge_base import get_relevant_tactic
from ai.security_and_affordance import strip_cjk, normalize_item_alias, AffordanceEngine

logger = get_logger("OllamaClient")


# Canonical runtime options for mc-qwen:3b (F1-R8: strictly identical between preload and chat to prevent model reloads)
OLLAMA_MODEL_OPTIONS: Dict[str, Any] = {
    "num_gpu": 999,      # Force 100% layer offload to RTX 3060 GPU VRAM
    "num_ctx": 8192,     # Accommodates 44 MINECRAFT_TOOLS JSON specs (~4700 tokens)
    "num_thread": 8,     # Parallel thread processing
    "temperature": 0.1,  # Ultra-deterministic, fast tool calling
    "top_p": 0.8,        # Reduce sampling variance
    "top_k": 40,
    "num_predict": 128   # Sub-second response generation
}


BLOCK_KEYWORDS = (
    "_log", "log", "_ore", "stone", "cobble", "cobblestone",
    "deepslate", "dirt", "wood", "plank", "planks", "sand", "gravel"
)


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

        # LLM timeout & performance metrics
        self.llm_timeouts: int = 0
        self.llm_calls_count: int = 0
        self.llm_tool_call_count: int = 0
        self.fallback_count: int = 0

    @staticmethod
    def recover_tool_calls_from_text(raw_text: str) -> List[Dict[str, Any]]:
        """4-layer JSON tool call extractor recovering standard and compact schemas."""
        if not raw_text or not isinstance(raw_text, str):
            return []

        clean_text = strip_cjk(raw_text).strip()
        parsed_data = None

        # Layer 1: Direct JSON parsing
        try:
            parsed_data = json.loads(clean_text)
        except Exception:
            pass

        # Layer 2: Markdown ```json ... ``` block extraction
        if parsed_data is None:
            md_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text, re.IGNORECASE)
            if md_match:
                try:
                    parsed_data = json.loads(md_match.group(1).strip())
                except Exception:
                    pass

        # Layer 3: Regex JSON object {...} extraction with trailing comma cleanup
        if parsed_data is None:
            brace_match = re.search(r"\{[\s\S]*\}", clean_text)
            if brace_match:
                candidate = brace_match.group(0)
                cleaned_candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    parsed_data = json.loads(cleaned_candidate)
                except Exception:
                    pass

        # Layer 3.5: Truncated JSON brace / quote completion
        if parsed_data is None and "{" in clean_text:
            first_brace = clean_text.find("{")
            fragment = clean_text[first_brace:].strip()
            for prefix in ['', '"', '"}']:
                for num_braces in range(1, 4):
                    try:
                        cand = fragment + prefix + ("}" * num_braces)
                        cand = re.sub(r",\s*([}\]])", r"\1", cand)
                        parsed_data = json.loads(cand)
                        if parsed_data:
                            break
                    except Exception:
                        continue
                if parsed_data:
                    break

        if not parsed_data:
            return []

        results: List[Dict[str, Any]] = []

        # Handle list of items or single item
        items = parsed_data if isinstance(parsed_data, list) else [parsed_data]

        for item in items:
            if not isinstance(item, dict):
                continue

            # Standard tool_calls array format
            if "tool_calls" in item and isinstance(item["tool_calls"], list):
                for tc in item["tool_calls"]:
                    func = tc.get("function", {})
                    f_name = func.get("name") or tc.get("name")
                    f_args = func.get("arguments", {}) if "function" in tc else tc.get("arguments", {})
                    if isinstance(f_args, str):
                        try:
                            f_args = json.loads(f_args)
                        except Exception:
                            f_args = {}
                    if f_name:
                        results.append({"name": f_name, "arguments": f_args})
                continue

            # Standard {"name": "...", "arguments": {...}} format
            if "name" in item:
                f_name = item["name"]
                f_args = item.get("arguments", {})
                if isinstance(f_args, str):
                    try:
                        f_args = json.loads(f_args)
                    except Exception:
                        f_args = {}
                results.append({"name": f_name, "arguments": f_args})
                continue

            # Compact schema: action/aksiyon, target/hedef
            action = (item.get("action") or item.get("aksiyon") or item.get("tool") or item.get("cmd") or "").lower().strip()
            target = (item.get("target") or item.get("hedef") or item.get("item") or item.get("block") or "").strip()
            count = item.get("count") or item.get("sayi") or item.get("miktar") or 1
            try:
                count = int(count)
            except Exception:
                count = 1

            if not action:
                continue

            norm_target = normalize_item_alias(target)

            if action in ("mine", "collect", "maden", "topla", "kaz"):
                results.append({
                    "name": "collect_block",
                    "arguments": {"block_name": norm_target or "log", "count": count}
                })
            elif action in ("craft", "uret", "yap"):
                if norm_target:
                    results.append({
                        "name": "craft_item",
                        "arguments": {"item_name": norm_target, "count": count}
                    })
            elif action in ("smelt", "erit", "pisir"):
                results.append({
                    "name": "smelt_item",
                    "arguments": {"input_item": norm_target or "raw_iron", "count": count}
                })
            elif action in ("attack", "kill", "saldir", "oldur"):
                # Attack vs Block disambiguation
                if any(k in norm_target.lower() for k in BLOCK_KEYWORDS):
                    results.append({
                        "name": "collect_block",
                        "arguments": {"block_name": norm_target, "count": count}
                    })
                else:
                    results.append({
                        "name": "attack_target",
                        "arguments": {"target_name": norm_target or "zombie"}
                    })
            elif action in ("eat", "ye"):
                results.append({"name": "eat_food", "arguments": {}})
            elif action in ("sleep", "uyu", "yat"):
                results.append({"name": "sleep_in_bed", "arguments": {}})
            elif action in ("fish", "balik"):
                results.append({"name": "catch_fish", "arguments": {"count": 2}})
            elif action in ("goto", "git", "walk"):
                coords = re.findall(r"-?\d+", str(target))
                if len(coords) >= 3:
                    results.append({
                        "name": "go_to_coordinates",
                        "arguments": {"x": int(coords[0]), "y": int(coords[1]), "z": int(coords[2])}
                    })
                elif "x" in item and "y" in item and "z" in item:
                    results.append({
                        "name": "go_to_coordinates",
                        "arguments": {"x": int(item["x"]), "y": int(item["y"]), "z": int(item["z"])}
                    })
                else:
                    results.append({
                        "name": "go_to_coordinates",
                        "arguments": {"target_player": target or "Omer"}
                    })
            elif action in ("shelter", "build", "siginak", "insaat"):
                if "portal" in target.lower():
                    results.append({"name": "build_nether_portal", "arguments": {}})
                else:
                    results.append({"name": "build_shelter", "arguments": {"mode": "auto"}})

        # Sanitize arguments in all recovered results
        sanitized = []
        for call in results:
            c_name = call.get("name", "")
            args = call.get("arguments", {})
            if not isinstance(args, dict):
                args = {}

            for key in ("item_name", "block_name", "input_item", "target_name"):
                if key in args and isinstance(args[key], str):
                    args[key] = normalize_item_alias(strip_cjk(args[key]))

            # Remap attack_target on block keyword
            if c_name in ("attack", "attack_target"):
                t_name = args.get("target_name", "")
                if any(k in t_name.lower() for k in BLOCK_KEYWORDS):
                    c_name = "collect_block"
                    args = {"block_name": t_name, "count": 1}

            sanitized.append({"name": c_name, "arguments": args})

        return sanitized

    async def ensure_session(self) -> aiohttp.ClientSession:
        """Reuses persistent aiohttp session for connection pooling and fast Ollama inference."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def initialize(self):
        """Initialize persistent aiohttp session."""
        await self.ensure_session()
        logger.info("✅ Ollama session initialized.")

    async def shutdown(self):
        """Graceful shutdown of session."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("🛑 Ollama session closed.")

    async def close(self):
        """Alias for shutdown."""
        await self.shutdown()

    async def check_health(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            session = await self.ensure_session()
            async with session.get(f"{self.base_url}/api/tags", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    logger.info(f"✅ Ollama active. Available models: {models}")
                    if not any(self.model in m for m in models):
                        logger.warning(
                            f"⚠️ '{self.model}' model not found! "
                            f"Run: ollama run {self.model}"
                        )
                    try:
                        preload_payload = {
                            "model": self.model,
                            "keep_alive": -1,
                            "options": dict(OLLAMA_MODEL_OPTIONS)
                        }
                        logger.info(f"⚡ Preloading '{self.model}' into GPU VRAM (zero-latency warmup, timeout 60s)...")
                        async with session.post(f"{self.base_url}/api/generate", json=preload_payload, timeout=60) as warm_resp:
                            if warm_resp.status == 200:
                                logger.info(f"🔥 Model '{self.model}' pinned to RTX 3060 GPU VRAM!")
                    except Exception as warm_err:
                        logger.debug(f"Preload info: {warm_err}")
                    return True
                else:
                    logger.error(f"❌ Ollama returned HTTP {resp.status}.")
                    return False
        except Exception as e:
            logger.error(f"❌ Could not connect to Ollama service ({self.base_url}): {e}")
            return False

    async def process_chat(
        self,
        sender: str,
        message: str,
        state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Process chat message with optimized prompting, CJK stripping, and JSON recovery."""
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

        payload = {
            "model": self.model,
            "messages": messages,
            "tools": MINECRAFT_TOOLS,
            "stream": False,
            "keep_alive": -1,        # Keep pinned in GPU VRAM indefinitely
            "options": dict(OLLAMA_MODEL_OPTIONS)
        }

        self.llm_calls_count += 1
        try:
            session = await self.ensure_session()
            start_time = time.time()

            async with session.post(
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
                    logger.error(f"❌ Ollama API error ({resp.status}): {err_text[:200]}")
                    return {"text": "LLM error - using fallback.", "tool_calls": []}

                data = await resp.json()
                msg = data.get("message", {})
                response_text = strip_cjk(msg.get("content", "")).strip()
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

                        # Normalize argument values with normalize_item_alias and strip_cjk
                        for key in ("item_name", "block_name", "input_item", "target_name"):
                            if key in args and isinstance(args[key], str):
                                args[key] = normalize_item_alias(strip_cjk(args[key]))

                    if func_name:
                        # Remap attack_target if block
                        if func_name in ("attack", "attack_target"):
                            target_val = args.get("target_name", "")
                            if any(k in target_val.lower() for k in BLOCK_KEYWORDS):
                                func_name = "collect_block"
                                args = {"block_name": target_val, "count": 1}

                        parsed_tools.append({
                            "name": func_name,
                            "arguments": args
                        })

                # If no native tool calls parsed, attempt 4-layer JSON text recovery
                if not parsed_tools and response_text:
                    recovered = OllamaBrain.recover_tool_calls_from_text(response_text)
                    if recovered:
                        parsed_tools.extend(recovered)
                        logger.info(f"✨ Recovered {len(recovered)} tool call(s) from text response.")

                self.llm_tool_call_count += len(parsed_tools)

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
            self.llm_timeouts += 1
            timeout_rate = self.llm_timeouts / max(1, self.llm_calls_count)
            logger.error("⏱️ Ollama timeout (20s).")
            if timeout_rate > 0.30 and self.llm_calls_count >= 3:
                logger.warning(
                    f"⚠️ [LLM Timeout Alert] Ollama timeout rate is {timeout_rate:.1%} (> 30% threshold)! "
                    f"(Timeouts: {self.llm_timeouts}/{self.llm_calls_count})"
                )
            return {"text": "LLM timeout.", "tool_calls": []}
        except Exception as e:
            logger.error(f"❌ Ollama error: {e}")
            return {"text": "LLM connection error.", "tool_calls": []}

    def get_average_latency(self) -> float:
        """Get average LLM call latency."""
        if not self._llm_call_latency:
            return 0.0
        return sum(self._llm_call_latency) / len(self._llm_call_latency)

    def get_metrics(self) -> Dict[str, Any]:
        """Get LLM performance and timeout metrics."""
        timeout_rate = round(self.llm_timeouts / max(1, self.llm_calls_count), 3) if self.llm_calls_count > 0 else 0.0
        return {
            "llm_timeouts": self.llm_timeouts,
            "llm_calls_count": self.llm_calls_count,
            "llm_tool_call_count": self.llm_tool_call_count,
            "fallback_count": self.fallback_count,
            "llm_timeout_rate": timeout_rate,
        }
