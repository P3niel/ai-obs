import unittest
from datetime import datetime
from datetime import timezone

from app.canonical_mapping import CanonicalMappingError
from app.canonical_mapping import to_canonical_latency_metrics
from app.canonical_mapping import to_canonical_run
from app.canonical_mapping import to_canonical_status
from app.kernel import InMemoryKernelStore
from app.operational_observability import summarize_kernel_runs


class CanonicalStatusMappingTest(unittest.TestCase):
    def test_maps_reachable_runtime_statuses(self) -> None:
        self.assertEqual(to_canonical_status("RUNNING"), "running")
        self.assertEqual(to_canonical_status("COMPLETED"), "completed")

    def test_maps_case_insensitively(self) -> None:
        self.assertEqual(to_canonical_status("running"), "running")
        self.assertEqual(to_canonical_status("Completed"), "completed")

    def test_maps_not_yet_reachable_future_statuses(self) -> None:
        self.assertEqual(to_canonical_status("FAILED"), "failed")
        self.assertEqual(to_canonical_status("ERROR"), "failed")
        self.assertEqual(to_canonical_status("CANCELLED"), "cancelled")
        self.assertEqual(to_canonical_status("STUCK"), "stuck")

    def test_unknown_status_is_not_guessed(self) -> None:
        self.assertEqual(to_canonical_status("SOMETHING_ELSE"), "unknown")
        self.assertEqual(to_canonical_status(""), "unknown")


class CanonicalRunMappingTest(unittest.TestCase):
    def _build_completed_run(self) -> dict:
        moments = iter(
            [
                datetime(2026, 8, 3, 9, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 8, 3, 9, 0, 1, 0, tzinfo=timezone.utc),
                datetime(2026, 8, 3, 9, 0, 2, 0, tzinfo=timezone.utc),
                datetime(2026, 8, 3, 9, 0, 3, 0, tzinfo=timezone.utc),
            ]
        )
        store = InMemoryKernelStore(clock=lambda: next(moments))
        store.create_run("run-canonical-001")
        store.append_step(
            "run-canonical-001",
            step_id="model_call",
            name="model call",
            expected_state={"status": "ok"},
        )
        store.record_observation(
            "run-canonical-001",
            step_id="model_call",
            observation_id="obs-1",
            fact="Model call completed.",
            observed_state={"status": "ok"},
        )
        store.complete_run("run-canonical-001")
        return store.get_run("run-canonical-001").to_dict()

    def test_maps_kernel_run_to_canonical_shape(self) -> None:
        payload = self._build_completed_run()

        canonical = to_canonical_run(payload)

        self.assertEqual(
            canonical.to_dict(),
            {
                "run_id": "run-canonical-001",
                "status": "completed",
                "run_start_timestamp": "2026-08-03T09:00:00.000Z",
                "run_end_timestamp": "2026-08-03T09:00:03.000Z",
                "steps": [
                    {
                        "step_id": "model_call",
                        "step_start_timestamp": "2026-08-03T09:00:01.000Z",
                        "step_end_timestamp": "2026-08-03T09:00:02.000Z",
                    }
                ],
            },
        )

    def test_accepts_kernel_run_object_directly(self) -> None:
        store = InMemoryKernelStore()
        run = store.create_run("run-canonical-002")

        canonical = to_canonical_run(run)

        self.assertEqual(canonical.run_id, "run-canonical-002")
        self.assertEqual(canonical.status, "running")
        self.assertEqual(canonical.steps, ())

    def test_requires_id_field(self) -> None:
        with self.assertRaises(CanonicalMappingError):
            to_canonical_run({"status": "RUNNING"})


class CanonicalLatencyMetricsMappingTest(unittest.TestCase):
    def test_maps_latency_fields_to_canonical_metric_names(self) -> None:
        store = InMemoryKernelStore()
        store.create_run("run-latency-001")
        store.append_step(
            "run-latency-001",
            step_id="model_call",
            name="model call",
        )
        store.record_observation(
            "run-latency-001",
            step_id="model_call",
            observation_id="obs-1",
            fact="Model call completed.",
            observed_state={"latency_ms": "742"},
        )
        store.complete_run("run-latency-001")
        payload = store.get_run("run-latency-001").to_dict()

        metrics = summarize_kernel_runs([payload])
        canonical_metrics = to_canonical_latency_metrics(metrics)

        self.assertEqual(
            canonical_metrics,
            {
                "step.mean.duration.ms": 742.0,
                "step.max.duration.ms": 742.0,
            },
        )

    def test_maps_missing_latency_to_none(self) -> None:
        store = InMemoryKernelStore()
        store.create_run("run-latency-002")
        payload = store.get_run("run-latency-002").to_dict()

        metrics = summarize_kernel_runs([payload])
        canonical_metrics = to_canonical_latency_metrics(metrics)

        self.assertEqual(
            canonical_metrics,
            {
                "step.mean.duration.ms": None,
                "step.max.duration.ms": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
