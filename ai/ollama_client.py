"""Ollama Yerel Yapay Zeka İstemcisi ve Tool Calling Yöneticisi."""
import asyncio
import json
from typing import Dict, Any, List, Optional
import aiohttp

from utils.logger import get_logger
from ai.tools import MINECRAFT_TOOLS
from ai.prompts import MINECRAFT_SYSTEM_PROMPT

logger = get_logger("OllamaClient")

class OllamaBrain:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:7b", bot_name: str = "AIAssistant", bot_owner: str = "Omer"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.bot_name = bot_name
        self.bot_owner = bot_owner
        self.chat_history: List[Dict[str, Any]] = []
        self.max_history = 12

    async def check_health(self) -> bool:
        """Ollama servisinin ayakta olup olmadığını ve modelin varlığını kontrol eder."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/tags", timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m.get("name") for m in data.get("models", [])]
                        logger.info(f"✅ Ollama aktif. Mevcut modeller: {models}")
                        if not any(self.model in m for m in models):
                            logger.warning(f"⚠️ Dikkat: '{self.model}' modeli Ollama'da bulunamadı! 'ollama run {self.model}' komutunu çalıştırdığınızdan emin olun.")
                        return True
                    else:
                        logger.error(f"❌ Ollama HTTP {resp.status} döndürdü.")
                        return False
        except Exception as e:
            logger.error(f"❌ Ollama servisine bağlanılamadı ({self.base_url}): {e}")
            return False

    def build_system_prompt(self, state: Optional[Dict[str, Any]] = None) -> str:
        """Dynamically builds system prompt injecting bot vitals, inventory, entities, and vision."""
        if not state:
            state = {}

        health = state.get("health", 20)
        food = state.get("food", 20)
        hearts = round(health / 2, 1)
        pos = state.get("position", {"x": 0, "y": 0, "z": 0})
        pos_str = f"X: {pos.get('x', 0):.1f}, Y: {pos.get('y', 0):.1f}, Z: {pos.get('z', 0):.1f}"
        inventory = state.get("inventory_summary", "Empty")
        
        # Entities & Threats Radar (32m)
        nearby_entities = (
            state.get("nearby_entities_summary") or 
            ", ".join(state.get("nearby_hostiles", [])) or 
            "No entities detected within 32m."
        )
        nearby_players = ", ".join(state.get("nearby_players", [])) or "None nearby"

        # Vision & 3D Environment (64m field)
        vision = state.get("vision_metrics", {})
        light = vision.get("light_level", 15)
        alt_zone = vision.get("altitude_zone", "Surface")
        biome = state.get("biome", "unknown")
        
        vis_res = state.get("visible_resources", {})
        if vis_res:
            res_list = [f"{k} ({v['total_found']}x total, {v['visible_exposed']} air-exposed, {v['closest_distance']}m away)" for k, v in vis_res.items()]
            res_str = ", ".join(res_list)
        else:
            res_str = "No key resources detected within 64m."

        vision_overview = f"Radius: 64 blocks | Biome: {biome} | Altitude: {alt_zone} (Y: {pos.get('y', 0):.0f}) | Light: {light}/15 | Visible Resources: {res_str}"

        is_day = state.get("is_day", True)
        time_status = "Daytime (Safe)" if is_day else "Nighttime (Hostile Mobs Active!)"
        guard_status = "Guarding Partner" if state.get("is_guarding", False) else "Autonomous Free Roam"

        return MINECRAFT_SYSTEM_PROMPT.format(
            bot_name=self.bot_name,
            bot_owner=self.bot_owner,
            health=health,
            hearts=hearts,
            food=food,
            time_status=time_status,
            guard_status=guard_status,
            position=pos_str,
            biome=biome,
            inventory=inventory,
            nearby_entities=nearby_entities,
            nearby_players=nearby_players,
            vision_overview=vision_overview,
            carried_tools=state.get("carried_tools", "None")
        )

    async def process_chat(self, sender: str, message: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Oyuncudan gelen mesajı değerlendirir. 
        Dönüş: {
            "text": str,           # Sohbette söylenecek söz (varsa)
            "tool_calls": List[dict] # Yürütülecek Mineflayer eylemleri (varsa)
        }
        """
        system_content = self.build_system_prompt(state)
        
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
            "options": {
                "temperature": 0.4
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/api/chat", json=payload, timeout=25) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        logger.error(f"❌ Ollama API hatası ({resp.status}): {err_text}")
                        return {"text": "Şu an düşüncelerimi toparlayamıyorum (LLM Hatası).", "tool_calls": []}

                    data = await resp.json()
                    msg = data.get("message", {})
                    response_text = msg.get("content", "").strip()
                    tool_calls = msg.get("tool_calls", [])

                    # Asistan yanıtını geçmişe ekle
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

                        # Flatten nested LLM arguments like {'arguments': {...}}
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

                    logger.info(f"🤖 Ollama Response: '{response_text}' | Tools Dispatched: {parsed_tools}")
                    return {
                        "text": response_text,
                        "tool_calls": parsed_tools
                    }

        except asyncio.TimeoutError:
            logger.error("⏱️ Ollama response timed out.")
            return {"text": "Thinking timed out. Standing by.", "tool_calls": []}
        except Exception as e:
            logger.error(f"❌ Ollama communication error: {e}", exc_info=True)
            return {"text": "Encountered a connection issue.", "tool_calls": []}
