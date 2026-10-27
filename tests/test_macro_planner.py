"""Unit tests for DAG-Based Macro-Plan Chaining Engine (ai/macro_planner.py).

Verifies:
1. PlanStep satisfaction logic and alias resolution.
2. MacroPlan step advancement, lifecycle, and completion states.
3. MacroPlanner DAG decomposition for stone_pickaxe, furnace, iron_pickaxe, shield.
4. AutonomousCoopBrain macro plan execution and local step dispatching.
5. Interrupt guards: damage drop, nearby hostile mobs, high urgency scenarios.
"""
import unittest
from unittest.mock import AsyncMock, MagicMock

from ai.macro_planner import MacroPlanner, MacroPlan, PlanStep
from ai.planner import AutonomousCoopBrain
from ai.scenario_engine import ScenarioType, ScenarioFrame


class TestMacroPlanner(unittest.IsolatedAsyncioTestCase):
    """Test suite covering deterministic DAG macro-planning and planner execution."""

    def setUp(self):
        self.planner = MacroPlanner()

    def test_plan_step_is_satisfied(self):
        """Verifies PlanStep satisfaction with exact matches and Minecraft aliases."""
        step_none = PlanStep(action="collect_block", arguments={}, description="No item")
        self.assertFalse(step_none.is_satisfied({"log": 5}))

        step_exact = PlanStep(
            action="craft_item",
            arguments={"item_name": "furnace"},
            description="Craft furnace",
            verification_item="furnace",
            verification_count=1
        )
        self.assertFalse(step_exact.is_satisfied({}))
        self.assertTrue(step_exact.is_satisfied({"furnace": 1}))
        self.assertTrue(step_exact.is_satisfied({"furnace": 2}))

        # Fuzzy log matching
        step_log = PlanStep(
            action="collect_block",
            arguments={"block_name": "log"},
            description="Gather logs",
            verification_item="log",
            verification_count=3
        )
        self.assertFalse(step_log.is_satisfied({"dirt": 10}))
        self.assertTrue(step_log.is_satisfied({"oak_log": 3}))
        self.assertTrue(step_log.is_satisfied({"birch_log": 2, "spruce_log": 1}))

        # Fuzzy planks matching
        step_planks = PlanStep(
            action="craft_item",
            arguments={"item_name": "planks"},
            description="Craft planks",
            verification_item="planks",
            verification_count=4
        )
        self.assertTrue(step_planks.is_satisfied({"oak_planks": 4}))
        self.assertFalse(step_planks.is_satisfied({"oak_planks": 3}))

        # Fuzzy stone/cobblestone matching
        step_cobble = PlanStep(
            action="collect_block",
            arguments={"block_name": "stone"},
            description="Mine stone",
            verification_item="cobblestone",
            verification_count=3
        )
        self.assertTrue(step_cobble.is_satisfied({"cobbled_deepslate": 3}))
        self.assertTrue(step_cobble.is_satisfied({"cobblestone": 3}))

    def test_macro_plan_step_advancement_and_completion(self):
        """Verifies MacroPlan pointer advancement and completed status transition."""
        step1 = PlanStep("collect_block", {"block_name": "log", "count": 3}, "Gather logs", "log", 3)
        step2 = PlanStep("craft_item", {"item_name": "planks", "count": 4}, "Craft planks", "planks", 4)
        plan = MacroPlan(target_item="wooden_pickaxe", steps=[step1, step2])

        self.assertEqual(plan.get_current_step(), step1)
        self.assertFalse(plan.is_completed())

        next_step = plan.advance_step()
        self.assertEqual(next_step, step2)
        self.assertEqual(plan.get_current_step(), step2)
        self.assertFalse(plan.is_completed())

        final_step = plan.advance_step()
        self.assertIsNone(final_step)
        self.assertTrue(plan.is_completed())
        self.assertEqual(plan.status, "completed")

    def test_dag_expansion_wooden_and_stone_pickaxe(self):
        """Verifies DAG step synthesis for wooden and stone pickaxe from scratch."""
        # Wooden pickaxe from empty inventory
        wood_plan = self.planner.build_macro_plan("wooden_pickaxe", {})
        self.assertFalse(wood_plan.is_completed())
        actions = [s.action for s in wood_plan.steps]
        self.assertIn("collect_block", actions)
        self.assertIn("craft_item", actions)
        self.assertEqual(wood_plan.steps[-1].arguments["item_name"], "wooden_pickaxe")

        # Stone pickaxe from empty inventory requires wooden pickaxe first
        stone_plan = self.planner.build_macro_plan("stone_pickaxe", {})
        self.assertFalse(stone_plan.is_completed())
        item_crafts = [s.arguments.get("item_name") for s in stone_plan.steps if s.action == "craft_item"]
        self.assertIn("wooden_pickaxe", item_crafts)
        self.assertIn("stone_pickaxe", item_crafts)
        # wooden_pickaxe must precede stone_pickaxe
        self.assertLess(item_crafts.index("wooden_pickaxe"), item_crafts.index("stone_pickaxe"))

        # When bot already has wooden pickaxe and cobblestone:
        ready_stone_plan = self.planner.build_macro_plan("stone_pickaxe", {
            "wooden_pickaxe": 1,
            "cobblestone": 3,
            "crafting_table": 1,
            "stick": 2
        })
        self.assertEqual(len(ready_stone_plan.steps), 1)
        self.assertEqual(ready_stone_plan.steps[0].arguments["item_name"], "stone_pickaxe")

    def test_dag_expansion_furnace(self):
        """Verifies DAG step synthesis for furnace."""
        # Empty inventory needs wooden pickaxe to mine 8 stone
        plan = self.planner.build_macro_plan("furnace", {})
        self.assertFalse(plan.is_completed())
        mine_steps = [s for s in plan.steps if s.action == "collect_block"]
        self.assertTrue(any(s.arguments.get("block_name") in ("stone", "cobblestone") for s in mine_steps))
        self.assertEqual(plan.steps[-1].arguments["item_name"], "furnace")

        # When bot already has 8 cobblestone and crafting table
        fast_furnace = self.planner.build_macro_plan("furnace", {
            "cobblestone": 8,
            "crafting_table": 1
        })
        self.assertEqual(len(fast_furnace.steps), 1)
        self.assertEqual(fast_furnace.steps[0].arguments["item_name"], "furnace")

    def test_dag_expansion_iron_pickaxe_and_shield(self):
        """Verifies multi-step smelting chain for iron_pickaxe and shield."""
        # Iron pickaxe from scratch requires stone pickaxe, furnace, iron mining and smelting
        iron_pick_plan = self.planner.build_macro_plan("iron_pickaxe", {})
        self.assertFalse(iron_pick_plan.is_completed())
        actions = [s.action for s in iron_pick_plan.steps]
        self.assertIn("smelt_item", actions)
        self.assertEqual(iron_pick_plan.steps[-1].arguments["item_name"], "iron_pickaxe")

        # Shield requires 6 planks and 1 iron ingot
        shield_plan = self.planner.build_macro_plan("shield", {
            "iron_ingot": 1,
            "oak_planks": 6,
            "crafting_table": 1
        })
        self.assertEqual(len(shield_plan.steps), 1)
        self.assertEqual(shield_plan.steps[0].arguments["item_name"], "shield")

    async def test_brain_macro_plan_execution_and_auto_advance(self):
        """Verifies AutonomousCoopBrain executes macro steps locally and advances when satisfied."""
        brain = AutonomousCoopBrain(ollama_brain=None)
        mock_cortex = MagicMock()
        mock_cortex.think_and_decide = AsyncMock(return_value=None)
        brain.cortex = mock_cortex

        # Start macro plan for stone_pickaxe with wooden pickaxe on hand but cobblestone missing
        inv_dict = {"wooden_pickaxe": 1, "crafting_table": 1, "stick": 4}
        state = {
            "position": {"x": 10, "y": 64, "z": 20},
            "is_day": True,
            "health": 20,
            "food": 20,
            "nearby_hostiles": [],
            "inventory_items": [
                {"name": "wooden_pickaxe", "count": 1},
                {"name": "crafting_table", "count": 1},
                {"name": "stick", "count": 4}
            ]
        }

        brain.start_macro_plan("stone_pickaxe", inv_dict, state)
        self.assertIsNotNone(brain.active_macro_plan)
        self.assertEqual(brain.active_macro_plan.target_item, "stone_pickaxe")

        # Step 1: Should dispatch collect_block(cobblestone)
        decision1 = await brain.decide_next_action(state)
        self.assertIsNotNone(decision1)
        tool1 = decision1["tool_calls"][0]
        self.assertEqual(tool1["name"], "collect_block")

        # Now simulate cobblestone collected into inventory -> should auto-advance to craft stone_pickaxe
        state["inventory_items"].append({"name": "cobblestone", "count": 3})
        decision2 = await brain.decide_next_action(state)
        self.assertIsNotNone(decision2)
        tool2 = decision2["tool_calls"][0]
        self.assertEqual(tool2["name"], "craft_item")
        self.assertEqual(tool2["arguments"]["item_name"], "stone_pickaxe")

        # Now simulate stone_pickaxe crafted -> macro plan completes
        state["inventory_items"].append({"name": "stone_pickaxe", "count": 1})
        await brain.decide_next_action(state)
        self.assertIsNone(brain.active_macro_plan)

    async def test_brain_macro_plan_aborts_on_damage(self):
        """Verifies that sudden health drop (> 1.5 HP) immediately aborts the active macro plan."""
        brain = AutonomousCoopBrain(ollama_brain=None)
        brain.cortex = MagicMock()
        brain.cortex.think_and_decide = AsyncMock(return_value={"thought": "evading", "tool_calls": []})

        state = {
            "position": {"x": 0, "y": 64, "z": 0},
            "is_day": True,
            "health": 20,
            "food": 20,
            "nearby_hostiles": [],
            "inventory_items": []
        }
        brain.start_macro_plan("wooden_pickaxe", {}, state)
        self.assertIsNotNone(brain.active_macro_plan)

        # Baseline step executed at full HP
        await brain.decide_next_action(state)
        self.assertIsNotNone(brain.active_macro_plan)

        # Bot takes 3 damage (20 -> 17)
        damaged_state = dict(state)
        damaged_state["health"] = 17
        await brain.decide_next_action(damaged_state)

        # Plan must be aborted to yield to survival reflexes
        self.assertIsNone(brain.active_macro_plan)

    async def test_brain_macro_plan_aborts_on_nearby_hostile_mob(self):
        """Verifies that a hostile mob within 6m immediately aborts the active macro plan."""
        brain = AutonomousCoopBrain(ollama_brain=None)
        brain.cortex = MagicMock()
        brain.cortex.think_and_decide = AsyncMock(return_value={"thought": "fighting", "tool_calls": []})

        state = {
            "position": {"x": 0, "y": 64, "z": 0},
            "is_day": True,
            "health": 20,
            "food": 20,
            "nearby_hostiles": [],
            "inventory_items": []
        }
        brain.start_macro_plan("furnace", {}, state)
        self.assertIsNotNone(brain.active_macro_plan)

        # Hostile zombie approaches within 4m
        ambush_state = dict(state)
        ambush_state["nearby_hostiles"] = ["zombie (4m away)"]
        await brain.decide_next_action(ambush_state)

        self.assertIsNone(brain.active_macro_plan)


if __name__ == "__main__":
    unittest.main()
