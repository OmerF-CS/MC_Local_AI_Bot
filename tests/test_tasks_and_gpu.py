"""Unit tests for Task Queue Lifecycle and GPU Acceleration Configuration."""
import unittest
import os
import tempfile
from core.database import Database
from ai.ollama_client import OllamaBrain

class TestTasksAndGPU(unittest.TestCase):
    """Verifies SQLite task management and GPU parameter configurations."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.db = Database(db_path=self.temp_db_path)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass
        os.close(self.temp_db_fd)
        try:
            if os.path.exists(self.temp_db_path):
                os.remove(self.temp_db_path)
        except Exception:
            pass

    def test_task_queue_full_lifecycle(self):
        """Test adding, retrieving, updating, completing, and clearing tasks."""
        # 1. Add tasks
        task1_id = self.db.add_task("mine 5 iron", primary_action="collect_block", assigned_by="Omer", priority=5)
        task2_id = self.db.add_task("craft diamond sword", primary_action="craft_item", assigned_by="Omer", priority=3)

        self.assertIsNotNone(task1_id)
        self.assertIsNotNone(task2_id)

        # 2. Retrieve pending tasks (ordered by priority DESC)
        pending = self.db.get_pending_tasks()
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["id"], task1_id)
        self.assertEqual(pending[0]["instruction"], "mine 5 iron")

        # 3. Update task1 to active
        self.db.update_task_status(task1_id, "active")
        pending_after_active = self.db.get_pending_tasks()
        self.assertEqual(len(pending_after_active), 1)
        self.assertEqual(pending_after_active[0]["id"], task2_id)

        # 4. Complete task1
        self.db.complete_task(task1_id)

        # 5. Clear remaining pending tasks
        self.db.clear_pending_tasks()
        self.assertEqual(len(self.db.get_pending_tasks()), 0)

    def test_chat_handler_scoping_and_dispatch(self):
        """Verify chat handler runs without UnboundLocalError for asyncio or subprocess."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from core.chat_handler import MinecraftChatHandler

        bot = MagicMock()
        bot.config.BOT_NAME = "AIAssistant"
        bot.config.MINECRAFT_USERNAME = "AIAssistant"
        bot.config.BOT_OWNER = "Schizo_D"
        bot.config.COOLDOWN_SECONDS = 0.0
        bot.config.OLLAMA_MODEL = "qwen2.5:3b"
        bot.db = self.db
        bot.bridge = MagicMock()
        bot.bridge.send_action = AsyncMock()
        bot.bridge.latest_state = {}
        bot.brain = MagicMock()
        bot.brain.process_chat = AsyncMock(return_value={
            "text": "Understood",
            "tool_calls": [{"name": "say_chat", "arguments": {"message": "Understood"}}]
        })

        handler = MinecraftChatHandler(bot)
        asyncio.run(handler.handle_chat("Schizo_D", "Set own game mode to Spectator Mode", {}))
        self.assertTrue(bot.bridge.send_action.called)


if __name__ == "__main__":
    unittest.main()

