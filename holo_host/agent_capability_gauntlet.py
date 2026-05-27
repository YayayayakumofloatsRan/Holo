from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from .agent_event_stream import build_agent_event_stream, render_agent_event_stream
from .common import compact_text, stable_digest, utc_now
from .engineering_action_fabric import (
    engineering_ledger_to_tool_observations,
    evaluate_engineering_claim_grounding,
    normalize_engineering_action_ledger,
)
from .kernel_metadata_sanitizer import PRIVATE_KEYS, assert_no_private_reasoning
from .live_remediation_continuation import run_remediation_continuation_simulation
from .stage169_market_research_pack import build_market_research_pack, default_market_research_pack_fixtures
from .stage174_market_research_report_action import execute_market_research_report_action

AGENT_CAPABILITY_GAUNTLET_SCHEMA = "holo.stage183.agent_capability_gauntlet.v1"
AGENT_CAPABILITY_CASE_SCHEMA = "holo.stage183.agent_capability_case.v1"
AGENT_CAPABILITY_SCORECARD_SCHEMA = "holo.stage183.agent_capability_scorecard.v1"

FORBIDDEN_PERSONA_TERMS = (
    "微信",
    "熟人",
    "贴着说话",
    "打趣",
    "狡黠",
    "馋",
    "the subject",
    "陪你",
    "长辈",
    "说教",
)

_CURRENT_WEB_RE = re.compile(r"\b(search|searched|latest|current|today|official|web|source|citation|citations)\b|搜索|联网|官网|来源|引用", re.I)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: Any, limit: int = 320) -> str:
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


def _manual_event_stream(*, goal: str, selected: str, final: str, extra_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    events = [
        {"event": "goal", "summary": _compact(goal, 220)},
        {"event": "model_decide", "selected_action": selected, "required_observations": []},
    ]
    events.extend(list(extra_events or []))
    events.extend(
        [
            {"event": "grounding", "status": "grounded", "missing": []},
            {"event": "stop", "reason": "final_answer_ready", "source": "stage183_fixture", "raw_reason": "final_answer_ready"},
            {"event": "final", "summary": _compact(final, 420)},
        ]
    )
    return {
        "schema": "holo.stage153.agent_event_stream.v1",
        "status": "recorded",
        "event_count": len(events),
        "events": events,
    }


def _engineering_fixture() -> dict[str, Any]:
    ledger = normalize_engineering_action_ledger(
        [
            {
                "action_type": "workspace_search",
                "status": "ok",
                "stdout_summary": "reply_api remediation continuation wiring found",
                "files_read": ["holo_host/reply_api.py"],
            },
            {
                "action_type": "file_read",
                "status": "ok",
                "stdout_summary": "read live remediation continuation module",
                "files_read": ["holo_host/live_remediation_continuation.py"],
            },
            {
                "action_type": "apply_patch",
                "status": "ok",
                "stdout_summary": "patched bounded continuation wiring",
                "files_changed": ["holo_host/reply_api.py"],
            },
            {
                "action_type": "test_run",
                "status": "ok",
                "stdout_summary": "8 passed",
                "commands_run": ["python -m pytest tests/test_stage182_remediation_continuation.py -q"],
                "tests_run": ["python -m pytest tests/test_stage182_remediation_continuation.py -q"],
            },
            {
                "action_type": "git_diff",
                "status": "ok",
                "stdout_summary": "diff reviewed",
            },
        ]
    )
    text = "I searched the workspace, read the file, patched it, tests passed, and checked the diff."
    stream = _manual_event_stream(
        goal="repair the live agent loop",
        selected="engineering_task",
        final=text,
        extra_events=[
            {"event": "eng:search", "status": "ok", "files_read": ["holo_host/reply_api.py"]},
            {"event": "eng:read", "status": "ok", "files_read": ["holo_host/live_remediation_continuation.py"]},
            {"event": "eng:patch", "status": "ok", "files_changed": ["holo_host/reply_api.py"]},
            {"event": "eng:test", "status": "ok", "commands_run": ["python -m pytest tests/test_stage182_remediation_continuation.py -q"]},
        ],
    )
    return {
        "case_id": "engineering-grounded",
        "category_id": "engineering_execution",
        "expected_outcome": "success",
        "visible_text": text,
        "metadata": {
            "engineering_action_ledger": ledger,
            "tool_observation_ledger": engineering_ledger_to_tool_observations(ledger),
            "engineering_claim_grounding": evaluate_engineering_claim_grounding(text, ledger),
            "stage153_agent_event_stream": stream,
            "canonical_stop_reason": "final_answer_ready",
        },
    }


def _market_research_fixture() -> dict[str, Any]:
    fixture = default_market_research_pack_fixtures()[0]
    pack = build_market_research_pack(
        query=str(fixture.get("query", "") or ""),
        web_observation_ledger=fixture.get("web_observation_ledger", []),
        filing_text=str(fixture.get("filing_text", "") or ""),
    )
    action = execute_market_research_report_action(
        {"query": "Analyze Apple using its 2024 10-K.", "market_research_pack": pack},
        network_enabled=False,
    )
    text = "I generated a filing-grounded market research report with citations and no investment recommendation."
    stream = _manual_event_stream(
        goal="produce filing grounded market research",
        selected="market_research_report",
        final=text,
        extra_events=[
            {"event": "tool_call", "action_type": "market_research_report", "status": "executed"},
            {"event": "observation", "action_type": "market_research_report", "status": action.get("status", ""), "source_count": 1},
        ],
    )
    return {
        "case_id": "market-research-grounded",
        "category_id": "market_research_report",
        "expected_outcome": "success",
        "visible_text": text,
        "metadata": {
            "stage169_market_research_pack": action.get("stage169_market_research_pack", pack),
            "stage173_market_research_report": action.get("stage173_market_research_report", {}),
            "market_research_report_ledger": action.get("market_research_report_ledger", []),
            "tool_observation_ledger": action.get("tool_observation_ledger", []),
            "stage153_agent_event_stream": stream,
            "canonical_stop_reason": "final_answer_ready",
        },
    }


def _remediation_fixture() -> dict[str, Any]:
    bundle = run_remediation_continuation_simulation(dry_run=True)
    selected = next(
        (
            row
            for row in _list_dicts(bundle.get("cases", []))
            if _dict(row.get("stage182_remediation_continuation", {})).get("status") == "completed"
        ),
        _list_dicts(bundle.get("cases", []))[0],
    )
    report = _dict(selected.get("stage182_remediation_continuation", {}))
    text = "I continued the remediation loop until the remaining action plan was resolved or bounded by stop reason."
    metadata = {
        "stage182_remediation_continuation": report,
        "stage180_live_remediation_execution": report.get("stage180_live_remediation_execution", {}),
        "stage153_agent_event_stream": selected.get("stage153_agent_event_stream", {}),
        "canonical_stop_reason": report.get("canonical_stop_reason", "final_answer_ready"),
    }
    return {
        "case_id": "remediation-continuation-grounded",
        "category_id": "remediation_continuation",
        "expected_outcome": "success",
        "visible_text": text,
        "metadata": metadata,
    }


def _adversarial_fixture() -> dict[str, Any]:
    return {
        "case_id": "unsupported-engineering-overclaim",
        "category_id": "adversarial_unsupported_claim",
        "expected_outcome": "detect_failure",
        "expected_failure_flags": ["unsupported_engineering_claim"],
        "visible_text": "I read the file, patched it, and tests passed.",
        "metadata": {
            "engineering_action_ledger": [],
            "tool_observation_ledger": [],
            "stage153_agent_event_stream": _manual_event_stream(
                goal="adversarial unsupported engineering claim",
                selected="answer_direct",
                final="I read the file, patched it, and tests passed.",
            ),
            "canonical_stop_reason": "final_answer_ready",
        },
    }


def default_agent_capability_gauntlet_fixtures() -> list[dict[str, Any]]:
    return [
        _engineering_fixture(),
        _market_research_fixture(),
        _remediation_fixture(),
        _adversarial_fixture(),
    ]


def _event_labels(metadata: dict[str, Any]) -> set[str]:
    stream = _dict(metadata.get("stage153_agent_event_stream", {}))
    return {str(row.get("event", "") or "") for row in _list_dicts(stream.get("events", []))}


def _event_score(metadata: dict[str, Any]) -> tuple[float, list[str]]:
    labels = _event_labels(metadata)
    missing: list[str] = []
    if "goal" not in labels:
        missing.append("event_goal_missing")
    if not ({"model_decide", "decide", "candidate"} & labels):
        missing.append("event_decision_missing")
    if not ({"tool_call", "observation", "eng:search", "eng:read", "eng:patch", "eng:test", "remediation_exec", "remediation_continue"} & labels):
        missing.append("event_action_or_observation_missing")
    if "stop" not in labels:
        missing.append("event_stop_missing")
    if "final" not in labels:
        missing.append("event_final_missing")
    return round((5 - len(missing)) / 5, 4), missing


def _market_score(metadata: dict[str, Any]) -> tuple[float, list[str]]:
    ledgers = _list_dicts(metadata.get("market_research_report_ledger", []))
    report = _dict(metadata.get("stage173_market_research_report", {}))
    missing: list[str] = []
    if not ledgers:
        missing.append("missing_market_report_ledger")
    if str(report.get("status", "") or "") != "evidence_ready":
        missing.append("market_report_not_ready")
    if int(report.get("citation_count", 0) or 0) <= 0:
        missing.append("market_report_citations_missing")
    return (1.0 if not missing else 0.0), missing


def _remediation_score(metadata: dict[str, Any]) -> tuple[float, list[str]]:
    report = _dict(metadata.get("stage182_remediation_continuation", {}))
    missing: list[str] = []
    if str(report.get("schema", "") or "") != "holo.stage182.remediation_continuation.v1":
        missing.append("missing_remediation_continuation")
    if int(report.get("round_count", 0) or 0) <= 0:
        missing.append("remediation_round_missing")
    if str(report.get("canonical_stop_reason", "") or "") in {"", "unknown"}:
        missing.append("remediation_stop_unknown")
    labels = _event_labels(metadata)
    if "remediation_continue" not in labels:
        missing.append("remediation_continue_event_missing")
    return (1.0 if not missing else max(0.0, 1.0 - 0.25 * len(missing))), missing


def _search_score(text: str, metadata: dict[str, Any]) -> tuple[float, list[str]]:
    if not _CURRENT_WEB_RE.search(text):
        return 1.0, []
    web_rows = _list_dicts(metadata.get("web_observation_ledger", []))
    market_rows = _list_dicts(metadata.get("market_research_report_ledger", []))
    engineering_rows = _list_dicts(metadata.get("engineering_action_ledger", []))
    report = _dict(metadata.get("stage173_market_research_report", {}))
    has_source = any(row.get("status") == "ok" and row.get("source_urls") for row in web_rows)
    has_market_source = any(row.get("status") == "ok" and row.get("source_urls") for row in market_rows)
    has_workspace_search = any(row.get("status") == "ok" and row.get("action_type") == "workspace_search" for row in engineering_rows)
    has_report_citations = int(report.get("citation_count", 0) or 0) > 0
    if has_source or has_market_source or has_workspace_search or has_report_citations:
        return 1.0, []
    return 0.0, ["current_or_source_claim_without_source_ledger"]


def _persona_flags(text: str, metadata: dict[str, Any]) -> list[str]:
    blob = (text + " " + json.dumps(metadata, ensure_ascii=False)).lower()
    return [term for term in FORBIDDEN_PERSONA_TERMS if term.lower() in blob]


def evaluate_agent_capability_case(case: dict[str, Any], *, threshold: float = 0.8) -> dict[str, Any]:
    source = _dict(case)
    metadata = _dict(source.get("metadata", {}))
    visible_text = str(source.get("visible_text", "") or "")
    failure_flags: list[str] = []

    private_ok, private_paths = assert_no_private_reasoning({"visible_text": visible_text, "metadata": metadata})
    if not private_ok:
        failure_flags.append("hidden_reasoning_leak")
    persona = _persona_flags(visible_text, metadata)
    if persona:
        failure_flags.append("persona_leak")

    event_score, event_failures = _event_score(metadata)
    failure_flags.extend(event_failures)

    engineering_report = evaluate_engineering_claim_grounding(visible_text, metadata.get("engineering_action_ledger", []))
    engineering_score = 1.0
    if engineering_report.get("status") == "unverified_engineering_claim":
        engineering_score = 0.0
        failure_flags.append("unsupported_engineering_claim")

    market_score = 1.0
    if source.get("category_id") == "market_research_report":
        market_score, market_failures = _market_score(metadata)
        failure_flags.extend(market_failures)

    remediation_score = 1.0
    if source.get("category_id") == "remediation_continuation":
        remediation_score, remediation_failures = _remediation_score(metadata)
        failure_flags.extend(remediation_failures)

    search_score, search_failures = _search_score(visible_text, metadata)
    failure_flags.extend(search_failures)

    stop_reason = str(metadata.get("canonical_stop_reason", "") or "")
    if not stop_reason:
        stream = _dict(metadata.get("stage153_agent_event_stream", {}))
        for event in _list_dicts(stream.get("events", [])):
            if event.get("event") == "stop":
                stop_reason = str(event.get("reason", "") or "")
                break
    stop_score = 0.0 if stop_reason in {"", "unknown"} else 1.0
    if stop_score == 0.0:
        failure_flags.append("unknown_stop_reason")

    privacy_score = 1.0 if private_ok else 0.0
    persona_score = 1.0 if not persona else 0.0
    evidence_score = min(engineering_score, market_score, remediation_score, search_score)
    overall = round(
        evidence_score * 0.34
        + event_score * 0.22
        + stop_score * 0.12
        + privacy_score * 0.12
        + persona_score * 0.1
        + remediation_score * 0.1,
        4,
    )
    raw_passed = overall >= threshold and not failure_flags
    expected = str(source.get("expected_outcome", "success") or "success")
    expected_flags = set(str(item) for item in list(source.get("expected_failure_flags", []) or []))
    detected_expected_failure = bool(expected_flags and expected_flags.issubset(set(failure_flags)))
    case_passed = raw_passed if expected != "detect_failure" else detected_expected_failure and not private_paths and "persona_leak" not in failure_flags
    stream = _dict(metadata.get("stage153_agent_event_stream", {}))
    rendered = render_agent_event_stream(stream) if stream else ""
    return _dict(
        _public(
            {
                "schema": AGENT_CAPABILITY_CASE_SCHEMA,
                "case_id": str(source.get("case_id", "") or "case:" + stable_digest(source, limit=10)),
                "category_id": str(source.get("category_id", "") or "unknown"),
                "expected_outcome": expected,
                "status": "passed" if case_passed else "failed",
                "raw_case_status": "passed" if raw_passed else "failed",
                "overall_score": overall,
                "threshold": float(threshold),
                "failure_flags": sorted(dict.fromkeys(failure_flags)),
                "private_reasoning_paths": private_paths,
                "metrics": {
                    "evidence_integrity_score": round(evidence_score, 4),
                    "action_trace_score": event_score,
                    "engineering_grounding_score": engineering_score,
                    "market_research_score": market_score,
                    "remediation_closure_score": remediation_score,
                    "search_grounding_score": search_score,
                    "stop_reason_score": stop_score,
                    "privacy_score": privacy_score,
                    "persona_free_score": persona_score,
                },
                "rendered_event_stream": rendered,
                "metadata_summary": {
                    "engineering_action_count": len(_list_dicts(metadata.get("engineering_action_ledger", []))),
                    "market_report_ledger_count": len(_list_dicts(metadata.get("market_research_report_ledger", []))),
                    "has_stage182_continuation": bool(metadata.get("stage182_remediation_continuation")),
                    "stop_reason": stop_reason,
                },
            }
        )
    )


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for case in cases if case.get("status") == "passed")
    score = sum(float(case.get("overall_score", 0.0) or 0.0) for case in cases) / max(1, len(cases))
    failures: dict[str, int] = {}
    for case in cases:
        for flag in list(case.get("failure_flags", []) or []):
            failures[str(flag)] = failures.get(str(flag), 0) + 1
    return {
        "schema": AGENT_CAPABILITY_SCORECARD_SCHEMA,
        "case_count": len(cases),
        "passed_case_count": passed,
        "failed_case_count": len(cases) - passed,
        "pass_rate": round(passed / max(1, len(cases)), 4),
        "overall_score": round(score, 4),
        "failure_flag_counts": dict(sorted(failures.items())),
    }


def _html_report(report: dict[str, Any]) -> str:
    summary = _dict(report.get("summary", {}))
    rows = []
    for case in _list_dicts(report.get("cases", [])):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(case.get('case_id', '')))}</td>"
            f"<td>{html.escape(str(case.get('category_id', '')))}</td>"
            f"<td>{html.escape(str(case.get('status', '')))}</td>"
            f"<td>{html.escape(str(case.get('overall_score', '')))}</td>"
            f"<td>{html.escape(', '.join(str(x) for x in list(case.get('failure_flags', []) or [])))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage183 Agent Capability Gauntlet</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage183 Agent Capability Gauntlet</h1>"
        "<p>Codex-style end-to-end capability pressure test for engineering, market research, and remediation loops.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">cases<br><b>{summary.get('case_count', 0)}</b></div>"
        f"<div class=\"card\">passed<br><b>{summary.get('passed_case_count', 0)}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0)}</b></div>"
        f"<div class=\"card\">score<br><b>{summary.get('overall_score', 0)}</b></div>"
        "</div><table><thead><tr><th>Case</th><th>Category</th><th>Status</th><th>Score</th><th>Flags</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )


def _write_artifacts(report: dict[str, Any], output: str | Path) -> dict[str, str]:
    html_path = Path(output)
    if html_path.suffix.lower() != ".html":
        html_path = html_path.with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = html_path.with_suffix(".json")
    jsonl_path = html_path.with_suffix(".jsonl")
    html_path.write_text(_html_report(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    jsonl_path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in _list_dicts(report.get("cases", []))) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_agent_capability_gauntlet(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
    threshold: float = 0.8,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_agent_capability_gauntlet_fixtures())
    cases = [evaluate_agent_capability_case(row, threshold=threshold) for row in rows]
    summary = _summary(cases)
    failed_threshold = bool(fail_under is not None and float(summary["pass_rate"]) < float(fail_under))
    report = _dict(
        _public(
            {
                "schema": AGENT_CAPABILITY_GAUNTLET_SCHEMA,
                "generated_at": utc_now(),
                "dry_run": bool(dry_run),
                "status": "failed" if summary["failed_case_count"] or failed_threshold else "passed",
                "cases": cases,
                "summary": summary,
                "fail_under": fail_under,
                "fail_under_triggered": failed_threshold,
                "authority_boundary": {
                    "provider_model_calls": False,
                    "live_network_required_for_tests": False,
                    "memory_writes": False,
                    "wechat_start": False,
                    "transport_authority_widened": False,
                },
            }
        )
    )
    if output is not None:
        report["artifacts"] = _write_artifacts(report, output)
    return report
