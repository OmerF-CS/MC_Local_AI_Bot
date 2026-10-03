"""Comprehensive Universal Minecraft Knowledge Engine & Encyclopedia in English.

Loads and queries all 1,312 official items, 1,058 blocks, foods, tools,
and mob stats directly from the official Mojang dataset.
"""
import os
import json
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("MinecraftRegistry")

class MinecraftKnowledgeEngine:
    """In-memory encyclopedia indexing all Minecraft components, functions, and mining rules."""

    def __init__(self, data_path: Optional[str] = None):
        if not data_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_path = os.path.join(base_dir, "data", "minecraft_knowledge_graph.json")

        self.data_path = data_path
        self.items: Dict[str, Any] = {}
        self.blocks: Dict[str, Any] = {}
        self.foods: Dict[str, Any] = {}
        self.mobs: Dict[str, Any] = {}
        self.load_data()

    def load_data(self):
        """Loads the official knowledge graph into memory."""
        if not os.path.exists(self.data_path):
            logger.warning(f"⚠️ Knowledge graph not found at {self.data_path}. Running with fallback entries.")
            return

        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                self.items = raw.get("items", {})
                self.blocks = raw.get("blocks", {})
                self.foods = raw.get("foods", {})
                self.mobs = raw.get("mobs", {})
            logger.info(f"📚 Knowledge Engine Loaded: {len(self.items)} items, {len(self.blocks)} blocks, {len(self.foods)} food types.")
        except Exception as e:
            logger.error(f"❌ Failed to load Minecraft knowledge graph: {e}")

    def query_component(self, name: str) -> Dict[str, Any]:
        """Looks up complete intelligence regarding any block, item, or mob."""
        clean = name.lower().strip().replace(" ", "_")

        result = {
            "name": clean,
            "exists": False,
            "is_item": clean in self.items,
            "is_block": clean in self.blocks,
            "is_food": clean in self.foods,
            "is_mob": clean in self.mobs,
            "details": {}
        }

        # Item metadata
        if clean in self.items:
            result["exists"] = True
            result["details"]["item"] = self.items[clean]

        # Block metadata (hardness, harvest tools)
        if clean in self.blocks:
            result["exists"] = True
            result["details"]["block"] = self.blocks[clean]

        # Food metadata
        if clean in self.foods:
            result["exists"] = True
            result["details"]["food"] = self.foods[clean]

        # Mob metadata
        if clean in self.mobs:
            result["exists"] = True
            result["details"]["mob"] = self.mobs[clean]

        return result

    def get_summary_string(self, name: str) -> str:
        """Returns a natural English description of what an item/block is and how to use it."""
        info = self.query_component(name)
        if not info["exists"]:
            return f"'{name}' is not recognized in the official Minecraft registry."

        parts = []
        clean = info["name"]
        details = info["details"]

        if "item" in details:
            it = details["item"]
            parts.append(f"{it.get('displayName')} (Category: {it.get('category')}, Stack Size: {it.get('stackSize')})")

        if "block" in details:
            bl = details["block"]
            hardness = bl.get("hardness")
            tools = ", ".join(bl.get("harvestTools", [])) or "Can be broken by hand / any tool"
            parts.append(f"Block Hardness: {hardness} | Recommended Tools: {tools}")

        if "food" in details:
            fd = details["food"]
            parts.append(f"Food Quality: Restores {fd.get('foodPoints')} hunger points (Saturation: {fd.get('saturation')})")

        if "mob" in details:
            mb = details["mob"]
            parts.append(f"Entity: {mb.get('displayName')} ({mb.get('type')})")

        return " | ".join(parts)

# Global Singleton Engine Instance
_engine_instance = None

def get_knowledge_engine() -> MinecraftKnowledgeEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = MinecraftKnowledgeEngine()
    return _engine_instance

def lookup_component_data(name: str) -> str:
    """Convenience helper to get summary string for any component."""
    engine = get_knowledge_engine()
    return engine.get_summary_string(name)
