"""Telemetry refresh orchestration with freshness window and refresh lock."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from core import config
from core.connectors.models import (
    CONNECTOR_NAMES,
    EXTERNAL_CONNECTOR_NAMES,
    ConnectorResult,
    utc_now_iso,
)
from core.connectors.scoring import compute_sync_health
from core.settings import get_settings_store
from core.telemetry.collector import (
    collect_connector_results,
    disabled_result,
    enabled_connector_names,
)
from core.telemetry.models import (
    FRESHNESS_WINDOW_SECONDS,
    TelemetryModuleEntry,
    TelemetrySnapshot,
)
from core.telemetry.store import TelemetrySnapshotStore, build_snapshot_from_results

_LOGGER = logging.getLogger(__name__)


class RefreshInProgressError(RuntimeError):
    """Raised when a non-blocking refresh lock cannot be acquired."""


def _demo_snapshot() -> TelemetrySnapshot:
    """Build a typed static snapshot from DEMO_MODE mock telemetry."""
    # Lazy import avoids a circular dependency with core.api.
    from core.api.demo import load_mock_telemetry

    telemetry, digest = load_mock_telemetry()
    modules: dict[str, TelemetryModuleEntry] = {}
    health_by_name = {
        entry.name: entry for entry in digest.connector_health
    }

    display_by_name = {
        "weather": telemetry.weather,
        "news": telemetry.news,
        "email": telemetry.email,
        "calendar": telemetry.calendar,
        "reminders": telemetry.reminders,
        "f1": telemetry.sports,
        "football": "",
    }

    for name in CONNECTOR_NAMES:
        health = health_by_name.get(name)
        if health is not None:
            modules[name] = TelemetryModuleEntry(
                name=name,
                status=health.status,
                freshness=health.freshness,
                reason_code=health.reason_code,
                observed_at=health.observed_at or utc_now_iso(),
                display_text=display_by_name.get(name, ""),
                data={},
            )
        else:
            modules[name] = TelemetryModuleEntry.from_connector_result(
                disabled_result(name)
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
    return TelemetrySnapshot(
        modules=modules,
        sync_health_score=(
            digest.sync_health_score
            if digest.sync_health_score is not None
            else report.sync_health_score
        ),
        connector_health=list(digest.connector_health) or report.connector_health,
        failed_connectors=list(digest.failed_connectors),
        collected_at=utc_now_iso(),
    )


class TelemetryService:
    """Process-local telemetry collection, store, and refresh coordination."""

    def __init__(self, store: TelemetrySnapshotStore | None = None) -> None:
        self._store = store or TelemetrySnapshotStore()
        self._refresh_lock = threading.Lock()

    @property
    def store(self) -> TelemetrySnapshotStore:
        return self._store

    def latest(self) -> TelemetrySnapshot | None:
        return self._store.get()

    def had_forced_refresh_within_window(self) -> bool:
        last = self._store.last_forced_refresh_at()
        if last is None:
            return False
        age = (datetime.now(timezone.utc) - last).total_seconds()
        return age < FRESHNESS_WINDOW_SECONDS

    def refresh(
        self,
        *,
        connectors: list[str] | None = None,
        force: bool = False,
    ) -> TelemetrySnapshot:
        """
        Refresh telemetry and return the resulting complete snapshot.

        Raises:
            RefreshInProgressError: when another refresh holds the lock.
            ValueError: when connector names are invalid.
        """
        acquired = self._refresh_lock.acquire(blocking=False)
        if not acquired:
            raise RefreshInProgressError("Telemetry refresh already in progress.")

        try:
            return self._refresh_locked(connectors=connectors, force=force)
        finally:
            self._refresh_lock.release()

    def _refresh_locked(
        self,
        *,
        connectors: list[str] | None,
        force: bool,
    ) -> TelemetrySnapshot:
        names = list(connectors) if connectors else None
        if names is not None:
            unknown = sorted(set(names) - set(CONNECTOR_NAMES))
            if unknown:
                raise ValueError(f"Unknown connector names: {unknown}")
        if names is not None and len(names) == 0:
            names = None

        if config.DEMO_MODE:
            snapshot = _demo_snapshot()
            self._store.set(snapshot)
            return snapshot

        current = self._store.get()
        settings = get_settings_store().get_snapshot()
        enabled_names = enabled_connector_names(
            features=settings.features,
            modules=settings.modules,
        )
        target_names = names or list(CONNECTOR_NAMES)
        if (
            not force
            and current is not None
            and self._store.connectors_are_fresh(
                target_names,
                enabled_names=enabled_names,
                max_age_seconds=FRESHNESS_WINDOW_SECONDS,
            )
        ):
            _LOGGER.info(
                "Returning fresh telemetry snapshot without connector calls",
            )
            return current

        collected = collect_connector_results(
            features=settings.features,
            modules=settings.modules,
            connectors=names,
        )

        # Partial refresh merges into the prior complete snapshot.
        prior = current if names is not None else None
        if names is None:
            # Full refresh: include explicit disabled state for every module.
            full: dict[str, ConnectorResult] = dict(collected)
            for name in CONNECTOR_NAMES:
                full.setdefault(name, disabled_result(name))
            snapshot = build_snapshot_from_results(full, prior=current)
        else:
            snapshot = build_snapshot_from_results(collected, prior=prior)

        self._store.set(snapshot)
        forced_external_refresh = force and any(
            name in enabled_names and name in EXTERNAL_CONNECTOR_NAMES
            for name in target_names
        )
        if forced_external_refresh:
            self._store.mark_forced_refresh()
        return snapshot

    def collect_for_briefing(self) -> TelemetrySnapshot:
        """Force-collect all enabled connectors for the legacy trigger pipeline."""
        return self.refresh(force=True)

    def seed_demo_snapshot(self) -> TelemetrySnapshot:
        """Install the static DEMO_MODE snapshot without external connector calls."""
        snapshot = _demo_snapshot()
        return self._store.set(snapshot)


_telemetry_service: TelemetryService | None = None
_service_lock = threading.Lock()


def get_telemetry_service() -> TelemetryService:
    """Return the process-wide telemetry service singleton."""
    global _telemetry_service
    with _service_lock:
        if _telemetry_service is None:
            _telemetry_service = TelemetryService()
        return _telemetry_service


def reset_telemetry_service_for_tests() -> None:
    """Clear the singleton (test helper)."""
    global _telemetry_service
    with _service_lock:
        if _telemetry_service is not None:
            _telemetry_service.store.clear()
        _telemetry_service = None
