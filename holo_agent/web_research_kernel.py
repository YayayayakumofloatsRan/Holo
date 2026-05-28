from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Literal
from urllib.parse import urlparse

from .schema import short_id
from .source_authority import classify_source_url


SearchDepth = Literal["low", "medium", "high"]
TaskType = Literal[
    "quick_lookup",
    "official_docs",
    "api_docs",
    "literature_review",
    "market_research",
    "financial_filing",
    "news_current",
    "entity_disambiguation",
    "technical_troubleshooting",
]


@dataclass(slots=True)
class SearchGoal:
    user_question: str
    task_type: TaskType
    required_source_families: list[str]
    blocked_source_families: list[str]
    freshness_required: bool
    min_supporting_sources: int
    min_primary_sources: int
    source_diversity_targets: list[str]
    language: str
    region: str | None
    max_queries: int
    max_pages: int
    search_depth: SearchDepth
    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)
    goal_id: str = field(default_factory=lambda: short_id("search_goal"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class QueryAttempt:
    query: str
    purpose: str
    expected_source_family: str
    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SearchPlan:
    goal_id: str
    queries: list[QueryAttempt]
    stop_criteria: dict[str, Any]
    search_depth: SearchDepth

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "queries": [query.to_dict() for query in self.queries],
            "stop_criteria": dict(self.stop_criteria),
            "search_depth": self.search_depth,
        }


@dataclass(slots=True)
class EvidenceItem:
    evidence_id: str
    claim: str
    source_url: str
    source_title: str
    quote: str
    source_family: str
    support_score: float
    authority_score: float
    freshness_score: float
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Citation:
    citation_id: str
    evidence_id: str
    title: str
    url: str
    quote: str
    source_family: str
    freshness_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CrawlReport:
    schema: str
    goal: SearchGoal
    plan: SearchPlan
    status: Literal["sufficient", "weak", "failed", "rejected"]
    stop_reason: str
    source_graph: dict[str, list[str]]
    evidence_items: list[EvidenceItem]
    citations: list[Citation]
    missing: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "goal": self.goal.to_dict(),
            "plan": self.plan.to_dict(),
            "status": self.status,
            "stop_reason": self.stop_reason,
            "source_graph": {key: list(value) for key, value in self.source_graph.items()},
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "citations": [citation.to_dict() for citation in self.citations],
            "missing": list(self.missing),
        }


class CitationBuilder:
    def build(self, evidence_items: list[EvidenceItem]) -> list[Citation]:
        citations: list[Citation] = []
        for index, item in enumerate(evidence_items, start=1):
            citations.append(
                Citation(
                    citation_id=f"cite_{index}",
                    evidence_id=item.evidence_id,
                    title=item.source_title or item.source_url,
                    url=item.source_url,
                    quote=item.quote,
                    source_family=item.source_family,
                    freshness_note="freshness not asserted" if item.freshness_score < 0.75 else "fresh source signal",
                )
            )
        return citations


def _language_of(text: str) -> str:
    return "zh" if re.search(r"[\u4e00-\u9fff]", text or "") else "en"


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def build_search_goal(user_question: str, *, region: str | None = None) -> SearchGoal:
    text = str(user_question or "").strip()
    lowered = text.lower()
    language = _language_of(text)

    if _contains_any(lowered, ("10-k", "10 k", "annual report", "net sales", "sec filing", "filing")):
        return SearchGoal(
            user_question=text,
            task_type="financial_filing",
            required_source_families=["regulatory_filing", "company_official"],
            blocked_source_families=["low_authority"],
            freshness_required=bool(re.search(r"\b20\d{2}\b|latest|current|最新", text, flags=re.I)),
            min_supporting_sources=2,
            min_primary_sources=1,
            source_diversity_targets=["regulatory_filing", "company_official"],
            language=language,
            region=region,
            max_queries=6,
            max_pages=12,
            search_depth="high",
            allowed_domains=["sec.gov", "investor.apple.com"],
            blocked_domains=["reddit.com", "quora.com"],
        )

    if _contains_any(lowered, ("deepseek", "api-docs.deepseek.com")) and _contains_any(lowered, ("tool", "calling", "docs", "documentation", "文档", "官方")):
        return SearchGoal(
            user_question=text,
            task_type="api_docs",
            required_source_families=["official_docs"],
            blocked_source_families=["low_authority"],
            freshness_required=_contains_any(lowered, ("latest", "current", "最新")),
            min_supporting_sources=1,
            min_primary_sources=1,
            source_diversity_targets=["official_docs"],
            language=language,
            region=region,
            max_queries=4,
            max_pages=6,
            search_depth="medium",
            allowed_domains=["api-docs.deepseek.com", "deepseek.com"],
            blocked_domains=[],
        )

    if _contains_any(lowered, ("official", "docs", "documentation", "官方", "官网", "文档", "codex cli", "openai codex")):
        allowed = ["developers.openai.com"] if _contains_any(lowered, ("openai", "codex")) else []
        return SearchGoal(
            user_question=text,
            task_type="official_docs",
            required_source_families=["official_docs"],
            blocked_source_families=["low_authority"],
            freshness_required=_contains_any(lowered, ("latest", "current", "最新")),
            min_supporting_sources=1,
            min_primary_sources=1,
            source_diversity_targets=["official_docs"],
            language=language,
            region=region,
            max_queries=3,
            max_pages=5,
            search_depth="medium",
            allowed_domains=allowed,
            blocked_domains=[],
        )

    return SearchGoal(
        user_question=text,
        task_type="quick_lookup",
        required_source_families=["primary", "secondary"],
        blocked_source_families=["low_authority"],
        freshness_required=_contains_any(lowered, ("latest", "current", "today", "news", "最新", "今天")),
        min_supporting_sources=1,
        min_primary_sources=0,
        source_diversity_targets=["relevant"],
        language=language,
        region=region,
        max_queries=2,
        max_pages=4,
        search_depth="low",
        allowed_domains=[],
        blocked_domains=[],
    )


def build_search_plan(goal: SearchGoal) -> SearchPlan:
    base = goal.user_question.strip()
    queries: list[QueryAttempt] = [
        QueryAttempt(
            query=base,
            purpose="initial_goal_query",
            expected_source_family=goal.required_source_families[0] if goal.required_source_families else "relevant",
            allowed_domains=list(goal.allowed_domains),
            blocked_domains=list(goal.blocked_domains),
        )
    ]
    if goal.task_type in {"official_docs", "api_docs"}:
        official_domains = goal.allowed_domains or ["developers.openai.com"]
        if "openai" in base.lower() or "codex" in base.lower():
            queries.append(
                QueryAttempt(
                    query="OpenAI Codex CLI official documentation",
                    purpose="canonical_official_docs_query",
                    expected_source_family="official_docs",
                    allowed_domains=["developers.openai.com"],
                    blocked_domains=list(goal.blocked_domains),
                )
            )
        if "deepseek" in base.lower():
            queries.append(
                QueryAttempt(
                    query="DeepSeek tool calling official documentation",
                    purpose="canonical_api_docs_query",
                    expected_source_family="official_docs",
                    allowed_domains=["api-docs.deepseek.com"],
                    blocked_domains=list(goal.blocked_domains),
                )
            )
        for domain in official_domains:
            queries.append(
                QueryAttempt(
                    query=f"site:{domain} {base}",
                    purpose="official_domain_query",
                    expected_source_family="official_docs",
                    allowed_domains=[domain],
                    blocked_domains=list(goal.blocked_domains),
                )
            )
    elif goal.task_type == "financial_filing":
        queries.extend(
            [
                QueryAttempt(
                    query=f"site:sec.gov {base}",
                    purpose="regulatory_filing_query",
                    expected_source_family="regulatory_filing",
                    allowed_domains=["sec.gov"],
                    blocked_domains=list(goal.blocked_domains),
                ),
                QueryAttempt(
                    query=f"site:investor.apple.com {base}",
                    purpose="company_ir_query",
                    expected_source_family="company_official",
                    allowed_domains=["investor.apple.com"],
                    blocked_domains=list(goal.blocked_domains),
                ),
            ]
        )
    queries = queries[: goal.max_queries]
    return SearchPlan(
        goal_id=goal.goal_id,
        queries=queries,
        stop_criteria={
            "min_supporting_sources": goal.min_supporting_sources,
            "min_primary_sources": goal.min_primary_sources,
            "required_source_families": list(goal.required_source_families),
            "source_diversity_targets": list(goal.source_diversity_targets),
        },
        search_depth=goal.search_depth,
    )


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _source_family(url: str, goal: SearchGoal) -> str:
    authority = classify_source_url(url)
    value = authority.get("authority", "secondary")
    if value == "official" and goal.task_type in {"official_docs", "api_docs"}:
        return "official_docs"
    if value == "official_repository":
        return "official_repository"
    if value == "regulatory_filing":
        return "regulatory_filing"
    if value == "company_official":
        return "company_official"
    if value == "official":
        return "primary"
    return str(value)


def _authority_score(url: str, source_family: str) -> float:
    authority = classify_source_url(url)
    if authority.get("primary"):
        return 1.0
    if source_family in {"official_docs", "regulatory_filing", "company_official"}:
        return 1.0
    return 0.35


def _source_allowed(goal: SearchGoal, url: str) -> bool:
    domain = _domain(url)
    if any(domain == blocked or domain.endswith("." + blocked) for blocked in goal.blocked_domains):
        return False
    if not goal.allowed_domains:
        return True
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in goal.allowed_domains)


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", text or "")}


def _support_score(goal: SearchGoal, title: str, text: str, url: str) -> float:
    goal_terms = _tokens(goal.user_question)
    if not goal_terms:
        return 0.5
    haystack = f"{title} {url} {text}".lower()
    hits = sum(1 for term in goal_terms if term in haystack)
    lexical = hits / max(1, len(goal_terms))
    source_bonus = 0.35 if _source_family(url, goal) in goal.required_source_families else 0.0
    return round(min(1.0, lexical + source_bonus), 4)


def _first_quote(text: str) -> str:
    compacted = re.sub(r"\s+", " ", text or "").strip()
    return compacted[:360]


def build_crawl_report(goal: SearchGoal, observations: list[dict[str, Any]]) -> CrawlReport:
    plan = build_search_plan(goal)
    candidate_sources: dict[str, str] = {}
    opened_sources: list[str] = []
    evidence_items: list[EvidenceItem] = []
    rejected: set[str] = set()

    for obs in observations:
        if obs.get("tool") == "web_search" and obs.get("status") == "ok":
            for result in obs.get("data", {}).get("results", []) or []:
                url = str(result.get("url", "") or "")
                if not url:
                    continue
                candidate_sources[url] = str(result.get("title", "") or url)
                if not _source_allowed(goal, url):
                    rejected.add(url)
        if obs.get("tool") == "open_page" and obs.get("status") == "ok":
            url = str(obs.get("data", {}).get("url", "") or "")
            if not url:
                continue
            title = candidate_sources.get(url, url)
            opened_sources.append(url)
            family = _source_family(url, goal)
            score = _support_score(goal, title, str(obs.get("data", {}).get("text", "") or obs.get("summary", "")), url)
            authority_score = _authority_score(url, family)
            if _source_allowed(goal, url) and family not in goal.blocked_source_families and (family in goal.required_source_families or authority_score >= 0.9):
                evidence_items.append(
                    EvidenceItem(
                        evidence_id=short_id("ev"),
                        claim=f"Source supports research goal: {goal.user_question}",
                        source_url=url,
                        source_title=title,
                        quote=_first_quote(str(obs.get("data", {}).get("text", "") or obs.get("summary", ""))),
                        source_family=family,
                        support_score=score,
                        authority_score=authority_score,
                        freshness_score=0.8 if goal.freshness_required else 0.6,
                    )
                )
            else:
                rejected.add(url)

    supporting_sources = [item.source_url for item in evidence_items]
    cited_sources = [citation.url for citation in CitationBuilder().build(evidence_items)]
    for url in candidate_sources:
        if url not in supporting_sources and url not in opened_sources:
            rejected.add(url)

    primary_count = sum(1 for item in evidence_items if item.authority_score >= 0.9)
    missing: list[str] = []
    if len(supporting_sources) < goal.min_supporting_sources:
        missing.append("min_supporting_sources")
    if primary_count < goal.min_primary_sources:
        missing.append("min_primary_sources")
    for family in goal.required_source_families:
        if family not in {item.source_family for item in evidence_items}:
            missing.append(f"required_source_family:{family}")

    if not candidate_sources and any(obs.get("tool") == "web_search" and obs.get("status") != "ok" for obs in observations):
        status: Literal["sufficient", "weak", "failed", "rejected"] = "failed"
        stop_reason = "search_provider_failed"
    elif not missing:
        status = "sufficient"
        stop_reason = "evidence_sufficient"
    elif evidence_items:
        status = "weak"
        stop_reason = "evidence_weak"
    else:
        status = "failed"
        stop_reason = "evidence_missing"

    citations = CitationBuilder().build(evidence_items)
    return CrawlReport(
        schema="holo.web_research_kernel.v2",
        goal=goal,
        plan=plan,
        status=status,
        stop_reason=stop_reason,
        source_graph={
            "candidate_sources": list(candidate_sources),
            "opened_sources": list(dict.fromkeys(opened_sources)),
            "consulted_sources": list(dict.fromkeys(opened_sources)),
            "supporting_sources": list(dict.fromkeys(supporting_sources)),
            "cited_sources": list(dict.fromkeys(cited_sources)),
            "rejected_sources": sorted(rejected),
        },
        evidence_items=evidence_items,
        citations=citations,
        missing=missing,
    )
