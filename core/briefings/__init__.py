"""Persistent briefing session foundations."""

from importlib import import_module

_EXPORTS = {"BriefingService": "service", "BriefingSessionStore": "store"}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"core.briefings.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
