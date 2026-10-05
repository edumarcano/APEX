"""Source-tracked internal personal knowledge domain."""

from importlib import import_module

_EXPORTS = {
    name: "service" for name in
    ("KnowledgeService", "get_knowledge_service", "set_knowledge_service")
}
_EXPORTS.update({name: "store" for name in (
    "KnowledgeConflictError", "KnowledgeNotFoundError", "KnowledgeStore",
    "KnowledgeStoreError", "normalize_alias",
)})
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"core.knowledge.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
