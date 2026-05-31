from __future__ import annotations

from typing import Protocol

from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import CandidateAction, JsonObject, Observation, ToolManifest
from kernel_v3.journal import JournalStore
from kernel_v3.research.contracts import CorpusDocument, ResearchProfile, SourceAssessment
from kernel_v3.research.profiles import profile_by_id
from kernel_v3.research.source_policy import assess_search_source, source_authority_summary
from kernel_v3.retrieval.citations import citation_from_evidence
from kernel_v3.retrieval.contracts import (
    EvidenceItem,
    FetchedDocument,
    FetchAttempt,
    QueryPlan,
    RankedSource,
    RankSources,
    RetrievalReport,
    SearchAttempt,
    SearchGoal,
    SearchSource,
)
from kernel_v3.retrieval.evaluate import EvidenceEvaluator
from kernel_v3.retrieval.extract import extract_spans
from kernel_v3.retrieval.providers import FetchProvider, SearchProvider, provider_capability
from kernel_v3.retrieval.rank import plan_queries, rank_sources
from kernel_v3.tools import ToolRegistry, ToolResult


class CorpusStore(Protocol):
    def record_retrieval_document(
        self,
        *,
        document: FetchedDocument,
        source: SearchSource,
        goal: SearchGoal,
        task_id: str | None,
        run_id: str,
        source_assessment: SourceAssessment | None = None,
    ) -> CorpusDocument:
        ...


class RetrievalOperator:
    def __init__(
        self,
        *,
        search_provider: SearchProvider,
        fetch_provider: FetchProvider,
        evaluator: EvidenceEvaluator | None = None,
        preview_chars: int = 160,
        corpus_store: CorpusStore | None = None,
    ) -> None:
        self.search_provider = search_provider
        self.fetch_provider = fetch_provider
        self.evaluator = evaluator or EvidenceEvaluator()
        self.preview_chars = preview_chars
        self.corpus_store = corpus_store
        self.network_access = bool(
            getattr(search_provider, "live_network", False)
            or getattr(fetch_provider, "live_network", False)
        )

    def provider_capabilities(self) -> list[JsonObject]:
        return [
            provider_capability(self.search_provider, provider_kind="search").to_dict(),
            provider_capability(self.fetch_provider, provider_kind="fetch").to_dict(),
        ]

    def run(
        self,
        goal: SearchGoal,
        *,
        journal: JournalStore,
        artifact_store: ArtifactStore,
        task_id: str | None,
        run_id: str,
        step_id_prefix: str = "retrieval",
        action_ref: str | None = None,
    ) -> RetrievalReport:
        research_profile = _research_profile_from_goal(goal)
        queries = plan_queries(goal)
        plan = QueryPlan(
            plan_id=f"plan-{goal.goal_id}",
            goal_id=goal.goal_id,
            queries=queries,
            max_sources=goal.max_sources,
            max_fetches=goal.max_fetches,
            diagnostics={
                "query_count": len(queries),
                "network_access": self.network_access,
                "budget": _goal_budget(goal),
                "provider_capabilities": self.provider_capabilities(),
                **({"research_profile": research_profile.profile_id} if research_profile is not None else {}),
            },
        )
        _append(
            journal,
            task_id,
            run_id,
            f"{step_id_prefix}-query-plan",
            "retrieval_query_plan",
            plan.to_dict(),
            action_ref=action_ref,
        )

        sources: list[SearchSource] = []
        search_attempt_ids: list[str] = []
        for index, query in enumerate(queries, start=1):
            search_error = None
            try:
                provider_sources = self.search_provider.search(query, goal=goal, plan=plan)
            except Exception as exc:  # pragma: no cover - concrete providers decide error types.
                provider_sources = []
                search_error = type(exc).__name__
            bounded_sources = _dedupe_sources(provider_sources)[: goal.max_sources]
            provider_diagnostics = _provider_search_diagnostics(self.search_provider)
            attempt_status = _search_attempt_status(
                search_error=search_error,
                bounded_sources=bounded_sources,
                provider_diagnostics=provider_diagnostics,
            )
            diagnostics = {
                "provider_source_count": len(provider_sources),
                "journaled_source_count": len(bounded_sources),
                **provider_diagnostics,
            }
            if search_error:
                diagnostics["error"] = search_error
            elif attempt_status == "failed":
                diagnostics["error"] = "provider_chain_failed"
            attempt = SearchAttempt(
                attempt_id=f"search-{goal.goal_id}-{index}",
                goal_id=goal.goal_id,
                plan_id=plan.plan_id,
                query=query,
                status=attempt_status,
                sources=[_safe_source_dict(source) for source in bounded_sources],
                diagnostics=diagnostics,
            )
            search_attempt_ids.append(attempt.attempt_id)
            sources.extend(bounded_sources)
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-search-{index}",
                "retrieval_search_attempt",
                attempt.to_dict(),
                action_ref=action_ref,
            )

        source_assessments: dict[str, SourceAssessment] = {}
        if research_profile is not None:
            for source in _dedupe_sources(sources):
                source_assessments[source.source_id] = assess_search_source(source, profile=research_profile)
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-source-assessment",
                "retrieval_source_assessment",
                {
                    "goal_id": goal.goal_id,
                    "research_profile": research_profile.to_dict(),
                    "assessments": [item.to_dict() for item in source_assessments.values()],
                    "diagnostics": source_authority_summary(list(source_assessments.values())),
                },
                action_ref=action_ref,
            )

        ranked = rank_sources(goal, _dedupe_sources(sources), research_profile=research_profile)[: goal.max_sources]
        ranking = RankSources(
            ranking_id=f"rank-{goal.goal_id}",
            goal_id=goal.goal_id,
            ranked_sources=[_safe_source_dict(source) for source in ranked],
            diagnostics={"ranked_source_count": len(ranked), "max_sources": goal.max_sources},
        )
        _append(
            journal,
            task_id,
            run_id,
            f"{step_id_prefix}-rank",
            "retrieval_rank_sources",
            ranking.to_dict(),
            action_ref=action_ref,
        )

        documents: list[tuple[FetchedDocument, str]] = []
        fetch_attempt_ids: list[str] = []
        source_by_id = {source.source_id: source for source in _dedupe_sources(sources)}
        for index, ranked_source in enumerate(ranked[: goal.max_fetches], start=1):
            source = source_by_id[ranked_source.source_id]
            fetch_error = None
            try:
                response = self.fetch_provider.fetch(source)
            except Exception as exc:  # pragma: no cover - concrete providers decide error types.
                response = None
                fetch_error = type(exc).__name__
            fetch_id = f"fetch-{goal.goal_id}-{index}"
            artifact_refs: list[str] = []
            if response is not None and response.status == "ok":
                artifact = artifact_store.write_blob(
                    kind="retrieval_fetched_document",
                    payload=response.body,
                    mime_type=response.mime_type,
                    metadata={
                        "goal_id": goal.goal_id,
                        "source_id": source.source_id,
                        "uri": source.uri,
                        "title": source.title,
                    },
                )
                preview = _preview(response.body, self.preview_chars)
                document = FetchedDocument(
                    document_id=f"doc-{goal.goal_id}-{index}",
                    goal_id=goal.goal_id,
                    source_id=source.source_id,
                    uri=source.uri,
                    title=source.title,
                    artifact_id=artifact.artifact_id,
                    payload_hash=artifact.payload_hash,
                    preview=preview,
                    size_bytes=int(artifact.metadata.get("size_bytes", 0)),
                    metadata={"mime_type": response.mime_type},
                )
                documents.append((document, response.body))
                artifact_refs.append(artifact.artifact_id)
                corpus_document = self._record_corpus_document(
                    document=document,
                    source=source,
                    goal=goal,
                    task_id=task_id,
                    run_id=run_id,
                    source_assessment=source_assessments.get(document.source_id),
                )
                if corpus_document is not None:
                    _append(
                        journal,
                        task_id,
                        run_id,
                        f"{step_id_prefix}-corpus-{index}",
                        "retrieval_corpus_document",
                        corpus_document.to_dict(),
                        action_ref=action_ref,
                        artifact_refs=[document.artifact_id],
                    )
                attempt = FetchAttempt(
                    fetch_id=fetch_id,
                    goal_id=goal.goal_id,
                    source_id=source.source_id,
                    uri=source.uri,
                    status="ok",
                    artifact_id=artifact.artifact_id,
                    payload_hash=artifact.payload_hash,
                    preview=preview,
                    size_bytes=document.size_bytes,
                    diagnostics=_safe_diagnostics(response.diagnostics),
                )
            else:
                attempt = FetchAttempt(
                    fetch_id=fetch_id,
                    goal_id=goal.goal_id,
                    source_id=source.source_id,
                    uri=source.uri,
                    status=response.status if response is not None else "failed",
                    artifact_id=None,
                    payload_hash=None,
                    preview="",
                    size_bytes=0,
                    diagnostics=_safe_diagnostics(
                        response.diagnostics if response is not None else {"error": fetch_error}
                    ),
                )
            fetch_attempt_ids.append(fetch_id)
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-fetch-{index}",
                "retrieval_fetch_attempt",
                attempt.to_dict(),
                action_ref=action_ref,
                artifact_refs=artifact_refs,
            )

        spans = []
        evidence: list[EvidenceItem] = []
        citations = []
        for index, (document, body) in enumerate(documents, start=1):
            document_spans = extract_spans(goal=goal, document=document, body=body)
            spans.extend(document_spans)
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-extract-{index}",
                "retrieval_extraction",
                {
                    "goal_id": goal.goal_id,
                    "document": document.to_dict(),
                    "spans": [span.to_dict() for span in document_spans],
                    "diagnostics": {"span_count": len(document_spans)},
                },
                action_ref=action_ref,
                artifact_refs=[document.artifact_id],
            )
            for span in document_spans:
                item = EvidenceItem(
                    evidence_id=f"evidence-{span.span_id}",
                    goal_id=goal.goal_id,
                    span_id=span.span_id,
                    document_id=document.document_id,
                    source_id=document.source_id,
                    artifact_id=document.artifact_id,
                    uri=document.uri,
                    title=document.title,
                    text=span.text,
                    score=span.score,
                    payload_hash=document.payload_hash,
                    diagnostics={
                        "start_offset": span.start_offset,
                        "end_offset": span.end_offset,
                        **(
                            {"source_assessment": source_assessments[document.source_id].to_dict()}
                            if document.source_id in source_assessments
                            else {}
                        ),
                    },
                )
                evidence.append(item)
                _append(
                    journal,
                    task_id,
                    run_id,
                    f"{step_id_prefix}-evidence-{len(evidence)}",
                    "retrieval_evidence",
                    item.to_dict(),
                    action_ref=action_ref,
                    artifact_refs=[document.artifact_id],
                )
                citation = citation_from_evidence(item, span)
                citations.append(citation)
                _append(
                    journal,
                    task_id,
                    run_id,
                    f"{step_id_prefix}-citation-{len(citations)}",
                    "retrieval_citation",
                    citation.to_dict(),
                    action_ref=action_ref,
                    artifact_refs=[document.artifact_id],
                )

        decision = self.evaluator.evaluate(
            goal=goal,
            evidence=evidence,
            citations=citations,
            research_profile=research_profile,
        )
        _append(
            journal,
            task_id,
            run_id,
            f"{step_id_prefix}-evaluate",
            "retrieval_evaluation_decision",
            decision.to_dict(),
            action_ref=action_ref,
        )
        report = RetrievalReport(
            report_id=f"report-{goal.goal_id}",
            goal_id=goal.goal_id,
            status=decision.status,
            query_plan_id=plan.plan_id,
            search_attempt_ids=search_attempt_ids,
            fetch_attempt_ids=fetch_attempt_ids,
            evidence_ids=[item.evidence_id for item in evidence],
            citation_ids=[item.citation_id for item in citations],
            evaluation_id=decision.decision_id,
            artifact_refs=_ordered_unique([item.artifact_id for item in evidence]),
            preview=_preview("; ".join(item.text for item in evidence), self.preview_chars),
            diagnostics={
                "sufficient": decision.sufficient,
                "reason": decision.reason,
                "network_access": self.network_access,
                "budget": _goal_budget(goal),
                "provider_capabilities": self.provider_capabilities(),
                "search_attempt_count": len(search_attempt_ids),
                "fetch_attempt_count": len(fetch_attempt_ids),
                "evidence_count": len(evidence),
                "citation_count": len(citations),
                **(
                    {
                        "research_profile": research_profile.profile_id,
                        "source_authority": source_authority_summary(list(source_assessments.values())),
                    }
                    if research_profile is not None
                    else {}
                ),
            },
        )
        _append(
            journal,
            task_id,
            run_id,
            f"{step_id_prefix}-report",
            "retrieval_report",
            report.to_dict(),
            action_ref=action_ref,
            artifact_refs=report.artifact_refs,
        )
        return report

    def _record_corpus_document(
        self,
        *,
        document: FetchedDocument,
        source: SearchSource,
        goal: SearchGoal,
        task_id: str | None,
        run_id: str,
        source_assessment: SourceAssessment | None,
    ) -> CorpusDocument | None:
        if self.corpus_store is None:
            return None
        return self.corpus_store.record_retrieval_document(
            document=document,
            source=source,
            goal=goal,
            task_id=task_id,
            run_id=run_id,
            source_assessment=source_assessment,
        )


def register_retrieval_tool(
    registry: ToolRegistry,
    *,
    operator: RetrievalOperator,
    journal: JournalStore,
    artifact_store: ArtifactStore,
) -> None:
    registry.register(
        "retrieval.run",
        _tool_executor(operator=operator, journal=journal, artifact_store=artifact_store),
        manifest=ToolManifest(
            name="retrieval.run",
            version="1",
            resource_kind="retrieval",
            operator_kind="run",
            side_effect_class="network" if operator.network_access else "read",
            permissions_required=["network:fetch"] if operator.network_access else [],
            enabled=True,
            description="retrieval.run",
            input_schema={
                "query": "str",
                "goal_id": "str optional",
                "max_queries": "int optional",
                "max_sources": "int optional",
                "max_fetches": "int optional",
                "max_spans_per_document": "int optional",
                "metadata": "object optional",
            },
        ),
    )


def _tool_executor(
    *,
    operator: RetrievalOperator,
    journal: JournalStore,
    artifact_store: ArtifactStore,
):
    def execute(action: CandidateAction) -> ToolResult:
        host_context = action.payload.get("_host_context")
        host_context = host_context if isinstance(host_context, dict) else {}
        task_id = host_context.get("task_id", action.payload.get("task_id"))
        run_id = host_context.get("run_id", action.payload.get("run_id"))
        if not isinstance(task_id, str) or not isinstance(run_id, str):
            return ToolResult(
                observation=_tool_observation(
                    action,
                    "failed",
                    {"reason": "task_id_and_run_id_required"},
                ),
                artifact_refs=[],
            )
        goal = _goal_from_payload(action)
        report = operator.run(
            goal,
            journal=journal,
            artifact_store=artifact_store,
            task_id=task_id,
            run_id=run_id,
            step_id_prefix=str(action.payload.get("step_id_prefix", f"retrieval-{action.action_id}")),
            action_ref=action.action_id,
        )
        artifacts = [
            artifact
            for artifact_id in report.artifact_refs
            if (artifact := artifact_store.get(artifact_id)) is not None
        ]
        return ToolResult(
            observation=_tool_observation(action, "ok", {"report": report.to_dict()}),
            artifact_refs=artifacts,
        )

    return execute


def _goal_from_payload(action: CandidateAction) -> SearchGoal:
    goal_data = action.payload.get("goal")
    data = goal_data if isinstance(goal_data, dict) else action.payload
    query = str(data.get("query", ""))
    goal_id = str(data.get("goal_id", f"goal-{action.action_id}"))
    return SearchGoal(
        goal_id=goal_id,
        query=query,
        max_queries=_positive_int(data.get("max_queries"), default=1),
        max_sources=_positive_int(data.get("max_sources"), default=5),
        max_fetches=_positive_int(data.get("max_fetches"), default=3),
        max_spans_per_document=_positive_int(data.get("max_spans_per_document"), default=2),
        metadata=_dict_or_empty(data.get("metadata")),
    )


def _research_profile_from_goal(goal: SearchGoal) -> ResearchProfile | None:
    raw_profile = goal.metadata.get("research_profile_id", goal.metadata.get("research_profile"))
    if not isinstance(raw_profile, str):
        return None
    return profile_by_id(raw_profile)


def _goal_budget(goal: SearchGoal) -> JsonObject:
    return {
        "max_queries": goal.max_queries,
        "max_sources": goal.max_sources,
        "max_fetches": goal.max_fetches,
        "max_spans_per_document": goal.max_spans_per_document,
    }


def _provider_search_diagnostics(provider) -> JsonObject:
    raw = getattr(provider, "search_diagnostics", None)
    if callable(raw):
        value = raw()
        if isinstance(value, dict) and value:
            return {"provider_diagnostics": _safe_json(dict(value))}
    value = getattr(provider, "last_search_diagnostics", {})
    if isinstance(value, dict) and value:
        return {"provider_diagnostics": _safe_json(dict(value))}
    return {}


def _search_attempt_status(
    *,
    search_error: str | None,
    bounded_sources: list[SearchSource],
    provider_diagnostics: JsonObject,
) -> str:
    if search_error:
        return "failed"
    if bounded_sources:
        return "ok"
    diagnostics = provider_diagnostics.get("provider_diagnostics")
    if isinstance(diagnostics, dict) and diagnostics.get("status") == "failed":
        return "failed"
    return "empty"


def _append(
    journal: JournalStore,
    task_id: str | None,
    run_id: str,
    step_id: str,
    kind: str,
    data: JsonObject,
    *,
    action_ref: str | None = None,
    artifact_refs: list[str] | None = None,
) -> None:
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        kind=kind,
        data=data,
        action_ref=action_ref,
        state_delta={"retrieval_stage": kind},
        artifact_refs=artifact_refs or [],
    )


def _tool_observation(action: CandidateAction, status: str, content: JsonObject) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="tool_result",
        status=status,
        source="tool:retrieval.run",
        content=content,
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def _dedupe_sources(sources: list[SearchSource]) -> list[SearchSource]:
    seen: set[str] = set()
    result: list[SearchSource] = []
    for source in sources:
        key = source.source_id or source.uri
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _preview(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _safe_diagnostics(data: JsonObject) -> JsonObject:
    return _safe_json(data)


def _safe_source_dict(source: SearchSource | RankedSource) -> JsonObject:
    data = source.to_dict()
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        data["metadata"] = _safe_json(metadata)
    return data


def _safe_json(data: JsonObject) -> JsonObject:
    safe: JsonObject = {}
    for key, value in data.items():
        lowered = key.lower()
        if "body" in lowered or "raw" in lowered:
            safe[key] = "[omitted]"
        elif isinstance(value, str):
            safe[key] = _preview(value, 160)
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, list):
            safe[key] = [_safe_list_item(item) for item in value[:10]]
        elif isinstance(value, dict):
            safe[key] = _safe_json(value)
        else:
            safe[key] = str(value)[:160]
    return safe


def _dict_or_empty(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _safe_list_item(value):
    if isinstance(value, str):
        return _preview(value, 160)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return _safe_json(value)
    return str(value)[:160]


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)
