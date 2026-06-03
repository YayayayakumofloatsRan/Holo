from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import (
    FakeFetchProvider,
    FakeSearchProvider,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
)
from kernel_v3.retrieval.evaluate import EvidenceEvaluator


def test_phase97_evidence_evaluator_requires_requested_query_facets():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "DeepSeek API 模型 鉴权方式": [
                    _source(
                        "pricing",
                        "https://api-docs.deepseek.com/quick_start/pricing",
                        "DeepSeek API pricing",
                        "DeepSeek API model pricing details.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://api-docs.deepseek.com/quick_start/pricing": (
                    "DeepSeek API 模型 Model Details include deepseek-v4-pro and deepseek-v4-flash. "
                    "Pricing is listed for each model."
                )
            }
        ),
        evaluator=EvidenceEvaluator(),
    )

    report = operator.run(
        SearchGoal(goal_id="goal-facets", query="DeepSeek API 模型 鉴权方式", max_spans_per_document=2),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-facets",
        run_id="run-1",
    )

    evaluation = journal.records(task_id="task-facets", kind="retrieval_evaluation_decision")[-1].data
    diagnostics = evaluation["diagnostics"]
    assert report.status == "insufficient_evidence"
    assert evaluation["reason"] == "query_facets_missing"
    assert diagnostics["covered_query_facets"] == ["model"]
    assert diagnostics["missing_query_facets"] == ["authentication"]
    assert report.diagnostics["evaluation_diagnostics"]["missing_query_facets"] == ["authentication"]


def test_phase97_evidence_evaluator_accepts_covered_query_facets():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "DeepSeek API 模型 鉴权方式": [
                    _source(
                        "auth",
                        "https://api-docs.deepseek.com/quick_start/auth",
                        "DeepSeek API auth",
                        "DeepSeek API model and authentication details.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://api-docs.deepseek.com/quick_start/auth": (
                    "DeepSeek API 模型 include deepseek-chat and deepseek-reasoner. "
                    "Authentication uses Authorization: Bearer API key."
                )
            }
        ),
        evaluator=EvidenceEvaluator(),
    )

    report = operator.run(
        SearchGoal(goal_id="goal-covered", query="DeepSeek API 模型 鉴权方式", max_spans_per_document=2),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-covered",
        run_id="run-1",
    )

    evaluation = journal.records(task_id="task-covered", kind="retrieval_evaluation_decision")[-1].data
    assert report.status == "sufficient"
    assert evaluation["diagnostics"]["missing_query_facets"] == []
    assert set(evaluation["diagnostics"]["covered_query_facets"]) == {"model", "authentication"}


def test_phase97_retrieval_rejects_partial_name_wrong_entity_evidence():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    query = "Citadel Security company size employees revenue"
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                query: [
                    _source(
                        "outlets",
                        "https://example.test/citadel-outlets",
                        "Citadel Outlets home page",
                        "Citadel Outlets company directory and visitor information.",
                    ),
                    _source(
                        "credit-union",
                        "https://example.test/citadel-credit-union",
                        "Citadel Credit Union",
                        "Citadel Credit Union operations and member services.",
                    ),
                    _source(
                        "college",
                        "https://example.test/the-citadel",
                        "The Citadel",
                        "The Citadel campus security office and operations.",
                    ),
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://example.test/citadel-outlets": (
                    "Citadel Outlets is a shopping center. This company page mentions revenue events "
                    "and employee parking, but it is not the requested security company."
                ),
                "https://example.test/citadel-credit-union": (
                    "Citadel Credit Union provides banking operations, employee benefits, and member revenue reports."
                ),
                "https://example.test/the-citadel": (
                    "The Citadel has campus security operations and employees, but it is a college."
                ),
            }
        ),
        evaluator=EvidenceEvaluator(),
    )

    report = operator.run(
        SearchGoal(goal_id="goal-citadel-wrong", query=query, max_spans_per_document=2),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-citadel-wrong",
        run_id="run-1",
    )

    rejections = journal.records(task_id="task-citadel-wrong", kind="retrieval_evidence_rejections")[-1].data
    evaluation = journal.records(task_id="task-citadel-wrong", kind="retrieval_evaluation_decision")[-1].data
    assert report.status == "insufficient_evidence"
    assert report.citation_ids == []
    assert rejections["diagnostics"]["reasons"]["target_entity_mismatch"] >= 1
    assert rejections["items"][0]["required_target_phrases"] == ["Citadel Security"]
    assert "Citadel Security" in evaluation["diagnostics"]["missing_target_phrases"]


def test_phase97_retrieval_accepts_matching_target_entity_evidence():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    query = "Citadel Security company size employees revenue"
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                query: [
                    _source(
                        "citadel-security",
                        "https://example.test/citadel-security-profile",
                        "Citadel Security company profile",
                        "Citadel Security scale, employees, revenue, and operations.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://example.test/citadel-security-profile": (
                    "Citadel Security is a private security company. Citadel Security operations include "
                    "guarding, monitoring, and risk response. Its company scale, employees, and revenue "
                    "are described in this profile."
                )
            }
        ),
        evaluator=EvidenceEvaluator(),
    )

    report = operator.run(
        SearchGoal(goal_id="goal-citadel-match", query=query, max_spans_per_document=2),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-citadel-match",
        run_id="run-1",
    )

    evaluation = journal.records(task_id="task-citadel-match", kind="retrieval_evaluation_decision")[-1].data
    assert report.status == "sufficient"
    assert report.citation_ids
    assert evaluation["diagnostics"]["covered_target_phrases"] == ["Citadel Security"]
    assert evaluation["diagnostics"]["missing_target_phrases"] == []


def test_phase97_workloop_blocks_final_answer_when_retrieval_report_is_insufficient():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider(
                {
                    "DeepSeek API 模型 鉴权方式": [
                        _source(
                            "pricing",
                            "https://api-docs.deepseek.com/quick_start/pricing",
                            "DeepSeek API pricing",
                            "DeepSeek API model pricing details.",
                        )
                    ]
                }
            ),
            fetch_provider=FakeFetchProvider(
                {
                    "https://api-docs.deepseek.com/quick_start/pricing": (
                        "DeepSeek API 模型 Model Details include deepseek-v4-pro and deepseek-v4-flash. "
                        "Pricing is listed for each model."
                    )
                }
            ),
        ),
    )

    result = runtime.run("DeepSeek API 模型 鉴权方式", mode="retrieval")

    assert result.status == "failed"
    assert result.final_answer is None
    decisions = [record.data for record in journal.records(task_id=result.task_id, kind="termination_decision")]
    assert decisions[0]["decision"] == "continue"
    assert decisions[0]["diagnostics"]["evidence_missing"] == [
        "sufficient_retrieval_evidence",
        "query_facet:authentication",
    ]
    sufficiency = journal.records(task_id=result.task_id, kind="evidence_sufficiency")[0].data
    assert sufficiency["reason"] == "query_facets_missing"
    assert sufficiency["diagnostics"]["missing_query_facets"] == ["authentication"]


def _source(source_id: str, uri: str, title: str, snippet: str) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="fake",
    )
