"""Cloudflare Access verification kept at the optional gateway boundary."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt
import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_JWKS_TIMEOUT_SECONDS = 5
_JWKS_FAILURE_COOLDOWN_SECONDS = 30.0


class CloudflareAccessVerificationError(RuntimeError):
    """A forwarded Access assertion cannot be trusted."""


class CloudflareAccessAuthorizationError(RuntimeError):
    """A valid Access assertion does not select exactly one registration."""


def _https_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("must be an absolute HTTPS URL without a query or fragment")
    return normalized


class CloudflareAccessBinding(BaseModel):
    """One remote registration selected by a distinct Access audience."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    audience: str = Field(min_length=1, max_length=512)
    allowed_subjects: list[str] = Field(min_length=1, max_length=50)

    @field_validator("audience")
    @classmethod
    def normalize_audience(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("allowed_subjects")
    @classmethod
    def normalize_subjects(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 256 for value in normalized):
            raise ValueError("must contain bounded non-blank subjects")
        return list(dict.fromkeys(normalized))

    @property
    def principal(self) -> str:
        """Keep Cloudflare identity outside the activity domain."""
        return f"client:{self.client_id}"


class CloudflareAccessConfiguration(BaseModel):
    """Non-secret Access issuer, signing-key endpoint, and client bindings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: str
    jwks_url: str
    bindings: list[CloudflareAccessBinding] = Field(min_length=1, max_length=50)
    key_cache_seconds: int = Field(default=300, ge=60, le=3600)

    @field_validator("issuer", "jwks_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return _https_url(value)

    @model_validator(mode="after")
    def require_distinct_bindings(self) -> "CloudflareAccessConfiguration":
        client_ids = [binding.client_id for binding in self.bindings]
        audiences = [binding.audience for binding in self.bindings]
        if len(client_ids) != len(set(client_ids)):
            raise ValueError("bindings must not repeat a client_id")
        if len(audiences) != len(set(audiences)):
            raise ValueError("bindings must use distinct audiences")
        return self

    def resolve_binding(self, claims: Mapping[str, object]) -> CloudflareAccessBinding:
        subject = claims.get("sub")
        audience_claim = claims.get("aud")
        if isinstance(audience_claim, str):
            audiences = {audience_claim}
        elif isinstance(audience_claim, list) and all(isinstance(item, str) for item in audience_claim):
            audiences = set(audience_claim)
        else:
            audiences = set()
        if not isinstance(subject, str) or not subject or not audiences:
            raise CloudflareAccessAuthorizationError("Cloudflare Access assertion is missing a usable subject or audience.")
        matches = [
            binding for binding in self.bindings
            if binding.audience in audiences and subject in binding.allowed_subjects
        ]
        if len(matches) != 1:
            raise CloudflareAccessAuthorizationError("Cloudflare Access assertion does not select one permitted registration.")
        return matches[0]


@dataclass(frozen=True, slots=True)
class CloudflareAccessIdentity:
    client_id: str
    principal: str


class CloudflareAccessVerifier:
    """Validate Access JWTs with a bounded in-memory signing-key cache."""

    def __init__(
        self,
        configuration: CloudflareAccessConfiguration,
        *,
        now: Callable[[], float] = time.monotonic,
        get: Callable[..., requests.Response] = requests.get,
    ) -> None:
        self.configuration = configuration
        self._now = now
        self._get = get
        self._keys: dict[str, jwt.PyJWK] = {}
        self._loaded_at: float | None = None
        self._unknown_key_refreshed_at: float | None = None
        self._refresh_failed_at: float | None = None
        self._lock = threading.Lock()

    def verify(self, assertion: str) -> Mapping[str, object]:
        if not assertion or len(assertion) > 16_384:
            raise CloudflareAccessVerificationError("Cloudflare Access assertion is missing or invalid.")
        try:
            header = jwt.get_unverified_header(assertion)
            key_id = header.get("kid")
            algorithm = header.get("alg")
        except jwt.PyJWTError as exc:
            raise CloudflareAccessVerificationError("Cloudflare Access assertion is invalid.") from exc
        if not isinstance(key_id, str) or not key_id or algorithm != "RS256":
            raise CloudflareAccessVerificationError("Cloudflare Access assertion uses an unsupported signing key.")
        key = self._key_for(key_id)
        try:
            claims = jwt.decode(
                assertion,
                key.key,
                algorithms=["RS256"],
                issuer=self.configuration.issuer,
                options={"require": ["exp", "sub", "aud"], "verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise CloudflareAccessVerificationError("Cloudflare Access assertion could not be verified.") from exc
        if not isinstance(claims, dict):
            raise CloudflareAccessVerificationError("Cloudflare Access assertion contains invalid claims.")
        return claims

    def _key_for(self, key_id: str) -> jwt.PyJWK:
        with self._lock:
            refreshed_for_expiry = (
                self._loaded_at is None
                or self._now() - self._loaded_at >= self.configuration.key_cache_seconds
            )
            if refreshed_for_expiry:
                self._require_refresh_after_cooldown()
                self._refresh_keys()
            key = self._keys.get(key_id)
            if key is None and refreshed_for_expiry:
                # The normal cache refresh already checked the current JWKS.
                self._unknown_key_refreshed_at = self._loaded_at
            elif key is None and (
                self._unknown_key_refreshed_at != self._loaded_at
                or (
                    self._refresh_failed_at is not None
                    and self._now() - self._refresh_failed_at >= _JWKS_FAILURE_COOLDOWN_SECONDS
                )
            ):
                # Consume this interval's forced-refresh allowance even when
                # the JWKS endpoint is unavailable, then fail closed.
                self._unknown_key_refreshed_at = self._loaded_at
                self._require_refresh_after_cooldown()
                self._refresh_keys()
                self._unknown_key_refreshed_at = self._loaded_at
                key = self._keys.get(key_id)
            if key is None:
                raise CloudflareAccessVerificationError("Cloudflare Access signing key is unavailable.")
            return key

    def _require_refresh_after_cooldown(self) -> None:
        if (
            self._refresh_failed_at is not None
            and self._now() - self._refresh_failed_at < _JWKS_FAILURE_COOLDOWN_SECONDS
        ):
            raise CloudflareAccessVerificationError("Cloudflare Access signing keys are temporarily unavailable.")

    def _refresh_keys(self) -> None:
        try:
            response = self._get(self.configuration.jwks_url, timeout=_JWKS_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            raw_keys = payload.get("keys") if isinstance(payload, dict) else None
            if not isinstance(raw_keys, list):
                raise ValueError("JWKS does not contain keys")
            keys = {
                key_id: jwt.PyJWK.from_dict(raw_key)
                for raw_key in raw_keys
                if isinstance(raw_key, dict)
                and isinstance((key_id := raw_key.get("kid")), str)
                and raw_key.get("kty") == "RSA"
                and raw_key.get("alg", "RS256") == "RS256"
            }
            if not keys:
                raise ValueError("JWKS does not contain usable RSA keys")
        except (requests.RequestException, ValueError, TypeError, jwt.PyJWTError) as exc:
            self._refresh_failed_at = self._now()
            raise CloudflareAccessVerificationError("Cloudflare Access signing keys are unavailable.") from exc
        self._keys = keys
        self._loaded_at = self._now()
        self._refresh_failed_at = None
