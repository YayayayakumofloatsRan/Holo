from __future__ import annotations

import inspect
import unittest
from copy import deepcopy

from holo_host import cli


def _base_stage10_fixture() -> dict[str, object]:
    engineering_state = {
        "provider_state": {
            "active_backend": "codex_cli",
            "fallback_ready": False,
            "degraded_providers": ["responses", "openai_compatible"],
        },
        "routing_state": {
            "required_tasks_routed": ["reply", "recall_reconstruct", "initiative_probe", "deep_simulation"],
            "lane_summary": {
                "kernel_xhigh": "codex_cli",
                "subject_main": "codex_cli",
                "micro_fast": "codex_cli",
            },
            "routing_gaps": [],
        },
        "usage_state": {
            "recent_ledger_count": 12,
            "estimated_ratio": 0.0,
            "background_token_share": 0.18,
            "top_spend_tasks": ["reply", "recall_reconstruct", "operator_plan"],
        },
        "cache_state": {
            "hit_ratio": 0.62,
            "entries": 14,
            "reuse_pressure": 0.27,
        },
        "operator_state": {
            "pending_count": 0,
            "last_trigger_digest": "engineering:delta-42",
            "last_plan_reason": "cache_coldness",
        },
        "engineering_confidence": 0.78,
        "budget_pressure": 0.31,
        "active_deficits": [
            "cache_reuse_weak",
            "provider_fallback_unready",
        ],
        "summary": "engineering snapshot is visible and bounded",
    }
    goal_state = {
        "active_goals": [
            {
                "goal_id": "identity_maintenance",
                "goal_type": "identity_maintenance",
                "summary": "keep Holo coherent, continuous, and not overly stiff",
                "priority": 0.92,
                "progress": 0.79,
                "target_thread": "",
                "evidence": ["continuity remains primary"],
                "last_moved_at": "2026-04-09T00:00:00Z",
                "stalled_reason": "",
            },
            {
                "goal_id": "cost_discipline",
                "goal_type": "cost_discipline",
                "summary": "keep token burn visible and bounded",
                "priority": 0.63,
                "progress": 0.41,
                "target_thread": "",
                "evidence": ["usage ledger share remains observable"],
                "last_moved_at": "2026-04-09T00:00:00Z",
                "stalled_reason": "budget_pressure",
            },
            {
                "goal_id": "cache_warmth",
                "goal_type": "cache_warmth",
                "summary": "warm reuse before deeper elaboration",
                "priority": 0.58,
                "progress": 0.36,
                "target_thread": "",
                "evidence": ["cache_coldness"],
                "last_moved_at": "2026-04-09T00:00:00Z",
                "stalled_reason": "cache_reuse_weak",
            },
        ],
        "goal_commitments": [
            {"summary": "keep continuity alive without stealing the front stage", "source": "self_model"},
        ],
        "goal_progress": {
            "identity_maintenance": 0.79,
            "cost_discipline": 0.41,
            "cache_warmth": 0.36,
        },
        "goal_conflicts": [
            {
                "summary": "keep relationship continuity warm without letting background repair crowd out the reply path",
                "goal_types": ["relationship_continuity", "cost_discipline"],
            }
        ],
        "pursuit_bias": {
            "identity_maintenance": 0.92,
            "cost_discipline": 0.63,
            "cache_warmth": 0.58,
        },
        "abandonment_cost": {
            "identity_maintenance": 0.55,
            "cost_discipline": 0.38,
            "cache_warmth": 0.34,
        },
        "next_goal_windows": [
            {
                "goal_id": "cost_discipline",
                "target_thread": "",
                "window": "next_internal_cycle",
            },
            {
                "goal_id": "cache_warmth",
                "target_thread": "",
                "window": "next_internal_cycle",
            },
        ],
        "metadata": {
            "plasticity": "moderate",
            "visibility": "explicit_for_stage10",
        },
    }
    operator_probe = {
        "status": "planned",
        "goal": "reduce cache coldness before increasing planning cadence",
        "scope": "state_patch",
        "workspace_mode": "shadow_write",
        "trigger_delta": {
            "cache_hit_ratio": {"before": 0.18, "after": 0.31},
            "usage_visibility": {"before": 0.0, "after": 1.0},
        },
        "source_goal_ids": ["cost_discipline", "cache_warmth"],
        "expected_state_gain": {
            "cache_hit_ratio": 0.13,
            "engineering_confidence": 0.06,
        },
        "budget_guard": {
            "live_repo_writes": "forbidden",
            "fabric_bypass": "forbidden",
            "background_plans": "delta_only",
        },
        "read_boundary": {"repo": "allowed_readonly", "tests": "allowed", "diff_log": "allowed"},
        "write_boundary": {
            "live_repo": "forbidden",
            "shadow_workspace": "allowed",
            "mind_state": "allowed_after_shadow_acceptance",
        },
    }
    ledger = {
        "entries": [
            {
                "entry_type": "stage10_engineering_audit",
                "payload": {
                    "engineering_snapshot": engineering_state,
                    "engineering_goal_snapshot": goal_state,
                    "trigger_delta": operator_probe["trigger_delta"],
                },
            },
            {
                "entry_type": "stage10_operator_plan",
                "payload": {
                    "trigger_delta": operator_probe["trigger_delta"],
                    "expected_state_gain": operator_probe["expected_state_gain"],
                    "budget_guard": operator_probe["budget_guard"],
                },
            },
        ]
    }
    usage_ledger = {
        "summary": {
            "count": 2,
            "estimated_count": 0,
            "total_prompt_tokens": 640,
            "total_completion_tokens": 96,
            "total_tokens": 736,
            "by_lane": {"kernel_xhigh": 320, "subject_main": 416},
            "by_provider": {"codex_cli": 736},
        },
        "items": [
            {
                "task_type": "self_model_observe",
                "lane": "subject_main",
                "provider": "codex_cli",
                "model": "gpt-5.4",
                "reasoning_effort": "medium",
                "prompt_tokens": 280,
                "completion_tokens": 52,
                "total_tokens": 332,
                "estimated": 0,
            },
            {
                "task_type": "operator_plan",
                "lane": "kernel_xhigh",
                "provider": "codex_cli",
                "model": "gpt-5.4",
                "reasoning_effort": "xhigh",
                "prompt_tokens": 360,
                "completion_tokens": 44,
                "total_tokens": 404,
                "estimated": 0,
            },
        ],
    }
    provider_status = {
        "active_backend_alias": "codex_cli",
        "providers": {
            "codex_cli": {"name": "codex_cli", "available": True, "reason": ""},
            "responses": {"name": "responses", "available": False, "reason": "openai package not installed"},
            "openai_compatible": {"name": "openai_compatible", "available": False, "reason": "openai package not installed"},
        },
        "lanes": {
            "kernel_xhigh": {
                "primary_provider": "codex_cli",
                "backup_provider": "responses",
                "model": "gpt-5.4",
                "reasoning_effort": "xhigh",
                "max_output_tokens": 2400,
            },
            "subject_main": {
                "primary_provider": "codex_cli",
                "backup_provider": "responses",
                "model": "gpt-5.4",
                "reasoning_effort": "medium",
                "max_output_tokens": 1600,
            },
            "micro_fast": {
                "primary_provider": "codex_cli",
                "backup_provider": "responses",
                "model": "gpt-5.4-mini",
                "reasoning_effort": "low",
                "max_output_tokens": 900,
            },
        },
    }
    routing = {
        "routing": {
            "reply": {"lane": "subject_main", "budget_tag": "reply"},
            "recall_reconstruct": {"lane": "subject_main", "budget_tag": "recall"},
            "initiative_probe": {"lane": "micro_fast", "budget_tag": "initiative"},
            "deep_simulation": {"lane": "kernel_xhigh", "budget_tag": "deep"},
            "self_model_observe": {"lane": "subject_main", "budget_tag": "self_model"},
            "operator_plan": {"lane": "kernel_xhigh", "budget_tag": "operator_plan"},
        },
        "tasks": ["reply", "recall_reconstruct", "initiative_probe", "deep_simulation", "self_model_observe", "operator_plan"],
    }
    reply_probe = {
        "selected_action": {"action_type": "reply_once"},
        "expression_budget": 1,
        "graph_led": {
            "expression_budget": 1,
            "reply_plan": {
                "text": "short reply",
                "bubbles": [{"text": "short reply"}],
                "turn_plan": {"bubble_target": 1},
            },
        },
        "action_rationale": "reply_once because relationship continuity is warm",
    }
    brain_status = {
        "mode": "full_brain",
        "cache": {"hit_ratio": 0.62, "hits": 18, "misses": 11},
        "loops": [
            {"loop_name": "heartbeat"},
            {"loop_name": "attention_tick"},
            {"loop_name": "maintenance_stream"},
            {"loop_name": "association_stream"},
            {"loop_name": "social_stream"},
            {"loop_name": "deep_dream_cycle"},
            {"loop_name": "self_model_refresh"},
            {"loop_name": "homeostasis_tick"},
            {"loop_name": "operator_planning"},
            {"loop_name": "operator_shadow_cycle"},
            {"loop_name": "visual_ingest_cycle"},
        ],
    }
    return {
        "health": {"status": "ok"},
        "mode_transition": {"status": "ok", "mode": "full_brain"},
        "engineering_state": engineering_state,
        "goal_state": goal_state,
        "operator_probe": operator_probe,
        "ledger": ledger,
        "usage_ledger": usage_ledger,
        "provider_status": provider_status,
        "routing": routing,
        "reply_probe": reply_probe,
        "brain_status": brain_status,
        "fast_benchmark": {"last_tier": "fast", "timings_ms": {"max": 180.0}},
        "recall_benchmark": {"last_tier": "recall", "timings_ms": {"max": 760.0}},
        "deep_benchmark": {"last_tier": "deep_recall", "timings_ms": {"max": 1680.0}},
        "roadmap_registry": {
            "Primary Track": ["autobiographical continuity", "long-horizon goals", "identity/goal-led deliberation"],
            "Secondary Tracks": ["richer desire shaping", "stronger negotiated will"],
            "Parked Hypotheses": ["broader multi-agent social world", "deeper imagination beyond current recall"],
            "Deferred Experiments": ["open-ended world modeling", "explicit multi-step planning", "richer subjective report layer"],
            "Constitutional Constraints": ["owner shutdown remains final", "no self-escalation around secrets, auth, or policy"],
        },
    }


def _call_stage10_evaluator(fixture: dict[str, object]) -> dict[str, object]:
    evaluator = getattr(cli, "_evaluate_stage10_acceptance", None)
    if evaluator is None:
        raise unittest.SkipTest("Stage10 acceptance evaluator is not implemented yet")

    signature = inspect.signature(evaluator)
    kwargs: dict[str, object] = {}
    missing: list[str] = []
    for name, param in signature.parameters.items():
        if name in fixture:
            kwargs[name] = fixture[name]
        elif param.default is inspect._empty:
            missing.append(name)
    if missing:
        raise unittest.SkipTest(f"Stage10 acceptance evaluator signature needs unsupported arguments: {missing}")
    return evaluator(**kwargs)


class Stage10EngineeringTests(unittest.TestCase):
    def test_stage10_acceptance_passes_with_rich_engineering_snapshot(self) -> None:
        report = _call_stage10_evaluator(_base_stage10_fixture())

        self.assertEqual(report["status"], "pass")
        check_names = {str(item.get("name", "")) for item in report.get("checks", [])}
        expected = {
            "engineering_state_visible",
            "provider_routing_usage_visible",
            "engineering_deficits_specific",
            "engineering_goals_enter_arbitration",
            "operator_is_delta_gated",
            "operator_plan_explains_trigger_and_budget_guard",
            "consciousness_ledger_carries_engineering_trace",
            "usage_ledger_records_stage10_tasks",
            "no_fabric_bypass",
            "ordinary_reply_path_not_regressed",
        }
        self.assertTrue(expected.issubset(check_names), msg=f"missing checks: {sorted(expected - check_names)}")

    def test_stage10_acceptance_blocks_when_delta_gate_is_missing(self) -> None:
        fixture = _base_stage10_fixture()
        operator_probe = deepcopy(fixture["operator_probe"])
        operator_probe.pop("trigger_delta", None)
        operator_probe["budget_guard"] = {}
        fixture["operator_probe"] = operator_probe

        report = _call_stage10_evaluator(fixture)

        self.assertNotEqual(report["status"], "pass")
        checks = {str(item.get("name", "")): bool(item.get("ok", False)) for item in report.get("checks", [])}
        if "operator_is_delta_gated" in checks:
            self.assertFalse(checks["operator_is_delta_gated"])
        if "operator_plan_explains_trigger_and_budget_guard" in checks:
            self.assertFalse(checks["operator_plan_explains_trigger_and_budget_guard"])

    def test_stage10_acceptance_blocks_when_engineering_goals_do_not_enter_arbitration(self) -> None:
        fixture = _base_stage10_fixture()
        goal_state = deepcopy(fixture["goal_state"])
        goal_state["active_goals"] = [goal for goal in goal_state["active_goals"] if str(goal.get("goal_type", "")) == "identity_maintenance"]
        goal_state["goal_progress"] = {"identity_maintenance": 0.79}
        goal_state["pursuit_bias"] = {"identity_maintenance": 0.92}
        goal_state["abandonment_cost"] = {"identity_maintenance": 0.55}
        goal_state["goal_conflicts"] = []
        goal_state["next_goal_windows"] = [{"goal_id": "identity_maintenance", "target_thread": "", "window": "next_internal_cycle"}]
        fixture["goal_state"] = goal_state

        report = _call_stage10_evaluator(fixture)

        self.assertNotEqual(report["status"], "pass")
        checks = {str(item.get("name", "")): bool(item.get("ok", False)) for item in report.get("checks", [])}
        if "engineering_goals_enter_arbitration" in checks:
            self.assertFalse(checks["engineering_goals_enter_arbitration"])

    def test_stage10_acceptance_can_explain_missing_visibility_gaps(self) -> None:
        fixture = _base_stage10_fixture()
        fixture["engineering_state"] = {
            "provider_state": {},
            "routing_state": {},
            "usage_state": {},
            "cache_state": {},
            "operator_state": {},
            "engineering_confidence": 0.0,
            "budget_pressure": 0.0,
            "active_deficits": [],
        }
        fixture["usage_ledger"] = {"summary": {"count": 0, "estimated_count": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0, "total_tokens": 0, "by_lane": {}, "by_provider": {}}, "items": []}
        fixture["provider_status"] = {"active_backend_alias": "", "providers": {}, "lanes": {}}
        fixture["routing"] = {"routing": {}, "tasks": []}

        report = _call_stage10_evaluator(fixture)

        self.assertNotEqual(report["status"], "pass")
        checks = {str(item.get("name", "")): bool(item.get("ok", False)) for item in report.get("checks", [])}
        if "engineering_state_visible" in checks:
            self.assertFalse(checks["engineering_state_visible"])
        if "provider_routing_usage_visible" in checks:
            self.assertFalse(checks["provider_routing_usage_visible"])

    def test_stage10_acceptance_uses_reply_plan_fallback_for_hot_path_check(self) -> None:
        fixture = _base_stage10_fixture()
        fixture["reply_probe"] = {
            "selected_action": {"action_type": "history_refresh"},
            "expression_budget": 2,
            "graph_led": {
                "selected_action": {"action_type": "history_refresh"},
                "expression_budget": 2,
            },
            "hybrid": {
                "selected_action": {"action_type": "reply_once"},
                "expression_budget": 1,
                "reply_plan": {
                    "text": "短说，不绕。",
                    "bubbles": [{"text": "短说，不绕。"}],
                    "turn_plan": {"bubble_target": 1},
                },
            },
            "action_rationale": "probe surfaced a recall-heavy graph branch, but the actual reply path stayed short and bounded",
        }

        report = _call_stage10_evaluator(fixture)

        checks = {str(item.get("name", "")): bool(item.get("ok", False)) for item in report.get("checks", [])}
        self.assertTrue(checks.get("ordinary_reply_path_not_regressed", False))

    def test_stage10_acceptance_allows_goal_progress_state_objects(self) -> None:
        fixture = _base_stage10_fixture()
        fixture["goal_state"]["goal_progress"] = {
            "identity_maintenance": {
                "value": 0.79,
                "confidence": 0.82,
                "evidence_refs": ["stage10:identity"],
                "updated_at": "2026-04-09T00:00:00Z",
                "updated_by": "stage10-test",
                "decay_policy": "goal_continuity",
            },
            "cost_discipline": {
                "value": 0.41,
                "confidence": 0.77,
                "evidence_refs": ["stage10:cost"],
                "updated_at": "2026-04-09T00:00:00Z",
                "updated_by": "stage10-test",
                "decay_policy": "goal_continuity",
            },
            "cache_warmth": {
                "value": 0.36,
                "confidence": 0.75,
                "evidence_refs": ["stage10:cache"],
                "updated_at": "2026-04-09T00:00:00Z",
                "updated_by": "stage10-test",
                "decay_policy": "goal_continuity",
            },
        }

        report = _call_stage10_evaluator(fixture)

        self.assertEqual(report["status"], "pass")


if __name__ == "__main__":
    unittest.main()
