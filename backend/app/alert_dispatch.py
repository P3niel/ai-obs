"""Webhook alert dispatch for Slack and Discord providers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from http.client import HTTPConnection
from http.client import HTTPSConnection
from typing import Any
from typing import Mapping
from typing import Sequence
from urllib.parse import urlparse

from app.operational_observability import Alert
from app.operational_observability import AlertThresholds
from app.operational_observability import KernelRunInput
from app.operational_observability import NotificationDispatchResult
from app.operational_observability import NotificationMessage
from app.operational_observability import NotificationProvider
from app.operational_observability import detect_alerts
from app.operational_observability import dispatch_alert_notifications


DEFAULT_TIMEOUT_SECONDS = 5.0


class AlertDispatchError(RuntimeError):
    """Raised when a webhook client cannot deliver a message."""


@dataclass(frozen=True)
class WebhookConfig:
    slack_webhook_url: str | None = None
    discord_webhook_url: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    allow_insecure_http: bool = False

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "WebhookConfig":
        source = os.environ if env is None else env
        return cls(
            slack_webhook_url=_optional_text(
                source.get("AI_OBS_SLACK_WEBHOOK_URL")
            ),
            discord_webhook_url=_optional_text(
                source.get("AI_OBS_DISCORD_WEBHOOK_URL")
            ),
            timeout_seconds=_timeout_seconds(
                source.get("AI_OBS_ALERT_WEBHOOK_TIMEOUT_SECONDS")
            ),
            allow_insecure_http=_truthy(
                source.get("AI_OBS_ALERT_ALLOW_INSECURE_HTTP")
            ),
        )


@dataclass(frozen=True)
class WebhookNotificationClient:
    provider: NotificationProvider
    webhook_url: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    allow_insecure_http: bool = False

    def send(self, message: NotificationMessage) -> None:
        if message.provider != self.provider:
            raise AlertDispatchError(
                "Message provider does not match webhook client provider."
            )
        payload = _provider_payload(message)
        _post_json(
            self.webhook_url,
            payload,
            timeout_seconds=self.timeout_seconds,
            allow_insecure_http=self.allow_insecure_http,
        )


def build_webhook_clients(
    config: WebhookConfig,
) -> dict[NotificationProvider, WebhookNotificationClient]:
    clients: dict[NotificationProvider, WebhookNotificationClient] = {}
    if config.slack_webhook_url:
        clients[NotificationProvider.SLACK] = WebhookNotificationClient(
            provider=NotificationProvider.SLACK,
            webhook_url=config.slack_webhook_url,
            timeout_seconds=config.timeout_seconds,
            allow_insecure_http=config.allow_insecure_http,
        )
    if config.discord_webhook_url:
        clients[NotificationProvider.DISCORD] = WebhookNotificationClient(
            provider=NotificationProvider.DISCORD,
            webhook_url=config.discord_webhook_url,
            timeout_seconds=config.timeout_seconds,
            allow_insecure_http=config.allow_insecure_http,
        )
    return clients


def dispatch_alerts_to_webhooks(
    alerts: Sequence[Alert],
    config: WebhookConfig | None = None,
) -> tuple[NotificationDispatchResult, ...]:
    active_config = config or WebhookConfig.from_env()
    return dispatch_alert_notifications(
        alerts,
        build_webhook_clients(active_config),
    )


def detect_and_dispatch_alerts(
    runs: Sequence[KernelRunInput],
    thresholds: AlertThresholds | None = None,
    config: WebhookConfig | None = None,
) -> tuple[NotificationDispatchResult, ...]:
    alerts = detect_alerts(runs, thresholds=thresholds)
    return dispatch_alerts_to_webhooks(alerts, config=config)


def _provider_payload(message: NotificationMessage) -> dict[str, str]:
    text = f"{message.title}\n{message.body}"
    if message.provider == NotificationProvider.SLACK:
        return {"text": text}
    if message.provider == NotificationProvider.DISCORD:
        return {"content": text}
    raise AlertDispatchError(
        f"Unsupported webhook provider: {message.provider.value}."
    )


def _post_json(
    webhook_url: str,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float,
    allow_insecure_http: bool,
) -> None:
    parsed = urlparse(webhook_url)
    if parsed.scheme not in {"http", "https"}:
        raise AlertDispatchError("Webhook URL must use http or https.")
    if parsed.scheme == "http" and not allow_insecure_http:
        raise AlertDispatchError(
            "HTTP webhook URLs are allowed only for local validation."
        )
    if not parsed.netloc:
        raise AlertDispatchError("Webhook URL must include a host.")

    body = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"

    if parsed.scheme == "https":
        connection: HTTPConnection = HTTPSConnection(
            parsed.netloc,
            timeout=timeout_seconds,
        )
    else:
        connection = HTTPConnection(
            parsed.netloc,
            timeout=timeout_seconds,
        )

    try:
        connection.request(
            "POST",
            target,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        response_body = response.read().decode("utf-8", errors="replace")
        if response.status < 200 or response.status >= 300:
            raise AlertDispatchError(
                f"Webhook returned HTTP {response.status}: "
                f"{response_body[:200]}"
            )
    finally:
        connection.close()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _timeout_seconds(value: str | None) -> float:
    if value is None or not value.strip():
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(value)
    except ValueError as exc:
        raise AlertDispatchError(
            "AI_OBS_ALERT_WEBHOOK_TIMEOUT_SECONDS must be numeric."
        ) from exc
    if timeout <= 0:
        raise AlertDispatchError(
            "AI_OBS_ALERT_WEBHOOK_TIMEOUT_SECONDS must be positive."
        )
    return timeout


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}
