"""Minecraft Tool (Function Calling) Schemas in English for Ollama / LLM."""

MINECRAFT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "craft_item",
            "description": "Crafts tools, weapons, armor, or utility blocks using inventory materials or nearby crafting tables.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The exact Minecraft registry name of the item (e.g. wooden_pickaxe, stone_pickaxe, iron_pickaxe, crafting_table, furnace, torch, shield, iron_sword, bucket, stick)."
                    },
                    "count": {
                        "type": "integer",
                        "description": "Quantity to craft.",
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
            "name": "smelt_item",
            "description": "Uses a nearby furnace to smelt raw ores into ingots or cook raw food items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input_item": {
                        "type": "string",
                        "description": "Material to smelt (e.g. raw_iron, iron_ore, beef, porkchop, raw_copper, raw_gold)."
                    }
                },
                "required": ["input_item"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "place_block",
            "description": "Places an inventory block (e.g. crafting_table, furnace, cobblestone, torch, dirt) onto the ground.",
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
            "name": "guard_player",
            "description": "Enters guard mode. The bot stays close to the player and automatically defends them against hostile mobs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Username of the player to protect."
                    }
                },
                "required": ["player_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "follow_player",
            "description": "Walks to and follows the specified player using A* pathfinding.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Username of the player to follow."
                    }
                },
                "required": ["player_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_actions",
            "description": "Immediately halts all ongoing movements, mining, guarding, and pathfinding goals.",
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
            "name": "sleep_in_bed",
            "description": "Finds a nearby bed at night and sleeps to skip until dawn.",
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
            "name": "eat_food",
            "description": "Consumes available food from inventory when hunger or health is low.",
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
            "name": "save_current_location",
            "description": "Saves current world coordinates under a custom label (e.g. home, mine, farm, portal).",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "Label for the location (e.g. home, mine, fortress)."
                    },
                    "description": {
                        "type": "string",
                        "description": "Short note about this location."
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
            "description": "Navigates back to a previously saved coordinate landmark in memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "Name of the landmark to navigate to."
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
            "description": "Lists all coordinates saved in the world memory.",
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
            "name": "go_to_coordinates",
            "description": "Directs the bot to walk to specific X, Y, Z world coordinates.",
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
            "name": "collect_block",
            "description": "Searches for, mines, and collects a nearby block type (e.g. oak_log, cobblestone, iron_ore, coal_ore, dirt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "block_name": {
                        "type": "string",
                        "description": "Block name or category (e.g. log, stone, iron_ore, coal_ore, dirt)."
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of blocks to mine.",
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
            "name": "attack_target",
            "description": "Engages in PvP/PvE combat against a nearby entity (zombie, skeleton, spider, creeper).",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_name": {
                        "type": "string",
                        "description": "Name of the target mob or entity."
                    }
                },
                "required": ["target_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hunt_food",
            "description": "Finds nearest passive food animals (cow, pig, sheep, chicken), hunts them for raw meat and food, and collects dropped items into inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "animal_type": {
                        "type": "string",
                        "description": "Optional specific animal type to hunt (e.g. cow, pig, sheep, chicken) or 'any'.",
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
            "name": "give_item_to_player",
            "description": "Approaches a player and tosses requested items from inventory to them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Player recipient username."
                    },
                    "item_name": {
                        "type": "string",
                        "description": "Item to give (e.g. bread, iron_ingot, diamond, torch)."
                    },
                    "count": {
                        "type": "integer",
                        "description": "Quantity to toss.",
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
            "name": "get_inventory",
            "description": "Inspects and queries current inventory contents and counts.",
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
            "name": "explain_component",
            "description": "Queries the universal official Minecraft encyclopedia for ANY of the 1,312 items, 1,058 blocks, foods, tools, or mobs. Returns hardness, category, food value, or usage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "component_name": {
                        "type": "string",
                        "description": "The exact or partial name of the Minecraft item, block, or mob (e.g. ancient_debris, crying_obsidian, golden_apple, blaze_rod, hopper)."
                    }
                },
                "required": ["component_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "say_chat",
            "description": "Broadcasts a concise message in public Minecraft chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Chat message string."
                    }
                },
                "required": ["message"]
            }
        }
    }
]
