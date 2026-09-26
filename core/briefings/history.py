from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.briefings.models import (
    NORMALIZATION_VERSION,
    BriefingComparison,
    BriefingComparisonSource,
    BriefingCoverage,
    BriefingEvidence,
    BriefingSessionRecord,
)
from core.briefings.service import BriefingHistoryContext


@dataclass(frozen=True, slots=True)
class HistoryAnalysis:
    """Deterministic comparison output kept independent of model execution."""

    evidence: tuple[BriefingEvidence, ...]
    comparison: BriefingComparison
    previous_by_current_id: dict[UUID, BriefingEvidence]


def compare_history(
    *,
    evidence: list[BriefingEvidence],
    coverage: list[BriefingCoverage],
    history: BriefingHistoryContext,
) -> HistoryAnalysis:
    """Compare current normalized source state with each source's newest usable checkpoint."""
    eligible_sessions = [
        session for session in history.sessions
        if session.partition in {"production", "sandbox"}
        and session.presented_at is not None
        and session.run_status == "completed"
        and session.artifact is not None
    ]
    missing_sessions = max(0, len(history.selection.session_ids) - len(eligible_sessions))
    annotated = list(evidence)
    previous_by_current_id: dict[UUID, BriefingEvidence] = {}
    comparisons: list[BriefingComparisonSource] = []
    material_changes = 0
    has_baseline = False
    has_limits = missing_sessions > 0

    for current_coverage in coverage:
        current_at = current_coverage.observed_at
        if current_coverage.status == "disabled":
            comparisons.append(BriefingComparisonSource(
                source=current_coverage.source, status="disabled",
                current_snapshot_at=current_at, reason=current_coverage.reason or "source_disabled",
            ))
            has_limits = True
            continue
        if current_coverage.status in {"failed", "unavailable"}:
            comparisons.append(BriefingComparisonSource(
                source=current_coverage.source, status="unavailable",
                current_snapshot_at=current_at, reason=current_coverage.reason or "source_unavailable",
            ))
            has_limits = True
            continue
        if (
            current_coverage.scope_key is None
            or current_coverage.normalization_version != NORMALIZATION_VERSION
        ):
            comparisons.append(BriefingComparisonSource(
                source=current_coverage.source, status="limited",
                current_snapshot_at=current_at, reason="comparison_scope_or_normalization_unavailable",
            ))
            annotated = [
                item.model_copy(update={"change_kind": "not_comparable"})
                if item.source == current_coverage.source else item
                for item in annotated
            ]
            has_limits = True
            continue

        baseline = _newest_compatible_checkpoint(current_coverage, eligible_sessions)
        if baseline is None:
            comparisons.append(BriefingComparisonSource(
                source=current_coverage.source, status="initial",
                current_snapshot_at=current_at, reason="no_compatible_presented_checkpoint",
            ))
            annotated = [
                item.model_copy(update={"change_kind": "not_comparable"})
                if item.source == current_coverage.source else item
                for item in annotated
            ]
            has_limits = True
            continue

        baseline_record, baseline_coverage = baseline
        baseline_at = baseline_coverage.observed_at
        if baseline_at is None or current_at is None:
            comparisons.append(BriefingComparisonSource(
                source=current_coverage.source, status="limited",
                baseline_session_id=baseline_record.id,
                baseline_snapshot_at=baseline_at,
                current_snapshot_at=current_at,
                reason="source_snapshot_time_unavailable",
            ))
            has_limits = True
            continue

        has_baseline = True
        if current_at < baseline_at:
            comparisons.append(BriefingComparisonSource(
                source=current_coverage.source,
                status="limited",
                baseline_session_id=baseline_record.id,
                baseline_snapshot_at=baseline_at,
                current_snapshot_at=current_at,
                reason="source_snapshot_predates_baseline",
            ))
            annotated = [
                item.model_copy(update={"change_kind": "not_comparable"})
                if item.source == current_coverage.source else item
                for item in annotated
            ]
            has_limits = True
            continue

        baseline_evidence = {
            (item.source, item.source_id): item
            for item in baseline_record.evidence
            if item.source == current_coverage.source
            and item.comparison_role == "current"
        }
        cited_ids = {
            evidence_id
            for section in baseline_record.artifact.sections
            for item in section.items
            for evidence_id in item.evidence_ids
        }
        membership_comparable = (
            current_coverage.status == "complete"
            and not current_coverage.truncated
            and baseline_coverage.status == "complete"
            and not baseline_coverage.truncated
        )
        source_limit = (
            current_coverage.status != "complete"
            or current_coverage.truncated
            or baseline_coverage.status != "complete"
            or baseline_coverage.truncated
        )
        source_limited = source_limit
        if source_limit:
            has_limits = True

        for index, current in enumerate(annotated):
            if current.source != current_coverage.source:
                continue
            if (
                current.identity_kind not in {"provider", "fixture", "content"}
                or current.semantic_fingerprint is None
                or current.normalization_version != current_coverage.normalization_version
            ):
                annotated[index] = current.model_copy(update={"change_kind": "not_comparable"})
                source_limited = True
                has_limits = True
                continue

            prior = baseline_evidence.get((current.source, current.source_id))
            if prior is None:
                timestamp_proves_new = _timestamp_proves_new_since_checkpoint(
                    current, baseline_at=baseline_at, current_at=current_at
                )
                if (
                    current.identity_kind in {"provider", "fixture"}
                    and (
                        (membership_comparable and current.source not in {"email", "news"})
                        or timestamp_proves_new
                    )
                ):
                    annotated[index] = current.model_copy(update={"change_kind": "new"})
                    material_changes += 1
                else:
                    annotated[index] = current.model_copy(update={"change_kind": "not_comparable"})
                    source_limited = True
                    has_limits = True
                continue

            if (
                prior.identity_kind not in {"provider", "fixture", "content"}
                or prior.semantic_fingerprint is None
                or prior.normalization_version != current_coverage.normalization_version
            ):
                annotated[index] = current.model_copy(update={"change_kind": "not_comparable"})
                source_limited = True
                has_limits = True
                continue

            cited_before = prior.id in cited_ids
            material_change = _material_semantic_change(prior, current)
            if material_change is None:
                annotated[index] = current.model_copy(update={"change_kind": "not_comparable"})
                source_limited = True
                has_limits = True
                continue
            if material_change:
                pair_id = uuid4()
                annotated[index] = current.model_copy(update={
                    "change_kind": "changed",
                    "comparison_pair_id": pair_id,
                    "previously_included": cited_before,
                })
                previous_by_current_id[current.id] = prior
                material_changes += 1
                continue

            kind: Literal["unchanged", "time_sensitive"] = "unchanged"
            if became_time_sensitive(
                current,
                baseline_at=baseline_at,
                current_at=current_at,
            ):
                kind = "time_sensitive"
                material_changes += 1
            annotated[index] = current.model_copy(update={
                "change_kind": kind,
                "previously_included": cited_before,
            })

        comparisons.append(BriefingComparisonSource(
            source=current_coverage.source,
            status="limited" if source_limited else "compared",
            baseline_session_id=baseline_record.id,
            baseline_snapshot_at=baseline_at,
            current_snapshot_at=current_at,
            reason=(
                current_coverage.reason
                or baseline_coverage.reason
                or ("source_coverage_is_partial" if source_limit else ("evidence_not_comparable" if source_limited else None))
            ),
        ))

    if missing_sessions:
        has_limits = True
    if not has_baseline:
        outcome = "initial"
        summary = "This is an initial snapshot; no compatible presented source history was available."
    elif material_changes == 0 and not has_limits:
        outcome = "no_change"
        summary = "No material changes were found since the recorded source checkpoints."
    elif material_changes == 0:
        outcome = "limited"
        summary = "No material changes were found in comparable data; some sources have limited comparison coverage."
    elif has_limits:
        outcome = "limited"
        summary = f"Found {material_changes} new, changed, or newly time-sensitive items in the comparable data; some sources have limited coverage."
    else:
        outcome = "compared"
        summary = f"Found {material_changes} new, changed, or newly time-sensitive items since the recorded source checkpoints."

    if missing_sessions:
        summary += " Some previously presented history is no longer available."
    comparison = BriefingComparison(
        outcome=outcome,
        summary=summary,
        sources=comparisons,
        material_change_count=material_changes,
        no_material_changes=material_changes == 0,
    )
    return HistoryAnalysis(
        evidence=tuple(annotated),
        comparison=comparison,
        previous_by_current_id=previous_by_current_id,
    )


def _material_semantic_change(
    prior: BriefingEvidence, current: BriefingEvidence,
) -> bool | None:
    """Ignore routine market/weather refresh noise using explicit thresholds."""
    if current.source == "market":
        before = _numeric_state(prior, "price")
        after = _numeric_state(current, "price")
        if before is None or after is None or before == 0:
            return None
        return abs(after - before) / abs(before) >= 0.05

    if current.source == "weather":
        before = prior.comparison_state or {}
        after = current.comparison_state or {}
        comparable = False
        for key in before.keys() & after.keys():
            old_value, new_value = before[key], after[key]
            if key.endswith(":condition"):
                comparable = True
                if str(old_value).strip().casefold() != str(new_value).strip().casefold():
                    return True
                continue
            try:
                difference = abs(float(new_value) - float(old_value))
            except (TypeError, ValueError, OverflowError):
                continue
            threshold = _weather_threshold(key)
            if threshold is not None:
                comparable = True
                if difference >= threshold:
                    return True
        return False if comparable else None

    return prior.semantic_fingerprint != current.semantic_fingerprint


def _numeric_state(evidence: BriefingEvidence, key: str) -> float | None:
    value = (evidence.comparison_state or {}).get(key)
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _weather_threshold(key: str) -> float | None:
    field = key.rsplit(":", 1)[-1]
    if field in {"temp_f", "apparent_temp_f", "temp_max_f", "temp_min_f"}:
        return 5.0
    if field in {"precip_probability_max", "precip_probability"}:
        return 20.0
    if field in {"precip_sum_in", "precipitation_in"}:
        return 0.1
    if field == "wind_speed_mph":
        return 5.0
    return None


def _timestamp_proves_new_since_checkpoint(
    evidence: BriefingEvidence,
    *,
    baseline_at: datetime,
    current_at: datetime,
) -> bool:
    """Use provider timestamps for genuinely post-checkpoint mail/articles only."""
    if evidence.source not in {"email", "news"} or evidence.effective_at is None:
        return False
    effective_at = _aware_utc(evidence.effective_at)
    return _aware_utc(baseline_at) < effective_at <= _aware_utc(current_at)


def _newest_compatible_checkpoint(
    current: BriefingCoverage,
    sessions: list[BriefingSessionRecord],
) -> tuple[BriefingSessionRecord, BriefingCoverage] | None:
    candidates: list[tuple[datetime, BriefingSessionRecord, BriefingCoverage]] = []
    complete_candidates: list[tuple[datetime, BriefingSessionRecord, BriefingCoverage]] = []
    for session in sessions:
        artifact = session.artifact
        if artifact is None:
            continue
        for prior in artifact.coverage:
            if (
                prior.source != current.source
                or prior.scope_key != current.scope_key
                or prior.normalization_version != current.normalization_version
                or prior.status not in {"complete", "partial"}
                or prior.observed_at is None
            ):
                continue
            candidate = (prior.observed_at, session, prior)
            candidates.append(candidate)
            if prior.status == "complete" and not prior.truncated:
                complete_candidates.append(candidate)
    if not candidates:
        return None
    # A complete current inventory can compare membership only against another
    # complete inventory. Newer partial snapshots must not hide items omitted
    # while their source was capped or unavailable. If no complete checkpoint
    # exists yet, keep the newest partial one for matched-ID fingerprint checks;
    # the caller already prevents membership conclusions from that baseline.
    if current.status == "complete" and not current.truncated and complete_candidates:
        candidates = complete_candidates
    _, record, source_coverage = max(
        candidates,
        key=lambda row: (row[0], row[1].created_at, str(row[1].id)),
    )
    return record, source_coverage


def became_time_sensitive(
    evidence: BriefingEvidence,
    *,
    baseline_at: datetime,
    current_at: datetime,
) -> bool:
    """Return true only when a reminder/event crossed a defined attention window."""
    if evidence.source == "reminders" and evidence.effective_at is not None:
        before = _reminder_band(evidence.effective_at, baseline_at)
        after = _reminder_band(evidence.effective_at, current_at)
        return after > before
    if evidence.source == "calendar" and evidence.effective_at is not None:
        before = _calendar_band(evidence, baseline_at)
        after = _calendar_band(evidence, current_at)
        return after > before
    return False


def _reminder_band(due_at: datetime, snapshot_at: datetime) -> int:
    due = _aware_utc(due_at)
    snapshot = _aware_utc(snapshot_at)
    if due < snapshot:
        return 3
    due_date = due.astimezone().date()
    snapshot_date = snapshot.astimezone().date()
    if due_date == snapshot_date:
        return 2
    if (due_date - snapshot_date).days == 1:
        return 1
    return 0


def _calendar_band(evidence: BriefingEvidence, snapshot_at: datetime) -> int:
    snapshot = _localize(snapshot_at, evidence.time_zone)
    starts = _localize(evidence.effective_at, evidence.time_zone)
    if evidence.all_day:
        start_date = starts.date()
        end_date = (
            _localize(evidence.effective_until, evidence.time_zone).date()
            if evidence.effective_until is not None
            else start_date
        )
        if start_date <= snapshot.date() < end_date:
            return 2 if start_date == snapshot.date() else 3
        days = (start_date - snapshot.date()).days
        return 1 if days <= 2 else 0

    seconds = (starts - snapshot).total_seconds()
    if seconds <= 0:
        return 3
    if seconds <= 3 * 60 * 60:
        return 3
    if starts.date() == snapshot.date():
        return 2
    if seconds <= 2 * 24 * 60 * 60:
        return 1
    return 0


def _localize(value: datetime | None, zone_name: str | None) -> datetime:
    if value is None:
        return datetime.now().astimezone()
    try:
        zone = ZoneInfo(zone_name) if zone_name else datetime.now().astimezone().tzinfo
    except (ZoneInfoNotFoundError, ValueError):
        zone = datetime.now().astimezone().tzinfo
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.astimezone(timezone.utc)
    return value.astimezone(timezone.utc)
