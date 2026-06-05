from __future__ import annotations

import re
from typing import TYPE_CHECKING

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.profiles import profile_by_id

if TYPE_CHECKING:
    from kernel_v3.retrieval.contracts import EvidenceItem, SearchGoal


QUERY_FACET_ALIASES: dict[str, list[str]] = {
    "model": ["model", "models", "deepseek-chat", "deepseek-reasoner", "deepseek-v3", "deepseek-v4", "模型"],
    "authentication": [
        "auth",
        "authentication",
        "authorization",
        "bearer",
        "api key",
        "apikey",
        "x-api-key",
        "secret key",
        "鉴权",
        "认证",
        "授权",
        "api密钥",
        "密钥",
    ],
    "pricing": ["pricing", "price", "cost", "billing", "bill", "定价", "价格", "费用", "计费"],
    "token": ["token", "tokens", "tokenizer", "context length", "上下文", "令牌"],
    "rate_limit": ["rate limit", "rate-limit", "quota", "qps", "rpm", "limit", "限流", "额度", "配额"],
    "endpoint": ["endpoint", "base url", "base_url", "api base", "host", "接口地址", "端点", "基础地址"],
}

QUERY_FACET_TRIGGERS: dict[str, list[str]] = {
    "model": ["model", "models", "模型"],
    "authentication": ["auth", "authentication", "authorization", "api key", "apikey", "鉴权", "认证", "授权", "密钥"],
    "pricing": ["pricing", "price", "cost", "billing", "定价", "价格", "费用", "计费"],
    "token": ["token", "tokens", "tokenizer", "context length", "上下文", "令牌"],
    "rate_limit": ["rate limit", "rate-limit", "quota", "qps", "rpm", "限流", "额度", "配额"],
    "endpoint": ["endpoint", "base url", "base_url", "接口地址", "端点", "基础地址"],
}


def resolve_goal_research_profile(
    goal: "SearchGoal",
    research_profile: ResearchProfile | None = None,
) -> ResearchProfile | None:
    if research_profile is not None:
        return research_profile
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    raw = metadata.get("research_profile") or metadata.get("research_profile_id")
    return profile_by_id(str(raw)) if isinstance(raw, str) and raw.strip() else None


def profile_evidence_policy(profile: ResearchProfile | None) -> JsonObject:
    if profile is None:
        return {}
    policy = profile.metadata.get("evidence_policy")
    return dict(policy) if isinstance(policy, dict) else {}


def profile_evidence_facets(
    *,
    goal: "SearchGoal",
    research_profile: ResearchProfile | None = None,
) -> list[str]:
    profile = resolve_goal_research_profile(goal, research_profile)
    policy = profile_evidence_policy(profile)
    if not policy:
        return []
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    task_kind = str(metadata.get("research_task_kind") or metadata.get("task_kind") or "").strip().lower()
    if task_kind in set(_string_list(policy.get("excluded_task_kinds"))):
        return []
    query = goal.query.lower()
    triggers = _string_list_map(policy.get("facet_triggers"))
    facets = [
        facet
        for facet, aliases in triggers.items()
        if any(alias.lower() in query for alias in aliases)
    ]
    if task_kind in set(_string_list(policy.get("task_kinds"))):
        facets.extend(_string_list(policy.get("task_default_facets")))
    if not any(facet in facets for facet in _string_list(policy.get("default_facets"))):
        default_facets = _string_list(policy.get("default_facets"))
        if default_facets and (facets or task_kind in set(_string_list(policy.get("task_kinds")))):
            facets.extend(default_facets)
    return _ordered_unique(facets)


def profile_extraction_aliases(
    *,
    goal: "SearchGoal",
    research_profile: ResearchProfile | None = None,
) -> list[str]:
    profile = resolve_goal_research_profile(goal, research_profile)
    aliases = _string_list_map(profile_evidence_policy(profile).get("facet_aliases"))
    result: list[str] = []
    for facet in profile_evidence_facets(goal=goal, research_profile=profile):
        result.extend(aliases.get(facet, []))
    return _ordered_unique(result)


def profile_discovery_source_kinds(profile: ResearchProfile | None) -> set[str]:
    return set(_string_list(profile_evidence_policy(profile).get("discovery_source_kinds")))


def profile_is_discovery_goal(
    *,
    goal: "SearchGoal",
    research_profile: ResearchProfile | None = None,
) -> bool:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    role = str(
        metadata.get("retrieval_role")
        or metadata.get("source_role")
        or metadata.get("goal_role")
        or metadata.get("evidence_role")
        or ""
    ).strip().lower()
    if role in {"discovery", "lookup", "metadata", "source_discovery"}:
        return True
    profile = resolve_goal_research_profile(goal, research_profile)
    policy = profile_evidence_policy(profile)
    query = goal.query.lower()
    discovery_markers = _string_list(policy.get("discovery_query_markers"))
    if not discovery_markers or not any(_marker_matches(query, marker) for marker in discovery_markers):
        return False
    evidence_markers = _string_list(policy.get("discovery_evidence_markers"))
    return not any(_marker_matches(query, marker) for marker in evidence_markers)


def qualify_profile_evidence_candidate(
    *,
    goal: "SearchGoal",
    evidence: "EvidenceItem",
    research_profile: ResearchProfile | None = None,
) -> JsonObject:
    profile = resolve_goal_research_profile(goal, research_profile)
    policy = profile_evidence_policy(profile)
    if profile is None or not policy:
        return {"accepted": True, "reason": "no_profile_evidence_policy"}
    source_kind = evidence_source_kind(evidence)
    if source_kind in profile_discovery_source_kinds(profile):
        return {
            "accepted": False,
            "reason": "discovery_metadata_not_final_evidence",
            "covered_profile_facets": [],
            "missing_profile_facets": ["final_evidence_fact"],
            "profile_numeric_fact_required": False,
            "profile_numeric_fact_present": False,
            "source_kind": source_kind,
            "research_profile": profile.profile_id,
        }
    required = profile_evidence_facets(goal=goal, research_profile=profile)
    if not required:
        return {"accepted": True, "reason": "no_required_profile_facets", "research_profile": profile.profile_id}
    covered = profile_text_facets(evidence.text, required, profile=profile)
    numeric_required = _profile_numeric_fact_required(required, profile=profile)
    numeric_present = profile_text_has_numeric_fact(evidence.text, required, profile=profile)
    missing = [facet for facet in required if facet not in set(covered)]
    if numeric_required and not numeric_present:
        missing.append("numeric_profile_fact")
    accepted = bool(numeric_present if numeric_required else covered)
    return {
        "accepted": accepted,
        "reason": "qualified_profile_evidence" if accepted else "missing_profile_fact_in_span",
        "covered_profile_facets": covered,
        "missing_profile_facets": _ordered_unique(missing),
        "profile_numeric_fact_required": numeric_required,
        "profile_numeric_fact_present": numeric_present,
        "research_profile": profile.profile_id,
    }


def assess_profile_evidence_coverage(
    *,
    goal: "SearchGoal",
    evidence: list["EvidenceItem"],
    research_profile: ResearchProfile | None = None,
) -> JsonObject:
    profile = resolve_goal_research_profile(goal, research_profile)
    required = profile_evidence_facets(goal=goal, research_profile=profile)
    aliases = _string_list_map(profile_evidence_policy(profile).get("facet_aliases"))
    corpus = "\n".join(item.text for item in evidence).lower()
    covered: list[str] = []
    missing: list[str] = []
    matched_aliases: dict[str, list[str]] = {}
    for facet in required:
        matches = [alias for alias in aliases.get(facet, []) if alias.lower() in corpus]
        if matches:
            covered.append(facet)
            matched_aliases[facet] = matches[:6]
        else:
            missing.append(facet)
    numeric_required = _profile_numeric_fact_required(required, profile=profile)
    numeric_present = any(profile_text_has_numeric_fact(item.text, required, profile=profile) for item in evidence)
    if numeric_required and not numeric_present:
        missing.append("numeric_profile_fact")
    return {
        "profile_evidence_required": bool(required),
        "profile_evidence_facets": required,
        "covered_profile_facets": covered,
        "missing_profile_facets": _ordered_unique(missing),
        "profile_numeric_fact_required": numeric_required,
        "profile_numeric_fact_present": numeric_present,
        "profile_facet_coverage": 1.0 if not required else round(len(covered) / len(required), 4),
        "profile_facet_matches": matched_aliases,
    }


def query_facets(query: str) -> list[str]:
    normalized = query.lower()
    return _ordered_unique(
        [
            facet
            for facet, triggers in QUERY_FACET_TRIGGERS.items()
            if any(trigger.lower() in normalized for trigger in triggers)
        ]
    )


def assess_query_facet_coverage(*, goal: "SearchGoal", evidence: list["EvidenceItem"]) -> JsonObject:
    required = query_facets(goal.query)
    corpus = "\n".join(item.text for item in evidence).lower()
    covered: list[str] = []
    missing: list[str] = []
    matched_aliases: dict[str, list[str]] = {}
    for facet in required:
        aliases = QUERY_FACET_ALIASES.get(facet, [])
        matches = [alias for alias in aliases if alias.lower() in corpus]
        if matches:
            covered.append(facet)
            matched_aliases[facet] = matches[:5]
        else:
            missing.append(facet)
    return {
        "query_facets": required,
        "covered_query_facets": covered,
        "missing_query_facets": missing,
        "query_facet_coverage": 1.0 if not required else round(len(covered) / len(required), 4),
        "query_facet_matches": matched_aliases,
    }


def profile_text_facets(text: str, required_facets: list[str], *, profile: ResearchProfile | None) -> list[str]:
    corpus = text.lower()
    aliases = _string_list_map(profile_evidence_policy(profile).get("facet_aliases"))
    covered: list[str] = []
    for facet in required_facets:
        if any(alias.lower() in corpus for alias in aliases.get(facet, [])):
            covered.append(facet)
    return covered


def profile_text_has_numeric_fact(text: str, required_facets: list[str], *, profile: ResearchProfile | None) -> bool:
    if not text or not _profile_numeric_fact_required(required_facets, profile=profile):
        return False
    aliases: list[str] = []
    policy = profile_evidence_policy(profile)
    facet_aliases = _string_list_map(policy.get("facet_aliases"))
    for facet in required_facets:
        if facet in set(_string_list(policy.get("numeric_fact_facets"))):
            aliases.extend(facet_aliases.get(facet, []))
    if not aliases:
        for facet in _string_list(policy.get("default_facets")):
            aliases.extend(facet_aliases.get(facet, []))
    pattern = _numeric_pattern(profile)
    if pattern is None:
        return bool(aliases) and any(alias.lower() in text.lower() for alias in aliases)
    corpus = text.lower()
    for alias in _ordered_unique([item.lower() for item in aliases if item]):
        start = 0
        while True:
            index = corpus.find(alias, start)
            if index < 0:
                break
            window = corpus[max(0, index - 160): index + len(alias) + 160]
            if pattern.search(window):
                return True
            start = index + len(alias)
    return False


def evidence_source_kind(evidence: "EvidenceItem") -> str:
    assessment = evidence.diagnostics.get("source_assessment")
    if isinstance(assessment, dict):
        metadata = assessment.get("metadata")
        if isinstance(metadata, dict):
            source_kind = metadata.get("source_kind")
            if isinstance(source_kind, str):
                return source_kind.strip()
    source_kind = evidence.diagnostics.get("source_kind")
    if isinstance(source_kind, str):
        return source_kind.strip()
    return ""


def evidence_compaction_policy(profile: ResearchProfile | None) -> JsonObject:
    if profile is None:
        return {}
    policy = profile.metadata.get("evidence_compaction")
    return dict(policy) if isinstance(policy, dict) else {}


def _profile_numeric_fact_required(required_facets: list[str], *, profile: ResearchProfile | None) -> bool:
    numeric_facets = set(_string_list(profile_evidence_policy(profile).get("numeric_fact_facets")))
    return any(facet in numeric_facets for facet in required_facets)


def _numeric_pattern(profile: ResearchProfile | None) -> re.Pattern[str] | None:
    raw = profile_evidence_policy(profile).get("numeric_fact_pattern")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return re.compile(raw, re.IGNORECASE)
    except re.error:
        return None


def _string_list_map(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, raw_items in value.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        items = _string_list(raw_items)
        if items:
            result[key_text] = items
    return result


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value if isinstance(raw, str)) if item]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _marker_matches(text: str, marker: str) -> bool:
    marker = marker.strip().lower()
    if not marker:
        return False
    if re.search(r"[\u4e00-\u9fff]", marker):
        return marker in text
    if re.search(r"\s|[_:/.-]", marker):
        return marker in text
    return re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text) is not None
