from __future__ import annotations

from pathlib import Path

from kernel_v3.agent.answer_profile import infer_answer_profile
from kernel_v3.agent.contracts import SemanticIntake
from kernel_v3.agent.taskgraph import build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.research import (
    ACADEMIC_RESEARCH_PROFILE_ID,
    RESEARCH_PROFILE_IDS,
    classify_source_family,
    profile_by_id,
    research_depth_defaults,
    source_directory_for_profile,
)
from kernel_v3.retrieval import ArxivApiSearchProvider, FakeFetchProvider, FakeSearchProvider, RetrievalOperator
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, QueryPlan, SearchGoal
from kernel_v3.retrieval.evaluate import EvidenceEvaluator, qualify_evidence_candidate
from kernel_v3.retrieval.http_provider import HttpTransportResponse
from kernel_v3.retrieval.rank import rank_sources
from kernel_v3.retrieval.contracts import SearchSource


def test_phase111_academic_profile_is_first_class_research_profile() -> None:
    profile = profile_by_id(ACADEMIC_RESEARCH_PROFILE_ID)

    assert profile is not None
    assert ACADEMIC_RESEARCH_PROFILE_ID in RESEARCH_PROFILE_IDS
    assert "scholarly_preprint" in profile.primary_source_families
    assert "scholarly_index" in profile.secondary_source_families
    assert "reference_dictionary" in profile.weak_source_families
    directory = source_directory_for_profile(ACADEMIC_RESEARCH_PROFILE_ID)
    assert {entry.source_id for entry in directory} >= {
        "academic-arxiv-search",
        "academic-semantic-scholar",
        "academic-openalex-works",
        "academic-crossref-search",
    }


def test_phase111_academic_default_research_depth_is_bounded() -> None:
    default_budget = research_depth_defaults(ACADEMIC_RESEARCH_PROFILE_ID)
    deep_budget = research_depth_defaults(ACADEMIC_RESEARCH_PROFILE_ID, "deep")

    assert default_budget["max_queries"] == 8
    assert default_budget["max_sources"] == 80
    assert default_budget["max_fetches"] == 24
    assert deep_budget["max_fetches"] == 72


def test_phase111_academic_source_classification_rejects_dictionary_path() -> None:
    dictionary_family, dictionary_reason = classify_source_family(
        uri="https://dictionary.cambridge.org/dictionary/english/hyperbolic",
        title="HYPERBOLIC definition in the Cambridge English Dictionary",
    )
    arxiv_family, arxiv_reason = classify_source_family(
        uri="https://arxiv.org/abs/2601.01234",
        title="Recent advances in hyperbolic dynamics",
    )
    publisher_family, publisher_reason = classify_source_family(
        uri="https://www.cambridge.org/core/journals/ergodic-theory-and-dynamical-systems/article/example",
        title="A journal article in Ergodic Theory and Dynamical Systems",
    )

    assert dictionary_family == "reference_dictionary"
    assert dictionary_reason == "recognized_reference_dictionary_domain"
    assert arxiv_family == "scholarly_preprint"
    assert arxiv_reason == "recognized_scholarly_preprint_domain"
    assert publisher_family == "scholarly_publisher"
    assert publisher_reason == "recognized_scholarly_publisher_domain"


def test_phase111_task_graph_implies_academic_payloads_from_frontier_label() -> None:
    intake = SemanticIntake(
        intake_id="intake-academic",
        goal="搜索双曲动力学的前沿研究",
        primary_intent="frontier_research",
        suggested_mode="retrieval_answer",
        compound=False,
        requires_clarification=False,
        intents=[
            {
                "kind": "frontier_research",
                "text": "搜索双曲动力学的前沿研究",
                "sequence_index": 1,
                "required_capabilities": [],
                "risk": "read",
                "status": "ready",
                "metadata": {"domain": "academic_research"},
            }
        ],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )

    proposal = task_graph_from_semantic(intake)
    validation = validate_task_graph(proposal)
    plan = build_task_execution_plan(proposal, validation)
    step = plan.steps[0]
    payloads = step["metadata"]["capability_args"]["retrieval.run"]

    assert validation.status == "ready"
    assert plan.selected_mode == "retrieval_answer"
    assert step["tool_name"] == "retrieval.run"
    assert "academic.frontier_research" in step["required_capabilities"]
    assert len(payloads) >= 3
    assert {item["metadata"]["research_profile"] for item in payloads} == {ACADEMIC_RESEARCH_PROFILE_ID}
    assert {item["metadata"]["search_strategy"] for item in payloads} >= {"aggregate", "fresh_live"}


def test_phase111_academic_answer_profile_defaults_to_detailed_report() -> None:
    goal = "搜索双曲动力学的前沿研究"
    intake = SemanticIntake(
        intake_id="intake-academic",
        goal=goal,
        primary_intent="academic_frontier_research",
        suggested_mode="retrieval_answer",
        compound=False,
        requires_clarification=False,
        intents=[
            {
                "kind": "academic_frontier_research",
                "text": goal,
                "sequence_index": 1,
                "required_capabilities": ["academic.frontier_research"],
                "risk": "read",
                "status": "ready",
                "metadata": {"domain": "academic_research"},
            }
        ],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )

    profile = infer_answer_profile(goal, semantic_intake=intake, response_language="zh")

    assert profile.format == "detailed_report"
    assert profile.detail_level == "detailed"
    assert profile.metadata["domain"] == "academic"
    assert "关键文献与来源" in profile.target_sections
    assert "frontier_or_open_questions" in profile.minimum_coverage


def test_phase111_academic_ranking_prefers_scholarly_source_over_dictionary() -> None:
    profile = profile_by_id(ACADEMIC_RESEARCH_PROFILE_ID)
    assert profile is not None
    goal = SearchGoal(
        goal_id="goal-academic",
        query="hyperbolic dynamics frontier research",
        metadata={"research_profile": ACADEMIC_RESEARCH_PROFILE_ID},
    )
    ranked = rank_sources(
        goal,
        [
            SearchSource(
                source_id="dict",
                uri="https://dictionary.cambridge.org/dictionary/english/hyperbolic",
                title="HYPERBOLIC definition",
                snippet="A dictionary definition of hyperbolic.",
                provider="fake",
                metadata={},
            ),
            SearchSource(
                source_id="arxiv",
                uri="https://arxiv.org/abs/2601.01234",
                title="Recent advances in hyperbolic dynamics",
                snippet="A survey paper on recent research, open problems, and new results.",
                provider="fake",
                metadata={},
            ),
        ],
        research_profile=profile,
    )

    assert ranked[0].source_id == "arxiv"
    assert ranked[-1].metadata["source_assessment"]["source_family"] == "reference_dictionary"


def test_phase111_academic_evaluator_rejects_dictionary_definition_as_frontier_evidence() -> None:
    profile = profile_by_id(ACADEMIC_RESEARCH_PROFILE_ID)
    assert profile is not None
    goal = SearchGoal(
        goal_id="goal-academic",
        query="hyperbolic dynamics frontier research",
        metadata={
            "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
            "research_task_kind": "frontier_research",
            "source_authority_requirement": "secondary_or_better",
        },
    )
    evidence = EvidenceItem(
        evidence_id="ev-dict",
        goal_id=goal.goal_id,
        span_id="span-1",
        document_id="doc-1",
        source_id="dict",
        artifact_id="artifact-1",
        uri="https://dictionary.cambridge.org/dictionary/english/hyperbolic",
        title="HYPERBOLIC definition",
        text="Hyperbolic means related to a hyperbola or exaggerated in style.",
        score=0.8,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-dict",
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

    assert decision.sufficient is False
    assert decision.reason in {"profile_evidence_facets_missing", "no_required_authority_source_for_research_profile"}
    assert "scholarly_work" in decision.diagnostics["missing_profile_facets"]


def test_phase111_academic_evaluator_rejects_off_topic_scholarly_evidence() -> None:
    profile = profile_by_id(ACADEMIC_RESEARCH_PROFILE_ID)
    assert profile is not None
    goal = SearchGoal(
        goal_id="goal-academic",
        query="hyperbolic dynamics frontier research",
        metadata={
            "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
            "research_task_kind": "frontier_research",
            "source_authority_requirement": "secondary_or_better",
        },
    )
    text = (
        "This arXiv paper is a recent review article with DOI metadata, authors, "
        "abstract, citations, and open problems, but it is about game theory."
    )
    evidence = EvidenceItem(
        evidence_id="ev-off-topic",
        goal_id=goal.goal_id,
        span_id="span-1",
        document_id="doc-1",
        source_id="arxiv",
        artifact_id="artifact-1",
        uri="https://arxiv.org/abs/2606.05108",
        title="A game theory preprint",
        text=text,
        score=0.95,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-off-topic",
        goal_id=goal.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote=text,
        span_start=0,
        span_end=len(text),
    )

    decision = EvidenceEvaluator().evaluate(
        goal=goal,
        evidence=[evidence],
        citations=[citation],
        research_profile=profile,
    )

    assert decision.sufficient is False
    assert decision.reason == "query_topic_terms_missing"
    assert decision.diagnostics["query_topic_coverage"]["topic_terms"] == ["hyperbolic", "dynamics"]
    assert decision.diagnostics["query_topic_coverage"]["matched_topic_terms"] == []


def test_phase111_academic_qualification_rejects_single_off_topic_paper_span() -> None:
    profile = profile_by_id(ACADEMIC_RESEARCH_PROFILE_ID)
    assert profile is not None
    goal = SearchGoal(
        goal_id="goal-academic",
        query="hyperbolic dynamics frontier research",
        metadata={
            "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
            "research_task_kind": "frontier_research",
            "source_authority_requirement": "secondary_or_better",
        },
    )
    evidence = EvidenceItem(
        evidence_id="ev-off-topic",
        goal_id=goal.goal_id,
        span_id="span-1",
        document_id="doc-1",
        source_id="arxiv",
        artifact_id="artifact-1",
        uri="https://arxiv.org/abs/2606.05108",
        title="A game theory preprint",
        text="This arXiv paper is a recent review article with DOI metadata and open problems.",
        score=0.95,
        payload_hash="hash",
        diagnostics={},
    )

    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence, research_profile=profile)

    assert qualification["accepted"] is False
    assert qualification["reason"] == "query_topic_terms_missing"
    assert qualification["query_topic_coverage"]["missing_topic_terms"] == ["hyperbolic", "dynamics"]


def test_phase111_academic_evaluator_accepts_scholarly_paper_evidence() -> None:
    profile = profile_by_id(ACADEMIC_RESEARCH_PROFILE_ID)
    assert profile is not None
    goal = SearchGoal(
        goal_id="goal-academic",
        query="hyperbolic dynamics frontier research",
        metadata={
            "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
            "research_task_kind": "frontier_research",
            "source_authority_requirement": "secondary_or_better",
        },
    )
    text = (
        "This arXiv survey paper reviews recent hyperbolic dynamics research, "
        "frontier open problems, theorem-level results, methods, authors, abstract, "
        "citation context, and DOI/arXiv bibliographic metadata."
    )
    evidence = EvidenceItem(
        evidence_id="ev-paper",
        goal_id=goal.goal_id,
        span_id="span-1",
        document_id="doc-1",
        source_id="arxiv",
        artifact_id="artifact-1",
        uri="https://arxiv.org/abs/2601.01234",
        title="Recent advances in hyperbolic dynamics",
        text=text,
        score=0.95,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-paper",
        goal_id=goal.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote=text,
        span_start=0,
        span_end=len(text),
    )

    decision = EvidenceEvaluator().evaluate(
        goal=goal,
        evidence=[evidence],
        citations=[citation],
        research_profile=profile,
    )

    assert decision.sufficient is True
    assert decision.reason == "evidence_with_citations"


def test_phase111_arxiv_api_provider_returns_concrete_paper_sources() -> None:
    def transport(url: str, headers: dict[str, str], timeout_seconds: int, max_bytes: int) -> HttpTransportResponse:
        assert "export.arxiv.org/api/query" in url
        body = b"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>http://arxiv.org/abs/2601.01234v2</id>
            <updated>2026-01-03T00:00:00Z</updated>
            <published>2026-01-01T00:00:00Z</published>
            <title>Recent Advances in Hyperbolic Dynamics</title>
            <summary>A survey paper on frontier hyperbolic dynamics, open problems, methods, and theorem-level results.</summary>
            <author><name>Ada Researcher</name></author>
          </entry>
        </feed>"""
        return HttpTransportResponse(status_code=200, body=body, mime_type="application/atom+xml")

    provider = ArxivApiSearchProvider(transport=transport)
    goal = SearchGoal(
        goal_id="goal-academic",
        query="hyperbolic dynamics frontier research",
        metadata={"research_profile": ACADEMIC_RESEARCH_PROFILE_ID},
    )
    sources = provider.search(
        goal.query,
        goal=goal,
        plan=QueryPlan(
            plan_id="plan-academic",
            goal_id=goal.goal_id,
            queries=[goal.query],
            max_sources=5,
            max_fetches=3,
        ),
    )

    assert len(sources) == 1
    assert sources[0].uri == "https://arxiv.org/abs/2601.01234v2"
    assert sources[0].metadata["source_family"] == "scholarly_preprint"
    assert sources[0].metadata["source_kind"] == "scholarly_preprint"
    assert "open problems" in sources[0].snippet


def test_phase111_academic_discovery_sources_are_not_final_evidence(tmp_path: Path) -> None:
    query = "hyperbolic dynamics frontier research"
    source = SearchSource(
        source_id="academic-directory",
        uri="https://arxiv.org/search/?query=hyperbolic+dynamics&searchtype=all",
        title="arXiv search for hyperbolic dynamics",
        snippet="Search page for recent arXiv papers.",
        provider="fake",
        metadata={
            "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
            "source_family": "scholarly_preprint",
            "authority_level": "primary",
            "source_kind": "scholarly_search",
        },
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({query: [source]}),
        fetch_provider=FakeFetchProvider(
            {
                source.uri: (
                    "This search page mentions paper, article, journal, arxiv, DOI, "
                    "recent frontier survey open problem and author metadata."
                )
            }
        ),
    )
    report = operator.run(
        SearchGoal(
            goal_id="goal-academic-discovery",
            query=query,
            max_sources=5,
            max_fetches=5,
            max_spans_per_document=4,
            metadata={
                "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
                "research_task_kind": "frontier_research",
                "source_authority_requirement": "secondary_or_better",
            },
        ),
        journal=JournalStore(tmp_path / "journal.jsonl", index_path=tmp_path / "journal.sqlite"),
        artifact_store=ArtifactStore(tmp_path / "artifacts.jsonl"),
        task_id="task-academic",
        run_id="run-academic",
    )

    assert report.status == "insufficient_evidence"
    assert report.diagnostics["fetch_attempt_count"] == 0
    assert report.diagnostics["source_rejection_reasons"]["source_discovery_only_for_research_profile"] == 1
    assert report.diagnostics["evidence_count"] == 0
    assert report.diagnostics["citation_count"] == 0
