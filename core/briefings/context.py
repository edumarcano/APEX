"""Bounded, trust-labeled saved evidence for briefing conversation follow-up."""

from __future__ import annotations

import json
import re
from dataclasses import replace

from core.briefings.models import BriefingSessionRecord
from core.context.assembly import ContextAssembler, ContextBundle, ContextPolicy, ContextReference

MAX_FOLLOWUP_EVIDENCE_TOKENS = 500
MAX_FOLLOWUP_EVIDENCE_ITEMS = 4
MAX_FOLLOWUP_EXCERPT_CHARS = 600

_PERSONAL_SOURCES = {"accepted_context", "pending_review", "external_report", "action"}
_WORD = re.compile(r"[a-z0-9]{4,}")


def saved_briefing_followup_context(
    record: BriefingSessionRecord | None, *, prompt: str, policy: ContextPolicy
) -> ContextBundle:
    """Select only evidence cited by a completed briefing artifact in this partition."""
    if (
        record is None
        or record.partition != policy.partition
        or record.request.profile_id not in {"daily", "catch_up", "deep"}
        or record.run_status != "completed"
        or record.artifact is None
    ):
        return ContextBundle()

    evidence_by_id = {evidence.id: evidence for evidence in record.evidence}
    terms = set(_WORD.findall(prompt.casefold()))
    ranked: list[tuple[int, int, str, ContextReference]] = []
    seen = set()
    excerpt_clipped = False
    for section in record.artifact.sections:
        for item in section.items:
            for evidence_id in item.evidence_ids:
                if evidence_id in seen:
                    continue
                seen.add(evidence_id)
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None or not evidence.available or not evidence.content:
                    continue
                if not policy.permits_retrieval and (
                    evidence.source in _PERSONAL_SOURCES or evidence.trust != "observed"
                ):
                    continue
                excerpt = evidence.content[:MAX_FOLLOWUP_EXCERPT_CHARS]
                clipped = len(evidence.content) > MAX_FOLLOWUP_EXCERPT_CHARS
                excerpt_clipped = excerpt_clipped or clipped
                payload = {
                    "briefing_item": item.title,
                    "category": item.category,
                    "evidence_id": str(evidence.id),
                    "source": evidence.source,
                    "trust": evidence.trust,
                    "snapshot_at": record.artifact.created_at.isoformat(),
                    "captured_at": evidence.observed_at.isoformat() if evidence.observed_at else None,
                    "comparison_role": evidence.comparison_role,
                    "change_kind": evidence.change_kind,
                    "comparison_pair_id": str(evidence.comparison_pair_id) if evidence.comparison_pair_id else None,
                    "effective_at": evidence.effective_at.isoformat() if evidence.effective_at else None,
                    "content_excerpt": excerpt,
                    "excerpt_truncated": clipped,
                }
                serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                # Source text and model-written titles must not close the context boundary.
                serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e")
                history_label = "prior comparison snapshot" if evidence.comparison_role == "historical" else "saved source snapshot"
                text = f"Saved briefing evidence ({history_label}, not a fresh read): {serialized}"
                reference = ContextReference(
                    namespace="briefing_session",
                    source_type=evidence.source,
                    source_id=str(evidence.id),
                    locator=f"briefing/session/{record.id}/evidence/{evidence.id}",
                    status=evidence.trust,
                )
                searchable = f"{item.title} {item.body} {evidence.content}".casefold()
                score = len(terms.intersection(_WORD.findall(searchable)))
                ranked.append((score, len(ranked), text, reference))

    ranked.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    candidates = [(text, reference) for _, _, text, reference in ranked[:MAX_FOLLOWUP_EVIDENCE_ITEMS]]
    bounded = ContextAssembler._bounded(
        candidates,
        max_tokens=min(MAX_FOLLOWUP_EVIDENCE_TOKENS, max(0, policy.max_retrieved_tokens)),
    )
    return replace(bounded, truncated=True) if excerpt_clipped else bounded


def combine_context_bundles(first: ContextBundle, second: ContextBundle) -> ContextBundle:
    return ContextBundle(
        rendered="\n\n".join(part for part in (first.rendered, second.rendered) if part),
        references=first.references + second.references,
        estimated_tokens=first.estimated_tokens + second.estimated_tokens,
        truncated=first.truncated or second.truncated,
    )


# Retained for callers outside the shared briefing router during migration.
saved_daily_followup_context = saved_briefing_followup_context
