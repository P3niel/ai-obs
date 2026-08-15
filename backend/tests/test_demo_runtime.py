import json
import unittest

from app.demo_runtime import DemoEvent
from app.demo_runtime import generate_demo_events
from app.demo_runtime import render_alert
from app.demo_runtime import render_dashboard
from app.demo_runtime import render_event_card
from app.demo_runtime import render_event_input
from app.demo_runtime import render_metrics
from app.demo_runtime import render_storage_summary
from app.demo_runtime import run_console_demo
from app.demo_runtime import run_demo_pipeline
from app.operational_observability import AlertCondition


class DemoEventGeneratorTest(unittest.TestCase):
    def test_generates_deterministic_sequence(self) -> None:
        first = generate_demo_events()
        second = generate_demo_events()

        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)
        self.assertEqual(
            [event.run_id for event in first],
            [f"run-{index:03d}" for index in range(1, 13)],
        )

    def test_includes_a_failed_and_a_high_latency_event(self) -> None:
        events = generate_demo_events()

        self.assertEqual(
            sum(1 for event in events if event.outcome == "FAILED"),
            1,
        )
        self.assertTrue(any(event.latency_ms > 1000 for event in events))


class DemoPipelineTest(unittest.TestCase):
    def test_pipeline_traverses_every_stage_for_every_event(self) -> None:
        results = run_demo_pipeline()

        self.assertEqual(len(results), 12)
        final = results[-1]

        self.assertEqual(final.metrics.run_count, 12)
        payload = final.metrics.to_dict()
        self.assertEqual(payload["evaluations"]["matchCount"], 11)
        self.assertEqual(payload["evaluations"]["mismatchCount"], 1)
        self.assertEqual(payload["maxLatencyMs"], 5100)

    def test_slow_run_alert_fires_for_the_high_latency_event(self) -> None:
        results = run_demo_pipeline()
        slow_run_result = next(
            result
            for result in results
            if result.event.run_id == "run-008"
        )

        conditions = {alert.condition for alert in slow_run_result.new_alerts}
        self.assertIn(AlertCondition.SLOW_RUN, conditions)

    def test_errored_step_and_evaluation_failure_fire_for_the_failed_event(
        self,
    ) -> None:
        results = run_demo_pipeline()
        failed_result = next(
            result
            for result in results
            if result.event.run_id == "run-005"
        )

        conditions = {alert.condition for alert in failed_result.new_alerts}
        self.assertIn(AlertCondition.ERRORED_STEP, conditions)
        self.assertIn(AlertCondition.EVALUATION_FAILURE, conditions)

    def test_alerts_are_only_reported_as_new_once(self) -> None:
        results = run_demo_pipeline()

        all_new_keys = [
            (alert.run_id, alert.condition.value, alert.message)
            for result in results
            for alert in result.new_alerts
        ]
        self.assertEqual(len(all_new_keys), len(set(all_new_keys)))

    def test_anomaly_report_reflects_supported_conditions_only(self) -> None:
        results = run_demo_pipeline()
        final_report = results[-1].anomaly_report

        self.assertGreaterEqual(final_report.anomaly_count, 2)
        self.assertIn("SLOW_RUN", final_report.condition_counts())
        self.assertIn("ERRORED_STEP", final_report.condition_counts())

    def test_pipeline_is_deterministic_across_runs(self) -> None:
        first = run_demo_pipeline()
        second = run_demo_pipeline()

        self.assertEqual(
            [step.metrics.to_dict() for step in first],
            [step.metrics.to_dict() for step in second],
        )


class DemoRenderingTest(unittest.TestCase):
    def test_render_event_input_matches_event_to_dict(self) -> None:
        event = DemoEvent("run-001", 742, "SUCCESS")
        rendered = render_event_input(event)

        self.assertEqual(json.loads(rendered), event.to_dict())

    def test_render_event_card_includes_core_fields(self) -> None:
        card = render_event_card(DemoEvent("run-001", 742, "SUCCESS"))

        self.assertIn("EVENT RECEIVED", card)
        self.assertIn("run-001", card)
        self.assertIn("742 ms", card)
        self.assertIn("SUCCESS", card)

    def test_render_metrics_reports_success_and_error_counts(self) -> None:
        results = run_demo_pipeline()
        rendered = render_metrics(results[-1].metrics)

        self.assertIn("Runs", rendered)
        self.assertIn("Success", rendered)
        self.assertIn("Errors", rendered)
        self.assertIn("11", rendered)

    def test_render_alert_includes_rule_run_and_message(self) -> None:
        results = run_demo_pipeline()
        alert = next(
            alert
            for result in results
            for alert in result.new_alerts
            if alert.condition == AlertCondition.SLOW_RUN
        )
        rendered = render_alert(alert)

        self.assertIn("ANOMALY DETECTED", rendered)
        self.assertIn("SLOW_RUN", rendered)
        self.assertIn("run-008", rendered)

    def test_render_dashboard_lists_active_alerts(self) -> None:
        results = run_demo_pipeline()
        final = results[-1]
        rendered = render_dashboard(final.metrics, final.alerts)

        self.assertIn("AI OBSERVABILITY - RUNTIME DEMO", rendered)
        self.assertIn("Current Alerts", rendered)
        self.assertIn("SLOW_RUN", rendered)

    def test_render_storage_summary_lists_every_stored_run(self) -> None:
        results = run_demo_pipeline()
        rendered = render_storage_summary(
            [step.run_payload for step in results]
        )

        for step in results:
            self.assertIn(step.event.run_id, rendered)
        self.assertIn("COMPLETED", rendered)


class DemoConsoleEntryPointTest(unittest.TestCase):
    def test_run_console_demo_prints_every_stage(self) -> None:
        printed: list[str] = []
        run_console_demo(print_fn=printed.append)

        joined = "\n".join(printed)
        self.assertIn("EVENT RECEIVED", joined)
        self.assertIn("ANOMALY DETECTED", joined)
        self.assertIn("AI OBSERVABILITY - RUNTIME DEMO", joined)
        self.assertIn("STORED RUNS", joined)
        self.assertIn("Detection engine summary", joined)

    def test_run_console_demo_is_quiet_about_input_by_default(self) -> None:
        printed: list[str] = []
        run_console_demo(print_fn=printed.append)

        self.assertNotIn("INPUT", printed)

    def test_run_console_demo_verbose_prints_input_before_output(
        self,
    ) -> None:
        printed: list[str] = []
        run_console_demo(verbose=True, print_fn=printed.append)

        input_index = printed.index("INPUT")
        output_index = next(
            index
            for index, line in enumerate(printed)
            if "EVENT RECEIVED" in line
        )
        first_input_payload = json.loads(printed[input_index + 1])

        self.assertLess(input_index, output_index)
        self.assertEqual(first_input_payload["run_id"], "run-001")
        self.assertEqual(printed.count("INPUT"), 12)


if __name__ == "__main__":
    unittest.main()
