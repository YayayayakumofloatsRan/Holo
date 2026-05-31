from __future__ import annotations

from kernel_v3.retrieval.contracts import (
    CitationItem,
    EvidenceEvaluationDecision,
    EvidenceItem,
    SearchGoal,
)
from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.source_policy import assess_evidence_source, source_authority_summary


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
        if research_profile is not None:
            assessments = [assess_evidence_source(item, profile=research_profile) for item in evidence]
            authority_summary = source_authority_summary(assessments)
            diagnostics["research_profile"] = research_profile.profile_id
            diagnostics["source_authority"] = authority_summary
            if not evidence:
                sufficient = False
                reason = "insufficient_evidence"
            elif research_profile.citations_required and not citations:
                sufficient = False
                reason = "citations_required_by_research_profile"
            elif not any(item.usable_as_primary for item in assessments):
                sufficient = False
                reason = "no_primary_source_for_research_profile"
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
