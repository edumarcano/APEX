"""Source-specific normalization and bounded evidence selection for Daily."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.actions import get_action_service
from core.activity import get_activity_service
from core.briefings.models import (
    NORMALIZATION_VERSION,
    BriefingCoverage,
    BriefingEvidence,
    ExistingRecordReference,
)
from core.config import is_dev_mode
from core.context import ContextAssembler, ContextPolicy
from core.knowledge import get_knowledge_service
from core.retrieval import get_retrieval_service
from core.telemetry.models import TelemetryModuleEntry, TelemetrySnapshot

CORE_DAILY_SOURCES = ("reminders", "calendar", "email", "weather")
SOURCE_SCOPES = {
    "reminders": "Pending reminders in the selected list",
    "calendar": "Selected calendar events in the configured 14-day window",
    "email": "Up to eight unread primary inbox message metadata records",
    "weather": "Current weather and the available near-term forecast",
    "news": "Available cached headlines",
    "f1": "Available F1 telemetry snapshot",
    "football": "Available followed-team fixtures",
    "market": "Available configured market symbols",
}
_MAX_OBSERVED_EVIDENCE = 32
_MAX_SYNTHESIS_EVIDENCE = 18
_MAX_PENDING_REVIEWS = 5
_MAX_REPORT_CANDIDATES = 50
_MAX_SELECTED_REPORTS = 3
_STOP_WORDS = frozenset(
    "about after again against and any are around because before between could "
    "from have into just more most other should some than that their there "
    "these this those through with your today tomorrow reminder calendar "
    "email event task meeting needs need update status outlook gmail".split()
)

def _telemetry_inputs(
    snapshot: TelemetrySnapshot | None,
    refresh_problem: str | None,
    dev_mode: bool,
    *,
    now: datetime | None = None,
) -> tuple[list[BriefingCoverage], list[BriefingEvidence]]:
    now = now or datetime.now(timezone.utc)
    coverage: list[BriefingCoverage] = []
    evidence: list[BriefingEvidence] = []
    for source in (
        "reminders", "calendar", "email", "weather", "news", "f1", "football", "market"
    ):
        entry = snapshot.modules.get(source) if snapshot else None
        status, reason = _coverage_status(entry)
        if snapshot is None:
            status, reason = "failed", "telemetry_snapshot_unavailable"
        elif refresh_problem and source in CORE_DAILY_SOURCES and status not in {"disabled", "failed"}:
            status, reason = "partial", refresh_problem
        data = entry.data if entry is not None else {}
        truncated = _module_truncated(source, data)
        if truncated and status == "complete":
            status = "partial"
            reason = "source_limit_reached"
        observed_at = _parse_datetime(entry.observed_at) if entry else None
        freshness_seconds = (
            max(0, int((now - observed_at).total_seconds()))
            if observed_at is not None
            else None
        )
        scope_key = _telemetry_scope_key(source, data, dev_mode=dev_mode)
        coverage_index = len(coverage)
        coverage.append(
            BriefingCoverage(
                source=source,
                scope=SOURCE_SCOPES[source],
                scope_key=scope_key,
                normalization_version=NORMALIZATION_VERSION if scope_key else None,
                status=status,
                observed_at=observed_at,
                freshness_seconds=freshness_seconds,
                truncated=truncated,
                reason=reason,
            )
        )
        if entry is None or status in {"disabled", "failed", "unavailable"}:
            continue
        normalized = _module_evidence(source, entry, dev_mode=dev_mode, now=now)
        if _expected_evidence_count(source, data) > len(normalized):
            current = coverage[coverage_index]
            coverage[coverage_index] = current.model_copy(update={
                "status": "partial" if current.status == "complete" else current.status,
                "truncated": True,
                "reason": current.reason or "evidence_normalization_limit",
            })
        evidence.extend(normalized)
    return coverage, evidence



def _semantic_fingerprint(value: Any) -> str:
    return _content_hash(_canonical(value))


def _expected_evidence_count(source: str, data: dict[str, Any]) -> int:
    if source == "reminders":
        return min(8, len(_dict_list(data.get("records"))))
    if source == "calendar":
        return min(12, len(_dict_list(data.get("events"))))
    if source == "email":
        return min(8, len(_dict_list(data.get("emails"))))
    if source == "news":
        return min(5, len(_dict_list(data.get("headlines"))))
    if source == "football":
        return min(6, len(_dict_list(data.get("fixtures"))))
    if source == "market":
        return min(12, len(_dict_list(data.get("tickers"))))
    if source == "weather":
        return int(bool(_weather_text(data)))
    if source == "f1":
        return int(isinstance(data.get("f1_map"), dict))
    return 0


def _scope_key(source: str, value: Any) -> str:
    return f"{source}:v{NORMALIZATION_VERSION}:{_content_hash(_canonical(value))}"


def _telemetry_scope_key(source: str, data: dict[str, Any], *, dev_mode: bool) -> str | None:
    if dev_mode and source in {"email", "calendar", "reminders"}:
        return None
    if source == "reminders":
        list_id = data.get("list_id")
        return _scope_key(source, {"list_id": list_id, "limit": 8}) if isinstance(list_id, str) and list_id else None
    if source == "calendar":
        selected = data.get("selected_calendar_ids")
        if not isinstance(selected, list) or not all(isinstance(value, str) for value in selected):
            return None
        return _scope_key(source, {"calendar_ids": sorted(selected), "window_days": data.get("window_days", 14), "limit": 12})
    if source == "email":
        return _scope_key(source, {"mailbox": "primary", "unread": True, "limit": 8})
    if source == "weather":
        location, zone = data.get("location"), data.get("timezone")
        if not isinstance(location, str) or not location or not isinstance(zone, str) or not zone:
            return None
        return _scope_key(source, {"location": location.casefold(), "timezone": zone, "forecast_days": 3})
    if source == "news":
        topics = data.get("topics")
        if not isinstance(topics, list) or not all(isinstance(value, str) for value in topics):
            return None
        return _scope_key(source, {"topics": sorted(topics), "headline_limit": 5})
    if source == "f1":
        return _scope_key(source, {"series": "formula1", "selection": "next_race"}) if isinstance(data.get("f1_map"), dict) else None
    if source == "football":
        team_ids = data.get("configured_team_ids")
        if not isinstance(team_ids, list) or not all(isinstance(value, (str, int)) for value in team_ids):
            return None
        return _scope_key(source, {"team_ids": sorted(str(value) for value in team_ids), "limit": 6})
    if source == "market":
        symbols = [str(item.get("symbol") or "").upper() for item in _dict_list(data.get("tickers")) if item.get("symbol")]
        if not symbols:
            return None
        return _scope_key(source, {"symbols": sorted(symbols), "limit": 12})
    return None


def _coverage_status(
    entry: TelemetryModuleEntry | None,
) -> tuple[str, str | None]:
    if entry is None:
        return "unavailable", "source_not_in_snapshot"
    if entry.status == "disabled":
        return "disabled", entry.reason_code or "disabled_by_settings"
    if entry.status == "unavailable":
        return "failed", entry.reason_code or "source_unavailable"
    if entry.status == "degraded" or entry.freshness == "stale":
        return "partial", entry.reason_code or "stale_or_partial_source"
    return "complete", None


def _module_truncated(source: str, data: dict[str, Any]) -> bool:
    if data.get("truncated") is True:
        return True
    if source == "reminders":
        records = _dict_list(data.get("records"))
        count = _safe_count(data.get("count"))
        return len(records) > 8 or count > 8
    if source == "email":
        emails = _dict_list(data.get("emails"))
        count = _safe_count(data.get("count"))
        return len(emails) > 8 or count > min(len(emails), 8)
    if source == "news":
        return len(_dict_list(data.get("headlines"))) >= 5
    if source == "calendar":
        events = _dict_list(data.get("events"))
        total_count = _safe_count(data.get("total_count"), default=len(events))
        return (
            _safe_count(data.get("failed_calendar_count")) > 0
            or len(events) > 12
            or total_count > 12
        )
    if source == "football":
        fixtures = _dict_list(data.get("fixtures"))
        return len(fixtures) > 6 or _safe_count(data.get("total_count")) > 6
    if source == "market":
        tickers = _dict_list(data.get("tickers"))
        return len(tickers) > 12 or _safe_count(data.get("count")) > 12
    if source == "weather":
        return len(_dict_list(data.get("daily"))) > 3
    return False


def _safe_count(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _module_evidence(
    source: str,
    entry: TelemetryModuleEntry,
    *,
    dev_mode: bool,
    now: datetime | None = None,
) -> list[BriefingEvidence]:
    now = now or datetime.now(timezone.utc)
    data = entry.data
    observed_at = _parse_datetime(entry.observed_at)
    items: list[BriefingEvidence] = []
    if source == "reminders":
        records = _dict_list(data.get("records"))
        records.sort(key=lambda item: (-_reminder_priority(item, now), _parse_datetime(item.get("due")) or datetime.max.replace(tzinfo=timezone.utc), str(item.get("id") or "")))
        for item in records[:8]:
            source_id = str(item.get("id") or "")
            if not source_id:
                source_id = _content_id(_canonical(item))
                identity_kind = "content"
            else:
                identity_kind = "provider"
            content = (
                "[HIDDEN] Reminder content masked due to DEV_MODE"
                if dev_mode
                else _reminder_text(item)
            )
            revision = str(item.get("last_modified_at") or "")
            items.append(_evidence(
                source=source,
                source_id=source_id,
                identity_kind=identity_kind,
                revision=revision or _content_hash(content),
                revision_kind="provider" if revision else "content",
                observed_at=observed_at,
                effective_at=_parse_datetime(item.get("due")),
                content=content,
                priority=_reminder_priority(item, now),
                semantic_fingerprint=_semantic_fingerprint({
                    "note": item.get("note"), "due": _normalized_instant(item.get("due")),
                    "importance": item.get("importance"), "sync_state": item.get("sync_state"),
                }) if identity_kind == "provider" and not dev_mode else None,
            ))
    elif source == "calendar":
        for item in _dict_list(data.get("events"))[:12]:
            calendar_id = str(item.get("calendar_id") or "")
            recurring_event_id = str(item.get("recurring_event_id") or "")
            instance_id = str(item.get("event_id") or "")
            original_start = _calendar_semantic_time(item.get("original_start"), item) or ""
            event_id = recurring_event_id if recurring_event_id and original_start else instance_id
            if calendar_id and event_id:
                source_id = f"calendar:{calendar_id}:{event_id}:{original_start}"
                identity_kind = "provider"
            else:
                source_id = _content_id(_calendar_text(item))
                identity_kind = "content"
            content = _calendar_text(item)
            revision = str(item.get("revision") or "")
            items.append(_evidence(
                source=source,
                source_id=source_id,
                identity_kind=identity_kind,
                revision=revision or _content_hash(content),
                revision_kind="provider" if revision else "content",
                observed_at=observed_at,
                effective_at=_calendar_datetime(item.get("start"), item),
                content=content,
                priority=_calendar_priority(item, now),
                semantic_fingerprint=_semantic_fingerprint({
                    "summary": item.get("summary"),
                    "start": _calendar_semantic_time(item.get("start"), item),
                    "end": _calendar_semantic_time(item.get("end"), item),
                    "location": item.get("location"),
                    "calendar_id": item.get("calendar_id"),
                    "calendar_name": item.get("calendar_name"),
                    "all_day": bool(item.get("all_day")),
                    "time_zone": item.get("time_zone"),
                }) if identity_kind == "provider" and not dev_mode else None,
                all_day=bool(item.get("all_day")),
                time_zone=str(item.get("time_zone") or "") or None,
                effective_until=_calendar_datetime(item.get("end"), item),
            ))
    elif source == "email":
        emails = _dict_list(data.get("emails"))
        for item in emails[:8]:
            message_id = str(item.get("id") or "")
            thread_id = str(item.get("thread_id") or "")
            stable = message_id and not message_id.startswith("masked:")
            source_id = f"gmail:{message_id}:{thread_id}" if message_id else _content_id(_email_text(item))
            identity_kind = "provider" if stable else ("masked" if message_id else "content")
            content = _email_text(item)
            revision = str(item.get("revision") or "")
            items.append(_evidence(
                source=source,
                source_id=source_id,
                identity_kind=identity_kind,
                revision=revision or _content_hash(content),
                revision_kind="provider" if revision and not dev_mode else "content",
                observed_at=_parse_datetime(item.get("received_at")) or observed_at,
                effective_at=_parse_datetime(item.get("received_at") or item.get("time")),
                content=content,
                priority=72,
                semantic_fingerprint=_semantic_fingerprint({
                    "subject": item.get("subject"), "sender": item.get("sender"),
                    "received_at": _normalized_instant(item.get("received_at") or item.get("time")),
                    "snippet": item.get("snippet"),
                }) if stable and not dev_mode else None,
            ))
    elif source == "weather":
        content = _weather_text(data)
        if content:
            items.append(_evidence(
                source=source,
                source_id="weather:current",
                identity_kind="provider",
                revision=_content_hash(content),
                revision_kind="content",
                observed_at=observed_at,
                content=content,
                priority=30,
                semantic_fingerprint=_semantic_fingerprint(_weather_semantics(data)),
                comparison_state=_weather_comparison_state(data),
            ))
    elif source == "news":
        for item in _dict_list(data.get("headlines"))[:5]:
            content = _news_text(item)
            article_id = str(item.get("article_id") or "").strip()
            items.append(_evidence(
                source=source,
                source_id=f"news:{article_id}" if article_id else _content_id(content),
                identity_kind="provider" if article_id else "content",
                revision=_content_hash(content),
                revision_kind="content",
                observed_at=observed_at,
                effective_at=_parse_datetime(item.get("published_at")),
                content=content,
                priority=15,
                semantic_fingerprint=_semantic_fingerprint({
                    "headline": item.get("headline"), "topic": item.get("topic"),
                    "source": item.get("source"), "published_at": _normalized_instant(item.get("published_at")),
                    "synopsis": item.get("synopsis"),
                }),
            ))
    elif source == "football":
        for item in _dict_list(data.get("fixtures"))[:6]:
            content = _fixture_text(item)
            source_id = str(item.get("id") or item.get("fixture_id") or "")
            items.append(_evidence(
                source=source,
                source_id=f"football:{source_id}" if source_id else _content_id(content),
                identity_kind="provider" if source_id else "content",
                revision=_content_hash(content),
                revision_kind="content",
                observed_at=observed_at,
                effective_at=_parse_datetime(item.get("kickoff_at")),
                content=content,
                priority=12,
                semantic_fingerprint=_semantic_fingerprint({
                    key: item.get(key) for key in (
                        "home_team", "away_team", "home", "away", "kickoff_at",
                        "competition", "status", "home_score", "away_score",
                    ) if key in item
                }) if source_id else None,
            ))
    elif source == "market":
        for item in _dict_list(data.get("tickers"))[:12]:
            symbol = str(item.get("symbol") or "").strip()
            content = _market_text(item)
            if not symbol or not content:
                continue
            items.append(_evidence(
                source=source,
                source_id=f"market:{symbol.upper()}",
                identity_kind="provider",
                revision=_content_hash(content),
                revision_kind="content",
                observed_at=observed_at,
                effective_at=_parse_datetime(item.get("close_date")),
                content=content,
                priority=10,
                semantic_fingerprint=_semantic_fingerprint({
                    "symbol": symbol.upper(), "price": item.get("price"),
                    "change_percent": item.get("change_percent"), "status": item.get("status"),
                }),
                comparison_state=_market_comparison_state(item),
            ))
    elif source == "f1":
        f1_map = data.get("f1_map")
        if isinstance(f1_map, dict):
            stable_f1 = {
                key: f1_map.get(key) for key in (
                    "raceName", "round", "country", "raceStart", "sprintScheduled", "sprintDateTimeEST"
                )
            }
            race_start = _parse_datetime(f1_map.get("raceStart"))
            content = "; ".join(
                part for part in (
                    f"Next race: {f1_map.get('raceName')}",
                    f"round {f1_map.get('round')}" if f1_map.get("round") else "",
                    str(f1_map.get("country") or ""),
                    f"starts {f1_map.get('raceDateTimeEST')}" if f1_map.get("raceDateTimeEST") else "",
                    f"sprint: {f1_map.get('sprintDateTimeEST')}" if f1_map.get("sprintScheduled") else "No sprint scheduled",
                ) if part
            )
            items.append(_evidence(
                source=source,
                source_id=f"f1:{f1_map.get('round') or 'next'}:{race_start.isoformat() if race_start else 'unknown'}",
                identity_kind="provider",
                revision=_content_hash(_canonical(stable_f1)),
                revision_kind="content",
                observed_at=observed_at,
                effective_at=race_start,
                content=content[:1000],
                priority=10,
                semantic_fingerprint=_semantic_fingerprint(stable_f1) if race_start else None,
            ))
    return items


def _personal_inputs(
    *,
    prompt: str,
    policy: ContextPolicy,
    partition: str,
    allow: bool,
    now: datetime | None = None,
) -> tuple[list[BriefingEvidence], list[BriefingCoverage]]:
    observed: list[BriefingEvidence] = []
    snapshot_at = now or datetime.now(timezone.utc)
    if not allow:
        reason = "dev_mode_personal_context_excluded" if is_dev_mode() else "personal_context_disabled"
        return observed, [
            BriefingCoverage(source=name, scope=scope, status="disabled", observed_at=snapshot_at, reason=reason)
            for name, scope in (
                ("accepted_context", "Relevant accepted personal context"),
                ("pending_review", "Pending personal-context reviews"),
                ("external_report", "Relevant non-dismissed external activity reports"),
                ("action", "Verified action outcomes"),
            )
        ]

    knowledge = get_knowledge_service()
    assembler = ContextAssembler(get_retrieval_service(), knowledge)
    try:
        personal_candidates = assembler.personal_candidates(prompt=prompt, policy=policy)
        for rendered, reference in personal_candidates:
            detail = knowledge.get_record(UUID(reference.id), partition=partition)
            record = detail.record
            observed.append(_evidence(
                source="accepted_context",
                source_id=str(record.id),
                identity_kind="provider",
                revision=record.updated_at,
                revision_kind="provider",
                observed_at=_parse_datetime(record.updated_at),
                effective_at=_parse_datetime(record.effective_at),
                trust="accepted",
                content=rendered[:1600],
                record_reference=ExistingRecordReference(kind="knowledge", id=str(record.id)),
                priority=66,
                semantic_fingerprint=_semantic_fingerprint({
                    "kind": record.kind, "text": record.text, "status": record.status,
                    "predicate": record.predicate, "object_value": record.object_value,
                    "effective_at": record.effective_at, "sensitive": record.sensitive,
                }),
            ))
        accepted_status = "partial"
        accepted_reason = "retrieval_is_relevance_limited"
    except Exception:
        observed = []
        accepted_status = "failed"
        accepted_reason = "accepted_context_unavailable"

    try:
        reviews = knowledge.list_reviews(partition=partition, decisions=("pending",), limit=20)
        for review in reviews[:_MAX_PENDING_REVIEWS]:
            text_value = _review_text(review)
            if not text_value:
                continue
            observed.append(_evidence(
                source="pending_review",
                source_id=str(review.id),
                identity_kind="provider",
                revision=review.created_at,
                revision_kind="provider",
                observed_at=_parse_datetime(review.created_at),
                trust="pending",
                content=text_value,
                record_reference=ExistingRecordReference(kind="context_review", id=str(review.id)),
                priority=58,
                semantic_fingerprint=_semantic_fingerprint({
                    "operation": review.operation, "proposal": review.proposal,
                    "evidence": review.evidence,
                }),
            ))
        reviews_truncated = len(reviews) > _MAX_PENDING_REVIEWS or len(reviews) >= 20
        review_status = "partial" if reviews_truncated else "complete"
        review_reason = "source_limit_reached" if reviews_truncated else None
    except Exception:
        review_status = "failed"
        review_reason = "pending_review_state_unavailable"

    external_coverage, external_evidence = _external_inputs(
        prompt=prompt, observed=observed, partition=partition, observed_at=snapshot_at
    )
    observed.extend(external_evidence)
    action_coverage = _verified_action_inputs(
        observed=observed, partition=partition, observed_at=snapshot_at
    )
    return observed, [
        BriefingCoverage(
            source="accepted_context",
            scope="Relevant canonically reloaded accepted records",
            scope_key=_scope_key("accepted_context", {"retrieval": "relevance-v1"}),
            normalization_version=NORMALIZATION_VERSION,
            status=accepted_status,
            observed_at=snapshot_at,
            truncated=True,
            reason=accepted_reason,
        ),
        BriefingCoverage(
            source="pending_review",
            scope="Pending personal-context reviews",
            scope_key=_scope_key("pending_review", {"decision": "pending", "limit": 5}),
            normalization_version=NORMALIZATION_VERSION,
            status=review_status,
            observed_at=snapshot_at,
            truncated=review_status == "partial",
            reason=review_reason,
        ),
        *external_coverage,
        *action_coverage,
    ]


def _external_inputs(
    *, prompt: str, observed: list[BriefingEvidence], partition: str,
    observed_at: datetime | None = None,
) -> tuple[list[BriefingCoverage], list[BriefingEvidence]]:
    try:
        reports = get_activity_service().list(
            partition=partition, disposition=None, limit=_MAX_REPORT_CANDIDATES
        )
        candidates: list[tuple[int, str, BriefingEvidence]] = []
        context = " ".join([prompt, *(item.content or "" for item in observed)])
        for report in reports[:_MAX_REPORT_CANDIDATES]:
            if report.disposition == "dismissed":
                continue
            content = report.content
            text_value = _report_text(content)
            score = _relevance_score(context, " ".join((content.title, *content.subjects, *content.projects)), text_value)
            if score <= 0:
                continue
            evidence = _evidence(
                source="external_report",
                source_id=str(report.id),
                identity_kind="provider",
                revision=report.received_at,
                revision_kind="provider",
                observed_at=_parse_datetime(report.received_at),
                trust="untrusted",
                content=text_value,
                record_reference=ExistingRecordReference(kind="external_activity", id=str(report.id)),
                priority=60 + score,
                semantic_fingerprint=_semantic_fingerprint({
                    "content": content.model_dump(mode="json"),
                    "provenance": {
                        "client_id": report.client_id,
                        "client_display_name": report.client_display_name,
                        "principal": report.principal,
                        "received_at": _normalized_instant(report.received_at),
                    },
                }),
            )
            candidates.append((score, report.received_at, evidence))
        candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
        selected = [row[2] for row in candidates[:_MAX_SELECTED_REPORTS]]
        return [
            BriefingCoverage(
                source="external_report",
                scope="At most three relevant, non-dismissed reports from the newest 50 candidates",
                scope_key=_scope_key("external_report", {"relevance": "context-v1", "limit": 3}),
                normalization_version=NORMALIZATION_VERSION,
                observed_at=observed_at or datetime.now(timezone.utc),
                status="partial",
                truncated=True,
                reason=("candidate_limit_reached" if len(reports) >= _MAX_REPORT_CANDIDATES else "relevance_selection_limit"),
            ),
        ], selected
    except Exception:
        return [BriefingCoverage(source="external_report", scope="Relevant non-dismissed external activity reports", status="failed", observed_at=observed_at or datetime.now(timezone.utc), reason="external_reports_unavailable")], []


def _verified_action_inputs(
    *, observed: list[BriefingEvidence], partition: str,
    observed_at: datetime | None = None,
) -> list[BriefingCoverage]:
    if is_dev_mode() or partition != "production":
        return [BriefingCoverage(source="action", scope="Verified action outcomes", status="disabled", observed_at=observed_at, reason="action_service_partition_unavailable")]
    try:
        actions = get_action_service().list(statuses=("verified",), limit=20)
        for action in actions:
            observed.append(_evidence(
                source="action",
                source_id=action.action_id,
                identity_kind="provider",
                revision=action.updated_at.isoformat(),
                revision_kind="provider",
                observed_at=action.updated_at,
                trust="observed",
                content=f"Verified action: {action.proposal.summary}",
                record_reference=ExistingRecordReference(kind="action", id=action.action_id),
                priority=40,
                semantic_fingerprint=_semantic_fingerprint({
                    "status": "verified", "summary": action.proposal.summary,
                }),
            ))
        truncated = len(actions) >= 20
        return [
            BriefingCoverage(
                source="action",
                scope="Up to 20 verified action outcomes",
                scope_key=_scope_key("action", {"status": "verified", "limit": 20}),
                normalization_version=NORMALIZATION_VERSION,
                observed_at=observed_at or datetime.now(timezone.utc),
                status="partial" if truncated else "complete",
                truncated=truncated,
                reason="source_limit_reached" if truncated else None,
            )
        ]
    except Exception:
        return [BriefingCoverage(source="action", scope="Verified action outcomes", status="failed", observed_at=observed_at, reason="verified_action_state_unavailable")]


def _evidence(
    *,
    source: str,
    source_id: str,
    identity_kind: str,
    revision: str | None = None,
    revision_kind: str = "none",
    observed_at: datetime | None = None,
    effective_at: datetime | None = None,
    trust: str = "observed",
    content: str,
    record_reference: ExistingRecordReference | None = None,
    priority: int = 0,
    semantic_fingerprint: str | None = None,
    comparison_state: dict[str, str | float | int | bool | None] | None = None,
    all_day: bool = False,
    time_zone: str | None = None,
    effective_until: datetime | None = None,
) -> BriefingEvidence:
    if is_dev_mode() and source in {"email", "calendar", "reminders"}:
        source_id = "dev:" + _content_hash(source_id)
        identity_kind = "masked"
        revision = _content_hash(revision or source_id)
        revision_kind = "content"
        content = "[HIDDEN] Source content masked due to DEV_MODE"
        record_reference = None
    item = BriefingEvidence(
        source=source,
        source_id=_bounded_source_id(source_id) or _content_id(content),
        identity_kind=identity_kind,  # type: ignore[arg-type]
        revision=revision,
        revision_kind=revision_kind,  # type: ignore[arg-type]
        semantic_fingerprint=(
            semantic_fingerprint
            if semantic_fingerprint and not (is_dev_mode() and source in {"email", "calendar", "reminders"})
            else None
        ),
        comparison_state=comparison_state,
        normalization_version=NORMALIZATION_VERSION if semantic_fingerprint else None,
        observed_at=observed_at,
        effective_at=effective_at,
        effective_until=effective_until,
        all_day=all_day,
        time_zone=time_zone,
        trust=trust,  # type: ignore[arg-type]
        content=content[:2000],
        record_reference=record_reference,
        selection_priority=min(100, max(0, int(priority))),
    )
    return item


def _bounded_source_id(value: str) -> str:
    if len(value) <= 512:
        return value
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return value[: 512 - len(suffix) - 1] + ":" + suffix


def _priority(item: BriefingEvidence) -> int:
    return item.selection_priority


def _reminder_priority(item: dict[str, Any], now: datetime | None = None) -> int:
    due = _parse_datetime(item.get("due"))
    if due is None:
        return 50
    now = now or datetime.now(timezone.utc)
    local_today = now.astimezone().date()
    due_local = due.astimezone().date() if due.tzinfo else due.date()
    if due < now:
        return 100
    if due_local == local_today:
        return 85
    return 60


def _calendar_priority(item: dict[str, Any], now: datetime | None = None) -> int:
    starts = _parse_datetime(item.get("start"))
    if starts is None:
        return 55
    now = now or datetime.now(timezone.utc)
    local_today = now.astimezone().date()
    start_local = starts.astimezone().date() if starts.tzinfo else starts.date()
    if starts < now + timedelta(hours=3):
        return 95
    if start_local == local_today:
        return 90
    if starts < now + timedelta(days=2):
        return 80
    return 58


def _reminder_text(item: dict[str, Any]) -> str:
    parts = [str(item.get("note") or "Reminder")]
    due = item.get("due")
    if due:
        parts.append(f"due {due}")
    importance = item.get("importance")
    if importance:
        parts.append(f"importance {importance}")
    return "; ".join(parts)[:1800]


def _calendar_text(item: dict[str, Any]) -> str:
    parts = [str(item.get("summary") or "Calendar event")]
    start = item.get("start")
    if start:
        parts.append(f"starts {start}")
    if item.get("end"):
        parts.append(f"ends {item['end']}")
    if item.get("location"):
        parts.append(f"location {item['location']}")
    if item.get("calendar_name"):
        parts.append(f"calendar {item['calendar_name']}")
    return "; ".join(parts)[:1800]


def _email_text(item: dict[str, Any]) -> str:
    parts = [f"Unread email: {item.get('subject') or '(no subject)'}"]
    if item.get("sender"):
        parts.append(f"from {item['sender']}")
    if item.get("received_at"):
        parts.append(f"received {item['received_at']}")
    if item.get("snippet"):
        parts.append(str(item["snippet"])[:240])
    return "; ".join(parts)[:1800]


def _weather_text(data: dict[str, Any]) -> str:
    current = data.get("current")
    if not isinstance(current, dict):
        current = data
    parts: list[str] = []
    for key, label in (("condition", "conditions"), ("temp_f", "temperature"), ("apparent_temp_f", "feels like"), ("temp_max_f", "high"), ("temp_min_f", "low"), ("precip_probability_max", "precipitation chance"), ("wind_speed_mph", "wind")):
        value = current.get(key)
        if value is not None:
            parts.append(f"{label}: {value}")
    daily = _dict_list(data.get("daily"))
    for forecast in daily[:3]:
        date_label = str(forecast.get("date") or "forecast")
        details = ", ".join(
            f"{label} {forecast[key]}" for key, label in (
                ("condition", "conditions"), ("temp_max_f", "high"),
                ("temp_min_f", "low"), ("precip_probability", "precipitation chance"),
            ) if forecast.get(key) is not None
        )
        if details:
            parts.append(f"{date_label}: {details}")
    return "; ".join(parts)[:1200]


def _weather_semantics(data: dict[str, Any]) -> dict[str, Any]:
    current = data.get("current")
    if not isinstance(current, dict):
        current = data
    current_fields = (
        "condition", "temp_f", "apparent_temp_f", "temp_max_f", "temp_min_f",
        "precip_probability_max", "precip_sum_in", "wind_speed_mph",
    )
    return {
        "location": data.get("location"),
        "timezone": data.get("timezone"),
        "current": {key: current.get(key) for key in current_fields if key in current},
        "daily": [
            {key: item.get(key) for key in ("date", "condition", "temp_max_f", "temp_min_f", "precip_probability", "precipitation_in", "wind_speed_mph") if key in item}
            for item in _dict_list(data.get("daily"))[:3]
        ],
    }


def _weather_comparison_state(data: dict[str, Any]) -> dict[str, str | float]:
    """Keep only bounded, user-meaningful weather values for comparison."""
    current = data.get("current")
    if not isinstance(current, dict):
        current = data
    state: dict[str, str | float] = {}
    numeric_fields = (
        "temp_f", "apparent_temp_f", "temp_max_f", "temp_min_f",
        "precip_probability_max", "precip_sum_in", "wind_speed_mph",
    )
    condition = current.get("condition")
    if isinstance(condition, str) and condition.strip():
        state["current:condition"] = condition.strip().casefold()
    for key in numeric_fields:
        value = _finite_number(current.get(key))
        if value is not None:
            state[f"current:{key}"] = value

    daily_fields = (
        "temp_max_f", "temp_min_f", "precip_probability",
        "precipitation_in", "wind_speed_mph",
    )
    for forecast in _dict_list(data.get("daily"))[:3]:
        try:
            forecast_date = date.fromisoformat(str(forecast.get("date") or "")).isoformat()
        except ValueError:
            continue
        key_prefix = f"daily:{forecast_date}:"
        forecast_condition = forecast.get("condition")
        if isinstance(forecast_condition, str) and forecast_condition.strip():
            state[key_prefix + "condition"] = forecast_condition.strip().casefold()
        for key in daily_fields:
            value = _finite_number(forecast.get(key))
            if value is not None:
                state[key_prefix + key] = value
    return state


def _market_comparison_state(item: dict[str, Any]) -> dict[str, str | float]:
    state: dict[str, str | float] = {}
    price = _finite_number(item.get("price"))
    status = item.get("status")
    if price is not None:
        state["price"] = price
    if isinstance(status, str) and status:
        state["status"] = status
    return state


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _normalized_instant(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed.astimezone(timezone.utc).isoformat()
    return str(value) if value is not None else None


def _calendar_semantic_time(value: Any, event: dict[str, Any]) -> str | None:
    """Normalize timed values to UTC and retain all-day values as local dates."""
    if bool(event.get("all_day")):
        raw = value.get("date") if isinstance(value, dict) else value
        try:
            return date.fromisoformat(str(raw)).isoformat()
        except (TypeError, ValueError):
            pass
    return _normalized_instant(value)


def _news_text(item: dict[str, Any]) -> str:
    parts = [str(item.get("headline") or "")]
    for key in ("topic", "source", "published_at", "synopsis"):
        value = item.get(key)
        if value:
            parts.append(f"{key.replace('_', ' ')}: {value}")
    return "; ".join(parts)[:1500]


def _fixture_text(item: dict[str, Any]) -> str:
    return "; ".join(f"{key}: {value}" for key, value in item.items() if value is not None)[:1200]


def _market_text(item: dict[str, Any]) -> str:
    symbol = str(item.get("symbol") or "")
    price = item.get("price")
    change = item.get("change_percent")
    status = item.get("status")
    return f"{symbol} market snapshot: price {price}; change {change}%; status {status}"[:800]


def _review_text(review: Any) -> str:
    values = [review.evidence.get("original_text"), review.proposal.get("text"), review.proposal.get("note")]
    text_value = next((value for value in values if isinstance(value, str) and value.strip()), "")
    if not text_value:
        return ""
    return f"Pending personal-context review ({review.operation}): {text_value[:1400]}"


def _report_text(content: Any) -> str:
    parts = [f"Untrusted external report: {content.title}", f"Status: {content.task_status}", f"Outcome: {content.outcome[:900]}"]
    if content.subjects:
        parts.append("Subjects: " + ", ".join(content.subjects[:8]))
    if content.projects:
        parts.append("Projects: " + ", ".join(content.projects[:8]))
    for finding in content.findings[:3]:
        parts.append(f"Finding: {finding.title or ''} {finding.text[:280]}")
    if content.suggested_follow_up:
        parts.append(f"Suggested follow-up: {content.suggested_follow_up[:240]}")
    return "; ".join(parts)[:1800]


def _relevance_score(context: str, labels: str, text_value: str) -> int:
    context_terms = _terms(context)
    content_terms = _terms(text_value)
    label_terms = _terms(labels)
    return len(context_terms & content_terms) + 3 * len(context_terms & label_terms)


def _context_query(evidence: list[BriefingEvidence]) -> str:
    return " ".join(item.content or "" for item in evidence[:16])[:8000] or "today commitments and current plans"


def _terms(value: str) -> set[str]:
    return {
        term for term in re.findall(r"[a-z0-9]{3,}", value.casefold())
        if term not in _STOP_WORDS
    }


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(value), time.min)
            except ValueError:
                return None
    elif isinstance(value, dict):
        raw = value.get("date_time") or value.get("dateTime") or value.get("date")
        return _parse_datetime(raw)
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed.astimezone(timezone.utc)



def _calendar_datetime(value: Any, event: dict[str, Any]) -> datetime | None:
    if bool(event.get("all_day")):
        try:
            day = date.fromisoformat(str(value))
        except ValueError:
            return _parse_datetime(value)
        zone_name = event.get("time_zone")
        try:
            zone = ZoneInfo(zone_name) if isinstance(zone_name, str) and zone_name else timezone.utc
        except (ZoneInfoNotFoundError, ValueError):
            zone = timezone.utc
        return datetime.combine(day, time.min, tzinfo=zone)
    return _parse_datetime(value)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(value)


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _content_id(value: str) -> str:
    return "content:" + _content_hash(value)[:32]
