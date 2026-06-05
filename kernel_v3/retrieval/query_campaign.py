from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.retrieval.contracts import SearchGoal
from kernel_v3.retrieval.strategy import materially_different_query, query_signature
from kernel_v3.retrieval.targeting import target_entity_phrases


QUERY_TEXT_LIMIT = 500
DEFAULT_GENERIC_CAMPAIGN_QUERIES = 8
MAX_ENTITY_CAMPAIGN_QUERIES = 8
MAX_FACET_CAMPAIGN_QUERIES = 16


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
    model_strategy = _retrieval_strategy(goal.metadata)
    strategy_queries = _strategy_query_candidates(model_strategy)
    strategy_driven = bool(strategy_queries)
    templates = _metadata_string_list(goal.metadata.get("query_templates"))
    profile_templates = _profile_query_templates(research_profile)
    expansion_enabled = _campaign_expansion_enabled(goal, explicit=explicit)
    host_axis_expansion_enabled = _host_axis_expansion_enabled(goal.metadata, strategy_driven=strategy_driven)
    attempted_queries = _attempted_queries(goal.metadata)

    candidates: list[tuple[str, str]] = []
    if explicit:
        candidates.extend((item, "explicit_query") for item in explicit)
    if strategy_queries:
        candidates.extend(strategy_queries)
    if not explicit and not strategy_queries:
        candidates.append((query, "base_query"))
    elif not explicit and strategy_queries:
        candidates.append((query, "base_query_fallback"))

    active_templates = templates if strategy_driven else templates or profile_templates
    candidates.extend((_render_query_template(template, query=query), "template") for template in active_templates)

    if expansion_enabled:
        candidates.extend((item, "suggested_query_hint") for item in _metadata_string_list(goal.metadata.get("suggested_query_hints")))
        candidates.extend((item, "source_target_hint") for item in _source_target_queries(goal.metadata))
        candidates.extend(_strategy_fallback_query_candidates(model_strategy, base_query=query))
        if host_axis_expansion_enabled:
            candidates.extend((item, "target_entity_axis") for item in _target_entity_queries(query, goal, research_profile=research_profile))
            candidates.extend((item, "profile_facet_axis") for item in _profile_facet_queries(query, goal, research_profile=research_profile))
            candidates.extend((item, "mission_coverage_axis") for item in _mission_coverage_queries(query, goal.metadata))
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
            "model_strategy_present": bool(model_strategy),
            "model_strategy_query_count": len(strategy_queries),
            "host_axis_expansion_enabled": host_axis_expansion_enabled,
            "template_count": len(active_templates),
            "profile_template_count": len(profile_templates),
            "target_entities": target_entity_phrases(query),
            "profile_facets": _profile_facets(query, goal, research_profile=research_profile),
            "attempted_query_signatures": [query_signature(item) for item in attempted_queries[-12:]],
            "selected": selected_reasons[:32],
            "skipped": skipped[:32],
            "skipped_count": len(skipped),
        },
    )


def _retrieval_strategy(metadata: JsonObject) -> JsonObject:
    raw = metadata.get("retrieval_strategy")
    if isinstance(raw, dict):
        return dict(raw)
    raw = metadata.get("model_retrieval_strategy")
    return dict(raw) if isinstance(raw, dict) else {}


def _strategy_query_candidates(strategy: JsonObject) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    candidates.extend((item, "model_strategy_query") for item in _metadata_string_list(strategy.get("queries")))
    candidates.extend(_strategy_query_plan_candidates(strategy.get("query_plan"), source="model_strategy_query_plan"))
    candidates.extend(_strategy_query_plan_candidates(strategy.get("search_moves"), source="model_strategy_search_move"))
    return _ordered_unique_candidates(candidates)


def _strategy_query_plan_candidates(value: object, *, source: str) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    candidates: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, str):
            query = item.strip()
        elif isinstance(item, dict):
            query = _string(item.get("query")) or _string(item.get("search_query")) or ""
        else:
            query = ""
        if query:
            candidates.append((query, source))
    return candidates


def _strategy_fallback_query_candidates(strategy: JsonObject, *, base_query: str) -> list[tuple[str, str]]:
    value = strategy.get("fallback_moves")
    if not isinstance(value, list):
        return []
    candidates: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            query = _string(item.get("query")) or _string(item.get("search_query"))
            if query:
                candidates.append((query, "model_strategy_fallback"))
            continue
        if not isinstance(item, str):
            continue
        text = " ".join(item.split())
        if not text:
            continue
        if any(marker in text.lower() for marker in ("search ", "query ", "site:", "\"")):
            candidates.append((f"{base_query} {text}", "model_strategy_fallback"))
    return _ordered_unique_candidates(candidates)


def _host_axis_expansion_enabled(metadata: JsonObject, *, strategy_driven: bool) -> bool:
    value = metadata.get("host_query_axes", metadata.get("fixed_query_axes"))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
        if normalized in {"1", "true", "yes", "on", "enabled", "auto", "fallback"}:
            return True
    return not strategy_driven


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


def _target_entity_queries(
    query: str,
    goal: SearchGoal,
    *,
    research_profile: ResearchProfile | None,
) -> list[str]:
    entities = target_entity_phrases(query)
    if not entities:
        return []
    source_terms = [
        _source_family_query_terms(family)
        for family in _preferred_campaign_families(goal, research_profile=research_profile)[:4]
    ]
    source_terms = [item for item in source_terms if item]
    task_terms = _task_axis_terms(goal.metadata)
    queries: list[str] = []
    for entity in entities[:3]:
        quoted = f'"{entity}"'
        queries.extend(
            [
                f"{quoted} official source",
                f"{quoted} profile operations scale",
                f"{quoted} primary source",
            ]
        )
        for term in source_terms[:3]:
            queries.append(f"{quoted} {term}")
        for term in task_terms[:3]:
            queries.append(f"{quoted} {term}")
    return _ordered_unique(queries)[:MAX_ENTITY_CAMPAIGN_QUERIES]


def _profile_facet_queries(
    query: str,
    goal: SearchGoal,
    *,
    research_profile: ResearchProfile | None,
) -> list[str]:
    facets = _profile_facets(query, goal, research_profile=research_profile)
    if research_profile is None or not facets:
        return []
    policy = research_profile.metadata.get("evidence_policy")
    if not isinstance(policy, dict):
        return []
    aliases = policy.get("facet_aliases")
    if not isinstance(aliases, dict):
        return []
    queries: list[str] = []
    for facet in facets[:8]:
        raw_terms = aliases.get(facet)
        terms = _metadata_string_list(raw_terms)[:4]
        if not terms:
            continue
        queries.append(f"{query} {' '.join(terms[:2])}")
        for term in terms[:3]:
            queries.append(f"{query} {term}")
    return _ordered_unique(queries)[:MAX_FACET_CAMPAIGN_QUERIES]


def _mission_coverage_queries(query: str, metadata: JsonObject) -> list[str]:
    terms: list[str] = []
    for item in _metadata_string_list(metadata.get("minimum_coverage")):
        terms.append(_coverage_term(item))
    answer_profile = metadata.get("answer_profile")
    if isinstance(answer_profile, dict):
        for item in _metadata_string_list(answer_profile.get("minimum_coverage")):
            terms.append(_coverage_term(item))
        for item in _metadata_string_list(answer_profile.get("target_sections")):
            terms.append(_coverage_term(item))
    research_mission = metadata.get("research_mission")
    if isinstance(research_mission, dict):
        requirements = research_mission.get("requirements")
        if isinstance(requirements, list):
            for requirement in requirements:
                if isinstance(requirement, dict):
                    terms.append(_coverage_term(str(requirement.get("text") or "")))
    return _ordered_unique([f"{query} {term}" for term in terms if term])[:12]


def _profile_facets(
    query: str,
    goal: SearchGoal,
    *,
    research_profile: ResearchProfile | None,
) -> list[str]:
    if research_profile is None:
        return []
    policy = research_profile.metadata.get("evidence_policy")
    if not isinstance(policy, dict):
        return []
    triggers = policy.get("facet_triggers")
    facets: list[str] = []
    if isinstance(triggers, dict):
        normalized = query.lower()
        for facet, raw_markers in triggers.items():
            markers = _metadata_string_list(raw_markers)
            if any(marker.lower() in normalized for marker in markers):
                facets.append(str(facet))
    task_kind = _string(goal.metadata.get("research_task_kind"))
    if task_kind:
        facets.extend(_metadata_string_list(policy.get("task_default_facets")))
    facets.extend(_metadata_string_list(policy.get("default_facets")))
    missing = _metadata_string_list(goal.metadata.get("missing"))
    for item in missing:
        if ":" in item:
            facets.append(item.split(":", 1)[1])
    return _ordered_unique(facets)


def _source_family_queries(
    query: str,
    goal: SearchGoal,
    *,
    research_profile: ResearchProfile | None,
) -> list[str]:
    families = _preferred_campaign_families(goal, research_profile=research_profile)
    result: list[str] = []
    for family in families[:10]:
        terms = _source_family_query_terms(family)
        if terms:
            result.append(f"{query} {terms}")
    return result


def _preferred_campaign_families(
    goal: SearchGoal,
    *,
    research_profile: ResearchProfile | None,
) -> list[str]:
    strategy = _retrieval_strategy(goal.metadata)
    return _ordered_unique(
        [
            *_strategy_source_families(strategy),
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


def _strategy_source_families(strategy: JsonObject) -> list[str]:
    families: list[str] = []
    families.extend(_metadata_string_list(strategy.get("preferred_source_families")))
    plan = strategy.get("source_family_plan")
    if isinstance(plan, list):
        for item in plan:
            if isinstance(item, str):
                families.append(item)
            elif isinstance(item, dict):
                family = _string(item.get("family")) or _string(item.get("source_family"))
                if family:
                    families.append(family)
    return _ordered_unique(families)


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


def _task_axis_terms(metadata: JsonObject) -> list[str]:
    task_kind = _string(metadata.get("research_task_kind")) or ""
    if not task_kind:
        return []
    return [
        task_kind.replace("_", " "),
        "facts evidence",
        "operations",
        "scale",
    ]


def _coverage_term(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").split())


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


def _ordered_unique_candidates(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for query, source in values:
        signature = query_signature(query)
        if not query or signature in seen:
            continue
        seen.add(signature)
        result.append((query, source))
    return result
