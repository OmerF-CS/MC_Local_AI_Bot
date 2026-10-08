"""Unit tests for MC Local AI Bot V2 Phase 2 & Phase 3:
Persistent Ore Map, Monotonic Checkpoints, Chest Recovery, and Combat Tuning.
"""
import asyncio
import json
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
        self.assertIn("barter_with_piglins", tool_names)
        self.assertIn("hunt_hoglin", tool_names)
        self.assertIn("setup_respawn_anchor", tool_names)
        self.assertIn("explore_end_city", tool_names)
        self.assertIn("eat_chorus_fruit", tool_names)

    def test_anvil_and_trading_and_brewing_in_planner(self):
        """Verify that planner triggers anvil repair, village trading, and potion brewing when preconditions meet."""
        mock_brain = MagicMock()
        brain = AutonomousCoopBrain(mock_brain, bot_owner="Omer", db=self.db)

        # 1. Anvil Repair Trigger
        state_damaged = {
            "health": 20, "food": 20, "dimension": "overworld",
            "low_durability_gear": True, "nearby_anvil": True
        }
        desc, act = brain.get_milestone_action({"target": "iron_pickaxe"}, {"iron_pickaxe": 1}, state_damaged)
        self.assertEqual(act["name"], "repair_gear_anvil")

        # 2. Village Trading Trigger
        state_village = {
            "health": 20, "food": 20, "dimension": "overworld",
            "nearby_villagers_count": 3
        }
        desc_tr, act_tr = brain.get_milestone_action({"target": "iron_pickaxe"}, {"iron_pickaxe": 1, "emerald": 5}, state_village)
        self.assertEqual(act_tr["name"], "trade_with_villager")

        # 3. Potion Brewing Trigger (Fire Resistance)
        state_brewing = {
            "health": 20, "food": 20, "dimension": "the_nether",
            "nearby_brewing_stand": True, "fire_resistance_active": False
        }
        inv_brew = {"iron_pickaxe": 1, "nether_wart": 2, "water_bottle": 1, "magma_cream": 1}
        desc_br, act_br = brain.get_milestone_action({"target": "nether_portal"}, inv_brew, state_brewing)
        self.assertEqual(act_br["name"], "brew_potion")
        self.assertEqual(act_br["arguments"]["ingredient"], "magma_cream")

    def test_nether_f4_and_end_f5_planner_flow(self):
        """Verify Piglin bartering, Hoglin hunting, and End City exploration trigger in planner."""
        mock_brain = MagicMock()
        brain = AutonomousCoopBrain(mock_brain, bot_owner="Omer", db=self.db)

        # 1. Piglin Bartering Trigger when pearls needed
        state_piglin = {
            "health": 20, "food": 20, "dimension": "the_nether",
            "nearby_piglins_count": 2
        }
        inv_piglin = {"gold_ingot": 5, "blaze_rod": 6, "blaze_powder": 2}
        desc_barter, act_barter = brain.get_milestone_action({"target": "eye_of_ender"}, inv_piglin, state_piglin)
        self.assertEqual(act_barter["name"], "barter_with_piglins")

        # 2. End City Exploration Trigger after dragon defeat
        state_end_city = {
            "health": 20, "food": 20, "dimension": "the_end",
            "dragon_defeated": True, "elytra_acquired": False
        }
        inv_end = {"ender_pearl": 4}
        desc_end, act_end = brain.get_milestone_action({"target": "ender_dragon"}, inv_end, state_end_city)
        self.assertEqual(act_end["name"], "explore_end_city")

    def test_js_combat_and_ore_navigation_integrity(self):
        """Verify that minecraft_bot/bot.js contains mob-specific tactics, F4 Nether, and F5 End code."""
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

        # F3 Combat: Enderman, Skeleton, Creeper, Witch tactics & fireball deflection
        self.assertIn("isEndermanGazeRisk", code)
        self.assertIn("performWaterBarrierDefense", code)
        self.assertIn("water_bucket", code)
        self.assertIn("creeper", code)
        self.assertIn("skeleton", code)
        self.assertIn("witch", code)
        self.assertIn("fireball", code)

        # F2 Extensions: Villager trading, brewing, anvil
        self.assertIn("tradeWithVillager", code)
        self.assertIn("brewPotion", code)
        self.assertIn("repairGearAnvil", code)

        # F4 & F5 Extensions: Piglin barter, Hoglin, Respawn anchor, End City, Chorus fruit
        self.assertIn("barterWithPiglins", code)
        self.assertIn("huntHoglin", code)
        self.assertIn("setupRespawnAnchor", code)
        self.assertIn("exploreEndCity", code)
        self.assertIn("eatChorusFruit", code)
        self.assertIn("exploreNetherFortress", code)
        self.assertIn("exploreBastion", code)
        self.assertIn("flyWithElytra", code)
        self.assertIn("Combat Funnel", code)

    def test_spare_tools_and_fortress_bastion_elytra_in_planner(self):
        """Verify spare tool logic, Nether fortress, bastion, and Elytra flight triggers in planner."""
        mock_brain = MagicMock()
        brain = AutonomousCoopBrain(mock_brain, bot_owner="Omer", db=self.db)

        # 1. Spare iron pickaxe craft trigger when only 1 pickaxe and surplus iron
        state_gear = {"health": 20, "food": 20, "dimension": "overworld"}
        inv_spare = {"shield": 1, "iron_pickaxe": 1, "iron_ingot": 4, "stick": 3}
        desc_spare, act_spare = brain.get_milestone_action({"target": "diamond_pickaxe"}, inv_spare, state_gear)
        self.assertEqual(act_spare["name"], "craft_item")
        self.assertEqual(act_spare["arguments"]["item_name"], "iron_pickaxe")

        # 2. Nether Fortress exploration trigger when blaze rods missing
        state_nether = {
            "health": 20, "food": 20, "dimension": "the_nether",
            "nearby_blazes_count": 0, "fortress_found": False
        }
        inv_nether = {"iron_pickaxe": 2, "gold_ingot": 0, "blaze_rod": 0}
        desc_fortress, act_fortress = brain.get_milestone_action({"target": "nether_portal"}, inv_nether, state_nether)
        self.assertEqual(act_fortress["name"], "explore_nether_fortress")

        # 3. Bastion Remnant exploration trigger when bastion detected
        state_bastion = {
            "health": 20, "food": 20, "dimension": "the_nether",
            "nearby_bastion": True
        }
        desc_bastion, act_bastion = brain.get_milestone_action({"target": "nether_portal"}, inv_nether, state_bastion)
        self.assertEqual(act_bastion["name"], "explore_bastion")

        # 4. Elytra flight trigger after acquiring Elytra and having firework rockets
        state_elytra = {
            "health": 20, "food": 20, "dimension": "the_end",
            "dragon_defeated": True, "elytra_acquired": True,
            "travel_target": {"x": 500, "y": 80, "z": -300}
        }
        inv_elytra = {"elytra": 1, "firework_rocket": 12}
        desc_fly, act_fly = brain.get_milestone_action({"target": "enter_exit_portal"}, inv_elytra, state_elytra)
        self.assertEqual(act_fly["name"], "fly_with_elytra")
        self.assertEqual(act_fly["arguments"]["x"], 500)

        # 5. Emergency Chorus fruit fallback when falling
        state_falling = {
            "health": 20, "food": 20, "dimension": "the_end",
            "is_falling": True
        }
        fallback_act = brain.generate_fallback_action({"target": "ender_dragon"}, {"chorus_fruit": 5}, None, state_falling)
        self.assertIsNotNone(fallback_act)
        self.assertEqual(fallback_act["name"], "eat_chorus_fruit")

    def test_benchmark_models_engine(self):
        """Verify the 3B vs 7B benchmark engine, JSON format validation, and schema compliance."""
        from scripts.benchmark_models import validate_model_response, benchmark_model, BENCHMARK_PROMPTS

        # 1. Valid JSON and tool call schema
        sample_valid = json.dumps({
            "text": "Crafting shield for protection",
            "tool_calls": [{"name": "craft_item", "arguments": {"item_name": "shield"}}]
        })
        is_json, is_schema, is_acc, call = validate_model_response(sample_valid, "craft_item")
        self.assertTrue(is_json)
        self.assertTrue(is_schema)
        self.assertTrue(is_acc)
        self.assertEqual(call["name"], "craft_item")

        # 2. Invalid non-JSON text
        is_json_inv, is_schema_inv, is_acc_inv, _ = validate_model_response("I will go mine some trees now without JSON", "collect_block")
        self.assertFalse(is_json_inv)
        self.assertFalse(is_schema_inv)
        self.assertFalse(is_acc_inv)

        # 3. Model Benchmark in simulated mock mode
        result_3b = benchmark_model("qwen2.5:3b", BENCHMARK_PROMPTS[:4], is_mock=True)
        self.assertEqual(result_3b["json_validity_pct"], 100.0)
        self.assertEqual(result_3b["schema_compliance_pct"], 100.0)
        self.assertEqual(result_3b["milestone_accuracy_pct"], 100.0)
        self.assertGreater(result_3b["avg_latency_ms"], 0)


if __name__ == "__main__":
    unittest.main()


