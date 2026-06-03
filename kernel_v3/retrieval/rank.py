from __future__ import annotations

from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.source_policy import assess_search_source
from kernel_v3.retrieval.contracts import RankedSource, SearchGoal, SearchSource


QUERY_TEXT_LIMIT = 500


def plan_queries(goal: SearchGoal, *, research_profile: ResearchProfile | None = None) -> list[str]:
    query = goal.query.strip()
    if not query:
        return []
    explicit = _metadata_string_list(goal.metadata.get("queries"))
    if explicit:
        return _bounded_unique_queries(explicit, limit=goal.max_queries)
    templates = _metadata_string_list(goal.metadata.get("query_templates"))
    if not templates and research_profile is not None:
        templates = _profile_query_templates(research_profile)
    if not templates:
        return _bounded_unique_queries([query], limit=goal.max_queries)
    return _bounded_unique_queries(
        [_render_query_template(template, query=query) for template in templates],
        limit=goal.max_queries,
    )


def rank_sources(
    goal: SearchGoal,
    sources: list[SearchSource],
    *,
    research_profile: ResearchProfile | None = None,
) -> list[RankedSource]:
    terms = _terms(goal.query)
    ranked: list[RankedSource] = []
    for source in sources:
        haystack = _source_haystack(source)
        hits = sum(1 for term in terms if term in haystack)
        term_score = hits / max(1, len(terms))
        reasons = ["query_term_match"] if hits else ["provider_result"]
        metadata = dict(source.metadata)
        source_kind_adjustment = _source_kind_score_adjustment(metadata)
        source_family_adjustment = _source_family_preference_adjustment(goal.metadata, metadata)
        if research_profile is not None:
            assessment = assess_search_source(source, profile=research_profile)
            score = (
                (term_score * 0.2)
                + (assessment.authority_score * 0.8)
                + source_kind_adjustment
                + source_family_adjustment
            )
            metadata["source_assessment"] = assessment.to_dict()
            reasons.append(f"authority:{assessment.authority_level}")
        else:
            score = term_score + source_kind_adjustment + source_family_adjustment
        ranked.append(
            RankedSource(
                source_id=source.source_id,
                uri=source.uri,
                title=source.title,
                snippet=source.snippet,
                provider=source.provider,
                score=score,
                rank=0,
                reasons=reasons,
                metadata=metadata,
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
        for candidate in [term, *_term_aliases(term)]:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            terms.append(candidate)
    return terms


def _source_haystack(source: SearchSource) -> str:
    uri_text = source.uri.replace("_", " ").replace("-", " ").replace("/", " ")
    return f"{source.title} {source.snippet} {uri_text}".lower()


def _source_kind_score_adjustment(metadata: dict[str, object]) -> float:
    source_kind = metadata.get("source_kind")
    if source_kind == "sec_primary_filing_document":
        return 0.55
    if source_kind == "sec_complete_submission_text":
        return 0.52
    if source_kind == "sec_submissions_json":
        return 0.48
    if source_kind == "sec_companyfacts_json":
        return 0.46
    if source_kind in {"sec_ticker_cik_directory", "sec_edgar_search", "sec_filing_directory"}:
        return -0.32
    if source_kind == "sec_edgar_browse":
        return -0.12
    if source_kind == "crawl_seed":
        return -0.08
    if source_kind in {"crawl_discovered", "crawl_sitemap", "direct_url"}:
        return 0.03
    return 0.0


def _source_family_preference_adjustment(goal_metadata: dict[str, object], source_metadata: dict[str, object]) -> float:
    source_family = source_metadata.get("source_family")
    if not isinstance(source_family, str) or not source_family:
        return 0.0
    preferred = _preferred_source_families(goal_metadata)
    if not preferred:
        return 0.0
    if source_family in preferred:
        return 0.18
    return -0.08


def _preferred_source_families(metadata: dict[str, object]) -> set[str]:
    raw = metadata.get("preferred_source_families")
    if isinstance(raw, list):
        return {item for item in raw if isinstance(item, str) and item}
    if metadata.get("research_task_kind") == "macro_data":
        return {"government_statistic", "central_bank_statistic", "treasury_data"}
    return set()


def _term_aliases(term: str) -> list[str]:
    aliases: list[str] = []
    if "文档" in term:
        aliases.extend(["docs", "documentation"])
    if "模型" in term:
        aliases.extend(["model", "models", "pricing"])
    if "鉴权" in term or "认证" in term or "授权" in term:
        aliases.extend(["auth", "authentication", "authorization", "token", "key"])
    if "接口" in term:
        aliases.append("api")
    if "价格" in term or "定价" in term:
        aliases.extend(["price", "pricing"])
    return aliases


def _profile_query_templates(profile: ResearchProfile) -> list[str]:
    strategy = profile.metadata.get("query_strategy")
    if not isinstance(strategy, dict):
        return []
    return _metadata_string_list(strategy.get("templates"))


def _metadata_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value if isinstance(raw, str)) if item]


def _render_query_template(template: str, *, query: str) -> str:
    if "{query}" in template:
        return template.replace("{query}", query)
    return f"{query} {template}"


def _bounded_unique_queries(queries: list[str], *, limit: int) -> list[str]:
    bounded: list[str] = []
    seen: set[str] = set()
    for raw in queries:
        query = _bounded_query_text(raw)
        key = query.lower()
        if not query or key in seen:
            continue
        seen.add(key)
        bounded.append(query)
        if len(bounded) >= max(0, int(limit)):
            break
    return bounded


def _bounded_query_text(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= QUERY_TEXT_LIMIT:
        return normalized
    return normalized[: max(0, QUERY_TEXT_LIMIT - 3)] + "..."
