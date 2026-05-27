from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Callable

from .agent_event_stream import build_agent_event_stream, render_agent_event_stream
from .agent_intent_frame import build_intent_frame
from .agent_loop_fsm import run_agent_loop_fsm
from .common import compact_text, stable_digest, utc_now
from .evidence_action_remediation import build_evidence_action_remediation
from .kernel_metadata_sanitizer import PRIVATE_KEYS
from .live_remediation_executor import execute_live_remediation_actions
from .live_remediation_loop import build_live_remediation_loop
from .live_remediation_stress import default_live_remediation_stress_fixtures

STAGE182_REMEDIATION_CONTINUATION_SCHEMA = "holo.stage182.remediation_continuation.v1"
STAGE182_REMEDIATION_CONTINUATION_BUNDLE_SCHEMA = "holo.stage182.remediation_continuation_bundle.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _public(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _public(item)
            for key, item in value.items()
            if str(key).strip().lower() not in PRIVATE_KEYS and str(key) != "reasoning_content_retained_count"
        }
    if isinstance(value, list):
        return [_public(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_public(item) for item in value)
    return value


def _best_web_score(rows: list[dict[str, Any]]) -> tuple[float, list[str]]:
    if not rows:
        return 0.0, ["missing_web_observation"]
    best = 0.0
    missing: list[str] = []
    for row in rows:
        row_score = 0.0
        if str(row.get("status", "") or "") == "ok":
            row_score += 0.25
        if list(row.get("source_urls", []) or []):
            row_score += 0.15
        search = _dict(row.get("search_evidence", {}))
        row_score += min(0.25, max(0.0, float(search.get("evidence_score", 0.0) or 0.0)) * 0.25)
        authority = _dict(row.get("source_authority", {}))
        authority_status = str(authority.get("status", "") or "")
        if authority_status in {"sufficient", "ok", "passed"}:
            row_score += 0.3
        elif authority_status == "insufficient":
            missing.append("weak_web_evidence")
        if str(search.get("status", "") or "") in {"weak", "failed"}:
            missing.append("weak_web_evidence")
        best = max(best, min(1.0, row_score))
    if best < 0.72 and "weak_web_evidence" not in missing:
        missing.append("weak_web_evidence")
    return best, sorted(set(missing))


def _memory_score(rows: list[dict[str, Any]]) -> tuple[float, list[str]]:
    if not rows:
        return 0.0, ["missing_memory_observation"]
    best = 0.0
    for row in rows:
        if str(row.get("status", "") or "") == "grounded":
            best = max(best, 0.75 + min(0.25, max(0.0, float(row.get("confidence", 0.0) or 0.0)) * 0.25))
        elif str(row.get("status", "") or "") == "weak":
            best = max(best, 0.45)
    return min(1.0, best), [] if best >= 0.72 else ["weak_memory_observation"]


def _engineering_score(rows: list[dict[str, Any]]) -> tuple[float, list[str]]:
    if not rows:
        return 0.0, ["missing_engineering_observation"]
    ok_rows = [row for row in rows if str(row.get("status", "") or "") == "ok"]
    if ok_rows:
        return 0.92, []
    return 0.25, ["engineering_action_not_ok"]


def score_remediation_sufficiency(report: dict[str, Any], *, threshold: float = 0.72) -> dict[str, Any]:
    action_results = _list_dicts(report.get("action_results", []))
    required_tools = {str(row.get("required_tool", "") or "") for row in action_results if str(row.get("required_tool", "") or "")}
    executed_ratio = sum(1 for row in action_results if str(row.get("status", "") or "") == "executed") / max(1, len(action_results))
    components: dict[str, float] = {"executed_ratio": round(executed_ratio, 4)}
    missing: list[str] = []
    observation_scores: list[float] = []
    if "web_search" in required_tools:
        score, missing_rows = _best_web_score(_list_dicts(report.get("web_observation_ledger", [])))
        components["web"] = round(score, 4)
        observation_scores.append(score)
        missing.extend(missing_rows)
    if "memory_recall" in required_tools:
        score, missing_rows = _memory_score(_list_dicts(report.get("memory_observation_ledger", [])))
        components["memory"] = round(score, 4)
        observation_scores.append(score)
        missing.extend(missing_rows)
    if "file_read" in required_tools:
        score, missing_rows = _engineering_score(_list_dicts(report.get("engineering_action_ledger", [])))
        components["engineering"] = round(score, 4)
        observation_scores.append(score)
        missing.extend(missing_rows)
    if not observation_scores:
        observation_scores.append(executed_ratio)
    observation_avg = sum(observation_scores) / max(1, len(observation_scores))
    score = max(0.0, min(1.0, executed_ratio * 0.35 + observation_avg * 0.65))
    if "weak_web_evidence" in missing and "web_search" in required_tools and components.get("web", 0.0) < threshold:
        status = "insufficient"
    elif score >= threshold:
        status = "sufficient"
    elif score >= threshold * 0.6:
        status = "partial"
    else:
        status = "insufficient"
    return {
        "schema": "holo.stage182.remediation_sufficiency.v1",
        "status": status,
        "score": round(score, 4),
        "threshold": float(threshold),
        "components": components,
        "missing_evidence": sorted(set(missing)),
    }


def _continuation_loop(base_loop: dict[str, Any], remaining: list[dict[str, Any]], round_index: int) -> dict[str, Any]:
    selected = remaining[0] if remaining else {}
    loop = dict(base_loop)
    loop["status"] = "blocked_for_remediation" if remaining else "no_remediation_required"
    loop["blocked"] = bool(remaining)
    loop["next_action_candidates"] = remaining
    loop["selected_next_action"] = selected
    loop["selected_action_type"] = str(selected.get("action_type", "") or "")
    loop["selected_required_tool"] = str(selected.get("required_tool", "") or "")
    loop["round_index"] = round_index
    return loop


def _merge_execution_reports(executions: list[dict[str, Any]], *, base_loop: dict[str, Any], remaining: list[dict[str, Any]], stop_reason: str) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "schema": "holo.stage180.live_remediation_executor.v1",
        "status": "executed",
        "stage179_live_remediation_loop": base_loop,
        "executed_count": 0,
        "rejected_count": 0,
        "failed_count": 0,
        "attempted_count": 0,
        "skipped_count": len(remaining),
        "remaining_action_candidates": remaining,
        "next_action_required": bool(remaining) or stop_reason != "final_answer_ready",
        "continuation_reason": "continuation_budget_exhausted" if remaining else stop_reason if stop_reason != "final_answer_ready" else "",
        "action_results": [],
        "web_observation_ledger": [],
        "memory_observation_ledger": [],
        "engineering_action_ledger": [],
        "canonical_stop_reason": stop_reason,
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    for execution in executions:
        merged["executed_count"] += int(execution.get("executed_count", 0) or 0)
        merged["rejected_count"] += int(execution.get("rejected_count", 0) or 0)
        merged["failed_count"] += int(execution.get("failed_count", 0) or 0)
        merged["attempted_count"] += int(execution.get("attempted_count", 0) or 0)
        for key in ("action_results", "web_observation_ledger", "memory_observation_ledger", "engineering_action_ledger"):
            merged[key].extend(_list_dicts(execution.get(key, [])))
        authority = _dict(execution.get("authority_boundary", {}))
        merged["authority_boundary"]["network_fetches_executed"] = bool(merged["authority_boundary"]["network_fetches_executed"] or authority.get("network_fetches_executed", False))
        merged["authority_boundary"]["tool_execution"] = bool(merged["authority_boundary"]["tool_execution"] or authority.get("tool_execution", False))
    if merged["failed_count"]:
        merged["status"] = "failed"
    elif merged["rejected_count"]:
        merged["status"] = "blocked"
    elif remaining:
        merged["status"] = "partial"
    elif merged["executed_count"]:
        merged["status"] = "executed"
    else:
        merged["status"] = "no_actions"
    return merged


def run_live_remediation_continuation(
    stage179_live_remediation_loop: dict[str, Any] | None,
    *,
    stage178_evidence_action_remediation: dict[str, Any] | None = None,
    repo_root: str | Path | None = None,
    network_enabled: bool = False,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    fallback_search_fns: list[tuple[str, Callable[[str], dict[str, Any]]]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    memory_recall_fn: Callable[[str], dict[str, Any]] | None = None,
    max_rounds: int = 2,
    actions_per_round: int = 1,
    sufficiency_threshold: float = 0.72,
) -> dict[str, Any]:
    base_loop = _dict(stage179_live_remediation_loop)
    remaining = _list_dicts(base_loop.get("next_action_candidates", []))
    executions: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    stop_reason = "final_answer_ready"
    status = "completed" if not remaining else "no_actions"

    for index in range(max(0, int(max_rounds or 0))):
        if not remaining:
            break
        loop = _continuation_loop(base_loop, remaining, index + 1)
        execution = execute_live_remediation_actions(
            loop,
            stage178_evidence_action_remediation=stage178_evidence_action_remediation,
            repo_root=repo_root,
            network_enabled=network_enabled,
            web_search_fn=web_search_fn,
            fallback_search_fns=fallback_search_fns,
            open_page_fn=open_page_fn,
            memory_recall_fn=memory_recall_fn,
            max_actions=actions_per_round,
        )
        executions.append(execution)
        remaining = _list_dicts(execution.get("remaining_action_candidates", []))
        stop_reason = str(execution.get("canonical_stop_reason", "") or "final_answer_ready")
        rounds.append(
            {
                "round_index": index + 1,
                "status": str(execution.get("status", "") or ""),
                "canonical_stop_reason": stop_reason,
                "executed_count": int(execution.get("executed_count", 0) or 0),
                "remaining_action_count": len(remaining),
                "action_results": _list_dicts(execution.get("action_results", [])),
            }
        )
        if stop_reason in {"needs_user_clarification", "boundary_or_permission", "tool_failure_report"}:
            break
    else:
        if remaining:
            stop_reason = "budget_exhausted"

    if remaining and stop_reason not in {"needs_user_clarification", "boundary_or_permission", "tool_failure_report"}:
        stop_reason = "budget_exhausted"
    aggregate = _merge_execution_reports(executions, base_loop=base_loop, remaining=remaining, stop_reason=stop_reason)
    sufficiency = score_remediation_sufficiency(aggregate, threshold=sufficiency_threshold)
    if stop_reason == "final_answer_ready" and sufficiency["status"] == "insufficient":
        stop_reason = "evidence_exhausted"
        status = "insufficient"
    elif stop_reason == "final_answer_ready":
        status = "completed"
    elif stop_reason == "budget_exhausted":
        status = "budget_exhausted"
    elif stop_reason in {"needs_user_clarification", "boundary_or_permission"}:
        status = "blocked"
    else:
        status = "failed"
    aggregate["canonical_stop_reason"] = stop_reason
    aggregate["status"] = "executed" if status == "completed" else "partial" if status == "budget_exhausted" else aggregate.get("status", "")
    report = {
        "schema": STAGE182_REMEDIATION_CONTINUATION_SCHEMA,
        "status": status,
        "stage179_live_remediation_loop": base_loop,
        "stage180_live_remediation_execution": aggregate,
        "round_count": len(rounds),
        "rounds": rounds,
        "executed_count": int(aggregate.get("executed_count", 0) or 0),
        "rejected_count": int(aggregate.get("rejected_count", 0) or 0),
        "failed_count": int(aggregate.get("failed_count", 0) or 0),
        "remaining_action_candidates": remaining,
        "next_action_required": bool(remaining) or status in {"blocked", "failed", "budget_exhausted", "insufficient"},
        "sufficiency": sufficiency,
        "canonical_stop_reason": stop_reason,
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": bool(_dict(aggregate.get("authority_boundary", {})).get("network_fetches_executed", False)),
            "tool_execution": bool(_dict(aggregate.get("authority_boundary", {})).get("tool_execution", False)),
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    return _dict(_public(report))


def default_remediation_continuation_fixtures() -> list[dict[str, Any]]:
    return default_live_remediation_stress_fixtures()


def _execute_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    issues = _list_dicts(fixture.get("issues", []))
    remediation = build_evidence_action_remediation(issues)
    loop = build_live_remediation_loop(remediation)
    mode = str(fixture.get("mode", "") or "")
    report = run_live_remediation_continuation(
        loop,
        stage178_evidence_action_remediation=remediation,
        repo_root=Path.cwd(),
        network_enabled=mode != "network_disabled",
        web_search_fn=lambda query: {
            "query": query,
            "status": "error" if mode == "fallback_success" else "ok",
            "error": "primary timeout" if mode == "fallback_success" else "",
            "provider": "primary",
            "results": [] if mode == "fallback_success" else [{"title": "source", "url": "https://example.com/source", "snippet": query}],
        },
        fallback_search_fns=[
            (
                "fallback",
                lambda query: {
                    "query": query,
                    "status": "ok",
                    "provider": "fallback",
                    "results": [{"title": "source", "url": "https://example.com/source", "snippet": query}],
                },
            )
        ]
        if mode == "fallback_success"
        else None,
        open_page_fn=lambda url: {
            "url": url,
            "status": "ok",
            "provider": "stage182_mock_page",
            "results": [{"title": "source", "url": url, "snippet": "official source missing source citation"}],
        },
        memory_recall_fn=lambda query: {
            "memory_call_id": "stage182:memory",
            "query": query,
            "status": "grounded",
            "selected_ids": ["stage182-memory"],
            "summary": "stage182 grounded memory evidence",
            "confidence": 0.9,
        },
        max_rounds=int(fixture.get("max_rounds", 2) or 2),
        actions_per_round=1,
        sufficiency_threshold=0.45,
    )
    frame = build_intent_frame(str(fixture.get("fixture_id", "") or "stage182 continuation"))
    fsm = run_agent_loop_fsm(
        intent_frame=frame,
        stage178_evidence_action_remediation=remediation,
        stage180_live_remediation_execution=_dict(report.get("stage180_live_remediation_execution", {})),
        final_text="continuation draft",
    )
    payload = {
        "text": fsm.get("final_text", ""),
        "stage178_evidence_action_remediation": remediation,
        "stage179_live_remediation_loop": loop,
        "stage180_live_remediation_execution": report.get("stage180_live_remediation_execution", {}),
        "stage182_remediation_continuation": report,
        "stage160r_agent_loop_fsm": fsm,
    }
    stream = build_agent_event_stream(payload, user_text=str(fixture.get("fixture_id", "")), channel="holo_cli")
    return _dict(
        _public(
            {
                "fixture_id": str(fixture.get("fixture_id", "") or stable_digest(fixture, limit=10)),
                "stage178_evidence_action_remediation": remediation,
                "stage179_live_remediation_loop": loop,
                "stage182_remediation_continuation": report,
                "stage160r_agent_loop_fsm": fsm,
                "stage153_agent_event_stream": stream,
                "rendered_event_stream": render_agent_event_stream(stream),
            }
        )
    )


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [str(_dict(case.get("stage182_remediation_continuation", {})).get("status", "") or "") for case in cases]
    return {
        "case_count": len(cases),
        "completed_count": statuses.count("completed"),
        "blocked_count": statuses.count("blocked"),
        "budget_exhausted_count": statuses.count("budget_exhausted"),
        "failed_count": statuses.count("failed"),
        "pass_rate": round(sum(1 for status in statuses if status in {"completed", "blocked", "budget_exhausted"}) / max(1, len(statuses)), 4),
    }


def _html_report(bundle: dict[str, Any]) -> str:
    summary = _dict(bundle.get("summary", {}))
    rows = []
    for case in _list_dicts(bundle.get("cases", [])):
        report = _dict(case.get("stage182_remediation_continuation", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(case.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(report.get('status', '')))}</td>"
            f"<td>{html.escape(str(report.get('round_count', 0)))}</td>"
            f"<td>{html.escape(str(report.get('canonical_stop_reason', '')))}</td>"
            f"<td>{html.escape(str(_dict(report.get('sufficiency', {})).get('score', '')))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage182 Remediation Continuation</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage182 Remediation Continuation</h1>"
        "<p>Bounded multi-round remediation continuation with sufficiency scoring.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">cases<br><b>{summary.get('case_count', 0)}</b></div>"
        f"<div class=\"card\">completed<br><b>{summary.get('completed_count', 0)}</b></div>"
        f"<div class=\"card\">blocked<br><b>{summary.get('blocked_count', 0)}</b></div>"
        f"<div class=\"card\">budget<br><b>{summary.get('budget_exhausted_count', 0)}</b></div>"
        "</div><table><thead><tr><th>Case</th><th>Status</th><th>Rounds</th><th>Stop</th><th>Sufficiency</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )


def _write_artifacts(bundle: dict[str, Any], output: str | Path) -> dict[str, str]:
    html_path = Path(output)
    if html_path.suffix.lower() != ".html":
        html_path = html_path.with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = html_path.with_suffix(".json")
    jsonl_path = html_path.with_suffix(".jsonl")
    html_path.write_text(_html_report(bundle), encoding="utf-8")
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    jsonl_path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in _list_dicts(bundle.get("cases", []))) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_remediation_continuation_simulation(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_remediation_continuation_fixtures())
    cases = [_execute_fixture(row) for row in rows]
    summary = _summary(cases)
    failed_threshold = bool(fail_under is not None and float(summary["pass_rate"]) < float(fail_under))
    bundle = {
        "schema": STAGE182_REMEDIATION_CONTINUATION_BUNDLE_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "failed" if summary["failed_count"] or failed_threshold else "passed",
        "case_count": len(cases),
        "cases": cases,
        "summary": summary,
        "fail_under": fail_under,
        "fail_under_triggered": failed_threshold,
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": False,
            "tool_execution": True,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return _dict(_public(bundle))
