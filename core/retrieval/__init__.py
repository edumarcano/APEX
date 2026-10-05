"""Local retrieval substrate for durable APEX context sources."""

from importlib import import_module

_EXPORTS = {
    "RetrievalHit": "models", "RetrievalStatus": "models",
    "RetrievalBusyError": "service", "RetrievalService": "service",
    "get_retrieval_service": "service", "set_retrieval_service": "service",
    "RetrievalStore": "store",
}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"core.retrieval.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
