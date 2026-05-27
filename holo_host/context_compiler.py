from __future__ import annotations

import re
from typing import Any

from .common import compact_text, stable_digest, utc_now

CONTEXT_COMPILER_SCHEMA = "holo.stage156.context_compiler.v1"

_NOISE_PATTERNS = (
    re.compile(r"^\s*#\s*In app browser:", re.I),
    re.compile(r"^\s*Current URL:\s*https?://(?:127\.0\.0\.1|0\.0\.0\.0|localhost)", re.I),
    re.compile(r"^\s*Current URL:\s*http://(?:127\.0\.0\.1|0\.0\.0\.0|localhost)", re.I),
    re.compile(r"\b/health\b", re.I),
    re.compile(r"^\s*Holo CLI chat\s*\|", re.I),
    re.compile(r"^\s*Type /help for commands", re.I),
    re.compile(r"^\s*environment[:=]", re.I),
    re.compile(r"^\s*session started", re.I),
    re.compile(r"^\s*health[-_ ]?check", re.I),
)


def estimate_tokens(text: str) -> int:
    cleaned = str(text or "")
    if not cleaned:
        return 0
    return max(1, (len(cleaned) + 3) // 4)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _clean_lines(lines: list[Any], *, limit: int = 10) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        text = compact_text(str(raw or ""), 260)
        if not text:
            continue
        if any(pattern.search(text) for pattern in _NOISE_PATTERNS):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _observation_lines(value: Any, *, limit: int = 16) -> list[str]:
    lines: list[str] = []

    def visit(item: Any) -> None:
        if len(lines) >= limit:
            return
        if item is None:
            return
        if isinstance(item, str):
            lines.extend(_clean_lines([item], limit=limit - len(lines)))
            return
        if isinstance(item, dict):
            status = str(item.get("status", "") or "").strip()
            family = str(item.get("family", item.get("source_family", item.get("action_type", item.get("tool", "")))) or "").strip()
            summary = str(item.get("summary", item.get("text", item.get("line", ""))) or "").strip()
            if summary:
                prefix = " ".join(part for part in (family, status) if part)
                lines.extend(_clean_lines([f"{prefix}: {summary}" if prefix else summary], limit=limit - len(lines)))
            for key in (
                "tool_observations",
                "engineering_observations",
                "memory_observations",
                "web_observations",
                "visual_observation",
                "time_observation",
                "stage160r_intent_frame",
                "stage160r_agent_loop_fsm",
                "stage160r_goal_state",
                "results",
                "lines",
            ):
                if key in item:
                    visit(item.get(key))
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
                if len(lines) >= limit:
                    break
            return
        lines.extend(_clean_lines([str(item)], limit=limit - len(lines)))

    visit(value)
    return _clean_lines(lines, limit=limit)


def _section(title: str, lines: list[str]) -> str:
    body = "\n".join(f"- {line}" for line in lines if str(line).strip())
    return f"{title}\n{body}" if body else f"{title}\n- none"


def _compact_background(packet: dict[str, Any]) -> dict[str, Any]:
    compact = _dict(packet.get("compact_background_summary"))
    open_loops = _list(packet.get("open_loops")) or _list(packet.get("open_questions")) or []
    decisions = _list(packet.get("latest_decisions"))
    event_inputs: list[str] = []
    for item in _list(packet.get("relevant_recent_events")):
        if isinstance(item, dict):
            event_inputs.append(str(item.get("summary", "") or item.get("text", "") or item.get("line", "") or ""))
        else:
            event_inputs.append(str(item or ""))
    events = _clean_lines(event_inputs, limit=6)
    filtered_events = _clean_lines(events, limit=6)
    return {
        "task_state_summary": compact_text(str(_dict(packet.get("active_task_state")).get("summary", "") or packet.get("user_goal", "")), 320),
        "decision_summary": "; ".join(
            compact_text(str(item.get("title", item) if isinstance(item, dict) else item), 180)
            for item in decisions[:4]
        ),
        "directive_summary": compact_text(str(_dict(packet.get("directive_state")).get("summary", "")), 320),
        "evidence_summary": "; ".join(filtered_events[:4]),
        "open_loop_summary": "; ".join(
            compact_text(str(item.get("title", item) if isinstance(item, dict) else item), 180)
            for item in open_loops[:6]
        ),
        "unresolved_conflicts": list(compact.get("unresolved_conflicts", [])) if isinstance(compact.get("unresolved_conflicts"), list) else [],
        "filtered_recent_events": filtered_events,
        "user_visible": False,
    }


def _extract_directives(packet: dict[str, Any]) -> list[str]:
    directive_state = _dict(packet.get("directive_state"))
    directives = []
    for item in _list(directive_state.get("hard_directives")) + _list(directive_state.get("directives")):
        if isinstance(item, dict):
            text = str(item.get("summary", "") or item.get("text", "") or item.get("directive", "")).strip()
        else:
            text = str(item or "").strip()
        if text:
            directives.append(text)
    summary = str(directive_state.get("summary", "") or "").strip()
    if summary:
        directives.append(summary)
    return _clean_lines(directives, limit=10)


def compile_context_memory(
    stage150_context_memory_fabric: dict[str, Any] | None = None,
    *,
    current_user_request: str = "",
    tool_schemas: list[str] | None = None,
    usage: dict[str, Any] | None = None,
    max_prompt_tokens: int = 8000,
) -> dict[str, Any]:
    """Compile Stage150 state into stable and dynamic prompt sections.

    This is a deterministic compiler surface. It does not call providers,
    execute tools, write memory, or make transport decisions.
    """

    fabric = _dict(stage150_context_memory_fabric)
    packet = _dict(fabric.get("working_context_packet")) or fabric
    exact_request = str(current_user_request or _dict(packet.get("user_goal")).get("current_user_request_exact", "") or packet.get("user_goal", "") or "")
    directives = _extract_directives(packet)
    observations = _observation_lines(
        [
            packet.get("active_task_state"),
            packet.get("evidence_ledger_view"),
            packet.get("tool_memory_visual_observations"),
            packet.get("relevant_recent_events"),
        ],
        limit=18,
    )
    active_project = _dict(packet.get("active_project"))
    active_tasks = _list(packet.get("active_tasks"))
    open_questions = _list(packet.get("open_questions"))
    next_actions = _list(packet.get("next_actions"))

    stable_prefix = _section(
        "Stable Prefix",
        [
            "Holo is a single local agent runtime; WSL host authority owns tools and memory.",
            "Visible claims require matching evidence ledgers.",
            "Never expose hidden provider reasoning.",
        ],
    )
    project_instruction_block = _section(
        "Project Instruction Block",
        _clean_lines(
            [
                f"active_project={active_project.get('title', '')}" if active_project else "",
                *[
                    f"active_task={item.get('title', item) if isinstance(item, dict) else item}"
                    for item in active_tasks[:5]
                ],
                *[
                    f"open_question={item.get('title', item) if isinstance(item, dict) else item}"
                    for item in open_questions[:5]
                ],
                *[
                    f"next_action={item.get('title', item) if isinstance(item, dict) else item}"
                    for item in next_actions[:5]
                ],
            ],
            limit=16,
        ),
    )
    tool_schema_block = _section("Tool Schema Block", _clean_lines(tool_schemas or [], limit=12))
    directive_block = _section("Directive Block", directives or ["No extra hard directive in packet."])
    dynamic_turn_block = _section("Dynamic Turn Block", [f"current_user_request_exact={exact_request}"])
    observation_block = _section("Observation Block", observations)
    final_constraints_block = _section(
        "Final Constraints Block",
        [
            "Answer from evidence; say when evidence is missing.",
            "Do not mention background compaction as visible speech.",
            "Do not claim tool, test, patch, read, web, or memory success without ledgers.",
            "All mandatory tool decisions must pass the Stage160R FSM before final speech.",
        ],
    )

    sections = {
        "stable_prefix": stable_prefix,
        "project_instruction_block": project_instruction_block,
        "tool_schema_block": tool_schema_block,
        "directive_block": directive_block,
        "dynamic_turn_block": dynamic_turn_block,
        "observation_block": observation_block,
        "final_constraints_block": final_constraints_block,
    }
    truncated: list[str] = []
    total_tokens = sum(estimate_tokens(text) for text in sections.values())
    for key in ("observation_block", "project_instruction_block", "tool_schema_block"):
        if total_tokens <= max_prompt_tokens:
            break
        original = sections[key]
        sections[key] = compact_text(original, max(120, max_prompt_tokens * 2))
        truncated.append(key)
        total_tokens = sum(estimate_tokens(text) for text in sections.values())

    usage_payload = _dict(usage)
    hit = int(usage_payload.get("prompt_cache_hit_tokens", usage_payload.get("cache_hit_tokens", 0)) or 0)
    miss = int(usage_payload.get("prompt_cache_miss_tokens", usage_payload.get("cache_miss_tokens", 0)) or 0)
    cache_total = hit + miss
    return {
        "schema": CONTEXT_COMPILER_SCHEMA,
        "compiled_at": utc_now(),
        "cache_key": "stage156:" + stable_digest(*sections.values(), limit=18),
        "stable_prefix_cache_key": "stage156:stable:" + stable_digest(sections["stable_prefix"], sections["project_instruction_block"], sections["tool_schema_block"], limit=18),
        "dynamic_suffix_digest": "stage156:dynamic:" + stable_digest(
            sections["directive_block"],
            sections["dynamic_turn_block"],
            sections["observation_block"],
            sections["final_constraints_block"],
            limit=18,
        ),
        "current_user_request_exact": exact_request,
        **sections,
        "background_compact": _compact_background(packet),
        "estimated_prompt_tokens": total_tokens,
        "stable_prefix_tokens": estimate_tokens(sections["stable_prefix"]),
        "dynamic_suffix_tokens": sum(
            estimate_tokens(sections[key])
            for key in (
                "project_instruction_block",
                "tool_schema_block",
                "directive_block",
                "dynamic_turn_block",
                "observation_block",
                "final_constraints_block",
            )
        ),
        "truncated_sections": truncated,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "cache_hit_ratio": round(hit / cache_total, 4) if cache_total else 0.0,
        "visible_compact_leak_forbidden": True,
    }


def render_context_compiler_prompt_lines(report: dict[str, Any] | None, *, limit: int = 36) -> list[str]:
    payload = _dict(report)
    if not payload:
        return []
    lines = [
        f"schema={payload.get('schema', CONTEXT_COMPILER_SCHEMA)}",
        f"cache_key={payload.get('cache_key', '')}",
        f"stable_prefix_cache_key={payload.get('stable_prefix_cache_key', '')}",
        f"stable_prefix_tokens={payload.get('stable_prefix_tokens', 0)}",
        f"dynamic_suffix_tokens={payload.get('dynamic_suffix_tokens', 0)}",
        f"estimated_prompt_tokens={payload.get('estimated_prompt_tokens', 0)}",
        f"cache_hit_tokens={payload.get('cache_hit_tokens', 0)}",
        f"cache_miss_tokens={payload.get('cache_miss_tokens', 0)}",
        f"cache_hit_ratio={payload.get('cache_hit_ratio', 0.0)}",
        f"truncated_sections={','.join(payload.get('truncated_sections', []) or []) or '-'}",
        f"current_user_request_exact={compact_text(str(payload.get('current_user_request_exact', '') or ''), 280)}",
        "stable_prefix=cacheable_static_policy",
        "dynamic_suffix=current_turn_directives_observations_constraints",
        "background_compact_internal_only=true",
    ]
    for key in (
        "project_instruction_block",
        "directive_block",
        "dynamic_turn_block",
        "observation_block",
        "final_constraints_block",
    ):
        value = str(payload.get(key, "") or "")
        if value.strip():
            lines.append(f"{key}={compact_text(value, 420)}")
    return [line for line in lines if str(line).strip()][:limit]


_VISIBLE_COMPACT_PATTERNS = (
    (re.compile(r"\bI compacted (?:the )?context\b", re.I), "I prepared the working context"),
    (re.compile(r"\bI compressed (?:the )?context\b", re.I), "I prepared the working context"),
    (re.compile(r"\bI summarized (?:the )?background compact\b", re.I), "I prepared the working context"),
    (re.compile(r"我压缩了上下文"), "我整理了工作上下文"),
    (re.compile(r"我做了上下文压缩"), "我整理了工作上下文"),
)


def repair_visible_compact_leak(text: str) -> str:
    repaired = str(text or "")
    for pattern, replacement in _VISIBLE_COMPACT_PATTERNS:
        repaired = pattern.sub(replacement, repaired)
    return repaired


def render_context_compiler_report(report: dict[str, Any]) -> str:
    payload = _dict(report)
    if not payload:
        return "Stage156 Context Compiler: no report"
    lines = [
        "Stage156 Context Compiler",
        f"schema={payload.get('schema', CONTEXT_COMPILER_SCHEMA)}",
        f"estimated_prompt_tokens={payload.get('estimated_prompt_tokens', 0)}",
        f"cache_hit_ratio={payload.get('cache_hit_ratio', 0.0)}",
        f"cache_tokens=hit:{payload.get('cache_hit_tokens', 0)} miss:{payload.get('cache_miss_tokens', 0)}",
        f"truncated_sections={','.join(payload.get('truncated_sections', []) or []) or '-'}",
    ]
    return "\n".join(lines)


def render_context_cache_status(report: dict[str, Any] | None) -> str:
    payload = _dict(report)
    if not payload:
        return "[cache] no Stage156 context compiler report"
    return (
        "[cache] "
        f"hit={int(payload.get('cache_hit_tokens', 0) or 0)} "
        f"miss={int(payload.get('cache_miss_tokens', 0) or 0)} "
        f"ratio={payload.get('cache_hit_ratio', 0.0)} "
        f"stable_tokens={int(payload.get('stable_prefix_tokens', 0) or 0)} "
        f"dynamic_tokens={int(payload.get('dynamic_suffix_tokens', 0) or 0)}"
    )
