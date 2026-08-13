"""SQLite persistence for the small, durable action lifecycle."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from core.actions.models import (
    ActionEvent,
    ActionProposal,
    ActionRecord,
    ActionStatus,
    ActionValidationError,
    canonical_json,
    proposal_hash_for,
    timestamp_from_storage,
    timestamp_to_storage,
)

_ALLOWED_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    "proposed": frozenset({"approved", "rejected", "expired"}),
    "approved": frozenset({"executing"}),
    "executing": frozenset({"verifying", "execution_failed", "outcome_unknown"}),
    "verifying": frozenset({"verified", "verification_failed"}),
    "verification_failed": frozenset({"verifying"}),
    "outcome_unknown": frozenset({"verifying"}),
    "verified": frozenset(),
    "rejected": frozenset(),
    "expired": frozenset(),
    "execution_failed": frozenset(),
}
_STATUSES = "'proposed', 'approved', 'executing', 'verifying', 'verified', " \
    "'rejected', 'expired', 'execution_failed', 'verification_failed', 'outcome_unknown'"


class ActionStoreError(RuntimeError):
    """Base class for action persistence failures."""


class ActionNotFoundError(ActionStoreError):
    """Raised when an action identifier does not exist."""


class ActionTransitionError(ActionStoreError):
    """Raised when a requested lifecycle transition is not permitted."""


class ActionConflictError(ActionStoreError):
    """Raised when a versioned transition loses a concurrent update race."""


class ActionIntegrityError(ActionStoreError):
    """Raised when an action's persisted proposal no longer matches its checksum."""


def initialize_action_schema(conn: sqlite3.Connection) -> None:
    """Create the additive action tables if they do not already exist.

    This is intentionally a small idempotent migration. More machinery is only
    warranted once this unshipped schema needs a second incompatible change.
    """
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS actions (
            action_id TEXT PRIMARY KEY NOT NULL,
            agent_key TEXT NOT NULL,
            capability_name TEXT NOT NULL,
            arguments_json TEXT NOT NULL CHECK (json_valid(arguments_json)),
            target TEXT NOT NULL,
            risk TEXT NOT NULL CHECK (risk IN ('write', 'destructive')),
            summary TEXT NOT NULL,
            proposed_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            proposal_hash TEXT NOT NULL CHECK (length(proposal_hash) = 64),
            status TEXT NOT NULL CHECK (status IN ({_STATUSES})),
            version INTEGER NOT NULL CHECK (version >= 0),
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS action_events (
            action_id TEXT NOT NULL REFERENCES actions(action_id),
            sequence INTEGER NOT NULL CHECK (sequence >= 0),
            from_status TEXT CHECK (from_status IS NULL OR from_status IN ({_STATUSES})),
            to_status TEXT NOT NULL CHECK (to_status IN ({_STATUSES})),
            occurred_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            result_code TEXT NOT NULL,
            evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
            PRIMARY KEY (action_id, sequence)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_actions_status_created "
        "ON actions(status, proposed_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_actions_proposed_expiry "
        "ON actions(expires_at) WHERE status = 'proposed'"
    )


class ActionStore:
    """Persist action state and append its audit events atomically."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from core import database

            db_path = database.DB_NAME
        self._db_path = str(db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create the action tables for standalone uses and tests."""
        with self._connection() as conn:
            with conn:
                initialize_action_schema(conn)

    def propose(self, proposal: ActionProposal, *, actor: str = "system") -> ActionRecord:
        """Store a proposal and its first audit event in one transaction."""
        action_id = str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO actions (
                        action_id, agent_key, capability_name, arguments_json, target, risk,
                        summary, proposed_at, expires_at, proposal_hash, status, version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', 0, ?)
                    """,
                    (
                        action_id,
                        proposal.agent_key,
                        proposal.capability_name,
                        canonical_json(proposal.arguments),
                        proposal.target,
                        proposal.risk,
                        proposal.summary,
                        timestamp_to_storage(proposal.proposed_at),
                        timestamp_to_storage(proposal.expires_at),
                        proposal.proposal_hash,
                        timestamp_to_storage(proposal.proposed_at),
                    ),
                )
                self._insert_event(
                    conn,
                    ActionEvent(
                        action_id=action_id,
                        sequence=0,
                        from_status=None,
                        to_status="proposed",
                        occurred_at=proposal.proposed_at,
                        actor=actor,
                        result_code="proposal_created",
                        evidence={},
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get(action_id)

    def get(self, action_id: str) -> ActionRecord:
        """Load one action record."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionNotFoundError("Action does not exist.")
        return self._record_from_row(row)

    def list(
        self,
        *,
        statuses: Iterable[ActionStatus] | None = None,
        limit: int | None = None,
    ) -> list[ActionRecord]:
        """List actions newest first, optionally filtered by current status."""
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
            raise ValueError("Action list limit must be a positive integer.")
        selected = list(statuses or [])
        if statuses is not None and not selected:
            return []
        placeholders = ",".join("?" for _ in selected)
        query = "SELECT * FROM actions" + (
            f" WHERE status IN ({placeholders})" if selected else ""
        ) + " ORDER BY proposed_at DESC, action_id DESC" + (
            " LIMIT ?" if limit is not None else ""
        )
        with self._connection() as conn:
            rows = conn.execute(query, [*selected, limit] if limit is not None else selected).fetchall()
        return [self._record_from_row(row) for row in rows]

    def events(self, action_id: str) -> list[ActionEvent]:
        """Return the ordered audit history for an action."""
        self.get(action_id)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM action_events WHERE action_id = ? ORDER BY sequence", (action_id,)
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def approve(self, action_id: str, *, actor: str, now: datetime, expected_version: int | None = None) -> ActionRecord:
        """Approve a current proposal or expire it at the approval boundary."""
        return self._resolve_proposal(action_id, actor=actor, requested_status="approved", now=now, expected_version=expected_version)

    def reject(self, action_id: str, *, actor: str, now: datetime, expected_version: int | None = None) -> ActionRecord:
        """Reject a current proposal or expire it at the approval boundary."""
        return self._resolve_proposal(action_id, actor=actor, requested_status="rejected", now=now, expected_version=expected_version)

    def claim_execution(self, action_id: str, *, actor: str, now: datetime, expected_version: int | None = None) -> ActionRecord:
        """Atomically claim one approved action for execution."""
        return self.transition(action_id, expected_statuses=("approved",), to_status="executing", actor=actor, result_code="execution_claimed", evidence={}, now=now, expected_version=expected_version)

    def begin_verification(self, action_id: str, *, actor: str, code: str, evidence: dict[str, Any], now: datetime) -> ActionRecord:
        """Record a successful execution before independent verification."""
        return self.transition(action_id, expected_statuses=("executing",), to_status="verifying", actor=actor, result_code=code, evidence=evidence, now=now)

    def retry_verification(self, action_id: str, *, actor: str, now: datetime, expected_version: int | None = None) -> ActionRecord:
        """Retry verification without executing the action again."""
        return self.transition(action_id, expected_statuses=("verification_failed", "outcome_unknown"), to_status="verifying", actor=actor, result_code="verification_retry_requested", evidence={}, now=now, expected_version=expected_version)

    def transition(
        self,
        action_id: str,
        *,
        expected_statuses: tuple[ActionStatus, ...],
        to_status: ActionStatus,
        actor: str,
        result_code: str,
        evidence: dict[str, Any],
        now: datetime,
        expected_version: int | None = None,
        expire_proposal_if_due: bool = False,
    ) -> ActionRecord:
        """Apply one legal state change and its audit event atomically."""
        now = now.astimezone(UTC)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
                if row is None:
                    raise ActionNotFoundError("Action does not exist.")
                current = self._record_from_row(row)
                if expected_version is not None and current.version != expected_version:
                    raise ActionConflictError("Action has changed since it was read.")
                if current.status not in expected_statuses:
                    raise ActionTransitionError("Action lifecycle transition is not permitted.")
                if expire_proposal_if_due and current.proposal.expires_at <= now:
                    to_status = "expired"
                    actor = "system"
                    result_code = "proposal_expired"
                    evidence = {}
                if to_status not in _ALLOWED_TRANSITIONS[current.status]:
                    raise ActionTransitionError("Action lifecycle transition is not permitted.")
                next_version = current.version + 1
                update = conn.execute(
                    "UPDATE actions SET status = ?, version = ?, updated_at = ? WHERE action_id = ? AND status = ? AND version = ?",
                    (to_status, next_version, timestamp_to_storage(now), action_id, current.status, current.version),
                )
                if update.rowcount != 1:
                    raise ActionConflictError("Action transition lost a concurrent update race.")
                self._insert_event(conn, ActionEvent(action_id=action_id, sequence=next_version, from_status=current.status, to_status=to_status, occurred_at=now, actor=actor, result_code=result_code, evidence=evidence))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get(action_id)

    def expire_due(self, *, now: datetime) -> list[ActionRecord]:
        """Expire all pending proposals whose approval window has elapsed."""
        with self._connection() as conn:
            rows = conn.execute("SELECT action_id FROM actions WHERE status = 'proposed' AND expires_at <= ?", (timestamp_to_storage(now),)).fetchall()
        expired: list[ActionRecord] = []
        for row in rows:
            try:
                expired.append(self.transition(str(row["action_id"]), expected_statuses=("proposed",), to_status="expired", actor="system", result_code="proposal_expired", evidence={}, now=now))
            except (ActionConflictError, ActionTransitionError):
                pass
        return expired

    def recover_interrupted(self, *, now: datetime) -> list[ActionRecord]:
        """Record interrupted work after restart without replaying external writes."""
        recovered = self.expire_due(now=now)
        for source, destination, code in (("executing", "outcome_unknown", "execution_interrupted"), ("verifying", "verification_failed", "verification_interrupted")):
            with self._connection() as conn:
                rows = conn.execute("SELECT action_id FROM actions WHERE status = ?", (source,)).fetchall()
            for row in rows:
                try:
                    recovered.append(self.transition(str(row["action_id"]), expected_statuses=(source,), to_status=destination, actor="system", result_code=code, evidence={}, now=now))  # type: ignore[arg-type]
                except (ActionConflictError, ActionTransitionError):
                    pass
        return recovered

    def _resolve_proposal(self, action_id: str, *, actor: str, requested_status: ActionStatus, now: datetime, expected_version: int | None) -> ActionRecord:
        code = "action_approved" if requested_status == "approved" else "action_rejected"
        return self.transition(
            action_id,
            expected_statuses=("proposed",),
            to_status=requested_status,
            actor=actor,
            result_code=code,
            evidence={},
            now=now,
            expected_version=expected_version,
            expire_proposal_if_due=True,
        )

    @staticmethod
    def _insert_event(conn: sqlite3.Connection, event: ActionEvent) -> None:
        conn.execute(
            "INSERT INTO action_events (action_id, sequence, from_status, to_status, occurred_at, actor, result_code, evidence_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event.action_id, event.sequence, event.from_status, event.to_status, timestamp_to_storage(event.occurred_at), event.actor, event.result_code, canonical_json(event.evidence)),
        )

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ActionRecord:
        try:
            proposal = ActionProposal(
                agent_key=str(row["agent_key"]), capability_name=str(row["capability_name"]),
                arguments=json.loads(str(row["arguments_json"])), target=str(row["target"]),
                risk=str(row["risk"]), summary=str(row["summary"]),  # type: ignore[arg-type]
                proposed_at=timestamp_from_storage(str(row["proposed_at"])), expires_at=timestamp_from_storage(str(row["expires_at"])),
            )
            if proposal_hash_for(proposal) != str(row["proposal_hash"]):
                raise ActionIntegrityError("Stored action proposal checksum does not match.")
            return ActionRecord(action_id=str(row["action_id"]), proposal=proposal, status=str(row["status"]), version=int(row["version"]), updated_at=timestamp_from_storage(str(row["updated_at"])))  # type: ignore[arg-type]
        except ActionIntegrityError:
            raise
        except (ActionValidationError, TypeError, ValueError) as exc:
            raise ActionStoreError("Stored action record is invalid.") from exc

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> ActionEvent:
        try:
            return ActionEvent(action_id=str(row["action_id"]), sequence=int(row["sequence"]), from_status=str(row["from_status"]) if row["from_status"] is not None else None, to_status=str(row["to_status"]), occurred_at=timestamp_from_storage(str(row["occurred_at"])), actor=str(row["actor"]), result_code=str(row["result_code"]), evidence=json.loads(str(row["evidence_json"])))  # type: ignore[arg-type]
        except (ActionValidationError, TypeError, ValueError) as exc:
            raise ActionStoreError("Stored action event is invalid.") from exc
