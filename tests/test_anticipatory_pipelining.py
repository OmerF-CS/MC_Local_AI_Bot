"""Unit tests for Phase 1: Dual-Thread Anticipatory Pipelining.

Validates StatePredictor heuristics, AnticipatoryPipeline speculative execution,
interrupt safety guards, and zero-latency decision retrieval (< 10ms).
"""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from ai.pipelining import StatePredictor, AnticipatoryPipeline, SMELT_OUTPUT_MAP
from ai.planner import AutonomousCoopBrain


class TestStatePredictor(unittest.TestCase):
    """Unit tests for speculative post-action state delta prediction."""

    def setUp(self):
        self.predictor = StatePredictor()
        self.base_state = {
            "health": 20.0,
            "food": 16,
            "position": {"x": 10.0, "y": 64.0, "z": 20.0},
            "inventory": {},
            "inventory_items": [],
            "nearby_hostiles": []
        }

    def test_collect_block_increment(self):
        """collect_block should increment target block count in inventory."""
        state = dict(self.base_state)
        state["inventory"] = {"oak_log": 2}

        predicted = self.predictor.predict_post_action_state(
            state,
            "collect_block",
            {"block_name": "oak_log", "count": 3}
        )
        self.assertEqual(predicted["inventory"].get("oak_log"), 5)
        self.assertIn("oak_log x5", predicted.get("inventory_summary", ""))

        # Test alternative argument key "target"
        predicted2 = self.predictor.predict_post_action_state(
            predicted,
            "collect_block",
            {"target": "cobblestone", "count": 4}
        )
        self.assertEqual(predicted2["inventory"].get("cobblestone"), 4)
        self.assertEqual(predicted2["inventory"].get("oak_log"), 5)

    def test_craft_item_deduction_and_increment(self):
        """craft_item should deduct recipe ingredients and increment crafted item."""
        state = dict(self.base_state)
        # Tech tree recipe for wooden_pickaxe: 3 planks, 2 sticks
        state["inventory"] = {
            "oak_planks": 5,
            "stick": 4
        }

        predicted = self.predictor.predict_post_action_state(
            state,
            "craft_item",
            {"item_name": "wooden_pickaxe", "count": 1}
        )

        inv = predicted["inventory"]
        self.assertEqual(inv.get("wooden_pickaxe"), 1)
        self.assertEqual(inv.get("oak_planks"), 2)  # 5 - 3 = 2
        self.assertEqual(inv.get("stick"), 2)       # 4 - 2 = 2

    def test_smelt_item_deduction_and_increment(self):
        """smelt_item should deduct raw ore & fuel, and increment smelted ingot."""
        state = dict(self.base_state)
        state["inventory"] = {
            "raw_iron": 6,
            "coal": 2
        }

        predicted = self.predictor.predict_post_action_state(
            state,
            "smelt_item",
            {"input_item": "raw_iron", "count": 4}
        )

        inv = predicted["inventory"]
        self.assertEqual(inv.get("iron_ingot"), 4)
        self.assertEqual(inv.get("raw_iron"), 2)  # 6 - 4 = 2
        self.assertEqual(inv.get("coal"), 1)      # 1 coal smelts up to 8 items, 2 - 1 = 1

    def test_go_to_coordinates_position_update(self):
        """go_to_coordinates should update bot position to target coordinates."""
        state = dict(self.base_state)
        predicted = self.predictor.predict_post_action_state(
            state,
            "go_to_coordinates",
            {"x": 125.5, "y": 72.0, "z": -340.2}
        )
        self.assertEqual(predicted["position"], {"x": 125.5, "y": 72.0, "z": -340.2})

    def test_eat_food_increment_and_cap(self):
        """eat_food should increment food level by 4, cap at 20, and deduct 1 food item."""
        # Case 1: food increment
        state1 = dict(self.base_state)
        state1["food"] = 12
        state1["inventory"] = {"bread": 3}

        pred1 = self.predictor.predict_post_action_state(state1, "eat_food", {})
        self.assertEqual(pred1["food"], 16)
        self.assertEqual(pred1["inventory"].get("bread"), 2)

        # Case 2: food cap at 20
        state2 = dict(self.base_state)
        state2["food"] = 18
        state2["inventory"] = {"cooked_beef": 2}

        pred2 = self.predictor.predict_post_action_state(state2, "eat_food", {})
        self.assertEqual(pred2["food"], 20)
        self.assertEqual(pred2["inventory"].get("cooked_beef"), 1)


class TestAnticipatoryPipeline(unittest.IsolatedAsyncioTestCase):
    """Unit tests for AnticipatoryPipeline background computation, interrupts, and latency."""

    def setUp(self):
        self.mock_planner = MagicMock()
        self.mock_planner.decide_next_action = AsyncMock()
        self.pipeline = AnticipatoryPipeline(self.mock_planner)
        self.base_state = {
            "health": 20.0,
            "food": 20,
            "position": {"x": 0.0, "y": 64.0, "z": 0.0},
            "inventory": {"raw_iron": 4, "coal": 1},
            "nearby_hostiles": []
        }

    async def test_smooth_precomputation_completion(self):
        """Pipeline should pre-compute next action in background during mock action execution."""
        speculative_decision = {
            "text": "Crafting iron pickaxe",
            "tool_calls": [{"name": "craft_item", "arguments": {"item_name": "iron_pickaxe"}}]
        }

        async def fake_decide(state, *args, **kwargs):
            await asyncio.sleep(0.01)  # Simulate small cognitive delay
            return speculative_decision

        self.mock_planner.decide_next_action.side_effect = fake_decide

        pre_state = dict(self.base_state)
        # Start pre-computation for smelting
        self.pipeline.start_precomputation(
            pre_state,
            "smelt_item",
            {"input_item": "raw_iron", "count": 3}
        )

        # Simulate execution duration of physical action in Mineflayer
        await asyncio.sleep(0.02)

        post_state = dict(self.base_state)
        post_state["inventory"] = {"iron_ingot": 3, "raw_iron": 1}
        exec_result = {"success": True, "action": "smelt_item"}

        decision = await self.pipeline.get_next_decision(post_state, pre_state, exec_result)

        self.assertEqual(decision, speculative_decision)
        # Planner was called with anticipated state (which had iron_ingot)
        called_state = self.mock_planner.decide_next_action.call_args[0][0]
        self.assertIn("iron_ingot", called_state.get("inventory", {}))

    def test_interrupt_discard_on_action_failed(self):
        """Pre-computed decision must be discarded if the running action fails."""
        exec_res_failure = {"success": False, "error": "No furnace found"}
        is_interrupted, reason = self.pipeline.should_discard_precomputation(
            self.base_state,
            self.base_state,
            exec_res_failure
        )
        self.assertTrue(is_interrupted)
        self.assertEqual(reason, "action_failed")

    def test_interrupt_discard_on_health_damage(self):
        """Pre-computed decision must be discarded if bot loses > 1.5 HP during action."""
        pre_state = dict(self.base_state)
        pre_state["health"] = 20.0

        # Health drop 2.0 HP (> 1.5)
        damaged_state = dict(self.base_state)
        damaged_state["health"] = 18.0
        exec_res = {"success": True}

        is_interrupted, reason = self.pipeline.should_discard_precomputation(
            damaged_state,
            pre_state,
            exec_res
        )
        self.assertTrue(is_interrupted)
        self.assertEqual(reason, "health_damage")

        # Health drop 1.0 HP (<= 1.5, minor, should NOT discard)
        minor_damage_state = dict(self.base_state)
        minor_damage_state["health"] = 19.0
        is_interrupted_minor, _ = self.pipeline.should_discard_precomputation(
            minor_damage_state,
            pre_state,
            exec_res
        )
        self.assertFalse(is_interrupted_minor)

    def test_interrupt_discard_on_hostile_threat(self):
        """Pre-computed decision must be discarded if hostile count increases or hostile is < 5m."""
        pre_state = dict(self.base_state)
        pre_state["nearby_hostiles"] = []

        # 1. Hostile count increased
        threat_state = dict(self.base_state)
        threat_state["nearby_hostiles"] = [{"name": "skeleton", "distance": 12.0}]
        exec_res = {"success": True}

        is_interrupted, reason = self.pipeline.should_discard_precomputation(
            threat_state,
            pre_state,
            exec_res
        )
        self.assertTrue(is_interrupted)
        self.assertEqual(reason, "hostile_threat")

        # 2. Hostile within 5m
        pre_state_with_hostile = dict(self.base_state)
        pre_state_with_hostile["nearby_hostiles"] = [{"name": "zombie", "distance": 8.0}]

        close_hostile_state = dict(self.base_state)
        close_hostile_state["nearby_hostiles"] = [{"name": "zombie", "distance": 3.2}]

        is_interrupted2, reason2 = self.pipeline.should_discard_precomputation(
            close_hostile_state,
            pre_state_with_hostile,
            exec_res
        )
        self.assertTrue(is_interrupted2)
        self.assertEqual(reason2, "hostile_threat")

    async def test_get_next_decision_recalculates_on_interrupt(self):
        """When interrupted, pipeline should discard pre-computation and calculate fresh decision."""
        fresh_decision = {"text": "Retreating!", "tool_calls": [{"name": "retreat"}]}
        self.mock_planner.decide_next_action.return_value = fresh_decision

        pre_state = dict(self.base_state)
        self.pipeline.start_precomputation(pre_state, "mine_block", {"block_name": "stone"})

        damaged_state = dict(self.base_state)
        damaged_state["health"] = 15.0  # Big damage
        exec_res = {"success": True}

        decision = await self.pipeline.get_next_decision(damaged_state, pre_state, exec_res)
        self.assertEqual(decision, fresh_decision)
        # Planner called again with the actual damaged_state
        self.mock_planner.decide_next_action.assert_called_with(damaged_state)

    async def test_zero_latency_decision_dispatch(self):
        """Pre-computed decision retrieval must complete in < 10ms once pre-computation finishes."""
        target_decision = {
            "text": "Crafting furnace",
            "tool_calls": [{"name": "craft_item", "arguments": {"item_name": "furnace"}}]
        }
        self.mock_planner.decide_next_action.return_value = target_decision

        pre_state = dict(self.base_state)
        self.pipeline.start_precomputation(pre_state, "collect_block", {"block_name": "cobblestone"})

        # Wait tiny moment so background task finishes
        await asyncio.sleep(0.01)

        t0 = time.perf_counter()
        decision = await self.pipeline.get_next_decision(
            self.base_state,
            pre_state,
            {"success": True}
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(decision, target_decision)
        self.assertLess(latency_ms, 10.0, f"Expected < 10ms dispatch latency, got {latency_ms:.2f}ms")


class TestPlannerStatePredictorIntegration(unittest.TestCase):
    """Verify AutonomousCoopBrain integration with StatePredictor."""

    def test_planner_has_state_predictor(self):
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer", db=None)
        self.assertIsNotNone(brain.state_predictor)
        self.assertIsInstance(brain.state_predictor, StatePredictor)

        state = {"inventory": {"oak_log": 1}}
        predicted = brain.predict_post_action_state(state, "collect_block", {"block_name": "oak_log", "count": 2})
        self.assertEqual(predicted["inventory"].get("oak_log"), 3)


if __name__ == "__main__":
    unittest.main()
