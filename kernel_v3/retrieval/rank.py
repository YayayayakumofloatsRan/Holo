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
        source_kind_adjustment = _source_kind_score_adjustment(metadata, query=_ranking_intent_text(goal))
        source_family_adjustment = _source_family_preference_adjustment(goal.metadata, metadata)
        source_rank_adjustment = _source_rank_preference_adjustment(metadata)
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
                + source_rank_adjustment
                + target_adjustment
            )
            metadata["source_assessment"] = assessment.to_dict()
            reasons.append(f"authority:{assessment.authority_level}")
        else:
            score = term_score + source_kind_adjustment + source_family_adjustment + source_rank_adjustment + target_adjustment
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
    ranking_intent = _ranking_intent_text(goal)
    if (
        _is_finance_profile(research_profile)
        and _sec_companyfacts_fact_intent(ranking_intent)
        and not _sec_filing_text_intent(ranking_intent)
    ):
        ordered = _prioritize_distinct_companyfacts(ordered)
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


def _is_finance_profile(research_profile: ResearchProfile | None) -> bool:
    return bool(research_profile is not None and research_profile.profile_id == "finance_fundamentals")


def _prioritize_distinct_companyfacts(items: list[RankedSource]) -> list[RankedSource]:
    companyfacts: list[RankedSource] = []
    remainder: list[RankedSource] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for item in items:
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        source_kind = str(metadata.get("source_kind") or "")
        if source_kind in {"sec_companyfacts_json", "sec_companyconcept_json"}:
            cik = str(metadata.get("sec_cik") or item.uri).strip()
            concept = str(metadata.get("sec_concept") or "").strip()
            key = (source_kind, cik, concept)
            if cik and key not in seen_keys:
                seen_keys.add(key)
                companyfacts.append(item)
                continue
        remainder.append(item)
    if not companyfacts:
        return items
    return [*companyfacts, *remainder]


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


def _ranking_intent_text(goal: SearchGoal) -> str:
    parts = [str(goal.query or "")]
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    for key in ("root_goal", "task_goal", "original_goal", "user_goal"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    mission = metadata.get("research_mission")
    if isinstance(mission, dict):
        value = mission.get("root_goal")
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


def _source_kind_score_adjustment(metadata: dict[str, object], *, query: str = "") -> float:
    source_kind = metadata.get("source_kind")
    query_text = query.lower()
    sec_directory_intent = _sec_directory_lookup_intent(query_text)
    sec_companyfacts_intent = _sec_companyfacts_fact_intent(query_text)
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
    filing_text_intent = _sec_filing_text_intent(query_text)
    if source_kind == "sec_primary_filing_document":
        return 0.78 if filing_text_intent else 0.55
    if source_kind == "sec_complete_submission_text":
        return 0.82 if filing_text_intent else 0.52
    if source_kind == "sec_exhibit_document":
        return 0.9 if filing_text_intent else 0.62
    if source_kind == "sec_companyfacts_json":
        if submissions_intent:
            return 0.38
        if sec_companyfacts_intent:
            return 1.18
        if filing_text_intent:
            return -0.20
        return 0.50
    if source_kind == "sec_companyconcept_json":
        if submissions_intent:
            return 0.40
        if sec_companyfacts_intent:
            return 1.24
        if filing_text_intent:
            return -0.18
        return 0.54
    if source_kind == "sec_submissions_json":
        if filing_text_intent:
            return 1.35
        if submissions_intent or filing_text_intent:
            return 0.51
        return 0.42
    if source_kind == "sec_ticker_cik_directory":
        if metadata.get("ticker") and not metadata.get("sec_cik"):
            return 0.96
        return 0.62 if sec_directory_intent else -0.32
    if source_kind == "sec_edgar_browse_ticker":
        return 1.05 if filing_text_intent else 0.74
    if source_kind in {"sec_edgar_search", "sec_filing_directory"}:
        if filing_text_intent:
            return -0.75
        return -0.32
    if source_kind == "sec_edgar_browse":
        if filing_text_intent:
            return -0.40
        return -0.12
    if source_kind == "market_data_statistics":
        if _valuation_market_data_intent(query_text):
            return 0.92
        return 0.24
    if source_kind == "market_data_quote":
        if _valuation_market_data_intent(query_text):
            return 0.42
        return 0.16
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


def _sec_companyfacts_fact_intent(query_text: str) -> bool:
    normalized = " ".join(str(query_text or "").replace("_", " ").replace("-", " ").split()).lower()
    compact = "".join(ch for ch in normalized if ch.isalnum())
    if not normalized:
        return False
    return any(
        marker in normalized or marker in compact
        for marker in (
            "companyfacts",
            "xbrl",
            "debt to equity",
            "debt/equity",
            "debttoequity",
            "revenue",
            "revenues",
            "net sales",
            "net income",
            "capital intensive",
            "capital intensity",
            "capital expenditures",
            "capex",
            "operating cash flow",
            "property plant",
            "pp&e",
            "cash and cash equivalents",
            "total debt",
            "long term debt",
            "short term debt",
            "assets",
            "liabilities",
            "shareholders equity",
            "stockholders equity",
            "shareholdersequity",
            "stockholdersequity",
            "inventorynet",
            "costofrevenue",
            "costofgoodsandservicessold",
            "paymentstoacquirepropertyplantandequipment",
            "netcashprovidedbyusedinoperatingactivities",
            "propertyplantandequipmentnet",
            "netincomeloss",
            "revenuefromcontract",
            "earningspershare",
        )
    )


def _sec_filing_text_intent(query_text: str) -> bool:
    normalized = " ".join(str(query_text or "").replace("_", " ").replace("-", " ").split()).lower()
    compact = "".join(ch for ch in normalized if ch.isalnum())
    if not normalized:
        return False
    return any(
        marker in normalized or marker in compact
        for marker in (
            "8-k",
            "8k",
            "merger",
            "acquisition",
            "transaction",
            "deal value",
            "purchase price",
            "consideration",
            "purchase price allocation",
            "goodwill",
            "intangible assets",
            "adjusted ebitda",
            "non-gaap",
            "non gaap",
            "reconciliation",
            "bridge",
            "addback",
            "add back",
            "add-back",
        )
    )


def _valuation_market_data_intent(query_text: str) -> bool:
    normalized = " ".join(str(query_text or "").replace("_", " ").replace("-", " ").split()).lower()
    compact = "".join(ch for ch in normalized if ch.isalnum())
    if not normalized:
        return False
    return any(
        marker in normalized or marker in compact
        for marker in (
            "ev/ebitda",
            "evebitda",
            "ev/revenue",
            "evrev",
            "enterprise value",
            "market cap",
            "market capitalization",
            "key statistics",
            "valuation multiple",
            "valuation multiples",
        )
    )


def _source_family_preference_adjustment(goal_metadata: dict[str, object], source_metadata: dict[str, object]) -> float:
    source_family = source_metadata.get("source_family")
    if not isinstance(source_family, str) or not source_family:
        return 0.0
    preferred = _preferred_source_families(goal_metadata)
    if not preferred:
        return 0.0
    if source_family in preferred and goal_metadata.get("research_task_kind") == "valuation":
        return 0.45
    if source_family in preferred:
        return 0.18
    return -0.08


def _source_rank_preference_adjustment(metadata: dict[str, object]) -> float:
    relevance_adjustment = 0.0
    try:
        relevance_adjustment = min(max(float(metadata.get("link_relevance_score") or 0.0), 0.0), 5.0) * 0.08
    except (TypeError, ValueError):
        relevance_adjustment = 0.0
    try:
        rank = int(str(metadata.get("rank") or "").strip())
    except ValueError:
        return relevance_adjustment
    if rank <= 0:
        return relevance_adjustment
    return relevance_adjustment - (min(rank, 500) * 0.0001)


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
