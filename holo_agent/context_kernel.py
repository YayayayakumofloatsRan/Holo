from __future__ import annotations

from typing import Any

from . import __version__
from .prompt_policy import SYSTEM_PROMPT
from .workspace import WorkspaceContext


CONTEXT_KERNEL_SCHEMA = "holo.stage231.context_kernel.v1"


def _estimate_tokens(text: str) -> int:
    raw = str(text or "")
    return max(1, len(raw) // 4) if raw else 0


def _compact(value: Any, limit: int = 500) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[: limit - 3] + "..." if len(text) > limit else text


def _instruction_chain(workspace: WorkspaceContext) -> list[dict[str, Any]]:
    return [
        {"path": layer.path, "scope": layer.scope, "text": layer.text}
        for layer in workspace.instruction_layers
        if layer.text.strip()
    ]


def _operator_metadata(workspace: WorkspaceContext) -> list[dict[str, str]]:
    return [
        {"name": skill.name, "path": skill.path, "description": skill.description}
        for skill in workspace.skills
    ]


def _selected_operator_brief(workspace: WorkspaceContext, selected_operator: str) -> dict[str, str]:
    if not selected_operator:
        return {}
    selected = selected_operator.replace("_", "-").lower()
    for skill in workspace.skills:
        if skill.name.lower() == selected or skill.name.lower().replace("_", "-") == selected:
            return {"name": skill.name, "path": skill.path, "description": skill.description, "body": skill.body}
    return {}


def compact_executable_state(
    *,
    decisions: list[dict[str, Any]] | None = None,
    observations: list[dict[str, Any]] | None = None,
    self_feedback_reports: list[dict[str, Any]] | None = None,
    stop_reason: str = "",
) -> dict[str, Any]:
    decisions = list(decisions or [])
    observations = list(observations or [])
    feedback = list(self_feedback_reports or [])
    last_decision = decisions[-1] if decisions else {}
    last_observation = observations[-1] if observations else {}
    unresolved_gaps = [
        str(item.get("evidence_gap", "") or "")
        for item in feedback
        if str(item.get("evidence_gap", "") or "").strip()
    ][-5:]
    return {
        "last_action": str(last_decision.get("action", "") or last_observation.get("tool", "")),
        "last_observation_tool": str(last_observation.get("tool", "") or ""),
        "last_observation_status": str(last_observation.get("status", "") or ""),
        "last_observation_summary": _compact(last_observation.get("summary", ""), 240),
        "unresolved_gaps": unresolved_gaps,
        "recommended_next_action": str((feedback[-1] if feedback else {}).get("recommended_next_action", "") or ""),
        "last_stop_reason": stop_reason,
        "decision_count": len(decisions),
        "observation_count": len(observations),
    }


def _observation_lines(observations: list[dict[str, Any]], *, max_items: int = 8) -> list[str]:
    lines = []
    for obs in observations[-max_items:]:
        tool = obs.get("tool", "")
        status = obs.get("status", "")
        summary = _compact(obs.get("summary", ""), 220)
        lines.append(f"- {tool} status={status}: {summary}".strip())
    return lines


def _feedback_lines(reports: list[dict[str, Any]], *, max_items: int = 6) -> list[str]:
    lines = []
    for report in reports[-max_items:]:
        lines.append(
            "- "
            + f"action={report.get('action', '')} sufficient={report.get('evidence_sufficient', False)} "
            + f"gap={_compact(report.get('evidence_gap', ''), 160)} "
            + f"next={report.get('recommended_next_action', '')} stop={report.get('canonical_stop_reason', '')}"
        )
    return lines


def _apply_budget(pack: dict[str, Any], token_budget: int | None) -> None:
    rendered = render_context_for_model(pack, include_budget=False)
    total = _estimate_tokens(rendered)
    pack["budget"] = {
        "estimated_prompt_tokens": total,
        "stable_prefix_tokens": _estimate_tokens(pack.get("stable_prefix", "")),
        "dynamic_suffix_tokens": _estimate_tokens(pack.get("dynamic_turn_block", ""))
        + _estimate_tokens(pack.get("observation_suffix", "")),
        "truncated_sections": [],
        "cache_layout": "stable_prefix_then_dynamic_suffix",
    }
    if not token_budget or total <= token_budget:
        return
    observations = pack.get("observation_rows", [])
    if len(observations) > 1:
        pack["observation_rows"] = observations[-1:]
        pack["observation_suffix"] = "\n".join(_observation_lines(pack["observation_rows"], max_items=1))
        pack["budget"]["truncated_sections"].append("older_observations")
    feedback = pack.get("self_feedback_rows", [])
    if len(feedback) > 1 and _estimate_tokens(render_context_for_model(pack, include_budget=False)) > token_budget:
        pack["self_feedback_rows"] = feedback[-1:]
        pack["self_feedback_suffix"] = "\n".join(_feedback_lines(pack["self_feedback_rows"], max_items=1))
        pack["budget"]["truncated_sections"].append("older_self_feedback")
    pack["budget"]["estimated_prompt_tokens"] = _estimate_tokens(render_context_for_model(pack, include_budget=False))
    pack["budget"]["dynamic_suffix_tokens"] = _estimate_tokens(pack.get("dynamic_turn_block", "")) + _estimate_tokens(
        pack.get("observation_suffix", "")
    )


def build_context_pack(
    *,
    user_text: str,
    workspace: WorkspaceContext,
    action_space: list[dict[str, Any]],
    workflow_policy: dict[str, Any] | None = None,
    search_goal: dict[str, Any] | None = None,
    observations: list[dict[str, Any]] | None = None,
    self_feedback_reports: list[dict[str, Any]] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    selected_operator: str = "",
    stop_reason: str = "",
    token_budget: int | None = None,
) -> dict[str, Any]:
    observations = list(observations or [])
    self_feedback_reports = list(self_feedback_reports or [])
    decisions = list(decisions or [])
    instruction_chain = _instruction_chain(workspace)
    operator_metadata = _operator_metadata(workspace)
    selected_brief = _selected_operator_brief(workspace, selected_operator)
    compact_state = compact_executable_state(
        decisions=decisions,
        observations=observations,
        self_feedback_reports=self_feedback_reports,
        stop_reason=stop_reason,
    )
    stable_prefix = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Kernel version: {__version__}\n"
        "Context rule: context is rendered state, not memory itself. "
        "Tool results are observations, not chat text. Exact current user message is authoritative."
    )
    instruction_block = "\n".join(f"- [{item['scope']}] {item['path']}: {_compact(item['text'], 500)}" for item in instruction_chain)
    action_block = "\n".join(f"- {item.get('name')}: {_compact(item.get('description', ''), 180)}" for item in action_space)
    operator_block = "\n".join(f"- {item['name']}: {item['description']} ({item['path']})" for item in operator_metadata)
    selected_operator_block = ""
    if selected_brief:
        selected_operator_block = (
            f"Selected operator: {selected_brief['name']}\n"
            f"Description: {selected_brief['description']}\n"
            f"Brief:\n{selected_brief['body']}"
        )
    dynamic_turn_block = (
        f"Workflow policy: {workflow_policy or {}}\n"
        f"Search goal: {search_goal or {}}\n"
        f"Compact executable state: {compact_state}"
    )
    observation_suffix = "\n".join(_observation_lines(observations))
    self_feedback_suffix = "\n".join(_feedback_lines(self_feedback_reports))
    final_constraints_block = (
        "Final constraints: cite or report only ledgered observations; "
        "continue if evidence gaps remain and budget allows; otherwise report a precise stop reason."
    )
    pack = {
        "schema": CONTEXT_KERNEL_SCHEMA,
        "kernel_version": __version__,
        "stable_prefix": stable_prefix,
        "instruction_chain": instruction_chain,
        "instruction_block": instruction_block,
        "operator_metadata": operator_metadata,
        "operator_metadata_block": operator_block,
        "selected_operator": selected_operator,
        "selected_operator_brief": selected_brief,
        "selected_operator_block": selected_operator_block,
        "action_space_block": action_block,
        "dynamic_turn_block": dynamic_turn_block,
        "observation_rows": observations,
        "observation_suffix": observation_suffix,
        "self_feedback_rows": self_feedback_reports,
        "self_feedback_suffix": self_feedback_suffix,
        "compact_state": compact_state,
        "final_constraints_block": final_constraints_block,
        "exact_user_message": str(user_text or ""),
        "sections": [
            {"name": "stable_prefix"},
            {"name": "instruction_chain"},
            {"name": "operator_metadata"},
            {"name": "selected_operator_brief"},
            {"name": "action_space"},
            {"name": "working_state"},
            {"name": "observations"},
            {"name": "self_feedback"},
            {"name": "final_constraints"},
            {"name": "exact_user_message"},
        ],
    }
    _apply_budget(pack, token_budget)
    return pack


def render_context_for_model(pack: dict[str, Any], *, include_budget: bool = True) -> str:
    chunks = [
        "# Stable Kernel Contract",
        str(pack.get("stable_prefix", "")),
        "# Instruction Chain",
        str(pack.get("instruction_block", "")) or "- none",
        "# Operator Registry Metadata",
        str(pack.get("operator_metadata_block", "")) or "- none",
    ]
    if pack.get("selected_operator_block"):
        chunks.extend(["# Selected Operator Brief", str(pack.get("selected_operator_block", ""))])
    chunks.extend(
        [
            "# Action Space",
            str(pack.get("action_space_block", "")) or "- none",
            "# Working State",
            str(pack.get("dynamic_turn_block", "")),
            "# Observation Ledger Window",
            str(pack.get("observation_suffix", "")) or "- none",
            "# Self Feedback Reports",
            str(pack.get("self_feedback_suffix", "")) or "- none",
            "# Final Constraints",
            str(pack.get("final_constraints_block", "")),
        ]
    )
    if include_budget:
        chunks.extend(["# Context Budget", str(pack.get("budget", {}))])
    chunks.extend(["# Exact User Message", str(pack.get("exact_user_message", ""))])
    return "\n".join(chunks)
