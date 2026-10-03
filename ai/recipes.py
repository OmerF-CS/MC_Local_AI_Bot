"""Minecraft Crafting Recipes & Knowledge Registry in English."""
from typing import Optional, Dict, Any

RECIPES: Dict[str, Dict[str, Any]] = {
    "torch": {
        "name": "Torch",
        "ingredients": "1 Coal or Charcoal + 1 Stick",
        "output_count": 4,
        "description": "Illuminates dark caves, tunnels, and prevents hostile mobs from spawning."
    },
    "crafting_table": {
        "name": "Crafting Table",
        "ingredients": "4 Wooden Planks (any wood type)",
        "output_count": 1,
        "description": "Provides a 3x3 crafting grid essential for almost all advanced tools and items."
    },
    "furnace": {
        "name": "Furnace",
        "ingredients": "8 Cobblestone, Cobbled Deepslate, or Blackstone",
        "output_count": 1,
        "description": "Used for smelting raw ores into ingots and cooking food."
    },
    "chest": {
        "name": "Chest",
        "ingredients": "8 Wooden Planks",
        "output_count": 1,
        "description": "Provides 27 slots of secure item storage."
    },
    "bed": {
        "name": "Bed",
        "ingredients": "3 Wool + 3 Wooden Planks",
        "output_count": 1,
        "description": "Skips the night and resets player and bot respawn points."
    },
    "wooden_pickaxe": {
        "name": "Wooden Pickaxe",
        "ingredients": "3 Wooden Planks + 2 Sticks",
        "output_count": 1,
        "description": "Fundamental mining tool required to break and harvest stone, deepslate, and coal."
    },
    "stone_pickaxe": {
        "name": "Stone Pickaxe",
        "ingredients": "3 Cobblestone, Cobbled Deepslate, or Blackstone + 2 Sticks",
        "output_count": 1,
        "description": "Mines iron ore, copper ore, and lapis lazuli."
    },
    "iron_pickaxe": {
        "name": "Iron Pickaxe",
        "ingredients": "3 Iron Ingots + 2 Sticks",
        "output_count": 1,
        "description": "Mines gold, redstone, and diamond ore."
    },
    "diamond_pickaxe": {
        "name": "Diamond Pickaxe",
        "ingredients": "3 Diamonds + 2 Sticks",
        "output_count": 1,
        "description": "Required to mine obsidian and access the Nether."
    },
    "shield": {
        "name": "Shield",
        "ingredients": "1 Iron Ingot + 6 Wooden Planks",
        "output_count": 1,
        "description": "Lifesaving off-hand defense against arrows and creeper blast damage."
    },
    "iron_sword": {
        "name": "Iron Sword",
        "ingredients": "2 Iron Ingots + 1 Stick",
        "output_count": 1,
        "description": "Deals 6 attack damage for effective combat."
    },
    "iron_chestplate": {
        "name": "Iron Chestplate",
        "ingredients": "8 Iron Ingots",
        "output_count": 1,
        "description": "Provides solid torso armor protection."
    },
    "bucket": {
        "name": "Bucket",
        "ingredients": "3 Iron Ingots",
        "output_count": 1,
        "description": "Carries water for MLG drops and portal casting, or scoops lava for fuel."
    },
    "flint_and_steel": {
        "name": "Flint and Steel",
        "ingredients": "1 Iron Ingot + 1 Flint",
        "output_count": 1,
        "description": "Ignites fire to activate Nether portals, ignite TNT, or create light."
    },
    "blaze_powder": {
        "name": "Blaze Powder",
        "ingredients": "1 Blaze Rod",
        "output_count": 2,
        "description": "Crafted from blaze rods; essential for Eye of Ender and brewing."
    },
    "eye_of_ender": {
        "name": "Eye of Ender",
        "ingredients": "1 Ender Pearl + 1 Blaze Powder",
        "output_count": 1,
        "description": "Used to locate Strongholds and activate the End Portal."
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
