"""SFT Dataset Exporter & Curated Augmenter for Minecraft Autonomous Co-op AI.

Converts recorded in-game decisions (data/minecraft_decisions.jsonl) and speedrun milestone
knowledge into high-quality ChatML training datasets for Qwen 2.5 3B (Phase 5 -> Phase 6).
Generates clean, diverse samples (350+) ready for Unsloth 4-bit QLoRA fine-tuning.
"""

import os
import sys
import json
import random
import argparse
from typing import Dict, Any, List, Optional, Tuple

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from ai.prompts import build_system_prompt_for_ollama
from ai.progression_tree import get_current_progression_goal, resolve_missing_ingredients


def create_chatml_sample(system_prompt: str, user_content: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Formats a training sample into standard ChatML conversation format."""
    tool_call_text = json.dumps({"name": tool_name, "arguments": arguments}, ensure_ascii=False)
    assistant_content = f"<tool_call>\n{tool_call_text}\n</tool_call>"

    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content}
        ],
        "tool_call": {
            "name": tool_name,
            "arguments": arguments
        }
    }


def clean_and_curate_recorded_decisions(
    raw_records: List[Dict[str, Any]],
    bot_name: str = "AIAssistant",
    bot_owner: str = "Omer",
    include_test_runs: bool = False
) -> List[Dict[str, Any]]:
    """Cleans real game decisions, deduplicates stuck loops, and teacher-corrects known edge cases."""
    curated = []
    seen_signatures = {}

    for rec in raw_records:
        if not include_test_runs:
            run_id = rec.get("run_id", "")
            if rec.get("is_test", False) or (isinstance(run_id, str) and run_id.startswith("test_")):
                continue

        st = rec.get("state", {})
        ms = rec.get("milestone", {})
        dec = rec.get("decision", {})
        ex = rec.get("execution", {})

        cmd = dec.get("tool_name", "")
        args = dec.get("arguments", {})
        progress = ex.get("progress_made", False)
        edge = ex.get("is_edge_case", False)
        bridge_ok = ex.get("bridge_success", False)
        inv = st.get("inventory", {})

        # Teacher correction 1: collect_block("plank") -> collect_block("log")
        if cmd == "collect_block":
            bname = str(args.get("block_name", "")).lower()
            if "plank" in bname:
                cmd = "collect_block"
                args = {"block_name": "log", "count": args.get("count", 3)}
                progress = True

        # Teacher correction 2: craft_item("iron_ingot") -> smelt_item("raw_iron")
        if cmd == "craft_item" and args.get("item_name") in ("iron_ingot", "iron"):
            cmd = "smelt_item"
            args = {"input_item": "raw_iron", "count": args.get("count", 3)}
            progress = True

        # Teacher correction 3: wooden_pickaxe craft with cherry/other logs was valid decision
        if cmd == "craft_item" and args.get("item_name") == "wooden_pickaxe":
            has_wood = any("log" in k or "plank" in k for k in inv.keys())
            if has_wood:
                progress = True

        # Teacher correction 4: Skip unproductive repeated failures (e.g. repeated hunt failures)
        if cmd == "hunt_food" and not progress:
            # Keep at most 2 distinct starving hunt calls
            sig = f"hunt_food_failed"
            if seen_signatures.get(sig, 0) >= 2:
                continue
            seen_signatures[sig] = seen_signatures.get(sig, 0) + 1

        # Teacher correction 5: Skip pure idle calls in autonomous mode
        if cmd in ("list_saved_locations", "stop_actions") and not st.get("active_player_task"):
            continue

        # Keep samples that made progress or represent genuine edge cases (shelter, defense)
        if not progress and not edge:
            continue

        # Deduplicate identical action signatures in identical state
        target = ms.get("target", "unknown") if isinstance(ms, dict) else "unknown"
        args_key = json.dumps(args, sort_keys=True)
        sig_key = f"{target}:{cmd}:{args_key}"
        if seen_signatures.get(sig_key, 0) >= 3:
            continue
        seen_signatures[sig_key] = seen_signatures.get(sig_key, 0) + 1

        # Build reconstructed system prompt
        goal_dict = ms if isinstance(ms, dict) else {"target": str(ms), "stage": "early"}
        sys_prompt = build_system_prompt_for_ollama(
            state=st,
            bot_name=bot_name,
            bot_owner=bot_owner,
            goal=goal_dict,
            pro_tactic=None,
            active_task=st.get("active_player_task")
        )

        user_content = "[autonomous]: Decide next action."
        sample = create_chatml_sample(sys_prompt, user_content, cmd, args)
        curated.append(sample)

    return curated


def generate_speedrun_golden_samples(bot_name: str = "AIAssistant", bot_owner: str = "Omer", target_count: int = 350) -> List[Dict[str, Any]]:
    """Synthesizes canonical speedrun milestone samples covering the complete progression tree."""
    golden = []

    # Templates covering all critical vanilla speedrun milestones & tactical emergencies
    scenarios = [
        # --- 1. WOOD MILESTONE ---
        {
            "stage": "WOOD", "target": "wooden_pickaxe",
            "hp": 20, "food": 20, "dim": "overworld",
            "inv": {},
            "pos": {"x": 10, "y": 64, "z": -20}, "hostiles": [],
            "action": ("collect_block", {"block_name": "log", "count": 3}),
            "missing": ["3x wood log"]
        },
        {
            "stage": "WOOD", "target": "wooden_pickaxe",
            "hp": 19, "food": 18, "dim": "overworld",
            "inv": {"cherry_log": 4},
            "pos": {"x": 15, "y": 70, "z": -5}, "hostiles": [],
            "action": ("craft_item", {"item_name": "wooden_pickaxe", "count": 1}),
            "missing": []
        },
        {
            "stage": "WOOD", "target": "wooden_pickaxe",
            "hp": 20, "food": 19, "dim": "overworld",
            "inv": {"oak_log": 3, "stick": 2},
            "pos": {"x": -4, "y": 65, "z": 12}, "hostiles": [],
            "action": ("craft_item", {"item_name": "wooden_pickaxe", "count": 1}),
            "missing": []
        },
        {
            "stage": "WOOD", "target": "wooden_pickaxe",
            "hp": 18, "food": 17, "dim": "overworld",
            "inv": {"birch_log": 5, "crafting_table": 1},
            "pos": {"x": 22, "y": 66, "z": 80}, "hostiles": [],
            "action": ("craft_item", {"item_name": "wooden_pickaxe", "count": 1}),
            "missing": []
        },

        # --- 2. STONE MILESTONE ---
        {
            "stage": "STONE", "target": "stone_pickaxe",
            "hp": 20, "food": 18, "dim": "overworld",
            "inv": {"wooden_pickaxe": 1, "cherry_log": 3, "stick": 2},
            "pos": {"x": 5, "y": 60, "z": 14}, "hostiles": [],
            "action": ("collect_block", {"block_name": "stone", "count": 3}),
            "missing": ["3x cobblestone"]
        },
        {
            "stage": "STONE", "target": "stone_pickaxe",
            "hp": 20, "food": 17, "dim": "overworld",
            "inv": {"wooden_pickaxe": 1, "cobblestone": 3, "stick": 2},
            "pos": {"x": 6, "y": 58, "z": 15}, "hostiles": [],
            "action": ("craft_item", {"item_name": "stone_pickaxe", "count": 1}),
            "missing": []
        },
        {
            "stage": "STONE", "target": "stone_pickaxe",
            "hp": 19, "food": 16, "dim": "overworld",
            "inv": {"wooden_pickaxe": 1, "cobbled_deepslate": 4, "oak_log": 2},
            "pos": {"x": 0, "y": 0, "z": 10}, "hostiles": [],
            "action": ("craft_item", {"item_name": "stone_pickaxe", "count": 1}),
            "missing": []
        },

        # --- 3. FURNACE & DEFENSE ---
        {
            "stage": "FURNACE", "target": "furnace",
            "hp": 20, "food": 18, "dim": "overworld",
            "inv": {"stone_pickaxe": 1, "cobblestone": 2, "stick": 4},
            "pos": {"x": 12, "y": 55, "z": -30}, "hostiles": [],
            "action": ("collect_block", {"block_name": "stone", "count": 8}),
            "missing": ["6x cobblestone"]
        },
        {
            "stage": "FURNACE", "target": "furnace",
            "hp": 20, "food": 16, "dim": "overworld",
            "inv": {"stone_pickaxe": 1, "cobblestone": 8, "stick": 4, "oak_log": 2},
            "pos": {"x": 12, "y": 55, "z": -30}, "hostiles": [],
            "action": ("craft_item", {"item_name": "furnace", "count": 1}),
            "missing": []
        },
        {
            "stage": "FURNACE", "target": "shield",
            "hp": 20, "food": 16, "dim": "overworld",
            "inv": {"stone_pickaxe": 1, "iron_ingot": 1, "oak_log": 3},
            "pos": {"x": 10, "y": 50, "z": -25}, "hostiles": [],
            "action": ("craft_item", {"item_name": "shield", "count": 1}),
            "missing": []
        },

        # --- 4. IRON GEAR & SMELTING ---
        {
            "stage": "IRON_GEAR", "target": "iron_pickaxe",
            "hp": 20, "food": 16, "dim": "overworld",
            "inv": {"stone_pickaxe": 1, "furnace": 1, "cobblestone": 12},
            "pos": {"x": 25, "y": 32, "z": -40}, "hostiles": [],
            "action": ("collect_block", {"block_name": "iron", "count": 3}),
            "missing": ["3x iron ingot"]
        },
        {
            "stage": "IRON_GEAR", "target": "iron_pickaxe",
            "hp": 20, "food": 15, "dim": "overworld",
            "inv": {"stone_pickaxe": 1, "raw_iron": 3, "coal": 4, "furnace": 1},
            "pos": {"x": 28, "y": 30, "z": -45}, "hostiles": [],
            "action": ("smelt_item", {"input_item": "raw_iron", "count": 3}),
            "missing": ["3x iron ingot"]
        },
        {
            "stage": "IRON_GEAR", "target": "iron_pickaxe",
            "hp": 20, "food": 15, "dim": "overworld",
            "inv": {"stone_pickaxe": 1, "raw_iron": 4, "oak_log": 5, "furnace": 1},
            "pos": {"x": 30, "y": 28, "z": -50}, "hostiles": [],
            "action": ("smelt_item", {"input_item": "raw_iron", "count": 3}),
            "missing": ["3x iron ingot"]
        },
        {
            "stage": "IRON_GEAR", "target": "iron_pickaxe",
            "hp": 20, "food": 14, "dim": "overworld",
            "inv": {"stone_pickaxe": 1, "iron_ingot": 3, "stick": 4, "shield": 1},
            "pos": {"x": 28, "y": 30, "z": -45}, "hostiles": [],
            "action": ("craft_item", {"item_name": "iron_pickaxe", "count": 1}),
            "missing": []
        },
        {
            "stage": "IRON_GEAR", "target": "iron_sword",
            "hp": 20, "food": 14, "dim": "overworld",
            "inv": {"iron_pickaxe": 1, "iron_ingot": 2, "stick": 2, "shield": 1},
            "pos": {"x": 28, "y": 30, "z": -45}, "hostiles": [],
            "action": ("craft_item", {"item_name": "iron_sword", "count": 1}),
            "missing": []
        },
        {
            "stage": "IRON_GEAR", "target": "bucket",
            "hp": 20, "food": 14, "dim": "overworld",
            "inv": {"iron_pickaxe": 1, "iron_ingot": 3, "iron_sword": 1},
            "pos": {"x": 28, "y": 30, "z": -45}, "hostiles": [],
            "action": ("craft_item", {"item_name": "bucket", "count": 1}),
            "missing": []
        },

        # --- 5. DIAMOND MILESTONE ---
        {
            "stage": "DIAMOND", "target": "diamond_pickaxe",
            "hp": 20, "food": 16, "dim": "overworld",
            "inv": {"iron_pickaxe": 1, "iron_sword": 1, "shield": 1, "torch": 16},
            "pos": {"x": 100, "y": -58, "z": 240}, "hostiles": [],
            "action": ("collect_block", {"block_name": "diamond", "count": 3}),
            "missing": ["3x diamond"]
        },
        {
            "stage": "DIAMOND", "target": "diamond_pickaxe",
            "hp": 20, "food": 15, "dim": "overworld",
            "inv": {"iron_pickaxe": 1, "diamond": 3, "stick": 4, "shield": 1},
            "pos": {"x": 105, "y": -58, "z": 242}, "hostiles": [],
            "action": ("craft_item", {"item_name": "diamond_pickaxe", "count": 1}),
            "missing": []
        },
        {
            "stage": "DIAMOND", "target": "diamond_sword",
            "hp": 20, "food": 15, "dim": "overworld",
            "inv": {"diamond_pickaxe": 1, "diamond": 2, "stick": 2},
            "pos": {"x": 105, "y": -58, "z": 242}, "hostiles": [],
            "action": ("craft_item", {"item_name": "diamond_sword", "count": 1}),
            "missing": []
        },

        # --- 6. NETHER PORTAL & EXPLORATION ---
        {
            "stage": "NETHER", "target": "nether_portal",
            "hp": 20, "food": 16, "dim": "overworld",
            "inv": {"diamond_pickaxe": 1, "water_bucket": 1, "shield": 1},
            "pos": {"x": 50, "y": 64, "z": 12}, "hostiles": [],
            "action": ("collect_block", {"block_name": "obsidian", "count": 10}),
            "missing": ["10x obsidian"]
        },
        {
            "stage": "NETHER", "target": "nether_portal",
            "hp": 20, "food": 16, "dim": "overworld",
            "inv": {"diamond_pickaxe": 1, "obsidian": 10, "flint_and_steel": 1},
            "pos": {"x": 52, "y": 64, "z": 15}, "hostiles": [],
            "action": ("build_nether_portal", {}),
            "missing": []
        },
        {
            "stage": "NETHER", "target": "nether_portal",
            "hp": 18, "food": 15, "dim": "the_nether",
            "inv": {"diamond_pickaxe": 1, "iron_sword": 1, "shield": 1},
            "pos": {"x": 120, "y": 72, "z": 40}, "hostiles": ["blaze (12m away)"],
            "action": ("attack_target", {"target_name": "blaze"}),
            "missing": ["6x blaze rod"]
        },
        {
            "stage": "NETHER", "target": "nether_portal",
            "hp": 20, "food": 16, "dim": "the_nether",
            "inv": {"diamond_pickaxe": 1, "cobblestone": 32, "iron_sword": 1},
            "pos": {"x": 90, "y": 65, "z": 10}, "hostiles": [],
            "action": ("build_nether_outpost", {"wall_material": "auto"}),
            "missing": []
        },

        # --- 7. EYE OF ENDER & STRONGHOLD ---
        {
            "stage": "EYE_OF_ENDER", "target": "eye_of_ender",
            "hp": 20, "food": 17, "dim": "overworld",
            "inv": {"diamond_pickaxe": 1, "blaze_rod": 6, "ender_pearl": 12},
            "pos": {"x": 50, "y": 64, "z": 12}, "hostiles": [],
            "action": ("craft_item", {"item_name": "blaze_powder", "count": 12}),
            "missing": []
        },
        {
            "stage": "EYE_OF_ENDER", "target": "eye_of_ender",
            "hp": 20, "food": 17, "dim": "overworld",
            "inv": {"diamond_pickaxe": 1, "blaze_powder": 12, "ender_pearl": 12},
            "pos": {"x": 50, "y": 64, "z": 12}, "hostiles": [],
            "action": ("craft_item", {"item_name": "eye_of_ender", "count": 12}),
            "missing": []
        },
        {
            "stage": "EYE_OF_ENDER", "target": "eye_of_ender",
            "hp": 20, "food": 16, "dim": "overworld",
            "inv": {"diamond_pickaxe": 1, "eye_of_ender": 12, "diamond_sword": 1},
            "pos": {"x": 150, "y": 68, "z": 400}, "hostiles": [],
            "action": ("throw_eye_of_ender", {}),
            "missing": []
        },
        {
            "stage": "THE_END", "target": "ender_dragon",
            "hp": 20, "food": 18, "dim": "overworld",
            "inv": {"diamond_pickaxe": 1, "eye_of_ender": 4, "diamond_sword": 1},
            "pos": {"x": 1240, "y": 32, "z": -820}, "hostiles": [],
            "action": ("activate_end_portal", {}),
            "missing": []
        },

        # --- 8. END FIGHT & VICTORY ---
        {
            "stage": "DESTROY_CRYSTALS", "target": "end_crystal",
            "hp": 20, "food": 18, "dim": "the_end",
            "inv": {"diamond_pickaxe": 1, "bow": 1, "arrow": 64, "water_bucket": 1},
            "pos": {"x": 20, "y": 60, "z": 15}, "hostiles": ["ender_dragon (45m away)"],
            "action": ("destroy_end_crystals", {}),
            "missing": []
        },
        {
            "stage": "SLAY_DRAGON", "target": "fight_ender_dragon",
            "hp": 18, "food": 16, "dim": "the_end",
            "inv": {"diamond_sword": 1, "shield": 1, "cooked_beef": 16},
            "pos": {"x": 0, "y": 65, "z": 0}, "hostiles": ["ender_dragon (8m away)"],
            "action": ("fight_ender_dragon", {"tactic": "melee_sword"}),
            "missing": []
        },
        {
            "stage": "GAME_VICTORY", "target": "enter_exit_portal",
            "hp": 20, "food": 18, "dim": "the_end",
            "inv": {"diamond_sword": 1, "dragon_egg": 1},
            "pos": {"x": 2, "y": 65, "z": 1}, "hostiles": [],
            "action": ("enter_exit_portal", {}),
            "missing": []
        },

        # --- 9. SURVIVAL EMERGENCIES & TACTICS ---
        {
            "stage": "SURVIVAL", "target": "eat_food",
            "hp": 14, "food": 3, "dim": "overworld",
            "inv": {"cooked_beef": 5, "stone_pickaxe": 1},
            "pos": {"x": 10, "y": 64, "z": 20}, "hostiles": [],
            "action": ("eat_food", {}),
            "missing": []
        },
        {
            "stage": "SURVIVAL", "target": "hunt_food",
            "hp": 15, "food": 3, "dim": "overworld",
            "inv": {"stone_pickaxe": 1, "dirt": 10},
            "pos": {"x": 12, "y": 65, "z": 22}, "hostiles": [],
            "action": ("hunt_food", {"animal_type": "cow"}),
            "missing": []
        },
        {
            "stage": "SURVIVAL", "target": "build_shelter",
            "hp": 5, "food": 8, "dim": "overworld",
            "inv": {"dirt": 24, "stone_pickaxe": 1},
            "pos": {"x": 40, "y": 68, "z": -10}, "hostiles": ["skeleton (10m away)", "creeper (8m away)"],
            "action": ("build_shelter", {"mode": "auto"}),
            "missing": []
        },
        {
            "stage": "SURVIVAL", "target": "sleep_in_bed",
            "hp": 16, "food": 14, "dim": "overworld",
            "inv": {"bed": 1, "stone_pickaxe": 1},
            "pos": {"x": 5, "y": 64, "z": 5}, "hostiles": [],
            "action": ("sleep_in_bed", {}),
            "missing": []
        },
        {
            "stage": "SURVIVAL", "target": "attack_target",
            "hp": 18, "food": 15, "dim": "overworld",
            "inv": {"iron_sword": 1, "shield": 1},
            "pos": {"x": 2, "y": 64, "z": 2}, "hostiles": ["zombie (2m away)"],
            "action": ("attack_target", {"target_name": "zombie"}),
            "missing": []
        },
        {
            "stage": "SURVIVAL", "target": "break_out_shelter",
            "hp": 20, "food": 18, "dim": "overworld",
            "inv": {"dirt": 12, "stone_pickaxe": 1},
            "pos": {"x": 40, "y": 68, "z": -10}, "hostiles": [],
            "action": ("break_out_shelter", {}),
            "missing": []
        },

        # --- 10. TEAMMATE COOPERATION (CHAT REQUESTS) ---
        {
            "stage": "COOP", "target": "follow_player",
            "hp": 20, "food": 18, "dim": "overworld",
            "inv": {"stone_pickaxe": 1},
            "pos": {"x": 10, "y": 64, "z": 20}, "hostiles": [],
            "user_chat": f"[{bot_owner}]: come to me",
            "task": {"instruction": "follow Omer"},
            "action": ("follow_player", {"player_name": bot_owner}),
            "missing": []
        },
        {
            "stage": "COOP", "target": "give_item_to_player",
            "hp": 20, "food": 18, "dim": "overworld",
            "inv": {"oak_log": 12, "stone_pickaxe": 1},
            "pos": {"x": 11, "y": 64, "z": 21}, "hostiles": [],
            "user_chat": f"[{bot_owner}]: give me 5 logs",
            "task": {"instruction": "give 5 log to Omer"},
            "action": ("give_item_to_player", {"player_name": bot_owner, "item_name": "oak_log", "count": 5}),
            "missing": []
        },
        {
            "stage": "COOP", "target": "guard_player",
            "hp": 20, "food": 18, "dim": "overworld",
            "inv": {"iron_sword": 1, "shield": 1},
            "pos": {"x": 12, "y": 64, "z": 22}, "hostiles": ["zombie (14m away)"],
            "user_chat": f"[{bot_owner}]: protect me",
            "task": {"instruction": "guard Omer"},
            "action": ("guard_player", {"player_name": bot_owner}),
            "missing": []
        }
    ]

    # Generate synthetic diverse variations by varying coordinates, inventories, and species
    wood_species = ["oak", "birch", "spruce", "dark_oak", "cherry", "acacia", "mangrove"]
    repeat_needed = max(1, target_count // len(scenarios) + 1)

    for i in range(repeat_needed):
        for sc in scenarios:
            if len(golden) >= target_count:
                break

            species = wood_species[i % len(wood_species)]
            inv_copy = {}
            for k, v in sc["inv"].items():
                if "log" in k:
                    inv_copy[f"{species}_log"] = v
                else:
                    inv_copy[k] = v

            # Perturb position slightly
            px = sc["pos"]["x"] + random.randint(-15, 15)
            py = max(-60, min(120, sc["pos"]["y"] + random.randint(-2, 2)))
            pz = sc["pos"]["z"] + random.randint(-15, 15)

            st = {
                "health": max(1, min(20, sc["hp"] + random.choice([-1, 0, 1]))),
                "food": max(1, min(20, sc["food"] + random.choice([-1, 0, 1]))),
                "dimension": sc["dim"],
                "position": {"x": px, "y": py, "z": pz},
                "inventory": inv_copy,
                "inventory_items": [{"name": k, "count": v} for k, v in inv_copy.items()],
                "nearby_hostiles": sc["hostiles"],
                "carried_tools": ", ".join(k for k in inv_copy if any(w in k for w in ("pickaxe", "sword", "shield", "bow"))) or "None",
                "missing_ingredients": sc["missing"],
                "goal_stage": sc["stage"],
                "goal_target": sc["target"]
            }

            goal_dict = {
                "stage": sc["stage"],
                "target": sc["target"],
                "next_hint": f"Advance towards {sc['target']}"
            }

            sys_prompt = build_system_prompt_for_ollama(
                state=st,
                bot_name=bot_name,
                bot_owner=bot_owner,
                goal=goal_dict,
                pro_tactic=None,
                active_task=sc.get("task")
            )

            user_msg = sc.get("user_chat") or "[autonomous]: Decide next action."
            tool_name, tool_args = sc["action"]
            sample = create_chatml_sample(sys_prompt, user_msg, tool_name, tool_args)
            golden.append(sample)

    return golden


def export_sft_dataset(
    input_path: str = "data/minecraft_decisions.jsonl",
    train_output: str = "data/sft_train.jsonl",
    val_output: str = "data/sft_val.jsonl",
    target_count: int = 350,
    val_ratio: float = 0.1,
    seed: int = 42,
    include_test_runs: bool = False
) -> Tuple[int, int]:
    """Orchestrates dataset loading, cleaning, golden synthesis, splitting, and saving."""
    random.seed(seed)
    raw_records = []

    if os.path.exists(input_path):
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        record = json.loads(line)
                        if not include_test_runs:
                            run_id = record.get("run_id", "")
                            if record.get("is_test", False) or (isinstance(run_id, str) and run_id.startswith("test_")):
                                continue
                        raw_records.append(record)
                    except Exception:
                        pass
        print(f"📖 Loaded {len(raw_records)} recorded in-game decisions from {input_path}")
    else:
        print(f"ℹ️ No recorded decisions found at {input_path}. Proceeding with golden synthesis.")

    # 1. Clean recorded samples
    curated_records = clean_and_curate_recorded_decisions(raw_records, include_test_runs=include_test_runs)
    print(f"✨ Cleaned & curated {len(curated_records)} high-quality in-game samples.")

    # 2. Golden speedrun augmentation to reach target dataset depth
    remaining_needed = max(0, target_count - len(curated_records))
    golden_samples = generate_speedrun_golden_samples(target_count=remaining_needed)
    print(f"🌟 Synthesized {len(golden_samples)} canonical golden speedrun milestone samples.")

    # 3. Combine and shuffle
    all_samples = curated_records + golden_samples
    random.shuffle(all_samples)
    print(f"📦 Total dataset size: {len(all_samples)} samples.")

    # 4. Train / Val split
    val_size = max(1, int(len(all_samples) * val_ratio))
    val_samples = all_samples[:val_size]
    train_samples = all_samples[val_size:]

    # 5. Write outputs
    os.makedirs(os.path.dirname(train_output) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(val_output) or ".", exist_ok=True)

    with open(train_output, "w", encoding="utf-8") as f:
        for s in train_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    with open(val_output, "w", encoding="utf-8") as f:
        for s in val_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"✅ Train dataset saved to: {train_output} ({len(train_samples)} samples)")
    print(f"✅ Val dataset saved to:   {val_output} ({len(val_samples)} samples)")

    # 6. Tool distribution summary
    tool_counts = {}
    for s in all_samples:
        tc = s.get("tool_call", {}).get("name", "unknown")
        tool_counts[tc] = tool_counts.get(tc, 0) + 1

    print("\n📊 Dataset Tool Distribution:")
    for t_name, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
        pct = (count / len(all_samples)) * 100
        print(f"  • {t_name:24s}: {count:3d} ({pct:4.1f}%)")

    return len(train_samples), len(val_samples)


def main():
    parser = argparse.ArgumentParser(description="Export curated SFT dataset for Qwen 2.5 3B.")
    parser.add_argument("--input", default="data/minecraft_decisions.jsonl", help="Input decision log path")
    parser.add_argument("--output-train", default="data/sft_train.jsonl", help="Output train jsonl path")
    parser.add_argument("--output-val", default="data/sft_val.jsonl", help="Output val jsonl path")
    parser.add_argument("--min-samples", type=int, default=350, help="Target minimum sample count")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation ratio (default 0.1)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--include-test-runs", action="store_true", help="Include records from test runs in training data")

    args = parser.parse_args()

    export_sft_dataset(
        input_path=args.input,
        train_output=args.output_train,
        val_output=args.output_val,
        target_count=args.min_samples,
        val_ratio=args.val_ratio,
        seed=args.seed,
        include_test_runs=args.include_test_runs
    )


if __name__ == "__main__":
    main()
