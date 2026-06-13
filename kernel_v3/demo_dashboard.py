from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
import uuid
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
    "chat_turn",
    "chat_routing_decision",
    "processor_request",
    "processor_result",
    "semantic_intake",
    "compiled_task_program",
    "policy_decision",
    "toolchain_step_proposed",
    "retrieval_query_plan",
    "retrieval_search_attempt",
    "retrieval_fetch",
    "retrieval_fetch_attempt",
    "retrieval_extraction",
    "retrieval_evidence",
    "retrieval_citation",
    "retrieval_report",
    "retrieval_evaluation",
    "retrieval_evidence_rejections",
    "retrieval_workbench_decision",
    "claim_ledger",
    "slot_frame",
    "transform_plan",
    "finance_numeric_judge",
    "verifier_gate_result",
    "synthesis_gate_result",
    "action",
    "observation",
    "feedback",
    "termination_decision",
    "agent_final_answer",
    "agent_failure_report",
    "chat_agent_result",
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
        self.command_runs: dict[str, Json] = {}
        self.command_lock = threading.Lock()


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
            console_thread = _query_value(query, "console_thread") or "demo-ui-live"
            thread_prefix = _query_value(query, "thread_prefix")
            if thread_prefix is None:
                mapped_thread_prefix = _thread_prefix_for_run(run_prefix)
                thread_prefix = mapped_thread_prefix if mapped_thread_prefix is not None else self.server.thread_prefix
            self._send_json(
                build_state(
                    self.server.root,
                    run_prefix,
                    thread_prefix,
                    item_id=item_id,
                    console_thread_id=console_thread,
                    command_runs=_command_runs_snapshot(self.server),
                )
            )
            return
        if parsed.path == "/api/live":
            query = parse_qs(parsed.query, keep_blank_values=True)
            console_thread = _safe_thread_id(_query_value(query, "console_thread") or "demo-ui-live")
            self._stream_live_events(console_thread)
            return
        if parsed.path == "/workflow":
            workflow = self.server.root / ".state/kernel_v3/visuals/kernel_v3_live_demo_task902.html"
            self._send_file(workflow, "text/html; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/command":
            payload = self._read_json_body(max_bytes=24_000)
            message = str(payload.get("message") or "").strip()
            if not message:
                self._send_json({"status": "error", "error": "empty_message"})
                return
            if len(message) > 12_000:
                self._send_json({"status": "error", "error": "message_too_large"})
                return
            thread_id = _safe_thread_id(str(payload.get("thread_id") or "demo-ui-live"))
            profile = str(payload.get("profile") or "quality")
            run_id = f"ui-{uuid.uuid4().hex[:10]}"
            record: Json = {
                "run_id": run_id,
                "thread_id": thread_id,
                "message": clip(message, 1000),
                "status": "queued",
                "created_at": time.time(),
                "started_at": None,
                "finished_at": None,
                "returncode": None,
                "answer": "",
                "error": "",
                "profile": profile,
            }
            with self.server.command_lock:
                self.server.command_runs[run_id] = record
                _trim_command_runs(self.server.command_runs)
            worker = threading.Thread(
                target=_run_dashboard_command_guarded,
                args=(self.server, run_id, message, thread_id, profile),
                name=f"holo-dashboard-command-{run_id}",
                daemon=True,
            )
            worker.start()
            self._send_json({"status": "accepted", "run_id": run_id, "thread_id": thread_id})
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
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

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
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _read_json_body(self, *, max_bytes: int) -> Json:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > max_bytes:
            return {}
        try:
            raw = self.rfile.read(length)
            value = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _stream_live_events(self, thread_id: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        journal = self.server.root / ".state/kernel_v3/journal/global.jsonl"
        position = journal.stat().st_size if journal.exists() else 0
        allowed_task_ids: set[str] = set()
        allowed_run_ids: set[str] = set()
        turn_records: list[Json] = []
        closed = False
        last_heartbeat = time.time()
        if not self._write_sse("ready", {"thread_id": thread_id}):
            return
        while True:
            if time.time() - last_heartbeat > 10:
                if not self._write_sse("heartbeat", {"thread_id": thread_id, "at": time.time()}):
                    return
                last_heartbeat = time.time()
            if not journal.exists():
                time.sleep(0.15)
                continue
            try:
                with journal.open("r", encoding="utf-8", errors="ignore") as handle:
                    handle.seek(position)
                    while True:
                        line = handle.readline()
                        if not line:
                            position = handle.tell()
                            break
                        position = handle.tell()
                        try:
                            record = json.loads(line)
                        except Exception:
                            continue
                        if not isinstance(record, dict):
                            continue
                        direct = _record_matches_thread_prefix(record, thread_id)
                        if direct and record.get("kind") == "chat_turn":
                            allowed_task_ids.clear()
                            allowed_run_ids.clear()
                            turn_records.clear()
                            closed = False
                        if direct:
                            _add_record_scope_ids(record, allowed_task_ids=allowed_task_ids, allowed_run_ids=allowed_run_ids)
                        if not direct and not _live_record_in_scope(record, allowed_task_ids=allowed_task_ids, allowed_run_ids=allowed_run_ids):
                            continue
                        if closed and not (direct and record.get("kind") == "chat_turn"):
                            continue
                        kind = str(record.get("kind") or "")
                        if kind not in RELEVANT_EVENT_KINDS:
                            continue
                        turn_records.append(record)
                        visible_turn = _records_until_terminal(turn_records)
                        closed = _has_terminal_record(visible_turn)
                        payload = {
                            "thread_id": thread_id,
                            "record": _public_flow_record(record),
                            "transcript": console_transcript(visible_turn, []),
                            "topology": loop_topology_state(visible_turn),
                            "search_branches": search_branch_state(visible_turn),
                            "stats": _console_trace_stats(visible_turn, thread_records=len(turn_records)),
                            "closed": closed,
                        }
                        if closed:
                            payload["runtime_console"] = runtime_console_state(visible_turn, None)
                        if not self._write_sse("journal", payload):
                            return
            except BrokenPipeError:
                return
            except Exception as exc:
                if not self._write_sse("stream_error", {"thread_id": thread_id, "error": clip(f"{type(exc).__name__}: {exc}", 400)}):
                    return
                time.sleep(0.5)
            time.sleep(0.05)

    def _write_sse(self, event: str, payload: Json) -> bool:
        try:
            body = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}\n\n"
            self.wfile.write(body.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False


def _command_runs_snapshot(server: DashboardServer) -> list[Json]:
    with server.command_lock:
        return [dict(item) for item in server.command_runs.values()]


def _trim_command_runs(command_runs: dict[str, Json], *, limit: int = 12) -> None:
    if len(command_runs) <= limit:
        return
    ordered = sorted(command_runs.values(), key=lambda item: float(item.get("created_at") or 0), reverse=True)
    keep = {str(item.get("run_id") or "") for item in ordered[:limit]}
    for key in list(command_runs):
        if key not in keep:
            command_runs.pop(key, None)


def _run_dashboard_command(server: DashboardServer, run_id: str, message: str, thread_id: str, profile: str) -> None:
    _update_command_run(server, run_id, status="running", started_at=time.time())
    mode = profile if profile in {"auto", "fast", "balanced", "quality", "finance_deep"} else "auto"
    cmd = [
        str(server.root / "holo-v3"),
        "chat",
        "--thread",
        thread_id,
        "--once",
        message,
        "--output",
        "json",
        "--planner",
        "model",
        "--evaluator",
        "model",
        "--synthesizer",
        "model",
        "--semantic-intake",
        "model",
        "--turn-router",
        "model",
        "--profile",
        "quality" if mode == "finance_deep" else ("balanced" if mode == "auto" else mode),
        "--response-language",
        "english",
        "--generation-mode",
        "auto",
    ]
    if mode == "finance_deep":
        cmd.extend(
            [
                "--reasoning-effort",
                "high",
                "--live-retrieval",
                "--live-max-network-fetches",
                "96",
                "--research-depth",
                "deep",
                "--max-agent-steps",
                "8",
                "--max-agent-tool-calls",
                "14",
            ]
        )
    else:
        cmd.extend(
            [
                "--reasoning-effort",
                "medium",
                "--latency-target",
                "balanced",
                "--max-output-tokens",
                "1600",
                "--max-agent-steps",
                "4",
                "--max-agent-tool-calls",
                "4",
                "--no-live-retrieval",
            ]
        )
    env = _dashboard_command_env()
    if not env.get("DEEPSEEK_API_KEY"):
        _update_command_run(
            server,
            run_id,
            status="blocked",
            finished_at=time.time(),
            returncode=1,
            error='{"reason":"live_model_not_enabled","status":"blocked","message":"DEEPSEEK_API_KEY is not visible to the WSL dashboard process."}',
        )
        return
    try:
        proc = subprocess.run(
            cmd,
            cwd=server.root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=900,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _update_command_run(
            server,
            run_id,
            status="timeout",
            finished_at=time.time(),
            returncode=None,
            error=clip(str(exc), 1200),
        )
        return
    except Exception as exc:
        _update_command_run(
            server,
            run_id,
            status="error",
            finished_at=time.time(),
            returncode=None,
            error=clip(str(exc), 1200),
        )
        return
    answer = ""
    status = "complete" if proc.returncode == 0 else "failed"
    parsed = _parse_last_json_object(proc.stdout)
    if parsed:
        answer = _chat_payload_answer(parsed)
        payload_status = str(parsed.get("status") or "")
        if payload_status in {"failed", "blocked"}:
            status = payload_status
    error = proc.stderr.strip() or (proc.stdout.strip() if proc.returncode != 0 and not answer else "")
    _update_command_run(
        server,
        run_id,
        status=status,
        finished_at=time.time(),
        returncode=proc.returncode,
        answer=clip(answer, 1600),
        error=clip(error, 1600),
        effective_profile=mode,
    )


def _run_dashboard_command_guarded(server: DashboardServer, run_id: str, message: str, thread_id: str, profile: str) -> None:
    try:
        _run_dashboard_command(server, run_id, message, thread_id, profile)
    except Exception as exc:
        _update_command_run(
            server,
            run_id,
            status="error",
            finished_at=time.time(),
            returncode=None,
            error=clip(f"{type(exc).__name__}: {exc}", 1600),
        )


def _update_command_run(server: DashboardServer, run_id: str, **updates: Any) -> None:
    with server.command_lock:
        current = dict(server.command_runs.get(run_id) or {"run_id": run_id})
        current.update(updates)
        server.command_runs[run_id] = current


def _dashboard_command_env() -> dict[str, str]:
    env = dict(os.environ)
    if not env.get("DEEPSEEK_API_KEY"):
        key = _read_windows_env("DEEPSEEK_API_KEY")
        if key:
            env["DEEPSEEK_API_KEY"] = key
    return env


def _read_windows_env(name: str) -> str:
    powershell = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if not powershell.exists():
        return ""
    script = (
        f"$v=[Environment]::GetEnvironmentVariable('{name}','User');"
        f"if(-not $v){{$v=[Environment]::GetEnvironmentVariable('{name}','Machine')}};"
        "if($v){[Console]::Out.Write($v)}"
    )
    try:
        proc = subprocess.run(
            [str(powershell), "-NoProfile", "-Command", script],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""
    value = proc.stdout.strip()
    return value if value and "%" not in value and "\n" not in value else ""


def _parse_last_json_object(text: str) -> Json:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _chat_payload_answer(payload: Json) -> str:
    for key in ("answer", "text", "message"):
        if payload.get(key):
            return clip(payload.get(key), 1600)
    final = payload.get("final_answer")
    if isinstance(final, dict):
        for key in ("answer", "text", "result"):
            if final.get(key):
                return clip(final.get(key), 1600)
    failure = payload.get("failure_report")
    if isinstance(failure, dict):
        return clip(failure.get("reason") or failure.get("summary") or json.dumps(failure, ensure_ascii=True), 1600)
    return ""


def _safe_thread_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned[:96] or "demo-ui-live"


def build_state(
    root: Path,
    run_prefix: str,
    thread_prefix: str = "",
    *,
    item_id: str = "",
    console_thread_id: str = "demo-ui-live",
    command_runs: list[Json] | None = None,
) -> Json:
    now = time.time()
    bench_dir = root / ".state/kernel_v3/bench/finance"
    journal = root / ".state/kernel_v3/journal/global.jsonl"
    result_path = bench_dir / f"{run_prefix}.jsonl"
    summary_path = bench_dir / f"{run_prefix}.summary.json"
    reasonable_path = bench_dir / f"{run_prefix}.reasonable.json"
    result_records = read_jsonl(result_path, max_bytes=8_000_000, max_records=200)
    summary = read_json(summary_path)
    reasonable = read_json(reasonable_path)
    journal_records = read_jsonl(journal, max_bytes=20_000_000, max_records=3_000)
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
        "workspace": workspace_state(root, console_thread_id),
        "current": current,
        "console": console_state(journal_records, console_thread_id, command_runs or []),
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
            "console_thread": console_thread_id,
        },
    }


def console_state(records: list[Json], thread_id: str, command_runs: list[Json]) -> Json:
    thread_id = _safe_thread_id(thread_id)
    scoped = _records_for_thread_scope(records, thread_id)
    turn_records = _latest_turn_records(scoped)
    visible_turn = _records_until_terminal(turn_records)
    runs = [dict(item) for item in command_runs if str(item.get("thread_id") or "") == thread_id]
    runs.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
    active = next((item for item in runs if item.get("status") in {"queued", "running"}), runs[0] if runs else {})
    return {
        "thread_id": thread_id,
        "job": active,
        "transcript": console_transcript(scoped, runs),
        "topology": loop_topology_state(visible_turn),
        "search_branches": search_branch_state(visible_turn),
        "runtime_console": runtime_console_state(visible_turn, active),
        "stats": _console_trace_stats(visible_turn, thread_records=len(scoped)),
        "notice": "Current turn runtime context: model packets, prompt/contract previews, structured outputs, tools, evidence, verifier gates, and answers.",
    }


def _console_trace_stats(records: list[Json], *, thread_records: int) -> Json:
    return {
        "records": len(records),
        "thread_records": thread_records,
        "actions": sum(1 for record in records if record.get("kind") == "action"),
        "searches": sum(1 for record in records if record.get("kind") == "retrieval_search_attempt"),
        "fetches": sum(1 for record in records if record.get("kind") in {"retrieval_fetch", "retrieval_fetch_attempt"}),
        "evidence": sum(
            1
            for record in records
            if record.get("kind") in {"retrieval_evidence", "claim_ledger", "slot_frame"}
        ),
        "closed": _has_terminal_record(records),
    }


def _public_flow_record(record: Json) -> Json:
    kind = str(record.get("kind") or "")
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    event: Json = {
        "kind": kind,
        "record_id": record.get("record_id"),
        "task_id": record.get("task_id") or data.get("task_id") or "",
        "run_id": record.get("run_id") or data.get("run_id") or "",
        "step_id": record.get("step_id") or data.get("step_id") or "",
        "at": record.get("recorded_at_ms"),
        "stage": _stage_for_kind(kind),
        "title": _activity_title(kind, data),
        "status": _activity_status(kind, data),
        "detail": _activity_detail(kind, data),
    }
    if kind == "processor_request":
        params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
        prompt = data.get("prompt") if isinstance(data.get("prompt"), dict) else {}
        event.update(
            {
                "processor": data.get("task_type") or data.get("processor") or "",
                "provider": data.get("provider") or params.get("provider") or "",
                "model": data.get("model") or params.get("model") or "",
                "prompt_chars": prompt.get("chars"),
                "prompt_hash": prompt.get("hash"),
                "body": clip(prompt.get("preview") or "", 1200),
            }
        )
    elif kind == "processor_result":
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        output = data.get("output") if isinstance(data.get("output"), dict) else {}
        event.update(
            {
                "processor": data.get("task_type") or data.get("processor") or "",
                "provider": data.get("provider") or "",
                "model": data.get("model") or "",
                "duration_ms": data.get("duration_ms"),
                "tokens": usage.get("total_tokens"),
                "body": _processor_output_body(output, data.get("error")),
            }
        )
    elif kind == "retrieval_search_attempt":
        diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
        event.update(
            {
                "query": clip(data.get("query") or data.get("goal"), 180),
                "source_count": diagnostics.get("journaled_source_count") or len(data.get("sources") or []),
            }
        )
    elif kind in {"retrieval_fetch", "retrieval_fetch_attempt"}:
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        event.update({"uri": clip(data.get("uri") or source.get("uri"), 220)})
    return event


def runtime_console_state(records: list[Json], active_job: Json | None = None) -> list[Json]:
    rows: list[Json] = []
    if active_job and active_job.get("status") in {"queued", "running"} and not records:
        rows.append(
            {
                "kind": "dashboard_job",
                "stage": "run",
                "level": "active",
                "line": f"$ holo-v3 chat --thread {active_job.get('thread_id')} --once ...",
                "body": clip(active_job.get("message"), 700),
                "at": int(float(active_job.get("started_at") or active_job.get("created_at") or time.time()) * 1000),
            }
        )
    for record in records:
        item = _runtime_console_record(record)
        if item:
            rows.append(item)
    return rows[-160:]


def _runtime_console_record(record: Json) -> Json:
    kind = str(record.get("kind") or "")
    if kind not in RELEVANT_EVENT_KINDS:
        return {}
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    at = int(record.get("recorded_at_ms") or 0)
    stage = _stage_for_kind(kind).lower()
    status = _activity_status(kind, data)
    title = _activity_title(kind, data) or kind.replace("_", ".")
    line = f"[{stage}] {title}"
    body = _activity_detail(kind, data)
    level = "active" if kind == "processor_request" else "ok"

    if kind == "chat_turn":
        line = "$ user"
        body = clip(data.get("text"), 1200)
    elif kind in {"processor_request", "processor_result"}:
        processor = data.get("task_type") or data.get("processor") or "processor"
        if kind == "processor_request":
            params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
            prompt = data.get("prompt") if isinstance(data.get("prompt"), dict) else {}
            provider = data.get("provider") or params.get("provider") or "provider"
            model = data.get("model") or params.get("model") or "model"
            line = f"[model:request] {processor} :: {provider}/{model} :: {prompt.get('chars', 0)} chars :: {str(prompt.get('hash') or '')[:10]}"
            body = clip(prompt.get("preview") or "", 1600)
        else:
            output = data.get("output") if isinstance(data.get("output"), dict) else {}
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            line = f"[model:result] {processor} :: {data.get('status') or 'result'} :: {data.get('duration_ms') or 0} ms :: {usage.get('total_tokens', '-')} tokens"
            body = _processor_output_body(output, data.get("error"))
            level = "failed" if data.get("status") not in {None, "", "ok", "complete", "success"} and data.get("error") else "ok"
    elif kind in {"action", "toolchain_step_proposed"}:
        name = data.get("name") or data.get("kind") or data.get("tool") or "tool"
        line = f"[tool:call] {name}"
        body = _runtime_json_body(data, keys=("arguments", "payload", "input", "description", "reason"))
        level = "active"
    elif kind == "policy_decision":
        line = f"[policy] allowed={data.get('allowed')}"
        body = _runtime_json_body(data, keys=("reason", "violations", "action", "tool"))
        level = "ok" if data.get("allowed") is not False else "failed"
    elif kind == "observation":
        line = f"[tool:observation] {data.get('source') or data.get('kind') or 'observation'}"
        body = _runtime_json_body(data, keys=("summary", "result", "observation", "text", "error"))
        level = "failed" if data.get("error") else "ok"
    elif kind == "retrieval_query_plan":
        line = "[retrieval:plan]"
        body = _runtime_json_body(data, keys=("queries", "goal", "reason", "sources"))
    elif kind == "retrieval_search_attempt":
        diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
        source_count = diagnostics.get("journaled_source_count") or len(data.get("sources") or [])
        line = f"[retrieval:search] {source_count} sources :: {data.get('status') or 'ok'}"
        body = clip(data.get("query") or data.get("goal") or "", 1000)
    elif kind in {"retrieval_fetch", "retrieval_fetch_attempt"}:
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        line = f"[retrieval:fetch] {data.get('status') or 'fetch'}"
        body = clip(data.get("uri") or source.get("uri") or data.get("url") or "", 1200)
        level = "failed" if str(data.get("status") or "").lower() in {"failed", "error"} else "ok"
    elif kind == "retrieval_extraction":
        doc = data.get("document") if isinstance(data.get("document"), dict) else {}
        diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
        line = f"[retrieval:extract] spans={diagnostics.get('span_count', '-')}"
        body = clip(doc.get("title") or doc.get("uri") or "", 1200)
    elif kind in {"retrieval_evidence", "retrieval_citation", "claim_ledger", "slot_frame", "transform_plan"}:
        line = f"[evidence] {kind.replace('_', '.')}"
        body = _runtime_json_body(data, keys=("claim", "slot", "value", "metric", "citation", "source", "formula", "reason"))
    elif kind in {"finance_numeric_judge", "verifier_gate_result", "synthesis_gate_result"}:
        line = f"[verify] {kind.replace('_', '.')} :: {status or data.get('decision') or 'checked'}"
        body = _runtime_json_body(data, keys=("status", "decision", "reason", "issues", "numeric_status", "support_status"))
        level = "failed" if str(status).lower() in {"failed", "error", "blocked"} else "ok"
    elif kind in {"termination_decision", "feedback"}:
        line = f"[loop] {kind.replace('_', '.')} :: {status or data.get('decision') or ''}"
        body = _runtime_json_body(data, keys=("reason", "stop_reason", "missing_evidence", "next_action", "feedback_status"))
    elif kind in {"agent_final_answer", "agent_failure_report", "chat_agent_result"}:
        line = f"[answer] {status or 'complete'}"
        body = clip(_chat_result_answer_text(data) if kind == "chat_agent_result" else _runtime_json_body(data), 1800)
        level = "failed" if kind == "agent_failure_report" or data.get("failure_report") else "ok"

    return {
        "kind": kind,
        "stage": stage,
        "level": level,
        "line": clip(line, 240),
        "body": clip(body, 1800),
        "at": at,
        "task_id": record.get("task_id") or data.get("task_id") or "",
        "step_id": record.get("step_id") or data.get("step_id") or "",
    }


def _runtime_json_body(data: Json, keys: tuple[str, ...] = ()) -> str:
    if keys:
        selected = {key: data.get(key) for key in keys if data.get(key) not in (None, "", [], {})}
        if selected:
            return clip(json.dumps(selected, ensure_ascii=True, sort_keys=True), 1600)
    return clip(json.dumps(data, ensure_ascii=True, sort_keys=True), 1600)


def workspace_state(root: Path, thread_id: str) -> Json:
    state_dir = root / ".state/kernel_v3"
    return {
        "root": str(root),
        "name": root.name,
        "thread_id": _safe_thread_id(thread_id),
        "branch": run_git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": run_git(root, "rev-parse", "--short", "HEAD"),
        "remote": run_git(root, "rev-parse", "--short", "github/kernel-v3"),
        "dirty": bool(run_git(root, "status", "--short")),
        "state_dir": str(state_dir.relative_to(root)) if state_dir.exists() else ".state/kernel_v3",
        "journal": ".state/kernel_v3/journal/global.jsonl",
    }


def _records_for_thread_scope(records: list[Json], thread_id: str) -> list[Json]:
    task_ids, run_ids = _thread_scoped_ids(records, thread_id)
    return [
        record
        for record in records
        if _record_in_thread_scope(record, thread_id, allowed_task_ids=task_ids, allowed_run_ids=run_ids)
    ]


def console_transcript(records: list[Json], runs: list[Json]) -> list[Json]:
    turns: list[Json] = []
    journal_user_texts: set[str] = set()
    journal_assistant_texts: set[str] = set()
    has_terminal = _has_terminal_record(_latest_turn_records(records))
    for record in records:
        kind = record.get("kind")
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        if kind == "chat_turn":
            journal_user_texts.add(str(data.get("text") or ""))
            turns.append(
                {
                    "role": "user",
                    "text": clip(data.get("text"), 1400),
                    "at": record.get("recorded_at_ms"),
                }
            )
        elif kind == "chat_agent_result":
            answer = clip(_chat_result_answer_text(data), 1800)
            journal_assistant_texts.add(answer)
            turns.append(
                {
                    "role": "assistant",
                    "text": answer,
                    "status": data.get("status") or ("failed" if data.get("failure_report") else "complete"),
                    "at": record.get("recorded_at_ms"),
                }
            )
    for run in reversed(runs[-8:]):
        message = str(run.get("message") or "")
        status = str(run.get("status") or "")
        if message and message not in journal_user_texts:
            turns.append(
                {
                    "role": "user",
                    "text": clip(message, 1400),
                    "status": status,
                    "at": int(float(run.get("created_at") or 0) * 1000),
                }
            )
        answer = str(run.get("answer") or "")
        error = str(run.get("error") or "")
        if status in {"queued", "running"}:
            turns.append(
                {
                    "role": "assistant",
                    "text": "Kernel v3 is running. Public model packets, tool calls, retrieval branches, and verifier gates will stream on the right as journal events arrive.",
                    "status": status,
                    "at": int(float(run.get("started_at") or run.get("created_at") or 0) * 1000),
                }
            )
        elif answer and answer not in journal_assistant_texts and (has_terminal or not records):
            turns.append(
                {
                    "role": "assistant",
                    "text": clip(answer, 1800),
                    "status": status,
                    "at": int(float(run.get("finished_at") or 0) * 1000),
                }
            )
        elif answer and answer not in journal_assistant_texts:
            turns.append(
                {
                    "role": "assistant",
                    "text": "Kernel process finished; synchronizing the final journal trace before displaying the answer.",
                    "status": "finalizing",
                    "at": int(float(run.get("finished_at") or 0) * 1000),
                }
            )
        elif error and not journal_assistant_texts:
            turns.append(
                {
                    "role": "assistant",
                    "text": clip(error, 1800),
                    "status": status or "error",
                    "at": int(float(run.get("finished_at") or 0) * 1000),
                }
            )
    turns.sort(key=lambda item: int(item.get("at") or 0))
    return turns[-12:]


def _latest_turn_records(records: list[Json]) -> list[Json]:
    if not records:
        return []
    start = 0
    for index, record in enumerate(records):
        if record.get("kind") == "chat_turn":
            start = index
    return records[start:]


def _records_until_terminal(records: list[Json]) -> list[Json]:
    for index, record in enumerate(records):
        if _is_terminal_record(record):
            return records[: index + 1]
    return records


def _has_terminal_record(records: list[Json]) -> bool:
    return any(_is_terminal_record(record) for record in records)


def _is_terminal_record(record: Json) -> bool:
    kind = record.get("kind")
    if kind in {"agent_final_answer", "agent_failure_report", "chat_agent_result"}:
        return True
    return False


def _chat_result_answer_text(data: Json) -> str:
    for key in ("answer", "text", "message"):
        if data.get(key):
            return str(data.get(key) or "")
    final = data.get("final_answer") if isinstance(data.get("final_answer"), dict) else {}
    for key in ("answer", "text", "result"):
        if final.get(key):
            return str(final.get(key) or "")
    failure = data.get("failure_report") if isinstance(data.get("failure_report"), dict) else {}
    if failure:
        return str(failure.get("reason") or failure.get("stop_reason") or "The run ended with a failure report.")
    return ""


def loop_topology_state(records: list[Json]) -> list[Json]:
    groups = [
        ("Intake", {"chat_turn", "chat_routing_decision", "semantic_intake", "compiled_task_program"}, "understand task"),
        ("Plan", {"processor_request", "processor_result", "action", "toolchain_step_proposed"}, "LLM proposes next move"),
        ("Policy", {"policy_decision"}, "host validates action"),
        ("Tools", {"observation", "retrieval_fetch", "retrieval_fetch_attempt"}, "execute bounded tools"),
        ("Search", {"retrieval_query_plan", "retrieval_search_attempt", "retrieval_workbench_decision"}, "branch over sources"),
        ("Evidence", {"retrieval_extraction", "retrieval_evidence", "retrieval_citation", "claim_ledger", "slot_frame"}, "build cited ledger"),
        ("Verify", {"transform_plan", "finance_numeric_judge", "verifier_gate_result", "synthesis_gate_result"}, "check numbers and support"),
        ("Answer", {"termination_decision", "feedback", "agent_final_answer", "agent_failure_report", "chat_agent_result"}, "reply or explain gap"),
    ]
    latest_kind = str(records[-1].get("kind") or "") if records else ""
    terminal = _has_terminal_record(records)
    has_failure = any(
        record.get("kind") in {"agent_failure_report"}
        or (record.get("kind") == "chat_agent_result" and isinstance(record.get("data"), dict) and record["data"].get("failure_report"))
        for record in records
    )
    rows: list[Json] = []
    for label, kinds, detail in groups:
        count = sum(1 for record in records if record.get("kind") in kinds)
        state = "idle"
        if count:
            state = "active" if latest_kind in kinds and not terminal else "ok"
        if terminal and label == "Answer" and count and not has_failure:
            state = "closed"
        if has_failure and label in {"Verify", "Answer"} and count:
            state = "warn"
        row = stage(label, state, count, detail)
        row["last_at"] = max((int(record.get("recorded_at_ms") or 0) for record in records if record.get("kind") in kinds), default=0)
        rows.append(row)
    return rows


def loop_flow_state(records: list[Json], active_job: Json | None = None) -> list[Json]:
    rows: list[Json] = []
    if active_job and active_job.get("status") in {"queued", "running"} and not records:
        rows.append(
            {
                "stage": "Run",
                "title": "Start",
                "kind": "dashboard_job",
                "status": str(active_job.get("status") or "running"),
                "detail": f"thread {active_job.get('thread_id')}",
                "at": int(float(active_job.get("started_at") or active_job.get("created_at") or time.time()) * 1000),
            }
        )
    for record in records:
        kind = str(record.get("kind") or "")
        if kind not in RELEVANT_EVENT_KINDS:
            continue
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        title = _activity_title(kind, data)
        if not title:
            continue
        rows.append(
            {
                "stage": _stage_for_kind(kind),
                "title": _short_event_title(kind, data, title),
                "kind": kind,
                "status": _activity_status(kind, data) or ("request" if kind == "processor_request" else ""),
                "detail": _activity_detail(kind, data),
                "at": int(record.get("recorded_at_ms") or 0),
                "step_id": record.get("step_id") or data.get("step_id") or "",
                "task_id": record.get("task_id") or data.get("task_id") or "",
            }
        )
    return rows[-36:]


def _stage_for_kind(kind: str) -> str:
    if kind in {"chat_turn", "chat_routing_decision", "semantic_intake", "compiled_task_program"}:
        return "Intake"
    if kind in {"processor_request", "processor_result", "action", "toolchain_step_proposed"}:
        return "Plan"
    if kind == "policy_decision":
        return "Policy"
    if kind in {"observation", "retrieval_fetch", "retrieval_fetch_attempt"}:
        return "Tools"
    if kind in {"retrieval_query_plan", "retrieval_search_attempt", "retrieval_workbench_decision"}:
        return "Search"
    if kind in {"retrieval_extraction", "retrieval_evidence", "retrieval_citation", "claim_ledger", "slot_frame"}:
        return "Evidence"
    if kind in {"transform_plan", "finance_numeric_judge", "verifier_gate_result", "synthesis_gate_result"}:
        return "Verify"
    if kind in {"termination_decision", "feedback", "agent_final_answer", "agent_failure_report", "chat_agent_result"}:
        return "Answer"
    return "Run"


def _short_event_title(kind: str, data: Json, fallback: str) -> str:
    if kind == "processor_request":
        return f"LLM request: {data.get('task_type') or data.get('processor') or 'processor'}"
    if kind == "processor_result":
        return f"LLM result: {data.get('task_type') or 'processor'}"
    if kind == "retrieval_search_attempt":
        return "Search"
    if kind in {"retrieval_fetch", "retrieval_fetch_attempt"}:
        return "Fetch"
    if kind in {"retrieval_extraction", "retrieval_evidence", "retrieval_citation"}:
        return "Evidence"
    if kind in {"claim_ledger", "slot_frame"}:
        return "Ledger"
    if kind in {"finance_numeric_judge", "verifier_gate_result", "synthesis_gate_result"}:
        return "Gate"
    if kind in {"chat_agent_result", "agent_final_answer"}:
        return "Answer"
    return clip(fallback, 48)


def search_branch_state(records: list[Json]) -> list[Json]:
    rows: list[Json] = []
    for index, record in enumerate([r for r in records if r.get("kind") == "retrieval_search_attempt"], start=1):
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
        attempts = (
            diagnostics.get("provider_diagnostics", {}).get("attempts")
            if isinstance(diagnostics.get("provider_diagnostics"), dict)
            else []
        )
        providers: list[str] = []
        accepted = 0
        sources = 0
        query_hash = ""
        if isinstance(attempts, list):
            for attempt in attempts[:6]:
                if not isinstance(attempt, dict):
                    continue
                provider = str(attempt.get("provider_id") or "provider")
                count = int(attempt.get("accepted_source_count") or attempt.get("source_count") or 0)
                accepted += int(attempt.get("accepted_source_count") or 0)
                sources += int(attempt.get("source_count") or 0)
                ad = attempt.get("diagnostics") if isinstance(attempt.get("diagnostics"), dict) else {}
                query_hash = query_hash or str(ad.get("query_hash") or "")[:10]
                providers.append(f"{provider}:{count}")
        rows.append(
            {
                "index": index,
                "step_id": record.get("step_id") or "",
                "query": clip(data.get("query") or data.get("goal") or f"search branch {index}", 180),
                "status": data.get("status") or diagnostics.get("status") or "ok",
                "sources": sources or diagnostics.get("journaled_source_count") or 0,
                "accepted": accepted,
                "query_hash": query_hash,
                "providers": providers,
            }
        )
    return rows[-12:]


def model_io_stream_state(records: list[Json]) -> list[Json]:
    calls: list[Json] = []
    by_request: dict[str, Json] = {}

    def ensure_call(request_id: str, *, data: Json, record: Json) -> Json:
        key = request_id or f"record-{record.get('record_id') or len(calls)}"
        existing = by_request.get(key)
        if existing is not None:
            return existing
        task_type = str(data.get("task_type") or data.get("processor") or "model.processor")
        params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
        call = {
            "request_id": request_id,
            "phase": _processor_phase(task_type),
            "title": task_type,
            "processor": str(data.get("processor") or task_type),
            "model": str(data.get("model") or params.get("model") or ""),
            "provider": str(data.get("provider") or params.get("provider") or ""),
            "status": "requested",
            "meta": _processor_meta(data),
            "task_id": record.get("task_id") or data.get("task_id") or "",
            "step_id": record.get("step_id") or data.get("step_id") or "",
            "children": [],
        }
        by_request[key] = call
        calls.append(call)
        return call

    for record in records:
        kind = record.get("kind")
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        if kind == "processor_request":
            params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
            prompt = data.get("prompt") if isinstance(data.get("prompt"), dict) else {}
            call = ensure_call(str(data.get("request_id") or ""), data=data, record=record)
            call["model"] = str(data.get("model") or params.get("model") or call.get("model") or "")
            call["provider"] = str(data.get("provider") or params.get("provider") or call.get("provider") or "")
            call["meta"] = _processor_meta(data)
            call["children"].append(
                {
                    "kind": "input",
                    "label": "Input contract",
                    "meta": f"{prompt.get('chars', 0)} chars | hash {str(prompt.get('hash') or '')[:10]}",
                    "body": clip(prompt.get("preview") or data.get("prompt") or "", 1500),
                    "status": "request",
                }
            )
        elif kind == "processor_result":
            output = data.get("output") if isinstance(data.get("output"), dict) else {}
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            call = ensure_call(str(data.get("request_id") or ""), data=data, record=record)
            call["status"] = str(data.get("status") or "result")
            call["model"] = str(data.get("model") or output.get("model") or call.get("model") or "")
            call["provider"] = str(data.get("provider") or output.get("provider") or call.get("provider") or "")
            call["meta"] = _processor_meta(data, usage=usage)
            call["children"].append(
                {
                    "kind": "output",
                    "label": "Structured output",
                    "meta": f"{data.get('duration_ms') or 0} ms | {usage.get('total_tokens', '-')} tokens",
                    "body": _processor_output_body(output, data.get("error")),
                    "status": str(data.get("status") or "result"),
                }
            )
    for call in calls:
        children = call.get("children") if isinstance(call.get("children"), list) else []
        call["child_count"] = len(children)
        call["summary"] = _processor_call_summary(call)
    return calls[-9:]


def _processor_phase(task_type: str) -> str:
    task = task_type.lower()
    if "route" in task or "semantic" in task or "intake" in task:
        return "Intake"
    if "retrieval" in task or "workbench" in task or "search" in task:
        return "Search"
    if "judge" in task or "verifier" in task or "gate" in task:
        return "Verify"
    if "synth" in task or "answer" in task or "final" in task:
        return "Answer"
    if "evaluator" in task or "assess" in task or "plan" in task:
        return "Plan"
    return "Model"


def _processor_meta(data: Json, usage: Json | None = None) -> str:
    params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
    parts = [
        str(data.get("provider") or params.get("provider") or ""),
        str(data.get("model") or params.get("model") or ""),
    ]
    if data.get("duration_ms") is not None:
        parts.append(f"{data.get('duration_ms')} ms")
    if usage:
        parts.append(f"{usage.get('total_tokens', '-')} tokens")
    if params.get("thinking"):
        parts.append(f"thinking {params.get('thinking')}")
    if params.get("latency_target"):
        parts.append(f"latency {params.get('latency_target')}")
    return " | ".join(part for part in parts if part)


def _processor_output_body(output: Json, error: object) -> str:
    if error:
        message = output.get("error_message_preview") if isinstance(output, dict) else ""
        return clip(f"error: {error}\n{message}", 900)
    parsed = output.get("parsed") if isinstance(output, dict) else None
    if isinstance(parsed, dict):
        lines: list[str] = []
        for key in (
            "status",
            "next_action",
            "answer",
            "missing_slots",
            "filled_slots",
            "missing_evidence",
            "used_evidence",
            "citation_refs",
            "confidence",
            "limitations",
            "stop_reason",
        ):
            if key not in parsed or parsed.get(key) in (None, "", []):
                continue
            value = parsed.get(key)
            if not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=True, sort_keys=True)
            lines.append(f"{key}: {clip(value, 360)}")
        if lines:
            return clip("\n".join(lines), 1100)
        return clip(json.dumps(parsed, ensure_ascii=True, sort_keys=True), 1800)
    body = output.get("raw_output_preview") if isinstance(output, dict) else ""
    if not isinstance(body, str):
        body = json.dumps(body, ensure_ascii=True, sort_keys=True)
    return clip(body, 1600)


def _processor_call_summary(call: Json) -> str:
    children = call.get("children") if isinstance(call.get("children"), list) else []
    labels = [str(child.get("label") or child.get("kind") or "") for child in children if isinstance(child, dict)]
    return " -> ".join(label for label in labels if label) or str(call.get("title") or "")


def public_activity_state(records: list[Json], active_job: Json | None = None) -> list[Json]:
    rows: list[Json] = []
    if active_job and active_job.get("status") in {"queued", "running"}:
        rows.append(
            {
                "kind": "dashboard_job",
                "title": "Kernel process running",
                "detail": f"thread {active_job.get('thread_id')}; command submitted through browser console",
                "status": str(active_job.get("status") or "running"),
                "task_id": "",
                "step_id": str(active_job.get("run_id") or ""),
            }
        )
    for record in records:
        kind = str(record.get("kind") or "")
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        title = _activity_title(kind, data)
        if not title:
            continue
        rows.append(
            {
                "kind": kind,
                "title": title,
                "detail": _activity_detail(kind, data),
                "status": _activity_status(kind, data),
                "task_id": record.get("task_id") or data.get("task_id") or "",
                "step_id": record.get("step_id") or data.get("step_id") or "",
            }
        )
    return rows[-40:]


def _activity_title(kind: str, data: Json) -> str:
    if kind == "chat_turn":
        return "User command"
    if kind == "chat_routing_decision":
        return f"Route: {data.get('route') or 'new_task'}"
    if kind == "processor_request":
        return f"Model packet: {data.get('task_type') or data.get('processor') or 'processor'}"
    if kind == "processor_result":
        return f"Model result: {data.get('task_type') or 'processor'}"
    if kind == "semantic_intake":
        return "Semantic intake"
    if kind == "compiled_task_program":
        return "Task program compiled"
    if kind == "action":
        return f"Action: {data.get('name') or data.get('kind') or 'tool'}"
    if kind == "policy_decision":
        return "Policy gate"
    if kind == "observation":
        return f"Observation: {data.get('source') or data.get('kind') or 'tool'}"
    if kind == "retrieval_search_attempt":
        return "Search branch"
    if kind in {"retrieval_fetch", "retrieval_fetch_attempt"}:
        return "Fetch source"
    if kind == "retrieval_extraction":
        return "Extract evidence"
    if kind == "retrieval_workbench_decision":
        return "LLM workbench judgment"
    if kind in {"claim_ledger", "slot_frame", "transform_plan"}:
        return kind.replace("_", " ").title()
    if kind in {"finance_numeric_judge", "verifier_gate_result", "synthesis_gate_result"}:
        return kind.replace("_", " ").title()
    if kind == "termination_decision":
        return f"Termination: {data.get('decision') or 'continue'}"
    if kind == "feedback":
        return f"Feedback: {data.get('status') or 'status'}"
    if kind == "chat_agent_result":
        return "Assistant reply"
    return kind.replace("_", " ").title() if kind else ""


def _activity_detail(kind: str, data: Json) -> str:
    if kind == "chat_turn":
        return clip(data.get("text"), 180)
    if kind == "action":
        return clip(data.get("description") or data.get("payload"), 180)
    if kind in {"retrieval_fetch", "retrieval_fetch_attempt"}:
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        return clip(data.get("uri") or source.get("uri"), 180)
    if kind == "retrieval_extraction":
        doc = data.get("document") if isinstance(data.get("document"), dict) else {}
        return clip(doc.get("title") or doc.get("uri"), 180)
    if kind == "retrieval_search_attempt":
        diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
        return clip(data.get("query") or f"{diagnostics.get('journaled_source_count', 0)} sources considered", 180)
    if kind == "feedback":
        missing = data.get("missing_evidence")
        return clip(", ".join(str(item) for item in missing[:4]) if isinstance(missing, list) else data.get("stop_reason"), 180)
    if kind == "termination_decision":
        return clip(data.get("reason") or data.get("feedback_status"), 180)
    if kind == "chat_agent_result":
        return clip(_chat_result_answer_text(data), 180)
    return clip(data.get("reason") or data.get("status") or data.get("decision") or data.get("task_type"), 180)


def _activity_status(kind: str, data: Json) -> str:
    if kind == "processor_result":
        return str(data.get("status") or "")
    if kind == "policy_decision":
        return "allowed" if data.get("allowed") is True else str(data.get("status") or "")
    if kind == "chat_agent_result":
        return "failed" if data.get("failure_report") else "complete"
    return str(data.get("status") or data.get("decision") or "")


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
            source = data.get("source") if isinstance(data.get("source"), dict) else {}
            event.update(
                {
                    "uri": clip(data.get("uri") or source.get("uri"), 160),
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
        _add_record_scope_ids(record, allowed_task_ids=task_ids, allowed_run_ids=run_ids)
    return task_ids, run_ids


def _add_record_scope_ids(record: Json, *, allowed_task_ids: set[str], allowed_run_ids: set[str]) -> None:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    thread_id = _record_thread_id(record)
    for value in (record.get("task_id"), data.get("task_id")):
        if isinstance(value, str) and value:
            allowed_task_ids.add(value)
    for value in (record.get("run_id"), data.get("run_id")):
        if isinstance(value, str) and _is_thread_scoped_run_id(value, thread_id):
            allowed_run_ids.add(value)


def _is_thread_scoped_run_id(value: str, thread_id: str = "") -> bool:
    if not value:
        return False
    if value.startswith("chat-") or value.startswith("mission-"):
        return True
    return bool(thread_id and thread_id in value)


def _live_record_in_scope(record: Json, *, allowed_task_ids: set[str], allowed_run_ids: set[str]) -> bool:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    task_id = record.get("task_id") or data.get("task_id")
    run_id = record.get("run_id") or data.get("run_id")
    if isinstance(task_id, str) and task_id in allowed_task_ids:
        return True
    if isinstance(run_id, str) and run_id in allowed_run_ids:
        return True
    return False


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
    if isinstance(run_id, str) and run_id in allowed_run_ids:
        return True
    if isinstance(task_id, str) and task_id in allowed_task_ids:
        return True
    return False


def _record_thread_id(record: Json) -> str:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    for candidate in (record.get("thread_id"), data.get("thread_id"), data.get("thread_key")):
        if isinstance(candidate, str) and candidate:
            return candidate
    return ""


def _record_matches_thread_prefix(record: Json, thread_prefix: str) -> bool:
    return bool(thread_prefix and _record_thread_id(record).startswith(thread_prefix))


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
      --bg: #f3f4f2;
      --panel: #ffffff;
      --ink: #161a1d;
      --muted: #667085;
      --line: #d9dee5;
      --blue: #1d4ed8;
      --teal: #0f766e;
      --green: #15803d;
      --amber: #b45309;
      --red: #b91c1c;
      --slate: #344054;
      --soft: #f8fafc;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      height: 100vh;
      overflow: hidden;
      font-family: "Times New Roman", Times, serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      height: 72px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    h1 { margin: 0; font-size: 25px; font-weight: 700; letter-spacing: 0; }
    .sub { color: var(--muted); font-size: 14px; margin-top: 3px; }
    .top-actions { display: flex; gap: 8px; align-items: center; }
    button, a.button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 14px;
      font-family: "Times New Roman", Times, serif;
      text-decoration: none;
      cursor: pointer;
    }
    button.active { border-color: var(--blue); color: var(--blue); background: #f8fbff; }
    .grid {
      height: calc(100vh - 72px);
      display: grid;
      grid-template-columns: minmax(390px, 31%) minmax(0, 1fr);
      gap: 16px;
      padding: 16px;
      overflow: hidden;
    }
    .left, .right { min-height: 0; display: grid; gap: 16px; }
    .left { grid-template-rows: 318px 1fr; }
    .right { grid-template-rows: 262px 1fr 142px; }
    .panel {
      min-height: 0;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 16px;
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
      letter-spacing: 0;
    }
    .command-box {
      display: grid;
      grid-template-rows: 1fr auto auto;
      gap: 10px;
      height: calc(100% - 28px);
    }
    textarea.command-input {
      width: 100%;
      min-height: 96px;
      resize: none;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      font-family: "Times New Roman", Times, serif;
      font-size: 16px;
      line-height: 1.35;
      color: var(--ink);
      background: #fbfcfd;
      outline: none;
    }
    textarea.command-input:focus { border-color: var(--blue); box-shadow: inset 0 0 0 1px var(--blue); }
    .command-row { display: flex; gap: 8px; align-items: center; min-width: 0; }
    .command-row button.primary { background: var(--blue); border-color: var(--blue); color: #fff; }
    .command-row .thread { flex: 1; color: var(--muted); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .quick-prompts {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      max-height: 126px;
      overflow: auto;
      padding-right: 4px;
    }
    .quick-prompts button { padding: 7px 8px; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .transcript {
      height: calc(100% - 28px);
      display: grid;
      align-content: start;
      gap: 9px;
      overflow: hidden;
    }
    .message {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fff;
      min-width: 0;
    }
    .message.user { background: #f8fbff; border-color: #c8d8fb; }
    .message.assistant { background: #fbfcfd; }
    .message .role { color: var(--muted); font-size: 12px; text-transform: uppercase; font-weight: 700; margin-bottom: 4px; }
    .message .body {
      color: var(--slate);
      font-size: 15px;
      line-height: 1.38;
      max-height: 240px;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .hero-title {
      margin: 2px 0 8px;
      font-size: 22px;
      line-height: 1.1;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .hero-copy {
      height: 42px;
      margin-bottom: 12px;
      color: var(--slate);
      font-size: 15px;
      line-height: 1.38;
      overflow: hidden;
    }
    .hero-metric { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    .metric { border: 1px solid var(--line); border-radius: 6px; padding: 12px; min-width: 0; background: var(--soft); }
    .metric .value { font-size: 31px; line-height: 1; font-weight: 700; }
    .metric .label { margin-top: 7px; color: var(--muted); font-size: 13px; }
    .status { display: inline-flex; align-items: center; gap: 7px; font-size: 14px; color: var(--muted); }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
    .dot.ok { background: var(--green); }
    .dot.running, .dot.active { background: var(--blue); }
    .dot.warn { background: var(--amber); }
    .dot.failed { background: var(--red); }
    .progress { height: 8px; background: #e7ebf0; border-radius: 8px; overflow: hidden; margin-top: 12px; }
    .bar { height: 100%; width: 0%; background: var(--blue); }
    .cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .run-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
    .baseline { border: 1px solid var(--line); border-radius: 6px; padding: 10px; min-width: 0; }
    .baseline strong { display: block; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .baseline .score { font-size: 26px; font-weight: 700; margin: 8px 0 4px; color: var(--teal); }
    .run-card {
      display: grid;
      gap: 4px;
      text-align: left;
      min-width: 0;
      padding: 8px;
      border-radius: 6px;
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
      border-radius: 6px;
      padding: 7px 9px;
      min-width: 0;
      background: #fbfcfd;
    }
    .evidence-chip strong { display: block; font-size: 14px; line-height: 1; }
    .evidence-chip span { display: block; margin-top: 4px; font-size: 10px; color: var(--muted); }
    .spotlight {
      margin-top: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: var(--soft);
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
      font-size: 15px;
      font-weight: 700;
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
    .workflow-statement {
      height: 42px;
      margin-bottom: 12px;
      padding: 9px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      color: var(--slate);
      font-size: 15px;
      line-height: 1.35;
      overflow: hidden;
    }
    .pipeline { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 10px; height: calc(100% - 70px); }
    .stage {
      position: relative;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-width: 0;
      background: #fff;
    }
    .stage:not(:last-child)::after {
      content: ">";
      position: absolute;
      right: -9px;
      top: 50%;
      transform: translateY(-50%);
      color: #98a2b3;
      font-size: 14px;
      font-weight: 700;
      z-index: 2;
    }
    .stage-index { color: var(--muted); font-size: 12px; }
    .stage .name { font-weight: 700; font-size: 15px; }
    .stage .num { font-size: 25px; font-weight: 700; line-height: 1; }
    .stage.ok { border-color: #9fd4b1; }
    .stage.warn { border-color: #e5c07b; }
    .stage.active { border-color: #93b4f8; }
    .stage.idle { opacity: 0.72; }
    .tabs { display: none; height: 100%; min-height: 0; }
    .tabs.active { display: grid; }
    .console-view { grid-template-columns: 1fr 1fr; gap: 12px; min-height: 0; }
    .console-column { min-height: 0; display: grid; grid-template-rows: 28px 1fr; gap: 8px; }
    .column-title { color: var(--muted); font-size: 13px; font-weight: 700; text-transform: uppercase; }
    .branch-list, .activity-list {
      min-height: 0;
      display: grid;
      align-content: start;
      gap: 8px;
      overflow: hidden;
    }
    .branch, .activity {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fff;
      min-width: 0;
    }
    .branch-head, .activity-head { display: flex; justify-content: space-between; gap: 8px; min-width: 0; }
    .branch-title, .activity-title { font-size: 15px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .branch-status, .activity-status { color: var(--muted); font-size: 12px; white-space: nowrap; }
    .branch-detail, .activity-detail {
      margin-top: 5px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.32;
      max-height: 76px;
      overflow: auto;
      white-space: normal;
      overflow-wrap: anywhere;
    }
    .finance-view { grid-template-rows: 104px 1fr; gap: 12px; }
    .question {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      font-size: 16px;
      line-height: 1.45;
      overflow: hidden;
      color: var(--slate);
      background: #fbfcfd;
    }
    .question-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: 6px;
    }
    .question-text {
      font-size: 17px;
      line-height: 1.38;
      height: 50px;
      overflow: hidden;
    }
    .diag { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; min-height: 0; }
    .diag-block { border: 1px solid var(--line); border-radius: 6px; padding: 12px; overflow: hidden; background: #fff; }
    .diag-block h3 { margin: 0 0 8px; font-size: 17px; font-weight: 700; }
    .diag-block p { margin: 0; font-size: 15px; line-height: 1.45; color: var(--muted); }
    .intel-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; height: 100%; }
    .intel { border: 1px solid var(--line); border-radius: 6px; padding: 12px; overflow: hidden; background: #fff; }
    .intel .label { font-weight: 700; font-size: 16px; }
    .intel .state { margin-top: 6px; color: var(--teal); font-weight: 700; font-size: 14px; }
    .intel .detail { margin-top: 8px; color: var(--muted); font-size: 14px; line-height: 1.45; }
    .timeline { display: grid; gap: 7px; height: 100%; grid-auto-rows: minmax(30px, auto); overflow: hidden; }
    .event { display: grid; grid-template-columns: 150px 84px 1fr; gap: 10px; align-items: center; border-bottom: 1px solid #edf0f4; padding-bottom: 7px; min-width: 0; }
    .event div { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px; }
    .event .kind { font-weight: 700; color: var(--slate); }
    .event .state { color: var(--muted); }
    .event .desc { color: var(--muted); }
    .footer-grid { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 10px; }
    .mono { font-family: "Times New Roman", Times, serif; }
    .grid { grid-template-columns: minmax(500px, 44%) minmax(620px, 56%); }
    .left { grid-template-rows: 120px minmax(0, 1fr); }
    .right { grid-template-rows: minmax(0, 1fr); }
    .workspace-grid { display: grid; grid-template-columns: 1.2fr .8fr; gap: 10px; height: calc(100% - 28px); }
    .workspace-card {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      min-width: 0;
      background: #fbfcfd;
    }
    .workspace-card strong { display: block; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .workspace-card span { display: block; margin-top: 5px; color: var(--muted); font-size: 13px; overflow: auto; white-space: nowrap; text-overflow: ellipsis; }
    .chat-panel { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: 10px; }
    .chat-panel .transcript { height: auto; overflow: auto; padding-right: 4px; align-content: start; }
    .thread-tools {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 140px auto auto;
      gap: 8px;
      align-items: center;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
    }
    .thread-tools select {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fff;
      color: var(--ink);
      font-family: "Times New Roman", Times, serif;
      font-size: 14px;
    }
    .composer { display: grid; gap: 8px; border-top: 1px solid var(--line); padding-top: 10px; }
    .composer textarea.command-input { min-height: 92px; }
    .runtime-terminal {
      min-height: 0;
      display: grid;
      grid-template-rows: 28px minmax(0, 1fr);
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      padding: 10px;
      overflow: hidden;
    }
    .runtime-terminal-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      min-width: 0;
      color: var(--slate);
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .runtime-terminal-head span:last-child {
      color: var(--muted);
      font-size: 12px;
      font-weight: 400;
      text-transform: none;
      white-space: nowrap;
    }
    .runtime-console {
      min-height: 0;
      overflow: auto;
      padding-right: 6px;
      display: grid;
      align-content: start;
      gap: 7px;
      font-family: "Times New Roman", Times, serif;
      font-size: 13px;
      line-height: 1.28;
    }
    .console-line {
      display: grid;
      grid-template-columns: 118px minmax(0, 1fr);
      gap: 10px;
      padding: 6px 0;
      border-bottom: 1px solid #edf0f4;
      min-width: 0;
    }
    .console-line .console-time {
      color: var(--blue);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .console-main { min-width: 0; }
    .console-command {
      color: var(--ink);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .console-body {
      margin-top: 3px;
      color: var(--muted);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      max-height: 130px;
      overflow: auto;
    }
    .console-line.active .console-command { color: var(--blue); }
    .console-line.failed .console-command { color: var(--red); }
    .console-line.ok .console-command { color: var(--teal); }
    .console-empty {
      color: var(--muted);
      padding: 10px 0;
      white-space: pre-wrap;
    }
    .live-grid { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: minmax(0, 1fr) 154px; gap: 12px; min-height: 0; height: calc(100% - 28px); }
    .loop-branch-strip {
      min-height: 0;
      display: grid;
      grid-template-rows: 22px minmax(0, 1fr);
      gap: 6px;
      border-top: 1px solid var(--line);
      padding-top: 8px;
    }
    .live-pane { min-height: 0; display: grid; grid-template-rows: 26px minmax(0, 1fr); gap: 8px; }
    .activity-list, .branch-list { overflow: auto; padding-right: 4px; }
    .activity, .branch { cursor: default; }
    .activity:hover, .branch:hover { border-color: #b8c5d8; background: #fbfcfd; }
    .bottom-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; height: calc(100% - 28px); min-height: 0; }
    .demo-rail { min-height: 0; overflow: auto; }
    .demo-rail .run-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .answer-brief { min-height: 0; display: grid; grid-template-rows: 84px 1fr; gap: 8px; }
    .answer-brief .diag { grid-template-columns: 1fr; }
    .topology-map { grid-template-columns: repeat(4, minmax(0, 1fr)); grid-template-rows: repeat(2, minmax(0, 1fr)); height: calc(100% - 70px); }
    .topology-map .stage:not(:last-child)::after { display: none; }
    .stage { overflow: hidden; }
    .topology-map .stage { gap: 6px; overflow: auto; }
    .topology-map .stage .name { line-height: 1.12; overflow-wrap: anywhere; }
    .topology-map .stage .tiny { white-space: normal; overflow: visible; text-overflow: clip; line-height: 1.2; }
    .message .body, .activity-detail, .branch-detail, .question-text, .diag-block p, .workspace-card span {
      overflow-wrap: anywhere;
      word-break: normal;
    }
    .llm-list {
      min-height: 0;
      overflow: auto;
      padding-right: 4px;
      display: grid;
      align-content: start;
      gap: 8px;
    }
    .workflow-node {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      min-width: 0;
      overflow: hidden;
    }
    .workflow-root {
      display: grid;
      grid-template-columns: 76px minmax(0, 1fr);
      gap: 10px;
      padding: 10px;
      background: #fbfcfd;
      border-bottom: 1px solid var(--line);
    }
    .workflow-phase {
      align-self: start;
      border: 1px solid #c8d8fb;
      background: #f8fbff;
      border-radius: 999px;
      color: var(--blue);
      font-size: 12px;
      font-weight: 700;
      text-align: center;
      padding: 4px 6px;
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .workflow-main { min-width: 0; }
    .workflow-head, .workflow-child-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px;
      min-width: 0;
    }
    .workflow-title {
      font-size: 15px;
      font-weight: 700;
      line-height: 1.18;
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .workflow-status {
      flex: 0 0 auto;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .workflow-meta, .workflow-summary {
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.28;
      overflow-wrap: anywhere;
    }
    .workflow-children {
      display: grid;
      gap: 0;
      padding: 0 10px 10px;
    }
    .workflow-child {
      display: grid;
      grid-template-columns: 24px minmax(0, 1fr);
      gap: 8px;
      padding-top: 10px;
      min-width: 0;
    }
    .workflow-indent {
      position: relative;
      min-height: 100%;
    }
    .workflow-indent::before {
      content: "";
      position: absolute;
      top: 0;
      bottom: -10px;
      left: 11px;
      border-left: 1px solid #d9e0ea;
    }
    .workflow-indent span::after {
      content: "";
      position: absolute;
      top: 12px;
      left: 11px;
      width: 12px;
      border-top: 1px solid #d9e0ea;
    }
    .workflow-child:last-child .workflow-indent::before { bottom: calc(100% - 13px); }
    .workflow-child-label {
      font-size: 13px;
      font-weight: 700;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }
    .workflow-body {
      margin-top: 5px;
      padding: 8px 9px;
      border: 1px solid #edf0f4;
      border-radius: 6px;
      background: #fff;
      color: var(--slate);
      font-size: 13px;
      line-height: 1.34;
      max-height: 150px;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .llm-card {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fff;
      min-width: 0;
    }
    .llm-card.input { border-left: 3px solid var(--blue); }
    .llm-card.output { border-left: 3px solid var(--teal); }
    .llm-head { display: flex; justify-content: space-between; gap: 8px; min-width: 0; }
    .llm-title { font-size: 15px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .llm-status { color: var(--muted); font-size: 12px; white-space: nowrap; }
    .llm-meta { margin-top: 4px; color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .llm-body {
      margin-top: 6px;
      color: var(--slate);
      font-size: 13px;
      line-height: 1.32;
      max-height: 86px;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .topology-shell {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 208px;
      gap: 12px;
      height: calc(100% - 28px);
      min-height: 0;
    }
    .loop-panel {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) 124px;
      gap: 12px;
    }
    .loop-panel .panel-title { margin-bottom: 0; }
    .loop-panel .topology-shell,
    .loop-panel .loop-branch-strip { height: auto; }
    .loop-panel-status {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      min-width: 0;
    }
    .loop-panel-status span { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .topology-canvas {
      position: relative;
      min-height: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      overflow: hidden;
    }
    .topology-canvas::before {
      content: "";
      position: absolute;
      inset: 26px 54px;
      border: 1px solid #dbe3ee;
      border-radius: 999px;
      background: #fbfcfd;
      pointer-events: none;
    }
    .topology-loop-label {
      position: absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
      display: grid;
      gap: 4px;
      place-items: center;
      width: 138px;
      height: 74px;
      border: 1px solid #dbe3ee;
      border-radius: 999px;
      background: rgba(255, 255, 255, .92);
      color: var(--slate);
      text-align: center;
      pointer-events: none;
      box-shadow: 0 8px 22px rgba(15, 23, 42, .06);
    }
    .topology-loop-label strong { font-size: 16px; line-height: 1; }
    .topology-loop-label span { color: var(--muted); font-size: 11px; line-height: 1.15; max-width: 118px; }
    .topology-svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
    }
    .topology-edge {
      stroke: #b8c2d1;
      stroke-width: 2.2;
      fill: none;
      opacity: .64;
      stroke-linecap: round;
    }
    .topology-edge.feedback {
      stroke-dasharray: 5 5;
      opacity: .48;
    }
    .topology-edge.loopback { stroke: var(--teal); opacity: .72; }
    .topology-edge.active { stroke: var(--blue); stroke-width: 3; opacity: .9; }
    .topology-edge.hot { stroke: var(--teal); stroke-width: 4; opacity: 1; }
    .topology-edge.warn { stroke: var(--amber); stroke-width: 3; opacity: .95; }
    .topology-node {
      position: absolute;
      width: 84px;
      min-height: 60px;
      transform: translate(-50%, -50%);
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      padding: 8px;
      box-shadow: 0 8px 18px rgba(15, 23, 42, .07);
      cursor: pointer;
      text-align: left;
    }
    .topology-node.ok { border-color: #9fd4b1; }
    .topology-node.warn { border-color: #e5c07b; box-shadow: 0 8px 18px rgba(180, 83, 9, .12); }
    .topology-node.active { border-color: #93b4f8; box-shadow: 0 8px 18px rgba(29, 78, 216, .13); }
    .topology-node.closed { border-color: #7fc9bd; box-shadow: 0 8px 18px rgba(15, 118, 110, .13); }
    .topology-node.idle { opacity: .62; }
    .topology-node .node-top { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
    .topology-node .node-name { font-size: 12px; font-weight: 700; line-height: 1.05; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .topology-node .node-count { margin-top: 6px; font-size: 20px; font-weight: 700; line-height: 1; color: var(--ink); }
    .topology-node .node-detail { margin-top: 4px; color: var(--muted); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .state-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); flex: 0 0 auto; }
    .state-dot.ok { background: var(--green); }
    .state-dot.active { background: var(--blue); }
    .state-dot.warn { background: var(--amber); }
    .state-dot.failed { background: var(--red); }
    .state-dot.closed { background: var(--teal); }
    .graph-inspector {
      min-width: 0;
      min-height: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      padding: 10px;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      gap: 7px;
    }
    .inspect-kicker { color: var(--muted); font-size: 11px; text-transform: uppercase; font-weight: 700; }
    .inspect-title { font-size: 16px; font-weight: 700; line-height: 1.15; overflow-wrap: anywhere; }
    .inspect-body {
      color: var(--slate);
      font-size: 13px;
      line-height: 1.35;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .signal-card {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #fff;
      color: var(--ink);
      cursor: pointer;
      display: grid;
      gap: 5px;
      text-align: left;
      min-width: 0;
    }
    .signal-card:hover { border-color: #b8c5d8; background: #fbfcfd; }
    .signal-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
    .signal-title { font-size: 13px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .signal-meta { color: var(--muted); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .signal-stage { color: var(--blue); font-size: 10px; font-weight: 700; text-transform: uppercase; }
    .signal-badges { display: flex; gap: 5px; flex-wrap: wrap; }
    .signal-badges span {
      border: 1px solid #dfe5ee;
      border-radius: 999px;
      padding: 2px 6px;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.2;
    }
    .chat-panel { grid-template-rows: auto auto minmax(140px, .42fr) minmax(260px, .58fr) auto; }
    .left { grid-template-rows: 98px minmax(0, 1fr); }
    .grid { grid-template-columns: minmax(500px, 44%) minmax(620px, 56%); }
    .wide-pane { grid-column: 1 / span 2; }
    @media (max-width: 980px) {
      body { overflow: auto; height: auto; }
      .grid { height: auto; grid-template-columns: 1fr; }
      .left, .right { grid-template-rows: auto; }
      .pipeline, .cards, .run-cards, .diag, .intel-list, .footer-grid, .workspace-grid, .live-grid, .bottom-grid { grid-template-columns: 1fr; }
      .wide-pane { grid-column: auto; }
      .topology-shell, .thread-tools { grid-template-columns: 1fr; }
      .topology-shell { grid-template-rows: minmax(360px, auto) 112px; }
      .loop-panel { grid-template-rows: auto minmax(480px, auto) minmax(150px, auto); }
      .stage:not(:last-child)::after { display: none; }
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
      <span class="status"><span class="dot ok"></span><span>WSL Kernel v3</span></span>
      <a class="button" href="/workflow" target="_blank">Audit View</a>
    </div>
  </header>
  <main class="grid">
    <section class="left">
      <div class="panel">
        <div class="panel-title"><span>Workspace</span><span id="repo">loading</span></div>
        <div class="workspace-grid">
          <div class="workspace-card">
            <strong id="workspaceRoot">/home/ran_yakumo/holo</strong>
            <span id="workspaceState">kernel-v3 workspace</span>
          </div>
          <div class="workspace-card">
            <strong id="workspaceThread">thread demo-ui-live</strong>
            <span id="provider">model surface</span>
          </div>
        </div>
      </div>
      <div class="panel loop-panel">
        <div class="panel-title">
          <span>Agent loop runtime</span>
          <span class="loop-panel-status"><span id="latestItem"></span><span id="publicTraceNotice">runtime context live</span></span>
        </div>
        <div class="topology-shell">
          <div class="topology-canvas" id="pipeline"></div>
          <div class="graph-inspector" id="graphInspector">
            <div class="inspect-kicker">Inspector</div>
            <div class="inspect-title">Select a node</div>
            <div class="inspect-body">The graph shows the live agent loop: model decisions, host validation, tool execution, search, evidence, verification, answer, and continuation.</div>
          </div>
        </div>
        <div class="loop-branch-strip">
          <div class="column-title">Search branches</div>
          <div class="branch-list" id="searchBranches"></div>
        </div>
      </div>
    </section>
    <section class="right">
      <div class="panel chat-panel">
        <div class="panel-title"><span>Chat with Holo Kernel v3</span><span class="status"><span id="consoleDot" class="dot"></span><span id="consoleStatus">ready</span></span></div>
        <div class="thread-tools">
          <select id="threadSelect" aria-label="Console thread"></select>
          <select id="runMode" aria-label="Execution mode">
            <option value="auto" selected>Auto Chat</option>
            <option value="finance_deep">Finance Deep</option>
            <option value="fast">Fast</option>
          </select>
          <button id="newThread">New Thread</button>
          <button id="clearScreen">Clear Screen</button>
        </div>
        <div class="transcript" id="transcript"></div>
        <div class="runtime-terminal">
          <div class="runtime-terminal-head"><span>Runtime Console</span><span id="runtimeConsoleState">waiting</span></div>
          <div class="runtime-console" id="runtimeConsole"></div>
        </div>
        <div class="composer">
          <textarea id="commandInput" class="command-input" placeholder="Ask Holo a finance question, or give it a research task. Example: What was Goldman Sachs' net revenues for fiscal year 2024?"></textarea>
          <div class="command-row">
            <button id="runCommand" class="primary">Run on Kernel v3</button>
            <button id="clearCommand">Clear</button>
            <div class="thread" id="consoleThread">thread demo-ui-live</div>
          </div>
          <div class="quick-prompts">
            <button data-mode="finance_deep" data-prompt="Hard stable FinanceBench task: compute Activision Blizzard's FY2019 fixed asset turnover ratio. Fixed asset turnover is FY2019 revenue divided by average net PP&E between FY2018 and FY2019. Retrieve the FY2019 10-K evidence, bind revenue and beginning/ending net PP&E to exact filing captions, compute average net PP&E, show the formula, round to two decimals, and cite the source lines used.">FB: Activision FAT</button>
            <button data-mode="finance_deep" data-prompt="Hard stable FinanceBench task: is 3M a capital-intensive business based on FY2022 data? Retrieve 3M filing evidence, identify sales or revenue and PP&E or asset intensity evidence, compute a relevant capital-intensity ratio, avoid any hard-coded threshold, reason from the business context, and cite exact filing line items.">FB: 3M capital intensity</button>
            <button data-mode="finance_deep" data-prompt="Hard stable FinanceBench task: what is 3M's FY2018 capital expenditure amount in USD millions? Rely primarily on the cash flow statement, bind the exact investing cash-flow caption, handle sign convention clearly, and cite the filing source.">FB: 3M capex</button>
            <button data-mode="finance_deep" data-prompt="Hard stable FinanceBench task: assume you are a public equities analyst. Using primarily 3M's balance sheet, find year-end FY2018 net PP&E and answer in USD billions. Bind the exact caption, convert units carefully, and cite the source.">FB: 3M net PP&E</button>
            <button data-mode="finance_deep" data-prompt="Hard stable FinanceBench task: what drove operating margin change as of FY2022 for 3M? If operating margin is not a useful metric for this company or period, state that and explain why. Retrieve evidence, compute or compare the margin components when appropriate, separate numeric facts from interpretation, and cite sources.">FB: 3M margin drivers</button>
            <button data-mode="finance_deep" data-prompt="Hard stable FinanceBench task: excluding the impact of M&A, which 3M segment dragged down overall growth in 2022? Retrieve segment revenue or organic growth evidence, separate acquisition/divestiture effects from underlying growth, identify the segment, and cite the filing table or management discussion used.">FB: 3M ex-M&A segment</button>
            <button data-mode="finance_deep" data-prompt="Hard stable metric-disambiguation task: what was Goldman Sachs' net revenues for fiscal year 2024? Use filing or annual-report evidence, distinguish net revenues from component revenue lines, name the exact caption, preserve the reported unit, and cite the source.">Metric: Goldman net rev</button>
            <button data-mode="finance_deep" data-prompt="Hard stable metric-disambiguation task: what was NextEra Energy's operating revenues for fiscal year 2024? Use filing evidence, choose the exact operating revenues caption rather than a generic revenue concept, preserve units, and cite the source.">Metric: NextEra op rev</button>
            <button data-mode="finance_deep" data-prompt="Long research task: for NYSE: HD and NYSE: LOW, calculate FY2024 days inventory outstanding and compare inventory efficiency. Retrieve public filings for both companies, bind inventory and cost-of-sales inputs, state whether average or ending inventory is used, show formulas, compare results, and explain which company appears more inventory-efficient.">Research: HD vs LOW DIO</button>
            <button data-mode="finance_deep" data-prompt="Long research task: for Kraft Heinz, use public filings to explain the adjusted EBITDA bridge for the requested period. Identify the base metric, add-backs, deductions, subtotal, and any non-recurring or management-adjusted components. Cite each bridge component and explain whether the adjustment quality looks conservative or aggressive.">Research: KHC EBITDA bridge</button>
            <button data-mode="finance_deep" data-prompt="Long research task: for Pfizer's acquisition of Seagen, calculate the transaction enterprise value to revenue multiple using public deal disclosures and filing evidence. Identify consideration, debt/cash treatment if disclosed, revenue basis, formula, limitations, and cite the relevant deal or filing sources.">Research: PFE-Seagen multiple</button>
            <button data-mode="finance_deep" data-prompt="Long research task: for WillScot Mobile Mini, investigate the adjusted EBITDA add-back trend across the relevant public filings. Summarize direction, key components, whether the add-backs appear recurring or one-time, and cite the evidence used for each claim.">Research: WSC add-backs</button>
          </div>
        </div>
      </div>
    </section>
    <div style="display:none"><span id="selectedRunLabel"></span><div id="demoRuns"></div><span id="questionText"></span><span id="answerState"></span><span id="diagnosis"></span><span id="resultPath"></span><span id="summaryPath"></span><span id="refreshState"></span><span id="runStatus"></span><span id="heroTitle"></span><span id="heroCopy"></span><span id="runDot"></span><span id="passRate"></span><span id="verifierState"></span><span id="progressText"></span><span id="progressBar"></span><span id="heroCalc"></span><span id="heroFacts"></span><span id="heroCitations"></span><span id="spotlightStep"></span><span id="spotlightTitle"></span><span id="spotlightText"></span><span id="llmCalls"></span><span id="retrievalFetches"></span><span id="calcCalls"></span><span id="factCount"></span><span id="stablePasses"></span><div id="intel"></div></div>
  </main>
  <script>
    const fmtPct = v => (v === null || v === undefined || Number.isNaN(Number(v))) ? "-" : `${(Number(v) * 100).toFixed(1)}%`;
    const fmtNum = v => (v === null || v === undefined || v === "") ? "0" : Number(v).toLocaleString();
    const text = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value ?? ""; };
    const cls = (id, value) => { const el = document.getElementById(id); if (el) el.className = value; };
    const params = new URLSearchParams(window.location.search);
    const selected = {
      runPrefix: params.get("run_prefix") || "",
      threadPrefix: params.has("thread_prefix") ? params.get("thread_prefix") : null,
      itemId: params.get("item_id") || "",
      consoleThread: params.get("console_thread") || localStorage.getItem("holo_console_thread") || "demo-ui-live"
    };
    let liveSource = null;
    let liveConnectedThread = "";
    let lastLiveAt = 0;
    let manualInspector = false;
    let frozenTrace = null;
    let runtimeConsoleLines = [];
    const topologyLabels = ["Intake", "Plan", "Policy", "Tools", "Search", "Evidence", "Verify", "Answer"];
    const topologyLayout = {
      Intake: [50, 12],
      Plan: [72, 22],
      Policy: [86, 50],
      Tools: [72, 78],
      Search: [50, 88],
      Evidence: [28, 78],
      Verify: [14, 50],
      Answer: [28, 22]
    };
    const topologyEdges = [
      ["Intake", "Plan"],
      ["Plan", "Policy"],
      ["Policy", "Tools"],
      ["Tools", "Search"],
      ["Search", "Evidence"],
      ["Evidence", "Verify"],
      ["Verify", "Answer"],
      ["Answer", "Plan", "loopback"]
    ];
    let latestSpotlights = [];
    let spotlightIndex = 0;
    function threadList() {
      let rows = [];
      try { rows = JSON.parse(localStorage.getItem("holo_threads") || "[]"); } catch (err) { rows = []; }
      rows = Array.isArray(rows) ? rows.filter(Boolean).map(String) : [];
      if (!rows.includes("demo-ui-live")) rows.unshift("demo-ui-live");
      if (!rows.includes(selected.consoleThread)) rows.unshift(selected.consoleThread);
      return Array.from(new Set(rows)).slice(0, 12);
    }
    function saveThreadList(rows) {
      localStorage.setItem("holo_threads", JSON.stringify(Array.from(new Set(rows.filter(Boolean))).slice(0, 12)));
    }
    function rememberThread(threadId) {
      const rows = threadList().filter(row => row !== threadId);
      rows.unshift(threadId);
      saveThreadList(rows);
      renderThreadSelect();
    }
    function renderThreadSelect() {
      const select = document.getElementById("threadSelect");
      if (!select) return;
      select.innerHTML = threadList().map(row => `<option value="${escapeHtml(row)}"${row === selected.consoleThread ? " selected" : ""}>${escapeHtml(row)}</option>`).join("");
    }
    function updateLocation() {
      const query = new URLSearchParams(window.location.search);
      if (selected.runPrefix) query.set("run_prefix", selected.runPrefix);
      if (selected.threadPrefix !== null) query.set("thread_prefix", selected.threadPrefix || "");
      if (selected.itemId) query.set("item_id", selected.itemId); else query.delete("item_id");
      query.set("console_thread", selected.consoleThread);
      window.history.replaceState(null, "", `?${query.toString()}`);
    }
    function switchThread(threadId) {
      selected.consoleThread = threadId || "demo-ui-live";
      localStorage.setItem("holo_console_thread", selected.consoleThread);
      rememberThread(selected.consoleThread);
      updateLocation();
      resetLiveView();
      connectLive();
      refresh();
    }
    function clearKey() { return `holo_clear_${selected.consoleThread}`; }
    function isScreenCleared() { return localStorage.getItem(clearKey()) === "1"; }
    function setScreenCleared(value) {
      if (value) localStorage.setItem(clearKey(), "1");
      else localStorage.removeItem(clearKey());
    }
    function newThreadId() {
      return `demo-ui-${Date.now().toString(36)}`;
    }
    function showInspector(title, meta, body, manual = false) {
      if (manual) manualInspector = true;
      const panel = document.getElementById("graphInspector");
      if (!panel) return;
      panel.innerHTML = `
        <div class="inspect-kicker">${escapeHtml(meta || "Inspector")}</div>
        <div class="inspect-title">${escapeHtml(title || "Runtime node")}</div>
        <div class="inspect-body">${escapeHtml(body || "No additional detail.")}</div>`;
    }
    function setTab(name) {
      document.querySelectorAll("button[data-tab]").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
      document.querySelectorAll(".tabs").forEach(p => p.classList.toggle("active", p.id === name));
    }
    document.querySelectorAll("button[data-tab]").forEach(b => b.addEventListener("click", () => setTab(b.dataset.tab)));
    document.getElementById("runCommand").addEventListener("click", submitCommand);
    document.getElementById("clearCommand").addEventListener("click", () => { document.getElementById("commandInput").value = ""; });
    document.getElementById("threadSelect").addEventListener("change", event => switchThread(event.target.value));
    document.getElementById("newThread").addEventListener("click", () => {
      document.getElementById("runMode").value = "auto";
      switchThread(newThreadId());
    });
    document.getElementById("clearScreen").addEventListener("click", () => {
      setScreenCleared(true);
      frozenTrace = null;
      renderTranscript([]);
      renderPipeline([]);
      renderBranches([]);
      runtimeConsoleLines = [];
      renderRuntimeConsole([]);
      showInspector("Screen cleared", selected.consoleThread, "Local view cleared. The durable journal is preserved; start a new run or switch thread to populate this screen again.");
    });
    document.getElementById("commandInput").addEventListener("keydown", event => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitCommand();
    });
    document.querySelectorAll("button[data-prompt]").forEach(button => {
      button.addEventListener("click", () => {
        document.getElementById("commandInput").value = button.dataset.prompt || "";
        if (button.dataset.mode) document.getElementById("runMode").value = button.dataset.mode;
      });
    });
    function stateUrl() {
      const query = new URLSearchParams();
      if (selected.runPrefix) query.set("run_prefix", selected.runPrefix);
      if (selected.threadPrefix !== null) query.set("thread_prefix", selected.threadPrefix || "");
      if (selected.itemId) query.set("item_id", selected.itemId);
      if (selected.consoleThread) query.set("console_thread", selected.consoleThread);
      const suffix = query.toString();
      return suffix ? `/api/state?${suffix}` : "/api/state";
    }
    function liveUrl() {
      const query = new URLSearchParams();
      query.set("console_thread", selected.consoleThread || "demo-ui-live");
      return `/api/live?${query.toString()}`;
    }
    function resetLiveView() {
      manualInspector = false;
      lastLiveAt = 0;
      frozenTrace = null;
      renderTranscript([]);
      renderPipeline([]);
      renderBranches([]);
      runtimeConsoleLines = [];
      renderRuntimeConsole([]);
      text("consoleThread", `thread ${selected.consoleThread}`);
      text("consoleStatus", "ready");
      text("publicTraceNotice", "live stream starting");
      cls("consoleDot", "dot ok");
      showInspector("Waiting for events", selected.consoleThread, "This thread has no visible agent-loop events yet. Submit a task to stream model packets, tool calls, search branches, verifier gates, and the final answer.");
    }
    function connectLive() {
      if (liveSource) {
        liveSource.close();
        liveSource = null;
      }
      if (!window.EventSource) {
        text("publicTraceNotice", "SSE unavailable; low-frequency state refresh active");
        return;
      }
      liveConnectedThread = selected.consoleThread || "demo-ui-live";
      liveSource = new EventSource(liveUrl());
      liveSource.addEventListener("ready", event => {
        let payload = {};
        try { payload = JSON.parse(event.data || "{}"); } catch (err) { payload = {}; }
        if ((payload.thread_id || liveConnectedThread) !== selected.consoleThread) return;
        text("publicTraceNotice", "live stream connected");
      });
      liveSource.addEventListener("heartbeat", event => {
        let payload = {};
        try { payload = JSON.parse(event.data || "{}"); } catch (err) { payload = {}; }
        if ((payload.thread_id || liveConnectedThread) !== selected.consoleThread) return;
        if (frozenTrace && frozenTrace.threadId === selected.consoleThread) {
          text("publicTraceNotice", `closed runtime context | ${fmtNum((frozenTrace.stats || {}).records)} records | frozen`);
          return;
        }
        const age = lastLiveAt ? Math.max(0, Math.round((Date.now() - lastLiveAt) / 1000)) : 0;
        text("publicTraceNotice", age ? `live stream connected | last event ${age}s ago` : "live stream connected");
      });
      liveSource.addEventListener("journal", event => {
        let payload = {};
        try { payload = JSON.parse(event.data || "{}"); } catch (err) { payload = {}; }
        applyLivePayload(payload);
      });
      liveSource.addEventListener("stream_error", event => {
        let payload = {};
        try { payload = JSON.parse(event.data || "{}"); } catch (err) { payload = {}; }
        if ((payload.thread_id || liveConnectedThread) !== selected.consoleThread) return;
        text("publicTraceNotice", `live stream error: ${payload.error || "unknown"}`);
      });
      liveSource.addEventListener("error", () => {
        if (liveConnectedThread === selected.consoleThread) text("publicTraceNotice", "live stream reconnecting");
      });
    }
    function applyLivePayload(payload) {
      if (!payload || payload.thread_id !== selected.consoleThread) return;
      const kind = payload.record && payload.record.kind;
      if (kind === "chat_turn") frozenTrace = null;
      if (frozenTrace && frozenTrace.threadId === selected.consoleThread) return;
      lastLiveAt = Date.now();
      setScreenCleared(false);
      const stats = payload.stats || {};
      const closed = Boolean(payload.closed || stats.closed);
      if (Array.isArray(payload.transcript) && payload.transcript.length) renderTranscript(payload.transcript);
      renderPipeline(payload.topology || []);
      renderBranches(payload.search_branches || []);
      if (closed && Array.isArray(payload.runtime_console)) {
        runtimeConsoleLines = payload.runtime_console;
        renderRuntimeConsole(runtimeConsoleLines);
      } else if (payload.record) {
        appendRuntimeConsoleRecord(payload.record);
      }
      text("publicTraceNotice", `${closed ? "closed runtime context" : "live runtime context"} | ${fmtNum(stats.records)} records${kind ? " | last " + kind : ""}`);
      text("consoleStatus", closed ? "complete" : "running");
      cls("consoleDot", `dot ${closed ? "ok" : "running"}`);
      if (closed) {
        frozenTrace = {
          threadId: selected.consoleThread,
          transcript: payload.transcript || [],
          topology: payload.topology || [],
          search_branches: payload.search_branches || [],
          runtime_console: runtimeConsoleLines.slice(),
          stats,
          frozenAt: Date.now()
        };
      }
    }
    function renderPendingSubmit(message) {
      const now = Date.now();
      frozenTrace = null;
      renderTranscript([
        { role: "user", text: message, status: "submitted", at: now },
        { role: "assistant", text: "Kernel v3 is running. Model packets, tool calls, retrieval branches, verifier gates, and the final answer will stream into the graph as journal events arrive.", status: "running", at: now + 1 }
      ]);
      renderPipeline([]);
      renderBranches([]);
      runtimeConsoleLines = [
        {
          at: now,
          level: "active",
          stage: "run",
          line: `$ browser submit -> holo-v3 chat --thread ${selected.consoleThread} --once ...`,
          body: message
        }
      ];
      renderRuntimeConsole(runtimeConsoleLines);
      manualInspector = false;
      showInspector("Kernel process running", selected.consoleThread, "Waiting for the first journal event from the WSL runtime.");
    }
    function selectRun(row) {
      selected.runPrefix = row.run_prefix || "";
      selected.threadPrefix = row.thread_prefix ?? "";
      selected.itemId = row.item_id || "";
      updateLocation();
      refresh();
    }
    async function submitCommand() {
      const input = document.getElementById("commandInput");
      const message = input.value.trim();
      if (!message) return;
      const button = document.getElementById("runCommand");
      button.disabled = true;
      text("consoleStatus", "starting");
      cls("consoleDot", "dot running");
      setScreenCleared(false);
      rememberThread(selected.consoleThread);
      if (!liveSource || liveConnectedThread !== selected.consoleThread) connectLive();
      renderPendingSubmit(message);
      try {
        const res = await fetch("/api/command", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, thread_id: selected.consoleThread, profile: document.getElementById("runMode").value || "auto" })
        });
        const payload = await res.json();
        if (payload.thread_id) {
          selected.consoleThread = payload.thread_id;
          localStorage.setItem("holo_console_thread", selected.consoleThread);
        }
        input.value = "";
        rememberThread(selected.consoleThread);
        updateLocation();
        if (liveConnectedThread !== selected.consoleThread) connectLive();
        window.setTimeout(refresh, 900);
      } catch (err) {
        text("consoleStatus", "submit failed");
        cls("consoleDot", "dot failed");
      } finally {
        button.disabled = false;
      }
    }
    async function refresh() {
      const res = await fetch(stateUrl(), { cache: "no-store" });
      const data = await res.json();
      const cur = data.current || {};
      const consoleState = data.console || {};
      const consoleJob = consoleState.job || {};
      const workspace = data.workspace || {};
      if (!selected.runPrefix && data.filters && data.filters.run_prefix) selected.runPrefix = data.filters.run_prefix;
      if (data.filters && data.filters.item_id !== undefined) selected.itemId = data.filters.item_id || "";
      if (data.filters && data.filters.console_thread) selected.consoleThread = data.filters.console_thread;
      if ((document.getElementById("threadSelect")?.value || "") !== selected.consoleThread) rememberThread(selected.consoleThread);
      const metrics = cur.latest_metrics || {};
      const stability = data.stability || {};
      text("subtitle", `${data.generated_at} | branch ${data.repo.branch || "-"} @ ${data.repo.head || "-"}`);
      text("workspaceRoot", workspace.root || "-");
      text("workspaceState", `${workspace.branch || "-"} @ ${workspace.head || "-"} | state ${workspace.state_dir || "-"}`);
      text("workspaceThread", `thread ${workspace.thread_id || selected.consoleThread}`);
      text("heroTitle", cur.selected_item_id || cur.latest_item_id ? `Case ${cur.selected_item_id || cur.latest_item_id}` : "Financial reasoning demo");
      text("heroCopy", cur.latest_question || "LLM chooses the research move; tools retrieve and compute; the host verifies, journals, and presents evidence.");
      text("workflowStatement", `${cur.name || "Kernel v3"}: LLM semantic decisions, tool execution, evidence ledger, verification, and final answer are visible in one flow.`);
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
      text("questionText", cur.latest_question || "Waiting for the next scored item.");
      text("answerState", answerStateText(cur));
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
      text("consoleThread", `thread ${consoleState.thread_id || selected.consoleThread}`);
      const jobStatus = consoleJob.status || (consoleState.transcript && consoleState.transcript.length ? "ready" : "ready");
      const traceClosed = Boolean(consoleState.stats && consoleState.stats.closed);
      const effectiveJobStatus = traceClosed ? "complete" : jobStatus;
      text("consoleStatus", effectiveJobStatus);
      cls("consoleDot", `dot ${effectiveJobStatus === "running" || effectiveJobStatus === "queued" ? "running" : effectiveJobStatus === "failed" || effectiveJobStatus === "timeout" || effectiveJobStatus === "error" ? "failed" : "ok"}`);
      renderDemoRuns(data.demo_runs || [], (data.filters || {}).run_prefix || selected.runPrefix, (data.filters || {}).item_id || selected.itemId);
      const cleared = isScreenCleared() && !["running", "queued"].includes(effectiveJobStatus);
      const hasFrozenTrace = Boolean(frozenTrace && frozenTrace.threadId === selected.consoleThread && !cleared);
      const preserveLiveTrace = Boolean((hasFrozenTrace || (lastLiveAt && Date.now() - lastLiveAt < 2500)) && !cleared);
      if (!preserveLiveTrace) {
        text("publicTraceNotice", consoleState.notice || "runtime context");
        renderTranscript(cleared ? [] : (consoleState.transcript || []));
        renderPipeline(cleared ? [] : (consoleState.topology || []));
        renderBranches(cleared ? [] : (consoleState.search_branches || []));
        runtimeConsoleLines = cleared ? [] : (consoleState.runtime_console || []);
        renderRuntimeConsole(runtimeConsoleLines);
        if (!cleared && consoleState.stats && consoleState.stats.closed) {
          frozenTrace = {
            threadId: selected.consoleThread,
            transcript: consoleState.transcript || [],
            topology: consoleState.topology || [],
            search_branches: consoleState.search_branches || [],
            runtime_console: runtimeConsoleLines.slice(),
            stats: consoleState.stats || {},
            frozenAt: Date.now()
          };
          text("publicTraceNotice", `closed runtime context | ${fmtNum((frozenTrace.stats || {}).records)} records | frozen`);
          text("consoleStatus", "complete");
          cls("consoleDot", "dot ok");
        }
        if (cleared) showInspector("Screen cleared", selected.consoleThread, "Local view cleared. The durable journal is preserved.");
      } else if (hasFrozenTrace) {
        text("publicTraceNotice", `closed runtime context | ${fmtNum((frozenTrace.stats || {}).records)} records | frozen`);
        text("consoleStatus", "complete");
        cls("consoleDot", "dot ok");
        renderTranscript(frozenTrace.transcript || []);
        renderPipeline(frozenTrace.topology || []);
        renderBranches(frozenTrace.search_branches || []);
        runtimeConsoleLines = frozenTrace.runtime_console || [];
        renderRuntimeConsole(runtimeConsoleLines);
      }
      renderIntel(data.intelligence || []);
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
    function answerStateText(cur) {
      const metrics = cur.latest_metrics || {};
      const item = cur.selected_item_id || cur.latest_item_id || "Current item";
      const status = cur.status === "complete" ? `${cur.passed || 0}/${cur.done || 0} items passed` : (cur.status || "waiting");
      const verifier = metrics.numeric_verifier_status || (metrics.synthesis_gate_passed ? "synthesis gate passed" : "verifier pending");
      const facts = fmtNum(metrics.finance_fact_count || metrics.claim_count || metrics.evidence_count);
      const citations = fmtNum(metrics.citation_count || metrics.retrieval_citation_count);
      const reason = cur.latest_reason ? `Reason: ${cur.latest_reason}.` : "Trace available in the audit log.";
      return `${item}: ${status}. ${reason} Evidence ledger: ${facts} facts and ${citations} citations. Gate: ${verifier}.`;
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
      const panel = document.getElementById("pipeline");
      const byLabel = new Map();
      (rows || []).forEach(row => byLabel.set(canonicalTopologyLabel(row.label), row));
      const nodes = topologyLabels.map(label => {
        const row = byLabel.get(label) || {};
        return {
          label,
          state: row.state || "idle",
          value: Number(row.value || 0),
          detail: row.detail || idleDetail(label)
        };
      });
      const nodeMap = new Map(nodes.map(row => [row.label, row]));
      const svgEdges = topologyEdges.map(([from, to, kind]) => {
        const a = topologyLayout[from];
        const b = topologyLayout[to];
        const fromNode = nodeMap.get(from) || {};
        const toNode = nodeMap.get(to) || {};
        const active = Number(fromNode.value || 0) > 0 && Number(toNode.value || 0) > 0;
        const hot = toNode.state === "active" || toNode.state === "closed";
        const warn = fromNode.state === "warn" || toNode.state === "warn";
        const curve = topologyEdgePath(a, b, kind);
        return `<path class="topology-edge ${kind === "loopback" ? "loopback feedback" : ""} ${active ? "active" : ""} ${hot ? "hot" : ""} ${warn ? "warn" : ""}" d="${curve}" />`;
      }).join("");
      const nodeHtml = nodes.map(row => {
        const pos = topologyLayout[row.label];
        const statusClass = row.state === "failed" ? "failed" : row.state;
        return `<button class="topology-node ${escapeHtml(row.state)}" style="left:${pos[0]}%;top:${pos[1]}%" data-label="${escapeHtml(row.label)}" title="${escapeHtml(row.detail)}">
          <div class="node-top"><div class="node-name">${escapeHtml(row.label)}</div><span class="state-dot ${escapeHtml(statusClass)}"></span></div>
          <div class="node-count">${fmtNum(row.value)}</div>
          <div class="node-detail">${escapeHtml(row.detail)}</div>
        </button>`;
      }).join("");
      panel.innerHTML = `
        <svg class="topology-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          ${svgEdges}
        </svg>
        <div class="topology-loop-label"><strong>Agent Loop</strong><span>model -> tools -> evidence -> verify -> answer -> continue</span></div>
        ${nodeHtml}`;
      panel.querySelectorAll(".topology-node").forEach(button => {
        button.addEventListener("click", () => {
          const row = nodeMap.get(button.dataset.label) || {};
          showInspector(row.label, `${row.state || "idle"} | ${fmtNum(row.value)} events`, row.detail || "", true);
        });
      });
      const activeNode = nodes.find(row => row.state === "active") || nodes.find(row => row.state === "warn") || nodes.find(row => row.value > 0) || nodes[0];
      if (activeNode && !manualInspector) showInspector(activeNode.label, `${activeNode.state} | ${fmtNum(activeNode.value)} events`, activeNode.detail);
    }
    function topologyEdgePath(a, b, kind) {
      const cx = 50;
      const cy = 50;
      const mx = (a[0] + b[0]) / 2;
      const my = (a[1] + b[1]) / 2;
      const dx = mx - cx;
      const dy = my - cy;
      const len = Math.hypot(dx, dy) || 1;
      const bend = kind === "loopback" ? 24 : 9;
      const qx = mx + (dx / len) * bend;
      const qy = my + (dy / len) * bend;
      return `M ${a[0]} ${a[1]} Q ${qx.toFixed(1)} ${qy.toFixed(1)} ${b[0]} ${b[1]}`;
    }
    function canonicalTopologyLabel(label) {
      const value = String(label || "").toLowerCase();
      if (value.includes("intake")) return "Intake";
      if (value.includes("plan") || value.includes("llm")) return "Plan";
      if (value.includes("policy") || value.includes("provider")) return "Policy";
      if (value.includes("tool") || value.includes("compute")) return "Tools";
      if (value.includes("search") || value.includes("retrieve")) return "Search";
      if (value.includes("evidence")) return "Evidence";
      if (value.includes("verify") || value.includes("gate")) return "Verify";
      if (value.includes("answer") || value.includes("synth") || value.includes("score")) return "Answer";
      return String(label || "");
    }
    function idleDetail(label) {
      return ({
        Intake: "task parsed",
        Plan: "LLM chooses move",
        Policy: "host validates",
        Tools: "tools execute",
        Search: "retrieval branches",
        Evidence: "facts and citations",
        Verify: "numeric/support gate",
        Answer: "final response"
      })[label] || "";
    }
    function appendRuntimeConsoleRecord(record) {
      if (!record) return;
      const line = runtimeLineFromRecord(record);
      if (!line) return;
      runtimeConsoleLines.push(line);
      runtimeConsoleLines = runtimeConsoleLines.slice(-160);
      renderRuntimeConsole(runtimeConsoleLines);
    }
    function runtimeLineFromRecord(record) {
      const kind = record.kind || "event";
      const stage = (record.stage || kind || "run").toString().toLowerCase();
      const level = record.status === "failed" || record.status === "error" ? "failed" : record.status === "request" ? "active" : "ok";
      const line = record.line || `[${stage}] ${record.title || kind}`;
      const body = record.body || record.detail || record.query || record.uri || "";
      return { at: Date.now(), source_at: record.at || 0, level, stage, line, body };
    }
    function renderRuntimeConsole(rows) {
      const panel = document.getElementById("runtimeConsole");
      if (!panel) return;
      const shown = (rows || []).slice(-160);
      text("runtimeConsoleState", shown.length ? `${fmtNum(shown.length)} lines` : "waiting");
      if (!shown.length) {
        panel.innerHTML = `<div class="console-empty">$ waiting for model packets, tool calls, retrieval branches, evidence, verifier gates, and final answer...</div>`;
        return;
      }
      const baseAt = firstConsoleAt(shown);
      panel.innerHTML = shown.map((row, index) => `
        <div class="console-line ${escapeHtml(row.level || "ok")}">
          <div class="console-time">${escapeHtml(formatConsoleTime(row.at, baseAt, index))}</div>
          <div class="console-main">
            <div class="console-command">${escapeHtml(row.line || "")}</div>
            ${row.body ? `<div class="console-body">${escapeHtml(row.body)}</div>` : ""}
          </div>
        </div>`).join("");
      panel.scrollTop = panel.scrollHeight;
    }
    function firstConsoleAt(rows) {
      for (const row of rows || []) {
        const n = Number(row.at || 0);
        if (Number.isFinite(n) && n > 0) return n;
      }
      return 0;
    }
    function formatConsoleTime(value, base, index) {
      const n = Number(value || 0);
      if (!n) return "--:--:--";
      const start = Number(base || n);
      if (n < 10_000_000_000 && start < 10_000_000_000) return `#${String((index || 0) + 1).padStart(3, "0")}`;
      const scale = 1000;
      const elapsed = Math.max(0, (n - start) / scale);
      return `+${elapsed.toFixed(elapsed < 10 ? 1 : 0)}s`;
    }
    function renderTranscript(rows) {
      const panel = document.getElementById("transcript");
      if (!rows.length) {
        panel.innerHTML = `<div class="message assistant"><div class="role">Holo</div><div class="body">Enter a task above. The WSL Kernel v3 runtime will execute it through the live agent loop, and the runtime context will appear here.</div></div>`;
        panel.scrollTop = panel.scrollHeight;
        return;
      }
      panel.innerHTML = rows.slice(-8).map(row => `
        <div class="message ${escapeHtml(row.role || "assistant")}">
          <div class="role">${escapeHtml(row.role || "assistant")}${row.status ? " / " + escapeHtml(row.status) : ""}</div>
          <div class="body">${escapeHtml(row.text || "")}</div>
        </div>`).join("");
      panel.scrollTop = panel.scrollHeight;
    }
    function renderBranches(rows) {
      const panel = document.getElementById("searchBranches");
      if (!panel) return;
      if (!rows.length) {
        panel.innerHTML = `<button class="signal-card"><div class="signal-head"><div class="signal-title">No branch</div><span class="state-dot idle"></span></div><div class="signal-meta">retrieval.run not called</div></button>`;
        return;
      }
      const shown = rows.slice(-8).reverse();
      panel.innerHTML = shown.map(row => `
        <button class="signal-card">
          <div class="signal-head"><div class="signal-title">Branch ${fmtNum(row.index)}</div><span class="state-dot ${escapeHtml(row.status === "failed" ? "failed" : "ok")}"></span></div>
          <div class="signal-meta">${fmtNum(row.sources)} sources | ${fmtNum(row.accepted)} accepted</div>
          <div class="signal-badges"><span>${escapeHtml((row.providers || []).slice(0, 3).join(" | ") || row.query_hash || "provider")}</span></div>
        </button>`).join("");
      panel.querySelectorAll(".signal-card").forEach((button, index) => {
        const row = shown[index] || {};
        button.addEventListener("click", () => showInspector(`Search branch ${row.index || ""}`, `${row.status || "ok"} | ${fmtNum(row.sources)} sources`, `${row.query || ""}\n${(row.providers || []).join(", ")}`, true));
      });
    }
    function renderIntel(rows) {
      document.getElementById("intel").innerHTML = rows.map(row => `
        <div class="intel">
          <div class="label">${escapeHtml(row.label)}</div>
          <div class="state">${escapeHtml(row.state)}</div>
          <div class="detail">${escapeHtml(row.detail)}</div>
        </div>`).join("");
    }
    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
    }
    rememberThread(selected.consoleThread);
    connectLive();
    refresh();
    setInterval(() => {
      if (!latestSpotlights.length) return;
      spotlightIndex = (spotlightIndex + 1) % latestSpotlights.length;
      renderSpotlight();
    }, 4500);
    setInterval(refresh, 5000);
    window.addEventListener("beforeunload", () => {
      if (liveSource) liveSource.close();
    });
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
