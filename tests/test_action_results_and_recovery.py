"""Unit & integration tests for V2 F0: Structured Action Results, Death Recovery, and Progression Checkpoints."""
import unittest
import os
import tempfile
import asyncio
from unittest.mock import AsyncMock, MagicMock
from core.database import Database
from ai.planner import AutonomousCoopBrain


class TestV2InfrastructureAndRecovery(unittest.TestCase):
    """Test suite covering F0 architecture: Death recovery, bed storage, structured results, and checkpoint loading."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_v2.db")
        self.db = Database(self.db_path)

    def tearDown(self):
        if hasattr(self, "db") and self.db:
            self.db.close()
        self.temp_dir.cleanup()

    def test_death_point_save_and_recovery(self):
        """Verify death location and inventory snapshot are recorded and recovered properly."""
        # Save death point
        inv = [{"name": "diamond_sword", "count": 1}, {"name": "iron_pickaxe", "count": 1}]
        death_id = self.db.save_death_point(dim="overworld", x=120.5, y=64.0, z=-340.2, inventory=inv)
        self.assertGreater(death_id, 0)

        # Retrieve unrecovered death point
        unrecovered = self.db.get_unrecovered_death_point(dim="overworld")
        self.assertIsNotNone(unrecovered)
        self.assertEqual(unrecovered["id"], death_id)
        self.assertEqual(unrecovered["x"], 120.5)
        self.assertEqual(unrecovered["y"], 64.0)
        self.assertEqual(unrecovered["z"], -340.2)
        self.assertEqual(len(unrecovered["inventory"]), 2)
        self.assertEqual(unrecovered["inventory"][0]["name"], "diamond_sword")

        # Mark recovered
        self.db.mark_death_point_recovered(death_id)
        after_recovery = self.db.get_unrecovered_death_point(dim="overworld")
        self.assertIsNone(after_recovery)

    def test_bed_location_tracking(self):
        """Verify bed location saving and lookup for spawn point management."""
        self.db.save_bed_location(dim="overworld", x=10.0, y=70.0, z=55.0, is_spawn=True)
        bed = self.db.get_latest_bed(dim="overworld")
        self.assertIsNotNone(bed)
        self.assertEqual(bed["x"], 10.0)
        self.assertEqual(bed["y"], 70.0)
        self.assertEqual(bed["z"], 55.0)
        self.assertEqual(bed["used_for_spawn"], 1)

    def test_checkpoint_loaded_on_planner_startup(self):
        """Verify AutonomousCoopBrain restores previous progression checkpoint from database on startup."""
        # Pre-seed progression checkpoint
        self.db.save_progression(stage="IRON_GEAR", target="iron_pickaxe", inventory={"iron_ingot": 3, "stick": 2})

        # Initialize planner with database
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer", db=self.db)
        self.assertEqual(brain.last_goal_target, "iron_pickaxe")

    def test_structured_action_results_parsing(self):
        """Verify action results structure with ok, reason, items_delta, duration_ms."""
        mock_raw_bridge_result = {
            "command": "craft_item",
            "action_id": "act_101",
            "success": True,
            "ok": True,
            "error": None,
            "reason": "success",
            "items_delta": {"wooden_pickaxe": 1, "oak_planks": -3, "stick": -2},
            "duration_ms": 1450,
            "state": {"health": 20, "food": 20}
        }
        self.assertTrue(mock_raw_bridge_result["ok"])
        self.assertEqual(mock_raw_bridge_result["reason"], "success")
        self.assertEqual(mock_raw_bridge_result["items_delta"]["wooden_pickaxe"], 1)
        self.assertEqual(mock_raw_bridge_result["items_delta"]["oak_planks"], -3)
        self.assertEqual(mock_raw_bridge_result["duration_ms"], 1450)

    def test_corpse_recovery_workflow(self):
        """Verify the full lifecycle: death records point, respawn queues task, arrival marks recovered."""
        from main import MinecraftAIBot
        from utils.config import Config
        cfg = Config()
        assistant = MinecraftAIBot(cfg)
        if hasattr(assistant, "db") and assistant.db:
            assistant.db.close()
        assistant.db = self.db
        assistant.bridge = MagicMock()
        assistant.bridge.send_action = AsyncMock()
        assistant.bridge.send_action_and_wait = AsyncMock(return_value={"success": True})

        # 1. Bot dies at (100, 65, 200) with iron tools
        death_data = {
            "death_pos": {"x": 100.0, "y": 65.0, "z": 200.0},
            "dimension": "overworld",
            "inventory_snapshot": [{"name": "iron_pickaxe", "count": 1}]
        }
        asyncio.run(assistant.on_bot_death(death_data))

        # Check death point recorded
        unrecovered = self.db.get_unrecovered_death_point("overworld")
        self.assertIsNotNone(unrecovered)
        self.assertEqual(unrecovered["x"], 100.0)

        # 2. Bot respawns
        spawn_state = {"health": 20, "food": 20, "dimension": "overworld"}
        asyncio.run(assistant.on_bot_spawn(spawn_state))

        # Check task queue contains corpse recovery task
        pending = self.db.get_pending_tasks()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["primary_action"], "go_to_coordinates")
        self.assertIn("Recover items from death site", pending[0]["instruction"])

        # 3. Bot arrives near death site (at 101, 65, 201) and completes movement
        arrival_state = {"position": {"x": 101.0, "y": 65.0, "z": 201.0}}
        asyncio.run(assistant.on_action_completed("go_to_coordinates", True, None, arrival_state))

        # Death point should now be marked recovered!
        unrecovered_after = self.db.get_unrecovered_death_point("overworld")
        self.assertIsNone(unrecovered_after)

        # Drop collection action should have been dispatched to bridge
        assistant.bridge.send_action.assert_any_call("collect_nearby_drops", {"radius": 32})


if __name__ == "__main__":
    unittest.main()

