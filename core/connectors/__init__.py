"""Typed connector collection and sync-health scoring."""

from core.connectors.models import (
    CONNECTOR_NAMES,
    ConnectorFreshness,
    ConnectorHealthEntry,
    ConnectorResult,
    ConnectorStatus,
    SyncHealthReport,
    utc_now_iso,
)
from core.connectors.scoring import compute_sync_health

__all__ = [
    "CONNECTOR_NAMES",
    "ConnectorFreshness",
    "ConnectorHealthEntry",
    "ConnectorResult",
    "ConnectorStatus",
    "SyncHealthReport",
    "compute_sync_health",
    "utc_now_iso",
]
