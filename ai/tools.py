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
    }
]
