import unittest

from app.kernel import InMemoryKernelStore
from app.operational_observability import AlertCondition
from app.operational_observability import AlertThresholds
from app.operational_observability import NotificationMessage
from app.operational_observability import NotificationProvider
from app.operational_observability import build_notification_message
from app.operational_observability import detect_alerts
from app.operational_observability import dispatch_alert_notifications
from app.operational_observability import summarize_kernel_runs


class RecordingClient:
    def __init__(self) -> None:
        self.messages: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> None:
        self.messages.append(message)


class FailingClient:
    def send(self, message: NotificationMessage) -> None:
        raise RuntimeError(f"{message.provider.value} webhook unavailable")


class OperationalObservabilityTest(unittest.TestCase):
    def test_summarizes_kernel_runs_with_latency_and_step_metrics(
        self,
    ) -> None:
        metrics = summarize_kernel_runs(
            [
                _completed_run_payload(
                    run_id="run-fast",
                    result="MATCH",
                    duration_ms=1000,
                    latency_ms=120,
                    step_durations_ms={"collect": 400, "evaluate": 600},
                ),
                _completed_run_payload(
                    run_id="run-slow",
                    result="MISMATCH",
                    duration_ms=5000,
                    latency_ms=900,
                    step_durations_ms={"collect": 1400, "evaluate": 800},
                ),
                _running_run_payload(),
            ]
        )
        payload = metrics.to_dict()

        self.assertEqual(metrics.run_count, 3)
        self.assertEqual(metrics.completed_count, 2)
        self.assertEqual(metrics.running_count, 1)
        self.assertEqual(metrics.observation_count, 3)
        self.assertEqual(metrics.max_latency_ms, 900)
        self.assertEqual(metrics.average_latency_ms, 510)
        self.assertEqual(metrics.max_duration_ms, 5000)
        self.assertEqual(payload["evaluations"]["matchCount"], 1)
        self.assertEqual(payload["evaluations"]["mismatchCount"], 1)
        self.assertEqual(
            payload["stepDurations"],
            [
                {
                    "stepId": "collect",
                    "sampleCount": 2,
                    "averageDurationMs": 900,
                    "maxDurationMs": 1400,
                },
                {
                    "stepId": "evaluate",
                    "sampleCount": 2,
                    "averageDurationMs": 700,
                    "maxDurationMs": 800,
                },
                {
                    "stepId": "notify",
                    "sampleCount": 1,
                    "averageDurationMs": 500,
                    "maxDurationMs": 500,
                },
            ],
        )

    def test_detects_slow_stuck_errored_and_evaluation_alerts(self) -> None:
        thresholds = AlertThresholds(
            max_latency_ms=800,
            max_run_duration_ms=3000,
            max_step_duration_ms=1000,
            stuck_after_ms=60000,
        )

        alerts = detect_alerts(
            [
                _completed_run_payload(
                    run_id="run-slow",
                    result="MISMATCH",
                    duration_ms=5000,
                    latency_ms=900,
                    step_durations_ms={"collect": 1400},
                ),
                _running_run_payload(),
            ],
            thresholds=thresholds,
        )
        conditions = {alert.condition for alert in alerts}

        self.assertTrue(
            {
                AlertCondition.SLOW_RUN,
                AlertCondition.SLOW_STEP,
                AlertCondition.STUCK_RUN,
                AlertCondition.ERRORED_STEP,
                AlertCondition.EVALUATION_FAILURE,
            }.issubset(conditions)
        )
        self.assertTrue(
            all(alert.to_dict()["runId"] for alert in alerts)
        )

    def test_dispatches_notifications_without_blocking_on_failures(
        self,
    ) -> None:
        alert = detect_alerts(
            [
                _completed_run_payload(
                    run_id="run-slow",
                    result="MATCH",
                    duration_ms=5000,
                    latency_ms=900,
                    step_durations_ms={},
                )
            ],
            thresholds=AlertThresholds(max_run_duration_ms=3000),
        )[0]
        slack_client = RecordingClient()

        results = dispatch_alert_notifications(
            [alert],
            {
                NotificationProvider.SLACK: slack_client,
                NotificationProvider.DISCORD: FailingClient(),
            },
        )
        payloads = [result.to_dict() for result in results]

        self.assertEqual(len(slack_client.messages), 1)
        self.assertIn("run-slow", slack_client.messages[0].body)
        self.assertEqual(len(payloads), 2)
        self.assertIn(
            {
                "provider": "SLACK",
                "alertCondition": "SLOW_RUN",
                "runId": "run-slow",
                "delivered": True,
                "error": None,
            },
            payloads,
        )
        self.assertTrue(
            any(
                payload["provider"] == "DISCORD"
                and payload["delivered"] is False
                and "webhook unavailable" in str(payload["error"])
                for payload in payloads
            )
        )

    def test_builds_provider_specific_messages(self) -> None:
        alert = detect_alerts(
            [
                _completed_run_payload(
                    run_id="run-mismatch",
                    result="MISMATCH",
                    duration_ms=1000,
                    latency_ms=120,
                    step_durations_ms={},
                )
            ]
        )[0]

        slack_message = build_notification_message(
            NotificationProvider.SLACK,
            alert,
        )
        discord_message = build_notification_message(
            NotificationProvider.DISCORD,
            alert,
        )

        self.assertEqual(slack_message.provider, NotificationProvider.SLACK)
        self.assertEqual(
            discord_message.provider,
            NotificationProvider.DISCORD,
        )
        self.assertIn("AI-Obs alert", slack_message.title)
        self.assertIn(" - ", discord_message.body)


def _completed_run_payload(
    *,
    run_id: str,
    result: str,
    duration_ms: int,
    latency_ms: int,
    step_durations_ms: dict[str, int],
) -> dict:
    store = InMemoryKernelStore()
    store.create_run(run_id)
    expected_state = {"status": "ok"}
    if result == "MATCH":
        expected_state["latency.ms"] = str(latency_ms)
    store.append_step(
        run_id,
        step_id="collect",
        name="collect service health",
        expected_state=expected_state,
    )
    observed_state = {
        "latency.ms": str(latency_ms),
        "status": "ok" if result == "MATCH" else "failed",
    }
    store.record_observation(
        run_id,
        step_id="collect",
        observation_id="obs-collect",
        fact="Collected service health.",
        observed_state=observed_state,
    )
    store.complete_run(run_id)
    payload = store.get_run(run_id).to_dict()
    payload["metadata"] = {
        "durationMs": duration_ms,
        "stepDurationsMs": step_durations_ms,
    }
    return payload


def _running_run_payload() -> dict:
    store = InMemoryKernelStore()
    store.create_run("run-stuck")
    store.append_step(
        "run-stuck",
        step_id="notify",
        name="notify provider",
        expected_state={"status": "ok"},
    )
    store.record_observation(
        "run-stuck",
        step_id="notify",
        observation_id="obs-notify",
        fact="Notification provider returned failure.",
        observed_state={"provider.status": "failed"},
    )
    payload = store.get_run("run-stuck").to_dict()
    payload["metadata"] = {
        "updatedAgeMs": 70000,
        "stepDurationsMs": {"notify": 500},
    }
    return payload
