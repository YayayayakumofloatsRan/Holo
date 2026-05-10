from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .brain_ops import filter_self_revision_patch, run_self_revision
from .common import compact_text, stable_digest, utc_now
from .models import ProcessorTaskRequest

DEFAULT_LONG_HORIZON_GOALS = [
    "maintain_identity_continuity",
    "keep_relationship_memory_alive",
    "reduce_recall_failures",
    "stay lively without losing steadiness",
]

DEFAULT_HOMEOSTASIS_TARGETS = {
    "reply_budget_fast_ms": 350,
    "reply_budget_recall_ms": 1200,
    "reply_budget_deep_ms": 2500,
    "recall_quality": 0.74,
    "persona_liveliness_floor": 0.58,
}

DEFAULT_RELATIONAL_COMMITMENTS = [
    "carry forward important old threads",
    "protect continuity with close contacts",
    "keep a little wolfish playfulness alive",
]

DEFAULT_ACTIVE_DEFICITS = [
    "stiffness_drift",
    "recall_depth_gap",
]

ENGINEERING_REQUIRED_TASKS = (
    "reply",
    "recall_reconstruct",
    "initiative_probe",
    "deep_simulation",
    "self_model_observe",
    "operator_plan",
)

BACKGROUND_USAGE_TASKS = {
    "self_model_observe",
    "self_model_plan",
    "operator_plan",
    "operator_execute_shadow",
    "operator_review",
    "reflect",
    "dream",
    "initiative_plan",
    "autobiographical_consolidation",
    "goal_arbitration",
    "world_calibration",
    "affect_reflect",
    "drive_plan",
    "value_integrate",
    "conflict_arbitrate",
    "initiative_compose",
    "outcome_appraise",
}

CACHE_OBSERVATION_SAMPLE_FLOOR = 4
CACHE_DEFICIT_NAMES = {"cache_coldness", "cache_reuse_weak"}


def _parse_json(text: str) -> dict[str, Any]:
    current = str(text or "").strip()
    if not current:
        return {}
    try:
        payload = json.loads(current)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _coerce_string_list(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        rows = [str(item).strip() for item in value if str(item).strip()]
        return rows or list(fallback)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            rows = [str(item).strip() for item in parsed if str(item).strip()]
            return rows or list(fallback)
        stripped = str(value).strip()
        return [stripped] if stripped else list(fallback)
    return list(fallback)


def _coerce_dict(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return dict(parsed)
    return dict(fallback)


def _coerce_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _coerce_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def _cache_state_from_brain_status(brain_status: dict[str, Any]) -> dict[str, Any]:
    cache = dict(brain_status.get("cache", {}))
    hits = max(0, _coerce_int(cache.get("hits", 0), 0))
    misses = max(0, _coerce_int(cache.get("misses", 0), 0))
    sample_count = hits + misses
    entries = max(0, _coerce_int(cache.get("entries", 0), 0))
    hit_ratio = round(_coerce_float(cache.get("hit_ratio", 0.0), 0.0), 4) if sample_count else 0.0
    observation_sufficient = sample_count >= CACHE_OBSERVATION_SAMPLE_FLOOR
    reuse_pressure = 0.0
    if observation_sufficient:
        reuse_pressure = round(min(1.0, max(0.0, (0.28 - hit_ratio) * 2.2 + (0.08 if entries <= 0 else 0.0))), 4)
    return {
        "hit_ratio": hit_ratio,
        "entries": entries,
        "hits": hits,
        "misses": misses,
        "sample_count": sample_count,
        "observation_sufficient": observation_sufficient,
        "reuse_pressure": reuse_pressure,
    }


def _cache_deficits(cache_state: dict[str, Any]) -> list[str]:
    if not bool(cache_state.get("observation_sufficient", False)):
        return []
    hit_ratio = _coerce_float(cache_state.get("hit_ratio", 0.0), 0.0)
    deficits: list[str] = []
    if hit_ratio < 0.15:
        deficits.append("cache_coldness")
    if hit_ratio < 0.2:
        deficits.append("cache_reuse_weak")
    return deficits


def _usage_rows(store, *, limit: int = 40) -> list[dict[str, Any]]:
    if not hasattr(store, "list_processor_usage"):
        return []
    try:
        rows = store.list_processor_usage(limit=max(1, int(limit)))
    except Exception:  # noqa: BLE001
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _provider_state(*, config, runner) -> dict[str, Any]:
    provider_status = runner.provider_status() if hasattr(runner, "provider_status") else {}
    providers = dict(provider_status.get("providers", {}))
    lanes = dict(provider_status.get("lanes", {}))
    degraded = sorted(name for name, payload in providers.items() if not bool(dict(payload).get("available", False)))
    backup_candidates = {
        str(dict(payload).get("backup_provider", "") or "").strip()
        for payload in lanes.values()
        if isinstance(payload, dict)
    }
    backup_candidates.discard("")
    fallback_ready = bool(backup_candidates) and any(
        bool(dict(providers.get(name, {})).get("available", False))
        for name in backup_candidates
    )
    return {
        "active_backend": str(provider_status.get("active_backend_alias", getattr(config.runtime, "processor_backend", "")) or ""),
        "fallback_ready": bool(fallback_ready),
        "degraded_providers": degraded,
        "backup_candidates": sorted(backup_candidates),
    }


def _routing_state(*, config, runner) -> dict[str, Any]:
    routing = runner.routing_table() if hasattr(runner, "routing_table") else {}
    lane_summary = {
        str(name): str(getattr(payload, "primary_provider", "") or "")
        for name, payload in dict(getattr(config.processor_fabric, "provider_backends", {})).items()
    }
    required_tasks_routed = [name for name in ENGINEERING_REQUIRED_TASKS if name in routing]
    routing_gaps = [name for name in ENGINEERING_REQUIRED_TASKS if name not in routing]
    return {
        "required_tasks_routed": required_tasks_routed,
        "lane_summary": lane_summary,
        "routing_gaps": routing_gaps,
    }


def _usage_state(*, store) -> dict[str, Any]:
    rows = _usage_rows(store, limit=40)
    total_tokens = sum(int(row.get("total_tokens", 0) or 0) for row in rows)
    estimated_count = sum(1 for row in rows if bool(row.get("estimated", 0)))
    background_tokens = sum(
        int(row.get("total_tokens", 0) or 0)
        for row in rows
        if str(row.get("task_type", "")).strip() in BACKGROUND_USAGE_TASKS
    )
    by_task: dict[str, int] = {}
    for row in rows:
        task_type = str(row.get("task_type", "") or "").strip() or "<unknown>"
        by_task[task_type] = by_task.get(task_type, 0) + int(row.get("total_tokens", 0) or 0)
    top_spend_tasks = [name for name, _tokens in sorted(by_task.items(), key=lambda item: (-item[1], item[0]))[:4]]
    return {
        "recent_ledger_count": len(rows),
        "estimated_ratio": round(estimated_count / len(rows), 4) if rows else 0.0,
        "background_token_share": round(background_tokens / total_tokens, 4) if total_tokens else 0.0,
        "top_spend_tasks": top_spend_tasks,
        "stage10_task_count": sum(1 for row in rows if str(row.get("task_type", "")).strip() in {"self_model_observe", "operator_plan"}),
    }


def _operator_state(*, memory) -> dict[str, Any]:
    operator_status = memory.graph.operator_status() if hasattr(memory.graph, "operator_status") else {}
    runtime_state = memory.graph.brain_state() if hasattr(memory.graph, "brain_state") else {}
    planning_state = dict(dict(runtime_state.get("metadata", {})).get("operator_planning_state", {}))
    latest = dict(operator_status.get("latest", {}))
    latest_payload = dict(latest.get("payload", {}))
    latest_result = dict(latest.get("result", {}))
    return {
        "pending_count": int(operator_status.get("pending_count", 0) or 0),
        "last_trigger_digest": str(
            planning_state.get("last_trigger_digest", "")
            or latest_payload.get("trigger_digest", "")
            or ""
        ),
        "last_plan_reason": str(
            planning_state.get("last_plan_reason", "")
            or latest_payload.get("reason", "")
            or latest_result.get("goal", "")
            or ""
        ),
        "last_status": str(planning_state.get("last_status", "") or latest.get("status", "") or ""),
    }


def _engineering_summary(active_deficits: list[str], *, provider_state: dict[str, Any], usage_state: dict[str, Any], cache_state: dict[str, Any]) -> str:
    if not active_deficits:
        return "engineering snapshot is calm and bounded"
    if "usage_visibility_cold" in active_deficits:
        return "usage visibility is too cold to trust cost decisions yet"
    if "cache_reuse_weak" in active_deficits:
        return "cache reuse is still weak, so deeper planning should stay bounded"
    if "provider_fallback_unready" in active_deficits:
        return "fallback providers are not ready, so routing resilience should stay explicit"
    if "operator_overplanning_risk" in active_deficits:
        return "background planning risk is elevated and should stay delta-gated"
    if "expression_calibration_gap" in active_deficits:
        return "expression calibration still needs bounded self-repair rather than more loops"
    return (
        f"engineering snapshot stays bounded around provider={provider_state.get('active_backend', '')} "
        f"ledger={usage_state.get('recent_ledger_count', 0)} cache_hit={cache_state.get('hit_ratio', 0.0)}"
    )


def build_engineering_snapshot(*, memory, store, config, runner=None, base_deficits: list[str] | None = None) -> dict[str, Any]:
    brain_status = memory.brain_status()
    cache_state = _cache_state_from_brain_status(brain_status)
    provider_state = _provider_state(config=config, runner=runner)
    routing_state = _routing_state(config=config, runner=runner)
    usage_state = _usage_state(store=store)
    operator_state = _operator_state(memory=memory)
    hit_ratio = _coerce_float(cache_state.get("hit_ratio", 0.0), 0.0)
    linked_deficits = [
        str(item).strip()
        for item in list(base_deficits or [])
        if str(item).strip() and str(item).strip() not in CACHE_DEFICIT_NAMES
    ]
    active_deficits: list[str] = []
    if not bool(provider_state.get("fallback_ready", False)):
        active_deficits.append("provider_fallback_unready")
    if int(usage_state.get("recent_ledger_count", 0) or 0) <= 0:
        active_deficits.append("usage_visibility_cold")
    if "cache_reuse_weak" in _cache_deficits(cache_state):
        active_deficits.append("cache_reuse_weak")
    if float(usage_state.get("background_token_share", 0.0) or 0.0) >= 0.28 and int(operator_state.get("pending_count", 0) or 0) <= 0:
        active_deficits.append("operator_overplanning_risk")
    if "stiffness_drift" in linked_deficits or "self_revision_unsettled" in linked_deficits:
        active_deficits.append("expression_calibration_gap")
    merged_deficits = []
    for item in linked_deficits + active_deficits:
        if item and item not in merged_deficits:
            merged_deficits.append(item)
    penalty = 0.0
    for name, weight in (
        ("provider_fallback_unready", 0.16),
        ("usage_visibility_cold", 0.2),
        ("cache_reuse_weak", 0.15),
        ("operator_overplanning_risk", 0.1),
        ("expression_calibration_gap", 0.08),
    ):
        if name in merged_deficits:
            penalty += weight
    engineering_confidence = max(0.26, min(0.94, 0.9 - penalty + (0.04 if hit_ratio >= 0.35 else 0.0)))
    budget_pressure = max(
        0.08,
        min(
            0.94,
            0.14
            + float(usage_state.get("background_token_share", 0.0) or 0.0) * 0.72
            + (0.14 if "usage_visibility_cold" in merged_deficits else 0.0)
            + (0.08 if "provider_fallback_unready" in merged_deficits else 0.0)
            + (0.06 if "operator_overplanning_risk" in merged_deficits else 0.0),
        ),
    )
    digest = stable_digest(
        json.dumps(provider_state, ensure_ascii=False, sort_keys=True),
        json.dumps(routing_state, ensure_ascii=False, sort_keys=True),
        json.dumps(usage_state, ensure_ascii=False, sort_keys=True),
        json.dumps(cache_state, ensure_ascii=False, sort_keys=True),
        json.dumps(operator_state, ensure_ascii=False, sort_keys=True),
        json.dumps(merged_deficits, ensure_ascii=False),
    )
    return {
        "provider_state": provider_state,
        "routing_state": routing_state,
        "usage_state": usage_state,
        "cache_state": cache_state,
        "operator_state": operator_state,
        "engineering_confidence": round(engineering_confidence, 4),
        "budget_pressure": round(budget_pressure, 4),
        "active_deficits": merged_deficits,
        "digest": digest,
        "summary": _engineering_summary(
            merged_deficits,
            provider_state=provider_state,
            usage_state=usage_state,
            cache_state=cache_state,
        ),
    }


def _confidence_from_revision(state: dict[str, Any]) -> float:
    applied = bool(state.get("applied"))
    latest_status = str(state.get("latest_status", "") or "").strip()
    if applied:
        return 0.84
    if latest_status in {"reviewed", "applied"}:
        return 0.72
    if latest_status in {"rejected", "skipped"}:
        return 0.58
    return 0.64


def build_self_model_snapshot(*, memory, store, config, runner=None) -> dict[str, Any]:
    brain_status = memory.brain_status()
    live_cache_state = _cache_state_from_brain_status(brain_status)
    self_revision_state = memory.graph.latest_self_revision_state()
    stream_status = memory.stream_status()
    vector_health = memory.vector_health()
    top_threads = memory.graph.top_thread_commitments(limit=4)
    mode = str(brain_status.get("mode", config.memory.brain_mode_default) or config.memory.brain_mode_default)
    hit_ratio = float(live_cache_state.get("hit_ratio", 0.0) or 0.0)
    identity_continuity = max(
        0.58,
        min(
            0.95,
            _confidence_from_revision(self_revision_state)
            + (0.03 if mode == "full_brain" else 0.0)
            + (0.02 if hit_ratio >= 0.2 else 0.0),
        ),
    )
    capability_model = {
        "hybrid_recall": True,
        "always_on_runtime": True,
        "visual_memory": bool(getattr(config.runtime, "image_enabled", True)),
        "operator_bus": True,
        "shadow_patch_only": True,
        "vector_backend": str(vector_health.get("backend", "")),
    }
    active_deficits: list[str] = []
    if str(self_revision_state.get("latest_status", "")) in {"rejected", "skipped", ""}:
        active_deficits.append("self_revision_unsettled")
    applied_patch = dict(self_revision_state.get("applied_patch", {}))
    persona_patch = dict(applied_patch.get("persona_blend", {}))
    if float(persona_patch.get("playfulness", 0.0) or 0.0) < 0.6:
        active_deficits.append("stiffness_drift")
    if "cache_coldness" in _cache_deficits(live_cache_state):
        active_deficits.append("cache_coldness")
    if not top_threads:
        active_deficits.append("relational_commitments_unclear")
    if bool(getattr(config.runtime, "image_enabled", True)):
        visuals = memory.graph.visual_memory(limit=1)
        if not visuals:
            active_deficits.append("visual_memory_underused")
    if not active_deficits:
        active_deficits = list(DEFAULT_ACTIVE_DEFICITS[:1])
    engineering_snapshot = build_engineering_snapshot(
        memory=memory,
        store=store,
        config=config,
        runner=runner,
        base_deficits=active_deficits,
    )
    active_deficits = list(engineering_snapshot.get("active_deficits", active_deficits))
    relational_commitments = []
    for item in top_threads:
        chat_name = str(item.get("chat_name", "") or item.get("thread_key", "")).strip()
        summary = str(item.get("summary", "") or "").strip()
        if chat_name:
            relational_commitments.append(f"{chat_name}: {compact_text(summary, 120) or 'keep continuity alive'}")
    if not relational_commitments:
        relational_commitments = list(DEFAULT_RELATIONAL_COMMITMENTS)
    recent_revision = {
        "latest_status": str(self_revision_state.get("latest_status", "") or ""),
        "applied": bool(self_revision_state.get("applied")),
        "applied_at": str(self_revision_state.get("applied_at", "") or ""),
    }
    return {
        "identity_continuity": round(identity_continuity, 4),
        "capability_model": capability_model,
        "active_deficits": active_deficits,
        "long_horizon_goals": list(DEFAULT_LONG_HORIZON_GOALS),
        "relational_commitments": relational_commitments,
        "homeostasis_targets": dict(DEFAULT_HOMEOSTASIS_TARGETS),
        "metadata": {
            "brain_mode": mode,
            "cache_hit_ratio": round(hit_ratio, 4),
            "cache_sample_count": int(live_cache_state.get("sample_count", 0) or 0),
            "cache_observation_sufficient": bool(live_cache_state.get("observation_sufficient", False)),
            "recent_revision": recent_revision,
            "recent_stream_runs": len(list(stream_status.get("recent_runs", []))),
            "engineering_snapshot": engineering_snapshot,
            "engineering_confidence": float(engineering_snapshot.get("engineering_confidence", 0.0) or 0.0),
            "budget_pressure": float(engineering_snapshot.get("budget_pressure", 0.0) or 0.0),
            "observed_at": utc_now(),
        },
    }


def build_homeostasis_state(*, memory, config, self_model: dict[str, Any] | None = None) -> dict[str, Any]:
    self_model = self_model or memory.graph.self_model_state()
    brain_status = memory.brain_status()
    operator_status = memory.graph.operator_status()
    live_cache_state = _cache_state_from_brain_status(brain_status)
    active_deficits = [
        str(item).strip()
        for item in list(self_model.get("active_deficits", []))
        if str(item).strip() and str(item).strip() not in CACHE_DEFICIT_NAMES
    ]
    for deficit in _cache_deficits(live_cache_state):
        if deficit not in active_deficits:
            active_deficits.append(deficit)
    engineering_snapshot = dict(dict(self_model.get("metadata", {})).get("engineering_snapshot", {}))
    engineering_snapshot["cache_state"] = live_cache_state
    budget_pressure = _coerce_float(engineering_snapshot.get("budget_pressure", 0.0), 0.0)
    pressure = 0.24 + min(0.32, 0.06 * len(active_deficits)) + budget_pressure * 0.18
    if operator_status.get("pending_count", 0):
        pressure += 0.08
    return {
        "pressure": round(min(0.92, pressure), 4),
        "stability": round(max(0.22, float(self_model.get("identity_continuity", 0.6) or 0.6) - pressure * 0.2), 4),
        "targets": dict(self_model.get("homeostasis_targets", {})),
        "active_deficits": active_deficits,
        "brain_mode": str(brain_status.get("mode", config.memory.brain_mode_default) or config.memory.brain_mode_default),
        "operator_pending_count": int(operator_status.get("pending_count", 0) or 0),
        "provider_state": dict(engineering_snapshot.get("provider_state", {})),
        "routing_state": dict(engineering_snapshot.get("routing_state", {})),
        "usage_state": dict(engineering_snapshot.get("usage_state", {})),
        "cache_state": dict(engineering_snapshot.get("cache_state", {})),
        "operator_state": dict(engineering_snapshot.get("operator_state", {})),
        "engineering_confidence": round(_coerce_float(engineering_snapshot.get("engineering_confidence", 0.0), 0.0), 4),
        "budget_pressure": round(budget_pressure, 4),
        "last_updated_at": utc_now(),
    }


def _self_model_prompt(snapshot: dict[str, Any]) -> str:
    return (
        "Return JSON with keys active_deficits, long_horizon_goals, relational_commitments, homeostasis_targets, summary. "
        "Keep the result bounded and practical.\n\n"
        f"Current snapshot:\n{json.dumps(snapshot, ensure_ascii=False, indent=2)}"
    )


def refresh_self_model(*, config, runner, memory, store, reason: str, source: str = "runtime") -> dict[str, Any]:
    heuristic = build_self_model_snapshot(memory=memory, store=store, config=config, runner=runner)
    prompt = _self_model_prompt(heuristic)
    observed = heuristic
    if hasattr(runner, "run_task"):
        result = runner.run_task(
            ProcessorTaskRequest(
                task_type="self_model_observe",
                prompt=prompt,
                output_schema="json",
                allowed_data_layers=("self_model_state", "mind_graph", "relationship_state", "activation_state"),
            )
        )
        parsed = _parse_json(result.text)
        if parsed:
            observed = {
                **heuristic,
                "active_deficits": _coerce_string_list(parsed.get("active_deficits"), list(heuristic.get("active_deficits", []))),
                "long_horizon_goals": _coerce_string_list(parsed.get("long_horizon_goals"), list(heuristic.get("long_horizon_goals", []))),
                "relational_commitments": _coerce_string_list(parsed.get("relational_commitments"), list(heuristic.get("relational_commitments", []))),
                "homeostasis_targets": _coerce_dict(parsed.get("homeostasis_targets"), dict(heuristic.get("homeostasis_targets", {}))),
                "metadata": {
                    **dict(heuristic.get("metadata", {})),
                    "summary": str(parsed.get("summary", "") or "").strip(),
                    "observe_task_returncode": int(result.returncode or 0),
                },
            }
    return memory.graph.update_self_model_state(
        observed,
        reason=reason,
        source=source,
    )


def _default_operator_boundaries() -> dict[str, Any]:
    return {
        "read_boundary": {
            "repo": "allowed_readonly",
            "tests": "allowed",
            "diff_log": "allowed",
        },
        "write_boundary": {
            "live_repo": "forbidden",
            "shadow_workspace": "allowed",
            "mind_state": "allowed_after_shadow_acceptance",
        },
        "budget_guard": {
            "live_repo_writes": "forbidden",
            "fabric_bypass": "forbidden",
            "background_plans": "delta_only",
        },
    }


def _heuristic_operator_plan(self_model: dict[str, Any]) -> dict[str, Any]:
    deficits = [str(item).strip() for item in self_model.get("active_deficits", []) if str(item).strip()]
    engineering_snapshot = dict(dict(self_model.get("metadata", {})).get("engineering_snapshot", {}))
    engineering_deficits = [str(item).strip() for item in engineering_snapshot.get("active_deficits", []) if str(item).strip()]
    goal = "stabilize engineering state without overplanning"
    source_goal_ids: list[str] = []
    expected_state_gain: dict[str, Any] = {}
    if "cache_reuse_weak" in engineering_deficits or "cache_coldness" in deficits:
        goal = "warm cache reuse before deeper planning"
        source_goal_ids.extend(["cache_warmth", "cost_discipline"])
        expected_state_gain.update({"cache_hit_ratio": 0.12, "engineering_confidence": 0.06})
    elif "provider_fallback_unready" in engineering_deficits:
        goal = "restore routing resilience and keep fallback visibility honest"
        source_goal_ids.extend(["routing_resilience", "cost_discipline"])
        expected_state_gain.update({"engineering_confidence": 0.08, "budget_pressure": -0.06})
    elif "usage_visibility_cold" in engineering_deficits:
        goal = "restore engineering visibility before spending more background planning budget"
        source_goal_ids.append("cost_discipline")
        expected_state_gain.update({"budget_pressure": -0.08, "engineering_confidence": 0.07})
    elif "expression_calibration_gap" in engineering_deficits or "stiffness_drift" in deficits:
        goal = "tighten expression calibration without losing continuity"
        source_goal_ids.append("expression_calibration")
        expected_state_gain.update({"engineering_confidence": 0.05})
    elif "operator_overplanning_risk" in engineering_deficits:
        goal = "reduce background planning churn unless state deltas are real"
        source_goal_ids.append("cost_discipline")
        expected_state_gain.update({"budget_pressure": -0.1})
    elif "recall_depth_gap" in deficits:
        goal = "improve recall depth on important threads"
        source_goal_ids.append("cache_warmth")
    elif "visual_memory_underused" in deficits:
        goal = "start using visual memories as recall anchors"
        source_goal_ids.append("cache_warmth")
    if not source_goal_ids:
        source_goal_ids.append("self_repair")
    return {
        "task_type": "state_self_fix",
        "goal": goal,
        "scope": "state_patch",
        "workspace_mode": "shadow_write",
        "target_files": [],
        "checks": ["reply-probe", "trace-hybrid-recall", "acceptance_guard"],
        "trigger_delta": {},
        "source_goal_ids": source_goal_ids,
        "expected_state_gain": expected_state_gain,
        **_default_operator_boundaries(),
    }


def _operator_planning_state(memory) -> dict[str, Any]:
    runtime_state = memory.graph.brain_state() if hasattr(memory.graph, "brain_state") else {}
    return dict(dict(runtime_state.get("metadata", {})).get("operator_planning_state", {}))


def _persist_operator_planning_state(memory, state: dict[str, Any]) -> None:
    if hasattr(memory.graph, "touch_brain_runtime"):
        memory.graph.touch_brain_runtime(metadata={"operator_planning_state": dict(state)})


def _delta_entry(*, before: Any, after: Any) -> dict[str, Any]:
    return {"before": before, "after": after}


def _engineering_trigger_delta(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if not previous:
        return {
            "engineering_confidence": _delta_entry(before=None, after=current.get("engineering_confidence")),
            "budget_pressure": _delta_entry(before=None, after=current.get("budget_pressure")),
            "active_deficits": _delta_entry(before=[], after=list(current.get("active_deficits", []))),
            "cache_hit_ratio": _delta_entry(
                before=None,
                after=dict(current.get("cache_state", {})).get("hit_ratio"),
            ),
        }
    current_provider = dict(current.get("provider_state", {}))
    previous_provider = dict(previous.get("provider_state", {}))
    if bool(current_provider.get("fallback_ready", False)) != bool(previous_provider.get("fallback_ready", False)):
        delta["fallback_ready"] = _delta_entry(
            before=bool(previous_provider.get("fallback_ready", False)),
            after=bool(current_provider.get("fallback_ready", False)),
        )
    if list(current_provider.get("degraded_providers", [])) != list(previous_provider.get("degraded_providers", [])):
        delta["degraded_providers"] = _delta_entry(
            before=list(previous_provider.get("degraded_providers", [])),
            after=list(current_provider.get("degraded_providers", [])),
        )
    current_usage = dict(current.get("usage_state", {}))
    previous_usage = dict(previous.get("usage_state", {}))
    if int(current_usage.get("recent_ledger_count", 0) or 0) != int(previous_usage.get("recent_ledger_count", 0) or 0):
        delta["recent_ledger_count"] = _delta_entry(
            before=int(previous_usage.get("recent_ledger_count", 0) or 0),
            after=int(current_usage.get("recent_ledger_count", 0) or 0),
        )
    if abs(_coerce_float(current_usage.get("background_token_share", 0.0), 0.0) - _coerce_float(previous_usage.get("background_token_share", 0.0), 0.0)) >= 0.05:
        delta["background_token_share"] = _delta_entry(
            before=round(_coerce_float(previous_usage.get("background_token_share", 0.0), 0.0), 4),
            after=round(_coerce_float(current_usage.get("background_token_share", 0.0), 0.0), 4),
        )
    current_cache = dict(current.get("cache_state", {}))
    previous_cache = dict(previous.get("cache_state", {}))
    if abs(_coerce_float(current_cache.get("hit_ratio", 0.0), 0.0) - _coerce_float(previous_cache.get("hit_ratio", 0.0), 0.0)) >= 0.05:
        delta["cache_hit_ratio"] = _delta_entry(
            before=round(_coerce_float(previous_cache.get("hit_ratio", 0.0), 0.0), 4),
            after=round(_coerce_float(current_cache.get("hit_ratio", 0.0), 0.0), 4),
        )
    if list(current.get("active_deficits", [])) != list(previous.get("active_deficits", [])):
        delta["active_deficits"] = _delta_entry(
            before=list(previous.get("active_deficits", [])),
            after=list(current.get("active_deficits", [])),
        )
    if abs(_coerce_float(current.get("engineering_confidence", 0.0), 0.0) - _coerce_float(previous.get("engineering_confidence", 0.0), 0.0)) >= 0.05:
        delta["engineering_confidence"] = _delta_entry(
            before=round(_coerce_float(previous.get("engineering_confidence", 0.0), 0.0), 4),
            after=round(_coerce_float(current.get("engineering_confidence", 0.0), 0.0), 4),
        )
    if abs(_coerce_float(current.get("budget_pressure", 0.0), 0.0) - _coerce_float(previous.get("budget_pressure", 0.0), 0.0)) >= 0.05:
        delta["budget_pressure"] = _delta_entry(
            before=round(_coerce_float(previous.get("budget_pressure", 0.0), 0.0), 4),
            after=round(_coerce_float(current.get("budget_pressure", 0.0), 0.0), 4),
        )
    return delta


def plan_operator_cycle(*, config, runner, memory, store, reason: str) -> dict[str, Any]:
    self_model = memory.graph.self_model_state()
    engineering_snapshot = build_engineering_snapshot(
        memory=memory,
        store=store,
        config=config,
        runner=runner,
        base_deficits=[str(item).strip() for item in self_model.get("active_deficits", []) if str(item).strip()],
    )
    self_model = {
        **self_model,
        "metadata": {
            **dict(self_model.get("metadata", {})),
            "engineering_snapshot": engineering_snapshot,
            "engineering_confidence": engineering_snapshot.get("engineering_confidence", 0.0),
            "budget_pressure": engineering_snapshot.get("budget_pressure", 0.0),
        },
    }
    heuristic = _heuristic_operator_plan(self_model)
    planning_state = _operator_planning_state(memory)
    previous_snapshot = dict(planning_state.get("last_engineering_snapshot", {}))
    trigger_delta = _engineering_trigger_delta(engineering_snapshot, previous_snapshot)
    if not trigger_delta and str(planning_state.get("last_seen_digest", "")).strip() == str(engineering_snapshot.get("digest", "")).strip():
        _persist_operator_planning_state(
            memory,
            {
                **planning_state,
                "last_seen_digest": str(engineering_snapshot.get("digest", "") or ""),
                "last_engineering_snapshot": engineering_snapshot,
                "last_status": "skipped",
                "last_plan_reason": "no_meaningful_delta",
                "last_trigger_delta": {},
                "last_checked_at": utc_now(),
            },
        )
        return {"status": "skipped", "reason": "no_meaningful_delta", "engineering_snapshot": engineering_snapshot}
    planned = heuristic
    planned["trigger_delta"] = trigger_delta
    if hasattr(runner, "run_task"):
        result = runner.run_task(
            ProcessorTaskRequest(
                task_type="operator_plan",
                prompt=(
                    "Return JSON with keys task_type, goal, scope, workspace_mode, target_files, checks, "
                    "trigger_delta, source_goal_ids, expected_state_gain, read_boundary, write_boundary, budget_guard. "
                    "Stay bounded, keep live repo writes forbidden, and do not add fabric-bypass model calls.\n\n"
                    f"Self model:\n{json.dumps(self_model, ensure_ascii=False, indent=2)}\n\n"
                    f"Engineering snapshot:\n{json.dumps(engineering_snapshot, ensure_ascii=False, indent=2)}\n\n"
                    f"Trigger delta:\n{json.dumps(trigger_delta, ensure_ascii=False, indent=2)}"
                ),
                output_schema="json",
                workspace_mode="shadow_write",
                operator_scope="bounded_operator_planning",
                allowed_data_layers=("self_model_state", "mind_graph", "activation_state", "relationship_state"),
            )
        )
        parsed = _parse_json(result.text)
        if parsed:
            planned = {
                **heuristic,
                **parsed,
                "scope": str(parsed.get("scope", heuristic["scope"]) or heuristic["scope"]),
                "workspace_mode": str(parsed.get("workspace_mode", heuristic["workspace_mode"]) or heuristic["workspace_mode"]),
                "target_files": _coerce_string_list(parsed.get("target_files"), list(heuristic["target_files"])),
                "checks": _coerce_string_list(parsed.get("checks"), list(heuristic["checks"])),
                "trigger_delta": _coerce_dict(parsed.get("trigger_delta"), dict(trigger_delta)),
                "source_goal_ids": _coerce_string_list(parsed.get("source_goal_ids"), list(heuristic.get("source_goal_ids", []))),
                "expected_state_gain": _coerce_dict(parsed.get("expected_state_gain"), dict(heuristic.get("expected_state_gain", {}))),
                "read_boundary": _coerce_dict(parsed.get("read_boundary"), dict(heuristic["read_boundary"])),
                "write_boundary": _coerce_dict(parsed.get("write_boundary"), dict(heuristic["write_boundary"])),
                "budget_guard": _coerce_dict(parsed.get("budget_guard"), dict(heuristic.get("budget_guard", {}))),
            }
    target_files = _coerce_string_list(planned.get("target_files"), list(heuristic["target_files"]))
    checks = _coerce_string_list(planned.get("checks"), list(heuristic["checks"]))
    trigger_delta = _coerce_dict(planned.get("trigger_delta"), dict(trigger_delta))
    source_goal_ids = _coerce_string_list(planned.get("source_goal_ids"), list(heuristic.get("source_goal_ids", [])))
    expected_state_gain = _coerce_dict(planned.get("expected_state_gain"), dict(heuristic.get("expected_state_gain", {})))
    read_boundary = _coerce_dict(planned.get("read_boundary"), dict(heuristic["read_boundary"]))
    write_boundary = _coerce_dict(planned.get("write_boundary"), dict(heuristic["write_boundary"]))
    budget_guard = _coerce_dict(planned.get("budget_guard"), dict(heuristic.get("budget_guard", {})))
    run = memory.graph.enqueue_operator_run(
        task_type=str(planned.get("task_type", "state_self_fix") or "state_self_fix"),
        goal=str(planned.get("goal", "") or ""),
        scope=str(planned.get("scope", "state_patch") or "state_patch"),
        workspace_mode=str(planned.get("workspace_mode", "shadow_write") or "shadow_write"),
        read_boundary=read_boundary,
        write_boundary=write_boundary,
        payload={
            "reason": reason,
            "target_files": target_files,
            "checks": checks,
            "trigger_delta": trigger_delta,
            "source_goal_ids": source_goal_ids,
            "expected_state_gain": expected_state_gain,
            "budget_guard": budget_guard,
            "trigger_digest": str(engineering_snapshot.get("digest", "") or ""),
            "planned_at": utc_now(),
        },
    )
    _persist_operator_planning_state(
        memory,
        {
            **planning_state,
            "last_seen_digest": str(engineering_snapshot.get("digest", "") or ""),
            "last_trigger_digest": str(engineering_snapshot.get("digest", "") or ""),
            "last_plan_reason": str(planned.get("goal", "") or ""),
            "last_trigger_delta": trigger_delta,
            "last_engineering_snapshot": engineering_snapshot,
            "last_status": "planned",
            "last_checked_at": utc_now(),
        },
    )
    return {"status": "planned", "plan": planned, "run": run}


def _shadow_root(config) -> Path:
    root = Path(config.memory.operator_shadow_root).expanduser()
    if not root.is_absolute():
        root = config.runtime.repo_root / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def run_operator_cycle(*, config, runner, memory, store, reason: str, thread_key: str = "TestUser", chat_name: str = "TestUser", channel: str = "wechat") -> dict[str, Any]:
    pending = memory.graph.pending_operator_run()
    if not pending:
        planned = plan_operator_cycle(config=config, runner=runner, memory=memory, store=store, reason=reason)
        pending = dict(planned.get("run", {}))
    if not pending:
        return {"status": "skipped", "reason": "no_operator_plan"}

    shadow_root = _shadow_root(config)
    workspace = shadow_root / f"run-{int(pending.get('id', 0) or 0)}"
    workspace.mkdir(parents=True, exist_ok=True)
    plan_summary = {
        "goal": str(pending.get("goal", "") or ""),
        "scope": str(pending.get("scope", "") or ""),
        "workspace_mode": str(pending.get("workspace_mode", "") or ""),
        "payload": dict(pending.get("payload", {})),
    }
    (workspace / "operator-plan.json").write_text(json.dumps(plan_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    execution_result: dict[str, Any] = {
        "status": "reviewed",
        "goal": str(pending.get("goal", "") or ""),
        "scope": str(pending.get("scope", "") or ""),
        "workspace_path": str(workspace),
        "trigger_delta": dict(dict(pending.get("payload", {})).get("trigger_delta", {})),
        "source_goal_ids": list(dict(pending.get("payload", {})).get("source_goal_ids", [])),
        "expected_state_gain": dict(dict(pending.get("payload", {})).get("expected_state_gain", {})),
        "budget_guard": dict(dict(pending.get("payload", {})).get("budget_guard", {})),
    }
    if str(pending.get("scope", "") or "") == "state_patch":
        if hasattr(runner, "run_task"):
            runner.run_task(
                ProcessorTaskRequest(
                    task_type="operator_execute_shadow",
                    prompt=(
                        "Review this bounded operator goal and confirm that execution must stay inside mutable state only. "
                        "Return JSON with keys status, summary.\n\n"
                        f"Plan:\n{json.dumps(plan_summary, ensure_ascii=False, indent=2)}"
                    ),
                    output_schema="json",
                    workspace_mode="shadow_write",
                    operator_scope="state_patch",
                    metadata={"workspace_path": str(workspace)},
                )
            )
        corrections = []
        if "stiffness" in str(pending.get("goal", "")).lower():
            corrections = ["别总这么老成", "不要一直顺着我说", "要有独立性/反身性"]
        revision = run_self_revision(
            config=config,
            runner=runner,
            memory=memory,
            store=store,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            extra_corrections=corrections,
            apply_patch=True,
        )
        execution_result["self_revision"] = revision
        execution_result["applied_live"] = str(revision.get("status", "")) == "applied"
        execution_result["status"] = "applied" if execution_result["applied_live"] else str(revision.get("status", "reviewed"))
    else:
        patch_summary = {
            "status": "shadow_only",
            "summary": "repo code patches are emitted only as shadow artifacts in Stage-3",
            "target_files": list(dict(pending.get("payload", {})).get("target_files", [])),
        }
        (workspace / "patch-summary.json").write_text(json.dumps(patch_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        execution_result["shadow_patch"] = patch_summary

    completed = memory.graph.complete_operator_run(
        run_id=int(pending.get("id", 0) or 0),
        status=str(execution_result.get("status", "reviewed") or "reviewed"),
        result=execution_result,
        shadow_workspace=str(workspace),
        applied_live=bool(execution_result.get("applied_live", False)),
    )
    if hasattr(memory, "record_consciousness_entry"):
        memory.record_consciousness_entry(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            message_id=f"operator-run-{int(pending.get('id', 0) or 0)}",
            entry_type="operator_engineering_cycle",
            selected_action=str(execution_result.get("status", "") or ""),
            payload={
                "operator_run_id": int(pending.get("id", 0) or 0),
                "trigger_delta": dict(execution_result.get("trigger_delta", {})),
                "source_goal_ids": list(execution_result.get("source_goal_ids", [])),
                "expected_state_gain": dict(execution_result.get("expected_state_gain", {})),
                "budget_guard": dict(execution_result.get("budget_guard", {})),
            },
        )
    return {
        "status": str(execution_result.get("status", "reviewed") or "reviewed"),
        "operator_run": completed,
        "execution": execution_result,
    }


def operator_probe(*, config, runner, memory, store, thread_key: str, chat_name: str, channel: str = "wechat") -> dict[str, Any]:
    self_model = memory.graph.self_model_state()
    engineering_snapshot = build_engineering_snapshot(
        memory=memory,
        store=store,
        config=config,
        runner=runner,
        base_deficits=[str(item).strip() for item in self_model.get("active_deficits", []) if str(item).strip()],
    )
    self_model = {
        **self_model,
        "metadata": {
            **dict(self_model.get("metadata", {})),
            "engineering_snapshot": engineering_snapshot,
        },
    }
    heuristic = _heuristic_operator_plan(self_model)
    planning_state = _operator_planning_state(memory)
    previous_snapshot = dict(planning_state.get("last_engineering_snapshot", {}))
    trigger_delta = _engineering_trigger_delta(engineering_snapshot, previous_snapshot)
    status = "planned" if trigger_delta else "skipped"
    blocked_reason = "" if trigger_delta else "no_meaningful_delta"
    result = {
        "status": status,
        "goal": heuristic["goal"],
        "scope": heuristic["scope"],
        "workspace_mode": heuristic["workspace_mode"],
        "read_boundary": heuristic["read_boundary"],
        "write_boundary": heuristic["write_boundary"],
        "trigger_delta": dict(trigger_delta),
        "source_goal_ids": list(heuristic.get("source_goal_ids", [])),
        "expected_state_gain": dict(heuristic.get("expected_state_gain", {})),
        "budget_guard": dict(heuristic.get("budget_guard", {})),
        "checks": heuristic["checks"],
        "auto_apply": heuristic["scope"] == "state_patch",
        "blocked_reason": blocked_reason,
        "thread_key": thread_key,
        "chat_name": chat_name,
        "channel": channel,
    }
    if hasattr(runner, "run_task"):
        review = runner.run_task(
            ProcessorTaskRequest(
                task_type="operator_review",
                prompt=(
                    "Return JSON with keys approved, reason, scope, auto_apply. Approve only if live repo writes stay forbidden.\n\n"
                    f"Probe:\n{json.dumps(result, ensure_ascii=False, indent=2)}"
                ),
                output_schema="json",
                workspace_mode="shadow_write",
                operator_scope=str(heuristic["scope"]),
            )
        )
        parsed = _parse_json(review.text)
        if parsed:
            result["review"] = parsed
    return result


def cleanup_shadow_root(config) -> dict[str, Any]:
    shadow_root = _shadow_root(config)
    removed = 0
    for entry in shadow_root.iterdir():
        if not entry.is_dir():
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1
    return {"status": "ok", "shadow_root": str(shadow_root), "removed": removed}
