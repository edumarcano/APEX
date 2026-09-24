"""Callable selection-to-publication boundary for the Context vault."""

from __future__ import annotations

from core.context_vault.publisher import ContextVaultPublishResult, ContextVaultPublisher
from core.context_vault.render import ContextVaultMarkdownRenderer
from core.context_vault.selection import ContextVaultSelectionService


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
