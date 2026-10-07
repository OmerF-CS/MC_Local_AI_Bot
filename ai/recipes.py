"""Minecraft Crafting Recipes & Knowledge Registry in English.

Provides comprehensive recipe definitions, material requirements, output counts,
and 3x3 crafting table requirement flags for all vanilla survival items.
"""
from typing import Optional, Dict, Any, List

RECIPES: Dict[str, Dict[str, Any]] = {
    # --- BASIC INVENTORY (2x2 GRID) RECIPES ---
    "wooden_planks": {
        "name": "Wooden Planks",
        "ingredients": "1 Wood Log (any species)",
        "output_count": 4,
        "requires_table": False,
        "description": "Fundamental construction and crafting base crafted from any tree log."
    },
    "planks": {
        "name": "Wooden Planks",
        "ingredients": "1 Wood Log (any species)",
        "output_count": 4,
        "requires_table": False,
        "description": "Fundamental construction and crafting base crafted from any tree log."
    },
    "stick": {
        "name": "Stick",
        "ingredients": "2 Wooden Planks",
        "output_count": 4,
        "requires_table": False,
        "description": "Essential component for handles of all tools, torches, and weapons."
    },
    "crafting_table": {
        "name": "Crafting Table",
        "ingredients": "4 Wooden Planks (any wood type)",
        "output_count": 1,
        "requires_table": False,
        "description": "Provides a 3x3 crafting grid essential for almost all advanced tools and items."
    },
    "torch": {
        "name": "Torch",
        "ingredients": "1 Coal or Charcoal + 1 Stick",
        "output_count": 4,
        "requires_table": False,
        "description": "Illuminates dark caves, tunnels, and prevents hostile mobs from spawning."
    },

    # --- MINING TOOLS (REQUIRES 3x3 CRAFTING TABLE) ---
    "wooden_pickaxe": {
        "name": "Wooden Pickaxe",
        "ingredients": "3 Wooden Planks + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Fundamental mining tool required to break and harvest stone, deepslate, and coal."
    },
    "stone_pickaxe": {
        "name": "Stone Pickaxe",
        "ingredients": "3 Cobblestone, Cobbled Deepslate, or Blackstone + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Mines iron ore, copper ore, and lapis lazuli."
    },
    "iron_pickaxe": {
        "name": "Iron Pickaxe",
        "ingredients": "3 Iron Ingots + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Mines gold, redstone, and diamond ore."
    },
    "diamond_pickaxe": {
        "name": "Diamond Pickaxe",
        "ingredients": "3 Diamonds + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Required to mine obsidian and access the Nether."
    },

    # --- WEAPONS & COMBAT GEAR (REQUIRES 3x3 CRAFTING TABLE) ---
    "wooden_sword": {
        "name": "Wooden Sword",
        "ingredients": "2 Wooden Planks + 1 Stick",
        "output_count": 1,
        "requires_table": True,
        "description": "Starter melee weapon dealing 4 attack damage."
    },
    "stone_sword": {
        "name": "Stone Sword",
        "ingredients": "2 Cobblestone + 1 Stick",
        "output_count": 1,
        "requires_table": True,
        "description": "Standard early game weapon dealing 5 attack damage."
    },
    "iron_sword": {
        "name": "Iron Sword",
        "ingredients": "2 Iron Ingots + 1 Stick",
        "output_count": 1,
        "requires_table": True,
        "description": "Reliable mid-game weapon dealing 6 attack damage."
    },
    "diamond_sword": {
        "name": "Diamond Sword",
        "ingredients": "2 Diamonds + 1 Stick",
        "output_count": 1,
        "requires_table": True,
        "description": "High damage endgame melee weapon dealing 7 attack damage."
    },
    "shield": {
        "name": "Shield",
        "ingredients": "1 Iron Ingot + 6 Wooden Planks",
        "output_count": 1,
        "requires_table": True,
        "description": "Lifesaving off-hand defense against arrows and creeper blast damage."
    },
    "bow": {
        "name": "Bow",
        "ingredients": "3 Sticks + 3 String",
        "output_count": 1,
        "requires_table": True,
        "description": "Ranged weapon essential for shooting End Crystals and airborne dragons."
    },
    "arrow": {
        "name": "Arrow",
        "ingredients": "1 Flint + 1 Stick + 1 Feather",
        "output_count": 4,
        "requires_table": True,
        "description": "Ammunition for bows and dispensers."
    },
    "crossbow": {
        "name": "Crossbow",
        "ingredients": "3 Sticks + 2 String + 1 Iron Ingot + 1 Tripwire Hook",
        "output_count": 1,
        "requires_table": True,
        "description": "Powerful ranged weapon with high velocity and enchantments like Piercing."
    },

    # --- AXES & HARVESTING TOOLS (REQUIRES 3x3 CRAFTING TABLE) ---
    "wooden_axe": {
        "name": "Wooden Axe",
        "ingredients": "3 Wooden Planks + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Chops wood quickly and disables enemy shields."
    },
    "stone_axe": {
        "name": "Stone Axe",
        "ingredients": "3 Cobblestone + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Chops wood and deals heavy 9-point critical hit damage."
    },
    "iron_axe": {
        "name": "Iron Axe",
        "ingredients": "3 Iron Ingots + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Chops trees rapidly and deals heavy single-target burst damage."
    },
    "diamond_axe": {
        "name": "Diamond Axe",
        "ingredients": "3 Diamonds + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Endgame woodcutting tool with high durability."
    },
    "wooden_shovel": {
        "name": "Wooden Shovel",
        "ingredients": "1 Wooden Plank + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Digs dirt, sand, and gravel."
    },
    "stone_shovel": {
        "name": "Stone Shovel",
        "ingredients": "1 Cobblestone + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Digs dirt, sand, gravel, and snow."
    },
    "iron_shovel": {
        "name": "Iron Shovel",
        "ingredients": "1 Iron Ingot + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Rapidly excavates soil, clay, and gravel."
    },
    "diamond_shovel": {
        "name": "Diamond Shovel",
        "ingredients": "1 Diamond + 2 Sticks",
        "output_count": 1,
        "requires_table": True,
        "description": "Instant-breaks dirt and gravel with efficiency."
    },

    # --- ARMOR SETS (REQUIRES 3x3 CRAFTING TABLE) ---
    "iron_helmet": {
        "name": "Iron Helmet",
        "ingredients": "5 Iron Ingots",
        "output_count": 1,
        "requires_table": True,
        "description": "Head protection providing +2 armor points."
    },
    "iron_chestplate": {
        "name": "Iron Chestplate",
        "ingredients": "8 Iron Ingots",
        "output_count": 1,
        "requires_table": True,
        "description": "Torso armor protection providing +6 armor points."
    },
    "iron_leggings": {
        "name": "Iron Leggings",
        "ingredients": "7 Iron Ingots",
        "output_count": 1,
        "requires_table": True,
        "description": "Leg protection providing +5 armor points."
    },
    "iron_boots": {
        "name": "Iron Boots",
        "ingredients": "4 Iron Ingots",
        "output_count": 1,
        "requires_table": True,
        "description": "Footwear providing +2 armor points and reduced fall vulnerability."
    },
    "diamond_helmet": {
        "name": "Diamond Helmet",
        "ingredients": "5 Diamonds",
        "output_count": 1,
        "requires_table": True,
        "description": "High tier headgear providing +3 armor points and armor toughness."
    },
    "diamond_chestplate": {
        "name": "Diamond Chestplate",
        "ingredients": "8 Diamonds",
        "output_count": 1,
        "requires_table": True,
        "description": "Maximum standard torso defense providing +8 armor points."
    },
    "diamond_leggings": {
        "name": "Diamond Leggings",
        "ingredients": "7 Diamonds",
        "output_count": 1,
        "requires_table": True,
        "description": "High defense leggings providing +6 armor points."
    },
    "diamond_boots": {
        "name": "Diamond Boots",
        "ingredients": "4 Diamonds",
        "output_count": 1,
        "requires_table": True,
        "description": "Foot protection providing +3 armor points and toughness."
    },

    # --- SURVIVAL STATIONS & UTILITIES (REQUIRES 3x3 CRAFTING TABLE) ---
    "furnace": {
        "name": "Furnace",
        "ingredients": "8 Cobblestone, Cobbled Deepslate, or Blackstone",
        "output_count": 1,
        "requires_table": True,
        "description": "Used for smelting raw ores into ingots and cooking food."
    },
    "blast_furnace": {
        "name": "Blast Furnace",
        "ingredients": "1 Furnace + 5 Iron Ingots + 3 Smooth Stone",
        "output_count": 1,
        "requires_table": True,
        "description": "Smelts ores and raw metals at 2x normal speed."
    },
    "smoker": {
        "name": "Smoker",
        "ingredients": "1 Furnace + 4 Wood Logs",
        "output_count": 1,
        "requires_table": True,
        "description": "Cooks food at 2x normal furnace speed."
    },
    "chest": {
        "name": "Chest",
        "ingredients": "8 Wooden Planks",
        "output_count": 1,
        "requires_table": True,
        "description": "Provides 27 slots of secure item storage."
    },
    "barrel": {
        "name": "Barrel",
        "ingredients": "6 Wooden Planks + 2 Wooden Slabs",
        "output_count": 1,
        "requires_table": True,
        "description": "Compact item storage that opens even when blocks are placed above it."
    },
    "bed": {
        "name": "Bed",
        "ingredients": "3 Wool + 3 Wooden Planks",
        "output_count": 1,
        "requires_table": True,
        "description": "Skips the night and resets player and bot respawn points."
    },
    "bucket": {
        "name": "Bucket",
        "ingredients": "3 Iron Ingots",
        "output_count": 1,
        "requires_table": True,
        "description": "Carries water for MLG drops and portal casting, or scoops lava for fuel."
    },
    "flint_and_steel": {
        "name": "Flint and Steel",
        "ingredients": "1 Iron Ingot + 1 Flint",
        "output_count": 1,
        "requires_table": False,
        "description": "Ignites fire to activate Nether portals, ignite TNT, or create light."
    },
    "shears": {
        "name": "Shears",
        "ingredients": "2 Iron Ingots",
        "output_count": 1,
        "requires_table": False,
        "description": "Harvests wool from sheep without hurting them, and cuts cobwebs/vines."
    },
    "boat": {
        "name": "Boat",
        "ingredients": "5 Wooden Planks",
        "output_count": 1,
        "requires_table": True,
        "description": "High-speed water travel and trapping hostile mobs inside."
    },

    # --- ADVANCED ENCHANTING & SPEEDRUN PROGRESSION ---
    "paper": {
        "name": "Paper",
        "ingredients": "3 Sugar Cane",
        "output_count": 3,
        "requires_table": True,
        "description": "Crafted from sugar cane to make books and maps."
    },
    "book": {
        "name": "Book",
        "ingredients": "3 Paper + 1 Leather",
        "output_count": 1,
        "requires_table": False,
        "description": "Combined with obsidian and diamonds to craft an enchanting table."
    },
    "bookshelf": {
        "name": "Bookshelf",
        "ingredients": "3 Books + 6 Wooden Planks",
        "output_count": 1,
        "requires_table": True,
        "description": "Surrounds enchanting tables to unlock Level 30 max enchantments."
    },
    "enchanting_table": {
        "name": "Enchanting Table",
        "ingredients": "4 Obsidian + 2 Diamonds + 1 Book",
        "output_count": 1,
        "requires_table": True,
        "description": "Imbues gear with magical powers like Sharpness, Protection, and Fortune."
    },
    "blaze_powder": {
        "name": "Blaze Powder",
        "ingredients": "1 Blaze Rod",
        "output_count": 2,
        "requires_table": False,
        "description": "Crafted from blaze rods; essential for Eye of Ender and brewing."
    },
    "eye_of_ender": {
        "name": "Eye of Ender",
        "ingredients": "1 Ender Pearl + 1 Blaze Powder",
        "output_count": 1,
        "requires_table": False,
        "description": "Used to locate Strongholds and activate the End Portal."
    },

    # --- FOOD & NOURISHMENT ---
    "bread": {
        "name": "Bread",
        "ingredients": "3 Wheat",
        "output_count": 1,
        "requires_table": True,
        "description": "Fast staple food replenishing 5 hunger points (crafted from hay bales or farmed wheat)."
    },
    "golden_apple": {
        "name": "Golden Apple",
        "ingredients": "8 Gold Ingots + 1 Apple",
        "output_count": 1,
        "requires_table": True,
        "description": "Grants Absorption and Regeneration II for emergency survival."
    }
}


def get_recipe(query: str) -> Optional[Dict[str, Any]]:
    """Returns the most appropriate recipe definition for a query."""
    clean = query.lower().strip().replace(" ", "_")
    # Direct match
    if clean in RECIPES:
        return RECIPES[clean]
    # Fuzzy match
    for key, val in RECIPES.items():
        if clean in key or key in clean or clean in val["name"].lower():
            return val
    return None


def get_table_recipes() -> List[str]:
    """Returns all recipes that strictly require a 3x3 crafting table."""
    return [k for k, v in RECIPES.items() if v.get("requires_table", True)]


def get_inventory_recipes() -> List[str]:
    """Returns all simple 2x2 recipes craftable directly inside player inventory."""
    return [k for k, v in RECIPES.items() if not v.get("requires_table", False)]
