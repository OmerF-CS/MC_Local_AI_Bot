"""Unit and Behavioral Tests for Phase F1: Yaşam Temelleri (Survival Basics).

Validates:
- F1-1: Eating when hunger < 14 and inventory has food; prioritized when HP < 8.
        If no food, logs warning and issues food gathering goal via tool call (no silent pass).
- F1-2: Low HP (< 8) management: safe retreat, HP tracking over time, and 60s stagnancy strategy switch.
- F1-5: LLM timeout tracking, >30% timeout rate alert, and run_meta.json metrics.
- F1-6: Single-line fallback rule logging on 0 tool calls, and category diversification
        after 3 consecutive identical fallbacks (e.g. exploration or waiting).
"""

import unittest
import asyncio
import time
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

from ai.planner import AutonomousCoopBrain
from ai.ollama_client import OllamaBrain
from utils.run_context import write_run_metadata, get_run_directory, reset_current_run_id, set_current_run_id


class TestF1SurvivalBasics(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_brain = MagicMock()
        self.mock_brain.process_chat = AsyncMock(return_value={"text": "OK", "tool_calls": []})
        self.mock_brain.llm_timeouts = 0
        self.mock_brain.llm_calls_count = 0
        self.mock_brain.llm_tool_call_count = 0
        self.mock_brain.fallback_count = 0

        self.planner = AutonomousCoopBrain(self.mock_brain, bot_owner="Player1")

    # ------------------------------------------------------------------
    # F1-1: Eating & Hunger Management
    # ------------------------------------------------------------------
    async def test_low_hp_prioritizes_eat_action_when_food_available(self):
        """F1-1: When HP < 8 and food in inventory, eat action is prioritized."""
        state = {
            "health": 6.0,  # HP < 8
            "food": 16.0,
            "inventory_items": [{"name": "bread", "count": 2}],
            "inventory_summary": "bread x2",
            "nearby_hostiles": []
        }

        decision = await self.planner.decide_next_action(state)
        self.assertIsNotNone(decision)
        tool_calls = decision.get("tool_calls", [])
        self.assertTrue(len(tool_calls) > 0, "Expected a tool call for eating")
        self.assertEqual(tool_calls[0].get("name"), "eat_food")

    async def test_low_hp_without_food_issues_gathering_goal_not_silent(self):
        """F1-1: When HP < 8 and NO food in inventory, log and issue food gathering tool call."""
        state = {
            "health": 7.0,  # HP < 8
            "food": 12.0,
            "inventory_items": [{"name": "dirt", "count": 10}],
            "inventory_summary": "dirt x10",
            "nearby_hostiles": []
        }

        with self.assertLogs("AutonomousCoopBrain", level="WARNING") as log:
            decision = await self.planner.decide_next_action(state)
            self.assertIsNotNone(decision)
            tool_calls = decision.get("tool_calls", [])
            self.assertTrue(len(tool_calls) > 0, "Must NOT pass silently; expected food gathering tool call")
            cmd = tool_calls[0].get("name")
            self.assertIn(cmd, ["hunt_food", "farm_crops"], "Expected hunt_food or farm_crops")
            self.assertTrue(any("Critical HP" in msg and "NO food" in msg for msg in log.output))

    async def test_hunger_under_14_with_food_eats(self):
        """F1-1: When food < 14 and food in inventory, eat action is issued."""
        state = {
            "health": 18.0,
            "food": 12.0,  # food < 14
            "inventory_items": [{"name": "cooked_beef", "count": 4}],
            "inventory_summary": "cooked_beef x4",
            "nearby_hostiles": []
        }

        decision = await self.planner.decide_next_action(state)
        self.assertIsNotNone(decision)
        tool_calls = decision.get("tool_calls", [])
        self.assertTrue(len(tool_calls) > 0)
        self.assertEqual(tool_calls[0].get("name"), "eat_food")

    async def test_hunger_under_14_without_food_gathers_food(self):
        """F1-1: When food < 14 and NO food in inventory, issues gathering goal."""
        state = {
            "health": 18.0,
            "food": 10.0,  # food < 14
            "inventory_items": [{"name": "cobblestone", "count": 20}],
            "inventory_summary": "cobblestone x20",
            "nearby_hostiles": []
        }

        with self.assertLogs("AutonomousCoopBrain", level="WARNING") as log:
            decision = await self.planner.decide_next_action(state)
            self.assertIsNotNone(decision)
            tool_calls = decision.get("tool_calls", [])
            self.assertTrue(len(tool_calls) > 0)
            self.assertIn(tool_calls[0].get("name"), ["hunt_food", "farm_crops"])
            self.assertTrue(any("NO food in inventory" in msg for msg in log.output))

    # ------------------------------------------------------------------
    # F1-2: Low HP Management & 60s Stagnancy Strategy Switch
    # ------------------------------------------------------------------
    async def test_low_hp_with_hostiles_withdraws_to_shelter(self):
        """F1-2: When HP < 8 with nearby hostiles and not sheltered, withdraws to shelter."""
        state = {
            "health": 5.0,
            "food": 20.0,
            "inventory_items": [{"name": "bread", "count": 1}],
            "inventory_summary": "bread x1",
            "nearby_hostiles": ["zombie (4m away)"],
            "is_sheltered": False
        }

        decision = await self.planner.decide_next_action(state)
        self.assertIsNotNone(decision)
        tool_calls = decision.get("tool_calls", [])
        self.assertEqual(tool_calls[0].get("name"), "build_shelter")

    async def test_low_hp_60s_stagnancy_switches_strategy(self):
        """F1-2: When HP < 8 does not increase within 60s, planner switches strategy and logs result."""
        state = {
            "health": 6.0,
            "food": 20.0,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "nearby_hostiles": [],
            "is_sheltered": True
        }

        # Initial call sets the low HP monitor
        await self.planner.decide_next_action(state)
        self.assertIsNotNone(self.planner._low_hp_monitor)

        # Simulate 61 seconds passing without HP increasing
        self.planner._low_hp_monitor["start_time"] = time.time() - 65.0

        with self.assertLogs("AutonomousCoopBrain", level="WARNING") as log_warn:
            decision = await self.planner.decide_next_action(state)
            self.assertIsNotNone(decision)
            # Confirms 60s warning logged
            self.assertTrue(any("HP did not increase within 60s" in msg for msg in log_warn.output))
            # Confirms strategy switched (relocate or gather_food)
            tool_calls = decision.get("tool_calls", [])
            self.assertTrue(len(tool_calls) > 0)

    # ------------------------------------------------------------------
    # F1-6: Unanswered Tool Calls, Fallback Logging & Category Shift
    # ------------------------------------------------------------------
    async def test_fallback_rule_single_line_logging(self):
        """F1-6: When LLM returns 0 tool calls, fallback rule is logged in a single line."""
        state = {
            "health": 20.0,
            "food": 20.0,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "nearby_hostiles": [],
            "dimension": "overworld",
            "is_day": True
        }
        self.mock_brain.process_chat = AsyncMock(return_value={"text": "Thinking...", "tool_calls": []})

        with self.assertLogs("AutonomousCoopBrain", level="INFO") as log_info:
            decision = await self.planner.decide_next_action(state)
            self.assertIsNotNone(decision)
            self.assertTrue(any("ℹ️ [Fallback Rule] Triggered rule" in msg for msg in log_info.output))

    async def test_consecutive_same_fallback_shifts_category_after_3_repeats(self):
        """F1-6: If same fallback is chosen 3 consecutive times, planner shifts category."""
        state = {
            "health": 20.0,
            "food": 20.0,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "nearby_hostiles": [],
            "dimension": "overworld",
            "is_day": True,
            "position": {"x": 100, "y": 64, "z": 200}
        }
        self.mock_brain.process_chat = AsyncMock(return_value={"text": "", "tool_calls": []})

        # Call 1 & 2: Normal fallback
        d1 = await self.planner.decide_next_action(state)
        d2 = await self.planner.decide_next_action(state)
        self.assertEqual(self.planner._consecutive_same_fallback_count, 2)

        # Call 3: Reaches 3 repeats -> must shift category to exploration (go_to_coordinates) or waiting
        d3 = await self.planner.decide_next_action(state)
        tool_3 = d3["tool_calls"][0]["name"]
        self.assertIn(tool_3, ["go_to_coordinates", "say_chat"], "Expected shifted category action")
        self.assertEqual(self.planner._consecutive_same_fallback_count, 0, "Streak must be reset upon category shift")

    # ------------------------------------------------------------------
    # F1-5: LLM Timeout Measurement & Run Metadata
    # ------------------------------------------------------------------
    async def test_ollama_timeout_rate_warning_above_30_percent(self):
        """F1-5: OllamaClient warns if timeout rate exceeds 30%."""
        brain = OllamaBrain(base_url="http://localhost:11434", model="test-model")

        class TimeoutContextManager:
            async def __aenter__(self):
                raise asyncio.TimeoutError()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=TimeoutContextManager())
        brain.ensure_session = AsyncMock(return_value=mock_session)

        with self.assertLogs("OllamaClient", level="WARNING") as log_warn:
            for _ in range(4):
                await brain.process_chat(sender="System", message="Hello", state={})

            self.assertEqual(brain.llm_timeouts, 4)
            self.assertEqual(brain.llm_calls_count, 4)
            self.assertTrue(any("timeout rate is 100.0% (> 30% threshold)" in msg for msg in log_warn.output))

    def test_run_metadata_persists_f1_metrics(self):
        """F1-5: run_meta.json contains llm_timeouts, fallback_count, llm_tool_call_count."""
        reset_current_run_id()
        run_id = set_current_run_id("test_f1_meta_verify")
        meta_file = write_run_metadata(run_id, {
            "llm_timeouts": 2,
            "fallback_count": 5,
            "llm_tool_call_count": 14,
            "llm_timeout_rate": 0.125
        })

        self.assertTrue(os.path.isfile(meta_file))
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("llm_timeouts"), 2)
        self.assertEqual(data.get("fallback_count"), 5)
        self.assertEqual(data.get("llm_tool_call_count"), 14)
        self.assertEqual(data.get("llm_timeout_rate"), 0.125)

    # ------------------------------------------------------------------
    # F1-R7: Hunger Root & Food Strategy Rotation
    # ------------------------------------------------------------------
    async def test_f1_r7_stagnant_hp_food_strategy_rotation(self):
        """F1-R7: Consecutive stagnant HP cycles rotate through hunt -> farm -> fish -> explore without repeating."""
        state = {
            "health": 6.0,
            "food": 10.0,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "nearby_hostiles": [],
            "is_sheltered": True
        }

        # Initialize monitor
        await self.planner.decide_next_action(state)

        # 4 consecutive stagnant cycles
        actions_received = []
        for i in range(4):
            self.planner._low_hp_monitor["start_time"] = time.time() - 65.0
            dec = await self.planner.decide_next_action(state)
            self.assertIsNotNone(dec)
            tc = dec.get("tool_calls", [])
            self.assertTrue(len(tc) > 0)
            actions_received.append(tc[0].get("name"))

        # Verify progression without immediate repeat: hunt -> farm -> fish -> go_to_coordinates
        self.assertEqual(actions_received[0], "hunt_food", "Step 1 must be hunt_food")
        self.assertEqual(actions_received[1], "farm_crops", "Step 2 must rotate to farm_crops")
        self.assertEqual(actions_received[2], "catch_fish", "Step 3 must rotate to catch_fish")
        self.assertEqual(actions_received[3], "go_to_coordinates", "Step 4 must rotate to go_to_coordinates (relocation)")

    # ------------------------------------------------------------------
    # F1-R8: Ollama Preload & Chat Options Uniformity
    # ------------------------------------------------------------------
    def test_f1_r8_ollama_options_consistency(self):
        """F1-R8: OLLAMA_MODEL_OPTIONS guarantees identical num_ctx, num_gpu, num_thread between preload and chat."""
        from ai.ollama_client import OLLAMA_MODEL_OPTIONS
        self.assertEqual(OLLAMA_MODEL_OPTIONS.get("num_ctx"), 8192)
        self.assertEqual(OLLAMA_MODEL_OPTIONS.get("num_gpu"), 999)
        self.assertEqual(OLLAMA_MODEL_OPTIONS.get("num_thread"), 8)
        self.assertIn("temperature", OLLAMA_MODEL_OPTIONS)

    # ------------------------------------------------------------------
    # F1-R11: Planner Failure Reason Mapping & Repetition Category Shift
    # ------------------------------------------------------------------
    async def test_f1_r11_farm_crops_no_crop_found_written_to_history_and_triggers_shift(self):
        """F1-R11: farm_crops -> no_crop_found is written to failure history and shifts category on 3 repeats."""
        state = {
            "health": 20.0,
            "food": 20.0,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "nearby_hostiles": [],
            "position": {"x": 100, "y": 64, "z": 200}
        }
        self.mock_brain.process_chat = AsyncMock(return_value={"text": "OK", "tool_calls": []})

        # 1st failure: farm_crops with no_crop_found
        shift1 = self.planner.record_action_failure("farm_crops", "no_crop_found", target="all")
        self.assertIsNone(shift1, "1st repeat should not trigger category shift")
        self.assertEqual(len(self.planner.action_failure_history), 1)
        self.assertEqual(self.planner.action_failure_history[0]["action"], "farm_crops")
        self.assertEqual(self.planner.action_failure_history[0]["reason"], "no_crop_found")
        self.assertEqual(self.planner.action_failure_history[0]["target"], "all")
        self.assertEqual(self.planner._consecutive_same_fallback_count, 1)

        # 2nd failure with same reason and target
        shift2 = self.planner.record_action_failure("farm_crops", "no_crop_found", target="all")
        self.assertIsNone(shift2, "2nd repeat should not trigger category shift")
        self.assertEqual(len(self.planner.action_failure_history), 2)
        self.assertEqual(self.planner._consecutive_same_fallback_count, 2)

        # 3rd failure with same reason and target -> triggers category shift!
        shift3 = self.planner.record_action_failure("farm_crops", "no_crop_found", target="all")
        self.assertIsNotNone(shift3, "3rd repeat must trigger category shift")
        self.assertIn(shift3["name"], ["go_to_coordinates", "say_chat"])
        self.assertEqual(self.planner._consecutive_same_fallback_count, 3)

        # decide_next_action consumes pending category shift and resets counter
        decision = await self.planner.decide_next_action(state)
        self.assertIsNotNone(decision)
        self.assertTrue(len(decision["tool_calls"]) > 0)
        tool_name = decision["tool_calls"][0]["name"]
        self.assertIn(tool_name, ["go_to_coordinates", "say_chat"], "Decision must be shifted category action")
        self.assertEqual(self.planner._consecutive_same_fallback_count, 0, "Counter must reset upon category shift")

    async def test_f1_r11_go_to_coordinates_did_not_reach_destination_triggers_shift(self):
        """F1-R11: go_to_coordinates -> did_not_reach_destination normalizes reason and triggers category shift."""
        state = {
            "health": 20.0,
            "food": 20.0,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "nearby_hostiles": [],
            "position": {"x": 10, "y": 64, "z": 20}
        }
        self.mock_brain.process_chat = AsyncMock(return_value={"text": "OK", "tool_calls": []})
        target_coords = {"x": 150, "y": 64, "z": 250}
        raw_error = "did_not_reach_destination (dist=16.8m > range=3m)"

        # Repeat 1 & 2
        self.planner.record_action_failure("go_to_coordinates", raw_error, target=target_coords)
        self.assertEqual(self.planner.action_failure_history[-1]["reason"], "did_not_reach_destination")
        self.assertEqual(self.planner._consecutive_same_fallback_count, 1)

        self.planner.record_action_failure("go_to_coordinates", raw_error, target=target_coords)
        self.assertEqual(self.planner._consecutive_same_fallback_count, 2)

        # Repeat 3
        shift = self.planner.record_action_failure("go_to_coordinates", raw_error, target=target_coords)
        self.assertIsNotNone(shift)
        self.assertEqual(self.planner._consecutive_same_fallback_count, 3)

        decision = await self.planner.decide_next_action(state)
        self.assertIn(decision["tool_calls"][0]["name"], ["go_to_coordinates", "say_chat"])
        self.assertEqual(self.planner._consecutive_same_fallback_count, 0)

    async def test_f1_r11_go_to_coordinates_position_unknown_triggers_shift(self):
        """F1-R11: go_to_coordinates -> position_unknown records failure and shifts category after 3 repeats."""
        state = {
            "health": 20.0,
            "food": 20.0,
            "inventory_items": [],
            "inventory_summary": "Empty",
            "nearby_hostiles": [],
            "position": {"x": 0, "y": 64, "z": 0}
        }
        self.mock_brain.process_chat = AsyncMock(return_value={"text": "OK", "tool_calls": []})
        target_coords = (80, 64, 120)

        # Repeat 1, 2, 3
        self.planner.record_action_failure("go_to_coordinates", "position_unknown", target=target_coords)
        self.assertEqual(self.planner.action_failure_history[-1]["reason"], "position_unknown")
        self.assertEqual(self.planner._consecutive_same_fallback_count, 1)

        self.planner.record_action_failure("go_to_coordinates", "position_unknown", target=target_coords)
        self.assertEqual(self.planner._consecutive_same_fallback_count, 2)

        shift = self.planner.record_action_failure("go_to_coordinates", "position_unknown", target=target_coords)
        self.assertIsNotNone(shift)

        decision = await self.planner.decide_next_action(state)
        self.assertIn(decision["tool_calls"][0]["name"], ["go_to_coordinates", "say_chat"])
        self.assertEqual(self.planner._consecutive_same_fallback_count, 0)

    def test_f1_r11_different_target_or_reason_resets_streak(self):
        """F1-R11: Changing target or failure reason resets streak to 1 without triggering category shift."""
        # 2 failures on target A
        self.planner.record_action_failure("go_to_coordinates", "did_not_reach_destination", target={"x": 10, "y": 64, "z": 10})
        self.assertEqual(self.planner._consecutive_same_fallback_count, 1)
        self.planner.record_action_failure("go_to_coordinates", "did_not_reach_destination", target={"x": 10, "y": 64, "z": 10})
        self.assertEqual(self.planner._consecutive_same_fallback_count, 2)

        # 3rd failure has different target B -> streak resets to 1
        shift_diff_target = self.planner.record_action_failure("go_to_coordinates", "did_not_reach_destination", target={"x": 90, "y": 64, "z": 90})
        self.assertIsNone(shift_diff_target, "Streak must reset to 1 when target changes")
        self.assertEqual(self.planner._consecutive_same_fallback_count, 1)

        # 4th failure has different reason -> streak resets to 1
        shift_diff_reason = self.planner.record_action_failure("go_to_coordinates", "position_unknown", target={"x": 90, "y": 64, "z": 90})
        self.assertIsNone(shift_diff_reason, "Streak must reset to 1 when reason changes")
        self.assertEqual(self.planner._consecutive_same_fallback_count, 1)

    def test_f1_r11_action_success_resets_failure_tracking(self):
        """F1-R11: Successful action execution resets consecutive failure counter."""
        self.planner.record_action_failure("farm_crops", "no_crop_found", target="wheat")
        self.planner.record_action_failure("farm_crops", "no_crop_found", target="wheat")
        self.assertEqual(self.planner.consecutive_failure_repeats, 2)

        self.planner.record_action_success("farm_crops")
        self.assertEqual(self.planner.consecutive_failure_repeats, 0)
        self.assertIsNone(self.planner._last_action_failure_key)


if __name__ == "__main__":
    unittest.main()

