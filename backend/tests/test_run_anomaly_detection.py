import unittest

from app.kernel import InMemoryKernelStore
from app.operational_observability import AlertThresholds
from app.run_anomaly_detection import detect_run_anomalies


class RunAnomalyDetectionTest(unittest.TestCase):
    def test_detects_latency_error_and_stuck_run_anomalies(self) -> None:
        report = detect_run_anomalies(
            [
                _completed_run_payload(
                    run_id="run-latency",
                    expected_state={"status": "ok"},
                    observed_state={
                        "latency.ms": "900",
                        "status": "ok",
                    },
                    duration_ms=1000,
                    step_durations_ms={"collect": 400},
                ),
                _completed_run_payload(
                    run_id="run-error",
                    expected_state={"status": "ok"},
                    observed_state={"status": "failed"},
                    duration_ms=1000,
                    step_durations_ms={"collect": 400},
                ),
                _running_run_payload(),
                _completed_run_payload(
                    run_id="run-healthy",
                    expected_state={"status": "ok"},
                    observed_state={
                        "latency.ms": "120",
                        "status": "ok",
                    },
                    duration_ms=1000,
                    step_durations_ms={"collect": 400},
                ),
            ],
            thresholds=AlertThresholds(
                max_latency_ms=800,
                max_run_duration_ms=3000,
                max_step_duration_ms=1000,
                stuck_after_ms=60000,
            ),
        )
        payload = report.to_dict()

        self.assertEqual(payload["anomalyCount"], 3)
        self.assertEqual(payload["affectedRunCount"], 3)
        self.assertEqual(
            payload["conditionCounts"],
            {
                "ERRORED_STEP": 1,
                "SLOW_RUN": 1,
                "STUCK_RUN": 1,
            },
        )
        self.assertEqual(
            [anomaly["runId"] for anomaly in payload["anomalies"]],
            ["run-error", "run-latency", "run-stuck"],
        )
        self.assertTrue(
            any(
                anomaly["details"].get("maxLatencyMs") == 900
                for anomaly in payload["anomalies"]
            )
        )

    def test_filters_non_scope_alert_conditions(self) -> None:
        report = detect_run_anomalies(
            [
                _completed_run_payload(
                    run_id="run-slow-step-mismatch",
                    expected_state={"status": "ok", "mode": "green"},
                    observed_state={"status": "ok", "mode": "red"},
                    duration_ms=1000,
                    step_durations_ms={"collect": 2000},
                )
            ],
            thresholds=AlertThresholds(
                max_latency_ms=800,
                max_run_duration_ms=3000,
                max_step_duration_ms=1000,
                stuck_after_ms=60000,
            ),
        )

        self.assertEqual(report.to_dict()["anomalies"], [])
        self.assertEqual(report.anomaly_count, 0)


def _completed_run_payload(
    *,
    run_id: str,
    expected_state: dict[str, str],
    observed_state: dict[str, str],
    duration_ms: int,
    step_durations_ms: dict[str, int],
) -> dict:
    store = InMemoryKernelStore()
    store.create_run(run_id)
    store.append_step(
        run_id,
        step_id="collect",
        name="collect service health",
        expected_state=expected_state,
    )
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
    payload = store.get_run("run-stuck").to_dict()
    payload["metadata"] = {"updatedAgeMs": 70000}
    return payload
