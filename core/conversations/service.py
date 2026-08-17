"""Partition-aware application service for Cortex conversations."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from core.config import is_dev_mode
from core.conversations.models import ConversationCreateRequest, ConversationPatchRequest
from core.conversations.store import ConversationStore
from core.settings import get_settings_store

_service: "ConversationService | None" = None


def set_conversation_service(service: "ConversationService | None") -> None:
    global _service
    _service = service


def get_conversation_service() -> "ConversationService":
    if _service is None:
        raise RuntimeError("Conversation service is unavailable.")
    return _service


class ConversationService:
    def __init__(self, store: ConversationStore, *, history_limit: int) -> None:
        self.store = store
        self.history_limit = history_limit

    @staticmethod
    def partition() -> str:
        sandbox = is_dev_mode() and get_settings_store().get_snapshot().ask_apex.sandbox_mode
        return "sandbox" if sandbox else "production"

    @staticmethod
    def default_agent() -> str:
        return get_settings_store().get_snapshot().ask_apex.agent

    def create(self, request: ConversationCreateRequest):
        return self.store.create(
            conversation_id=uuid4(), title=request.title or "New conversation", partition=self.partition(),
            origin=request.origin, agent=request.agent or self.default_agent(),
            selected_tool_names=request.selected_tool_names, tool_profile_id=request.tool_profile_id,
        )

    def list(self, archived: bool):
        return self.store.list(self.partition(), archived)

    def detail(self, conversation_id: UUID):
        return self.store.detail(conversation_id, self.partition())

    def active_history(self, conversation_id: UUID):
        return self.store.active_history(conversation_id, self.partition(), self.history_limit)

    def patch(self, conversation_id: UUID, request: ConversationPatchRequest):
        updates = request.model_dump(exclude_unset=True)
        return self.store.patch(conversation_id, self.partition(), updates)

    def delete(self, conversation_id: UUID) -> None:
        self.store.delete(conversation_id, self.partition())

    def begin_turn(self, conversation_id: UUID, *, user_id: UUID, agent_id: UUID, parent_id: UUID | None, prompt: str, agent: str, request_metadata: dict[str, Any], selected_tool_names: list[str] | None, tool_profile_id: str | None):
        return self.store.begin_turn(conversation_id=conversation_id, partition=self.partition(), user_id=user_id, agent_id=agent_id, parent_id=parent_id, prompt=prompt, agent=agent, request_metadata=request_metadata, selected_tool_names=selected_tool_names, tool_profile_id=tool_profile_id, history_limit=self.history_limit)

    def finalize(self, conversation_id: UUID, agent_id: UUID, *, answer: str, status: str, response_metadata: dict[str, Any]):
        return self.store.finalize(conversation_id=conversation_id, agent_id=agent_id, answer=answer, status=status, response_metadata=response_metadata)

    def recover_interrupted(self) -> int:
        return self.store.recover_interrupted()
