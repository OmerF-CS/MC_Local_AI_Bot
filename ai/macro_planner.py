"""DAG-Based Macro-Plan Chaining Engine in English.

Constructs deterministic dependency graphs for key Minecraft crafting and mining
milestones, executing multi-step prerequisite chains with zero LLM query latency.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("MacroPlanner")


@dataclass
class PlanStep:
    action: str  # "collect_block", "craft_item", "smelt_item", "go_to_coordinates", "place_block"
    arguments: Dict[str, Any]
    description: str
    verification_item: Optional[str] = None
    verification_count: int = 1

    def is_satisfied(self, inv_dict: Dict[str, int]) -> bool:
        """Checks if the step's expected outcome is satisfied in the current inventory."""
        if not self.verification_item:
            return False

        # Direct exact match check
        direct = inv_dict.get(self.verification_item, 0)
        if direct >= self.verification_count:
            return True

        # Equivalent variants and material tags
        item_lower = self.verification_item.lower().strip()
        if item_lower in ("planks", "wooden_planks"):
            total = sum(v for k, v in inv_dict.items() if "plank" in k.lower())
            return total >= self.verification_count
        if item_lower in ("log", "logs", "wood"):
            total = sum(v for k, v in inv_dict.items() if any(w in k.lower() for w in ("log", "wood", "stem", "hyphae")))
            return total >= self.verification_count
        if item_lower in ("stone", "cobblestone", "stone_tool_materials"):
            total = sum(v for k, v in inv_dict.items() if k.lower() in (
                "cobblestone", "cobbled_deepslate", "blackstone", "stone", "deepslate"
            ))
            return total >= self.verification_count
        if item_lower in ("stick", "sticks"):
            total = inv_dict.get("stick", 0) + inv_dict.get("sticks", 0)
            return total >= self.verification_count
        if item_lower in ("raw_iron", "raw_iron_materials", "iron_ore"):
            total = inv_dict.get("raw_iron", 0) + inv_dict.get("iron_ore", 0)
            return total >= self.verification_count
        if item_lower in ("iron_ingot", "iron"):
            total = inv_dict.get("iron_ingot", 0)
            return total >= self.verification_count

        return False


@dataclass
class MacroPlan:
    target_item: str
    steps: List[PlanStep] = field(default_factory=list)
    current_step_idx: int = 0
    status: str = "in_progress"  # "in_progress", "completed", "aborted"

    def get_current_step(self) -> Optional[PlanStep]:
        """Returns the current active step to execute, or None if completed."""
        if 0 <= self.current_step_idx < len(self.steps):
            return self.steps[self.current_step_idx]
        return None

    def advance_step(self) -> Optional[PlanStep]:
        """Advances pointer to the next plan step."""
        self.current_step_idx += 1
        if self.current_step_idx >= len(self.steps):
            self.status = "completed"
            return None
        return self.get_current_step()

    def is_completed(self) -> bool:
        """Checks if all plan steps are finished or status is marked completed."""
        return self.status == "completed" or self.current_step_idx >= len(self.steps)


class MacroPlanner:
    """Evaluates missing ingredients and constructs deterministic DAG plans."""

    SUPPORTED_TARGETS = {
        "wooden_pickaxe",
        "stone_pickaxe",
        "furnace",
        "iron_pickaxe",
        "shield",
        "iron_sword",
        "bucket"
    }

    def __init__(self):
        pass

    def build_macro_plan(
        self,
        target_item: str,
        inv_dict: Dict[str, int],
        state: Optional[Dict[str, Any]] = None
    ) -> MacroPlan:
        """Builds a deterministic MacroPlan based on missing ingredients and tools."""
        clean_target = str(target_item).lower().strip()
        steps: List[PlanStep] = []

        if clean_target == "wooden_pickaxe":
            steps = self._plan_wooden_pickaxe(inv_dict)
        elif clean_target == "stone_pickaxe":
            steps = self._plan_stone_pickaxe(inv_dict)
        elif clean_target == "furnace":
            steps = self._plan_furnace(inv_dict)
        elif clean_target == "iron_pickaxe":
            steps = self._plan_iron_pickaxe(inv_dict)
        elif clean_target == "shield":
            steps = self._plan_shield(inv_dict)
        elif clean_target == "iron_sword":
            steps = self._plan_iron_sword(inv_dict)
        elif clean_target == "bucket":
            steps = self._plan_bucket(inv_dict)
        else:
            logger.debug(f"Target '{target_item}' has no dedicated DAG recipe in MacroPlanner.")

        plan = MacroPlan(target_item=clean_target, steps=steps)
        if not steps:
            plan.status = "completed"
        return plan

    @staticmethod
    def _count_logs(inv_dict: Dict[str, int]) -> int:
        return sum(v for k, v in inv_dict.items() if any(w in k.lower() for w in ("log", "wood", "stem", "hyphae")))

    @staticmethod
    def _count_planks(inv_dict: Dict[str, int]) -> int:
        return sum(v for k, v in inv_dict.items() if "plank" in k.lower())

    @staticmethod
    def _count_cobblestone(inv_dict: Dict[str, int]) -> int:
        return sum(v for k, v in inv_dict.items() if k.lower() in (
            "cobblestone", "cobbled_deepslate", "blackstone", "stone", "deepslate"
        ))

    def _plan_wooden_pickaxe(self, inv_dict: Dict[str, int]) -> List[PlanStep]:
        # If already possessing wooden_pickaxe or better pickaxe, return empty
        if any(inv_dict.get(p, 0) > 0 for p in ("wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe")):
            return []

        steps: List[PlanStep] = []
        has_table = inv_dict.get("crafting_table", 0) > 0
        sticks = inv_dict.get("stick", 0) + inv_dict.get("sticks", 0)
        planks = self._count_planks(inv_dict)
        logs = self._count_logs(inv_dict)

        # Calculate needed planks: 3 for pickaxe, 2 for sticks (yields 4), 4 for table if missing
        needed_planks = 3
        if not has_table:
            needed_planks += 4
        if sticks < 2:
            needed_planks += 2

        # 1. Collect logs if total available wood is insufficient
        total_potential_planks = planks + (logs * 4)
        if total_potential_planks < needed_planks and logs == 0:
            steps.append(PlanStep(
                action="collect_block",
                arguments={"block_name": "log", "count": 3},
                description="Gather 3 wood logs for wooden tool crafting",
                verification_item="log",
                verification_count=3
            ))

        # 2. Craft planks if current inventory planks are insufficient
        if planks < needed_planks:
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "planks", "count": 4},
                description="Craft wooden planks from logs",
                verification_item="planks",
                verification_count=4
            ))

        # 3. Craft crafting table if missing
        if not has_table:
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "crafting_table", "count": 1},
                description="Craft a crafting table",
                verification_item="crafting_table",
                verification_count=1
            ))

        # 4. Craft sticks if missing
        if sticks < 2:
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "stick", "count": 4},
                description="Craft wooden sticks",
                verification_item="stick",
                verification_count=2
            ))

        # 5. Craft wooden pickaxe
        steps.append(PlanStep(
            action="craft_item",
            arguments={"item_name": "wooden_pickaxe", "count": 1},
            description="Craft a wooden pickaxe at crafting table",
            verification_item="wooden_pickaxe",
            verification_count=1
        ))

        return steps

    def _plan_stone_pickaxe(self, inv_dict: Dict[str, int]) -> List[PlanStep]:
        # If already possessing stone_pickaxe or better pickaxe, return empty
        if any(inv_dict.get(p, 0) > 0 for p in ("stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe")):
            return []

        steps: List[PlanStep] = []
        has_wood_pick = any(inv_dict.get(p, 0) > 0 for p in ("wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe"))
        has_table = inv_dict.get("crafting_table", 0) > 0
        cobble = self._count_cobblestone(inv_dict)
        sticks = inv_dict.get("stick", 0) + inv_dict.get("sticks", 0)

        # 1. Prerequisites: wooden pickaxe if no mining tool present and cobble missing
        if cobble < 3 and not has_wood_pick:
            wood_steps = self._plan_wooden_pickaxe(inv_dict)
            steps.extend(wood_steps)

        # 2. Crafting table if missing
        if not has_table and not any(s.action == "craft_item" and s.arguments.get("item_name") == "crafting_table" for s in steps):
            planks = self._count_planks(inv_dict)
            if planks < 4:
                steps.append(PlanStep(
                    action="craft_item",
                    arguments={"item_name": "planks", "count": 4},
                    description="Craft wooden planks for crafting table",
                    verification_item="planks",
                    verification_count=4
                ))
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "crafting_table", "count": 1},
                description="Craft a crafting table",
                verification_item="crafting_table",
                verification_count=1
            ))

        # 3. Collect cobblestone
        if cobble < 3:
            needed_cobble = 3 - cobble
            steps.append(PlanStep(
                action="collect_block",
                arguments={"block_name": "cobblestone", "count": max(3, needed_cobble)},
                description=f"Mine {max(3, needed_cobble)} cobblestone with wooden pickaxe",
                verification_item="cobblestone",
                verification_count=3
            ))

        # 4. Sticks
        if sticks < 2 and not any(s.action == "craft_item" and s.arguments.get("item_name") == "stick" for s in steps):
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "stick", "count": 4},
                description="Craft wooden sticks",
                verification_item="stick",
                verification_count=2
            ))

        # 5. Craft stone pickaxe
        steps.append(PlanStep(
            action="craft_item",
            arguments={"item_name": "stone_pickaxe", "count": 1},
            description="Craft stone pickaxe at crafting table",
            verification_item="stone_pickaxe",
            verification_count=1
        ))

        return steps

    def _plan_furnace(self, inv_dict: Dict[str, int]) -> List[PlanStep]:
        # If already possessing furnace, return empty
        if inv_dict.get("furnace", 0) > 0:
            return []

        steps: List[PlanStep] = []
        has_wood_pick = any(inv_dict.get(p, 0) > 0 for p in ("wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe"))
        has_table = inv_dict.get("crafting_table", 0) > 0
        cobble = self._count_cobblestone(inv_dict)

        # 1. Mining pickaxe required to mine cobblestone
        if cobble < 8 and not has_wood_pick:
            steps.extend(self._plan_wooden_pickaxe(inv_dict))

        # 2. Crafting table if missing
        if not has_table and not any(s.action == "craft_item" and s.arguments.get("item_name") == "crafting_table" for s in steps):
            planks = self._count_planks(inv_dict)
            if planks < 4:
                steps.append(PlanStep(
                    action="craft_item",
                    arguments={"item_name": "planks", "count": 4},
                    description="Craft wooden planks for crafting table",
                    verification_item="planks",
                    verification_count=4
                ))
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "crafting_table", "count": 1},
                description="Craft a crafting table",
                verification_item="crafting_table",
                verification_count=1
            ))

        # 3. Cobblestone (8 required for furnace)
        if cobble < 8:
            needed_cobble = 8 - cobble
            steps.append(PlanStep(
                action="collect_block",
                arguments={"block_name": "cobblestone", "count": max(8, needed_cobble)},
                description=f"Mine {max(8, needed_cobble)} cobblestone for furnace",
                verification_item="cobblestone",
                verification_count=8
            ))

        # 4. Craft furnace
        steps.append(PlanStep(
            action="craft_item",
            arguments={"item_name": "furnace", "count": 1},
            description="Craft furnace at crafting table",
            verification_item="furnace",
            verification_count=1
        ))

        return steps

    def _plan_iron_pickaxe(self, inv_dict: Dict[str, int]) -> List[PlanStep]:
        # If already possessing iron_pickaxe or better pickaxe, return empty
        if any(inv_dict.get(p, 0) > 0 for p in ("iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe")):
            return []

        steps: List[PlanStep] = []
        has_stone_pick = any(inv_dict.get(p, 0) > 0 for p in ("stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe"))
        has_furnace = inv_dict.get("furnace", 0) > 0
        has_table = inv_dict.get("crafting_table", 0) > 0
        ingots = inv_dict.get("iron_ingot", 0)
        raw_iron = inv_dict.get("raw_iron", 0) + inv_dict.get("iron_ore", 0)
        sticks = inv_dict.get("stick", 0) + inv_dict.get("sticks", 0)

        # 1. Stone pickaxe & Furnace required if iron ingots need to be mined/smelted
        needed_ingots = max(0, 3 - ingots)
        if needed_ingots > 0:
            if raw_iron < needed_ingots and not has_stone_pick:
                steps.extend(self._plan_stone_pickaxe(inv_dict))
            if not has_furnace and not any(s.action == "craft_item" and s.arguments.get("item_name") == "furnace" for s in steps):
                steps.extend(self._plan_furnace(inv_dict))

        # 3. Crafting table if missing
        if not has_table and not any(s.action == "craft_item" and s.arguments.get("item_name") == "crafting_table" for s in steps):
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "crafting_table", "count": 1},
                description="Craft crafting table",
                verification_item="crafting_table",
                verification_count=1
            ))

        # 4. Raw iron mining & smelting
        if needed_ingots > 0:
            if raw_iron < needed_ingots:
                needed_raw = needed_ingots - raw_iron
                steps.append(PlanStep(
                    action="collect_block",
                    arguments={"block_name": "iron", "count": max(3, needed_raw), "optimal_y": 16},
                    description=f"Mine {max(3, needed_raw)} iron ore with stone pickaxe",
                    verification_item="raw_iron",
                    verification_count=needed_ingots
                ))
            steps.append(PlanStep(
                action="smelt_item",
                arguments={"input_item": "raw_iron", "count": needed_ingots},
                description=f"Smelt {needed_ingots} raw iron into iron ingots in furnace",
                verification_item="iron_ingot",
                verification_count=3
            ))

        # 5. Sticks
        if sticks < 2 and not any(s.action == "craft_item" and s.arguments.get("item_name") == "stick" for s in steps):
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "stick", "count": 4},
                description="Craft wooden sticks",
                verification_item="stick",
                verification_count=2
            ))

        # 6. Craft iron pickaxe
        steps.append(PlanStep(
            action="craft_item",
            arguments={"item_name": "iron_pickaxe", "count": 1},
            description="Craft iron pickaxe at crafting table",
            verification_item="iron_pickaxe",
            verification_count=1
        ))

        return steps

    def _plan_shield(self, inv_dict: Dict[str, int]) -> List[PlanStep]:
        # If already possessing shield, return empty
        if inv_dict.get("shield", 0) > 0:
            return []

        steps: List[PlanStep] = []
        has_table = inv_dict.get("crafting_table", 0) > 0
        has_stone_pick = any(inv_dict.get(p, 0) > 0 for p in ("stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe"))
        has_furnace = inv_dict.get("furnace", 0) > 0
        ingots = inv_dict.get("iron_ingot", 0)
        raw_iron = inv_dict.get("raw_iron", 0) + inv_dict.get("iron_ore", 0)
        planks = self._count_planks(inv_dict)
        logs = self._count_logs(inv_dict)

        # 1. Crafting table
        if not has_table:
            if planks < 4 and logs == 0:
                steps.append(PlanStep(
                    action="collect_block",
                    arguments={"block_name": "log", "count": 3},
                    description="Gather logs for crafting table and shield",
                    verification_item="log",
                    verification_count=3
                ))
            if planks < 4:
                steps.append(PlanStep(
                    action="craft_item",
                    arguments={"item_name": "planks", "count": 4},
                    description="Craft planks for crafting table",
                    verification_item="planks",
                    verification_count=4
                ))
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "crafting_table", "count": 1},
                description="Craft a crafting table",
                verification_item="crafting_table",
                verification_count=1
            ))

        # 2. Iron Ingot (1 required)
        if ingots < 1:
            if not has_stone_pick and raw_iron < 1:
                steps.extend(self._plan_stone_pickaxe(inv_dict))
            if not has_furnace and not any(s.action == "craft_item" and s.arguments.get("item_name") == "furnace" for s in steps):
                steps.extend(self._plan_furnace(inv_dict))
            if raw_iron < 1:
                steps.append(PlanStep(
                    action="collect_block",
                    arguments={"block_name": "iron", "count": 1, "optimal_y": 16},
                    description="Mine 1 iron ore with stone pickaxe",
                    verification_item="raw_iron",
                    verification_count=1
                ))
            steps.append(PlanStep(
                action="smelt_item",
                arguments={"input_item": "raw_iron", "count": 1},
                description="Smelt raw iron into 1 iron ingot",
                verification_item="iron_ingot",
                verification_count=1
            ))

        # 3. Planks (6 required)
        if planks < 6:
            if logs == 0 and not any(s.action == "collect_block" and s.arguments.get("block_name") == "log" for s in steps):
                steps.append(PlanStep(
                    action="collect_block",
                    arguments={"block_name": "log", "count": 3},
                    description="Gather logs for shield planks",
                    verification_item="log",
                    verification_count=3
                ))
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "planks", "count": 8},
                description="Craft wooden planks for shield",
                verification_item="planks",
                verification_count=6
            ))

        # 4. Craft shield
        steps.append(PlanStep(
            action="craft_item",
            arguments={"item_name": "shield", "count": 1},
            description="Craft shield (6 planks + 1 iron ingot)",
            verification_item="shield",
            verification_count=1
        ))

        return steps

    def _plan_iron_sword(self, inv_dict: Dict[str, int]) -> List[PlanStep]:
        # If already possessing iron_sword, return empty
        if inv_dict.get("iron_sword", 0) > 0:
            return []

        steps: List[PlanStep] = []
        has_table = inv_dict.get("crafting_table", 0) > 0
        has_stone_pick = any(inv_dict.get(p, 0) > 0 for p in ("stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe"))
        has_furnace = inv_dict.get("furnace", 0) > 0
        ingots = inv_dict.get("iron_ingot", 0)
        raw_iron = inv_dict.get("raw_iron", 0) + inv_dict.get("iron_ore", 0)
        sticks = inv_dict.get("stick", 0) + inv_dict.get("sticks", 0)

        # 1. Crafting table
        if not has_table:
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "crafting_table", "count": 1},
                description="Craft crafting table",
                verification_item="crafting_table",
                verification_count=1
            ))

        # 2. Iron ingots (2 required)
        needed_ingots = max(0, 2 - ingots)
        if needed_ingots > 0:
            if not has_stone_pick and raw_iron < needed_ingots:
                steps.extend(self._plan_stone_pickaxe(inv_dict))
            if not has_furnace and not any(s.action == "craft_item" and s.arguments.get("item_name") == "furnace" for s in steps):
                steps.extend(self._plan_furnace(inv_dict))
            if raw_iron < needed_ingots:
                needed_raw = needed_ingots - raw_iron
                steps.append(PlanStep(
                    action="collect_block",
                    arguments={"block_name": "iron", "count": max(2, needed_raw), "optimal_y": 16},
                    description=f"Mine {max(2, needed_raw)} iron ore",
                    verification_item="raw_iron",
                    verification_count=needed_ingots
                ))
            steps.append(PlanStep(
                action="smelt_item",
                arguments={"input_item": "raw_iron", "count": needed_ingots},
                description=f"Smelt {needed_ingots} raw iron into iron ingots",
                verification_item="iron_ingot",
                verification_count=2
            ))

        # 3. Stick (1 required)
        if sticks < 1 and not any(s.action == "craft_item" and s.arguments.get("item_name") == "stick" for s in steps):
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "stick", "count": 4},
                description="Craft wooden sticks",
                verification_item="stick",
                verification_count=1
            ))

        # 4. Craft iron sword
        steps.append(PlanStep(
            action="craft_item",
            arguments={"item_name": "iron_sword", "count": 1},
            description="Craft iron sword at crafting table",
            verification_item="iron_sword",
            verification_count=1
        ))

        return steps

    def _plan_bucket(self, inv_dict: Dict[str, int]) -> List[PlanStep]:
        # If already possessing bucket, return empty
        if inv_dict.get("bucket", 0) > 0 or inv_dict.get("water_bucket", 0) > 0:
            return []

        steps: List[PlanStep] = []
        has_table = inv_dict.get("crafting_table", 0) > 0
        has_stone_pick = any(inv_dict.get(p, 0) > 0 for p in ("stone_pickaxe", "iron_pickaxe", "diamond_pickaxe", "netherite_pickaxe"))
        has_furnace = inv_dict.get("furnace", 0) > 0
        ingots = inv_dict.get("iron_ingot", 0)
        raw_iron = inv_dict.get("raw_iron", 0) + inv_dict.get("iron_ore", 0)

        # 1. Crafting table
        if not has_table:
            steps.append(PlanStep(
                action="craft_item",
                arguments={"item_name": "crafting_table", "count": 1},
                description="Craft crafting table",
                verification_item="crafting_table",
                verification_count=1
            ))

        # 2. Iron ingots (3 required)
        needed_ingots = max(0, 3 - ingots)
        if needed_ingots > 0:
            if not has_stone_pick and raw_iron < needed_ingots:
                steps.extend(self._plan_stone_pickaxe(inv_dict))
            if not has_furnace and not any(s.action == "craft_item" and s.arguments.get("item_name") == "furnace" for s in steps):
                steps.extend(self._plan_furnace(inv_dict))
            if raw_iron < needed_ingots:
                needed_raw = needed_ingots - raw_iron
                steps.append(PlanStep(
                    action="collect_block",
                    arguments={"block_name": "iron", "count": max(3, needed_raw), "optimal_y": 16},
                    description=f"Mine {max(3, needed_raw)} iron ore",
                    verification_item="raw_iron",
                    verification_count=needed_ingots
                ))
            steps.append(PlanStep(
                action="smelt_item",
                arguments={"input_item": "raw_iron", "count": needed_ingots},
                description=f"Smelt {needed_ingots} raw iron into iron ingots",
                verification_item="iron_ingot",
                verification_count=3
            ))

        # 3. Craft bucket
        steps.append(PlanStep(
            action="craft_item",
            arguments={"item_name": "bucket", "count": 1},
            description="Craft iron bucket (3 iron ingots)",
            verification_item="bucket",
            verification_count=1
        ))

        return steps
