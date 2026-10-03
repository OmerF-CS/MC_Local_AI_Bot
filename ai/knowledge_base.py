"""Minecraft Pro Player Tactical Knowledge Base and RAG system."""
from typing import Dict, Any, List, Optional

MINECRAFT_TACTICS = {
    "wood": {
        "title": "Wood & Log Harvesting",
        "tip": "Punch or chop logs (oak, birch, spruce). 3 logs convert into 12 wooden planks, which is plenty for a crafting table and wooden pickaxe."
    },
    "mining_depths": {
        "title": "Optimal Ore Mining Depths",
        "tip": "Coal: Y 95-130 in mountains | Iron: Y 14-16 in caves | Diamonds: Y -58 deepslate layer right above lava lakes."
    },
    "combat_creeper": {
        "title": "Creeper Defense",
        "tip": "When a Creeper hisses, NEVER stand still! Backpedal 4 blocks or raise your shield immediately. A shield blocks 100% of blast damage."
    },
    "combat_skeleton": {
        "title": "Skeleton Tactics",
        "tip": "Do not charge straight into arrows. Block arrow with shield, then rush in sword strikes during the 1-second recharge delay."
    },
    "combat_enderman": {
        "title": "Enderman Safety",
        "tip": "Never make direct eye contact. If provoked, stand under a 2-block ceiling (they are 3 blocks tall) or stand in water."
    },
    "night_survival": {
        "title": "Nighttime Survival",
        "tip": "Avoid open terrain combat without armor. Sleep in a bed if available, or pillar up 3 dirt blocks until dawn."
    },
    "food_efficiency": {
        "title": "Hunger and Saturation",
        "tip": "Cook raw meat in a furnace (cooked steak restores 8 hunger). Maintain 18+ food hunger points for rapid health regeneration."
    },
    "nether_portal": {
        "title": "Nether Portal Construction",
        "tip": "Without a diamond pickaxe, cast a portal using a water bucket and lava pools. Otherwise mine 10-14 obsidian blocks and ignite with flint & steel."
    },
    "blaze_combat": {
        "title": "Blaze & Nether Fortress Combat",
        "tip": "Blazes puff smoke before shooting fireballs. Use a shield to deflect fire charges, and close in for sword strikes. Gather at least 7 blaze rods."
    },
    "stronghold_tracking": {
        "title": "Stronghold Locating",
        "tip": "Craft Eyes of Ender (blaze powder + ender pearl). Throw them in the Overworld and follow their flight vector to locate the underground stronghold portal room."
    },
    "ender_dragon": {
        "title": "Ender Dragon Battle Tactics",
        "tip": "Destroy the End Crystals atop obsidian pillars first with bow/arrows or snowballs. When the dragon perches at the central bedrock fountain, attack with sword or bed explosions (Bed Bombing)."
    }
}

def get_relevant_tactic(state: Dict[str, Any]) -> str:
    """Returns the most critical pro-survival tactic matching current game state."""
    hostiles = [h.lower() for h in state.get("nearby_hostiles", [])]
    dimension = state.get("dimension", "overworld")
    is_day = state.get("is_day", True)
    health = state.get("health", 20)
    food = state.get("food", 20)
    pos = state.get("position", {})
    y = pos.get("y", 64)

    # Dragon / End tactics
    if dimension == "the_end" or any("dragon" in h for h in hostiles):
        return MINECRAFT_TACTICS["ender_dragon"]["tip"]

    # Nether tactics
    if dimension == "the_nether" or any("blaze" in h for h in hostiles):
        return MINECRAFT_TACTICS["blaze_combat"]["tip"]

    # Immediate hostile threats
    if any("creeper" in h for h in hostiles):
        return MINECRAFT_TACTICS["combat_creeper"]["tip"]
    if any("skeleton" in h for h in hostiles):
        return MINECRAFT_TACTICS["combat_skeleton"]["tip"]
    if any("enderman" in h for h in hostiles):
        return MINECRAFT_TACTICS["combat_enderman"]["tip"]

    # Survival triage
    if not is_day and health < 14:
        return MINECRAFT_TACTICS["night_survival"]["tip"]
    if food < 14:
        return MINECRAFT_TACTICS["food_efficiency"]["tip"]

    # Mining depth tips
    if y < 0:
        return MINECRAFT_TACTICS["mining_depths"]["tip"]

    return MINECRAFT_TACTICS["wood"]["tip"]
