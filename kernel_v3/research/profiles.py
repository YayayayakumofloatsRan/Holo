from __future__ import annotations

from kernel_v3.research.contracts import ResearchProfile


FINANCE_FUNDAMENTALS_PROFILE_ID = "finance_fundamentals"


def finance_fundamentals_profile() -> ResearchProfile:
    return ResearchProfile(
        profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        domain="finance",
        description="Financial fundamental research with primary-source preference and citation gating.",
        primary_source_families=[
            "regulatory_filing",
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
            "investment_recommendation": "not_without_explicit_user_scope_and_evidence",
        },
    )


def profile_by_id(profile_id: str | None) -> ResearchProfile | None:
    if profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID:
        return finance_fundamentals_profile()
    return None
