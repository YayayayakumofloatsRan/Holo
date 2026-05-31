import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, ResearchCorpusStore
from kernel_v3.retrieval import (
    CorpusFetchProvider,
    CorpusSearchProvider,
    FakeFetchProvider,
    FakeSearchProvider,
    FallbackSearchProvider,
    QueryPlan,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
    inspect_retrieval_providers,
)
from kernel_v3.resident import ResidentDoctor, ResidentQueue, ResidentScheduler


def test_phase89_retrieval_provider_inspection_reports_fake_profile_gap() -> None:
    operator = _fake_operator()

    inspection = inspect_retrieval_providers(
        operator,
        research_profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        clock_ms=lambda: 101,
    )

    assert inspection.status == "ok"
    assert inspection.generated_at_ms == 101
    assert inspection.network_access is False
    assert inspection.diagnostics["search_provider_ids"] == ["fake_search"]
    assert inspection.diagnostics["fetch_provider_ids"] == ["fake_fetch"]
    assert inspection.issues[0]["code"] == "research_profile_not_provider_native"
    assert "prefer a profile-aware corpus or retrieval provider for directed research" in inspection.recommended_actions


def test_phase89_retrieval_provider_inspection_accepts_profile_aware_corpus() -> None:
    artifacts = ArtifactStore.in_memory()
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 202)
    operator = RetrievalOperator(
        search_provider=CorpusSearchProvider(corpus),
        fetch_provider=CorpusFetchProvider(artifacts),
    )

    inspection = inspect_retrieval_providers(
        operator,
        research_profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        clock_ms=lambda: 203,
    )

    assert inspection.status == "ok"
    assert inspection.issues == []
    search_capability = inspection.provider_capabilities[0]
    assert search_capability["provider_id"] == "research_corpus"
    assert search_capability["profile_aware"] is True
    assert search_capability["supported_research_profiles"] == ["*"]


def test_phase89_retrieval_provider_inspection_flags_empty_fallback_search_chain() -> None:
    operator = RetrievalOperator(
        search_provider=FallbackSearchProvider([]),
        fetch_provider=FakeFetchProvider({}),
    )

    inspection = inspect_retrieval_providers(operator, clock_ms=lambda: 204)

    assert inspection.status == "error"
    assert inspection.generated_at_ms == 204
    assert inspection.issues[0]["code"] == "empty_fallback_search_chain"
    assert inspection.issues[0]["provider_id"] == "fallback_search"
    assert "configure at least one concrete fallback search provider" in inspection.recommended_actions


def test_phase89_fallback_search_skips_disabled_default_providers() -> None:
    disabled = _DisabledSearchProvider()
    enabled_source = SearchSource(
        source_id="src-enabled",
        uri="https://example.test/enabled",
        title="Enabled",
        snippet="enabled source",
        provider="enabled_search",
    )
    enabled = FakeSearchProvider({"AAPL revenue": [enabled_source]})
    provider = FallbackSearchProvider([disabled, enabled])

    sources = provider.search(
        "AAPL revenue",
        goal=_search_goal(),
        plan=_query_plan(),
    )
    diagnostics = provider.search_diagnostics()

    assert sources == [enabled_source]
    assert disabled.called is False
    assert diagnostics["status"] == "ok"
    assert diagnostics["attempts"][0]["status"] == "skipped"
    assert diagnostics["attempts"][0]["reason"] == "disabled_by_default"
    assert diagnostics["selected_provider_id"] == "fake_search"


def test_phase89_retrieval_provider_inspection_flags_fallback_chain_without_enabled_provider() -> None:
    operator = RetrievalOperator(
        search_provider=FallbackSearchProvider([_DisabledSearchProvider()]),
        fetch_provider=FakeFetchProvider({}),
    )

    inspection = inspect_retrieval_providers(operator, clock_ms=lambda: 205)

    assert inspection.status == "error"
    assert inspection.issues[0]["code"] == "no_enabled_fallback_search_provider"
    assert any(issue["code"] == "retrieval_provider_disabled_by_default" for issue in inspection.issues)
    assert any(issue["code"] == "no_enabled_fallback_search_provider" for issue in inspection.issues)
    assert "enable at least one concrete fallback search provider" in inspection.recommended_actions


def test_phase89_cli_retrieval_providers_is_read_only(tmp_path: Path, capsys) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "retrieval-providers",
                "--profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["mode"] == "fake"
    assert payload["network_access"] is False
    assert payload["provider_capabilities"][0]["provider_id"] == "fake_search"
    assert payload["inspection"]["issues"][0]["code"] == "research_profile_not_provider_native"
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase89_cli_retrieval_providers_flattens_default_corpus_chain(tmp_path: Path, capsys) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    artifact_path = tmp_path / "artifacts.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    corpus_index = tmp_path / "corpus.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "--artifact-log",
                str(artifact_path),
                "--corpus-log",
                str(corpus_path),
                "--corpus-index",
                str(corpus_index),
                "retrieval-providers",
                "--profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["mode"] == "default"
    chain = payload["inspection"]["diagnostics"]["provider_chain"]
    chain_ids = {(item["provider_kind"], item["provider_id"]) for item in chain}
    assert ("search", "research_corpus") in chain_ids
    assert ("search", "fake_search") in chain_ids
    assert ("fetch", "research_corpus_fetch") in chain_ids
    assert ("fetch", "fake_fetch") in chain_ids
    assert payload["inspection"]["issues"] == []
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase89_resident_doctor_includes_retrieval_provider_inspection(tmp_path: Path) -> None:
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=lambda: 303)
    scheduler = ResidentScheduler(queue=queue, clock_ms=lambda: 304)

    report = ResidentDoctor(
        queue=queue,
        scheduler=scheduler,
        retrieval_operator=_fake_operator(),
        research_profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        clock_ms=lambda: 305,
    ).inspect(sample_limit=1)

    assert report.status == "ok"
    assert report.configured["retrieval_operator"] is True
    assert report.retrieval_provider_inspection is not None
    assert report.retrieval_provider_inspection["provider_capabilities"][0]["provider_id"] == "fake_search"
    assert report.issues[0]["component"] == "retrieval"
    assert report.issues[0]["code"] == "research_profile_not_provider_native"


def test_phase89_resident_doctor_promotes_retrieval_provider_errors(tmp_path: Path) -> None:
    queue = ResidentQueue(tmp_path / "resident-empty-provider.sqlite", clock_ms=lambda: 306)
    scheduler = ResidentScheduler(queue=queue, clock_ms=lambda: 307)
    operator = RetrievalOperator(
        search_provider=FallbackSearchProvider([]),
        fetch_provider=FakeFetchProvider({}),
    )

    report = ResidentDoctor(
        queue=queue,
        scheduler=scheduler,
        retrieval_operator=operator,
        research_profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        clock_ms=lambda: 308,
    ).inspect(sample_limit=1)

    assert report.status == "error"
    assert report.retrieval_provider_inspection is not None
    assert report.retrieval_provider_inspection["status"] == "error"
    assert report.issues[0]["component"] == "retrieval"
    assert report.issues[0]["code"] == "empty_fallback_search_chain"
    assert "configure at least one concrete fallback search provider" in report.recommended_actions


def _fake_operator() -> RetrievalOperator:
    source = SearchSource(
        source_id="src-inspection-test",
        uri="https://example.test/inspection",
        title="Inspection",
        snippet="inspection fixture",
        provider="fake",
    )
    return RetrievalOperator(
        search_provider=FakeSearchProvider({"inspection": [source]}),
        fetch_provider=FakeFetchProvider({source.uri: "inspection fixture"}),
    )


def _search_goal() -> SearchGoal:
    return SearchGoal(goal_id="goal-disabled-provider", query="AAPL revenue")


def _query_plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-disabled-provider",
        goal_id="goal-disabled-provider",
        queries=["AAPL revenue"],
        max_sources=5,
        max_fetches=3,
    )


class _DisabledSearchProvider:
    provider_id = "disabled_search"
    live_network = True
    default_enabled = False
    profile_aware = True
    supported_research_profiles = [FINANCE_FUNDAMENTALS_PROFILE_ID]

    def __init__(self) -> None:
        self.called = False

    def search(self, query: str, *, goal, plan):
        self.called = True
        raise AssertionError("disabled search provider should not be called")
