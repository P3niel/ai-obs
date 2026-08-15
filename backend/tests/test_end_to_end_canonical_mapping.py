"""End-to-end test for the P3N-106 implementation of the P3N-105 contracts.

Exercises the full chain in one pass: Kernel run capture (with real
timestamps) -> operational observability metrics/alerts -> anomaly
detection -> canonical mapping (status vocabulary, run shape, latency
metric names). Asserts the resulting shapes actually satisfy the active
contracts (docs/kernel/contracts/kernelrun-serialization-contract-v0.1.md,
docs/kernel/contracts/run-status-contract-v0.3.md,
docs/kernel/contracts/latency-compatibility-mapping-contract-v0.1.md),
not just that individual functions return expected values in isolation.
"""

import re
import unittest

from app.canonical_mapping import to_canonical_latency_metrics
from app.canonical_mapping import to_canonical_run
from app.canonical_mapping import to_canonical_status
from app.kernel import InMemoryKernelStore
from app.operational_observability import AlertCondition
from app.operational_observability import detect_alerts
from app.operational_observability import summarize_kernel_runs
from app.run_anomaly_detection import detect_run_anomalies

ISO8601_UTC_MS_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
CANONICAL_STATUS_VOCABULARY = {
    "running",
    "completed",
    "failed",
    "cancelled",
    "stuck",
    "unknown",
}


class P3N106EndToEndTest(unittest.TestCase):
    def test_full_chain_from_kernel_to_canonical_output(self) -> None:
        store = InMemoryKernelStore()

        run_specs = [
            ("run-e2e-001", 420, "ok"),
            ("run-e2e-002", 1250, "ok"),
            ("run-e2e-003", 300, "failed"),
        ]
        payloads = []
        for run_id, latency_ms, observed_status in run_specs:
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
            payloads.append(store.get_run(run_id).to_dict())

        # Stage 1: every stored Kernel run exposes canonical timestamps
        # per the temporal/serialization contracts.
        for payload in payloads:
            self.assertRegex(
                payload["run_start_timestamp"], ISO8601_UTC_MS_PATTERN
            )
            self.assertRegex(
                payload["run_end_timestamp"], ISO8601_UTC_MS_PATTERN
            )
            self.assertGreaterEqual(
                payload["run_end_timestamp"], payload["run_start_timestamp"]
            )
            step = payload["steps"][0]
            self.assertRegex(
                step["step_start_timestamp"], ISO8601_UTC_MS_PATTERN
            )
            self.assertRegex(
                step["step_end_timestamp"], ISO8601_UTC_MS_PATTERN
            )

        # Stage 2: existing operational observability and detection still
        # work unchanged over payloads that now carry timestamps.
        metrics = summarize_kernel_runs(payloads)
        alerts = detect_alerts(payloads)
        anomalies = detect_run_anomalies(payloads)

        self.assertEqual(metrics.run_count, 3)
        alert_conditions = {alert.condition for alert in alerts}
        self.assertIn(AlertCondition.SLOW_RUN, alert_conditions)
        self.assertIn(AlertCondition.ERRORED_STEP, alert_conditions)
        self.assertGreaterEqual(anomalies.anomaly_count, 1)

        # Stage 3: canonical mapping over the same payloads satisfies the
        # v0.3 status vocabulary and the serialization contract shape.
        canonical_runs = [to_canonical_run(payload) for payload in payloads]
        for canonical_run in canonical_runs:
            self.assertIn(canonical_run.status, CANONICAL_STATUS_VOCABULARY)
            self.assertEqual(
                canonical_run.status, canonical_run.status.lower()
            )
            self.assertRegex(
                canonical_run.run_start_timestamp or "",
                ISO8601_UTC_MS_PATTERN,
            )
            self.assertRegex(
                canonical_run.run_end_timestamp or "",
                ISO8601_UTC_MS_PATTERN,
            )

        self.assertEqual(
            [run.status for run in canonical_runs],
            ["completed", "completed", "completed"],
        )

        # Stage 4: canonical latency metric mapping exposes the contract's
        # canonical metric names, derived from the existing metrics facade.
        canonical_metrics = to_canonical_latency_metrics(metrics)
        self.assertEqual(
            set(canonical_metrics),
            {"step.mean.duration.ms", "step.max.duration.ms"},
        )
        self.assertEqual(canonical_metrics["step.max.duration.ms"], 1250.0)

        # Stage 5: runtime status mapping is deterministic and does not
        # invent values outside the canonical vocabulary.
        for runtime_value in ("RUNNING", "COMPLETED", "NOT_A_REAL_STATUS"):
            self.assertIn(
                to_canonical_status(runtime_value),
                CANONICAL_STATUS_VOCABULARY,
            )


if __name__ == "__main__":
    unittest.main()
