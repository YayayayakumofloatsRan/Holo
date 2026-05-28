from __future__ import annotations

from holo_agent.schema import Decision
from holo_agent.web_research_kernel import (
    CitationBuilder,
    EvidenceItem,
    SearchGoal,
    build_crawl_report,
    build_search_goal,
    build_search_plan,
)
from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.tools import OpenPageTool, ToolRegistry, WebClient, WebSearchTool


def test_search_goal_models_official_docs_source_policy() -> None:
    goal = build_search_goal("联网搜索 OpenAI Codex CLI 官方文档")

    assert goal.task_type == "official_docs"
    assert "official_docs" in goal.required_source_families
    assert goal.min_primary_sources >= 1
    assert goal.search_depth in {"low", "medium"}
    assert "developers.openai.com" in goal.allowed_domains


def test_search_goal_models_financial_filing_policy() -> None:
    goal = build_search_goal("Apple 2024 10-K net sales")

    assert goal.task_type == "financial_filing"
    assert "regulatory_filing" in goal.required_source_families
    assert "company_official" in goal.required_source_families
    assert goal.min_primary_sources >= 1
    assert goal.search_depth == "high"
    assert "sec.gov" in goal.allowed_domains


def test_search_plan_uses_goal_not_plain_query_rewrite() -> None:
    goal = build_search_goal("DeepSeek tool calling docs official")

    plan = build_search_plan(goal)

    assert plan.goal_id == goal.goal_id
    assert len(plan.queries) >= 2
    assert any(query.expected_source_family == "official_docs" for query in plan.queries)
    assert any("api-docs.deepseek.com" in query.allowed_domains for query in plan.queries)
    assert plan.stop_criteria["min_primary_sources"] == goal.min_primary_sources


def test_crawl_report_separates_source_buckets_and_citations() -> None:
    goal = SearchGoal(
        user_question="Find official Codex CLI docs",
        task_type="official_docs",
        required_source_families=["official_docs"],
        blocked_source_families=["low_authority"],
        freshness_required=False,
        min_supporting_sources=1,
        min_primary_sources=1,
        source_diversity_targets=["official"],
        language="en",
        region=None,
        max_queries=2,
        max_pages=3,
        search_depth="medium",
        allowed_domains=["developers.openai.com"],
        blocked_domains=[],
    )
    observations = [
        {
            "tool": "web_search",
            "status": "ok",
            "data": {
                "query": "OpenAI Codex CLI official documentation",
                "results": [
                    {"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "Official docs"},
                    {"title": "Blog", "url": "https://example.com/codex", "snippet": "Unofficial notes"},
                ],
            },
        },
        {
            "tool": "open_page",
            "status": "ok",
            "summary": "Codex CLI is a local coding agent.",
            "data": {
                "url": "https://developers.openai.com/codex/cli",
                "text": "Codex CLI is a local coding agent. It runs in your terminal and works with your code.",
            },
        },
    ]

    report = build_crawl_report(goal, observations)

    assert report.status == "sufficient"
    assert report.source_graph["candidate_sources"]
    assert report.source_graph["opened_sources"] == ["https://developers.openai.com/codex/cli"]
    assert report.source_graph["supporting_sources"] == ["https://developers.openai.com/codex/cli"]
    assert report.source_graph["cited_sources"] == ["https://developers.openai.com/codex/cli"]
    assert report.source_graph["rejected_sources"] == ["https://example.com/codex"]
    assert report.citations[0].url == "https://developers.openai.com/codex/cli"


def test_citation_builder_uses_evidence_items_not_freeform_sources() -> None:
    item = EvidenceItem(
        evidence_id="ev_1",
        claim="Codex CLI runs in a terminal.",
        source_url="https://developers.openai.com/codex/cli",
        source_title="Codex CLI",
        quote="Codex CLI is a local coding agent that runs in your terminal.",
        source_family="official_docs",
        support_score=0.92,
        authority_score=1.0,
        freshness_score=0.6,
    )

    citations = CitationBuilder().build([item])

    assert len(citations) == 1
    assert citations[0].evidence_id == "ev_1"
    assert citations[0].source_family == "official_docs"
    assert "terminal" in citations[0].quote


def test_agent_metadata_includes_search_goal_and_crawl_report(tmp_path) -> None:
    class Client(WebClient):
        def search(self, query: str, *, max_results: int = 5):
            return [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "Official docs"}]

        def fetch_text(self, url: str) -> str:
            return "Codex CLI is a local coding agent that runs in your terminal."

    class Model:
        def decide(self, *, user_text: str, context: dict, action_space: list[dict]) -> Decision:
            if not context["observations"]:
                assert context["search_goal"]["task_type"] == "official_docs"
                return Decision(action="web_search", arguments={"query": "OpenAI Codex CLI official documentation"}, can_answer=False)
            if len(context["observations"]) == 1:
                return Decision(action="open_page", arguments={"url": "https://developers.openai.com/codex/cli"}, can_answer=False)
            assert context["crawl_report"]["status"] == "sufficient"
            return Decision(action="answer_direct", can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict], context: dict) -> str:
            return "Official source found: https://developers.openai.com/codex/cli"

        def evaluate_source(self, *, query: str, source: dict, page_text: str, trajectory: list[dict]) -> dict:
            return {"accepted": True}

    client = Client()
    result = HoloAgent(
        tools=ToolRegistry([WebSearchTool(client), OpenPageTool(client)]),
        model=Model(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Find official OpenAI Codex CLI docs")

    assert result.status == "ok"
    assert result.metadata["search_goal"]["task_type"] == "official_docs"
    assert result.metadata["crawl_report"]["status"] == "sufficient"
    assert result.metadata["crawl_report"]["source_graph"]["cited_sources"] == ["https://developers.openai.com/codex/cli"]


def test_fallback_model_does_not_open_off_policy_search_result(tmp_path) -> None:
    queries: list[str] = []
    opened: list[str] = []

    class Client(WebClient):
        def search(self, query: str, *, max_results: int = 5):
            queries.append(query)
            if len(queries) == 1:
                return [{"title": "Linux find command", "url": "https://www.runoob.com/linux/linux-comm-find.html", "snippet": ""}]
            return [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "Official docs"}]

        def fetch_text(self, url: str) -> str:
            opened.append(url)
            return "Codex CLI is a local coding agent that runs in your terminal."

    client = Client()
    result = HoloAgent(
        tools=ToolRegistry([WebSearchTool(client), OpenPageTool(client)]),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Find official OpenAI Codex CLI docs and cite sources")

    assert any("official documentation" in query.lower() or "site:developers.openai.com" in query for query in queries[1:])
    assert opened == ["https://developers.openai.com/codex/cli"]
    assert "runoob" not in result.final
