"""Durable Cortex conversation ownership and lifecycle services."""

from importlib import import_module

_EXPORTS = {
    "ConversationService": "service",
    "get_conversation_service": "service",
    "set_conversation_service": "service",
    "ConversationStore": "store",
}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"core.conversations.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
