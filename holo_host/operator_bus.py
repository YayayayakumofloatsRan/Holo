from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .brain_ops import filter_self_revision_patch, run_self_revision
from .common import compact_text, utc_now
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


def build_self_model_snapshot(*, memory, store, config) -> dict[str, Any]:
    brain_status = memory.brain_status()
    self_revision_state = memory.graph.latest_self_revision_state()
    stream_status = memory.stream_status()
    vector_health = memory.vector_health()
    top_threads = memory.graph.top_thread_commitments(limit=4)
    mode = str(brain_status.get("mode", config.memory.brain_mode_default) or config.memory.brain_mode_default)
    cache = dict(brain_status.get("cache", {}))
    hit_ratio = float(cache.get("hit_ratio", 0.0) or 0.0)
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
    if hit_ratio < 0.15:
        active_deficits.append("cache_coldness")
    if not top_threads:
        active_deficits.append("relational_commitments_unclear")
    if bool(getattr(config.runtime, "image_enabled", True)):
        visuals = memory.graph.visual_memory(limit=1)
        if not visuals:
            active_deficits.append("visual_memory_underused")
    if not active_deficits:
        active_deficits = list(DEFAULT_ACTIVE_DEFICITS[:1])
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
            "recent_revision": recent_revision,
            "recent_stream_runs": len(list(stream_status.get("recent_runs", []))),
            "observed_at": utc_now(),
        },
    }


def build_homeostasis_state(*, memory, config) -> dict[str, Any]:
    self_model = memory.graph.self_model_state()
    brain_status = memory.brain_status()
    operator_status = memory.graph.operator_status()
    active_deficits = list(self_model.get("active_deficits", []))
    pressure = 0.24 + min(0.32, 0.06 * len(active_deficits))
    if operator_status.get("pending_count", 0):
        pressure += 0.08
    return {
        "pressure": round(min(0.92, pressure), 4),
        "stability": round(max(0.22, float(self_model.get("identity_continuity", 0.6) or 0.6) - pressure * 0.2), 4),
        "targets": dict(self_model.get("homeostasis_targets", {})),
        "active_deficits": active_deficits,
        "brain_mode": str(brain_status.get("mode", config.memory.brain_mode_default) or config.memory.brain_mode_default),
        "operator_pending_count": int(operator_status.get("pending_count", 0) or 0),
        "last_updated_at": utc_now(),
    }


def _self_model_prompt(snapshot: dict[str, Any]) -> str:
    return (
        "Return JSON with keys active_deficits, long_horizon_goals, relational_commitments, homeostasis_targets, summary. "
        "Keep the result bounded and practical.\n\n"
        f"Current snapshot:\n{json.dumps(snapshot, ensure_ascii=False, indent=2)}"
    )


def refresh_self_model(*, config, runner, memory, store, reason: str, source: str = "runtime") -> dict[str, Any]:
    heuristic = build_self_model_snapshot(memory=memory, store=store, config=config)
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
    }


def _heuristic_operator_plan(self_model: dict[str, Any]) -> dict[str, Any]:
    deficits = [str(item).strip() for item in self_model.get("active_deficits", []) if str(item).strip()]
    goal = "stabilize self model"
    if "stiffness_drift" in deficits:
        goal = "loosen persona stiffness without losing continuity"
    elif "recall_depth_gap" in deficits:
        goal = "improve recall depth on important threads"
    elif "visual_memory_underused" in deficits:
        goal = "start using visual memories as recall anchors"
    return {
        "task_type": "state_self_fix",
        "goal": goal,
        "scope": "state_patch",
        "workspace_mode": "shadow_write",
        "target_files": [],
        "checks": ["reply-probe", "trace-hybrid-recall", "acceptance_guard"],
        **_default_operator_boundaries(),
    }


def plan_operator_cycle(*, config, runner, memory, store, reason: str) -> dict[str, Any]:
    self_model = memory.graph.self_model_state()
    heuristic = _heuristic_operator_plan(self_model)
    planned = heuristic
    if hasattr(runner, "run_task"):
        result = runner.run_task(
            ProcessorTaskRequest(
                task_type="operator_plan",
                prompt=(
                    "Return JSON with keys task_type, goal, scope, workspace_mode, target_files, checks, "
                    "read_boundary, write_boundary. Stay bounded and never request live repo writes.\n\n"
                    f"Self model:\n{json.dumps(self_model, ensure_ascii=False, indent=2)}"
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
                "read_boundary": _coerce_dict(parsed.get("read_boundary"), dict(heuristic["read_boundary"])),
                "write_boundary": _coerce_dict(parsed.get("write_boundary"), dict(heuristic["write_boundary"])),
            }
    target_files = _coerce_string_list(planned.get("target_files"), list(heuristic["target_files"]))
    checks = _coerce_string_list(planned.get("checks"), list(heuristic["checks"]))
    read_boundary = _coerce_dict(planned.get("read_boundary"), dict(heuristic["read_boundary"]))
    write_boundary = _coerce_dict(planned.get("write_boundary"), dict(heuristic["write_boundary"]))
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
            "planned_at": utc_now(),
        },
    )
    return {"status": "planned", "plan": planned, "run": run}


def _shadow_root(config) -> Path:
    root = Path(config.memory.operator_shadow_root).expanduser()
    if not root.is_absolute():
        root = config.runtime.repo_root / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def run_operator_cycle(*, config, runner, memory, store, reason: str, thread_key: str = "Nemoqi", chat_name: str = "Nemoqi", channel: str = "wechat") -> dict[str, Any]:
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
    return {
        "status": str(execution_result.get("status", "reviewed") or "reviewed"),
        "operator_run": completed,
        "execution": execution_result,
    }


def operator_probe(*, config, runner, memory, store, thread_key: str, chat_name: str, channel: str = "wechat") -> dict[str, Any]:
    self_model = memory.graph.self_model_state()
    heuristic = _heuristic_operator_plan(self_model)
    result = {
        "goal": heuristic["goal"],
        "scope": heuristic["scope"],
        "workspace_mode": heuristic["workspace_mode"],
        "read_boundary": heuristic["read_boundary"],
        "write_boundary": heuristic["write_boundary"],
        "checks": heuristic["checks"],
        "auto_apply": heuristic["scope"] == "state_patch",
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
