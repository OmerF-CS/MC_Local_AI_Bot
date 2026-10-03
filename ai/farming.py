"""Agricultural and sustainable food decision engine for Minecraft."""
from typing import Dict, Any, List, Optional

# Equivalent crop names and mature age thresholds
CROP_TYPES = {
    "wheat": {"seed": "wheat_seeds", "mature_age": 7, "harvest_item": "wheat"},
    "carrots": {"seed": "carrot", "mature_age": 7, "harvest_item": "carrot"},
    "potatoes": {"seed": "potato", "mature_age": 7, "harvest_item": "potato"},
    "beetroots": {"seed": "beetroot_seeds", "mature_age": 3, "harvest_item": "beetroot"}
}

# Agricultural tools
HOE_TYPES = ["netherite_hoe", "diamond_hoe", "iron_hoe", "stone_hoe", "wooden_hoe"]


def calculate_food_points(inventory: Dict[str, int]) -> int:
    """Calculates total potential hunger restoration points from current inventory."""
    nutrition_map = {
        "bread": 5,
        "cooked_beef": 8,
        "cooked_porkchop": 8,
        "cooked_mutton": 6,
        "cooked_chicken": 6,
        "cooked_salmon": 6,
        "cooked_cod": 5,
        "baked_potato": 5,
        "golden_apple": 4,
        "apple": 4,
        "carrot": 3,
        "sweet_berries": 2,
        "melon_slice": 2,
        # Convert raw materials to potential food
        "wheat": 5 / 3,       # 3 wheat = 1 bread (5 hunger)
        "hay_block": 15       # 1 hay block = 9 wheat = 3 bread (15 hunger)
    }

    total_points = 0
    for item, count in inventory.items():
        if item in nutrition_map:
            total_points += int(nutrition_map[item] * count)
    return total_points


def should_prioritize_farming(inventory: Dict[str, int], state: Dict[str, Any]) -> bool:
    """Determines whether bot should harvest hay bales or farm crops."""
    food_points = calculate_food_points(inventory)
    food_level = state.get("food", 20)

    # 1. Critical food shortage: less than 15 total food points in reserve
    if food_points < 15 or food_level < 14:
        vis_res = state.get("visible_resources", {})
        # If hay bales or crops are visible in the vicinity
        if vis_res.get("hay_block") or any(k in vis_res for k in CROP_TYPES):
            return True

    # 2. Opportunistic farming: abundant hay bales visible nearby (village found!)
    vis_res = state.get("visible_resources", {})
    if vis_res.get("hay_block", {}).get("total_found", 0) >= 1:
        return True

    return False


def get_farming_action_plan(inventory: Dict[str, int], state: Dict[str, Any]) -> Dict[str, Any]:
    """Generates the recommended farming priority action."""
    vis_res = state.get("visible_resources", {})

    # Priority 1: Hay Bale Harvest (Massive food yield: 1 hay = 3 bread)
    if vis_res.get("hay_block", {}).get("total_found", 0) > 0:
        return {
            "name": "farm_crops",
            "arguments": {"action_type": "harvest_hay_bales"}
        }

    # Priority 2: Harvest Ripe Crops
    for crop_name in CROP_TYPES:
        if vis_res.get(crop_name, {}).get("total_found", 0) > 0:
            return {
                "name": "farm_crops",
                "arguments": {"action_type": "harvest_ripe_crops"}
            }

    # Priority 3: Till & Plant if seeds and hoe exist
    has_hoe = any(h in inventory for h in HOE_TYPES)
    has_seeds = any(crop["seed"] in inventory for crop in CROP_TYPES.values())
    if has_hoe and has_seeds:
        return {
            "name": "farm_crops",
            "arguments": {"action_type": "till_and_plant"}
        }

    # Fallback: General farming scan
    return {
        "name": "farm_crops",
        "arguments": {"action_type": "auto"}
    }
