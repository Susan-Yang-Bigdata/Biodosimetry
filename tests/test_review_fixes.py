from pathlib import Path
import unittest

from recommendation_helpers import recommended_next_actions
from rule_engine import evaluate, load_guidelines_json, load_rules_json


ROOT = Path(__file__).resolve().parents[1]
RULES = load_rules_json(ROOT / "rules.json")
GUIDELINES = load_guidelines_json(ROOT / "data" / "guidelines.json")


class ReviewFixTests(unittest.TestCase):
    def test_critical_summary_uses_highest_priority_rules_only(self) -> None:
        scenario = {
            "incident_scale": "local",
            "elapsed_hours": 12,
            "num_exposed": 10,
            "exposure_known": False,
            "partial_body_suspected": False,
            "internal_contamination_suspected": False,
            "symptom_severity": "severe",
            "resource_level": "full",
        }

        ev = evaluate(scenario, RULES, GUIDELINES)

        self.assertEqual(ev.synthesized_priority, "critical")
        self.assertEqual([t.rule_id for t in ev.summary_triggered], ["R005"])
        self.assertIn("[R005]", ev.biodosimetry_direction)
        self.assertNotIn("[R008]", ev.biodosimetry_direction)
        self.assertFalse(any("세포유전학" in item for item in ev.assay_options))

    def test_critical_actions_skip_lower_priority_rule_actions(self) -> None:
        scenario = {
            "incident_scale": "local",
            "elapsed_hours": 12,
            "num_exposed": 10,
            "exposure_known": False,
            "partial_body_suspected": False,
            "internal_contamination_suspected": False,
            "symptom_severity": "severe",
            "resource_level": "full",
        }

        ev = evaluate(scenario, RULES, GUIDELINES)
        actions = recommended_next_actions(scenario, ev)

        self.assertTrue(any("의료기관 응급·임상 경로" in action for action in actions))
        self.assertFalse(any("정밀 검사" in action for action in actions))

    def test_no_match_fallback_actions_are_unique(self) -> None:
        scenario = {
            "incident_scale": "local",
            "elapsed_hours": 12,
            "num_exposed": 10,
            "exposure_known": True,
            "partial_body_suspected": False,
            "internal_contamination_suspected": False,
            "symptom_severity": "none",
            "resource_level": "moderate",
        }

        ev = evaluate(scenario, RULES, GUIDELINES)
        actions = recommended_next_actions(scenario, ev)

        self.assertEqual(ev.triggered, ())
        self.assertEqual(len(actions), 3)
        self.assertEqual(len(actions), len(set(actions)))


if __name__ == "__main__":
    unittest.main()
