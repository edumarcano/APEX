"""Capability routing decision service."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from core.agent.capabilities import CapabilityDescriptor
from core.agent.local_commands import (
    estimate_schema_tokens,
    project_local_descriptor,
    resolve_local_command,
)
from core.agent.routing.families import CAPABILITY_FAMILIES, get_family
from core.agent.routing.models import (
    CapabilityRoutingDecision,
    CapabilityRoutingRequest,
    RankedCapabilityFamily,
)
from core.agent.routing.calibration import (
    DISABLED_CALIBRATOR,
    ScoreCalibrator,
    is_calibrated_low_confidence,
)
from core.agent.routing.ranker import RankerResult, RankerUnavailable, rank_capability_families
from core.agent.routing.rules import RuleMatch
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS, RoutingThresholds

_LOGGER = logging.getLogger(__name__)


def _is_routable(descriptor: CapabilityDescriptor) -> bool:
    return (
        descriptor.expose_to_agent
        and descriptor.risk == "read"
        and descriptor.routing_family is not None
        and get_family(descriptor.routing_family) is not None
        and descriptor.routing_family != "none"
    )


def _schema_budget_for_agent(agent_key: str, thresholds: RoutingThresholds) -> int:
    if agent_key == "sorex":
        return thresholds.max_schema_tokens_sorex
    if agent_key == "mus":
        return thresholds.max_schema_tokens_mus
    if agent_key == "apodemus":
        return thresholds.max_schema_tokens_apodemus
    return thresholds.max_schema_tokens_cloud


def _family_eligible(family_key: str, runtime: str) -> bool:
    family = get_family(family_key)
    if family is None:
        return False
    if runtime == "local":
        return family.local_auto_enabled
    return family.cloud_auto_enabled


def _order_descriptors_for_family(
    family_key: str,
    descriptors: tuple[CapabilityDescriptor, ...],
) -> list[CapabilityDescriptor]:
    family = get_family(family_key)
    priority = list(family.tool_priority) if family else []
    priority_set = set(priority)
    family_descriptors = [
        descriptor
        for descriptor in descriptors
        if descriptor.routing_family == family_key
    ]
    ordered: list[CapabilityDescriptor] = [
        descriptor
        for name in priority
        for descriptor in family_descriptors
        if descriptor.name == name
    ]
    for descriptor in sorted(family_descriptors, key=lambda item: item.name):
        if descriptor.name not in priority_set:
            ordered.append(descriptor)
    return ordered


def _select_families(
    rankings: list[RankedCapabilityFamily],
    thresholds: RoutingThresholds,
    runtime: str,
    *,
    rule_matches: Sequence[RuleMatch] | None = None,
    calibrator: ScoreCalibrator = DISABLED_CALIBRATOR,
) -> tuple[list[str], float | None, float | None, bool]:
    if not rankings:
        return [], None, None, True
    none_score = next(
        (item.score for item in rankings if item.key == "none"),
        0.0,
    )
    real = [item for item in rankings if item.key != "none" and _family_eligible(item.key, runtime)]
    if not real:
        return [], None, None, True
    top = real[0]
    margin = top.score - none_score
    if none_score >= top.score and none_score >= thresholds.minimum_top_score:
        return [], top.score, margin, False
    if top.score < thresholds.minimum_top_score:
        rule_only = [
            match.family
            for match in rule_matches or ()
            if match.family != "none"
            and match.confidence >= thresholds.rule_match_minimum_confidence
            and _family_eligible(match.family, runtime)
        ]
        if rule_only:
            return rule_only[: thresholds.max_selected_families], top.score, margin, False
        return [], top.score, margin, True
    if margin < thresholds.minimum_none_margin:
        return [], top.score, margin, True
    rule_supported_top = any(
        match.family == top.key
        and match.confidence >= thresholds.rule_match_minimum_confidence
        for match in rule_matches or ()
    )
    if (
        not rule_supported_top
        and is_calibrated_low_confidence(
            rankings,
            calibrator=calibrator,
            thresholds=thresholds,
        )
    ):
        return [], top.score, margin, True
    selected = [top.key]
    for candidate in real[1:]:
        if len(selected) >= thresholds.max_selected_families:
            break
        if candidate.score < thresholds.additional_family_minimum_score:
            continue
        if top.score - candidate.score > thresholds.additional_family_margin:
            continue
        selected.append(candidate.key)
    for match in rule_matches or ():
        if match.family == "none":
            continue
        if match.confidence < thresholds.rule_match_minimum_confidence:
            continue
        if not _family_eligible(match.family, runtime):
            continue
        if match.family in selected:
            continue
        if len(selected) >= thresholds.max_selected_families:
            break
        selected.append(match.family)
    return selected, top.score, margin, False


def _apply_schema_budget(
    selected_families: list[str],
    descriptors: list[CapabilityDescriptor],
    schema_budget: int,
    *,
    local_runtime: bool = False,
) -> tuple[list[CapabilityDescriptor], tuple[str, ...], tuple[str, ...]]:
    """Apply schema budget with atomic per-family inclusion.

    A family is offered only when every ordered descriptor fits. Partial fits are
    recorded as partial truncation and nothing from that family is offered.
    """
    offered: list[CapabilityDescriptor] = []
    fully_truncated: list[str] = []
    partially_truncated: list[str] = []
    used_tokens = 0
    for family_key in selected_families:
        family_descriptors = _order_descriptors_for_family(family_key, tuple(descriptors))
        if local_runtime:
            family_descriptors = [
                project_local_descriptor(family_key, descriptor)  # type: ignore[arg-type]
                for descriptor in family_descriptors
            ]
        if not family_descriptors:
            continue
        fitting: list[CapabilityDescriptor] = []
        family_tokens = 0
        for descriptor in family_descriptors:
            tokens = estimate_schema_tokens([descriptor])
            if used_tokens + family_tokens + tokens > schema_budget:
                break
            fitting.append(descriptor)
            family_tokens += tokens
        if len(fitting) < len(family_descriptors):
            if fitting:
                partially_truncated.append(family_key)
            else:
                fully_truncated.append(family_key)
            continue
        offered.extend(fitting)
        used_tokens += family_tokens
    return offered, tuple(fully_truncated), tuple(partially_truncated)


def _decision_from_capabilities(
    *,
    kind: str,
    capabilities: tuple[CapabilityDescriptor, ...],
    considered: tuple[CapabilityDescriptor, ...],
    selected_families: tuple[str, ...],
    top_score: float | None,
    score_margin: float | None,
    latency_ms: float,
    enforced: bool,
    model_key: str | None,
    fallback_reason: str | None,
    truncated_families: tuple[str, ...] = (),
    partially_truncated_families: tuple[str, ...] = (),
) -> CapabilityRoutingDecision:
    considered_tokens = estimate_schema_tokens(list(considered))
    offered_tokens = estimate_schema_tokens(list(capabilities))
    return CapabilityRoutingDecision(
        kind=kind,  # type: ignore[arg-type]
        offered_capabilities=capabilities,
        selected_families=selected_families,
        considered_tool_count=len(considered),
        offered_tool_count=len(capabilities),
        considered_schema_tokens=considered_tokens,
        offered_schema_tokens=offered_tokens,
        top_score=top_score,
        score_margin=score_margin,
        latency_ms=latency_ms,
        enforced=enforced,
        model_key=model_key,
        fallback_reason=fallback_reason,
        truncated_families=truncated_families,
        partially_truncated_families=partially_truncated_families,
    )


def resolve_capabilities(
    request: CapabilityRoutingRequest,
    *,
    thresholds: RoutingThresholds = DEFAULT_THRESHOLDS,
    calibrator: ScoreCalibrator = DISABLED_CALIBRATOR,
) -> CapabilityRoutingDecision:
    started = time.perf_counter()
    exposed = tuple(
        descriptor
        for descriptor in request.capabilities
        if descriptor.expose_to_agent
    )
    routable = tuple(descriptor for descriptor in exposed if _is_routable(descriptor))

    def elapsed() -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    if request.runtime == "local" and request.explicit_scope is not None:
        if request.explicit_scope == "none":
            return _decision_from_capabilities(
                kind="explicit_none",
                capabilities=(),
                considered=exposed,
                selected_families=(),
                top_score=None,
                score_margin=None,
                latency_ms=elapsed(),
                enforced=True,
                model_key=None,
                fallback_reason=None,
            )
        resolved = resolve_local_command(request.explicit_scope)
        return _decision_from_capabilities(
            kind="explicit",
            capabilities=resolved.descriptors,
            considered=exposed,
            selected_families=(request.explicit_scope,),
            top_score=None,
            score_margin=None,
            latency_ms=elapsed(),
            enforced=True,
            model_key=None,
            fallback_reason=None,
        )

    if request.mode == "disabled":
        if request.runtime == "cloud":
            offered = exposed
            kind = "disabled"
        else:
            offered = ()
            kind = "disabled"
        decision = _decision_from_capabilities(
            kind=kind,
            capabilities=offered,
            considered=exposed,
            selected_families=(),
            top_score=None,
            score_margin=None,
            latency_ms=elapsed(),
            enforced=False,
            model_key=None,
            fallback_reason=None,
        )
        _log_decision(request, decision)
        return decision

    rank_outcome = rank_capability_families(request.prompt, request.history)
    rankings: list[RankedCapabilityFamily] = []
    model_key: str | None = None
    rank_latency = 0.0
    rule_matches: tuple[RuleMatch, ...] = ()
    if isinstance(rank_outcome, RankerResult):
        rankings = list(rank_outcome.rankings)
        model_key = rank_outcome.model_key
        rank_latency = rank_outcome.latency_ms
        rule_matches = rank_outcome.rule_matches
    elif isinstance(rank_outcome, RankerUnavailable):
        if request.mode == "shadow":
            fallback_kind = "shadow"
            offered = exposed if request.runtime == "cloud" else ()
            decision = _decision_from_capabilities(
                kind=fallback_kind,
                capabilities=offered,
                considered=exposed,
                selected_families=(),
                top_score=None,
                score_margin=None,
                latency_ms=elapsed(),
                enforced=False,
                model_key=rank_outcome.model_key,
                fallback_reason=rank_outcome.reason,
            )
            _log_decision(request, decision)
            return decision
        fallback_kind = (
            "fallback_full" if request.runtime == "cloud" else "fallback_none"
        )
        offered = exposed if request.runtime == "cloud" else ()
        decision = _decision_from_capabilities(
            kind=fallback_kind,
            capabilities=offered,
            considered=exposed,
            selected_families=(),
            top_score=None,
            score_margin=None,
            latency_ms=elapsed(),
            enforced=False,
            model_key=rank_outcome.model_key,
            fallback_reason=rank_outcome.reason,
        )
        _log_decision(request, decision)
        return decision

    selected_families, top_score, score_margin, low_confidence = _select_families(
        rankings,
        thresholds,
        request.runtime,
        rule_matches=rule_matches,
        calibrator=calibrator,
    )

    if request.mode == "shadow":
        offered = exposed if request.runtime == "cloud" else ()
        decision = _decision_from_capabilities(
            kind="shadow",
            capabilities=offered,
            considered=exposed,
            selected_families=tuple(selected_families),
            top_score=top_score,
            score_margin=score_margin,
            latency_ms=max(elapsed(), rank_latency),
            enforced=False,
            model_key=model_key,
            fallback_reason=None,
        )
        _log_decision(request, decision)
        return decision

    if low_confidence or not selected_families:
        kind = "semantic_none" if not selected_families and not low_confidence else (
            "fallback_full" if request.runtime == "cloud" else "fallback_none"
        )
        if not selected_families and not low_confidence:
            offered = ()
            kind = "semantic_none"
        else:
            offered = exposed if request.runtime == "cloud" else ()
        decision = _decision_from_capabilities(
            kind=kind,  # type: ignore[arg-type]
            capabilities=offered,
            considered=exposed,
            selected_families=tuple(selected_families),
            top_score=top_score,
            score_margin=score_margin,
            latency_ms=max(elapsed(), rank_latency),
            enforced=kind.startswith("semantic"),
            model_key=model_key,
            fallback_reason="low_confidence" if low_confidence else None,
        )
        _log_decision(request, decision)
        return decision

    selected_descriptors = [
        descriptor
        for descriptor in routable
        if descriptor.routing_family in selected_families
    ]
    offered_list, fully_truncated, partially_truncated = _apply_schema_budget(
        selected_families,
        selected_descriptors,
        _schema_budget_for_agent(request.agent_key, thresholds),
        local_runtime=request.runtime == "local",
    )
    truncated = fully_truncated + partially_truncated
    if not offered_list and request.runtime == "local":
        decision = _decision_from_capabilities(
            kind="fallback_none",
            capabilities=(),
            considered=exposed,
            selected_families=tuple(selected_families),
            top_score=top_score,
            score_margin=score_margin,
            latency_ms=max(elapsed(), rank_latency),
            enforced=False,
            model_key=model_key,
            fallback_reason="no_available_tools",
        )
        _log_decision(request, decision)
        return decision

    decision = _decision_from_capabilities(
        kind="semantic",
        capabilities=tuple(offered_list),
        considered=exposed,
        selected_families=tuple(selected_families),
        top_score=top_score,
        score_margin=score_margin,
        latency_ms=max(elapsed(), rank_latency),
        enforced=True,
        model_key=model_key,
        fallback_reason=None,
        truncated_families=truncated,
        partially_truncated_families=partially_truncated,
    )
    _log_decision(request, decision)
    return decision


def _log_decision(
    request: CapabilityRoutingRequest,
    decision: CapabilityRoutingDecision,
) -> None:
    _LOGGER.info(
        "tool_routing mode=%s decision=%s runtime=%s agent=%s families=%s "
        "considered_tools=%s offered_tools=%s considered_tokens=%s "
        "offered_tokens=%s latency_ms=%s model_key=%s fallback=%s",
        request.mode,
        decision.kind,
        request.runtime,
        request.agent_key,
        len(decision.selected_families),
        decision.considered_tool_count,
        decision.offered_tool_count,
        decision.considered_schema_tokens,
        decision.offered_schema_tokens,
        decision.latency_ms,
        decision.model_key,
        decision.fallback_reason,
    )
