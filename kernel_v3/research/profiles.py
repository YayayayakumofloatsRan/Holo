from __future__ import annotations

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import ResearchProfile


FINANCE_FUNDAMENTALS_PROFILE_ID = "finance_fundamentals"
TECHNICAL_DOCUMENTATION_PROFILE_ID = "technical_documentation"
ACADEMIC_RESEARCH_PROFILE_ID = "academic_research"
RESEARCH_PROFILE_IDS = (
    FINANCE_FUNDAMENTALS_PROFILE_ID,
    TECHNICAL_DOCUMENTATION_PROFILE_ID,
    ACADEMIC_RESEARCH_PROFILE_ID,
)
RESEARCH_DEPTHS = ("light", "balanced", "deep")

FINANCE_FUNDAMENTAL_FACET_ALIASES: dict[str, list[str]] = {
    "official_financial_statement": [
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
    ],
    "financial_metric": [
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
    ],
    "revenue": ["revenue", "net sales", "sales", "total revenues", "营收", "收入"],
    "net_income": ["net income", "net income loss", "netincomeloss", "net earnings", "net profit", "净利润", "净收益"],
    "eps": [
        "eps",
        "earnings per share",
        "diluted earnings per share",
        "basic earnings per share",
        "earningspersharediluted",
        "earningspersharebasic",
        "每股收益",
        "摊薄每股收益",
        "基本每股收益",
    ],
    "margin": ["margin", "gross margin", "operating margin", "profit margin", "利润率", "毛利率"],
    "cash_flow": [
        "cash flow",
        "operating cash flow",
        "cash provided by operating activities",
        "free cash flow",
        "现金流",
        "经营活动现金流",
    ],
    "balance_sheet": [
        "balance sheet",
        "assets",
        "liabilities",
        "equity",
        "shareholders' equity",
        "资产负债表",
        "资产",
        "负债",
        "股东权益",
    ],
    "valuation": [
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
    ],
}

FINANCE_FUNDAMENTAL_FACET_TRIGGERS: dict[str, list[str]] = {
    "official_financial_statement": [
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
    ],
    "financial_metric": [
        "financial information",
        "fundamental",
        "fundamentals",
        "key metric",
        "key metrics",
        "财务信息",
        "财务数据",
        "基本面",
        "关键指标",
    ],
    "revenue": ["revenue", "sales", "营收", "收入"],
    "net_income": ["net income", "net profit", "earnings", "净利润", "利润"],
    "eps": ["eps", "earnings per share", "每股收益"],
    "margin": ["margin", "gross margin", "operating margin", "profit margin", "利润率", "毛利率"],
    "cash_flow": ["cash flow", "free cash flow", "现金流"],
    "balance_sheet": ["balance sheet", "assets", "liabilities", "资产负债表", "资产", "负债"],
    "valuation": ["p/e", "pe ratio", "market cap", "valuation", "stock price", "市盈率", "估值", "市值", "股价"],
}

FINANCE_FUNDAMENTAL_TASK_KINDS = [
    "fundamentals",
    "finance_fundamentals",
    "finance_fundamentals_research",
    "fundamentals_research",
]

FINANCE_NUMERIC_FACT_FACETS = [
    "financial_metric",
    "revenue",
    "net_income",
    "eps",
    "cash_flow",
    "balance_sheet",
    "valuation",
    "margin",
]

FINANCE_DISCOVERY_SOURCE_KINDS = [
    "sec_submissions_json",
    "sec_ticker_cik_directory",
    "sec_edgar_search",
    "sec_edgar_browse",
    "sec_filing_directory",
]

FINANCE_VALUE_PATTERN = (
    r"[$€£¥]\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?"
    r"|[$€£¥]\s*\d+(?:\.\d+)?"
    r"|\b(?:usd|dollars|shares)\b.{0,24}\b\d{2,}(?:,\d{3})*(?:\.\d+)?\b"
    r"|\b\d{2,}(?:,\d{3})*(?:\.\d+)?\b.{0,24}\b(?:usd|dollars|shares)\b"
    r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\s*(?:million|billion|trillion|mn|bn|usd|dollars|shares)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:million|billion|trillion|mn|bn|usd|dollars|shares)\b"
    r"|\b\d+(?:\.\d+)?\s*%"
    r"|(?:营收|收入|净利润|利润|现金流|资产|负债|市值|股价|市盈率|利润率).{0,20}\d+(?:\.\d+)?\s*(?:亿|万|元|人民币|美元|%)?"
)

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
        "max_queries": 64,
        "max_sources": 2_000,
        "max_fetches": 1_024,
        "max_spans_per_document": 48,
    },
    "deep": {
        "max_queries": 128,
        "max_sources": 5_000,
        "max_fetches": 2_048,
        "max_spans_per_document": 64,
    },
}

_TECHNICAL_DOC_QUERY_TEMPLATES = [
    "{query}",
    "{query} official documentation",
    "{query} API reference authentication endpoint",
    "{query} developer docs parameters examples",
    "{query} rate limits errors SDK docs",
]

_TECHNICAL_DOC_DEPTH_DEFAULTS: dict[str, JsonObject] = {
    "light": {
        "max_queries": 3,
        "max_sources": 20,
        "max_fetches": 8,
        "max_spans_per_document": 4,
    },
    "balanced": {
        "max_queries": 32,
        "max_sources": 500,
        "max_fetches": 128,
        "max_spans_per_document": 16,
    },
    "deep": {
        "max_queries": 64,
        "max_sources": 1_000,
        "max_fetches": 256,
        "max_spans_per_document": 24,
    },
}

ACADEMIC_RESEARCH_FACET_ALIASES: dict[str, list[str]] = {
    "scholarly_work": [
        "paper",
        "preprint",
        "article",
        "journal",
        "conference",
        "proceedings",
        "arxiv",
        "doi",
        "论文",
        "预印本",
        "期刊",
        "会议",
        "学术",
    ],
    "frontier_or_recent": [
        "recent",
        "latest",
        "frontier",
        "state of the art",
        "open problem",
        "survey",
        "review",
        "综述",
        "前沿",
        "最新",
        "开放问题",
        "研究进展",
    ],
    "method_or_result": [
        "theorem",
        "proof",
        "method",
        "result",
        "experiment",
        "algorithm",
        "model",
        "定理",
        "证明",
        "方法",
        "结果",
        "实验",
        "算法",
        "模型",
    ],
    "bibliographic_metadata": [
        "author",
        "authors",
        "abstract",
        "citation",
        "cited by",
        "venue",
        "year",
        "doi",
        "arxiv",
        "作者",
        "摘要",
        "引用",
        "发表",
        "年份",
    ],
}

ACADEMIC_RESEARCH_FACET_TRIGGERS: dict[str, list[str]] = {
    "scholarly_work": [
        "paper",
        "papers",
        "literature",
        "research",
        "academic",
        "scholarly",
        "论文",
        "文献",
        "研究",
        "学术",
    ],
    "frontier_or_recent": [
        "frontier",
        "frontiers",
        "latest",
        "recent",
        "state of the art",
        "open problem",
        "前沿",
        "最新",
        "进展",
        "开放问题",
    ],
    "method_or_result": [
        "method",
        "methods",
        "theorem",
        "proof",
        "result",
        "experiment",
        "方法",
        "定理",
        "证明",
        "结果",
        "实验",
    ],
    "bibliographic_metadata": [
        "citation",
        "doi",
        "arxiv",
        "author",
        "venue",
        "引用",
        "作者",
        "期刊",
        "会议",
    ],
}

ACADEMIC_RESEARCH_TASK_KINDS = [
    "academic_research",
    "frontier_research",
    "literature_review",
    "paper_search",
    "scholarly_research",
]

ACADEMIC_DISCOVERY_SOURCE_KINDS = [
    "scholarly_search",
    "scholarly_index_search",
    "academic_source_directory",
]

_ACADEMIC_QUERY_TEMPLATES = [
    "{query}",
    "{query} arXiv recent papers survey",
    "{query} state of the art survey review open problems",
    "{query} academic paper literature review",
    "{query} site:arxiv.org/abs",
    "{query} Semantic Scholar papers",
    "{query} OpenAlex works",
    "{query} DOI journal article",
]

_ACADEMIC_DEPTH_DEFAULTS: dict[str, JsonObject] = {
    "light": {
        "max_queries": 4,
        "max_sources": 30,
        "max_fetches": 12,
        "max_spans_per_document": 4,
    },
    "balanced": {
        "max_queries": 8,
        "max_sources": 80,
        "max_fetches": 24,
        "max_spans_per_document": 8,
    },
    "deep": {
        "max_queries": 24,
        "max_sources": 240,
        "max_fetches": 72,
        "max_spans_per_document": 16,
    },
}

TECHNICAL_DOC_FACET_ALIASES: dict[str, list[str]] = {
    "endpoint": ["endpoint", "base url", "base_url", "api base", "host", "接口地址", "端点", "基础地址"],
    "authentication": [
        "authentication",
        "authorization",
        "bearer",
        "api key",
        "apikey",
        "secret key",
        "鉴权",
        "认证",
        "授权",
        "密钥",
    ],
    "parameters": ["parameter", "parameters", "request body", "query parameter", "payload", "参数", "请求体"],
    "response_schema": ["response", "response schema", "returns", "json", "响应", "返回"],
    "rate_limit": ["rate limit", "quota", "rpm", "qps", "限流", "额度", "配额"],
    "pricing": ["pricing", "price", "cost", "billing", "定价", "价格", "费用", "计费"],
    "example": ["example", "curl", "python", "javascript", "示例", "例子"],
}

TECHNICAL_DOC_FACET_TRIGGERS: dict[str, list[str]] = {
    "endpoint": ["endpoint", "base url", "api base", "接口地址", "端点", "基础地址"],
    "authentication": ["auth", "authentication", "authorization", "api key", "apikey", "鉴权", "认证", "授权", "密钥"],
    "parameters": ["parameter", "request", "payload", "参数", "请求体"],
    "response_schema": ["response", "schema", "返回", "响应"],
    "rate_limit": ["rate limit", "quota", "qps", "rpm", "限流", "额度", "配额"],
    "pricing": ["pricing", "price", "cost", "billing", "定价", "价格", "费用", "计费"],
    "example": ["example", "curl", "python", "javascript", "示例", "例子"],
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
            "central_bank_statistic",
            "treasury_data",
            "fund_disclosure",
        ],
        secondary_source_families=[
            "reputable_news",
            "market_data_provider",
            "credit_rating_agency",
            "earnings_transcript",
            "portfolio_risk_data_provider",
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
            "default_research_depth": "deep",
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
                    "central_bank_statistic",
                    "treasury_data",
                    "fund_disclosure",
                ],
            },
            "evidence_policy": {
                "policy_id": "finance_fundamentals_evidence",
                "facet_aliases": FINANCE_FUNDAMENTAL_FACET_ALIASES,
                "facet_triggers": FINANCE_FUNDAMENTAL_FACET_TRIGGERS,
                "task_kinds": FINANCE_FUNDAMENTAL_TASK_KINDS,
                "excluded_task_kinds": ["market_data", "market_news", "macro_data", "competitive_landscape"],
                "default_facets": ["financial_metric"],
                "task_default_facets": ["official_financial_statement"],
                "numeric_fact_facets": FINANCE_NUMERIC_FACT_FACETS,
                "numeric_fact_pattern": FINANCE_VALUE_PATTERN,
                "discovery_source_kinds": FINANCE_DISCOVERY_SOURCE_KINDS,
                "discovery_query_markers": [
                    "accession",
                    "primarydocument",
                    "primary document",
                    "submissions",
                    "companyfacts submissions",
                    "ticker cik",
                    "cik directory",
                    "company_tickers",
                    "directory",
                    "filing history",
                    "search",
                    "series search",
                    "macro series",
                    "announcement",
                    "announcements",
                ],
                "discovery_evidence_markers": [
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
                ],
            },
            "evidence_compaction": {
                "strategy_id": "profile_facet_authority_compaction",
                "max_items": 16,
                "per_source_limit": 6,
                "prefer_authority": True,
                "prefer_facet_coverage": True,
            },
            "research_depths": {
                key: dict(value)
                for key, value in _FINANCE_DEPTH_DEFAULTS.items()
            },
        },
    )


def technical_documentation_profile() -> ResearchProfile:
    return ResearchProfile(
        profile_id=TECHNICAL_DOCUMENTATION_PROFILE_ID,
        domain="technical_documentation",
        description="Technical documentation research with official-doc and source-reference preference.",
        primary_source_families=[
            "official_documentation",
            "source_repository",
            "standards_body",
            "official_guidance",
        ],
        secondary_source_families=[
            "reputable_news",
            "generic_web",
        ],
        weak_source_families=[
            "blog",
            "forum",
            "social",
            "unknown",
        ],
        minimum_primary_authority_score=0.8,
        citations_required=True,
        metadata={
            "default_output_boundary": "documented_facts_examples_limitations",
            "freshness_max_age_ms": 7776000000,
            "default_research_depth": "balanced",
            "query_strategy": {
                "strategy_id": "technical_docs_expansion",
                "templates": list(_TECHNICAL_DOC_QUERY_TEMPLATES),
                "preferred_source_families": [
                    "official_documentation",
                    "source_repository",
                    "standards_body",
                    "official_guidance",
                ],
            },
            "evidence_policy": {
                "policy_id": "technical_documentation_evidence",
                "facet_aliases": TECHNICAL_DOC_FACET_ALIASES,
                "facet_triggers": TECHNICAL_DOC_FACET_TRIGGERS,
                "task_kinds": ["technical_documentation", "api_documentation", "developer_docs"],
                "default_facets": ["endpoint", "authentication"],
                "task_default_facets": [],
                "numeric_fact_facets": [],
                "discovery_source_kinds": ["docs_search_index", "repository_search", "site_search"],
                "discovery_query_markers": ["search index", "site search", "repository search"],
                "discovery_evidence_markers": ["endpoint", "authentication", "parameter", "response", "example"],
            },
            "evidence_compaction": {
                "strategy_id": "profile_facet_authority_compaction",
                "max_items": 12,
                "per_source_limit": 5,
                "prefer_authority": True,
                "prefer_facet_coverage": True,
            },
            "research_depths": {
                key: dict(value)
                for key, value in _TECHNICAL_DOC_DEPTH_DEFAULTS.items()
            },
        },
    )


def academic_research_profile() -> ResearchProfile:
    return ResearchProfile(
        profile_id=ACADEMIC_RESEARCH_PROFILE_ID,
        domain="academic_research",
        description="Scholarly research with paper, preprint, publisher, and academic-index source preference.",
        primary_source_families=[
            "scholarly_preprint",
            "scholarly_publisher",
            "academic_repository",
            "standards_body",
        ],
        secondary_source_families=[
            "scholarly_index",
            "reputable_news",
        ],
        weak_source_families=[
            "reference_dictionary",
            "encyclopedia",
            "generic_web",
            "blog",
            "forum",
            "social",
            "unknown",
        ],
        minimum_primary_authority_score=0.78,
        citations_required=True,
        metadata={
            "default_output_boundary": "scholarly_facts_methods_open_questions_limitations",
            "default_research_depth": "balanced",
            "query_strategy": {
                "strategy_id": "academic_scholarly_expansion",
                "templates": list(_ACADEMIC_QUERY_TEMPLATES),
                "preferred_source_families": [
                    "scholarly_preprint",
                    "scholarly_publisher",
                    "academic_repository",
                    "scholarly_index",
                ],
            },
            "evidence_policy": {
                "policy_id": "academic_research_evidence",
                "facet_aliases": ACADEMIC_RESEARCH_FACET_ALIASES,
                "facet_triggers": ACADEMIC_RESEARCH_FACET_TRIGGERS,
                "task_kinds": ACADEMIC_RESEARCH_TASK_KINDS,
                "default_facets": ["scholarly_work"],
                "task_default_facets": ["bibliographic_metadata"],
                "numeric_fact_facets": [],
                "discovery_source_kinds": ACADEMIC_DISCOVERY_SOURCE_KINDS,
                "discovery_query_markers": ["search", "index", "catalog", "directory"],
                "discovery_evidence_markers": [
                    "paper",
                    "preprint",
                    "article",
                    "journal",
                    "doi",
                    "arxiv",
                    "论文",
                    "文献",
                ],
            },
            "evidence_compaction": {
                "strategy_id": "profile_facet_authority_compaction",
                "max_items": 14,
                "per_source_limit": 4,
                "prefer_authority": True,
                "prefer_facet_coverage": True,
            },
            "research_depths": {
                key: dict(value)
                for key, value in _ACADEMIC_DEPTH_DEFAULTS.items()
            },
        },
    )


def profile_by_id(profile_id: str | None) -> ResearchProfile | None:
    if profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID:
        return finance_fundamentals_profile()
    if profile_id == TECHNICAL_DOCUMENTATION_PROFILE_ID:
        return technical_documentation_profile()
    if profile_id == ACADEMIC_RESEARCH_PROFILE_ID:
        return academic_research_profile()
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
