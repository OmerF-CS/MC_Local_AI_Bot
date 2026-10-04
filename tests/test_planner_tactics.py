"""Unit tests for AutonomousCoopBrain tactics: Starvation Cooldown and Craft Interception."""
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from ai.planner import AutonomousCoopBrain


class TestPlannerTactics(unittest.TestCase):
    """Test suite covering hunger emergency rate limiting and uncraftable action interception."""

    def test_starvation_hunt_cooldown(self):
        """Verify starvation hunt action triggers once then respects cooldown."""
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer")
        state = {
            "health": 20,
            "food": 2,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "is_day": True,
            "nearby_hostiles": []
        }

        # First trigger should return hunt_food
        action1 = brain._should_use_emergency_action(state, {})
        self.assertIsNotNone(action1)
        self.assertEqual(action1["tool_calls"][0]["name"], "hunt_food")

        # Immediate second trigger should be suppressed by cooldown
        action2 = brain._should_use_emergency_action(state, {})
        self.assertIsNone(action2)

    def test_uncraftable_item_intercepted(self):
        """Verify craft_item calls with missing materials are intercepted with prerequisite tactical actions."""
        mock_ollama = MagicMock()
        # Simulate 3B model blindly returning craft_item for iron_pickaxe with 0 iron ingots
        mock_ollama.process_chat = AsyncMock(return_value={
            "text": "I will craft an iron pickaxe.",
            "tool_calls": [
                {"name": "craft_item", "arguments": {"item_name": "iron_pickaxe", "count": 1}}
            ]
        })

        brain = AutonomousCoopBrain(ollama_brain=mock_ollama, bot_owner="Omer")
        state = {
            "health": 20,
            "food": 20,
            "inventory_items": [{"name": "stone_pickaxe", "count": 1}],
            "inventory_summary": "stone_pickaxe x1",
            "is_day": True,
            "dimension": "overworld",
            "nearby_hostiles": []
        }

        decision = asyncio.run(brain.decide_next_action(state))
        self.assertIsNotNone(decision)
        tool_calls = decision.get("tool_calls", [])
        self.assertEqual(len(tool_calls), 1)

        # The impossible craft_item must be substituted with collect_block for iron!
        substituted_action = tool_calls[0]
        self.assertEqual(substituted_action["name"], "collect_block")
        self.assertEqual(substituted_action["arguments"]["block_name"], "iron")

    def test_wood_logs_satisfy_wooden_pickaxe_crafting(self):
        """Verify wood logs (e.g. cherry_log) count towards planks and sticks so craft_item is allowed."""
        from ai.progression_tree import resolve_missing_ingredients, count_equivalent_materials

        # With 4 cherry logs, planks and sticks are satisfied
        inv_with_logs = {"cherry_log": 4}
        self.assertGreaterEqual(count_equivalent_materials("planks", inv_with_logs), 4)
        self.assertGreaterEqual(count_equivalent_materials("stick", inv_with_logs), 2)
        missing = resolve_missing_ingredients("wooden_pickaxe", inv_with_logs)
        self.assertEqual(missing, [], "4 cherry logs must satisfy wooden_pickaxe crafting!")

        # With 0 wood, missing items should request wood logs, NOT unminable planks
        missing_empty = resolve_missing_ingredients("wooden_pickaxe", {})
        self.assertEqual(missing_empty, ["3x wood log"])

    def test_plank_collection_remapped_to_log(self):
        """Verify collect_block for planks is automatically remapped to log."""
        mock_ollama = MagicMock()
        mock_ollama.process_chat = AsyncMock(return_value={
            "text": "Collecting planks",
            "tool_calls": [
                {"name": "collect_block", "arguments": {"block_name": "planks", "count": 3}}
            ]
        })

        brain = AutonomousCoopBrain(ollama_brain=mock_ollama, bot_owner="Omer")
        state = {
            "health": 20,
            "food": 20,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "is_day": True,
            "dimension": "overworld",
            "nearby_hostiles": []
        }

        decision = asyncio.run(brain.decide_next_action(state))
        self.assertIsNotNone(decision)
        tool_call = decision["tool_calls"][0]
        self.assertEqual(tool_call["name"], "collect_block")
        self.assertEqual(tool_call["arguments"]["block_name"], "log")

    def test_idle_utility_tool_substituted_in_autonomous_mode(self):
        """Verify idle utility tools like list_saved_locations are replaced with milestone action."""
        mock_ollama = MagicMock()
        mock_ollama.process_chat = AsyncMock(return_value={
            "text": "Listing locations",
            "tool_calls": [
                {"name": "list_saved_locations", "arguments": {}}
            ]
        })

        brain = AutonomousCoopBrain(ollama_brain=mock_ollama, bot_owner="Omer")
        state = {
            "health": 20,
            "food": 20,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "is_day": True,
            "dimension": "overworld",
            "nearby_hostiles": []
        }

        decision = asyncio.run(brain.decide_next_action(state))
        self.assertIsNotNone(decision)
        tool_call = decision["tool_calls"][0]
        # Should be substituted with milestone action (collect_block log for wooden_pickaxe)
        self.assertEqual(tool_call["name"], "collect_block")
        self.assertEqual(tool_call["arguments"]["block_name"], "log")


if __name__ == "__main__":
    unittest.main()

