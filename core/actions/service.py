"""Connector-neutral orchestration for action execution and verification."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from core.actions.models import (
    ActionProposal,
    ActionRecord,
    ActionRisk,
    ExecutionOutcome,
    VerificationOutcome,
    action_risk,
)
from core.actions.store import ActionStore
from core.agent.capabilities import CapabilityRisk

_LOGGER = logging.getLogger(__name__)
DEFAULT_APPROVAL_WINDOW = timedelta(hours=24)


class ActionExecutor(Protocol):
    """Execute exactly one persisted, approved action record."""

    def execute(self, action: ActionRecord) -> ExecutionOutcome:
        """Return a definitive, failed, or ambiguous execution outcome."""


class ActionVerifier(Protocol):
    """Independently verify the observed outcome of a persisted action."""

    def verify(self, action: ActionRecord) -> VerificationOutcome:
        """Return whether read-back evidence verifies the intended result."""


class ActionService:
    """Action lifecycle service with pluggable capability-specific handlers."""

    def __init__(
        self,
        store: ActionStore | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store or ActionStore()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._executors: dict[str, ActionExecutor] = {}
        self._verifiers: dict[str, ActionVerifier] = {}
        self._store.initialize()

    @property
    def store(self) -> ActionStore:
        """Expose the persistence boundary for future API adapters."""
        return self._store

    def register_handler(
        self,
        capability_name: str,
        *,
        executor: ActionExecutor,
        verifier: ActionVerifier,
    ) -> None:
        """Register the deterministic executor/verifier pair for a capability."""
        if not capability_name.strip():
            raise ValueError("Capability name must not be blank.")
        self._executors[capability_name] = executor
        self._verifiers[capability_name] = verifier

    def supports(self, capability_name: str) -> bool:
        """Return whether a capability has both action execution handlers."""
        return (
            capability_name in self._executors
            and capability_name in self._verifiers
        )

    def propose(
        self,
        *,
        agent_key: str,
        capability_name: str,
        arguments: Mapping[str, object],
        target: str,
        risk: CapabilityRisk,
        summary: str,
        actor: str = "agent",
    ) -> ActionRecord:
        """Create a frozen action proposal without executing it."""
        now = self._now()
        proposal = ActionProposal(
            agent_key=agent_key,
            capability_name=capability_name,
            arguments=arguments,
            target=target,
            risk=self._proposal_risk(risk),
            summary=summary,
            proposed_at=now,
            expires_at=now + DEFAULT_APPROVAL_WINDOW,
        )
        return self._store.propose(proposal, actor=actor)

    def get(self, action_id: str) -> ActionRecord:
        """Load one action's authoritative current state."""
        return self._store.get(action_id)

    def list(self) -> list[ActionRecord]:
        """List persisted action records."""
        return self._store.list()

    def events(self, action_id: str):
        """Return the immutable action audit ledger."""
        return self._store.events(action_id)

    def approve(self, action_id: str, *, actor: str, expected_version: int | None = None) -> ActionRecord:
        """Approve a pending action, respecting its proposal expiry boundary."""
        return self._store.approve(
            action_id,
            actor=actor,
            now=self._now(),
            expected_version=expected_version,
        )

    def reject(self, action_id: str, *, actor: str, expected_version: int | None = None) -> ActionRecord:
        """Reject a pending action."""
        return self._store.reject(
            action_id,
            actor=actor,
            now=self._now(),
            expected_version=expected_version,
        )

    def approve_and_execute(
        self,
        action_id: str,
        *,
        actor: str,
        expected_version: int,
    ) -> ActionRecord:
        """Approve a proposal or resume one approved action exactly once."""
        action = self.get(action_id)
        if action.status == "proposed":
            action = self.approve(
                action_id,
                actor=actor,
                expected_version=expected_version,
            )
            if action.status == "expired":
                return action
        elif action.status != "approved":
            from core.actions.store import ActionTransitionError

            raise ActionTransitionError("Action lifecycle transition is not permitted.")
        elif action.version != expected_version:
            from core.actions.store import ActionConflictError

            raise ActionConflictError("Action has changed since it was read.")
        return self.claim_and_execute(action_id, actor="executor")

    def claim_and_execute(
        self,
        action_id: str,
        *,
        actor: str,
        expected_version: int | None = None,
    ) -> ActionRecord:
        """Claim once, execute once, then independently verify any success."""
        action = self._store.claim_execution(
            action_id,
            actor=actor,
            now=self._now(),
            expected_version=expected_version,
        )
        executor = self._executors.get(action.proposal.capability_name)
        if executor is None:
            return self._unknown_execution(action, "executor_unavailable")
        try:
            outcome = executor.execute(action)
        except Exception:
            _LOGGER.warning(
                "Action execution failed action_id=%s category=executor_exception",
                action.action_id,
            )
            return self._unknown_execution(action, "executor_exception")
        if not isinstance(outcome, ExecutionOutcome):
            _LOGGER.warning(
                "Action execution failed action_id=%s category=invalid_executor_outcome",
                action.action_id,
            )
            return self._unknown_execution(action, "invalid_executor_outcome")
        if outcome.succeeded is None:
            return self._unknown_execution(action, outcome.code, evidence=outcome.evidence)
        if outcome.succeeded is False:
            return self._store.transition(
                action.action_id,
                expected_statuses=("executing",),
                to_status="execution_failed",
                actor="executor",
                result_code=outcome.code,
                evidence=dict(outcome.evidence),
                now=self._now(),
            )
        verifying = self._store.begin_verification(
            action.action_id,
            actor="executor",
            code=outcome.code,
            evidence=dict(outcome.evidence),
            now=self._now(),
        )
        return self._verify(verifying)

    def retry_verification(
        self,
        action_id: str,
        *,
        actor: str,
        expected_version: int | None = None,
    ) -> ActionRecord:
        """Retry only the verifier for a recoverable action outcome."""
        verifying = self._store.retry_verification(
            action_id,
            actor=actor,
            now=self._now(),
            expected_version=expected_version,
        )
        return self._verify(verifying)

    def expire_due(self) -> list[ActionRecord]:
        """Expire pending proposals whose approval window elapsed."""
        return self._store.expire_due(now=self._now())

    def recover_interrupted(self) -> list[ActionRecord]:
        """Recover after restart without automatically retrying external work."""
        return self._store.recover_interrupted(now=self._now())

    def _verify(self, action: ActionRecord) -> ActionRecord:
        verifier = self._verifiers.get(action.proposal.capability_name)
        if verifier is None:
            return self._verification_failed(action, "verifier_unavailable")
        try:
            outcome = verifier.verify(action)
        except Exception:
            _LOGGER.warning(
                "Action verification failed action_id=%s category=verifier_exception",
                action.action_id,
            )
            return self._verification_failed(action, "verifier_exception")
        if not isinstance(outcome, VerificationOutcome):
            _LOGGER.warning(
                "Action verification failed action_id=%s category=invalid_verifier_outcome",
                action.action_id,
            )
            return self._verification_failed(action, "invalid_verifier_outcome")
        if outcome.verified:
            return self._store.transition(
                action.action_id,
                expected_statuses=("verifying",),
                to_status="verified",
                actor="verifier",
                result_code=outcome.code,
                evidence=dict(outcome.evidence),
                now=self._now(),
            )
        return self._verification_failed(action, outcome.code, evidence=outcome.evidence)

    def _unknown_execution(
        self,
        action: ActionRecord,
        code: str,
        *,
        evidence: Mapping[str, object] | None = None,
    ) -> ActionRecord:
        return self._store.transition(
            action.action_id,
            expected_statuses=("executing",),
            to_status="outcome_unknown",
            actor="executor",
            result_code=code,
            evidence=dict(evidence or {}),
            now=self._now(),
        )

    def _verification_failed(
        self,
        action: ActionRecord,
        code: str,
        *,
        evidence: Mapping[str, object] | None = None,
    ) -> ActionRecord:
        return self._store.transition(
            action.action_id,
            expected_statuses=("verifying",),
            to_status="verification_failed",
            actor="verifier",
            result_code=code,
            evidence=dict(evidence or {}),
            now=self._now(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("Action clock must return a timezone-aware datetime.")
        return value.astimezone(UTC)

    @staticmethod
    def _proposal_risk(risk: CapabilityRisk) -> ActionRisk:
        return action_risk(risk)
