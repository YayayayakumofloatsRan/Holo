from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

from kernel_v3.contracts import JsonObject, LedgerRecord


TOOL_RESULT_REPLACEMENT_SCHEMA = "holo.kernel_v3.tool_result_replacement.v1"
DEFAULT_TOOL_RESULT_BATCH_BUDGET_CHARS = 50_000


@dataclass
class ToolResultReplacementState:
    seen_ids: set[str] = field(default_factory=set)
    replacements: dict[str, JsonObject] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "schema": "holo.kernel_v3.tool_result_replacement_state.v1",
            "seen_ids": sorted(self.seen_ids),
            "replacements": {key: dict(value) for key, value in sorted(self.replacements.items())},
        }


def apply_tool_result_replacement_budget(
    results: list[JsonObject],
    state: ToolResultReplacementState,
    *,
    limit_chars: int = DEFAULT_TOOL_RESULT_BATCH_BUDGET_CHARS,
) -> tuple[list[JsonObject], list[JsonObject]]:
    candidates = [_candidate(result) for result in results]
    candidates = [candidate for candidate in candidates if candidate is not None]
    replacement_map: dict[str, JsonObject] = {}
    newly_replaced: list[JsonObject] = []

    fresh: list[_ToolResultCandidate] = []
    frozen_size = 0
    for candidate in candidates:
        existing = state.replacements.get(candidate.tool_call_id)
        if existing is not None:
            replacement_map[candidate.tool_call_id] = dict(existing)
            continue
        if candidate.tool_call_id in state.seen_ids:
            frozen_size += candidate.estimated_chars
            continue
        fresh.append(candidate)

    fresh_size = sum(candidate.estimated_chars for candidate in fresh)
    selected: set[str] = set()
    if frozen_size + fresh_size > max(1, limit_chars):
        remaining = frozen_size + fresh_size
        for candidate in sorted(fresh, key=lambda item: item.estimated_chars, reverse=True):
            if remaining <= max(1, limit_chars):
                break
            selected.add(candidate.tool_call_id)
            remaining -= candidate.estimated_chars

    for candidate in fresh:
        state.seen_ids.add(candidate.tool_call_id)
        if candidate.tool_call_id not in selected:
            continue
        replacement = _replacement_for(candidate)
        state.replacements[candidate.tool_call_id] = dict(replacement)
        replacement_map[candidate.tool_call_id] = replacement
        newly_replaced.append(
            {
                "kind": "tool-result",
                "tool_call_id": candidate.tool_call_id,
                "replacement": replacement,
            }
        )

    if not replacement_map:
        return results, []

    replaced_results: list[JsonObject] = []
    for result in results:
        tool_call_id = str(result.get("tool_call_id") or "")
        replacement = replacement_map.get(tool_call_id)
        if replacement is None:
            replaced_results.append(result)
            continue
        updated = dict(result)
        updated["content_preview"] = str(replacement.get("replacement_preview") or "")
        updated["content_replacement"] = dict(replacement)
        updated["content_replacement_applied"] = True
        replaced_results.append(updated)
    return replaced_results, newly_replaced


def reconstruct_tool_result_replacement_state(records: Iterable[LedgerRecord]) -> ToolResultReplacementState:
    state = ToolResultReplacementState()
    for record in records:
        data = record.data if isinstance(record.data, dict) else {}
        content = data.get("content")
        if not isinstance(content, dict):
            continue
        replacement_state = content.get("replacement_state")
        if isinstance(replacement_state, dict):
            for value in replacement_state.get("seen_ids", []) if isinstance(replacement_state.get("seen_ids"), list) else []:
                if str(value):
                    state.seen_ids.add(str(value))
            replacements = replacement_state.get("replacements")
            if isinstance(replacements, dict):
                for key, value in replacements.items():
                    if str(key) and isinstance(value, dict):
                        state.replacements[str(key)] = dict(value)
        replacements = content.get("new_replacements")
        if isinstance(replacements, list):
            for item in replacements:
                if not isinstance(item, dict):
                    continue
                tool_call_id = str(item.get("tool_call_id") or "")
                replacement = item.get("replacement")
                if tool_call_id:
                    state.seen_ids.add(tool_call_id)
                if tool_call_id and isinstance(replacement, dict):
                    state.replacements[tool_call_id] = dict(replacement)
    return state


@dataclass(frozen=True)
class _ToolResultCandidate:
    tool_call_id: str
    estimated_chars: int
    preview: str
    projection: JsonObject
    artifact_refs: list[str]


def _candidate(result: JsonObject) -> _ToolResultCandidate | None:
    tool_call_id = str(result.get("tool_call_id") or "")
    if not tool_call_id:
        return None
    projection = result.get("content_projection")
    projection_obj = dict(projection) if isinstance(projection, dict) else {}
    estimated = _positive_int(projection_obj.get("estimated_chars"))
    if estimated is None:
        estimated = len(_stable_json(result.get("content_preview")))
    artifact_refs = [str(item) for item in result.get("artifact_refs", []) if str(item)] if isinstance(result.get("artifact_refs"), list) else []
    return _ToolResultCandidate(
        tool_call_id=tool_call_id,
        estimated_chars=estimated,
        preview=str(result.get("content_preview") or ""),
        projection=projection_obj,
        artifact_refs=artifact_refs,
    )


def _replacement_for(candidate: _ToolResultCandidate) -> JsonObject:
    read_hint = (
        "Full or richer tool output is available through artifact.read using one of artifact_refs."
        if candidate.artifact_refs
        else "Full output was omitted from model-visible context; rerun or request a narrower tool call if needed."
    )
    replacement_preview = _bounded_preview(candidate.preview, 1600)
    return {
        "schema": TOOL_RESULT_REPLACEMENT_SCHEMA,
        "tool_call_id": candidate.tool_call_id,
        "reason": "aggregate_tool_result_budget",
        "original_estimated_chars": candidate.estimated_chars,
        "artifact_refs": list(candidate.artifact_refs),
        "replacement_preview": replacement_preview,
        "projection": dict(candidate.projection),
        "read_hint": read_hint,
    }


def _bounded_preview(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _stable_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
