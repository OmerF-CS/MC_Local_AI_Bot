"""Minecraft AI System Prompt - Ultra-compact Qwen 2.5 3B optimized format."""
import re
from typing import Dict, Any, List, Optional

MINECRAFT_SYSTEM_PROMPT = """You are {bot_name}, an autonomous Minecraft survival speedrunner.
Your owner/spectator is {bot_owner}.
Goal: Defeat Ender Dragon. Make EXACTLY ONE tool call per cycle.
You play 100% autonomously on your own. Do NOT follow {bot_owner} unless explicitly asked in chat.

CORE RULES:
- Starving (Food<4) -> eat_food or hunt_food
- Low HP (<6) + hostiles -> attack_target or build_shelter
- Night or low health + mobs -> sleep_in_bed or build_shelter
- Progress gear towards Target using Missing materials
- Mine resources, craft items, smelt ores, and progress completely independently
- NEVER call craft_item if missing raw ingredients. Mine or smelt first.
- In autonomous mode, NEVER call give_item_to_player. Keep all items for yourself.
- NEVER call craft_item for iron_ingot or gold_ingot. Smelt them in furnace using smelt_item.

EXAMPLES:
Target: wooden_pickaxe | Missing: 3 oak_log -> collect_block(block_name="oak_log", count=3)
Target: furnace | Missing: 8 cobblestone -> collect_block(block_name="stone", count=8)
Target: iron_pickaxe | Missing: 3 iron_ingot (0 iron) -> collect_block(block_name="iron", count=3)
Target: iron_pickaxe | Missing: 3 iron_ingot (have raw_iron) -> smelt_item(input_item="raw_iron", count=3)
Target: iron_pickaxe | Missing: Ready to craft! -> craft_item(item_name="iron_pickaxe", count=1)

STATUS:
- HP: {health}/20 | Food: {food}/20 | Dim: {dimension} | Pos: {position}
- Target: {goal_target} ({goal_stage}) | Missing: {goal_missing}
- Tools: {carried_tools} | Hostiles: {nearby_entities}
- Mission: {active_task_header}"""


def build_system_prompt_for_ollama(state, bot_name, bot_owner, goal, pro_tactic, active_task):
    """Build ultra-compact system prompt with dynamic state injection."""
    if not state:
        state = {}

    health = state.get("health", 20)
    food = state.get("food", 20)
    pos = state.get("position", {})
    pos_str = f"({pos.get('x', 0):.0f}, {pos.get('y', 0):.0f}, {pos.get('z', 0):.0f})"
    dimension = state.get("dimension", "overworld")

    nearby_entities = (
        state.get("nearby_entities_summary") or
        ", ".join(state.get("nearby_hostiles", [])) or
        "None"
    )

    owner_info = state.get("owner_info")
    if owner_info:
        dist = owner_info.get("distance", 0)
        owner_summary = f"{bot_owner} {dist}m away"
    else:
        owner_summary = f"{bot_owner} out of sight"

    carried_tools = state.get("carried_tools", "None")
    goal_stage = goal.get("stage", "early") if goal else "early"
    goal_target = goal.get("target", "wooden_pickaxe") if goal else "wooden_pickaxe"

    missing = state.get("missing_ingredients", [])
    if isinstance(missing, list):
        goal_missing = ", ".join(missing) if missing else "Ready to craft!"
    else:
        goal_missing = str(missing)

    if active_task:
        active_task_header = f"'{active_task.get('instruction')}'"
    elif state.get("active_player_task"):
        active_task_header = f"'{state['active_player_task'].get('instruction')}'"
    else:
        active_task_header = "None (Autonomous)"

    base_prompt = MINECRAFT_SYSTEM_PROMPT.format(
        bot_name=bot_name,
        bot_owner=bot_owner,
        health=health,
        food=food,
        dimension=dimension,
        position=pos_str,
        goal_stage=goal_stage,
        goal_target=goal_target,
        goal_missing=goal_missing,
        carried_tools=carried_tools,
        nearby_entities=nearby_entities,
        owner_summary=owner_summary,
        active_task_header=active_task_header
    )

    # Dynamic contextual extensions: affordances, recent actions, and learned lessons
    extra_context_lines = []
    if state.get("affordances_summary"):
        extra_context_lines.append(f"AFFORDANCES: {state['affordances_summary']}")
    if state.get("recent_actions_summary"):
        extra_context_lines.append(f"RECENT ACTIONS: {state['recent_actions_summary']}")
    if state.get("learned_lessons_summary"):
        extra_context_lines.append(f"MEMORY LESSONS: {state['learned_lessons_summary']}")

    if extra_context_lines:
        base_prompt = base_prompt + "\n\nCONTEXT:\n" + "\n".join(extra_context_lines)

    return base_prompt


def _truncate_entities_sensory(state: Dict[str, Any]) -> str:
    """Extracts and truncates nearby entities to max 3 closest in compact format."""
    # 1. Structured list of entity dicts
    entities = state.get("nearby_entities")
    if isinstance(entities, list) and entities:
        def get_dist(e):
            if isinstance(e, dict):
                return e.get("distance", 999.0)
            return 999.0
        sorted_ents = sorted(entities, key=get_dist)
        items = []
        for e in sorted_ents[:3]:
            if isinstance(e, dict):
                name = e.get("name", "mob")
                dist = e.get("distance")
                if dist is not None:
                    items.append(f"{name}({int(round(dist))}m)")
                else:
                    items.append(str(name))
            else:
                items.append(str(e))
        return ", ".join(items) if items else "none"

    # 2. String summary in state
    summary = state.get("nearby_entities_summary")
    if summary and isinstance(summary, str) and summary.strip():
        parts = [p.strip() for p in summary.split(",") if p.strip()]
        if len(parts) > 3:
            return ", ".join(parts[:3])
        return summary.strip()

    # 3. Hostiles & passives list
    hostiles = state.get("nearby_hostiles") or []
    passives = state.get("nearby_passives") or []
    combined = list(hostiles) + list(passives)
    if combined:
        items = []
        for e in combined[:3]:
            if isinstance(e, dict):
                name = e.get("name", "mob")
                dist = e.get("distance")
                if dist is not None:
                    items.append(f"{name}({int(round(dist))}m)")
                else:
                    items.append(str(name))
            elif isinstance(e, str):
                m = re.match(r"^([a-zA-Z0-9_]+)\s*\(([\d\.]+)m.*?\)", e.strip())
                if m:
                    items.append(f"{m.group(1)}({int(round(float(m.group(2))))}m)")
                else:
                    items.append(e.strip())
            else:
                items.append(str(e))
        return ", ".join(items) if items else "none"

    return "none"


def _truncate_blocks_sensory(state: Dict[str, Any]) -> str:
    """Extracts and truncates nearby relevant blocks to max 4 closest."""
    # 1. Structured list of block dicts
    blocks = state.get("nearby_blocks")
    if isinstance(blocks, list) and blocks:
        def get_dist(b):
            if isinstance(b, dict):
                return b.get("distance", 999.0)
            return 999.0
        sorted_blocks = sorted(blocks, key=get_dist)
        items = []
        for b in sorted_blocks[:4]:
            if isinstance(b, dict):
                name = b.get("name", "block")
                dist = b.get("distance")
                if dist is not None:
                    items.append(f"{name}({int(round(dist))}m)")
                else:
                    items.append(str(name))
            elif isinstance(b, str):
                m = re.match(r"^([a-zA-Z0-9_]+)\s*\(([\d\.]+)m.*?\)", b.strip())
                if m:
                    items.append(f"{m.group(1)}({int(round(float(m.group(2))))}m)")
                else:
                    items.append(b.strip())
            else:
                items.append(str(b))
        return ", ".join(items) if items else "none"

    # 2. String summary in state
    summary = state.get("nearby_blocks_summary")
    if summary and isinstance(summary, str) and summary.strip():
        parts = [p.strip() for p in summary.split(",") if p.strip()]
        if len(parts) > 4:
            return ", ".join(parts[:4])
        return summary.strip()

    # 3. Visible resources dict
    vis = state.get("visible_resources")
    if isinstance(vis, dict) and vis:
        items = []
        for k, v in list(vis.items())[:4]:
            if isinstance(v, dict) and "closest_distance" in v:
                items.append(f"{k}({int(round(v['closest_distance']))}m)")
            else:
                items.append(f"{k}:{v}")
        return ", ".join(items) if items else "none"

    return "none"


def build_cortex_sensory_prompt(
    state: Optional[Dict[str, Any]] = None,
    inv_dict: Optional[Dict[str, int]] = None,
    alerts: Optional[List[str]] = None,
    affordances_summary: str = "",
    opportunities: Optional[List[str]] = None,
    style: str = "speedrunner",
    recent_actions: str = "",
    lessons: Optional[List[str]] = None,
    goal: Optional[Dict[str, Any]] = None,
    missing_ingredients: Optional[List[str]] = None,
    feasible_actions: Optional[List[str]] = None,
    scenario: Optional[Any] = None
) -> str:
    """Constructs ultra-compact (<160 words, ~180 tokens) sensory perception text for Cognitive Cortex.

    Format:
    [STATE] HP:{hp}/20 | Food:{food}/20 | Light:{light} ({day_phase}) | Pos:({x},{y},{z}) | Biome:{biome}
    [INV] {compact_inventory_string}
    [AFFORD] {affordances_summary}
    [PERCEPTION] Mobs: {mobs} | Blocks: {blocks}
    [ALERTS] {alerts_string}
    [OPPORTUNITIES] {opportunities_string}
    [GOAL] Target: {target} | Need: {missing} (if goal provided)
    [FEASIBLE] {feasible_actions} (if feasible_actions provided)
    [STYLE] {style}
    [RECENT] {recent_actions}
    [LESSONS] {lessons_string}
    """
    if not state:
        state = {}
    if inv_dict is None:
        inv_dict = {}
    if alerts is None:
        alerts = []
    if opportunities is None:
        opportunities = []
    if lessons is None:
        lessons = []

    # Health & Food
    hp = state.get("health", 20)
    if isinstance(hp, float) and hp.is_integer():
        hp = int(hp)
    food = state.get("food", 20)
    if isinstance(food, float) and food.is_integer():
        food = int(food)

    # Light & Day phase
    light = state.get("light_level", state.get("light", 15))
    day_phase = state.get("day_phase")
    if not day_phase:
        time_of_day = state.get("time_of_day")
        if time_of_day:
            day_phase = str(time_of_day).capitalize()
        else:
            is_day = state.get("is_day", True)
            day_phase = "Day" if is_day else "Night"

    # Coordinates
    pos = state.get("position", {})
    x = round(pos.get("x", 0))
    y = round(pos.get("y", 0))
    z = round(pos.get("z", 0))

    biome = state.get("biome", "plains")

    # Compact Inventory String (non-zero items only)
    if inv_dict:
        nonzero_items = [f"{k}:{v}" for k, v in inv_dict.items() if isinstance(v, (int, float)) and v > 0]
        inv_str = ", ".join(nonzero_items) if nonzero_items else "empty"
    else:
        inv_str = "empty"

    # Affordances
    afford_str = affordances_summary.strip() if affordances_summary else "none"

    # Perception: Mobs (max 3) & Blocks (max 4)
    mobs = _truncate_entities_sensory(state)
    blocks = _truncate_blocks_sensory(state)

    # Alerts & Opportunities (bounded to avoid bloat)
    alerts_str = "; ".join(alerts[:3]) if alerts else "none"
    opps_str = "; ".join(opportunities[:2]) if opportunities else "none"

    # Sanitize lessons: filter out generic "unknown hazard" / "awareness" boilerplate
    generic_lesson_patterns = (
        "unknown hazard",
        "exercise heightened situational awareness",
        "heightened situational awareness"
    )
    sanitized_lessons = []
    raw_lessons = lessons if isinstance(lessons, list) else ([str(lessons)] if lessons else [])
    for l in raw_lessons:
        l_str = str(l).strip()
        if not l_str:
            continue
        l_lower = l_str.lower()
        if any(pat in l_lower for pat in generic_lesson_patterns):
            continue
        if l_str not in sanitized_lessons:
            sanitized_lessons.append(l_str)
        if len(sanitized_lessons) >= 2:
            break

    lessons_str = "; ".join(sanitized_lessons) if sanitized_lessons else "none"

    # Style & Recent actions
    style_str = style or "speedrunner"
    recent_str = recent_actions.strip() if recent_actions else "none"

    prompt_lines = [
        f"[STATE] HP:{hp}/20 | Food:{food}/20 | Light:{light} ({day_phase}) | Pos:({x},{y},{z}) | Biome:{biome}",
        f"[INV] {inv_str}",
        f"[AFFORD] {afford_str}",
        f"[PERCEPTION] Mobs: {mobs} | Blocks: {blocks}",
        f"[ALERTS] {alerts_str}",
    ]

    if scenario:
        if hasattr(scenario, "format_prompt_line"):
            prompt_lines.append(scenario.format_prompt_line())
        else:
            prompt_lines.append(f"[SCENARIO] {str(scenario)}")

    prompt_lines.append(f"[OPPORTUNITIES] {opps_str}")

    # Goal line if goal present
    if goal:
        target_name = goal.get("target", "wooden_pickaxe") if isinstance(goal, dict) else str(goal)
        if missing_ingredients is not None:
            if isinstance(missing_ingredients, list):
                missing_str = ", ".join(missing_ingredients) if missing_ingredients else "Ready to craft!"
            else:
                missing_str = str(missing_ingredients)
        elif isinstance(goal, dict) and goal.get("missing"):
            m = goal.get("missing")
            missing_str = ", ".join(m) if isinstance(m, list) else str(m)
        elif state and state.get("missing_ingredients"):
            m = state.get("missing_ingredients")
            missing_str = ", ".join(m) if isinstance(m, list) else str(m)
        else:
            missing_str = "Ready to craft!"
        prompt_lines.append(f"[GOAL] Target: {target_name} | Need: {missing_str}")

    # Feasible actions line if feasible_actions present
    if feasible_actions:
        prompt_lines.append(f"[FEASIBLE] {', '.join(feasible_actions)}")

    prompt_lines.extend([
        f"[STYLE] {style_str}",
        f"[RECENT] {recent_str}",
        f"[LESSONS] {lessons_str}"
    ])

    result = "\n".join(prompt_lines)

    # Hard safety bound: ensure strictly under 160 words
    words = result.split()
    if len(words) >= 160:
        result = " ".join(words[:155])

    return result
