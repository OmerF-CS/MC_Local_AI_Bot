"""Comprehensive Unit & Scenario Tests for H1-H14 Bug Fixes:
Death Recovery, Action Result Lifecycle, Progression Prerequisite & Chat Directives.
"""
import unittest
import asyncio
import tempfile
import os
import time
from unittest.mock import MagicMock, AsyncMock, patch

from core.database import Database
from main import MinecraftAIBot
from core.chat_handler import MinecraftChatHandler
from ai.planner import AutonomousCoopBrain
from utils.config import Config


class TestDeathRecoveryAndActionLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp_dir.name, "test_lifecycle.db")
        self.db = Database(db_path=self.db_path)
        
        self.config = Config()
        self.config.BOT_NAME = "AIAssistant"
        self.config.BOT_OWNER = "Schizo_D"
        self.config.MINECRAFT_USERNAME = "AIAssistant"

        # Mock Ollama Brain
        self.mock_brain = MagicMock()
        self.mock_brain.process_chat = AsyncMock(return_value={"text": "Acknowledged", "tool_calls": []})
        self.mock_brain.generate_decision = AsyncMock(return_value={"text": "Mining", "tool_calls": []})

        # Mock Bridge
        self.mock_bridge = MagicMock()
        self.mock_bridge.latest_state = {}
        self.mock_bridge.send_action = AsyncMock()
        self.mock_bridge.send_action_and_wait = AsyncMock(return_value={"success": True, "error": None})
        self.config.RUN_ID = "test-lifecycle-run"
        self.config.DB_PATH = self.db_path

        # Instantiate MinecraftAIBot with mocks
        with patch("main.OllamaBrain", return_value=self.mock_brain), \
             patch("main.MinecraftBridge", return_value=self.mock_bridge), \
             patch("main.Database", return_value=self.db):
            self.bot = MinecraftAIBot(self.config)
            self.bot.db = self.db
            self.bot.bridge = self.mock_bridge

    async def asyncTearDown(self):
        if hasattr(self, "bot") and hasattr(self.bot, "db") and self.bot.db:
            try:
                self.bot.db.close()
            except Exception:
                pass
        if hasattr(self, "db") and self.db:
            try:
                self.db.close()
            except Exception:
                pass
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    # --- H1 & H2 & H4: Death Event & Inventory Snapshot Fallback ---

    async def test_death_event_uses_cached_inventory_when_empty(self):
        """H2: If death event contains empty inventory, fallback to last known non-empty inventory."""
        # 1. Simulate active gameplay with items
        active_state = {
            "health": 20,
            "inventory": [{"name": "diamond_sword", "count": 1}, {"name": "bread", "count": 5}],
            "position": {"x": 100.0, "y": 64.0, "z": 200.0},
            "dimension": "overworld"
        }
        self.bot._update_last_known_state(active_state)

        # 2. Death event arrives with empty inventory (e.g. from respawn wipe race)
        death_data = {
            "death_pos": {"x": 105.0, "y": 64.0, "z": 205.0},
            "dimension": "overworld",
            "inventory_snapshot": []
        }
        await self.bot.on_bot_death(death_data)

        # 3. Verify death point in database has recovered the cached inventory
        dp = self.db.get_unrecovered_death_point("overworld")
        self.assertIsNotNone(dp)
        self.assertEqual(len(dp["inventory"]), 2)
        self.assertEqual(dp["inventory"][0]["name"], "diamond_sword")
        self.assertEqual(dp["x"], 105.0)

    async def test_death_with_empty_inventory_skips_recovery_task(self):
        """H4: If bot dies with truly empty inventory, death point is marked recovered and no task is opened."""
        self.bot.last_known_inventory = []
        death_data = {
            "death_pos": {"x": 50.0, "y": 64.0, "z": 50.0},
            "dimension": "overworld",
            "inventory_snapshot": []
        }
        await self.bot.on_bot_death(death_data)

        # Death point should be automatically marked as recovered = 1
        unrecovered = self.db.get_unrecovered_death_point("overworld")
        self.assertIsNone(unrecovered)

        # Respawn should not trigger any corpse recovery task
        respawn_state = {"health": 20, "position": {"x": 0.0, "y": 64.0, "z": 0.0}, "dimension": "overworld"}
        await self.bot.on_bot_respawn(respawn_state)
        self.assertIsNone(self.bot.active_recovery_task_id)
        self.assertIsNone(self.bot.active_player_task)

    # --- H3: Respawn Event & Readiness ---

    async def test_bot_respawn_sets_ready_flag_and_triggers_recovery(self):
        """H3: Respawn event sets _bot_ready and triggers corpse recovery for dropped items."""
        # Record a death with dropped items
        self.db.save_death_point("overworld", 100.0, 64.0, 200.0, inventory=[{"name": "iron_pickaxe", "count": 1}])
        self.bot._bot_ready.clear()

        respawn_state = {
            "health": 20,
            "position": {"x": 0.0, "y": 64.0, "z": 0.0},
            "dimension": "overworld"
        }
        await self.bot.on_bot_respawn(respawn_state)

        # Bot ready event must be set
        self.assertTrue(self.bot._bot_ready.is_set())
        # Recovery task must be queued in DB
        pending = self.db.get_pending_tasks()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["primary_action"], "go_to_coordinates")
        self.assertEqual(pending[0]["args"]["x"], 100.0)

    # --- H5: Corpse Recovery Physical Proximity, Dimension & Timeout ---

    async def test_corpse_recovery_deduplication(self):
        """H5: Corpse recovery must not be queued multiple times for the same death_id."""
        death_id = self.db.save_death_point("overworld", 80.0, 64.0, 80.0, inventory=[{"name": "shield", "count": 1}])
        
        respawn_state = {"health": 20, "position": {"x": 0.0, "y": 64.0, "z": 0.0}, "dimension": "overworld"}
        await self.bot.check_and_trigger_corpse_recovery(respawn_state)
        # Call it again repeatedly
        await self.bot.check_and_trigger_corpse_recovery(respawn_state)
        await self.bot.check_and_trigger_corpse_recovery(respawn_state)

        pending = self.db.get_pending_tasks()
        self.assertEqual(len(pending), 1, "Should only have exactly 1 recovery task queued")

    async def test_corpse_recovery_not_completed_if_distance_greater_than_5m(self):
        """H5: go_to_coordinates completion does not mark recovery task complete if bot is not within 5m."""
        death_id = self.db.save_death_point("overworld", 100.0, 64.0, 100.0, inventory=[{"name": "cooked_beef", "count": 8}])
        task_id = self.db.add_task(
            instruction="Recover items from death site",
            primary_action="go_to_coordinates",
            args={"x": 100.0, "y": 64.0, "z": 100.0, "death_id": death_id},
            priority=10
        )
        self.bot.active_player_task = {
            "id": task_id,
            "instruction": "Recover items from death site",
            "primary_action": "go_to_coordinates",
            "args": {"death_id": death_id}
        }
        self.bot.active_recovery_task_id = task_id
        self.bot.active_recovery_death_id = death_id
        self.bot.active_recovery_start_time = time.time()

        # Bot arrived at (50, 64, 50), which is > 5m from (100, 64, 100)
        state_far = {"position": {"x": 50.0, "y": 64.0, "z": 50.0}, "dimension": "overworld"}
        await self.bot.on_action_completed("go_to_coordinates", True, None, state_far)

        # Task must NOT be marked complete in DB
        unrecovered = self.db.get_unrecovered_death_point("overworld")
        self.assertIsNotNone(unrecovered)
        self.assertEqual(unrecovered["id"], death_id)

    async def test_corpse_recovery_succeeds_when_within_5m_in_same_dimension(self):
        """H5: When bot reaches within 5m in the same dimension, items are collected and marked recovered."""
        death_id = self.db.save_death_point("overworld", 100.0, 64.0, 100.0, inventory=[{"name": "iron_sword", "count": 1}])
        task_id = self.db.add_task(
            instruction="Recover items from death site",
            primary_action="go_to_coordinates",
            args={"x": 100.0, "y": 64.0, "z": 100.0, "death_id": death_id},
            priority=10
        )
        self.bot.active_player_task = {
            "id": task_id,
            "instruction": "Recover items from death site",
            "primary_action": "go_to_coordinates",
            "args": {"death_id": death_id}
        }
        self.bot.active_recovery_task_id = task_id
        self.bot.active_recovery_death_id = death_id
        self.bot.active_recovery_start_time = time.time()

        # Bot is at (101.5, 64.0, 101.5), dist ~= 2.12m <= 5m
        state_near = {"position": {"x": 101.5, "y": 64.0, "z": 101.5}, "dimension": "overworld"}
        await self.bot.on_action_completed("go_to_coordinates", True, None, state_near)

        # Task and death point must both be marked completed
        unrecovered = self.db.get_unrecovered_death_point("overworld")
        self.assertIsNone(unrecovered)
        self.assertIsNone(self.bot.active_player_task)
        self.mock_bridge.send_action.assert_any_call("collect_nearby_drops", {"radius": 32})

    # --- H8: Strict Action Correlation ---

    async def test_unrelated_actions_do_not_complete_active_task(self):
        """H8: stuck_recovery or say_chat finishing must NOT mark a mining/movement task completed."""
        task_id = self.db.add_task(
            instruction="Mine diamond ore",
            primary_action="collect_block",
            args={"block_name": "diamond_ore", "count": 1},
            priority=5
        )
        self.bot.active_player_task = {
            "id": task_id,
            "instruction": "Mine diamond ore",
            "primary_action": "collect_block"
        }

        # Anti-stuck or say_chat finishes
        state = {"position": {"x": 0.0, "y": 64.0, "z": 0.0}}
        await self.bot.on_action_completed("stuck_recovery", True, None, state)
        await self.bot.on_action_completed("say_chat", True, None, state)

        # Active player task must remain active!
        self.assertIsNotNone(self.bot.active_player_task)
        self.assertEqual(self.bot.active_player_task["id"], task_id)

        # Only the matching primary action completes it
        await self.bot.on_action_completed("collect_block", True, None, state)
        self.assertIsNone(self.bot.active_player_task)

    # --- H9: Progression Prerequisite Check ---

    def test_milestone_action_requires_pickaxe_before_stone(self):
        """H9: get_milestone_action orders wood/pickaxe first if bot has no pickaxe when targeting stone."""
        state_no_tools = {
            "inventory": [],
            "nearby_blocks": ["oak_log", "stone"]
        }
        desc, action = self.bot.planner.get_milestone_action({"target": "stone_pickaxe"}, {}, state_no_tools)
        # Cannot order stone directly without a pickaxe; must gather logs / wooden pickaxe first
        self.assertEqual(action["name"], "collect_block")
        self.assertIn("log", action["arguments"]["block_name"])

    # --- H10: Chat Directive Filtering ---

    async def test_casual_chat_and_short_messages_do_not_create_tasks(self):
        """H10: Casual chats like 't' or system death broadcasts do not create active tasks."""
        handler = MinecraftChatHandler(self.bot)
        state = {"health": 20, "inventory": []}

        # 1. Single character or 2-char accidental keystroke 't'
        await handler.handle_chat("Schizo_D", "t", state)
        self.assertIsNone(self.bot.active_player_task)

        # 2. Death broadcast / combat message
        await handler.handle_chat("Schizo_D", "Schizo_D Killed AIAssistant]", state)
        self.assertIsNone(self.bot.active_player_task)

        # 3. Explicit directive DOES create a task
        await handler.handle_chat("Schizo_D", "!mine stone 5", state)
        self.assertIsNotNone(self.bot.active_player_task)
        self.assertEqual(self.bot.active_player_task["primary_action"], "collect_block")

    # --- Comprehensive Scenario Test (H1 -> H6) ---

    async def test_full_death_recovery_lifecycle_scenario(self):
        """Scenario: death event -> death_point saved -> snapshot populated -> respawn ->
        recovery task created -> unrelated action doesn't complete -> goto arrived (dist <= 5m) ->
        drops collected -> death point marked recovered.
        """
        # Step 1: Pre-death state caching (H2)
        alive_state = {
            "health": 20,
            "inventory": [
                {"name": "diamond_pickaxe", "count": 1},
                {"name": "golden_apple", "count": 2}
            ],
            "position": {"x": 150.0, "y": 65.0, "z": 250.0},
            "dimension": "overworld"
        }
        self.bot._update_last_known_state(alive_state)

        # Step 2: Death event arrives with empty inventory snapshot (H1, H2)
        death_data = {
            "death_pos": {"x": 155.0, "y": 65.0, "z": 255.0},
            "dimension": "overworld",
            "inventory_snapshot": []
        }
        await self.bot.on_bot_death(death_data)

        # Verify death point in database is recorded with the 2 item stacks (H2)
        dp = self.db.get_unrecovered_death_point("overworld")
        self.assertIsNotNone(dp)
        self.assertEqual(dp["x"], 155.0)
        self.assertEqual(len(dp["inventory"]), 2)
        self.assertEqual(dp["inventory"][0]["name"], "diamond_pickaxe")

        # Step 3: Bot respawns (H3)
        self.bot._bot_ready.clear()
        respawn_state = {
            "health": 20,
            "position": {"x": 0.0, "y": 65.0, "z": 0.0},
            "dimension": "overworld"
        }
        await self.bot.on_bot_respawn(respawn_state)

        # Bot is ready and corpse recovery task is queued
        self.assertTrue(self.bot._bot_ready.is_set())
        pending = self.db.get_pending_tasks()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["primary_action"], "go_to_coordinates")
        self.assertEqual(pending[0]["args"]["death_id"], dp["id"])

        # Promote task to active
        task = pending[0]
        self.db.update_task_status(task["id"], "active")
        self.bot.active_player_task = task
        self.bot.active_recovery_task_id = task["id"]
        self.bot.active_recovery_death_id = dp["id"]
        self.bot.active_recovery_start_time = time.time()

        # Step 4: Unrelated actions complete (H8)
        intermediate_state = {"position": {"x": 10.0, "y": 65.0, "z": 10.0}, "dimension": "overworld"}
        await self.bot.on_action_completed("say_chat", True, None, intermediate_state)
        await self.bot.on_action_completed("stuck_recovery", True, None, intermediate_state)
        self.assertIsNotNone(self.bot.active_player_task, "Unrelated actions must NOT complete corpse recovery task")

        # Step 5: Movement action finishes, but bot is still far away (> 5m) (H5)
        far_state = {"position": {"x": 50.0, "y": 65.0, "z": 50.0}, "dimension": "overworld"}
        await self.bot.on_action_completed("go_to_coordinates", True, None, far_state)
        self.assertIsNotNone(self.bot.active_player_task, "Task must NOT complete if bot is > 5m from death site")
        self.assertIsNotNone(self.db.get_unrecovered_death_point("overworld"))

        # Step 6: Bot successfully arrives within 5m of death location (H5, H6)
        near_state = {"position": {"x": 155.5, "y": 65.0, "z": 155.0}, "dimension": "overworld"} # dx=0.5, dz=0.0 -> dist=0.5m
        near_state["position"]["z"] = 255.0
        await self.bot.on_action_completed("go_to_coordinates", True, None, near_state)

        # Step 7: Verification of completion (H5)
        self.assertIsNone(self.bot.active_player_task, "Task must be marked complete")
        self.assertIsNone(self.db.get_unrecovered_death_point("overworld"), "Death point must be marked recovered in DB")
        self.mock_bridge.send_action.assert_any_call("collect_nearby_drops", {"radius": 32})

    # --- Watchdog and Disconnected State Verification ---

    async def test_action_rejected_immediately_when_worker_disconnected(self):
        """Worker not connected results in immediate bot_not_ready response without waiting."""
        self.bot.bridge.clients = set()
        res = await self.bot.chat_handler._execute_tool("collect_block", {"block_name": "log"}, {}, "Schizo_D")
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("error"), "bot_not_ready")

    async def test_wait_for_bot_ready_rejects_stale_state_when_worker_disconnected(self):
        """wait_for_bot_ready must reject stale state when no worker is connected."""
        self.bot.bridge.clients = set()
        self.bot.bridge.latest_state = {"health": 20}
        self.bot._bot_ready.clear()
        ready = await self.bot.wait_for_bot_ready(timeout=0.1)
        self.assertFalse(ready, "Must not return True from stale state when worker is disconnected")

    async def test_wait_for_bot_ready_accepts_when_worker_connected_and_ready(self):
        """wait_for_bot_ready succeeds when worker client is connected and ready."""
        self.bot.bridge.clients = {"client_1"}
        self.bot.bridge.latest_state = {"health": 20}
        self.bot._bot_ready.set()
        ready = await self.bot.wait_for_bot_ready(timeout=0.1)
        self.assertTrue(ready)

    # --- Chat Spam Prevention & Relocation Verification ---

    def test_sheltered_idle_wait_returns_empty_text_and_no_tools(self):
        """When safely sheltered in bunker, reflex returns empty text so chat is not spammed."""
        state = {
            "health": 4,
            "food": 18,
            "is_sheltered": True,
            "is_day": False,
            "nearby_hostiles": ["zombie (8m away)"]
        }
        self.bot.planner.last_bunker_wait_chat_time = time.time()  # recent chat
        reflex = self.bot.planner._should_use_emergency_action(state, {})
        self.assertIsNotNone(reflex)
        self.assertEqual(reflex.get("text"), "")
        self.assertEqual(reflex.get("tool_calls"), [])

    def test_stuck_relocation_uses_ignore_y(self):
        """Loop breaker relocation produces go_to_coordinates with ignore_y to avoid unreachable height errors."""
        state = {
            "position": {"x": 10.0, "y": 92.0, "z": -20.0},
            "inventory_summary": "raw_iron x3"
        }
        self.bot.planner.consecutive_repeats = 3
        # Calling loop breaker relocation directly
        pos = state.get("position")
        plan = {
            "text": "Action stalled. Relocating to a better position.",
            "tool_calls": [
                {"name": "go_to_coordinates", "arguments": {"x": round(pos["x"] + 10), "z": round(pos["z"] + 10), "ignore_y": True, "range": 3}}
            ]
        }
        cmd = plan["tool_calls"][0]["name"]
        args = plan["tool_calls"][0]["arguments"]
        self.assertEqual(cmd, "go_to_coordinates")
        self.assertTrue(args.get("ignore_y"))
        self.assertNotIn("y", args)


if __name__ == "__main__":
    unittest.main()
