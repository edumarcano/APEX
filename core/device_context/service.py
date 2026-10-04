"""Thread-safe on-demand location acquisition over the private host channel."""

from __future__ import annotations

import math
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Mapping

LOCATION_FIX_MAX_AGE_SECONDS = 900.0
LOCATION_REQUEST_TIMEOUT_SECONDS = 12.0
_NATIVE_TIMEOUT_SECONDS = 10.0
_PERMISSIONS = frozenset({"unknown", "granted", "denied", "revoked", "unsupported"})
_AVAILABILITIES = frozenset({"unknown", "available", "unavailable", "timed_out", "unsupported"})
_OUTCOMES = frozenset({
    "ok", "permission_required", "denied", "revoked", "unavailable",
    "timed_out", "expired", "unsupported",
})
_LOCK = threading.RLock()
_SERVICE: "DeviceContextService | None" = None


@dataclass(frozen=True, slots=True)
class WeatherLocation:
    """Resolved location; coordinates remain internal and are never status output."""

    location: str | None
    source: str
    coordinates: tuple[float, float] | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class DeviceContextStatus:
    enabled: bool
    permission: str
    availability: str
    source: str
    freshness: str
    fix_age_seconds: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "permission": self.permission,
            "availability": self.availability,
            "source": self.source,
            "freshness": self.freshness,
            "fix_age_seconds": self.fix_age_seconds,
        }


class DeviceContextService:
    """Own one session's preference, permission signal, and ephemeral location fix."""

    def __init__(
        self,
        *,
        instance_id: str,
        enabled: bool,
        supported: bool,
        request_sink: Callable[[dict[str, object], str], bool] | None,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.instance_id = str(uuid.UUID(instance_id))
        self._enabled = bool(enabled)
        self._supported = bool(supported and request_sink is not None)
        self._request_sink = request_sink
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._condition = threading.Condition(threading.RLock())
        self._revision = 1
        self._request_sequence = 0
        self._state_sequence = 0
        self._permission = "unknown" if self._supported else "unsupported"
        self._availability = "unknown" if self._supported else "unsupported"
        self._pending_id: str | None = None
        self._pending_revision: int | None = None
        self._completed: dict[
            str, tuple[str, int, int, tuple[float, float, float, float, float] | None]
        ] = {}
        self._pending_readers = 0
        self._fix: tuple[float, float, float, float, float] | None = None
        self._last_fix_expired = False
        self._closed = False

    @property
    def revision(self) -> int:
        with self._condition:
            return self._revision

    def preference_payload(self) -> dict[str, object]:
        with self._condition:
            return {
                "instance_id": self.instance_id,
                "revision": self._revision,
                "location_enabled": self._enabled,
            }

    def set_enabled(self, enabled: bool) -> bool:
        """Apply only a durably committed preference; return whether it changed."""
        with self._condition:
            if self._closed or self._enabled is enabled:
                return False
            self._enabled = enabled
            self._revision += 1
            self._clear_fix_locked()
            self._scrub_completed_fixes_locked()
            self._finish_pending_locked("revoked")
            self._permission = "unknown" if self._supported else "unsupported"
            self._availability = "unknown" if self._supported else "unsupported"
            self._condition.notify_all()
            return True

    def handle_state(self, payload: Mapping[str, object], request_id: str) -> bool:
        """Apply a valid current-generation native permission/capability signal."""
        with self._condition:
            if (
                self._closed
                or payload.get("instance_id") != self.instance_id
                or payload.get("revision") != self._revision
            ):
                return False
            sequence_text = request_id.removeprefix("device-state:")
            if not sequence_text.isdecimal():
                return False
            sequence = int(sequence_text)
            if sequence <= self._state_sequence:
                return False
            permission = payload.get("permission")
            availability = payload.get("availability")
            if (
                not isinstance(permission, str)
                or permission not in _PERMISSIONS
                or not isinstance(availability, str)
                or availability not in _AVAILABILITIES
            ):
                return False
            self._state_sequence = sequence
            changed = permission != self._permission or availability != self._availability
            self._permission = str(permission)
            self._availability = str(availability)
            if self._permission != "granted" or self._availability != "available":
                self._clear_fix_locked()
                self._scrub_completed_fixes_locked()
                if self._pending_id is not None and self._permission != "granted":
                    self._finish_pending_locked(
                        "revoked" if self._permission == "revoked" else "permission_required"
                    )
            if changed:
                self._condition.notify_all()
            return True

    def handle_result(self, payload: Mapping[str, object], request_id: str) -> bool:
        """Apply only the result matching the active request, instance, and revision."""
        with self._condition:
            if (
                self._closed
                or self._pending_id != request_id
                or payload.get("instance_id") != self.instance_id
                or payload.get("revision") != self._revision
                or self._pending_revision != self._revision
            ):
                return False
            outcome = payload.get("outcome")
            if not isinstance(outcome, str) or outcome not in _OUTCOMES:
                return False
            self._clear_fix_locked()
            if outcome == "ok":
                fix = payload.get("fix")
                if not isinstance(fix, Mapping) or set(fix) != {
                    "latitude", "longitude", "observed_at"
                }:
                    self._finish_pending_locked("unavailable")
                    self._availability = "unavailable"
                    return True
                latitude = fix.get("latitude")
                longitude = fix.get("longitude")
                observed_at = fix.get("observed_at")
                if not all(_finite_number(value) for value in (latitude, longitude, observed_at)):
                    self._finish_pending_locked("unavailable")
                    self._availability = "unavailable"
                    return True
                latitude, longitude, observed_at = float(latitude), float(longitude), float(observed_at)
                age = self._wall_clock() - observed_at
                if age < 0 or age > LOCATION_FIX_MAX_AGE_SECONDS:
                    self._finish_pending_locked("expired")
                    self._availability = "unavailable"
                    self._last_fix_expired = True
                    return True
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    self._finish_pending_locked("unavailable")
                    self._availability = "unavailable"
                    return True
                self._fix = (
                    latitude,
                    longitude,
                    observed_at,
                    self._monotonic_clock(),
                    max(0.0, age),
                )
                self._last_fix_expired = False
                self._permission = "granted"
                self._availability = "available"
            else:
                self._fix = None
                if outcome == "permission_required":
                    self._permission = "unknown"
                    self._availability = "unavailable"
                elif outcome == "denied":
                    self._permission = "denied"
                    self._availability = "unavailable"
                elif outcome == "revoked":
                    self._permission = "revoked"
                    self._availability = "unavailable"
                elif outcome == "unsupported":
                    self._permission = "unsupported"
                    self._availability = "unsupported"
                elif outcome == "timed_out":
                    self._availability = "timed_out"
                else:
                    self._availability = "unavailable"
                    if outcome == "expired":
                        self._last_fix_expired = True
            self._finish_pending_locked(str(outcome), self._fix if outcome == "ok" else None)
            return True

    def status(self) -> DeviceContextStatus:
        """Return sanitized state without prompting or starting native work."""
        with self._condition:
            had_fix = self._fix is not None
            age = self._fix_age_locked()
            if had_fix and age is None:
                self._clear_fix_locked(expired=True)
            if self._enabled and self._supported and self._permission == "granted" and age is not None:
                source = "device"
            elif _configured_location():
                source = "configured"
            else:
                source = "none"
            return DeviceContextStatus(
                enabled=self._enabled,
                permission=self._permission,
                availability=self._availability,
                source=source,
                freshness="fresh" if age is not None else "expired" if (had_fix or self._last_fix_expired) else "none",
                fix_age_seconds=age,
            )

    def resolve(self, explicit_location: str | None = None) -> WeatherLocation:
        """Resolve explicit, permissioned device, then configured location synchronously."""
        if isinstance(explicit_location, str) and explicit_location.strip():
            return WeatherLocation(explicit_location.strip(), "explicit", revision=self.revision)
        with self._condition:
            if self._closed or not (self._enabled and self._supported):
                return _configured_result(self._revision)
            if self._permission != "granted":
                return _configured_result(self._revision)
            if self._request_sink is None:
                return _configured_result(self._revision)
            if self._pending_id is None:
                self._request_sequence += 1
                request_id = f"device:{self._request_sequence}"
                self._pending_id = request_id
                self._pending_revision = self._revision
                self._pending_outcome = None
                self._pending_readers = 0
                payload: dict[str, object] = {
                    "instance_id": self.instance_id,
                    "revision": self._revision,
                }
                leader = True
            else:
                request_id = self._pending_id
                payload = {}
                leader = False
            self._pending_readers += 1
            revision = self._revision
        if leader:
            try:
                sent = self._request_sink(payload, request_id)
            except Exception:
                sent = False
            if not sent:
                with self._condition:
                    if self._pending_id == request_id:
                        self._availability = "unavailable"
                        self._finish_pending_locked("unavailable")
        deadline = self._monotonic_clock() + LOCATION_REQUEST_TIMEOUT_SECONDS
        with self._condition:
            while request_id not in self._completed:
                remaining = deadline - self._monotonic_clock()
                if remaining <= 0:
                    if self._pending_id == request_id:
                        self._availability = "timed_out"
                        self._finish_pending_locked("timed_out")
                    break
                self._condition.wait(timeout=min(remaining, _NATIVE_TIMEOUT_SECONDS))
            completion = self._completed.get(request_id)
            if completion is not None:
                outcome, completed_revision, remaining_readers, completed_fix = completion
                if remaining_readers <= 1:
                    self._completed.pop(request_id, None)
                else:
                    self._completed[request_id] = (
                        outcome, completed_revision, remaining_readers - 1, completed_fix
                    )
            else:
                outcome, completed_revision, completed_fix = None, None, None
            if (outcome, completed_revision) == ("ok", revision) and self._revision == revision:
                age = self._fix_age_for(completed_fix)
                if (
                    completed_fix is not None
                    and self._enabled
                    and self._permission == "granted"
                    and self._availability == "available"
                    and age is not None
                    and age <= LOCATION_FIX_MAX_AGE_SECONDS
                ):
                    return WeatherLocation(
                        "Current area", "device", (completed_fix[0], completed_fix[1]), revision
                    )
        return _configured_result(self.revision)

    def channel_lost(self) -> None:
        with self._condition:
            self._clear_fix_locked()
            self._scrub_completed_fixes_locked()
            self._permission = "unknown" if self._supported else "unsupported"
            self._availability = "unavailable" if self._supported else "unsupported"
            self._finish_pending_locked("unavailable")
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._clear_fix_locked()
            self._scrub_completed_fixes_locked()
            self._permission = "unknown" if self._supported else "unsupported"
            self._availability = "unavailable" if self._supported else "unsupported"
            self._finish_pending_locked("unavailable")
            self._condition.notify_all()

    def _fix_age_locked(self) -> float | None:
        return self._fix_age_for(self._fix)

    def _fix_age_for(
        self, fix: tuple[float, float, float, float, float] | None
    ) -> float | None:
        if fix is None:
            return None
        age = self._wall_clock() - fix[2]
        monotonic_age = fix[4] + (self._monotonic_clock() - fix[3])
        if age < 0 or age > LOCATION_FIX_MAX_AGE_SECONDS or monotonic_age > LOCATION_FIX_MAX_AGE_SECONDS:
            return None
        return max(0.0, age, monotonic_age)

    def _clear_fix_locked(self, *, expired: bool = False) -> None:
        self._fix = None
        self._last_fix_expired = expired

    def _finish_pending_locked(
        self,
        outcome: str,
        fix: tuple[float, float, float, float, float] | None = None,
    ) -> None:
        request_id = self._pending_id
        if request_id is None:
            return
        self._completed[request_id] = (
            outcome,
            self._pending_revision or self._revision,
            self._pending_readers,
            fix,
        )
        if len(self._completed) > 16:
            self._completed.pop(next(iter(self._completed)))
        self._pending_id = None
        self._pending_revision = None
        self._pending_readers = 0
        self._condition.notify_all()

    def _scrub_completed_fixes_locked(self) -> None:
        for request_id, (outcome, revision, readers, _fix) in tuple(self._completed.items()):
            if outcome == "ok":
                self._completed[request_id] = ("revoked", revision, readers, None)


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _configured_location() -> str | None:
    value = os.getenv("TARGET_LOCATION", "").strip()
    return value or None


def _configured_result(revision: int = 0) -> WeatherLocation:
    configured = _configured_location()
    return WeatherLocation(configured, "configured" if configured else "none", revision=revision)


def set_device_context_service(service: DeviceContextService | None) -> None:
    global _SERVICE
    with _LOCK:
        old = _SERVICE
        _SERVICE = service
    if old is not None and old is not service:
        old.close()


def get_device_context_service() -> DeviceContextService | None:
    with _LOCK:
        return _SERVICE


def resolve_weather_location(explicit_location: str | None = None) -> WeatherLocation:
    service = get_device_context_service()
    if service is not None:
        return service.resolve(explicit_location)
    if isinstance(explicit_location, str) and explicit_location.strip():
        return WeatherLocation(explicit_location.strip(), "explicit")
    return _configured_result()


def default_weather_available() -> bool:
    return weather_location_eligible() or _configured_location() is not None


def weather_location_eligible() -> bool:
    service = get_device_context_service()
    if service is None:
        return False
    with service._condition:
        return service._enabled and service._supported and service._permission == "granted"


def weather_location_revision() -> int:
    service = get_device_context_service()
    return service.revision if service is not None else 0
