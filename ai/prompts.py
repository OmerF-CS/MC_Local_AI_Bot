"""Minecraft AI System Prompt - Ultra-compact Qwen 2.5 3B optimized format."""
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
    pos = state.get("position", {"x": 0, "y": 0, "z": 0})
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


def build_cortex_sensory_prompt(
    state: Optional[Dict[str, Any]] = None,
    inv_dict: Optional[Dict[str, int]] = None,
    alerts: Optional[List[str]] = None,
    affordances_summary: str = "",
    opportunities: Optional[List[str]] = None,
    style: str = "speedrunner",
    recent_actions: str = "",
    lessons: Optional[List[str]] = None
) -> str:
    """Constructs high-density, concise (~150-200 token) sensory perception text for Cognitive Cortex.

    Format:
    [STATE] HP:{hp}/20 | Food:{food}/20 | Light:{light} ({day_phase}) | Pos:({x},{y},{z}) | Biome:{biome}
    [INV] {compact_inventory_string}
    [AFFORD] {affordances_summary}
    [PERCEPTION] Mobs: {mobs} | Blocks: {blocks}
    [ALERTS] {alerts_string}
    [OPPORTUNITIES] {opportunities_string}
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

    # Compact Inventory String
    if inv_dict:
        inv_str = ", ".join(f"{k}:{v}" for k, v in inv_dict.items())
    else:
        inv_str = "empty"

    # Affordances
    afford_str = affordances_summary.strip() if affordances_summary else "none"

    # Perception: Mobs & Blocks
    mobs = (
        state.get("nearby_entities_summary") or
        ", ".join(state.get("nearby_hostiles", [])) or
        "none"
    )
    blocks = (
        state.get("nearby_blocks_summary") or
        ", ".join(state.get("nearby_blocks", [])) or
        "none"
    )

    # Alerts & Opportunities
    alerts_str = "; ".join(alerts) if alerts else "none"
    opps_str = "; ".join(opportunities) if opportunities else "none"

    # Style, Recent actions, Lessons
    style_str = style or "speedrunner"
    recent_str = recent_actions.strip() if recent_actions else "none"
    if isinstance(lessons, list):
        lessons_str = "; ".join(lessons) if lessons else "none"
    else:
        lessons_str = str(lessons) if lessons else "none"

    prompt_lines = [
        f"[STATE] HP:{hp}/20 | Food:{food}/20 | Light:{light} ({day_phase}) | Pos:({x},{y},{z}) | Biome:{biome}",
        f"[INV] {inv_str}",
        f"[AFFORD] {afford_str}",
        f"[PERCEPTION] Mobs: {mobs} | Blocks: {blocks}",
        f"[ALERTS] {alerts_str}",
        f"[OPPORTUNITIES] {opps_str}",
        f"[STYLE] {style_str}",
        f"[RECENT] {recent_str}",
        f"[LESSONS] {lessons_str}"
    ]
    return "\n".join(prompt_lines)

