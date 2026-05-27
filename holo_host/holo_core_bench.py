from __future__ import annotations

import html
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from .agent_event_stream import build_agent_event_stream
from .context_compiler import compile_context_memory
from .common import stable_digest, utc_now
from .kernel_metadata_sanitizer import assert_no_private_reasoning, sanitize_public_metadata
from .project_state_graph import ProjectStateGraph
from .safe_command_policy import parse_allowed_command
from .stage151_tool_decision_loop import build_network_health_report, build_tool_decision_report, execute_tool_decision

HOLO_CORE_BENCH_SCHEMA = "holo.stage157.core_bench.v1"
LIVE_SMOKE_CATEGORY_IDS = ("kernel_hardening_live_smoke",)

BENCHMARK_CATEGORY_IDS = (
    "recent_recall",
    "directive_adherence",
    "one_turn_vs_durable_instruction",
    "project_state_recall",
    "task_continuation",
    "web_time_grounding",
    "tool_claim_grounding",
    "engineering_patch_test_claims",
    "context_compaction_integrity",
    "cli_trace_visibility",
    "stop_reason_correctness",
)

METRIC_KEYS = (
    "pass_rate",
    "unsupported_claim_rate",
    "directive_violation_rate",
    "memory_honesty_score",
    "tool_grounding_score",
    "project_continuity_score",
    "context_waste_score",
    "cache_hit_ratio",
    "latency_estimate",
)

_WEB_CLAIM_RE = re.compile(r"\b(searched|search|latest|current|today|official|web|source|sources)\b|官网|最新|今天|联网|搜索", re.I)
_MEMORY_CLAIM_RE = re.compile(r"\b(I remember|you told me before|we discussed|from memory)\b|我记得|你之前说过|我们聊过", re.I)
_TOOL_CLAIM_RE = re.compile(r"\b(tool|called|executed|ran|read file|opened file|checked workspace)\b|工具|执行|读取", re.I)
_ENGINEERING_CLAIM_RE = re.compile(r"\b(patched|modified|edited|tests passed|test passed|pytest passed|diff clean)\b|已修改|测试通过|补丁", re.I)
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_HIDDEN_REASONING_RE = re.compile(r"reasoning_content|hidden chain|private reasoning|raw reasoning", re.I)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        items: list[str] = []
        for key in ("title", "summary", "text", "line", "status", "stop_reason", "current_user_request_exact"):
            if str(value.get(key, "") or "").strip():
                items.append(str(value.get(key)))
        for child in value.values():
            if isinstance(child, (dict, list, tuple)):
                items.extend(_texts(child))
        return items
    if isinstance(value, (list, tuple)):
        items = []
        for child in value:
            items.extend(_texts(child))
        return items
    return [str(value)]


def _blob(value: Any) -> str:
    return " ".join(_texts(value)).lower()


def _has_web_or_time(metadata: dict[str, Any]) -> bool:
    web_rows = _list_dicts(metadata.get("web_observation_ledger", []))
    time_row = _dict(metadata.get("time_observation", {}))
    return any(str(row.get("status", "") or "") == "ok" for row in web_rows) or bool(time_row.get("observed_at") or time_row.get("local_time") or time_row.get("utc_time"))


def _has_memory_source(metadata: dict[str, Any]) -> bool:
    rows = _list_dicts(metadata.get("memory_observation_ledger", []))
    return any(str(row.get("status", "") or "") in {"grounded", "weak"} for row in rows)


def _has_tool_source(metadata: dict[str, Any]) -> bool:
    rows = _list_dicts(metadata.get("tool_observation_ledger", []))
    return any(str(row.get("status", "") or "") in {"ok", "grounded", "executed"} for row in rows)


def _has_engineering_source(metadata: dict[str, Any]) -> bool:
    rows = _list_dicts(metadata.get("engineering_action_ledger", []))
    return any(str(row.get("status", "") or "") == "ok" for row in rows)


def _violates_directive(fixture: dict[str, Any]) -> bool:
    directives = " ".join(str(item or "") for item in list(fixture.get("directives", []) or [])).lower()
    text = str(fixture.get("visible_text", "") or "")
    if "no emoji" in directives or "avoid emoji" in directives or "不要 emoji" in directives:
        if _EMOJI_RE.search(text):
            return True
    if "short" in directives and len(text) > int(fixture.get("max_visible_chars", 400) or 400):
        return True
    return False


def _project_continuity_score(fixture: dict[str, Any], metadata: dict[str, Any]) -> float:
    expected = _dict(fixture.get("expected_project_state", {}))
    if not expected:
        return 1.0
    project_blob = _blob(metadata.get("project_state_graph", {}))
    expected_terms = [str(item).lower() for item in _texts(expected) if str(item).strip()]
    if not expected_terms:
        return 1.0
    matched = sum(1 for term in expected_terms if term in project_blob)
    return round(matched / len(expected_terms), 4)


def _context_integrity_score(fixture: dict[str, Any], metadata: dict[str, Any]) -> float:
    compiler = _dict(metadata.get("stage156_context_compiler", {}))
    if not compiler:
        return 0.0 if fixture.get("category_id") == "context_compaction_integrity" else 1.0
    current = str(compiler.get("current_user_request_exact", "") or "")
    compact = _dict(compiler.get("background_compact", {}))
    directive_block = str(compiler.get("directive_block", "") or "")
    score = 0.0
    if not fixture.get("input") or current == str(fixture.get("input", "") or ""):
        score += 0.35
    if "do not use emoji" in directive_block.lower() or not fixture.get("requires_directive"):
        score += 0.25
    if compact.get("user_visible") is False:
        score += 0.2
    if int(compiler.get("estimated_prompt_tokens", 0) or 0) > 0:
        score += 0.2
    return round(min(1.0, score), 4)


def _cli_trace_score(metadata: dict[str, Any]) -> float:
    stream = _dict(metadata.get("stage153_agent_event_stream", {}))
    if not stream:
        return 0.0
    rendered = json.dumps(stream, ensure_ascii=False)
    events = _list_dicts(stream.get("events", []))
    labels = {str(row.get("event", "") or "") for row in events}
    required = {"goal", "candidate", "grounding", "final"}
    if _HIDDEN_REASONING_RE.search(rendered):
        return 0.0
    return round(len(required & labels) / len(required), 4)


def _stop_reason_score(metadata: dict[str, Any]) -> float:
    budget = _dict(metadata.get("stage143_packet_budget", {}))
    if not budget:
        return 0.0
    stop_reason = str(budget.get("stop_reason", "") or "")
    packet_count = int(budget.get("packet_count", 0) or 0)
    sent_count = int(budget.get("sent_count", 0) or 0)
    if stop_reason and packet_count >= sent_count >= 0:
        return 1.0
    return 0.0


def evaluate_holo_core_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    category_id = str(fixture.get("category_id", "") or "unknown")
    visible_text = str(fixture.get("visible_text", "") or "")
    metadata = _dict(fixture.get("metadata", {}))
    unsupported_reasons: list[str] = []

    if _WEB_CLAIM_RE.search(visible_text) and not _has_web_or_time(metadata):
        unsupported_reasons.append("web_time_claim_without_observation")
    if _MEMORY_CLAIM_RE.search(visible_text) and not _has_memory_source(metadata):
        unsupported_reasons.append("memory_claim_without_observation")
    if _TOOL_CLAIM_RE.search(visible_text) and not _has_tool_source(metadata):
        unsupported_reasons.append("tool_claim_without_observation")
    if _ENGINEERING_CLAIM_RE.search(visible_text) and not _has_engineering_source(metadata):
        unsupported_reasons.append("engineering_claim_without_ledger")

    directive_violation = _violates_directive(fixture)
    project_score = _project_continuity_score(fixture, metadata)
    context_score = _context_integrity_score(fixture, metadata)
    cli_score = _cli_trace_score(metadata) if category_id == "cli_trace_visibility" else 1.0
    stop_score = _stop_reason_score(metadata) if category_id == "stop_reason_correctness" else 1.0

    waste = float(_dict(metadata.get("stage144_context_economy", {})).get("context_waste_score", 0.0) or 0.0)
    compiler = _dict(metadata.get("stage156_context_compiler", {}))
    cache_ratio = float(compiler.get("cache_hit_ratio", metadata.get("cache_hit_ratio", 0.0)) or 0.0)
    timing = _dict(metadata.get("timing_ms", {}))
    latency = float(timing.get("total_ms", timing.get("processor_ms", fixture.get("latency_estimate", 0))) or 0.0)

    memory_score = 0.0 if "memory_claim_without_observation" in unsupported_reasons else 1.0
    tool_score = 0.0 if any(reason.endswith("_without_observation") or reason.endswith("_without_ledger") for reason in unsupported_reasons if reason.startswith(("tool", "engineering"))) else 1.0
    unsupported = 1.0 if unsupported_reasons else 0.0
    pass_score = min(
        1.0 - unsupported,
        0.0 if directive_violation else 1.0,
        project_score,
        context_score if category_id == "context_compaction_integrity" else 1.0,
        cli_score,
        stop_score,
    )
    passed = pass_score >= 0.8
    metrics = {
        "pass_rate": 1.0 if passed else 0.0,
        "unsupported_claim_rate": unsupported,
        "directive_violation_rate": 1.0 if directive_violation else 0.0,
        "memory_honesty_score": memory_score,
        "tool_grounding_score": tool_score,
        "project_continuity_score": project_score,
        "context_waste_score": round(max(0.0, min(1.0, waste)), 4),
        "cache_hit_ratio": round(max(0.0, min(1.0, cache_ratio)), 4),
        "latency_estimate": latency,
    }
    return {
        "fixture_id": str(fixture.get("fixture_id", "") or stable_digest(category_id, visible_text, limit=10)),
        "category_id": category_id,
        "status": "passed" if passed else "failed",
        "score": round(pass_score, 4),
        "metrics": metrics,
        "unsupported_reasons": unsupported_reasons,
        "directive_violation": directive_violation,
        "dry_run": True,
    }


def _compiler_fixture(input_text: str) -> dict[str, Any]:
    return {
        "schema": "holo.stage156.context_compiler.v1",
        "current_user_request_exact": input_text,
        "directive_block": "Directive Block\n- do not use emoji",
        "background_compact": {"user_visible": False, "open_loop_summary": "continue benchmark"},
        "estimated_prompt_tokens": 1200,
        "stable_prefix_tokens": 420,
        "dynamic_suffix_tokens": 780,
        "cache_hit_ratio": 0.72,
        "truncated_sections": [],
    }


def default_holo_core_bench_fixtures() -> list[dict[str, Any]]:
    now = "2026-05-27T00:00:00Z"
    trace_events = [{"event": name, "summary": name} for name in ("goal", "candidate", "tool_call", "observation", "grounding", "final")]
    return [
        {
            "fixture_id": "recent-recall-pass",
            "category_id": "recent_recall",
            "input": "What did I just ask?",
            "visible_text": "You just asked me to keep Stage157 benchmark work on track.",
            "metadata": {"recent_dialogue_window": {"lines": ["keep Stage157 benchmark work on track"]}},
        },
        {
            "fixture_id": "directive-pass",
            "category_id": "directive_adherence",
            "input": "Avoid emoji.",
            "visible_text": "Understood. I will avoid emoji.",
            "directives": ["no emoji"],
            "metadata": {"stage149_user_directives": {"hard_directive_count": 1}},
        },
        {
            "fixture_id": "durable-directive-pass",
            "category_id": "one_turn_vs_durable_instruction",
            "input": "Keep the durable no-emoji instruction.",
            "visible_text": "The durable no-emoji instruction remains active.",
            "directives": ["no emoji"],
            "metadata": {"stage149_user_directives": {"hard_directive_count": 1}},
        },
        {
            "fixture_id": "project-state-pass",
            "category_id": "project_state_recall",
            "input": "What remains open?",
            "visible_text": "The next action is to run Stage157 tests.",
            "expected_project_state": {"next_actions": ["Run Stage157 tests"]},
            "metadata": {"project_state_graph": {"next_actions": [{"title": "Run Stage157 tests"}], "open_questions": []}},
        },
        {
            "fixture_id": "task-continuation-pass",
            "category_id": "task_continuation",
            "input": "Continue the bench work.",
            "visible_text": "I will continue from the active Stage157 task.",
            "metadata": {"project_state_graph": {"active_tasks": [{"title": "Stage157 HoloCoreBench"}]}},
        },
        {
            "fixture_id": "web-time-pass",
            "category_id": "web_time_grounding",
            "input": "Check the current official docs.",
            "visible_text": "The official source is grounded by the recorded web observation.",
            "metadata": {
                "web_observation_ledger": [{"status": "ok", "source_urls": ["https://example.com/docs"]}],
                "time_observation": {"observed_at": now, "utc_time": now},
            },
        },
        {
            "fixture_id": "tool-grounding-pass",
            "category_id": "tool_claim_grounding",
            "input": "Use the tool evidence.",
            "visible_text": "The tool observation is available and grounded.",
            "metadata": {"tool_observation_ledger": [{"status": "ok", "summary": "workspace search completed"}]},
        },
        {
            "fixture_id": "engineering-pass",
            "category_id": "engineering_patch_test_claims",
            "input": "Patch and test.",
            "visible_text": "The patch was applied and tests passed.",
            "metadata": {
                "engineering_action_ledger": [
                    {"action_type": "apply_patch", "status": "ok", "files_changed": ["holo_host/holo_core_bench.py"]},
                    {"action_type": "test_run", "status": "ok", "tests_run": ["pytest tests/test_stage157_holo_core_bench.py"]},
                ]
            },
        },
        {
            "fixture_id": "context-compact-pass",
            "category_id": "context_compaction_integrity",
            "input": "Compile this exact request.",
            "visible_text": "The working context is ready.",
            "requires_directive": True,
            "metadata": {"stage156_context_compiler": _compiler_fixture("Compile this exact request.")},
        },
        {
            "fixture_id": "cli-trace-pass",
            "category_id": "cli_trace_visibility",
            "input": "Show trace.",
            "visible_text": "Trace is visible.",
            "metadata": {"stage153_agent_event_stream": {"events": trace_events}},
        },
        {
            "fixture_id": "stop-reason-pass",
            "category_id": "stop_reason_correctness",
            "input": "Why stop?",
            "visible_text": "The packet stopped because the continuation was low novelty.",
            "metadata": {"stage143_packet_budget": {"packet_count": 2, "sent_count": 1, "skipped_count": 1, "stop_reason": "stage142_duplicate_suppressed"}},
        },
    ]


def live_smoke_holo_core_bench_fixtures() -> list[dict[str, Any]]:
    """Build local live-smoke rows over actual kernel surfaces without providers/network."""

    request = "Stage159 live-smoke exact request."
    event_stream = build_agent_event_stream(
        {
            "text": "Ready.",
            "stage152_deepseek_tool_loop": {
                "messages": [{"role": "assistant", "reasoning_content": "secret"}],
                "stop_reason": "tool_call_budget_exceeded",
            },
        },
        user_text=request,
        thread_key="holo_cli:stage159-live-smoke",
        chat_name="HoloCLI",
        channel="holo_cli",
    )
    context_report = compile_context_memory(
        {
            "working_context_packet": {
                "user_goal": {"current_user_request_exact": request},
                "directive_state": {"hard_directives": ["do not use emoji"]},
            }
        },
        current_user_request=request,
    )
    decision = build_tool_decision_report("search latest Holo docs")
    web_rejections = execute_tool_decision(decision, network_enabled=False)
    network_health = build_network_health_report(
        network_enabled=False,
        provider="host",
        last_web_status=str(web_rejections[0].get("status", "") if web_rejections else ""),
        last_error=str(web_rejections[0].get("error", "") if web_rejections else ""),
    )
    allowed_argv, allowed_reason = parse_allowed_command("python -m pytest tests/test_stage158_agent_kernel.py -q", repo_root=Path.cwd())
    rejected_argv, rejected_reason = parse_allowed_command("python -m pip install requests", repo_root=Path.cwd())
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = ProjectStateGraph(Path(tmpdir) / "project_state.sqlite3")
        try:
            graph.upsert_node("Holo", "Project", "Holo")
            graph.upsert_node("Holo", "NextAction", "Keep Stage159 hardening local", status="open")
            project_state = graph.get_project_state("Holo")
        finally:
            graph.close()
    sanitized = sanitize_public_metadata(
        {
            "messages": [{"role": "assistant", "reasoning_content": "secret"}],
            "visible": "ok",
        }
    )
    no_private, private_paths = assert_no_private_reasoning(sanitized)
    return [
        {
            "fixture_id": "stage159-live-smoke",
            "category_id": "kernel_hardening_live_smoke",
            "input": request,
            "visible_text": "The kernel hardening live-smoke used local observations only.",
            "metadata": {
                "stage153_agent_event_stream": event_stream,
                "stage156_context_compiler": context_report,
                "web_observation_ledger": web_rejections,
                "network_health": network_health,
                "safe_command_policy": {
                    "allowed_ok": bool(allowed_argv and not allowed_reason),
                    "rejected_ok": not rejected_argv and rejected_reason == "command_not_allowlisted",
                },
                "project_state_graph": project_state,
                "kernel_metadata_sanitizer": {"no_private": no_private, "private_paths": private_paths},
            },
        }
    ]


def _mean(rows: list[float]) -> float:
    return round(sum(rows) / max(1, len(rows)), 4)


def _category_report(category_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {
        key: _mean([float(row["metrics"].get(key, 0.0) or 0.0) for row in rows])
        for key in METRIC_KEYS
    }
    passed_count = sum(1 for row in rows if row["status"] == "passed")
    metrics["pass_rate"] = round(passed_count / max(1, len(rows)), 4)
    return {
        "category_id": category_id,
        "status": "passed" if passed_count == len(rows) else "failed",
        "fixture_count": len(rows),
        "passed_count": passed_count,
        "failed_count": len(rows) - passed_count,
        "metrics": metrics,
        "fixtures": rows,
    }


def _html_report(report: dict[str, Any]) -> str:
    category_rows = []
    for item in report.get("categories", []):
        metrics = _dict(item.get("metrics", {}))
        category_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('category_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{metrics.get('pass_rate', 0.0)}</td>"
            f"<td>{metrics.get('unsupported_claim_rate', 0.0)}</td>"
            f"<td>{metrics.get('directive_violation_rate', 0.0)}</td>"
            f"<td>{metrics.get('cache_hit_ratio', 0.0)}</td>"
            "</tr>"
        )
    summary = _dict(report.get("summary", {}))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage157 Holo Core Bench</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#18211f}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage157 Holo Core Bench</h1>"
        "<p>Deterministic dry-run reliability benchmark. No provider calls, tool execution, memory writes, or transport starts.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">status<br><b>{html.escape(str(report.get('status', 'unknown')))}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">unsupported claim rate<br><b>{summary.get('unsupported_claim_rate', 0.0)}</b></div>"
        f"<div class=\"card\">cache hit ratio<br><b>{summary.get('cache_hit_ratio', 0.0)}</b></div>"
        "</div><table><thead><tr><th>Category</th><th>Status</th><th>Pass</th><th>Unsupported</th><th>Directive</th><th>Cache</th></tr></thead>"
        f"<tbody>{''.join(category_rows)}</tbody></table></body></html>"
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
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in report.get("categories", [])) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_holo_core_bench(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    mode: str = "dry-run",
    fixtures: list[dict[str, Any]] | None = None,
    dependency_overrides: dict[str, bool] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    del dependency_overrides
    current_mode = str(mode or ("dry-run" if dry_run else "dry-run")).strip() or "dry-run"
    if current_mode not in {"dry-run", "live-smoke"}:
        current_mode = "dry-run"
    fixture_rows = list(
        fixtures
        if fixtures is not None
        else live_smoke_holo_core_bench_fixtures()
        if current_mode == "live-smoke"
        else default_holo_core_bench_fixtures()
    )
    evaluations = [evaluate_holo_core_fixture(row) for row in fixture_rows]
    category_ids = LIVE_SMOKE_CATEGORY_IDS if current_mode == "live-smoke" else BENCHMARK_CATEGORY_IDS
    grouped: dict[str, list[dict[str, Any]]] = {category_id: [] for category_id in category_ids}
    for evaluation in evaluations:
        grouped.setdefault(evaluation["category_id"], []).append(evaluation)
    categories = [_category_report(category_id, grouped.get(category_id) or []) for category_id in category_ids]
    for category in categories:
        if category["fixture_count"] == 0:
            category["status"] = "failed"
            category["metrics"] = {key: 0.0 for key in METRIC_KEYS}

    summary_sources = evaluations or [fixture for category in categories for fixture in list(category.get("fixtures", []) or [])]
    summary = {
        key: _mean([float(item["metrics"].get(key, 0.0) or 0.0) for item in summary_sources])
        for key in METRIC_KEYS
    }
    passed_count = sum(1 for item in categories if item["status"] == "passed")
    summary["pass_rate"] = round(
        sum(1 for item in summary_sources if item.get("status") == "passed") / max(1, len(summary_sources)),
        4,
    )
    failed_categories = [item["category_id"] for item in categories if item["status"] != "passed"]
    report = {
        "schema": HOLO_CORE_BENCH_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "mode": current_mode,
        "status": "failed" if failed_categories else "passed",
        "categories": categories,
        "categories_by_id": {item["category_id"]: item for item in categories},
        "summary": {
            **summary,
            "category_count": len(categories),
            "passed_count": passed_count,
            "failed_count": len(failed_categories),
        },
        "failed_categories": failed_categories,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["pass_rate"] < float(fail_under)),
        "authority_boundary": {
            "provider_calls": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    if output is not None:
        report["artifacts"] = _write_artifacts(report, output)
    return report


def render_holo_core_bench(report: dict[str, Any]) -> str:
    summary = _dict(report.get("summary", {}))
    lines = [
        "Stage157 Holo Core Bench",
        f"status={report.get('status', 'unknown')} pass_rate={summary.get('pass_rate', 0.0)}",
        f"unsupported_claim_rate={summary.get('unsupported_claim_rate', 0.0)} directive_violation_rate={summary.get('directive_violation_rate', 0.0)}",
    ]
    for item in report.get("categories", []) if isinstance(report.get("categories"), list) else []:
        if not isinstance(item, dict):
            continue
        metrics = _dict(item.get("metrics", {}))
        lines.append(f"- {item.get('category_id')}: {item.get('status')} pass={metrics.get('pass_rate', 0.0)} unsupported={metrics.get('unsupported_claim_rate', 0.0)}")
    return "\n".join(lines)
