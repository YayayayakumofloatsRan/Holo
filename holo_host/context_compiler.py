from __future__ import annotations

import re
from typing import Any

from .common import compact_text, stable_digest, utc_now

CONTEXT_COMPILER_SCHEMA = "holo.stage156.context_compiler.v1"

_NOISE_PATTERNS = (
    re.compile(r"^\s*#\s*In app browser:", re.I),
    re.compile(r"^\s*Current URL:\s*https?://(?:127\.0\.0\.1|0\.0\.0\.0|localhost)", re.I),
    re.compile(r"\b/health\b", re.I),
    re.compile(r"^\s*Holo CLI chat\s*\|", re.I),
    re.compile(r"^\s*Type /help for commands", re.I),
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


def _section(title: str, lines: list[str]) -> str:
    body = "\n".join(f"- {line}" for line in lines if str(line).strip())
    return f"{title}\n{body}" if body else f"{title}\n- none"


def _compact_background(packet: dict[str, Any]) -> dict[str, Any]:
    compact = _dict(packet.get("compact_background_summary"))
    open_loops = _list(packet.get("open_loops")) or _list(packet.get("open_questions")) or []
    decisions = _list(packet.get("latest_decisions"))
    events = _clean_lines(_list(packet.get("relevant_recent_events")), limit=6)
    return {
        "task_state_summary": compact_text(str(_dict(packet.get("active_task_state")).get("summary", "") or packet.get("user_goal", "")), 320),
        "decision_summary": "; ".join(
            compact_text(str(item.get("title", item) if isinstance(item, dict) else item), 180)
            for item in decisions[:4]
        ),
        "directive_summary": compact_text(str(_dict(packet.get("directive_state")).get("summary", "")), 320),
        "evidence_summary": "; ".join(events[:4]),
        "open_loop_summary": "; ".join(
            compact_text(str(item.get("title", item) if isinstance(item, dict) else item), 180)
            for item in open_loops[:6]
        ),
        "unresolved_conflicts": list(compact.get("unresolved_conflicts", [])) if isinstance(compact.get("unresolved_conflicts"), list) else [],
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
    observations = _clean_lines(
        _list(packet.get("evidence_ledger_view"))
        + _list(packet.get("tool_memory_visual_observations"))
        + _list(packet.get("relevant_recent_events")),
        limit=14,
    )
    active_project = _dict(packet.get("active_project"))
    active_tasks = _list(packet.get("active_tasks"))
    open_questions = _list(packet.get("open_questions"))
    next_actions = _list(packet.get("next_actions"))

    stable_prefix = _section(
        "Stable Prefix",
        [
            "Holo is a single local subject runtime; WSL host authority owns tools and memory.",
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


def render_context_compiler_report(report: dict[str, Any]) -> str:
    payload = _dict(report)
    if not payload:
        return "Stage156 Context Compiler: no report"
    lines = [
        "Stage156 Context Compiler",
        f"schema={payload.get('schema', CONTEXT_COMPILER_SCHEMA)}",
        f"estimated_prompt_tokens={payload.get('estimated_prompt_tokens', 0)}",
        f"cache_hit_ratio={payload.get('cache_hit_ratio', 0.0)}",
        f"truncated_sections={','.join(payload.get('truncated_sections', []) or []) or '-'}",
    ]
    return "\n".join(lines)
