"""Unit tests for MC Local AI Bot V2 Phase 1: Life Cycle Mechanics (Beds, Farming, Breeding, Fishing, Chests, Phantoms)."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import MagicMock, AsyncMock

from core.database import Database
from ai.tools import MINECRAFT_TOOLS
from ai.planner import AutonomousCoopBrain
from core.chat_handler import MinecraftChatHandler
from utils.config import Config


class TestV2Phase1LifeCycle(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_lifecycle.db")
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_new_lifecycle_tools_in_registry(self):
        """Verify breed_animals, catch_fish, and manage_chest exist in MINECRAFT_TOOLS."""
        tool_names = [t["function"]["name"] for t in MINECRAFT_TOOLS if t.get("type") == "function"]
        self.assertIn("breed_animals", tool_names)
        self.assertIn("catch_fish", tool_names)
        self.assertIn("manage_chest", tool_names)

        chest_tool = next(t for t in MINECRAFT_TOOLS if t["function"]["name"] == "manage_chest")
        self.assertIn("action_type", chest_tool["function"]["parameters"]["properties"])
        self.assertIn("target_item", chest_tool["function"]["parameters"]["properties"])

        breed_tool = next(t for t in MINECRAFT_TOOLS if t["function"]["name"] == "breed_animals")
        self.assertIn("animal_type", breed_tool["function"]["parameters"]["properties"])

    def test_chest_database_storage_and_query(self):
        """Verify saving and querying chest storage locations and snapshots in SQLite."""
        items = [{"name": "cobblestone", "count": 64}, {"name": "dirt", "count": 32}]
        chest_id = self.db.save_chest_location("overworld", 10.0, 64.0, 20.0, items)
        self.assertIsInstance(chest_id, int)

        # Query nearby within 15 meters
        nearby = self.db.get_nearby_chests("overworld", 12.0, 64.0, 21.0, max_dist=15.0)
        self.assertEqual(len(nearby), 1)
        self.assertEqual(nearby[0]["x"], 10.0)
        self.assertEqual(len(nearby[0]["items"]), 2)
        self.assertEqual(nearby[0]["items"][0]["name"], "cobblestone")

        # Far distance query should return empty
        far = self.db.get_nearby_chests("overworld", 300.0, 64.0, 300.0, max_dist=20.0)
        self.assertEqual(len(far), 0)

    def test_phantom_risk_and_night_sleep_trigger(self):
        """Verify AutonomousCoopBrain prioritizes sleep when phantom risk is detected or night falls."""
        mock_ollama = MagicMock()
        brain = AutonomousCoopBrain(ollama_brain=mock_ollama, bot_owner="Omer", db=self.db)

        # State 1: Overworld with phantom risk (over 3 days awake) and a bed in inventory
        state_phantom = {
            "dimension": "overworld",
            "health": 20,
            "food": 20,
            "phantom_risk": True,
            "should_sleep": False,
            "inventory_items": [{"name": "white_bed", "count": 1}],
            "visible_resources": {},
            "nearby_hostiles": []
        }
        action = asyncio.run(brain.decide_next_action(state_phantom))
        self.assertIsNotNone(action)
        self.assertEqual(action["tool_calls"][0]["name"], "sleep_in_bed")

        # State 2: Nighttime (should_sleep=True) with wool and planks to craft a bed
        brain.last_sleep_try_time = 0.0  # Reset cooldown
        state_night = {
            "dimension": "overworld",
            "health": 20,
            "food": 20,
            "phantom_risk": False,
            "should_sleep": True,
            "inventory_items": [
                {"name": "white_wool", "count": 3},
                {"name": "oak_planks", "count": 4}
            ],
            "visible_resources": {},
            "nearby_hostiles": []
        }
        action2 = asyncio.run(brain.decide_next_action(state_night))
        self.assertIsNotNone(action2)
        self.assertEqual(action2["tool_calls"][0]["name"], "sleep_in_bed")

    def test_inventory_full_chest_trigger(self):
        """Verify AutonomousCoopBrain prioritizes chest storage when inventory has >= 32 filled stacks."""
        mock_ollama = MagicMock()
        brain = AutonomousCoopBrain(ollama_brain=mock_ollama, bot_owner="Omer", db=self.db)

        # Build 33 item stacks
        full_inv_items = [{"name": f"item_{i}", "count": 64} for i in range(33)]
        state_full = {
            "dimension": "overworld",
            "health": 20,
            "food": 20,
            "phantom_risk": False,
            "should_sleep": False,
            "inventory_items": full_inv_items,
            "nearby_hostiles": []
        }
        action = asyncio.run(brain.decide_next_action(state_full))
        self.assertIsNotNone(action)
        self.assertEqual(action["tool_calls"][0]["name"], "manage_chest")
        self.assertEqual(action["tool_calls"][0]["arguments"]["action_type"], "deposit_surplus")

    def test_chat_commands_lifecycle_dispatch(self):
        """Verify player chat commands (!breed, !fish, !chest, !withdraw) route and register tasks correctly."""
        bot_mock = MagicMock()
        bot_mock.config = Config()
        bot_mock.db = self.db
        bot_mock.bridge = MagicMock()
        bot_mock.bridge.send_action = AsyncMock()
        bot_mock.active_player_task = None

        handler = MinecraftChatHandler(bot_mock)
        state = {"health": 20, "food": 20}

        # 1. Test !breed cow
        asyncio.run(handler.handle_chat("Omer", "!breed cow", state))
        bot_mock.bridge.send_action.assert_called_with("breed_animals", {"animal_type": "cow"})
        self.assertIsNotNone(bot_mock.active_player_task)
        self.assertEqual(bot_mock.active_player_task["primary_action"], "breed_animals")

        # 2. Test !fish 5
        asyncio.run(handler.handle_chat("Omer", "!fish 5", state))
        bot_mock.bridge.send_action.assert_called_with("catch_fish", {"count": 5})
        self.assertEqual(bot_mock.active_player_task["primary_action"], "catch_fish")

        # 3. Test !chest (deposit)
        asyncio.run(handler.handle_chat("Omer", "!chest", state))
        bot_mock.bridge.send_action.assert_called_with("manage_chest", {"action_type": "deposit_surplus"})

        # 4. Test !withdraw iron_ingot 3
        asyncio.run(handler.handle_chat("Omer", "!withdraw iron_ingot 3", state))
        bot_mock.bridge.send_action.assert_called_with(
            "manage_chest",
            {"action_type": "withdraw", "target_item": "iron_ingot", "count": 3}
        )


if __name__ == "__main__":
    unittest.main()
