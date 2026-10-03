"""Universal shelter, bunker, and self-enclosure decision engine for Minecraft."""
from typing import Dict, Any, List, Optional, Tuple

# Comprehensive list of solid, blast-resistant, and structural building blocks in Minecraft
SOLID_BUILDING_BLOCKS = [
    # Stones & Cobblestones
    "cobblestone", "cobbled_deepslate", "stone", "deepslate", "blackstone",
    "granite", "diorite", "andesite", "tuff", "calcite", "dripstone_block",
    "stone_bricks", "deepslate_bricks", "mossy_cobblestone", "bricks", "mud_bricks",
    # Dimension Blocks
    "netherrack", "end_stone", "basalt", "polished_blackstone", "sandstone", "red_sandstone",
    # Earth & Dirt Variants
    "dirt", "coarse_dirt", "rooted_dirt", "mud", "packed_mud",
    # Wood Planks (all variants)
    "oak_planks", "spruce_planks", "birch_planks", "jungle_planks", "acacia_planks",
    "dark_oak_planks", "mangrove_planks", "cherry_planks", "bamboo_planks",
    "crimson_planks", "warped_planks"
]


def is_usable_shelter_block(item_name: str) -> bool:
    """Checks if an item is a solid building block that can be placed as a protective wall."""
    if not item_name:
        return False
    name_clean = item_name.lower().strip()
    if name_clean in SOLID_BUILDING_BLOCKS:
        return True
    if any(k in name_clean for k in ("planks", "stone", "cobble", "brick", "dirt", "mud")):
        return True
    return False


def get_usable_building_blocks(inventory: Dict[str, int]) -> List[Tuple[str, int]]:
    """Returns all available solid blocks sorted by quantity descending."""
    usable = []
    for item_name, count in inventory.items():
        if count > 0 and is_usable_shelter_block(item_name):
            usable.append((item_name, count))
    usable.sort(key=lambda x: x[1], reverse=True)
    return usable


def calculate_total_building_blocks(inventory: Dict[str, int]) -> int:
    """Calculates total quantity of all solid building blocks held in inventory."""
    return sum(count for item_name, count in inventory.items() if is_usable_shelter_block(item_name))


def select_shelter_strategy(inventory: Dict[str, int], state: Dict[str, Any]) -> str:
    """Determines the most effective defensive shelter structure given materials and threats.

    Strategies:
    - 'enderman_roof': 2-block-tall ceiling canopy to immobilize attacking Endermen.
    - 'emergency_box': 4 walls + 1 ceiling enclosing bot on surface (requires >= 10 blocks).
    - 'burrow': Zero-material 3-block-deep burrow hole sealed from above.
    """
    hostiles = [h.lower() for h in state.get("nearby_hostiles", [])]
    total_blocks = calculate_total_building_blocks(inventory)

    # 1. Enderman threat -> 2-block canopy roof
    if any("enderman" in h for h in hostiles):
        return "enderman_roof"

    # 2. Ample building blocks available -> Surface defensive box
    if total_blocks >= 10:
        return "emergency_box"

    # 3. Low or zero blocks -> Zero-resource burrowing (dig into terrain & seal top)
    return "burrow"


def should_break_out_of_shelter(state: Dict[str, Any]) -> bool:
    """Checks whether the bot can safely unbunker and resume normal exploration."""
    is_day = state.get("is_day", True)
    health = state.get("health", 20)
    food = state.get("food", 20)
    dimension = str(state.get("dimension", "overworld")).lower()
    hostiles = state.get("nearby_hostiles", [])

    # In Nether or End, break out once health recovers and immediate area is clear
    if "nether" in dimension or "end" in dimension:
        return health >= 16 and len(hostiles) == 0

    # In Overworld, wait for daytime and healthy stats
    if is_day and health >= 16 and food >= 14 and len(hostiles) == 0:
        return True

    return False
