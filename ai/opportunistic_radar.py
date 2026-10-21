"""Opportunistic Radar & Real-Time World Scanner."""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from utils.logger import get_logger

logger = get_logger("OpportunityScanner")


@dataclass
class Opportunity:
    name: str
    priority: int
    action: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class OpportunityScanner:
    """Scans world state and inventory for high-value opportunistic shortcuts."""

    def evaluate_opportunities(
        self,
        inv_dict: Dict[str, int],
        state: Dict[str, Any],
        current_goal: Dict[str, Any]
    ) -> Optional[Opportunity]:
        """Evaluates situational rules and returns highest priority Opportunity or None."""
        if not state:
            return None

        opportunities: List[Opportunity] = []

        # -------------------------------------------------------------
        # Rule 1: WoolNeedRule (Priority 8)
        # If no bed and total wool < 3, and sheep within 24m
        # -------------------------------------------------------------
        total_wool = sum(count for name, count in inv_dict.items() if "wool" in name.lower())
        has_bed = inv_dict.get("bed", 0) > 0 or any("bed" in k.lower() for k in inv_dict.keys())
        if not has_bed and total_wool < 3:
            sheep_detected = False

            # Check nearby_passives
            passives = state.get("nearby_passives", [])
            if isinstance(passives, list):
                for p in passives:
                    if isinstance(p, dict):
                        p_name = str(p.get("name", "")).lower()
                        p_dist = float(p.get("distance", 999))
                        if "sheep" in p_name and p_dist <= 24.0:
                            sheep_detected = True
                            break
                    elif isinstance(p, str) and "sheep" in p.lower():
                        sheep_detected = True
                        break

            # Check visible_resources
            if not sheep_detected:
                vis_res = state.get("visible_resources", {})
                if isinstance(vis_res, dict) and "sheep" in vis_res:
                    s_info = vis_res["sheep"]
                    dist = float(s_info.get("closest_distance", 999)) if isinstance(s_info, dict) else (float(s_info) if isinstance(s_info, (int, float)) else 999)
                    if dist <= 24.0:
                        sheep_detected = True

            # Check raw entities map if present
            if not sheep_detected:
                entities = state.get("entities", {})
                if isinstance(entities, dict):
                    for ent in entities.values():
                        if isinstance(ent, dict) and str(ent.get("name", "")).lower() == "sheep":
                            pos = ent.get("position")
                            bot_pos = state.get("position", {})
                            if isinstance(pos, dict) and isinstance(bot_pos, dict):
                                dx = pos.get("x", 0) - bot_pos.get("x", 0)
                                dy = pos.get("y", 0) - bot_pos.get("y", 0)
                                dz = pos.get("z", 0) - bot_pos.get("z", 0)
                                if (dx * dx + dy * dy + dz * dz) <= 24.0 * 24.0:
                                    sheep_detected = True
                                    break

            if sheep_detected:
                opportunities.append(
                    Opportunity(
                        name="gather_wool_for_bed",
                        priority=8,
                        action="attack_target",
                        arguments={"target_name": "sheep"},
                        reason="Secure 3 wool for bed before nightfall"
                    )
                )

        # -------------------------------------------------------------
        # Rule 2: SurfaceCoalRule (Priority 6)
        # If torch < 4 and coal < 2 and current_goal target != wooden_pickaxe,
        # and coal_ore visible within 16m
        # -------------------------------------------------------------
        goal_target = str(current_goal.get("target", "")).lower() if isinstance(current_goal, dict) else ""
        torches = inv_dict.get("torch", 0)
        coal = inv_dict.get("coal", 0) + inv_dict.get("charcoal", 0)
        if torches < 4 and coal < 2 and goal_target != "wooden_pickaxe":
            coal_detected = False
            vis_res = state.get("visible_resources", {})
            if isinstance(vis_res, dict):
                for c_key in ("coal_ore", "deepslate_coal_ore", "coal"):
                    if c_key in vis_res:
                        c_info = vis_res[c_key]
                        c_dist = float(c_info.get("closest_distance", 999)) if isinstance(c_info, dict) else (float(c_info) if isinstance(c_info, (int, float)) else 999)
                        if c_dist <= 16.0:
                            coal_detected = True
                            break

            # Also check special_ores_radar
            if not coal_detected:
                radar = state.get("special_ores_radar", {})
                if isinstance(radar, dict):
                    for r_list in radar.values():
                        if isinstance(r_list, list):
                            for ore_entry in r_list:
                                if isinstance(ore_entry, dict) and "coal" in str(ore_entry.get("block", "")).lower():
                                    if float(ore_entry.get("closest_distance", 999)) <= 16.0:
                                        coal_detected = True
                                        break

            if coal_detected:
                opportunities.append(
                    Opportunity(
                        name="grab_surface_coal",
                        priority=6,
                        action="collect_block",
                        arguments={"block_name": "coal_ore", "count": 4},
                        reason="Harvest surface coal for torches"
                    )
                )

        # -------------------------------------------------------------
        # Rule 3: StructureLootRule (Priority 7)
        # If state detects desert_pyramid / village / ruined_portal / shipwreck nearby
        # -------------------------------------------------------------
        STRUCTURE_KEYS = ["desert_pyramid", "village", "ruined_portal", "shipwreck"]
        detected_structure = None

        search_sources = [
            state.get("landmarks"),
            state.get("structures"),
            state.get("nearby_structures"),
            state.get("detected_structures"),
            state.get("telemetry", {}).get("landmarks") if isinstance(state.get("telemetry"), dict) else None
        ]

        for source in search_sources:
            if isinstance(source, dict):
                for s_key in STRUCTURE_KEYS:
                    val = source.get(s_key)
                    if val is True or (isinstance(val, (int, float)) and val > 0) or (isinstance(val, dict) and val):
                        detected_structure = s_key
                        break
            elif isinstance(source, list):
                for item in source:
                    s_name = item.get("name") if isinstance(item, dict) else str(item)
                    if s_name in STRUCTURE_KEYS:
                        detected_structure = s_name
                        break
            if detected_structure:
                break

        if not detected_structure:
            for s_key in STRUCTURE_KEYS:
                if state.get(s_key):
                    detected_structure = s_key
                    break

        if detected_structure:
            opportunities.append(
                Opportunity(
                    name="loot_structure",
                    priority=7,
                    action="explore_structure",
                    arguments={"structure_type": detected_structure},
                    reason="Opportunistically loot structure treasure"
                )
            )

        if not opportunities:
            return None

        # Return opportunity with highest priority
        opportunities.sort(key=lambda o: o.priority, reverse=True)
        chosen = opportunities[0]
        logger.info(f"✨ [Opportunity Scanner] Found {len(opportunities)} opportunities. Selected: '{chosen.name}' (Priority {chosen.priority}): {chosen.reason}")
        return chosen
