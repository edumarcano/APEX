"""Bounded, read-only report projections for native Agent capabilities."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from core.activity.models import ActivityReport, is_valid_activity_client_id
from core.activity.service import ActivityService

AGENT_REPORT_MAX_OUTPUT_CHARS = 8_000
_CURSOR_MAX_CHARS = 2_048
_DEFAULT_LIMIT = 5
_MAX_LIMIT = 20
_EXCERPT_CHARS = 240
_VALID_PARTITIONS = {"production", "sandbox"}
_VALID_DISPOSITIONS = {"new", "reviewed", "dismissed"}


class AgentReportReadInputError(ValueError):
    """An invalid discovery/detail argument or continuation cursor."""


def _encoded_size(value: dict[str, Any]) -> int:
    # Match the capability registry's json.dumps(default=str) serialization.
    return len(json.dumps(value, default=str))


def _encode_cursor(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, *, expected: dict[str, Any], position_keys: set[str]) -> dict[str, Any]:
    if not isinstance(cursor, str) or not cursor or len(cursor) > _CURSOR_MAX_CHARS:
        raise AgentReportReadInputError("invalid_cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        payload = json.loads(decoded)
    except (UnicodeEncodeError, ValueError, json.JSONDecodeError):
        raise AgentReportReadInputError("invalid_cursor") from None
    if (
        not isinstance(payload, dict)
        or isinstance(payload.get("v"), bool)
        or not isinstance(payload.get("v"), int)
        or payload.get("v") != 1
    ):
        raise AgentReportReadInputError("invalid_cursor")
    if any(payload.get(key) != value for key, value in expected.items()):
        raise AgentReportReadInputError("invalid_cursor")
    if set(payload) != set(expected) | position_keys | {"v"}:
        raise AgentReportReadInputError("invalid_cursor")
    return payload


def _validate_partition(partition: str) -> None:
    if not isinstance(partition, str) or partition not in _VALID_PARTITIONS:
        raise AgentReportReadInputError("invalid_partition")


def _validate_search_inputs(
    *, partition: str, query: str | None, client_id: str | None,
    disposition: str | None, limit: int,
) -> tuple[str | None, int]:
    _validate_partition(partition)
    if query is not None and (not isinstance(query, str) or len(query) > 256):
        raise AgentReportReadInputError("invalid_query")
    normalized_query = query if query and query.strip() else None
    if client_id is not None and not is_valid_activity_client_id(client_id):
        raise AgentReportReadInputError("invalid_client_id")
    if disposition is not None and (
        not isinstance(disposition, str) or disposition not in _VALID_DISPOSITIONS
    ):
        raise AgentReportReadInputError("invalid_disposition")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIMIT:
        raise AgentReportReadInputError("invalid_limit")
    return normalized_query, limit


def _search_cursor(
    *, partition: str, query: str | None, client_id: str | None,
    disposition: str | None, limit: int, received_at: str, rowid: int,
) -> str:
    return _encode_cursor({
        "v": 1, "partition": partition, "query_sha256": hashlib.sha256((query or "").encode("utf-8")).hexdigest(),
        "client_id": client_id, "disposition": disposition, "limit": limit,
        "received_at": received_at, "rowid": rowid,
    })


def _receipt_projection(report: ActivityReport) -> dict[str, Any]:
    content = report.content
    occurred = content.occurred_at
    excerpt = content.outcome[:_EXCERPT_CHARS]
    if len(content.outcome) > _EXCERPT_CHARS:
        excerpt += "…"
    return {
        "report_id": str(report.id),
        "title": content.title[:160],
        "source_id": report.client_id,
        "source_label": report.client_display_name[:120],
        "source_label_is_caller_declared": True,
        "content_is_untrusted": True,
        "received_at": report.received_at,
        "occurred_at": occurred.isoformat() if isinstance(occurred, datetime) else None,
        "disposition": report.disposition,
        "outcome_excerpt": excerpt,
    }


def search_activity_reports(
    service: ActivityService, *, partition: str, query: str | None = None,
    client_id: str | None = None, disposition: str | None = None,
    limit: int = _DEFAULT_LIMIT, cursor: str | None = None,
) -> dict[str, Any]:
    """Find report receipts by title, outcome, subject, or project."""
    query, limit = _validate_search_inputs(
        partition=partition, query=query, client_id=client_id,
        disposition=disposition, limit=limit,
    )
    expected = {
        "partition": partition,
        "query_sha256": hashlib.sha256((query or "").encode("utf-8")).hexdigest(),
        "client_id": client_id,
        "disposition": disposition, "limit": limit,
    }
    after = None
    if cursor is not None:
        payload = _decode_cursor(
            cursor, expected=expected, position_keys={"received_at", "rowid"},
        )
        received_at = payload.get("received_at")
        rowid = payload.get("rowid")
        if (not isinstance(received_at, str) or not received_at or isinstance(rowid, bool)
            or not isinstance(rowid, int) or not 1 <= rowid <= 2**63 - 1):
            raise AgentReportReadInputError("invalid_cursor")
        after = (received_at, rowid)

    rows = service.search_agent_reports(
        partition=partition, query=query, client_id=client_id,
        disposition=disposition, limit=limit + 1, after=after,
    )
    candidates = rows[:limit]
    results: list[dict[str, Any]] = []
    next_cursor: str | None = None
    for index, (report, rowid) in enumerate(candidates):
        candidate_results = [*results, _receipt_projection(report)]
        has_more = index < len(rows) - 1
        candidate_cursor = (
            _search_cursor(
                partition=partition, query=query, client_id=client_id,
                disposition=disposition, limit=limit,
                received_at=report.received_at, rowid=rowid,
            ) if has_more else None
        )
        response = {"results": candidate_results, "next_cursor": candidate_cursor}
        if _encoded_size(response) > AGENT_REPORT_MAX_OUTPUT_CHARS:
            break
        results = candidate_results
        next_cursor = candidate_cursor

    # One receipt always fits under the fixed field bounds. This branch is a
    # defensive guard if those bounds change without updating this projection.
    if not results and rows:
        raise AgentReportReadInputError("result_too_large")
    return {"results": results, "next_cursor": next_cursor}


def _content_blocks(report: ActivityReport) -> list[dict[str, Any]]:
    content = report.content
    blocks: list[dict[str, Any]] = []

    def add(reference: str, kind: str, text: str | None, *, derivation: str | None = None) -> None:
        if not text:
            return
        block: dict[str, Any] = {"reference": reference, "kind": kind, "text": text}
        if derivation is not None:
            block["derivation"] = derivation
        blocks.append(block)

    add("/title", "title", content.title)
    add("/task_status", "task_status", content.task_status)
    add("/outcome", "outcome", content.outcome)
    for index, finding in enumerate(content.findings):
        add(f"/findings/{index}/title", "finding_title", finding.title)
        add(f"/findings/{index}", "finding", finding.text, derivation=finding.derivation)
    for index, question in enumerate(content.unresolved_questions):
        add(f"/unresolved_questions/{index}", "unresolved_question", question)
    add("/suggested_follow_up", "suggested_follow_up", content.suggested_follow_up)
    for index, subject in enumerate(content.subjects):
        add(f"/subjects/{index}", "subject", subject)
    for index, project in enumerate(content.projects):
        add(f"/projects/{index}", "project", project)
    for index, link in enumerate(content.evidence_links):
        add(f"/evidence_links/{index}", "evidence_link", link)
    for index, reference in enumerate(content.artifact_references):
        add(f"/artifact_references/{index}", "artifact_reference", reference)
    add("/native_task_url", "native_task_url", content.native_task_url)
    add("/markdown_body", "markdown_body", content.markdown_body)
    return blocks


def _detail_cursor(*, partition: str, report_id: str, block_index: int, offset: int) -> str:
    return _encode_cursor({
        "v": 1, "partition": partition, "report_id": report_id,
        "block_index": block_index, "offset": offset,
    })


def _detail_envelope(report: ActivityReport, content: list[dict[str, Any]], cursor: str | None) -> dict[str, Any]:
    occurred = report.content.occurred_at
    return {
        "report": {
            "report_id": str(report.id),
            "title": report.content.title[:120],
            "task_status": report.content.task_status[:80],
            "source_id": report.client_id,
            "source_label": report.client_display_name[:120],
            "source_label_is_caller_declared": True,
            "received_at": report.received_at,
            "occurred_at": occurred.isoformat() if occurred is not None else None,
            "disposition": report.disposition,
            "content_is_untrusted": True,
        },
        "content": content,
        "next_cursor": cursor,
    }


def get_activity_report(
    service: ActivityService, *, partition: str, report_id: str,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Read a report as provenance-labeled, bounded content blocks."""
    _validate_partition(partition)
    if not isinstance(report_id, str) or len(report_id) > 36:
        raise AgentReportReadInputError("invalid_report_id")
    try:
        parsed_id = UUID(report_id)
    except (ValueError, AttributeError, TypeError):
        raise AgentReportReadInputError("invalid_report_id") from None
    canonical_id = str(parsed_id)
    expected = {"partition": partition, "report_id": canonical_id}
    block_index, offset = 0, 0
    if cursor is not None:
        payload = _decode_cursor(
            cursor, expected=expected, position_keys={"block_index", "offset"},
        )
        block_index, offset = payload.get("block_index"), payload.get("offset")
        if (
            isinstance(block_index, bool) or not isinstance(block_index, int) or block_index < 0
            or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
        ):
            raise AgentReportReadInputError("invalid_cursor")

    report = service.get(parsed_id, partition=partition)
    blocks = _content_blocks(report)
    if block_index > len(blocks) or (block_index == len(blocks) and offset != 0):
        raise AgentReportReadInputError("invalid_cursor")
    if block_index < len(blocks) and offset > len(blocks[block_index]["text"]):
        raise AgentReportReadInputError("invalid_cursor")
    if block_index == len(blocks):
        offset = 0

    emitted: list[dict[str, Any]] = []
    current_index, current_offset = block_index, offset
    while current_index < len(blocks):
        source_block = blocks[current_index]
        remainder = source_block["text"][current_offset:]
        # First try the full remaining block; if it does not fit, find the
        # longest prefix that fits together with a cursor to the next character.
        full_content = [*emitted, {**source_block, "text": remainder}]
        full_next_index = current_index + 1
        full_cursor = (
            _detail_cursor(partition=partition, report_id=canonical_id, block_index=full_next_index, offset=0)
            if full_next_index < len(blocks) else None
        )
        if _encoded_size(_detail_envelope(report, full_content, full_cursor)) <= AGENT_REPORT_MAX_OUTPUT_CHARS:
            emitted = full_content
            current_index, current_offset = full_next_index, 0
            continue

        low, high = 0, len(remainder)
        best: tuple[list[dict[str, Any]], int, str] | None = None
        while low <= high:
            count = (low + high) // 2
            end_offset = current_offset + count
            next_index = current_index if end_offset < len(source_block["text"]) else current_index + 1
            next_offset = end_offset if next_index == current_index else 0
            candidate_cursor = _detail_cursor(
                partition=partition, report_id=canonical_id,
                block_index=next_index, offset=next_offset,
            )
            candidate_content = [*emitted, {**source_block, "text": remainder[:count]}]
            if _encoded_size(_detail_envelope(report, candidate_content, candidate_cursor)) <= AGENT_REPORT_MAX_OUTPUT_CHARS:
                best = (candidate_content, count, candidate_cursor)
                low = count + 1
            else:
                high = count - 1
        if best is None or best[1] == 0:
            if emitted:
                continuation = _detail_cursor(
                    partition=partition, report_id=canonical_id,
                    block_index=current_index, offset=current_offset,
                )
                return _detail_envelope(report, emitted, continuation)
            # A cursor-only response cannot advance. The fixed metadata leaves
            # ample room for at least one character; this catches contract drift.
            raise AgentReportReadInputError("result_too_large")
        emitted, count, continuation = best
        current_offset += count
        if current_offset >= len(source_block["text"]):
            current_index += 1
            current_offset = 0
        return _detail_envelope(report, emitted, continuation)

    response = _detail_envelope(report, emitted, None)
    if _encoded_size(response) > AGENT_REPORT_MAX_OUTPUT_CHARS:
        raise AgentReportReadInputError("result_too_large")
    return response
