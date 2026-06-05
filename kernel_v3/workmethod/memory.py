from __future__ import annotations

import hashlib

from kernel_v3.contracts import JsonObject
from kernel_v3.workmethod.contracts import ThreadWorkingSet


def build_thread_working_set(
    *,
    thread_id: str,
    active_goal: str,
    current_method: str,
    thread_context: JsonObject | None = None,
    mission_context: JsonObject | None = None,
    interaction_preferences: JsonObject | None = None,
) -> ThreadWorkingSet:
    thread_context = dict(thread_context or {})
    mission_context = dict(mission_context or {})
    mission_state = mission_context.get("mission_state") if isinstance(mission_context.get("mission_state"), dict) else {}
    coverage = mission_state.get("coverage_map") if isinstance(mission_state.get("coverage_map"), dict) else {}
    recent_results = [item for item in thread_context.get("recent_results", []) if isinstance(item, dict)]
    recent_trace = [item for item in thread_context.get("recent_task_trace", []) if isinstance(item, dict)]
    failure_diagnostics = [item for item in thread_context.get("failure_diagnostics", []) if isinstance(item, dict)]
    successful_findings = _ordered_unique(
        [
            *_string_list(thread_context.get("evidence_refs")),
            *_string_list(thread_context.get("citation_refs")),
            *_string_list(coverage.get("evidence_refs")),
            *_string_list(coverage.get("citation_refs")),
            *[
                str(item.get("answer_preview"))
                for item in recent_results[-3:]
                if isinstance(item.get("answer_preview"), str) and item.get("answer_preview")
            ],
        ]
    )[:16]
    failed_attempts = _ordered_unique(
        [
            *[
                str(item.get("failure_reason"))
                for item in recent_results
                if isinstance(item.get("failure_reason"), str) and item.get("failure_reason")
            ],
            *[
                str(item.get("reason"))
                for item in failure_diagnostics
                if isinstance(item.get("reason"), str) and item.get("reason")
            ],
            *[
                str(item.get("content_preview"))
                for item in recent_trace
                if item.get("kind") == "observation"
                and item.get("status") in {"failed", "blocked", "not_implemented"}
                and isinstance(item.get("content_preview"), str)
            ],
        ]
    )[-16:]
    open_gaps = _ordered_unique(
        [
            *_string_list(mission_state.get("open_gaps")),
            *_string_list(coverage.get("missing_requirements")),
            *[
                str(item.get("missing_reason"))
                for item in coverage.get("requirements", [])
                if isinstance(item, dict) and isinstance(item.get("missing_reason"), str)
            ],
        ]
    )[:24]
    next_intent = None
    directive = mission_context.get("directive") if isinstance(mission_context.get("directive"), dict) else None
    if directive is not None and isinstance(directive.get("next_subgoal"), str):
        next_intent = str(directive["next_subgoal"])
    return ThreadWorkingSet(
        working_set_id="workset-" + _short_hash(thread_id, active_goal, current_method),
        thread_id=thread_id,
        active_goal=active_goal,
        current_method=current_method,
        successful_findings=successful_findings,
        failed_attempts=failed_attempts,
        open_gaps=open_gaps,
        user_preferences=dict(interaction_preferences or {}),
        next_intent=next_intent,
        trace_refs=_ordered_unique(
            [
                *[
                    str(item.get("record_ref"))
                    for item in recent_trace[-8:]
                    if isinstance(item.get("record_ref"), str)
                ],
                *[
                    str(item.get("record_ref"))
                    for item in recent_results[-4:]
                    if isinstance(item.get("record_ref"), str)
                ],
            ]
        ),
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item)]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _short_hash(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8", errors="replace")).hexdigest()[:12]
