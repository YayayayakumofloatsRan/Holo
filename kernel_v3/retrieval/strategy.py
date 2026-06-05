from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from kernel_v3.contracts import JsonObject


QUERY_TOKEN_LIMIT = 64
QUERY_TEXT_LIMIT = 500
MIN_MATERIAL_NEW_TOKEN_RATIO = 0.24
DEFAULT_REPLAN_QUERY_FLOOR = 8


@dataclass(frozen=True, kw_only=True)
class RetrievalStrategyDecision:
    payload: JsonObject
    diagnostics: JsonObject = field(default_factory=dict)


def normalize_query(text: str) -> str:
    """Normalize query text for novelty checks without losing CJK words."""

    lowered = str(text or "").lower()
    lowered = re.sub(r"https?://\S+", " url ", lowered)
    lowered = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", lowered)
    return " ".join(lowered.split())


def query_signature(text: str) -> str:
    return hashlib.sha256(normalize_query(text).encode("utf-8", errors="replace")).hexdigest()[:16]


def materially_different_query(candidate: str, previous: list[str]) -> bool:
    candidate_terms = _query_terms(candidate)
    if not candidate_terms:
        return False
    for prior in previous:
        prior_terms = _query_terms(prior)
        if not prior_terms:
            continue
        if candidate_terms == prior_terms:
            return False
        shared = len(candidate_terms.intersection(prior_terms))
        ratio = 1.0 - (shared / max(1, len(candidate_terms.union(prior_terms))))
        if ratio < MIN_MATERIAL_NEW_TOKEN_RATIO:
            return False
    return True


def supervise_retrieval_payload(
    payload: JsonObject,
    *,
    replan_hints: JsonObject | None,
    root_goal: str = "",
) -> RetrievalStrategyDecision:
    """Apply host-owned retrieval strategy constraints to a model action payload.

    The planner remains free to propose the next action. This function validates
    whether a retrieval.run payload actually advances the host-observed search
    state, then rewrites only the bounded search fields that would otherwise
    repeat an already failed strategy.
    """

    hints = dict(replan_hints or {})
    updated = dict(payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    attempted_queries = _string_list(hints.get("attempted_queries"))
    attempted_signatures = [query_signature(item) for item in attempted_queries]
    query = _string(updated.get("query")) or root_goal
    strategy_has_changed = _strategy_has_changed(metadata, hints)
    payload_has_targeted_source = _payload_has_targeted_source(updated, metadata) or strategy_has_changed
    needs_replan = hints.get("needs_replan") is True or bool(attempted_queries)
    diagnostics: JsonObject = {
        "status": "not_needed" if not needs_replan else "checked",
        "rewritten": False,
        "query_signature": query_signature(query),
        "attempted_query_signatures": attempted_signatures[-12:],
    }
    if not needs_replan:
        if metadata:
            updated["metadata"] = metadata
        return RetrievalStrategyDecision(payload=updated, diagnostics=diagnostics)

    structured = _first_structured_payload(hints, attempted_queries)
    selected_query = None if payload_has_targeted_source else (_string(structured.get("query")) if structured else None)
    selected_metadata = {} if payload_has_targeted_source else (_dict(structured.get("metadata")) if structured else {})
    selected_reason = "" if payload_has_targeted_source else ("structured_candidate" if selected_query else "")

    if selected_query is None:
        selected_query = _first_material_query(
            [
                *_string_list(hints.get("suggested_query_hints")),
                *_source_target_queries(hints),
                query,
            ],
            attempted_queries=attempted_queries,
        )
        selected_reason = "query_diversification" if selected_query else selected_reason

    if selected_query is None and query:
        selected_query = _fallback_material_query(query, hints=hints, attempted_queries=attempted_queries)
        selected_reason = "fallback_gap_expansion" if selected_query else selected_reason

    repeated = query_signature(query) in set(attempted_signatures)
    should_rewrite_query = not payload_has_targeted_source and selected_query and (
        repeated or materially_different_query(selected_query, attempted_queries)
    )
    if should_rewrite_query:
        if selected_query != query:
            updated["query"] = _bounded_query(selected_query)
            diagnostics["rewritten"] = True
            diagnostics["previous_query"] = query
            diagnostics["new_query"] = updated["query"]
            diagnostics["rewrite_reason"] = selected_reason or "materially_new_query_required"
        for key, value in selected_metadata.items():
            metadata.setdefault(key, value)

    strategy = None if payload_has_targeted_source else _required_strategy(hints, metadata)
    if strategy:
        current = _string(metadata.get("search_strategy"))
        if current != strategy:
            metadata["search_strategy"] = strategy
            diagnostics["rewritten"] = True
            diagnostics["strategy_rewrite"] = {"previous": current, "required": strategy}

    queries = [] if payload_has_targeted_source else _diversified_queries(
        updated.get("query"),
        hints=hints,
        attempted_queries=attempted_queries,
    )
    if queries:
        updated["queries"] = queries
        updated["max_queries"] = max(_positive_int(updated.get("max_queries")), len(queries), DEFAULT_REPLAN_QUERY_FLOOR)
        diagnostics["query_batch_count"] = len(queries)

    source_families = [] if payload_has_targeted_source else _preferred_source_families(hints, existing=_string_list(metadata.get("preferred_source_families")))
    if source_families:
        metadata["preferred_source_families"] = source_families

    if diagnostics.get("rewritten") is True:
        metadata["strategy_supervision"] = {
            "status": "enforced",
            "reason": diagnostics.get("rewrite_reason") or diagnostics.get("strategy_rewrite", {}).get("required") or "payload_ok",
            "attempted_query_signatures": attempted_signatures[-12:],
            "missing": _string_list(hints.get("missing"))[:12],
        }
    if metadata:
        updated["metadata"] = metadata
    return RetrievalStrategyDecision(payload=updated, diagnostics=diagnostics)


def _first_structured_payload(hints: JsonObject, attempted_queries: list[str]) -> JsonObject:
    for key in (
        "suggested_sec_structured_sources",
        "suggested_filing_documents",
        "suggested_macro_series",
        "suggested_fiscaldata_endpoints",
    ):
        values = hints.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            payload = item.get("suggested_payload")
            payload = payload if isinstance(payload, dict) else item
            query = _string(payload.get("query"))
            if query and materially_different_query(query, attempted_queries):
                return dict(payload)
    return {}


def _first_material_query(candidates: list[str], *, attempted_queries: list[str]) -> str | None:
    seen: set[str] = set()
    for candidate in candidates:
        query = _bounded_query(candidate)
        signature = query_signature(query)
        if not query or signature in seen:
            continue
        seen.add(signature)
        if materially_different_query(query, attempted_queries):
            return query
    return None


def _source_target_queries(hints: JsonObject) -> list[str]:
    queries: list[str] = []
    targets = hints.get("suggested_source_targets")
    if not isinstance(targets, list):
        return queries
    for target in targets:
        if not isinstance(target, dict):
            continue
        base = _string(target.get("title")) or _string(target.get("source_id"))
        for hint in _string_list(target.get("query_hints")):
            queries.append(f"{base} {hint}" if base else hint)
    return queries


def _fallback_material_query(query: str, *, hints: JsonObject, attempted_queries: list[str]) -> str | None:
    missing_terms = [
        _missing_to_query_term(item)
        for item in _string_list(hints.get("missing"))
        if _missing_to_query_term(item)
    ]
    source_terms = [
        item
        for item in _preferred_source_families(hints, existing=[])
        if item
    ]
    additions = _ordered_unique([*missing_terms, *source_terms])
    if not additions:
        return None
    candidate = _bounded_query(" ".join([query, *additions[:8]]))
    return candidate if materially_different_query(candidate, attempted_queries) else None


def _missing_to_query_term(value: str) -> str:
    text = str(value or "").strip()
    if ":" in text:
        text = text.split(":", 1)[1]
    return " ".join(text.replace("_", " ").replace("-", " ").split())


def _required_strategy(hints: JsonObject, metadata: JsonObject) -> str | None:
    attempted = set(_string_list(hints.get("attempted_search_strategies")))
    current = _string(metadata.get("search_strategy"))
    if current and current not in attempted:
        return current
    suggested = _string_list(hints.get("suggested_search_strategies"))
    for strategy in suggested:
        if strategy not in attempted:
            return strategy
    for fallback in ("aggregate", "structured", "fresh_live", "crawl"):
        if fallback not in attempted:
            return fallback
    return suggested[0] if suggested else None


def _diversified_queries(value: object, *, hints: JsonObject, attempted_queries: list[str]) -> list[str]:
    base = _string(value)
    candidates = [
        *([base] if base else []),
        *_string_list(hints.get("suggested_query_hints")),
        *_source_target_queries(hints),
    ]
    diversified: list[str] = []
    seen: set[str] = set(query_signature(item) for item in attempted_queries)
    for candidate in candidates:
        query = _bounded_query(candidate)
        signature = query_signature(query)
        if not query or signature in seen:
            continue
        seen.add(signature)
        diversified.append(query)
        if len(diversified) >= DEFAULT_REPLAN_QUERY_FLOOR:
            break
    return diversified


def _preferred_source_families(hints: JsonObject, *, existing: list[str]) -> list[str]:
    families = list(existing)
    targets = hints.get("suggested_source_targets")
    if isinstance(targets, list):
        for target in targets:
            if isinstance(target, dict):
                family = _string(target.get("source_family"))
                if family:
                    families.append(family)
    return _ordered_unique(families)[:12]


def _payload_has_targeted_source(payload: JsonObject, metadata: JsonObject) -> bool:
    if _payload_source_urls(payload, metadata):
        return True
    targeted_keys = {
        "sec_cik",
        "sec_accession_number",
        "sec_primary_document",
        "fred_series_id",
        "fiscaldata_api_path",
        "source_family",
    }
    return any(_string(metadata.get(key)) for key in targeted_keys)


def _strategy_has_changed(metadata: JsonObject, hints: JsonObject) -> bool:
    current = _string(metadata.get("search_strategy"))
    if not current:
        return False
    attempted = set(_string_list(hints.get("attempted_search_strategies")))
    return current not in attempted


def _payload_source_urls(payload: JsonObject, metadata: JsonObject) -> list[str]:
    values: list[str] = []
    for container in (payload, metadata):
        for key in ("url", "urls", "source_url", "source_urls", "seed_url", "seed_urls"):
            value = container.get(key)
            if isinstance(value, str) and _looks_like_url(value):
                values.append(value)
            elif isinstance(value, list):
                values.extend(item for item in value if isinstance(item, str) and _looks_like_url(item))
    return _ordered_unique(values)


def _looks_like_url(value: str) -> bool:
    stripped = value.strip().lower()
    return stripped.startswith("https://") or stripped.startswith("http://")


def _query_terms(value: str) -> set[str]:
    normalized = normalize_query(value)
    return set(normalized.split()[:QUERY_TOKEN_LIMIT])


def _bounded_query(value: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= QUERY_TEXT_LIMIT:
        return text
    return text[: QUERY_TEXT_LIMIT - 3] + "..."


def _string(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _dict(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, (str, int, float)) and str(item).strip()]


def _positive_int(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
