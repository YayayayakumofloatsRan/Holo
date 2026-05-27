from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .market_research_agent_trajectory import run_market_research_dossier_agent_trajectory

STAGE202_MARKET_RESEARCH_DOSSIER_RESUME_ACTION_SCHEMA = "holo.stage202.market_research_dossier_resume_action.v1"

MarketResumeWebSearchFn = Callable[[str], dict[str, Any]]
MarketResumeOpenPageFn = Callable[[str], dict[str, Any]]


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _state_dir(value: str | Path | None) -> Path:
    return Path(value or ".holo_runtime").resolve()


def execute_market_research_dossier_resume_action(
    arguments: dict[str, Any] | None = None,
    *,
    state_dir: str | Path | None = None,
    network_enabled: bool = False,
    web_search_fn: MarketResumeWebSearchFn | None = None,
    open_page_fn: MarketResumeOpenPageFn | None = None,
    max_actions: int = 1,
) -> dict[str, Any]:
    """Resume a persisted market-research dossier through the Stage201 registry."""

    args = dict(arguments or {})
    thread_key = str(args.get("thread_key", "") or "")
    project_key = str(args.get("project_key", "") or "")
    query = str(args.get("query", args.get("question", "")) or "")
    max_action_count = int(args.get("max_actions", max_actions) or max_actions or 1)
    trajectory = run_market_research_dossier_agent_trajectory(
        state_dir=_state_dir(state_dir),
        thread_key=thread_key,
        project_key=project_key,
        question=query,
        network_enabled=bool(network_enabled),
        web_search_fn=web_search_fn,
        open_page_fn=open_page_fn,
        max_actions=max(0, min(max_action_count, 4)),
    )
    registry = dict(trajectory.get("stage201_market_research_dossier_registry", {}) or {})
    status = str(registry.get("status", "") or "missing")
    resume = dict(registry.get("stage200_market_research_dossier_resume", {}) or {})
    if str(trajectory.get("status", "") or "") == "ready":
        status = "ready"
    action_type = str(resume.get("selected_action", "") or "")
    record = {
        "schema": STAGE202_MARKET_RESEARCH_DOSSIER_RESUME_ACTION_SCHEMA,
        "action_id": "stage202_market_resume:" + stable_digest(thread_key, project_key, query, status, limit=12),
        "tool": "market_research_dossier_resume",
        "status": status,
        "thread_key": thread_key,
        "project_key": project_key,
        "query": _compact(query, 260),
        "lookup_status": str(dict(registry.get("lookup", {}) or {}).get("status", "") or ""),
        "selected_action": action_type,
        "canonical_stop_reason": str(registry.get("canonical_stop_reason", "") or ""),
        "source_count": int(dict(dict(registry.get("lookup", {}) or {}).get("dossier", {}) or {}).get("source_count", 0) or 0),
        "metric_count": int(dict(dict(registry.get("lookup", {}) or {}).get("dossier", {}) or {}).get("metric_count", 0) or 0),
        "summary": _compact(registry.get("public_summary", "") or f"market research dossier resume status={status}", 360),
        "observed_at": utc_now(),
        "hidden_reasoning_exposed": False,
    }
    return sanitize_public_metadata(
        {
            "schema": STAGE202_MARKET_RESEARCH_DOSSIER_RESUME_ACTION_SCHEMA,
            "status": status,
            "stage201_market_research_dossier_registry": registry,
            "stage204_market_research_agent_trajectory": trajectory,
            "stage195_market_research_continuation_loop": dict(trajectory.get("stage195_market_research_continuation_loop", {}) or {}),
            "web_observation_ledger": [dict(row) for row in list(trajectory.get("web_observation_ledger", []) or []) if isinstance(row, dict)],
            "market_research_pack_ledger": [
                dict(row) for row in list(trajectory.get("market_research_pack_ledger", []) or []) if isinstance(row, dict)
            ],
            "market_research_report_ledger": [
                dict(row) for row in list(trajectory.get("market_research_report_ledger", []) or []) if isinstance(row, dict)
            ],
            "stage169_market_research_pack": dict(trajectory.get("stage169_market_research_pack", {}) or {}),
            "stage173_market_research_report": dict(trajectory.get("stage173_market_research_report", {}) or {}),
            "market_research_dossier_resume_ledger": [record],
            "tool_observation_ledger": [
                {
                    "provider_call_id": "",
                    "tool": "market_research_dossier_resume",
                    "status": "ok" if status in {"resumed", "completed", "already_complete", "no_next_action"} else status,
                    "summary": record["summary"],
                    "data_keys": ["thread_key", "project_key", "query", "lookup_status", "selected_action"],
                    "grounding_tags": ["market_research", "dossier", "resume"] if status not in {"missing", "error"} else [],
                    "query": _compact(query, 260),
                }
            ],
            "canonical_stop_reason": str(registry.get("canonical_stop_reason", "") or ""),
            "hidden_reasoning_exposed": False,
        }
    )
