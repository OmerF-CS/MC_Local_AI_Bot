"""Unit tests for Hamle 1 (Prompt Compression) & Hamle 2 (Curated Dataset Collector)."""

import os
import json
import tempfile
import unittest
from ai.prompts import build_system_prompt_for_ollama
from ai.dataset_collector import DatasetCollector


class TestDatasetAndPrompt(unittest.TestCase):
    """Test suite covering prompt compression, inventory delta validation, and deduplication."""

    def test_compressed_prompt_format(self):
        """Verify prompt is under 25 lines and contains few-shot examples and dynamic state."""
        state = {
            "health": 18,
            "food": 16,
            "position": {"x": 100.5, "y": 64.0, "z": -200.2},
            "dimension": "overworld",
            "nearby_hostiles": ["zombie"],
            "owner_info": {"distance": 5.2, "held_item": "iron_sword"},
            "carried_tools": ["stone_pickaxe"],
            "missing_ingredients": ["3 oak_log"]
        }
        goal = {"stage": "stone_era", "target": "furnace", "next_hint": "Mine stone"}
        prompt = build_system_prompt_for_ollama(
            state=state,
            bot_name="AIAssistant",
            bot_owner="Schizo_D",
            goal=goal,
            pro_tactic="Stay close",
            active_task=None
        )

        lines = [ln for ln in prompt.strip().split("\n") if ln.strip()]
        self.assertLessEqual(len(lines), 25, "Prompt must be compressed to <= 25 lines")
        self.assertIn("AIAssistant", prompt)
        self.assertIn("Schizo_D", prompt)
        self.assertIn("furnace", prompt)
        self.assertIn("EXAMPLES:", prompt)
        self.assertIn("HP: 18/20", prompt)

    def test_inventory_delta_computation(self):
        """Verify calculation of item increases, decreases, and additions."""
        pre_inv = {"oak_log": 2, "dirt": 5}
        post_inv = {"oak_log": 5, "dirt": 3, "cobblestone": 8}
        delta = DatasetCollector.compute_inventory_delta(pre_inv, post_inv)

        self.assertEqual(delta["oak_log"], 3)
        self.assertEqual(delta["dirt"], -2)
        self.assertEqual(delta["cobblestone"], 8)
        self.assertNotIn("sand", delta)

    def test_progress_made_verification(self):
        """Verify progress_made catches empty/accidental actions despite boolean success."""
        collector = DatasetCollector(output_path=os.path.join(tempfile.gettempdir(), "test_decisions_1.jsonl"))

        pre_state = {
            "target": "furnace",
            "inventory_items": [{"name": "stick", "count": 2}]
        }
        post_state_success = {
            "target": "furnace",
            "inventory_items": [{"name": "stick", "count": 2}, {"name": "cobblestone", "count": 3}]
        }
        post_state_noop = {
            "target": "furnace",
            "inventory_items": [{"name": "stick", "count": 2}]
        }

        decision = {"name": "collect_block", "arguments": {"block_name": "stone", "count": 3}}

        # True success: cobblestone gained
        delta_success = collector.compute_inventory_delta(
            collector.parse_inventory_dict(pre_state),
            collector.parse_inventory_dict(post_state_success)
        )
        is_prog_1 = collector.check_progress_made(
            pre_state, post_state_success, decision, {"success": True}, delta_success
        )
        self.assertTrue(is_prog_1, "Mining stone with cobblestone gained should be progress")

        # Fake success: action reported success but 0 blocks/items gained
        delta_noop = collector.compute_inventory_delta(
            collector.parse_inventory_dict(pre_state),
            collector.parse_inventory_dict(post_state_noop)
        )
        is_prog_2 = collector.check_progress_made(
            pre_state, post_state_noop, decision, {"success": True}, delta_noop
        )
        self.assertFalse(is_prog_2, "Action that produced no inventory change must not be flagged as progress")

    def test_deduplication_bucketing(self):
        """Verify repetitive routine actions are capped at max_duplicates."""
        tmp_file = os.path.join(tempfile.gettempdir(), f"test_dedup_{os.getpid()}.jsonl")
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

        collector = DatasetCollector(output_path=tmp_file, max_duplicates_per_bucket=2)

        pre_state = {
            "health": 20,
            "food": 20,
            "target": "wooden_pickaxe",
            "inventory_items": [{"name": "oak_log", "count": 1}]
        }
        post_state = {
            "health": 20,
            "food": 20,
            "target": "wooden_pickaxe",
            "inventory_items": [{"name": "oak_log", "count": 2}]
        }
        decision = {"name": "collect_block", "arguments": {"block_name": "oak_log", "count": 1}}
        exec_res = {"success": True}

        # Record 5 identical routine steps
        records = []
        for _ in range(5):
            rec = collector.record_step(pre_state, decision, exec_res, post_state)
            if rec:
                records.append(rec)

        self.assertEqual(len(records), 2, "Only 2 duplicates should be recorded")
        self.assertEqual(collector.stats["dedup_skipped_count"], 3)

        if os.path.exists(tmp_file):
            os.remove(tmp_file)

    def test_edge_case_bypass_and_tagging(self):
        """Verify critical survival edge cases are tagged and bypass deduplication limits."""
        tmp_file = os.path.join(tempfile.gettempdir(), f"test_edge_{os.getpid()}.jsonl")
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

        collector = DatasetCollector(output_path=tmp_file, max_duplicates_per_bucket=1)

        critical_state = {
            "health": 4,  # Critical HP
            "food": 3,   # Starving
            "dimension": "the_nether",
            "nearby_hostiles": ["blaze"],
            "target": "nether_portal"
        }
        decision = {"name": "build_shelter", "arguments": {"mode": "auto"}}
        exec_res = {"success": True}

        self.assertTrue(collector.is_edge_case(critical_state, decision))

        # Record edge case 3 times - none should be skipped because edge cases are valuable
        records = []
        for _ in range(3):
            rec = collector.record_step(critical_state, decision, exec_res, critical_state)
            if rec:
                records.append(rec)

        self.assertEqual(len(records), 3, "Edge cases must not be skipped by deduplication")
        self.assertEqual(collector.stats["edge_cases_count"], 3)

        if os.path.exists(tmp_file):
            os.remove(tmp_file)


if __name__ == "__main__":
    unittest.main()
