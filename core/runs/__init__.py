"""Cortex run ledger package with lazy service and coordinator imports."""

from importlib import import_module

_MODEL_EXPORTS = (
    "SAFE_ERROR_MESSAGES", "FinalMessageStatus", "RunCompletionEvidence", "RunError",
    "RunErrorCode", "RunLimitSnapshot", "RunPartition", "RunRecord",
    "RunRuntimeMeasurements", "RunStatus", "RunStopReason", "TraceId", "UsageQuality",
)
_EXPORTS = {name: "models" for name in _MODEL_EXPORTS}
_EXPORTS.update({name: "service" for name in ("RunHandle", "RunService", "get_run_service", "set_run_service")})
_EXPORTS.update({name: "coordinator" for name in (
    "ActiveConversationRunError", "CortexRunCoordinator", "RunCapacityError",
    "RunCoordinatorClosingError", "RunHttpError", "get_run_coordinator", "set_run_coordinator",
)})
_EXPORTS.update({name: "store" for name in ("RunConflictError", "RunNotFoundError", "RunStore", "RunStoreError")})
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"core.runs.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
