"""Minecraft Tool (Function Calling) Schemas - Qwen 2.5 optimized for clarity."""

MINECRAFT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "craft_item",
            "description": "Craft a tool, weapon, or item. Will use nearby crafting table if needed. Choose from: wooden_pickaxe, stone_pickaxe, iron_pickaxe, diamond_pickaxe, furnace, crafting_table, torch, shield, sword (specify material: wooden, stone, iron, diamond), axe (specify material), shovel (specify material), chest, bed, armor (specify type and material).",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Exact item name: wooden_pickaxe, stone_pickaxe, iron_pickaxe, diamond_pickaxe, furnace, crafting_table, torch, shield, stone_sword, iron_sword, diamond_sword, stone_axe, iron_axe, diamond_axe, wooden_axe, stone_shovel, iron_shovel, wooden_shovel, diamond_shovel, chest, bed, leather_helmet, iron_helmet, diamond_helmet, iron_chestplate, iron_leggings, iron_boots, etc.",
                        "enum": [
                            "wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe",
                            "wooden_sword", "stone_sword", "iron_sword", "diamond_sword",
                            "wooden_axe", "stone_axe", "iron_axe", "diamond_axe",
                            "wooden_shovel", "stone_shovel", "iron_shovel", "diamond_shovel",
                            "furnace", "crafting_table", "torch", "shield", "chest", "bed",
                            "leather_helmet", "iron_helmet", "diamond_helmet",
                            "iron_chestplate", "diamond_chestplate",
                            "iron_leggings", "diamond_leggings",
                            "iron_boots", "diamond_boots",
                            "stone_stairs", "wooden_stairs",
                            "flint_and_steel", "blaze_powder", "eye_of_ender"
                        ]
                    },
                    "count": {
                        "type": "integer",
                        "description": "How many to craft (default 1).",
                        "default": 1
                    }
                },
                "required": ["item_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "collect_block",
            "description": "Mine and collect blocks. Examples: log, stone, iron_ore, coal_ore, diamond_ore, cobblestone, dirt, sand, obsidian, netherrack, glowstone, lapis_ore, gold_ore, copper_ore, deepslate_iron_ore, deepslate_diamond_ore, deepslate_coal_ore.",
            "parameters": {
                "type": "object",
                "properties": {
                    "block_name": {
                        "type": "string",
                        "description": "Block to collect: log, stone, iron_ore, coal_ore, diamond_ore, cobblestone, dirt, sand, obsidian, netherrack, glowstone, soul_sand, lapis_ore, gold_ore, copper_ore, deepslate_iron_ore, deepslate_diamond_ore, deepslate_coal_ore, deepslate_lapis_ore.",
                        "enum": [
                            "log", "wood", "stone", "cobblestone", "deepslate", "cobbled_deepslate", "blackstone",
                            "iron_ore", "deepslate_iron_ore", "coal_ore", "deepslate_coal_ore",
                            "diamond_ore", "deepslate_diamond_ore",
                            "gold_ore", "deepslate_gold_ore",
                            "copper_ore", "deepslate_copper_ore",
                            "lapis_ore", "deepslate_lapis_ore",
                            "redstone_ore", "deepslate_redstone_ore",
                            "obsidian", "dirt", "sand", "gravel",
                            "netherrack", "glowstone", "soul_sand", "basalt"
                        ]
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of blocks to mine (default 1).",
                        "default": 1
                    }
                },
                "required": ["block_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "smelt_item",
            "description": "Use furnace to smelt raw ores into ingots, or cook raw food. Examples: raw_iron, iron_ore, raw_copper, raw_gold, raw_beef, raw_porkchop, raw_chicken, raw_mutton.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input_item": {
                        "type": "string",
                        "description": "Item to smelt: raw_iron, iron_ore, raw_copper, raw_gold, raw_beef, raw_porkchop, raw_chicken, raw_mutton, deepslate_iron_ore, deepslate_coal_ore.",
                        "enum": [
                            "raw_iron", "iron_ore", "deepslate_iron_ore",
                            "raw_copper", "copper_ore", "deepslate_copper_ore",
                            "raw_gold", "gold_ore", "deepslate_gold_ore",
                            "raw_beef", "raw_porkchop", "raw_chicken", "raw_mutton",
                            "coal_ore", "deepslate_coal_ore"
                        ]
                    },
                    "count": {
                        "type": "integer",
                        "description": "Quantity to smelt (default 1).",
                        "default": 1
                    }
                },
                "required": ["input_item"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hunt_food",
            "description": "Hunt passive food animals (cows, pigs, sheep, chickens) for meat. Specify animal type or 'any' to hunt whatever is nearby.",
            "parameters": {
                "type": "object",
                "properties": {
                    "animal_type": {
                        "type": "string",
                        "description": "Which animal to hunt: 'cow', 'pig', 'sheep', 'chicken', 'horse', or 'any'.",
                        "enum": ["cow", "pig", "sheep", "chicken", "horse", "any"],
                        "default": "any"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "eat_food",
            "description": "Eat food from inventory to restore hunger. Automatically selects best available food (cooked meat > bread > apple).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "guard_player",
            "description": "Enter guard mode - stay close to player and defend against hostile mobs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Username of player to protect (usually your partner's name)."
                    }
                },
                "required": ["player_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "attack_target",
            "description": "Attack a nearby hostile mob (zombie, skeleton, spider, creeper, etc).",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_name": {
                        "type": "string",
                        "description": "Mob type to attack: zombie, skeleton, spider, creeper, enderman, drowned, witch, husk, stray, etc.",
                        "enum": [
                            "zombie", "skeleton", "spider", "creeper", "enderman", "drowned",
                            "witch", "husk", "stray", "cave_spider", "phantom", "silverfish",
                            "blaze", "ghast", "wither", "warden", "hoglin", "piglin"
                        ]
                    }
                },
                "required": ["target_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "follow_player",
            "description": "Walk to and follow a player.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Player username to follow."
                    }
                },
                "required": ["player_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "go_to_coordinates",
            "description": "Walk to specific X, Y, Z world coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": "X coordinate"},
                    "y": {"type": "number", "description": "Y coordinate"},
                    "z": {"type": "number", "description": "Z coordinate"}
                },
                "required": ["x", "y", "z"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sleep_in_bed",
            "description": "Find nearby bed and sleep through the night.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "place_block",
            "description": "Place a block from inventory (torch, dirt, cobblestone, crafting_table, furnace, etc).",
            "parameters": {
                "type": "object",
                "properties": {
                    "block_name": {
                        "type": "string",
                        "description": "Block to place from inventory."
                    }
                },
                "required": ["block_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_current_location",
            "description": "Save current coordinates with a name (e.g. 'home', 'iron_mine', 'village').",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "Label for this location."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description (e.g. 'Iron ore vein with 5 exposed ores')."
                    }
                },
                "required": ["location_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "go_to_saved_location",
            "description": "Navigate to a previously saved location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "Name of saved location to visit."
                    }
                },
                "required": ["location_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_saved_locations",
            "description": "List all previously saved locations.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_actions",
            "description": "Stop all current actions immediately (pathfinding, mining, combat, etc).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "say_chat",
            "description": "Send a message in chat (keep it SHORT - 1-2 sentences max).",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Chat message (be concise and natural).",
                        "maxLength": 100
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "explain_component",
            "description": "Look up info about an item, block, or mob in Minecraft encyclopedia.",
            "parameters": {
                "type": "object",
                "properties": {
                    "component_name": {
                        "type": "string",
                        "description": "Item/block/mob name to look up."
                    }
                },
                "required": ["component_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "give_item_to_player",
            "description": "Approach a player and give them items from inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Player to give items to."
                    },
                    "item_name": {
                        "type": "string",
                        "description": "Item name to give."
                    },
                    "count": {
                        "type": "integer",
                        "description": "Quantity (default 1).",
                        "default": 1
                    }
                },
                "required": ["player_name", "item_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_nether_portal",
            "description": "Construct a 4x5 vertical obsidian frame and ignite it with flint_and_steel to activate a Nether Portal. Requires at least 10 obsidian blocks and flint_and_steel in inventory.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "throw_eye_of_ender",
            "description": "Throw an Eye of Ender into the sky to track the Stronghold and detect the direction/angle of the signal.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "activate_end_portal",
            "description": "Scan for nearby End Portal Frames (within 16m), insert Eyes of Ender into any empty frames, and activate the End Portal.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "destroy_end_crystals",
            "description": "Scan and destroy End Crystals atop obsidian pillars in the End dimension using ranged weapons (bow/arrows, snowballs) or scaffolding up with a protective shield.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fight_ender_dragon",
            "description": "Engage the Ender Dragon in combat. Deflect dragon attacks with shield, dodge breath clouds, and perform burst attacks with sword or beds when the dragon perches on the central exit bedrock portal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tactic": {
                        "type": "string",
                        "description": "Combat approach: 'melee_sword', 'bed_bomb', or 'ranged_bow'.",
                        "default": "melee_sword"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "enter_exit_portal",
            "description": "Approach the central bedrock fountain at (0, 65, 0), collect all dropped Ender Dragon XP orbs, and step into the exit End Portal to complete the game and win.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "farm_crops",
            "description": "Harvest hay bales (converting to wheat & bread), harvest ripe crops, till farmland near water, plant seeds, or apply bone meal for sustainable food.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "description": "Farming action to perform: 'auto', 'harvest_hay_bales', 'harvest_ripe_crops', 'till_and_plant', or 'bone_meal'.",
                        "enum": ["auto", "harvest_hay_bales", "harvest_ripe_crops", "till_and_plant", "bone_meal"],
                        "default": "auto"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_shelter",
            "description": "Construct an emergency protective shelter or burrow using ANY available solid blocks in inventory (cobblestone, dirt, deepslate, planks, netherrack, etc.) or dig a sealed burrow hole.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "description": "Shelter structure type: 'auto' (chooses best based on materials/threats), 'emergency_box' (4 walls + roof), 'burrow' (zero-material 3-deep sealed hole), or 'enderman_roof' (2-block canopy).",
                        "enum": ["auto", "emergency_box", "burrow", "enderman_roof"],
                        "default": "auto"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "break_out_shelter",
            "description": "Mine the ceiling or doorway block of an emergency shelter/burrow to safely exit and resume travel when danger has passed.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "enchant_gear",
            "description": "Enchant equipped weapons, armor, or tools using an enchanting table, XP levels, and lapis lazuli catalyst.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gear_type": {
                        "type": "string",
                        "description": "Gear to enchant: 'auto', 'sword', 'chestplate', 'helmet', 'leggings', 'boots', 'bow', or 'pickaxe'.",
                        "enum": ["auto", "sword", "chestplate", "helmet", "leggings", "boots", "bow", "pickaxe"],
                        "default": "auto"
                    },
                    "target_level": {
                        "type": "integer",
                        "description": "Desired enchantment tier or minimum level (1 to 30). Default 15.",
                        "default": 15
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_nether_outpost",
            "description": "Construct a blast-resistant cobblestone/deepslate enclosure surrounding the Nether portal to protect against Ghast fireball explosions and hostile mob intrusions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "wall_material": {
                        "type": "string",
                        "description": "Blast-resistant building material: 'auto', 'cobblestone', 'cobbled_deepslate', 'stone', or 'blackstone'.",
                        "enum": ["auto", "cobblestone", "cobbled_deepslate", "stone", "blackstone"],
                        "default": "auto"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bridge_chasm",
            "description": "Safely bridge across voids, lava lakes, or chasms by crouching (sneaking) and placing blocks beneath feet iteratively without falling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": "Direction to bridge: 'forward', 'north', 'south', 'east', or 'west'.",
                        "enum": ["forward", "north", "south", "east", "west"],
                        "default": "forward"
                    },
                    "distance": {
                        "type": "integer",
                        "description": "Number of blocks to extend the bridge (default 5).",
                        "default": 5
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "breed_animals",
            "description": "Breed nearby farm animals (cows, sheep, chickens, pigs) by feeding them matching breeding food (wheat, seeds, carrots/potatoes) to multiply animals, earn XP, and produce food sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "animal_type": {
                        "type": "string",
                        "description": "Type of animal to breed: 'cow', 'sheep', 'chicken', 'pig', or 'any'.",
                        "enum": ["cow", "sheep", "chicken", "pig", "any"],
                        "default": "any"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "catch_fish",
            "description": "Catch fish and treasure from water sources using a fishing rod.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of fishing attempts or fish to catch (default 3).",
                        "default": 3
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_chest",
            "description": "Store surplus inventory items in a nearby chest or withdraw needed items. If no chest exists, crafts and places one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "description": "Action: 'deposit_surplus' (deposit excess blocks/items), 'withdraw', or 'deposit_all'.",
                        "enum": ["deposit_surplus", "withdraw", "deposit_all"],
                        "default": "deposit_surplus"
                    },
                    "target_item": {
                        "type": "string",
                        "description": "Specific item to withdraw from chest (if action_type is 'withdraw').",
                        "default": ""
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of items to transfer.",
                        "default": 1
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "trade_with_villager",
            "description": "Trade with nearby village villagers to obtain emeralds, enchanted books, diamond armor/tools, or food.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trade_item": {
                        "type": "string",
                        "description": "Desired trade item (e.g. 'emerald', 'bread', 'iron_sword', 'enchanted_book'). Default '' accepts first available trade.",
                        "default": ""
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of times to execute the trade (default 1).",
                        "default": 1
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "brew_potion",
            "description": "Brew potions using a brewing stand, blaze powder fuel, and water bottles. Examples: nether_wart (awkward potion), sugar (speed), magma_cream (fire resistance), glistering_melon_slice (healing).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ingredient": {
                        "type": "string",
                        "description": "Brewing ingredient: 'auto', 'nether_wart', 'sugar', 'magma_cream', 'ghast_tear', 'glistering_melon_slice', 'redstone', 'glowstone_dust'.",
                        "enum": ["auto", "nether_wart", "sugar", "magma_cream", "ghast_tear", "glistering_melon_slice", "redstone", "glowstone_dust"],
                        "default": "auto"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "repair_gear_anvil",
            "description": "Repair damaged weapons, tools, or armor on an anvil using repair ingots/diamonds or combining duplicate items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_item": {
                        "type": "string",
                        "description": "Gear item to repair: 'auto' (most damaged item), or specific name like 'diamond_pickaxe', 'iron_chestplate'.",
                        "default": "auto"
                    },
                    "repair_material": {
                        "type": "string",
                        "description": "Material used for repair: 'auto', 'diamond', 'iron_ingot'.",
                        "default": "auto"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "barter_with_piglins",
            "description": "Barter gold ingots with Nether Piglins to obtain Ender Pearls, Fire Resistance potions, obsidian, and crying obsidian.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of gold ingots to barter (default 1).",
                        "default": 1
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hunt_hoglin",
            "description": "Hunt Hoglins in the Nether Crimson Forest for high-saturation cooked porkchop food supplies.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "setup_respawn_anchor",
            "description": "Place and charge a Respawn Anchor with Glowstone inside the Nether to establish a persistent Nether spawn point.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "explore_end_city",
            "description": "Navigate through the End Gateway to the Outer End Islands to discover End Cities, defeat Shulkers for shells, and claim the Elytra.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "eat_chorus_fruit",
            "description": "Consume a Chorus Fruit from the End to restore hunger and trigger tactical short-range teleportation.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "explore_nether_fortress",
            "description": "Locate and explore Nether Fortress structure. Searches for Nether Bricks, Blaze spawners, and Nether Wart corridors, registering fortress coordinates to spatial memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_resource": {
                        "type": "string",
                        "description": "Target fortress component: 'blaze_spawner', 'nether_wart', 'chest', or 'explore'.",
                        "enum": ["blaze_spawner", "nether_wart", "chest", "explore"],
                        "default": "explore"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "explore_bastion",
            "description": "Locate and explore Bastion Remnant structure. Searches for gilded blackstone, piglin brutes, and treasure chests, looting high-value materials (ancient debris, gold, upgrade templates).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_mode": {
                        "type": "string",
                        "description": "Action mode: 'loot_chests' or 'explore'.",
                        "enum": ["loot_chests", "explore"],
                        "default": "explore"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fly_with_elytra",
            "description": "Equip Elytra and perform rocket-propelled flight towards destination coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": "Target X coordinate"},
                    "y": {"type": "number", "description": "Target Y coordinate"},
                    "z": {"type": "number", "description": "Target Z coordinate"}
                },
                "required": ["x", "y", "z"]
            }
        }
    }
]
