from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.retrieval.contracts import SearchGoal
from kernel_v3.retrieval.strategy import materially_different_query, query_signature


QUERY_TEXT_LIMIT = 500
DEFAULT_GENERIC_CAMPAIGN_QUERIES = 8


@dataclass(frozen=True, kw_only=True)
class QueryCampaign:
    queries: list[str]
    diagnostics: JsonObject = field(default_factory=dict)


def build_query_campaign(
    goal: SearchGoal,
    *,
    research_profile: ResearchProfile | None = None,
) -> QueryCampaign:
    query = _bounded_query(goal.query)
    if not query:
        return QueryCampaign(queries=[], diagnostics={"campaign_status": "empty_query"})

    explicit = _metadata_string_list(goal.metadata.get("queries"))
    templates = _metadata_string_list(goal.metadata.get("query_templates"))
    profile_templates = _profile_query_templates(research_profile)
    expansion_enabled = _campaign_expansion_enabled(goal, explicit=explicit)
    attempted_queries = _attempted_queries(goal.metadata)

    candidates: list[tuple[str, str]] = []
    if explicit:
        candidates.extend((item, "explicit_query") for item in explicit)
    else:
        candidates.append((query, "base_query"))

    active_templates = templates or profile_templates
    candidates.extend((_render_query_template(template, query=query), "template") for template in active_templates)

    if expansion_enabled:
        candidates.extend((item, "suggested_query_hint") for item in _metadata_string_list(goal.metadata.get("suggested_query_hints")))
        candidates.extend((item, "source_target_hint") for item in _source_target_queries(goal.metadata))
        candidates.extend((item, "source_family_switch") for item in _source_family_queries(query, goal, research_profile=research_profile))
        candidates.extend((item, "generic_research_axis") for item in _generic_research_queries(query))

    selected: list[str] = []
    selected_reasons: list[JsonObject] = []
    skipped: list[JsonObject] = []
    seen: set[str] = set()
    for raw, reason in candidates:
        candidate = _bounded_query(raw)
        signature = query_signature(candidate)
        if not candidate:
            continue
        if signature in seen:
            skipped.append({"query": candidate, "reason": "duplicate_candidate", "source": reason})
            continue
        if attempted_queries and not materially_different_query(candidate, attempted_queries):
            skipped.append({"query": candidate, "reason": "attempted_or_too_similar", "source": reason})
            continue
        seen.add(signature)
        selected.append(candidate)
        selected_reasons.append({"query": candidate, "source": reason, "signature": signature})
        if len(selected) >= max(0, int(goal.max_queries)):
            break

    if not selected and query:
        selected = [query]
        selected_reasons = [{"query": query, "source": "fallback_base_query", "signature": query_signature(query)}]

    return QueryCampaign(
        queries=selected,
        diagnostics={
            "campaign_status": "ready" if selected else "empty",
            "expansion_enabled": expansion_enabled,
            "base_query_signature": query_signature(query),
            "query_count": len(selected),
            "max_queries": goal.max_queries,
            "explicit_query_count": len(explicit),
            "template_count": len(active_templates),
            "profile_template_count": len(profile_templates),
            "attempted_query_signatures": [query_signature(item) for item in attempted_queries[-12:]],
            "selected": selected_reasons[:32],
            "skipped": skipped[:32],
            "skipped_count": len(skipped),
        },
    )


def _campaign_expansion_enabled(goal: SearchGoal, *, explicit: list[str]) -> bool:
    metadata = goal.metadata
    value = metadata.get("query_expansion", metadata.get("query_campaign"))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
        if normalized in {"1", "true", "yes", "on", "enabled", "auto", "deep"}:
            return True
    if goal.max_queries <= max(1, len(explicit)):
        return False
    return True


def _attempted_queries(metadata: JsonObject) -> list[str]:
    values: list[str] = []
    for key in ("attempted_queries", "avoid_repeating"):
        values.extend(_metadata_string_list(metadata.get(key)))
    directive = metadata.get("mission_directive")
    if isinstance(directive, dict):
        values.extend(_metadata_string_list(directive.get("avoid_repeating")))
    return _ordered_unique(values)


def _source_target_queries(metadata: JsonObject) -> list[str]:
    queries: list[str] = []
    targets = metadata.get("suggested_source_targets")
    if not isinstance(targets, list):
        return queries
    for target in targets:
        if not isinstance(target, dict):
            continue
        base = _string(target.get("title")) or _string(target.get("source_id"))
        for hint in _metadata_string_list(target.get("query_hints")):
            queries.append(f"{base} {hint}" if base else hint)
    return queries


def _source_family_queries(
    query: str,
    goal: SearchGoal,
    *,
    research_profile: ResearchProfile | None,
) -> list[str]:
    families = _ordered_unique(
        [
            *_metadata_string_list(goal.metadata.get("preferred_source_families")),
            *(
                list(research_profile.primary_source_families)
                if research_profile is not None
                else []
            ),
            *(
                list(research_profile.secondary_source_families)
                if research_profile is not None
                else []
            ),
        ]
    )
    result: list[str] = []
    for family in families[:10]:
        terms = _source_family_query_terms(family)
        if terms:
            result.append(f"{query} {terms}")
    return result


def _source_family_query_terms(source_family: str) -> str:
    normalized = source_family.strip().lower().replace("-", "_")
    terms = {
        "regulatory_filing": "official filing annual report",
        "structured_regulatory_data": "official structured data API",
        "exchange_filing": "exchange disclosure annual report",
        "company_ir": "investor relations annual report earnings",
        "earnings_release": "earnings release financial results",
        "government_statistic": "official government statistics data",
        "central_bank_statistic": "central bank official data",
        "treasury_data": "treasury official data",
        "market_data_provider": "market data price valuation metrics",
        "reputable_news": "reputable news analysis",
        "scholarly_index": "academic papers DOI",
        "scholarly_search": "arxiv papers survey",
        "technical_documentation": "official documentation API reference",
        "developer_docs": "developer docs examples parameters",
        "company_registry": "company registry filings officers",
    }
    return terms.get(normalized, normalized.replace("_", " "))


def _generic_research_queries(query: str) -> list[str]:
    return [
        f"{query} official source",
        f"{query} primary source",
        f"{query} report PDF",
        f"{query} data statistics",
        f"{query} recent research",
        f"{query} analysis overview",
        f"{query} methodology evidence",
        f"{query} source documentation",
    ]


def _profile_query_templates(profile: ResearchProfile | None) -> list[str]:
    if profile is None:
        return []
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


def _bounded_query(value: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= QUERY_TEXT_LIMIT:
        return text
    return text[: max(0, QUERY_TEXT_LIMIT - 3)] + "..."


def _string(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
