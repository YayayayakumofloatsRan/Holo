from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .market_research_continuation_loop import run_market_research_continuation_loop
from .market_research_dossier_registry import resume_latest_market_research_dossier

STAGE204_MARKET_RESEARCH_AGENT_TRAJECTORY_SCHEMA = "holo.stage204.market_research_agent_trajectory.v1"
STAGE204_MARKET_RESEARCH_TRAJECTORY_ROW_SCHEMA = "holo.stage204.market_research_trajectory_row.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _extend_unique_rows(target: list[dict[str, Any]], rows: Any) -> None:
    seen = {
        str(row.get("observation_id", row.get("action_id", row.get("provider_call_id", row.get("retrieval_id", "")))) or repr(row))
        for row in target
    }
    for row in _list_dicts(rows):
        key = str(row.get("observation_id", row.get("action_id", row.get("provider_call_id", row.get("retrieval_id", "")))) or repr(row))
        if key in seen:
            continue
        seen.add(key)
        target.append(row)


def _row(
    *,
    index: int,
    phase: str,
    action_type: str = "",
    status: str = "",
    observation_count: int = 0,
    source_count: int = 0,
    stop_reason: str = "",
    summary: str = "",
) -> dict[str, Any]:
    return {
        "schema": STAGE204_MARKET_RESEARCH_TRAJECTORY_ROW_SCHEMA,
        "row_id": "stage204_row:" + stable_digest(str(index), phase, action_type, status, stop_reason, summary, limit=12),
        "step_index": int(index),
        "phase": str(phase or ""),
        "action_type": str(action_type or ""),
        "status": str(status or ""),
        "observation_count": max(0, int(observation_count or 0)),
        "source_count": max(0, int(source_count or 0)),
        "canonical_stop_reason": str(stop_reason or ""),
        "summary": _compact(summary, 320),
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }


def _resume_source_count(resume: dict[str, Any]) -> int:
    urls: set[str] = set()
    for row in _list_dicts(resume.get("web_observation_ledger", [])):
        for url in list(row.get("source_urls", []) or []):
            text = str(url or "").strip()
            if text:
                urls.add(text)
        for result in _list_dicts(row.get("results", [])):
            text = str(result.get("url", "") or "").strip()
            if text:
                urls.add(text)
    return len(urls)


def build_market_research_agent_trajectory(
    *,
    registry_report: dict[str, Any] | None = None,
    continuation_loop: dict[str, Any] | None = None,
    max_actions: int = 1,
) -> dict[str, Any]:
    registry = _dict(registry_report)
    continuation = _dict(continuation_loop)
    lookup = _dict(registry.get("lookup", {}))
    resume = _dict(registry.get("stage200_market_research_dossier_resume", {}))
    rows: list[dict[str, Any]] = []
    index = 1

    selected_action = str(resume.get("selected_action", "") or "")
    if selected_action:
        rows.append(
            _row(
                index=index,
                phase="resume_action",
                action_type=selected_action,
                status=str(resume.get("status", "") or ""),
                observation_count=len(_list_dicts(resume.get("web_observation_ledger", [])))
                + len(_list_dicts(resume.get("market_research_pack_ledger", [])))
                + len(_list_dicts(resume.get("market_research_report_ledger", []))),
                source_count=_resume_source_count(resume),
                stop_reason=str(resume.get("canonical_stop_reason", "") or ""),
                summary=str(resume.get("public_summary", "") or ""),
            )
        )
        index += 1

    for round_row in _list_dicts(continuation.get("rounds", [])):
        action_type = str(round_row.get("selected_action", "") or "")
        if not action_type:
            continue
        execution = _dict(round_row.get("execution", {}))
        observation_count = (
            len(_list_dicts(execution.get("web_observation_ledger", [])))
            + len(_list_dicts(execution.get("market_research_pack_ledger", [])))
            + len(_list_dicts(execution.get("market_research_report_ledger", [])))
        )
        rows.append(
            _row(
                index=index,
                phase="continuation_round",
                action_type=action_type,
                status=str(round_row.get("execution_status", "") or ""),
                observation_count=observation_count,
                source_count=len(_list_dicts(execution.get("web_observation_ledger", []))),
                stop_reason=str(round_row.get("canonical_stop_reason", "") or ""),
                summary=f"round={round_row.get('round_index', index)} status={round_row.get('execution_status', '')}",
            )
        )
        index += 1

    action_sequence = [str(row.get("action_type", "") or "") for row in rows if str(row.get("action_type", "") or "")]
    status = str(continuation.get("status", "") or registry.get("status", "") or resume.get("status", "") or lookup.get("status", "") or "missing")
    if status == "ready":
        trajectory_status = "ready"
    elif status in {"blocked", "failed", "missing", "exhausted"}:
        trajectory_status = status
    elif continuation:
        trajectory_status = status or "partial"
    else:
        trajectory_status = status if status in {"resumed", "completed", "already_complete"} else "partial"
    stop_reason = str(continuation.get("canonical_stop_reason", "") or registry.get("canonical_stop_reason", "") or resume.get("canonical_stop_reason", "") or "")

    return sanitize_public_metadata(
        {
            "schema": STAGE204_MARKET_RESEARCH_AGENT_TRAJECTORY_SCHEMA,
            "status": trajectory_status,
            "lookup_status": str(lookup.get("status", "") or ""),
            "resume_status": str(resume.get("status", "") or ""),
            "continuation_status": str(continuation.get("status", "") or ""),
            "trajectory_round_count": len(rows),
            "trajectory_rows": rows,
            "action_sequence": action_sequence,
            "max_actions": max(0, int(max_actions or 0)),
            "stage201_market_research_dossier_registry": registry,
            "stage195_market_research_continuation_loop": continuation,
            "canonical_stop_reason": stop_reason or "final_answer_ready",
            "public_summary": _compact(
                f"market research trajectory: status={trajectory_status}; actions={','.join(action_sequence) or 'none'}; stop={stop_reason}",
                360,
            ),
            "hidden_reasoning_exposed": False,
            "created_at": utc_now(),
        }
    )


def run_market_research_dossier_agent_trajectory(
    *,
    state_dir: str | Path,
    thread_key: str = "",
    project_key: str = "",
    question: str = "",
    network_enabled: bool = False,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    fallback_search_fns: list[tuple[str, Callable[[str], dict[str, Any]]]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    max_actions: int = 1,
) -> dict[str, Any]:
    action_budget = max(0, min(int(max_actions or 0), 8))
    first_action_budget = 1 if action_budget > 0 else 0
    registry = resume_latest_market_research_dossier(
        state_dir=state_dir,
        thread_key=thread_key,
        project_key=project_key,
        question=question,
        network_enabled=bool(network_enabled),
        web_search_fn=web_search_fn,
        fallback_search_fns=fallback_search_fns,
        open_page_fn=open_page_fn,
        max_actions=first_action_budget,
    )
    resume = _dict(registry.get("stage200_market_research_dossier_resume", {}))
    continuation: dict[str, Any] = {}
    remaining = max(0, action_budget - (1 if str(resume.get("selected_action", "") or "") else 0))
    if remaining > 0 and str(registry.get("status", "") or "") in {"resumed", "completed", "already_complete", "no_next_action"}:
        continuation = run_market_research_continuation_loop(
            question=str(resume.get("question", "") or question or ""),
            web_observation_ledger=resume.get("web_observation_ledger", []),
            market_research_pack_ledger=resume.get("market_research_pack_ledger", []),
            market_research_report_ledger=resume.get("market_research_report_ledger", []),
            network_enabled=bool(network_enabled),
            web_search_fn=web_search_fn,
            fallback_search_fns=fallback_search_fns,
            open_page_fn=open_page_fn,
            max_rounds=remaining,
        )
    report = build_market_research_agent_trajectory(
        registry_report=registry,
        continuation_loop=continuation,
        max_actions=action_budget,
    )
    web_rows = _list_dicts(resume.get("web_observation_ledger", []))
    pack_rows = _list_dicts(resume.get("market_research_pack_ledger", []))
    report_rows = _list_dicts(resume.get("market_research_report_ledger", []))
    tool_rows = _list_dicts(resume.get("tool_observation_ledger", []))
    _extend_unique_rows(web_rows, continuation.get("web_observation_ledger", []))
    _extend_unique_rows(tool_rows, continuation.get("tool_observation_ledger", []))
    _extend_unique_rows(pack_rows, continuation.get("market_research_pack_ledger", []))
    _extend_unique_rows(report_rows, continuation.get("market_research_report_ledger", []))
    report["web_observation_ledger"] = web_rows
    report["tool_observation_ledger"] = tool_rows
    report["market_research_pack_ledger"] = pack_rows
    report["market_research_report_ledger"] = report_rows
    report["stage169_market_research_pack"] = _dict(continuation.get("stage169_market_research_pack", {}))
    report["stage173_market_research_report"] = _dict(continuation.get("stage173_market_research_report", {}))
    return sanitize_public_metadata(report)
