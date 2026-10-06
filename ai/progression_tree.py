"""Minecraft Universal Tech Tree & Tag-Aware Progression Engine in English.

Resolves material equivalents (all wood species, all stone & deepslate variants,
Nether blackstone, fuel sources) exactly as the Minecraft game engine does.
"""
from typing import Dict, Any, List, Optional

# Equivalent Material Tags (Game-Engine Compatible)
def count_equivalent_materials(tag_or_item: str, inventory: Dict[str, int]) -> int:
    """Calculates total available quantity across all equivalent variants in inventory."""
    clean_inv = {str(k).lower().strip(): int(v) for k, v in inventory.items() if isinstance(v, (int, float, str)) and str(v).isdigit()}
    log_count = sum(count for item, count in clean_inv.items() if any(k in item for k in ("log", "stem", "wood", "hyphae")))
    plank_count = sum(count for item, count in clean_inv.items() if "plank" in item)
    direct_sticks = clean_inv.get("stick", 0)

    # 1 log crafts into 4 planks
    if tag_or_item in ("planks", "wooden_planks"):
        return plank_count + (log_count * 4)

    # 1 plank crafts into 2 sticks, 1 log crafts into 8 sticks
    if tag_or_item in ("stick", "sticks"):
        return direct_sticks + (plank_count * 2) + (log_count * 8)

    if tag_or_item in ("log", "logs", "wood"):
        return log_count

    if tag_or_item in ("stone", "cobblestone", "stone_tool_materials"):
        return sum(count for item, count in inventory.items() if item in (
            "cobblestone", "cobbled_deepslate", "blackstone", "stone", "deepslate"
        ))

    if tag_or_item in ("iron", "iron_materials"):
        return inventory.get("iron_ingot", 0) + inventory.get("raw_iron", 0) + inventory.get("iron_ore", 0)

    if tag_or_item in ("raw_iron", "raw_iron_materials"):
        return inventory.get("raw_iron", 0) + inventory.get("iron_ore", 0)

    if tag_or_item in ("raw_gold", "raw_gold_materials"):
        return inventory.get("raw_gold", 0) + inventory.get("gold_ore", 0)

    if tag_or_item in ("fuel", "smelting_fuel"):
        return (
            inventory.get("coal", 0) +
            inventory.get("charcoal", 0) +
            sum(c for i, c in inventory.items() if "planks" in i or "log" in i)
        )

    return inventory.get(tag_or_item, 0)

# Complete Flexible Progression Tree
TECH_TREE: Dict[str, Dict[str, Any]] = {
    # --- SMELTED INGOTS (FURNACE) ---
    "iron_ingot": {
        "requires_tools": ["furnace"],
        "ingredients": {"raw_iron": 1, "fuel": 1},
        "description": "Smelted from raw iron or iron ore inside a furnace using coal or wood fuel."
    },
    "gold_ingot": {
        "requires_tools": ["furnace"],
        "ingredients": {"raw_gold": 1, "fuel": 1},
        "description": "Smelted from raw gold or gold ore inside a furnace using coal or wood fuel."
    },
    # --- WOODEN AGE ---
    "crafting_table": {
        "requires_tools": [],
        "ingredients": {"planks": 4},
        "description": "Essential 3x3 crafting grid. Works with any wood species."
    },
    "wooden_pickaxe": {
        "requires_tools": ["crafting_table"],
        "ingredients": {"planks": 3, "stick": 2},
        "description": "First mining tool to break stone, cobblestone, deepslate, and coal."
    },

    # --- STONE & DEEPSLATE AGE ---
    "stone_pickaxe": {
        "requires_tools": ["crafting_table", "wooden_pickaxe"],
        "ingredients": {"cobblestone": 3, "stick": 2},
        "description": "Mines iron ore and lapis lazuli. Crafted with cobblestone, cobbled deepslate, or blackstone."
    },
    "furnace": {
        "requires_tools": ["crafting_table", "wooden_pickaxe"],
        "ingredients": {"cobblestone": 8},
        "description": "Smelts raw ores and cooks food. Crafted with cobblestone, cobbled deepslate, or blackstone."
    },
    "shield": {
        "requires_tools": ["crafting_table"],
        "ingredients": {"planks": 6, "iron_ingot": 1},
        "description": "Critical defense against creepers and skeletons. Works with any planks."
    },

    # --- IRON AGE ---
    "iron_pickaxe": {
        "requires_tools": ["crafting_table", "furnace", "stone_pickaxe"],
        "ingredients": {"iron_ingot": 3, "stick": 2},
        "description": "Mines gold, redstone, and diamond ore."
    },
    "bucket": {
        "requires_tools": ["crafting_table", "furnace"],
        "ingredients": {"iron_ingot": 3},
        "description": "Crucial utility for water bucket drops (MLG) and building Nether portals with lava."
    },

    # --- DIAMOND & OBSIDIAN AGE ---
    "diamond_pickaxe": {
        "requires_tools": ["crafting_table", "iron_pickaxe"],
        "ingredients": {"diamond": 3, "stick": 2},
        "description": "Mines obsidian to build portals or enchantment tables."
    },
    "paper": {
        "requires_tools": ["crafting_table"],
        "ingredients": {"sugar_cane": 3},
        "description": "Crafted from sugar cane to make books and maps."
    },
    "book": {
        "requires_tools": ["crafting_table"],
        "ingredients": {"paper": 3, "leather": 1},
        "description": "Combined with obsidian and diamonds to craft an enchanting table."
    },
    "enchanting_table": {
        "requires_tools": ["crafting_table", "diamond_pickaxe"],
        "ingredients": {"obsidian": 4, "diamond": 2, "book": 1},
        "description": "Imbues weapons, armor, and tools with powerful magical enchantments."
    },
    "bookshelf": {
        "requires_tools": ["crafting_table"],
        "ingredients": {"book": 3, "planks": 6},
        "description": "Surrounds enchanting table to unlock up to Level 30 max enchantments."
    },

    # --- NETHER AGE ---
    "nether_portal": {
        "requires_tools": ["flint_and_steel"],
        "ingredients": {"obsidian": 10},
        "description": "Gateway to the Nether dimension."
    },
    "blaze_powder": {
        "requires_tools": [],
        "ingredients": {"blaze_rod": 1},
        "description": "Crafted from blaze rods harvested in Nether fortresses."
    },

    # --- END & ENDER DRAGON AGE ---
    "eye_of_ender": {
        "requires_tools": ["crafting_table"],
        "ingredients": {"ender_pearl": 1, "blaze_powder": 1},
        "description": "Locates the Stronghold and fills End Portal frames."
    }
}

# Grand Progression Milestones
MILESTONES = [
    {
        "stage": "WOOD",
        "target": "wooden_pickaxe",
        "check": lambda inv: any(p in inv for p in ("wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe")),
        "next_hint": "Gather logs (any tree species), craft planks and sticks, then craft a wooden pickaxe."
    },
    {
        "stage": "STONE",
        "target": "stone_pickaxe",
        "check": lambda inv: any(p in inv for p in ("stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe")),
        "next_hint": "Mine stone, cobblestone, or deepslate. Craft a stone pickaxe."
    },
    {
        "stage": "FURNACE",
        "target": "furnace",
        "check": lambda inv: "furnace" in inv,
        "next_hint": "Mine 8 cobblestone or cobbled deepslate and craft a furnace for smelting."
    },
    {
        "stage": "IRON_GEAR",
        "target": "iron_pickaxe",
        "check": lambda inv: any(p in inv for p in ("iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe")),
        "next_hint": "Mine iron ore / deepslate iron ore in caves, smelt into ingots, and craft an iron pickaxe and shield."
    },
    {
        "stage": "DIAMOND",
        "target": "diamond_pickaxe",
        "check": lambda inv: "diamond_pickaxe" in inv or "netherite_pickaxe" in inv,
        "next_hint": "Descend to depth Y: -58. Mine diamond ore and craft a diamond pickaxe."
    },
    {
        "stage": "NETHER",
        "target": "nether_portal",
        "check": lambda inv: inv.get("blaze_rod", 0) >= 6,
        "next_hint": "Construct an obsidian portal or cast it with lava + water. In the Nether, defeat Blazes for 6+ rods."
    },
    {
        "stage": "EYE_OF_ENDER",
        "target": "eye_of_ender",
        "check": lambda inv: inv.get("eye_of_ender", 0) >= 12,
        "next_hint": "Combine Ender Pearls with Blaze Powder to craft 12 Eyes of Ender."
    },
    {
        "stage": "THE_END",
        "target": "ender_dragon",
        "check": lambda inv: False,
        "next_hint": "Toss Eyes of Ender to locate the Stronghold, activate the portal, destroy the End Crystals, and slay the Ender Dragon!"
    },
    {
        "stage": "DESTROY_CRYSTALS",
        "target": "end_crystal",
        "check": lambda inv: False,
        "next_hint": "Destroy all End Crystals atop obsidian pillars using bow/arrows or towering with shields."
    },
    {
        "stage": "SLAY_DRAGON",
        "target": "fight_ender_dragon",
        "check": lambda inv: False,
        "next_hint": "Engage the Ender Dragon with bow or burst attacks when it perches at the central bedrock portal."
    },
    {
        "stage": "GAME_VICTORY",
        "target": "enter_exit_portal",
        "check": lambda inv: False,
        "next_hint": "Collect the fallen Ender Dragon XP drops and leap into the central exit portal to beat the game!"
    }
]

def get_current_progression_goal(inventory: Dict[str, int], state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Evaluates inventory and world state to return the active speedrun progression goal."""
    if state:
        dimension = str(state.get("dimension", "overworld")).lower()
        if "end" in dimension:
            if state.get("dragon_defeated", False):
                return next(m for m in MILESTONES if m["stage"] == "GAME_VICTORY")
            crystals_count = state.get("end_crystals_count", 0)
            if crystals_count > 0:
                return next(m for m in MILESTONES if m["stage"] == "DESTROY_CRYSTALS")
            return next(m for m in MILESTONES if m["stage"] == "SLAY_DRAGON")

    for milestone in MILESTONES:
        if not milestone["check"](inventory):
            return milestone
    return MILESTONES[-1]

def resolve_missing_ingredients(target_item: str, inventory: Dict[str, int]) -> List[str]:
    """Computes missing materials using universal tag equivalents (any wood, any stone)."""
    recipe = TECH_TREE.get(target_item)
    if not recipe:
        return []

    missing = []
    wood_deficit_reported = False
    for ing_tag, count in recipe["ingredients"].items():
        available = count_equivalent_materials(ing_tag, inventory)
        if available < count:
            if ing_tag in ("planks", "wooden_planks", "stick", "sticks"):
                if not wood_deficit_reported:
                    missing.append("3x wood log")
                    wood_deficit_reported = True
            else:
                readable_tag = ing_tag.replace("_", " ")
                missing.append(f"{count - available}x {readable_tag}")
    return missing
