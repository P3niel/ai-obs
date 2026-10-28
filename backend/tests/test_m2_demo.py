import json
import subprocess  # nosec B404 - fixed-argv call of the demo script
import sys
import unittest
from pathlib import Path
from typing import Any

import m2_demo


_DEMO = Path(m2_demo.__file__).resolve()


class M2DemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = {
            item["scenario"]: item["result"]
            for item in m2_demo.run_scenarios()
        }

    def _drift(self, scenario: int) -> dict[str, Any]:
        drift = self.results[scenario]["drift"]
        self.assertIsInstance(drift, dict)
        return drift  # type: ignore[no-any-return]

    def test_runs_exactly_nine_scenarios(self) -> None:
        self.assertEqual(sorted(self.results), list(range(1, 10)))

    def test_matching_success_gives_zero_drift(self) -> None:
        drift = self._drift(1)
        self.assertTrue(drift["evaluable"])
        self.assertEqual(drift["drift"], 0)
        self.assertEqual(drift["signed_delta"], 0)

    def test_observed_failure_gives_negative_signed_delta(self) -> None:
        drift = self._drift(2)
        self.assertTrue(drift["evaluable"])
        self.assertEqual(drift["m1"]["value"], 0)
        self.assertEqual(drift["m2"]["value"], 1)
        self.assertEqual(drift["drift"], 1)
        self.assertEqual(drift["signed_delta"], -1)

    def test_missing_or_invalid_evidence_abstains_without_drift(
        self,
    ) -> None:
        for scenario, reason in (
            (3, "EVIDENCE_MISSING"),
            (4, "INTEGRITY_VALIDATION_FAILED"),
        ):
            with self.subTest(scenario=scenario):
                result = self.results[scenario]
                self.assertFalse(result["m1_produced"])
                self.assertEqual(result["reason_code"], reason)
                self.assertIsNone(result["drift"])

    def test_version_mismatch_is_non_evaluable_without_drift(self) -> None:
        drift = self._drift(5)
        self.assertFalse(drift["evaluable"])
        self.assertNotIn("drift", drift)
        self.assertNotIn("signed_delta", drift)
        self.assertEqual(
            [r["field"] for r in drift["non_evaluable_reasons"]],
            ["system_version"],
        )

    def test_m3_stability_values(self) -> None:
        self.assertTrue(self.results[6]["evaluable"])
        self.assertEqual(self.results[6]["m3"], 1.0)
        self.assertTrue(self.results[7]["evaluable"])
        self.assertEqual(self.results[7]["m3"], 0.5)

    def test_m3_with_nine_runs_is_non_evaluable(self) -> None:
        result = self.results[8]
        self.assertFalse(result["evaluable"])
        self.assertNotIn("m3", result)
        self.assertEqual(
            result["non_evaluable_reasons"][0]["code"],
            "INSUFFICIENT_COMPARABLE_RUNS",
        )

    def test_repeated_inputs_give_identical_results(self) -> None:
        self.assertTrue(self.results[9]["identical"])
        self.assertEqual(
            json.dumps(m2_demo.run_scenarios(), sort_keys=True),
            json.dumps(m2_demo.run_scenarios(), sort_keys=True),
        )

    def test_drift_output_carries_no_action_or_classification(self) -> None:
        drift = self._drift(2)
        forbidden = {"severity", "alert", "threshold", "class", "action"}
        self.assertFalse(forbidden & set(drift))

    def test_script_prints_json_from_a_separate_process(self) -> None:
        completed = subprocess.run(  # nosec B603 - fixed argv
            [sys.executable, str(_DEMO), "--json"],
            capture_output=True,
            text=True,
            check=True,
            cwd=_DEMO.parent.parent,
        )
        printed = json.loads(completed.stdout)
        self.assertEqual(len(printed), 9)


if __name__ == "__main__":
    unittest.main()
