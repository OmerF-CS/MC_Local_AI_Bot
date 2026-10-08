"""Unit tests for MC Local AI Bot V2 Phase 2 & Phase 3:
Persistent Ore Map, Monotonic Checkpoints, Chest Recovery, and Combat Tuning.
"""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import MagicMock, AsyncMock

from core.database import Database
from ai.planner import AutonomousCoopBrain
from ai.progression_tree import (
    get_stage_rank,
    get_optimal_ore_height,
    get_milestone_by_stage,
    MILESTONES
)


class TestV2Phase2And3Features(unittest.TestCase):
    """Test suite for Ore Map, Checkpoint Resumption, and Combat/Mining Intelligence."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_v2_p2p3.db")
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_ore_map_persistence_and_queries(self):
        """Verify discovering, storing, finding, and marking ores as mined in SQLite."""
        # Save discovered ores
        self.db.save_ore("overworld", 100, 16, 200, "iron_ore")
        self.db.save_ore("overworld", 102, -58, 205, "deepslate_diamond_ore")
        self.db.save_ore("the_nether", 45, 15, -80, "ancient_debris")

        # Duplicate save should be ignored gracefully (UNIQUE constraint)
        self.db.save_ore("overworld", 100, 16, 200, "iron_ore")

        # Query unmined ores near (100, 16, 200)
        ores = self.db.get_unmined_ores("overworld", block_type="iron", x=98.0, y=16.0, z=199.0, max_dist=30.0)
        self.assertEqual(len(ores), 1)
        self.assertEqual(ores[0]["block"], "iron_ore")
        self.assertEqual(ores[0]["x"], 100)
        self.assertEqual(ores[0]["y"], 16)
        self.assertAlmostEqual(ores[0]["distance"], 2.236, places=2)

        # Query diamond ores
        diamonds = self.db.get_unmined_ores("overworld", block_type="diamond", x=100.0, y=-50.0, z=200.0, max_dist=50.0)
        self.assertEqual(len(diamonds), 1)
        self.assertEqual(diamonds[0]["block"], "deepslate_diamond_ore")

        # Mark iron ore as mined
        self.db.mark_ore_mined("overworld", 100, 16, 200)
        ores_after = self.db.get_unmined_ores("overworld", block_type="iron", x=98.0, y=16.0, z=199.0, max_dist=30.0)
        self.assertEqual(len(ores_after), 0)

    def test_monotonic_progression_checkpoints_do_not_downgrade(self):
        """Verify that when the bot restarts or inventory is empty, saved checkpoints are preserved."""
        # Pre-seed progression checkpoint at DIAMOND era
        self.db.save_progression(stage="DIAMOND", target="diamond_pickaxe", inventory={"diamond": 3, "stick": 2})

        mock_brain = MagicMock()
        mock_brain.process_chat = AsyncMock(return_value={"text": "crafting", "tool_calls": []})
        brain = AutonomousCoopBrain(mock_brain, bot_owner="Omer", db=self.db)
        self.assertEqual(brain.checkpoint_stage, "DIAMOND")
        self.assertEqual(brain.checkpoint_target, "diamond_pickaxe")

        # Bot spawns with empty inventory (e.g. after death or server reboot)
        empty_state = {
            "health": 20,
            "food": 20,
            "is_day": True,
            "inventory_items": [],
            "position": {"x": 0, "y": 64, "z": 0},
            "dimension": "overworld"
        }

        # Decide next action
        asyncio.run(brain.decide_next_action(empty_state))

        # Crucial check: database progression checkpoint must NOT have been downgraded to WOOD!
        latest = self.db.get_latest_progression()
        self.assertEqual(latest["stage"], "DIAMOND")
        self.assertEqual(latest["target"], "diamond_pickaxe")

    def test_checkpoint_chest_tool_recovery(self):
        """Verify that if the bot lost tools but they are stored in a nearby chest, it retrieves them."""
        # Checkpoint is IRON_GEAR
        self.db.save_progression(stage="IRON_GEAR", target="iron_pickaxe", inventory={})

        # Save a nearby chest containing iron_pickaxe
        chest_items = [{"name": "iron_pickaxe", "count": 1}, {"name": "shield", "count": 1}]
        self.db.save_chest_location("overworld", 5.0, 64.0, 5.0, chest_items)

        mock_brain = MagicMock()
        brain = AutonomousCoopBrain(mock_brain, bot_owner="Omer", db=self.db)

        # Empty inventory state near the chest
        state = {
            "health": 20,
            "food": 20,
            "is_day": True,
            "inventory_items": [],
            "position": {"x": 4.0, "y": 64.0, "z": 4.0},
            "dimension": "overworld"
        }

        action = asyncio.run(brain.decide_next_action(state))
        self.assertIsNotNone(action)
        self.assertEqual(len(action["tool_calls"]), 1)
        tool_call = action["tool_calls"][0]
        self.assertEqual(tool_call["name"], "manage_chest")
        self.assertEqual(tool_call["arguments"]["action_type"], "withdraw")
        self.assertEqual(tool_call["arguments"]["item_name"], "iron_pickaxe")

    def test_optimal_ore_heights_and_milestone_ranks(self):
        """Verify 1.20.4 optimal mining altitudes and progressive milestone ranks."""
        self.assertEqual(get_optimal_ore_height("iron"), 16)
        self.assertEqual(get_optimal_ore_height("iron_ore"), 16)
        self.assertEqual(get_optimal_ore_height("diamond"), -58)
        self.assertEqual(get_optimal_ore_height("deepslate_diamond_ore"), -58)
        self.assertEqual(get_optimal_ore_height("gold"), -16)
        self.assertEqual(get_optimal_ore_height("coal"), 95)
        self.assertEqual(get_optimal_ore_height("ancient_debris"), 15)

        # Milestone stage ranking monotonic verification
        self.assertLess(get_stage_rank("WOOD"), get_stage_rank("STONE"))
        self.assertLess(get_stage_rank("STONE"), get_stage_rank("FURNACE"))
        self.assertLess(get_stage_rank("FURNACE"), get_stage_rank("IRON_GEAR"))
        self.assertLess(get_stage_rank("IRON_GEAR"), get_stage_rank("DIAMOND"))
        self.assertLess(get_stage_rank("DIAMOND"), get_stage_rank("NETHER"))
        self.assertLess(get_stage_rank("NETHER"), get_stage_rank("EYE_OF_ENDER"))
        self.assertLess(get_stage_rank("EYE_OF_ENDER"), get_stage_rank("THE_END"))

        # Look up milestone by stage
        diamond_m = get_milestone_by_stage("DIAMOND")
        self.assertIsNotNone(diamond_m)
        self.assertEqual(diamond_m["target"], "diamond_pickaxe")

    def test_ore_map_navigation_in_planner(self):
        """Verify that when unmined ores are in the SQLite database, planner passes target coordinates."""
        # Save known iron ore vein
        self.db.save_ore("overworld", 120, 16, -45, "iron_ore")
        self.db.save_ore("overworld", 88, -58, -35, "deepslate_diamond_ore")

        mock_brain = MagicMock()
        brain = AutonomousCoopBrain(mock_brain, bot_owner="Omer", db=self.db)

        # State with cobblestone pickaxe ready to mine iron
        state = {
            "health": 20,
            "food": 20,
            "is_day": True,
            "inventory_items": [{"name": "stone_pickaxe", "count": 1}],
            "position": {"x": 100, "y": 64, "z": -40},
            "dimension": "overworld"
        }
        inv = {"stone_pickaxe": 1}

        # Query milestone for iron_pickaxe
        desc, action = brain.get_milestone_action({"target": "iron_pickaxe"}, inv, state)
        self.assertIn("Navigate to known", desc)
        self.assertEqual(action["name"], "collect_block")
        self.assertEqual(action["arguments"]["target_x"], 120)
        self.assertEqual(action["arguments"]["target_y"], 16)
        self.assertEqual(action["arguments"]["target_z"], -45)

        # Query milestone for diamond_pickaxe
        inv_diamond = {"iron_pickaxe": 1}
        desc_dia, action_dia = brain.get_milestone_action({"target": "diamond_pickaxe"}, inv_diamond, state)
        self.assertIn("Navigate to known", desc_dia)
        self.assertEqual(action_dia["name"], "collect_block")
        self.assertEqual(action_dia["arguments"]["target_x"], 88)
        self.assertEqual(action_dia["arguments"]["target_y"], -58)
        self.assertEqual(action_dia["arguments"]["target_z"], -35)

    def test_new_tool_definitions(self):
        """Verify that trade_with_villager, brew_potion, and repair_gear_anvil are defined."""
        from ai.tools import MINECRAFT_TOOLS
        tool_names = [t["function"]["name"] for t in MINECRAFT_TOOLS]
        self.assertIn("trade_with_villager", tool_names)
        self.assertIn("brew_potion", tool_names)
        self.assertIn("repair_gear_anvil", tool_names)

    def test_js_combat_and_ore_navigation_integrity(self):
        """Verify that minecraft_bot/bot.js contains mob-specific tactics and ore navigation code."""
        bot_js_path = os.path.join(os.path.dirname(__file__), "..", "minecraft_bot", "bot.js")
        with open(bot_js_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Ore map navigation in collect_block
        self.assertIn("args.target_x !== undefined", code)
        self.assertIn("GoalNear(oreVec.x, oreVec.y, oreVec.z, 2)", code)

        # F3 Combat: Ranged bow combat & ballistics
        self.assertIn("getRangedCombatGear", code)
        self.assertIn("performRangedBowShot", code)
        self.assertIn("pitchOffset", code)

        # F3 Combat: Enderman, Skeleton, Creeper, Witch tactics
        self.assertIn("isEndermanGazeRisk", code)
        self.assertIn("performWaterBarrierDefense", code)
        self.assertIn("water_bucket", code)
        self.assertIn("creeper", code)
        self.assertIn("skeleton", code)
        self.assertIn("witch", code)

        # F2 Extensions: Villager trading, brewing, anvil
        self.assertIn("tradeWithVillager", code)
        self.assertIn("brewPotion", code)
        self.assertIn("repairGearAnvil", code)


if __name__ == "__main__":
    unittest.main()

