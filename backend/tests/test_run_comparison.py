import unittest

from app.kernel import InMemoryKernelStore
from app.run_comparison import DifferenceKind
from app.run_comparison import DifferenceSeverity
from app.run_comparison import RunComparisonError
from app.run_comparison import compare_kernel_runs


class RunComparisonTest(unittest.TestCase):
    def test_marks_small_latency_delta_as_noise(self) -> None:
        baseline = _completed_run_payload(
            run_id="run-baseline",
            status="ok",
            latency_ms=100,
            duration_ms=1000,
            step_durations_ms={"collect": 400, "evaluate": 600},
        )
        candidate = _completed_run_payload(
            run_id="run-candidate",
            status="ok",
            latency_ms=120,
            duration_ms=1000,
            step_durations_ms={"collect": 400, "evaluate": 600},
        )

        comparison = compare_kernel_runs(baseline, candidate)
        payload = comparison.to_dict()

        self.assertFalse(comparison.has_material_differences)
        self.assertEqual(comparison.material_difference_count, 0)
        self.assertEqual(comparison.noise_difference_count, 1)
        self.assertEqual(payload["latencyDelta"]["delta"], 20)
        self.assertEqual(
            payload["differences"],
            [
                {
                    "kind": "LATENCY_DELTA",
                    "severity": "NOISE",
                    "message": "Run max latency changed.",
                    "details": {
                        "baseline": 100,
                        "candidate": 120,
                        "delta": 20,
                    },
                }
            ],
        )

    def test_detects_material_latency_step_and_behavior_differences(
        self,
    ) -> None:
        baseline = _completed_run_payload(
            run_id="run-baseline",
            status="ok",
            latency_ms=100,
            duration_ms=1000,
            step_durations_ms={"collect": 400, "evaluate": 600},
        )
        candidate = _completed_run_payload(
            run_id="run-candidate",
            status="failed",
            latency_ms=900,
            duration_ms=2200,
            step_durations_ms={"collect": 1500, "evaluate": 600},
            step_order=("evaluate", "collect", "notify"),
        )

        comparison = compare_kernel_runs(baseline, candidate)
        kinds = {difference.kind for difference in comparison.differences}
        severities = {
            difference.kind: difference.severity
            for difference in comparison.differences
        }

        self.assertTrue(comparison.has_material_differences)
        self.assertIn(DifferenceKind.LATENCY_DELTA, kinds)
        self.assertIn(DifferenceKind.DURATION_DELTA, kinds)
        self.assertIn(DifferenceKind.STEP_ADDED, kinds)
        self.assertIn(DifferenceKind.STEP_ORDER, kinds)
        self.assertIn(DifferenceKind.STEP_DURATION_DELTA, kinds)
        self.assertIn(DifferenceKind.OBSERVED_STATE, kinds)
        self.assertIn(DifferenceKind.EVALUATION_RESULT, kinds)
        self.assertEqual(
            severities[DifferenceKind.LATENCY_DELTA],
            DifferenceSeverity.MATERIAL,
        )

    def test_compares_kernel_run_instances(self) -> None:
        baseline = _kernel_run(
            run_id="run-baseline",
            status="ok",
            latency_ms=100,
        )
        candidate = _kernel_run(
            run_id="run-candidate",
            status="failed",
            latency_ms=100,
        )

        comparison = compare_kernel_runs(baseline, candidate)
        kinds = {difference.kind for difference in comparison.differences}

        self.assertIn(DifferenceKind.OBSERVED_STATE, kinds)
        self.assertIn(DifferenceKind.EVALUATION_RESULT, kinds)

    def test_rejects_payloads_that_cannot_be_compared_safely(self) -> None:
        valid = _completed_run_payload(
            run_id="run-valid",
            status="ok",
            latency_ms=100,
            duration_ms=1000,
            step_durations_ms={},
        )

        with self.assertRaises(RunComparisonError):
            compare_kernel_runs(
                valid,
                {
                    "id": "run-invalid",
                    "steps": [],
                },
            )

        invalid_observation = _completed_run_payload(
            run_id="run-invalid-observation",
            status="ok",
            latency_ms=100,
            duration_ms=1000,
            step_durations_ms={},
        )
        invalid_observation["observations"][0]["stepId"] = "missing"
        with self.assertRaises(RunComparisonError):
            compare_kernel_runs(valid, invalid_observation)


def _kernel_run(
    *,
    run_id: str,
    status: str,
    latency_ms: int,
):
    store = InMemoryKernelStore()
    _populate_run(
        store,
        run_id=run_id,
        status=status,
        latency_ms=latency_ms,
        step_order=("collect", "evaluate"),
    )
    return store.get_run(run_id)


def _completed_run_payload(
    *,
    run_id: str,
    status: str,
    latency_ms: int,
    duration_ms: int,
    step_durations_ms: dict[str, int],
    step_order: tuple[str, ...] = ("collect", "evaluate"),
) -> dict:
    store = InMemoryKernelStore()
    _populate_run(
        store,
        run_id=run_id,
        status=status,
        latency_ms=latency_ms,
        step_order=step_order,
    )
    payload = store.get_run(run_id).to_dict()
    payload["metadata"] = {
        "durationMs": duration_ms,
        "stepDurationsMs": step_durations_ms,
    }
    return payload


def _populate_run(
    store: InMemoryKernelStore,
    *,
    run_id: str,
    status: str,
    latency_ms: int,
    step_order: tuple[str, ...],
) -> None:
    store.create_run(run_id)
    for step_id in step_order:
        if step_id == "collect":
            store.append_step(
                run_id,
                step_id="collect",
                name="collect service health",
                expected_state={
                    "latency.ms": str(latency_ms),
                    "status": "ok",
                },
            )
            store.record_observation(
                run_id,
                step_id="collect",
                observation_id="obs-collect",
                fact="Collected service health.",
                observed_state={
                    "latency.ms": str(latency_ms),
                    "status": status,
                },
            )
        elif step_id == "evaluate":
            store.append_step(
                run_id,
                step_id="evaluate",
                name="evaluate health decision",
                expected_state={"decision": "accept"},
            )
            store.record_observation(
                run_id,
                step_id="evaluate",
                observation_id="obs-evaluate",
                fact="Evaluation completed.",
                observed_state={"decision": "accept"},
            )
        elif step_id == "notify":
            store.append_step(
                run_id,
                step_id="notify",
                name="notify downstream owner",
                expected_state={"notification": "sent"},
            )
            store.record_observation(
                run_id,
                step_id="notify",
                observation_id="obs-notify",
                fact="Notification was sent.",
                observed_state={"notification": "sent"},
            )
        else:  # pragma: no cover - test helper guard.
            raise AssertionError(f"Unknown step id: {step_id}")
    store.complete_run(run_id)
