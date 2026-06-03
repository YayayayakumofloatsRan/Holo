from __future__ import annotations

import re

from kernel_v3.retrieval.contracts import (
    CitationItem,
    EvidenceEvaluationDecision,
    EvidenceItem,
    SearchGoal,
)
from kernel_v3.research.profiles import FINANCE_FUNDAMENTALS_PROFILE_ID
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

FINANCE_FUNDAMENTAL_FACET_ALIASES: dict[str, tuple[str, ...]] = {
    "official_financial_statement": (
        "10-k",
        "10-q",
        "form 10-k",
        "form 10-q",
        "annual report",
        "quarterly report",
        "sec filing",
        "edgar",
        "companyfacts",
        "financial statements",
        "income statement",
        "balance sheet",
        "cash flow statement",
        "investor relations",
        "earnings release",
        "年报",
        "季报",
        "财务报表",
        "资产负债表",
        "现金流量表",
        "利润表",
    ),
    "financial_metric": (
        "revenue",
        "revenues",
        "total revenue",
        "total revenues",
        "net sales",
        "total net sales",
        "sales",
        "net income",
        "operating income",
        "profit margin",
        "margin",
        "gross margin",
        "operating margin",
        "cash flow",
        "free cash flow",
        "assets",
        "liabilities",
        "shareholders' equity",
        "shareholders equity",
        "earnings per share",
        "eps",
        "营收",
        "收入",
        "净利润",
        "营业利润",
        "利润率",
        "毛利率",
        "现金流",
        "资产",
        "负债",
        "每股收益",
    ),
    "revenue": ("revenue", "net sales", "sales", "total revenues", "营收", "收入"),
    "net_income": ("net income", "net income loss", "netincomeloss", "net earnings", "net profit", "净利润", "净收益"),
    "margin": ("margin", "gross margin", "operating margin", "profit margin", "利润率", "毛利率"),
    "cash_flow": (
        "cash flow",
        "operating cash flow",
        "cash provided by operating activities",
        "free cash flow",
        "现金流",
        "经营活动现金流",
    ),
    "balance_sheet": (
        "balance sheet",
        "assets",
        "liabilities",
        "equity",
        "shareholders' equity",
        "资产负债表",
        "资产",
        "负债",
        "股东权益",
    ),
    "valuation": (
        "p/e",
        "pe ratio",
        "price earnings",
        "market cap",
        "market capitalization",
        "stock price",
        "share price",
        "市盈率",
        "估值",
        "市值",
        "股价",
    ),
}

FINANCE_FUNDAMENTAL_FACET_TRIGGERS: dict[str, tuple[str, ...]] = {
    "official_financial_statement": (
        "financial statement",
        "financial statements",
        "financial information",
        "fundamental",
        "fundamentals",
        "10-k",
        "10-q",
        "annual report",
        "quarterly report",
        "sec",
        "edgar",
        "财务",
        "基本面",
        "年报",
        "季报",
    ),
    "financial_metric": (
        "financial information",
        "fundamental",
        "fundamentals",
        "key metric",
        "key metrics",
        "财务信息",
        "财务数据",
        "基本面",
        "关键指标",
    ),
    "revenue": ("revenue", "sales", "营收", "收入"),
    "net_income": ("net income", "net profit", "earnings", "净利润", "利润"),
    "margin": ("margin", "gross margin", "operating margin", "profit margin", "利润率", "毛利率"),
    "cash_flow": ("cash flow", "free cash flow", "现金流"),
    "balance_sheet": ("balance sheet", "assets", "liabilities", "资产负债表", "资产", "负债"),
    "valuation": ("p/e", "pe ratio", "market cap", "valuation", "stock price", "市盈率", "估值", "市值", "股价"),
}

FINANCE_FUNDAMENTAL_TASK_KINDS = {
    "fundamentals",
    "finance_fundamentals",
    "finance_fundamentals_research",
    "fundamentals_research",
}

FINANCE_NUMERIC_FACT_FACETS = {
    "financial_metric",
    "revenue",
    "net_income",
    "cash_flow",
    "balance_sheet",
    "valuation",
    "margin",
}

FINANCE_DISCOVERY_SOURCE_KINDS = {
    "sec_submissions_json",
    "sec_ticker_cik_directory",
    "sec_edgar_search",
    "sec_edgar_browse",
    "sec_filing_directory",
}

FINANCE_VALUE_PATTERN = re.compile(
    r"[$€£¥]\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?"
    r"|[$€£¥]\s*\d+(?:\.\d+)?"
    r"|\b(?:usd|dollars|shares)\b.{0,24}\b\d{2,}(?:,\d{3})*(?:\.\d+)?\b"
    r"|\b\d{2,}(?:,\d{3})*(?:\.\d+)?\b.{0,24}\b(?:usd|dollars|shares)\b"
    r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\s*(?:million|billion|trillion|mn|bn|usd|dollars|shares)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:million|billion|trillion|mn|bn|usd|dollars|shares)\b"
    r"|\b\d+(?:\.\d+)?\s*%"
    r"|(?:营收|收入|净利润|利润|现金流|资产|负债|市值|股价|市盈率|利润率).{0,20}\d+(?:\.\d+)?\s*(?:亿|万|元|人民币|美元|%)?",
    re.IGNORECASE,
)


def qualify_evidence_candidate(
    *,
    goal: SearchGoal,
    evidence: EvidenceItem,
    research_profile: ResearchProfile | None = None,
) -> dict[str, object]:
    source_kind = _evidence_source_kind(evidence)
    if _is_finance_profile(goal=goal, research_profile=research_profile) and source_kind in FINANCE_DISCOVERY_SOURCE_KINDS:
        return {
            "accepted": False,
            "reason": "finance_discovery_metadata_not_final_evidence",
            "covered_finance_facets": [],
            "missing_finance_facets": ["final_financial_fact"],
            "finance_numeric_fact_required": True,
            "finance_numeric_fact_present": False,
            "source_kind": source_kind,
        }
    required = finance_fundamental_facets(goal=goal, research_profile=research_profile)
    if not required:
        return {"accepted": True, "reason": "not_finance_fundamental_goal"}
    covered = _finance_text_facets(evidence.text, required)
    numeric_required = any(facet in FINANCE_NUMERIC_FACT_FACETS for facet in required)
    numeric_present = _finance_text_has_numeric_fact(evidence.text, required)
    missing = [facet for facet in required if facet not in set(covered)]
    if numeric_required and not numeric_present:
        missing.append("numeric_financial_fact")
    accepted = bool(numeric_present if numeric_required else covered)
    return {
        "accepted": accepted,
        "reason": "qualified_finance_evidence" if accepted else "missing_finance_fact_in_span",
        "covered_finance_facets": covered,
        "missing_finance_facets": _ordered_unique(missing),
        "finance_numeric_fact_required": numeric_required,
        "finance_numeric_fact_present": numeric_present,
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
        finance_diagnostics = assess_finance_fundamental_coverage(
            goal=goal,
            evidence=evidence,
            research_profile=research_profile,
        )
        diagnostics.update(finance_diagnostics)
        if sufficient and finance_diagnostics["finance_fundamental_required"] and finance_diagnostics["missing_finance_facets"]:
            sufficient = False
            reason = "finance_fundamental_facets_missing"
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


def assess_finance_fundamental_coverage(
    *,
    goal: SearchGoal,
    evidence: list[EvidenceItem],
    research_profile: ResearchProfile | None = None,
) -> dict[str, object]:
    required = finance_fundamental_facets(goal=goal, research_profile=research_profile)
    corpus = "\n".join(
        item.text
        for item in evidence
    ).lower()
    covered: list[str] = []
    missing: list[str] = []
    matched_aliases: dict[str, list[str]] = {}
    for facet in required:
        aliases = FINANCE_FUNDAMENTAL_FACET_ALIASES.get(facet, ())
        matches = [alias for alias in aliases if alias.lower() in corpus]
        if matches:
            covered.append(facet)
            matched_aliases[facet] = matches[:6]
        else:
            missing.append(facet)
    numeric_required = any(facet in FINANCE_NUMERIC_FACT_FACETS for facet in required)
    numeric_present = _finance_numeric_fact_present(evidence, required)
    if numeric_required and not numeric_present:
        missing.append("numeric_financial_fact")
    return {
        "finance_fundamental_required": bool(required),
        "finance_fundamental_facets": required,
        "covered_finance_facets": covered,
        "missing_finance_facets": _ordered_unique(missing),
        "finance_numeric_fact_required": numeric_required,
        "finance_numeric_fact_present": numeric_present,
        "finance_facet_coverage": 1.0 if not required else round(len(covered) / len(required), 4),
        "finance_facet_matches": matched_aliases,
    }


def finance_fundamental_facets(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> list[str]:
    if not _is_finance_fundamental_goal(goal=goal, research_profile=research_profile):
        return []
    normalized = goal.query.lower()
    facets = [
        facet
        for facet, triggers in FINANCE_FUNDAMENTAL_FACET_TRIGGERS.items()
        if any(trigger.lower() in normalized for trigger in triggers)
    ]
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    task_kind = str(metadata.get("research_task_kind") or metadata.get("task_kind") or "").strip().lower()
    if task_kind in FINANCE_FUNDAMENTAL_TASK_KINDS:
        facets.append("official_financial_statement")
    if not any(item in facets for item in ("financial_metric", "revenue", "net_income", "cash_flow", "balance_sheet", "valuation", "margin")):
        facets.append("financial_metric")
    return _ordered_unique(facets)


def _finance_numeric_fact_present(evidence: list[EvidenceItem], required_facets: list[str]) -> bool:
    return any(_finance_text_has_numeric_fact(item.text, required_facets) for item in evidence)


def _finance_text_has_numeric_fact(text: str, required_facets: list[str]) -> bool:
    if not text:
        return False
    aliases: list[str] = []
    for facet in required_facets:
        if facet not in FINANCE_NUMERIC_FACT_FACETS:
            continue
        aliases.extend(FINANCE_FUNDAMENTAL_FACET_ALIASES.get(facet, ()))
    if not aliases:
        aliases.extend(FINANCE_FUNDAMENTAL_FACET_ALIASES["financial_metric"])
    for alias in _ordered_unique([item.lower() for item in aliases if item]):
        corpus = text.lower()
        start = 0
        while True:
            index = corpus.find(alias, start)
            if index < 0:
                break
            window = corpus[max(0, index - 160): index + len(alias) + 160]
            if FINANCE_VALUE_PATTERN.search(window):
                return True
            start = index + len(alias)
    return False


def _finance_text_facets(text: str, required_facets: list[str]) -> list[str]:
    corpus = text.lower()
    covered: list[str] = []
    for facet in required_facets:
        aliases = FINANCE_FUNDAMENTAL_FACET_ALIASES.get(facet, ())
        if any(alias.lower() in corpus for alias in aliases):
            covered.append(facet)
    return covered


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


def _is_finance_fundamental_goal(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
    if not _is_finance_profile(goal=goal, research_profile=research_profile):
        return False
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    task_kind = str(metadata.get("research_task_kind") or metadata.get("task_kind") or "").strip().lower()
    if task_kind in FINANCE_FUNDAMENTAL_TASK_KINDS:
        return True
    if task_kind in {"market_data", "market_news", "macro_data", "competitive_landscape"}:
        return False
    query = goal.query.lower()
    if _is_sec_discovery_query(query):
        return False
    return any(
        marker in query
        for marker in (
            "fundamental",
            "fundamentals",
            "financial information",
            "financial statement",
            "financial statements",
            "10-k",
            "10-q",
            "annual report",
            "primary filing document",
            "companyfacts",
            "xbrl",
            "reported fundamentals",
            "基本面",
            "财务",
            "年报",
            "季报",
        )
    )


def _is_sec_discovery_query(query: str) -> bool:
    discovery_markers = (
        "accession",
        "primarydocument",
        "primary document",
        "submissions",
        "companyfacts submissions",
        "ticker cik",
        "cik directory",
        "company_tickers",
    )
    if not any(marker in query for marker in discovery_markers):
        return False
    evidence_markers = (
        "fundamental",
        "fundamentals",
        "revenue",
        "net income",
        "net sales",
        "profit",
        "margin",
        "cash flow",
        "balance sheet",
        "financial results",
        "financial statement",
        "财务",
        "基本面",
        "营收",
        "净利润",
    )
    if any(marker in query for marker in evidence_markers):
        return False
    return True


def is_discovery_goal(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
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
    query = goal.query.lower()
    if _is_finance_profile(goal=goal, research_profile=research_profile) and _is_sec_discovery_query(query):
        return True
    return False


def _is_finance_profile(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    profile_id = metadata.get("research_profile") or metadata.get("research_profile_id")
    if research_profile is not None:
        profile_id = research_profile.profile_id
    return profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID


def _evidence_source_kind(evidence: EvidenceItem) -> str:
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
