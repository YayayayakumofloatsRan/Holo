from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .agent_event_stream import build_agent_event_stream, render_agent_event_stream
from .agent_intent_frame import build_intent_frame
from .agent_loop_fsm import run_agent_loop_fsm
from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import build_public_stage152_report, sanitize_public_metadata
from .model_tool_arbitration import derive_arbitration_from_stage152
from .stage135_i_state_topology import build_stage135_i_state_topology
from .stage152_deepseek_tool_loop import build_deepseek_native_tool_payload, run_deepseek_native_tool_loop
from .stage169_market_research_pack import default_market_research_pack_fixtures
from .tool_action_space import build_tool_action_space

STAGE175_MARKET_RESEARCH_LIVE_SMOKE_SCHEMA = "holo.stage175.market_research_live_smoke.v1"
STAGE175_MARKET_RESEARCH_LIVE_SMOKE_RESULT_SCHEMA = "holo.stage175.market_research_live_smoke_result.v1"
STAGE175_MARKET_RESEARCH_SCORECARD_SCHEMA = "holo.stage175.codex_style_market_research_scorecard.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _stage175_public(value: Any) -> Any:
    clean = sanitize_public_metadata(value)
    if isinstance(clean, dict):
        return {key: _stage175_public(item) for key, item in clean.items() if str(key) != "reasoning_content_retained_count"}
    if isinstance(clean, list):
        return [_stage175_public(item) for item in clean]
    return clean


def _tool_call(name: str, arguments: dict[str, Any], *, call_id: str = "call_market_research_report") -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False, sort_keys=True)},
    }


def _response(content: str, *, tool_calls: list[dict[str, Any]] | None = None, reasoning_content: str = "") -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"finish_reason": "tool_calls" if tool_calls else "stop", "message": message}],
        "usage": {
            "prompt_tokens": 128,
            "completion_tokens": 32,
            "total_tokens": 160,
            "prompt_cache_hit_tokens": 64,
            "prompt_cache_miss_tokens": 64,
        },
    }


def default_market_research_live_smoke_fixtures() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fixture in default_market_research_pack_fixtures():
        fixture_id = str(fixture.get("fixture_id", "") or "")
        if fixture_id == "apple-10k-ready":
            rows.append(
                {
                    "fixture_id": "apple-10k-ready-live-smoke",
                    "query": str(fixture.get("query", "") or "Apple AAPL 2024 10-K financial analysis"),
                    "filing_text": str(fixture.get("filing_text", "") or ""),
                    "web_observation_ledger": _list_dicts(fixture.get("web_observation_ledger", [])),
                    "expected_report_status": "evidence_ready",
                    "expected_live_status": "passed",
                }
            )
        elif fixture_id == "third-party-source-insufficient":
            rows.append(
                {
                    "fixture_id": "third-party-insufficient-live-smoke",
                    "query": str(fixture.get("query", "") or "Apple 2024 10-K financial analysis"),
                    "filing_text": str(fixture.get("filing_text", "") or ""),
                    "web_observation_ledger": _list_dicts(fixture.get("web_observation_ledger", [])),
                    "expected_report_status": "evidence_insufficient",
                    "expected_live_status": "failed",
                }
            )
    return rows


def _run_stage152_report_tool(fixture: dict[str, Any]) -> dict[str, Any]:
    query = str(fixture.get("query", "") or "").strip()
    arguments = {
        "query": query,
        "filing_text": str(fixture.get("filing_text", "") or ""),
        "web_observation_ledger": _list_dicts(fixture.get("web_observation_ledger", [])),
    }
    initial = _response(
        "",
        reasoning_content="internal market reasoning: choose report tool from filing evidence",
        tool_calls=[_tool_call("market_research_report", arguments)],
    )
    result = run_deepseek_native_tool_loop(
        initial_decoded=initial,
        base_payload={
            "messages": [{"role": "user", "content": query}],
            **build_deepseek_native_tool_payload(tool_names=("market_research_report",)),
        },
        call_model=lambda payload: _response("Market research report generated from the recorded filing observations."),
        network_enabled=True,
        max_rounds=2,
    )
    return _dict(_stage175_public(build_public_stage152_report(result)))


def _build_fsm(stage152: dict[str, Any], *, query: str) -> dict[str, Any]:
    arbitration = derive_arbitration_from_stage152(stage152, user_text=query)
    if not arbitration.get("selected_action"):
        arbitration["selected_action"] = "market_research_report"
    required = list(arbitration.get("required_observations", []) or [])
    if "market_research_report_ledger" not in required:
        required.append("market_research_report_ledger")
    arbitration["required_observations"] = required
    intent = build_intent_frame(query, channel="holo_cli")
    return run_agent_loop_fsm(
        intent_frame=intent,
        model_arbitration=arbitration,
        market_research_report_ledger=stage152.get("market_research_report_ledger", []),
        final_text="Market research report generated from filing evidence.",
    )


def _render_observation_lines(stage152: dict[str, Any]) -> str:
    lines: list[str] = []
    for row in _list_dicts(stage152.get("market_research_report_ledger", []))[:3]:
        lines.append(
            "[observe] market_research_report "
            f"status={row.get('status', '') or '-'} observations=1 "
            f"sources={len(list(row.get('source_urls', []) or []))} citations={int(row.get('citation_count', 0) or 0)}"
        )
    return "\n".join(lines)


def _source_urls(report: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for citation in _list_dicts(report.get("citations", [])):
        url = str(citation.get("url", "") or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def _check(passed: bool, *, score: float, reason: str = "") -> dict[str, Any]:
    return {"passed": bool(passed), "score": round(max(0.0, min(1.0, float(score or 0.0))), 4), "reason": reason}


def build_market_research_live_smoke_scorecard(result: dict[str, Any]) -> dict[str, Any]:
    stage152 = _dict(result.get("stage152_deepseek_tool_loop", {}))
    report = _dict(result.get("stage173_market_research_report", {}))
    fsm = _dict(result.get("stage160r_agent_loop_fsm", {}))
    event_stream = _dict(result.get("stage153_agent_event_stream", {}))
    topology = _dict(result.get("stage135_i_state_topology", {}))
    metrics = _dict(topology.get("metrics", {}))
    urls = _source_urls(report)
    rendered = str(result.get("rendered_event_stream", "") or "")
    blob = json.dumps(result, ensure_ascii=False).lower()
    checks = {
        "model_decide_visible": _check("[model_decide] selected=market_research_report" in rendered, score=1.0 if "[model_decide]" in rendered else 0.0),
        "report_ledger_exists": _check(bool(_list_dicts(stage152.get("market_research_report_ledger", []))), score=1.0 if stage152.get("market_research_report_ledger") else 0.0),
        "report_ready": _check(str(report.get("status", "") or "") == "evidence_ready", score=1.0 if report.get("status") == "evidence_ready" else 0.0, reason="report_not_evidence_ready"),
        "primary_citations_present": _check(any(url.startswith("https://www.sec.gov/") for url in urls), score=1.0 if any(url.startswith("https://www.sec.gov/") for url in urls) else 0.0),
        "unsupported_claim_rate_low": _check(int(report.get("unsupported_claim_count", 0) or 0) == 0, score=1.0 if int(report.get("unsupported_claim_count", 0) or 0) == 0 else 0.0),
        "stop_reason_known": _check(str(fsm.get("canonical_stop_reason", "") or "") != "unknown", score=1.0 if fsm.get("canonical_stop_reason") else 0.0),
        "trace_visibility": _check(int(event_stream.get("event_count", 0) or 0) >= 5 and "[act]" in rendered, score=1.0 if "[act]" in rendered and "[stop]" in rendered else 0.0),
        "topology_visibility": _check(
            int(metrics.get("market_research_report_action_node_count", 0) or 0) >= 1
            and int(metrics.get("market_research_report_node_count", 0) or 0) >= 1,
            score=1.0 if int(metrics.get("market_research_report_action_node_count", 0) or 0) >= 1 else 0.0,
        ),
        "privacy": _check("reasoning_content" not in blob and "internal market reasoning" not in blob, score=1.0 if "reasoning_content" not in blob else 0.0),
        "persona_free": _check(not any(term in blob for term in ("微信", "打趣", "熟人", "the subject")), score=1.0),
    }
    critical = [
        "report_ledger_exists",
        "report_ready",
        "primary_citations_present",
        "unsupported_claim_rate_low",
        "stop_reason_known",
        "privacy",
        "persona_free",
    ]
    overall = round(sum(float(row["score"]) for row in checks.values()) / max(1, len(checks)), 4)
    return {
        "schema": STAGE175_MARKET_RESEARCH_SCORECARD_SCHEMA,
        "status": "passed" if overall >= 0.8 and all(bool(checks[key]["passed"]) for key in critical) else "failed",
        "overall_score": overall,
        "critical_gates": critical,
        "checks": checks,
    }


def evaluate_market_research_live_smoke_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    source = dict(fixture or {})
    query = str(source.get("query", "") or "")
    stage152 = _run_stage152_report_tool(source)
    report = _dict(stage152.get("stage173_market_research_report", {}))
    fsm = _build_fsm(stage152, query=query)
    payload = {
        "text": "Market research report generated from filing evidence.",
        "stage152_deepseek_tool_loop": stage152,
        "stage160r_agent_loop_fsm": fsm,
        "market_research_report_ledger": stage152.get("market_research_report_ledger", []),
        "stage173_market_research_report": report,
        "stage161_tool_action_space_count": len(build_tool_action_space()),
    }
    event_stream = build_agent_event_stream(payload, user_text=query, channel="holo_cli")
    rendered = render_agent_event_stream(event_stream)
    observation_lines = _render_observation_lines(stage152)
    if observation_lines:
        rendered = rendered.rstrip() + "\n" + observation_lines
    topology = build_stage135_i_state_topology(
        stage152_deepseek_tool_loop=stage152,
        stage160r_agent_loop_fsm=fsm,
        stage153_agent_event_stream=event_stream,
        stage173_market_research_report=report,
        market_research_report_ledger=stage152.get("market_research_report_ledger", []),
    )
    result: dict[str, Any] = {
        "schema": STAGE175_MARKET_RESEARCH_LIVE_SMOKE_RESULT_SCHEMA,
        "fixture_id": str(source.get("fixture_id", "") or stable_digest(query, limit=10)),
        "query": _compact(query, 260),
        "status": "pending",
        "expected_report_status": str(source.get("expected_report_status", "") or ""),
        "stage152_deepseek_tool_loop": stage152,
        "stage160r_agent_loop_fsm": fsm,
        "stage153_agent_event_stream": event_stream,
        "rendered_event_stream": rendered,
        "stage135_i_state_topology": topology,
        "stage173_market_research_report": report,
        "failure_reasons": [],
    }
    scorecard = build_market_research_live_smoke_scorecard(result)
    expected_report_status = str(source.get("expected_report_status", "") or "")
    failures: list[str] = []
    if expected_report_status and str(report.get("status", "") or "") != expected_report_status:
        failures.append("report_status_expectation_mismatch")
    for key, check in _dict(scorecard.get("checks", {})).items():
        if not bool(_dict(check).get("passed", False)):
            reason = str(_dict(check).get("reason", "") or key)
            if reason not in failures:
                failures.append(reason)
    result["scorecard"] = scorecard
    result["status"] = "passed" if scorecard["status"] == "passed" and not failures else "failed"
    result["failure_reasons"] = failures
    return _dict(_stage175_public(result))


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for row in results if row.get("status") == "passed")
    failed = len(results) - passed
    scores = [float(_dict(row.get("scorecard", {})).get("overall_score", 0.0) or 0.0) for row in results]
    ready = sum(1 for row in results if _dict(row.get("stage173_market_research_report", {})).get("status") == "evidence_ready")
    return {
        "passed_count": passed,
        "failed_count": failed,
        "pass_rate": round(passed / max(1, len(results)), 4),
        "average_score": round(sum(scores) / max(1, len(scores)), 4),
        "ready_report_rate": round(ready / max(1, len(results)), 4),
    }


def _html_report(bundle: dict[str, Any]) -> str:
    summary = _dict(bundle.get("summary", {}))
    rows: list[str] = []
    for result in _list_dicts(bundle.get("results", [])):
        scorecard = _dict(result.get("scorecard", {}))
        report = _dict(result.get("stage173_market_research_report", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(result.get('status', '')))}</td>"
            f"<td>{html.escape(str(report.get('status', '')))}</td>"
            f"<td>{html.escape(str(scorecard.get('overall_score', 0.0)))}</td>"
            f"<td>{html.escape(', '.join(str(x) for x in list(result.get('failure_reasons', []) or [])))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage175 Market Research Live Smoke</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage175 Market Research Live Smoke</h1>"
        "<p>Provider-free live-smoke through the model-proposed tool call, host report action, FSM, event stream, and topology.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">status<br><b>{html.escape(str(bundle.get('status', 'unknown')))}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">avg score<br><b>{summary.get('average_score', 0.0)}</b></div>"
        f"<div class=\"card\">ready reports<br><b>{summary.get('ready_report_rate', 0.0)}</b></div>"
        "</div><table><thead><tr><th>Fixture</th><th>Live Smoke</th><th>Report</th><th>Score</th><th>Failures</th></tr></thead>"
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
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in _list_dicts(bundle.get("results", []))) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_market_research_live_smoke(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_market_research_live_smoke_fixtures())
    results = [evaluate_market_research_live_smoke_fixture(row) for row in rows]
    summary = _summary(results)
    failed = [str(row.get("fixture_id", "") or "") for row in results if row.get("status") != "passed"]
    bundle: dict[str, Any] = {
        "schema": STAGE175_MARKET_RESEARCH_LIVE_SMOKE_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "failed" if failed else "passed",
        "result_count": len(results),
        "results": results,
        "summary": summary,
        "failed_fixture_ids": failed,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["pass_rate"] < float(fail_under)),
        "authority_boundary": {
            "provider_model_calls": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
            "live_network_required_for_tests": False,
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return _dict(_stage175_public(bundle))
