import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import Any

from app.alert_dispatch import AlertDispatchError
from app.alert_dispatch import WebhookConfig
from app.alert_dispatch import WebhookNotificationClient
from app.alert_dispatch import build_webhook_clients
from app.alert_dispatch import detect_and_dispatch_alerts
from app.alert_dispatch import dispatch_alerts_to_webhooks
from app.kernel import InMemoryKernelStore
from app.operational_observability import AlertThresholds
from app.operational_observability import NotificationProvider
from app.operational_observability import build_notification_message
from app.operational_observability import detect_alerts


class AlertDispatchTest(unittest.TestCase):
    def test_dispatches_slack_and_discord_webhooks_end_to_end(
        self,
    ) -> None:
        alert = _slow_run_alert()
        with RecordingWebhookServer() as server:
            config = WebhookConfig(
                slack_webhook_url=server.url("/slack"),
                discord_webhook_url=server.url("/discord"),
                allow_insecure_http=True,
            )

            results = dispatch_alerts_to_webhooks([alert], config=config)

        payloads = [result.to_dict() for result in results]
        requests = {path: payload for path, payload in server.requests}
        self.assertEqual(
            {payload["provider"] for payload in payloads},
            {"SLACK", "DISCORD"},
        )
        self.assertTrue(all(payload["delivered"] for payload in payloads))
        self.assertIn("AI-Obs alert", requests["/slack"]["text"])
        self.assertIn("run-slow", requests["/slack"]["text"])
        self.assertIn("AI-Obs alert", requests["/discord"]["content"])
        self.assertIn("run-slow", requests["/discord"]["content"])

    def test_dispatch_records_webhook_failure_without_raising(self) -> None:
        alert = _slow_run_alert()
        with RecordingWebhookServer(statuses={"/discord": 500}) as server:
            config = WebhookConfig(
                slack_webhook_url=server.url("/slack"),
                discord_webhook_url=server.url("/discord"),
                allow_insecure_http=True,
            )

            results = dispatch_alerts_to_webhooks([alert], config=config)

        payloads = [result.to_dict() for result in results]
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
                and "HTTP 500" in str(payload["error"])
                for payload in payloads
            )
        )

    def test_detect_and_dispatch_alerts_uses_configured_webhooks(
        self,
    ) -> None:
        with RecordingWebhookServer() as server:
            config = WebhookConfig(
                slack_webhook_url=server.url("/slack"),
                allow_insecure_http=True,
            )

            results = detect_and_dispatch_alerts(
                [_completed_run_payload()],
                thresholds=AlertThresholds(max_run_duration_ms=3000),
                config=config,
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].delivered)
        self.assertEqual(server.requests[0][0], "/slack")

    def test_builds_clients_from_environment_config(self) -> None:
        config = WebhookConfig.from_env(
            {
                "AI_OBS_SLACK_WEBHOOK_URL": "https://hooks.slack.test/x",
                "AI_OBS_ALERT_WEBHOOK_TIMEOUT_SECONDS": "2.5",
                "AI_OBS_ALERT_ALLOW_INSECURE_HTTP": "yes",
            }
        )

        clients = build_webhook_clients(config)

        self.assertEqual(config.timeout_seconds, 2.5)
        self.assertTrue(config.allow_insecure_http)
        self.assertEqual(
            set(clients.keys()),
            {NotificationProvider.SLACK},
        )

    def test_http_webhook_urls_require_local_validation_opt_in(
        self,
    ) -> None:
        alert = _slow_run_alert()
        message = build_notification_message(
            NotificationProvider.SLACK,
            alert,
        )
        client = WebhookNotificationClient(
            provider=NotificationProvider.SLACK,
            webhook_url="http://127.0.0.1:9/slack",
        )

        with self.assertRaises(AlertDispatchError):
            client.send(message)


class RecordingWebhookServer:
    def __init__(self, statuses: dict[str, int] | None = None) -> None:
        self.statuses = statuses or {}
        self.requests: list[tuple[str, dict[str, Any]]] = []
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                parent.requests.append((self.path, payload))
                self.send_response(parent.statuses.get(self.path, 204))
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )

    def __enter__(self) -> "RecordingWebhookServer":
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def url(self, path: str) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}{path}"


def _slow_run_alert():
    return detect_alerts(
        [_completed_run_payload()],
        thresholds=AlertThresholds(max_run_duration_ms=3000),
    )[0]


def _completed_run_payload() -> dict:
    store = InMemoryKernelStore()
    store.create_run("run-slow")
    store.append_step(
        "run-slow",
        step_id="collect",
        name="collect service health",
        expected_state={"status": "ok"},
    )
    store.record_observation(
        "run-slow",
        step_id="collect",
        observation_id="obs-collect",
        fact="Collected service health.",
        observed_state={"status": "ok"},
    )
    store.complete_run("run-slow")
    payload = store.get_run("run-slow").to_dict()
    payload["metadata"] = {"durationMs": 5000}
    return payload
