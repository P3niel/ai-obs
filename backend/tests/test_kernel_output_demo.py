import json
import subprocess  # nosec B404 - fixed-argv call of the demo script
import sys
import unittest
from pathlib import Path

import kernel_output_demo


_DEMO = Path(kernel_output_demo.__file__).resolve()
_EXPECTED = {
    1: ("healthy", []),
    2: ("warning", []),
    3: ("critical", []),
    4: ("unclassified", ["HEALTH_REGION_UNDEFINED"]),
    5: ("unclassified", ["STABILITY_UNAVAILABLE"]),
    6: ("critical", []),
    7: ("unclassified", ["DRIFT_NOT_EVALUABLE"]),
}


class KernelOutputDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = kernel_output_demo.run_scenarios()

    def test_runs_exactly_seven_scenarios_with_expected_statuses(self) -> None:
        self.assertEqual(
            [item["scenario"] for item in self.results], list(range(1, 8))
        )
        for item in self.results:
            status, reasons = _EXPECTED[item["scenario"]]
            with self.subTest(scenario=item["scenario"]):
                self.assertEqual(item["output"]["status"], status)
                self.assertEqual(
                    [r["code"] for r in item["output"]["status_reasons"]],
                    reasons,
                )

    def test_every_output_is_simulated_and_non_authoritative(
        self,
    ) -> None:
        for item in self.results:
            with self.subTest(scenario=item["scenario"]):
                self.assertIs(item["simulated"], True)
                self.assertIs(item["output"]["authoritative"], False)

    def test_gap_and_stability_follow_the_real_evaluators(self) -> None:
        by_number = {item["scenario"]: item["output"] for item in self.results}
        self.assertAlmostEqual(by_number[1]["drift"]["value"], 0.05)
        self.assertAlmostEqual(by_number[1]["stability"]["value"], 0.95)
        self.assertAlmostEqual(by_number[4]["stability"]["m3"], 4 / 12)
        self.assertFalse(by_number[5]["stability"]["evaluable"])
        self.assertFalse(by_number[7]["drift"]["evaluable"])

    def test_results_are_deterministic(self) -> None:
        self.assertEqual(
            json.dumps(self.results, sort_keys=True),
            json.dumps(kernel_output_demo.run_scenarios(), sort_keys=True),
        )

    def _run(self, *args: str) -> str:
        completed = subprocess.run(  # nosec B603 - fixed argv, no shell
            [sys.executable, str(_DEMO), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout

    def test_json_mode_matches_the_scenarios(self) -> None:
        self.assertEqual(json.loads(self._run("--json")), self.results)

    def test_readable_output_labels_inputs_as_simulated(self) -> None:
        text = self._run()
        self.assertIn("SIMULATED", text)
        self.assertIn("not an input of the Safety Gate", text)
        for status in ("healthy", "warning", "critical", "unclassified"):
            self.assertIn(f"status = {status}", text)


if __name__ == "__main__":
    unittest.main()
