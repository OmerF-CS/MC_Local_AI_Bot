"""Unit tests for Spatial Home-Base Anchor and Hazard Memory (Phase 3).

Verifies:
1. HomeBaseManager registration, retrieval, and return triggers (inventory full, night shelter).
2. HazardMemoryManager persistent SQLite hazard_map, proximity queries, and vector safety.
3. ExplorationEngine candidate scoring and -50.0 hazard proximity penalty.
4. AutonomousCoopBrain base auto-registration and surplus deposit return routing.
"""
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.database import Database
from ai.spatial_and_exploration import HomeBaseManager, HazardMemoryManager, ExplorationEngine
from ai.planner import AutonomousCoopBrain


class TestSpatialHomeAndHazards(unittest.IsolatedAsyncioTestCase):
    """Test suite for spatial home base anchoring and persistent hazard avoidance."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_spatial.db")
        self.db = Database(self.db_path)
        self.home_mgr = HomeBaseManager(self.db)
        self.hazard_mgr = HazardMemoryManager(self.db)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_home_base_registration_and_retrieval(self):
        """Verifies registering home base coordinates and retrieving from persistent landmarks."""
        self.assertIsNone(self.home_mgr.get_home_base())

        # Register home coordinates
        success = self.home_mgr.register_home_base({"x": 120.5, "y": 68.0, "z": -45.2}, dim="overworld", source="player_bed")
        self.assertTrue(success)

        home = self.home_mgr.get_home_base()
        self.assertIsNotNone(home)
        self.assertEqual(home["name"], "home_base")
        self.assertAlmostEqual(home["x"], 120.5)
        self.assertAlmostEqual(home["y"], 68.0)
        self.assertAlmostEqual(home["z"], -45.2)
        self.assertIn("player_bed", home.get("description", ""))

    def test_should_return_home_conditions(self):
        """Verifies inventory saturation and nightfall shelter return conditions."""
        inv_dict = {"dirt": 64, "cobblestone": 64}
        state = {
            "position": {"x": 100, "y": 64, "z": 100},
            "is_day": True,
            "inventory_items": [{"name": f"item_{i}", "count": 1} for i in range(10)]
        }

        # 1. No home base registered -> returns False
        should_ret, reason = self.home_mgr.should_return_home(inv_dict, state)
        self.assertFalse(should_ret)
        self.assertEqual(reason, "no_home_base")

        # Register home base at (120, 64, 100)
        self.home_mgr.register_home_base({"x": 120, "y": 64, "z": 100})

        # 2. Normal conditions (daytime, inventory light) -> returns False
        should_ret, reason = self.home_mgr.should_return_home(inv_dict, state)
        self.assertFalse(should_ret)
        self.assertEqual(reason, "normal")

        # 3. Inventory full (>= 28 filled slots) -> returns True, "inventory_full"
        full_state = dict(state)
        full_state["inventory_items"] = [{"name": f"item_{i}", "count": 1} for i in range(29)]
        should_ret, reason = self.home_mgr.should_return_home(inv_dict, full_state)
        self.assertTrue(should_ret)
        self.assertEqual(reason, "inventory_full")

        # 4. Inventory unique filled items >= 26 -> returns True, "inventory_full"
        heavy_inv = {f"res_{i}": 5 for i in range(27)}
        should_ret, reason = self.home_mgr.should_return_home(heavy_inv, state)
        self.assertTrue(should_ret)
        self.assertEqual(reason, "inventory_full")

        # 5. Night shelter check near home base (distance = 20m <= 64m) without bed on person
        night_state = dict(state)
        night_state["is_day"] = False
        night_state["time_of_day"] = "night"
        should_ret, reason = self.home_mgr.should_return_home(inv_dict, night_state)
        self.assertTrue(should_ret)
        self.assertEqual(reason, "night_shelter")

        # 6. Night but bot carries a bed -> can sleep on the go, normal
        bed_inv = dict(inv_dict)
        bed_inv["white_bed"] = 1
        should_ret, reason = self.home_mgr.should_return_home(bed_inv, night_state)
        self.assertFalse(should_ret)
        self.assertEqual(reason, "normal")

        # 7. Night but far from home base (> 64m) -> should not walk long distance in dark
        far_state = dict(night_state)
        far_state["position"] = {"x": 500, "y": 64, "z": 500}
        should_ret, reason = self.home_mgr.should_return_home(inv_dict, far_state)
        self.assertFalse(should_ret)
        self.assertEqual(reason, "normal")

    def test_hazard_memory_storage_and_queries(self):
        """Verifies recording environmental hazards into SQLite hazard_map and spatial radius queries."""
        # Record lava lake and ravine
        self.hazard_mgr.record_hazard("overworld", 10.0, 12.0, 20.0, "lava_lake", radius=6.0)
        self.hazard_mgr.record_environmental_hazard("ravine_drop", {"x": 50.0, "y": 45.0, "z": 50.0}, dim="overworld", radius=8.0)
        self.hazard_mgr.record_hazard("the_nether", 100.0, 30.0, -80.0, "lava_sea", radius=15.0)

        # Query nearby hazards in Overworld within 40m of (12, 22)
        nearby = self.hazard_mgr.get_nearby_hazards("overworld", x=12.0, z=22.0, max_dist=40.0)
        self.assertEqual(len(nearby), 1)
        self.assertEqual(nearby[0]["hazard_type"], "lava_lake")
        self.assertLess(nearby[0]["distance"], 5.0)

        # Proximity checks via is_hazard_near (within radius 6.0 + default margin 4.0 = 10.0m)
        self.assertTrue(self.hazard_mgr.is_hazard_near("overworld", x=14.0, z=23.0))   # dist ~4.1m <= 10m
        self.assertFalse(self.hazard_mgr.is_hazard_near("overworld", x=100.0, z=100.0)) # far away
        self.assertFalse(self.hazard_mgr.is_hazard_near("the_nether", x=14.0, z=23.0))  # different dim

    def test_exploration_engine_penalizes_hazards(self):
        """Verifies ExplorationEngine docks 50 points from compass directions near recorded hazards."""
        # Bot position at (0, 0)
        pos = {"x": 0.0, "y": 64.0, "z": 0.0, "dimension": "overworld"}

        # Record a hazard 30 blocks North (x=0, z=-30)
        self.hazard_mgr.record_hazard("overworld", 0.0, 60.0, -32.0, "lava_ravine", radius=5.0)

        engine = ExplorationEngine(hazard_memory=self.hazard_mgr)
        target = engine.get_frontier_target(pos, distance=32.0)

        # The chosen direction should NOT be North due to the -50.0 penalty
        self.assertNotEqual(target["direction"], "N")
        self.assertNotIn((target["x"], target["z"]), [(0, -32)])

    async def test_brain_auto_registers_base_and_deposits_surplus(self):
        """Verifies AutonomousCoopBrain auto-anchors base from DB and returns home on full inventory."""
        # Pre-seed DB with a bed location
        with self.db.conn:
            self.db.conn.execute("INSERT INTO beds (dim, x, y, z) VALUES ('overworld', 200, 64, 300)")

        brain = AutonomousCoopBrain(ollama_brain=None, db=self.db)
        brain.cortex = MagicMock()
        brain.cortex.think_and_decide = AsyncMock(return_value=None)

        # State with full inventory (30 items), bot located far from home base at (100, 64, 150)
        state = {
            "position": {"x": 100, "y": 64, "z": 150},
            "is_day": True,
            "health": 20,
            "food": 20,
            "nearby_hostiles": [],
            "inventory_items": [{"name": f"item_{i}", "count": 64} for i in range(30)]
        }

        # 1. Decision cycle: Auto-registers home base from bed AND routes navigation back to home
        decision1 = await brain.decide_next_action(state)
        self.assertIsNotNone(decision1)

        # Verify home base auto-registered
        home = brain.home_base_manager.get_home_base()
        self.assertIsNotNone(home)
        self.assertEqual(round(home["x"]), 200)
        self.assertEqual(round(home["z"]), 300)

        # Verify navigation to home base was dispatched
        tool1 = decision1["tool_calls"][0]
        self.assertEqual(tool1["name"], "go_to_coordinates")
        self.assertEqual(tool1["arguments"]["x"], 200)
        self.assertEqual(tool1["arguments"]["z"], 300)

        # 2. When bot arrives at home (<= 4m from 200, 300): should deposit surplus materials into chest
        state_arrived = dict(state)
        state_arrived["position"] = {"x": 201, "y": 64, "z": 300}
        # Reset last_home_return_try rate-limit for test
        brain.last_home_return_try = 0.0

        decision2 = await brain.decide_next_action(state_arrived)
        self.assertIsNotNone(decision2)
        tool2 = decision2["tool_calls"][0]
        self.assertEqual(tool2["name"], "manage_chest")
        self.assertEqual(tool2["arguments"]["action_type"], "deposit_surplus")


if __name__ == "__main__":
    unittest.main()
