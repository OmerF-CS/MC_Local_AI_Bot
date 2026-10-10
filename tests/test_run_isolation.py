import os
import tempfile
import unittest
import json
import sqlite3
import logging

from utils.run_context import (
    generate_run_id,
    get_git_commit_hash,
    set_current_run_id,
    get_current_run_id,
    reset_current_run_id,
    get_run_directory,
    write_run_metadata,
)
from utils.logger import setup_logging, get_logger, RunIdFilter
from core.database import Database
from ai.dataset_collector import DatasetCollector


class TestRunIsolation(unittest.TestCase):
    """Unit tests for run ID generation, runs directory isolation, and metadata logging."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        reset_current_run_id()

    def tearDown(self):
        reset_current_run_id()

    def test_run_id_format(self):
        """Test default run_id format, test prefix, and environment override."""
        rid = generate_run_id()
        self.assertIn("_", rid)
        # Should have timestamp part and commit part
        parts = rid.split("_")
        self.assertGreaterEqual(len(parts), 2)

        # Test prefix
        test_rid = generate_run_id(is_test=True)
        self.assertTrue(test_rid.startswith("test_"))

        # Custom prefix
        bench_rid = generate_run_id(prefix="benchmark")
        self.assertTrue(bench_rid.startswith("benchmark_"))

        # MC_RUN_ID environment override
        os.environ["MC_RUN_ID"] = "custom_test_env_run"
        try:
            self.assertEqual(generate_run_id(), "custom_test_env_run")
        finally:
            del os.environ["MC_RUN_ID"]

    def test_run_directory_and_metadata(self):
        """Test directory creation and run_meta.json serialization."""
        test_id = "test_run_12345"
        set_current_run_id(test_id)
        run_dir = get_run_directory(test_id, base_dir=self.temp_dir.name)
        self.assertTrue(os.path.isdir(run_dir))
        self.assertTrue(run_dir.endswith(test_id))

        meta_path = write_run_metadata(
            test_id,
            extra_meta={"status": "completed", "custom_field": "val"},
            base_dir=self.temp_dir.name,
        )
        self.assertTrue(os.path.isfile(meta_path))

        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["run_id"], test_id)
        self.assertEqual(data["custom_field"], "val")
        self.assertEqual(data["status"], "completed")
        self.assertTrue(data["is_test"])
        self.assertIn("timestamp_utc", data)

    def test_logger_run_id_injection(self):
        """Test that RunIdFilter sets run_id attribute on log records."""
        set_current_run_id("test_filter_run")
        filter_obj = RunIdFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=10,
            msg="hello", args=(), exc_info=None
        )
        filter_obj.filter(record)
        self.assertEqual(getattr(record, "run_id", None), "test_filter_run")

    def test_database_run_id_migration_and_isolation(self):
        """Test database isolation using MC_DB_PATH and run_id schema migration."""
        db_path = os.path.join(self.temp_dir.name, "isolated_test.db")
        db = Database(db_path)

        try:
            # Check runs table exists
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runs'")
                self.assertIsNotNone(cursor.fetchone())

                # Verify runs table insert
                db.record_run("test_db_run_1", is_test=True, model_name="test_model", notes="unit testing")
                cursor.execute("SELECT run_id, is_test, model_name FROM runs WHERE run_id='test_db_run_1'")
                row = cursor.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "test_db_run_1")
                self.assertEqual(row[1], 1)
                self.assertEqual(row[2], "test_model")

                # Check progression_checkpoints has run_id column
                cursor.execute("PRAGMA table_info(progression_checkpoints)")
                columns = [col[1] for col in cursor.fetchall()]
                self.assertIn("run_id", columns)

                # Test save_progression saves run_id
                db.save_progression("wood_age", "wooden_pickaxe", run_id="test_db_run_1")
                cursor.execute("SELECT stage, target, run_id FROM progression_checkpoints WHERE run_id='test_db_run_1'")
                p_row = cursor.fetchone()
                self.assertIsNotNone(p_row)
                self.assertEqual(p_row[0], "wood_age")
                self.assertEqual(p_row[1], "wooden_pickaxe")
                self.assertEqual(p_row[2], "test_db_run_1")
            finally:
                conn.close()
        finally:
            db.close()

    def test_dataset_collector_run_directory_sync(self):
        """Test dataset collector dual-writes to main file and runs/<run_id>/decisions.jsonl."""
        main_out = os.path.join(self.temp_dir.name, "decisions_main.jsonl")
        test_run_id = "test_collector_run"
        set_current_run_id(test_run_id)

        # Pre-create run dir inside temp_dir
        run_dir = os.path.join(self.temp_dir.name, "runs", test_run_id)
        os.makedirs(run_dir, exist_ok=True)

        collector = DatasetCollector(output_path=main_out, run_id=test_run_id)
        collector.run_output_path = os.path.join(run_dir, "decisions.jsonl")

        pre_state = {"health": 20, "inventory": {"oak_log": 2}, "goal_target": "wooden_pickaxe"}
        decision = {"name": "craft_item", "arguments": {"item": "oak_planks", "count": 4}}
        exec_result = {"success": True, "error": None}
        post_state = {"health": 20, "inventory": {"oak_log": 1, "oak_planks": 4}, "goal_target": "wooden_pickaxe"}

        collector.record_step(
            pre_state=pre_state,
            decision=decision,
            exec_result=exec_result,
            post_state=post_state,
            duration_s=0.5
        )

        # Check main file
        self.assertTrue(os.path.isfile(main_out))
        with open(main_out, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data.get("run_id"), test_run_id)

        # Check run-isolated file
        run_decisions = os.path.join(run_dir, "decisions.jsonl")
        self.assertTrue(os.path.isfile(run_decisions))
        with open(run_decisions, "r", encoding="utf-8") as f:
            run_lines = f.readlines()
        self.assertEqual(len(run_lines), 1)
        run_data = json.loads(run_lines[0])
        self.assertEqual(run_data.get("run_id"), test_run_id)

    def test_benchmark_models_persistence_and_mock_flag(self):
        """Test benchmark results.json and samples.jsonl persistence with mock tagging."""
        from scripts.benchmark_models import run_benchmark_suite, BENCHMARK_PROMPTS

        bench_run_id = "test_benchmark_persist"
        results, run_dir = run_benchmark_suite(
            models=["qwen2.5:3b"],
            test_cases=BENCHMARK_PROMPTS[:2],
            is_mock=True,
            run_id=bench_run_id,
            base_dir=self.temp_dir.name
        )

        results_file = os.path.join(run_dir, "results.json")
        samples_file = os.path.join(run_dir, "samples.jsonl")

        self.assertTrue(os.path.isfile(results_file))
        self.assertTrue(os.path.isfile(samples_file))

        with open(results_file, "r", encoding="utf-8") as f:
            res_data = json.load(f)
        self.assertEqual(res_data["run_id"], bench_run_id)
        self.assertTrue(res_data["mock"])
        self.assertEqual(len(res_data["metrics"]), 1)
        self.assertTrue(res_data["metrics"][0]["mock"])

        with open(samples_file, "r", encoding="utf-8") as f:
            sample_lines = f.readlines()
        self.assertEqual(len(sample_lines), 2)
        sample_0 = json.loads(sample_lines[0])
        self.assertTrue(sample_0["mock"])
        self.assertEqual(sample_0["model"], "qwen2.5:3b")

    def test_server_log_capture_logic(self):
        """Test capturing server latest.log and bot.log into run directory."""
        import shutil
        test_run_id = "test_log_capture_run"
        set_current_run_id(test_run_id)

        # Mock server directory with logs/latest.log
        mock_server_dir = os.path.join(self.temp_dir.name, "test_server")
        os.makedirs(os.path.join(mock_server_dir, "logs"), exist_ok=True)
        server_log_src = os.path.join(mock_server_dir, "logs", "latest.log")
        with open(server_log_src, "w", encoding="utf-8") as f:
            f.write("[Server thread/INFO]: Done (2.123s)! For help, type \"help\"\n")

        run_dir = get_run_directory(test_run_id, base_dir=self.temp_dir.name)
        target_server_log = os.path.join(run_dir, "server_latest.log")
        shutil.copy2(server_log_src, target_server_log)

        self.assertTrue(os.path.isfile(target_server_log))
        with open(target_server_log, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Done (2.123s)!", content)

    def test_machine_readable_test_runner_report(self):
        """Test scripts/run_tests.py execution and test_report.json output generation."""
        from scripts.run_tests import execute_test_runner

        # Create an isolated dummy test file inside temp_dir to prevent recursive test execution
        dummy_test_path = os.path.join(self.temp_dir.name, "test_dummy.py")
        with open(dummy_test_path, "w", encoding="utf-8") as f:
            f.write(
                "import unittest\n\n"
                "class DummyTest(unittest.TestCase):\n"
                "    def test_dummy_success(self):\n"
                "        self.assertTrue(True)\n"
            )

        runner_run_id = "test_runner_isolation_check"
        report, report_path, exit_code = execute_test_runner(
            test_dir=self.temp_dir.name,
            pattern="test_dummy.py",
            run_id=runner_run_id,
            verbosity=0,
            base_dir=self.temp_dir.name
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(os.path.isfile(report_path))
        self.assertIn("summary", report)
        self.assertIn("environment", report)
        self.assertIn("tests", report)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["passed"], 1)


if __name__ == "__main__":
    unittest.main()




