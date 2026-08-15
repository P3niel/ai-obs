import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


class DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.run_data_chunks: list[str] = []
        self.controls: set[str] = set()
        self.ids: set[str] = set()
        self._in_run_data = False

    def handle_starttag(self, tag, attrs) -> None:
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.links.append(attributes.get("href", ""))
        if tag == "script" and attributes.get("src"):
            self.scripts.append(attributes["src"])
        if tag == "script" and attributes.get("id") == "run-data":
            self._in_run_data = True
        if "data-state-filter" in attributes:
            self.controls.add(f"state:{attributes['data-state-filter']}")
        if "data-result-filter" in attributes:
            self.controls.add(f"result:{attributes['data-result-filter']}")

    def handle_endtag(self, tag) -> None:
        if tag == "script":
            self._in_run_data = False

    def handle_data(self, data) -> None:
        if self._in_run_data:
            self.run_data_chunks.append(data)


class StaticDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.frontend_dir = cls.repo_root / "frontend"
        cls.html_path = cls.frontend_dir / "dashboard.html"
        cls.css_path = cls.frontend_dir / "dashboard.css"
        cls.js_path = cls.frontend_dir / "dashboard.js"
        parser = DashboardParser()
        parser.feed(cls.html_path.read_text(encoding="utf-8"))
        cls.parser = parser
        cls.runs = json.loads("".join(parser.run_data_chunks))

    def test_dashboard_assets_are_local(self) -> None:
        self.assertEqual(self.parser.links, ["./dashboard.css"])
        self.assertEqual(self.parser.scripts, ["./dashboard.js"])

    def test_dashboard_exposes_expected_filters_and_regions(self) -> None:
        self.assertTrue(
            {
                "state:ALL",
                "state:SUCCESS",
                "state:FAILED",
                "state:RUNNING",
                "result:ALL",
                "result:MATCH",
                "result:MISMATCH",
            }.issubset(self.parser.controls)
        )
        self.assertTrue(
            {
                "run-list",
                "detail-title",
                "timeline",
                "evaluation-delta",
                "summary-total",
                "summary-errors",
                "metric-status",
                "metric-error",
                "metric-cost",
                "error-summary",
                "error-severity",
            }.issubset(self.parser.ids)
        )

    def test_embedded_runs_match_kernel_dashboard_contract(self) -> None:
        self.assertGreaterEqual(len(self.runs), 4)
        statuses = {run["status"] for run in self.runs}
        results = {
            run["evaluation"]["result"]
            for run in self.runs
            if run["evaluation"] is not None
        }

        self.assertIn("COMPLETED", statuses)
        self.assertIn("RUNNING", statuses)
        self.assertIn("MATCH", results)
        self.assertIn("MISMATCH", results)
        state_categories = {self._run_state_for(run) for run in self.runs}
        self.assertEqual(
            {"SUCCESS", "FAILED", "RUNNING"},
            state_categories,
        )

        for run in self.runs:
            with self.subTest(run=run["id"]):
                self.assertIn("id", run)
                self.assertIn("status", run)
                self.assertIsInstance(run["steps"], list)
                self.assertIsInstance(run["observations"], list)
                self.assertEqual(run["stepCount"], len(run["steps"]))
                self.assertEqual(
                    run["observationCount"],
                    len(run["observations"]),
                )
                for step in run["steps"]:
                    self.assertIn("events", step)
                    self.assertIsInstance(step["events"], list)
                self.assertIn("metadata", run)
                self.assertIsInstance(run["metadata"]["durationMs"], int)
                self.assertRegex(
                    run["metadata"]["estimatedCostUsd"],
                    r"^\d+\.\d{2}$",
                )

    def test_representative_runs_include_error_signal_source(self) -> None:
        errored_runs = [
            run for run in self.runs if self._errored_steps_for(run)
        ]

        self.assertTrue(errored_runs)
        for run in errored_runs:
            with self.subTest(run=run["id"]):
                self.assertEqual(run["evaluation"]["result"], "MISMATCH")
                self.assertTrue(self._errored_steps_for(run))

    def test_completed_runs_include_evaluation_delta(self) -> None:
        completed_runs = [
            run for run in self.runs if run["status"] == "COMPLETED"
        ]
        self.assertTrue(completed_runs)

        for run in completed_runs:
            with self.subTest(run=run["id"]):
                evaluation = run["evaluation"]
                self.assertIsNotNone(evaluation)
                self.assertEqual(evaluation["runId"], run["id"])
                self.assertIn(evaluation["result"], {"MATCH", "MISMATCH"})
                self.assertIn("expectedState", evaluation)
                self.assertIn("observedState", evaluation)
                self.assertIn("matches", evaluation)
                self.assertIn("missing", evaluation)
                self.assertIn("unexpected", evaluation)
                self.assertIn("mismatched", evaluation)

    def test_dashboard_css_uses_responsive_constraints(self) -> None:
        css = self.css_path.read_text(encoding="utf-8")

        self.assertIn("@media (max-width: 960px)", css)
        self.assertIn("@media (max-width: 620px)", css)
        for value in re.findall(r"border-radius:\s*(\d+)px", css):
            self.assertLessEqual(int(value), 8)

    def test_dashboard_javascript_uses_kernel_artifact_fields(self) -> None:
        javascript = self.js_path.read_text(encoding="utf-8")

        for token in (
            "data-state-filter",
            "runStateFor(run)",
            "run.evaluation.result",
            "run.steps.length",
            "run.observations.length",
            "step.events",
            "observation.stepId",
            "observation.observedState",
            "observedStateSummary(",
            "timeline-events",
            "run.metadata.durationMs",
            "run.metadata.estimatedCostUsd",
            "window.location.hash",
            "URLSearchParams",
            "errorSignalFor(run)",
            "renderErrorSummary(run)",
            "formatEstimatedCost(",
            "selectors.metricCost",
            "selectors.metricStatus",
            "syncHash(runId)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, javascript)

    def test_dashboard_javascript_has_no_live_transport(self) -> None:
        javascript = self.js_path.read_text(encoding="utf-8")

        for token in (
            "fetch(",
            "XMLHttpRequest",
            "EventSource",
            "WebSocket",
            "setInterval(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, javascript)

    def test_dashboard_copy_names_timeline_filter_surface(self) -> None:
        html = self.html_path.read_text(encoding="utf-8")

        self.assertIn("aria-label=\"Run state filter\"", html)
        self.assertIn("data-state-filter=\"SUCCESS\"", html)
        self.assertIn("data-state-filter=\"FAILED\"", html)
        self.assertIn("data-state-filter=\"RUNNING\"", html)
        self.assertIn("<h3 id=\"timeline-title\">Timeline</h3>", html)

    def test_dashboard_copy_names_run_explorer(self) -> None:
        html = self.html_path.read_text(encoding="utf-8")

        self.assertIn("<title>AI-Obs Run Explorer</title>", html)
        self.assertIn("<h1>Run Explorer</h1>", html)

    @staticmethod
    def _errored_steps_for(run) -> set[str]:
        errored = set()
        error_values = {"error", "errored", "failed", "failure"}
        for observation in run["observations"]:
            for key, value in observation.get("observedState", {}).items():
                key_token = str(key).lower()
                value_token = str(value).strip().lower()
                has_error_key = (
                    "status" in key_token or "result" in key_token
                )
                if (
                    observation.get("stepId")
                    and has_error_key
                    and value_token in error_values
                ):
                    errored.add(observation["stepId"])
        return errored

    @classmethod
    def _run_state_for(cls, run) -> str:
        if run["status"] == "RUNNING":
            return "RUNNING"
        if cls._errored_steps_for(run):
            return "FAILED"
        evaluation = run.get("evaluation")
        if evaluation and evaluation.get("result") == "MISMATCH":
            return "FAILED"
        return "SUCCESS"
