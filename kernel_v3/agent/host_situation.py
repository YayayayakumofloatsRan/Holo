from __future__ import annotations

from kernel_v3.agent.contracts import TaskRecipe
from kernel_v3.contracts import JsonObject, LedgerRecord, ToolManifest
from kernel_v3.journal import JournalStore


HOST_SITUATION_SCHEMA = "holo.kernel_v3.host_situation.v1"


def build_host_situation(
    *,
    journal: JournalStore | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    recipe: TaskRecipe | None = None,
    tool_manifests: list[ToolManifest] | None = None,
    failure_report: JsonObject | None = None,
    thread_id: str | None = None,
) -> JsonObject:
    """Build a compact, redaction-safe host-state packet for model calls.

    This packet is deliberately factual and host-derived. It should not contain
    raw fetched bodies, secrets, or private reasoning; it tells processors what
    the host can do and what just happened so models do not infer capability
    state from generic defaults.
    """

    records = _records(journal, task_id=task_id, run_id=run_id)
    retrieval = _retrieval_state(tool_manifests or [], recipe=recipe)
    activity = _recent_activity(records)
    task = _task_state(recipe=recipe, task_id=task_id, run_id=run_id, thread_id=thread_id)
    failure = _failure_state(
        failure_report,
        activity=activity,
        retrieval=retrieval,
        task_mode=task.get("mode") if isinstance(task.get("mode"), str) else None,
    )
    return {
        "schema": HOST_SITUATION_SCHEMA,
        "task": task,
        "permissions": _permission_state(recipe=recipe),
        "tools": _tool_state(tool_manifests or [], recipe=recipe),
        "retrieval": retrieval,
        "recent_activity": activity,
        "failure": failure,
        "professional_boundary": {
            "finance_research": "supported_when_evidence_grounded",
            "financial_advice_boundary": "do_public_research_and_analysis; do_not_present_personalized_licensed_advice",
        },
        "user_visible_rules": [
            "Use this host_situation as the source of truth for current tool, network, retrieval, budget, and failure state.",
            "Do not claim network, live retrieval, or finance research is unavailable when host_situation says it is available.",
            "Distinguish permission/configuration failures from search quality, fetch, extraction, citation, or coverage failures.",
            "If retrieval attempted and failed, say what failed and what different host-valid strategy remains; do not ask for generic missing information.",
        ],
    }


def _records(journal: JournalStore | None, *, task_id: str | None, run_id: str | None) -> list[LedgerRecord]:
    if journal is None:
        return []
    if task_id is not None or run_id is not None:
        return journal.records(task_id=task_id, run_id=run_id)
    return journal.records()


def _task_state(
    *,
    recipe: TaskRecipe | None,
    task_id: str | None,
    run_id: str | None,
    thread_id: str | None,
) -> JsonObject:
    metadata = recipe.metadata if recipe is not None and isinstance(recipe.metadata, dict) else {}
    execution = metadata.get("execution_metadata") if isinstance(metadata.get("execution_metadata"), dict) else {}
    inferred_thread = thread_id or metadata.get("thread_id") or execution.get("thread_id")
    return {
        "task_id": task_id,
        "run_id": run_id,
        "thread_id": inferred_thread if isinstance(inferred_thread, str) else None,
        "mode": recipe.mode if recipe is not None else None,
        "recipe_id": recipe.recipe_id if recipe is not None else None,
        "citations_required": recipe.citations_required if recipe is not None else None,
        "context_budget_mode": recipe.context_budget_mode if recipe is not None else None,
    }


def _permission_state(*, recipe: TaskRecipe | None) -> JsonObject:
    if recipe is None:
        return {
            "permission_profile": None,
            "allowed_tools": [],
            "allowed_permissions": [],
        }
    return {
        "permission_profile": recipe.permission_profile,
        "allowed_tools": list(recipe.allowed_tools),
        "allowed_permissions": _allowed_permissions(recipe),
        "limits": {
            "max_steps": recipe.max_steps,
            "max_tool_calls": recipe.max_tool_calls,
            "max_network_fetches": recipe.max_network_fetches,
            "max_total_artifact_bytes": recipe.max_total_artifact_bytes,
        },
    }


def _allowed_permissions(recipe: TaskRecipe) -> list[str]:
    metadata = recipe.metadata if isinstance(recipe.metadata, dict) else {}
    execution = metadata.get("execution_metadata") if isinstance(metadata.get("execution_metadata"), dict) else {}
    permissions = execution.get("allowed_permissions")
    if isinstance(permissions, list):
        return [str(item) for item in permissions if isinstance(item, str)]
    return []


def _tool_state(tool_manifests: list[ToolManifest], *, recipe: TaskRecipe | None) -> JsonObject:
    allowed = set(recipe.allowed_tools) if recipe is not None else {manifest.name for manifest in tool_manifests}
    available: list[JsonObject] = []
    blocked: list[JsonObject] = []
    for manifest in tool_manifests:
        item = {
            "name": manifest.name,
            "enabled": manifest.enabled,
            "allowed_by_recipe": manifest.name in allowed,
            "side_effect_class": manifest.side_effect_class,
            "permissions_required": list(manifest.permissions_required),
        }
        if manifest.enabled and manifest.name in allowed:
            available.append(item)
        else:
            blocked.append(item)
    return {
        "available": available,
        "blocked_or_unavailable": blocked,
        "available_tool_names": [item["name"] for item in available],
        "network_tool_names": [
            item["name"]
            for item in available
            if item["side_effect_class"] == "network" or "network:fetch" in item["permissions_required"]
        ],
    }


def _retrieval_state(tool_manifests: list[ToolManifest], *, recipe: TaskRecipe | None) -> JsonObject:
    manifest = next((item for item in tool_manifests if item.name == "retrieval.run"), None)
    max_network_fetches = recipe.max_network_fetches if recipe is not None else 0
    allowed_tools = set(recipe.allowed_tools) if recipe is not None else set()
    if manifest is None:
        return {
            "configured": False,
            "available": False,
            "allowed_by_recipe": "retrieval.run" in allowed_tools,
            "reason": "retrieval_tool_not_registered",
            "network_budget_available": max_network_fetches > 0,
            "max_network_fetches": max_network_fetches,
            "live_search_available": False,
            "live_fetch_available": False,
            "search_provider_ids": [],
            "fetch_provider_ids": [],
        }

    schema = manifest.input_schema if isinstance(manifest.input_schema, dict) else {}
    capabilities = schema.get("_provider_capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
    search = [item for item in capabilities if isinstance(item, dict) and item.get("provider_kind") == "search"]
    fetch = [item for item in capabilities if isinstance(item, dict) and item.get("provider_kind") == "fetch"]
    configured = manifest.enabled and manifest.name in allowed_tools if recipe is not None else manifest.enabled
    return {
        "configured": configured,
        "available": manifest.enabled,
        "allowed_by_recipe": manifest.name in allowed_tools if recipe is not None else True,
        "tool_name": manifest.name,
        "side_effect_class": manifest.side_effect_class,
        "network_access": bool(schema.get("_network_access") or manifest.side_effect_class == "network"),
        "network_permission_required": "network:fetch" in manifest.permissions_required,
        "network_budget_available": max_network_fetches > 0,
        "max_network_fetches": max_network_fetches,
        "max_tool_calls": recipe.max_tool_calls if recipe is not None else None,
        "max_steps": recipe.max_steps if recipe is not None else None,
        "live_search_available": any(bool(item.get("live_network")) for item in search),
        "live_fetch_available": any(bool(item.get("live_network")) for item in fetch),
        "profile_aware_search_available": any(bool(item.get("profile_aware")) for item in search),
        "search_provider_ids": _provider_ids(search),
        "fetch_provider_ids": _provider_ids(fetch),
        "provider_summary": _provider_summary(capabilities),
    }


def _provider_summary(capabilities: list[object]) -> list[JsonObject]:
    summary: list[JsonObject] = []
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        summary.append(
            {
                "provider_id": item.get("provider_id"),
                "provider_kind": item.get("provider_kind"),
                "live_network": bool(item.get("live_network")),
                "profile_aware": bool(item.get("profile_aware")),
                "authority": item.get("authority"),
            }
        )
    return summary[:20]


def _provider_ids(items: list[JsonObject]) -> list[str]:
    ids: list[str] = []
    for item in items:
        provider_id = item.get("provider_id")
        if isinstance(provider_id, str) and provider_id:
            ids.append(provider_id)
        diagnostics = item.get("diagnostics")
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        nested = diagnostics.get("providers")
        if isinstance(nested, list):
            ids.extend(_provider_ids([entry for entry in nested if isinstance(entry, dict)]))
    return _ordered_unique(ids)


def _recent_activity(records: list[LedgerRecord]) -> JsonObject:
    action_records = [record for record in records if record.kind == "action"]
    observation_records = [record for record in records if record.kind == "observation"]
    retrieval_reports = [record for record in records if record.kind == "retrieval_report"]
    search_attempts = [record for record in records if record.kind == "retrieval_search_attempt"]
    fetch_attempts = [record for record in records if record.kind == "retrieval_fetch_attempt"]
    processor_results = [record for record in records if record.kind == "processor_result"]
    termination = [record for record in records if record.kind == "termination_decision"]
    failures = [record for record in records if record.kind == "agent_failure_report"]
    latest_report = retrieval_reports[-1].data if retrieval_reports else {}
    latest_failure = failures[-1].data if failures else {}
    processor_summary = [_compact_processor_result(record) for record in processor_results[-8:]]
    latest_processor_error = next(
        (
            item.get("error_preview") or item.get("error")
            for item in reversed(processor_summary)
            if item.get("status") == "failed"
        ),
        None,
    )
    return {
        "attempted_actions": _ordered_unique([_action_name(record.data) for record in action_records if _action_name(record.data)]),
        "tool_observations": [_compact_observation(record) for record in observation_records[-8:]],
        "processor_results": processor_summary,
        "failed_processor_results": sum(1 for item in processor_summary if item.get("status") == "failed"),
        "latest_processor_error": latest_processor_error,
        "retrieval_runs": len(retrieval_reports),
        "search_attempts": len(search_attempts),
        "fetch_attempts": len(fetch_attempts),
        "successful_fetches": sum(1 for record in fetch_attempts if _record_status(record) == "ok"),
        "failed_fetches": sum(1 for record in fetch_attempts if _record_status(record) == "failed"),
        "latest_retrieval_status": latest_report.get("status") if isinstance(latest_report, dict) else None,
        "latest_retrieval_reason": _first_string(latest_report, ("reason", "status")) if isinstance(latest_report, dict) else None,
        "latest_termination_decision": termination[-1].data.get("decision") if termination else None,
        "latest_termination_reason": termination[-1].data.get("reason") if termination else None,
        "latest_failure_reason": latest_failure.get("reason") if isinstance(latest_failure, dict) else None,
    }


def _action_name(data: JsonObject) -> str | None:
    for key in ("name", "action_name"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    payload = data.get("action")
    if isinstance(payload, dict):
        value = payload.get("name")
        if isinstance(value, str) and value:
            return value
    return None


def _compact_observation(record: LedgerRecord) -> JsonObject:
    data = record.data
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    return {
        "record_id": record.record_id,
        "source": data.get("source"),
        "status": data.get("status") or content.get("status"),
        "reason": _first_string(content, ("reason", "error", "stop_reason")),
    }


def _compact_processor_result(record: LedgerRecord) -> JsonObject:
    data = record.data
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    return {
        "record_id": record.record_id,
        "task_type": data.get("task_type"),
        "provider": data.get("provider"),
        "model": data.get("model"),
        "status": data.get("status"),
        "duration_ms": data.get("duration_ms"),
        "error": data.get("error"),
        "error_preview": output.get("error_message_preview"),
    }


def _record_status(record: LedgerRecord) -> str | None:
    data = record.data
    value = data.get("status")
    if isinstance(value, str):
        return value
    content = data.get("content")
    if isinstance(content, dict):
        value = content.get("status")
        if isinstance(value, str):
            return value
    return None


def _failure_state(
    failure_report: JsonObject | None,
    *,
    activity: JsonObject,
    retrieval: JsonObject,
    task_mode: str | None,
) -> JsonObject:
    report = failure_report if isinstance(failure_report, dict) else {}
    reason = report.get("reason") if isinstance(report.get("reason"), str) else activity.get("latest_failure_reason")
    missing = report.get("missing_evidence")
    missing_list = [str(item) for item in missing if isinstance(item, str)] if isinstance(missing, list) else []
    permission_issue = _is_permission_issue(str(reason or ""), retrieval=retrieval, task_mode=task_mode)
    retrieval_attempted = int(activity.get("retrieval_runs") or 0) > 0
    return {
        "reason": reason,
        "missing_evidence": missing_list,
        "next_possible_action": report.get("next_possible_action"),
        "retrieval_attempted": retrieval_attempted,
        "failure_is_permission_or_configuration_issue": permission_issue,
        "failure_is_evidence_or_quality_issue": bool(reason) and not permission_issue,
        "diagnosis": _failure_diagnosis(str(reason or ""), retrieval=retrieval, activity=activity, task_mode=task_mode),
    }


def _is_permission_issue(reason: str, *, retrieval: JsonObject, task_mode: str | None) -> bool:
    if not reason:
        return False
    reason_l = reason.lower()
    if any(token in reason_l for token in ("permission", "not_allowed", "policy", "disabled", "not_configured", "unconfigured")):
        return True
    if reason_l in {"max_network_fetches", "missing_citation_refs", "planned_retrieval_subgoals_incomplete"}:
        return False
    if task_mode == "retrieval_answer" and retrieval.get("configured") is False:
        return True
    return False


def _failure_diagnosis(reason: str, *, retrieval: JsonObject, activity: JsonObject, task_mode: str | None) -> str:
    retrieval_runs = int(activity.get("retrieval_runs") or 0)
    if task_mode == "retrieval_answer" and retrieval.get("configured") is False:
        return "retrieval_tool_or_provider_not_configured"
    if retrieval.get("network_budget_available") is False and retrieval.get("network_permission_required") is True:
        return "network_budget_or_permission_unavailable"
    if reason == "max_network_fetches":
        return "tool_budget_exhausted_after_attempts"
    if reason in {"missing_citation_refs", "citations_required_but_missing"}:
        return "citation_coverage_insufficient"
    if retrieval_runs > 0 and int(activity.get("successful_fetches") or 0) == 0:
        return "search_or_fetch_quality_issue"
    if retrieval_runs > 0:
        return "evidence_extraction_or_coverage_issue"
    if reason in {"model_planner_processor_failed", "model_evaluator_failed", "semantic_intake_processor_failed"}:
        return "processor_or_planning_failure"
    if int(activity.get("failed_processor_results") or 0) > 0:
        return "processor_or_planning_failure"
    if task_mode in {"direct_answer", "semantic_answer", "clarify_first"}:
        return "non_retrieval_task_incomplete"
    return "host_task_incomplete"


def _first_string(data: JsonObject, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _ordered_unique(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
