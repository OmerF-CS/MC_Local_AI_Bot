"""Player Style Archetypes & Persona Strategies."""
from enum import Enum
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("PlayerStyles")


class PlayerStyle(Enum):
    SPEEDRUNNER = "speedrunner"
    EXPLORER_LOOTER = "explorer"
    HOMESTEAD_BUILDER = "builder"
    COMBAT_CRAWLER = "combat"

    @classmethod
    def from_str(cls, value: str) -> "PlayerStyle":
        v = str(value).strip().lower()
        if "speed" in v or "rush" in v:
            return cls.SPEEDRUNNER
        if "explore" in v or "loot" in v:
            return cls.EXPLORER_LOOTER
        if "build" in v or "home" in v or "farm" in v:
            return cls.HOMESTEAD_BUILDER
        if "combat" in v or "fight" in v or "crawl" in v:
            return cls.COMBAT_CRAWLER
        return cls.SPEEDRUNNER


class StyleStrategy:
    """Calculates tactical biases and gear adjustments based on player persona archetype."""

    def get_style_milestone_bias(
        self,
        style: PlayerStyle,
        inv_dict: Dict[str, int],
        state: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Returns priority action adjustments depending on style, or None."""
        if style == PlayerStyle.HOMESTEAD_BUILDER:
            # Homestead builder prioritizes hoe, fence, chest
            has_hoe = any("hoe" in k for k in inv_dict.keys())
            if not has_hoe:
                cobble = inv_dict.get("cobblestone", 0) + inv_dict.get("cobbled_deepslate", 0)
                planks = inv_dict.get("planks", 0) + inv_dict.get("oak_planks", 0) + inv_dict.get("birch_planks", 0)
                if cobble >= 2:
                    return {
                        "action": "craft_item",
                        "arguments": {"item_name": "stone_hoe", "count": 1},
                        "reason": "Homestead builder prioritizing stone hoe for agriculture"
                    }
                elif planks >= 2 or inv_dict.get("log", 0) >= 1:
                    return {
                        "action": "craft_item",
                        "arguments": {"item_name": "wooden_hoe", "count": 1},
                        "reason": "Homestead builder prioritizing wooden hoe for agriculture"
                    }

            has_chest = inv_dict.get("chest", 0) > 0
            planks = inv_dict.get("planks", 0) + inv_dict.get("oak_planks", 0) + inv_dict.get("birch_planks", 0)
            logs = inv_dict.get("log", 0) + inv_dict.get("wood", 0)
            if not has_chest and (planks >= 8 or logs >= 2):
                return {
                    "action": "craft_item",
                    "arguments": {"item_name": "chest", "count": 1},
                    "reason": "Homestead builder prioritizing chest for base resource storage"
                }

            has_fence = any("fence" in k for k in inv_dict.keys())
            if not has_fence and planks >= 4:
                return {
                    "action": "craft_item",
                    "arguments": {"item_name": "oak_fence", "count": 3},
                    "reason": "Homestead builder prioritizing fencing for animal pens"
                }

        elif style == PlayerStyle.EXPLORER_LOOTER:
            # Explorer looter prioritizes boat, scout_high_ground
            has_boat = any("boat" in k for k in inv_dict.keys())
            planks = inv_dict.get("planks", 0) + inv_dict.get("oak_planks", 0) + inv_dict.get("birch_planks", 0)
            logs = inv_dict.get("log", 0) + inv_dict.get("wood", 0)
            if not has_boat and (planks >= 5 or logs >= 2):
                return {
                    "action": "craft_item",
                    "arguments": {"item_name": "oak_boat", "count": 1},
                    "reason": "Explorer looter prioritizing boat for rapid ocean/river traversal"
                }

            # If no high ground scouted recently or in open biome
            if not state.get("scouted_high_ground", False) and not state.get("landmarks"):
                return {
                    "action": "scout_high_ground",
                    "arguments": {"radius": 30},
                    "reason": "Explorer looter scouting high ground for structures and landmarks"
                }

        elif style == PlayerStyle.COMBAT_CRAWLER:
            # Combat crawler prioritizes shield, iron_sword, bow
            has_shield = inv_dict.get("shield", 0) > 0
            iron = inv_dict.get("iron_ingot", 0)
            planks = inv_dict.get("planks", 0) + inv_dict.get("oak_planks", 0) + inv_dict.get("birch_planks", 0)
            if not has_shield and iron >= 1 and planks >= 6:
                return {
                    "action": "craft_item",
                    "arguments": {"item_name": "shield", "count": 1},
                    "reason": "Combat crawler prioritizing shield for active mob defense"
                }

            has_iron_sword = inv_dict.get("iron_sword", 0) > 0 or inv_dict.get("diamond_sword", 0) > 0
            if not has_iron_sword and iron >= 2:
                return {
                    "action": "craft_item",
                    "arguments": {"item_name": "iron_sword", "count": 1},
                    "reason": "Combat crawler prioritizing iron sword for weapon damage"
                }

            has_bow = inv_dict.get("bow", 0) > 0
            strings = inv_dict.get("string", 0)
            sticks = inv_dict.get("stick", 0)
            if not has_bow and strings >= 3 and sticks >= 3:
                return {
                    "action": "craft_item",
                    "arguments": {"item_name": "bow", "count": 1},
                    "reason": "Combat crawler prioritizing bow for ranged combat"
                }

        elif style == PlayerStyle.SPEEDRUNNER:
            # Speedrunner focuses on minimal tech rush, bed bombing, and dragon progression
            return None

        return None
