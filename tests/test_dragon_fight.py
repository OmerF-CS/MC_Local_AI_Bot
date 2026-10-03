"""Unit tests for Phase 4: Ender Dragon Combat & Victory Sequence (unittest compatible)."""
import unittest
from ai.progression_tree import get_current_progression_goal, MILESTONES
from ai.tools import MINECRAFT_TOOLS
from ai.knowledge_base import get_relevant_tactic
from ai.planner import AutonomousCoopBrain


class TestDragonFight(unittest.TestCase):

    def test_end_tools_registered(self):
        """Verify Phase 4 End combat tools exist and are properly formatted."""
        tool_names = [t["function"]["name"] for t in MINECRAFT_TOOLS if t.get("type") == "function"]
        self.assertIn("destroy_end_crystals", tool_names)
        self.assertIn("fight_ender_dragon", tool_names)
        self.assertIn("enter_exit_portal", tool_names)

        dragon_tool = next(t for t in MINECRAFT_TOOLS if t["function"]["name"] == "fight_ender_dragon")
        self.assertIn("tactic", dragon_tool["function"]["parameters"]["properties"])

    def test_progression_in_the_end(self):
        """Verify progression milestones adapt dynamically inside the End dimension."""
        empty_inv = {}

        # 1. End crystals remain
        state_crystals = {
            "dimension": "the_end",
            "end_crystals_count": 4,
            "dragon_defeated": False
        }
        goal = get_current_progression_goal(empty_inv, state_crystals)
        self.assertEqual(goal["stage"], "DESTROY_CRYSTALS")
        self.assertEqual(goal["target"], "end_crystal")

        # 2. Crystals eliminated, dragon alive
        state_dragon = {
            "dimension": "the_end",
            "end_crystals_count": 0,
            "dragon_defeated": False,
            "dragon_health": 200
        }
        goal = get_current_progression_goal(empty_inv, state_dragon)
        self.assertEqual(goal["stage"], "SLAY_DRAGON")
        self.assertEqual(goal["target"], "fight_ender_dragon")

        # 3. Dragon dead, exit portal active
        state_won = {
            "dimension": "the_end",
            "end_crystals_count": 0,
            "dragon_defeated": True,
            "dragon_health": 0
        }
        goal = get_current_progression_goal(empty_inv, state_won)
        self.assertEqual(goal["stage"], "GAME_VICTORY")
        self.assertEqual(goal["target"], "enter_exit_portal")

    def test_knowledge_base_end_tactics(self):
        """Verify RAG knowledge base serves Dragon tactics when in the End."""
        state = {
            "dimension": "the_end",
            "health": 20,
            "food": 20,
            "nearby_hostiles": []
        }
        tactic = get_relevant_tactic(state)
        self.assertTrue("End Crystals" in tactic or "Ender Dragon" in tactic)

    def test_planner_fallback_in_the_end(self):
        """Verify AutonomousCoopBrain executes correct fallback actions during End boss phases."""
        brain = AutonomousCoopBrain(ollama_brain=None, bot_owner="Omer")

        # Phase A: Destroying crystals
        state_a = {
            "dimension": "the_end",
            "end_crystals_count": 3,
            "dragon_defeated": False
        }
        goal_a = {"target": "end_crystal", "stage": "DESTROY_CRYSTALS"}
        action_a = brain.generate_fallback_action(goal=goal_a, inv={}, owner_info=None, state=state_a)
        self.assertEqual(action_a["name"], "destroy_end_crystals")

        # Phase B: Fighting dragon
        state_b = {
            "dimension": "the_end",
            "end_crystals_count": 0,
            "dragon_defeated": False
        }
        goal_b = {"target": "fight_ender_dragon", "stage": "SLAY_DRAGON"}
        action_b = brain.generate_fallback_action(goal=goal_b, inv={}, owner_info=None, state=state_b)
        self.assertEqual(action_b["name"], "fight_ender_dragon")
        self.assertEqual(action_b["arguments"].get("tactic"), "melee_sword")

        # Phase C: Game won -> entering exit portal
        state_c = {
            "dimension": "the_end",
            "end_crystals_count": 0,
            "dragon_defeated": True
        }
        goal_c = {"target": "enter_exit_portal", "stage": "GAME_VICTORY"}
        action_c = brain.generate_fallback_action(goal=goal_c, inv={}, owner_info=None, state=state_c)
        self.assertEqual(action_c["name"], "enter_exit_portal")


if __name__ == "__main__":
    unittest.main()
