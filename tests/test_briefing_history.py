"""Deterministic source-history comparison contracts."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from core.briefings.history import compare_history
from core.briefings.models import (
    BUILTIN_BRIEFING_PROFILES,
    NORMALIZATION_VERSION,
    BriefingCoverage,
    BriefingDraft,
    BriefingEvidence,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingHistorySelection,
    BriefingItemDraft,
    BriefingModelConfiguration,
    BriefingSectionDraft,
    BriefingSessionRecord,
    CanonicalBriefingArtifact,
    build_canonical_artifact,
)
from core.briefings.service import BriefingHistoryContext


UTC = timezone.utc
SCOPE_KEY = "pending_review:test-v1"


def _coverage(source: str, at: datetime, *, status: str = "complete", truncated: bool = False) -> BriefingCoverage:
    return BriefingCoverage(
        source=source, scope="bounded test inventory", scope_key=f"{source}:test-v1",
        normalization_version=NORMALIZATION_VERSION, status=status,
        observed_at=at, truncated=truncated,
    )


def _evidence(
    source: str, source_id: str, fingerprint: str, *,
    effective_at: datetime | None = None,
    comparison_state: dict[str, str | float | int | bool | None] | None = None,
) -> BriefingEvidence:
    trust = "accepted" if source == "accepted_context" else ("pending" if source == "pending_review" else "observed")
    return BriefingEvidence(
        source=source, source_id=source_id, identity_kind="provider",
        semantic_fingerprint=fingerprint, normalization_version=NORMALIZATION_VERSION,
        comparison_state=comparison_state,
        observed_at=datetime(2026, 9, 24, 10, tzinfo=UTC), effective_at=effective_at,
        trust=trust, content=f"Saved {source} content: {fingerprint[:8]}",
    )


def _baseline(
    *, source: str, evidence: BriefingEvidence, coverage: BriefingCoverage, cited: bool,
) -> BriefingSessionRecord:
    session_id = uuid4()
    request = BriefingGenerationRequest(
        idempotency_key=uuid4(), profile_id="daily", model_id="test/model",
    )
    configuration = BriefingGenerationConfiguration(
        profile=BUILTIN_BRIEFING_PROFILES["daily"],
        model=BriefingModelConfiguration(
            model_id="test/model", provider="openrouter", runtime="cloud",
            max_elapsed_seconds=30, max_retries=0, max_model_turns=1,
            max_tool_calls=1, output_token_limit=512,
        ), origin="hud",
    )
    draft = BriefingDraft(sections=[])
    if cited:
        draft = BriefingDraft(sections=[BriefingSectionDraft(title="Saved", items=[
            BriefingItemDraft(
                category="accepted_context" if source == "accepted_context" else ("pending_review" if source == "pending_review" else "observation"),
                title="Prior evidence", body="The previous artifact cited this source.",
                evidence_ids=[evidence.id],
            )
        ])])
    artifact = build_canonical_artifact(
        session_id=session_id, draft=draft, evidence=[evidence], coverage=[coverage],
        created_at=coverage.observed_at,
    )
    return BriefingSessionRecord(
        id=session_id, partition="production", idempotency_key=request.idempotency_key,
        conversation_id=uuid4(), opening_message_id=uuid4(), run_id=uuid4(),
        request=request, configuration=configuration, created_at=coverage.observed_at,
        presented_at=coverage.observed_at, artifact=artifact, evidence=[evidence],
        run_status="completed",
    )


def _history(
    record: BriefingSessionRecord | list[BriefingSessionRecord], current_at: datetime,
) -> BriefingHistoryContext:
    records = [record] if isinstance(record, BriefingSessionRecord) else record
    return BriefingHistoryContext(
        selection=BriefingHistorySelection(captured_at=current_at, session_ids=[item.id for item in records]),
        sessions=tuple(records),
    )


class BriefingHistoryComparisonTests(unittest.TestCase):
    def test_new_requires_complete_current_and_presented_evidence_inventories(self) -> None:
        before = datetime(2026, 9, 24, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 25, 10, tzinfo=UTC)
        prior_item = _evidence("calendar", "event-old", "a" * 64)
        current_item = _evidence("calendar", "event-new", "b" * 64)
        complete_prior = _coverage("calendar", before)

        for current_coverage, prior_coverage in (
            (_coverage("calendar", current_at, status="partial", truncated=True), complete_prior),
            (_coverage("calendar", current_at), _coverage("calendar", before, status="partial", truncated=True)),
        ):
            with self.subTest(current=current_coverage.status, prior=prior_coverage.status):
                baseline = _baseline(source="calendar", evidence=prior_item, coverage=prior_coverage, cited=False)
                result = compare_history(
                    evidence=[current_item], coverage=[current_coverage],
                    history=_history(baseline, current_at),
                )
                self.assertEqual(result.evidence[0].change_kind, "not_comparable")
                self.assertEqual(result.comparison.material_change_count, 0)

        baseline = _baseline(source="calendar", evidence=prior_item, coverage=complete_prior, cited=False)
        result = compare_history(
            evidence=[current_item], coverage=[_coverage("calendar", current_at)],
            history=_history(baseline, current_at),
        )
        self.assertEqual(result.evidence[0].change_kind, "new")

    def test_newer_partial_checkpoint_does_not_mask_changed_item_from_complete_checkpoint(self) -> None:
        complete_at = datetime(2026, 9, 24, 10, tzinfo=UTC)
        partial_at = datetime(2026, 9, 25, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 26, 10, tzinfo=UTC)
        older_complete = _baseline(
            source="calendar", evidence=_evidence("calendar", "event-x", "a" * 64),
            coverage=_coverage("calendar", complete_at), cited=True,
        )
        newer_partial = _baseline(
            source="calendar", evidence=_evidence("calendar", "event-y", "b" * 64),
            coverage=_coverage("calendar", partial_at, status="partial", truncated=True), cited=False,
        )
        current = _evidence("calendar", "event-x", "c" * 64)

        result = compare_history(
            evidence=[current], coverage=[_coverage("calendar", current_at)],
            history=_history([newer_partial, older_complete], current_at),
        )

        self.assertEqual(result.evidence[0].change_kind, "changed")
        self.assertTrue(result.evidence[0].previously_included)
        self.assertEqual(result.comparison.sources[0].baseline_session_id, older_complete.id)
        self.assertEqual(result.comparison.sources[0].status, "compared")

    def test_changed_personal_evidence_gets_a_pair_and_prior_citation_state(self) -> None:
        before = datetime(2026, 9, 24, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 25, 10, tzinfo=UTC)
        prior = _evidence("accepted_context", "record-7", "a" * 64)
        current = _evidence("accepted_context", "record-7", "b" * 64)
        prior_coverage = _coverage("accepted_context", before, status="partial", truncated=True)
        current_coverage = _coverage("accepted_context", current_at, status="partial", truncated=True)
        baseline = _baseline(source="accepted_context", evidence=prior, coverage=prior_coverage, cited=True)

        result = compare_history(
            evidence=[current], coverage=[current_coverage], history=_history(baseline, current_at),
        )

        changed = result.evidence[0]
        self.assertEqual(changed.change_kind, "changed")
        self.assertIsNotNone(changed.comparison_pair_id)
        self.assertTrue(changed.previously_included)
        self.assertIs(result.previous_by_current_id[changed.id], prior)

    def test_snapshot_older_than_baseline_is_limited_not_changed(self) -> None:
        prior_at = datetime(2026, 9, 25, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 24, 10, tzinfo=UTC)
        prior = _evidence("calendar", "event-1", "a" * 64)
        current = _evidence("calendar", "event-1", "b" * 64)
        prior_coverage = _coverage("calendar", prior_at)
        baseline = _baseline(source="calendar", evidence=prior, coverage=prior_coverage, cited=True)

        result = compare_history(
            evidence=[current], coverage=[_coverage("calendar", current_at)],
            history=_history(baseline, current_at),
        )

        self.assertEqual(result.evidence[0].change_kind, "not_comparable")
        self.assertEqual(result.comparison.sources[0].status, "limited")
        self.assertEqual(result.comparison.sources[0].reason, "source_snapshot_predates_baseline")
        self.assertEqual(result.comparison.material_change_count, 0)

    def test_unchanged_reminder_becomes_time_sensitive_as_due_date_approaches(self) -> None:
        due = datetime(2026, 9, 26, 11, tzinfo=UTC)
        baseline_at = datetime(2026, 9, 24, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 26, 10, tzinfo=UTC)
        prior = _evidence("reminders", "task-1", "a" * 64, effective_at=due)
        current = _evidence("reminders", "task-1", "a" * 64, effective_at=due)
        baseline = _baseline(
            source="reminders", evidence=prior, coverage=_coverage("reminders", baseline_at), cited=False,
        )

        result = compare_history(
            evidence=[current], coverage=[_coverage("reminders", current_at)],
            history=_history(baseline, current_at),
        )

        self.assertEqual(result.evidence[0].change_kind, "time_sensitive")
        self.assertEqual(result.comparison.material_change_count, 1)

    def test_unchanged_reminder_becomes_time_sensitive_when_due_tomorrow(self) -> None:
        due = datetime(2026, 9, 26, 11, tzinfo=UTC)
        baseline_at = datetime(2026, 9, 24, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 25, 10, tzinfo=UTC)
        prior = _evidence("reminders", "task-1", "a" * 64, effective_at=due)
        current = _evidence("reminders", "task-1", "a" * 64, effective_at=due)
        baseline = _baseline(
            source="reminders", evidence=prior,
            coverage=_coverage("reminders", baseline_at), cited=False,
        )

        result = compare_history(
            evidence=[current], coverage=[_coverage("reminders", current_at)],
            history=_history(baseline, current_at),
        )

        self.assertEqual(result.evidence[0].change_kind, "time_sensitive")
        self.assertEqual(result.comparison.material_change_count, 1)

    def test_market_change_threshold_ignores_routine_price_refreshes(self) -> None:
        before = datetime(2026, 9, 24, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 25, 10, tzinfo=UTC)
        prior = _evidence(
            "market", "market:APEX", "a" * 64,
            comparison_state={"price": 100.0, "status": "healthy"},
        )
        baseline = _baseline(
            source="market", evidence=prior,
            coverage=_coverage("market", before), cited=False,
        )

        for price, expected in ((102.0, "unchanged"), (105.0, "changed")):
            current = _evidence(
                "market", "market:APEX", "b" * 64,
                comparison_state={"price": price, "status": "healthy"},
            )
            with self.subTest(price=price):
                result = compare_history(
                    evidence=[current], coverage=[_coverage("market", current_at)],
                    history=_history(baseline, current_at),
                )
                self.assertEqual(result.evidence[0].change_kind, expected)
                self.assertEqual(result.comparison.material_change_count, int(expected == "changed"))

    def test_weather_thresholds_ignore_small_refreshes_and_compare_shared_forecast_dates(self) -> None:
        before = datetime(2026, 9, 24, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 25, 10, tzinfo=UTC)
        prior = _evidence(
            "weather", "weather:current", "a" * 64,
            comparison_state={
                "current:condition": "clear", "current:temp_f": 72.0,
                "daily:2026-09-25:condition": "clear",
                "daily:2026-09-25:temp_max_f": 80.0,
                "daily:2026-09-25:precip_probability": 20.0,
            },
        )
        baseline = _baseline(
            source="weather", evidence=prior,
            coverage=_coverage("weather", before), cited=False,
        )
        refreshed = _evidence(
            "weather", "weather:current", "b" * 64,
            comparison_state={
                "current:condition": "clear", "current:temp_f": 74.0,
                "daily:2026-09-25:condition": "clear",
                "daily:2026-09-25:temp_max_f": 82.0,
                "daily:2026-09-25:precip_probability": 30.0,
                "daily:2026-09-26:condition": "rain",
            },
        )

        result = compare_history(
            evidence=[refreshed], coverage=[_coverage("weather", current_at)],
            history=_history(baseline, current_at),
        )

        self.assertEqual(result.evidence[0].change_kind, "unchanged")
        self.assertEqual(result.comparison.material_change_count, 0)

    def test_insufficient_market_or_weather_state_is_limited_not_unchanged(self) -> None:
        before = datetime(2026, 9, 24, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 25, 10, tzinfo=UTC)
        cases = (
            (
                "market", "market:APEX", {"status": "healthy"},
                {"status": "degraded"},
            ),
            (
                "weather", "weather:current",
                {"daily:2026-09-24:condition": "clear"},
                {"daily:2026-09-25:condition": "rain"},
            ),
        )
        for source, source_id, before_state, current_state in cases:
            prior = _evidence(
                source, source_id, "a" * 64, comparison_state=before_state,
            )
            current = _evidence(
                source, source_id, "b" * 64, comparison_state=current_state,
            )
            baseline = _baseline(
                source=source, evidence=prior,
                coverage=_coverage(source, before), cited=False,
            )
            with self.subTest(source=source):
                result = compare_history(
                    evidence=[current], coverage=[_coverage(source, current_at)],
                    history=_history(baseline, current_at),
                )
                self.assertEqual(result.evidence[0].change_kind, "not_comparable")
                self.assertEqual(result.comparison.sources[0].status, "limited")
                self.assertEqual(result.comparison.outcome, "limited")

    def test_timestamped_new_mail_and_articles_are_safe_under_bounded_inventories(self) -> None:
        before = datetime(2026, 9, 24, 10, tzinfo=UTC)
        current_at = datetime(2026, 9, 25, 10, tzinfo=UTC)
        for source, source_id in (("email", "gmail:new-message"), ("news", "news:stable-article")):
            prior = _evidence(source, f"{source}:old-item", "a" * 64)
            current = _evidence(
                source, source_id, "b" * 64,
                effective_at=datetime(2026, 9, 25, 9, tzinfo=UTC),
            )
            baseline = _baseline(
                source=source, evidence=prior,
                coverage=_coverage(source, before), cited=False,
            )
            partial_current = _coverage(source, current_at, status="partial", truncated=True)

            result = compare_history(
                evidence=[current], coverage=[partial_current],
                history=_history(baseline, current_at),
            )

            with self.subTest(source=source):
                self.assertEqual(result.evidence[0].change_kind, "new")
                self.assertEqual(result.comparison.material_change_count, 1)
                self.assertEqual(result.comparison.sources[0].status, "limited")
                self.assertEqual(result.comparison.outcome, "limited")

                old_timestamp = current.model_copy(update={
                    "effective_at": datetime(2026, 9, 24, 9, tzinfo=UTC),
                })
                old_result = compare_history(
                    evidence=[old_timestamp], coverage=[partial_current],
                    history=_history(baseline, current_at),
                )
                self.assertEqual(old_result.evidence[0].change_kind, "not_comparable")
                self.assertEqual(old_result.comparison.material_change_count, 0)
                complete_old_result = compare_history(
                    evidence=[old_timestamp], coverage=[_coverage(source, current_at)],
                    history=_history(baseline, current_at),
                )
                self.assertEqual(complete_old_result.evidence[0].change_kind, "not_comparable")
                self.assertEqual(complete_old_result.comparison.material_change_count, 0)

                untimed_result = compare_history(
                    evidence=[current.model_copy(update={"effective_at": None})],
                    coverage=[partial_current], history=_history(baseline, current_at),
                )
                self.assertEqual(untimed_result.evidence[0].change_kind, "not_comparable")
                self.assertEqual(untimed_result.comparison.material_change_count, 0)


if __name__ == "__main__":
    unittest.main()
