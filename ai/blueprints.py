"""Minecraft Tactical Architectural Blueprints & Void Bridging Engine in English.

Provides exact structural layouts for:
1. Nether Outposts: Blast-resistant perimeter enclosing Nether portals against Ghast fireballs.
2. Void & Chasm Bridging: Step-by-step sneak (crouch) vector generation over lava lakes and End void chasms.
3. Enderman Canopy: Low 2-block ceilings for safe Enderman XP and pearl farming.
"""
from typing import Dict, Any, List, Tuple

# Blocks with blast resistance >= 6 (immune to Ghast fireball explosions)
BLAST_RESISTANT_MATERIALS = [
    "cobblestone",
    "cobbled_deepslate",
    "stone",
    "deepslate",
    "blackstone",
    "polished_blackstone",
    "polished_deepslate",
    "stone_bricks",
    "deepslate_bricks",
    "nether_bricks",
    "end_stone",
    "end_stone_bricks",
    "iron_block",
    "obsidian"
]

def is_blast_resistant(block_name: str) -> bool:
    """Checks whether a block name satisfies Ghast explosion blast resistance (>= 6)."""
    clean = block_name.lower().strip()
    return any(mat in clean for mat in BLAST_RESISTANT_MATERIALS)

def get_nether_outpost_layout(portal_x: int, portal_y: int, portal_z: int) -> List[Tuple[int, int, int]]:
    """Generates coordinate offsets for a 5x5x4 blast-resistant protective fort around a Nether portal.
    
    Leaves a 1x2 exit doorway while covering the perimeter and ceiling to prevent
    Ghast fireballs from extinguishing the portal or killing the bot.
    """
    blocks_to_place: List[Tuple[int, int, int]] = []
    
    # Outer box dimensions: x from -2 to 2, z from -2 to 2, y from 0 to 3
    # 4 walls
    for y in range(0, 4):
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                # Is it an outer wall?
                is_wall = (dx == -2 or dx == 2 or dz == -2 or dz == 2)
                if is_wall:
                    # Keep a 1x2 doorway on the south face (dz == 2, dx == 0, y in {0, 1})
                    if dz == 2 and dx == 0 and y in (0, 1):
                        continue
                    blocks_to_place.append((portal_x + dx, portal_y + y, portal_z + dz))
                    
    # Solid roof at y = 3
    for dx in range(-2, 3):
        for dz in range(-2, 3):
            roof_pos = (portal_x + dx, portal_y + 3, portal_z + dz)
            if roof_pos not in blocks_to_place:
                blocks_to_place.append(roof_pos)
                
    return blocks_to_place

def get_bridge_step_vectors(direction: str = "forward", distance: int = 5, yaw: float = 0.0) -> List[Dict[str, Any]]:
    """Calculates step-by-step placement and sneak vectors for bridging across a gap.
    
    Direction can be 'forward', 'north', 'south', 'east', 'west'.
    Returns list of relative displacement vectors for block placement beneath feet.
    """
    clean_dir = direction.lower().strip()
    dx, dz = 0, 0
    
    if clean_dir == "north":
        dz = -1
    elif clean_dir == "south":
        dz = 1
    elif clean_dir == "west":
        dx = -1
    elif clean_dir == "east":
        dx = 1
    else:  # forward based on yaw angle
        # Yaw 0: South (dz=1), 90: West (dx=-1), 180: North (dz=-1), 270: East (dx=1)
        import math
        rad = math.radians(yaw)
        dx = -round(math.sin(rad))
        dz = round(math.cos(rad))
        if dx == 0 and dz == 0:
            dz = 1

    steps: List[Dict[str, Any]] = []
    for step_idx in range(1, distance + 1):
        target_x = dx * step_idx
        target_z = dz * step_idx
        # Block placed directly below ground level (dy = -1)
        steps.append({
            "step": step_idx,
            "place_offset": (target_x, -1, target_z),
            "walk_offset": (target_x, 0, target_z),
            "sneak_required": True
        })
        
    return steps

def get_enderman_canopy_layout(player_x: int, player_y: int, player_z: int) -> List[Tuple[int, int, int]]:
    """Generates a 3x3 horizontal canopy at Y+2 height.
    
    Since Endermen are 3 blocks tall, they cannot reach underneath the canopy.
    The player/bot (1.8m height) stands safely under the roof and strikes Endermen legs.
    """
    blocks: List[Tuple[int, int, int]] = []
    # 3x3 canopy at y + 2
    for dx in range(-1, 2):
        for dz in range(-1, 2):
            blocks.append((player_x + dx, player_y + 2, player_z + dz))
            
    # Support pillar at corner (-1, -1) so roof can be anchored to the ground
    blocks.append((player_x - 1, player_y, player_z - 1))
    blocks.append((player_x - 1, player_y + 1, player_z - 1))
    
    return blocks
