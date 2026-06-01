from __future__ import annotations

import json
import base64
from datetime import datetime
from typing import Any
from urllib import error, request

from app.runtime.models import TickContext
from app.runtime.settings import RuntimeConfig


class Trading212ApiError(RuntimeError):
    """Raised when the Trading 212 demo API cannot return a trusted payload."""


class Trading212PaperClient:
    """Minimal read client for Trading 212's demo API.

    The demo API is intentionally kept behind a paper-only client. Order
    mutation remains disabled in the broker adapter until the lane has explicit
    execution approval, idempotency handling, and evidence review.
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str,
        timeout_seconds: int,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = _normalize_base_url(base_url)
        self.timeout_seconds = int(timeout_seconds)

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> "Trading212PaperClient":
        if not config.trading212_paper_api_configured:
            raise Trading212ApiError("Trading 212 paper API credentials are not configured.")
        return cls(
            api_key=config.trading212_paper_api_key,
            api_secret=config.trading212_paper_api_secret,
            base_url=config.trading212_paper_base_url,
            timeout_seconds=config.trading212_paper_request_timeout_seconds,
        )

    def get_account_cash(self, context: TickContext) -> dict[str, Any]:
        payload = self._request_json(context=context, path="/equity/account/cash")
        if isinstance(payload, dict):
            return payload
        raise Trading212ApiError("Unexpected Trading 212 account cash response payload.")

    def get_instruments(self, context: TickContext) -> list[dict[str, Any]]:
        payload = self._request_json(context=context, path="/equity/metadata/instruments")
        if isinstance(payload, list):
            return payload
        raise Trading212ApiError("Unexpected Trading 212 instruments response payload.")

    def get_positions(self, context: TickContext) -> list[dict[str, Any]]:
        payload = self._request_json(context=context, path="/equity/portfolio")
        if isinstance(payload, list):
            return payload
        raise Trading212ApiError("Unexpected Trading 212 portfolio response payload.")

    def get_orders(self, context: TickContext) -> list[dict[str, Any]]:
        payload = self._request_json(context=context, path="/equity/orders")
        if isinstance(payload, list):
            return payload
        raise Trading212ApiError("Unexpected Trading 212 orders response payload.")

    def submit_limit_order(
        self,
        context: TickContext,
        *,
        order_request: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._request_json(
            context=context,
            path="/equity/orders/limit",
            method="POST",
            body_json={
                "limitPrice": order_request["limitPrice"],
                "quantity": order_request["quantity"],
                "ticker": order_request["ticker"],
                "timeValidity": order_request.get("timeValidity", "DAY"),
            },
        )
        if isinstance(payload, dict):
            return payload
        raise Trading212ApiError("Unexpected Trading 212 order submission response payload.")

    def cancel_order(self, context: TickContext, *, order_id: str) -> None:
        self._request_json(
            context=context,
            path=f"/equity/orders/{order_id}",
            method="DELETE",
        )

    def _request_json(
        self,
        *,
        context: TickContext,
        path: str,
        method: str = "GET",
        body_json: dict[str, Any] | None = None,
    ) -> Any:
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": _basic_auth_header(
                api_key=self.api_key,
                api_secret=self.api_secret,
            ),
            "User-Agent": "ghostfrog-centaur/0.1",
        }
        if body_json is not None:
            body = json.dumps(body_json).encode("utf-8")
            headers["Content-Type"] = "application/json"

        http_request = request.Request(
            url=f"{self.base_url}{path}",
            headers=headers,
            data=body,
            method=method,
        )
        requested_at = datetime.now().astimezone()
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                status_code = getattr(response, "status", 200)
            context.record_api_usage(
                source="trading212_paper",
                endpoint=path,
                success=True,
                metadata={
                    "method": method,
                    "status_code": status_code,
                    "requested_at": requested_at.isoformat(),
                },
            )
            return json.loads(response_body) if response_body else None
        except error.HTTPError as exc:
            context.record_api_usage(
                source="trading212_paper",
                endpoint=path,
                success=False,
                notes=f"HTTP {exc.code}",
                metadata={"method": method, "requested_at": requested_at.isoformat()},
            )
            raise Trading212ApiError(f"Trading 212 API HTTP {exc.code}: {exc.reason}") from exc
        except error.URLError as exc:
            context.record_api_usage(
                source="trading212_paper",
                endpoint=path,
                success=False,
                notes=str(exc.reason),
                metadata={"method": method, "requested_at": requested_at.isoformat()},
            )
            raise Trading212ApiError(f"Trading 212 API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            context.record_api_usage(
                source="trading212_paper",
                endpoint=path,
                success=False,
                notes="invalid_json",
                metadata={"method": method, "requested_at": requested_at.isoformat()},
            )
            raise Trading212ApiError("Trading 212 API returned invalid JSON.") from exc


def _normalize_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        raise Trading212ApiError("Trading 212 API base URL is not configured.")
    return normalized


def _basic_auth_header(*, api_key: str, api_secret: str) -> str:
    credential = f"{api_key}:{api_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(credential).decode("ascii")
