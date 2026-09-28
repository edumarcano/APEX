"""Bounded asynchronous orchestration for archived conversation retention."""

from __future__ import annotations

import asyncio

from core.conversations.store import (
    MAX_CONVERSATION_PURGE_BATCH_SIZE,
    ConversationStore,
)


async def purge_expired_archived_conversations(
    store: ConversationStore,
    *,
    retention_days: int,
    stop_event: asyncio.Event,
) -> int:
    """Drain expired archives in bounded transactions until none remain."""
    total_deleted = 0
    while not stop_event.is_set():
        deleted = await asyncio.to_thread(
            store.purge_expired_archived,
            retention_days=retention_days,
            limit=MAX_CONVERSATION_PURGE_BATCH_SIZE,
        )
        total_deleted += deleted
        if deleted < MAX_CONVERSATION_PURGE_BATCH_SIZE:
            break
        # Let shutdown and other application tasks run between write batches.
        await asyncio.sleep(0)
    return total_deleted
