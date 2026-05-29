from __future__ import annotations

from kernel_v3.retrieval.contracts import ExtractedSpan, FetchedDocument, SearchGoal


def extract_spans(
    *,
    goal: SearchGoal,
    document: FetchedDocument,
    body: str,
) -> list[ExtractedSpan]:
    if not body:
        return []
    terms = _terms(goal.query)
    if not terms:
        return []
    spans: list[ExtractedSpan] = []
    lower = body.lower()
    for term in terms:
        start = lower.find(term)
        if start < 0:
            continue
        window_start = max(0, start - 80)
        window_end = min(len(body), start + len(term) + 120)
        text = _normalize_span(body[window_start:window_end])
        if not text:
            continue
        spans.append(
            ExtractedSpan(
                span_id=f"span-{document.document_id}-{len(spans) + 1}",
                goal_id=goal.goal_id,
                document_id=document.document_id,
                source_id=document.source_id,
                text=text,
                start_offset=window_start,
                end_offset=window_end,
                score=1.0,
                metadata={"matched_term": term},
            )
        )
        if len(spans) >= goal.max_spans_per_document:
            break
    return spans


def _terms(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in text.lower().replace("-", " ").split():
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _normalize_span(text: str) -> str:
    return " ".join(text.split())
