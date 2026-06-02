from __future__ import annotations

import json
from urllib import error, request


class SlackNotificationError(RuntimeError):
    """Raised when a Slack webhook does not accept an alert message."""


class SlackWebhookClient:
    """Minimal one-way Slack incoming webhook client.

    Slack is an operator notification channel only. It must not become a control
    surface for live trading mutations.
    """

    def __init__(self, *, webhook_url: str, timeout_seconds: int = 5) -> None:
        self.webhook_url = str(webhook_url or "").strip()
        self.timeout_seconds = max(1, int(timeout_seconds or 5))

    def post_message(self, text: str) -> None:
        if not self.webhook_url:
            raise SlackNotificationError("slack_webhook_url_missing")
        payload = json.dumps({"text": str(text)}).encode("utf-8")
        http_request = request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                if int(response.status) >= 400:
                    raise SlackNotificationError(
                        f"Slack webhook failed with status {response.status}"
                    )
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise SlackNotificationError(
                f"Slack webhook failed with status {exc.code}: {body}"
            ) from exc
        except error.URLError as exc:
            raise SlackNotificationError(f"Slack webhook failed: {exc.reason}") from exc
