from __future__ import annotations

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import ResearchProfile


FINANCE_FUNDAMENTALS_PROFILE_ID = "finance_fundamentals"
RESEARCH_DEPTHS = ("light", "balanced", "deep")

_FINANCE_QUERY_TEMPLATES = [
    "{query}",
    "{query} annual report 10-K 10-Q filing",
    "{query} SEC EDGAR 10-K 10-Q companyfacts",
    "{query} site:sec.gov/Archives/edgar/data annual report",
    "{query} investor relations earnings release",
    "{query} investor relations earnings presentation annual report",
    "{query} exchange filing annual report",
    "{query} HKEX annual report announcement",
    "{query} cninfo 年报 季报 公告",
    "{query} official financial statements annual report",
]

_FINANCE_DEPTH_DEFAULTS: dict[str, JsonObject] = {
    "light": {
        "max_queries": 1,
        "max_sources": 5,
        "max_fetches": 2,
        "max_spans_per_document": 2,
    },
    "balanced": {
        "max_queries": 3,
        "max_sources": 10,
        "max_fetches": 4,
        "max_spans_per_document": 3,
    },
    "deep": {
        "max_queries": 4,
        "max_sources": 20,
        "max_fetches": 8,
        "max_spans_per_document": 5,
    },
}


def finance_fundamentals_profile() -> ResearchProfile:
    return ResearchProfile(
        profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        domain="finance",
        description="Financial fundamental research with primary-source preference and citation gating.",
        primary_source_families=[
            "regulatory_filing",
            "structured_regulatory_data",
            "exchange_filing",
            "company_ir",
            "earnings_release",
            "government_statistic",
        ],
        secondary_source_families=[
            "reputable_news",
            "market_data_provider",
            "analyst_report",
        ],
        weak_source_families=[
            "blog",
            "forum",
            "social",
            "generic_web",
            "unknown",
        ],
        minimum_primary_authority_score=0.8,
        citations_required=True,
        metadata={
            "default_output_boundary": "facts_inferences_risks_limitations",
            "freshness_max_age_ms": 15552000000,
            "investment_recommendation": "not_without_explicit_user_scope_and_evidence",
            "default_research_depth": "balanced",
            "query_strategy": {
                "strategy_id": "finance_primary_source_expansion",
                "templates": list(_FINANCE_QUERY_TEMPLATES),
                "preferred_source_families": [
                    "regulatory_filing",
                    "structured_regulatory_data",
                    "exchange_filing",
                    "company_ir",
                    "earnings_release",
                    "government_statistic",
                ],
            },
            "research_depths": {
                key: dict(value)
                for key, value in _FINANCE_DEPTH_DEFAULTS.items()
            },
        },
    )


def profile_by_id(profile_id: str | None) -> ResearchProfile | None:
    if profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID:
        return finance_fundamentals_profile()
    return None


def research_depth_defaults(profile_id: str | None, depth: str | None = None) -> JsonObject:
    profile = profile_by_id(profile_id)
    if profile is None:
        return {}
    requested = str(depth or profile.metadata.get("default_research_depth") or "balanced")
    if requested not in RESEARCH_DEPTHS:
        requested = str(profile.metadata.get("default_research_depth") or "balanced")
    depths = profile.metadata.get("research_depths")
    if not isinstance(depths, dict):
        return {}
    defaults = depths.get(requested)
    return dict(defaults) if isinstance(defaults, dict) else {}
