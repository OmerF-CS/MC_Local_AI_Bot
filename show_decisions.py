"""CLI tool to display recorded Minecraft AI decisions in markdown table format."""

import os
import sys
import json
import argparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def format_table(limit: int = 15):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(base_dir, "data", "minecraft_decisions.jsonl")

    if not os.path.exists(log_file):
        print(f"⚠️ No recorded decision log found at: {log_file}")
        print("Run the bot with 'python main.py' and execute actions in-game, then try again.")
        return

    records = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue

    if not records:
        print(f"ℹ️ {log_file} is currently empty.")
        return

    selected = records[-limit:] if limit > 0 else records
    start_no = len(records) - len(selected) + 1

    print(f"\n📊 Total Recorded Decisions: {len(records)} | Displaying: Last {len(selected)} Decisions\n")
    print("| decision_no | state_summary | model_output | inventory_delta | success | error_type |")
    print("|:---:|:---|:---|:---|:---:|:---|")

    errors_count = 0
    progress_count = 0

    for idx, rec in enumerate(selected, start=start_no):
        st = rec.get("state", {})
        ms = rec.get("milestone", {})
        dec = rec.get("decision", {})
        ex = rec.get("execution", {})

        # 1. State summary
        hp = st.get("health", "?")
        food = st.get("food", "?")
        target = ms.get("target", "?")
        state_summary = f"HP:{hp} Food:{food} Target:{target}"

        # 2. Model output
        tool_name = dec.get("tool_name", "?")
        args = dec.get("arguments", {})
        args_str = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
        model_output = f"`{tool_name}({args_str})`"

        # 3. Inventory delta
        delta = ex.get("inventory_delta", {})
        if delta:
            delta_str = ", ".join(f"{k} {'+' if v > 0 else ''}{v}" for k, v in delta.items())
        else:
            delta_str = "No Change"

        # 4. Success / Progress status
        progress = ex.get("progress_made", False)
        bridge_ok = ex.get("bridge_success", False)
        if progress:
            success_str = "✅ Yes"
            progress_count += 1
        elif bridge_ok:
            success_str = "⚠️ Ineffective"
        else:
            success_str = "❌ No"
            errors_count += 1

        # 5. Error classification
        err = ex.get("error")
        if not err:
            if not progress and bridge_ok:
                error_type = "No Progress (Inventory unchanged)"
            elif not progress and not bridge_ok:
                error_type = "Action Failed"
            else:
                error_type = "-"
        else:
            err_lower = str(err).lower()
            if "parameter" in err_lower or "missing" in err_lower or "invalid argument" in err_lower:
                error_type = f"Parameter Error ({err[:40]})"
            elif "craft" in err_lower or "recipe" in err_lower:
                error_type = f"Crafting Error ({err[:40]})"
            else:
                error_type = f"{err[:40]}"

        print(f"| {idx} | {state_summary} | {model_output} | {delta_str} | {success_str} | {error_type} |")

    success_pct = (progress_count / len(selected)) * 100 if selected else 0
    print(f"\n📈 Success Rate: {success_pct:.1f}% ({progress_count}/{len(selected)}) | Ineffective / Errors: {len(selected) - progress_count}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minecraft Autonomous Decision Log Formatter")
    parser.add_argument("--limit", type=int, default=15, help="Number of recent decisions to display (default: 15)")
    args = parser.parse_args()
    format_table(args.limit)
