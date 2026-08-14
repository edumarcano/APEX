"""Single-user reminder authority backed by one selected Microsoft To Do list."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from clients.microsoft_todo_client import MicrosoftTodoClient
from clients.microsoft_auth import (
    MicrosoftTodoAuthenticationRequiredError,
    MicrosoftTodoNotConfiguredError,
)
from clients.microsoft_todo_client import (
    MicrosoftTodoInvalidInputError,
    MicrosoftTodoNotFoundError,
    MicrosoftTodoPermissionError,
    MicrosoftTodoThrottledError,
    MicrosoftTodoUpstreamError,
)
from core import database
from core.actions.models import ActionEvent, ActionRecord
from core.actions.service import ActionService
from core.connectors.models import utc_now_iso
from core.settings.store import get_settings_store

ReminderSourceState = Literal["live", "stale", "unavailable"]
_LOGGER = logging.getLogger(__name__)
_EXPECTED_READ_ERRORS = (
    MicrosoftTodoAuthenticationRequiredError,
    MicrosoftTodoNotConfiguredError,
    MicrosoftTodoInvalidInputError,
    MicrosoftTodoNotFoundError,
    MicrosoftTodoPermissionError,
    MicrosoftTodoThrottledError,
    MicrosoftTodoUpstreamError,
    TimeoutError,
)
_ACTIVE_ACTION_STATUSES = frozenset({"proposed", "approved", "executing", "verifying"})


class ReminderServiceError(RuntimeError):
    """Stable service failure suitable for a loopback API response."""

    def __init__(self, code: str, *, action_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.action_id = action_id


@dataclass(frozen=True)
class ReminderList:
    items: list[dict[str, str]]
    source_state: ReminderSourceState
    cache_timestamp: str | None
    pending_sync_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "items": self.items,
            "source_state": self.source_state,
            "cache_timestamp": self.cache_timestamp,
            "pending_sync_count": self.pending_sync_count,
        }


class ReminderService:
    """Own reminder reads, direct operator actions, cache, and local outbox."""

    def __init__(self, client: MicrosoftTodoClient, actions: ActionService) -> None:
        self._client = client
        self._actions = actions
        self._sync_lock = threading.Lock()

    def reconcile(self) -> None:
        """Apply terminal action results to linked local outbox rows after restart."""
        for row in database.fetch_linked_reminders():
            try:
                action = self._actions.get(row["sync_action_id"])
            except Exception:
                continue
            self._reconcile_row(row["id"], action)

    def list(self) -> ReminderList:
        """Read the selected list once, with a selected-list-only stale fallback."""
        list_id = self._selected_list_id()
        local = self._local_items()
        if not list_id:
            return self._assemble([], local, "unavailable", None)

        if self._is_connected():
            try:
                result = self._client.list_tasks(
                    list_id, include_completed=False, max_results=50
                )
                remote = [
                    {
                        "id": f"todo:{task.id}", "note": task.title,
                        "source": "todo", "sync_state": "synced",
                        "last_modified_at": task.last_modified_at,
                    }
                    for task in result.tasks[:50]
                ]
                database.replace_microsoft_todo_reminder_cache(
                    list_id,
                    fetched_at=utc_now_iso(),
                    tasks=[
                        {
                            "id": task["id"].removeprefix("todo:"),
                            "title": task["note"],
                            "last_modified_at": task["last_modified_at"],
                        }
                        for task in remote
                    ],
                )
                return self._assemble(remote, local, "live", None)
            except _EXPECTED_READ_ERRORS as exc:
                _LOGGER.warning(
                    "Microsoft To Do reminder read unavailable: error_type=%s",
                    type(exc).__name__,
                )

        cached = database.fetch_microsoft_todo_reminder_cache(list_id)
        if cached is None:
            return self._assemble([], local, "unavailable", None)
        fetched_at, tasks = cached
        remote = [
            {
                "id": f"todo:{task.get('id', '')}",
                "note": str(task.get("title", "")),
                "source": "todo", "sync_state": "synced",
                "last_modified_at": str(task.get("last_modified_at", "")),
            }
            for task in tasks[:50]
            if isinstance(task, dict) and task.get("id") and task.get("title")
        ]
        return self._assemble(remote, local, "stale", fetched_at)

    def create(self, note: str) -> dict[str, object]:
        """Quick-add remotely when known connected, otherwise queue locally."""
        note = self._validated_note(note)
        list_id = self._selected_list_id()
        if not list_id or not self._is_connected():
            row_id = database.save_reminder(note)
            return {"id": f"local:{row_id}", "outcome": "pending", "action_id": None}
        action = self._propose_create(note, list_id=list_id, local_id=None)
        result = self._create_result(action, local_id=None)
        evidence = self._creation_evidence(action.action_id)
        if evidence is not None:
            result["id"] = f"todo:{evidence['task_id']}"
        return result

    def complete(self, public_id: str) -> dict[str, object]:
        """Complete a remote reminder through the existing verified action path."""
        kind, identifier = self._parse_public_id(public_id)
        if kind == "local":
            row = database.get_local_reminder(int(identifier))
            if row is None or row["is_read"]:
                raise ReminderServiceError("reminder_not_found")
            if self._linked_action_is_active(row):
                raise ReminderServiceError("reminder_sync_in_progress")
            if row["sync_state"] == "unknown":
                raise ReminderServiceError("unknown_reminder_requires_review")
            database.set_reminder_sync_state(int(identifier), "dismissed")
            return {"id": public_id, "outcome": "dismissed", "action_id": None}

        list_id = self._selected_list_id()
        if not list_id or not self._is_connected():
            raise ReminderServiceError("microsoft_todo_unavailable")
        cached = database.fetch_microsoft_todo_reminder_cache(list_id)
        task = next(
            (
                item for item in (cached[1] if cached else [])
                if isinstance(item, dict) and item.get("id") == identifier
            ),
            None,
        )
        if not isinstance(task, dict) or not isinstance(task.get("last_modified_at"), str) or not task["last_modified_at"]:
            raise ReminderServiceError("reminder_target_unavailable")
        action = self._actions.propose(
            agent_key="operator",
            capability_name="complete_microsoft_todo_task",
            arguments={
                "list_id": list_id, "task_id": identifier,
                "last_modified_at": task["last_modified_at"],
            },
            target="Complete Microsoft To Do Task", risk="write",
            summary="Approve Complete Microsoft To Do Task", actor="operator",
        )
        resolved = self._actions.approve_and_execute(
            action.action_id, actor="operator", expected_version=action.version
        )
        if resolved.status == "verified":
            return {"id": public_id, "outcome": "synced", "action_id": resolved.action_id}
        if resolved.status == "execution_failed" and self._action_code(resolved) == "microsoft_todo_task_changed":
            raise ReminderServiceError("reminder_target_changed", action_id=resolved.action_id)
        if resolved.status in {"outcome_unknown", "verification_failed"}:
            raise ReminderServiceError("microsoft_todo_outcome_unknown", action_id=resolved.action_id)
        raise ReminderServiceError("microsoft_todo_completion_failed", action_id=resolved.action_id)

    def dismiss_unknown(self, public_id: str) -> None:
        """Archive one operator-reviewed uncertain local row."""
        kind, identifier = self._parse_public_id(public_id)
        if kind != "local":
            raise ReminderServiceError("only_local_unknown_reminders_can_be_dismissed")
        row = database.get_local_reminder(int(identifier))
        if row is None or row["is_read"] or row["sync_state"] != "unknown":
            raise ReminderServiceError("unknown_reminder_not_found")
        database.set_reminder_sync_state(int(identifier), "dismissed")

    def sync(self, public_ids: list[str]) -> list[dict[str, object]]:
        """Synchronize exactly the reviewed pending IDs sequentially once."""
        if not self._sync_lock.acquire(blocking=False):
            raise ReminderServiceError("reminder_sync_in_progress")
        try:
            list_id = self._selected_list_id()
            if not list_id or not self._is_connected():
                return [{"id": item, "outcome": "failed", "action_id": None} for item in public_ids]
            outcomes: list[dict[str, object]] = []
            for public_id in public_ids:
                try:
                    kind, identifier = self._parse_public_id(public_id)
                    if kind != "local":
                        raise ReminderServiceError("only_pending_local_reminders_can_sync")
                    row = database.get_local_reminder(int(identifier))
                    if row is None or row["is_read"] or row["sync_state"] != "pending":
                        raise ReminderServiceError("reminder_not_pending")
                    action = self._linked_or_new_create(row, list_id)
                    result = self._create_result(action, local_id=int(identifier))
                    outcomes.append({"id": public_id, **result})
                except ReminderServiceError as exc:
                    outcomes.append({"id": public_id, "outcome": "failed", "action_id": exc.action_id})
            return outcomes
        finally:
            self._sync_lock.release()

    def _linked_or_new_create(self, row: Mapping[str, object], list_id: str) -> ActionRecord:
        existing = row.get("sync_action_id")
        if isinstance(existing, str) and existing:
            try:
                action = self._actions.get(existing)
                if action.status == "proposed":
                    if action.proposal.arguments.get("list_id") != list_id:
                        return self._propose_create(
                            str(row["note"]), list_id=list_id, local_id=int(row["id"])
                        )
                    return self._actions.approve_and_execute(
                        action.action_id, actor="operator", expected_version=action.version
                    )
                if action.status == "execution_failed":
                    return self._propose_create(
                        str(row["note"]), list_id=list_id, local_id=int(row["id"])
                    )
                return action
            except Exception:
                pass
        return self._propose_create(str(row["note"]), list_id=list_id, local_id=int(row["id"]))

    def _propose_create(self, note: str, *, list_id: str, local_id: int | None) -> ActionRecord:
        action = self._actions.propose(
            agent_key="operator",
            capability_name="create_microsoft_todo_task",
            arguments={"list_id": list_id, "title": note, "importance": "normal"},
            target="Create Microsoft To Do Task", risk="write",
            summary="Approve Create Microsoft To Do Task", actor="operator",
        )
        if local_id is not None and not database.link_reminder_action(local_id, action.action_id):
            raise ReminderServiceError("reminder_not_pending", action_id=action.action_id)
        return self._actions.approve_and_execute(
            action.action_id, actor="operator", expected_version=action.version
        )

    def _create_result(self, action: ActionRecord, *, local_id: int | None) -> dict[str, object]:
        if action.status == "verified":
            evidence = self._creation_evidence(action.action_id)
            if local_id is not None and evidence is not None:
                database.mark_reminder_synced(
                    local_id,
                    list_id=evidence["list_id"],
                    task_id=evidence["task_id"],
                    action_id=action.action_id,
                )
            return {"outcome": "synced", "action_id": action.action_id}
        if action.status in {"outcome_unknown", "verification_failed"}:
            if local_id is not None:
                database.set_reminder_sync_state(local_id, "unknown")
            return {"outcome": "unknown", "action_id": action.action_id}
        return {"outcome": "failed", "action_id": action.action_id}

    def _reconcile_row(self, row_id: int, action: ActionRecord) -> None:
        if action.status == "verified":
            evidence = self._creation_evidence(action.action_id)
            if evidence is not None:
                database.mark_reminder_synced(
                    row_id,
                    list_id=evidence["list_id"],
                    task_id=evidence["task_id"],
                    action_id=action.action_id,
                )
        elif action.status in {"outcome_unknown", "verification_failed"}:
            database.set_reminder_sync_state(row_id, "unknown")

    def _creation_evidence(self, action_id: str) -> dict[str, str] | None:
        for event in self._actions.events(action_id):
            if event.from_status == "executing" and event.to_status == "verifying":
                list_id = event.evidence.get("list_id")
                task_id = event.evidence.get("task_id")
                if isinstance(list_id, str) and isinstance(task_id, str):
                    return {"list_id": list_id, "task_id": task_id}
        return None

    def _action_code(self, action: ActionRecord) -> str:
        events = self._actions.events(action.action_id)
        return events[-1].result_code if events else ""

    def _linked_action_is_active(self, row: Mapping[str, object]) -> bool:
        action_id = row.get("sync_action_id")
        if not isinstance(action_id, str) or not action_id:
            return False
        try:
            return self._actions.get(action_id).status in _ACTIVE_ACTION_STATUSES
        except Exception:
            return False

    def _local_items(self) -> list[dict[str, str]]:
        return [
            {
                "id": f"local:{row['id']}", "note": str(row["note"]),
                "source": "local", "sync_state": str(row["sync_state"]),
            }
            for row in database.fetch_local_reminders()
        ]

    def _assemble(
        self, remote: list[dict[str, str]], local: list[dict[str, str]],
        source_state: ReminderSourceState, cache_timestamp: str | None,
    ) -> ReminderList:
        public_remote = [
            {key: value for key, value in item.items() if key != "last_modified_at"}
            for item in remote
        ]
        return ReminderList(
            items=public_remote + local,
            source_state=source_state,
            cache_timestamp=cache_timestamp,
            pending_sync_count=sum(item["sync_state"] == "pending" for item in local),
        )

    def _selected_list_id(self) -> str:
        return get_settings_store().get_snapshot().microsoft_todo.reminder_list_id

    def _is_connected(self) -> bool:
        try:
            return self._client.get_status().state == "connected"
        except Exception:
            return False

    @staticmethod
    def _validated_note(value: str) -> str:
        if not isinstance(value, str):
            raise ReminderServiceError("reminder_invalid_input")
        cleaned = " ".join(value.split())
        if not cleaned or len(cleaned) > 500:
            raise ReminderServiceError("reminder_invalid_input")
        return cleaned

    @staticmethod
    def _parse_public_id(value: str) -> tuple[str, str]:
        if not isinstance(value, str) or ":" not in value:
            raise ReminderServiceError("reminder_invalid_id")
        kind, identifier = value.split(":", 1)
        if kind not in {"todo", "local"} or not identifier:
            raise ReminderServiceError("reminder_invalid_id")
        if kind == "local" and (not identifier.isdecimal() or int(identifier) < 1):
            raise ReminderServiceError("reminder_invalid_id")
        return kind, identifier
