from __future__ import annotations

from kernel_v3.agent.contracts import TaskRecipe
from kernel_v3.contracts import JsonObject
from kernel_v3.research import ACADEMIC_RESEARCH_PROFILE_ID, FINANCE_FUNDAMENTALS_PROFILE_ID


def adaptive_retrieval_completion(
    *,
    recipe: TaskRecipe,
    planned_coverage: JsonObject,
    evidence_count: int,
    citation_count: int,
) -> JsonObject:
    """Decide whether an open research plan can finish with soft gaps.

    This is a host-side coverage judgment, not a model shortcut. It only applies
    to open academic research profiles where at least one planned retrieval
    subgoal succeeded and enough citable evidence exists to synthesize a useful
    answer with explicit limitations.
    """

    incomplete_goal_ids = _string_list(planned_coverage.get("incomplete_goal_ids"))
    complete_goal_ids = _string_list(planned_coverage.get("complete_goal_ids"))
    if planned_coverage.get("required") is not True or not incomplete_goal_ids:
        return _decision(False, "no_required_incomplete_subgoals")
    open_research = _open_research_judgment(recipe)
    if open_research.get("eligible") is not True:
        return _decision(False, str(open_research.get("reason") or "not_open_research"), diagnostics=open_research)
    if not complete_goal_ids:
        return _decision(False, "no_completed_retrieval_subgoal")
    if citation_count < 3 or evidence_count < 3:
        return _decision(False, "insufficient_citable_evidence")
    return {
        "sufficient": True,
        "reason": "open_research_soft_subgoals_can_be_limited",
        "complete_goal_ids": complete_goal_ids,
        "soft_incomplete_goal_ids": incomplete_goal_ids,
        "limitations": [
            "planned_retrieval_completed_with_soft_gaps",
            *[f"soft_retrieval_subgoal:{goal_id}" for goal_id in incomplete_goal_ids],
        ],
        "diagnostics": open_research,
    }


def _open_research_judgment(recipe: TaskRecipe) -> JsonObject:
    """Return whether incomplete retrieval subgoals can be treated as soft gaps.

    This deliberately does not depend on a single profile flag. Live semantic
    routing can classify a task like "frontier research" as general_research
    while the actual user objective is still an open-ended literature/research
    synthesis. Conversely, company fundamentals, policy facts, and other hard
    factual research should keep all required subgoals strict.
    """

    signals = _research_signals_from_recipe(recipe)
    if _has_hard_retrieval_constraints(signals):
        return {"eligible": False, "reason": "hard_research_constraints", "signals": signals}
    if _is_open_academic_research_recipe(recipe):
        return {"eligible": True, "reason": "academic_research_profile", "signals": signals}
    if _has_open_research_signals(signals):
        return {"eligible": True, "reason": "open_research_signals", "signals": signals}
    return {"eligible": False, "reason": "not_open_research", "signals": signals}


def _is_open_academic_research_recipe(recipe: TaskRecipe) -> bool:
    profiles = _research_profile_ids_from_recipe(recipe)
    if ACADEMIC_RESEARCH_PROFILE_ID not in profiles:
        return False
    task_kinds = _research_task_kinds_from_recipe(recipe)
    if not task_kinds:
        return True
    return bool(task_kinds.intersection({"academic_research", "frontier_research", "literature_review", "paper_search"}))


def _research_signals_from_recipe(recipe: TaskRecipe) -> JsonObject:
    answer_profile = _answer_profile_from_recipe(recipe)
    research_mission = _research_mission_from_recipe(recipe)
    semantic = _json_object(recipe.metadata.get("semantic_intake"))
    execution = _json_object(recipe.metadata.get("execution_metadata"))
    state_summary = _state_profile_summary_from_recipe(recipe)
    payloads = _retrieval_payloads_from_recipe(recipe)
    payload_text = " ".join(str(payload.get("query") or payload.get("goal") or "") for payload in payloads)
    metadata_text = " ".join(
        [
            str(recipe.metadata.get("root_goal") or ""),
            str(semantic.get("goal") or ""),
            str(semantic.get("primary_intent") or ""),
            str(research_mission.get("root_goal") or ""),
            str(research_mission.get("domain") or ""),
            str(answer_profile.get("format") or ""),
            str(answer_profile.get("detail_level") or ""),
            str(answer_profile.get("metadata", {}) if isinstance(answer_profile.get("metadata"), dict) else ""),
            payload_text,
        ]
    )
    capabilities = _capabilities_from_semantic(semantic)
    domains = _ordered_unique(
        [
            _string_value(answer_profile.get("metadata", {}).get("domain") if isinstance(answer_profile.get("metadata"), dict) else None),
            _string_value(research_mission.get("domain")),
            _string_value(state_summary.get("dominant_domain")),
        ]
    )
    return {
        "profiles": sorted(_research_profile_ids_from_recipe(recipe)),
        "task_kinds": sorted(_research_task_kinds_from_recipe(recipe)),
        "capabilities": sorted(capabilities),
        "domains": domains,
        "answer_format": _string_value(answer_profile.get("format")),
        "answer_detail_level": _string_value(answer_profile.get("detail_level")),
        "target_sections": _string_list(answer_profile.get("target_sections")),
        "minimum_coverage": _string_list(answer_profile.get("minimum_coverage")),
        "text": metadata_text,
        "execution_metadata_keys": sorted(str(key) for key in execution.keys()),
    }


def _has_hard_retrieval_constraints(signals: JsonObject) -> bool:
    profiles = set(_string_list(signals.get("profiles")))
    capabilities = set(_string_list(signals.get("capabilities")))
    domains = set(_string_list(signals.get("domains")))
    text = str(signals.get("text") or "").lower()
    if FINANCE_FUNDAMENTALS_PROFILE_ID in profiles or "finance" in domains:
        return True
    if any(item.startswith("finance.") for item in capabilities):
        return True
    if "policy" in domains or any(item.startswith("policy.") for item in capabilities):
        return True
    hard_markers = (
        "基本面",
        "财务",
        "估值",
        "市盈率",
        "资产负债",
        "现金流",
        "规模",
        "营收",
        "员工人数",
        "股价",
        "market cap",
        "p/e",
        "pe ratio",
        "revenue",
        "employees",
        "regulation",
        "policy",
    )
    return _contains_any(text, hard_markers)


def _has_open_research_signals(signals: JsonObject) -> bool:
    text = str(signals.get("text") or "").lower()
    capabilities = set(_string_list(signals.get("capabilities")))
    domains = set(_string_list(signals.get("domains")))
    task_kinds = set(_string_list(signals.get("task_kinds")))
    sections = set(_string_list(signals.get("target_sections")))
    coverage = set(_string_list(signals.get("minimum_coverage")))
    if "academic" in domains or any(item.startswith("academic.") for item in capabilities):
        return True
    if task_kinds.intersection({"academic_research", "frontier_research", "literature_review", "paper_search"}):
        return True
    if sections.intersection({"前沿方向", "争议与开放问题", "关键文献与来源"}) or coverage.intersection(
        {"scholarly_sources", "frontier_or_open_questions"}
    ):
        return True
    open_markers = (
        "前沿",
        "开放问题",
        "文献",
        "论文",
        "学术",
        "综述",
        "研究方向",
        "arxiv",
        "doi",
        "survey",
        "literature",
        "paper",
        "papers",
        "frontier",
        "state of the art",
        "open problem",
    )
    return _contains_any(text, open_markers)


def _research_profile_ids_from_recipe(recipe: TaskRecipe) -> set[str]:
    profiles: set[str] = set()
    for payload in _retrieval_payloads_from_recipe(recipe):
        metadata = _json_object(payload.get("metadata"))
        for value in (
            metadata.get("research_profile"),
            metadata.get("research_profile_id"),
            payload.get("research_profile"),
            payload.get("research_profile_id"),
        ):
            if isinstance(value, str) and value.strip():
                profiles.add(value.strip())
    return profiles


def _research_task_kinds_from_recipe(recipe: TaskRecipe) -> set[str]:
    kinds: set[str] = set()
    for payload in _retrieval_payloads_from_recipe(recipe):
        metadata = _json_object(payload.get("metadata"))
        value = metadata.get("research_task_kind") or payload.get("research_task_kind")
        if isinstance(value, str) and value.strip():
            kinds.add(value.strip())
    return kinds


def _retrieval_payloads_from_recipe(recipe: TaskRecipe) -> list[JsonObject]:
    plan = _json_object(recipe.metadata.get("task_execution_plan"))
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return []
    payloads: list[JsonObject] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        metadata = _json_object(raw_step.get("metadata"))
        capability_args = _json_object(metadata.get("capability_args"))
        value = capability_args.get("retrieval.run")
        if isinstance(value, dict):
            payloads.append(dict(value))
        elif isinstance(value, list):
            payloads.extend(dict(item) for item in value if isinstance(item, dict))
    return payloads


def _answer_profile_from_recipe(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("answer_profile")
    if isinstance(value, dict):
        return dict(value)
    execution = _json_object(recipe.metadata.get("execution_metadata"))
    value = execution.get("answer_profile")
    return dict(value) if isinstance(value, dict) else {}


def _research_mission_from_recipe(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("research_mission")
    if isinstance(value, dict):
        return dict(value)
    execution = _json_object(recipe.metadata.get("execution_metadata"))
    value = execution.get("research_mission")
    return dict(value) if isinstance(value, dict) else {}


def _state_profile_summary_from_recipe(recipe: TaskRecipe) -> JsonObject:
    graph = _json_object(recipe.metadata.get("task_graph"))
    metadata = _json_object(graph.get("metadata"))
    summary = _json_object(metadata.get("state_profile_summary"))
    return summary


def _capabilities_from_semantic(semantic: JsonObject) -> set[str]:
    capabilities: set[str] = set()
    intents = semantic.get("intents")
    if isinstance(intents, list):
        for intent in intents:
            if not isinstance(intent, dict):
                continue
            values = intent.get("required_capabilities")
            if isinstance(values, list):
                capabilities.update(str(item) for item in values if isinstance(item, str) and item)
    return capabilities


def _decision(sufficient: bool, reason: str, *, diagnostics: JsonObject | None = None) -> JsonObject:
    return {
        "sufficient": sufficient,
        "reason": reason,
        "complete_goal_ids": [],
        "soft_incomplete_goal_ids": [],
        "limitations": [],
        "diagnostics": diagnostics or {},
    }


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value if isinstance(raw, str)) if item]


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _string_value(value: object) -> str:
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lower = str(text or "").lower()
    return any(marker.lower() in lower for marker in markers)
