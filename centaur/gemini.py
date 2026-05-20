from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib import error, request

from .config import RuntimeConfig
from .models import TickContext


class GeminiApiError(RuntimeError):
    """Raised when the Gemini API request fails or returns invalid output."""


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> "GeminiClient":
        if not config.gemini_api_configured:
            raise GeminiApiError("Gemini API key is not configured.")

        return cls(
            api_key=config.gemini_api_key,
            base_url=config.gemini_api_base_url,
            model=config.gemini_model,
            timeout_seconds=config.gemini_request_timeout_seconds,
            max_output_tokens=config.gemini_max_output_tokens,
        )

    def analyze_candidates(
        self,
        *,
        context: TickContext,
        candidates: list[dict[str, Any]],
        market_context: dict[str, Any],
    ) -> dict[str, Any]:
        endpoint = f"/v1beta/models/{self.model}:generateContent"
        url = f"{self.base_url}{endpoint}?key={self.api_key}"
        requested_at = datetime.now().astimezone()
        prompt = _build_prompt(candidates=candidates, market_context=market_context)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "maxOutputTokens": self.max_output_tokens,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ghostfrog-centaur/0.1",
            },
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw_response = response.read().decode("utf-8")
                status_code = getattr(response, "status", 200)
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            context.record_api_usage(
                source="gemini_api",
                endpoint=endpoint,
                success=False,
                metadata={
                    "method": "POST",
                    "status_code": exc.code,
                    "requested_at": requested_at.isoformat(),
                    "error": body_text[:240],
                },
            )
            raise GeminiApiError(
                f"Gemini request failed with status {exc.code}: {body_text[:240]}"
            ) from exc
        except error.URLError as exc:
            context.record_api_usage(
                source="gemini_api",
                endpoint=endpoint,
                success=False,
                metadata={
                    "method": "POST",
                    "requested_at": requested_at.isoformat(),
                    "error": str(exc.reason),
                },
            )
            raise GeminiApiError(f"Gemini request failed: {exc.reason}") from exc

        parsed_response = json.loads(raw_response)
        text = _extract_candidate_text(parsed_response)
        usage_metadata = parsed_response.get("usageMetadata", {})
        prompt_tokens = int(usage_metadata.get("promptTokenCount", 0) or 0)
        candidate_tokens = int(usage_metadata.get("candidatesTokenCount", 0) or 0)
        try:
            analysis = _parse_analysis_payload(text)
        except GeminiApiError as exc:
            context.record_api_usage(
                source="gemini_api",
                endpoint=endpoint,
                success=False,
                input_units=prompt_tokens,
                output_units=candidate_tokens,
                metadata={
                    "method": "POST",
                    "status_code": status_code,
                    "requested_at": requested_at.isoformat(),
                    "model": self.model,
                    "total_token_count": int(usage_metadata.get("totalTokenCount", 0) or 0),
                    "error": str(exc),
                    "response_excerpt": text[:240],
                },
            )
            raise

        context.record_api_usage(
            source="gemini_api",
            endpoint=endpoint,
            success=True,
            input_units=prompt_tokens,
            output_units=candidate_tokens,
            metadata={
                "method": "POST",
                "status_code": status_code,
                "requested_at": requested_at.isoformat(),
                "model": self.model,
                "total_token_count": int(usage_metadata.get("totalTokenCount", 0) or 0),
            },
        )
        return {
            "analysis": analysis,
            "usage_metadata": usage_metadata,
            "raw_response": parsed_response,
        }


def get_gemini_client(context: TickContext) -> GeminiClient:
    cached = context.metadata.get("gemini_client")
    if isinstance(cached, GeminiClient):
        return cached

    client = GeminiClient.from_config(context.config)
    context.metadata["gemini_client"] = client
    return client


def _build_prompt(
    *,
    candidates: list[dict[str, Any]],
    market_context: dict[str, Any],
) -> str:
    payload = {
        "task": (
            "You are a cautious market analyst for a paper-trading system. "
            "Score the candidates for watch quality only. Do not recommend leverage. "
            "Return compact JSON with a top-level summary and a candidates array."
        ),
        "requirements": {
            "output_format": {
                "summary": "short string",
                "candidates": [
                    {
                        "symbol": "string",
                        "action_bias": "watch|hold|avoid",
                        "opportunity_score": "integer 0-100",
                        "confidence": "number 0-1",
                        "thesis": "short string",
                        "risks": ["short string"],
                    }
                ],
            },
            "rules": [
                "Use only the provided data.",
                "Be conservative when data is thin.",
                "Do not invent catalysts.",
                "Keep each thesis brief.",
            ],
        },
        "market_context": market_context,
        "candidates": candidates,
    }
    return json.dumps(payload, separators=(",", ":"))


def _extract_candidate_text(response_payload: dict[str, Any]) -> str:
    candidates = response_payload.get("candidates") or []
    if not candidates:
        raise GeminiApiError("Gemini response did not include any candidates.")

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    for part in parts:
        text = part.get("text")
        if text:
            return text
    raise GeminiApiError("Gemini response did not include a text payload.")


def _parse_analysis_payload(text: str) -> dict[str, Any]:
    candidates = [text.strip()]
    unfenced = _strip_code_fences(text)
    if unfenced not in candidates:
        candidates.append(unfenced)

    extracted = _extract_json_object(unfenced)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise GeminiApiError("Gemini response text was not valid structured JSON.")


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if not lines:
        return stripped
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1].strip()
