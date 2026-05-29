from __future__ import annotations

from kernel_v3.retrieval.contracts import RankedSource, SearchGoal, SearchSource


def plan_queries(goal: SearchGoal) -> list[str]:
    query = goal.query.strip()
    if not query:
        return []
    return [query][: max(0, goal.max_queries)]


def rank_sources(goal: SearchGoal, sources: list[SearchSource]) -> list[RankedSource]:
    terms = _terms(goal.query)
    ranked: list[RankedSource] = []
    for source in sources:
        haystack = f"{source.title} {source.snippet}".lower()
        hits = sum(1 for term in terms if term in haystack)
        score = hits / max(1, len(terms))
        ranked.append(
            RankedSource(
                source_id=source.source_id,
                uri=source.uri,
                title=source.title,
                snippet=source.snippet,
                provider=source.provider,
                score=score,
                rank=0,
                reasons=["query_term_match"] if hits else ["provider_result"],
                metadata=source.metadata,
            )
        )
    ordered = sorted(ranked, key=lambda item: (-item.score, item.source_id))
    return [
        RankedSource(
            source_id=item.source_id,
            uri=item.uri,
            title=item.title,
            snippet=item.snippet,
            provider=item.provider,
            score=item.score,
            rank=index,
            reasons=item.reasons,
            metadata=item.metadata,
        )
        for index, item in enumerate(ordered, start=1)
    ]


def _terms(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in text.lower().replace("-", " ").split():
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms
