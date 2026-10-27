"""Unit tests for Speculative Concurrency Guard (Pending Commit Pattern).

Validates that decide_next_action(state, is_speculative=True):
1. Does NOT immediately mutate checkpoint_stage or last_goal_target.
2. Does NOT immediately write to db.save_progression.
3. Does NOT immediately write to register_home_base.
4. Does NOT immediately advance active_macro_plan.current_step_idx.
5. Pending commits are applied when commit_speculative_state() is called.
6. Pending commits are discarded when discard_speculative_state() is called.
7. AnticipatoryPipeline commits on success and discards on interrupt.
"""
import asyncio
import os
import sqlite3
import unittest
from unittest.mock import MagicMock, AsyncMock

from ai.planner import AutonomousCoopBrain
from ai.pipelining import AnticipatoryPipeline
from ai.macro_planner import MacroPlan, PlanStep
from core.database import Database


class DummyBrain:
    def __init__(self):
        self.model = "mc-qwen:3b"
        self._is_mock = True

    async def think_and_decide(self, *args, **kwargs):
        return {
            "text": "Autonomous decision",
            "thought": "Autonomous decision",
            "tool_calls": [{"name": "collect_block", "arguments": {"block_name": "oak_log", "count": 1}}]
        }


class TestSpeculativeConcurrencyGuard(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # In-memory database for isolated testing
        self.db = Database(":memory:")
        self.brain = DummyBrain()
        self.planner = AutonomousCoopBrain(self.brain, bot_owner="Omer", db=self.db)

    def tearDown(self):
        self.db.close()

    async def test_speculative_call_defers_progression_and_db_write(self):
        """is_speculative=True must collect progression in pending commits without writing to DB."""
        # Initial state: 0 items, stage should advance to wooden_pickaxe
        state = {
            "health": 20,
            "food": 20,
            "position": {"x": 0, "y": 64, "z": 0},
            "inventory_items": [],
            "inventory_summary": "Empty"
        }

        # Verify DB progression checkpoints table is empty initially
        cur = self.db.conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM progression_checkpoints")
        self.assertEqual(cur.fetchone()["cnt"], 0)
        self.assertIsNone(self.planner.checkpoint_stage)

        # Call with is_speculative=True
        decision = await self.planner.decide_next_action(state, is_speculative=True)
        self.assertIsNotNone(decision)

        # 1. Checkpoint stage and target must NOT be updated yet
        self.assertIsNone(self.planner.checkpoint_stage)
        self.assertIsNone(self.planner.last_goal_target)

        # 2. Database must NOT have any saved progression yet
        cur.execute("SELECT COUNT(*) as cnt FROM progression_checkpoints")
        self.assertEqual(cur.fetchone()["cnt"], 0)

        # 3. Pending commits must contain the deferred progression callback
        self.assertGreater(len(self.planner._pending_speculative_commits), 0)

        # Test Discard: if discarded, nothing should be applied
        self.planner.discard_speculative_state()
        self.assertEqual(len(self.planner._pending_speculative_commits), 0)
        self.assertIsNone(self.planner.checkpoint_stage)
        cur.execute("SELECT COUNT(*) as cnt FROM progression_checkpoints")
        self.assertEqual(cur.fetchone()["cnt"], 0)

        # Re-run speculative and Test Commit
        await self.planner.decide_next_action(state, is_speculative=True)
        self.assertGreater(len(self.planner._pending_speculative_commits), 0)

        self.planner.commit_speculative_state()
        self.assertEqual(len(self.planner._pending_speculative_commits), 0)
        # Now checkpoint must be set and DB saved!
        self.assertIsNotNone(self.planner.checkpoint_stage)
        cur.execute("SELECT COUNT(*) as cnt FROM progression_checkpoints")
        self.assertEqual(cur.fetchone()["cnt"], 1)

    async def test_speculative_call_defers_home_base_registration(self):
        """is_speculative=True must not register home_base in locations table until committed."""
        # Insert a bed in beds table
        with self.db.conn:
            self.db.conn.execute("INSERT INTO beds (dim, x, y, z) VALUES ('overworld', 10.0, 64.0, 20.0)")

        self.assertIsNone(self.planner.home_base_manager.get_home_base())

        state = {
            "health": 20,
            "food": 20,
            "position": {"x": 0, "y": 64, "z": 0},
            "inventory_items": [],
            "inventory_summary": "Empty"
        }

        # Speculative call
        await self.planner.decide_next_action(state, is_speculative=True)

        # home_base must NOT be registered in DB locations yet
        self.assertIsNone(self.planner.home_base_manager.get_home_base())

        # Commit
        self.planner.commit_speculative_state()
        # Now home_base must be registered
        home = self.planner.home_base_manager.get_home_base()
        self.assertIsNotNone(home)
        self.assertEqual(home["x"], 10.0)

    async def test_speculative_call_defers_macro_plan_advance_step(self):
        """is_speculative=True must not mutate active_macro_plan.current_step_idx."""
        # Create a 3-step macro plan
        plan = MacroPlan(
            target_item="stone_pickaxe",
            steps=[
                PlanStep(action="collect_block", arguments={"block_name": "log"}, description="Collect log", verification_item="log", verification_count=1),
                PlanStep(action="craft_item", arguments={"item_name": "planks"}, description="Craft planks", verification_item="planks", verification_count=4),
                PlanStep(action="craft_item", arguments={"item_name": "wooden_pickaxe"}, description="Craft pickaxe", verification_item="wooden_pickaxe", verification_count=1)
            ]
        )
        self.planner.active_macro_plan = plan
        self.assertEqual(self.planner.active_macro_plan.current_step_idx, 0)

        # State has 1 log satisfied (step 0 satisfied)
        state = {
            "health": 20,
            "food": 20,
            "position": {"x": 0, "y": 64, "z": 0},
            "inventory_items": [{"name": "oak_log", "count": 2}],
            "inventory_summary": "oak_log x2"
        }

        # In speculative mode, step 0 is satisfied, so it should suggest step 1 without mutating plan.current_step_idx
        decision = await self.planner.decide_next_action(state, is_speculative=True)
        self.assertIsNotNone(decision)
        tc = decision.get("tool_calls", [])
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0]["name"], "craft_item")
        self.assertEqual(tc[0]["arguments"]["item_name"], "planks")

        # Crucial check: permanent plan pointer must STILL be 0!
        self.assertEqual(self.planner.active_macro_plan.current_step_idx, 0)

        # If discarded:
        self.planner.discard_speculative_state()
        self.assertEqual(self.planner.active_macro_plan.current_step_idx, 0)

        # Re-run speculative and commit:
        await self.planner.decide_next_action(state, is_speculative=True)
        self.planner.commit_speculative_state()
        # After commit, the pointer is advanced to step 1!
        self.assertEqual(self.planner.active_macro_plan.current_step_idx, 1)

    async def test_anticipatory_pipeline_commits_and_discards(self):
        """AnticipatoryPipeline must commit on successful retrieval and discard on damage interrupt."""
        pipeline = AnticipatoryPipeline(self.planner)
        pre_state = {
            "health": 20.0,
            "food": 18,
            "position": {"x": 0, "y": 64, "z": 0},
            "inventory_items": [],
            "inventory_summary": "Empty",
            "nearby_hostiles": []
        }

        # 1. Start precomputation
        pipeline.start_precomputation(pre_state, "collect_block", {"block_name": "log", "count": 1})
        self.assertIsNotNone(pipeline._precomputed_task)

        # 2. Case A: Interrupted by health damage (takes 2.0 damage)
        post_state_damaged = dict(pre_state)
        post_state_damaged["health"] = 17.5  # 2.5 damage > 1.5 threshold

        decision = await pipeline.get_next_decision(
            current_state=post_state_damaged,
            pre_snapshot=pre_state,
            exec_result={"success": True}
        )
        self.assertIsNotNone(decision)
        # Since interrupted, speculative commits were discarded!
        self.assertEqual(len(self.planner._pending_speculative_commits), 0)

        # 3. Case B: Successful execution without interrupt
        pipeline.start_precomputation(pre_state, "collect_block", {"block_name": "log", "count": 1})
        post_state_success = dict(pre_state)
        post_state_success["health"] = 20.0

        decision2 = await pipeline.get_next_decision(
            current_state=post_state_success,
            pre_snapshot=pre_state,
            exec_result={"success": True}
        )
        self.assertIsNotNone(decision2)
        # Since confirmed, speculative commits were committed!
        self.assertEqual(len(self.planner._pending_speculative_commits), 0)
        self.assertIsNotNone(self.planner.checkpoint_stage)


if __name__ == "__main__":
    unittest.main()
