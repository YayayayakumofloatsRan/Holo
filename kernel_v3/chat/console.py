from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

from kernel_v3.chat.runtime import ChatRuntime
from kernel_v3.chat.theme import status_style, style
from kernel_v3.contracts import JsonObject


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
    stripped = text.strip()
    if not stripped:
        return False, thread_id, output_mode, color
    local = handle_chat_local_command(stripped, runtime=runtime, thread_id=thread_id, output_mode=output_mode, color=color)
    if local is not None:
        return local
    start_index = len(runtime.journal.records())
    if output_mode == "human":
        print(style("processing...", "dim", color=color))
        sys.stdout.flush()
    payload = runtime.receive(stripped, thread_id=thread_id)
    if output_mode == "json":
        print(json.dumps(payload.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(render_chat_result(payload, color=color))
        activity = render_chat_activity(runtime.journal.records()[start_index:], color=color)
        if activity:
            print(activity)
    sys.stdout.flush()
    return False, thread_id, output_mode, color


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
    if command not in {"/thread", "/threads", "/color", "/json", "/quit", "/exit", "/help", "/?"}:
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
                "/json on|off",
                "/color on|off",
                "/quit",
            ],
            "runtime_commands": ["/status", "/summary", "/tasks", "/trace", "/plan", "/memory", "/cancel", "/interrupt"],
        }
    elif command == "/threads":
        threads = known_chat_threads(runtime)
        result = {"current_thread": thread_id, "threads": threads}
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
    hint = "Commands: /thread new <id>, /thread switch <id>, /threads, /json on, /color off, /quit"
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
        lines.append(answer)
    pending = data.get("pending_question")
    if isinstance(pending, dict) and pending.get("question"):
        lines.append(style("needs input:", "yellow", color=color) + f" {pending['question']}")
    failure = data.get("failure_report")
    if isinstance(failure, dict) and failure:
        reason = failure.get("reason") or failure.get("status") or "failed"
        lines.append(style("failure:", "red", color=color) + f" {reason}")
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
    prefix = style("·", "dim", color=color)
    if kind == "chat_routing_decision":
        return f"{prefix} route {data.get('route')} reasons={compact_list(data.get('reasons'))}"
    if kind == "processor_request":
        task_type = data.get("task_type") or data.get("processor")
        provider = data.get("provider")
        model = data.get("model")
        return f"{prefix} model request {task_type} provider={provider} model={model}"
    if kind == "processor_result":
        task_type = data.get("task_type")
        status = data.get("status")
        duration = data.get("duration_ms")
        error = data.get("error")
        tail = f" error={error}" if error else ""
        return f"{prefix} model result {task_type} status={status} duration_ms={duration}{tail}"
    if kind == "semantic_intake":
        return f"{prefix} semantic intent={data.get('primary_intent')} mode={data.get('suggested_mode')} blocked={compact_list(data.get('blocked_capabilities'))}"
    if kind == "semantic_task_plan":
        return f"{prefix} task plan status={data.get('status')} mode={data.get('selected_mode')} blocked={compact_list(data.get('blocked_capabilities'))}"
    if kind == "action":
        action = data.get("name") or data.get("kind")
        return f"{prefix} action {action} side_effect={data.get('side_effect_class')}"
    if kind == "policy_decision":
        return f"{prefix} policy allowed={data.get('allowed')} reason={data.get('reason')}"
    if kind == "observation":
        source = data.get("source") or data.get("kind")
        return f"{prefix} observation source={source} status={data.get('status')}"
    if kind == "retrieval_report":
        return f"{prefix} retrieval report status={data.get('status')} evidence={data.get('evidence_count')} citations={data.get('citation_count')}"
    if kind == "progress_assessment":
        return f"{prefix} progress made={data.get('made_progress')} type={data.get('progress_type')} score={data.get('progress_score')}"
    if kind == "repetition_signal":
        return f"{prefix} repetition repeated={data.get('repeated')} type={data.get('repeat_type')}"
    if kind == "evidence_sufficiency":
        return f"{prefix} evidence sufficient={data.get('sufficient')} reason={data.get('reason')}"
    if kind == "termination_decision":
        return f"{prefix} termination decision={data.get('decision')} reason={data.get('reason')}"
    if kind == "agent_final_answer":
        return f"{prefix} final answer confidence={data.get('confidence')}"
    if kind == "agent_failure_report":
        return f"{prefix} failure reason={data.get('reason')}"
    if kind == "chat_agent_result":
        return f"{prefix} chat result status={data.get('status')} route={data.get('route')}"
    return None


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
    return None


def known_chat_threads(runtime: ChatRuntime) -> list[JsonObject]:
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
    return runtime.journal.append(
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


def thread_state_line(state: JsonObject) -> str:
    parts = [
        f"active_task={state.get('active_task_id') or '-'}",
        f"last_status={state.get('last_result_status') or '-'}",
        f"pending={'yes' if state.get('pending_question') else 'no'}",
        f"recent_tasks={len(state.get('recent_task_refs') or [])}",
    ]
    return " ".join(parts)
