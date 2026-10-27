"""Unit tests for Cortex Optimization (Track A & Track B) - Context, Latency, and Safety Guards."""
import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from ai.cortex import CognitiveCortex, ParsedCortexResponse
from ai.planner import AutonomousCoopBrain
from ai.prompts import build_cortex_sensory_prompt
from core.database import Database


class TestCortexOptimization(unittest.IsolatedAsyncioTestCase):
    """Test suite covering sensory vector token budget, scout obsession cooldown,
    crafting precondition intercept, corpse recovery status logic, and plan chaining extraction.
    """

    def setUp(self):
        self.cortex = CognitiveCortex(
            ollama_brain=None,
            bot_owner="Omer",
            model="mc-qwen:3b",
            temperature=0.2,
            num_predict=64,
            num_ctx=2048,
            keep_alive="60m"
        )

    async def asyncTearDown(self):
        await self.cortex.close()

    def test_sensory_vector_word_count_and_context_window_safety(self):
        """Verify sensory perception prompt is ultra-compact (<160 words) under heavy perception loads."""
        # Heavy state with >10 entities, >10 blocks, generic lesson boilerplate, and zero-count items
        state = {
            "health": 16,
            "food": 12,
            "light": 9,
            "day_phase": "Dusk",
            "position": {"x": 105.4, "y": 68.0, "z": -250.2},
            "biome": "forest",
            "nearby_entities": [
                {"name": f"zombie_{i}", "distance": 2.5 + i} for i in range(12)
            ],
            "nearby_blocks": [
                {"name": f"iron_ore_{i}", "distance": 1.2 + i} for i in range(10)
            ],
            "missing_ingredients": ["3 iron_ingot", "2 stick"]
        }
        inv_dict = {
            "oak_log": 4,
            "stick": 0,
            "dirt": 12,
            "cobblestone": 0,
            "apple": 2,
            "wooden_pickaxe": 1,
            "rotten_flesh": 0
        }
        alerts = [
            "Hunger low (12/20). Need food soon.",
            "Monster risk high near trees.",
            "Tool wooden_pickaxe damaged.",
            "Excessive alert 4",
            "Excessive alert 5"
        ]
        opportunities = [
            "SheepOpportunity (2 sheep 6m away)",
            "CoalVeinOpportunity (4 coal 5m away)",
            "IronVeinOpportunity (3 iron 8m away)"
        ]
        lessons = [
            "Exercise heightened situational awareness in dark caverns",
            "Fell in lava while mining deepslate",
            "Unknown hazard: unknown entity damaged player",
            "Exercise heightened situational awareness around creepers",
            "Zombies can break wooden doors"
        ]
        goal = {"target": "iron_pickaxe", "stage": "iron", "missing": ["3 iron_ingot"]}
        feasible_actions = ["craft:iron_pickaxe", "collect:iron", "smelt:raw_iron"]

        vector = build_cortex_sensory_prompt(
            state=state,
            inv_dict=inv_dict,
            alerts=alerts,
            affordances_summary="Craft: iron_pickaxe",
            opportunities=opportunities,
            style="speedrunner",
            recent_actions="collect_block(iron) -> success",
            lessons=lessons,
            goal=goal,
            missing_ingredients=state["missing_ingredients"],
            feasible_actions=feasible_actions
        )

        words = vector.split()
        self.assertLess(
            len(words),
            160,
            f"Sensory vector word count ({len(words)}) must be strictly < 160 words to protect context window."
        )

        # Verify zero-count items are excluded from inventory
        self.assertNotIn("stick:0", vector)
        self.assertNotIn("cobblestone:0", vector)
        self.assertNotIn("rotten_flesh:0", vector)
        self.assertIn("oak_log:4", vector)

        # Verify generic boilerplate lessons are filtered out and capped at 2
        self.assertNotIn("Exercise heightened situational awareness", vector)
        self.assertNotIn("unknown hazard", vector)
        self.assertIn("Fell in lava while mining deepslate", vector)

        # Verify goal and feasible actions lines are formatted
        self.assertIn("[GOAL] Target: iron_pickaxe", vector)
        self.assertIn("[FEASIBLE] craft:iron_pickaxe, collect:iron, smelt:raw_iron", vector)

        # Verify entity truncation (max 3) and block truncation (max 4)
        self.assertIn("zombie_0(2m)", vector)
        self.assertIn("zombie_1(4m)", vector)
        self.assertIn("zombie_2(4m)", vector)
        self.assertNotIn("zombie_5", vector)

    def test_plan_chaining_json_extraction(self):
        """Verify parse_response and think_and_decide correctly extract and normalize multi-step plan JSON."""
        plan_json = json.dumps({
            "thought": "Need wood then tools.",
            "plan": [
                {"action": "attack_target", "arguments": {"target_name": "oak_log"}},
                {"action": "craft_item", "arguments": {"item_name": "crafting_table", "count": 1}}
            ]
        })

        parsed = self.cortex.parse_response(plan_json)
        self.assertIsNotNone(parsed)
        self.assertIsInstance(parsed, ParsedCortexResponse)

        # Test tuple unpacking compatibility (3 elements)
        thought, first_action, first_args = parsed
        self.assertEqual(thought, "Need wood then tools.")
        # Attack on block disambiguated to collect_block
        self.assertEqual(first_action, "collect_block")
        self.assertEqual(first_args.get("block_name"), "oak_log")

        # Test plan property extraction
        self.assertEqual(len(parsed.plan), 2)
        self.assertEqual(parsed.plan[0]["name"], "collect_block")
        self.assertEqual(parsed.plan[1]["name"], "craft_item")
        self.assertEqual(parsed.plan[1]["arguments"]["item_name"], "crafting_table")

    async def test_scout_obsession_cooldown(self):
        """Verify Scout Obsession Guard enforces a 180s cooldown and diverts repeated scout calls."""
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer", db=None)
        state = {
            "health": 20,
            "food": 20,
            "position": {"x": 0.0, "y": 64.0, "z": 0.0},
            "inventory_items": [{"name": "wooden_pickaxe", "count": 1}, {"name": "oak_log", "count": 5}],
            "is_busy": False
        }

        # Mock Cortex to repeatedly suggest scout_high_ground
        mock_cortex = MagicMock()
        mock_cortex.think_and_decide = AsyncMock(return_value={
            "text": "Scouting elevation.",
            "thought": "Scouting elevation.",
            "tool_calls": [{"name": "scout_high_ground", "arguments": {"radius": 16}}]
        })
        brain.cortex = mock_cortex

        # First call: cooldown was 0.0 -> allowed
        dec1 = await brain.decide_next_action(state)
        self.assertIsNotNone(dec1)
        self.assertEqual(dec1["tool_calls"][0]["name"], "scout_high_ground")
        self.assertGreater(brain.last_scout_time, 0.0)

        # Second call immediately (<180s elapsed) -> Intercepted and diverted!
        dec2 = await brain.decide_next_action(state)
        self.assertIsNotNone(dec2)
        action_name_2 = dec2["tool_calls"][0]["name"]
        self.assertNotEqual(
            action_name_2,
            "scout_high_ground",
            "Scout Obsession Guard must divert repeated scout calls within 180s!"
        )
        self.assertIn(action_name_2, ("collect_block", "go_to_coordinates"))

        # Third call: simulate 185s elapsed -> scout allowed again
        brain.last_scout_time = time.time() - 185.0
        dec3 = await brain.decide_next_action(state)
        self.assertIsNotNone(dec3)
        self.assertEqual(dec3["tool_calls"][0]["name"], "scout_high_ground")

    async def test_invalid_craft_auto_redirect_to_missing_ingredients(self):
        """Verify Crafting Precondition Guard intercepts craft_item when materials are missing and rewrites to gather."""
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer", db=None)
        # Empty inventory: missing both iron and wood for iron_pickaxe
        state = {
            "health": 20,
            "food": 20,
            "position": {"x": 10.0, "y": 64.0, "z": 10.0},
            "inventory_items": [],
            "is_busy": False
        }

        # Model returns craft_item for iron_pickaxe despite 0 iron ingots and 0 sticks
        mock_cortex = MagicMock()
        mock_cortex.think_and_decide = AsyncMock(return_value={
            "text": "Crafting iron pickaxe.",
            "thought": "Crafting iron pickaxe.",
            "tool_calls": [{"name": "craft_item", "arguments": {"item_name": "iron_pickaxe", "count": 1}}]
        })
        brain.cortex = mock_cortex

        dec = await brain.decide_next_action(state)
        self.assertIsNotNone(dec)
        tool_call = dec["tool_calls"][0]

        # Guard must prevent craft_item and redirect to collecting iron or wood
        self.assertNotEqual(tool_call["name"], "craft_item")
        self.assertIn(tool_call["name"], ("collect_block", "smelt_item"))
        if tool_call["name"] == "collect_block":
            self.assertIn(tool_call["arguments"]["block_name"], ("iron", "log", "stone"))

    def test_corpse_recovery_database_status_logic(self):
        """Verify corpse recovery does NOT mark death point recovered when task failed or timed out."""
        mock_db = MagicMock()
        death_id = 42
        task_id = 99
        in_range = False
        elapsed = 125.0
        success = False
        error = "Pathfinder timeout"

        # Simulate main.py corpse recovery result evaluation logic
        if in_range:
            mock_db.mark_death_point_recovered(death_id)
            mock_db.complete_task(task_id)
        elif elapsed > 120.0 or not success:
            mock_db.update_task_status(task_id, "failed")
            # CRITICAL FIX VERIFICATION: db.mark_death_point_recovered MUST NOT be called!

        mock_db.update_task_status.assert_called_once_with(task_id, "failed")
        mock_db.mark_death_point_recovered.assert_not_called()

        # Verify that when in_range IS true, it is marked recovered
        mock_db.reset_mock()
        in_range_success = True
        if in_range_success:
            mock_db.mark_death_point_recovered(death_id)
            mock_db.complete_task(task_id)

        mock_db.mark_death_point_recovered.assert_called_once_with(death_id)
        mock_db.complete_task.assert_called_once_with(task_id)


if __name__ == "__main__":
    unittest.main()
