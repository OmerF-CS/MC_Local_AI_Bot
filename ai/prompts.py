"""Minecraft AI System Prompt - Ultra-compact Qwen 2.5 3B optimized format."""

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

EXAMPLES:
Target: wooden_pickaxe | Missing: 3 oak_log -> collect_block(block_name="oak_log", count=3)
Target: furnace | Missing: 8 cobblestone -> collect_block(block_name="stone", count=8)
Target: iron_pickaxe | Missing: craft iron_pickaxe -> craft_item(item_name="iron_pickaxe", count=1)

STATUS:
- HP: {health}/20 | Food: {food}/20 | Dim: {dimension} | Pos: {position}
- Target: {goal_target} ({goal_stage}) | Missing: {goal_missing}
- Tools: {carried_tools} | Hostiles: {nearby_entities}
- Mission: {active_task_header}"""


def build_system_prompt_for_ollama(state, bot_name, bot_owner, goal, pro_tactic, active_task):
    """Build ultra-compact system prompt with dynamic state injection."""
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
    goal_stage = goal.get("stage", "early")
    goal_target = goal.get("target", "wooden_pickaxe")

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

    return MINECRAFT_SYSTEM_PROMPT.format(
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
