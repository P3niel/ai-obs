import unittest

from app.kernel import InMemoryKernelStore
from app.replay import ReplayError
from app.replay import ReplayPhase
from app.replay import build_replay_session


class ReplayEngineTest(unittest.TestCase):
    def test_replays_completed_kernel_run_step_by_step(self) -> None:
        run_payload = _completed_run_payload()

        session = build_replay_session(run_payload)
        phases = [frame.phase for frame in session.frames]

        self.assertEqual(
            phases,
            [
                ReplayPhase.RUN_STARTED,
                ReplayPhase.STEP,
                ReplayPhase.STEP,
                ReplayPhase.EVALUATION,
                ReplayPhase.RUN_COMPLETED,
            ],
        )
        self.assertEqual(session.current.phase, ReplayPhase.RUN_STARTED)
        self.assertTrue(session.can_advance)

        collect_frame = session.advance().current
        self.assertEqual(collect_frame.step_id, "collect")
        self.assertEqual(collect_frame.step_name, "collect service health")
        self.assertEqual(
            collect_frame.events,
            ("probe started", "probe finished"),
        )
        self.assertEqual(
            collect_frame.observations[0]["fact"],
            "Health endpoint returned ok.",
        )

        evaluate_frame = session.seek(2).current
        self.assertEqual(evaluate_frame.step_id, "evaluate")
        self.assertEqual(
            evaluate_frame.observations[0]["observedState"],
            {"decision": "accept", "status": "ok"},
        )

        evaluation_frame = session.seek(3).current
        self.assertEqual(evaluation_frame.phase, ReplayPhase.EVALUATION)
        self.assertEqual(evaluation_frame.evaluation["result"], "MATCH")

        terminal_frame = session.seek(4).current
        self.assertEqual(terminal_frame.phase, ReplayPhase.RUN_COMPLETED)
        self.assertTrue(terminal_frame.is_terminal)

    def test_replay_session_advances_without_mutating_prior_positions(
        self,
    ) -> None:
        session = build_replay_session(_completed_run_payload())

        advanced = session.advance()
        retreated = advanced.retreat()
        payload = advanced.to_dict()

        self.assertEqual(session.current_position, 0)
        self.assertEqual(advanced.current_position, 1)
        self.assertEqual(retreated.current_position, 0)
        self.assertEqual(payload["current"]["phase"], "STEP")
        self.assertEqual(payload["totalFrames"], 5)
        self.assertTrue(payload["canRetreat"])

    def test_replays_running_run_without_terminal_evaluation(self) -> None:
        store = InMemoryKernelStore()
        store.create_run("run-live")
        store.append_step(
            "run-live",
            step_id="collect",
            name="collect service health",
        )
        store.record_observation(
            "run-live",
            step_id="collect",
            observation_id="obs-collect",
            fact="Collection is still in progress.",
            observed_state={"status": "running"},
        )

        session = build_replay_session(store.get_run("run-live"))
        phases = [frame.phase for frame in session.frames]

        self.assertEqual(
            phases,
            [
                ReplayPhase.RUN_STARTED,
                ReplayPhase.STEP,
            ],
        )
        self.assertEqual(session.seek(1).current.step_id, "collect")
        self.assertIsNone(session.seek(1).current.evaluation)

    def test_rejects_invalid_replay_positions(self) -> None:
        session = build_replay_session(_completed_run_payload())

        with self.assertRaises(ReplayError):
            session.retreat()

        with self.assertRaises(ReplayError):
            session.seek(session.total_frames)

        terminal = session.seek(session.total_frames - 1)
        with self.assertRaises(ReplayError):
            terminal.advance()

    def test_rejects_payloads_not_grounded_in_kernel_steps(self) -> None:
        payload = _completed_run_payload()
        payload["observations"][0]["stepId"] = "missing-step"

        with self.assertRaises(ReplayError):
            build_replay_session(payload)

        with self.assertRaises(ReplayError):
            build_replay_session(
                {
                    "id": "run-empty",
                    "status": "RUNNING",
                    "steps": [],
                }
            )

        duplicate_steps = _completed_run_payload()
        duplicate_steps["steps"][1]["id"] = "collect"
        with self.assertRaises(ReplayError):
            build_replay_session(duplicate_steps)


def _completed_run_payload() -> dict:
    store = InMemoryKernelStore()
    store.create_run("run-replay")
    store.append_step(
        "run-replay",
        step_id="collect",
        name="collect service health",
        expected_state={"status": "ok"},
        events=("probe started", "probe finished"),
    )
    store.record_observation(
        "run-replay",
        step_id="collect",
        observation_id="obs-collect",
        fact="Health endpoint returned ok.",
        observed_state={"status": "ok"},
    )
    store.append_step(
        "run-replay",
        step_id="evaluate",
        name="evaluate health decision",
        expected_state={"decision": "accept"},
    )
    store.record_observation(
        "run-replay",
        step_id="evaluate",
        observation_id="obs-evaluate",
        fact="Evaluation accepted the healthy run.",
        observed_state={
            "decision": "accept",
            "status": "ok",
        },
    )
    store.complete_run("run-replay")
    return store.get_run("run-replay").to_dict()
