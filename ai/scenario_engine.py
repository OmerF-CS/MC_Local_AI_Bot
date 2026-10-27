"""Scenario Deliberation Engine - Micro-scenario framing and autonomous decision framing.

Features:
- Identifies critical tactical game situations (ambush, underground tool crisis, windfall, barriers, villages)
- Packages dilemmas and candidate options into ultra-compact prompt tokens (<25 words)
- Preserves LLM agency for local model (mc-qwen:3b) deliberation
- Provides safe heuristic fallbacks if LLM is offline
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional


class ScenarioType(str, Enum):
    """Recognized tactical survival scenarios."""
    NIGHT_SURVIVAL_AMBUSH = "NIGHT_SURVIVAL_AMBUSH"
    RESOURCE_WINDFALL = "RESOURCE_WINDFALL"
    VILLAGE_DISCOVERY = "VILLAGE_DISCOVERY"
    TOOL_CRISIS_UNDERGROUND = "TOOL_CRISIS_UNDERGROUND"
    TERRAIN_BARRIER = "TERRAIN_BARRIER"
    STANDARD_SURVIVAL = "STANDARD_SURVIVAL"


@dataclass
class ScenarioFrame:
    """Encapsulates a situational trade-off frame presented to the cognitive cortex."""
    scenario_type: ScenarioType
    situation: str
    dilemma: str
    candidate_tools: List[str]
    urgency: int  # 1-10 priority scale
    metadata: Dict[str, Any] = field(default_factory=dict)

    def format_prompt_line(self) -> str:
        """Formats an ultra-compact scenario prompt line strictly bounded to <= 25 words."""
        options_str = ", ".join(self.candidate_tools[:3])
        line = f"[SCENARIO] {self.scenario_type.value}: {self.situation} | Dilemma: {self.dilemma} | Options: {options_str}"
        words = line.split()
        if len(words) > 25:
            return " ".join(words[:25])
        return line

    def get_fallback_action(self) -> Optional[Dict[str, Any]]:
        """Safe heuristic action if Cortex/Ollama is offline or timed out."""
        st = self.scenario_type
        if st == ScenarioType.NIGHT_SURVIVAL_AMBUSH:
            if self.metadata.get("has_bed"):
                return {"name": "sleep_in_bed", "arguments": {}}
            return {"name": "build_shelter", "arguments": {"mode": "auto"}}
        elif st == ScenarioType.RESOURCE_WINDFALL:
            target_resource = self.metadata.get("resource", "iron_ore")
            return {"name": "collect_block", "arguments": {"block_name": target_resource, "count": 3}}
        elif st == ScenarioType.VILLAGE_DISCOVERY:
            return {"name": "farm_crops", "arguments": {}}
        elif st == ScenarioType.TOOL_CRISIS_UNDERGROUND:
            return {"name": "mine_staircase", "arguments": {"target_y": 68}}
        elif st == ScenarioType.TERRAIN_BARRIER:
            return {"name": "pillar_jump", "arguments": {"height": 3}}
        elif st == ScenarioType.STANDARD_SURVIVAL:
            return None
        return None


class ScenarioDetector:
    """Ultra-fast (<0.2ms) in-memory tactical scenario detector."""

    def detect_scenario(
        self,
        state: Dict[str, Any],
        inv_dict: Dict[str, int],
        current_goal: Optional[Dict[str, Any]] = None
    ) -> ScenarioFrame:
        """Evaluates world state in order of crisis priority and frames tactical dilemmas."""
        if not state:
            state = {}
        if inv_dict is None:
            inv_dict = {}

        # 1. TOOL_CRISIS_UNDERGROUND
        # Pos y < 50 or in_cave or underground dimension
        pos = state.get("position") or {}
        y = pos.get("y", 64) if isinstance(pos, dict) else 64
        is_underground = (
            y < 50
            or bool(state.get("in_cave"))
            or state.get("dimension") == "underground"
        )

        pickaxes = ("wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe")
        has_usable_pickaxe = any(inv_dict.get(p, 0) > 0 for p in pickaxes)

        pick_durability_low = False
        tool_base = state.get("tool_base")
        if not tool_base and isinstance(state.get("survival_inventory"), dict):
            tool_base = state["survival_inventory"].get("tool_base")

        if isinstance(tool_base, dict):
            for t_name, t_info in tool_base.items():
                if any(p in t_name.lower() for p in ("pickaxe", "pick")):
                    if isinstance(t_info, dict) and t_info.get("durability", 100) < 5:
                        pick_durability_low = True
                    elif isinstance(t_info, (int, float)) and t_info < 5:
                        pick_durability_low = True

        no_pickaxe = (not has_usable_pickaxe) or pick_durability_low

        planks_cnt = sum(cnt for item, cnt in inv_dict.items() if "plank" in item)
        logs_cnt = sum(cnt for item, cnt in inv_dict.items() if ("log" in item or "wood" in item) and "plank" not in item)
        no_wood = (planks_cnt < 4 and logs_cnt < 2)

        if is_underground and no_pickaxe and no_wood:
            return ScenarioFrame(
                scenario_type=ScenarioType.TOOL_CRISIS_UNDERGROUND,
                situation=f"Y={y:.0f}, pickaxe broken/low, no wood",
                dilemma="staircase to surface vs scavenge cave vs bare-hand",
                candidate_tools=["mine_staircase", "collect_block", "go_to_coordinates"],
                urgency=8
            )

        # 2. NIGHT_SURVIVAL_AMBUSH
        is_day = state.get("is_day", True)
        day_phase = state.get("day_phase", "")
        time_of_day = str(state.get("time_of_day", "")).capitalize()
        light_level = state.get("light_level", state.get("light", 15))
        is_dark = (
            (not is_day)
            or (day_phase in ("Dusk", "Night", "dusk", "night"))
            or (time_of_day in ("Dusk", "Night", "dusk", "night"))
            or (light_level < 5)
        )

        hostile_names = {
            "zombie", "skeleton", "creeper", "spider", "cave_spider", "enderman",
            "witch", "phantom", "drowned", "husk", "stray", "slime", "pillager",
            "vindicator", "evoker", "ravager", "warden", "silverfish", "piglin_brute"
        }

        nearby_hostiles = state.get("nearby_hostiles") or []
        hostiles_in_range: List[str] = []
        for h in nearby_hostiles:
            if isinstance(h, str):
                hostiles_in_range.append(h)
            elif isinstance(h, dict):
                hostiles_in_range.append(h.get("name", "hostile"))

        nearby_entities = state.get("nearby_entities") or []
        for ent in nearby_entities:
            if isinstance(ent, dict):
                name = ent.get("name", "").lower()
                dist = ent.get("distance", 999.0)
                is_hostile = ent.get("is_hostile", False) or any(hn in name for hn in hostile_names)
                if is_hostile and dist <= 16.0:
                    if name not in hostiles_in_range:
                        hostiles_in_range.append(name)
            elif isinstance(ent, str):
                ent_lower = ent.lower()
                if any(hn in ent_lower for hn in hostile_names):
                    hostiles_in_range.append(ent)

        hostile_count = len(hostiles_in_range)
        is_sheltered = bool(state.get("is_sheltered", False))

        if is_dark and hostile_count > 0 and not is_sheltered:
            health = state.get("health", 20)
            has_bed = any("bed" in k for k in inv_dict.keys()) or bool(state.get("visible_resources", {}).get("bed"))
            urgency = 9 if health < 12 else 7
            return ScenarioFrame(
                scenario_type=ScenarioType.NIGHT_SURVIVAL_AMBUSH,
                situation=f"{hostile_count} hostiles in darkness, unsheltered",
                dilemma="burrow shelter vs fight hostiles vs pillar jump",
                candidate_tools=["build_shelter", "attack_target", "pillar_jump"],
                urgency=urgency,
                metadata={"has_bed": has_bed, "hostile_count": hostile_count}
            )

        # 3. TERRAIN_BARRIER
        if (
            state.get("terrain_barrier")
            or state.get("cliff_detected")
            or state.get("lava_hazard_ahead")
            or state.get("ravine_detected")
            or state.get("nav_stuck_elevation")
        ):
            return ScenarioFrame(
                scenario_type=ScenarioType.TERRAIN_BARRIER,
                situation="Cliff, chasm or lava barrier blocking path",
                dilemma="pillar jump up vs water descent vs detour",
                candidate_tools=["pillar_jump", "water_bucket_descent", "go_to_coordinates"],
                urgency=7
            )

        # 4. RESOURCE_WINDFALL
        high_tier_ores = ("diamond_ore", "deepslate_diamond_ore", "ancient_debris", "diamond")
        structures = ("desert_pyramid", "shipwreck", "ruined_portal")

        found_windfall: Optional[str] = None

        # Check nearby_blocks
        nearby_blocks = state.get("nearby_blocks") or []
        iron_count = 0
        if isinstance(nearby_blocks, list):
            for b in nearby_blocks:
                b_name = b.get("name", "") if isinstance(b, dict) else str(b)
                b_lower = b_name.lower()
                for hto in high_tier_ores:
                    if hto in b_lower:
                        found_windfall = hto
                        break
                if found_windfall:
                    break
                for st in structures:
                    if st in b_lower:
                        found_windfall = st
                        break
                if found_windfall:
                    break
                if "iron_ore" in b_lower or "raw_iron" in b_lower:
                    iron_count += 1

        # Check visible_resources
        vis_res = state.get("visible_resources") or {}
        if isinstance(vis_res, dict):
            for r_name, r_data in vis_res.items():
                r_lower = r_name.lower()
                for hto in high_tier_ores:
                    if hto in r_lower:
                        found_windfall = hto
                        break
                if found_windfall:
                    break
                for st in structures:
                    if st in r_lower:
                        found_windfall = st
                        break
                if found_windfall:
                    break
                if "iron_ore" in r_lower or "raw_iron" in r_lower:
                    count = 1
                    if isinstance(r_data, dict):
                        count = r_data.get("count", 1)
                    elif isinstance(r_data, (int, float)):
                        count = int(r_data)
                    iron_count += count

        # Check discovered_structures
        disc_structs = state.get("discovered_structures") or []
        if not found_windfall and isinstance(disc_structs, list):
            for st in disc_structs:
                st_name = st.get("name", "") if isinstance(st, dict) else str(st)
                st_lower = st_name.lower()
                for s in structures:
                    if s in st_lower:
                        found_windfall = s
                        break
                if found_windfall:
                    break

        if not found_windfall and iron_count >= 4:
            found_windfall = "iron_ore"

        if found_windfall:
            goal_target = ""
            if isinstance(current_goal, dict):
                goal_target = current_goal.get("target", "")
            elif isinstance(current_goal, str):
                goal_target = current_goal

            lower_tier_targets = {
                "wooden_pickaxe", "stone_pickaxe", "crafting_table", "wooden_sword",
                "stick", "planks", "log", "oak_log", "furnace", "stone_sword"
            }

            is_same_target = (goal_target == found_windfall or goal_target.replace("_ore", "") == found_windfall.replace("_ore", ""))
            is_lower_tier = (goal_target in lower_tier_targets or not goal_target)

            if (not is_same_target) or is_lower_tier:
                return ScenarioFrame(
                    scenario_type=ScenarioType.RESOURCE_WINDFALL,
                    situation=f"Exposed {found_windfall} spotted nearby",
                    dilemma=f"mine {found_windfall} windfall vs stay on goal",
                    candidate_tools=["collect_block", "explore_structure", "manage_chest"],
                    urgency=6,
                    metadata={"resource": found_windfall}
                )

        # 5. VILLAGE_DISCOVERY
        village_detected = bool(state.get("village_detected")) or bool(state.get("village"))
        if not village_detected:
            if isinstance(disc_structs, list):
                for st in disc_structs:
                    st_name = st.get("name", "") if isinstance(st, dict) else str(st)
                    if "village" in st_name.lower():
                        village_detected = True
                        break

        if not village_detected:
            entities_to_check = []
            if isinstance(nearby_entities, list):
                for e in nearby_entities:
                    e_name = e.get("name", "") if isinstance(e, dict) else str(e)
                    entities_to_check.append(e_name.lower())
            ent_summary = str(state.get("nearby_entities_summary", "")).lower()
            if any("villager" in en or "iron_golem" in en for en in entities_to_check) or "villager" in ent_summary or "iron_golem" in ent_summary:
                village_detected = True

        if village_detected:
            return ScenarioFrame(
                scenario_type=ScenarioType.VILLAGE_DISCOVERY,
                situation="Village discovered with crops and beds",
                dilemma="loot hay & trade vs sleep in bed vs set base",
                candidate_tools=["farm_crops", "trade_with_villager", "sleep_in_bed"],
                urgency=6
            )

        # 6. STANDARD_SURVIVAL
        return ScenarioFrame(
            scenario_type=ScenarioType.STANDARD_SURVIVAL,
            situation="Standard progression",
            dilemma="advance tech tree vs gather resources",
            candidate_tools=["collect_block", "craft_item", "smelt_item"],
            urgency=3
        )
