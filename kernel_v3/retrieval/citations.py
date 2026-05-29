from __future__ import annotations

from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, ExtractedSpan


def citation_from_evidence(evidence: EvidenceItem, span: ExtractedSpan) -> CitationItem:
    return CitationItem(
        citation_id=f"cite-{evidence.evidence_id}",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote=evidence.text,
        span_start=span.start_offset,
        span_end=span.end_offset,
        metadata={
            "payload_hash": evidence.payload_hash,
            "source_id": evidence.source_id,
            "span_id": span.span_id,
        },
    )
