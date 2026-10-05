"""Durable, approval-gated action domain primitives with lazy service imports."""

from importlib import import_module

_EXPORTS = {name: "models" for name in (
    "ActionEvent", "ActionProposal", "ActionRecord", "ExecutionOutcome", "VerificationOutcome",
)}
_EXPORTS.update({name: "runtime" for name in ("get_action_service", "set_action_service")})
_EXPORTS.update({name: "service" for name in ("ActionExecutor", "ActionService", "ActionVerifier")})
_EXPORTS.update({name: "store" for name in (
    "ActionConflictError", "ActionIntegrityError", "ActionNotFoundError", "ActionStore",
    "ActionTransitionError",
)})
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"core.actions.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
