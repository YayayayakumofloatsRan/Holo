from __future__ import annotations

import hashlib
import urllib.parse

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.profile_policy import profile_discovery_source_kinds
from kernel_v3.retrieval.contracts import (
    CitationItem,
    DiscoveryExpansion,
    EvidenceItem,
    FetchedDocument,
    RankedSource,
    ResearchGraph,
    RetrievalNextAction,
    SearchGoal,
    SearchSource,
)


DISCOVERY_EXPANSION_PROVIDER_ID = "discovery_expansion"
DISCOVERY_EXPANSION_SOURCE_KINDS = {
    "scholarly_preprint",
    "scholarly_index_metadata",
    "scholarly_publisher_metadata",
}


def expand_discovery_sources(
    *,
    goal: SearchGoal,
    sources: list[SearchSource],
    research_profile: ResearchProfile | None,
    max_candidates: int = 48,
) -> tuple[list[SearchSource], list[DiscoveryExpansion], list[RetrievalNextAction]]:
    """Compile discovery/search surfaces into concrete fetchable document candidates."""

    profile_discovery_kinds = profile_discovery_source_kinds(research_profile)
    expanded: list[SearchSource] = []
    expansion_records: list[DiscoveryExpansion] = []
    actions: list[RetrievalNextAction] = []
    seen_uris: set[str] = {source.uri for source in sources}
    seen_expansions: set[str] = set()
    for source in sources:
        if len(expanded) >= max_candidates:
            break
        if not _is_discovery_source(source, profile_discovery_kinds=profile_discovery_kinds):
            continue
        candidates, source_actions = _expand_source(goal=goal, source=source)
        accepted: list[SearchSource] = []
        for candidate in candidates:
            if candidate.uri in seen_uris or candidate.uri in seen_expansions:
                continue
            seen_uris.add(candidate.uri)
            seen_expansions.add(candidate.uri)
            accepted.append(candidate)
            if len(expanded) + len(accepted) >= max_candidates:
                break
        expanded.extend(accepted)
        actions.extend(source_actions)
        expansion_records.append(
            DiscoveryExpansion(
                expansion_id=f"disc-exp-{goal.goal_id}-{_hash(source.source_id + source.uri)[:12]}",
                goal_id=goal.goal_id,
                source_id=source.source_id,
                uri=source.uri,
                status="expanded" if accepted else ("action_only" if source_actions else "skipped"),
                candidate_sources=[candidate.to_dict() for candidate in accepted],
                next_tool_actions=[action.to_dict() for action in source_actions],
                diagnostics={
                    "candidate_count": len(accepted),
                    "candidate_uri_hashes": [_hash(candidate.uri) for candidate in accepted[:12]],
                    "source_kind": _source_kind(source),
                    "source_family": _source_family(source),
                    "host": _host(source.uri),
                },
            )
        )
    return expanded, expansion_records, _dedupe_actions(actions)


def build_next_tool_actions(
    *,
    goal: SearchGoal,
    failure_attribution: JsonObject,
    source_rejections: list[JsonObject],
    expansion_actions: list[RetrievalNextAction],
    fetch_summaries: list[JsonObject],
) -> list[RetrievalNextAction]:
    actions: list[RetrievalNextAction] = list(expansion_actions)
    rejection_reasons = {str(item.get("reason") or "") for item in source_rejections}
    failure_mode = str(failure_attribution.get("primary_failure_mode") or "")
    if "source_discovery_only_for_research_profile" in rejection_reasons:
        actions.append(
            RetrievalNextAction(
                action_id=f"next-{goal.goal_id}-expand-discovery",
                action="expand_discovery_source",
                tool_hint="retrieval.discovery_expansion",
                reason="ranked sources are discovery/search surfaces and need concrete document candidates",
                payload_hint={"goal_id": goal.goal_id, "source_rejection_reason": "source_discovery_only_for_research_profile"},
            )
        )
    if failure_mode == "fetch_failed_or_empty" or any(item.get("status") != "ok" for item in fetch_summaries):
        actions.append(
            RetrievalNextAction(
                action_id=f"next-{goal.goal_id}-alternate-fetch",
                action="try_alternate_document_urls",
                tool_hint="retrieval.run",
                reason="fetch attempts failed or produced empty documents; try another source family or direct document URL",
                payload_hint={
                    "avoid_source_ids": [
                        str(item.get("source_id"))
                        for item in fetch_summaries
                        if item.get("status") != "ok" and item.get("source_id")
                    ][:16],
                    "strategy": "alternate_source_family_or_direct_url",
                },
            )
        )
    if failure_mode in {"search_no_sources", "ranking_no_sources", "coverage_gap", "no_fetchable_sources"}:
        actions.append(
            RetrievalNextAction(
                action_id=f"next-{goal.goal_id}-diversify",
                action="diversify_acquisition_plan",
                tool_hint="planner.propose",
                reason="current acquisition path did not cover the user goal; planner should switch source family or query facet",
                payload_hint={
                    "goal_query": goal.query,
                    "failure_mode": failure_mode,
                    "avoid_repeating": True,
                },
            )
        )
    return _dedupe_actions(actions)


def build_research_graph(
    *,
    goal: SearchGoal,
    queries: list[str],
    sources: list[SearchSource],
    ranked: list[RankedSource],
    discovery_expansions: list[DiscoveryExpansion],
    documents: list[tuple[FetchedDocument, str]],
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    next_tool_actions: list[RetrievalNextAction],
) -> ResearchGraph:
    nodes: list[JsonObject] = [
        {"id": goal.goal_id, "type": "goal", "label": goal.query[:240]},
    ]
    edges: list[JsonObject] = []
    for index, query in enumerate(queries[:32], start=1):
        query_id = f"query:{index}"
        nodes.append({"id": query_id, "type": "query", "label": query[:240]})
        edges.append({"from": goal.goal_id, "to": query_id, "type": "plans_query"})
    ranked_by_id = {item.source_id: item for item in ranked}
    for source in sources[:96]:
        source_id = f"source:{source.source_id}"
        ranked_source = ranked_by_id.get(source.source_id)
        family = _source_family(source)
        nodes.append(
            {
                "id": source_id,
                "type": "source",
                "label": source.title[:240],
                "uri": source.uri,
                "source_kind": _source_kind(source),
                "source_family": family,
                "provider": source.provider,
                **({"rank": ranked_source.rank, "score": ranked_source.score} if ranked_source else {}),
            }
        )
        edges.append({"from": goal.goal_id, "to": source_id, "type": "discovers_source"})
        if family:
            family_id = f"family:{family}"
            if not any(node.get("id") == family_id for node in nodes):
                nodes.append({"id": family_id, "type": "source_family", "label": family})
            edges.append({"from": family_id, "to": source_id, "type": "contains_source"})
    for expansion in discovery_expansions[:64]:
        exp_id = f"expansion:{expansion.expansion_id}"
        nodes.append({"id": exp_id, "type": "discovery_expansion", "label": expansion.status, "source_id": expansion.source_id})
        edges.append({"from": f"source:{expansion.source_id}", "to": exp_id, "type": "expands"})
        for candidate in expansion.candidate_sources[:24]:
            candidate_id = f"source:{candidate.get('source_id')}"
            edges.append({"from": exp_id, "to": candidate_id, "type": "creates_candidate"})
    for document, _body in documents[:96]:
        doc_id = f"document:{document.document_id}"
        nodes.append({"id": doc_id, "type": "document", "label": document.title[:240], "uri": document.uri, "size_bytes": document.size_bytes})
        edges.append({"from": f"source:{document.source_id}", "to": doc_id, "type": "fetched_as"})
    for item in evidence[:128]:
        evidence_id = f"evidence:{item.evidence_id}"
        nodes.append({"id": evidence_id, "type": "evidence", "label": item.text[:240], "score": item.score})
        edges.append({"from": f"document:{item.document_id}", "to": evidence_id, "type": "extracts_evidence"})
    for citation in citations[:128]:
        citation_id = f"citation:{citation.citation_id}"
        nodes.append({"id": citation_id, "type": "citation", "label": citation.title[:240], "uri": citation.uri})
        edges.append({"from": f"evidence:{citation.evidence_id}", "to": citation_id, "type": "supports_citation"})
    for action in next_tool_actions[:32]:
        action_id = f"next_action:{action.action_id}"
        nodes.append({"id": action_id, "type": "next_tool_action", "label": action.action, "tool_hint": action.tool_hint})
        edges.append({"from": goal.goal_id, "to": action_id, "type": "suggests_next_action"})
    return ResearchGraph(
        graph_id=f"research-graph-{goal.goal_id}",
        goal_id=goal.goal_id,
        nodes=nodes,
        edges=edges,
        diagnostics={
            "query_count": len(queries),
            "source_count": len(sources),
            "ranked_count": len(ranked),
            "expansion_count": len(discovery_expansions),
            "document_count": len(documents),
            "evidence_count": len(evidence),
            "citation_count": len(citations),
            "next_tool_action_count": len(next_tool_actions),
        },
    )


def _expand_source(*, goal: SearchGoal, source: SearchSource) -> tuple[list[SearchSource], list[RetrievalNextAction]]:
    host = _host(source.uri)
    source_kind = _source_kind(source)
    directory_id = str(source.metadata.get("source_directory_id") or "")
    query = _query_from_source(source) or goal.query
    candidates: list[SearchSource] = []
    actions: list[RetrievalNextAction] = []
    if host in {"arxiv.org", "www.arxiv.org"} or directory_id == "academic-arxiv-search":
        candidate = _candidate(
            goal=goal,
            source=source,
            action="query_arxiv_api",
            uri=_arxiv_api_uri(query=query, max_results=_candidate_limit(goal)),
            title=f"arXiv API results for {query}",
            snippet="Machine-readable arXiv metadata and abstracts compiled from a search/discovery surface.",
            source_family="scholarly_preprint",
            authority_level="primary",
            source_kind="scholarly_preprint",
            allowed_hosts=["export.arxiv.org"],
            mime_hint="application/atom+xml",
        )
        candidates.append(candidate)
        actions.append(_next_action(goal=goal, source=source, action="query_arxiv_api", uri=candidate.uri, reason="arXiv search page should be expanded through the Atom API before final evidence extraction."))
    if host in {"openalex.org", "www.openalex.org"} or directory_id == "academic-openalex-works":
        candidate = _candidate(
            goal=goal,
            source=source,
            action="query_openalex_api",
            uri=_openalex_api_uri(query=query, per_page=_candidate_limit(goal)),
            title=f"OpenAlex works API results for {query}",
            snippet="OpenAlex works metadata search result for scholarly document discovery.",
            source_family="scholarly_index",
            authority_level="secondary",
            source_kind="scholarly_index_metadata",
            allowed_hosts=["api.openalex.org"],
            mime_hint="application/json",
        )
        candidates.append(candidate)
        actions.append(_next_action(goal=goal, source=source, action="query_openalex_api", uri=candidate.uri, reason="OpenAlex HTML search should be expanded through the JSON works API."))
    if host in {"search.crossref.org", "crossref.org", "www.crossref.org", "doi.org"} or directory_id == "academic-crossref-search":
        candidate = _candidate(
            goal=goal,
            source=source,
            action="query_crossref_api",
            uri=_crossref_api_uri(query=query, rows=_candidate_limit(goal)),
            title=f"Crossref works API results for {query}",
            snippet="Crossref DOI and publication metadata for bibliographic verification and paper URL discovery.",
            source_family="scholarly_index",
            authority_level="secondary",
            source_kind="scholarly_index_metadata",
            allowed_hosts=["api.crossref.org"],
            mime_hint="application/json",
        )
        candidates.append(candidate)
        actions.append(_next_action(goal=goal, source=source, action="query_crossref_api", uri=candidate.uri, reason="Crossref search should be expanded through DOI metadata API before citation use."))
    if host in {"semanticscholar.org", "www.semanticscholar.org"} or directory_id == "academic-semantic-scholar":
        candidate = _candidate(
            goal=goal,
            source=source,
            action="query_semantic_scholar_api",
            uri=_semantic_scholar_api_uri(query=query, limit=min(_candidate_limit(goal), 20)),
            title=f"Semantic Scholar paper search API results for {query}",
            snippet="Semantic Scholar paper metadata and abstracts for citation graph oriented discovery.",
            source_family="scholarly_index",
            authority_level="secondary",
            source_kind="scholarly_index_metadata",
            allowed_hosts=["api.semanticscholar.org"],
            mime_hint="application/json",
        )
        candidates.append(candidate)
        actions.append(_next_action(goal=goal, source=source, action="query_semantic_scholar_api", uri=candidate.uri, reason="Semantic Scholar search page should be expanded through paper search API."))
    if _looks_like_publisher_search(host=host, source_kind=source_kind, directory_id=directory_id):
        candidate = _candidate(
            goal=goal,
            source=source,
            action="fetch_publisher_result_page",
            uri=source.uri,
            title=f"Publisher result page for {query}",
            snippet="Fetchable publisher search/result page; use to extract article titles, abstracts, DOI, and concrete article URLs.",
            source_family=_source_family(source) or "scholarly_publisher",
            authority_level=str(source.metadata.get("authority_level") or "primary"),
            source_kind="scholarly_publisher_metadata",
            allowed_hosts=[host] if host else [],
            mime_hint="text/html",
        )
        candidates.append(candidate)
        actions.append(_next_action(goal=goal, source=source, action="extract_publisher_result_links", uri=source.uri, reason="Publisher search page should be fetched for article/result links if APIs do not cover the topic."))
    return candidates, actions


def _candidate(
    *,
    goal: SearchGoal,
    source: SearchSource,
    action: str,
    uri: str,
    title: str,
    snippet: str,
    source_family: str,
    authority_level: str,
    source_kind: str,
    allowed_hosts: list[str],
    mime_hint: str,
) -> SearchSource:
    metadata = {
        "research_profile": source.metadata.get("research_profile") or goal.metadata.get("research_profile"),
        "research_profile_id": source.metadata.get("research_profile_id") or goal.metadata.get("research_profile_id"),
        "source_family": source_family,
        "authority_level": authority_level,
        "source_kind": source_kind,
        "expanded_from_source_id": source.source_id,
        "expanded_from_uri": source.uri,
        "expanded_from_source_kind": _source_kind(source),
        "discovery_expanded": True,
        "discovery_action": action,
        "fetch_allowed_hosts": [host for host in allowed_hosts if host],
        "mime_hint": mime_hint,
    }
    return SearchSource(
        source_id=f"{DISCOVERY_EXPANSION_PROVIDER_ID}-{_hash(action + uri)[:12]}",
        uri=uri,
        title=title[:240],
        snippet=snippet[:1000],
        provider=DISCOVERY_EXPANSION_PROVIDER_ID,
        metadata=metadata,
    )


def _next_action(*, goal: SearchGoal, source: SearchSource, action: str, uri: str, reason: str) -> RetrievalNextAction:
    return RetrievalNextAction(
        action_id=f"next-{goal.goal_id}-{_hash(source.source_id + action + uri)[:12]}",
        action=action,
        tool_hint="retrieval.run",
        source_id=source.source_id,
        uri=uri,
        reason=reason,
        payload_hint={
            "goal_id": goal.goal_id,
            "query": _query_from_source(source) or goal.query,
            "expanded_from_source_id": source.source_id,
            "uri": uri,
        },
        diagnostics={
            "source_kind": _source_kind(source),
            "source_family": _source_family(source),
            "host": _host(source.uri),
        },
    )


def _is_discovery_source(source: SearchSource, *, profile_discovery_kinds: set[str]) -> bool:
    source_kind = _source_kind(source)
    if source_kind in profile_discovery_kinds:
        return True
    host = _host(source.uri)
    path = urllib.parse.urlparse(source.uri).path.lower()
    if host in {"arxiv.org", "www.arxiv.org"} and path.startswith("/search"):
        return True
    if host in {"openalex.org", "www.openalex.org", "search.crossref.org", "semanticscholar.org", "www.semanticscholar.org"}:
        return True
    return _looks_like_publisher_search(host=host, source_kind=source_kind, directory_id=str(source.metadata.get("source_directory_id") or ""))


def _looks_like_publisher_search(*, host: str, source_kind: str, directory_id: str) -> bool:
    if source_kind != "scholarly_search" and directory_id != "academic-publisher-search":
        return False
    return host in {
        "link.springer.com",
        "springer.com",
        "www.springer.com",
        "cambridge.org",
        "www.cambridge.org",
        "dl.acm.org",
        "ieeexplore.ieee.org",
        "epubs.siam.org",
        "www.nature.com",
        "nature.com",
        "onlinelibrary.wiley.com",
        "wiley.com",
        "www.wiley.com",
        "www.sciencedirect.com",
        "sciencedirect.com",
    }


def _query_from_source(source: SearchSource) -> str:
    parsed = urllib.parse.urlparse(source.uri)
    params = urllib.parse.parse_qs(parsed.query)
    for key in ("query", "q", "search", "all"):
        values = params.get(key)
        if values and values[0].strip():
            return values[0].strip()
    title = source.title
    for marker in (" for ", " search for "):
        if marker in title:
            return title.rsplit(marker, 1)[-1].strip()
    return ""


def _arxiv_api_uri(*, query: str, max_results: int) -> str:
    params = {
        "search_query": _arxiv_search_expression(query),
        "start": "0",
        "max_results": str(max(1, min(max_results, 100))),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)


def _openalex_api_uri(*, query: str, per_page: int) -> str:
    params = {
        "search": query,
        "per-page": str(max(1, min(per_page, 200))),
        "sort": "publication_date:desc",
    }
    return "https://api.openalex.org/works?" + urllib.parse.urlencode(params)


def _crossref_api_uri(*, query: str, rows: int) -> str:
    params = {
        "query.bibliographic": query,
        "rows": str(max(1, min(rows, 100))),
        "sort": "published",
        "order": "desc",
    }
    return "https://api.crossref.org/works?" + urllib.parse.urlencode(params)


def _semantic_scholar_api_uri(*, query: str, limit: int) -> str:
    params = {
        "query": query,
        "limit": str(max(1, min(limit, 100))),
        "fields": "title,abstract,year,url,authors,citationCount,externalIds,venue,openAccessPdf",
    }
    return "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)


def _arxiv_search_expression(query: str) -> str:
    terms = _focus_terms(query)
    if not terms:
        return f"all:{query}"
    if len(terms) >= 2:
        return f'all:"{" ".join(terms[: min(4, len(terms))])}"'
    return " AND ".join(f"all:{term}" for term in terms[:6])


def _focus_terms(query: str) -> list[str]:
    raw = [
        item.strip().lower()
        for item in query.replace("-", " ").replace("_", " ").split()
        if item.strip()
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for term in raw:
        cleaned = "".join(ch for ch in term if ch.isalnum())
        if len(cleaned) < 4 or cleaned in _STOPWORDS or cleaned.isdigit():
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    return terms


def _candidate_limit(goal: SearchGoal) -> int:
    return max(10, min(int(goal.max_sources or 10), 50))


def _source_kind(source: SearchSource) -> str:
    value = source.metadata.get("source_kind") if isinstance(source.metadata, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _source_family(source: SearchSource) -> str:
    value = source.metadata.get("source_family") if isinstance(source.metadata, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _host(uri: str) -> str:
    return (urllib.parse.urlparse(uri).hostname or "").lower()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dedupe_actions(actions: list[RetrievalNextAction]) -> list[RetrievalNextAction]:
    seen: set[tuple[str, str | None]] = set()
    result: list[RetrievalNextAction] = []
    for action in actions:
        key = (action.action, action.uri)
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    return result


_STOPWORDS = {
    "academic",
    "advance",
    "advances",
    "article",
    "frontier",
    "frontiers",
    "journal",
    "latest",
    "literature",
    "paper",
    "papers",
    "preprint",
    "recent",
    "research",
    "review",
    "scholarly",
    "state",
    "survey",
    "open",
    "problem",
    "problems",
}
