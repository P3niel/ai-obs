import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from app.kernel import EvaluationResult
from app.kernel import InMemoryKernelStore
from app.kernel import KernelError
from app.kernel import RunStatus


class KernelTest(unittest.TestCase):
    def test_run_executes_end_to_end_and_persists_artifacts(self) -> None:
        store = InMemoryKernelStore()

        run = store.create_run("run-001")
        step = store.append_step(
            run.run_id,
            step_id="step-001",
            name="collect service health",
            expected_state={"status": "ok"},
            events=("probe started", "probe finished"),
        )
        observation = store.record_observation(
            run.run_id,
            step_id=step.step_id,
            observation_id="obs-001",
            fact="Service health endpoint returned ok.",
            observed_state={"status": "ok"},
        )
        evaluation = store.complete_run(
            run.run_id,
            evaluation_id="eval-001",
        )

        completed = store.get_run("run-001")
        payload = completed.to_dict()

        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertEqual(evaluation.result, EvaluationResult.MATCH)
        observed_step = store.list_steps("run-001")[0]
        self.assertEqual(observed_step.step_id, step.step_id)
        self.assertIsNotNone(observed_step.step_end_timestamp)
        self.assertEqual(store.list_observations("run-001"), (observation,))
        self.assertEqual(store.get_evaluation("run-001"), evaluation)
        self.assertEqual(payload["evaluation"]["matches"], ["status"])
        self.assertEqual(payload["steps"][0]["events"], [
            "probe started",
            "probe finished",
        ])

    def test_evaluation_reports_belief_reality_delta(self) -> None:
        store = InMemoryKernelStore()
        store.create_run("run-002")
        store.append_step(
            "run-002",
            step_id="step-001",
            name="expected healthy service",
            expected_state={
                "cost": "low",
                "status": "ok",
            },
        )
        store.record_observation(
            "run-002",
            step_id="step-001",
            observation_id="obs-001",
            fact="Service answered with failure and high latency.",
            observed_state={
                "latency": "high",
                "status": "failed",
            },
        )

        evaluation = store.complete_run("run-002")
        payload = evaluation.to_dict()

        self.assertEqual(evaluation.result, EvaluationResult.MISMATCH)
        self.assertEqual(payload["matches"], [])
        self.assertEqual(payload["missing"], ["cost"])
        self.assertEqual(payload["unexpected"], ["latency"])
        self.assertEqual(
            payload["mismatched"],
            [
                {
                    "key": "status",
                    "expected": "ok",
                    "observed": "failed",
                }
            ],
        )

    def test_requires_observation_before_completion(self) -> None:
        store = InMemoryKernelStore()
        store.create_run("run-003")
        store.append_step(
            "run-003",
            step_id="step-001",
            name="define expectation",
            expected_state={"status": "ok"},
        )

        with self.assertRaises(KernelError):
            store.complete_run("run-003")

    def test_observations_are_immutable_runtime_facts(self) -> None:
        store = InMemoryKernelStore()
        observed_state = {"status": "ok"}
        store.create_run("run-004")
        store.append_step(
            "run-004",
            step_id="step-001",
            name="capture state",
            expected_state={"status": "ok"},
        )

        observation = store.record_observation(
            "run-004",
            step_id="step-001",
            observation_id="obs-001",
            fact="Captured a healthy service.",
            observed_state=observed_state,
        )
        observed_state["status"] = "failed"

        self.assertEqual(
            observation.to_dict()["observedState"],
            {"status": "ok"},
        )
        with self.assertRaises(FrozenInstanceError):
            observation.fact = "Captured a changed fact."

    def test_rejects_duplicate_ids_and_completed_run_mutation(self) -> None:
        store = InMemoryKernelStore()
        store.create_run("run-005")

        with self.assertRaises(KernelError):
            store.create_run("run-005")

        store.append_step(
            "run-005",
            step_id="step-001",
            name="capture state",
        )
        with self.assertRaises(KernelError):
            store.append_step(
                "run-005",
                step_id="step-001",
                name="capture state again",
            )

        store.record_observation(
            "run-005",
            step_id="step-001",
            observation_id="obs-001",
            fact="Captured a fact.",
            observed_state={"status": "ok"},
        )
        store.complete_run("run-005")

        with self.assertRaises(KernelError):
            store.append_step(
                "run-005",
                step_id="step-002",
                name="too late",
            )

    def test_timestamps_use_injected_clock_and_iso8601_utc_format(
        self,
    ) -> None:
        moments = iter(
            [
                datetime(2026, 8, 3, 10, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 8, 3, 10, 0, 1, 500000, tzinfo=timezone.utc),
                datetime(2026, 8, 3, 10, 0, 2, 250000, tzinfo=timezone.utc),
                datetime(2026, 8, 3, 10, 0, 5, 0, tzinfo=timezone.utc),
            ]
        )
        store = InMemoryKernelStore(clock=lambda: next(moments))

        store.create_run("run-006")
        store.append_step(
            "run-006",
            step_id="step-001",
            name="capture state",
            expected_state={"status": "ok"},
        )
        store.record_observation(
            "run-006",
            step_id="step-001",
            observation_id="obs-001",
            fact="Captured a healthy service.",
            observed_state={"status": "ok"},
        )
        store.complete_run("run-006")

        payload = store.get_run("run-006").to_dict()

        self.assertEqual(
            payload["run_start_timestamp"], "2026-08-03T10:00:00.000Z"
        )
        self.assertEqual(
            payload["run_end_timestamp"], "2026-08-03T10:00:05.000Z"
        )
        step_payload = payload["steps"][0]
        self.assertEqual(
            step_payload["step_start_timestamp"], "2026-08-03T10:00:01.500Z"
        )
        self.assertEqual(
            step_payload["step_end_timestamp"], "2026-08-03T10:00:02.250Z"
        )

    def test_step_end_timestamp_is_set_only_by_first_observation(
        self,
    ) -> None:
        store = InMemoryKernelStore()
        store.create_run("run-007")
        store.append_step(
            "run-007",
            step_id="step-001",
            name="capture state",
        )
        store.record_observation(
            "run-007",
            step_id="step-001",
            observation_id="obs-001",
            fact="First observation.",
            observed_state={"status": "ok"},
        )
        first_step = store.list_steps("run-007")[0]
        first_end_timestamp = first_step.step_end_timestamp

        store.record_observation(
            "run-007",
            step_id="step-001",
            observation_id="obs-002",
            fact="Second observation for the same step.",
            observed_state={"status": "ok"},
        )
        second_step = store.list_steps("run-007")[0]
        second_end_timestamp = second_step.step_end_timestamp

        self.assertIsNotNone(first_end_timestamp)
        self.assertEqual(first_end_timestamp, second_end_timestamp)

    def test_default_clock_produces_timezone_aware_utc_timestamps(
        self,
    ) -> None:
        before = datetime.now(timezone.utc) - timedelta(seconds=1)
        store = InMemoryKernelStore()
        run = store.create_run("run-008")
        after = datetime.now(timezone.utc) + timedelta(seconds=1)

        parsed = datetime.strptime(
            run.run_start_timestamp, "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=timezone.utc)

        self.assertTrue(before <= parsed <= after)
