"""Unit tests for Sustainable Farming and Universal Shelter Enclosure Engine."""
import unittest
from ai.farming import calculate_food_points, should_prioritize_farming, get_farming_action_plan
from ai.shelter import (
    is_usable_shelter_block,
    get_usable_building_blocks,
    calculate_total_building_blocks,
    select_shelter_strategy,
    should_break_out_of_shelter
)
from ai.tools import MINECRAFT_TOOLS
from ai.planner import AutonomousCoopBrain


class TestFarmingAndShelter(unittest.TestCase):

    def test_farming_tools_registered(self):
        """Verify farm_crops, build_shelter, and break_out_shelter exist in tools registry."""
        tool_names = [t["function"]["name"] for t in MINECRAFT_TOOLS if t.get("type") == "function"]
        self.assertIn("farm_crops", tool_names)
        self.assertIn("build_shelter", tool_names)
        self.assertIn("break_out_shelter", tool_names)

        shelter_tool = next(t for t in MINECRAFT_TOOLS if t["function"]["name"] == "build_shelter")
        self.assertIn("mode", shelter_tool["function"]["parameters"]["properties"])

        farm_tool = next(t for t in MINECRAFT_TOOLS if t["function"]["name"] == "farm_crops")
        self.assertIn("action_type", farm_tool["function"]["parameters"]["properties"])

    def test_calculate_food_points(self):
        """Verify calculation of potential nutrition points from food and crops."""
        inv = {
            "bread": 4,         # 4 * 5 = 20
            "cooked_beef": 2,   # 2 * 8 = 16
            "hay_block": 2,     # 2 * 15 = 30
            "dirt": 64          # 0
        }
        total = calculate_food_points(inv)
        self.assertEqual(total, 66)

    def test_should_prioritize_farming(self):
        """Verify farming triggers on low food reserves or village hay discoveries."""
        # Low food + visible hay bales -> True
        low_inv = {"bread": 1}
        state_with_hay = {
            "food": 10,
            "visible_resources": {"hay_block": {"total_found": 5}}
        }
        self.assertTrue(should_prioritize_farming(low_inv, state_with_hay))

        # Abundant food -> False if no hay
        full_inv = {"bread": 20}
        state_no_hay = {
            "food": 20,
            "visible_resources": {}
        }
        self.assertFalse(should_prioritize_farming(full_inv, state_no_hay))

    def test_farming_action_plan_priority(self):
        """Verify hay bales take highest priority in action planning."""
        state_hay = {
            "visible_resources": {
                "hay_block": {"total_found": 3},
                "wheat": {"total_found": 5}
            }
        }
        plan = get_farming_action_plan({}, state_hay)
        self.assertEqual(plan["name"], "farm_crops")
        self.assertEqual(plan["arguments"]["action_type"], "harvest_hay_bales")

    def test_universal_shelter_block_recognition(self):
        """Verify recognition of diverse vanilla Minecraft blocks for building."""
        self.assertTrue(is_usable_shelter_block("cobblestone"))
        self.assertTrue(is_usable_shelter_block("cobbled_deepslate"))
        self.assertTrue(is_usable_shelter_block("dirt"))
        self.assertTrue(is_usable_shelter_block("stone"))
        self.assertTrue(is_usable_shelter_block("oak_planks"))
        self.assertTrue(is_usable_shelter_block("netherrack"))
        self.assertTrue(is_usable_shelter_block("end_stone"))
        self.assertTrue(is_usable_shelter_block("sandstone"))
        self.assertTrue(is_usable_shelter_block("tuff"))
        self.assertTrue(is_usable_shelter_block("mud"))

        # Non-building items
        self.assertFalse(is_usable_shelter_block("diamond"))
        self.assertFalse(is_usable_shelter_block("iron_ingot"))
        self.assertFalse(is_usable_shelter_block("stick"))

    def test_shelter_strategy_selection(self):
        """Verify adaptive strategy selection between canopy, box, and zero-resource burrow."""
        # Enderman attack -> canopy roof
        state_enderman = {"nearby_hostiles": ["Enderman (8m away)"]}
        strategy = select_shelter_strategy({"dirt": 30}, state_enderman)
        self.assertEqual(strategy, "enderman_roof")

        # Plentiful blocks -> emergency box
        state_zombie = {"nearby_hostiles": ["Zombie (6m away)"]}
        strategy = select_shelter_strategy({"cobblestone": 16}, state_zombie)
        self.assertEqual(strategy, "emergency_box")

        # Zero or minimal blocks -> burrowing hole
        strategy = select_shelter_strategy({"cobblestone": 2}, state_zombie)
        self.assertEqual(strategy, "burrow")

    def test_should_break_out_of_shelter(self):
        """Verify unbunker conditions require safety, daylight, and health."""
        # Safe conditions
        safe_state = {
            "is_day": True,
            "health": 18,
            "food": 16,
            "dimension": "overworld",
            "nearby_hostiles": []
        }
        self.assertTrue(should_break_out_of_shelter(safe_state))

        # Night danger -> remain sheltered
        night_state = {
            "is_day": False,
            "health": 18,
            "food": 16,
            "dimension": "overworld",
            "nearby_hostiles": []
        }
        self.assertFalse(should_break_out_of_shelter(night_state))

    def test_emergency_shelter_reflex_in_planner(self):
        """Verify AutonomousCoopBrain builds an emergency bunker on critical health."""
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer")
        critical_state = {
            "health": 4,
            "food": 14,
            "nearby_hostiles": ["Creeper (5m away)"],
            "is_day": True
        }
        emergency = brain._should_use_emergency_action(critical_state, {"cobblestone": 20})
        self.assertIsNotNone(emergency)
        self.assertEqual(emergency["tool_calls"][0]["name"], "build_shelter")


if __name__ == "__main__":
    unittest.main()
