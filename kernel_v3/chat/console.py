from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass
from typing import Any

from kernel_v3.chat.runtime import ChatRuntime
from kernel_v3.chat.theme import event_style, status_style, style
from kernel_v3.contracts import JsonObject
from kernel_v3.text_safety import normalize_chat_input


@dataclass(frozen=True, kw_only=True)
class ChatConsoleOptions:
    thread: str = "default"
    output: str = "auto"
    color: str = "auto"
    no_color: bool = False


def run_chat_console(runtime: ChatRuntime, options: ChatConsoleOptions) -> int:
    current_thread = str(options.thread or "default")
    output_mode = chat_output_mode(options, once=False)
    color_enabled = chat_color_enabled(options)
    if output_mode == "human":
        print(chat_banner(current_thread, color=color_enabled))
    if stream_is_tty(sys.stdin):
        while True:
            try:
                text = input(chat_prompt(current_thread, color=color_enabled))
            except EOFError:
                print()
                return 0
            exit_requested, current_thread, output_mode, color_enabled = handle_chat_line(
                runtime,
                text,
                thread_id=current_thread,
                output_mode=output_mode,
                color=color_enabled,
            )
            if exit_requested:
                return 0
    for line in sys.stdin:
        exit_requested, current_thread, output_mode, color_enabled = handle_chat_line(
            runtime,
            line,
            thread_id=current_thread,
            output_mode=output_mode,
            color=color_enabled,
        )
        if exit_requested:
            return 0
    return 0


def handle_chat_line(
    runtime: ChatRuntime,
    text: str,
    *,
    thread_id: str,
    output_mode: str,
    color: bool,
) -> tuple[bool, str, str, bool]:
    stripped = normalize_chat_input(text)
    if not stripped:
        return False, thread_id, output_mode, color
    local = handle_chat_local_command(stripped, runtime=runtime, thread_id=thread_id, output_mode=output_mode, color=color)
    if local is not None:
        return local
    start_index = len(runtime.journal.records())
    if output_mode == "json":
        payload = runtime.receive(stripped, thread_id=thread_id)
        print(json.dumps(payload.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print_chat_turn_human(runtime, stripped, thread_id=thread_id, start_index=start_index, color=color)
    sys.stdout.flush()
    return False, thread_id, output_mode, color


def print_chat_turn_human(
    runtime: ChatRuntime,
    text: str,
    *,
    thread_id: str,
    start_index: int | None = None,
    color: bool,
):
    if start_index is None:
        start_index = len(runtime.journal.records())
    print(style("processing...", "bold_cyan", color=color))
    sys.stdout.flush()
    payload = receive_with_live_activity(runtime, text, thread_id=thread_id, start_index=start_index, color=color)
    print(render_chat_result(payload, color=color))
    print()
    return payload


def receive_with_live_activity(
    runtime: ChatRuntime,
    text: str,
    *,
    thread_id: str,
    start_index: int,
    color: bool,
):
    payload_holder: dict[str, object] = {}
    error_holder: dict[str, BaseException] = {}

    def run_receive() -> None:
        try:
            payload_holder["payload"] = runtime.receive(text, thread_id=thread_id)
        except BaseException as exc:  # pragma: no cover - re-raised on caller thread.
            error_holder["error"] = exc

    worker = threading.Thread(target=run_receive, name="holo-v3-chat-turn", daemon=True)
    worker.start()
    next_index = start_index
    printed_header = False
    while worker.is_alive():
        next_index, printed_header = stream_new_activity(
            runtime,
            next_index=next_index,
            printed_header=printed_header,
            color=color,
        )
        worker.join(0.12)
    next_index, printed_header = stream_new_activity(
        runtime,
        next_index=next_index,
        printed_header=printed_header,
        color=color,
    )
    if "error" in error_holder:
        raise error_holder["error"]
    return payload_holder["payload"]


def stream_new_activity(runtime: ChatRuntime, *, next_index: int, printed_header: bool, color: bool) -> tuple[int, bool]:
    records = runtime.journal.records()
    if len(records) <= next_index:
        return next_index, printed_header
    lines = []
    for record in records[next_index:]:
        data = getattr(record, "data", {})
        if not isinstance(data, dict):
            continue
        line = chat_activity_line(str(getattr(record, "kind", "") or ""), data, color=color)
        if line:
            lines.append(line)
    if lines:
        if not printed_header:
            print(style("steps", "dim", color=color))
            printed_header = True
        for line in lines:
            print(line)
        sys.stdout.flush()
    return len(records), printed_header


def handle_chat_local_command(
    text: str,
    *,
    runtime: ChatRuntime,
    thread_id: str,
    output_mode: str,
    color: bool,
) -> tuple[bool, str, str, bool] | None:
    parts = text.split()
    command = parts[0].lower()
    args = parts[1:]
    if command not in {"/thread", "/threads", "/history", "/color", "/json", "/quit", "/exit", "/help", "/?"}:
        return None
    status = "ok"
    result: JsonObject
    new_thread = thread_id
    new_output = output_mode
    new_color = color
    exit_requested = False
    if command in {"/quit", "/exit"}:
        result = {"message": "bye", "thread_id": thread_id}
        exit_requested = True
    elif command in {"/help", "/?"}:
        result = {
            "commands": [
                "/thread",
                "/thread list",
                "/thread switch <thread_id>",
                "/thread new <thread_id>",
                "/threads",
                "/history [limit]",
                "/json on|off",
                "/color on|off",
                "/quit",
            ],
            "runtime_commands": ["/status", "/summary", "/tasks", "/trace", "/plan", "/memory", "/cancel", "/interrupt"],
        }
    elif command == "/threads":
        threads = known_chat_threads(runtime)
        result = {"current_thread": thread_id, "threads": threads}
    elif command == "/history":
        limit = parse_history_limit(args, default=12)
        if limit is None:
            status = "failed"
            result = {"error": "invalid_history_limit", "usage": "/history [limit]"}
        else:
            result = {"current_thread": thread_id, "limit": limit, "history": thread_history(runtime, thread_id, limit=limit)}
    elif command == "/thread":
        if args and args[0].lower() in {"list", "ls", "threads"}:
            threads = known_chat_threads(runtime)
            result = {"current_thread": thread_id, "threads": threads}
        elif not args or args[0].lower() in {"status", "show", "current"}:
            state = runtime.build_thread_state(thread_id).to_dict()
            result = {"current_thread": thread_id, "state": state}
        elif args[0].lower() in {"create", "new", "switch", "use"}:
            if len(args) < 2 or not args[1].strip():
                status = "failed"
                result = {"error": "missing_thread_id", "usage": "/thread new <thread_id>"}
            else:
                command_action = args[0].lower()
                new_thread = args[1].strip()
                already_exists = thread_known(runtime, new_thread)
                action = "created" if command_action in {"create", "new"} and not already_exists else "switched"
                record = append_thread_event(
                    runtime,
                    thread_id=new_thread,
                    action=action,
                    previous_thread_id=thread_id,
                    created=not already_exists,
                )
                state = runtime.build_thread_state(new_thread).to_dict()
                result = {
                    "current_thread": new_thread,
                    "previous_thread": thread_id,
                    "created": not already_exists,
                    "event_ref": record.record_id,
                    "state": state,
                }
        else:
            new_thread = args[0].strip()
            already_exists = thread_known(runtime, new_thread)
            record = append_thread_event(
                runtime,
                thread_id=new_thread,
                action="switched",
                previous_thread_id=thread_id,
                created=not already_exists,
            )
            state = runtime.build_thread_state(new_thread).to_dict()
            result = {
                "current_thread": new_thread,
                "previous_thread": thread_id,
                "created": not already_exists,
                "event_ref": record.record_id,
                "state": state,
            }
    elif command == "/json":
        if not args:
            result = {"output": new_output}
        elif args[0].lower() in {"on", "true", "1"}:
            new_output = "json"
            result = {"output": new_output}
        elif args[0].lower() in {"off", "false", "0"}:
            new_output = "human"
            result = {"output": new_output}
        else:
            status = "failed"
            result = {"error": "invalid_json_command", "usage": "/json on|off"}
    elif command == "/color":
        if not args:
            result = {"color": new_color}
        elif args[0].lower() in {"on", "true", "1"}:
            new_color = True
            result = {"color": new_color}
        elif args[0].lower() in {"off", "false", "0"}:
            new_color = False
            result = {"color": new_color}
        else:
            status = "failed"
            result = {"error": "invalid_color_command", "usage": "/color on|off"}
    else:
        return None
    print_chat_local_result(
        {"status": status, "command": command, "result": result},
        output_mode=output_mode,
        color=new_color,
    )
    return exit_requested, new_thread, new_output, new_color


def chat_output_mode(options: ChatConsoleOptions | Any, *, once: bool) -> str:
    requested = str(getattr(options, "output", "auto") or "auto")
    if requested in {"human", "json"}:
        return requested
    if once:
        return "json"
    return "human" if stream_is_tty(sys.stdin) else "json"


def chat_color_enabled(options: ChatConsoleOptions | Any) -> bool:
    if bool(getattr(options, "no_color", False)):
        return False
    requested = str(getattr(options, "color", "auto") or "auto")
    if requested == "always":
        return True
    if requested == "never":
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return stream_is_tty(sys.stdout)


def stream_is_tty(stream: object) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


def chat_banner(thread_id: str, *, color: bool) -> str:
    title = style("Holo Kernel v3 chat", "bold_cyan", color=color)
    hint = "Commands: /thread new <id>, /thread switch <id>, /threads, /history, /json on, /color off, /quit"
    return f"{title}\n{style('Thread', 'dim', color=color)}: {thread_id}\n{style(hint, 'dim', color=color)}"


def chat_prompt(thread_id: str, *, color: bool) -> str:
    return style(f"holo[{thread_id}]> ", "bold_green", color=color)


def print_chat_local_result(payload: JsonObject, *, output_mode: str, color: bool) -> None:
    if output_mode == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    status = str(payload.get("status", "ok"))
    command = str(payload.get("command", "local"))
    result = payload.get("result", {})
    lines = [style(f"{command} {status}", status_style(status), color=color)]
    if isinstance(result, dict) and "threads" in result:
        threads = result.get("threads")
        if isinstance(threads, list) and threads:
            for item in threads:
                if isinstance(item, dict):
                    marker = "*" if item.get("thread_id") == result.get("current_thread") else " "
                    lines.append(
                        f"{marker} {item.get('thread_id')} turns={item.get('turn_count')} status={item.get('last_result_status')}"
                    )
        else:
            lines.append("No chat threads recorded yet.")
    elif isinstance(result, dict) and "history" in result:
        lines.append(f"thread: {result.get('current_thread')}")
        history = result.get("history")
        if isinstance(history, list) and history:
            for item in history:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "event")
                label = style(role, "cyan" if role == "user" else "green", color=color)
                meta = str(item.get("meta") or "")
                text = str(item.get("text") or "")
                suffix = f" {style(meta, 'dim', color=color)}" if meta else ""
                lines.append(f"{item.get('index')}. {label}{suffix}: {text}")
        else:
            lines.append("No history for this thread yet.")
    elif isinstance(result, dict) and "current_thread" in result:
        lines.append(f"thread: {result['current_thread']}")
        if "created" in result:
            lines.append(f"created: {str(bool(result['created'])).lower()}")
        if result.get("event_ref"):
            lines.append(f"event_ref: {result['event_ref']}")
        state = result.get("state")
        if isinstance(state, dict):
            lines.append(thread_state_line(state))
    elif isinstance(result, dict) and "commands" in result:
        lines.append("CLI commands: " + ", ".join(str(item) for item in result.get("commands", [])))
        lines.append("Runtime commands: " + ", ".join(str(item) for item in result.get("runtime_commands", [])))
    elif isinstance(result, dict) and "message" in result:
        lines.append(str(result["message"]))
    else:
        lines.append(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print("\n".join(lines))
    print()


def render_chat_result(payload: object, *, color: bool) -> str:
    data = payload.to_dict()
    status = str(data.get("status", "unknown"))
    route = str(data.get("route", "unknown"))
    header = style(f"{status}", status_style(status), color=color)
    refs = []
    if data.get("task_id"):
        refs.append(f"task={data['task_id']}")
    if data.get("run_id"):
        refs.append(f"run={data['run_id']}")
    refs.append(f"route={route}")
    lines = [f"{header} {style(' '.join(refs), 'dim', color=color)}"]
    answer = chat_answer_text(data)
    if answer:
        lines.append(f"{event_label('answer', color=color)} {output_text(answer, color=color)}")
    pending = data.get("pending_question")
    if isinstance(pending, dict) and pending.get("question"):
        lines.append(style("needs input:", "yellow", color=color) + f" {pending['question']}")
    failure = data.get("failure_report")
    if isinstance(failure, dict) and failure:
        reason = failure.get("reason") or failure.get("status") or "failed"
        lines.append(style("failure:", "red", color=color) + f" {reason}")
        missing = failure.get("missing_evidence")
        if isinstance(missing, list) and missing:
            lines.append(style("missing:", "yellow", color=color) + f" {compact_list(missing, limit=6)}")
        attempted = failure.get("attempted_actions")
        if isinstance(attempted, list) and attempted:
            lines.append(style("attempted:", "dim", color=color) + f" {compact_list(attempted, limit=6)}")
        next_action = failure.get("next_possible_action")
        if isinstance(next_action, str) and next_action:
            lines.append(style("next:", "dim", color=color) + f" {next_action}")
    if data.get("command_result") and not answer:
        lines.append(json.dumps(data["command_result"], ensure_ascii=False, sort_keys=True))
    trace_refs = data.get("trace_refs")
    if isinstance(trace_refs, list) and trace_refs:
        lines.append(style(f"trace_refs={len(trace_refs)}", "dim", color=color))
    return "\n".join(lines)


def render_chat_activity(records: list[object], *, color: bool) -> str:
    lines: list[str] = []
    for record in records:
        kind = str(getattr(record, "kind", "") or "")
        data = getattr(record, "data", {})
        if not isinstance(data, dict):
            continue
        line = chat_activity_line(kind, data, color=color)
        if line:
            lines.append(line)
    if not lines:
        return ""
    return "\n".join([style("steps", "dim", color=color), *lines])


def chat_activity_line(kind: str, data: JsonObject, *, color: bool) -> str | None:
    if kind == "context":
        state = data.get("state")
        sections = data.get("packs") or data.get("sections")
        if not sections and isinstance(state, dict):
            sections = state.get("sections")
        return activity_line(
            "context",
            f"context compiled id={data.get('context_id')} sections={len(sections or [])}",
            color=color,
        )
    if kind == "chat_routing_decision":
        return activity_line("route", f"route {data.get('route')} reasons={compact_list(data.get('reasons'))}", color=color)
    if kind == "processor_request":
        task_type = data.get("task_type") or data.get("processor")
        provider = data.get("provider")
        model = data.get("model")
        params = data.get("parameters")
        tail = processor_parameter_tail(params if isinstance(params, dict) else {})
        return activity_line("model", f"model request {task_type} provider={provider} model={model}{tail}", color=color)
    if kind == "processor_result":
        task_type = data.get("task_type")
        status = data.get("status")
        duration = data.get("duration_ms")
        error = data.get("error")
        usage = data.get("usage")
        token_tail = processor_usage_tail(usage if isinstance(usage, dict) else {})
        error_tail = f" error={error}" if error else ""
        return activity_line(
            "model",
            f"model result {task_type} status={status} duration_ms={duration}{token_tail}{error_tail}",
            status=str(status or ""),
            color=color,
        )
    if kind == "semantic_intake":
        return activity_line(
            "reason",
            f"semantic intent={data.get('primary_intent')} mode={data.get('suggested_mode')} blocked={compact_list(data.get('blocked_capabilities'))}",
            color=color,
        )
    if kind == "semantic_task_plan":
        return activity_line(
            "reason",
            f"task plan status={data.get('status')} mode={data.get('selected_mode')} steps={len(data.get('steps') or [])} blocked={compact_list(data.get('blocked_capabilities'))}",
            status=str(data.get("status") or ""),
            color=color,
        )
    if kind == "action":
        action = data.get("name") or data.get("kind")
        category = "action" if action == "respond" and data.get("side_effect_class") == "none" else "tool"
        return activity_line(
            category,
            f"action {action} side_effect={data.get('side_effect_class')} reasons={compact_list(data.get('reasons'))}",
            color=color,
        )
    if kind == "policy_decision":
        status = "ok" if data.get("allowed") else "blocked"
        return activity_line("policy", f"policy allowed={data.get('allowed')} reason={data.get('reason')}", status=status, color=color)
    if kind == "observation":
        source = data.get("source") or data.get("kind")
        category = "tool" if str(source).startswith("tool:") else "observe"
        return activity_line(category, f"observation source={source} status={data.get('status')}", status=str(data.get("status") or ""), color=color)
    if kind == "feedback":
        return activity_line(
            "reason",
            f"evaluator feedback status={data.get('status')} missing={compact_list(data.get('missing_evidence'))} stop={data.get('stop_reason')}",
            status=str(data.get("status") or ""),
            color=color,
        )
    if kind == "retrieval_query_plan":
        diagnostics = data.get("diagnostics")
        query_count = diagnostics.get("query_count") if isinstance(diagnostics, dict) else None
        return activity_line(
            "retrieval",
            f"retrieval query plan queries={query_count or len(data.get('queries') or [])} max_sources={data.get('max_sources')} max_fetches={data.get('max_fetches')}",
            color=color,
        )
    if kind == "retrieval_search_attempt":
        return activity_line(
            "retrieval",
            f"retrieval search query={preview_history_text(str(data.get('query') or ''), limit=80)} status={data.get('status')} sources={len(data.get('sources') or [])}",
            status=str(data.get("status") or ""),
            color=color,
        )
    if kind == "retrieval_rank_sources":
        return activity_line("retrieval", f"retrieval rank sources={len(data.get('ranked_sources') or [])}", color=color)
    if kind == "retrieval_fetch_attempt":
        return activity_line(
            "retrieval",
            f"retrieval fetch source={data.get('source_id')} status={data.get('status')} bytes={data.get('size_bytes')}",
            status=str(data.get("status") or ""),
            color=color,
        )
    if kind == "retrieval_extraction":
        diagnostics = data.get("diagnostics")
        span_count = diagnostics.get("span_count") if isinstance(diagnostics, dict) else len(data.get("spans") or [])
        document = data.get("document")
        title = document.get("title") if isinstance(document, dict) else None
        return activity_line("retrieval", f"retrieval extract spans={span_count} doc={preview_history_text(str(title or ''), limit=80)}", color=color)
    if kind == "retrieval_evidence":
        return activity_line("evidence", f"evidence {data.get('evidence_id')} score={data.get('score')} source={data.get('source_id')}", color=color)
    if kind == "retrieval_citation":
        return activity_line("evidence", f"citation {data.get('citation_id')} evidence={data.get('evidence_id')}", color=color)
    if kind == "retrieval_report":
        return activity_line(
            "retrieval",
            f"retrieval report status={data.get('status')} evidence={data.get('evidence_count')} citations={data.get('citation_count')}",
            status=str(data.get("status") or ""),
            color=color,
        )
    if kind == "progress_assessment":
        return activity_line("reason", f"progress made={data.get('made_progress')} type={data.get('progress_type')} score={data.get('progress_score')}", color=color)
    if kind == "repetition_signal":
        status = "blocked" if data.get("repeated") else None
        return activity_line("reason", f"repetition repeated={data.get('repeated')} type={data.get('repeat_type')}", status=status, color=color)
    if kind == "evidence_sufficiency":
        status = "sufficient" if data.get("sufficient") else "blocked"
        return activity_line("reason", f"evidence sufficient={data.get('sufficient')} reason={data.get('reason')}", status=status, color=color)
    if kind == "termination_decision":
        return activity_line("reason", f"termination decision={data.get('decision')} reason={data.get('reason')}", color=color)
    if kind == "agent_final_answer":
        return activity_line("final", f"final answer confidence={data.get('confidence')}", color=color)
    if kind == "agent_failure_report":
        return activity_line("failure", f"failure reason={data.get('reason')}", status="failed", color=color)
    if kind == "chat_agent_result":
        return activity_line("chat", f"chat result status={data.get('status')} route={data.get('route')}", status=str(data.get("status") or ""), color=color)
    return None


def activity_line(category: str, text: str, *, color: bool, status: str | None = None) -> str:
    return f"{style('·', 'dim', color=color)} {event_label(category, status=status, color=color)} {output_text(text, color=color)}"


def event_label(category: str, *, color: bool, status: str | None = None) -> str:
    label = f"[{category}]"
    return style(label, event_style(category, status=status), color=color)


def output_text(text: str, *, color: bool) -> str:
    return style(text, "light", color=color)


def processor_parameter_tail(parameters: JsonObject) -> str:
    parts: list[str] = []
    for key, label in (
        ("thinking", "thinking"),
        ("reasoning_effort", "effort"),
        ("temperature", "temp"),
        ("timeout_seconds", "timeout"),
    ):
        value = parameters.get(key)
        if value is not None:
            parts.append(f"{label}={value}")
    return " " + " ".join(parts) if parts else ""


def processor_usage_tail(usage: JsonObject) -> str:
    total = usage.get("total_tokens")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if total is None and prompt is None and completion is None:
        return ""
    return f" tokens={total or '-'} prompt={prompt or '-'} completion={completion or '-'}"


def compact_list(value: object, *, limit: int = 3) -> str:
    if not isinstance(value, list) or not value:
        return "[]"
    items = [str(item) for item in value[:limit]]
    suffix = ", ..." if len(value) > limit else ""
    return "[" + ", ".join(items) + suffix + "]"


def render_status_notice(payload: JsonObject, *, color: bool) -> str:
    status = str(payload.get("status", "unknown"))
    reason = str(payload.get("reason") or payload.get("error") or "")
    message = str(payload.get("message") or "")
    lines = [style(status, status_style(status), color=color)]
    if reason:
        lines[0] = f"{lines[0]} {style(reason, 'dim', color=color)}"
    if message:
        lines.append(message)
    return "\n".join(lines)


def chat_answer_text(data: JsonObject) -> str | None:
    answer = data.get("answer")
    if isinstance(answer, str) and answer:
        return answer
    final_answer = data.get("final_answer")
    if isinstance(final_answer, dict):
        final_text = final_answer.get("answer")
        if isinstance(final_text, str) and final_text:
            return final_text
    summary = data.get("summary")
    if isinstance(summary, dict):
        preview = summary.get("last_answer_preview")
        if isinstance(preview, str) and preview:
            return preview
    failure = data.get("failure_report")
    if isinstance(failure, dict) and failure:
        return failure_answer_text(failure)
    return None


def failure_answer_text(failure: JsonObject) -> str:
    reason = str(failure.get("reason") or "failed")
    attempted = failure.get("attempted_actions")
    missing = failure.get("missing_evidence")
    next_action = failure.get("next_possible_action")
    lines = ["我这次没有完成目标，因为没有拿到足够可靠的结果。"]
    if isinstance(attempted, list) and attempted:
        lines.append(f"我已经尝试过：{', '.join(str(item) for item in attempted[:4])}。")
    if reason:
        lines.append(f"停止原因：{reason}。")
    if isinstance(missing, list) and missing:
        lines.append(f"缺少：{', '.join(str(item) for item in missing[:4])}。")
    if isinstance(next_action, str) and next_action:
        lines.append(f"下一步：{next_action}。")
    lines.append("我不会把没有证据的内容编成答案。")
    return "\n".join(lines)


def parse_history_limit(args: list[str], *, default: int) -> int | None:
    if not args:
        return default
    try:
        value = int(args[0])
    except ValueError:
        return None
    if value <= 0:
        return None
    return min(value, 100)


def thread_history(runtime: ChatRuntime, thread_id: str, *, limit: int) -> list[JsonObject]:
    entries: list[JsonObject] = []
    transcript_store = getattr(runtime, "thread_store", None)
    if transcript_store is not None:
        entries.extend(_thread_history_entries_from_transcript(transcript_store.records(thread_id)))
    for record in runtime.journal.records():
        data = record.data if isinstance(record.data, dict) else {}
        if data.get("thread_id") != thread_id:
            continue
        if record.kind == "chat_turn":
            entries.append(
                {
                    "record_id": record.record_id,
                    "recorded_at_ms": record.recorded_at_ms,
                    "role": str(data.get("role") or "user"),
                    "text": str(data.get("text") or ""),
                    "meta": str(data.get("task_id") or ""),
                }
            )
        elif record.kind == "chat_agent_result":
            text = chat_answer_text(data) or _chat_result_status_text(data)
            entries.append(
                {
                    "record_id": record.record_id,
                    "recorded_at_ms": record.recorded_at_ms,
                    "role": "assistant",
                    "text": text,
                    "meta": f"status={data.get('status')} route={data.get('route')}",
                }
            )
    entries = sorted(
        _dedupe_history_entries(entries),
        key=lambda item: (int(item.get("recorded_at_ms") or 0), str(item.get("record_id") or "")),
    )
    recent = entries[-limit:]
    start = len(entries) - len(recent) + 1
    return [{**entry, "index": start + offset, "text": preview_history_text(str(entry.get("text") or ""))} for offset, entry in enumerate(recent)]


def _chat_result_status_text(data: JsonObject) -> str:
    failure = data.get("failure_report")
    if isinstance(failure, dict) and failure.get("reason"):
        return f"failure: {failure['reason']}"
    pending = data.get("pending_question")
    if isinstance(pending, dict) and pending.get("question"):
        return f"needs input: {pending['question']}"
    command_result = data.get("command_result")
    if isinstance(command_result, dict):
        return json.dumps(command_result, ensure_ascii=False, sort_keys=True)
    return str(data.get("status") or "completed")


def preview_history_text(text: str, *, limit: int = 260) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def known_chat_threads(runtime: ChatRuntime) -> list[JsonObject]:
    payload_by_thread = {item["thread_id"]: item for item in _known_chat_threads_from_journal(runtime)}
    transcript_store = getattr(runtime, "thread_store", None)
    if transcript_store is not None:
        for item in transcript_store.threads():
            thread_id = str(item.get("thread_id") or "")
            if not thread_id:
                continue
            state = runtime.build_thread_state(thread_id).to_dict()
            existing = dict(payload_by_thread.get(thread_id) or {})
            payload_by_thread[thread_id] = {
                "thread_id": thread_id,
                "turn_count": max(int(existing.get("turn_count") or 0), int(item.get("turn_count") or 0)),
                "active_task_id": state.get("active_task_id") or existing.get("active_task_id"),
                "pending_question": bool(state.get("pending_question") or item.get("pending_question") or existing.get("pending_question")),
                "last_result_status": state.get("last_result_status") or item.get("last_result_status") or existing.get("last_result_status"),
                "last_recorded_at_ms": max(int(existing.get("last_recorded_at_ms") or 0), int(item.get("last_recorded_at_ms") or 0)),
                "transcript_path": item.get("transcript_path") or existing.get("transcript_path"),
            }
    ordered = sorted(
        payload_by_thread.values(),
        key=lambda item: (-int(item.get("last_recorded_at_ms") or 0), str(item.get("thread_id") or "")),
    )
    for item in ordered:
        item.pop("last_recorded_at_ms", None)
    return ordered


def _known_chat_threads_from_journal(runtime: ChatRuntime) -> list[JsonObject]:
    latest: dict[str, int] = {}
    turns: dict[str, int] = {}
    for record in runtime.journal.records():
        data = record.data if isinstance(record.data, dict) else {}
        thread_id = data.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            continue
        latest[thread_id] = max(latest.get(thread_id, 0), record.recorded_at_ms)
        if record.kind == "chat_turn":
            turns[thread_id] = turns.get(thread_id, 0) + 1
    ordered = sorted(latest, key=lambda item: (-latest[item], item))
    payload: list[JsonObject] = []
    for thread_id in ordered:
        state = runtime.build_thread_state(thread_id).to_dict()
        payload.append(
            {
                "thread_id": thread_id,
                "turn_count": turns.get(thread_id, 0),
                "active_task_id": state.get("active_task_id"),
                "pending_question": bool(state.get("pending_question")),
                "last_result_status": state.get("last_result_status"),
                "last_recorded_at_ms": latest[thread_id],
            }
        )
    return payload


def thread_known(runtime: ChatRuntime, thread_id: str) -> bool:
    return any(item.get("thread_id") == thread_id for item in known_chat_threads(runtime))


def append_thread_event(
    runtime: ChatRuntime,
    *,
    thread_id: str,
    action: str,
    previous_thread_id: str | None,
    created: bool,
):
    record = runtime.journal.append(
        task_id=None,
        run_id=f"chat-thread-{thread_id}",
        step_id=None,
        kind="chat_thread_event",
        data={
            "thread_id": thread_id,
            "action": action,
            "previous_thread_id": previous_thread_id,
            "created": created,
        },
        state_delta={"thread_id": thread_id, "chat_thread_action": action},
    )
    transcript_store = getattr(runtime, "thread_store", None)
    if transcript_store is not None:
        transcript_store.append_journal_record(record)
    return record


def thread_state_line(state: JsonObject) -> str:
    parts = [
        f"active_task={state.get('active_task_id') or '-'}",
        f"last_status={state.get('last_result_status') or '-'}",
        f"pending={'yes' if state.get('pending_question') else 'no'}",
        f"recent_tasks={len(state.get('recent_task_refs') or [])}",
    ]
    return " ".join(parts)


def _thread_history_entries_from_transcript(records: list[JsonObject]) -> list[JsonObject]:
    entries: list[JsonObject] = []
    for record in records:
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        if record.get("kind") == "chat_turn":
            entries.append(
                {
                    "record_id": record.get("record_id"),
                    "recorded_at_ms": record.get("recorded_at_ms"),
                    "role": str(data.get("role") or "user"),
                    "text": str(data.get("text") or ""),
                    "meta": str(data.get("task_id") or ""),
                }
            )
        elif record.get("kind") == "chat_agent_result":
            text = chat_answer_text(data) or _chat_result_status_text(data)
            entries.append(
                {
                    "record_id": record.get("record_id"),
                    "recorded_at_ms": record.get("recorded_at_ms"),
                    "role": "assistant",
                    "text": text,
                    "meta": f"status={data.get('status')} route={data.get('route')}",
                }
            )
    return entries


def _dedupe_history_entries(entries: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    deduped: list[JsonObject] = []
    for entry in entries:
        key = str(entry.get("record_id") or "")
        if not key:
            key = json.dumps(
                {
                    "recorded_at_ms": entry.get("recorded_at_ms"),
                    "role": entry.get("role"),
                    "text": entry.get("text"),
                    "meta": entry.get("meta"),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped
