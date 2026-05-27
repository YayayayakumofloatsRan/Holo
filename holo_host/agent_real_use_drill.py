from __future__ import annotations

import html
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .agent_event_stream import build_agent_event_stream, render_agent_event_stream
from .common import compact_text, stable_digest, utc_now
from .engineering_action_fabric import evaluate_engineering_claim_grounding, normalize_engineering_action_ledger
from .engineering_workspace_tools import (
    apply_patch as apply_workspace_patch,
    file_read,
    git_diff,
    git_status,
    test_run,
    workspace_search,
)
from .kernel_metadata_sanitizer import PRIVATE_KEYS, assert_no_private_reasoning, sanitize_public_metadata
from .stage151_tool_decision_loop import (
    build_grounded_web_observation_answer,
    build_stage151_live_trace,
    build_time_observation,
    build_tool_decision_report,
    evaluate_tool_decision_grounding,
    execute_tool_decision,
    format_stage151_live_trace,
    repair_tool_decision_grounding,
    web_observations_to_tool_ledger,
)
from .stage169_market_research_pack import build_market_research_pack, default_market_research_pack_fixtures
from .stage174_market_research_report_action import execute_market_research_report_action

STAGE184_REAL_USE_DRILL_SCHEMA = "holo.stage184.real_use_agent_drill.v1"
STAGE184_REAL_USE_CASE_SCHEMA = "holo.stage184.real_use_case.v1"
STAGE184_REAL_USE_SCORECARD_SCHEMA = "holo.stage184.real_use_scorecard.v1"


def _compact(value: Any, limit: int = 320) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _public(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _public(item)
            for key, item in value.items()
            if str(key).strip().lower() not in PRIVATE_KEYS
        }
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _case_status(failure_flags: list[str], *, expected_failure: bool = False) -> str:
    if expected_failure:
        return "passed" if failure_flags else "failed"
    return "failed" if failure_flags else "passed"


def _score_from_flags(failure_flags: list[str]) -> float:
    return round(max(0.0, 1.0 - 0.18 * len(failure_flags)), 4)


def _write_artifacts(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    public_report = _public(report)
    target.with_suffix(".json").write_text(json.dumps(public_report, ensure_ascii=False, indent=2), encoding="utf-8")
    with target.with_suffix(".jsonl").open("w", encoding="utf-8") as handle:
        for case in _list_dicts(public_report.get("cases", [])):
            handle.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
    summary = _dict(public_report.get("summary", {}))
    rows = []
    for case in _list_dicts(public_report.get("cases", [])):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(case.get('case_id', '')))}</td>"
            f"<td>{html.escape(str(case.get('category_id', '')))}</td>"
            f"<td>{html.escape(str(case.get('status', '')))}</td>"
            f"<td>{html.escape(str(case.get('canonical_stop_reason', '')))}</td>"
            f"<td>{html.escape(', '.join(str(x) for x in list(case.get('failure_flags', []) or [])))}</td>"
            "</tr>"
        )
    body = f"""<!doctype html>
<meta charset="utf-8">
<title>Stage184 Real Use Agent Drill</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; line-height: 1.45; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; vertical-align: top; }}
th {{ background: #f4f4f4; }}
pre {{ white-space: pre-wrap; background: #f7f7f7; padding: 10px; }}
</style>
<h1>Stage184 Real Use Agent Drill</h1>
<p>Status: <b>{html.escape(str(public_report.get('status', '')))}</b></p>
<pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>
<table>
<thead><tr><th>Case</th><th>Category</th><th>Status</th><th>Stop</th><th>Failure Flags</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""
    target.write_text(body, encoding="utf-8")


def _init_engineering_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "calc.py").write_text(
        "def add(left, right):\n"
        "    # BUG_STAGE184: this should add.\n"
        "    return left - right\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\n"
        "def test_add_returns_sum():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def execute_engineering_real_use_drill() -> dict[str, Any]:
    """Run a real local engineering loop in a temporary repo."""

    with tempfile.TemporaryDirectory(prefix="holo_stage184_engineering_") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_engineering_repo(repo)
        patch = """diff --git a/src/calc.py b/src/calc.py
--- a/src/calc.py
+++ b/src/calc.py
@@ -1,3 +1,3 @@
 def add(left, right):
     # BUG_STAGE184: this should add.
-    return left - right
+    return left + right
"""
        command = "python -m pytest tests/test_calc.py -q"
        ledger = normalize_engineering_action_ledger(
            [
                workspace_search(repo, query="BUG_STAGE184", glob="*.py"),
                file_read(repo, "src/calc.py", start_line=1, end_line=3),
                apply_workspace_patch(repo, patch),
                test_run(repo, command),
                git_status(repo),
                git_diff(repo, "src/calc.py"),
            ]
        )
    visible = "I searched the workspace, read src/calc.py, patched it, tests passed, and checked the diff."
    grounding = evaluate_engineering_claim_grounding(visible, ledger)
    stream = build_agent_event_stream(
        {
            "text": visible,
            "engineering_action_ledger": ledger,
            "engineering_claim_grounding": grounding,
            "canonical_stop_reason": "final_answer_ready",
        },
        user_text="repair the Stage184 fixture bug and verify it",
        thread_key="holo_cli:stage184",
        chat_name="HoloCLI",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    actions = {row["action_type"]: row["status"] for row in ledger}
    required_actions = ("workspace_search", "file_read", "apply_patch", "test_run", "git_diff")
    failure_flags: list[str] = []
    for action_type in required_actions:
        if actions.get(action_type) != "ok":
            failure_flags.append(f"{action_type}_not_ok")
    if str(grounding.get("status", "") or "") != "grounded":
        failure_flags.append("engineering_claim_not_grounded")
    if "[eng:test] status=ok" not in rendered:
        failure_flags.append("engineering_trace_missing_test")
    return sanitize_public_metadata(
        {
            "schema": STAGE184_REAL_USE_CASE_SCHEMA,
            "case_id": "engineering-real-use",
            "category_id": "engineering_execution_real",
            "status": _case_status(failure_flags),
            "score": _score_from_flags(failure_flags),
            "visible_text": visible,
            "engineering_action_ledger": ledger,
            "engineering_claim_grounding": grounding,
            "stage153_agent_event_stream": stream,
            "rendered_event_stream": rendered,
            "canonical_stop_reason": "final_answer_ready" if not failure_flags else "tool_failure_report",
            "failure_flags": failure_flags,
            "observed_at": utc_now(),
        }
    )


def _default_mock_search(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "status": "ok",
        "provider": "stage184_mock_search",
        "results": [
            {
                "title": "OpenAI Codex CLI",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "Official Codex CLI documentation for a terminal coding agent.",
            }
        ],
    }


def _default_mock_open_page(url: str) -> dict[str, Any]:
    return {
        "url": url,
        "status": "ok",
        "provider": "stage184_mock_open_page",
        "results": [
            {
                "title": "Codex CLI",
                "url": url,
                "snippet": "Codex CLI is an OpenAI coding agent that can read code, edit files, run commands, and show auditable progress.",
            }
        ],
    }


def execute_search_real_use_drill(
    *,
    query: str = "official Codex CLI documentation",
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    network_enabled: bool = True,
) -> dict[str, Any]:
    """Run the Stage151 search decision/execution/grounding chain."""

    user_text = f"search {query} and cite sources"
    time_observation = build_time_observation()
    decision = build_tool_decision_report(user_text, time_observation=time_observation)
    observations = execute_tool_decision(
        decision,
        network_enabled=network_enabled,
        web_search_fn=web_search_fn or _default_mock_search,
        open_page_fn=open_page_fn or _default_mock_open_page,
    )
    ok_observations = [row for row in observations if str(row.get("status", "") or "") == "ok" and row.get("source_urls")]
    if ok_observations:
        visible = build_grounded_web_observation_answer(
            user_text=user_text,
            web_observation_ledger=observations,
            time_observation=time_observation,
        ) or "I searched the web and found verifiable sources."
    else:
        visible = repair_tool_decision_grounding(
            "I searched the web and found current official sources.",
            evaluate_tool_decision_grounding(
                "I searched the web and found current official sources.",
                web_observation_ledger=observations,
                time_observation=time_observation,
            ),
            channel="holo_cli",
        )
    grounding = evaluate_tool_decision_grounding(
        visible,
        web_observation_ledger=observations,
        time_observation=time_observation,
    )
    trace = build_stage151_live_trace(
        user_text=user_text,
        tool_decision=decision,
        web_observation_ledger=observations,
        grounding=grounding,
        final_text=visible,
    )
    rendered = format_stage151_live_trace({"stage151_live_trace": trace})
    rejected = any(str(row.get("status", "") or "") == "rejected_network_disabled" for row in observations)
    failure_flags: list[str] = []
    if network_enabled and not ok_observations:
        failure_flags.append("web_observation_missing")
    if network_enabled and str(grounding.get("status", "") or "") != "grounded":
        failure_flags.append("web_claim_not_grounded")
    if "[tool_call] web_search" not in rendered:
        failure_flags.append("search_trace_missing_tool_call")
    if rejected and "cannot treat this as current web evidence" not in visible:
        failure_flags.append("network_boundary_not_visible")
    stop_reason = "boundary_or_permission" if rejected else "final_answer_ready" if not failure_flags else "tool_failure_report"
    return sanitize_public_metadata(
        {
            "schema": STAGE184_REAL_USE_CASE_SCHEMA,
            "case_id": "search-real-use" if network_enabled else "search-network-disabled-boundary",
            "category_id": "search_grounding_real",
            "status": _case_status(failure_flags),
            "score": _score_from_flags(failure_flags),
            "visible_text": visible,
            "stage151_tool_decision": decision,
            "web_observation_ledger": observations,
            "tool_observation_ledger": web_observations_to_tool_ledger(observations),
            "time_observation": time_observation,
            "tool_decision_grounding": grounding,
            "stage151_live_trace": trace,
            "rendered_event_stream": rendered,
            "canonical_stop_reason": stop_reason,
            "failure_flags": failure_flags,
            "observed_at": utc_now(),
        }
    )


def execute_market_research_real_use_drill() -> dict[str, Any]:
    fixture = default_market_research_pack_fixtures()[0]
    pack = build_market_research_pack(
        query=str(fixture.get("query", "") or ""),
        web_observation_ledger=fixture.get("web_observation_ledger", []),
        filing_text=str(fixture.get("filing_text", "") or ""),
    )
    action = execute_market_research_report_action(
        {
            "query": "Produce a filing-grounded market research report for Apple.",
            "market_research_pack": pack,
        },
        network_enabled=False,
    )
    report = _dict(action.get("stage173_market_research_report", {}))
    ledger = _list_dicts(action.get("market_research_report_ledger", []))
    visible = "I produced a filing-grounded market research report with citations and an evidence boundary."
    failure_flags: list[str] = []
    if str(action.get("status", "") or "") != "ok":
        failure_flags.append("market_report_action_not_ok")
    if not ledger:
        failure_flags.append("market_report_ledger_missing")
    if int(report.get("citation_count", 0) or 0) < 1:
        failure_flags.append("market_report_citations_missing")
    if str(report.get("status", "") or "") != "evidence_ready":
        failure_flags.append("market_report_not_evidence_ready")
    return sanitize_public_metadata(
        {
            "schema": STAGE184_REAL_USE_CASE_SCHEMA,
            "case_id": "market-research-real-use",
            "category_id": "market_research_real",
            "status": _case_status(failure_flags),
            "score": _score_from_flags(failure_flags),
            "visible_text": visible,
            "stage169_market_research_pack": _dict(action.get("stage169_market_research_pack", {})),
            "stage173_market_research_report": report,
            "market_research_report_ledger": ledger,
            "tool_observation_ledger": _list_dicts(action.get("tool_observation_ledger", [])),
            "canonical_stop_reason": "final_answer_ready" if not failure_flags else "evidence_exhausted",
            "failure_flags": failure_flags,
            "observed_at": utc_now(),
        }
    )


def execute_claim_only_baseline_drill() -> dict[str, Any]:
    visible = "I read the file, patched it, tests passed, searched the web, and produced a market report."
    engineering_grounding = evaluate_engineering_claim_grounding(visible, [])
    web_grounding = evaluate_tool_decision_grounding(visible, web_observation_ledger=[], time_observation=None)
    failure_flags: list[str] = []
    if bool(engineering_grounding.get("repair_required", False)):
        failure_flags.append("unsupported_engineering_claim")
    if bool(web_grounding.get("repair_required", False)):
        failure_flags.append("unsupported_web_claim")
    failure_flags.append("market_report_ledger_missing")
    return sanitize_public_metadata(
        {
            "schema": STAGE184_REAL_USE_CASE_SCHEMA,
            "case_id": "claim-only-baseline",
            "category_id": "adversarial_claim_only",
            "expected_outcome": "detect_failure",
            "status": _case_status(failure_flags, expected_failure=True),
            "raw_case_status": "failed" if failure_flags else "passed",
            "score": 0.12 if failure_flags else 1.0,
            "visible_text": visible,
            "engineering_claim_grounding": engineering_grounding,
            "tool_decision_grounding": web_grounding,
            "canonical_stop_reason": "tool_failure_report",
            "failure_flags": failure_flags,
            "observed_at": utc_now(),
        }
    )


def default_real_use_drill_cases() -> list[dict[str, Any]]:
    return [
        execute_engineering_real_use_drill(),
        execute_search_real_use_drill(network_enabled=True),
        execute_search_real_use_drill(network_enabled=False),
        execute_market_research_real_use_drill(),
        execute_claim_only_baseline_drill(),
    ]


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(cases)
    passed = sum(1 for case in cases if str(case.get("status", "") or "") == "passed")
    baseline = next((case for case in cases if str(case.get("case_id", "")) == "claim-only-baseline"), {})
    full_cases = [case for case in cases if str(case.get("case_id", "")) != "claim-only-baseline"]
    full_loop_score = round(sum(float(case.get("score", 0.0) or 0.0) for case in full_cases) / max(1, len(full_cases)), 4)
    baseline_score = round(float(baseline.get("score", 0.0) or 0.0), 4)
    flags: list[str] = []
    for case in cases:
        flags.extend(str(flag) for flag in list(case.get("failure_flags", []) or []) if str(flag))
    return {
        "schema": STAGE184_REAL_USE_SCORECARD_SCHEMA,
        "case_count": total,
        "passed_case_count": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "full_loop_score": full_loop_score,
        "claim_only_baseline_score": baseline_score,
        "score_delta_vs_claim_only": round(full_loop_score - baseline_score, 4),
        "baseline_failure_flags": list(baseline.get("failure_flags", []) or []),
        "failure_flag_counts": {flag: flags.count(flag) for flag in sorted(set(flags))},
        "private_reasoning_free": assert_no_private_reasoning(cases)[0],
    }


def run_agent_real_use_drill(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fail_under: float | None = None,
) -> dict[str, Any]:
    cases = default_real_use_drill_cases()
    summary = _summary(cases)
    status = "passed" if summary["passed_case_count"] == summary["case_count"] and summary["full_loop_score"] > summary["claim_only_baseline_score"] else "failed"
    report = sanitize_public_metadata(
        {
            "schema": STAGE184_REAL_USE_DRILL_SCHEMA,
            "status": status,
            "dry_run": bool(dry_run),
            "generated_at": utc_now(),
            "summary": summary,
            "cases": cases,
            "fail_under": fail_under,
            "fail_under_triggered": bool(fail_under is not None and float(summary.get("full_loop_score", 0.0) or 0.0) < float(fail_under)),
            "authority_boundary": {
                "provider_model_calls": False,
                "memory_writes": False,
                "wechat_start": False,
                "transport_authority_widened": False,
                "live_network_required_for_tests": False,
                "workspace_actions_confined_to_temporary_repo": True,
            },
        }
    )
    if output:
        _write_artifacts(report, output)
    return report
