"""Sanitized, non-generative cloud Agent verification and runtime health cache."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import requests

from core.agent.catalog import AGENT_SPECS

CloudStatus = Literal[
    "configured",
    "verifying",
    "verified",
    "unauthorized",
    "model_unavailable",
    "rate_limited",
    "quota_exhausted",
    "billing_blocked",
    "provider_unreachable",
    "provider_error",
]
StatusSource = Literal["configuration", "verification", "request"]

_SUCCESS_TTL = timedelta(minutes=10)
_TRANSIENT_TTL = timedelta(minutes=1)
_ACCOUNT_TTL = timedelta(minutes=5)
_LOCK = threading.Lock()
_IN_FLIGHT: set[str] = set()
_CACHE: dict[str, "CloudStatusRecord"] = {}


@dataclass(frozen=True, slots=True)
class CloudStatusRecord:
    status: CloudStatus
    reason: str | None
    checked_at: datetime
    expires_at: datetime
    source: StatusSource


def cloud_status(agent_key: str) -> CloudStatusRecord:
    """Return the configured fallback or a non-expired sanitized status."""
    now = _now()
    with _LOCK:
        cached = _CACHE.get(agent_key)
        if cached is not None and cached.expires_at > now:
            return cached
        if cached is not None:
            _CACHE.pop(agent_key, None)
        if agent_key in _IN_FLIGHT:
            return CloudStatusRecord("verifying", None, now, now + _TRANSIENT_TTL, "verification")
    return CloudStatusRecord("configured", None, now, now, "configuration")


def verify_cloud_agent(agent_key: str) -> CloudStatusRecord:
    """Force a bounded model-metadata probe and cache its sanitized result."""
    spec = AGENT_SPECS[agent_key]
    if spec.runtime != "cloud" or spec.credential_env is None:
        raise ValueError("Cloud verification requires a credential-backed cloud Agent.")
    api_key = os.getenv(spec.credential_env)
    if not api_key:
        raise ValueError("Cloud verification requires configured credentials.")

    with _LOCK:
        if agent_key in _IN_FLIGHT:
            raise RuntimeError("Cloud verification is already in progress.")
        _IN_FLIGHT.add(agent_key)
    try:
        status, reason = _probe_model(spec.provider, spec.api_model, api_key)
        record = _record(status, reason, "verification")
        with _LOCK:
            previous = _CACHE.get(agent_key)
            if (
                status == "verified"
                and previous is not None
                and previous.source == "request"
                and previous.status in {"quota_exhausted", "billing_blocked"}
                and previous.expires_at > _now()
            ):
                # Metadata access does not prove inference quota or billing health.
                return previous
            _CACHE[agent_key] = record
        return record
    finally:
        with _LOCK:
            _IN_FLIGHT.discard(agent_key)


def record_cloud_request_success(agent_key: str) -> None:
    """A completed inference is stronger evidence than a metadata probe."""
    spec = AGENT_SPECS.get(agent_key)
    if spec is None or spec.runtime != "cloud":
        return
    record = _record("verified", None, "request")
    with _LOCK:
        _CACHE[agent_key] = record


def record_cloud_request_failure(agent_key: str, exc: BaseException) -> None:
    """Remember only conservative provider failure categories, never raw content."""
    spec = AGENT_SPECS.get(agent_key)
    if spec is None or spec.runtime != "cloud":
        return
    status, reason = classify_provider_failure(exc)
    if status is None:
        return
    record = _record(status, reason, "request")
    with _LOCK:
        _CACHE[agent_key] = record


def clear_cloud_status_cache() -> None:
    """Test-only cache reset."""
    with _LOCK:
        _CACHE.clear()
        _IN_FLIGHT.clear()


def classify_provider_failure(exc: BaseException) -> tuple[CloudStatus | None, str | None]:
    """Classify only explicit provider information into stable HUD states."""
    status_code = getattr(exc, "status_code", None)
    if not isinstance(status_code, int):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            status_code = getattr(exc, "code", None)

    text = _exception_text(exc).lower()
    if status_code == 401:
        return "unauthorized", "Provider rejected the configured credentials."
    if status_code == 403:
        return "unauthorized", "Provider denied access to this agent."
    if status_code == 404:
        return "model_unavailable", "Configured model is not available to this provider account."
    if "billing" in text or "payment" in text or "failed_precondition" in text:
        return "billing_blocked", "Provider reported a billing or account prerequisite."
    if "insufficient_quota" in text or "quota exhausted" in text or "credit balance" in text:
        return "quota_exhausted", "Provider reported exhausted quota or credits."
    if status_code == 429:
        return "rate_limited", "Provider rate limit is currently active."
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return "provider_unreachable", "Provider could not be reached."
    if status_code is not None and status_code >= 500:
        return "provider_unreachable", "Provider service is temporarily unavailable."
    return None, None


def _probe_model(provider: str, model: str, api_key: str) -> tuple[CloudStatus, str | None]:
    if provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        headers = {"x-goog-api-key": api_key}
    elif provider == "openai":
        url = f"https://api.openai.com/v1/models/{model}"
        headers = {"Authorization": f"Bearer {api_key}"}
    elif provider == "xai":
        url = f"https://api.x.ai/v1/models/{model}"
        headers = {"Authorization": f"Bearer {api_key}"}
    else:
        return "provider_error", "Agent has no supported cloud verification probe."

    try:
        response = requests.get(url, headers=headers, timeout=5)
    except (requests.ConnectionError, requests.Timeout):
        return "provider_unreachable", "Provider could not be reached."
    except requests.RequestException:
        return "provider_error", "Provider verification request failed."

    if response.ok:
        return "verified", None
    return _classify_http_failure(response.status_code, _response_code(response))


def _classify_http_failure(status_code: int, code: str | None) -> tuple[CloudStatus, str]:
    normalized = (code or "").lower()
    if status_code == 401:
        return "unauthorized", "Provider rejected the configured credentials."
    if status_code == 403:
        return "unauthorized", "Provider denied access to this agent."
    if status_code == 404:
        return "model_unavailable", "Configured model is not available to this provider account."
    if "billing" in normalized or "payment" in normalized or "failed_precondition" in normalized:
        return "billing_blocked", "Provider reported a billing or account prerequisite."
    if "insufficient_quota" in normalized or "quota" in normalized or "credit" in normalized:
        return "quota_exhausted", "Provider reported exhausted quota or credits."
    if status_code == 429:
        return "rate_limited", "Provider rate limit is currently active."
    if status_code >= 500:
        return "provider_unreachable", "Provider service is temporarily unavailable."
    return "provider_error", "Provider rejected the verification request."


def _record(status: CloudStatus, reason: str | None, source: StatusSource) -> CloudStatusRecord:
    ttl = _SUCCESS_TTL
    if status in {"rate_limited", "provider_unreachable", "provider_error"}:
        ttl = _TRANSIENT_TTL
    elif status in {"quota_exhausted", "billing_blocked"}:
        ttl = _ACCOUNT_TTL
    now = _now()
    return CloudStatusRecord(status, reason, now, now + ttl, source)


def _response_code(response: requests.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("code", "type", "status"):
            value = error.get(key)
            if isinstance(value, str):
                return value
    for key in ("code", "status"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


def _exception_text(exc: BaseException) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return " ".join(str(error.get(key) or "") for key in ("code", "type", "status"))
    return " ".join(str(getattr(exc, key, "") or "") for key in ("code", "type"))


def _now() -> datetime:
    return datetime.now(UTC)
