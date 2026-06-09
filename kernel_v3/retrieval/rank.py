from __future__ import annotations

from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.source_policy import assess_search_source
from kernel_v3.retrieval.contracts import RankedSource, SearchGoal, SearchSource
from kernel_v3.retrieval.query_campaign import build_query_campaign
from kernel_v3.retrieval.targeting import target_entity_diagnostics


def plan_queries(goal: SearchGoal, *, research_profile: ResearchProfile | None = None) -> list[str]:
    return build_query_campaign(goal, research_profile=research_profile).queries


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
        source_kind_adjustment = _source_kind_score_adjustment(metadata, query=goal.query)
        source_family_adjustment = _source_family_preference_adjustment(goal.metadata, metadata)
        target_diagnostics = target_entity_diagnostics(goal.query, [source.title, source.snippet, source.uri])
        target_adjustment = _target_entity_score_adjustment(target_diagnostics)
        if bool(target_diagnostics.get("target_entity_required")):
            metadata["target_entity"] = target_diagnostics
            reasons.append("target_entity_match" if bool(target_diagnostics.get("target_entity_satisfied")) else "target_entity_mismatch")
        if research_profile is not None:
            assessment = assess_search_source(source, profile=research_profile)
            score = (
                (term_score * 0.2)
                + (assessment.authority_score * 0.8)
                + source_kind_adjustment
                + source_family_adjustment
                + target_adjustment
            )
            metadata["source_assessment"] = assessment.to_dict()
            reasons.append(f"authority:{assessment.authority_level}")
        else:
            score = term_score + source_kind_adjustment + source_family_adjustment + target_adjustment
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


def _source_kind_score_adjustment(metadata: dict[str, object], *, query: str = "") -> float:
    source_kind = metadata.get("source_kind")
    query_text = query.lower()
    sec_directory_intent = _sec_directory_lookup_intent(query_text)
    submissions_intent = any(
        marker in query_text
        for marker in (
            "submissions",
            "accession",
            "primarydocument",
            "primary document",
            "filing metadata",
            "filing chronology",
        )
    )
    if source_kind == "sec_primary_filing_document":
        return 0.55
    if source_kind == "sec_complete_submission_text":
        return 0.52
    if source_kind == "sec_companyfacts_json":
        if submissions_intent:
            return 0.38
        return 0.50
    if source_kind == "sec_submissions_json":
        if submissions_intent:
            return 0.51
        return 0.42
    if source_kind == "sec_ticker_cik_directory":
        return 0.62 if sec_directory_intent else -0.32
    if source_kind in {"sec_edgar_search", "sec_filing_directory"}:
        return -0.32
    if source_kind == "sec_edgar_browse":
        return -0.12
    if source_kind in {"academic_source_directory", "scholarly_search", "scholarly_index_search"}:
        return -0.48
    if metadata.get("discovery_expanded") is True and source_kind in {
        "scholarly_preprint",
        "scholarly_publisher_metadata",
        "scholarly_index_metadata",
    }:
        return -0.08
    if source_kind == "scholarly_preprint":
        return 0.32
    if source_kind == "scholarly_publisher_metadata":
        return 0.18
    if source_kind == "scholarly_index_metadata":
        return 0.08
    if source_kind == "crawl_seed":
        return -0.08
    if source_kind in {"crawl_discovered", "crawl_sitemap", "direct_url"}:
        return 0.03
    return 0.0


def _sec_directory_lookup_intent(query_text: str) -> bool:
    normalized = " ".join(str(query_text or "").replace("_", " ").replace("-", " ").split())
    if not normalized:
        return False
    has_identity_term = any(term in normalized for term in ("cik", "ticker", "identifier", "company_tickers"))
    has_directory_term = any(term in normalized for term in ("directory", "mapping", "lookup", "registry", "index"))
    return has_identity_term and has_directory_term


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


def _target_entity_score_adjustment(diagnostics: dict[str, object]) -> float:
    if not bool(diagnostics.get("target_entity_required")):
        return 0.0
    if bool(diagnostics.get("target_entity_satisfied")):
        return 0.28
    return -0.62


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
