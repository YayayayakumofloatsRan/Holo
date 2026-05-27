from __future__ import annotations

from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .stage162_search_evidence_controller import run_search_evidence_controller

STAGE164_SEARCH_FALLBACK_SCHEMA = "holo.stage164.search_fallback.v1"
STAGE164_SOURCE_SYNTHESIS_SCHEMA = "holo.stage164.source_synthesis.v1"
STAGE164_SEARCH_FALLBACK_ATTEMPT_SCHEMA = "holo.stage164.search_fallback_attempt.v1"


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _provider_rows(search_providers: list[tuple[str, Callable[[str], dict[str, Any]]]] | None) -> list[tuple[str, Callable[[str], dict[str, Any]]]]:
    rows: list[tuple[str, Callable[[str], dict[str, Any]]]] = []
    for index, item in enumerate(list(search_providers or []), start=1):
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        name, fn = item
        if not callable(fn):
            continue
        rows.append((str(name or f"provider_{index}"), fn))
    return rows


def _fallback_marker(*, provider_name: str, provider_index: int, provider_status: str, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": STAGE164_SEARCH_FALLBACK_ATTEMPT_SCHEMA,
        "provider_name": provider_name,
        "provider_index": int(provider_index),
        "provider_status": str(provider_status or ""),
        "attempt_count": int(report.get("attempt_count", 0) or 0),
        "best_evidence_score": float(report.get("best_evidence_score", 0.0) or 0.0),
        "stop_reason": str(report.get("stop_reason", "") or ""),
    }


def run_search_fallback_controller(
    query: str,
    *,
    user_text: str = "",
    network_enabled: bool,
    search_providers: list[tuple[str, Callable[[str], dict[str, Any]]]] | None,
    max_attempts_per_provider: int = 3,
) -> dict[str, Any]:
    providers = _provider_rows(search_providers)
    base_query = _compact(query, 180)
    if not network_enabled:
        row = {
            "schema": "holo.web_observation.v1",
            "observation_id": "web:" + stable_digest("stage164_network_disabled", base_query, limit=12),
            "action_type": "web_search",
            "query": base_query,
            "status": "rejected_network_disabled",
            "provider": "network_gate",
            "results": [],
            "source_urls": [],
            "fetched_at": utc_now(),
            "error": "network_disabled",
            "confidence": 0.0,
            "stage164_search_fallback": {
                "schema": STAGE164_SEARCH_FALLBACK_ATTEMPT_SCHEMA,
                "provider_name": "network_gate",
                "provider_index": 0,
                "provider_status": "rejected_network_disabled",
                "attempt_count": 0,
                "best_evidence_score": 0.0,
                "stop_reason": "network_disabled",
            },
        }
        return {
            "schema": STAGE164_SEARCH_FALLBACK_SCHEMA,
            "status": "rejected_network_disabled",
            "query": base_query,
            "provider_count": len(providers),
            "provider_attempt_count": 0,
            "selected_provider": "",
            "observations": [row],
            "provider_reports": [],
            "best_evidence_score": 0.0,
            "stop_reason": "network_disabled",
        }
    observations: list[dict[str, Any]] = []
    provider_reports: list[dict[str, Any]] = []
    selected_provider = ""
    best_score = 0.0
    if not providers:
        return {
            "schema": STAGE164_SEARCH_FALLBACK_SCHEMA,
            "status": "failed",
            "query": base_query,
            "provider_count": 0,
            "provider_attempt_count": 0,
            "selected_provider": "",
            "observations": [],
            "provider_reports": [],
            "best_evidence_score": 0.0,
            "stop_reason": "no_search_provider",
        }
    for index, (provider_name, provider_fn) in enumerate(providers, start=1):
        report = run_search_evidence_controller(
            base_query,
            user_text=user_text,
            network_enabled=True,
            web_search_fn=provider_fn,
            max_attempts=max(1, int(max_attempts_per_provider or 1)),
        )
        provider_status = str(report.get("status", "") or "")
        provider_reports.append(
            {
                "provider_name": provider_name,
                "provider_index": index,
                "status": provider_status,
                "attempt_count": int(report.get("attempt_count", 0) or 0),
                "best_evidence_score": float(report.get("best_evidence_score", 0.0) or 0.0),
                "stop_reason": str(report.get("stop_reason", "") or ""),
            }
        )
        marker = _fallback_marker(provider_name=provider_name, provider_index=index, provider_status=provider_status, report=report)
        for row in list(report.get("observations", []) or []):
            if not isinstance(row, dict):
                continue
            current = dict(row)
            current["stage164_search_fallback"] = marker
            observations.append(current)
        best_score = max(best_score, float(report.get("best_evidence_score", 0.0) or 0.0))
        if provider_status == "sufficient":
            selected_provider = provider_name
            break
    status = "sufficient" if selected_provider else "failed" if all(str(row.get("status", "") or "") in {"error", "failed", "empty"} for row in observations) else "weak"
    return {
        "schema": STAGE164_SEARCH_FALLBACK_SCHEMA,
        "status": status,
        "query": base_query,
        "provider_count": len(providers),
        "provider_attempt_count": len(provider_reports),
        "selected_provider": selected_provider,
        "observations": observations,
        "provider_reports": provider_reports,
        "best_evidence_score": round(best_score, 4),
        "stop_reason": "sufficient_provider_evidence" if selected_provider else "provider_evidence_exhausted",
    }


def _page_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("page_evidence", {}) if isinstance(row.get("page_evidence", {}), dict) else {})


def _snippet_conflicts(snippets: list[str]) -> bool:
    positives = [text for text in snippets if any(marker in text.lower() for marker in ("supports", "support ", "can ", "is ", "provides"))]
    negatives = [text for text in snippets if any(marker in text.lower() for marker in ("does not support", "not support", "cannot", "no longer"))]
    return bool(positives and negatives)


def build_source_synthesis(
    web_observation_ledger: list[dict[str, Any]] | Any,
    *,
    query: str = "",
) -> dict[str, Any]:
    rows = [dict(item) for item in list(web_observation_ledger or []) if isinstance(item, dict)]
    supported: list[dict[str, Any]] = []
    weak: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    snippets: list[str] = []
    for row in rows:
        page = _page_evidence(row)
        status = str(page.get("status", "") or "")
        if status not in {"supported", "weak"}:
            continue
        url = str(page.get("selected_url", "") or "")
        snippet = _compact(page.get("supporting_snippet", ""), 320)
        item = {
            "url": url,
            "status": status,
            "score": float(page.get("best_evidence_score", 0.0) or 0.0),
            "snippet": snippet,
            "provider": str(row.get("provider", "") or ""),
        }
        if status == "supported":
            supported.append(item)
        else:
            weak.append(item)
        if url:
            citations.append({"url": url, "status": status, "snippet": snippet})
        if snippet:
            snippets.append(snippet)
    conflict = _snippet_conflicts(snippets)
    status = "conflicted" if conflict else "supported" if supported else "weak" if weak else "unsupported"
    selected = supported or weak
    confidence = 0.0
    if selected:
        confidence = sum(float(item.get("score", 0.0) or 0.0) for item in selected) / max(1, len(selected))
        if len(supported) >= 2:
            confidence = min(1.0, confidence + 0.08)
        if conflict:
            confidence = min(confidence, 0.42)
    summary_parts = []
    for item in selected[:3]:
        snippet = str(item.get("snippet", "") or "")
        if snippet:
            summary_parts.append(snippet)
    return {
        "schema": STAGE164_SOURCE_SYNTHESIS_SCHEMA,
        "status": status,
        "query": _compact(query, 180),
        "source_count": len(rows),
        "supported_source_count": len(supported),
        "weak_source_count": len(weak),
        "conflict_count": 1 if conflict else 0,
        "risk_flags": ["source_conflict"] if conflict else [],
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "citations": citations[:8],
        "synthesized_summary": _compact(" ".join(summary_parts), 700),
        "created_at": utc_now(),
    }


def attach_source_synthesis_to_observations(
    observations: list[dict[str, Any]],
    *,
    query: str = "",
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in observations if isinstance(row, dict)]
    synthesis = build_source_synthesis(rows, query=query)
    if str(synthesis.get("status", "") or "") == "unsupported":
        return rows
    return [{**row, "source_synthesis": synthesis} for row in rows]
