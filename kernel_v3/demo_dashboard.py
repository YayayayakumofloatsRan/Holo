from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


Json = dict[str, Any]

DEFAULT_RUN_PREFIX = "run_metric_disambiguation_live14_20260613"
DEMO_RUNS = (
    {
        "label": "Live14 metric disambiguation",
        "run_prefix": "run_metric_disambiguation_live14_20260613",
        "thread_prefix": "metric-disambiguation-live14-20260613",
        "item_id": "",
        "difficulty": "Medium-Hard",
        "question": "Live shard covering net revenues, operating revenues, sales-to-customers, and total-revenue line-item ambiguity.",
    },
    {
        "label": "Goldman net revenues verifier pass",
        "run_prefix": "run_metric_disambiguation_live14_20260613",
        "thread_prefix": "metric-disambiguation-live14-20260613",
        "item_id": "FE_009",
        "difficulty": "Medium-Hard",
        "question": "Goldman Sachs FY2024 net revenues, a historical failure now used to show exact metric phrase disambiguation.",
    },
    {
        "label": "FinanceBench Activision fixed asset turnover",
        "run_prefix": "run_demo_financebench_activision_fat_live_20260613",
        "thread_prefix": "demo-financebench-activision-fat",
        "item_id": "financebench_id_02987",
        "difficulty": "Medium-High",
        "question": "Compute Activision Blizzard FY2019 fixed asset turnover from the 2019 10-K source URL.",
    },
    {
        "label": "Activision strong trace live10",
        "run_prefix": "run_financebench_doc_live10_capability_parallel_v2",
        "thread_prefix": "",
        "item_id": "financebench_id_02987",
        "difficulty": "Medium-High",
        "question": "Same Activision task with 15 calculator calls, 738 finance facts, and verifier passed.",
    },
    {
        "label": "FinanceBench live10 capability parallel",
        "run_prefix": "run_financebench_doc_live10_capability_parallel_v2",
        "thread_prefix": "",
        "item_id": "",
        "difficulty": "Medium-High",
        "question": "Live 10-item FinanceBench capability batch; includes the Activision fixed asset turnover pass.",
    },
    {
        "label": "FinanceBench live10 doclink capability",
        "run_prefix": "run_financebench_doc_live10_capability_doclink_v2",
        "thread_prefix": "",
        "item_id": "financebench_id_02987",
        "difficulty": "Medium-High",
        "question": "Live 10-item FinanceBench document-link batch; includes another Activision fixed asset turnover pass.",
    },
    {
        "label": "FAB v2 HD vs LOW DIO search stress",
        "run_prefix": "run_demo_fabv2_hd_low_dio_flash_workbenchfollow_20260613",
        "thread_prefix": "demo-fabv2-hd-low-dio-workbenchfollow",
        "item_id": "fabv2-hd-low-dio",
        "difficulty": "High",
        "question": "Multi-issuer DIO task used to debug workbench follow-up retrieval and LOW COGS search.",
    },
    {
        "label": "FAB v2 HD vs LOW DIO Pro",
        "run_prefix": "run_demo_fabv2_hd_low_dio_pro_high_20260613",
        "thread_prefix": "demo-fabv2-hd-low-dio-high",
        "item_id": "fabv2-hd-low-dio",
        "difficulty": "High",
        "question": "Same FAB v2 DIO task with DeepSeek Pro high reasoning.",
    },
    {
        "label": "FAB v2 HD vs LOW DIO Pro Max",
        "run_prefix": "run_demo_fabv2_hd_low_dio_pro_max_20260613",
        "thread_prefix": "demo-fabv2-hd-low-dio-pro",
        "item_id": "fabv2-hd-low-dio",
        "difficulty": "High",
        "question": "Same FAB v2 DIO task with DeepSeek Pro max reasoning.",
    },
    {
        "label": "FAB v2 historical DIO baseline",
        "run_prefix": "run_fabv2_dev10_capability_parallel10_judgefix",
        "thread_prefix": "",
        "item_id": "fabv2-hd-low-dio",
        "difficulty": "High",
        "question": "Historical HD/LOW DIO run with retrieval, facts, calculator traces, and citations.",
    },
    {
        "label": "FinanceBench 3M capital intensity",
        "run_prefix": "run_financebench_doc_live10_after_source_equivalence",
        "thread_prefix": "",
        "item_id": "financebench_id_00499",
        "difficulty": "Medium-High",
        "question": "3M capital-intensive assessment with filing evidence and calculation.",
    },
)
BASELINE_RUNS = (
    ("Global FE live10 dev", "run_global_finagent_limit10_live_20260613.summary.json"),
    ("Global FE live10 test", "run_global_finagent_test10_live_20260613.summary.json"),
    ("Global FE holdout20 stress", "run_global_finagent_holdout20_live_20260613.summary.json"),
    ("Failure regression metric+NR", "run_failure_regression_metric_nr_live_20260613.summary.json"),
    ("Failure regression round2", "run_failure_regression_round2_live_20260613.summary.json"),
    ("Historical FE live10 best", "run_limit10_parallel_v1_rescored.summary.json"),
    ("FinanceBench live10 best", "run_financebench_doc_live10_after_source_equivalence.summary.json"),
    ("FinanceBench promoted URL live3", "run_demo_financebench_doc_live3_promoted_url_20260613.summary.json"),
    ("FinanceBench live3 closed", "run_financebench_doc_live3_model_net_v1.summary.json"),
    ("FAB v2 dev10 capability", "run_fabv2_dev10_capability_parallel10_judgefix.summary.json"),
)
RELEVANT_EVENT_KINDS = {
    "processor_request",
    "processor_result",
    "retrieval_search_attempt",
    "retrieval_fetch",
    "retrieval_fetch_attempt",
    "retrieval_extraction",
    "retrieval_report",
    "retrieval_evaluation",
    "retrieval_evidence_rejections",
    "action",
    "observation",
    "feedback",
    "termination_decision",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Holo Kernel v3 live demo dashboard.")
    parser.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--run-prefix", default=DEFAULT_RUN_PREFIX)
    parser.add_argument("--thread-prefix", default="", help="Only show journal events for threads with this prefix.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    server = DashboardServer(
        (args.host, args.port),
        DashboardHandler,
        root=root,
        run_prefix=args.run_prefix,
        thread_prefix=args.thread_prefix,
    )
    print(f"Holo Kernel v3 dashboard: http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


class DashboardServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler,
        *,
        root: Path,
        run_prefix: str,
        thread_prefix: str = "",
    ) -> None:
        super().__init__(server_address, handler)
        self.root = root
        self.run_prefix = run_prefix
        self.thread_prefix = thread_prefix


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_text(HTML, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/state":
            query = parse_qs(parsed.query, keep_blank_values=True)
            run_prefix = _query_value(query, "run_prefix") or self.server.run_prefix
            item_id = _query_value(query, "item_id") or ""
            thread_prefix = _query_value(query, "thread_prefix")
            if thread_prefix is None:
                mapped_thread_prefix = _thread_prefix_for_run(run_prefix)
                thread_prefix = mapped_thread_prefix if mapped_thread_prefix is not None else self.server.thread_prefix
            self._send_json(build_state(self.server.root, run_prefix, thread_prefix, item_id=item_id))
            return
        if parsed.path == "/workflow":
            workflow = self.server.root / ".state/kernel_v3/visuals/kernel_v3_live_demo_task902.html"
            self._send_file(workflow, "text/html; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Json) -> None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Workflow view not generated yet")
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_state(root: Path, run_prefix: str, thread_prefix: str = "", *, item_id: str = "") -> Json:
    now = time.time()
    bench_dir = root / ".state/kernel_v3/bench/finance"
    journal = root / ".state/kernel_v3/journal/global.jsonl"
    result_path = bench_dir / f"{run_prefix}.jsonl"
    summary_path = bench_dir / f"{run_prefix}.summary.json"
    reasonable_path = bench_dir / f"{run_prefix}.reasonable.json"
    result_records = read_jsonl(result_path, max_bytes=8_000_000, max_records=200)
    summary = read_json(summary_path)
    reasonable = read_json(reasonable_path)
    journal_records = read_jsonl(journal, max_bytes=5_000_000, max_records=900)
    events = compact_events(journal_records, thread_prefix=thread_prefix)
    item_records = _records_for_item(result_records, item_id)
    display_records = item_records if item_records else result_records
    latest_item = display_records[-1] if display_records else {}
    latest_metrics = dict(latest_item.get("trace_metrics") or latest_item.get("scorecard", {}).get("trace_metrics") or {})
    current = current_run_state(
        result_path=result_path,
        summary_path=summary_path,
        records=display_records,
        summary=summary,
        reasonable=reasonable,
        latest=latest_item,
        latest_metrics=latest_metrics,
        now=now,
        selected_item_id=item_id if item_records else "",
    )
    return {
        "generated_at": iso_time(now),
        "repo": repo_state(root),
        "current": current,
        "baselines": baseline_state(bench_dir),
        "demo_runs": demo_run_state(bench_dir),
        "stability": stability_state(bench_dir, latest_item.get("item_id") or latest_item.get("id") or item_id),
        "llm": llm_state(events),
        "pipeline": pipeline_state(latest_item, latest_metrics, events),
        "intelligence": intelligence_state(root, latest_metrics),
        "events": events[-16:],
        "diagnosis": diagnosis_state(latest_item, latest_metrics, events),
        "links": {
            "workflow": "/workflow",
            "result_jsonl": str(result_path.relative_to(root)) if result_path.exists() else "",
            "summary_json": str(summary_path.relative_to(root)) if summary_path.exists() else "",
        },
        "filters": {
            "run_prefix": run_prefix,
            "thread_prefix": thread_prefix,
            "item_id": item_id,
        },
    }


def demo_run_state(bench_dir: Path) -> list[Json]:
    rows: list[Json] = []
    for item in DEMO_RUNS:
        run_prefix = str(item["run_prefix"])
        item_id = str(item.get("item_id") or "")
        summary = read_json(bench_dir / f"{run_prefix}.summary.json")
        records = read_jsonl(bench_dir / f"{run_prefix}.jsonl", max_bytes=8_000_000, max_records=200)
        item_records = _records_for_item(records, item_id)
        display_records = item_records if item_records else records
        latest = display_records[-1] if display_records else {}
        latest_metrics = dict(latest.get("trace_metrics") or latest.get("scorecard", {}).get("trace_metrics") or {})
        if item_id and item_records:
            statuses = _status_counts(item_records)
            done = len(item_records)
            passed = int(statuses.get("passed", 0))
            failed = int(statuses.get("failed", 0))
            pass_rate = passed / max(1, done)
        else:
            done = int(summary.get("scored_count") or len(records))
            passed = int(summary.get("passed_count") or (1 if latest.get("status") == "passed" else 0))
            failed = int(summary.get("failed_count") or (1 if latest.get("status") == "failed" else 0))
            pass_rate = safe_float(summary.get("pass_rate"))
        rows.append(
            {
                **item,
                "status": _run_status(bench_dir, run_prefix, summary=summary, latest=latest),
                "item_id": item_id,
                "pass_rate": pass_rate,
                "done": done,
                "passed": passed,
                "failed": failed,
                "latest_item_id": latest.get("item_id") or latest.get("id") or "",
                "calculator_calls": latest_metrics.get("calculator_call_count"),
                "retrieval_runs": latest_metrics.get("retrieval_run_count"),
                "fetches": latest_metrics.get("fetch_attempt_count"),
                "facts": latest_metrics.get("finance_fact_count") or latest_metrics.get("claim_count") or latest_metrics.get("evidence_count"),
                "tokens": latest_metrics.get("total_tokens"),
            }
        )
    return rows


def stability_state(bench_dir: Path, item_id: Any) -> Json:
    target = str(item_id or "")
    runs: list[Json] = []
    if not target:
        return {"target_item_id": "", "pass_traces": 0, "total_traces": 0, "verified_traces": 0, "runs": runs}
    seen: set[str] = set()
    pass_traces = 0
    total_traces = 0
    verified_traces = 0
    for item in DEMO_RUNS:
        run_prefix = str(item.get("run_prefix") or "")
        if str(item.get("item_id") or "") != target:
            continue
        if not run_prefix or run_prefix in seen:
            continue
        seen.add(run_prefix)
        records = _records_for_item(
            read_jsonl(bench_dir / f"{run_prefix}.jsonl", max_bytes=8_000_000, max_records=200),
            target,
        )
        if not records:
            continue
        latest = records[-1]
        metrics = dict(latest.get("trace_metrics") or latest.get("scorecard", {}).get("trace_metrics") or {})
        passed = sum(1 for record in records if record.get("status") == "passed")
        total_traces += len(records)
        pass_traces += passed
        if metrics.get("numeric_verifier_status") == "passed":
            verified_traces += 1
        runs.append(
            {
                "label": item.get("label") or run_prefix,
                "run_prefix": run_prefix,
                "passed": passed,
                "total": len(records),
                "verifier": metrics.get("numeric_verifier_status") or "",
                "calculator_calls": metrics.get("calculator_call_count"),
                "facts": metrics.get("finance_fact_count") or metrics.get("claim_count") or metrics.get("evidence_count"),
                "citations": metrics.get("citation_count") or metrics.get("retrieval_citation_count"),
            }
        )
    return {
        "target_item_id": target,
        "pass_traces": pass_traces,
        "total_traces": total_traces,
        "verified_traces": verified_traces,
        "runs": runs,
    }


def _records_for_item(records: list[Json], item_id: str) -> list[Json]:
    if not item_id:
        return []
    return [record for record in records if _record_item_id(record) == item_id]


def _record_item_id(record: Json) -> str:
    return str(record.get("item_id") or record.get("id") or "")


def _status_counts(records: list[Json]) -> dict[str, int]:
    statuses: dict[str, int] = {}
    for item in records:
        status = str(item.get("status") or item.get("scorecard", {}).get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    return statuses


def _query_value(query: dict[str, list[str]], key: str) -> str | None:
    if key not in query:
        return None
    values = query.get(key) or []
    if not values:
        return ""
    return str(values[0])


def _thread_prefix_for_run(run_prefix: str) -> str | None:
    for item in DEMO_RUNS:
        if item.get("run_prefix") == run_prefix:
            return str(item.get("thread_prefix") or "")
    return None


def current_run_state(
    *,
    result_path: Path,
    summary_path: Path,
    records: list[Json],
    summary: Json,
    reasonable: Json,
    latest: Json,
    latest_metrics: Json,
    now: float,
    selected_item_id: str = "",
) -> Json:
    statuses = _status_counts(records)
    if selected_item_id:
        total = max(1, len(records))
        done = len(records)
        passed = int(statuses.get("passed", 0))
        failed = int(statuses.get("failed", 0))
        pass_rate = passed / max(1, done) if done else None
    else:
        total = int(summary.get("item_count") or max(3, len(records)))
        done = int(summary.get("scored_count") or len(records))
        passed = int(summary.get("passed_count") or statuses.get("passed", 0))
        failed = int(summary.get("failed_count") or statuses.get("failed", 0))
        pass_rate = safe_float(summary.get("pass_rate"))
        if pass_rate is None and done:
            pass_rate = passed / max(1, done)
    status = _run_status(result_path.parent, result_path.stem, summary=summary, latest=latest)
    mtime = result_path.stat().st_mtime if result_path.exists() else 0.0
    stale_seconds = max(0, int(now - mtime)) if mtime else None
    return {
        "name": result_path.stem,
        "status": status,
        "done": done,
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "reasonable_pass_rate": safe_float(reasonable.get("pass_rate")),
        "reasonable_passed": reasonable.get("passed_count"),
        "reasonable_failed": reasonable.get("failed_count"),
        "status_counts": statuses or summary.get("status_counts") or {},
        "latest_item_id": latest.get("item_id") or latest.get("id") or "",
        "selected_item_id": selected_item_id,
        "latest_question": latest.get("question") or "",
        "latest_reason": latest.get("scorecard", {}).get("reason") or latest.get("failure_report", {}).get("reason") or "",
        "latest_answer": _answer_text(latest.get("final_answer") or latest.get("answer") or ""),
        "latest_metrics": selected_metrics(latest_metrics),
        "result_exists": result_path.exists(),
        "summary_exists": summary_path.exists(),
        "stale_seconds": stale_seconds,
    }


def _answer_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("answer", "final_answer", "result", "text"):
            if value.get(key):
                return clip(value.get(key), 900)
        return clip(json.dumps(value, ensure_ascii=True, sort_keys=True), 900)
    if isinstance(value, list):
        return clip(json.dumps(value, ensure_ascii=True), 900)
    return clip(value, 900)


def _run_status(bench_dir: Path, run_prefix: str, *, summary: Json, latest: Json) -> str:
    result_path = bench_dir / f"{run_prefix}.jsonl"
    summary_path = bench_dir / f"{run_prefix}.summary.json"
    if summary_path.exists():
        return "complete"
    if latest.get("status") in {"failed", "passed"}:
        return "complete"
    if result_path.exists():
        return "running"
    return "waiting"


def baseline_state(bench_dir: Path) -> list[Json]:
    rows: list[Json] = []
    for label, filename in BASELINE_RUNS:
        summary = read_json(bench_dir / filename)
        if not summary:
            continue
        reasonable = read_json(bench_dir / filename.replace(".summary.json", ".reasonable.json"))
        dev = summary.get("dev_annotation_score") if isinstance(summary.get("dev_annotation_score"), dict) else {}
        rows.append(
            {
                "label": label,
                "run": filename.replace(".summary.json", ""),
                "items": summary.get("item_count"),
                "pass_rate": safe_float(summary.get("pass_rate")),
                "passed": summary.get("passed_count"),
                "failed": summary.get("failed_count"),
                "overall": safe_float(dev.get("overall_score")),
                "behavior": safe_float(dev.get("behavior_score")),
                "substrate": safe_float(dev.get("substrate_score")),
                "workflow": safe_float(dev.get("workflow_score")),
                "numeric": safe_float(summary.get("numeric_accuracy") if summary.get("numeric_accuracy") is not None else dev.get("numeric_score")),
                "reasonable": safe_float(reasonable.get("pass_rate")),
                "citation": safe_float(summary.get("citation_present_rate")),
                "calculator": safe_float(summary.get("calculator_used_rate")),
            }
        )
    rows.sort(key=lambda row: (row.get("overall") or row.get("pass_rate") or 0), reverse=True)
    return rows


def llm_state(events: list[Json]) -> Json:
    requests = [event for event in events if event.get("kind") == "processor_request"]
    results = [event for event in events if event.get("kind") == "processor_result"]
    latest_request = requests[-1] if requests else {}
    latest_result = results[-1] if results else {}
    ok_results = [event for event in results if event.get("status") == "ok"]
    return {
        "provider": latest_request.get("provider") or latest_result.get("provider") or "deepseek",
        "model": latest_request.get("model") or latest_result.get("model") or "",
        "task_type": latest_request.get("task_type") or latest_result.get("task_type") or "",
        "requests": len(requests),
        "results": len(results),
        "ok_results": len(ok_results),
        "last_duration_ms": latest_result.get("duration_ms"),
        "last_status": latest_result.get("status") or ("waiting" if latest_request else "idle"),
    }


def pipeline_state(latest: Json, metrics: Json, events: list[Json]) -> list[Json]:
    citation_count = int(metrics.get("citation_count") or metrics.get("retrieval_citation_count") or 0)
    evidence_count = int(metrics.get("evidence_count") or 0)
    calc_calls = int(metrics.get("calculator_call_count") or 0)
    processor_errors = int(metrics.get("processor_error_count") or 0)
    return [
        stage("LLM plan", "active" if any(e.get("kind") == "processor_request" for e in events[-4:]) else "ok", int(metrics.get("processor_call_count") or 0), "model-owned routing"),
        stage("Retrieve", "ok" if int(metrics.get("retrieval_run_count") or 0) else "idle", int(metrics.get("fetch_attempt_count") or 0), "live sources fetched"),
        stage("Evidence", "ok" if evidence_count else "warn", evidence_count, f"{citation_count} citations"),
        stage("Compute", "ok" if calc_calls else "idle", calc_calls, "calculator traces"),
        stage("Verify", verifier_status(metrics), int(metrics.get("verifier_gate_issue_count") or 0), str(metrics.get("numeric_verifier_status") or "-")),
        stage("Synthesize", synth_status(metrics, latest), int(metrics.get("synthesis_gate_attempt_count") or 0), str(metrics.get("synthesis_gate_status") or latest.get("status") or "-")),
        stage("Score", "ok" if latest.get("status") == "passed" else "warn" if latest else "idle", 1 if latest else 0, str(latest.get("status") or "waiting")),
        stage("Provider", "warn" if processor_errors else "ok", processor_errors, "errors"),
    ]


def intelligence_state(root: Path, metrics: Json) -> list[Json]:
    memory_path = root / ".state/kernel_v3/memory/memory.sqlite"
    return [
        {"label": "Finance research", "state": "live", "detail": "SEC/company filing retrieval, numeric verification, synthesis gates"},
        {"label": "General reasoning", "state": "live", "detail": "LLM planner owns semantic decisions; host only validates and executes"},
        {"label": "Math tools", "state": "ready" if metrics.get("calculator_call_count") is not None else "available", "detail": "calculator.compute and formula traces for auditable arithmetic"},
        {"label": "Physics/general tasks", "state": "available", "detail": "same LLM+tool harness; finance pack is currently the specialized domain"},
        {"label": "Durable memory", "state": "ready" if memory_path.exists() else "not ready", "detail": "structured memory store under host control"},
        {"label": "No table cheating", "state": "enforced", "detail": "gold files are scoring-only; live model and retrieval paths are visible in journal"},
    ]


def diagnosis_state(latest: Json, metrics: Json, events: list[Json]) -> Json:
    reason = latest.get("scorecard", {}).get("reason") or latest.get("failure_report", {}).get("reason") or ""
    failure_mode = str(metrics.get("latest_failure_mode") or "")
    if failure_mode.lower() == "none":
        failure_mode = ""
    next_hint = metrics.get("latest_next_strategy_hint") or latest.get("failure_report", {}).get("next_possible_action") or ""
    issue = "Waiting for live run."
    if latest.get("status") == "failed":
        issue = "Live run failed honestly: evidence extraction did not produce enough final answer evidence."
    elif latest.get("status") == "passed":
        issue = "Latest item passed."
    elif events:
        issue = "Live run is in progress."
    return {
        "headline": issue,
        "reason": reason,
        "failure_mode": failure_mode,
        "next_hint": next_hint,
        "engineering_takeaway": "Improve target filing document expansion from SEC index/direct URLs into the primary 10-K HTML before another live run." if failure_mode else "",
    }


def compact_events(records: list[Json], *, thread_prefix: str = "") -> list[Json]:
    events: list[Json] = []
    allowed_task_ids, allowed_run_ids = _thread_scoped_ids(records, thread_prefix)
    for record in records:
        if thread_prefix and not _record_in_thread_scope(
            record,
            thread_prefix,
            allowed_task_ids=allowed_task_ids,
            allowed_run_ids=allowed_run_ids,
        ):
            continue
        kind = str(record.get("kind") or "")
        if kind not in RELEVANT_EVENT_KINDS:
            continue
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        event: Json = {
            "kind": kind,
            "record_id": record.get("record_id"),
            "task_id": record.get("task_id") or data.get("task_id"),
            "step_id": record.get("step_id"),
            "at": record.get("recorded_at_ms"),
        }
        if kind == "processor_request":
            params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
            event.update(
                {
                    "task_type": data.get("task_type") or data.get("processor"),
                    "provider": data.get("provider") or params.get("provider"),
                    "model": data.get("model") or params.get("model"),
                    "status": "request",
                }
            )
        elif kind == "processor_result":
            event.update(
                {
                    "task_type": data.get("task_type"),
                    "provider": data.get("provider"),
                    "model": data.get("model"),
                    "status": data.get("status"),
                    "duration_ms": data.get("duration_ms"),
                }
            )
        elif kind == "retrieval_search_attempt":
            event.update(
                {
                    "query": clip(data.get("query"), 160),
                    "status": data.get("status"),
                    "source_count": len(data.get("sources") or []),
                }
            )
        elif kind in {"retrieval_fetch", "retrieval_fetch_attempt"}:
            event.update(
                {
                    "uri": clip(data.get("uri") or data.get("source", {}).get("uri"), 160),
                    "status": data.get("status"),
                }
            )
        elif kind == "retrieval_extraction":
            doc = data.get("document") if isinstance(data.get("document"), dict) else {}
            event.update(
                {
                    "title": clip(doc.get("title"), 120),
                    "uri": clip(doc.get("uri"), 160),
                    "span_count": data.get("diagnostics", {}).get("span_count"),
                    "status": "extracted",
                }
            )
        elif kind in {"feedback", "termination_decision"}:
            event.update(
                {
                    "status": data.get("status") or data.get("decision"),
                    "reason": data.get("reason") or data.get("stop_reason"),
                }
            )
        else:
            event.update({"status": data.get("status") or data.get("reason") or ""})
        events.append(event)
    return events


def _thread_scoped_ids(records: list[Json], thread_prefix: str) -> tuple[set[str], set[str]]:
    task_ids: set[str] = set()
    run_ids: set[str] = set()
    if not thread_prefix:
        return task_ids, run_ids
    for record in records:
        if not _record_matches_thread_prefix(record, thread_prefix):
            continue
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        for value in (record.get("task_id"), data.get("task_id")):
            if isinstance(value, str) and value:
                task_ids.add(value)
        for value in (record.get("run_id"), data.get("run_id")):
            if isinstance(value, str) and value:
                run_ids.add(value)
    return task_ids, run_ids


def _record_in_thread_scope(
    record: Json,
    thread_prefix: str,
    *,
    allowed_task_ids: set[str],
    allowed_run_ids: set[str],
) -> bool:
    if _record_matches_thread_prefix(record, thread_prefix):
        return True
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    task_id = record.get("task_id") or data.get("task_id")
    run_id = record.get("run_id") or data.get("run_id")
    if isinstance(task_id, str) and task_id in allowed_task_ids:
        return True
    if isinstance(run_id, str) and run_id in allowed_run_ids:
        return True
    return False


def _record_matches_thread_prefix(record: Json, thread_prefix: str) -> bool:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    candidates = [
        record.get("thread_id"),
        data.get("thread_id"),
        data.get("thread_key"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith(thread_prefix):
            return True
    return False


def selected_metrics(metrics: Json) -> Json:
    keys = (
        "total_tokens",
        "processor_call_count",
        "processor_duration_ms",
        "retrieval_run_count",
        "fetch_attempt_count",
        "fetch_success_rate",
        "downloaded_bytes",
        "calculator_call_count",
        "finance_fact_count",
        "claim_count",
        "evidence_count",
        "citation_count",
        "retrieval_citation_count",
        "claim_ledger_present",
        "formula_trace_present",
        "synthesis_gate_passed",
        "numeric_verifier_status",
        "query_repetition_rate",
    )
    return {key: metrics.get(key) for key in keys if key in metrics}


def stage(label: str, state: str, value: int, detail: str) -> Json:
    return {"label": label, "state": state, "value": value, "detail": detail}


def verifier_status(metrics: Json) -> str:
    if metrics.get("numeric_verifier_passed") is True or metrics.get("verifier_gate_passed") is True:
        return "ok"
    if metrics.get("numeric_verifier_status") or metrics.get("verifier_gate_status"):
        return "warn"
    return "idle"


def synth_status(metrics: Json, latest: Json) -> str:
    if metrics.get("synthesis_gate_passed") is True:
        return "ok"
    if latest.get("status") == "failed":
        return "warn"
    if metrics.get("synthesis_gate_status"):
        return "warn"
    return "idle"


def repo_state(root: Path) -> Json:
    return {
        "branch": run_git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": run_git(root, "rev-parse", "--short", "HEAD"),
        "remote": run_git(root, "rev-parse", "--short", "github/kernel-v3"),
        "dirty": bool(run_git(root, "status", "--short")),
    }


def run_git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except Exception:
        return ""
    return proc.stdout.strip()


def read_json(path: Path) -> Json:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_jsonl(path: Path, *, max_bytes: int, max_records: int) -> list[Json]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            raw = handle.read()
    except Exception:
        return []
    text = raw.decode("utf-8", errors="ignore")
    if len(raw) >= max_bytes:
        text = text.split("\n", 1)[-1]
    records: list[Json] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records[-max_records:]


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "..."


def iso_time(value: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Holo Kernel v3 Live Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7f9;
      --panel: #ffffff;
      --ink: #162029;
      --muted: #637083;
      --line: #d7dde5;
      --blue: #2563eb;
      --teal: #0f766e;
      --green: #15803d;
      --amber: #b45309;
      --red: #b91c1c;
      --slate: #334155;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      height: 100vh;
      overflow: hidden;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 22px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    h1 { margin: 0; font-size: 20px; font-weight: 720; letter-spacing: 0; }
    .sub { color: var(--muted); font-size: 13px; margin-top: 3px; }
    .top-actions { display: flex; gap: 8px; align-items: center; }
    button, a.button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 8px 10px;
      border-radius: 8px;
      font-size: 13px;
      text-decoration: none;
      cursor: pointer;
    }
    button.active { border-color: var(--blue); color: var(--blue); }
    .grid {
      height: calc(100vh - 64px);
      display: grid;
      grid-template-columns: minmax(420px, 34%) 1fr;
      gap: 14px;
      padding: 14px;
      overflow: hidden;
    }
    .left, .right { min-height: 0; display: grid; gap: 14px; }
    .left { grid-template-rows: 278px 1fr 178px; }
    .right { grid-template-rows: 220px 1fr 150px; }
    .panel {
      min-height: 0;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      overflow: hidden;
    }
    .panel-title {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
      font-size: 13px;
      color: var(--muted);
      font-weight: 700;
      text-transform: uppercase;
    }
    .hero-metric { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    .metric { border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-width: 0; }
    .metric .value { font-size: 30px; line-height: 1; font-weight: 780; }
    .metric .label { margin-top: 7px; color: var(--muted); font-size: 12px; }
    .status { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; color: var(--muted); }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
    .dot.ok { background: var(--green); }
    .dot.running, .dot.active { background: var(--blue); }
    .dot.warn { background: var(--amber); }
    .dot.failed { background: var(--red); }
    .progress { height: 8px; background: #e7ebf0; border-radius: 8px; overflow: hidden; margin-top: 12px; }
    .bar { height: 100%; width: 0%; background: var(--blue); }
    .cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .run-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
    .baseline { border: 1px solid var(--line); border-radius: 8px; padding: 10px; min-width: 0; }
    .baseline strong { display: block; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .baseline .score { font-size: 26px; font-weight: 780; margin: 8px 0 4px; color: var(--teal); }
    .run-card {
      display: grid;
      gap: 4px;
      text-align: left;
      min-width: 0;
      padding: 8px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
    }
    .run-card.active { border-color: var(--blue); box-shadow: inset 0 0 0 1px var(--blue); }
    .run-card strong { display: block; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .run-card .question-line { color: var(--muted); font-size: 10px; line-height: 1.25; height: 25px; overflow: hidden; }
    .run-status-line { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      color: var(--muted);
      font-size: 10px;
      white-space: nowrap;
    }
    .tiny { color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .run-card .tiny { font-size: 10px; }
    .evidence-ribbon {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .evidence-chip {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px 9px;
      min-width: 0;
      background: #fbfcfd;
    }
    .evidence-chip strong { display: block; font-size: 14px; line-height: 1; }
    .evidence-chip span { display: block; margin-top: 4px; font-size: 10px; color: var(--muted); }
    .spotlight {
      margin-top: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 10px;
      background: #f8fafc;
      min-height: 62px;
      overflow: hidden;
    }
    .spotlight-kicker {
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      font-weight: 750;
    }
    .spotlight-title {
      margin-top: 5px;
      font-size: 14px;
      font-weight: 760;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .spotlight-text {
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      height: 32px;
      overflow: hidden;
    }
    .tool-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
    .pipeline { display: grid; grid-template-columns: repeat(4, 1fr); grid-template-rows: repeat(2, minmax(0, 1fr)); gap: 10px; height: calc(100% - 28px); }
    .stage { border: 1px solid var(--line); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; justify-content: space-between; min-width: 0; }
    .stage .name { font-weight: 720; font-size: 14px; }
    .stage .num { font-size: 24px; font-weight: 780; line-height: 1; }
    .stage.ok { border-color: #9fd4b1; }
    .stage.warn { border-color: #e5c07b; }
    .stage.active { border-color: #93b4f8; }
    .stage.idle { opacity: 0.72; }
    .tabs { display: none; height: 100%; min-height: 0; }
    .tabs.active { display: grid; }
    .finance-view { grid-template-rows: 52px 1fr; gap: 10px; }
    .question {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      font-size: 13px;
      line-height: 1.45;
      overflow: hidden;
      color: var(--slate);
      background: #fbfcfd;
    }
    .diag { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; min-height: 0; }
    .diag-block { border: 1px solid var(--line); border-radius: 8px; padding: 12px; overflow: hidden; }
    .diag-block h3 { margin: 0 0 8px; font-size: 15px; }
    .diag-block p { margin: 0; font-size: 13px; line-height: 1.45; color: var(--muted); }
    .intel-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; height: 100%; }
    .intel { border: 1px solid var(--line); border-radius: 8px; padding: 12px; overflow: hidden; }
    .intel .label { font-weight: 720; font-size: 14px; }
    .intel .state { margin-top: 6px; color: var(--teal); font-weight: 700; font-size: 13px; }
    .intel .detail { margin-top: 8px; color: var(--muted); font-size: 12px; line-height: 1.45; }
    .timeline { display: grid; gap: 7px; height: 100%; grid-auto-rows: minmax(30px, auto); overflow: hidden; }
    .event { display: grid; grid-template-columns: 150px 84px 1fr; gap: 10px; align-items: center; border-bottom: 1px solid #edf0f4; padding-bottom: 7px; min-width: 0; }
    .event div { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12px; }
    .event .kind { font-weight: 720; color: var(--slate); }
    .event .state { color: var(--muted); }
    .event .desc { color: var(--muted); }
    .footer-grid { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 10px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    @media (max-width: 980px) {
      body { overflow: auto; height: auto; }
      .grid { height: auto; grid-template-columns: 1fr; }
      .left, .right { grid-template-rows: auto; }
      .pipeline, .cards, .run-cards, .diag, .intel-list, .footer-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Holo Kernel v3 Live Dashboard</h1>
      <div class="sub" id="subtitle">Loading live state...</div>
    </div>
    <div class="top-actions">
      <button data-tab="finance" class="active">Finance</button>
      <button data-tab="intelligence">Intelligence</button>
      <button data-tab="trace">Trace</button>
      <a class="button" href="/workflow" target="_blank">Audit View</a>
    </div>
  </header>
  <main class="grid">
    <section class="left">
      <div class="panel">
        <div class="panel-title"><span>Current live run</span><span class="status"><span id="runDot" class="dot"></span><span id="runStatus">loading</span></span></div>
        <div class="hero-metric">
          <div class="metric"><div class="value" id="passRate">-</div><div class="label">strict pass rate</div></div>
          <div class="metric"><div class="value" id="verifierState">-</div><div class="label">numeric verifier</div></div>
          <div class="metric"><div class="value" id="progressText">0/0</div><div class="label">items scored</div></div>
        </div>
        <div class="progress"><div class="bar" id="progressBar"></div></div>
        <div class="evidence-ribbon">
          <div class="evidence-chip"><strong id="heroCalc">0</strong><span>calculator</span></div>
          <div class="evidence-chip"><strong id="heroFacts">0</strong><span>finance facts</span></div>
          <div class="evidence-chip"><strong id="heroCitations">0</strong><span>citations</span></div>
        </div>
        <div class="spotlight">
          <div class="spotlight-kicker"><span>Auto demo reel</span><span id="spotlightStep">1/1</span></div>
          <div class="spotlight-title" id="spotlightTitle">Loading spotlight</div>
          <div class="spotlight-text" id="spotlightText">The dashboard will rotate through live capability evidence automatically.</div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-title"><span>Demo case selector</span><span id="selectedRunLabel">live</span></div>
        <div class="run-cards" id="demoRuns"></div>
      </div>
      <div class="panel">
        <div class="panel-title"><span>LLM and tools</span><span id="provider"></span></div>
        <div class="tool-grid">
          <div class="metric"><div class="value" id="llmCalls">0</div><div class="label">processor calls</div></div>
          <div class="metric"><div class="value" id="retrievalFetches">0</div><div class="label">fetches</div></div>
          <div class="metric"><div class="value" id="calcCalls">0</div><div class="label">calculator</div></div>
          <div class="metric"><div class="value" id="factCount">0</div><div class="label">facts</div></div>
          <div class="metric"><div class="value" id="stablePasses">0/0</div><div class="label">pass traces</div></div>
        </div>
      </div>
    </section>
    <section class="right">
      <div class="panel">
        <div class="panel-title"><span>Agent pipeline</span><span id="latestItem"></span></div>
        <div class="pipeline" id="pipeline"></div>
      </div>
      <div class="panel">
        <section id="finance" class="tabs finance-view active">
          <div class="question" id="question"></div>
          <div class="diag">
            <div class="diag-block"><h3>Answer state</h3><p id="answerState"></p></div>
            <div class="diag-block"><h3>Engineering diagnosis</h3><p id="diagnosis"></p></div>
          </div>
        </section>
        <section id="intelligence" class="tabs">
          <div class="intel-list" id="intel"></div>
        </section>
        <section id="trace" class="tabs">
          <div class="timeline" id="events"></div>
        </section>
      </div>
      <div class="panel">
        <div class="panel-title"><span>Run files</span><span id="repo"></span></div>
        <div class="footer-grid">
          <div class="diag-block"><h3>Result JSONL</h3><p class="mono" id="resultPath"></p></div>
          <div class="diag-block"><h3>Summary JSON</h3><p class="mono" id="summaryPath"></p></div>
          <div class="diag-block"><h3>Refresh</h3><p id="refreshState"></p></div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const fmtPct = v => (v === null || v === undefined || Number.isNaN(Number(v))) ? "-" : `${(Number(v) * 100).toFixed(1)}%`;
    const fmtNum = v => (v === null || v === undefined || v === "") ? "0" : Number(v).toLocaleString();
    const text = (id, value) => { document.getElementById(id).textContent = value ?? ""; };
    const cls = (id, value) => { document.getElementById(id).className = value; };
    const params = new URLSearchParams(window.location.search);
    const selected = {
      runPrefix: params.get("run_prefix") || "",
      threadPrefix: params.has("thread_prefix") ? params.get("thread_prefix") : null,
      itemId: params.get("item_id") || ""
    };
    let latestSpotlights = [];
    let spotlightIndex = 0;
    function setTab(name) {
      document.querySelectorAll("button[data-tab]").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
      document.querySelectorAll(".tabs").forEach(p => p.classList.toggle("active", p.id === name));
    }
    document.querySelectorAll("button[data-tab]").forEach(b => b.addEventListener("click", () => setTab(b.dataset.tab)));
    function stateUrl() {
      const query = new URLSearchParams();
      if (selected.runPrefix) query.set("run_prefix", selected.runPrefix);
      if (selected.threadPrefix !== null) query.set("thread_prefix", selected.threadPrefix || "");
      if (selected.itemId) query.set("item_id", selected.itemId);
      const suffix = query.toString();
      return suffix ? `/api/state?${suffix}` : "/api/state";
    }
    function selectRun(row) {
      selected.runPrefix = row.run_prefix || "";
      selected.threadPrefix = row.thread_prefix ?? "";
      selected.itemId = row.item_id || "";
      const query = new URLSearchParams();
      if (selected.runPrefix) query.set("run_prefix", selected.runPrefix);
      query.set("thread_prefix", selected.threadPrefix || "");
      if (selected.itemId) query.set("item_id", selected.itemId);
      window.history.replaceState(null, "", `?${query.toString()}`);
      refresh();
    }
    async function refresh() {
      const res = await fetch(stateUrl(), { cache: "no-store" });
      const data = await res.json();
      const cur = data.current || {};
      if (!selected.runPrefix && data.filters && data.filters.run_prefix) selected.runPrefix = data.filters.run_prefix;
      if (data.filters && data.filters.item_id !== undefined) selected.itemId = data.filters.item_id || "";
      const metrics = cur.latest_metrics || {};
      const stability = data.stability || {};
      text("subtitle", `${data.generated_at} | branch ${data.repo.branch || "-"} @ ${data.repo.head || "-"}`);
      text("runStatus", cur.status || "unknown");
      cls("runDot", `dot ${cur.status === "complete" && cur.failed ? "failed" : cur.status === "complete" ? "ok" : cur.status || ""}`);
      text("passRate", fmtPct(cur.pass_rate));
      text("verifierState", metrics.numeric_verifier_status || (metrics.synthesis_gate_passed ? "passed" : "-"));
      text("progressText", `${cur.done || 0}/${cur.total || 0}`);
      document.getElementById("progressBar").style.width = `${Math.min(100, ((cur.done || 0) / Math.max(1, cur.total || 1)) * 100)}%`;
      text("heroCalc", fmtNum(metrics.calculator_call_count));
      text("heroFacts", fmtNum(metrics.finance_fact_count || metrics.claim_count || metrics.evidence_count));
      text("heroCitations", fmtNum(metrics.citation_count || metrics.retrieval_citation_count));
      text("latestItem", cur.latest_item_id || "waiting");
      text("question", cur.latest_question || "Waiting for the next scored item.");
      text("answerState", cur.latest_answer || cur.latest_reason || "No final answer yet.");
      const d = data.diagnosis || {};
      text("diagnosis", [d.headline, d.reason, d.failure_mode, d.next_hint, d.engineering_takeaway].filter(Boolean).join(" | "));
      text("provider", `${data.llm.provider || "-"} ${data.llm.model || ""}`.trim());
      text("llmCalls", fmtNum(metrics.processor_call_count || data.llm.requests));
      text("retrievalFetches", fmtNum(metrics.fetch_attempt_count));
      text("calcCalls", fmtNum(metrics.calculator_call_count));
      text("factCount", fmtNum(metrics.finance_fact_count || metrics.claim_count || metrics.evidence_count));
      text("stablePasses", `${stability.pass_traces ?? 0}/${stability.total_traces ?? 0}`);
      text("repo", `${data.repo.dirty ? "dirty" : "clean"} | remote ${data.repo.remote || "-"}`);
      text("resultPath", data.links.result_jsonl || "-");
      text("summaryPath", data.links.summary_json || "-");
      text("refreshState", `auto refresh on | stale ${cur.stale_seconds ?? "-"}s`);
      text("selectedRunLabel", `${cur.name || (data.filters || {}).run_prefix || "live"}${cur.selected_item_id ? " / " + cur.selected_item_id : ""}`);
      renderDemoRuns(data.demo_runs || [], (data.filters || {}).run_prefix || selected.runPrefix, (data.filters || {}).item_id || selected.itemId);
      renderPipeline(data.pipeline || []);
      renderIntel(data.intelligence || []);
      renderEvents(data.events || []);
      latestSpotlights = buildSpotlights(data);
      if (spotlightIndex >= latestSpotlights.length) spotlightIndex = 0;
      renderSpotlight();
    }
    function buildSpotlights(data) {
      const cur = data.current || {};
      const metrics = cur.latest_metrics || {};
      const demoRuns = data.demo_runs || [];
      const stability = data.stability || {};
      const passedRuns = demoRuns.filter(row => Number(row.pass_rate || 0) > 0 || Number(row.passed || 0) > 0);
      const best = passedRuns[0] || demoRuns[0] || {};
      const fe009 = demoRuns.find(row => row.item_id === "FE_009") || {};
      return [
        {
          title: `Live scoring: ${cur.passed || 0}/${cur.done || 0} passed`,
          text: `${cur.name || "current run"} is scoring live questions with DeepSeek and live retrieval; strict pass rate is ${fmtPct(cur.pass_rate)}.`
        },
        {
          title: `Financial evidence: ${fmtNum(metrics.finance_fact_count || metrics.claim_count || metrics.evidence_count)} facts`,
          text: `The visible loop is LLM plan, retrieval.run, ClaimLedger, SlotFrame, calculator when needed, verifier gate, and synthesis.`
        },
        {
          title: fe009.status ? `Goldman FE_009: ${fe009.status}` : "Goldman FE_009 metric disambiguation",
          text: fe009.done ? `Net revenues trace: pass ${fmtPct(fe009.pass_rate)}, fetch ${fmtNum(fe009.fetches)}, facts ${fmtNum(fe009.facts)}, calculator ${fmtNum(fe009.calculator_calls)}.` : "The demo tracks exact metric phrase matching for net revenues instead of component revenue lines."
        },
        {
          title: best.label || "Promoted finance demo",
          text: `${best.question || "A selected finance task shows the full tool-backed reasoning path."} Pass ${fmtPct(best.pass_rate)}; facts ${fmtNum(best.facts)}; fetch ${fmtNum(best.fetches)}.`
        },
        {
          title: `Stability traces: ${stability.pass_traces ?? 0}/${stability.total_traces ?? 0}`,
          text: `Same-item pass traces and verifier-heavy records are surfaced for recording, not hidden behind a final answer only.`
        },
        {
          title: "Core architecture",
          text: "The model owns semantic decisions; the host validates schemas, executes tools, journals evidence, and verifies numeric support."
        }
      ];
    }
    function renderSpotlight() {
      if (!latestSpotlights.length) return;
      const row = latestSpotlights[spotlightIndex % latestSpotlights.length] || {};
      text("spotlightStep", `${(spotlightIndex % latestSpotlights.length) + 1}/${latestSpotlights.length}`);
      text("spotlightTitle", row.title || "");
      text("spotlightText", row.text || "");
    }
    function renderDemoRuns(rows, activeRunPrefix, activeItemId) {
      document.getElementById("demoRuns").innerHTML = rows.map(row => {
        const statusClass = row.status === "complete" && row.failed ? "failed" : row.status === "complete" ? "ok" : row.status || "";
        const active = row.run_prefix === activeRunPrefix && String(row.item_id || "") === String(activeItemId || "") ? " active" : "";
        return `<button class="run-card${active}" data-run="${escapeHtml(row.run_prefix)}" title="${escapeHtml(row.question)}">
          <div class="run-status-line">
            <strong>${escapeHtml(row.label)}</strong>
            <span class="pill"><span class="dot ${escapeHtml(statusClass)}"></span>${escapeHtml(row.status || "waiting")}</span>
          </div>
          <div class="question-line">${escapeHtml(row.question)}</div>
          <div class="tiny">${escapeHtml(row.difficulty || "-")} | scored ${row.done ?? 0} | pass ${fmtPct(row.pass_rate)}</div>
          <div class="tiny">fetch ${fmtNum(row.fetches)} | calc ${fmtNum(row.calculator_calls)} | facts ${fmtNum(row.facts)}</div>
          <div class="tiny">${escapeHtml(row.latest_item_id || row.item_id || "")}</div>
        </button>`;
      }).join("");
      document.querySelectorAll(".run-card").forEach((button, index) => {
        button.addEventListener("click", () => selectRun(rows[index]));
      });
    }
    function renderBaselines(rows) {
      document.getElementById("baselines").innerHTML = rows.slice(0, 9).map(row => `
        <div class="baseline">
          <strong>${escapeHtml(row.label)}</strong>
          <div class="score">${fmtPct(row.pass_rate)}</div>
          <div class="tiny">items ${row.items ?? "-"} | pass ${fmtPct(row.pass_rate)} | judge ${fmtPct(row.reasonable)}</div>
          <div class="tiny">workflow ${fmtPct(row.workflow)} | numeric ${fmtPct(row.numeric)}</div>
        </div>`).join("");
    }
    function renderPipeline(rows) {
      document.getElementById("pipeline").innerHTML = rows.map(row => `
        <div class="stage ${escapeHtml(row.state)}">
          <div><div class="name">${escapeHtml(row.label)}</div><div class="tiny">${escapeHtml(row.detail)}</div></div>
          <div class="num">${fmtNum(row.value)}</div>
        </div>`).join("");
    }
    function renderIntel(rows) {
      document.getElementById("intel").innerHTML = rows.map(row => `
        <div class="intel">
          <div class="label">${escapeHtml(row.label)}</div>
          <div class="state">${escapeHtml(row.state)}</div>
          <div class="detail">${escapeHtml(row.detail)}</div>
        </div>`).join("");
    }
    function renderEvents(rows) {
      const recent = rows.slice(-10).reverse();
      document.getElementById("events").innerHTML = recent.map(row => {
        const desc = row.query || row.uri || row.title || row.reason || row.task_type || "";
        return `<div class="event"><div class="kind">${escapeHtml(row.kind)}</div><div class="state">${escapeHtml(row.status || "")}</div><div class="desc">${escapeHtml(desc)}</div></div>`;
      }).join("");
    }
    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
    }
    refresh();
    setInterval(() => {
      if (!latestSpotlights.length) return;
      spotlightIndex = (spotlightIndex + 1) % latestSpotlights.length;
      renderSpotlight();
    }, 4500);
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
