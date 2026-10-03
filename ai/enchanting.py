"""Minecraft Autonomous Enchanting & Experience (XP) Progression Engine in English.

Evaluates XP levels, lapis lazuli catalyst availability, gear tiers,
bookshelf positioning geometry, and optimal enchantment prioritization.
"""
from typing import Dict, Any, List, Optional, Tuple

# Priority order for selecting items to enchant
ENCHANTABLE_GEAR_PRIORITY: List[str] = [
    # Top Tier: Diamond Weapons & Armor
    "diamond_sword",
    "diamond_chestplate",
    "diamond_leggings",
    "diamond_helmet",
    "diamond_boots",
    "bow",
    "diamond_pickaxe",
    "diamond_axe",
    # Mid Tier: Iron Equipment
    "iron_sword",
    "iron_chestplate",
    "iron_leggings",
    "iron_helmet",
    "iron_boots",
    "iron_pickaxe",
    "crossbow",
    "shield"
]

PREFERRED_ENCHANTMENTS: Dict[str, List[str]] = {
    "sword": ["sharpness", "looting", "unbreaking", "sweeping", "fire_aspect"],
    "chestplate": ["protection", "unbreaking", "thorns"],
    "leggings": ["protection", "unbreaking", "swift_sneak"],
    "helmet": ["protection", "respiration", "aqua_affinity", "unbreaking"],
    "boots": ["protection", "feather_falling", "depth_strider", "unbreaking"],
    "bow": ["power", "infinity", "punch", "unbreaking", "flame"],
    "pickaxe": ["efficiency", "fortune", "unbreaking", "silk_touch"],
    "axe": ["sharpness", "efficiency", "unbreaking"]
}

def calculate_enchanting_readiness(inventory: Dict[str, int], xp_level: int) -> Dict[str, Any]:
    """Evaluates whether the bot is ready to enchant gear.
    
    Returns readiness status, available lapis, best gear candidate, and recommendations.
    """
    has_table = (
        inventory.get("enchanting_table", 0) > 0 or
        (inventory.get("obsidian", 0) >= 4 and inventory.get("diamond", 0) >= 2 and inventory.get("book", 0) >= 1)
    )
    lapis_count = inventory.get("lapis_lazuli", 0)
    best_candidate = get_best_item_to_enchant(inventory)
    
    is_ready = bool(best_candidate and (has_table or inventory.get("enchanting_table", 0) > 0) and lapis_count >= 1 and xp_level >= 1)
    
    tier = 1
    if xp_level >= 30 and lapis_count >= 3:
        tier = 3
    elif xp_level >= 15 and lapis_count >= 2:
        tier = 2
        
    return {
        "ready": is_ready,
        "xp_level": xp_level,
        "lapis_count": lapis_count,
        "has_enchanting_table": has_table,
        "target_gear": best_candidate,
        "recommended_tier": tier,
        "bookshelves_available": inventory.get("bookshelf", 0)
    }

def get_best_item_to_enchant(inventory: Dict[str, int]) -> Optional[str]:
    """Identifies the highest priority unenchanted or upgradable equipment item in inventory."""
    for gear_name in ENCHANTABLE_GEAR_PRIORITY:
        if inventory.get(gear_name, 0) > 0:
            return gear_name
    return None

def calculate_missing_enchanting_materials(inventory: Dict[str, int], xp_level: int) -> List[str]:
    """Returns missing items needed to craft an enchanting table and enchant gear."""
    missing: List[str] = []
    
    if inventory.get("enchanting_table", 0) == 0:
        obsidian_needed = max(0, 4 - inventory.get("obsidian", 0))
        diamonds_needed = max(0, 2 - inventory.get("diamond", 0))
        books_needed = max(0, 1 - inventory.get("book", 0))
        
        if obsidian_needed > 0:
            missing.append(f"{obsidian_needed}x obsidian")
        if diamonds_needed > 0:
            missing.append(f"{diamonds_needed}x diamond")
        if books_needed > 0:
            # Check if paper and leather can be crafted
            sugar_cane = inventory.get("sugar_cane", 0)
            paper = inventory.get("paper", 0)
            leather = inventory.get("leather", 0)
            if paper < 3 and sugar_cane < 3:
                missing.append(f"{3 - paper}x paper (or {3 - sugar_cane}x sugar_cane)")
            if leather < 1:
                missing.append("1x leather")
                
    if inventory.get("lapis_lazuli", 0) < 3:
        missing.append(f"{3 - inventory.get('lapis_lazuli', 0)}x lapis_lazuli")
        
    if xp_level < 15:
        missing.append(f"{15 - xp_level} more XP levels (mine coal/lapis or smelt food)")
        
    return missing

def should_prioritize_enchanting(inventory: Dict[str, int], xp_level: int, dimension: str = "overworld") -> bool:
    """Determines if the bot should proactively pause mining/travel to enchant gear.
    
    Triggered when:
    - Bot has level 15+ XP, lapis lazuli, and diamond gear before challenging the Nether or End.
    - Bot has an enchanting table in inventory or nearby.
    """
    has_lapis = inventory.get("lapis_lazuli", 0) >= 2
    has_diamond_gear = any(inventory.get(g, 0) > 0 for g in [
        "diamond_sword", "diamond_chestplate", "diamond_leggings", "diamond_helmet", "diamond_boots", "diamond_pickaxe"
    ])
    has_table = (
        inventory.get("enchanting_table", 0) > 0 or
        (inventory.get("obsidian", 0) >= 4 and inventory.get("diamond", 0) >= 2 and inventory.get("book", 0) >= 1)
    )
    
    # Critical buff window before entering End or Nether boss fights
    if has_diamond_gear and has_lapis and has_table and xp_level >= 15:
        return True
        
    return False

def get_bookshelf_positions(center_x: int, center_y: int, center_z: int, max_count: int = 15) -> List[Tuple[int, int, int]]:
    """Generates standard 5x5 bookshelf placement coordinates with a 1-block air gap around table.
    
    Minecraft mechanics require bookshelves to be exactly 1 block away horizontally
    at Y or Y+1 with air in between for maximum level 30 enchanting power.
    """
    positions: List[Tuple[int, int, int]] = []
    # 5x5 perimeter offsets: dx, dz in {-2, 2} or combinations
    offsets_2d: List[Tuple[int, int]] = [
        (-2, -2), (-2, -1), (-2, 0), (-2, 1), (-2, 2),
        (2, -2),  (2, -1),  (2, 0),  (2, 1),  (2, 2),
        (-1, -2), (0, -2),  (1, -2),
        (-1, 2),  (0, 2),   (1, 2)
    ]
    
    # First layer at table height Y
    for dx, dz in offsets_2d:
        if len(positions) >= max_count:
            break
        positions.append((center_x + dx, center_y, center_z + dz))
        
    # Second layer at table height Y+1 if more needed
    for dx, dz in offsets_2d:
        if len(positions) >= max_count:
            break
        positions.append((center_x + dx, center_y + 1, center_z + dz))
        
    return positions[:max_count]
