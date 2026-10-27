"""Unit tests for Scenario Deliberation Engine (ai/scenario_engine.py).

Verifies:
1. ScenarioDetector detection rules:
   - TOOL_CRISIS_UNDERGROUND (Y < 50, no pickaxe/low durability, no wood)
   - NIGHT_SURVIVAL_AMBUSH (dark/night, hostiles present, unsheltered)
   - TERRAIN_BARRIER (cliff, lava barrier, ravine, or elevation stuck)
   - RESOURCE_WINDFALL (exposed diamond ore, ancient debris, >=4 iron, structures)
   - VILLAGE_DISCOVERY (village flag, villager or iron golem entities)
   - STANDARD_SURVIVAL (default baseline progression)
2. ScenarioFrame formatting & constraints:
   - Word count strictly <= 25 words
   - Strict format [SCENARIO] <type>: <situation> | Dilemma: <dilemma> | Options: <options>
3. Sensory prompt integration in build_cortex_sensory_prompt:
   - [SCENARIO] line rendered correctly between [ALERTS] and [OPPORTUNITIES]
   - Total prompt word count strictly < 160 words
4. ScenarioFrame fallback actions:
   - Valid actionable tool dicts for emergency situations
5. AutonomousCoopBrain integration:
   - Passes scenario to cortex.think_and_decide
   - Preserves LLM decision when Cortex is online
   - Executes scenario heuristic fallback when Cortex is offline on high urgency
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from ai.scenario_engine import ScenarioDetector, ScenarioFrame, ScenarioType
from ai.prompts import build_cortex_sensory_prompt
from ai.planner import AutonomousCoopBrain


class TestScenarioEngine(unittest.IsolatedAsyncioTestCase):
    """Test suite covering scenario detection, prompt framing, and planner integration."""

    def setUp(self):
        self.detector = ScenarioDetector()

    def test_detect_tool_crisis_underground(self):
        """Underground (Y < 50) without usable pickaxe and no wood triggers TOOL_CRISIS_UNDERGROUND."""
        state = {
            "position": {"x": 100, "y": 32, "z": -200},
            "is_day": True,
            "nearby_hostiles": [],
            "nearby_entities": []
        }
        inv_dict = {
            "cobblestone": 20,
            "dirt": 15,
            "torch": 8
        }
        frame = self.detector.detect_scenario(state, inv_dict)
        self.assertEqual(frame.scenario_type, ScenarioType.TOOL_CRISIS_UNDERGROUND)
        self.assertEqual(frame.urgency, 8)
        self.assertIn("mine_staircase", frame.candidate_tools)
        fallback = frame.get_fallback_action()
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback["name"], "mine_staircase")
        self.assertEqual(fallback["arguments"]["target_y"], 68)

    def test_detect_tool_crisis_underground_durability_low(self):
        """Underground with pickaxe durability < 5 and no wood triggers TOOL_CRISIS_UNDERGROUND."""
        state = {
            "position": {"x": 50, "y": 20, "z": 50},
            "in_cave": True,
            "tool_base": {
                "iron_pickaxe": {"durability": 3}
            }
        }
        inv_dict = {
            "iron_pickaxe": 1,
            "raw_iron": 5
        }
        frame = self.detector.detect_scenario(state, inv_dict)
        self.assertEqual(frame.scenario_type, ScenarioType.TOOL_CRISIS_UNDERGROUND)
        self.assertEqual(frame.urgency, 8)

    def test_detect_night_survival_ambush(self):
        """Hostiles nearby in darkness unsheltered triggers NIGHT_SURVIVAL_AMBUSH."""
        state = {
            "position": {"x": 0, "y": 68, "z": 0},
            "is_day": False,
            "day_phase": "Night",
            "light_level": 2,
            "is_sheltered": False,
            "health": 10,
            "nearby_hostiles": ["zombie (3m away)", "skeleton (7m away)"],
            "nearby_entities": [
                {"name": "zombie", "distance": 3.0, "is_hostile": True},
                {"name": "skeleton", "distance": 7.0, "is_hostile": True}
            ]
        }
        inv_dict = {"dirt": 16, "wooden_sword": 1}
        frame = self.detector.detect_scenario(state, inv_dict)
        self.assertEqual(frame.scenario_type, ScenarioType.NIGHT_SURVIVAL_AMBUSH)
        # Urgency is 9 when health < 12
        self.assertEqual(frame.urgency, 9)
        self.assertIn("build_shelter", frame.candidate_tools)
        fallback = frame.get_fallback_action()
        self.assertEqual(fallback["name"], "build_shelter")
        self.assertEqual(fallback["arguments"]["mode"], "auto")

    def test_detect_night_survival_ambush_with_bed(self):
        """Night survival ambush with bed in inventory suggests bed sleep fallback."""
        state = {
            "position": {"x": 0, "y": 68, "z": 0},
            "is_day": False,
            "day_phase": "Night",
            "is_sheltered": False,
            "health": 18,
            "nearby_hostiles": ["creeper (10m away)"]
        }
        inv_dict = {"red_bed": 1}
        frame = self.detector.detect_scenario(state, inv_dict)
        self.assertEqual(frame.scenario_type, ScenarioType.NIGHT_SURVIVAL_AMBUSH)
        self.assertEqual(frame.urgency, 7)  # health >= 12
        fallback = frame.get_fallback_action()
        self.assertEqual(fallback["name"], "sleep_in_bed")

    def test_detect_terrain_barrier(self):
        """Flagged cliff, lava hazard, ravine, or elevation stuck triggers TERRAIN_BARRIER."""
        state = {
            "position": {"x": 200, "y": 70, "z": 300},
            "is_day": True,
            "cliff_detected": True
        }
        inv_dict = {"cobblestone": 30, "water_bucket": 1}
        frame = self.detector.detect_scenario(state, inv_dict)
        self.assertEqual(frame.scenario_type, ScenarioType.TERRAIN_BARRIER)
        self.assertEqual(frame.urgency, 7)
        self.assertIn("pillar_jump", frame.candidate_tools)
        fallback = frame.get_fallback_action()
        self.assertEqual(fallback["name"], "pillar_jump")
        self.assertEqual(fallback["arguments"]["height"], 3)

    def test_detect_resource_windfall_diamonds(self):
        """Spotted exposed diamond ore triggers RESOURCE_WINDFALL when goal is lower tier."""
        state = {
            "position": {"x": 10, "y": 64, "z": 20},
            "is_day": True,
            "nearby_blocks": [
                {"name": "deepslate_diamond_ore", "distance": 4.5}
            ]
        }
        inv_dict = {"iron_pickaxe": 1}
        goal = {"target": "wooden_pickaxe", "stage": "early"}
        frame = self.detector.detect_scenario(state, inv_dict, current_goal=goal)
        self.assertEqual(frame.scenario_type, ScenarioType.RESOURCE_WINDFALL)
        self.assertEqual(frame.urgency, 6)
        self.assertIn("diamond_ore", frame.situation)
        fallback = frame.get_fallback_action()
        self.assertEqual(fallback["name"], "collect_block")
        self.assertIn("diamond", fallback["arguments"]["block_name"])

    def test_detect_resource_windfall_structure(self):
        """Discovered structure (desert_pyramid) triggers RESOURCE_WINDFALL."""
        state = {
            "position": {"x": -300, "y": 65, "z": 150},
            "is_day": True,
            "discovered_structures": ["desert_pyramid"]
        }
        inv_dict = {"bread": 5}
        goal = {"target": "stone_pickaxe"}
        frame = self.detector.detect_scenario(state, inv_dict, current_goal=goal)
        self.assertEqual(frame.scenario_type, ScenarioType.RESOURCE_WINDFALL)
        self.assertEqual(frame.metadata.get("resource"), "desert_pyramid")

    def test_detect_village_discovery(self):
        """Village flagged or villager in nearby entities triggers VILLAGE_DISCOVERY."""
        state = {
            "position": {"x": 500, "y": 70, "z": -400},
            "is_day": True,
            "nearby_entities": [
                {"name": "villager", "distance": 8.0},
                {"name": "iron_golem", "distance": 12.0}
            ]
        }
        inv_dict = {"apple": 3}
        frame = self.detector.detect_scenario(state, inv_dict)
        self.assertEqual(frame.scenario_type, ScenarioType.VILLAGE_DISCOVERY)
        self.assertEqual(frame.urgency, 6)
        fallback = frame.get_fallback_action()
        self.assertEqual(fallback["name"], "farm_crops")

    def test_detect_standard_survival(self):
        """Ordinary state defaults to STANDARD_SURVIVAL."""
        state = {
            "position": {"x": 0, "y": 65, "z": 0},
            "is_day": True,
            "health": 20,
            "food": 20,
            "nearby_hostiles": [],
            "nearby_entities": []
        }
        inv_dict = {"oak_log": 5, "stone_pickaxe": 1}
        frame = self.detector.detect_scenario(state, inv_dict)
        self.assertEqual(frame.scenario_type, ScenarioType.STANDARD_SURVIVAL)
        self.assertEqual(frame.urgency, 3)
        self.assertIsNone(frame.get_fallback_action())

    def test_format_prompt_line_structure_and_bounds(self):
        """ScenarioFrame.format_prompt_line produces correct structure and is strictly <= 25 words."""
        all_types = [
            ScenarioType.TOOL_CRISIS_UNDERGROUND,
            ScenarioType.NIGHT_SURVIVAL_AMBUSH,
            ScenarioType.TERRAIN_BARRIER,
            ScenarioType.RESOURCE_WINDFALL,
            ScenarioType.VILLAGE_DISCOVERY,
            ScenarioType.STANDARD_SURVIVAL,
        ]
        for st in all_types:
            frame = ScenarioFrame(
                scenario_type=st,
                situation="test situation active",
                dilemma="choice A vs choice B",
                candidate_tools=["tool1", "tool2", "tool3"],
                urgency=5
            )
            line = frame.format_prompt_line()
            words = line.split()
            self.assertLessEqual(len(words), 25)
            self.assertTrue(line.startswith(f"[SCENARIO] {st.value}:"))
            self.assertIn("| Dilemma: choice A vs choice B", line)
            self.assertIn("| Options: tool1, tool2, tool3", line)

    def test_format_prompt_line_truncation_on_overflow(self):
        """ScenarioFrame.format_prompt_line truncates cleanly when input would exceed 25 words."""
        frame = ScenarioFrame(
            scenario_type=ScenarioType.NIGHT_SURVIVAL_AMBUSH,
            situation="5 hostile mobs including a creeper and 2 skeletons surrounded the player in total darkness on rough terrain",
            dilemma="burrow underground into a quick dirt shelter or fight aggressively with sword or pillar jump 4 blocks high",
            candidate_tools=["build_shelter", "attack_target", "pillar_jump", "go_to_coordinates"],
            urgency=9
        )
        prompt_line = frame.format_prompt_line()
        words = prompt_line.split()
        self.assertLessEqual(len(words), 25)
        self.assertEqual(len(words), 25)

    def test_sensory_prompt_integration_and_token_budget(self):
        """build_cortex_sensory_prompt integrates [SCENARIO] and remains strictly < 160 words."""
        scenario = ScenarioFrame(
            scenario_type=ScenarioType.TOOL_CRISIS_UNDERGROUND,
            situation="Y=28, pickaxe broken/low, no wood",
            dilemma="staircase to surface vs scavenge cave vs bare-hand",
            candidate_tools=["mine_staircase", "collect_block", "go_to_coordinates"],
            urgency=8
        )
        state = {
            "health": 14,
            "food": 10,
            "light": 4,
            "day_phase": "Day",
            "position": {"x": 42.5, "y": 28.0, "z": -120.3},
            "biome": "dripstone_caves",
            "nearby_entities": [{"name": "bat", "distance": 4}],
            "nearby_blocks": [{"name": "deepslate", "distance": 1}]
        }
        inv_dict = {"cobblestone": 12, "raw_copper": 4}
        alerts = ["Pickaxe broken! No wood carried."]
        prompt = build_cortex_sensory_prompt(
            state=state,
            inv_dict=inv_dict,
            alerts=alerts,
            scenario=scenario,
            goal={"target": "iron_pickaxe"}
        )

        # Check [SCENARIO] line is present
        self.assertIn("[SCENARIO] TOOL_CRISIS_UNDERGROUND:", prompt)
        # Check order: after [ALERTS] and before [OPPORTUNITIES]
        alerts_idx = prompt.find("[ALERTS]")
        scenario_idx = prompt.find("[SCENARIO]")
        opps_idx = prompt.find("[OPPORTUNITIES]")
        self.assertTrue(alerts_idx < scenario_idx < opps_idx, f"Order incorrect: alerts={alerts_idx}, scenario={scenario_idx}, opps={opps_idx}")

        # Check total word count strictly under 160 words
        word_count = len(prompt.split())
        self.assertLess(word_count, 160, f"Prompt exceeded 160 words: {word_count}")

    async def test_planner_passes_scenario_to_cortex(self):
        """AutonomousCoopBrain detects scenario, stores in state, and passes to cortex."""
        mock_cortex = MagicMock()
        mock_decision = {
            "thought": "Digging staircase to escape cave crisis.",
            "tool_calls": [{"name": "mine_staircase", "arguments": {"target_y": 68}}]
        }
        mock_cortex.think_and_decide = AsyncMock(return_value=mock_decision)

        brain = AutonomousCoopBrain(ollama_brain=None)
        brain.cortex = mock_cortex

        state = {
            "position": {"x": 50, "y": 30, "z": 50},
            "is_day": True,
            "health": 20,
            "food": 20,
            "inventory_items": [{"name": "dirt", "count": 10}]
        }

        result = await brain.decide_next_action(state)
        self.assertIsNotNone(result)
        self.assertEqual(state.get("current_scenario"), ScenarioType.TOOL_CRISIS_UNDERGROUND.value)

        # Verify think_and_decide received scenario argument
        mock_cortex.think_and_decide.assert_called_once()
        call_kwargs = mock_cortex.think_and_decide.call_args.kwargs
        self.assertIn("scenario", call_kwargs)
        scenario_arg = call_kwargs["scenario"]
        self.assertIsInstance(scenario_arg, ScenarioFrame)
        self.assertEqual(scenario_arg.scenario_type, ScenarioType.TOOL_CRISIS_UNDERGROUND)

    async def test_planner_executes_fallback_when_cortex_offline_high_urgency(self):
        """When Cortex is offline (returns None) on high urgency (>=7), planner executes scenario fallback."""
        mock_cortex = MagicMock()
        mock_cortex.think_and_decide = AsyncMock(return_value=None)

        brain = AutonomousCoopBrain(ollama_brain=None)
        brain.cortex = mock_cortex

        # High urgency scenario: TOOL_CRISIS_UNDERGROUND (urgency 8)
        state = {
            "position": {"x": 10, "y": 25, "z": 10},
            "is_day": True,
            "health": 20,
            "food": 20,
            "inventory_items": [{"name": "cobblestone", "count": 10}]
        }

        result = await brain.decide_next_action(state)
        self.assertIsNotNone(result)
        tool_calls = result.get("tool_calls", [])
        self.assertEqual(len(tool_calls), 1)
        # Should execute mine_staircase fallback action
        self.assertEqual(tool_calls[0]["name"], "mine_staircase")
        self.assertEqual(tool_calls[0]["arguments"]["target_y"], 68)


if __name__ == "__main__":
    unittest.main()
