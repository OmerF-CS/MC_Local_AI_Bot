"""Unit tests for SFT Dataset Exporter and Data Curator."""

import unittest
import os
import json
import tempfile
from export_sft_dataset import (
    clean_and_curate_recorded_decisions,
    generate_speedrun_golden_samples,
    export_sft_dataset,
    create_chatml_sample
)


class TestExportSFTDataset(unittest.TestCase):
    """Test suite covering data curation, augmentation, and ChatML serialization."""

    def test_create_chatml_sample_format(self):
        sample = create_chatml_sample(
            system_prompt="Test system",
            user_content="[autonomous]: Decide next action",
            tool_name="craft_item",
            arguments={"item_name": "wooden_pickaxe", "count": 1}
        )
        self.assertIn("messages", sample)
        self.assertEqual(len(sample["messages"]), 3)
        self.assertEqual(sample["messages"][0]["role"], "system")
        self.assertEqual(sample["messages"][1]["role"], "user")
        self.assertEqual(sample["messages"][2]["role"], "assistant")
        self.assertIn("<tool_call>", sample["messages"][2]["content"])
        self.assertIn("wooden_pickaxe", sample["messages"][2]["content"])

    def test_curation_remaps_planks_to_log(self):
        raw_records = [{
            "state": {"health": 20, "food": 20, "inventory": {}},
            "milestone": {"target": "wooden_pickaxe", "stage": "WOOD"},
            "decision": {"tool_name": "collect_block", "arguments": {"block_name": "planks", "count": 3}},
            "execution": {"progress_made": False, "is_edge_case": False, "bridge_success": True}
        }]
        curated = clean_and_curate_recorded_decisions(raw_records)
        self.assertEqual(len(curated), 1)
        tool_call = curated[0]["tool_call"]
        self.assertEqual(tool_call["name"], "collect_block")
        self.assertEqual(tool_call["arguments"]["block_name"], "log")

    def test_curation_remaps_iron_ingot_craft_to_smelt(self):
        raw_records = [{
            "state": {"health": 20, "food": 20, "inventory": {"raw_iron": 3}},
            "milestone": {"target": "iron_pickaxe", "stage": "IRON_GEAR"},
            "decision": {"tool_name": "craft_item", "arguments": {"item_name": "iron_ingot", "count": 3}},
            "execution": {"progress_made": False, "is_edge_case": False, "bridge_success": True}
        }]
        curated = clean_and_curate_recorded_decisions(raw_records)
        self.assertEqual(len(curated), 1)
        tool_call = curated[0]["tool_call"]
        self.assertEqual(tool_call["name"], "smelt_item")
        self.assertEqual(tool_call["arguments"]["input_item"], "raw_iron")

    def test_curation_preserves_cherry_log_wooden_pickaxe_craft(self):
        raw_records = [{
            "state": {"health": 20, "food": 20, "inventory": {"cherry_log": 4}},
            "milestone": {"target": "wooden_pickaxe", "stage": "WOOD"},
            "decision": {"tool_name": "craft_item", "arguments": {"item_name": "wooden_pickaxe", "count": 1}},
            "execution": {"progress_made": False, "is_edge_case": False, "bridge_success": False}
        }]
        curated = clean_and_curate_recorded_decisions(raw_records)
        self.assertEqual(len(curated), 1)
        tool_call = curated[0]["tool_call"]
        self.assertEqual(tool_call["name"], "craft_item")
        self.assertEqual(tool_call["arguments"]["item_name"], "wooden_pickaxe")

    def test_curation_skips_autonomous_idle_calls(self):
        raw_records = [
            {
                "state": {"health": 20, "food": 20, "inventory": {}},
                "milestone": {"target": "wooden_pickaxe", "stage": "WOOD"},
                "decision": {"tool_name": "list_saved_locations", "arguments": {}},
                "execution": {"progress_made": False, "is_edge_case": False, "bridge_success": True}
            },
            {
                "state": {"health": 20, "food": 20, "inventory": {}},
                "milestone": {"target": "wooden_pickaxe", "stage": "WOOD"},
                "decision": {"tool_name": "stop_actions", "arguments": {}},
                "execution": {"progress_made": False, "is_edge_case": False, "bridge_success": True}
            }
        ]
        curated = clean_and_curate_recorded_decisions(raw_records)
        self.assertEqual(len(curated), 0)

    def test_speedrun_golden_samples_count_and_syntax(self):
        golden = generate_speedrun_golden_samples(target_count=50)
        self.assertGreaterEqual(len(golden), 50)
        for s in golden:
            self.assertIn("messages", s)
            assistant_msg = s["messages"][2]["content"]
            self.assertTrue(assistant_msg.startswith("<tool_call>\n"))
            self.assertTrue(assistant_msg.endswith("\n</tool_call>"))
            inner_json = assistant_msg.replace("<tool_call>\n", "").replace("\n</tool_call>", "")
            parsed = json.loads(inner_json)
            self.assertIn("name", parsed)
            self.assertIn("arguments", parsed)

    def test_export_pipeline_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_input = os.path.join(tmpdir, "test_decisions.jsonl")
            train_out = os.path.join(tmpdir, "train.jsonl")
            val_out = os.path.join(tmpdir, "val.jsonl")

            with open(raw_input, "w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "state": {"health": 20, "food": 20, "inventory": {"oak_log": 4}},
                    "milestone": {"target": "wooden_pickaxe", "stage": "WOOD"},
                    "decision": {"tool_name": "craft_item", "arguments": {"item_name": "wooden_pickaxe", "count": 1}},
                    "execution": {"progress_made": True, "is_edge_case": False, "bridge_success": True}
                }) + "\n")

            train_n, val_n = export_sft_dataset(
                input_path=raw_input,
                train_output=train_out,
                val_output=val_out,
                target_count=30,
                val_ratio=0.1
            )

            self.assertTrue(os.path.exists(train_out))
            self.assertTrue(os.path.exists(val_out))
            self.assertGreater(train_n, 20)
            self.assertGreater(val_n, 0)
            self.assertEqual(train_n + val_n, 30)

    def test_curation_filters_test_runs(self):
        """Verify that records from test runs are filtered out unless include_test_runs=True."""
        raw_records = [
            {
                "run_id": "test_20261010_123456",
                "state": {"health": 20, "food": 20, "inventory": {"oak_log": 4}},
                "milestone": {"target": "wooden_pickaxe", "stage": "WOOD"},
                "decision": {"tool_name": "craft_item", "arguments": {"item_name": "wooden_pickaxe", "count": 1}},
                "execution": {"progress_made": True, "is_edge_case": False, "bridge_success": True}
            },
            {
                "run_id": "prod_20261010_654321",
                "state": {"health": 20, "food": 20, "inventory": {"oak_log": 4}},
                "milestone": {"target": "wooden_pickaxe", "stage": "WOOD"},
                "decision": {"tool_name": "craft_item", "arguments": {"item_name": "wooden_pickaxe", "count": 1}},
                "execution": {"progress_made": True, "is_edge_case": False, "bridge_success": True}
            }
        ]

        # By default, test run should be excluded
        curated_default = clean_and_curate_recorded_decisions(raw_records, include_test_runs=False)
        self.assertEqual(len(curated_default), 1)

        # When include_test_runs=True, both should be included
        curated_included = clean_and_curate_recorded_decisions(raw_records, include_test_runs=True)
        self.assertEqual(len(curated_included), 2)


if __name__ == "__main__":
    unittest.main()
