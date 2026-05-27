from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .agent_event_stream import build_agent_event_stream, render_agent_event_stream
from .agent_intent_frame import build_intent_frame
from .agent_loop_fsm import run_agent_loop_fsm
from .common import compact_text, stable_digest, utc_now
from .evidence_action_remediation import build_evidence_action_remediation
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .live_remediation_executor import execute_live_remediation_actions
from .live_remediation_loop import build_live_remediation_loop

STAGE181_LIVE_REMEDIATION_STRESS_SCHEMA = "holo.stage181.live_remediation_stress.v1"


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


def default_live_remediation_stress_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "fallback-recovers-source",
            "issues": [
                {
                    "issue_id": "lit-fallback",
                    "domain": "literature_research",
                    "issue_type": "source_missing",
                    "claim": "official source missing",
                }
            ],
            "mode": "fallback_success",
            "max_actions": 1,
        },
        {
            "fixture_id": "budget-preserves-second-action",
            "issues": [
                {"issue_id": "src-1", "domain": "literature_research", "issue_type": "source_missing", "claim": "source"},
                {"issue_id": "mem-1", "domain": "agent_memory", "issue_type": "memory_unsupported", "claim": "memory"},
            ],
            "mode": "budget_guard",
            "max_actions": 1,
        },
        {
            "fixture_id": "missing-artifact-path",
            "issues": [
                {"issue_id": "gpu-1", "domain": "gpu_experiment", "issue_type": "experiment_failed", "claim": "training succeeded"}
            ],
            "mode": "missing_artifact",
            "max_actions": 1,
        },
        {
            "fixture_id": "network-disabled-source",
            "issues": [
                {"issue_id": "src-net", "domain": "literature_research", "issue_type": "source_missing", "claim": "needs live web"}
            ],
            "mode": "network_disabled",
            "max_actions": 1,
        },
    ]


def _execute_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    issues = _list_dicts(fixture.get("issues", []))
    remediation = build_evidence_action_remediation(issues)
    loop = build_live_remediation_loop(remediation)
    mode = str(fixture.get("mode", "") or "")
    max_actions = int(fixture.get("max_actions", 1) or 1)
    network_enabled = mode != "network_disabled"

    def primary_search(query: str) -> dict[str, Any]:
        if mode == "fallback_success":
            return {"query": query, "status": "error", "error": "primary timeout", "provider": "primary"}
        return {
            "query": query,
            "status": "ok",
            "provider": "primary",
            "results": [{"title": "source", "url": "https://example.com/source", "snippet": query}],
        }

    fallback_search_fns = []
    if mode == "fallback_success":
        fallback_search_fns.append(
            (
                "fallback",
                lambda query: {
                    "query": query,
                    "status": "ok",
                    "provider": "fallback",
                    "results": [{"title": "official source", "url": "https://example.com/official", "snippet": query}],
                },
            )
        )

    execution = execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        repo_root=Path.cwd(),
        network_enabled=network_enabled,
        web_search_fn=primary_search,
        fallback_search_fns=fallback_search_fns,
        memory_recall_fn=lambda query: {
            "memory_call_id": "stage181:memory",
            "query": query,
            "status": "grounded",
            "selected_ids": ["stage181-memory"],
            "summary": "stage181 grounded memory evidence",
            "confidence": 0.9,
        },
        max_actions=max_actions,
    )
    frame = build_intent_frame(str(fixture.get("fixture_id", "") or "stage181 stress"))
    fsm = run_agent_loop_fsm(
        intent_frame=frame,
        stage178_evidence_action_remediation=remediation,
        stage180_live_remediation_execution=execution,
        final_text="stress draft",
    )
    payload = {
        "text": fsm.get("final_text", ""),
        "stage178_evidence_action_remediation": remediation,
        "stage179_live_remediation_loop": loop,
        "stage180_live_remediation_execution": execution,
        "stage160r_agent_loop_fsm": fsm,
    }
    stream = build_agent_event_stream(payload, user_text=str(fixture.get("fixture_id", "")), channel="holo_cli")
    return _dict(
        _public(
            {
                "fixture_id": str(fixture.get("fixture_id", "") or stable_digest(fixture, limit=10)),
                "mode": mode,
                "stage178_evidence_action_remediation": remediation,
                "stage179_live_remediation_loop": loop,
                "stage180_live_remediation_execution": execution,
                "stage160r_agent_loop_fsm": fsm,
                "stage153_agent_event_stream": stream,
                "rendered_event_stream": render_agent_event_stream(stream),
            }
        )
    )


def _case_passed(case: dict[str, Any]) -> bool:
    mode = str(case.get("mode", "") or "")
    execution = _dict(case.get("stage180_live_remediation_execution", {}))
    fsm = _dict(case.get("stage160r_agent_loop_fsm", {}))
    if mode == "fallback_success":
        return execution.get("status") == "executed" and any(
            row.get("provider") == "fallback" and row.get("status") == "ok"
            for row in _list_dicts(execution.get("web_observation_ledger", []))
        )
    if mode == "budget_guard":
        return (
            execution.get("status") == "partial"
            and execution.get("canonical_stop_reason") == "budget_exhausted"
            and bool(execution.get("remaining_action_candidates", []))
            and fsm.get("canonical_stop_reason") == "budget_exhausted"
        )
    if mode == "missing_artifact":
        return execution.get("canonical_stop_reason") == "needs_user_clarification"
    if mode == "network_disabled":
        return execution.get("canonical_stop_reason") == "boundary_or_permission"
    return False


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for case in cases if _case_passed(case))
    fallback_recovery = sum(
        1
        for case in cases
        if any(
            row.get("provider") == "fallback" and row.get("status") == "ok"
            for row in _list_dicts(_dict(case.get("stage180_live_remediation_execution", {})).get("web_observation_ledger", []))
        )
    )
    budget_guard = sum(
        1
        for case in cases
        if _dict(case.get("stage180_live_remediation_execution", {})).get("canonical_stop_reason") == "budget_exhausted"
    )
    clarification = sum(
        1
        for case in cases
        if _dict(case.get("stage180_live_remediation_execution", {})).get("canonical_stop_reason") == "needs_user_clarification"
    )
    boundary = sum(
        1
        for case in cases
        if _dict(case.get("stage180_live_remediation_execution", {})).get("canonical_stop_reason") == "boundary_or_permission"
    )
    return {
        "case_count": len(cases),
        "passed_case_count": passed,
        "failed_case_count": len(cases) - passed,
        "fallback_recovery_count": fallback_recovery,
        "budget_guard_count": budget_guard,
        "clarification_stop_count": clarification,
        "boundary_stop_count": boundary,
        "pass_rate": round(passed / max(1, len(cases)), 4),
    }


def _html_report(bundle: dict[str, Any]) -> str:
    summary = _dict(bundle.get("summary", {}))
    rows = []
    for case in _list_dicts(bundle.get("cases", [])):
        execution = _dict(case.get("stage180_live_remediation_execution", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(case.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(case.get('mode', '')))}</td>"
            f"<td>{html.escape(str(execution.get('status', '')))}</td>"
            f"<td>{html.escape(str(execution.get('canonical_stop_reason', '')))}</td>"
            f"<td>{html.escape(str(_case_passed(case)))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage181 Live Remediation Stress</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage181 Live Remediation Stress</h1>"
        "<p>Adversarial offline simulation for fallback recovery, budget guards, clarification stops, and network boundaries.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">cases<br><b>{summary.get('case_count', 0)}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0)}</b></div>"
        f"<div class=\"card\">fallbacks<br><b>{summary.get('fallback_recovery_count', 0)}</b></div>"
        f"<div class=\"card\">budget guards<br><b>{summary.get('budget_guard_count', 0)}</b></div>"
        "</div><table><thead><tr><th>Case</th><th>Mode</th><th>Status</th><th>Stop</th><th>Passed</th></tr></thead>"
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


def run_live_remediation_stress_simulation(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_live_remediation_stress_fixtures())
    cases = [_execute_fixture(row) for row in rows]
    summary = _summary(cases)
    failed_threshold = bool(fail_under is not None and float(summary["pass_rate"]) < float(fail_under))
    bundle = {
        "schema": STAGE181_LIVE_REMEDIATION_STRESS_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "failed" if summary["failed_case_count"] or failed_threshold else "passed",
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
