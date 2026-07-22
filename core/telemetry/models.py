"""In-memory telemetry snapshot contracts."""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from core.connectors.models import (
    CONNECTOR_NAMES,
    ConnectorFreshness,
    ConnectorHealthEntry,
    ConnectorResult,
    ConnectorStatus,
    utc_now_iso,
)

ModuleName = Literal[
    "weather",
    "news",
    "email",
    "calendar",
    "f1",
    "football",
    "reminders",
]

FRESHNESS_WINDOW_SECONDS = 300


class TelemetryModuleEntry(BaseModel):
    """Typed per-module telemetry entry for a snapshot."""

    name: str
    status: ConnectorStatus
    freshness: ConnectorFreshness = "none"
    reason_code: str = "ok"
    observed_at: str | None = None
    display_text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_connector_result(cls, result: ConnectorResult) -> TelemetryModuleEntry:
        return cls(
            name=result.name,
            status=result.status,
            freshness=result.freshness,
            reason_code=result.reason_code,
            observed_at=result.observed_at,
            display_text=result.display_text,
            data=dict(result.data),
        )

    def to_connector_result(self) -> ConnectorResult:
        return ConnectorResult(
            name=self.name,
            status=self.status,
            freshness=self.freshness,
            reason_code=self.reason_code,
            observed_at=self.observed_at or utc_now_iso(),
            display_text=self.display_text,
            data=dict(self.data),
        )


class TelemetrySnapshot(BaseModel):
    """Process-local telemetry snapshot (not persisted to SQLite)."""

    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    collected_at: str = Field(default_factory=utc_now_iso)
    modules: dict[str, TelemetryModuleEntry] = Field(default_factory=dict)
    sync_health_score: float = 100.0
    connector_health: list[ConnectorHealthEntry] = Field(default_factory=list)
    failed_connectors: list[str] = Field(default_factory=list)

    def results_map(self) -> dict[str, ConnectorResult | None]:
        """Map module entries to connector results; missing keys stay absent."""
        out: dict[str, ConnectorResult | None] = {name: None for name in CONNECTOR_NAMES}
        for name, entry in self.modules.items():
            if entry.status == "disabled":
                out[name] = None
            else:
                out[name] = entry.to_connector_result()
        return out


class TelemetryRefreshRequest(BaseModel):
    """Optional connector filter and force flag for telemetry refresh."""

    connectors: list[str] | None = Field(
        default=None,
        description=(
            "Connector names to refresh. Omitted or empty refreshes all enabled "
            "connectors."
        ),
    )
    force: bool = Field(
        default=False,
        description=(
            "When true, bypass the five-minute freshness window and execute "
            "connector calls."
        ),
    )


PreflightOperation = Literal[
    "activate",
    "activate_with_briefing",
    "refresh_telemetry",
    "generate_briefing",
    "assistant_query",
]

PreflightWarningCode = Literal[
    "outside_configured_network",
    "network_trust_unknown",
    "running_on_battery",
    "rapid_connector_refresh",
    "cloud_data_disclosure",
    "high_resource_local_profile",
]

PreflightBlockerCode = Literal[
    "missing_credentials",
    "model_unreachable",
    "model_not_installed",
    "concurrent_local_execution",
    "insufficient_ram",
    "cpu_overloaded",
    "database_failure",
    "configuration_failure",
    "invalid_input",
    "model_load_failure",
]


class PreflightWarning(BaseModel):
    code: PreflightWarningCode
    message: str


class PreflightBlocker(BaseModel):
    code: PreflightBlockerCode
    message: str


class PreflightRequest(BaseModel):
    """Identify a planned operation for advisory risk evaluation."""

    operation: PreflightOperation
    connectors: list[str] | None = None
    synthesis_profile: str | None = None
    force: bool = False
    involves_cloud: bool = False
    acknowledged_warnings: list[str] = Field(default_factory=list)
    cloud_disclosure_acknowledged: bool = False


class PreflightResponse(BaseModel):
    """Advisory warnings plus non-overridable blockers."""

    warnings: list[PreflightWarning] = Field(default_factory=list)
    blockers: list[PreflightBlocker] = Field(default_factory=list)
    can_proceed: bool = True
