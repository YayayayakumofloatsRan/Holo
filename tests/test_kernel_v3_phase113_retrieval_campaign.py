from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.cli import _run_retrieve
from kernel_v3.retrieval.contracts import ExtractedSpan, QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.operator import RetrievalOperator, _goal_from_payload
from kernel_v3.retrieval.providers import FetchResponse
from kernel_v3.retrieval.query_campaign import build_query_campaign
from kernel_v3.contracts import CandidateAction


def test_phase113_generic_deep_goal_builds_multi_query_campaign():
    campaign = build_query_campaign(
        SearchGoal(
            goal_id="goal-campaign",
            query="hyperbolic dynamics frontier research",
            max_queries=8,
            max_sources=100,
            max_fetches=50,
            metadata={
                "attempted_queries": ["hyperbolic dynamics frontier research"],
                "suggested_query_hints": ["hyperbolic dynamics arxiv recent papers open problems"],
            },
        )
    )

    assert len(campaign.queries) >= 4
    assert "hyperbolic dynamics frontier research" not in campaign.queries
    assert campaign.diagnostics["query_count"] == len(campaign.queries)
    assert any("arxiv" in query.lower() or "official" in query.lower() or "research" in query.lower() for query in campaign.queries)


def test_phase113_query_campaign_renders_source_target_templates_without_placeholder_leakage():
    campaign = build_query_campaign(
        SearchGoal(
            goal_id="goal-template",
            query="For Pfizer estimate the Seagen transaction multiple",
            max_queries=8,
            max_sources=20,
            max_fetches=10,
            metadata={
                "ticker": "PFE",
                "company": "Pfizer Inc.",
                "query_campaign": "auto",
                "suggested_source_targets": [
                    {
                        "source_id": "sec-edgar",
                        "title": "SEC EDGAR",
                        "query_hints": [
                            "{ticker} 8-K merger agreement Seagen",
                            "{company} acquisition purchase price allocation",
                            "SEC submissions {missing_identifier} accession",
                        ],
                    }
                ],
            },
        )
    )

    joined = "\n".join(campaign.queries)
    assert "{ticker}" not in joined
    assert "{company}" not in joined
    assert "{missing_identifier}" not in joined
    assert "PFE 8-K merger agreement Seagen" in joined
    assert "Pfizer Inc. acquisition purchase price allocation" in joined


def test_phase113_large_fetch_budget_defaults_to_multi_query_search_goal():
    goal = _goal_from_payload(
        CandidateAction(
            action_id="act-research",
            kind="tool",
            name="retrieval.run",
            description="research",
            score=0.9,
            reasons=["large research budget"],
            payload={
                "query": "Citadel Security scale operations",
                "max_fetches": 128,
                "max_sources": 128,
                "metadata": {"search_strategy": "aggregate"},
            },
            side_effect_class="network",
        )
    )

    assert goal.max_queries >= 8


def test_phase113_operator_journals_query_campaign_and_search_no_sources_failure():
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=_RecordingSearchProvider(results_by_query={}),
        fetch_provider=_StaticFetchProvider({}),
    )

    report = operator.run(
        SearchGoal(goal_id="goal-empty", query="rare target research", max_queries=6, max_sources=10, max_fetches=5),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-empty",
        run_id="run-empty",
    )

    plan = journal.records(task_id="task-empty", kind="retrieval_query_plan")[0].data
    assert len(plan["queries"]) >= 4
    assert plan["diagnostics"]["query_campaign"]["query_count"] == len(plan["queries"])
    assert report.diagnostics["failure_attribution"]["primary_failure_mode"] == "search_no_sources"
    assert report.diagnostics["failure_attribution"]["next_strategy_hint"] == "diversify_query_or_switch_search_provider"


def test_phase113_cli_retrieve_large_budget_defaults_to_multi_query_campaign():
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=_RecordingSearchProvider(results_by_query={}),
        fetch_provider=_StaticFetchProvider({}),
    )

    payload = _run_retrieve(
        journal,
        query="generic public research target",
        body=None,
        synthesizer_mode="fake",
        retrieval_operator=operator,
        max_sources=32,
        max_fetches=32,
    )

    assert payload["status"] == "ok"
    report = payload["report"]
    assert report["diagnostics"]["budget"]["max_queries"] >= 8
    assert report["diagnostics"]["failure_attribution"]["primary_failure_mode"] == "search_no_sources"


def test_phase113_operator_attributes_fetch_failures_separately_from_search_failure():
    sources = [
        SearchSource(
            source_id="src-1",
            uri="https://example.com/report",
            title="Target report",
            snippet="A relevant report",
            provider="fixture",
        )
    ]
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=_RecordingSearchProvider(results_by_query={"target report": sources}),
        fetch_provider=_StaticFetchProvider({"https://example.com/report": FetchResponse(status="failed", body="", diagnostics={"reason": "timeout"})}),
    )

    report = operator.run(
        SearchGoal(goal_id="goal-fetch", query="target report", max_queries=1, max_sources=5, max_fetches=1),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-fetch",
        run_id="run-fetch",
    )

    attribution = report.diagnostics["failure_attribution"]
    assert attribution["primary_failure_mode"] == "fetch_failed_or_empty"
    assert attribution["fetch"]["failure_reasons"] == {"timeout": 1}


def test_phase113_operator_keeps_running_when_one_document_extraction_fails(monkeypatch):
    sources = [
        SearchSource(
            source_id="src-bad",
            uri="https://example.com/bad-sec",
            title="Bad SEC document",
            snippet="Parser edge case",
            provider="fixture",
        ),
        SearchSource(
            source_id="src-good",
            uri="https://example.com/good-sec",
            title="Good SEC document",
            snippet="Revenue evidence",
            provider="fixture",
        ),
    ]

    def fake_extract_spans(*, goal, document, body):
        if document.source_id == "src-bad":
            raise AssertionError("unknown status keyword 'BZ' in marked section")
        return [
            ExtractedSpan(
                span_id=f"span-{document.document_id}",
                goal_id=goal.goal_id,
                document_id=document.document_id,
                source_id=document.source_id,
                text="The company reported revenue of 10 million in the annual report.",
                start_offset=0,
                end_offset=67,
                score=1.0,
                metadata={},
            )
        ]

    monkeypatch.setattr("kernel_v3.retrieval.operator.extract_spans", fake_extract_spans)
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=_RecordingSearchProvider(results_by_query={"company revenue": sources}),
        fetch_provider=_StaticFetchProvider(
            {
                "https://example.com/bad-sec": FetchResponse(status="ok", body="bad body"),
                "https://example.com/good-sec": FetchResponse(status="ok", body="good body"),
            }
        ),
    )

    report = operator.run(
        SearchGoal(goal_id="goal-extract", query="company revenue", max_queries=1, max_sources=5, max_fetches=2),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-extract",
        run_id="run-extract",
    )

    extraction_records = journal.records(task_id="task-extract", kind="retrieval_extraction")
    assert any(record.data["diagnostics"].get("reason") == "extract_failed" for record in extraction_records)
    assert report.citation_ids
    rejections = journal.records(task_id="task-extract", kind="retrieval_evidence_rejections")
    assert rejections
    assert rejections[0].data["diagnostics"]["reasons"]["extract_failed"] == 1


class _RecordingSearchProvider:
    provider_id = "recording_search"
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, *, results_by_query: dict[str, list[SearchSource]]) -> None:
        self.results_by_query = {query.lower(): list(sources) for query, sources in results_by_query.items()}
        self.queries: list[str] = []

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        self.queries.append(query)
        return list(self.results_by_query.get(query.lower(), []))


class _StaticFetchProvider:
    provider_id = "static_fetch"
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, responses_by_uri: dict[str, FetchResponse]) -> None:
        self.responses_by_uri = dict(responses_by_uri)

    def fetch(self, source: SearchSource) -> FetchResponse:
        return self.responses_by_uri.get(
            source.uri,
            FetchResponse(status="failed", body="", diagnostics={"reason": "missing_fixture"}),
        )
