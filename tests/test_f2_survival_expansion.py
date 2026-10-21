"""Unit tests for MC local AI Survival Inventory Expansion, Full Tool Base, Villager Trading, Golem Construction, and Special Ores."""
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock

from ai.tools import MINECRAFT_TOOLS
from ai.progression_tree import TECH_TREE, get_optimal_ore_height, resolve_missing_ingredients
from ai.planner import AutonomousCoopBrain
from core.chat_handler import MinecraftChatHandler
from utils.config import Config


class TestF2SurvivalExpansion(unittest.TestCase):

    def test_golem_and_toolset_in_minecraft_tools(self):
        """Verify build_golem and craft_tool_set exist in MINECRAFT_TOOLS and collect_block documents special ores."""
        tool_map = {t["function"]["name"]: t["function"] for t in MINECRAFT_TOOLS if t.get("type") == "function"}
        self.assertIn("build_golem", tool_map)
        self.assertIn("craft_tool_set", tool_map)
        self.assertIn("golem_type", tool_map["build_golem"]["parameters"]["properties"])
        self.assertIn("tier", tool_map["craft_tool_set"]["parameters"]["properties"])
        self.assertIn("emerald", tool_map["collect_block"]["description"])
        self.assertIn("amethyst", tool_map["collect_block"]["description"])

    def test_tech_tree_full_tool_base_and_golem_blocks(self):
        """Verify hoes, utility tools, and golem blocks are in TECH_TREE and ORE_OPTIMAL_Y."""
        for item in ("wooden_hoe", "stone_hoe", "iron_hoe", "diamond_hoe", "shears", "fishing_rod", "bow", "iron_block", "snow_block", "carved_pumpkin"):
            self.assertIn(item, TECH_TREE)
        self.assertEqual(resolve_missing_ingredients("iron_block", {"iron_ingot": 5}), ["4x iron ingot"])
        self.assertEqual(resolve_missing_ingredients("iron_block", {"iron_ingot": 9}), [])
        self.assertEqual(get_optimal_ore_height("emerald_ore"), 16)
        self.assertEqual(get_optimal_ore_height("amethyst_cluster"), -20)
        self.assertEqual(get_optimal_ore_height("nether_quartz_ore"), 60)

    def test_chat_handler_golem_trade_tools_scan_inv_commands(self):
        """Verify !golem, !trade, !tools, !scan, and !inv dispatch properly."""
        bot_mock = MagicMock()
        bot_mock.config = Config()
        bot_mock.db = MagicMock()
        bot_mock.bridge = MagicMock()
        bot_mock.bridge.send_action = AsyncMock()
        bot_mock.active_player_task = None

        handler = MinecraftChatHandler(bot_mock)
        state = {
            "health": 20,
            "food": 20,
            "special_ores_radar": {
                "precious_overworld": [{"block": "deepslate_emerald_ore", "closest_distance": 12}]
            },
            "visible_resources": {"deepslate_emerald_ore": {"total_found": 2}},
            "survival_inventory": {
                "slots": {"used_slots": 10, "max_slots": 36},
                "tool_base": {"completeness_pct": 89},
                "trading_capital": {"emeralds": 7, "can_trade_now": True},
                "golem_readiness": {"can_build_iron_golem": True, "can_build_snow_golem": False}
            }
        }

        asyncio.run(handler.handle_chat("Omer", "!golem iron", state))
        bot_mock.bridge.send_action.assert_called_with("build_golem", {"golem_type": "iron_golem", "count": 1})

        asyncio.run(handler.handle_chat("Omer", "!golem snow", state))
        bot_mock.bridge.send_action.assert_called_with("build_golem", {"golem_type": "snow_golem", "count": 1})

        asyncio.run(handler.handle_chat("Omer", "!trade emerald 3", state))
        bot_mock.bridge.send_action.assert_called_with("trade_with_villager", {"trade_item": "emerald", "count": 3})

        asyncio.run(handler.handle_chat("Omer", "!tools iron", state))
        bot_mock.bridge.send_action.assert_called_with("craft_tool_set", {"tier": "iron"})

        asyncio.run(handler.handle_chat("Omer", "!scan", state))
        last_call = bot_mock.bridge.send_action.call_args
        self.assertEqual(last_call[0][0], "say_chat")
        self.assertIn("deepslate_emerald_ore(12m)", last_call[0][1]["message"])

        asyncio.run(handler.handle_chat("Omer", "!inv", state))
        last_inv_call = bot_mock.bridge.send_action.call_args
        self.assertEqual(last_inv_call[0][0], "say_chat")
        self.assertIn("10/36 slots", last_inv_call[0][1]["message"])
        self.assertIn("IronGolem=True", last_inv_call[0][1]["message"])

    def test_planner_format_survival_inventory_context(self):
        """Verify AutonomousCoopBrain formats survival_inventory context concisely."""
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer")
        state = {
            "survival_inventory": {
                "tool_base": {"completeness_pct": 78, "missing_core_tools": ["hoe"]},
                "trading_capital": {"emeralds": 4, "can_trade_now": True},
                "golem_readiness": {"can_build_iron_golem": True, "can_build_snow_golem": False},
                "special_ores_radar": {
                    "precious_overworld": [{"block": "emerald_ore", "closest_distance": 9}]
                }
            }
        }
        ctx = brain.format_survival_inventory_context(state)
        self.assertIn("ToolBase:78%(missing:hoe)", ctx)
        self.assertIn("TradeReady(emeralds:4)", ctx)
        self.assertIn("IronGolemReady", ctx)
        self.assertIn("SpecialOres:emerald_ore@9m", ctx)

    def test_gp1_autonomous_milestone_triggers_golem_trade_and_toolset(self):
        """Verify GP-1 autonomous triggers in get_milestone_action for golem, villager trade, and tool base completion."""
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer")

        # 1. Iron Golem autonomous trigger when materials ready and no iron golem nearby
        golem_state = {
            "dimension": "overworld",
            "inventory": [{"name": "iron_pickaxe", "count": 2}, {"name": "iron_sword", "count": 1}, {"name": "shield", "count": 1}, {"name": "torch", "count": 8}],
            "nearby_iron_golems_count": 0,
            "survival_inventory": {
                "golem_readiness": {"can_build_iron_golem": True, "can_build_snow_golem": False}
            }
        }
        reason, tool_call = brain.get_milestone_action({"target": "diamond_pickaxe", "stage": "DIAMOND"}, golem_state)
        self.assertEqual(tool_call["name"], "build_golem")
        self.assertEqual(tool_call["arguments"]["golem_type"], "iron_golem")

        # 2. Villager trade trigger via survival_inventory.trading_capital.can_trade_now
        trade_state = {
            "dimension": "overworld",
            "inventory": [{"name": "iron_pickaxe", "count": 2}, {"name": "iron_sword", "count": 1}, {"name": "shield", "count": 1}, {"name": "torch", "count": 8}],
            "nearby_villagers_count": 2,
            "survival_inventory": {
                "trading_capital": {"can_trade_now": True, "emeralds": 3}
            }
        }
        reason, tool_call = brain.get_milestone_action({"target": "diamond_pickaxe", "stage": "DIAMOND"}, trade_state)
        self.assertEqual(tool_call["name"], "trade_with_villager")

        # 3. Tool base completion trigger when completeness_pct < 60 and iron surplus exists
        toolset_state = {
            "dimension": "overworld",
            "inventory": [
                {"name": "iron_pickaxe", "count": 2},
                {"name": "iron_sword", "count": 1},
                {"name": "shield", "count": 1},
                {"name": "torch", "count": 8},
                {"name": "iron_ingot", "count": 8}
            ],
            "survival_inventory": {
                "tool_base": {"completeness_pct": 45, "missing_core_tools": ["axe", "shovel", "hoe"]}
            }
        }
        reason, tool_call = brain.get_milestone_action({"target": "diamond_pickaxe", "stage": "DIAMOND"}, toolset_state)
        self.assertEqual(tool_call["name"], "craft_tool_set")

    def test_gp3_special_ores_radar_synced_to_sqlite_ore_map(self):
        """Verify GP-3 syncs special_ores_radar entries to SQLite ore_map via _update_last_known_state."""
        from main import MinecraftAIBot
        bot = MinecraftAIBot.__new__(MinecraftAIBot)
        bot.db = MagicMock()
        bot.last_known_inventory = []
        bot.last_known_position = None
        bot.last_known_dimension = "overworld"

        state = {
            "dimension": "overworld",
            "position": {"x": 10, "y": 16, "z": 20},
            "special_ores_radar": {
                "precious_overworld": [
                    {"block": "deepslate_emerald_ore", "closest_distance": 6, "closest_pos": {"x": 14, "y": 16, "z": 22}}
                ]
            }
        }
        bot._update_last_known_state(state)
        bot.db.save_ore.assert_called_once_with("overworld", 14, 16, 22, "deepslate_emerald_ore")
        # Calling a second time with same state must deduplicate and not re-insert
        bot._update_last_known_state(state)
        self.assertEqual(bot.db.save_ore.call_count, 1)

    def test_gp5_special_ore_navigation_from_sqlite_ore_map(self):
        """Verify GP-5 directs bot to recorded special ore (emerald/gold/lapis/ancient_debris) in SQLite ore_map."""
        db_mock = MagicMock()
        db_mock.get_unmined_ores.return_value = [
            {"block": "deepslate_emerald_ore", "x": 42, "y": 14, "z": -18, "distance": 11.0}
        ]
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer", db=db_mock)
        state = {"dimension": "overworld", "position": {"x": 35, "y": 16, "z": -15}, "inventory": []}
        reason, tool_call = brain.get_milestone_action({"target": "emerald", "stage": "VILLAGE_TRADE"}, state)
        self.assertEqual(tool_call["name"], "collect_block")
        self.assertEqual(tool_call["arguments"]["block_name"], "deepslate_emerald_ore")
        self.assertEqual(tool_call["arguments"]["target_x"], 42)
        self.assertEqual(tool_call["arguments"]["target_y"], 14)
        self.assertEqual(tool_call["arguments"]["target_z"], -18)

    def test_gp7_live_path_golem_failure_triggers_single_count_and_category_shift(self):
        """Verify GP-7 live callback path: 3 consecutive build_golem failures with unique action_ids trigger category shift and deduplicate duplicate action_ids."""
        from main import MinecraftAIBot
        bot = MinecraftAIBot.__new__(MinecraftAIBot)
        bot.db = MagicMock()
        bot.db.get_pending_tasks.return_value = []
        bot.db.get_unrecovered_death_point.return_value = None
        bot.chat_handler = MagicMock()
        bot.bridge = MagicMock()
        bot.bridge.send_action = AsyncMock()
        bot.bridge._last_action_args = {}
        bot.planner = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer", db=bot.db)
        bot.active_player_task = None
        bot.last_known_inventory = []
        bot.last_known_position = {"x": 0, "y": 64, "z": 0}
        bot.last_known_dimension = "overworld"
        bot._loop_wakeup = asyncio.Event()

        state = {"health": 20, "food": 20, "position": {"x": 0, "y": 64, "z": 0}, "dimension": "overworld"}
        golem_args = {"golem_type": "iron_golem", "count": 1}

        # Failure 1 (plus duplicate callback with same action_id 'act-g1' must only count once!)
        asyncio.run(bot.on_action_completed("build_golem", False, "missing_iron_blocks_for_iron_golem", state, args=golem_args, action_id="act-g1"))
        asyncio.run(bot.on_action_completed("build_golem", False, "missing_iron_blocks_for_iron_golem", state, args=golem_args, action_id="act-g1"))
        self.assertEqual(bot.planner._consecutive_same_fallback_count, 1)

        # Failure 2
        asyncio.run(bot.on_action_completed("build_golem", False, "missing_iron_blocks_for_iron_golem", state, args=golem_args, action_id="act-g2"))
        self.assertEqual(bot.planner._consecutive_same_fallback_count, 2)

        # Failure 3 -> triggers category shift!
        asyncio.run(bot.on_action_completed("build_golem", False, "missing_iron_blocks_for_iron_golem", state, args=golem_args, action_id="act-g3"))
        self.assertIsNotNone(bot.planner._pending_category_shift_action)


if __name__ == "__main__":
    unittest.main()
