"""Unit tests for Phase 5 Enchanting Engine, Tactical Blueprints, and Void Bridging."""
import unittest
from ai.enchanting import (
    calculate_enchanting_readiness,
    get_best_item_to_enchant,
    calculate_missing_enchanting_materials,
    should_prioritize_enchanting,
    get_bookshelf_positions
)
from ai.blueprints import (
    is_blast_resistant,
    get_nether_outpost_layout,
    get_bridge_step_vectors,
    get_enderman_canopy_layout
)
from ai.tools import MINECRAFT_TOOLS
from ai.planner import AutonomousCoopBrain

class TestEnchantingAndBlueprints(unittest.TestCase):
    """Test suite validating Autonomous Enchanting, Tactical Blueprints, and Void Bridging."""

    def test_enchanting_readiness_evaluation(self):
        """Verify enchanting readiness calculations with different levels of preparation."""
        # Unprepared bot
        inv_empty = {}
        status = calculate_enchanting_readiness(inv_empty, xp_level=0)
        self.assertFalse(status["ready"])
        self.assertEqual(status["recommended_tier"], 1)

        # Mid-tier prepared bot
        inv_mid = {
            "enchanting_table": 1,
            "lapis_lazuli": 5,
            "diamond_sword": 1
        }
        status_mid = calculate_enchanting_readiness(inv_mid, xp_level=16)
        self.assertTrue(status_mid["ready"])
        self.assertEqual(status_mid["target_gear"], "diamond_sword")
        self.assertEqual(status_mid["recommended_tier"], 2)

        # High-tier level 30 bot
        status_high = calculate_enchanting_readiness(inv_mid, xp_level=32)
        self.assertTrue(status_high["ready"])
        self.assertEqual(status_high["recommended_tier"], 3)

    def test_best_gear_selection(self):
        """Verify priority ranking picks diamond sword over iron armor, etc."""
        inv = {
            "iron_helmet": 1,
            "iron_sword": 1,
            "diamond_pickaxe": 1,
            "diamond_sword": 1
        }
        best = get_best_item_to_enchant(inv)
        self.assertEqual(best, "diamond_sword")

        inv_no_sword = {
            "iron_helmet": 1,
            "bow": 1
        }
        best_bow = get_best_item_to_enchant(inv_no_sword)
        self.assertEqual(best_bow, "bow")

    def test_missing_materials_calculation(self):
        """Verify calculation of missing items needed to craft table and enchant."""
        inv = {"obsidian": 2, "diamond": 1}
        missing = calculate_missing_enchanting_materials(inv, xp_level=5)
        missing_str = " ".join(missing)
        self.assertIn("obsidian", missing_str)
        self.assertIn("diamond", missing_str)
        self.assertIn("lapis_lazuli", missing_str)
        self.assertIn("XP levels", missing_str)

    def test_should_prioritize_enchanting(self):
        """Verify conditions that trigger autonomous gear enchanting."""
        inv = {
            "enchanting_table": 1,
            "lapis_lazuli": 4,
            "diamond_sword": 1
        }
        self.assertTrue(should_prioritize_enchanting(inv, xp_level=16))
        self.assertFalse(should_prioritize_enchanting(inv, xp_level=5))

    def test_bookshelf_geometry(self):
        """Verify bookshelf coordinates generate proper 5x5 perimeter with 1-block gap."""
        positions = get_bookshelf_positions(0, 64, 0, max_count=15)
        self.assertEqual(len(positions), 15)
        for x, y, z in positions:
            self.assertTrue(y in (64, 65))
            dist_sq = x * x + z * z
            # Bookshelves must be placed 2 blocks away horizontally
            self.assertTrue(dist_sq >= 4)

    def test_blast_resistant_filter(self):
        """Verify blast resistance recognition for Ghast explosion immunity."""
        self.assertTrue(is_blast_resistant("cobblestone"))
        self.assertTrue(is_blast_resistant("cobbled_deepslate"))
        self.assertTrue(is_blast_resistant("blackstone"))
        self.assertTrue(is_blast_resistant("stone_bricks"))
        self.assertFalse(is_blast_resistant("dirt"))
        self.assertFalse(is_blast_resistant("oak_planks"))
        self.assertFalse(is_blast_resistant("netherrack"))

    def test_nether_outpost_layout(self):
        """Verify layout builds full perimeter walls and ceiling with a doorway."""
        blocks = get_nether_outpost_layout(10, 60, 20)
        self.assertGreater(len(blocks), 20)
        # Check roof block
        self.assertIn((10, 63, 20), blocks)
        # Check south doorway at y=0,1 (dx=0, dz=2 -> 10, y, 22) is kept open
        self.assertNotIn((10, 60, 22), blocks)
        self.assertNotIn((10, 61, 22), blocks)

    def test_bridge_vectors(self):
        """Verify safe bridging displacements and sneak requirement."""
        steps_north = get_bridge_step_vectors("north", distance=3)
        self.assertEqual(len(steps_north), 3)
        for s in steps_north:
            self.assertTrue(s["sneak_required"])
            self.assertEqual(s["place_offset"][1], -1)

        self.assertEqual(steps_north[0]["place_offset"], (0, -1, -1))
        self.assertEqual(steps_north[2]["place_offset"], (0, -1, -3))

    def test_enderman_canopy_layout(self):
        """Verify 3x3 low ceiling layout at height Y+2."""
        canopy = get_enderman_canopy_layout(5, 70, 5)
        roof_blocks = [b for b in canopy if b[1] == 72]
        self.assertEqual(len(roof_blocks), 9)

    def test_tools_registered(self):
        """Verify enchant_gear, build_nether_outpost, and bridge_chasm are in MINECRAFT_TOOLS."""
        tool_names = [t["function"]["name"] for t in MINECRAFT_TOOLS]
        self.assertIn("enchant_gear", tool_names)
        self.assertIn("build_nether_outpost", tool_names)
        self.assertIn("bridge_chasm", tool_names)

    def test_planner_nether_outpost_fallback(self):
        """Verify planner fortifies Nether portal upon arrival when cobblestone is present."""
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer")
        state = {
            "dimension": "the_nether",
            "nether_outpost_built": False,
            "health": 20,
            "food": 20
        }
        inv = {
            "cobblestone": 32,
            "stone_pickaxe": 1
        }
        goal = {"target": "nether_portal", "stage": "NETHER"}
        action = brain.generate_fallback_action(goal=goal, inv=inv, owner_info=None, state=state)
        self.assertEqual(action["name"], "build_nether_outpost")

    def test_planner_enchanting_fallback(self):
        """Verify planner prioritizes gear enchanting when holding diamond gear, table, lapis and XP."""
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer")
        state = {
            "dimension": "overworld",
            "xp_level": 20,
            "health": 20,
            "food": 20
        }
        inv = {
            "enchanting_table": 1,
            "lapis_lazuli": 6,
            "diamond_sword": 1,
            "diamond_pickaxe": 1
        }
        goal = {"target": "nether_portal", "stage": "NETHER"}
        action = brain.generate_fallback_action(goal=goal, inv=inv, owner_info=None, state=state)
        self.assertEqual(action["name"], "enchant_gear")

if __name__ == "__main__":
    unittest.main()
