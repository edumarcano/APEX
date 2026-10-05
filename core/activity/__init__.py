"""Immutable external activity report storage and local service boundary."""

from importlib import import_module

_EXPORTS = {name: "models" for name in (
    "ActivityDisposition", "ActivityReport", "ActivityReportContent",
    "ActivitySubmissionRequest", "ActivitySubmissionReceipt",
)}
_EXPORTS.update({name: "service" for name in (
    "ActivityNotFoundError", "ActivityService", "ActivityUnavailableError",
    "get_activity_service", "set_activity_service",
)})
_EXPORTS.update({name: "store" for name in (
    "ActivityConflictError", "ActivityStore", "ActivityStoreError",
)})
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"core.activity.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
