"""Callable selection-to-publication boundary for the Context vault."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Mapping

from core.context_vault.publisher import ContextVaultPublishResult, ContextVaultPublisher
from core.context_vault.render import ContextVaultMarkdownRenderer
from core.context_vault.selection import ContextVaultScopeProjection, ContextVaultSelectionService


ContextVaultProjectionComparisonState = Literal[
    "compared", "no_prior_export", "destination_unconfigured", "export_restricted", "unavailable",
]


@dataclass(frozen=True, slots=True)
class ContextVaultProjectionChange:
    path: str
    action: Literal["added", "updated", "removed"]


@dataclass(frozen=True, slots=True)
class ContextVaultProjectionComparison:
    state: ContextVaultProjectionComparisonState
    changes: tuple[ContextVaultProjectionChange, ...] = ()


def compare_scope_projection(
    renderer: ContextVaultMarkdownRenderer,
    *,
    scope_id: str,
    projections: tuple[ContextVaultScopeProjection, ...],
    owned_file_hashes: Mapping[str, str] | None,
) -> ContextVaultProjectionComparison:
    """Compare one scope and the shared root index with the last local export."""
    prefix = f"scopes/{scope_id}/"
    current_hashes = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in renderer.render(projections).items()
        if path == "index.md" or path.startswith(prefix)
    }

    if owned_file_hashes is None:
        baseline: dict[str, str] = {}
        state: ContextVaultProjectionComparisonState = "no_prior_export"
    else:
        baseline = {
            path: digest for path, digest in owned_file_hashes.items()
            if path == "index.md" or path.startswith(prefix)
        }
        state = "compared"

    changes: list[ContextVaultProjectionChange] = []
    for path in sorted(current_hashes.keys() | baseline.keys()):
        current = current_hashes.get(path)
        previous = baseline.get(path)
        if current is None:
            changes.append(ContextVaultProjectionChange(path=path, action="removed"))
        elif previous is None:
            changes.append(ContextVaultProjectionChange(path=path, action="added"))
        elif current != previous:
            changes.append(ContextVaultProjectionChange(path=path, action="updated"))
    return ContextVaultProjectionComparison(state=state, changes=tuple(changes))


class ContextVaultMarkdownService:
    """Render and publish the current enabled selection on an explicit refresh."""

    def __init__(
        self,
        selection: ContextVaultSelectionService,
        publisher: ContextVaultPublisher,
        renderer: ContextVaultMarkdownRenderer | None = None,
    ) -> None:
        self._selection = selection
        self._publisher = publisher
        self._renderer = renderer or ContextVaultMarkdownRenderer()

    def refresh(self) -> ContextVaultPublishResult | None:
        """Publish an enabled vault; disabled vaults retain their existing files."""
        if not self._selection.vault_enabled:
            return None
        projection = self._renderer.render(self._selection.export_enabled_scopes())
        return self._publisher.publish(projection)
