from __future__ import annotations

import json
import re
from typing import Any

from .common import compact_text, stable_digest, utc_now

STAGE150_SCHEMA = "holo.stage150.context_memory_fabric.v1"

_INSTRUCTION_ORDER = (
    ("system_policy", 10),
    ("persona_style_memory", 20),
    ("project_instruction", 40),
    ("domain_instruction", 50),
    ("module_instruction", 60),
    ("current_task_instruction", 82),
    ("user_directive", 90),
)

_NOISE_HINTS = (
    "127.0.0.1",
    "0.0.0.0",
    "localhost",
    "/health",
    "current url:",
    "in app browser",
    "environment:",
    "session started",
    "wsl health",
    "http://",
    "https://",
)

_CLAIM_PATTERNS: dict[str, tuple[str, ...]] = {
    "read": ("i read", "i checked", "i inspected", "i saw", "i opened", "read the", "checked the"),
    "tool": ("i ran", "i executed", "i called", "i searched", "used the tool", "tool returned"),
    "test": ("tests passed", "test passed", "pytest passed", "all tests pass", "verified by tests"),
    "patch": ("i patched", "patched", "i edited", "edited", "i modified", "modified", "changed the file", "applied patch", "updated the file"),
}


def _compact(value: Any, limit: int = 220) -> str:
    return compact_text(" ".join(str(value or "").strip().split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        current = float(value)
    except (TypeError, ValueError):
        current = default
    return round(max(0.0, min(1.0, current)), 4)


def _lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [_compact(value)] if value.strip() else []
    if isinstance(value, dict):
        collected: list[str] = []
        for key in ("summary", "line", "text", "instruction", "value"):
            text = str(value.get(key, "") or "").strip()
            if text:
                collected.append(_compact(text))
        raw_lines = value.get("lines", [])
        if isinstance(raw_lines, list):
            collected.extend(_compact(item) for item in raw_lines if str(item).strip())
        if not collected:
            for key, item in value.items():
                if isinstance(item, (str, int, float, bool)) and str(item).strip():
                    collected.append(_compact(f"{key}: {item}"))
        return [item for item in collected if item]
    if isinstance(value, (list, tuple)):
        collected = []
        for item in value:
            collected.extend(_lines(item))
        return collected
    text = str(value).strip()
    return [_compact(text)] if text else []


def _instruction_key_value(line: str) -> tuple[str, str]:
    current = str(line or "").strip()
    for sep in ("=", ":"):
        if sep in current:
            left, right = current.split(sep, 1)
            key = re.sub(r"[^a-z0-9_]+", "_", left.strip().lower()).strip("_")
            value = right.strip()
            if key and value:
                return key, value
    lowered = current.lower()
    if "emoji" in lowered or "emoticon" in lowered:
        return "visible_emoji_policy", current
    if "roleplay" in lowered or "role play" in lowered:
        return "identity_mode", current
    return "instruction_" + stable_digest(current, limit=8), current


def _directive_lines(stage149_user_directives: dict[str, Any] | None) -> list[str]:
    report = _dict(stage149_user_directives)
    lines: list[str] = []
    core = _dict(report.get("core_identity", {}))
    if core.get("summary"):
        lines.append(_compact(core.get("summary")))
    for item in _list_dicts(report.get("directives", [])):
        summary = _compact(item.get("summary", ""))
        directive_type = str(item.get("directive_type", "") or "").strip()
        if directive_type and summary:
            lines.append(f"{directive_type}: {summary}")
    return lines


def resolve_instruction_scope(
    *,
    system_policy: Any = None,
    user_directive: Any = None,
    project_instruction: Any = None,
    domain_instruction: Any = None,
    module_instruction: Any = None,
    current_task_instruction: Any = None,
    persona_style_memory: Any = None,
) -> dict[str, Any]:
    """Resolve deterministic instruction precedence for packet construction.

    The result is metadata only. It does not enforce policy or execute actions.
    """

    sources = {
        "system_policy": _lines(system_policy),
        "persona_style_memory": _lines(persona_style_memory),
        "project_instruction": _lines(project_instruction),
        "domain_instruction": _lines(domain_instruction),
        "module_instruction": _lines(module_instruction),
        "current_task_instruction": _lines(current_task_instruction),
        "user_directive": _lines(user_directive),
    }
    precedence = {name: score for name, score in _INSTRUCTION_ORDER}
    effective: dict[str, dict[str, Any]] = {}
    raw_layers: list[dict[str, Any]] = []
    for name, _score in _INSTRUCTION_ORDER:
        for line in sources.get(name, []):
            key, value = _instruction_key_value(line)
            previous = effective.get(key)
            current = {"key": key, "value": value, "source": name, "priority": precedence[name]}
            if previous is None or int(current["priority"]) >= int(previous.get("priority", 0)):
                effective[key] = current
            raw_layers.append({"scope": name, "instruction": value, "key": key, "priority": precedence[name]})

    constraints: dict[str, dict[str, Any]] = {}
    for line in sources.get("user_directive", []):
        lowered = line.lower()
        if "emoji" in lowered or "emoticon" in lowered:
            constraints["visible_no_emoji"] = {"source": "user_directive", "summary": line, "hard": True}
        if "roleplay" in lowered or "role play" in lowered:
            constraints["identity_not_roleplay"] = {"source": "user_directive", "summary": line, "hard": True}

    overridden_sources: list[str] = []
    persona_blob = " ".join(sources.get("persona_style_memory", [])).lower()
    if constraints.get("visible_no_emoji") and ("emoji" in persona_blob or "emoticon" in persona_blob):
        overridden_sources.append("persona_style_memory:visible_emoji_policy")
    if constraints.get("identity_not_roleplay") and ("roleplay" in persona_blob or "role play" in persona_blob):
        overridden_sources.append("persona_style_memory:identity_mode")

    return {
        "schema": STAGE150_SCHEMA,
        "resolution": "specific_over_broad_with_user_directive_priority",
        "layers": raw_layers,
        "effective_instructions": effective,
        "effective_constraints": constraints,
        "overridden_sources": overridden_sources,
    }


def _recent_events(
    *,
    user_text: str,
    history: list[dict[str, Any]] | None,
    sidecar: dict[str, Any],
    limit: int = 10,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, row in enumerate(list(history or [])[-limit:]):
        if not isinstance(row, dict):
            continue
        text = str(row.get("body_text", row.get("text", "")) or "").strip()
        if not text:
            continue
        direction = str(row.get("direction", "") or "unknown")
        events.append(
            {
                "event_id": str(row.get("id", "") or row.get("message_id", "") or f"history:{index}"),
                "direction": direction,
                "summary": _compact(text, 180),
                "source": "history",
            }
        )
    recent = _dict(sidecar.get("recent_dialogue_window", {}))
    for index, line in enumerate(list(recent.get("lines", []) or [])[-limit:]):
        text = str(line or "").strip()
        if not text:
            continue
        events.append({"event_id": f"recent:{index}", "direction": "unknown", "summary": _compact(text, 180), "source": "sidecar_recent_dialogue"})
    if user_text.strip():
        events.append({"event_id": "current:" + stable_digest(user_text, limit=10), "direction": "user", "summary": user_text, "source": "current_turn"})
    return events[-limit:]


def _filtered_event_summaries(events: list[dict[str, Any]]) -> list[str]:
    summaries: list[str] = []
    for item in events:
        summary = str(item.get("summary", "") or "").strip()
        lowered = summary.lower()
        if not summary or any(hint in lowered for hint in _NOISE_HINTS):
            continue
        summaries.append(_compact(summary, 180))
    return summaries[:8]


def _stage148_slots(stage148_react_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    report = _dict(stage148_react_state)
    reusable = _dict(report.get("reusable_state_memory", {}))
    slots = []
    for item in _list_dicts(reusable.get("slots", []))[:12]:
        slots.append(
            {
                "slot_id": str(item.get("slot_id", "") or "slot:" + stable_digest(item.get("summary", ""), limit=8)),
                "slot_type": str(item.get("slot_type", "") or "reusable_state"),
                "summary": _compact(item.get("summary", ""), 180),
                "priority": _clamp(item.get("priority", 0.5), 0.5),
                "freshness": _clamp(item.get("freshness", 0.5), 0.5),
                "confidence": _clamp(item.get("confidence", 0.5), 0.5),
                "source": "stage148_react_state",
            }
        )
    return slots


def _evidence_items(
    *,
    sidecar: dict[str, Any],
    reply_debug: dict[str, Any] | None,
    tool_observation_ledger: Any = None,
    memory_observation_ledger: Any = None,
    web_observation_ledger: Any = None,
    time_observation: Any = None,
) -> list[dict[str, Any]]:
    debug = _dict(reply_debug)
    tools = _list_dicts(tool_observation_ledger if tool_observation_ledger is not None else debug.get("tool_observation_ledger", sidecar.get("tool_observation_ledger", [])))
    memories = _list_dicts(memory_observation_ledger if memory_observation_ledger is not None else debug.get("memory_observation_ledger", sidecar.get("memory_observation_ledger", [])))
    web_rows = _list_dicts(web_observation_ledger if web_observation_ledger is not None else debug.get("web_observation_ledger", sidecar.get("web_observation_ledger", [])))
    time_row = _dict(time_observation if time_observation is not None else debug.get("time_observation", sidecar.get("time_observation", {})))
    items: list[dict[str, Any]] = []
    for index, row in enumerate(tools[:10]):
        tool = str(row.get("tool", row.get("name", "")) or "tool")
        items.append(
            {
                "evidence_id": str(row.get("provider_call_id", "") or row.get("tool_call_id", "") or f"tool:{index}"),
                "family": "tool",
                "source_family": tool,
                "status": str(row.get("status", "") or "unknown"),
                "summary": _compact(row.get("summary", row.get("result_summary", "")), 220),
                "confidence": _clamp(row.get("confidence", 0.75), 0.75),
            }
        )
    for index, row in enumerate(memories[:10]):
        items.append(
            {
                "evidence_id": str(row.get("memory_call_id", "") or row.get("selected_ids", [""])[0] if isinstance(row.get("selected_ids", []), list) and row.get("selected_ids", []) else f"memory:{index}"),
                "family": "memory",
                "source_family": str(row.get("source_family", "") or "memory"),
                "status": str(row.get("status", "") or "unknown"),
                "summary": _compact(row.get("summary", ""), 220),
                "confidence": _clamp(row.get("confidence", 0.5), 0.5),
            }
        )
    for index, row in enumerate(web_rows[:8]):
        query = str(row.get("query", "") or row.get("url", "") or "").strip()
        items.append(
            {
                "evidence_id": str(row.get("observation_id", "") or f"web:{index}"),
                "family": "web",
                "source_family": str(row.get("action_type", "") or "web"),
                "status": str(row.get("status", "") or "unknown"),
                "summary": _compact(f"{row.get('action_type', 'web')} {row.get('status', '')}: {query}; sources={len(list(row.get('source_urls', []) or []))}", 220),
                "confidence": _clamp(row.get("confidence", 0.5), 0.5),
            }
        )
    if time_row:
        items.append(
            {
                "evidence_id": str(time_row.get("observation_id", "") or "time:current"),
                "family": "time",
                "source_family": "host_clock",
                "status": "grounded",
                "summary": _compact(f"local_time={time_row.get('local_time', '')}; utc_time={time_row.get('utc_time', '')}; timezone={time_row.get('timezone', '')}", 220),
                "confidence": _clamp(time_row.get("confidence", 1.0), 1.0),
            }
        )
    for key, family in (
        ("memory_grounding", "memory_grounding"),
        ("memory_alignment", "memory_alignment"),
        ("tool_grounding", "tool_grounding"),
        ("stage142_semantic_novelty", "semantic_novelty"),
        ("stage143_packet_budget", "packet_budget"),
        ("stage144_context_economy", "context_economy"),
        ("stage145_outcome_appraisal", "outcome_appraisal"),
    ):
        report = _dict(debug.get(key, sidecar.get(key, {})))
        if not report:
            continue
        status = str(report.get("status", "") or report.get("stop_reason", "") or report.get("recommended_deep_policy", "") or "reported")
        items.append(
            {
                "evidence_id": key,
                "family": family,
                "source_family": family,
                "status": status,
                "summary": _compact(json.dumps(report, ensure_ascii=False, sort_keys=True), 220),
                "confidence": 0.7,
            }
        )
    return items[:24]


def _claim_support(evidence: list[dict[str, Any]]) -> dict[str, bool]:
    tool_blob = " ".join(
        f"{item.get('source_family', '')} {item.get('status', '')} {item.get('summary', '')}".lower()
        for item in evidence
        if item.get("family") == "tool"
    )
    return {
        "read": any(token in tool_blob for token in ("workspace_inspect", "git_inspect", "read", "inspect")) and "rejected" not in tool_blob,
        "tool": bool(tool_blob) and "rejected" not in tool_blob,
        "test": "test_runner" in tool_blob and "passed" in tool_blob,
        "patch": "workspace_edit" in tool_blob and any(token in tool_blob for token in ("applied", "patched", "edited")),
    }


def _evidence_discipline(candidate_visible_text: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    text = str(candidate_visible_text or "")
    lowered = text.lower()
    support = _claim_support(evidence)
    claims: list[dict[str, Any]] = []
    unverified: list[str] = []
    for family, patterns in _CLAIM_PATTERNS.items():
        if not any(pattern in lowered for pattern in patterns):
            continue
        verified = bool(support.get(family, False))
        claims.append({"claim_family": family, "verified": verified, "source": "candidate_visible_text"})
        if not verified:
            unverified.append(family)
    forbidden: list[str] = []
    if unverified:
        forbidden.append("Do not claim read/test/patch/tool success unless a matching observation ledger exists.")
    return {
        "claims": claims,
        "unverified_claim_families": sorted(set(unverified)),
        "forbidden_visible_claims": forbidden,
        "read_tool_memory_project_claims_require_ledger": True,
    }


def build_stage150_context_memory_fabric(
    *,
    user_text: str,
    channel: str = "",
    thread_key: str = "",
    chat_name: str = "",
    history: list[dict[str, Any]] | None = None,
    sidecar: dict[str, Any] | None = None,
    capability_context: dict[str, Any] | None = None,
    reply_debug: dict[str, Any] | None = None,
    tool_observation_ledger: Any = None,
    memory_observation_ledger: Any = None,
    candidate_visible_text: str = "",
) -> dict[str, Any]:
    packet = _dict(sidecar)
    debug = _dict(reply_debug)
    capability = _dict(capability_context)
    if tool_observation_ledger is None and capability.get("tool_observation_ledger"):
        tool_observation_ledger = capability.get("tool_observation_ledger")
    web_observation_ledger = capability.get("web_observation_ledger", packet.get("web_observation_ledger", debug.get("web_observation_ledger", [])))
    time_observation = capability.get("time_observation", packet.get("time_observation", debug.get("time_observation", {})))
    stage148 = _dict(packet.get("stage148_react_state", debug.get("stage148_react_state", {})))
    stage149 = _dict(packet.get("stage149_user_directives", debug.get("stage149_user_directives", {})))
    current_request = str(user_text or "")
    events = _recent_events(user_text=current_request, history=history, sidecar=packet)
    slots = _stage148_slots(stage148)
    evidence = _evidence_items(
        sidecar=packet,
        reply_debug=debug,
        tool_observation_ledger=tool_observation_ledger,
        memory_observation_ledger=memory_observation_ledger,
        web_observation_ledger=web_observation_ledger,
        time_observation=time_observation,
    )
    discipline = _evidence_discipline(candidate_visible_text, evidence)
    active_slots = [item for item in slots if item.get("slot_type") in {"active_task", "unresolved_question", "recent_correction"}]
    open_loops = [
        {"loop_id": item.get("slot_id", ""), "summary": item.get("summary", ""), "source": item.get("source", "stage148_react_state")}
        for item in active_slots
        if item.get("summary")
    ][:6]
    directive_lines = _directive_lines(stage149)
    scope = resolve_instruction_scope(
        system_policy=[
            "single_brain_boundary=WSL Holo host is the decision authority",
            "background_compact=internal_only",
            "evidence_claims=require_observation_ledgers",
        ],
        user_directive=directive_lines,
        project_instruction=packet.get("project_instruction", packet.get("project_or_domain_instructions", {})),
        domain_instruction=packet.get("domain_instruction", {}),
        module_instruction=packet.get("module_instruction", {}),
        current_task_instruction=packet.get("current_task_instruction", current_request),
        persona_style_memory=packet.get("persona_blend", {}),
    )
    compact_summaries = _filtered_event_summaries(events)
    decision_summary = [
        str(_dict(_dict(stage148.get("react_loop", {})).get("plan", {})).get("selected_action_hint", "") or ""),
        str(_dict(packet.get("selected_action", {})).get("action_type", "") or ""),
    ]
    decision_summary = [item for item in decision_summary if item]
    compact_background = {
        "task_state_summary": _compact("; ".join(item.get("summary", "") for item in active_slots if item.get("summary")), 360),
        "decision_summary": _compact("; ".join(decision_summary), 220),
        "directive_summary": _compact("; ".join(directive_lines), 320),
        "evidence_summary": _compact("; ".join(item.get("summary", "") for item in evidence if item.get("summary")), 360),
        "open_loop_summary": _compact("; ".join(item.get("summary", "") for item in open_loops), 360),
        "unresolved_conflicts": [],
        "filtered_recent_events": compact_summaries,
        "current_user_request_exact": current_request,
        "user_visible": False,
    }
    working_packet = {
        "user_goal": {
            "current_user_request_exact": current_request,
            "inferred_goal": _compact(current_request, 220),
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
        },
        "active_task_state": {
            "selected_action": _dict(packet.get("selected_action", {})),
            "react_plan": _dict(_dict(stage148.get("react_loop", {})).get("plan", {})),
            "active_slots": active_slots,
        },
        "reusable_state_slots": slots,
        "directive_state": {
            "stage149_status": str(stage149.get("status", "") or ""),
            "core_identity": _dict(stage149.get("core_identity", {})),
            "directives": _list_dicts(stage149.get("directives", [])),
            "effective_constraints": scope.get("effective_constraints", {}),
        },
        "project_or_domain_instructions": {
            "project_instruction": _lines(packet.get("project_instruction", packet.get("project_or_domain_instructions", {}))),
            "domain_instruction": _lines(packet.get("domain_instruction", {})),
            "module_instruction": _lines(packet.get("module_instruction", {})),
            "current_task_instruction": _lines(packet.get("current_task_instruction", current_request)),
        },
        "relevant_recent_events": events,
        "evidence_ledger_view": evidence,
        "tool_memory_visual_observations": {
            "tool_observations": [item for item in evidence if item.get("family") == "tool"],
            "memory_observations": [item for item in evidence if item.get("family") == "memory"],
            "web_observations": [item for item in evidence if item.get("family") == "web"],
            "time_observation": _dict(time_observation),
            "visual_observation": _dict(packet.get("visual_memory", packet.get("visual_ingest", {}))),
        },
        "open_loops": open_loops,
        "compact_background_summary": compact_background,
        "forbidden_visible_claims": list(discipline.get("forbidden_visible_claims", [])),
    }
    slot_count = len(slots)
    evidence_count = len(evidence)
    return {
        "schema": STAGE150_SCHEMA,
        "stage": "stage150-codex-style-context-memory",
        "status": "active",
        "generated_at": utc_now(),
        "instruction_scope": scope,
        "working_context_packet": working_packet,
        "background_compact": compact_background,
        "evidence_discipline": discipline,
        "slot_count": slot_count,
        "evidence_count": evidence_count,
        "open_loop_count": len(open_loops),
        "directive_count": int(stage149.get("hard_directive_count", len(_list_dicts(stage149.get("directives", [])))) or 0),
        "background_compact_internal_only": True,
        "provider_call_added": False,
        "tool_execution_added": False,
        "memory_write_added": False,
        "transport_authority_widened": False,
        "cache_hint": "stage150:" + stable_digest(json.dumps(working_packet, ensure_ascii=False, sort_keys=True), limit=12),
    }


def stage150_prompt_lines(report: dict[str, Any] | None) -> list[str]:
    payload = _dict(report)
    if not payload:
        return []
    packet = _dict(payload.get("working_context_packet", {}))
    user_goal = _dict(packet.get("user_goal", {}))
    active_task = _dict(packet.get("active_task_state", {}))
    directive_state = _dict(packet.get("directive_state", {}))
    compact = _dict(payload.get("background_compact", {}))
    evidence = list(packet.get("evidence_ledger_view", []) or [])
    open_loops = list(packet.get("open_loops", []) or [])
    forbidden = list(packet.get("forbidden_visible_claims", []) or [])
    lines = [
        "User Goal",
        f"current_user_request_exact={_compact(user_goal.get('current_user_request_exact', ''), 260)}",
        "Active Task",
        f"selected_action={_compact(json.dumps(active_task.get('selected_action', {}), ensure_ascii=False, sort_keys=True), 180)}",
        "Directives",
        f"directive_status={directive_state.get('stage149_status', '')}; hard_count={len(list(directive_state.get('directives', []) or []))}",
        "Working Context",
    ]
    for slot in list(packet.get("reusable_state_slots", []) or [])[:6]:
        if isinstance(slot, dict):
            lines.append(f"slot:{slot.get('slot_type', 'state')}={_compact(slot.get('summary', ''), 140)}")
    lines.extend(["Evidence Ledger", f"evidence_count={len(evidence)}"])
    for item in evidence[:5]:
        if isinstance(item, dict):
            lines.append(f"evidence:{item.get('family', 'unknown')}:{item.get('status', '')}={_compact(item.get('summary', ''), 140)}")
    lines.extend(["Open Loops", f"open_loop_count={len(open_loops)}"])
    for item in open_loops[:4]:
        if isinstance(item, dict):
            lines.append(f"open_loop={_compact(item.get('summary', ''), 140)}")
    lines.extend(
        [
            "Background Compact Summary",
            f"task_state={_compact(compact.get('task_state_summary', ''), 180)}",
            f"decision={_compact(compact.get('decision_summary', ''), 160)}",
            "background_compact_visible_to_user=false",
        ]
    )
    if forbidden:
        lines.append("Forbidden Visible Claims")
        lines.extend(_compact(item, 160) for item in forbidden[:4])
    return [line for line in lines if str(line).strip()][:36]
