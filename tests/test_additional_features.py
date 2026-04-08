from pathlib import Path
import shutil
import unittest
import uuid

import app
from rule_engine import evaluate, load_guidelines_json, load_rules_json
from scenario_store import load_saved_scenarios, save_compare_scenario, save_single_scenario


ROOT = Path(__file__).resolve().parents[1]
RULES = load_rules_json(ROOT / "rules.json")
GUIDELINES = load_guidelines_json(ROOT / "data" / "guidelines.json")


class AdditionalFeatureTests(unittest.TestCase):
    def make_temp_path(self) -> Path:
        root = ROOT / "tests" / "_tmp" / str(uuid.uuid4())
        root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root / "saved.json"

    def test_saved_scenarios_overwrite_by_name_and_keep_latest_values(self) -> None:
        path = self.make_temp_path()
        first = {
            "incident_scale": "local",
            "elapsed_hours": 12,
            "num_exposed": 10,
            "exposure_known": True,
            "partial_body_suspected": False,
            "internal_contamination_suspected": False,
            "symptom_severity": "none",
            "resource_level": "moderate",
        }
        second = dict(first)
        second["num_exposed"] = 120

        save_single_scenario("demo", first, path)
        save_single_scenario("demo", second, path)

        store = load_saved_scenarios(path)
        self.assertEqual(len(store["single"]), 1)
        self.assertEqual(store["single"][0]["name"], "demo")
        self.assertEqual(store["single"][0]["scenario"]["num_exposed"], 120)

    def test_saved_compare_scenarios_persist_a_and_b(self) -> None:
        path = self.make_temp_path()
        scenario_a = {
            "incident_scale": "regional",
            "elapsed_hours": 24,
            "num_exposed": 150,
            "exposure_known": False,
            "partial_body_suspected": False,
            "internal_contamination_suspected": False,
            "symptom_severity": "none",
            "resource_level": "minimal",
        }
        scenario_b = {
            "incident_scale": "local",
            "elapsed_hours": 12,
            "num_exposed": 10,
            "exposure_known": True,
            "partial_body_suspected": False,
            "internal_contamination_suspected": False,
            "symptom_severity": "none",
            "resource_level": "full",
        }

        save_compare_scenario("compare-demo", scenario_a, scenario_b, path)

        store = load_saved_scenarios(path)
        self.assertEqual(len(store["compare"]), 1)
        self.assertEqual(store["compare"][0]["scenario_a"]["num_exposed"], 150)
        self.assertEqual(store["compare"][0]["scenario_b"]["resource_level"], "full")

    def test_compare_difference_helpers_and_report_include_explanations(self) -> None:
        scenario_a = {
            "incident_scale": "local",
            "elapsed_hours": 12,
            "num_exposed": 10,
            "exposure_known": False,
            "partial_body_suspected": False,
            "internal_contamination_suspected": False,
            "symptom_severity": "severe",
            "resource_level": "full",
        }
        scenario_b = {
            "incident_scale": "regional",
            "elapsed_hours": 24,
            "num_exposed": 150,
            "exposure_known": True,
            "partial_body_suspected": False,
            "internal_contamination_suspected": False,
            "symptom_severity": "none",
            "resource_level": "minimal",
        }

        ev_a = evaluate(scenario_a, RULES, GUIDELINES)
        ev_b = evaluate(scenario_b, RULES, GUIDELINES)

        input_diffs = app._input_difference_bullets(scenario_a, scenario_b)
        decision_diffs = app._decision_difference_bullets(scenario_a, scenario_b, ev_a, ev_b)
        report = app._build_compare_report_markdown(scenario_a, scenario_b, ev_a, ev_b)

        self.assertTrue(any("가용 자원 수준" in line for line in input_diffs))
        self.assertTrue(any("대응 우선순위" in line for line in decision_diffs))
        self.assertIn("입력 차이 설명", report)
        self.assertIn("판단 차이 설명", report)


if __name__ == "__main__":
    unittest.main()
