from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import CandidateAction, JsonObject, Observation, ToolManifest
from kernel_v3.journal import JournalStore
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.research.contracts import CorpusDocument, ResearchProfile, SourceAssessment
from kernel_v3.research.profile_policy import profile_discovery_source_kinds
from kernel_v3.research.profiles import profile_by_id
from kernel_v3.research.source_policy import (
    assess_search_source,
    source_authority_summary,
    source_quality_summary,
)
from kernel_v3.retrieval.citations import citation_from_evidence
from kernel_v3.retrieval.contracts import (
    DiscoveryExpansion,
    EvidenceEvaluationDecision,
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
from kernel_v3.retrieval.evidence_compaction import EvidenceCandidate, compact_evidence_candidates
from kernel_v3.retrieval.discovery import (
    build_next_tool_actions,
    build_research_graph,
    expand_discovery_sources,
)
from kernel_v3.retrieval.document_expansion import expand_document_links
from kernel_v3.retrieval.evaluate import EvidenceEvaluator, is_discovery_goal, qualify_evidence_candidate
from kernel_v3.retrieval.extract import extract_spans
from kernel_v3.retrieval.providers import FetchProvider, FetchResponse, SearchProvider, provider_capability
from kernel_v3.retrieval.query_campaign import build_query_campaign
from kernel_v3.retrieval.rank import rank_sources
from kernel_v3.tools import ToolRegistry, ToolResult


RETRIEVAL_BUDGET_CAPS = {
    "max_queries": 256,
    "max_sources": 10_000,
    "max_fetches": 4_096,
    "max_spans_per_document": 128,
}
DEFAULT_EVIDENCE_ITEM_LIMIT = 64
EVIDENCE_ITEM_LIMIT_CAP = 512
TARGET_ENTITY_EXEMPT_SOURCE_KINDS = {
    "direct_url",
    "sec_companyfacts_json",
    "sec_submissions_json",
    "sec_primary_filing_document",
    "sec_complete_submission_text",
    "sec_exhibit_document",
    "fred_series_page",
    "fred_observations_csv",
    "fiscaldata_api_json",
}


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
        fetch_concurrency: int = 8,
    ) -> None:
        self.search_provider = search_provider
        self.fetch_provider = fetch_provider
        self.evaluator = evaluator or EvidenceEvaluator()
        self.preview_chars = preview_chars
        self.corpus_store = corpus_store
        self.fetch_concurrency = max(1, int(fetch_concurrency))
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
        requested_goal = goal
        goal = _bounded_goal(goal)
        research_profile = _research_profile_from_goal(goal)
        query_campaign = build_query_campaign(goal, research_profile=research_profile)
        queries = query_campaign.queries
        plan = QueryPlan(
            plan_id=f"plan-{goal.goal_id}",
            goal_id=goal.goal_id,
            queries=queries,
            max_sources=goal.max_sources,
            max_fetches=goal.max_fetches,
            diagnostics={
                "query_count": len(queries),
                "query_campaign": query_campaign.diagnostics,
                "network_access": self.network_access,
                "budget": _goal_budget(goal),
                **_budget_clamp_diagnostics(requested_goal, goal),
                "fetch_concurrency": min(self.fetch_concurrency, max(1, goal.max_fetches)),
                "provider_capabilities": self.provider_capabilities(),
                **(_research_query_strategy_diagnostics(research_profile) if research_profile is not None else {}),
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
        search_summaries: list[JsonObject] = []
        for index, query in enumerate(queries, start=1):
            search_error = None
            try:
                provider_sources = self.search_provider.search(query, goal=goal, plan=plan)
            except Exception as exc:  # pragma: no cover - concrete providers decide error types.
                provider_sources = []
                search_error = type(exc).__name__
            search_candidate_limit = _search_candidate_limit(goal)
            bounded_sources = _dedupe_sources(provider_sources)[:search_candidate_limit]
            provider_diagnostics = _provider_search_diagnostics(self.search_provider)
            attempt_status = _search_attempt_status(
                search_error=search_error,
                bounded_sources=bounded_sources,
                provider_diagnostics=provider_diagnostics,
            )
            diagnostics = {
                "provider_source_count": len(provider_sources),
                "journaled_source_count": len(bounded_sources),
                "search_candidate_limit": search_candidate_limit,
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
            search_summaries.append(
                {
                    "attempt_id": attempt.attempt_id,
                    "query": query,
                    "status": attempt_status,
                    "source_count": len(bounded_sources),
                    "error": search_error or diagnostics.get("error"),
                }
            )
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-search-{index}",
                "retrieval_search_attempt",
                attempt.to_dict(),
                action_ref=action_ref,
            )

        discovery_expansions: list[DiscoveryExpansion] = []
        expansion_actions = []
        expanded_sources, discovery_expansions, expansion_actions = expand_discovery_sources(
            goal=goal,
            sources=_dedupe_sources(sources),
            research_profile=research_profile,
            max_candidates=min(max(1, goal.max_sources * 8), 256),
        )
        if expanded_sources:
            sources.extend(expanded_sources)
        if discovery_expansions:
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-discovery-expansion",
                "retrieval_discovery_expansion",
                {
                    "goal_id": goal.goal_id,
                    "expanded_source_count": len(expanded_sources),
                    "expansion_count": len(discovery_expansions),
                    "expansions": [item.to_dict() for item in discovery_expansions[:64]],
                    "diagnostics": {
                        "truncated": len(discovery_expansions) > 64,
                        "next_tool_action_count": len(expansion_actions),
                    },
                },
                action_ref=action_ref,
            )

        source_assessments: dict[str, SourceAssessment] = {}
        source_quality: JsonObject = {}
        if research_profile is not None:
            for source in _dedupe_sources(sources):
                source_assessments[source.source_id] = assess_search_source(source, profile=research_profile)
            source_quality = source_quality_summary(
                list(source_assessments.values()),
                authority_requirement=_source_authority_requirement(goal),
            )
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
                    "diagnostics": {
                        **source_authority_summary(list(source_assessments.values())),
                        "source_quality": source_quality,
                    },
                },
                action_ref=action_ref,
            )

        ranked_all = rank_sources(goal, _dedupe_sources(sources), research_profile=research_profile)
        fetchable_ranked, source_rejections = _fetchable_ranked_sources(goal, ranked_all)
        ranked = fetchable_ranked[: goal.max_sources] if fetchable_ranked else ranked_all[: goal.max_sources]
        ranking = RankSources(
            ranking_id=f"rank-{goal.goal_id}",
            goal_id=goal.goal_id,
            ranked_sources=[_safe_source_dict(source) for source in ranked],
            diagnostics={
                "ranked_source_count": len(ranked),
                "raw_ranked_source_count": len(ranked_all),
                "rejected_ranked_source_count": len(source_rejections),
                "max_sources": goal.max_sources,
            },
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

        if source_rejections:
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-source-rejections",
                "retrieval_source_rejections",
                {
                    "goal_id": goal.goal_id,
                    "rejected_count": len(source_rejections),
                    "items": source_rejections[:50],
                    "diagnostics": {
                        "truncated": len(source_rejections) > 50,
                        "reasons": _count_by_key(source_rejections, "reason"),
                    },
                },
                action_ref=action_ref,
            )

        documents: list[tuple[FetchedDocument, str]] = []
        fetch_attempt_ids: list[str] = []
        fetch_summaries: list[JsonObject] = []
        source_by_id = {source.source_id: source for source in _dedupe_sources(sources)}
        if fetchable_ranked:
            fetch_queue = _initial_fetch_queue_with_discovery_supplements(
                goal,
                fetchable_ranked=fetchable_ranked,
                ranked_all=ranked_all,
                research_profile=research_profile,
            )
        elif _should_fetch_rejected_sources(goal, research_profile=research_profile, source_rejections=source_rejections):
            fetch_queue = ranked_all
        else:
            fetch_queue = []
        initial_fetch_limit = _initial_fetch_limit(goal, ranked=fetch_queue)
        fetch_jobs = [
            (index, ranked_source, source_by_id[ranked_source.source_id])
            for index, ranked_source in enumerate(fetch_queue[:initial_fetch_limit], start=1)
            if ranked_source.source_id in source_by_id
        ]
        (
            documents,
            fetch_attempt_ids,
            fetch_summaries,
        ) = self._fetch_jobs_and_record(
            fetch_jobs,
            goal=goal,
            journal=journal,
            artifact_store=artifact_store,
            task_id=task_id,
            run_id=run_id,
            step_id_prefix=step_id_prefix,
            action_ref=action_ref,
            source_assessments=source_assessments,
        )

        all_fetch_jobs = list(fetch_jobs)
        document_expanded_sources: list[SearchSource] = []
        remaining_fetch_budget = max(0, goal.max_fetches - len(fetch_attempt_ids))
        if documents and remaining_fetch_budget > 0:
            document_expansions: list[DiscoveryExpansion]
            document_expansion_actions = []
            document_expanded_sources, document_expansions, document_expansion_actions = expand_document_links(
                goal=goal,
                documents=documents,
                source_by_id=source_by_id,
                max_candidates=min(remaining_fetch_budget, max(1, goal.max_sources * 4), 128),
            )
            if document_expansions:
                discovery_expansions.extend(document_expansions)
                expansion_actions.extend(document_expansion_actions)
                _append(
                    journal,
                    task_id,
                    run_id,
                    f"{step_id_prefix}-document-expansion",
                    "retrieval_document_expansion",
                    {
                        "goal_id": goal.goal_id,
                        "expanded_source_count": len(document_expanded_sources),
                        "expansion_count": len(document_expansions),
                        "expansions": [item.to_dict() for item in document_expansions[:64]],
                        "diagnostics": {
                            "truncated": len(document_expansions) > 64,
                            "next_tool_action_count": len(document_expansion_actions),
                            "remaining_fetch_budget": remaining_fetch_budget,
                        },
                    },
                    action_ref=action_ref,
                )
            if document_expanded_sources:
                sources.extend(document_expanded_sources)
                for source in document_expanded_sources:
                    source_by_id[source.source_id] = source
                    if research_profile is not None:
                        source_assessments[source.source_id] = assess_search_source(source, profile=research_profile)
                if research_profile is not None:
                    source_quality = source_quality_summary(
                        list(source_assessments.values()),
                        authority_requirement=_source_authority_requirement(goal),
                    )
                    _append(
                        journal,
                        task_id,
                        run_id,
                        f"{step_id_prefix}-source-assessment-document-expansion",
                        "retrieval_source_assessment",
                        {
                            "goal_id": goal.goal_id,
                            "research_profile": research_profile.to_dict(),
                            "assessments": [
                                source_assessments[source.source_id].to_dict()
                                for source in document_expanded_sources
                                if source.source_id in source_assessments
                            ],
                            "diagnostics": {
                                **source_authority_summary(list(source_assessments.values())),
                                "source_quality": source_quality,
                                "assessment_scope": "document_expansion",
                            },
                        },
                        action_ref=action_ref,
                    )
                expanded_ranked_all = rank_sources(goal, document_expanded_sources, research_profile=research_profile)
                expanded_fetchable_ranked, expanded_source_rejections = _fetchable_ranked_sources(goal, expanded_ranked_all)
                source_rejections.extend(expanded_source_rejections)
                _append(
                    journal,
                    task_id,
                    run_id,
                    f"{step_id_prefix}-rank-document-expansion",
                    "retrieval_rank_sources",
                    RankSources(
                        ranking_id=f"rank-{goal.goal_id}-document-expansion",
                        goal_id=goal.goal_id,
                        ranked_sources=[_safe_source_dict(source) for source in expanded_ranked_all],
                        diagnostics={
                            "ranked_source_count": len(expanded_ranked_all),
                            "raw_ranked_source_count": len(expanded_ranked_all),
                            "rejected_ranked_source_count": len(expanded_source_rejections),
                            "max_sources": goal.max_sources,
                            "ranking_scope": "document_expansion",
                        },
                    ).to_dict(),
                    action_ref=action_ref,
                )
                if _wants_sec_filing_text(goal):
                    expansion_fetch_queue = _merge_ranked_sources(
                        max_count=remaining_fetch_budget,
                        groups=[
                            _priority_sec_filing_discovery_sources(expanded_ranked_all),
                            _priority_sec_filing_document_sources(expanded_fetchable_ranked),
                            expanded_fetchable_ranked,
                        ],
                    )
                elif expanded_fetchable_ranked:
                    expansion_fetch_queue = expanded_fetchable_ranked
                elif _should_fetch_rejected_sources(
                    goal,
                    research_profile=research_profile,
                    source_rejections=expanded_source_rejections,
                ):
                    expansion_fetch_queue = expanded_ranked_all
                else:
                    expansion_fetch_queue = []
                expansion_fetch_limit = _document_expansion_fetch_limit(
                    goal,
                    fetch_queue=expansion_fetch_queue,
                    remaining_fetch_budget=remaining_fetch_budget,
                    depth=1,
                )
                expanded_fetch_jobs = [
                    (index, ranked_source, source_by_id[ranked_source.source_id])
                    for index, ranked_source in enumerate(
                        expansion_fetch_queue[:expansion_fetch_limit],
                        start=len(fetch_attempt_ids) + 1,
                    )
                    if ranked_source.source_id in source_by_id
                ]
                (
                    extra_documents,
                    extra_fetch_attempt_ids,
                    extra_fetch_summaries,
                ) = self._fetch_jobs_and_record(
                    expanded_fetch_jobs,
                    goal=goal,
                    journal=journal,
                    artifact_store=artifact_store,
                    task_id=task_id,
                    run_id=run_id,
                    step_id_prefix=step_id_prefix,
                    action_ref=action_ref,
                    source_assessments=source_assessments,
                )
                documents.extend(extra_documents)
                fetch_attempt_ids.extend(extra_fetch_attempt_ids)
                fetch_summaries.extend(extra_fetch_summaries)
                all_fetch_jobs.extend(expanded_fetch_jobs)
                ranked_all = rank_sources(goal, _dedupe_sources(sources), research_profile=research_profile)
                remaining_fetch_budget = max(0, goal.max_fetches - len(fetch_attempt_ids))
                if extra_documents and remaining_fetch_budget > 0:
                    second_expanded_sources, second_expansions, second_actions = expand_document_links(
                        goal=goal,
                        documents=extra_documents,
                        source_by_id=source_by_id,
                        max_candidates=min(remaining_fetch_budget, max(1, goal.max_sources * 4), 128),
                    )
                    if second_expansions:
                        discovery_expansions.extend(second_expansions)
                        expansion_actions.extend(second_actions)
                        _append(
                            journal,
                            task_id,
                            run_id,
                            f"{step_id_prefix}-document-expansion-2",
                            "retrieval_document_expansion",
                            {
                                "goal_id": goal.goal_id,
                                "expanded_source_count": len(second_expanded_sources),
                                "expansion_count": len(second_expansions),
                                "expansions": [item.to_dict() for item in second_expansions[:64]],
                                "diagnostics": {
                                    "truncated": len(second_expansions) > 64,
                                    "next_tool_action_count": len(second_actions),
                                    "remaining_fetch_budget": remaining_fetch_budget,
                                    "expansion_depth": 2,
                                },
                            },
                            action_ref=action_ref,
                        )
                    if second_expanded_sources:
                        sources.extend(second_expanded_sources)
                        for source in second_expanded_sources:
                            source_by_id[source.source_id] = source
                            if research_profile is not None:
                                source_assessments[source.source_id] = assess_search_source(source, profile=research_profile)
                        second_ranked_all = rank_sources(goal, second_expanded_sources, research_profile=research_profile)
                        second_fetchable_ranked, second_source_rejections = _fetchable_ranked_sources(goal, second_ranked_all)
                        source_rejections.extend(second_source_rejections)
                        _append(
                            journal,
                            task_id,
                            run_id,
                            f"{step_id_prefix}-rank-document-expansion-2",
                            "retrieval_rank_sources",
                            RankSources(
                                ranking_id=f"rank-{goal.goal_id}-document-expansion-2",
                                goal_id=goal.goal_id,
                                ranked_sources=[_safe_source_dict(source) for source in second_ranked_all],
                                diagnostics={
                                    "ranked_source_count": len(second_ranked_all),
                                    "raw_ranked_source_count": len(second_ranked_all),
                                    "rejected_ranked_source_count": len(second_source_rejections),
                                    "max_sources": goal.max_sources,
                                    "ranking_scope": "document_expansion",
                                    "expansion_depth": 2,
                                },
                            ).to_dict(),
                            action_ref=action_ref,
                        )
                        if _wants_sec_filing_text(goal):
                            second_fetch_queue = _merge_ranked_sources(
                                max_count=remaining_fetch_budget,
                                groups=[
                                    _priority_sec_filing_discovery_sources(second_ranked_all),
                                    _priority_sec_filing_document_sources(second_fetchable_ranked),
                                    second_fetchable_ranked,
                                ],
                            )
                        else:
                            second_fetch_queue = second_fetchable_ranked
                        if not second_fetch_queue and _should_fetch_rejected_sources(
                            goal,
                            research_profile=research_profile,
                            source_rejections=second_source_rejections,
                        ):
                            second_fetch_queue = _merge_ranked_sources(
                                max_count=remaining_fetch_budget,
                                groups=[
                                    _priority_sec_filing_document_sources(second_ranked_all),
                                    second_ranked_all,
                                ],
                            )
                        second_fetch_jobs = [
                            (index, ranked_source, source_by_id[ranked_source.source_id])
                            for index, ranked_source in enumerate(
                                second_fetch_queue[:remaining_fetch_budget],
                                start=len(fetch_attempt_ids) + 1,
                            )
                            if ranked_source.source_id in source_by_id
                        ]
                        (
                            second_documents,
                            second_fetch_attempt_ids,
                            second_fetch_summaries,
                        ) = self._fetch_jobs_and_record(
                            second_fetch_jobs,
                            goal=goal,
                            journal=journal,
                            artifact_store=artifact_store,
                            task_id=task_id,
                            run_id=run_id,
                            step_id_prefix=step_id_prefix,
                            action_ref=action_ref,
                            source_assessments=source_assessments,
                        )
                        documents.extend(second_documents)
                        fetch_attempt_ids.extend(second_fetch_attempt_ids)
                        fetch_summaries.extend(second_fetch_summaries)
                        all_fetch_jobs.extend(second_fetch_jobs)
                        ranked_all = rank_sources(goal, _dedupe_sources(sources), research_profile=research_profile)

        spans = []
        evidence_candidates: list[EvidenceCandidate] = []
        evidence: list[EvidenceItem] = []
        citations = []
        rejected_evidence: list[JsonObject] = []
        evidence_item_limit = _evidence_item_limit(goal)
        for index, (document, body) in enumerate(documents, start=1):
            try:
                document_spans = extract_spans(goal=goal, document=document, body=body)
            except Exception as exc:  # pragma: no cover - exact parser failures vary by document type.
                error_diagnostics = {
                    "span_count": 0,
                    "status": "failed",
                    "reason": "extract_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
                _append(
                    journal,
                    task_id,
                    run_id,
                    f"{step_id_prefix}-extract-{index}",
                    "retrieval_extraction",
                    {
                        "goal_id": goal.goal_id,
                        "document": document.to_dict(),
                        "spans": [],
                        "diagnostics": error_diagnostics,
                    },
                    action_ref=action_ref,
                    artifact_refs=[document.artifact_id] if document.artifact_id else [],
                )
                rejected_evidence.append(
                    {
                        "source_id": document.source_id,
                        "document_id": document.document_id,
                        "uri": document.uri,
                        "title": document.title,
                        "reason": "extract_failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "preview": _preview(body, self.preview_chars),
                    }
                )
                continue
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
                    "diagnostics": {
                        "span_count": len(document_spans),
                        "text_modes": _ordered_unique(
                            [
                                str(span.metadata.get("text_mode"))
                                for span in document_spans
                                if isinstance(span.metadata.get("text_mode"), str)
                            ]
                        ),
                    },
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
                qualification = qualify_evidence_candidate(goal=goal, evidence=item, research_profile=research_profile)
                item = EvidenceItem(
                    evidence_id=item.evidence_id,
                    goal_id=item.goal_id,
                    span_id=item.span_id,
                    document_id=item.document_id,
                    source_id=item.source_id,
                    artifact_id=item.artifact_id,
                    uri=item.uri,
                    title=item.title,
                    text=item.text,
                    score=item.score,
                    payload_hash=item.payload_hash,
                    diagnostics={**item.diagnostics, "qualification": qualification},
                )
                if not bool(qualification.get("accepted")):
                    rejected_evidence.append(
                        {
                            "evidence_id": item.evidence_id,
                            "source_id": item.source_id,
                            "document_id": item.document_id,
                            "uri": item.uri,
                            "title": item.title,
                            "reason": qualification.get("reason"),
                            "source_authority": qualification.get("source_authority", {}),
                            "missing_profile_facets": qualification.get("missing_profile_facets", []),
                            "missing_finance_facets": qualification.get("missing_finance_facets", []),
                            "required_target_phrases": qualification.get("required_target_phrases", []),
                            "matched_target_phrases": qualification.get("matched_target_phrases", []),
                            "missing_target_phrases": qualification.get("missing_target_phrases", []),
                            "preview": _preview(item.text, self.preview_chars),
                        }
                    )
                    continue
                evidence_candidates.append(EvidenceCandidate(evidence=item, span=span))

        selected_candidates, compaction_rejections, compaction_diagnostics = compact_evidence_candidates(
            evidence_candidates,
            goal=goal,
            research_profile=research_profile,
            limit=evidence_item_limit,
        )
        rejected_evidence.extend(compaction_rejections)
        for candidate in selected_candidates:
            item = candidate.evidence
            evidence.append(item)
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-evidence-{len(evidence)}",
                "retrieval_evidence",
                item.to_dict(),
                action_ref=action_ref,
                artifact_refs=[item.artifact_id],
            )
            citation = citation_from_evidence(item, candidate.span)
            citations.append(citation)
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-citation-{len(citations)}",
                "retrieval_citation",
                citation.to_dict(),
                action_ref=action_ref,
                artifact_refs=[item.artifact_id],
            )

        if rejected_evidence:
            _append(
                journal,
                task_id,
                run_id,
                f"{step_id_prefix}-evidence-rejections",
                "retrieval_evidence_rejections",
                {
                    "goal_id": goal.goal_id,
                    "rejected_count": len(rejected_evidence),
                    "items": rejected_evidence[:50],
                    "diagnostics": {
                        "truncated": len(rejected_evidence) > 50,
                        "reasons": _count_by_key(rejected_evidence, "reason"),
                    },
                },
                action_ref=action_ref,
            )

        decision = self.evaluator.evaluate(
            goal=goal,
            evidence=evidence,
            citations=citations,
            research_profile=research_profile,
        )
        if _decision_has_source_authority_gap(
            decision=decision,
            source_quality=source_quality,
            rejected_evidence=rejected_evidence,
            evidence=evidence,
            citations=citations,
            source_rejections=source_rejections,
        ):
            decision = EvidenceEvaluationDecision(
                decision_id=decision.decision_id,
                goal_id=decision.goal_id,
                status="insufficient_evidence",
                sufficient=False,
                reason=_authority_gap_reason(source_quality),
                evidence_count=decision.evidence_count,
                citation_count=decision.citation_count,
                diagnostics={
                    **decision.diagnostics,
                    "source_quality": source_quality,
                    "source_authority_requirement": source_quality.get("authority_requirement") or _source_authority_requirement(goal),
                    "original_reason": decision.reason,
                },
            )
        failure_attribution = _failure_attribution(
            decision=decision,
            queries=queries,
            sources=sources,
            ranked=ranked,
            source_rejections=source_rejections,
            fetch_jobs=all_fetch_jobs,
            fetch_summaries=fetch_summaries,
            documents=documents,
            spans=spans,
            evidence_candidates=evidence_candidates,
            rejected_evidence=rejected_evidence,
            evidence=evidence,
            citations=citations,
            search_summaries=search_summaries,
            source_quality=source_quality,
        )
        if (
            not decision.sufficient
            and not evidence
            and documents
            and is_discovery_goal(goal=goal, research_profile=research_profile)
        ):
            decision = EvidenceEvaluationDecision(
                decision_id=decision.decision_id,
                goal_id=decision.goal_id,
                status="sufficient",
                sufficient=True,
                reason="discovery_artifact_available",
                evidence_count=0,
                citation_count=0,
                diagnostics={
                    **decision.diagnostics,
                    "discovery_goal": True,
                    "discovery_artifact_count": len(documents),
                    "original_reason": decision.reason,
                },
            )
            failure_attribution = {
                **failure_attribution,
                "primary_failure_mode": "none",
                "reason": "discovery_artifact_available",
            }
        _append(
            journal,
            task_id,
            run_id,
            f"{step_id_prefix}-evaluate",
            "retrieval_evaluation_decision",
            decision.to_dict(),
            action_ref=action_ref,
        )
        next_tool_actions = (
            []
            if decision.sufficient
            else build_next_tool_actions(
                goal=goal,
                failure_attribution=failure_attribution,
                source_rejections=source_rejections,
                expansion_actions=expansion_actions,
                fetch_summaries=fetch_summaries,
            )
        )
        research_graph = build_research_graph(
            goal=goal,
            queries=queries,
            sources=_dedupe_sources(sources),
            ranked=ranked_all,
            discovery_expansions=discovery_expansions,
            documents=documents,
            evidence=evidence,
            citations=citations,
            next_tool_actions=next_tool_actions,
        )
        operator_critic = {
            "goal_id": goal.goal_id,
            "decision_status": decision.status,
            "sufficient": decision.sufficient,
            "primary_failure_mode": failure_attribution.get("primary_failure_mode"),
            "next_strategy_hint": failure_attribution.get("next_strategy_hint"),
            "next_tool_actions": [action.to_dict() for action in next_tool_actions],
            "research_graph_summary": research_graph.diagnostics,
            "diagnostics": {
                "source_rejection_reasons": _count_by_key(source_rejections, "reason"),
                "fetch_failure_reasons": _count_by_key(
                    [item for item in fetch_summaries if item.get("reason")],
                    "reason",
                ),
            },
        }
        _append(
            journal,
            task_id,
            run_id,
            f"{step_id_prefix}-operator-critic",
            "retrieval_operator_critic",
            operator_critic,
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
                "evaluation_diagnostics": decision.diagnostics,
                "goal_query": goal.query,
                "interaction_preferences": goal.metadata.get("interaction_preferences", {}),
                "response_language": goal.metadata.get("response_language"),
                "network_access": self.network_access,
                "budget": _goal_budget(goal),
                **_budget_clamp_diagnostics(requested_goal, goal),
                "fetch_concurrency": min(self.fetch_concurrency, max(1, len(all_fetch_jobs))),
                "provider_capabilities": self.provider_capabilities(),
                "search_attempt_count": len(search_attempt_ids),
                "search_summaries": search_summaries[-16:],
                "fetch_attempt_count": len(fetch_attempt_ids),
                "fetch_summaries": fetch_summaries[-16:],
                "failure_attribution": failure_attribution,
                "next_tool_actions": [action.to_dict() for action in next_tool_actions],
                "research_graph": research_graph.to_dict(),
                "operator_critic": operator_critic,
                "discovery_expansion_count": len(discovery_expansions),
                "discovery_expanded_source_count": len(expanded_sources),
                "document_expanded_source_count": len(document_expanded_sources),
                "source_rejection_count": len(source_rejections),
                "source_rejection_reasons": _count_by_key(source_rejections, "reason"),
                "candidate_span_count": len(spans),
                "evidence_candidate_count": len(evidence_candidates),
                "evidence_compaction": compaction_diagnostics,
                "evidence_item_limit": evidence_item_limit,
                "rejected_evidence_count": len(rejected_evidence),
                "rejected_evidence_reasons": _count_by_key(rejected_evidence, "reason"),
                "evidence_count": len(evidence),
                "citation_count": len(citations),
                **(
                    {
                        "research_profile": research_profile.profile_id,
                        "source_authority": source_authority_summary(list(source_assessments.values())),
                        "source_quality": source_quality,
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

    def _fetch_jobs_and_record(
        self,
        fetch_jobs: list[tuple[int, RankedSource, SearchSource]],
        *,
        goal: SearchGoal,
        journal: JournalStore,
        artifact_store: ArtifactStore,
        task_id: str | None,
        run_id: str,
        step_id_prefix: str,
        action_ref: str | None,
        source_assessments: dict[str, SourceAssessment],
    ) -> tuple[list[tuple[FetchedDocument, str]], list[str], list[JsonObject]]:
        documents: list[tuple[FetchedDocument, str]] = []
        fetch_attempt_ids: list[str] = []
        fetch_summaries: list[JsonObject] = []
        for index, _ranked_source, source, response, fetch_error in self._fetch_ranked_sources(fetch_jobs):
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
                    metadata={"mime_type": response.mime_type, "source_metadata": _safe_json(source.metadata)},
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
            fetch_summaries.append(
                {
                    "fetch_id": fetch_id,
                    "source_id": source.source_id,
                    "uri": source.uri,
                    "title": _preview(source.title, 160),
                    "provider": source.provider,
                    "source_kind": _search_source_kind(source),
                    "source_family": _search_source_family(source),
                    "host": _uri_host(source.uri),
                    "status": attempt.status,
                    "size_bytes": attempt.size_bytes,
                    "reason": attempt.diagnostics.get("reason") or attempt.diagnostics.get("error"),
                }
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
        return documents, fetch_attempt_ids, fetch_summaries

    def _fetch_ranked_sources(
        self,
        fetch_jobs: list[tuple[int, RankedSource, SearchSource]],
    ) -> list[tuple[int, RankedSource, SearchSource, FetchResponse | None, str | None]]:
        if len(fetch_jobs) <= 1 or self.fetch_concurrency <= 1:
            return [self._fetch_one(index, ranked_source, source) for index, ranked_source, source in fetch_jobs]
        workers = min(self.fetch_concurrency, len(fetch_jobs))
        results: dict[int, tuple[int, RankedSource, SearchSource, FetchResponse | None, str | None]] = {}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="holo-retrieval-fetch") as executor:
            future_by_index = {
                executor.submit(self._fetch_one, index, ranked_source, source): index
                for index, ranked_source, source in fetch_jobs
            }
            for future in as_completed(future_by_index):
                index = future_by_index[future]
                try:
                    results[index] = future.result()
                except Exception as exc:  # pragma: no cover - _fetch_one already catches provider exceptions.
                    ranked_source, source = next(
                        (ranked, source)
                        for item_index, ranked, source in fetch_jobs
                        if item_index == index
                    )
                    results[index] = (index, ranked_source, source, None, type(exc).__name__)
        return [results[index] for index in sorted(results)]

    def _fetch_one(
        self,
        index: int,
        ranked_source: RankedSource,
        source: SearchSource,
    ) -> tuple[int, RankedSource, SearchSource, FetchResponse | None, str | None]:
        try:
            response = self.fetch_provider.fetch(source)
            return index, ranked_source, source, response, None
        except Exception as exc:  # pragma: no cover - concrete providers decide error types.
            return index, ranked_source, source, None, type(exc).__name__

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
                "query": {"type": "str", "required": True, "min_length": 1, "aliases": ["goal"]},
                "goal_id": "str optional",
                "max_queries": "int optional",
                "max_sources": "int optional",
                "max_fetches": "int optional",
                "max_spans_per_document": "int optional",
                "metadata": "object optional",
                "_provider_capabilities": operator.provider_capabilities(),
                "_network_access": operator.network_access,
                "network_fetch_cost_field": "max_fetches",
                "default_network_fetch_cost": 3,
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
    metadata = _dict_or_empty(data.get("metadata"))
    for key in (
        "research_profile",
        "research_profile_id",
        "research_depth",
        "queries",
        "query_templates",
        "retrieval_strategy",
        "model_retrieval_strategy",
        "preferred_source_families",
        "source_family_plan",
        "source_authority_requirement",
        "search_strategy",
        "query_campaign",
        "minimum_coverage",
        "url",
        "urls",
        "source_url",
        "source_urls",
        "seed_url",
        "seed_urls",
        "crawl_seed_url",
        "crawl_seed_urls",
    ):
        if key in data and key not in metadata:
            metadata[key] = data[key]
    return SearchGoal(
        goal_id=goal_id,
        query=query,
        max_queries=_positive_int(data.get("max_queries"), default=_default_query_count(metadata, data=data)),
        max_sources=_positive_int(data.get("max_sources"), default=5),
        max_fetches=_positive_int(data.get("max_fetches"), default=3),
        max_spans_per_document=_positive_int(data.get("max_spans_per_document"), default=2),
        metadata=metadata,
    )


def _research_profile_from_goal(goal: SearchGoal) -> ResearchProfile | None:
    raw_profile = goal.metadata.get("research_profile_id", goal.metadata.get("research_profile"))
    if not isinstance(raw_profile, str):
        return None
    return profile_by_id(raw_profile)


def _research_query_strategy_diagnostics(profile: ResearchProfile) -> JsonObject:
    strategy = profile.metadata.get("query_strategy")
    strategy = dict(strategy) if isinstance(strategy, dict) else {}
    templates = strategy.get("templates")
    return {
        "research_profile": profile.profile_id,
        "query_strategy": {
            "strategy_id": str(strategy.get("strategy_id") or ""),
            "template_count": len(templates) if isinstance(templates, list) else 0,
            "preferred_source_families": [
                item for item in strategy.get("preferred_source_families", [])
                if isinstance(item, str)
            ] if isinstance(strategy.get("preferred_source_families"), list) else [],
        },
    }


def _goal_budget(goal: SearchGoal) -> JsonObject:
    return {
        "max_queries": goal.max_queries,
        "max_sources": goal.max_sources,
        "max_fetches": goal.max_fetches,
        "max_spans_per_document": goal.max_spans_per_document,
    }


def _initial_fetch_limit(goal: SearchGoal, *, ranked: list[RankedSource]) -> int:
    max_fetches = max(0, int(goal.max_fetches))
    if max_fetches <= 2:
        return max_fetches
    if not _should_reserve_document_expansion_budget(goal, ranked=ranked):
        return max_fetches
    return max(1, max_fetches // 2)


def _should_reserve_document_expansion_budget(goal: SearchGoal, *, ranked: list[RankedSource]) -> bool:
    if not _wants_sec_filing_text(goal):
        return False
    return any(
        isinstance(item.metadata, dict) and item.metadata.get("source_kind") == "sec_submissions_json"
        for item in ranked[: max(4, min(len(ranked), goal.max_fetches))]
    )


def _wants_sec_filing_text(goal: SearchGoal) -> bool:
    query = _goal_intent_text(goal).lower()
    compact = "".join(ch for ch in query if ch.isalnum())
    return any(
        marker in query or marker in compact
        for marker in (
            "8-k",
            "8k",
            "merger",
            "acquisition",
            "transaction",
            "deal value",
            "purchase price",
            "consideration",
            "adjusted ebitda",
            "non-gaap",
            "nongaap",
            "bridge",
            "addback",
            "add back",
            "purchase price allocation",
        )
    )


def _wants_market_valuation_data(goal: SearchGoal) -> bool:
    query = _goal_intent_text(goal).lower()
    compact = "".join(ch for ch in query if ch.isalnum())
    return any(
        marker in query or marker in compact
        for marker in (
            "ev/ebitda",
            "evebitda",
            "ev/revenue",
            "evrevenue",
            "enterprise value",
            "market cap",
            "market capitalization",
            "valuation multiple",
            "trading multiple",
            "stock price",
            "share price",
        )
    )


def _goal_intent_text(goal: SearchGoal) -> str:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    parts = [str(goal.query or "")]
    for key in ("root_goal", "task_goal", "original_goal", "user_goal"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    mission = metadata.get("research_mission")
    if isinstance(mission, dict):
        value = mission.get("root_goal")
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


def _search_candidate_limit(goal: SearchGoal) -> int:
    if not _needs_expanded_search_candidate_pool(goal):
        return goal.max_sources
    return min(
        max(
            24,
            goal.max_sources,
            goal.max_fetches * 4,
        ),
        512,
    )


def _needs_expanded_search_candidate_pool(goal: SearchGoal) -> bool:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    if metadata.get("research_profile") or metadata.get("research_profile_id"):
        return True
    if str(metadata.get("research_depth") or "").strip().lower() in {"balanced", "deep"}:
        return True
    if str(metadata.get("search_strategy") or "").strip().lower() in {"aggregate", "fresh_live", "structured", "crawl"}:
        return True
    if str(metadata.get("query_campaign") or "").strip().lower() in {"auto", "deep", "enabled", "true"}:
        return True
    return goal.max_sources >= 16 or goal.max_fetches >= 16


def _default_query_count(metadata: JsonObject, *, data: JsonObject | None = None) -> int:
    for key in ("queries", "query_templates"):
        value = metadata.get(key)
        if isinstance(value, list):
            count = sum(1 for item in value if isinstance(item, str) and item.strip())
            if count > 0:
                return count
    strategy_count = _retrieval_strategy_query_count(metadata)
    if strategy_count > 0:
        return strategy_count
    data = data if isinstance(data, dict) else {}
    if bool(metadata.get("respect_explicit_budget") or data.get("respect_explicit_budget")):
        return 1
    if str(metadata.get("research_depth") or data.get("research_depth") or "").strip().lower() in {"balanced", "deep"}:
        return 8
    if str(metadata.get("search_strategy") or "").strip().lower() in {"aggregate", "adaptive", "fresh_live", "structured"}:
        return 8
    max_fetches = _positive_int(data.get("max_fetches"), default=0)
    max_sources = _positive_int(data.get("max_sources"), default=0)
    if max_fetches >= 16 or max_sources >= 16:
        return 8
    return 1


def _retrieval_strategy_query_count(metadata: JsonObject) -> int:
    raw = metadata.get("retrieval_strategy")
    if not isinstance(raw, dict):
        raw = metadata.get("model_retrieval_strategy")
    if not isinstance(raw, dict):
        return 0
    count = 0
    for key in ("queries", "query_plan", "search_moves"):
        value = raw.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str) and item.strip():
                count += 1
            elif isinstance(item, dict) and isinstance(item.get("query") or item.get("search_query"), str):
                if str(item.get("query") or item.get("search_query")).strip():
                    count += 1
    return count


def _bounded_goal(goal: SearchGoal) -> SearchGoal:
    return SearchGoal(
        goal_id=goal.goal_id,
        query=goal.query,
        max_queries=_clamp_budget(goal.max_queries, "max_queries"),
        max_sources=_clamp_budget(goal.max_sources, "max_sources"),
        max_fetches=_clamp_budget(goal.max_fetches, "max_fetches"),
        max_spans_per_document=_clamp_budget(goal.max_spans_per_document, "max_spans_per_document"),
        metadata=dict(goal.metadata),
    )


def _budget_clamp_diagnostics(requested: SearchGoal, effective: SearchGoal) -> JsonObject:
    requested_budget = _goal_budget(requested)
    effective_budget = _goal_budget(effective)
    if requested_budget == effective_budget:
        return {}
    return {
        "requested_budget": requested_budget,
        "budget_clamped": True,
        "budget_caps": dict(RETRIEVAL_BUDGET_CAPS),
    }


def _clamp_budget(value: int, key: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return min(max(0, parsed), RETRIEVAL_BUDGET_CAPS[key])


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


def _fetchable_ranked_sources(goal: SearchGoal, ranked: list[RankedSource]) -> tuple[list[RankedSource], list[JsonObject]]:
    fetchable: list[RankedSource] = []
    rejections: list[JsonObject] = []
    for source in ranked:
        reason = _ranked_source_fetch_rejection_reason(goal, source)
        if reason is None:
            fetchable.append(source)
            continue
        target = _dict_or_empty(source.metadata.get("target_entity"))
        assessment = _dict_or_empty(source.metadata.get("source_assessment"))
        rejections.append(
            {
                "source_id": source.source_id,
                "uri": source.uri,
                "title": _preview(source.title, 160),
                "provider": source.provider,
                "rank": source.rank,
                "score": source.score,
                "reason": reason,
                "required_target_phrases": _string_list(target.get("required_target_phrases")),
                "matched_target_phrases": _string_list(target.get("matched_target_phrases")),
                "missing_target_phrases": _string_list(target.get("missing_target_phrases")),
                "metadata": _safe_json(
                    {
                        "goal_id": goal.goal_id,
                        "source_kind": _ranked_source_kind(source),
                        "source_family": source.metadata.get("source_family") or assessment.get("source_family"),
                        "authority_level": assessment.get("authority_level"),
                    }
                ),
            }
        )
    return fetchable, rejections


def _initial_fetch_queue_with_discovery_supplements(
    goal: SearchGoal,
    *,
    fetchable_ranked: list[RankedSource],
    ranked_all: list[RankedSource],
    research_profile: ResearchProfile | None,
) -> list[RankedSource]:
    """Reserve a small part of the fetch budget for discovery pages.

    High-authority structured sources can be directly useful, but they can also
    mask better primary documents behind filing or issuer discovery pages. The
    reserved discovery fetches are not treated as final evidence; they are
    inputs for the document-expansion layer.
    """

    if goal.max_fetches <= 0:
        return []
    discovery = _supplemental_discovery_ranked_sources(
        goal,
        ranked_all=ranked_all,
        research_profile=research_profile,
    )
    if _wants_sec_filing_text(goal):
        priority_companyfacts = _priority_sec_companyfacts_sources(goal, ranked_all)
        priority_discovery = _priority_sec_filing_discovery_sources(discovery)
        priority_event_sources = _priority_issuer_event_sources(goal, discovery)
        priority_market_sources = _priority_market_data_sources(goal, ranked_all)
        if _wants_transaction_filing_evidence(goal):
            return _merge_ranked_sources(
                max_count=goal.max_fetches,
                groups=[
                    priority_discovery,
                    priority_companyfacts,
                    priority_event_sources,
                    priority_market_sources,
                    fetchable_ranked,
                    [
                        source
                        for source in discovery
                        if source.source_id
                        not in {item.source_id for item in [*priority_companyfacts, *priority_discovery, *priority_event_sources, *priority_market_sources]}
                    ],
                ],
            )
        if priority_discovery or priority_market_sources or priority_companyfacts:
            return _merge_ranked_sources(
                max_count=goal.max_fetches,
                groups=[
                    priority_companyfacts,
                    priority_market_sources,
                    priority_discovery,
                    priority_event_sources,
                    fetchable_ranked,
                    [
                        source
                        for source in discovery
                        if source.source_id
                        not in {item.source_id for item in [*priority_companyfacts, *priority_market_sources, *priority_discovery, *priority_event_sources]}
                    ],
                ],
            )
    if not discovery:
        return fetchable_ranked
    reserved = min(len(discovery), _supplemental_discovery_fetch_limit(goal, research_profile=research_profile))
    if reserved <= 0 or goal.max_fetches <= 1:
        return fetchable_ranked
    primary_limit = max(1, goal.max_fetches - reserved)
    queue: list[RankedSource] = []
    seen: set[str] = set()
    for source in fetchable_ranked[:primary_limit]:
        queue.append(source)
        seen.add(source.uri)
    for source in discovery:
        if len(queue) >= goal.max_fetches:
            break
        if source.uri in seen:
            continue
        queue.append(source)
        seen.add(source.uri)
    return queue


def _priority_sec_filing_discovery_sources(sources: list[RankedSource]) -> list[RankedSource]:
    priority_kinds = {"sec_submissions_json", "sec_edgar_browse"}
    result = [
        source
        for source in sources
        if _ranked_source_kind(source) in priority_kinds
    ]
    result.sort(key=lambda source: (0 if _ranked_source_kind(source) == "sec_submissions_json" else 1, source.rank))
    return result


def _priority_sec_companyfacts_sources(goal: SearchGoal, sources: list[RankedSource]) -> list[RankedSource]:
    if not _wants_companyfacts_fact_sources(goal):
        return []
    result = [
        source
        for source in sources
        if _ranked_source_kind(source) == "sec_companyfacts_json"
    ]
    result.sort(key=lambda source: source.rank)
    return result[:4]


def _priority_sec_filing_document_sources(sources: list[RankedSource]) -> list[RankedSource]:
    result = [
        source
        for source in sources
        if _ranked_source_kind(source) in {"sec_primary_filing_document", "sec_complete_submission_text", "sec_exhibit_document"}
    ]
    result.sort(
        key=lambda source: (
            _sec_filing_document_form_rank(source),
            _safe_rank_int(source.metadata.get("filing_index"), default=10_000),
            _sec_filing_document_kind_rank(source),
            source.rank,
        )
    )
    return result


def _sec_filing_document_kind_rank(source: RankedSource) -> int:
    kind = _ranked_source_kind(source)
    if kind == "sec_exhibit_document":
        return 0
    if kind == "sec_primary_filing_document":
        return 1
    if kind == "sec_complete_submission_text":
        return 2
    return 3


def _sec_filing_document_form_rank(source: RankedSource) -> int:
    form = str(source.metadata.get("sec_form") or "").upper().replace(" ", "")
    if form in {"10-K", "20-F", "40-F"}:
        return 0
    if form == "10-Q":
        return 1
    if form in {"8-K", "6-K"}:
        return 3
    return 2


def _safe_rank_int(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _priority_issuer_event_sources(goal: SearchGoal, sources: list[RankedSource]) -> list[RankedSource]:
    intent = _goal_intent_text(goal).lower()
    event_markers = {
        "acquisition",
        "acquire",
        "merger",
        "transaction",
        "deal",
        "purchase",
        "consideration",
        "press release",
        "announcement",
    }
    query_terms = [term for term in intent.replace("-", " ").replace("/", " ").split() if len(term) >= 4]
    result: list[RankedSource] = []
    for source in sources:
        family = str(source.metadata.get("source_family") or "")
        kind = _ranked_source_kind(source)
        if family != "company_ir" and kind not in {"issuer_investor_relations", "issuer_earnings_releases"}:
            continue
        haystack = f"{source.uri} {source.title} {source.snippet}".lower()
        if not any(marker in haystack or marker in intent for marker in event_markers):
            continue
        if not any(term in haystack for term in query_terms):
            continue
        result.append(source)
    result.sort(key=lambda source: source.rank)
    return result[:4]


def _priority_market_data_sources(goal: SearchGoal, sources: list[RankedSource]) -> list[RankedSource]:
    if not _wants_market_valuation_data(goal):
        return []
    result: list[RankedSource] = []
    for source in sources:
        family = str(source.metadata.get("source_family") or "")
        assessment = _dict_or_empty(source.metadata.get("source_assessment"))
        family = family or str(assessment.get("source_family") or "")
        uri = source.uri.lower()
        if family != "market_data_provider" and not any(
            host in uri
            for host in (
                "finance.yahoo.com",
                "api.nasdaq.com",
                "marketwatch.com",
                "companiesmarketcap.com",
                "macrotrends.net",
            )
        ):
            continue
        result.append(source)
    result.sort(key=lambda source: (0 if _market_data_source_is_key_statistics(source) else 1, source.rank))
    return result[:4]


def _wants_transaction_filing_evidence(goal: SearchGoal) -> bool:
    intent = _goal_intent_text(goal).lower()
    return any(
        marker in intent
        for marker in (
            "transaction",
            "acquisition",
            "merger",
            "deal disclosure",
            "deal disclosures",
            "merger agreement",
            "8-k",
            "form 8-k",
            "consideration",
            "purchase price allocation",
        )
    )


def _wants_companyfacts_fact_sources(goal: SearchGoal) -> bool:
    intent = _goal_intent_text(goal).lower().replace("_", " ").replace("-", " ")
    compact = "".join(ch for ch in intent if ch.isalnum())
    fact_markers = (
        "companyfacts",
        "xbrl",
        "revenue",
        "revenues",
        "net sales",
        "net income",
        "cash and cash equivalents",
        "cash equivalents",
        "total debt",
        "long term debt",
        "short term debt",
        "assets",
        "liabilities",
        "shares outstanding",
    )
    compact_markers = (
        "companyfacts",
        "netincomeloss",
        "revenuefromcontract",
        "cashandcashequivalents",
        "longtermdebt",
        "sharesoutstanding",
    )
    return any(marker in intent for marker in fact_markers) or any(marker in compact for marker in compact_markers)


def _market_data_source_is_key_statistics(source: RankedSource) -> bool:
    haystack = f"{source.uri} {source.title} {source.snippet}".lower()
    return any(
        marker in haystack
        for marker in ("key-statistics", "key statistics", "statistics", "valuation", "summary?assetclass=stocks")
    )


def _merge_ranked_sources(*, max_count: int, groups: list[list[RankedSource]]) -> list[RankedSource]:
    result: list[RankedSource] = []
    seen: set[str] = set()
    for group in groups:
        for source in group:
            key = source.source_id or source.uri
            if key in seen:
                continue
            seen.add(key)
            result.append(source)
            if len(result) >= max_count:
                return result
    return result


def _document_expansion_fetch_limit(
    goal: SearchGoal,
    *,
    fetch_queue: list[RankedSource],
    remaining_fetch_budget: int,
    depth: int,
) -> int:
    budget = max(0, int(remaining_fetch_budget))
    if budget <= 0:
        return 0
    if depth != 1 or not _wants_sec_filing_text(goal):
        return budget
    if not _wants_transaction_filing_evidence(goal):
        return budget
    if not any(
        _ranked_source_kind(source) in {"sec_submissions_json", "sec_complete_submission_text"}
        for source in fetch_queue
    ):
        return budget
    if budget <= 2:
        return budget
    return max(1, budget - 1)


def _supplemental_discovery_ranked_sources(
    goal: SearchGoal,
    *,
    ranked_all: list[RankedSource],
    research_profile: ResearchProfile | None,
) -> list[RankedSource]:
    if is_discovery_goal(goal=goal, research_profile=research_profile):
        return []
    result: list[RankedSource] = []
    for source in ranked_all:
        if _research_profile_discovery_source_rejection(goal, source) == "source_discovery_only_for_research_profile":
            result.append(source)
    return result


def _supplemental_discovery_fetch_limit(goal: SearchGoal, *, research_profile: ResearchProfile | None) -> int:
    profile = _research_profile_from_goal(goal) if research_profile is None else research_profile
    if profile is None:
        return 0
    depth = str(goal.metadata.get("research_depth") or "").strip().lower()
    if profile.profile_id == "finance_fundamentals":
        return 8 if depth == "deep" else 4
    if profile.profile_id == "academic_research":
        return 6 if depth == "deep" else 3
    return 4 if depth in {"balanced", "deep"} else 2


def _ranked_source_fetch_rejection_reason(goal: SearchGoal, source: RankedSource) -> str | None:
    discovery_reason = _research_profile_discovery_source_rejection(goal, source)
    if discovery_reason is not None:
        return discovery_reason
    weak_reason = _research_profile_weak_source_rejection(source)
    if weak_reason is not None:
        return weak_reason
    target = _dict_or_empty(source.metadata.get("target_entity"))
    if not bool(target.get("target_entity_required")):
        return None
    if bool(target.get("target_entity_satisfied")):
        return None
    if _ranked_source_target_exempt(source):
        return None
    return "source_target_entity_mismatch"


def _should_fetch_rejected_sources(
    goal: SearchGoal,
    *,
    research_profile: ResearchProfile | None,
    source_rejections: list[JsonObject],
) -> bool:
    if not source_rejections:
        return False
    if is_discovery_goal(goal=goal, research_profile=research_profile):
        return True
    profile = _research_profile_from_goal(goal) if research_profile is None else research_profile
    if profile is None:
        return False
    if profile.profile_id == "finance_fundamentals":
        return True
    return any(str(item.get("reason") or "").startswith("source_weak_for_") for item in source_rejections)


def _research_profile_discovery_source_rejection(goal: SearchGoal, source: RankedSource) -> str | None:
    assessment = _dict_or_empty(source.metadata.get("source_assessment"))
    profile_id = str(assessment.get("profile_id") or source.metadata.get("research_profile") or "")
    source_kind = _ranked_source_kind(source)
    if not profile_id or not source_kind:
        return None
    profile = profile_by_id(profile_id)
    if profile is None:
        return None
    if is_discovery_goal(goal=goal, research_profile=profile):
        return None
    if source_kind in profile_discovery_source_kinds(profile):
        return "source_discovery_only_for_research_profile"
    return None


def _research_profile_weak_source_rejection(source: RankedSource) -> str | None:
    assessment = _dict_or_empty(source.metadata.get("source_assessment"))
    profile_id = str(assessment.get("profile_id") or source.metadata.get("research_profile") or "")
    family = str(assessment.get("source_family") or source.metadata.get("source_family") or "")
    profile = profile_by_id(profile_id) if profile_id else None
    if profile is None or not family:
        return None
    if family in set(profile.weak_source_families):
        if profile_id == "academic_research":
            return "source_weak_for_academic_research_profile"
        return "source_weak_for_research_profile"
    return None


def _ranked_source_kind(source: RankedSource) -> str:
    raw = source.metadata.get("source_kind")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    assessment = _dict_or_empty(source.metadata.get("source_assessment"))
    metadata = _dict_or_empty(assessment.get("metadata"))
    raw = metadata.get("source_kind")
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def _search_source_kind(source: SearchSource) -> str:
    raw = source.metadata.get("source_kind")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    assessment = _dict_or_empty(source.metadata.get("source_assessment"))
    metadata = _dict_or_empty(assessment.get("metadata"))
    raw = metadata.get("source_kind")
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def _search_source_family(source: SearchSource) -> str:
    raw = source.metadata.get("source_family")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    assessment = _dict_or_empty(source.metadata.get("source_assessment"))
    raw = assessment.get("source_family")
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def _uri_host(uri: str) -> str:
    try:
        return urllib.parse.urlparse(uri).netloc.lower()
    except Exception:
        return ""


def _ranked_source_target_exempt(source: RankedSource) -> bool:
    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    source_kind = metadata.get("source_kind")
    if isinstance(source_kind, str) and source_kind in TARGET_ENTITY_EXEMPT_SOURCE_KINDS:
        return True
    assessment = _dict_or_empty(metadata.get("source_assessment"))
    if assessment.get("usable_as_primary") is True:
        return True
    authority = assessment.get("authority_level")
    return isinstance(authority, str) and authority == "primary"


def _failure_attribution(
    *,
    decision: EvidenceEvaluationDecision,
    queries: list[str],
    sources: list[SearchSource],
    ranked: list[RankedSource],
    source_rejections: list[JsonObject],
    fetch_jobs: list[tuple[int, RankedSource, SearchSource]],
    fetch_summaries: list[JsonObject],
    documents: list[tuple[FetchedDocument, str]],
    spans: list[object],
    evidence_candidates: list[EvidenceCandidate],
    rejected_evidence: list[JsonObject],
    evidence: list[EvidenceItem],
    citations: list[object],
    search_summaries: list[JsonObject],
    source_quality: JsonObject,
) -> JsonObject:
    mode = "none"
    if decision.sufficient:
        mode = "none"
    elif not queries:
        mode = "query_plan_empty"
    elif not sources:
        mode = "search_no_sources"
    elif not ranked:
        mode = "ranking_no_sources"
    elif not fetch_jobs:
        if _fetch_rejections_indicate_source_authority_gap(source_rejections, source_quality):
            mode = "source_authority_gap"
        else:
            mode = "no_fetchable_sources"
    elif not documents:
        mode = "fetch_failed_or_empty"
    elif not spans:
        mode = "extraction_no_spans"
    elif not evidence_candidates and rejected_evidence:
        if _has_source_authority_rejection(rejected_evidence, source_quality):
            mode = "source_authority_gap"
        else:
            mode = "all_evidence_rejected"
    elif evidence and not citations:
        mode = "citation_generation_missing"
    elif _source_quality_gap(source_quality, evidence=evidence, citations=citations):
        mode = "source_authority_gap"
    else:
        mode = "coverage_gap"
    search_empty_count = sum(1 for item in search_summaries if int(item.get("source_count") or 0) == 0)
    fetch_failed_count = sum(1 for item in fetch_summaries if item.get("status") != "ok")
    return {
        "primary_failure_mode": mode,
        "reason": decision.reason,
        "search": {
            "query_count": len(queries),
            "attempt_count": len(search_summaries),
            "empty_attempt_count": search_empty_count,
            "status_counts": _count_by_key(search_summaries, "status"),
        },
        "source": {
            "candidate_count": len(sources),
            "ranked_count": len(ranked),
            "rejected_count": len(source_rejections),
            "rejection_reasons": _count_by_key(source_rejections, "reason"),
            "quality": source_quality,
        },
        "fetch": {
            "scheduled_count": len(fetch_jobs),
            "attempt_count": len(fetch_summaries),
            "failed_count": fetch_failed_count,
            "status_counts": _count_by_key(fetch_summaries, "status"),
            "failure_reasons": _count_by_key([item for item in fetch_summaries if item.get("reason")], "reason"),
        },
        "extract": {
            "document_count": len(documents),
            "span_count": len(spans),
        },
        "evidence": {
            "candidate_count": len(evidence_candidates),
            "accepted_count": len(evidence),
            "citation_count": len(citations),
            "rejected_count": len(rejected_evidence),
            "rejection_reasons": _count_by_key(rejected_evidence, "reason"),
        },
        "next_strategy_hint": _next_strategy_hint(mode),
    }


def _next_strategy_hint(primary_failure_mode: str) -> str:
    return {
        "none": "finalize_if_requirements_covered",
        "query_plan_empty": "create_non_empty_query_plan",
        "search_no_sources": "diversify_query_or_switch_search_provider",
        "ranking_no_sources": "relax_ranking_or_change_source_family",
        "no_fetchable_sources": "switch_to_direct_or_structured_source",
        "fetch_failed_or_empty": "try_alternate_urls_or_source_family",
        "extraction_no_spans": "fetch_more_relevant_documents_or_change_extract_terms",
        "all_evidence_rejected": "repair_entity_or_source_authority_mismatch",
        "source_authority_gap": "switch_to_higher_authority_source_family",
        "citation_generation_missing": "repair_citation_generation",
        "coverage_gap": "target_missing_facets_with_new_queries",
    }.get(primary_failure_mode, "continue_if_requirements_remain")


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


def _source_quality_gap(source_quality: JsonObject, *, evidence: list[EvidenceItem], citations: list[object]) -> bool:
    if not source_quality:
        return False
    if not evidence and not citations:
        return False
    if source_quality.get("authority_sufficient") is True:
        return False
    return int(source_quality.get("assessment_count") or 0) > 0


def _has_source_authority_rejection(rejected_evidence: list[JsonObject], source_quality: JsonObject) -> bool:
    if any(item.get("reason") == "weak_source_authority_for_research_profile" for item in rejected_evidence):
        return True
    return bool(source_quality) and source_quality.get("authority_sufficient") is False


def _fetch_rejections_indicate_source_authority_gap(source_rejections: list[JsonObject], source_quality: JsonObject) -> bool:
    if bool(source_quality) and source_quality.get("authority_sufficient") is False:
        return True
    return any(str(item.get("reason") or "").startswith("source_weak_for_") for item in source_rejections)


def _decision_has_source_authority_gap(
    *,
    decision: EvidenceEvaluationDecision,
    source_quality: JsonObject,
    rejected_evidence: list[JsonObject],
    evidence: list[EvidenceItem],
    citations: list[object],
    source_rejections: list[JsonObject],
) -> bool:
    if decision.sufficient or not source_quality:
        return False
    if source_quality.get("authority_sufficient") is True:
        return False
    if int(source_quality.get("assessment_count") or 0) <= 0:
        return False
    return bool(rejected_evidence or evidence or citations or source_rejections)


def _authority_gap_reason(source_quality: JsonObject) -> str:
    requirement = str(source_quality.get("authority_requirement") or "primary")
    if requirement == "primary":
        return "no_primary_source_for_research_profile"
    return "no_required_authority_source_for_research_profile"


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _count_by_key(items: list[JsonObject], key: str) -> JsonObject:
    counts: JsonObject = {}
    for item in items:
        value = item.get(key)
        label = str(value or "unknown")
        counts[label] = int(counts.get(label, 0)) + 1
    return counts


def _evidence_item_limit(goal: SearchGoal) -> int:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    value = metadata.get("max_evidence_items")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_EVIDENCE_ITEM_LIMIT
    return max(1, min(parsed, EVIDENCE_ITEM_LIMIT_CAP))


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
        elif _secret_like_key(lowered):
            safe[key] = "[omitted]"
        elif isinstance(value, str):
            safe[key] = "[omitted]" if contains_secret_like_content(value) else _preview(value, 160)
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, list):
            safe[key] = [_safe_list_item(item) for item in value[:10]]
        elif isinstance(value, dict):
            safe[key] = _safe_json(value)
        else:
            safe[key] = str(value)[:160]
    return safe


def _secret_like_key(key: str) -> bool:
    normalized = key.replace("-", "_")
    return normalized in {
        "api_key",
        "apikey",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "password",
        "private_key",
    }


def _dict_or_empty(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value if isinstance(raw, str)) if item]


def _safe_list_item(value):
    if isinstance(value, str):
        return "[omitted]" if contains_secret_like_content(value) else _preview(value, 160)
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
