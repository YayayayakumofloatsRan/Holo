from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Callable

from .agent_event_stream import build_agent_event_stream, render_agent_event_stream
from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import assert_no_private_reasoning, sanitize_public_metadata
from .market_research_agent_trajectory import run_market_research_dossier_agent_trajectory
from .market_research_dossier_registry import record_market_research_dossier
from .market_research_task_dossier import build_market_research_task_dossier
from .stage135_i_state_topology import build_stage135_i_state_topology
from .stage169_market_research_pack import default_market_research_pack_fixtures

STAGE205_MARKET_RESEARCH_TRAJECTORY_LIVE_SMOKE_SCHEMA = "holo.stage205.market_research_trajectory_live_smoke.v1"
STAGE205_MARKET_RESEARCH_TRAJECTORY_LIVE_SMOKE_RESULT_SCHEMA = "holo.stage205.market_research_trajectory_live_smoke_result.v1"
STAGE205_MARKET_RESEARCH_TRAJECTORY_SCORECARD_SCHEMA = "holo.stage205.market_research_trajectory_scorecard.v1"

DEFAULT_OUTPUT = Path("artifacts") / "stage205" / "stage205_trajectory_live_smoke.html"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _public(value: Any) -> Any:
    return sanitize_public_metadata(value)


def _fixture_by_id(fixture_id: str) -> dict[str, Any]:
    for fixture in default_market_research_pack_fixtures():
        if str(fixture.get("fixture_id", "") or "") == fixture_id:
            return dict(fixture)
    return dict(default_market_research_pack_fixtures()[0])


def _weak_dossier(question: str) -> dict[str, Any]:
    return build_market_research_task_dossier(
        question=question,
        stage197_market_research_report_assembly={
            "schema": "holo.stage197.market_research_report_assembly.v1",
            "status": "needs_report",
            "missing_requirements": ["financial_filing_source"],
        },
        stage198_market_research_finalization_gate={
            "schema": "holo.stage198.market_research_finalization_gate.v1",
            "status": "blocked",
            "final_visible_text_ready": False,
            "canonical_stop_reason": "evidence_exhausted",
        },
    )


def _seed_dossier(*, state_dir: str | Path, thread_key: str, project_key: str, question: str) -> dict[str, Any]:
    return record_market_research_dossier(
        state_dir=state_dir,
        thread_key=thread_key,
        project_key=project_key,
        dossier=_weak_dossier(question),
        source_metadata={"stage": "stage205", "fixture": "weak_market_research_dossier"},
    )


def _dry_search(query: str) -> dict[str, Any]:
    fixture = _fixture_by_id("apple-10k-ready")
    return {
        "query": query,
        "status": "ok",
        "provider": "stage205-sec-search",
        "results": [
            {
                "title": "Apple Form 10-K 2024",
                "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                "snippet": "Apple annual report on Form 10-K with audited financial statements.",
            }
        ],
        "source_urls": [
            "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
        ],
        "fixture_id": str(fixture.get("fixture_id", "")),
    }


def _dry_open_page(url: str) -> dict[str, Any]:
    fixture = _fixture_by_id("apple-10k-ready")
    return {
        "url": url,
        "status": "ok",
        "provider": "stage205-sec-page",
        "html": str(fixture.get("filing_text", "") or ""),
    }


def default_market_research_trajectory_live_smoke_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "stage205-apple-trajectory",
            "thread_key": "holo_cli:market-stage205",
            "project_key": "market:apple",
            "question": "Continue Apple AAPL 2024 10-K fundamental research.",
            "max_actions": 4,
            "expected_action_sequence": ["web_search", "market_research_pack", "market_research_report"],
            "expected_status": "passed",
        }
    ]


def _source_count(trajectory: dict[str, Any]) -> int:
    urls: set[str] = set()
    for row in _list_dicts(trajectory.get("web_observation_ledger", [])):
        for url in list(row.get("source_urls", []) or []):
            text = str(url or "").strip()
            if text:
                urls.add(text)
        for item in _list_dicts(row.get("results", [])):
            url = str(item.get("url", "") or "").strip()
            if url:
                urls.add(url)
    for row in _list_dicts(trajectory.get("market_research_report_ledger", [])):
        for url in list(row.get("source_urls", []) or []):
            text = str(url or "").strip()
            if text:
                urls.add(text)
    return len(urls)


def _web_failures(trajectory: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for row in _list_dicts(trajectory.get("web_observation_ledger", [])):
        status = str(row.get("status", "") or "")
        error = str(row.get("error", "") or "").strip()
        if status in {"error", "rejected_network_disabled", "empty"}:
            failures.append(error or status)
    return failures


def _final_summary(trajectory: dict[str, Any]) -> str:
    status = str(trajectory.get("status", "") or "")
    actions = [str(item) for item in list(trajectory.get("action_sequence", []) or []) if str(item)]
    failures = _web_failures(trajectory)
    if status == "ready":
        return _compact(
            f"Stage205 trajectory completed with actions={','.join(actions)} and sources={_source_count(trajectory)}.",
            360,
        )
    if any("network_disabled" in failure for failure in failures):
        return "web_search was attempted but rejected: network_disabled. No current web evidence was established."
    if failures:
        return _compact(
            f"web_search was attempted but failed: {failures[0]}. No current web evidence was established.",
            360,
        )
    return _compact(
        f"Market research trajectory stopped before completion; actions={','.join(actions) or 'none'}.",
        360,
    )


def _check(passed: bool, *, score: float, reason: str = "") -> dict[str, Any]:
    return {"passed": bool(passed), "score": round(max(0.0, min(1.0, float(score or 0.0))), 4), "reason": reason}


def build_market_research_trajectory_scorecard(result: dict[str, Any]) -> dict[str, Any]:
    trajectory = _dict(result.get("stage204_market_research_agent_trajectory", {}))
    event_stream = _dict(result.get("stage153_agent_event_stream", {}))
    topology = _dict(result.get("stage135_i_state_topology", {}))
    metrics = _dict(topology.get("metrics", {}))
    rendered = str(result.get("rendered_event_stream", "") or "")
    action_sequence = [str(item) for item in list(trajectory.get("action_sequence", []) or []) if str(item)]
    web_rows = _list_dicts(trajectory.get("web_observation_ledger", []))
    report_rows = _list_dicts(trajectory.get("market_research_report_ledger", []))
    source_count = _source_count(trajectory)
    failures = _web_failures(trajectory)
    ok, private_paths = assert_no_private_reasoning(result)
    final_summary = str(result.get("final_summary", "") or "")
    no_overclaim = bool(
        str(trajectory.get("status", "") or "") == "ready"
        or (
            "completed" not in final_summary.lower()
            and "sufficient" not in final_summary.lower()
            and "evidence_ready" not in final_summary.lower()
        )
    )
    checks = {
        "trajectory_present": _check(bool(trajectory), score=1.0 if trajectory else 0.0),
        "trajectory_ready": _check(str(trajectory.get("status", "") or "") == "ready", score=1.0 if trajectory.get("status") == "ready" else 0.0, reason="trajectory_not_complete"),
        "full_action_sequence": _check(
            action_sequence == ["web_search", "market_research_pack", "market_research_report"],
            score=1.0 if action_sequence == ["web_search", "market_research_pack", "market_research_report"] else 0.0,
            reason="trajectory_action_sequence_incomplete",
        ),
        "source_evidence_present": _check(source_count > 0 and bool(web_rows), score=1.0 if source_count > 0 else 0.0, reason="source_evidence_missing"),
        "report_ledger_present": _check(bool(report_rows), score=1.0 if report_rows else 0.0, reason="report_ledger_missing"),
        "event_trace_visible": _check(
            "[market_trajectory]" in rendered and int(event_stream.get("event_count", 0) or 0) > 0,
            score=1.0 if "[market_trajectory]" in rendered else 0.0,
            reason="trajectory_trace_missing",
        ),
        "topology_visible": _check(
            int(metrics.get("market_research_agent_trajectory_node_count", 0) or 0) >= 1,
            score=1.0 if int(metrics.get("market_research_agent_trajectory_node_count", 0) or 0) >= 1 else 0.0,
            reason="trajectory_topology_missing",
        ),
        "stop_reason_known": _check(
            str(trajectory.get("canonical_stop_reason", "") or "") not in {"", "unknown"},
            score=1.0 if trajectory.get("canonical_stop_reason") else 0.0,
            reason="stop_reason_missing",
        ),
        "no_success_overclaim": _check(no_overclaim, score=1.0 if no_overclaim else 0.0, reason="success_overclaim"),
        "privacy": _check(ok, score=1.0 if ok else 0.0, reason="private_reasoning:" + ",".join(private_paths[:3])),
        "persona_free": _check(
            not any(term in json.dumps(result, ensure_ascii=False).lower() for term in ("微信", "熟人", "打趣", "the subject", "陪你")),
            score=1.0,
            reason="persona_text_leak",
        ),
    }
    critical = ["trajectory_present", "event_trace_visible", "topology_visible", "stop_reason_known", "no_success_overclaim", "privacy", "persona_free"]
    if str(trajectory.get("status", "") or "") == "ready":
        critical.extend(["trajectory_ready", "full_action_sequence", "source_evidence_present", "report_ledger_present"])
    overall = round(sum(float(row["score"]) for row in checks.values()) / max(1, len(checks)), 4)
    return {
        "schema": STAGE205_MARKET_RESEARCH_TRAJECTORY_SCORECARD_SCHEMA,
        "status": "passed" if all(bool(checks[key]["passed"]) for key in critical) and overall >= 0.72 else "failed",
        "overall_score": overall,
        "critical_gates": critical,
        "checks": checks,
        "web_failure_count": len(failures),
    }


def evaluate_market_research_trajectory_live_smoke_fixture(
    fixture: dict[str, Any],
    *,
    state_dir: str | Path,
    dry_run: bool = True,
    network_enabled: bool | None = None,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    fallback_search_fns: list[tuple[str, Callable[[str], dict[str, Any]]]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source = dict(fixture or {})
    thread_key = str(source.get("thread_key", "") or "holo_cli:market-stage205")
    project_key = str(source.get("project_key", "") or "market:apple")
    question = str(source.get("question", "") or "Continue Apple AAPL 2024 10-K fundamental research.")
    enabled = bool(dry_run) if network_enabled is None else bool(network_enabled)
    search = _dry_search if dry_run and web_search_fn is None else web_search_fn
    open_page = _dry_open_page if dry_run and open_page_fn is None else open_page_fn

    seed_record = _seed_dossier(state_dir=state_dir, thread_key=thread_key, project_key=project_key, question=question)
    trajectory = run_market_research_dossier_agent_trajectory(
        state_dir=state_dir,
        thread_key=thread_key,
        project_key=project_key,
        question=question,
        network_enabled=enabled,
        web_search_fn=search,
        fallback_search_fns=fallback_search_fns,
        open_page_fn=open_page,
        max_actions=int(source.get("max_actions", 4) or 4),
    )
    payload = {
        "text": _final_summary(trajectory),
        "stage204_market_research_agent_trajectory": trajectory,
        "stage201_market_research_dossier_registry": trajectory.get("stage201_market_research_dossier_registry", {}),
        "stage195_market_research_continuation_loop": trajectory.get("stage195_market_research_continuation_loop", {}),
        "market_research_pack_ledger": trajectory.get("market_research_pack_ledger", []),
        "market_research_report_ledger": trajectory.get("market_research_report_ledger", []),
        "web_observation_ledger": trajectory.get("web_observation_ledger", []),
    }
    event_stream = build_agent_event_stream(payload, user_text=question, thread_key=thread_key, chat_name="HoloCLI", channel="holo_cli")
    rendered = render_agent_event_stream(event_stream)
    topology = build_stage135_i_state_topology(
        user_text=question,
        channel="holo_cli",
        thread_key=thread_key,
        stage204_market_research_agent_trajectory=trajectory,
        stage153_agent_event_stream=event_stream,
        stage195_market_research_continuation_loop=trajectory.get("stage195_market_research_continuation_loop", {}),
        market_research_pack_ledger=trajectory.get("market_research_pack_ledger", []),
        market_research_report_ledger=trajectory.get("market_research_report_ledger", []),
    )
    result: dict[str, Any] = {
        "schema": STAGE205_MARKET_RESEARCH_TRAJECTORY_LIVE_SMOKE_RESULT_SCHEMA,
        "fixture_id": str(source.get("fixture_id", "") or stable_digest(question, limit=10)),
        "query": _compact(question, 260),
        "dry_run": bool(dry_run),
        "network_enabled": enabled,
        "seed_record_id": str(seed_record.get("record_id", "") or ""),
        "stage204_market_research_agent_trajectory": trajectory,
        "stage153_agent_event_stream": event_stream,
        "rendered_event_stream": rendered,
        "stage135_i_state_topology": topology,
        "final_summary": _final_summary(trajectory),
        "failure_reasons": [],
        "created_at": utc_now(),
    }
    scorecard = build_market_research_trajectory_scorecard(result)
    failures: list[str] = []
    if str(trajectory.get("status", "") or "") != "ready":
        failures.append("trajectory_incomplete")
    for failure in _web_failures(trajectory):
        if failure and failure not in failures:
            failures.append(failure)
    for key, check in _dict(scorecard.get("checks", {})).items():
        if not bool(_dict(check).get("passed", False)):
            reason = str(_dict(check).get("reason", "") or key)
            if reason and reason not in failures:
                failures.append(reason)
    result["scorecard"] = scorecard
    result["status"] = "passed" if scorecard["status"] == "passed" and not failures else "failed"
    result["failure_reasons"] = failures
    return _dict(_public(result))


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for row in results if row.get("status") == "passed")
    failed = len(results) - passed
    scores = [float(_dict(row.get("scorecard", {})).get("overall_score", 0.0) or 0.0) for row in results]
    ready = sum(1 for row in results if _dict(row.get("stage204_market_research_agent_trajectory", {})).get("status") == "ready")
    return {
        "passed_count": passed,
        "failed_count": failed,
        "pass_rate": round(passed / max(1, len(results)), 4),
        "average_score": round(sum(scores) / max(1, len(scores)), 4),
        "ready_trajectory_rate": round(ready / max(1, len(results)), 4),
    }


def _html_report(bundle: dict[str, Any]) -> str:
    summary = _dict(bundle.get("summary", {}))
    rows: list[str] = []
    traces: list[str] = []
    for result in _list_dicts(bundle.get("results", [])):
        trajectory = _dict(result.get("stage204_market_research_agent_trajectory", {}))
        scorecard = _dict(result.get("scorecard", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(result.get('status', '')))}</td>"
            f"<td>{html.escape(str(trajectory.get('status', '')))}</td>"
            f"<td>{html.escape(', '.join(str(x) for x in list(trajectory.get('action_sequence', []) or [])))}</td>"
            f"<td>{html.escape(str(scorecard.get('overall_score', 0.0)))}</td>"
            f"<td>{html.escape(', '.join(str(x) for x in list(result.get('failure_reasons', []) or [])))}</td>"
            "</tr>"
        )
        traces.append(
            f"<h2>{html.escape(str(result.get('fixture_id', '')))}</h2>"
            f"<pre>{html.escape(str(result.get('rendered_event_stream', '') or ''))}</pre>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage205 Market Research Trajectory Live Smoke</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left;vertical-align:top}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}pre{background:#f7f9f8;padding:12px;white-space:pre-wrap}</style></head><body>"
        "<h1>Stage205 Market Research Trajectory Live Smoke</h1>"
        "<p>Validates persisted dossier resume through bounded market-research action trajectory, public event stream, and topology.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">status<br><b>{html.escape(str(bundle.get('status', 'unknown')))}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">avg score<br><b>{summary.get('average_score', 0.0)}</b></div>"
        f"<div class=\"card\">ready trajectories<br><b>{summary.get('ready_trajectory_rate', 0.0)}</b></div>"
        "</div><table><thead><tr><th>Fixture</th><th>Smoke</th><th>Trajectory</th><th>Actions</th><th>Score</th><th>Failures</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>{''.join(traces)}</body></html>"
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


def run_market_research_trajectory_live_smoke(
    *,
    output: str | Path | None = None,
    state_dir: str | Path | None = None,
    dry_run: bool = True,
    network_enabled: bool | None = None,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_market_research_trajectory_live_smoke_fixtures())
    state_root = Path(state_dir) if state_dir is not None else (Path(output).with_suffix("").parent / "stage205_state" if output is not None else Path("artifacts") / "stage205" / "stage205_state")
    results = [
        evaluate_market_research_trajectory_live_smoke_fixture(
            row,
            state_dir=state_root / str(row.get("fixture_id", stable_digest(str(index), limit=8))),
            dry_run=dry_run,
            network_enabled=network_enabled,
        )
        for index, row in enumerate(rows)
    ]
    summary = _summary(results)
    failed = [str(row.get("fixture_id", "") or "") for row in results if row.get("status") != "passed"]
    bundle: dict[str, Any] = {
        "schema": STAGE205_MARKET_RESEARCH_TRAJECTORY_LIVE_SMOKE_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "network_enabled": bool(dry_run) if network_enabled is None else bool(network_enabled),
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
            "live_network_available_when_enabled": not bool(dry_run),
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return _dict(_public(bundle))
