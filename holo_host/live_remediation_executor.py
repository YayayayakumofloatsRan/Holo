from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .engineering_workspace_tools import file_read
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .live_remediation_loop import build_live_remediation_loop, default_live_remediation_simulation_fixtures
from .stage151_tool_decision_loop import execute_tool_decision

STAGE180_LIVE_REMEDIATION_EXECUTOR_SCHEMA = "holo.stage180.live_remediation_executor.v1"
STAGE180_LIVE_REMEDIATION_EXECUTION_SIMULATION_SCHEMA = "holo.stage180.live_remediation_execution_simulation.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _public(value: Any) -> Any:
    clean = sanitize_public_metadata(value)
    if isinstance(clean, dict):
        return {str(key): _public(item) for key, item in clean.items() if str(key) != "reasoning_content_retained_count"}
    if isinstance(clean, list):
        return [_public(item) for item in clean]
    return clean


def _issues_by_id(stage178_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for issue in _list_dicts(_dict(stage178_report).get("issues", [])):
        issue_id = str(issue.get("issue_id", "") or "")
        if issue_id:
            rows[issue_id] = issue
    return rows


def _query_for_action(action: dict[str, Any], issue: dict[str, Any]) -> str:
    for key in ("query", "search_query"):
        value = str(action.get(key, "") or issue.get(key, "") or "").strip()
        if value:
            return value
    claim = str(issue.get("claim", "") or action.get("reason", "") or "").strip()
    evidence = " ".join(str(item) for item in list(action.get("required_evidence", issue.get("required_evidence", [])) or []))
    return _compact((claim + " " + evidence).strip() or str(action.get("action_type", "") or "evidence search"), 240)


def _artifact_path_for_action(action: dict[str, Any], issue: dict[str, Any]) -> str:
    for key in ("path", "artifact_path", "file_path"):
        value = str(action.get(key, "") or issue.get(key, "") or "").strip()
        if value:
            return value
    for value in list(action.get("artifact_paths", []) or issue.get("artifact_paths", []) or []):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _memory_row_from_result(result: Any, *, query: str, action: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, dict):
        row = dict(result)
    else:
        row = {
            "summary": str(result or ""),
            "status": "grounded" if str(result or "").strip() else "missing",
            "selected_ids": [],
            "confidence": 0.25,
        }
    row.setdefault("memory_call_id", "stage180:" + stable_digest(query, str(action.get("action_id", "")), limit=12))
    row.setdefault("query", query)
    row.setdefault("status", "grounded" if row.get("summary") or row.get("selected_ids") else "missing")
    row.setdefault("selected_ids", [])
    row.setdefault("summary", "")
    row.setdefault("confidence", 0.0)
    return row


def _action_result(
    action: dict[str, Any],
    *,
    status: str,
    observation_count: int = 0,
    stop_reason: str = "",
    error: str = "",
) -> dict[str, Any]:
    return {
        "action_id": str(action.get("action_id", "") or ""),
        "action_type": str(action.get("action_type", "") or ""),
        "required_tool": str(action.get("required_tool", "") or ""),
        "status": status,
        "observation_count": int(max(0, observation_count)),
        "canonical_stop_reason": stop_reason,
        "error": _compact(error, 320),
    }


def execute_live_remediation_actions(
    stage179_live_remediation_loop: dict[str, Any] | None,
    *,
    stage178_evidence_action_remediation: dict[str, Any] | None = None,
    repo_root: str | Path | None = None,
    network_enabled: bool = False,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    memory_recall_fn: Callable[[str], dict[str, Any]] | None = None,
    max_actions: int = 1,
) -> dict[str, Any]:
    loop = _dict(stage179_live_remediation_loop)
    stage178 = _dict(stage178_evidence_action_remediation)
    actions = _list_dicts(loop.get("next_action_candidates", []))[: max(0, int(max_actions or 0))]
    issues = _issues_by_id(stage178)
    web_rows: list[dict[str, Any]] = []
    memory_rows: list[dict[str, Any]] = []
    engineering_rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    executed = rejected = failed = 0

    for action in actions:
        required_tool = str(action.get("required_tool", "") or "")
        issue = issues.get(str(action.get("issue_id", "") or ""), {})
        if required_tool == "web_search":
            query = _query_for_action(action, issue)
            decision = {"user_text": query, "selected_actions": [{"action_type": "web_search", "query": query}]}
            observations = execute_tool_decision(
                decision,
                network_enabled=bool(network_enabled),
                web_search_fn=web_search_fn,
                open_page_fn=open_page_fn,
            )
            web_rows.extend(observations)
            if observations and str(observations[0].get("status", "") or "") == "ok":
                executed += 1
                results.append(_action_result(action, status="executed", observation_count=len(observations), stop_reason="final_answer_ready"))
            elif observations and str(observations[0].get("status", "") or "") == "rejected_network_disabled":
                rejected += 1
                results.append(_action_result(action, status="rejected", observation_count=len(observations), stop_reason="boundary_or_permission", error="network_disabled"))
            else:
                failed += 1
                error = str(observations[0].get("error", "") if observations else "web_search_failed")
                results.append(_action_result(action, status="failed", observation_count=len(observations), stop_reason="tool_failure_report", error=error))
            continue
        if required_tool == "file_read":
            if repo_root is None:
                rejected += 1
                results.append(_action_result(action, status="rejected", stop_reason="boundary_or_permission", error="repo_root_required"))
                continue
            path = _artifact_path_for_action(action, issue)
            if not path:
                rejected += 1
                results.append(_action_result(action, status="rejected", stop_reason="needs_user_clarification", error="artifact_path_required"))
                continue
            row = file_read(repo_root, path)
            engineering_rows.append(row)
            if str(row.get("status", "") or "") == "ok":
                executed += 1
                results.append(_action_result(action, status="executed", observation_count=1, stop_reason="final_answer_ready"))
            else:
                failed += 1
                results.append(_action_result(action, status="failed", observation_count=1, stop_reason="tool_failure_report", error=str(row.get("stderr_summary", "") or "")))
            continue
        if required_tool == "memory_recall":
            query = _query_for_action(action, issue)
            if memory_recall_fn is None:
                rejected += 1
                row = {
                    "memory_call_id": "stage180:" + stable_digest(query, limit=12),
                    "query": query,
                    "status": "unavailable",
                    "selected_ids": [],
                    "summary": "memory_recall_fn unavailable",
                    "confidence": 0.0,
                }
            else:
                row = _memory_row_from_result(memory_recall_fn(query), query=query, action=action)
                if str(row.get("status", "") or "") in {"grounded", "weak"}:
                    executed += 1
                else:
                    failed += 1
            memory_rows.append(row)
            status = "executed" if str(row.get("status", "") or "") in {"grounded", "weak"} else "rejected" if str(row.get("status", "") or "") == "unavailable" else "failed"
            stop = "final_answer_ready" if status == "executed" else "evidence_exhausted"
            results.append(_action_result(action, status=status, observation_count=1, stop_reason=stop, error=str(row.get("summary", "") or "") if status != "executed" else ""))
            continue
        rejected += 1
        results.append(_action_result(action, status="rejected", stop_reason="boundary_or_permission", error=f"unsupported_required_tool:{required_tool}"))

    if not actions:
        status = "no_actions"
        stop_reason = str(loop.get("canonical_stop_reason", "") or "final_answer_ready")
    elif executed and not failed and not rejected:
        status = "executed"
        stop_reason = "final_answer_ready"
    elif executed:
        status = "partial"
        stop_reason = "tool_failure_report" if failed else "boundary_or_permission"
    elif rejected and not failed:
        status = "blocked"
        stop_reason = "boundary_or_permission"
    else:
        status = "failed"
        stop_reason = "tool_failure_report"

    report = {
        "schema": STAGE180_LIVE_REMEDIATION_EXECUTOR_SCHEMA,
        "status": status,
        "stage179_live_remediation_loop": loop,
        "executed_count": executed,
        "rejected_count": rejected,
        "failed_count": failed,
        "action_results": results,
        "web_observation_ledger": web_rows,
        "memory_observation_ledger": memory_rows,
        "engineering_action_ledger": engineering_rows,
        "canonical_stop_reason": stop_reason,
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": bool(network_enabled and web_rows),
            "tool_execution": bool(results),
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    return _dict(_public(report))


def _simulate_case(fixture: dict[str, Any]) -> dict[str, Any]:
    from .evidence_action_remediation import build_evidence_action_remediation
    from .agent_intent_frame import build_intent_frame
    from .agent_loop_fsm import run_agent_loop_fsm
    from .agent_event_stream import build_agent_event_stream, render_agent_event_stream

    remediation = build_evidence_action_remediation(_list_dicts(fixture.get("issues", [])))
    loop = build_live_remediation_loop(remediation)
    execution = execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "ok",
            "provider": "stage180_mock_search",
            "results": [{"title": "mock source", "url": "https://example.org/source", "snippet": query}],
        },
        memory_recall_fn=lambda query: {
            "memory_call_id": "stage180:mock-memory",
            "query": query,
            "status": "grounded",
            "selected_ids": ["fixture-memory"],
            "summary": "mock grounded memory evidence",
            "confidence": 0.9,
        },
    )
    frame = build_intent_frame(str(fixture.get("fixture_id", "") or "stage180 simulation"))
    fsm = run_agent_loop_fsm(
        intent_frame=frame,
        stage178_evidence_action_remediation=remediation,
        stage180_live_remediation_execution=execution,
        final_text="simulation final",
    )
    payload = {
        "text": fsm.get("final_text", ""),
        "stage160r_agent_loop_fsm": fsm,
        "stage178_evidence_action_remediation": remediation,
        "stage179_live_remediation_loop": loop,
        "stage180_live_remediation_execution": execution,
    }
    event_stream = build_agent_event_stream(payload, user_text=str(fixture.get("fixture_id", "") or ""), channel="holo_cli")
    return _dict(
        _public(
            {
                "fixture_id": str(fixture.get("fixture_id", "") or stable_digest(json.dumps(fixture, ensure_ascii=False), limit=10)),
                "stage178_evidence_action_remediation": remediation,
                "stage179_live_remediation_loop": loop,
                "stage180_live_remediation_execution": execution,
                "stage160r_agent_loop_fsm": fsm,
                "stage153_agent_event_stream": event_stream,
                "rendered_event_stream": render_agent_event_stream(event_stream),
            }
        )
    )


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    executed = 0
    blocked = 0
    failed = 0
    for case in cases:
        execution = _dict(case.get("stage180_live_remediation_execution", {}))
        if str(execution.get("status", "") or "") == "executed":
            executed += 1
        elif str(execution.get("status", "") or "") == "failed":
            failed += 1
        elif str(execution.get("status", "") or "") in {"blocked", "partial"}:
            blocked += 1
    return {
        "case_count": len(cases),
        "executed_case_count": executed,
        "blocked_case_count": blocked,
        "failed_case_count": failed,
    }


def _html_report(bundle: dict[str, Any]) -> str:
    rows = []
    for case in _list_dicts(bundle.get("cases", [])):
        execution = _dict(case.get("stage180_live_remediation_execution", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(case.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(execution.get('status', '')))}</td>"
            f"<td>{html.escape(str(execution.get('executed_count', 0)))}</td>"
            f"<td>{html.escape(str(execution.get('canonical_stop_reason', '')))}</td>"
            "</tr>"
        )
    summary = _dict(bundle.get("summary", {}))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage180 Live Remediation Execution</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}</style></head><body>"
        "<h1>Stage180 Live Remediation Execution Simulation</h1>"
        f"<p>cases={summary.get('case_count', 0)} executed={summary.get('executed_case_count', 0)} blocked={summary.get('blocked_case_count', 0)}</p>"
        "<table><thead><tr><th>Case</th><th>Status</th><th>Executed</th><th>Stop</th></tr></thead>"
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
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in _list_dicts(bundle.get("cases", []))) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_live_remediation_execution_simulation(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_live_remediation_simulation_fixtures())
    cases = [_simulate_case(row) for row in rows]
    summary = _summary(cases)
    bundle = {
        "schema": STAGE180_LIVE_REMEDIATION_EXECUTION_SIMULATION_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "passed",
        "case_count": len(cases),
        "cases": cases,
        "summary": summary,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["executed_case_count"] / max(1, len(cases)) < float(fail_under)),
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
