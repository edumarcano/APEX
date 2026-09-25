"""Source-specific normalization and bounded evidence selection for Daily."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from core.actions import get_action_service
from core.activity import get_activity_service
from core.briefings.models import BriefingCoverage, BriefingEvidence, ExistingRecordReference
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
) -> tuple[list[BriefingCoverage], list[BriefingEvidence]]:
    now = datetime.now(timezone.utc)
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
        coverage.append(
            BriefingCoverage(
                source=source,
                scope=SOURCE_SCOPES[source],
                status=status,
                observed_at=observed_at,
                freshness_seconds=freshness_seconds,
                truncated=truncated,
                reason=reason,
            )
        )
        if entry is None or status in {"disabled", "failed", "unavailable"}:
            continue
        evidence.extend(_module_evidence(source, entry, dev_mode=dev_mode))
    return coverage, evidence


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
) -> list[BriefingEvidence]:
    data = entry.data
    observed_at = _parse_datetime(entry.observed_at)
    items: list[BriefingEvidence] = []
    if source == "reminders":
        records = _dict_list(data.get("records"))
        records.sort(key=_reminder_priority)
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
                priority=_reminder_priority(item),
            ))
    elif source == "calendar":
        for item in _dict_list(data.get("events"))[:12]:
            calendar_id = str(item.get("calendar_id") or "")
            recurring_event_id = str(item.get("recurring_event_id") or "")
            instance_id = str(item.get("event_id") or "")
            original_start = str(item.get("original_start") or "")
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
                effective_at=_parse_datetime(item.get("start")),
                content=content,
                priority=_calendar_priority(item),
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
                effective_at=_parse_datetime(item.get("received_at")),
                content=content,
                priority=72,
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
            ))
    elif source == "news":
        for item in _dict_list(data.get("headlines"))[:5]:
            content = _news_text(item)
            items.append(_evidence(
                source=source,
                source_id=_content_id(content),
                identity_kind="content",
                revision=_content_hash(content),
                revision_kind="content",
                observed_at=observed_at,
                effective_at=_parse_datetime(item.get("published_at")),
                content=content,
                priority=15,
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
            ))
    elif source == "f1":
        display = entry.display_text.strip()
        if display and not display.lower().endswith("unavailable"):
            items.append(_evidence(
                source=source,
                source_id="f1:current",
                identity_kind="provider",
                revision=_content_hash(display),
                revision_kind="content",
                observed_at=observed_at,
                content=display[:1000],
                priority=10,
            ))
    return items


def _personal_inputs(
    *,
    prompt: str,
    policy: ContextPolicy,
    partition: str,
    allow: bool,
) -> tuple[list[BriefingEvidence], list[BriefingCoverage]]:
    observed: list[BriefingEvidence] = []
    if not allow:
        reason = "dev_mode_personal_context_excluded" if is_dev_mode() else "personal_context_disabled"
        return observed, [
            BriefingCoverage(source=name, scope=scope, status="disabled", reason=reason)
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
            ))
        accepted_status = "complete"
        accepted_reason = None
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
            ))
        reviews_truncated = len(reviews) > _MAX_PENDING_REVIEWS or len(reviews) >= 20
        review_status = "partial" if reviews_truncated else "complete"
        review_reason = "source_limit_reached" if reviews_truncated else None
    except Exception:
        review_status = "failed"
        review_reason = "pending_review_state_unavailable"

    external_coverage, external_evidence = _external_inputs(
        prompt=prompt, observed=observed, partition=partition
    )
    observed.extend(external_evidence)
    action_coverage = _verified_action_inputs(observed=observed, partition=partition)
    return observed, [
        BriefingCoverage(source="accepted_context", scope="Relevant canonically reloaded accepted records", status=accepted_status, reason=accepted_reason),
        BriefingCoverage(
            source="pending_review",
            scope="Pending personal-context reviews",
            status=review_status,
            truncated=review_status == "partial",
            reason=review_reason,
        ),
        *external_coverage,
        *action_coverage,
    ]


def _external_inputs(
    *, prompt: str, observed: list[BriefingEvidence], partition: str
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
            )
            candidates.append((score, report.received_at, evidence))
        candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
        selected = [row[2] for row in candidates[:_MAX_SELECTED_REPORTS]]
        return [
            BriefingCoverage(
                source="external_report",
                scope="At most three relevant, non-dismissed reports from the newest 50 candidates",
                status="partial" if len(reports) >= _MAX_REPORT_CANDIDATES else "complete",
                truncated=len(reports) >= _MAX_REPORT_CANDIDATES,
                reason="candidate_limit_reached" if len(reports) >= _MAX_REPORT_CANDIDATES else None,
            ),
        ], selected
    except Exception:
        return [BriefingCoverage(source="external_report", scope="Relevant non-dismissed external activity reports", status="failed", reason="external_reports_unavailable")], []


def _verified_action_inputs(
    *, observed: list[BriefingEvidence], partition: str
) -> list[BriefingCoverage]:
    if is_dev_mode() or partition != "production":
        return [BriefingCoverage(source="action", scope="Verified action outcomes", status="disabled", reason="action_service_partition_unavailable")]
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
            ))
        truncated = len(actions) >= 20
        return [
            BriefingCoverage(
                source="action",
                scope="Up to 20 verified action outcomes",
                status="partial" if truncated else "complete",
                truncated=truncated,
                reason="source_limit_reached" if truncated else None,
            )
        ]
    except Exception:
        return [BriefingCoverage(source="action", scope="Verified action outcomes", status="failed", reason="verified_action_state_unavailable")]


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
        observed_at=observed_at,
        effective_at=effective_at,
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


def _reminder_priority(item: dict[str, Any]) -> int:
    due = _parse_datetime(item.get("due"))
    if due is None:
        return 50
    now = datetime.now(timezone.utc)
    local_today = datetime.now().astimezone().date()
    due_local = due.astimezone().date() if due.tzinfo else due.date()
    if due < now:
        return 100
    if due_local == local_today:
        return 85
    return 60


def _calendar_priority(item: dict[str, Any]) -> int:
    starts = _parse_datetime(item.get("start"))
    if starts is None:
        return 55
    now = datetime.now(timezone.utc)
    local_today = datetime.now().astimezone().date()
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
    return "; ".join(parts)[:1200]


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
