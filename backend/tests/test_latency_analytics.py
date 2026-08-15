import unittest

from app.kernel import InMemoryKernelStore
from app.latency_analytics import summarize_latency_analytics


class LatencyAnalyticsTest(unittest.TestCase):
    def test_exposes_core_latency_aggregates(self) -> None:
        summary = summarize_latency_analytics(
            [
                _completed_run_payload(
                    run_id="run-fast",
                    duration_ms=1000,
                    latency_ms=120,
                    step_durations_ms={"collect": 400, "evaluate": 600},
                ),
                _completed_run_payload(
                    run_id="run-slow",
                    duration_ms=5000,
                    latency_ms=900,
                    step_durations_ms={"collect": 1400, "evaluate": 800},
                ),
                _running_run_payload(),
            ]
        )
        payload = summary.to_dict()

        self.assertEqual(payload["runCount"], 3)
        self.assertEqual(payload["completedCount"], 2)
        self.assertEqual(payload["runningCount"], 1)
        self.assertEqual(payload["averageLatencyMs"], 510)
        self.assertEqual(payload["maxLatencyMs"], 900)
        self.assertEqual(payload["averageDurationMs"], 3000)
        self.assertEqual(payload["maxDurationMs"], 5000)
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


def _completed_run_payload(
    *,
    run_id: str,
    duration_ms: int,
    latency_ms: int,
    step_durations_ms: dict[str, int],
) -> dict:
    store = InMemoryKernelStore()
    store.create_run(run_id)
    store.append_step(
        run_id,
        step_id="collect",
        name="collect service health",
        expected_state={"status": "ok"},
    )
    store.record_observation(
        run_id,
        step_id="collect",
        observation_id="obs-collect",
        fact="Collected service health.",
        observed_state={"latency.ms": str(latency_ms), "status": "ok"},
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
    store.create_run("run-active")
    store.append_step(
        "run-active",
        step_id="notify",
        name="notify provider",
        expected_state={"status": "ok"},
    )
    payload = store.get_run("run-active").to_dict()
    payload["metadata"] = {"stepDurationsMs": {"notify": 500}}
    return payload
