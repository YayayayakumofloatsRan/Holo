from __future__ import annotations

from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.profile_policy import (
    QUERY_FACET_ALIASES,
    QUERY_FACET_TRIGGERS,
    assess_profile_evidence_coverage,
    assess_query_facet_coverage,
    evidence_source_kind,
    profile_evidence_facets,
    profile_is_discovery_goal,
    qualify_profile_evidence_candidate,
    query_facets,
    resolve_goal_research_profile,
)
from kernel_v3.research.profiles import (
    FINANCE_DISCOVERY_SOURCE_KINDS,
    FINANCE_FUNDAMENTAL_FACET_ALIASES,
    FINANCE_FUNDAMENTAL_FACET_TRIGGERS,
    FINANCE_FUNDAMENTAL_TASK_KINDS,
    FINANCE_FUNDAMENTALS_PROFILE_ID,
    FINANCE_NUMERIC_FACT_FACETS,
)
from kernel_v3.research.source_policy import assess_evidence_source, source_authority_summary
from kernel_v3.retrieval.contracts import (
    CitationItem,
    EvidenceEvaluationDecision,
    EvidenceItem,
    SearchGoal,
)
from kernel_v3.retrieval.targeting import assess_target_entity_coverage, target_entity_diagnostics


def qualify_evidence_candidate(
    *,
    goal: SearchGoal,
    evidence: EvidenceItem,
    research_profile: ResearchProfile | None = None,
) -> dict[str, object]:
    result = dict(
        qualify_profile_evidence_candidate(
            goal=goal,
            evidence=evidence,
            research_profile=research_profile,
        )
    )
    target_diagnostics = target_entity_diagnostics(goal.query, [evidence.title, evidence.uri, evidence.text])
    if bool(target_diagnostics.get("target_entity_required")):
        result["target_entity"] = target_diagnostics
        result["required_target_phrases"] = target_diagnostics.get("required_target_phrases", [])
        result["matched_target_phrases"] = target_diagnostics.get("matched_target_phrases", [])
        result["missing_target_phrases"] = target_diagnostics.get("missing_target_phrases", [])
        if not bool(target_diagnostics.get("target_entity_satisfied")):
            result["accepted"] = False
            result["reason"] = "target_entity_mismatch"
    if _is_finance_profile(goal=goal, research_profile=research_profile):
        _add_finance_compatibility_fields(result)
    return result


class EvidenceEvaluator:
    def evaluate(
        self,
        *,
        goal: SearchGoal,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
        research_profile: ResearchProfile | None = None,
    ) -> EvidenceEvaluationDecision:
        diagnostics = {
            "query": goal.query,
            "max_fetches": goal.max_fetches,
            "max_spans_per_document": goal.max_spans_per_document,
        }
        sufficient = bool(evidence and citations)
        reason = "evidence_with_citations" if sufficient else "insufficient_evidence"

        facet_diagnostics = assess_query_facet_coverage(goal=goal, evidence=evidence)
        diagnostics.update(facet_diagnostics)
        if sufficient and facet_diagnostics["missing_query_facets"]:
            sufficient = False
            reason = "query_facets_missing"

        target_diagnostics = assess_target_entity_coverage(
            goal.query,
            [f"{item.title} {item.uri} {item.text}" for item in evidence],
        )
        diagnostics.update(target_diagnostics)
        if (
            sufficient
            and target_diagnostics["target_entity_required"]
            and target_diagnostics["missing_target_phrases"]
        ):
            sufficient = False
            reason = "target_entity_mismatch"

        profile_diagnostics = assess_profile_evidence_coverage(
            goal=goal,
            evidence=evidence,
            research_profile=research_profile,
        )
        diagnostics.update(profile_diagnostics)
        if _is_finance_profile(goal=goal, research_profile=research_profile):
            diagnostics.update(_finance_coverage_compatibility(profile_diagnostics))
        if sufficient and profile_diagnostics["profile_evidence_required"] and profile_diagnostics["missing_profile_facets"]:
            sufficient = False
            reason = (
                "finance_fundamental_facets_missing"
                if _is_finance_profile(goal=goal, research_profile=research_profile)
                else "profile_evidence_facets_missing"
            )

        resolved_profile = resolve_goal_research_profile(goal, research_profile)
        if resolved_profile is not None:
            assessments = [assess_evidence_source(item, profile=resolved_profile) for item in evidence]
            authority_summary = source_authority_summary(assessments)
            diagnostics["research_profile"] = resolved_profile.profile_id
            diagnostics["source_authority"] = authority_summary
            authority_requirement = _source_authority_requirement(goal)
            diagnostics["source_authority_requirement"] = authority_requirement
            if not evidence:
                sufficient = False
                reason = "insufficient_evidence"
            elif resolved_profile.citations_required and not citations:
                sufficient = False
                reason = "citations_required_by_research_profile"
            elif not _authority_satisfies(assessments, authority_requirement):
                sufficient = False
                reason = (
                    "no_primary_source_for_research_profile"
                    if authority_requirement == "primary"
                    else "no_required_authority_source_for_research_profile"
                )

        return EvidenceEvaluationDecision(
            decision_id=f"eval-{goal.goal_id}",
            goal_id=goal.goal_id,
            status="sufficient" if sufficient else "insufficient_evidence",
            sufficient=sufficient,
            reason=reason,
            evidence_count=len(evidence),
            citation_count=len(citations),
            diagnostics=diagnostics,
        )


def assess_finance_fundamental_coverage(
    *,
    goal: SearchGoal,
    evidence: list[EvidenceItem],
    research_profile: ResearchProfile | None = None,
) -> dict[str, object]:
    return _finance_coverage_compatibility(
        assess_profile_evidence_coverage(
            goal=goal,
            evidence=evidence,
            research_profile=research_profile,
        )
    )


def finance_fundamental_facets(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> list[str]:
    if not _is_finance_fundamental_goal(goal=goal, research_profile=research_profile):
        return []
    return profile_evidence_facets(goal=goal, research_profile=research_profile)


def is_discovery_goal(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
    return profile_is_discovery_goal(goal=goal, research_profile=research_profile)


def _finance_coverage_compatibility(profile_diagnostics: dict[str, object]) -> dict[str, object]:
    missing = _finance_missing_names(_string_list(profile_diagnostics.get("missing_profile_facets")))
    return {
        "finance_fundamental_required": bool(profile_diagnostics.get("profile_evidence_required")),
        "finance_fundamental_facets": _string_list(profile_diagnostics.get("profile_evidence_facets")),
        "covered_finance_facets": _string_list(profile_diagnostics.get("covered_profile_facets")),
        "missing_finance_facets": missing,
        "finance_numeric_fact_required": bool(profile_diagnostics.get("profile_numeric_fact_required")),
        "finance_numeric_fact_present": bool(profile_diagnostics.get("profile_numeric_fact_present")),
        "finance_facet_coverage": profile_diagnostics.get("profile_facet_coverage", 1.0),
        "finance_facet_matches": profile_diagnostics.get("profile_facet_matches", {}),
    }


def _add_finance_compatibility_fields(result: dict[str, object]) -> None:
    if result.get("reason") == "discovery_metadata_not_final_evidence":
        result["reason"] = "finance_discovery_metadata_not_final_evidence"
    elif result.get("reason") == "qualified_profile_evidence":
        result["reason"] = "qualified_finance_evidence"
    elif result.get("reason") == "missing_profile_fact_in_span":
        result["reason"] = "missing_finance_fact_in_span"
    elif result.get("reason") == "no_required_profile_facets":
        result["reason"] = "not_finance_fundamental_goal"
    result["covered_finance_facets"] = _string_list(result.get("covered_profile_facets"))
    result["missing_finance_facets"] = _finance_missing_names(_string_list(result.get("missing_profile_facets")))
    result["finance_numeric_fact_required"] = bool(result.get("profile_numeric_fact_required"))
    result["finance_numeric_fact_present"] = bool(result.get("profile_numeric_fact_present"))


def _finance_missing_names(values: list[str]) -> list[str]:
    return ["numeric_financial_fact" if value == "numeric_profile_fact" else value for value in values]


def _is_finance_fundamental_goal(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
    if not _is_finance_profile(goal=goal, research_profile=research_profile):
        return False
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    task_kind = str(metadata.get("research_task_kind") or metadata.get("task_kind") or "").strip().lower()
    if task_kind in set(FINANCE_FUNDAMENTAL_TASK_KINDS):
        return True
    if task_kind in {"market_data", "market_news", "macro_data", "competitive_landscape"}:
        return False
    return bool(profile_evidence_facets(goal=goal, research_profile=research_profile))


def _is_sec_discovery_query(query: str) -> bool:
    goal = SearchGoal(
        goal_id="compat-sec-discovery",
        query=query,
        metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )
    return profile_is_discovery_goal(goal=goal)


def _is_finance_profile(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
    resolved = resolve_goal_research_profile(goal, research_profile)
    return resolved is not None and resolved.profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID


def _evidence_source_kind(evidence: EvidenceItem) -> str:
    return evidence_source_kind(evidence)


def _source_authority_requirement(goal: SearchGoal) -> str:
    value = goal.metadata.get("source_authority_requirement")
    if not isinstance(value, str):
        value = goal.metadata.get("authority_requirement")
    normalized = str(value or "primary").strip().lower()
    if normalized in {"secondary_or_better", "secondary_allowed", "secondary"}:
        return "secondary_or_better"
    if normalized in {"any", "any_citable"}:
        return "any_citable"
    return "primary"


def _authority_satisfies(assessments: object, requirement: str) -> bool:
    items = list(assessments) if isinstance(assessments, list) else []
    if requirement == "any_citable":
        return bool(items)
    if requirement == "secondary_or_better":
        return any(item.usable_as_primary or item.authority_level == "secondary" for item in items)
    return any(item.usable_as_primary for item in items)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value if isinstance(raw, str)) if item]
