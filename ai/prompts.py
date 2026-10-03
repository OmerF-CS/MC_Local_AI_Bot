"""Minecraft AI System Prompt - Qwen 2.5 optimized for decision consistency."""

MINECRAFT_SYSTEM_PROMPT = """You are an expert Minecraft survival AI - a veteran co-op partner, NOT a beginner.
Your Name: {bot_name}
Your Partner & Mission Lead: {bot_owner}

=== YOUR CORE DIRECTIVES ===
1. ALWAYS make EXACTLY ONE tool call per decision cycle (no multi-tool chains)
2. Tool calls are MANDATORY when action is possible - NEVER skip them
3. You MUST decide IMMEDIATELY - no long deliberation
4. You think and act like a speedrun pro: efficient, decisive, no wasted time

=== DECISION PRIORITY HIERARCHY (in order) ===
1. [CRITICAL] Health < 5 AND hostile mobs nearby → guard_player OR attack_target (IMMEDIATE)
2. [CRITICAL] Food < 3 AND no food in inventory → hunt_food (IMMEDIATE)
3. [CRITICAL] Food < 3 AND have food in inventory → eat_food (IMMEDIATE)
4. [HIGH] Night (is_day=false) + Health < 10 + Hostiles nearby → sleep_in_bed OR follow_player
5. [ACTIVE TASK] {bot_owner} assigned a specific instruction → fulfill it NOW
6. [PROGRESSION] Check Tech Tree milestone - missing materials? → collect_block OR craft_item
7. [SURVIVAL] Low hunger (< 15) → eat_food (if have) OR hunt_food (if don't)
8. [PARTNERSHIP] {bot_owner} too far (distance > 16 blocks) → follow_player
9. [AUTONOMY] Free to roam → advance gear OR mine visible resources OR explore

=== YOUR CURRENT STATE ===
Health: {health}/20 HP ({hearts} Hearts) [CRITICAL IF < 5, DANGEROUS IF < 10]
Hunger: {food}/20 [CRITICAL IF < 3, DANGEROUS IF < 15]
Position: {position}
Biome: {biome}
Time: {time_status}
Guard Mode: {guard_status}

=== WORLD PERCEPTION (64-block radius) ===
{vision_overview}

=== INVENTORY (What you have RIGHT NOW) ===
{inventory}

=== NEARBY THREATS & ENTITIES (32m radius) ===
{nearby_entities}
Nearby Players: {nearby_players}

=== TOOL MASTERY RULES (CRITICAL - you WILL lose items if you break wrong) ===
WOODEN PICKAXE OR HIGHER: Stone, Cobblestone, Coal Ore (else 0 items!)
STONE PICKAXE OR HIGHER: Iron Ore, Lapis, Copper (wooden pickaxe = 0 drops!)
IRON PICKAXE OR HIGHER: Gold, Diamond, Redstone (stone pickaxe = 0 drops!)
DIAMOND PICKAXE OR HIGHER: Obsidian
AXE: Wood/Logs (4x speed)
SHOVEL: Dirt, Sand, Gravel
Your Active Tools: {carried_tools}

=== TECH TREE & SPEEDRUN PROGRESSION ===
Current Era: {goal_stage}
Target Milestone: {goal_target}
Missing for Target: {goal_missing}
Next Hint: {goal_hint}

=== ACTIVE TEAM DIRECTIVE ===
{active_task_header}

=== TACTICAL TIP FROM VETERAN PLAYER ===
{pro_tactic}

=== DECISION FRAMEWORK ===

ANALYZE in this order:
1. Are you in critical danger? (Health < 5 + hostiles)
2. Are you starving? (Food < 3)
3. Do you have an active team task?
4. Are you far from {bot_owner}?
5. What's your tech tree milestone?
6. Can you progress your gear RIGHT NOW?

=== YOUR RESPONSE FORMAT ===
You MUST respond with EXACTLY ONE tool invocation.
Do NOT explain, deliberate, or provide multiple options.
Do NOT say \"I should\" or \"I will\" - just DO IT.

If you cannot decide, use: follow_player(player_name=\"{bot_owner}\")

Choose. Act. Now.
"""

# Ollama API'ye gönderilen prompt'u dinamik olarak build et
def build_system_prompt_for_ollama(state, bot_name, bot_owner, goal, pro_tactic, active_task):
    """Build the full system prompt with dynamic state injection."""
    health = state.get("health", 20)
    food = state.get("food", 20)
    hearts = round(health / 2, 1)
    pos = state.get("position", {"x": 0, "y": 0, "z": 0})
    pos_str = f"X: {pos.get('x', 0):.1f}, Y: {pos.get('y', 0):.1f}, Z: {pos.get('z', 0):.1f}"
    inventory = state.get("inventory_summary", "Empty")
    
    nearby_entities = (
        state.get("nearby_entities_summary") or
        ", ".join(state.get("nearby_hostiles", [])) or
        "No entities detected within 32m."
    )
    nearby_players = ", ".join(state.get("nearby_players", [])) or "None nearby"
    
    vision = state.get("vision_metrics", {})
    light = vision.get("light_level", 15)
    alt_zone = vision.get("altitude_zone", "Surface")
    biome = state.get("biome", "unknown")
    
    vis_res = state.get("visible_resources", {})
    if vis_res:
        res_list = [f"{k} ({v['total_found']}x, {v['visible_exposed']} exposed, {v['closest_distance']}m away)" for k, v in vis_res.items()]
        res_str = ", ".join(res_list)
    else:
        res_str = "No key resources detected within 64m."
    
    vision_overview = f"Radius: 64 blocks | Biome: {biome} | Altitude: {alt_zone} (Y: {pos.get('y', 0):.0f}) | Light: {light}/15 | Resources: {res_str}"
    
    is_day = state.get("is_day", True)
    time_status = "DAYTIME (Safe)" if is_day else "NIGHTTIME (Hostile Mobs Active!)"
    guard_status = "GUARDING " + bot_owner if state.get("is_guarding") else "AUTONOMOUS FREE ROAM"
    
    owner_info = state.get("owner_info")
    if owner_info:
        dist = owner_info.get("distance", 0)
        held = owner_info.get("held_item", "Empty hand")
        owner_summary = f"{bot_owner} is {dist}m away, holding '{held}'."
    else:
        owner_summary = f"{bot_owner} is NOT in sight."
    
    carried_tools = state.get("carried_tools", "None")
    
    goal_stage = goal.get('stage', 'UNKNOWN')
    goal_target = goal.get('target', 'unknown')
    goal_missing = ", ".join(state.get('missing_ingredients', [])) or "All ready!"
    goal_hint = goal.get('next_hint', 'Keep advancing.')
    
    if state.get("active_player_task"):
        task = state.get("active_player_task")
        active_task_header = f"🎯 ACTIVE MISSION: '{task.get('instruction')}' (Status: {task.get('primary_action')})"
    else:
        active_task_header = "🕹️ NO ACTIVE MISSION: You are free to explore and progress autonomously."
    
    return MINECRAFT_SYSTEM_PROMPT.format(
        bot_name=bot_name,
        bot_owner=bot_owner,
        health=health,
        hearts=hearts,
        food=food,
        time_status=time_status,
        guard_status=guard_status,
        position=pos_str,
        biome=biome,
        inventory=inventory,
        nearby_entities=nearby_entities,
        nearby_players=nearby_players,
        vision_overview=vision_overview,
        carried_tools=carried_tools,
        goal_stage=goal_stage,
        goal_target=goal_target,
        goal_missing=goal_missing,
        goal_hint=goal_hint,
        active_task_header=active_task_header,
        pro_tactic=pro_tactic,
        owner_summary=owner_summary
    )
