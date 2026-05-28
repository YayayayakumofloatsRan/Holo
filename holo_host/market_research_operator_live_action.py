from __future__ import annotations

import re
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .market_research_operator_run import default_market_research_operator_run_fixtures, run_market_research_operator_run

STAGE215_MARKET_RESEARCH_OPERATOR_ACTION_SCHEMA = "holo.stage215.market_research_operator_action.v1"

_AGENT_CHANNELS = {"holo_cli", "engineering", "research", "project"}
_OPERATOR_MARKET_TERMS_RE = re.compile(
    r"(market research|fundamental|financial research|filing-grounded|research report|"
    r"equity research|company research|valuation report|"
    r"\u57fa\u672c\u9762|\u5e02\u573a\u7814\u7a76|\u516c\u53f8\u7814\u7a76|\u7814\u7a76\u62a5\u544a|\u4f30\u503c\u62a5\u544a)",
    re.IGNORECASE,
)
_FINANCE_CONTEXT_RE = re.compile(
    r"(sec\b|10-k|10-q|annual report|financial|finance|stock|ticker|valuation|"
    r"\u91d1\u878d|\u8d22\u62a5|\u5e74\u62a5|\u4f30\u503c|\u80a1\u7968)",
    re.IGNORECASE,
)
_ACTION_TERMS_RE = re.compile(
    r"(do|run|research|analy[sz]e|build|produce|report|investigate|crawl|search|"
    r"\u505a|\u7814\u7a76|\u5206\u6790|\u68c0\u7d22|\u641c|\u67e5|\u53bb\u505a|\u5f00\u59cb|\u62a5\u544a)",
    re.IGNORECASE,
)
_AUTONOMOUS_ACTION_RE = re.compile(
    r"(pick.*direction|choose.*direction|go.*do|start.*research|self-directed|"
    r"\u81ea\u5df1\u68c0\u7d22|\u6311\u4e00\u4e2a|\u611f\u5174\u8da3|\u53bb\u505a|\u5f00\u59cb\u505a)",
    re.IGNORECASE,
)


def should_run_market_research_operator(
    user_text: str,
    *,
    metadata: dict[str, Any] | None = None,
    channel: str = "",
) -> bool:
    meta = dict(metadata or {})
    if meta.get("stage215_market_research_operator_disabled"):
        return False
    if meta.get("stage215_market_research_operator_dry_run") or meta.get("stage215_market_research_operator_fixture"):
        return True
    if channel and channel not in _AGENT_CHANNELS:
        return False
    text = str(user_text or "").strip()
    if not text:
        return False
    if _OPERATOR_MARKET_TERMS_RE.search(text) and _ACTION_TERMS_RE.search(text):
        return True
    return bool(_FINANCE_CONTEXT_RE.search(text) and _AUTONOMOUS_ACTION_RE.search(text))


def _default_query(user_text: str) -> str:
    text = " ".join(str(user_text or "").split())
    if not text:
        return "NVIDIA 2024 10-K AI infrastructure Data Center revenue official SEC filing"
    if "sec" not in text.lower() and "10-k" not in text.lower() and "\u8d22\u62a5" not in text:
        text = f"{text} official SEC 10-K filing"
    return compact_text(text, 260)


def build_market_research_operator_fixture(user_text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = dict(metadata or {})
    fixture = meta.get("stage215_market_research_operator_fixture")
    if isinstance(fixture, dict):
        return dict(fixture)
    if meta.get("stage215_market_research_operator_dry_run") and not meta.get("stage215_market_research_operator_query"):
        template = dict(default_market_research_operator_run_fixtures()[0])
        template["fixture_id"] = "stage215-live:" + stable_digest(user_text, template.get("search_query", ""), limit=12)
        template["question"] = compact_text(str(user_text or template.get("question", "")), 360)
        return template
    query = str(meta.get("stage215_market_research_operator_query", "") or _default_query(user_text))
    return {
        "fixture_id": "stage215-live:" + stable_digest(user_text, query, limit=12),
        "question": compact_text(str(user_text or query), 360),
        "search_query": query,
    }


def run_market_research_operator_live_action(
    *,
    user_text: str,
    metadata: dict[str, Any] | None = None,
    channel: str = "",
    network_enabled: bool = True,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    if not should_run_market_research_operator(user_text, metadata=meta, channel=channel):
        return {
            "schema": STAGE215_MARKET_RESEARCH_OPERATOR_ACTION_SCHEMA,
            "status": "skipped",
            "selected_action": "none",
            "reason": "market_research_operator_not_required",
            "created_at": utc_now(),
        }
    dry_run = bool(meta.get("stage215_market_research_operator_dry_run", False))
    fixture = build_market_research_operator_fixture(user_text, meta)
    operator_run = run_market_research_operator_run(
        fixture,
        dry_run=dry_run,
        network_enabled=bool(network_enabled),
        web_search_fn=None if dry_run else web_search_fn,
        open_page_fn=None if dry_run else open_page_fn,
    )
    status = "executed" if str(operator_run.get("status", "") or "") == "ready" else "failed"
    final_gate = operator_run.get("stage198_market_research_finalization_gate", {})
    if not isinstance(final_gate, dict):
        final_gate = {}
    action = {
        "schema": STAGE215_MARKET_RESEARCH_OPERATOR_ACTION_SCHEMA,
        "action_id": "stage215_action:" + stable_digest(user_text, operator_run.get("operator_run_id", ""), limit=12),
        "status": status,
        "selected_action": "market_research_operator_run",
        "dry_run": dry_run,
        "network_enabled": bool(network_enabled),
        "operator_run_id": str(operator_run.get("operator_run_id", "") or ""),
        "phase_count": len(list(operator_run.get("operator_trajectory", []) or [])),
        "final_visible_text_ready": bool(final_gate.get("final_visible_text_ready", False)),
        "canonical_stop_reason": "final_answer_ready" if status == "executed" else "tool_failure_report",
        "failure_reasons": list(operator_run.get("failure_reasons", []) or []),
        "created_at": utc_now(),
    }
    return sanitize_public_metadata(
        {
            **action,
            "stage214_market_research_operator_run": operator_run,
            "final_visible_text": str(operator_run.get("final_visible_text", "") or ""),
        }
    )
