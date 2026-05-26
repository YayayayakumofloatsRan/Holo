from __future__ import annotations

import re
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .tool_grounding import normalize_tool_observation_ledger

STAGE151_SCHEMA = "holo.stage151.live_tool_trace.v1"
STAGE151_NETWORK_GROUNDING_SCHEMA = "holo.stage151.network_grounding.v1"

_CURRENT_LOOKUP_PATTERNS: tuple[str, ...] = (
    r"\bi searched\b",
    r"\bi looked up\b",
    r"\bi checked (?:the )?(?:web|internet|online)\b",
    r"\bfrom (?:the )?(?:web|internet|online)\b",
    r"\bcurrent (?:web|online|internet|lookup|source|information)\b",
    r"\blatest\b",
    r"\bas of today\b",
    r"\baccording to (?:the )?(?:web|internet|online|current sources)\b",
    r"\bweb search\b",
    r"\bonline search\b",
    "\u6211\u641c\u4e86",
    "\u6211\u67e5\u4e86\u7f51\u4e0a",
    "\u6211\u4e0a\u7f51\u67e5",
    "\u6839\u636e\u7f51\u4e0a",
    "\u6839\u636e\u6700\u65b0",
    "\u6700\u65b0\u8d44\u6599",
    "\u5f53\u524d\u8d44\u6599",
)


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _result_items(raw_results: Any) -> list[dict[str, str]]:
    if not isinstance(raw_results, list):
        return []
    items: list[dict[str, str]] = []
    for raw in raw_results[:5]:
        if not isinstance(raw, dict):
            continue
        title = _compact(raw.get("title", ""), 120)
        url = str(raw.get("url", "") or "").strip()
        snippet = _compact(raw.get("snippet", ""), 180)
        item = {"title": title, "url": url, "snippet": snippet}
        if title or url or snippet:
            items.append(item)
    return items


def build_external_lookup_observation(
    lookup: dict[str, Any] | None,
    *,
    network_enabled: bool,
    reason: str = "",
    provider_call_id: str = "",
    fetched_at: str = "",
) -> dict[str, Any]:
    """Build a normalized live-network observation row for `external_lookup`."""

    payload = dict(lookup or {})
    query = _compact(payload.get("query", ""), 180)
    status = str(payload.get("status", "") or ("rejected" if not network_enabled else "unknown")).strip().lower()
    if not network_enabled and status not in {"rejected", "denied"}:
        status = "rejected"
    results = _result_items(payload.get("results", []))
    source_urls = [str(item.get("url", "") or "").strip() for item in results if str(item.get("url", "") or "").strip()]
    error = _compact(payload.get("error", "") or ("network_disabled" if not network_enabled else ""), 180)
    call_id = str(provider_call_id or "").strip()
    if not call_id:
        call_id = "external_lookup:" + stable_digest(query, status, ",".join(source_urls), limit=12)
    summary_parts = [f"external_lookup {status}"]
    if query:
        summary_parts.append(f"query={query}")
    if results:
        summary_parts.append(f"results={len(results)}")
    if error:
        summary_parts.append(f"error={error}")
    grounded = bool(network_enabled and status == "ok" and (results or source_urls))
    return {
        "provider_call_id": call_id,
        "tool": "external_lookup",
        "status": status,
        "summary": _compact("; ".join(summary_parts), 260),
        "data_keys": sorted(["query", "results", "source_urls"] + (["error"] if error else [])),
        "grounding_tags": ["current_fact", "external_lookup"] if grounded else [],
        "query": query,
        "results": results,
        "error": error,
        "source_urls": source_urls,
        "fetched_at": str(fetched_at or utc_now()),
        "network_enabled": bool(network_enabled),
        "reason": _compact(reason, 160),
    }


def merge_tool_observation_ledgers(*ledgers: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ledger in ledgers:
        for row in normalize_tool_observation_ledger(ledger):
            key = "|".join(
                (
                    str(row.get("provider_call_id", "") or ""),
                    str(row.get("tool", "") or ""),
                    str(row.get("query", "") or ""),
                    str(row.get("status", "") or ""),
                    str(row.get("summary", "") or ""),
                )
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def _has_current_lookup_claim(text: str) -> bool:
    current = str(text or "")
    lowered = current.lower()
    for pattern in _CURRENT_LOOKUP_PATTERNS:
        if pattern.startswith("\\"):
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                return True
        elif pattern in current:
            return True
    return False


def evaluate_network_grounding(text: str, tool_observation_ledger: Any) -> dict[str, Any]:
    ledger = normalize_tool_observation_ledger(tool_observation_ledger)
    lookup_rows = [row for row in ledger if str(row.get("tool", "") or "") == "external_lookup"]
    successful = [
        row
        for row in lookup_rows
        if str(row.get("status", "") or "").lower() == "ok"
        and ("external_lookup" in list(row.get("grounding_tags", []) or []) or row.get("source_urls") or row.get("results"))
    ]
    rejected = [
        row
        for row in lookup_rows
        if str(row.get("status", "") or "").lower() in {"rejected", "denied", "skipped", "error", "failed", "planned", "empty"}
    ]
    claim = _has_current_lookup_claim(text)
    if not claim:
        status = "no_current_lookup_claim"
        repair_required = False
        reason = ""
    elif successful:
        status = "grounded"
        repair_required = False
        reason = ""
    elif lookup_rows:
        status = "unverified_current_lookup_claim"
        repair_required = True
        reason = "current lookup claim has no successful external_lookup observation"
    else:
        status = "missing_current_lookup_ledger"
        repair_required = True
        reason = "current lookup claim has no external_lookup observation ledger"
    return {
        "schema": STAGE151_NETWORK_GROUNDING_SCHEMA,
        "status": status,
        "claim_count": 1 if claim else 0,
        "ledger_count": len(ledger),
        "external_lookup_ledger_count": len(lookup_rows),
        "successful_lookup_count": len(successful),
        "rejected_lookup_count": len(rejected),
        "source_urls": [url for row in successful for url in list(row.get("source_urls", []) or [])][:8],
        "repair_required": repair_required,
        "repair_reason": reason,
    }


def repair_network_grounding(text: str, grounding_report: dict[str, Any], *, channel: str = "") -> str:
    if not bool(grounding_report.get("repair_required", False)):
        return str(text or "")
    if str(channel or "").startswith("wechat"):
        return "I do not have a recorded current web lookup for that exact claim."
    return "I do not have a recorded current web lookup for that exact claim, so I should treat it as unverified."


def build_stage151_live_tool_trace(
    *,
    user_text: str = "",
    capability_context: dict[str, Any] | None = None,
    reply_result: dict[str, Any] | None = None,
    reply_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cap = dict(capability_context or {})
    result = dict(reply_result or {})
    debug = dict(reply_debug or {})
    ledger = merge_tool_observation_ledgers(
        cap.get("tool_observation_ledger", []),
        debug.get("tool_observation_ledger", []),
        result.get("tool_observation_ledger", []),
    )
    tool_requests = [
        dict(item)
        for item in list(cap.get("tool_requests", result.get("tool_requests", [])) or [])
        if isinstance(item, dict)
    ]
    events: list[dict[str, Any]] = []
    events.append(
        {
            "event": "plan",
            "summary": _compact(user_text or result.get("text", ""), 220),
            "tool_request_count": len(tool_requests),
        }
    )
    for request in tool_requests:
        if str(request.get("name", "") or "") != "external_lookup":
            continue
        payload = dict(request.get("payload", {})) if isinstance(request.get("payload", {}), dict) else {}
        events.append(
            {
                "event": "tool_call",
                "tool": "external_lookup",
                "query": _compact(payload.get("query", ""), 180),
                "status": str(payload.get("status", "") or "requested"),
                "reason": _compact(request.get("reason", ""), 180),
            }
        )
    if not any(event.get("event") == "tool_call" for event in events):
        for row in ledger:
            if str(row.get("tool", "") or "") != "external_lookup":
                continue
            events.append(
                {
                    "event": "tool_call",
                    "tool": "external_lookup",
                    "query": _compact(row.get("query", ""), 180),
                    "status": str(row.get("status", "") or "observed"),
                    "reason": _compact(row.get("reason", ""), 180),
                }
            )
    for row in ledger:
        if str(row.get("tool", "") or "") != "external_lookup":
            continue
        events.append(
            {
                "event": "tool_observation",
                "tool": "external_lookup",
                "query": _compact(row.get("query", ""), 180),
                "status": str(row.get("status", "") or ""),
                "result_count": len(list(row.get("results", []) or [])),
                "source_urls": list(row.get("source_urls", []) or [])[:3],
                "error": _compact(row.get("error", ""), 120),
            }
        )
    network_grounding = dict(result.get("stage151_network_grounding", debug.get("stage151_network_grounding", {})))
    tool_grounding = dict(result.get("tool_grounding", debug.get("tool_grounding", {})))
    events.append(
        {
            "event": "grounding",
            "tool_grounding_status": str(tool_grounding.get("status", "") or ""),
            "network_grounding_status": str(network_grounding.get("status", "") or ""),
            "missing_families": list(tool_grounding.get("missing_families", []) or [])[:6],
        }
    )
    events.append({"event": "final", "summary": _compact(result.get("text", ""), 260)})
    return {
        "schema": STAGE151_SCHEMA,
        "status": "recorded",
        "event_count": len(events),
        "events": events,
    }


def format_stage151_live_trace(payload: dict[str, Any]) -> str:
    trace = dict(payload.get("stage151_live_tool_trace", payload)) if isinstance(payload, dict) else {}
    if trace.get("schema") != STAGE151_SCHEMA:
        trace = build_stage151_live_tool_trace(reply_result=payload if isinstance(payload, dict) else {})
    lines: list[str] = []
    for event in list(trace.get("events", []) or []):
        if not isinstance(event, dict):
            continue
        kind = str(event.get("event", "") or "event")
        if kind == "plan":
            lines.append(f"[plan] tools={event.get('tool_request_count', 0)} input={event.get('summary', '')}")
        elif kind == "tool_call":
            lines.append(f"[tool_call] {event.get('tool', '')} status={event.get('status', '')} query={event.get('query', '')}")
        elif kind == "tool_observation":
            lines.append(
                f"[tool_observation] {event.get('tool', '')} status={event.get('status', '')} results={event.get('result_count', 0)}"
            )
        elif kind == "grounding":
            lines.append(
                f"[grounding] tool={event.get('tool_grounding_status', '') or '-'} network={event.get('network_grounding_status', '') or '-'}"
            )
        elif kind == "final":
            lines.append(f"[final] {event.get('summary', '')}")
    return "\n".join(lines)
