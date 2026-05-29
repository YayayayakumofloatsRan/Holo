from __future__ import annotations

from kernel_v3.retrieval.contracts import (
    CitationItem,
    EvidenceEvaluationDecision,
    EvidenceItem,
    SearchGoal,
)


class EvidenceEvaluator:
    def evaluate(
        self,
        *,
        goal: SearchGoal,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
    ) -> EvidenceEvaluationDecision:
        sufficient = bool(evidence and citations)
        reason = "evidence_with_citations" if sufficient else "insufficient_evidence"
        return EvidenceEvaluationDecision(
            decision_id=f"eval-{goal.goal_id}",
            goal_id=goal.goal_id,
            status="sufficient" if sufficient else "insufficient_evidence",
            sufficient=sufficient,
            reason=reason,
            evidence_count=len(evidence),
            citation_count=len(citations),
            diagnostics={
                "query": goal.query,
                "max_fetches": goal.max_fetches,
                "max_spans_per_document": goal.max_spans_per_document,
            },
        )
