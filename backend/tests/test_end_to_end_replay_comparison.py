"""End-to-end test for the shared payload-coercion extraction.

Exercises the four modules that import their coercion helpers from
``app.payload_coercion`` (``operational_observability``, ``canonical_mapping``,
``replay``, and ``run_comparison``) together, over Kernel run payloads built
through the real ``InMemoryKernelStore``. The goal is to confirm the
extraction is behavior-preserving across every consumer in one integrated
pass, not just that each module's own unit tests still pass in isolation.
"""

import unittest

from app.canonical_mapping import to_canonical_run
from app.kernel import InMemoryKernelStore
from app.operational_observability import detect_alerts
from app.operational_observability import summarize_kernel_runs
from app.replay import ReplayPhase
from app.replay import build_replay_session
from app.run_comparison import compare_kernel_runs


def _record_run(
    store: InMemoryKernelStore,
    run_id: str,
    *,
    latency_ms: int,
    observed_status: str,
) -> dict:
    store.create_run(run_id)
    store.append_step(
        run_id,
        step_id="model_call",
        name="model call",
        expected_state={"status": "ok"},
    )
    store.record_observation(
        run_id,
        step_id="model_call",
        observation_id=f"{run_id}-obs",
        fact="Model call completed.",
        observed_state={
            "status": observed_status,
            "latency_ms": str(latency_ms),
        },
    )
    store.complete_run(run_id)
    payload = store.get_run(run_id).to_dict()
    payload["metadata"] = {
        "durationMs": latency_ms,
        "stepDurationsMs": {"model_call": latency_ms},
    }
    return payload


class PayloadCoercionEndToEndTest(unittest.TestCase):
    def test_shared_coercion_helpers_work_across_every_consumer(
        self,
    ) -> None:
        store = InMemoryKernelStore()
        baseline = _record_run(
            store, "run-e2e-baseline", latency_ms=400, observed_status="ok"
        )
        candidate = _record_run(
            store,
            "run-e2e-candidate",
            latency_ms=1200,
            observed_status="failed",
        )
        payloads = [baseline, candidate]

        # operational_observability: uses as_mapping, optional_number,
        # optional_text, sequence_of_mappings from payload_coercion.
        metrics = summarize_kernel_runs(payloads)
        self.assertEqual(metrics.run_count, 2)
        self.assertEqual(metrics.max_latency_ms, 1200.0)
        alerts = detect_alerts(payloads)
        self.assertTrue(
            any(alert.run_id == "run-e2e-candidate" for alert in alerts)
        )

        # canonical_mapping: uses optional_text from payload_coercion.
        canonical_runs = [to_canonical_run(payload) for payload in payloads]
        self.assertEqual(
            [run.run_id for run in canonical_runs],
            ["run-e2e-baseline", "run-e2e-candidate"],
        )
        self.assertTrue(
            all(run.status == "completed" for run in canonical_runs)
        )

        # replay: uses copy_mapping and sequence_of_mappings from
        # payload_coercion.
        session = build_replay_session(baseline)
        self.assertEqual(session.frames[0].phase, ReplayPhase.RUN_STARTED)
        self.assertEqual(session.frames[1].phase, ReplayPhase.STEP)
        self.assertEqual(session.frames[-1].phase, ReplayPhase.RUN_COMPLETED)
        # The replay frame must be an independent deep copy: mutating the
        # source payload must not affect a session already built from it.
        baseline["steps"][0]["expectedState"]["status"] = "mutated"
        self.assertEqual(
            session.frames[1].to_dict()["expectedState"], {"status": "ok"}
        )

        # run_comparison: uses as_mapping, copy_mapping, optional_number,
        # optional_text, sequence_of_mappings from payload_coercion.
        comparison = compare_kernel_runs(baseline, candidate)
        self.assertEqual(comparison.baseline_run_id, "run-e2e-baseline")
        self.assertEqual(comparison.candidate_run_id, "run-e2e-candidate")
        self.assertTrue(comparison.has_material_differences)
        self.assertIsNotNone(comparison.latency_delta)
        self.assertEqual(comparison.latency_delta.delta, 800.0)


if __name__ == "__main__":
    unittest.main()
