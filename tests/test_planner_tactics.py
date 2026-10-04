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


if __name__ == "__main__":
    unittest.main()
