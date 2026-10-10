#!/usr/bin/env python3
"""Benchmark and evaluation engine for 3B vs 7B local models.

Measures:
1. JSON Format Validity Rate (%)
2. Tool Call Schema Compliance Rate (%)
3. Decision Latency (Average & p95 ms)
4. Milestone Tactical Accuracy (%) against canonical survival scenarios.
"""
import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from utils.run_context import (
    generate_run_id,
    get_run_directory,
    get_git_commit_hash,
    set_current_run_id,
    get_current_run_id
)

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Canonical test benchmarks across survival progression
BENCHMARK_PROMPTS = [
    {
        "id": "wood_gathering",
        "prompt": "Milestone: wooden_pickaxe. Missing: 3x wood log. HP: 20/20, Food: 20/20. Decide 1 tool to progress.",
        "expected_tool": "collect_block",
        "expected_args": {"block_name": "log"}
    },
    {
        "id": "stone_mining",
        "prompt": "Milestone: stone_pickaxe. Missing: 3x cobblestone. HP: 20/20, Food: 20/20. Decide 1 tool to progress.",
        "expected_tool": "collect_block",
        "expected_args": {"block_name": "stone"}
    },
    {
        "id": "shield_crafting",
        "prompt": "Milestone: iron_pickaxe. Have 1 iron ingot, 6 planks, 0 shields. Hostiles nearby: skeleton. Decide 1 tool to progress.",
        "expected_tool": "craft_item",
        "expected_args": {"item_name": "shield"}
    },
    {
        "id": "smelt_raw_iron",
        "prompt": "Milestone: iron_pickaxe. Inventory has raw_iron: 3, coal: 2, furnace: 1. Need 3 iron ingots. Decide 1 tool to progress.",
        "expected_tool": "smelt_item",
        "expected_args": {"input_item": "raw_iron"}
    },
    {
        "id": "emergency_bunker",
        "prompt": "Health is critical: 4/20. Hostiles: 3 zombies at 3m. Shelter mode: auto. Decide 1 tool to progress.",
        "expected_tool": "build_shelter",
        "expected_args": {}
    },
    {
        "id": "nether_piglin_barter",
        "prompt": "Dimension: the_nether. Milestone: eye_of_ender. Have gold_ingot: 8, ender_pearl: 0. Nearby piglins: 3. Decide 1 tool to progress.",
        "expected_tool": "barter_with_piglins",
        "expected_args": {}
    },
    {
        "id": "end_crystals_demolition",
        "prompt": "Dimension: the_end. Milestone: end_crystal. Dragon perching overhead. Remaining crystals: 4. Decide 1 tool to progress.",
        "expected_tool": "destroy_end_crystals",
        "expected_args": {}
    },
    {
        "id": "anvil_repair",
        "prompt": "Dimension: overworld. low_durability_gear: true, nearby_anvil: true, iron_ingot: 4. Decide 1 tool to progress.",
        "expected_tool": "repair_gear_anvil",
        "expected_args": {}
    }
]


def validate_model_response(raw_text: str, expected_tool: str) -> Tuple[bool, bool, bool, Optional[Dict[str, Any]]]:
    """Validates raw model output for:

    (is_valid_json, is_valid_tool_schema, is_accurate_decision, parsed_call)
    """
    if not raw_text or not isinstance(raw_text, str):
        return False, False, False, None

    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except Exception:
        # Check if text contains embedded JSON object
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(cleaned[start:end+1])
            except Exception:
                return False, False, False, None
        else:
            return False, False, False, None

    is_valid_json = True

    # Check tool call compliance
    tool_calls = parsed.get("tool_calls")
    if not tool_calls or not isinstance(tool_calls, list) or len(tool_calls) == 0:
        # Alternatively direct tool object schema: {"name": "...", "arguments": {...}}
        if "name" in parsed and "arguments" in parsed:
            tool_calls = [parsed]
        else:
            return is_valid_json, False, False, None

    call = tool_calls[0]
    if not isinstance(call, dict) or "name" not in call or not isinstance(call.get("arguments"), dict):
        return is_valid_json, False, False, None

    is_valid_tool_schema = True
    action_name = call.get("name", "").strip().lower()
    is_accurate = (action_name == expected_tool.lower())

    return is_valid_json, is_valid_tool_schema, is_accurate, call


def check_ollama_online(base_url: str = "http://localhost:11434") -> bool:
    """Checks whether the Ollama server is reachable and active."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def default_ollama_evaluator(model_name: str, prompt: str, base_url: str = "http://localhost:11434") -> str:
    """Evaluates a prompt against Ollama /api/chat endpoint."""
    import urllib.request
    payload = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0}
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("message", {}).get("content", "")


def benchmark_model(
    model_name: str,
    test_cases: List[Dict[str, Any]],
    client_evaluator=None,
    is_mock: bool = False,
    samples_collector: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Evaluates a model over test cases and returns performance metrics."""
    total_samples = len(test_cases)
    valid_json_count = 0
    valid_schema_count = 0
    accurate_count = 0
    latencies: List[float] = []

    for test in test_cases:
        prompt = test["prompt"]
        expected_tool = test["expected_tool"]

        start_t = time.perf_counter()
        if is_mock:
            # Deterministic evaluation simulator based on model tier parameters
            time.sleep(0.01)  # Simulated latency
            if "7b" in model_name.lower():
                raw_output = json.dumps({
                    "text": f"Prioritizing {expected_tool}",
                    "tool_calls": [{"name": expected_tool, "arguments": test.get("expected_args", {})}]
                })
                lat_ms = 185.0
            else:
                raw_output = json.dumps({
                    "text": f"Executing {expected_tool}",
                    "tool_calls": [{"name": expected_tool, "arguments": test.get("expected_args", {})}]
                })
                lat_ms = 95.0
        elif client_evaluator is not None:
            try:
                raw_output = client_evaluator(model_name, prompt)
                lat_ms = (time.perf_counter() - start_t) * 1000.0
            except Exception as e:
                raw_output = str(e)
                lat_ms = (time.perf_counter() - start_t) * 1000.0
        else:
            try:
                raw_output = default_ollama_evaluator(model_name, prompt)
                lat_ms = (time.perf_counter() - start_t) * 1000.0
            except Exception as e:
                raw_output = str(e)
                lat_ms = (time.perf_counter() - start_t) * 1000.0

        latencies.append(lat_ms)
        is_json, is_schema, is_acc, parsed_call = validate_model_response(raw_output, expected_tool)
        if is_json:
            valid_json_count += 1
        if is_schema:
            valid_schema_count += 1
        if is_acc:
            accurate_count += 1

        if samples_collector is not None:
            samples_collector.append({
                "model": model_name,
                "test_id": test.get("id", "unknown"),
                "prompt": prompt,
                "expected_tool": expected_tool,
                "raw_output": raw_output,
                "latency_ms": round(lat_ms, 2),
                "is_valid_json": is_json,
                "is_valid_tool_schema": is_schema,
                "is_accurate": is_acc,
                "parsed_call": parsed_call,
                "mock": is_mock
            })

    avg_latency = sum(latencies) / max(1, len(latencies))
    latencies_sorted = sorted(latencies)
    p95_idx = int(len(latencies_sorted) * 0.95)
    p95_latency = latencies_sorted[min(p95_idx, len(latencies_sorted) - 1)]

    return {
        "model": model_name,
        "samples": total_samples,
        "json_validity_pct": round((valid_json_count / total_samples) * 100, 1),
        "schema_compliance_pct": round((valid_schema_count / total_samples) * 100, 1),
        "milestone_accuracy_pct": round((accurate_count / total_samples) * 100, 1),
        "avg_latency_ms": round(avg_latency, 1),
        "p95_latency_ms": round(p95_latency, 1),
        "mock": is_mock
    }


def run_benchmark_suite(
    models: List[str],
    test_cases: List[Dict[str, Any]] = BENCHMARK_PROMPTS,
    is_mock: bool = False,
    client_evaluator=None,
    base_url: str = "http://localhost:11434",
    run_id: Optional[str] = None,
    base_dir: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], str]:
    """Executes benchmark across models and writes results.json & samples.jsonl to runs directory."""
    active_run_id = run_id or generate_run_id(prefix="benchmark")
    set_current_run_id(active_run_id)
    run_dir = get_run_directory(active_run_id, base_dir=base_dir)

    if not is_mock and client_evaluator is None:
        if not check_ollama_online(base_url):
            raise ConnectionError(
                f"Ollama server is offline or unreachable at {base_url}. "
                "Start Ollama or pass is_mock=True."
            )
        client_evaluator = lambda m, p: default_ollama_evaluator(m, p, base_url=base_url)

    all_samples: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []

    for m in models:
        res = benchmark_model(
            model_name=m,
            test_cases=test_cases,
            client_evaluator=client_evaluator,
            is_mock=is_mock,
            samples_collector=all_samples
        )
        results.append(res)

    # Persist results.json
    results_path = os.path.join(run_dir, "results.json")
    results_data = {
        "run_id": active_run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "commit_hash": get_git_commit_hash(short=False),
        "mock": is_mock,
        "models": models,
        "metrics": results
    }
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=2, ensure_ascii=False)

    # Persist samples.jsonl
    samples_path = os.path.join(run_dir, "samples.jsonl")
    with open(samples_path, "w", encoding="utf-8") as f:
        for sample in all_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    return results, run_dir


def format_markdown_table(results: List[Dict[str, Any]]) -> str:
    """Formats benchmark results into a clean markdown table."""
    lines = [
        "| Model | Samples | JSON Validity | Tool Schema Compliance | Decision Accuracy | Avg Latency | p95 Latency | Mock |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]
    for r in results:
        mock_tag = "Yes" if r.get("mock") else "No"
        lines.append(
            f"| **{r['model']}** | {r['samples']} | {r['json_validity_pct']}% | "
            f"{r['schema_compliance_pct']}% | {r['milestone_accuracy_pct']}% | "
            f"{r['avg_latency_ms']} ms | {r['p95_latency_ms']} ms | {mock_tag} |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Benchmark 3B vs 7B local LLM models on Minecraft decision scenarios.")
    parser.add_argument("--models", nargs="+", default=["qwen2.5:3b", "qwen2.5:7b"], help="Model names to evaluate")
    parser.add_argument("--mock", action="store_true", default=False, help="Use deterministic mock simulation if Ollama daemon is offline")
    parser.add_argument("--run-id", type=str, default="", help="Custom run identifier for results storage")
    args = parser.parse_args()

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Explicit offline check: Fail cleanly if Ollama is offline and --mock was NOT passed
    if not args.mock:
        if not check_ollama_online(base_url):
            print(f"❌ Error: Ollama server is offline or unreachable at {base_url}.")
            print("💡 Hint: Start Ollama with 'ollama serve' or pass '--mock' to execute deterministic benchmark simulation.")
            sys.exit(1)

    print(f"🚀 Running benchmark on models: {args.models} (Mock: {args.mock})...\n")

    run_id = args.run_id if args.run_id else None
    results, run_dir = run_benchmark_suite(
        models=args.models,
        test_cases=BENCHMARK_PROMPTS,
        is_mock=args.mock,
        base_url=base_url,
        run_id=run_id
    )

    table = format_markdown_table(results)
    print("## Benchmark Results\n")
    print(table)
    print(f"\n📁 Results saved to: {os.path.join(run_dir, 'results.json')}")
    print(f"📄 Sample decisions saved to: {os.path.join(run_dir, 'samples.jsonl')}")


if __name__ == "__main__":
    main()

