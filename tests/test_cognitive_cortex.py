"""Unit tests for Cognitive Cortex and Cortex-First AutonomousCoopBrain."""
import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from ai.cortex import CognitiveCortex
from ai.planner import AutonomousCoopBrain
from ai.player_styles import PlayerStyle
from core.database import Database


class TestCognitiveCortex(unittest.IsolatedAsyncioTestCase):
    """Test suite covering CognitiveCortex sensory perception, Micro-CoT, and parser."""

    def setUp(self):
        self.cortex = CognitiveCortex(
            ollama_brain=None,
            bot_owner="Omer",
            model="qwen2.5:3b",
            temperature=0.35,
            num_predict=128,
            num_ctx=2048,
            keep_alive="60m"
        )

    async def asyncTearDown(self):
        await self.cortex.close()

    def test_sensory_vector_formatting_and_density(self):
        """Verify high-density sensory vector contains all perception sections with concise token footprint."""
        state = {
            "health": 18,
            "food": 14,
            "light": 11,
            "day_phase": "Dusk",
            "position": {"x": 14.2, "y": 64.0, "z": -32.8},
            "biome": "plains",
            "nearby_entities_summary": "2 sheep (8m away), 1 zombie (28m away)",
            "nearby_blocks_summary": "coal_ore (6m away), oak_log (4m away)"
        }
        inv_dict = {"log": 3, "stick": 2, "wooden_pickaxe": 1}
        alerts = [
            "Hunger low (14/20). Need food soon.",
            "Night is falling/present. Phantom/monster risk."
        ]
        affordances = "Craft: wooden_sword, crafting_table"
        opportunities = ["SheepOpportunity (2 sheep 8m away)"]
        recent_actions = "collect_block(oak_log) -> success"
        lessons = ["Fell in water while mining", "Creepers hiss before exploding"]

        vector = self.cortex.format_sensory_vector(
            state=state,
            inv_dict=inv_dict,
            alerts=alerts,
            affordances_summary=affordances,
            opportunities=opportunities,
            style="speedrunner",
            recent_actions=recent_actions,
            lessons=lessons
        )

        # Check required tags are present
        self.assertIn("[STATE]", vector)
        self.assertIn("HP:18/20", vector)
        self.assertIn("Food:14/20", vector)
        self.assertIn("Light:11 (Dusk)", vector)
        self.assertIn("Pos:(14,64,-33)", vector)
        self.assertIn("Biome:plains", vector)

        self.assertIn("[INV] log:3, stick:2, wooden_pickaxe:1", vector)
        self.assertIn("[AFFORD] Craft: wooden_sword, crafting_table", vector)
        self.assertIn("[PERCEPTION] Mobs: 2 sheep (8m away), 1 zombie (28m away) | Blocks: coal_ore (6m away), oak_log (4m away)", vector)
        self.assertIn("[ALERTS]", vector)
        self.assertIn("Hunger low (14/20)", vector)
        self.assertIn("[OPPORTUNITIES] SheepOpportunity (2 sheep 8m away)", vector)
        self.assertIn("[STYLE] speedrunner", vector)
        self.assertIn("[RECENT] collect_block(oak_log) -> success", vector)
        self.assertIn("[LESSONS]", vector)
        self.assertIn("Creepers hiss before exploding", vector)

        # Verify compact token footprint (approx < 160 words)
        words = vector.split()
        self.assertLess(len(words), 160, f"Sensory vector word count ({len(words)}) exceeds ultra-compact density target.")

    def test_response_parsing_valid_json(self):
        """Verify parser correctly extracts thought, action, and arguments from standard JSON."""
        raw_json = (
            '{"thought": "Dusk is near and hunger is 14. Securing wool for a bed is the highest survival priority.", '
            '"action": "attack_target", "arguments": {"target_name": "sheep"}}'
        )

        parsed = self.cortex.parse_response(raw_json)
        self.assertIsNotNone(parsed)
        thought, action, args = parsed

        self.assertIn("highest survival priority", thought)
        self.assertEqual(action, "attack_target")
        self.assertEqual(args.get("target_name"), "sheep")

    def test_response_parsing_micro_cot(self):
        """Verify parser extracts thought from <think> tags and tool calls from body or Markdown blocks."""
        micro_cot_text = (
            "<think>\n"
            "Starvation risk is critical (HP:10, Food:5). Sheep are 8m away. I should harvest meat now.\n"
            "</think>\n"
            "```json\n"
            '{"action": "attack_target", "arguments": {"target_name": "sheep"}}\n'
            "```"
        )

        parsed = self.cortex.parse_response(micro_cot_text)
        self.assertIsNotNone(parsed)
        thought, action, args = parsed

        self.assertIn("Starvation risk is critical", thought)
        self.assertEqual(action, "attack_target")
        self.assertEqual(args.get("target_name"), "sheep")

    def test_attack_on_block_disambiguation(self):
        """Verify parser automatically remaps attack_target on block keywords to collect_block."""
        # Test tree log
        log_json = '{"thought": "Punching wood log to craft tools.", "action": "attack_target", "arguments": {"target_name": "oak_log"}}'
        p1 = self.cortex.parse_response(log_json)
        self.assertIsNotNone(p1)
        _, action1, args1 = p1
        self.assertEqual(action1, "collect_block")
        self.assertEqual(args1["block_name"], "oak_log")

        # Test stone
        stone_json = '{"thought": "Mining stone block.", "action": "attack", "arguments": {"target_name": "stone"}}'
        p2 = self.cortex.parse_response(stone_json)
        self.assertIsNotNone(p2)
        _, action2, args2 = p2
        self.assertEqual(action2, "collect_block")
        self.assertEqual(args2["block_name"], "stone")

    async def test_latency_tracking(self):
        """Verify think_and_decide records positive execution latency in milliseconds."""
        mock_brain = MagicMock()

        async def mock_chat(*args, **kwargs):
            await asyncio.sleep(0.01)  # Simulate 10ms inference
            return {
                "text": '{"thought": "Need wood.", "action": "collect_block", "arguments": {"block_name": "log", "count": 3}}',
                "tool_calls": []
            }

        mock_brain.process_chat = mock_chat
        cortex = CognitiveCortex(ollama_brain=mock_brain)

        decision = await cortex.think_and_decide(
            state={"health": 20, "food": 20},
            inv_dict={},
            alerts=[],
            affordances_summary="",
            opportunities=[],
            style="speedrunner",
            recent_actions="",
            lessons=[]
        )

        self.assertIsNotNone(decision)
        self.assertIn("latency_ms", decision)
        self.assertGreater(decision["latency_ms"], 0.0)
        self.assertEqual(decision["thought"], "Need wood.")
        self.assertEqual(decision["tool_calls"][0]["name"], "collect_block")

    async def test_autonomous_trade_off_reasoning(self):
        """Verify sensory alerts and opportunities guide the autonomous Micro-CoT decision."""
        mock_brain = MagicMock()

        async def mock_chat(*args, **kwargs):
            sensory_msg = kwargs.get("message", "")
            # Ensure sensory vector was passed to the LLM
            if "STARVATION RISK" in sensory_msg and "SheepOpportunity" in sensory_msg:
                return {
                    "text": (
                        '{"thought": "Hunger is 4/20 and sheep are nearby. Gathering food takes priority over mining.", '
                        '"action": "attack_target", "arguments": {"target_name": "sheep"}}'
                    )
                }
            return {"text": '{"thought": "Mining", "action": "collect_block", "arguments": {"block_name": "stone"}}'}

        mock_brain.process_chat = mock_chat
        cortex = CognitiveCortex(ollama_brain=mock_brain)

        alerts = ["STARVATION RISK: Hunger critical (4/20)!"]
        opportunities = ["SheepOpportunity (2 sheep 8m away)"]

        decision = await cortex.think_and_decide(
            state={"health": 16, "food": 4},
            inv_dict={},
            alerts=alerts,
            affordances_summary="",
            opportunities=opportunities,
            style="speedrunner",
            recent_actions="",
            lessons=[]
        )

        self.assertIsNotNone(decision)
        self.assertIn("Gathering food takes priority", decision["thought"])
        self.assertEqual(decision["tool_calls"][0]["name"], "attack_target")
        self.assertEqual(decision["tool_calls"][0]["arguments"]["target_name"], "sheep")


class TestCortexPlannerIntegration(unittest.IsolatedAsyncioTestCase):
    """Test suite covering AutonomousCoopBrain integration with CognitiveCortex."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_cortex_planner.db")
        self.db = Database(self.db_path)

    def tearDown(self):
        if hasattr(self, "db") and self.db:
            self.db.close()
        self.temp_dir.cleanup()

    async def test_cortex_first_decision_dispatch(self):
        """Verify AutonomousCoopBrain queries Cortex first and returns its thought and action."""
        mock_brain = MagicMock()

        async def mock_chat(*args, **kwargs):
            return {
                "text": (
                    '{"thought": "Night is falling. Placing bed to skip monster spawns.", '
                    '"action": "sleep_in_bed", "arguments": {}}'
                )
            }

        mock_brain.process_chat = mock_chat
        planner = AutonomousCoopBrain(ollama_brain=mock_brain, bot_owner="Omer", db=self.db)

        state = {
            "health": 20,
            "food": 20,
            "is_day": False,
            "time_of_day": "dusk",
            "inventory_items": [{"name": "bed", "count": 1}],
            "inventory_summary": "bed x1",
            "nearby_hostiles": []
        }

        decision = await planner.decide_next_action(state)
        self.assertIsNotNone(decision)
        self.assertIn("Placing bed to skip monster spawns", decision.get("thought", ""))
        self.assertEqual(decision["tool_calls"][0]["name"], "sleep_in_bed")

    async def test_offline_cortex_fallback_behavior(self):
        """Verify AutonomousCoopBrain falls back cleanly to tech tree progression when Cortex is offline/fails."""
        mock_brain = MagicMock()
        # Mock returns empty tool calls and non-JSON text (simulating offline/parse failure)
        mock_brain.process_chat = AsyncMock(return_value={"text": "I don't know what to do", "tool_calls": []})

        planner = AutonomousCoopBrain(ollama_brain=mock_brain, bot_owner="Omer", db=self.db)

        state = {
            "health": 20,
            "food": 20,
            "is_day": True,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "nearby_hostiles": []
        }

        decision = await planner.decide_next_action(state)
        self.assertIsNotNone(decision)
        tool_calls = decision.get("tool_calls", [])
        self.assertGreater(len(tool_calls), 0)
        # Should fallback to progression milestone (collect_block log for wooden_pickaxe)
        self.assertEqual(tool_calls[0]["name"], "collect_block")
        self.assertEqual(tool_calls[0]["arguments"]["block_name"], "log")


if __name__ == "__main__":
    unittest.main()
