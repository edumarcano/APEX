"""Process-local telemetry snapshot store."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from core.connectors.models import CONNECTOR_NAMES, ConnectorHealthEntry, ConnectorResult, utc_now_iso
from core.connectors.scoring import compute_sync_health
from core.telemetry.models import TelemetryModuleEntry, TelemetrySnapshot


def _parse_collected_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_retaining_failure(new: ConnectorResult, prior: TelemetryModuleEntry | None) -> bool:
    """True when a failed refresh should keep the previous healthy/degraded module."""
    if prior is None:
        return False
    if prior.status in {"disabled", "unavailable"}:
        return False
    return new.status == "unavailable"


def build_snapshot_from_results(
    results: dict[str, ConnectorResult],
    *,
    prior: TelemetrySnapshot | None = None,
) -> TelemetrySnapshot:
    """
    Build a complete snapshot from connector results.

    When ``prior`` is set, modules missing from ``results`` are carried forward.
    Unavailable refresh results retain the prior healthy/degraded entry as stale.
    """
    modules: dict[str, TelemetryModuleEntry] = {}
    if prior is not None:
        modules = {name: entry.model_copy(deep=True) for name, entry in prior.modules.items()}

    for name, result in results.items():
        prior_entry = modules.get(name)
        if _is_retaining_failure(result, prior_entry) and prior_entry is not None:
            retained = prior_entry.model_copy(deep=True)
            retained.freshness = "stale"
            retained.reason_code = result.reason_code or "refresh_failed"
            modules[name] = retained
            continue
        modules[name] = TelemetryModuleEntry.from_connector_result(result)

    for name in CONNECTOR_NAMES:
        modules.setdefault(
            name,
            TelemetryModuleEntry(
                name=name,
                status="disabled",
                freshness="none",
                reason_code="disabled",
                observed_at=utc_now_iso(),
            ),
        )

    report = compute_sync_health(
        {
            name: (
                None
                if entry.status == "disabled"
                else entry.to_connector_result()
            )
            for name, entry in modules.items()
        }
    )
    connector_health = [
        ConnectorHealthEntry(
            name=modules[name].name,
            status=modules[name].status,
            freshness=modules[name].freshness,
            reason_code=modules[name].reason_code,
            observed_at=modules[name].observed_at,
        )
        for name in CONNECTOR_NAMES
    ]

    return TelemetrySnapshot(
        modules=modules,
        sync_health_score=report.sync_health_score,
        connector_health=connector_health,
        failed_connectors=report.failed_connectors,
        collected_at=utc_now_iso(),
    )


class TelemetrySnapshotStore:
    """Thread-safe in-memory holder for the current telemetry snapshot."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot: TelemetrySnapshot | None = None
        self._last_forced_refresh_at: datetime | None = None

    def get(self) -> TelemetrySnapshot | None:
        with self._lock:
            return self._snapshot

    def set(self, snapshot: TelemetrySnapshot) -> TelemetrySnapshot:
        with self._lock:
            self._snapshot = snapshot
            return snapshot

    def clear(self) -> None:
        with self._lock:
            self._snapshot = None
            self._last_forced_refresh_at = None

    def mark_forced_refresh(self, when: datetime | None = None) -> None:
        with self._lock:
            self._last_forced_refresh_at = when or datetime.now(timezone.utc)

    def last_forced_refresh_at(self) -> datetime | None:
        with self._lock:
            return self._last_forced_refresh_at

    def age_seconds(self) -> float | None:
        with self._lock:
            if self._snapshot is None:
                return None
            collected = _parse_collected_at(self._snapshot.collected_at)
            return (datetime.now(timezone.utc) - collected).total_seconds()

    def connectors_are_fresh(
        self,
        names: list[str],
        *,
        enabled_names: set[str],
        max_age_seconds: float,
    ) -> bool:
        """Return whether requested modules match settings and are within the TTL."""
        with self._lock:
            if self._snapshot is None:
                return False

            now = datetime.now(timezone.utc)
            for name in names:
                entry = self._snapshot.modules.get(name)
                if entry is None:
                    return False

                expected_enabled = name in enabled_names
                if not expected_enabled:
                    if entry.status != "disabled":
                        return False
                    continue

                if entry.status == "disabled" or entry.observed_at is None:
                    return False
                try:
                    observed = _parse_collected_at(entry.observed_at)
                except (TypeError, ValueError):
                    return False
                if (now - observed).total_seconds() >= max_age_seconds:
                    return False

            return True
