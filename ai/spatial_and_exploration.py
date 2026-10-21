"""Spatial Awareness, Frontier Exploration Engine, and Death Reflection.

Manages chunk visitation memory, unvisited frontier direction calculation,
unreachable target blacklisting with TTL, and death reflection lesson synthesis.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import time
import math
import random

GENERIC_ACTION_NAMES = {
    "attack", "attack_target", "mine", "collect", "collect_block",
    "craft", "craft_item", "explore", "goto", "go_to_coordinates",
    "eat", "eat_food", "sleep", "sleep_in_bed"
}

class ExplorationEngine:
    """Tracks visited chunks, calculates frontier targets, and handles unreachable target blacklisting."""

    # 8 Compass Directions (dx, dz unit vectors)
    COMPASS_DIRECTIONS: List[Tuple[str, float, float]] = [
        ("N", 0.0, -1.0),
        ("NE", 0.7071, -0.7071),
        ("E", 1.0, 0.0),
        ("SE", 0.7071, 0.7071),
        ("S", 0.0, 1.0),
        ("SW", -0.7071, 0.7071),
        ("W", -1.0, 0.0),
        ("NW", -0.7071, -0.7071)
    ]

    def __init__(self):
        self.visited_chunks: Dict[Tuple[int, int], float] = {}
        self.current_chunk: Optional[Tuple[int, int]] = None
        self.chunk_entered_at: float = time.time()
        self.discovered_biomes: Set[str] = set()
        self.unreachable_targets: Dict[str, float] = {}

    def update_position(self, pos: Dict[str, Any], biome: str = "unknown") -> None:
        """Updates chunk visitation history and tracks current biome and chunk residency time."""
        if not pos or "x" not in pos or "z" not in pos:
            return

        now = time.time()
        cx = int(float(pos["x"])) // 16
        cz = int(float(pos["z"])) // 16
        chunk_coord = (cx, cz)

        self.visited_chunks[chunk_coord] = now

        if self.current_chunk != chunk_coord:
            self.current_chunk = chunk_coord
            self.chunk_entered_at = now

        if biome and biome != "unknown":
            self.discovered_biomes.add(biome.lower().strip())

    def get_curiosity_score(self, now: Optional[float] = None) -> float:
        """Calculates exploration urgency (0.0 to 1.0) based on dwell time in the current chunk."""
        if now is None:
            now = time.time()

        if self.current_chunk is None:
            return 0.5

        elapsed_in_chunk = max(0.0, now - self.chunk_entered_at)
        return min(1.0, elapsed_in_chunk / 120.0)

    def mark_unreachable(self, target: str, duration: float = 90.0) -> None:
        """Blacklists a specific target block or mob coordinates for duration seconds."""
        if not target or not isinstance(target, str):
            return

        clean_target = target.strip().lower()
        if clean_target in GENERIC_ACTION_NAMES or len(clean_target) < 2:
            return

        now = time.time()
        self.unreachable_targets[clean_target] = now + duration

    def is_unreachable(self, target: str) -> bool:
        """Checks if a target is currently blacklisted as unreachable."""
        if not target or not isinstance(target, str):
            return False

        clean_target = target.strip().lower()
        now = time.time()

        expiry = self.unreachable_targets.get(clean_target)
        if expiry is None:
            return False

        if now > expiry:
            del self.unreachable_targets[clean_target]
            return False

        return True

    def get_frontier_target(
        self,
        pos: Dict[str, Any],
        hazard_points: Optional[List[Dict[str, Any]]] = None,
        distance: float = 32.0
    ) -> Dict[str, Any]:
        """Evaluates 8 compass directions to pick an unvisited chunk frontier far from recent hazards."""
        if not pos or "x" not in pos or "z" not in pos:
            return {"x": 0, "z": 0, "ignore_y": True, "range": 3, "reason": "default_spawn_fallback"}

        current_x = float(pos["x"])
        current_z = float(pos["z"])
        now = time.time()

        candidates = []
        for name, dx, dz in self.COMPASS_DIRECTIONS:
            target_x = round(current_x + dx * distance)
            target_z = round(current_z + dz * distance)
            target_chunk = (int(target_x) // 16, int(target_z) // 16)

            score = 0.0

            # (a) Unvisited chunk bonus
            if target_chunk not in self.visited_chunks:
                score += 10.0
            else:
                last_visited = self.visited_chunks[target_chunk]
                time_since = max(1.0, now - last_visited)
                score += min(5.0, time_since / 60.0)

            # (b) Hazard point proximity penalty (death coordinates within 20m)
            if hazard_points:
                for hazard in hazard_points:
                    if not isinstance(hazard, dict) or "x" not in hazard or "z" not in hazard:
                        continue
                    hx = float(hazard["x"])
                    hz = float(hazard["z"])
                    dist = math.hypot(target_x - hx, target_z - hz)
                    if dist < 20.0:
                        score -= 20.0
                    elif dist < 35.0:
                        score -= 8.0

            # (c) Deterministic slight tie-breaker
            score += (hash((target_x, target_z)) % 100) / 1000.0

            candidates.append({
                "x": target_x,
                "z": target_z,
                "score": score,
                "direction": name
            })

        # Pick candidate with maximum score
        candidates.sort(key=lambda c: c["score"], reverse=True)
        best = candidates[0]

        return {
            "x": best["x"],
            "z": best["z"],
            "ignore_y": True,
            "range": 3,
            "reason": "unvisited_frontier",
            "direction": best["direction"]
        }

def analyze_death_reflection(cause: str) -> Dict[str, str]:
    """Analyzes death cause and synthesizes high-priority tactical lessons for autonomous memory."""
    cause_str = (cause or "unknown hazard").lower().strip()

    if any(k in cause_str for k in ("lava", "fire", "burn", "flame", "magma")):
        return {
            "category": "lava_fire",
            "lesson": "[DEATH LESSON - LAVA]: Avoid sprinting near ravines, never dig straight down, and keep a water bucket in off-hand.",
            "chat_message": "I fell into lava or burned. I will keep a water bucket ready and watch my footing."
        }

    if any(k in cause_str for k in ("drown", "water")):
        return {
            "category": "drowning",
            "lesson": "[DEATH LESSON - WATER]: Monitor oxygen bubbles when swimming underwater and carry doors or torches for air pockets.",
            "chat_message": "I ran out of breath underwater. I need to surface earlier when mining submerged."
        }

    if any(k in cause_str for k in ("fall", "fell", "hit the ground", "high place")):
        return {
            "category": "fall_damage",
            "lesson": "[DEATH LESSON - FALL]: Crouch when navigating cliffs and prepare water bucket clutch before descending drops.",
            "chat_message": "I suffered fatal fall damage. I should use ladders or water buckets when descending."
        }

    if any(k in cause_str for k in ("starv", "hunger")):
        return {
            "category": "starvation",
            "lesson": "[DEATH LESSON - HUNGER]: Keep emergency cooked food in hotbar and hunt or farm early before hunger drops to zero.",
            "chat_message": "I starved. I must prioritize food hunting or bread crafting before long journeys."
        }

    if any(k in cause_str for k in ("zombie", "skeleton", "creeper", "spider", "witch", "enderman", "slime", "phantom", "slain", "shot", "blown up", "mob")):
        return {
            "category": "mob_combat",
            "lesson": "[DEATH LESSON - COMBAT]: Equip a shield against projectile mobs, maintain spacing, and retreat to bunker when health falls below 6 HP.",
            "chat_message": "I was overpowered in combat. I need to raise my shield and retreat when HP drops."
        }

    return {
        "category": "generic",
        "lesson": f"[DEATH LESSON - HAZARD]: Exercise heightened situational awareness around unknown hazards ({cause_str}).",
        "chat_message": f"I was eliminated by {cause_str}. Refining survival pathfinding."
    }
