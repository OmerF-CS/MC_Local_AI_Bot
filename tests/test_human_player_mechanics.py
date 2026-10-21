"""Unit tests for Human-like AI Player Evolution Mechanics (Phase 2):
Physical Movement Tools, Opportunity Scanner, and Player Personas/Styles.
"""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import MagicMock, AsyncMock

from ai.tools import MINECRAFT_TOOLS
from ai.opportunistic_radar import OpportunityScanner, Opportunity
from ai.player_styles import PlayerStyle, StyleStrategy
from ai.planner import AutonomousCoopBrain
from core.chat_handler import MinecraftChatHandler
from core.database import Database


class TestHumanPlayerMechanics(unittest.TestCase):
    """Test suite covering movement tools, opportunistic radar, player styles, and planner integration."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_human_player.db")
        self.db = Database(self.db_path)

        self.mock_brain = MagicMock()
        self.mock_brain.process_chat = AsyncMock(return_value={"text": "Progressing", "tool_calls": []})

        self.planner = AutonomousCoopBrain(self.mock_brain, bot_owner="PlayerTest", db=self.db)

        # Mock Bot & Bridge for Chat Handler
        self.mock_bot = MagicMock()
        self.mock_bot.config = MagicMock()
        self.mock_bot.config.BOT_NAME = "AIAssistant"
        self.mock_bot.config.MINECRAFT_USERNAME = "AIAssistant"
        self.mock_bot.config.OLLAMA_MODEL = "qwen2.5:3b"
        self.mock_bot.db = self.db
        self.mock_bot.planner = self.planner
        self.mock_bot.active_player_task = None

        self.mock_bridge = MagicMock()
        self.mock_bridge.clients = [MagicMock()]
        self.mock_bridge.latest_state = {}
        self.mock_bridge.send_action = AsyncMock(return_value={"success": True})
        self.mock_bridge.send_action_and_wait = AsyncMock(return_value={"success": True, "ok": True})
        self.mock_bot.bridge = self.mock_bridge

        self.chat_handler = MinecraftChatHandler(self.mock_bot)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Tool Definitions Verification
    # -------------------------------------------------------------------------
    def test_tool_definitions_in_minecraft_tools(self):
        """Verify new movement and player persona tools are properly defined in MINECRAFT_TOOLS."""
        tool_names = [t["function"]["name"] for t in MINECRAFT_TOOLS if t.get("type") == "function"]

        expected_tools = [
            "mine_staircase",
            "pillar_jump",
            "scout_high_ground",
            "water_bucket_descent",
            "set_player_style"
        ]

        for expected in expected_tools:
            self.assertIn(expected, tool_names, f"Tool '{expected}' missing from MINECRAFT_TOOLS")

        # Check mine_staircase schema
        stair_tool = next(t["function"] for t in MINECRAFT_TOOLS if t["function"]["name"] == "mine_staircase")
        props = stair_tool["parameters"]["properties"]
        self.assertIn("target_y", props)
        self.assertIn("direction", props)
        self.assertIn("place_torches", props)
        self.assertEqual(props["direction"]["enum"], ["north", "south", "east", "west"])

        # Check pillar_jump schema
        pillar_tool = next(t["function"] for t in MINECRAFT_TOOLS if t["function"]["name"] == "pillar_jump")
        self.assertIn("height", pillar_tool["parameters"]["properties"])
        self.assertIn("block_type", pillar_tool["parameters"]["properties"])

        # Check scout_high_ground schema
        scout_tool = next(t["function"] for t in MINECRAFT_TOOLS if t["function"]["name"] == "scout_high_ground")
        self.assertIn("radius", scout_tool["parameters"]["properties"])

        # Check water_bucket_descent schema
        water_tool = next(t["function"] for t in MINECRAFT_TOOLS if t["function"]["name"] == "water_bucket_descent")
        self.assertIn("target_y", water_tool["parameters"]["properties"])
        self.assertEqual(water_tool["parameters"]["required"], ["target_y"])

        # Check set_player_style schema
        style_tool = next(t["function"] for t in MINECRAFT_TOOLS if t["function"]["name"] == "set_player_style")
        self.assertIn("style", style_tool["parameters"]["properties"])
        self.assertEqual(
            style_tool["parameters"]["properties"]["style"]["enum"],
            ["speedrunner", "explorer", "builder", "combat"]
        )

    # -------------------------------------------------------------------------
    # 2. Chat Handler Shortcut & Execution Tests
    # -------------------------------------------------------------------------
    def test_chat_shortcuts_dispatch(self):
        """Verify chat shortcuts dispatch physical actions and style changes."""
        state = {"position": {"x": 0, "y": 70, "z": 0}}

        # !staircase 16 north
        asyncio.run(self.chat_handler.handle_chat("PlayerTest", "!staircase 16 north", state))
        self.mock_bridge.send_action.assert_called_with(
            "mine_staircase",
            {"target_y": 16, "direction": "north", "place_torches": True}
        )

        # !pillar 4 dirt
        asyncio.run(self.chat_handler.handle_chat("PlayerTest", "!pillar 4 dirt", state))
        self.mock_bridge.send_action.assert_called_with(
            "pillar_jump",
            {"height": 4, "block_type": "dirt"}
        )

        # !scout 25
        asyncio.run(self.chat_handler.handle_chat("PlayerTest", "!scout 25", state))
        self.mock_bridge.send_action.assert_called_with(
            "scout_high_ground",
            {"radius": 25}
        )

        # !descend 45
        asyncio.run(self.chat_handler.handle_chat("PlayerTest", "!descend 45", state))
        self.mock_bridge.send_action.assert_called_with(
            "water_bucket_descent",
            {"target_y": 45}
        )

        # !style builder
        asyncio.run(self.chat_handler.handle_chat("PlayerTest", "!style builder", state))
        self.assertEqual(self.planner.player_style, PlayerStyle.HOMESTEAD_BUILDER)

    def test_execute_tool_methods(self):
        """Verify _execute_tool properly validates and routes new tools."""
        state = {"position": {"x": 10, "y": 64, "z": 10}}

        # Execute set_player_style
        res_style = asyncio.run(self.chat_handler._execute_tool(
            "set_player_style",
            {"style": "combat"},
            state,
            "PlayerTest"
        ))
        self.assertTrue(res_style["success"])
        self.assertEqual(self.planner.player_style, PlayerStyle.COMBAT_CRAWLER)

        # Execute mine_staircase
        asyncio.run(self.chat_handler._execute_tool(
            "mine_staircase",
            {"target_y": 12, "direction": "south", "place_torches": False},
            state,
            "PlayerTest"
        ))
        self.mock_bridge.send_action_and_wait.assert_called_with(
            "mine_staircase",
            {"target_y": 12, "direction": "south", "place_torches": False},
            timeout=60.0
        )

    # -------------------------------------------------------------------------
    # 3. Opportunity Scanner Rules Tests
    # -------------------------------------------------------------------------
    def test_opportunity_scanner_wool_need_rule(self):
        """Rule 1 (WoolNeedRule): Triggers when bed is missing, wool < 3, and sheep is within 24m."""
        scanner = OpportunityScanner()
        goal = {"target": "wooden_pickaxe", "stage": "Stage 0"}

        # Case 1: Bed missing, 1 wool, sheep at 15m -> Triggers Priority 8 Opportunity
        inv = {"white_wool": 1}
        state = {
            "nearby_passives": [{"name": "sheep", "distance": 15.0}]
        }
        opp = scanner.evaluate_opportunities(inv, state, goal)
        self.assertIsNotNone(opp)
        self.assertEqual(opp.name, "gather_wool_for_bed")
        self.assertEqual(opp.priority, 8)
        self.assertEqual(opp.action, "attack_target")
        self.assertEqual(opp.arguments["target_name"], "sheep")

        # Case 2: Already has a bed -> Does NOT trigger
        inv_with_bed = {"bed": 1}
        opp_bed = scanner.evaluate_opportunities(inv_with_bed, state, goal)
        self.assertIsNone(opp_bed)

        # Case 3: Already has 3 wool -> Does NOT trigger
        inv_with_3wool = {"white_wool": 3}
        opp_wool = scanner.evaluate_opportunities(inv_with_3wool, state, goal)
        self.assertIsNone(opp_wool)

        # Case 4: Sheep too far (> 24m) -> Does NOT trigger
        state_far = {
            "nearby_passives": [{"name": "sheep", "distance": 35.0}]
        }
        opp_far = scanner.evaluate_opportunities(inv, state_far, goal)
        self.assertIsNone(opp_far)

    def test_opportunity_scanner_surface_coal_rule(self):
        """Rule 2 (SurfaceCoalRule): Triggers when torch < 4, coal < 2, goal != wooden_pickaxe, coal <= 16m."""
        scanner = OpportunityScanner()

        # Case 1: 0 torches, 0 coal, goal is stone_pickaxe, coal_ore at 10m -> Triggers Priority 6 Opportunity
        goal_stone = {"target": "stone_pickaxe", "stage": "Stage 1"}
        inv = {"cobblestone": 3}
        state = {
            "visible_resources": {
                "coal_ore": {"closest_distance": 10.0}
            }
        }
        opp = scanner.evaluate_opportunities(inv, state, goal_stone)
        self.assertIsNotNone(opp)
        self.assertEqual(opp.name, "grab_surface_coal")
        self.assertEqual(opp.priority, 6)
        self.assertEqual(opp.action, "collect_block")
        self.assertEqual(opp.arguments["block_name"], "coal_ore")
        self.assertEqual(opp.arguments["count"], 4)

        # Case 2: Goal is wooden_pickaxe -> Suppressed to avoid deviating from first tool
        goal_wood = {"target": "wooden_pickaxe", "stage": "Stage 0"}
        opp_wood = scanner.evaluate_opportunities(inv, state, goal_wood)
        self.assertIsNone(opp_wood)

        # Case 3: Already has 4 torches -> Does NOT trigger
        inv_torches = {"torch": 4}
        opp_torches = scanner.evaluate_opportunities(inv_torches, state, goal_stone)
        self.assertIsNone(opp_torches)

        # Case 4: Coal ore too far (> 16m) -> Does NOT trigger
        state_far = {
            "visible_resources": {
                "coal_ore": {"closest_distance": 22.0}
            }
        }
        opp_far = scanner.evaluate_opportunities(inv, state_far, goal_stone)
        self.assertIsNone(opp_far)

    def test_opportunity_scanner_structure_loot_rule(self):
        """Rule 3 (StructureLootRule): Triggers when desert_pyramid / village / ruined_portal / shipwreck detected."""
        scanner = OpportunityScanner()
        goal = {"target": "iron_pickaxe", "stage": "Stage 2"}
        inv = {"iron_ingot": 1}

        # Case 1: Desert pyramid detected in landmarks -> Triggers Priority 7 Opportunity
        state_pyramid = {
            "landmarks": {"desert_pyramid": True}
        }
        opp = scanner.evaluate_opportunities(inv, state_pyramid, goal)
        self.assertIsNotNone(opp)
        self.assertEqual(opp.name, "loot_structure")
        self.assertEqual(opp.priority, 7)
        self.assertEqual(opp.action, "explore_structure")
        self.assertEqual(opp.arguments["structure_type"], "desert_pyramid")

        # Case 2: Village detected
        state_village = {
            "landmarks": {"village": True}
        }
        opp_v = scanner.evaluate_opportunities(inv, state_village, goal)
        self.assertIsNotNone(opp_v)
        self.assertEqual(opp_v.arguments["structure_type"], "village")

    def test_opportunity_priority_ranking(self):
        """Verify highest priority opportunity wins when multiple rules trigger simultaneously."""
        scanner = OpportunityScanner()
        goal = {"target": "stone_pickaxe", "stage": "Stage 1"}
        inv = {}  # Needs wool and needs coal

        # State contains Sheep (P8), Pyramid (P7), and Coal (P6)
        state_multi = {
            "nearby_passives": [{"name": "sheep", "distance": 12.0}],
            "landmarks": {"desert_pyramid": True},
            "visible_resources": {"coal_ore": {"closest_distance": 8.0}}
        }

        # Priority 8 (wool for bed) must supersede P7 and P6
        opp = scanner.evaluate_opportunities(inv, state_multi, goal)
        self.assertIsNotNone(opp)
        self.assertEqual(opp.name, "gather_wool_for_bed")
        self.assertEqual(opp.priority, 8)

        # When wool need is resolved, Priority 7 (pyramid loot) must supersede P6 (coal)
        inv_with_bed = {"bed": 1}
        opp2 = scanner.evaluate_opportunities(inv_with_bed, state_multi, goal)
        self.assertIsNotNone(opp2)
        self.assertEqual(opp2.name, "loot_structure")
        self.assertEqual(opp2.priority, 7)

    # -------------------------------------------------------------------------
    # 4. Player Persona / Style Tests
    # -------------------------------------------------------------------------
    def test_player_style_enum_and_strategy(self):
        """Verify PlayerStyle enum parsing and StyleStrategy milestone biasing."""
        strategy = StyleStrategy()

        # Enum string resolution
        self.assertEqual(PlayerStyle.from_str("speedrunner"), PlayerStyle.SPEEDRUNNER)
        self.assertEqual(PlayerStyle.from_str("speed"), PlayerStyle.SPEEDRUNNER)
        self.assertEqual(PlayerStyle.from_str("builder"), PlayerStyle.HOMESTEAD_BUILDER)
        self.assertEqual(PlayerStyle.from_str("explorer"), PlayerStyle.EXPLORER_LOOTER)
        self.assertEqual(PlayerStyle.from_str("combat"), PlayerStyle.COMBAT_CRAWLER)

        # 1. Homestead Builder: Prioritizes hoe when missing and materials available
        inv_builder = {"cobblestone": 4, "stick": 2}
        bias_builder = strategy.get_style_milestone_bias(PlayerStyle.HOMESTEAD_BUILDER, inv_builder, {})
        self.assertIsNotNone(bias_builder)
        self.assertEqual(bias_builder["action"], "craft_item")
        self.assertEqual(bias_builder["arguments"]["item_name"], "stone_hoe")

        # 2. Explorer Looter: Prioritizes boat when missing and materials available
        inv_explorer = {"planks": 6}
        bias_explorer = strategy.get_style_milestone_bias(PlayerStyle.EXPLORER_LOOTER, inv_explorer, {})
        self.assertIsNotNone(bias_explorer)
        self.assertEqual(bias_explorer["action"], "craft_item")
        self.assertEqual(bias_explorer["arguments"]["item_name"], "oak_boat")

        # 3. Combat Crawler: Prioritizes shield when iron and planks available
        inv_combat = {"iron_ingot": 2, "planks": 8}
        bias_combat = strategy.get_style_milestone_bias(PlayerStyle.COMBAT_CRAWLER, inv_combat, {})
        self.assertIsNotNone(bias_combat)
        self.assertEqual(bias_combat["action"], "craft_item")
        self.assertEqual(bias_combat["arguments"]["item_name"], "shield")

        # 4. Speedrunner: Returns None (focuses on minimal linear dragon progression)
        bias_speed = strategy.get_style_milestone_bias(PlayerStyle.SPEEDRUNNER, inv_combat, {})
        self.assertIsNone(bias_speed)

    # -------------------------------------------------------------------------
    # 5. Planner Integration Tests
    # -------------------------------------------------------------------------
    def test_planner_opportunistic_interception(self):
        """Verify planner intercepts decision cycle with high-priority opportunistic action."""
        # Setup state with sheep within 10m and no bed in inventory
        state = {
            "inventory_items": [{"name": "log", "count": 3}],
            "health": 20,
            "food": 20,
            "nearby_passives": [{"name": "sheep", "distance": 10.0}],
            "is_busy": False
        }

        # Decide next action
        decision = asyncio.run(self.planner.decide_next_action(state))
        self.assertIsNotNone(decision)
        tool_calls = decision.get("tool_calls", [])
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "attack_target")
        self.assertEqual(tool_calls[0]["arguments"]["target_name"], "sheep")
        self.assertIn("Opportunistic priority", decision.get("text", ""))

    def test_planner_style_biasing_interception(self):
        """Verify planner applies style strategy bias when no opportunistic rule triggers."""
        # Set persona to Homestead Builder
        self.planner.set_player_style(PlayerStyle.HOMESTEAD_BUILDER)

        # Inventory with cobblestone and bed (so WoolNeedRule does not trigger)
        state = {
            "inventory_items": [
                {"name": "bed", "count": 1},
                {"name": "cobblestone", "count": 4},
                {"name": "stick", "count": 2}
            ],
            "health": 20,
            "food": 20,
            "is_busy": False
        }

        decision = asyncio.run(self.planner.decide_next_action(state))
        self.assertIsNotNone(decision)
        tool_calls = decision.get("tool_calls", [])
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "craft_item")
        self.assertEqual(tool_calls[0]["arguments"]["item_name"], "stone_hoe")
        self.assertIn("Style priority", decision.get("text", ""))


if __name__ == "__main__":
    unittest.main()
