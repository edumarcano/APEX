"""Equal-weight sync health scoring from typed connector results."""

from __future__ import annotations

from collections.abc import Mapping

from core.connectors.models import (
    ConnectorHealthEntry,
    ConnectorResult,
    SyncHealthReport,
)


def _legacy_failure_name(connector_name: str) -> str:
    """Map independent sports modules onto the legacy sports failure label."""
    if connector_name in {"f1", "football"}:
        return "sports"
    return connector_name


def compute_sync_health(
    results: Mapping[str, ConnectorResult | None],
) -> SyncHealthReport:
    """
    Score enabled connectors equally.

    ``None`` and ``disabled`` entries are excluded from the denominator.
    Healthy contributes ``1.0``, degraded ``0.5``, unavailable ``0.0``.
    """
    scored: list[ConnectorResult] = [
        result
        for result in results.values()
        if result is not None and result.status != "disabled"
    ]
    # Public health rows include disabled modules for snapshot consumers, but
    # scoring below uses ``scored`` only.
    all_present: list[ConnectorResult] = [
        result for result in results.values() if result is not None
    ]
    connector_health = [
        ConnectorHealthEntry(
            name=result.name,
            status=result.status,
            freshness=result.freshness,
            reason_code=result.reason_code,
            observed_at=result.observed_at,
        )
        for result in all_present
    ]

    failed: list[str] = []
    for result in scored:
        if result.status != "unavailable":
            continue
        legacy_name = _legacy_failure_name(result.name)
        if legacy_name not in failed:
            failed.append(legacy_name)

    if not scored:
        return SyncHealthReport(
            sync_health_score=100.0,
            connector_health=connector_health,
            failed_connectors=failed,
        )

    earned = sum(result.score_weight for result in scored)
    score = round(max(0.0, min(100.0, (earned / len(scored)) * 100.0)), 1)
    return SyncHealthReport(
        sync_health_score=score,
        connector_health=connector_health,
        failed_connectors=failed,
    )
