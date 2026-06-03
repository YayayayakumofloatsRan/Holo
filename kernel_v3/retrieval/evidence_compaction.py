from __future__ import annotations

import hashlib
from dataclasses import dataclass

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.profile_policy import (
    evidence_compaction_policy,
    profile_evidence_facets,
)
from kernel_v3.retrieval.contracts import EvidenceItem, ExtractedSpan, SearchGoal


@dataclass(frozen=True, kw_only=True)
class EvidenceCandidate:
    evidence: EvidenceItem
    span: ExtractedSpan


def compact_evidence_candidates(
    candidates: list[EvidenceCandidate],
    *,
    goal: SearchGoal,
    research_profile: ResearchProfile | None,
    limit: int,
) -> tuple[list[EvidenceCandidate], list[JsonObject], JsonObject]:
    if not candidates or limit <= 0:
        return [], [], {"strategy": "none", "candidate_count": len(candidates), "selected_count": 0}
    policy = evidence_compaction_policy(research_profile)
    has_profile_compaction = bool(policy)
    effective_limit = _positive_int(policy.get("max_items"), default=limit)
    effective_limit = max(1, min(limit, effective_limit))
    per_source_limit = _positive_int(policy.get("per_source_limit"), default=effective_limit)
    unique_candidates = _dedupe_candidates(candidates)
    required_facets = profile_evidence_facets(goal=goal, research_profile=research_profile)
    ordered = sorted(unique_candidates, key=_candidate_sort_key)

    selected: list[EvidenceCandidate] = []
    selected_ids: set[str] = set()
    source_counts: dict[str, int] = {}
    if bool(policy.get("prefer_facet_coverage", True)) and required_facets:
        for facet in required_facets:
            candidate = _best_candidate_for_facet(
                ordered,
                facet=facet,
                selected_ids=selected_ids,
                source_counts=source_counts,
                per_source_limit=per_source_limit,
            )
            if candidate is not None:
                _select_candidate(candidate, selected, selected_ids, source_counts)
            if len(selected) >= effective_limit:
                break

    for candidate in ordered:
        if len(selected) >= effective_limit:
            break
        if candidate.evidence.evidence_id in selected_ids:
            continue
        if source_counts.get(candidate.evidence.source_id, 0) >= per_source_limit:
            continue
        _select_candidate(candidate, selected, selected_ids, source_counts)

    rejected = [
        _compaction_rejection(
            candidate,
            reason="evidence_compacted_out" if has_profile_compaction else "evidence_item_limit_reached",
        )
        for candidate in unique_candidates
        if candidate.evidence.evidence_id not in selected_ids
    ]
    diagnostics = {
        "strategy": str(policy.get("strategy_id") or "evidence_item_limit"),
        "candidate_count": len(candidates),
        "deduped_candidate_count": len(unique_candidates),
        "selected_count": len(selected),
        "compacted_out_count": len(rejected),
        "limit": effective_limit,
        "per_source_limit": per_source_limit,
        "required_facets": required_facets,
        "selected_facets": _selected_facets(selected),
    }
    return selected, rejected, diagnostics


def _dedupe_candidates(candidates: list[EvidenceCandidate]) -> list[EvidenceCandidate]:
    best_by_hash: dict[str, EvidenceCandidate] = {}
    for candidate in candidates:
        key = _text_hash(candidate.evidence.text)
        existing = best_by_hash.get(key)
        if existing is None or _candidate_sort_key(candidate) < _candidate_sort_key(existing):
            best_by_hash[key] = candidate
    return list(best_by_hash.values())


def _best_candidate_for_facet(
    candidates: list[EvidenceCandidate],
    *,
    facet: str,
    selected_ids: set[str],
    source_counts: dict[str, int],
    per_source_limit: int,
) -> EvidenceCandidate | None:
    for candidate in candidates:
        if candidate.evidence.evidence_id in selected_ids:
            continue
        if source_counts.get(candidate.evidence.source_id, 0) >= per_source_limit:
            continue
        if facet in _candidate_facets(candidate):
            return candidate
    return None


def _select_candidate(
    candidate: EvidenceCandidate,
    selected: list[EvidenceCandidate],
    selected_ids: set[str],
    source_counts: dict[str, int],
) -> None:
    selected.append(candidate)
    selected_ids.add(candidate.evidence.evidence_id)
    source_counts[candidate.evidence.source_id] = source_counts.get(candidate.evidence.source_id, 0) + 1


def _candidate_sort_key(candidate: EvidenceCandidate) -> tuple[float, float, float, int, str]:
    evidence = candidate.evidence
    qualification = evidence.diagnostics.get("qualification")
    facets = _candidate_facets(candidate)
    authority = _authority_score(evidence)
    numeric_bonus = 0.2 if isinstance(qualification, dict) and qualification.get("profile_numeric_fact_present") else 0.0
    return (
        -authority,
        -(float(evidence.score) + numeric_bonus),
        -float(len(facets)),
        len(evidence.text),
        evidence.evidence_id,
    )


def _candidate_facets(candidate: EvidenceCandidate) -> list[str]:
    qualification = candidate.evidence.diagnostics.get("qualification")
    if not isinstance(qualification, dict):
        return []
    raw = qualification.get("covered_profile_facets")
    if not isinstance(raw, list):
        raw = qualification.get("covered_finance_facets")
    return [item for item in (str(value).strip() for value in raw or [] if isinstance(value, str)) if item]


def _authority_score(evidence: EvidenceItem) -> float:
    assessment = evidence.diagnostics.get("source_assessment")
    if not isinstance(assessment, dict):
        return 0.0
    value = assessment.get("authority_score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _selected_facets(selected: list[EvidenceCandidate]) -> list[str]:
    facets: list[str] = []
    seen: set[str] = set()
    for candidate in selected:
        for facet in _candidate_facets(candidate):
            if facet in seen:
                continue
            seen.add(facet)
            facets.append(facet)
    return facets


def _compaction_rejection(candidate: EvidenceCandidate, *, reason: str) -> JsonObject:
    return {
        "evidence_id": candidate.evidence.evidence_id,
        "source_id": candidate.evidence.source_id,
        "document_id": candidate.evidence.document_id,
        "uri": candidate.evidence.uri,
        "title": candidate.evidence.title,
        "reason": reason,
        "covered_profile_facets": _candidate_facets(candidate),
        "preview": candidate.evidence.text[:160],
    }


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()
