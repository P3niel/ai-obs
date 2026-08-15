import unittest

from app.kernel import InMemoryKernelStore
from app.metrics_detection_handoff import CONTRACT_VERSION
from app.metrics_detection_handoff import CONSUMER
from app.metrics_detection_handoff import METRIC_SOURCE_CONTRACT
from app.metrics_detection_handoff import PRODUCER
from app.metrics_detection_handoff import SOURCE_PAYLOAD_CONTRACT
from app.metrics_detection_handoff import MetricsDetectionHandoffError
from app.metrics_detection_handoff import build_metrics_detection_handoff
from app.metrics_detection_handoff import consume_metrics_detection_handoff
from app.metrics_detection_handoff import validate_metrics_detection_handoff


class MetricsDetectionHandoffTest(unittest.TestCase):
    def test_builds_and_consumes_run_count_handoff(self) -> None:
        handoff = build_metrics_detection_handoff(
            [
                _kernel_run_payload("run-001"),
                _kernel_run_payload("run-002"),
            ],
            handoff_id="handoff-001",
            created_at="2026-07-05T18:55:00.000Z",
        )
        payload = handoff.to_dict()

        self.assertEqual(payload["contract_version"], CONTRACT_VERSION)
        self.assertEqual(payload["producer"], PRODUCER)
        self.assertEqual(payload["consumer"], CONSUMER)
        self.assertEqual(
            payload["source_runs"],
            [
                {
                    "run_id": "run-001",
                    "payload_contract": SOURCE_PAYLOAD_CONTRACT,
                },
                {
                    "run_id": "run-002",
                    "payload_contract": SOURCE_PAYLOAD_CONTRACT,
                },
            ],
        )
        self.assertEqual(
            payload["metrics"],
            [
                {
                    "metric": "run.count",
                    "value": 2,
                    "unit": None,
                    "sample_count": 2,
                    "source_contract": METRIC_SOURCE_CONTRACT,
                }
            ],
        )

        consumed_metrics = consume_metrics_detection_handoff(payload)

        self.assertEqual(len(consumed_metrics), 1)
        self.assertEqual(consumed_metrics[0].metric, "run.count")
        self.assertEqual(consumed_metrics[0].value, 2)

    def test_rejects_noncanonical_or_unsupported_metric(self) -> None:
        payload = _valid_handoff_payload()
        payload["metrics"][0]["metric"] = "latency.ms"

        with self.assertRaises(MetricsDetectionHandoffError):
            validate_metrics_detection_handoff(payload)

    def test_rejects_detector_or_threshold_fields(self) -> None:
        payload = _valid_handoff_payload()
        payload["alerts"] = []

        with self.assertRaises(MetricsDetectionHandoffError):
            validate_metrics_detection_handoff(payload)

        payload = _valid_handoff_payload()
        payload["metrics"][0]["thresholdMs"] = 1000

        with self.assertRaises(MetricsDetectionHandoffError):
            validate_metrics_detection_handoff(payload)

    def test_rejects_noncanonical_created_at(self) -> None:
        payload = _valid_handoff_payload()
        payload["created_at"] = "2026-07-05T18:55:00Z"

        with self.assertRaises(MetricsDetectionHandoffError):
            validate_metrics_detection_handoff(payload)


def _kernel_run_payload(run_id: str) -> dict:
    store = InMemoryKernelStore()
    store.create_run(run_id)
    return store.get_run(run_id).to_dict()


def _valid_handoff_payload() -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "handoff_id": "handoff-001",
        "created_at": "2026-07-05T18:55:00.000Z",
        "producer": PRODUCER,
        "consumer": CONSUMER,
        "source_runs": [
            {
                "run_id": "run-001",
                "payload_contract": SOURCE_PAYLOAD_CONTRACT,
            }
        ],
        "metrics": [
            {
                "metric": "run.count",
                "value": 1,
                "unit": None,
                "sample_count": 1,
                "source_contract": METRIC_SOURCE_CONTRACT,
            }
        ],
    }
