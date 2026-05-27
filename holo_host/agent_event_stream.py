from __future__ import annotations

import json
from typing import Any

from .canonical_stop_reason import map_canonical_stop_reason
from .common import compact_text
from .engineering_action_fabric import normalize_engineering_action_ledger
from .kernel_metadata_sanitizer import sanitize_public_metadata

AGENT_EVENT_STREAM_SCHEMA = "holo.stage153.agent_event_stream.v1"


def _compact(value: Any, limit: int = 180) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _final_text(payload: dict[str, Any]) -> str:
    bubbles = payload.get("bubbles", [])
    if isinstance(bubbles, list):
        lines = [str(item.get("text", item) if isinstance(item, dict) else item).strip() for item in bubbles]
        text = "\n".join(line for line in lines if line)
        if text:
            return text
    return str(payload.get("text", "") or "").strip()


def sanitize_event_payload(value: Any) -> Any:
    value = sanitize_public_metadata(value)
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            clean[key] = sanitize_event_payload(item)
        return clean
    if isinstance(value, list):
        return [sanitize_event_payload(item) for item in value]
    if isinstance(value, str):
        if "reasoning_content" in value.lower() or "chain_of_thought" in value.lower():
            return "[redacted]"
    return value


def _stage151_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    decision = payload.get("stage151_tool_decision", {})
    if not isinstance(decision, dict):
        return []
    rows = []
    for item in list(decision.get("action_candidates", []) or [])[:8]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "event": "candidate",
                "action_type": str(item.get("action_type", "") or ""),
                "score": float(item.get("score", 0.0) or 0.0),
                "required_observations": [str(x) for x in list(item.get("required_observations", []) or [])],
                "reason": _compact(item.get("reason", ""), 140),
            }
        )
    return rows


def _tool_call_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    trace = payload.get("stage152_live_trace", {})
    if isinstance(trace, dict):
        for item in list(trace.get("events", []) or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("event", "")) in {"tool", "tool_call"}:
                events.append(
                    {
                        "event": "tool_call",
                        "action_type": str(item.get("tool", item.get("action_type", "")) or ""),
                        "query": _compact(item.get("query", item.get("url", "")), 160),
                        "status": str(item.get("status", "accepted") or "accepted"),
                    }
                )
    if events:
        return events
    web_rows = [row for row in list(payload.get("web_observation_ledger", []) or []) if isinstance(row, dict)]
    if web_rows:
        return [
            {
                "event": "tool_call",
                "action_type": str(row.get("action_type", "web_search") or "web_search"),
                "query": _compact(row.get("query", row.get("url", "")), 160),
                "status": "recorded",
            }
            for row in web_rows[:5]
        ]
    return [{"event": "tool_call", "action_type": "none", "status": "no_tool_calls", "query": ""}]


def _observation_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in list(payload.get("web_observation_ledger", []) or [])[:8]:
        if not isinstance(row, dict):
            continue
        events.append(
            {
                "event": "observation",
                "action_type": str(row.get("action_type", "web_search") or "web_search"),
                "status": str(row.get("status", "") or ""),
                "query": _compact(row.get("query", row.get("url", "")), 160),
                "source_count": len(list(row.get("source_urls", []) or [])),
                "source_urls": [str(url) for url in list(row.get("source_urls", []) or [])[:3]],
                "result_count": len(list(row.get("results", []) or [])),
                "search_evidence_status": str(dict(row.get("search_evidence", {}) if isinstance(row.get("search_evidence", {}), dict) else {}).get("status", "") or ""),
                "evidence_score": float(dict(row.get("search_evidence", {}) if isinstance(row.get("search_evidence", {}), dict) else {}).get("evidence_score", 0.0) or 0.0),
                "page_evidence_status": str(dict(row.get("page_evidence", {}) if isinstance(row.get("page_evidence", {}), dict) else {}).get("status", "") or ""),
                "page_opened_count": int(dict(row.get("page_evidence", {}) if isinstance(row.get("page_evidence", {}), dict) else {}).get("opened_count", 0) or 0),
                "source_synthesis_status": str(dict(row.get("source_synthesis", {}) if isinstance(row.get("source_synthesis", {}), dict) else {}).get("status", "") or ""),
                "source_synthesis_supported_count": int(dict(row.get("source_synthesis", {}) if isinstance(row.get("source_synthesis", {}), dict) else {}).get("supported_source_count", 0) or 0),
            }
        )
    for row in list(payload.get("tool_observation_ledger", []) or [])[:8]:
        if not isinstance(row, dict):
            continue
        if str(row.get("tool", row.get("tool_name", "")) or "").startswith("web_"):
            continue
        events.append(
            {
                "event": "observation",
                "action_type": str(row.get("tool", row.get("tool_name", "tool")) or "tool"),
                "status": str(row.get("status", "") or ""),
                "query": _compact(row.get("summary", ""), 160),
                "source_count": 0,
                "source_urls": [],
                "result_count": 1 if row.get("summary") else 0,
            }
        )
    for row in list(payload.get("market_research_pack_ledger", []) or [])[:5]:
        if not isinstance(row, dict):
            continue
        events.append(
            {
                "event": "observation",
                "action_type": "market_research_pack",
                "status": str(row.get("status", "") or ""),
                "query": _compact(row.get("query", ""), 160),
                "source_count": len(list(row.get("source_urls", []) or [])),
                "source_urls": [str(url) for url in list(row.get("source_urls", []) or [])[:3]],
                "result_count": int(row.get("evidence_item_count", 0) or 0),
            }
        )
    for row in list(payload.get("market_research_report_ledger", []) or [])[:5]:
        if not isinstance(row, dict):
            continue
        events.append(
            {
                "event": "observation",
                "action_type": "market_research_report",
                "status": str(row.get("status", "") or ""),
                "query": _compact(row.get("query", ""), 160),
                "source_count": len(list(row.get("source_urls", []) or [])),
                "source_urls": [str(url) for url in list(row.get("source_urls", []) or [])[:3]],
                "result_count": int(row.get("citation_count", 0) or 0),
            }
        )
    filing = payload.get("filing_text_retrieval", {})
    if isinstance(filing, dict) and filing:
        events.append(
            {
                "event": "observation",
                "action_type": "filing_text_retrieval",
                "status": str(filing.get("status", "") or ""),
                "query": _compact(filing.get("query", filing.get("source_url", "")), 160),
                "source_count": 1 if filing.get("source_url") else 0,
                "source_urls": [str(filing.get("source_url", ""))] if filing.get("source_url") else [],
                "result_count": int(filing.get("filing_text_char_count", 0) or 0),
            }
        )
    return events


def _engineering_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    label_by_action = {
        "workspace_search": "eng:search",
        "file_read": "eng:read",
        "apply_patch": "eng:patch",
        "test_run": "eng:test",
        "git_status": "eng:diff",
        "git_diff": "eng:diff",
        "handoff": "eng:handoff",
    }
    for row in normalize_engineering_action_ledger(payload.get("engineering_action_ledger", []))[:12]:
        action_type = str(row.get("action_type", "") or "")
        label = label_by_action.get(action_type, "eng:handoff")
        events.append(
            {
                "event": label,
                "action_type": action_type,
                "status": str(row.get("status", "") or ""),
                "files_read": list(row.get("files_read", []) or []),
                "files_changed": list(row.get("files_changed", []) or []),
                "commands_run": list(row.get("commands_run", []) or []),
                "summary": _compact(row.get("stdout_summary", row.get("stderr_summary", "")), 160),
            }
        )
    return events


def _cache_event(payload: dict[str, Any]) -> dict[str, Any]:
    usage = {}
    if isinstance(payload.get("usage", {}), dict):
        usage.update(payload.get("usage", {}))
    loop = payload.get("stage152_deepseek_tool_loop", {})
    if isinstance(loop, dict) and isinstance(loop.get("usage", {}), dict):
        usage.update(loop.get("usage", {}))
    return {
        "event": "cache",
        "prompt_cache_hit_tokens": int(usage.get("prompt_cache_hit_tokens", 0) or 0),
        "prompt_cache_miss_tokens": int(usage.get("prompt_cache_miss_tokens", 0) or 0),
    }


def build_agent_event_stream(
    payload: dict[str, Any] | None,
    *,
    user_text: str = "",
    thread_key: str = "",
    chat_name: str = "",
    channel: str = "",
    transport: str = "",
) -> dict[str, Any]:
    source = sanitize_event_payload(dict(payload or {}))
    fsm = source.get("stage160r_agent_loop_fsm", {})
    if isinstance(fsm, dict) and fsm.get("schema") == "holo.stage160r.agent_loop_fsm.v1":
        events: list[dict[str, Any]] = [
            {"event": "goal", "summary": _compact(user_text or source.get("input_summary", ""), 220)}
        ]
        action_space_count = int(
            source.get("stage161_tool_action_space_count", fsm.get("stage161_tool_action_space_count", 0)) or 0
        )
        if action_space_count:
            events.append({"event": "action_space", "count": action_space_count})
        rendered_remediation_execute = False
        for step in list(fsm.get("steps", []) or []):
            if not isinstance(step, dict):
                continue
            phase = str(step.get("phase", "") or "")
            if phase == "observe":
                continue
            if phase == "decide":
                events.append(
                    {
                        "event": "decide",
                        "action_type": str(step.get("selected_action", "") or ""),
                        "required_observations": list(step.get("required_observations", []) or []),
                    }
                )
            elif phase == "model_decide":
                events.append(
                    {
                        "event": "model_decide",
                        "selected_action": str(step.get("selected_action", "") or ""),
                        "required_observations": list(step.get("required_observations", []) or []),
                    }
                )
            elif phase == "act_or_skip":
                events.append(
                    {
                        "event": "act",
                        "action_type": str(step.get("selected_action", "") or ""),
                        "status": str(step.get("action_status", "") or ""),
                        "skip_reason": str(step.get("skip_reason", "") or ""),
                    }
                )
            elif phase == "observe_result":
                events.append(
                    {
                        "event": "observe",
                        "action_type": str(step.get("selected_action", "") or ""),
                        "status": str(step.get("action_status", "") or ""),
                        "observation_count": len(list(step.get("observation_ids", []) or [])),
                        "unresolved_items": list(step.get("unresolved_items", []) or []),
                    }
                )
            elif phase == "evaluate_stop":
                events.append(
                    {
                        "event": "evaluate",
                        "status": str(step.get("canonical_stop_reason", "") or fsm.get("canonical_stop_reason", "")),
                        "unresolved_items": list(step.get("unresolved_items", []) or []),
                    }
                )
            elif phase in {"remediation_decide", "remediation_plan"}:
                events.append(
                    {
                        "event": "remediation",
                        "phase": phase,
                        "action_type": str(step.get("selected_action", "") or ""),
                        "required_tools": list(step.get("required_observations", []) or []),
                        "unresolved_items": list(step.get("unresolved_items", []) or []),
                        "status": str(step.get("action_status", "") or "planned"),
                    }
                )
            elif phase == "remediation_execute":
                rendered_remediation_execute = True
                events.append(
                    {
                        "event": "remediation_exec",
                        "action_type": str(step.get("selected_action", "") or ""),
                        "status": str(step.get("action_status", "") or "executed"),
                        "observation_count": len(list(step.get("required_observations", []) or [])),
                    }
                )
        execution = source.get("stage180_live_remediation_execution", fsm.get("stage180_live_remediation_execution", {}))
        if (
            not rendered_remediation_execute
            and isinstance(execution, dict)
            and execution.get("schema") == "holo.stage180.live_remediation_executor.v1"
        ):
            for row in list(execution.get("action_results", []) or [])[:5]:
                if not isinstance(row, dict):
                    continue
                events.append(
                    {
                        "event": "remediation_exec",
                        "action_type": str(row.get("action_type", "") or ""),
                        "status": str(row.get("status", "") or ""),
                        "observation_count": int(row.get("observation_count", 0) or 0),
                    }
                )
        continuation = source.get("stage182_remediation_continuation", fsm.get("stage182_remediation_continuation", {}))
        if isinstance(continuation, dict) and continuation.get("schema") == "holo.stage182.remediation_continuation.v1":
            events.append(
                {
                    "event": "remediation_continue",
                    "status": str(continuation.get("status", "") or ""),
                    "round_count": int(continuation.get("round_count", 0) or 0),
                    "executed_count": int(continuation.get("executed_count", 0) or 0),
                    "stop_reason": str(continuation.get("canonical_stop_reason", "") or ""),
                }
            )
        events.append(
            {
                "event": "stop",
                "reason": str(fsm.get("canonical_stop_reason", "") or "final_answer_ready"),
                "source": "stage160r_agent_loop_fsm",
                "raw_reason": str(fsm.get("stop_reason", "") or ""),
            }
        )
        events.append({"event": "final", "summary": _final_text(source)})
        return {
            "schema": AGENT_EVENT_STREAM_SCHEMA,
            "status": "recorded",
            "event_count": len(events),
            "events": events,
        }
    final_text = _final_text(source)
    grounding = source.get("engineering_claim_grounding", source.get("stage151_tool_decision_grounding", source.get("tool_grounding", {})))
    if not isinstance(grounding, dict):
        grounding = {}
    loop = source.get("stage152_deepseek_tool_loop", {})
    if not isinstance(loop, dict):
        loop = {}
    stage150 = source.get("stage150_context_memory_fabric", {})
    if not isinstance(stage150, dict):
        stage150 = {}
    events: list[dict[str, Any]] = [
        {"event": "goal", "summary": _compact(user_text or source.get("input_summary", ""), 220)},
        {
            "event": "context",
            "thread_key": str(thread_key or source.get("thread_key", "") or ""),
            "chat_name": str(chat_name or source.get("chat_name", "") or ""),
            "channel": str(channel or source.get("channel", "") or ""),
            "transport": str(transport or source.get("transport", "") or ""),
            "slot_count": int(source.get("stage150_context_memory_fabric_slot_count", stage150.get("slot_count", 0)) or 0),
            "evidence_count": int(source.get("stage150_context_memory_fabric_evidence_count", stage150.get("evidence_count", 0)) or 0),
        },
    ]
    events.extend(_stage151_candidates(source))
    events.extend(_tool_call_events(source))
    events.extend(_observation_events(source))
    events.extend(_engineering_events(source))
    execution = source.get("stage180_live_remediation_execution", {})
    if isinstance(execution, dict) and execution.get("schema") == "holo.stage180.live_remediation_executor.v1":
        for row in list(execution.get("action_results", []) or [])[:5]:
            if not isinstance(row, dict):
                continue
            events.append(
                {
                    "event": "remediation_exec",
                    "action_type": str(row.get("action_type", "") or ""),
                    "status": str(row.get("status", "") or ""),
                    "observation_count": int(row.get("observation_count", 0) or 0),
                }
            )
    continuation = source.get("stage182_remediation_continuation", {})
    if isinstance(continuation, dict) and continuation.get("schema") == "holo.stage182.remediation_continuation.v1":
        events.append(
            {
                "event": "remediation_continue",
                "status": str(continuation.get("status", "") or ""),
                "round_count": int(continuation.get("round_count", 0) or 0),
                "executed_count": int(continuation.get("executed_count", 0) or 0),
                "stop_reason": str(continuation.get("canonical_stop_reason", "") or ""),
            }
        )
    events.append(
        {
            "event": "grounding",
            "status": str(grounding.get("status", source.get("stage151_tool_decision_grounding_status", "")) or "-"),
            "missing": [str(item) for item in list(grounding.get("missing_observations", []) or grounding.get("missing_families", []) or [])],
        }
    )
    events.append(_cache_event(source))
    canonical_stop = map_canonical_stop_reason(
        stage143=source.get("stage143_packet_budget", {}) if isinstance(source.get("stage143_packet_budget", {}), dict) else {},
        stage151=source.get("stage151_tool_decision", {}) if isinstance(source.get("stage151_tool_decision", {}), dict) else {},
        stage152=loop,
        stage153=source.get("stage153_agent_event_stream", {}) if isinstance(source.get("stage153_agent_event_stream", {}), dict) else {},
    )
    events.append(
        {
            "event": "stop",
            "reason": canonical_stop["canonical_stop_reason"],
            "source": canonical_stop["canonical_stop_source"],
            "raw_reason": canonical_stop["raw_stop_reason"],
        }
    )
    events.append({"event": "final", "summary": final_text})
    return {
        "schema": AGENT_EVENT_STREAM_SCHEMA,
        "status": "recorded",
        "event_count": len(events),
        "events": events,
    }


def render_agent_event_stream(stream: dict[str, Any] | None) -> str:
    trace = stream if isinstance(stream, dict) else {}
    lines: list[str] = []
    for item in list(trace.get("events", []) or []):
        if not isinstance(item, dict):
            continue
        event = str(item.get("event", "") or "")
        if event == "goal":
            lines.append(f"[goal] {item.get('summary', '')}")
        elif event == "context":
            lines.append(
                f"[context] thread={item.get('thread_key', '-') or '-'} chat={item.get('chat_name', '-') or '-'} "
                f"channel={item.get('channel', '-') or '-'} evidence={item.get('evidence_count', 0)}"
            )
        elif event == "candidate":
            need = ",".join(str(x) for x in list(item.get("required_observations", []) or [])) or "-"
            lines.append(f"[candidate] {item.get('action_type', '')} score={item.get('score', 0)} need={need}")
        elif event == "action_space":
            lines.append(f"[action_space] count={item.get('count', 0)}")
        elif event == "model_decide":
            need = ",".join(str(x) for x in list(item.get("required_observations", []) or [])) or "-"
            lines.append(f"[model_decide] selected={item.get('selected_action', '')} need={need}")
        elif event == "decide":
            need = ",".join(str(x) for x in list(item.get("required_observations", []) or [])) or "-"
            lines.append(f"[decide] {item.get('action_type', '')} need={need}")
        elif event == "act":
            reason = str(item.get("skip_reason", "") or "")
            suffix = f" reason={reason}" if reason else ""
            lines.append(f"[act] {item.get('action_type', '')} status={item.get('status', '')}{suffix}")
        elif event == "observe":
            unresolved = ",".join(str(x) for x in list(item.get("unresolved_items", []) or [])) or "-"
            lines.append(
                f"[observe] {item.get('action_type', '')} status={item.get('status', '')} "
                f"observations={item.get('observation_count', 0)} unresolved={unresolved}"
            )
        elif event == "evaluate":
            unresolved = ",".join(str(x) for x in list(item.get("unresolved_items", []) or [])) or "-"
            lines.append(f"[evaluate] status={item.get('status', '') or '-'} unresolved={unresolved}")
        elif event == "remediation":
            tools = ",".join(str(x) for x in list(item.get("required_tools", []) or [])) or "-"
            unresolved = ",".join(str(x) for x in list(item.get("unresolved_items", []) or [])) or "-"
            lines.append(
                f"[remediation] {item.get('action_type', '')} status={item.get('status', '')} tools={tools} unresolved={unresolved}"
            )
        elif event == "remediation_exec":
            lines.append(
                f"[remediation_exec] {item.get('action_type', '')} status={item.get('status', '')} observations={int(item.get('observation_count', 0) or 0)}"
            )
        elif event == "remediation_continue":
            lines.append(
                f"[remediation_continue] status={item.get('status', '')} rounds={int(item.get('round_count', 0) or 0)} "
                f"executed={int(item.get('executed_count', 0) or 0)} stop={item.get('stop_reason', '')}"
            )
        elif event == "tool_call":
            if item.get("status") == "no_tool_calls" or item.get("action_type") == "none":
                lines.append("[tool_call] no tool calls")
            else:
                query = str(item.get("query", "") or "")
                detail = f" query={query}" if query else ""
                lines.append(f"[tool_call] {item.get('action_type', '')} status={item.get('status', '')}{detail}")
        elif event == "observation":
            sources = int(item.get("source_count", 0) or 0)
            evidence = str(item.get("search_evidence_status", "") or "")
            evidence_suffix = ""
            if evidence:
                evidence_suffix = f" evidence={evidence} score={item.get('evidence_score', 0)}"
            page = str(item.get("page_evidence_status", "") or "")
            page_suffix = f" page={page} opened={item.get('page_opened_count', 0)}" if page else ""
            synthesis = str(item.get("source_synthesis_status", "") or "")
            synthesis_suffix = (
                f" synthesis={synthesis} supported_sources={item.get('source_synthesis_supported_count', 0)}"
                if synthesis
                else ""
            )
            lines.append(
                f"[observation] {item.get('action_type', '')} status={item.get('status', '')} "
                f"sources={sources} results={item.get('result_count', 0)}{evidence_suffix}{page_suffix}{synthesis_suffix}"
            )
        elif event.startswith("eng:"):
            files_read = len(list(item.get("files_read", []) or []))
            files_changed = len(list(item.get("files_changed", []) or []))
            commands = len(list(item.get("commands_run", []) or []))
            detail = []
            if files_read:
                detail.append(f"read={files_read}")
            if files_changed:
                detail.append(f"changed={files_changed}")
            if commands:
                detail.append(f"commands={commands}")
            suffix = (" " + " ".join(detail)) if detail else ""
            lines.append(f"[{event}] status={item.get('status', '')}{suffix}")
        elif event == "grounding":
            missing = ",".join(str(x) for x in list(item.get("missing", []) or [])) or "-"
            lines.append(f"[grounding] status={item.get('status', '-') or '-'} missing={missing}")
        elif event == "cache":
            lines.append(f"[cache] hit={item.get('prompt_cache_hit_tokens', 0)} miss={item.get('prompt_cache_miss_tokens', 0)}")
        elif event == "stop":
            lines.append(f"[stop] {item.get('reason', '') or 'final'}")
        elif event == "final":
            summary = str(item.get("summary", "") or "")
            lines.append("[final]" if not summary else f"[final]\n{summary}")
    return "\n".join(lines)


def render_tool_observations(payload: dict[str, Any] | None) -> str:
    source = sanitize_event_payload(dict(payload or {}))
    rows = [row for row in list(source.get("web_observation_ledger", []) or []) if isinstance(row, dict)]
    rows.extend(row for row in list(source.get("tool_observation_ledger", []) or []) if isinstance(row, dict))
    rows.extend(row for row in list(source.get("market_research_pack_ledger", []) or []) if isinstance(row, dict))
    rows.extend(row for row in list(source.get("market_research_report_ledger", []) or []) if isinstance(row, dict))
    rows.extend(row for row in normalize_engineering_action_ledger(source.get("engineering_action_ledger", [])))
    if not rows:
        return "[tools] no tool observations"
    lines = ["[tools]"]
    for row in rows[:10]:
        action = str(row.get("action_type", row.get("tool", row.get("tool_name", ""))) or "")
        if not action and str(row.get("schema", "") or "") == "holo.stage171.market_research_pack_ledger.v1":
            action = "market_research_pack"
        if not action and str(row.get("schema", "") or "") == "holo.stage174.market_research_report_ledger.v1":
            action = "market_research_report"
        action = action or "tool"
        status = str(row.get("status", "") or "-")
        query = _compact(row.get("query", row.get("url", row.get("summary", ""))), 130)
        sources = list(row.get("source_urls", []) or [])
        line = f"- {action} status={status}"
        if query:
            line += f" query={query}"
        if sources:
            line += f" sources={len(sources)} first={sources[0]}"
        lines.append(line)
    return "\n".join(lines)


def render_compact_status(payload: dict[str, Any] | None) -> str:
    source = sanitize_event_payload(dict(payload or {}))
    fabric = source.get("stage150_context_memory_fabric", {})
    if not isinstance(fabric, dict):
        fabric = {}
    return (
        "[compact] "
        f"internal_only={bool(fabric.get('background_compact_internal_only', source.get('stage150_background_compact_internal', True)))} "
        f"slots={source.get('stage150_context_memory_fabric_slot_count', fabric.get('slot_count', 0)) or 0} "
        f"evidence={source.get('stage150_context_memory_fabric_evidence_count', fabric.get('evidence_count', 0)) or 0} "
        f"open_loops={source.get('stage150_context_memory_fabric_open_loop_count', fabric.get('open_loop_count', 0)) or 0}"
    )


def safe_json_dumps(value: Any) -> str:
    return json.dumps(sanitize_event_payload(value), ensure_ascii=False, indent=2)
