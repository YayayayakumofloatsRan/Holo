from __future__ import annotations

from pathlib import Path

from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.research.contracts import ResearchSourceEntry
from kernel_v3.research import (
    RESEARCH_PROFILE_IDS,
    TECHNICAL_DOCUMENTATION_PROFILE_ID,
    assess_profile_evidence_coverage,
    classify_source_family,
    profile_by_id,
    profile_evidence_facets,
    profile_extraction_aliases,
    qualify_profile_evidence_candidate,
    source_directory_for_profile,
)
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, SearchGoal, SearchSource
from kernel_v3.retrieval.evaluate import EvidenceEvaluator
from kernel_v3.retrieval.live_config import LIVE_RETRIEVAL_ENV, LIVE_SOURCE_DIRECTORY_ALLOWLIST_ENV, LiveRetrievalConfig
from kernel_v3.retrieval.providers import FakeFetchProvider, FakeSearchProvider
from kernel_v3.retrieval.operator import RetrievalOperator
from kernel_v3.retrieval.source_directory_rank import rank_source_directory_entries


def test_phase108_technical_documentation_profile_is_not_finance_only() -> None:
    profile = profile_by_id(TECHNICAL_DOCUMENTATION_PROFILE_ID)
    assert profile is not None
    assert TECHNICAL_DOCUMENTATION_PROFILE_ID in RESEARCH_PROFILE_IDS
    assert profile.primary_source_families == [
        "official_documentation",
        "source_repository",
        "standards_body",
        "official_guidance",
    ]
    family, reason = classify_source_family(
        uri="https://docs.example.com/api-reference/authentication",
        title="Example API documentation",
    )
    assert family == "official_documentation"
    assert reason == "recognized_official_documentation_surface"
    directory = source_directory_for_profile(TECHNICAL_DOCUMENTATION_PROFILE_ID)
    assert any(entry.source_id == "techdocs-deepseek-api-docs" for entry in directory)
    assert all(entry.profile_id == TECHNICAL_DOCUMENTATION_PROFILE_ID for entry in directory)


def test_phase108_live_source_directory_allowlist_includes_non_finance_profile_hosts() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            LIVE_RETRIEVAL_ENV: "1",
            LIVE_SOURCE_DIRECTORY_ALLOWLIST_ENV: "1",
        }
    )
    assert "api-docs.deepseek.com" in config.fetch.allowed_hosts
    assert "platform.openai.com" in config.fetch.allowed_hosts


def test_phase108_source_directory_filters_mismatched_target_terms() -> None:
    entries = source_directory_for_profile(TECHNICAL_DOCUMENTATION_PROFILE_ID)
    ranked = rank_source_directory_entries(
        entries,
        query="DeepSeek API authentication endpoint documentation",
        metadata={"research_profile": TECHNICAL_DOCUMENTATION_PROFILE_ID},
    )
    assert ranked
    assert [item.entry.source_id for item in ranked] == ["techdocs-deepseek-api-docs"]


def test_phase108_source_directory_boosts_technical_documentation_sources() -> None:
    entries = [
        ResearchSourceEntry(
            source_id="generic-web",
            profile_id=TECHNICAL_DOCUMENTATION_PROFILE_ID,
            title="Generic web result about API authentication",
            source_family="generic_web",
            authority_level="weak",
            base_url="https://example.com/blog/api-auth",
            allowed_hosts=["example.com"],
            use_cases=["API authentication"],
            required_identifiers=[],
            query_hints=[],
            crawl_notes=[],
        ),
        ResearchSourceEntry(
            source_id="official-docs",
            profile_id=TECHNICAL_DOCUMENTATION_PROFILE_ID,
            title="Official API documentation",
            source_family="official_documentation",
            authority_level="primary",
            base_url="https://docs.example.com/api/authentication",
            allowed_hosts=["docs.example.com"],
            use_cases=["API authentication endpoint documentation"],
            required_identifiers=[],
            query_hints=[],
            crawl_notes=[],
        ),
    ]
    ranked = rank_source_directory_entries(
        entries,
        query="API authentication endpoint documentation",
        metadata={
            "research_profile": TECHNICAL_DOCUMENTATION_PROFILE_ID,
            "research_task_kind": "api_documentation",
        },
    )
    assert ranked[0].entry.source_id == "official-docs"


def test_phase108_profile_policy_extracts_generic_facets_and_aliases() -> None:
    goal = SearchGoal(
        goal_id="goal-docs",
        query="Find the API endpoint and authentication method",
        metadata={"research_profile": TECHNICAL_DOCUMENTATION_PROFILE_ID},
    )
    assert profile_evidence_facets(goal=goal) == ["endpoint", "authentication"]
    aliases = profile_extraction_aliases(goal=goal)
    assert "endpoint" in aliases
    assert "api key" in aliases


def test_phase108_generic_profile_rejects_discovery_metadata_as_final_evidence() -> None:
    goal = SearchGoal(
        goal_id="goal-docs",
        query="Find the API endpoint and authentication method",
        metadata={"research_profile": TECHNICAL_DOCUMENTATION_PROFILE_ID},
    )
    evidence = EvidenceItem(
        evidence_id="ev-docs-search",
        goal_id=goal.goal_id,
        span_id="span-1",
        document_id="doc-1",
        source_id="src-1",
        artifact_id="artifact-1",
        uri="https://docs.example.com/search?q=auth",
        title="Docs search",
        text="Search results for authentication.",
        score=0.7,
        payload_hash="hash",
        diagnostics={"source_kind": "docs_search_index"},
    )
    decision = qualify_profile_evidence_candidate(goal=goal, evidence=evidence)
    assert decision["accepted"] is False
    assert decision["reason"] == "discovery_metadata_not_final_evidence"
    assert decision["missing_profile_facets"] == ["final_evidence_fact"]


def test_phase108_generic_profile_evaluator_requires_requested_documentation_facets() -> None:
    profile = profile_by_id(TECHNICAL_DOCUMENTATION_PROFILE_ID)
    assert profile is not None
    goal = SearchGoal(
        goal_id="goal-docs",
        query="Find the API endpoint and authentication method",
        metadata={"research_profile": TECHNICAL_DOCUMENTATION_PROFILE_ID},
    )
    evidence = EvidenceItem(
        evidence_id="ev-docs",
        goal_id=goal.goal_id,
        span_id="span-1",
        document_id="doc-1",
        source_id="src-1",
        artifact_id="artifact-1",
        uri="https://docs.example.com/api-reference/authentication",
        title="Example API docs",
        text="The endpoint is https://api.example.com/v1/chat. Authentication uses a Bearer API key.",
        score=0.95,
        payload_hash="hash",
        diagnostics={
            "source_assessment": {
                "assessment_id": "srcassess-docs",
                "profile_id": TECHNICAL_DOCUMENTATION_PROFILE_ID,
                "source_id": "src-1",
                "uri": "https://docs.example.com/api-reference/authentication",
                "source_family": "official_documentation",
                "authority_level": "primary",
                "authority_score": 0.88,
                "usable_as_primary": True,
                "reasons": ["recognized_official_documentation_surface", "authority_level:primary"],
                "warnings": [],
                "metadata": {"provider": "fake"},
            }
        },
    )
    coverage = assess_profile_evidence_coverage(goal=goal, evidence=[evidence], research_profile=profile)
    assert coverage["profile_evidence_required"] is True
    assert coverage["covered_profile_facets"] == ["endpoint", "authentication"]
    assert coverage["missing_profile_facets"] == []
    citation = CitationItem(
        citation_id="cite-docs",
        goal_id=goal.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote=evidence.text,
        span_start=0,
        span_end=len(evidence.text),
    )
    decision = EvidenceEvaluator().evaluate(
        goal=goal,
        evidence=[evidence],
        citations=[citation],
        research_profile=profile,
    )
    assert decision.sufficient is True
    assert decision.reason == "evidence_with_citations"


def test_phase108_retrieval_operator_compacts_profile_evidence_before_citations(tmp_path: Path) -> None:
    query = "Find the API endpoint and authentication method"
    sources = [
        SearchSource(
            source_id=f"src-{index}",
            uri=f"https://docs.example.com/api-reference/authentication/{index}",
            title=f"Docs page {index}",
            snippet="endpoint authentication bearer api key",
            provider="fake",
            metadata={"source_family": "official_documentation"},
        )
        for index in range(20)
    ]
    bodies = {
        source.uri: (
            f"Documentation page {index}. The endpoint is https://api.example.com/v1/chat. "
            "Authentication uses a Bearer API key. Parameters include messages and model."
        )
        for index, source in enumerate(sources)
    }
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({query: sources}),
        fetch_provider=FakeFetchProvider(bodies),
    )
    journal = JournalStore(tmp_path / "journal.jsonl", index_path=tmp_path / "journal.sqlite")
    artifacts = ArtifactStore(tmp_path / "artifacts.jsonl")
    report = operator.run(
        SearchGoal(
            goal_id="goal-docs",
            query=query,
            max_sources=20,
            max_fetches=20,
            max_spans_per_document=4,
            metadata={"research_profile": TECHNICAL_DOCUMENTATION_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-docs",
        run_id="run-docs",
    )
    compaction = report.diagnostics["evidence_compaction"]
    assert compaction["strategy"] == "profile_facet_authority_compaction"
    assert compaction["candidate_count"] > compaction["selected_count"]
    assert compaction["selected_count"] <= 12
    assert report.diagnostics["citation_count"] == compaction["selected_count"]
    rejections = journal.records(task_id="task-docs", kind="retrieval_evidence_rejections")
    assert rejections
    assert rejections[-1].data["diagnostics"]["reasons"]["evidence_compacted_out"] >= 1
