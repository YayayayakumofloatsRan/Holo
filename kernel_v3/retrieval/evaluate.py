from __future__ import annotations

from kernel_v3.retrieval.contracts import (
    CitationItem,
    EvidenceEvaluationDecision,
    EvidenceItem,
    SearchGoal,
)
from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.source_policy import assess_evidence_source, source_authority_summary


QUERY_FACET_ALIASES: dict[str, tuple[str, ...]] = {
    "model": (
        "model",
        "models",
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v3",
        "deepseek-v4",
        "模型",
    ),
    "authentication": (
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
    ),
    "pricing": (
        "pricing",
        "price",
        "cost",
        "billing",
        "bill",
        "定价",
        "价格",
        "费用",
        "计费",
    ),
    "token": (
        "token",
        "tokens",
        "tokenizer",
        "context length",
        "上下文",
        "令牌",
    ),
    "rate_limit": (
        "rate limit",
        "rate-limit",
        "quota",
        "qps",
        "rpm",
        "limit",
        "限流",
        "额度",
        "配额",
    ),
    "endpoint": (
        "endpoint",
        "base url",
        "base_url",
        "api base",
        "host",
        "接口地址",
        "端点",
        "基础地址",
    ),
}

QUERY_FACET_TRIGGERS: dict[str, tuple[str, ...]] = {
    "model": ("model", "models", "模型"),
    "authentication": (
        "auth",
        "authentication",
        "authorization",
        "api key",
        "apikey",
        "鉴权",
        "认证",
        "授权",
        "密钥",
    ),
    "pricing": ("pricing", "price", "cost", "billing", "定价", "价格", "费用", "计费"),
    "token": ("token", "tokens", "tokenizer", "context length", "上下文", "令牌"),
    "rate_limit": ("rate limit", "rate-limit", "quota", "qps", "rpm", "限流", "额度", "配额"),
    "endpoint": ("endpoint", "base url", "base_url", "接口地址", "端点", "基础地址"),
}


class EvidenceEvaluator:
    def evaluate(
        self,
        *,
        goal: SearchGoal,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
        research_profile: ResearchProfile | None = None,
    ) -> EvidenceEvaluationDecision:
        diagnostics = {
            "query": goal.query,
            "max_fetches": goal.max_fetches,
            "max_spans_per_document": goal.max_spans_per_document,
        }
        sufficient = bool(evidence and citations)
        reason = "evidence_with_citations" if sufficient else "insufficient_evidence"
        facet_diagnostics = assess_query_facet_coverage(goal=goal, evidence=evidence)
        diagnostics.update(facet_diagnostics)
        if sufficient and facet_diagnostics["missing_query_facets"]:
            sufficient = False
            reason = "query_facets_missing"
        if research_profile is not None:
            assessments = [assess_evidence_source(item, profile=research_profile) for item in evidence]
            authority_summary = source_authority_summary(assessments)
            diagnostics["research_profile"] = research_profile.profile_id
            diagnostics["source_authority"] = authority_summary
            authority_requirement = _source_authority_requirement(goal)
            diagnostics["source_authority_requirement"] = authority_requirement
            if not evidence:
                sufficient = False
                reason = "insufficient_evidence"
            elif research_profile.citations_required and not citations:
                sufficient = False
                reason = "citations_required_by_research_profile"
            elif not _authority_satisfies(assessments, authority_requirement):
                sufficient = False
                reason = (
                    "no_primary_source_for_research_profile"
                    if authority_requirement == "primary"
                    else "no_required_authority_source_for_research_profile"
                )
        return EvidenceEvaluationDecision(
            decision_id=f"eval-{goal.goal_id}",
            goal_id=goal.goal_id,
            status="sufficient" if sufficient else "insufficient_evidence",
            sufficient=sufficient,
            reason=reason,
            evidence_count=len(evidence),
            citation_count=len(citations),
            diagnostics=diagnostics,
        )


def assess_query_facet_coverage(*, goal: SearchGoal, evidence: list[EvidenceItem]) -> dict[str, object]:
    required = query_facets(goal.query)
    corpus = "\n".join(item.text for item in evidence).lower()
    covered: list[str] = []
    missing: list[str] = []
    matched_aliases: dict[str, list[str]] = {}
    for facet in required:
        aliases = QUERY_FACET_ALIASES.get(facet, ())
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


def query_facets(query: str) -> list[str]:
    normalized = query.lower()
    facets = [
        facet
        for facet, triggers in QUERY_FACET_TRIGGERS.items()
        if any(trigger.lower() in normalized for trigger in triggers)
    ]
    return _ordered_unique(facets)


def _source_authority_requirement(goal: SearchGoal) -> str:
    value = goal.metadata.get("source_authority_requirement")
    if not isinstance(value, str):
        value = goal.metadata.get("authority_requirement")
    normalized = str(value or "primary").strip().lower()
    if normalized in {"secondary_or_better", "secondary_allowed", "secondary"}:
        return "secondary_or_better"
    if normalized in {"any", "any_citable"}:
        return "any_citable"
    return "primary"


def _authority_satisfies(assessments: object, requirement: str) -> bool:
    items = list(assessments) if isinstance(assessments, list) else []
    if requirement == "any_citable":
        return bool(items)
    if requirement == "secondary_or_better":
        return any(item.usable_as_primary or item.authority_level == "secondary" for item in items)
    return any(item.usable_as_primary for item in items)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
