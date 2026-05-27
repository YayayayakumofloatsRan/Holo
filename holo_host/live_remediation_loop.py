from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .evidence_action_remediation import build_evidence_action_remediation, default_evidence_action_remediation_fixtures
from .kernel_metadata_sanitizer import sanitize_public_metadata

STAGE179_LIVE_REMEDIATION_LOOP_SCHEMA = "holo.stage179.live_remediation_loop.v1"
STAGE179_LIVE_REMEDIATION_LOOP_SIMULATION_SCHEMA = "holo.stage179.live_remediation_loop_simulation.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _public(value: Any) -> Any:
    clean = sanitize_public_metadata(value)
    if isinstance(clean, dict):
        return {str(key): _public(item) for key, item in clean.items() if str(key) != "reasoning_content_retained_count"}
    if isinstance(clean, list):
        return [_public(item) for item in clean]
    return clean


def _canonical_stop(remediation: dict[str, Any]) -> str:
    reason = str(remediation.get("canonical_stop_reason", "") or remediation.get("recommended_stop_reason", "") or "")
    if reason in {
        "final_answer_ready",
        "goal_complete",
        "needs_user_clarification",
        "evidence_exhausted",
        "budget_exhausted",
        "low_marginal_utility",
        "boundary_or_permission",
        "tool_failure_report",
        "model_final_no_tool_calls",
    }:
        return reason
    if reason in {"needs_evidence_action", "needs_source_retry", "needs_filing_text", "needs_metric_resolution"}:
        return "evidence_exhausted"
    return "final_answer_ready" if remediation.get("can_finalize") else "evidence_exhausted"


def build_live_remediation_loop(
    remediation: dict[str, Any] | None,
    *,
    goal_id: str = "",
    current_stop_reason: str = "final_answer_ready",
) -> dict[str, Any]:
    source = _dict(remediation)
    actions = _list_dicts(source.get("actions", []))
    if not actions:
        actions = _list_dicts(source.get("remediation_actions", []))
    can_finalize = bool(source.get("can_finalize", False))
    blocked = bool(source) and not can_finalize and bool(actions)
    canonical_stop = _canonical_stop(source) if source else str(current_stop_reason or "final_answer_ready")
    selected = actions[0] if actions else {}
    report = {
        "schema": STAGE179_LIVE_REMEDIATION_LOOP_SCHEMA,
        "status": "blocked_for_remediation" if blocked else "no_remediation_required",
        "goal_id": str(goal_id or ""),
        "source_schema": str(source.get("schema", "") or ""),
        "can_finalize": bool(can_finalize or not source),
        "blocked": blocked,
        "next_action_candidates": actions,
        "selected_next_action": selected,
        "selected_action_type": str(selected.get("action_type", "") or ""),
        "selected_required_tool": str(selected.get("required_tool", "") or ""),
        "recommended_stop_reason": str(source.get("recommended_stop_reason", "") or canonical_stop),
        "canonical_stop_reason": canonical_stop,
        "operator_message": _compact(source.get("operator_message", ""), 900),
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
    return _dict(_public(report))


def default_live_remediation_simulation_fixtures() -> list[dict[str, Any]]:
    return default_evidence_action_remediation_fixtures()


def _simulate_case(fixture: dict[str, Any]) -> dict[str, Any]:
    from .agent_event_stream import build_agent_event_stream, render_agent_event_stream
    from .agent_intent_frame import build_intent_frame
    from .agent_loop_fsm import run_agent_loop_fsm

    issues = _list_dicts(fixture.get("issues", []))
    remediation = build_evidence_action_remediation(issues)
    fixture_id = str(fixture.get("fixture_id", "") or stable_digest(json.dumps(fixture, ensure_ascii=False), limit=10))
    user_text = f"simulate remediation case {fixture_id}"
    frame = build_intent_frame(user_text)
    fsm = run_agent_loop_fsm(
        intent_frame=frame,
        final_text="simulated draft answer",
        stage178_evidence_action_remediation=remediation,
    )
    payload = {
        "text": fsm.get("final_text", ""),
        "stage160r_agent_loop_fsm": fsm,
        "stage178_evidence_action_remediation": remediation,
        "stage179_live_remediation_loop": fsm.get("stage179_live_remediation_loop", {}),
    }
    event_stream = build_agent_event_stream(payload, user_text=user_text, channel="holo_cli")
    domains = sorted({str(issue.get("domain", "") or "general") for issue in issues})
    return _dict(
        _public(
            {
                "fixture_id": fixture_id,
                "domains": domains,
                "stage178_evidence_action_remediation": remediation,
                "stage179_live_remediation_loop": fsm.get("stage179_live_remediation_loop", {}),
                "stage160r_agent_loop_fsm": fsm,
                "stage153_agent_event_stream": event_stream,
                "rendered_event_stream": render_agent_event_stream(event_stream),
            }
        )
    )


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    domains: list[str] = []
    blocked = 0
    action_count = 0
    for case in cases:
        remediation = _dict(case.get("stage178_evidence_action_remediation", {}))
        if not bool(remediation.get("can_finalize", False)):
            blocked += 1
        action_count += len(_list_dicts(remediation.get("actions", [])))
        for domain in list(case.get("domains", []) or []):
            text = str(domain)
            if text and text not in domains:
                domains.append(text)
    return {
        "case_count": len(cases),
        "blocked_case_count": blocked,
        "finalizable_case_count": len(cases) - blocked,
        "next_action_count": action_count,
        "domains": sorted(domains),
    }


def _html_report(bundle: dict[str, Any]) -> str:
    summary = _dict(bundle.get("summary", {}))
    rows: list[str] = []
    for case in _list_dicts(bundle.get("cases", [])):
        loop = _dict(case.get("stage179_live_remediation_loop", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(case.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(', '.join(str(x) for x in list(case.get('domains', []) or [])))}</td>"
            f"<td>{html.escape(str(loop.get('status', '')))}</td>"
            f"<td>{html.escape(str(loop.get('selected_action_type', '')))}</td>"
            f"<td>{html.escape(str(loop.get('canonical_stop_reason', '')))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage179 Live Remediation Loop</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage179 Live Remediation Loop Simulation</h1>"
        "<p>Simulation that feeds Stage178 remediation actions back into the agent FSM and event stream. It remains offline and executes no tools.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">cases<br><b>{summary.get('case_count', 0)}</b></div>"
        f"<div class=\"card\">blocked<br><b>{summary.get('blocked_case_count', 0)}</b></div>"
        f"<div class=\"card\">finalizable<br><b>{summary.get('finalizable_case_count', 0)}</b></div>"
        f"<div class=\"card\">next actions<br><b>{summary.get('next_action_count', 0)}</b></div>"
        "</div><table><thead><tr><th>Case</th><th>Domains</th><th>Status</th><th>Next Action</th><th>Stop</th></tr></thead>"
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


def run_live_remediation_simulation(
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
        "schema": STAGE179_LIVE_REMEDIATION_LOOP_SIMULATION_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "passed",
        "case_count": len(cases),
        "cases": cases,
        "summary": summary,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["blocked_case_count"] / max(1, len(cases)) < float(fail_under)),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return _dict(_public(bundle))
