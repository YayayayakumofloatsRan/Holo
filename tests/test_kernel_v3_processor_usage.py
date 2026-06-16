import json

from kernel_v3.chat.console import processor_usage_tail
from kernel_v3.contracts import ContextBundle, Observation
from kernel_v3.agent.semantics import _semantic_prompt
from kernel_v3.capabilities import compact_semantic_capability_catalog
from kernel_v3.processors.adapters import _evaluator_prompt, _planner_prompt
from kernel_v3.processors.contracts import FINANCE_SLOT_BIND_SCHEMA
from kernel_v3.processors.fabric import _normalize_processor_json_for_schema, validate_json_schema
from kernel_v3.processors.usage import aggregate_processor_usage_by_task_type, coerce_usage, summarize_processor_usage


def test_coerce_usage_preserves_deepseek_prompt_cache_counters() -> None:
    usage = coerce_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 64,
            "prompt_cache_miss_tokens": 36,
        }
    )

    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 20
    assert usage["total_tokens"] == 120
    assert usage["estimated"] is False
    assert usage["prompt_cache_hit_tokens"] == 64
    assert usage["prompt_cache_miss_tokens"] == 36
    assert usage["prompt_cache_hit_ratio"] == 0.64


def test_coerce_usage_normalizes_openai_style_cached_prompt_tokens() -> None:
    usage = coerce_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "total_tokens": 1050,
            "prompt_tokens_details": {"cached_tokens": 768},
        }
    )

    assert usage["prompt_cache_hit_tokens"] == 768
    assert usage["prompt_cache_miss_tokens"] == 232
    assert usage["prompt_cache_hit_ratio"] == 0.768


def test_coerce_usage_normalizes_compatible_input_token_cache_read() -> None:
    usage = coerce_usage(
        {
            "prompt_tokens": 400,
            "completion_tokens": 25,
            "input_token_details": {"cache_read": 300},
        }
    )

    assert usage["total_tokens"] == 425
    assert usage["prompt_cache_hit_tokens"] == 300
    assert usage["prompt_cache_miss_tokens"] == 100
    assert usage["prompt_cache_hit_ratio"] == 0.75


def test_processor_usage_tail_shows_prompt_cache_ratio() -> None:
    tail = processor_usage_tail(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 64,
            "prompt_cache_miss_tokens": 36,
        }
    )

    assert "tokens=120" in tail
    assert "cache_hit=64" in tail
    assert "cache_miss=36" in tail
    assert "cache_ratio=64.0%" in tail


def test_processor_usage_summary_groups_cache_by_task_type_and_provider_model() -> None:
    summary = summarize_processor_usage(
        [
            {
                "task_type": "task.compile",
                "provider": "deepseek",
                "model": "deepseek-reasoner",
                "status": "ok",
                "duration_ms": 1200,
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_cache_hit_tokens": 80,
                    "prompt_cache_miss_tokens": 20,
                },
            },
            {
                "task_type": "finance.slot_bind",
                "provider": "deepseek",
                "model": "deepseek-reasoner",
                "status": "failed",
                "error": "missing_required_field:formula_requests",
                "duration_ms": 800,
                "usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                    "prompt_cache_hit_tokens": 20,
                    "prompt_cache_miss_tokens": 30,
                },
            },
        ]
    )

    assert summary["call_count"] == 2
    assert summary["ok_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["total_tokens"] == 180
    assert summary["prompt_cache_hit_tokens"] == 100
    assert summary["prompt_cache_miss_tokens"] == 50
    assert summary["prompt_cache_hit_ratio"] == 0.666667
    assert summary["duration_ms"] == 2000
    assert summary["average_duration_ms"] == 1000
    assert summary["by_task_type"]["finance.slot_bind"]["failed_count"] == 1
    assert summary["by_task_type"]["finance.slot_bind"]["error_counts"] == {
        "missing_required_field:formula_requests": 1
    }
    assert summary["by_provider_model"]["deepseek/deepseek-reasoner"]["call_count"] == 2


def test_aggregate_processor_usage_by_task_type_merges_cache_buckets() -> None:
    merged = aggregate_processor_usage_by_task_type(
        [
            {
                "processor_usage_by_task_type": {
                    "task.compile": {
                        "call_count": 1,
                        "ok_count": 1,
                        "prompt_cache_hit_tokens": 80,
                        "prompt_cache_miss_tokens": 20,
                        "total_tokens": 120,
                    }
                }
            },
            {
                "processor_usage_by_task_type": {
                    "task.compile": {
                        "call_count": 1,
                        "failed_count": 1,
                        "prompt_cache_hit_tokens": 20,
                        "prompt_cache_miss_tokens": 80,
                        "total_tokens": 140,
                        "error_counts": {"json_invalid": 1},
                    },
                    "synthesizer.answer": {
                        "call_count": 1,
                        "ok_count": 1,
                        "prompt_cache_hit_tokens": 90,
                        "prompt_cache_miss_tokens": 10,
                        "total_tokens": 130,
                    },
                }
            },
        ]
    )

    assert merged["task.compile"]["call_count"] == 2
    assert merged["task.compile"]["ok_count"] == 1
    assert merged["task.compile"]["failed_count"] == 1
    assert merged["task.compile"]["prompt_cache_hit_tokens"] == 100
    assert merged["task.compile"]["prompt_cache_miss_tokens"] == 100
    assert merged["task.compile"]["prompt_cache_hit_ratio"] == 0.5
    assert merged["task.compile"]["error_counts"] == {"json_invalid": 1}
    assert merged["synthesizer.answer"]["prompt_cache_hit_ratio"] == 0.9


def test_finance_slot_bind_schema_normalizes_model_interface_variants() -> None:
    parsed = _normalize_processor_json_for_schema(
        {
            "decision": "ready",
            "slot_bindings": [{"slot_name": "hd_cogs", "fact_id": "fact-1"}],
            "calculations": [
                {
                    "formula_name": "dio_hd",
                    "expression": "(inventory_begin + inventory_end) / 2 / cogs * fiscal_days",
                    "variables": {"cogs": {"fact_id": "fact-1"}},
                }
            ],
            "next_action": "respond",
        },
        FINANCE_SLOT_BIND_SCHEMA,
    )

    assert validate_json_schema(parsed, FINANCE_SLOT_BIND_SCHEMA) is None
    assert parsed["formula_requests"][0]["formula_name"] == "dio_hd"
    assert parsed["next_action"] == {"tool": "respond", "reason": ""}


def test_processor_prompt_keeps_stable_contract_before_dynamic_context() -> None:
    context = ContextBundle(
        context_id="ctx-dynamic-1",
        thread_key="thread-dynamic",
        event_ids=["evt-dynamic-1"],
        memory_refs=[],
        state={
            "task_id": "task-dynamic-1",
            "run_id": "run-dynamic-1",
            "input_text": "Summarize this task.",
        },
        token_budget=4096,
    )

    prompt = _planner_prompt(context, None)

    assert prompt.index('"contract"') < prompt.index('"context"')
    assert ',"context":' in prompt
    payload = json.loads(prompt)
    assert payload["context"]["context_id"] == "ctx-dynamic-1"


def test_evaluator_prompt_keeps_stable_contract_before_dynamic_observation() -> None:
    context = ContextBundle(
        context_id="ctx-eval-cache",
        thread_key="thread-eval-cache",
        event_ids=["evt-eval-cache"],
        memory_refs=[],
        state={"task_id": "task-eval-cache", "run_id": "run-eval-cache", "input_text": "Use observation."},
        token_budget=4096,
    )
    observation = Observation(
        observation_id="obs-eval-cache",
        run_id="run-eval-cache",
        kind="tool_result",
        status="ok",
        source="tool:retrieval.run",
        content={"text": "dynamic observation payload"},
        observed_at_ms=0,
        action_id="act-eval-cache",
        tool_call_id=None,
    )

    prompt = _evaluator_prompt(context, observation)

    assert prompt.index('"contract"') < prompt.index('"context"')
    assert prompt.index('"contract"') < prompt.index('"observation"')
    payload = json.loads(prompt)
    assert payload["observation"]["observation_id"] == "obs-eval-cache"


def test_semantic_intake_prompt_uses_compact_capability_catalog_for_cache() -> None:
    prompt = _semantic_prompt(
        "Compare Apple's FY2024 gross margin with Microsoft's FY2024 gross margin.",
        response_language="en",
        runtime_context={},
    )
    payload = json.loads(prompt)
    catalog = payload["host_capability_catalog"]

    assert len(prompt) < 19000
    assert len(json.dumps(catalog, ensure_ascii=False, sort_keys=True)) < 7500
    assert "semantic_slots" not in catalog
    assert "task_domains" not in catalog
    assert "finance.fundamentals_research" in catalog["families"]["finance"]
    assert "finance.verify_numeric" in catalog["families"]["data"]
    assert "retrieval.run" in catalog["families"]["retrieval"]
    assert "calculator.compute" in catalog["families"]["data"]
    assert "system.time" in catalog["families"]["system"]
    assert catalog["executable_tools_by_recipe"]["retrieval_answer"] == [
        "retrieval.run",
        "calculator.compute",
    ]
    assert "domain_profile" in catalog["state_dimensions"]
    assert compact_semantic_capability_catalog()["families"]["finance"] == catalog["families"]["finance"]
    assert prompt.index('"contract"') < prompt.index('"user_goal"')


def test_direct_processor_prompt_uses_lightweight_provider_context() -> None:
    context = ContextBundle(
        context_id="ctx-light-1",
        thread_key="thread-light",
        event_ids=["evt-light-1"],
        memory_refs=[],
        state={
            "task_id": "task-light-1",
            "run_id": "run-light-1",
            "thread_id": "thread-light",
            "input_text": "Hi.",
            "agent_recipe": {
                "recipe_id": "recipe-direct-answer",
                "mode": "direct_answer",
                "allowed_tools": ["memory.recall"],
                "max_steps": 4,
                "max_tool_calls": 2,
                "max_network_fetches": 0,
                "max_total_artifact_bytes": 512000,
                "permission_profile": "read_only",
                "citations_required": False,
                "finalizer": "direct_observation",
                "context_budget_mode": "truncate",
                "metadata": {
                    "semantic_intake": {
                        "primary_intent": "direct_answer",
                        "suggested_mode": "direct_answer",
                        "response_hint": None,
                    },
                    "task_execution_plan": {"large_plan": "PLAN_FILLER" * 200},
                    "answer_profile": {"large_profile": "PROFILE_FILLER" * 200},
                    "research_mission": {"large_mission": "MISSION_FILLER" * 200},
                    "execution_metadata": {},
                },
            },
            "agent_runtime_directive": {
                "mode": "direct_answer",
                "required_outcome": "answer briefly",
                "allowed_tools": ["memory.recall"],
                "answer_profile": {"large_profile": "PROFILE_FILLER" * 200},
                "research_mission": {"large_mission": "MISSION_FILLER" * 200},
                "workmethod": {"large_workmethod": "WORKMETHOD_FILLER" * 200},
            },
            "answer_profile": {"large_profile": "TOP_PROFILE_FILLER" * 200},
            "research_mission": {"large_mission": "TOP_MISSION_FILLER" * 200},
            "workmethod": {"large_workmethod": "TOP_WORKMETHOD_FILLER" * 200},
            "retrieval_capability_state": {"large_state": "RETRIEVAL_STATE_FILLER" * 200},
            "agent_retrieval_plan_state": {"large_plan": "RETRIEVAL_PLAN_FILLER" * 200},
            "agent_replan_hints": {"large_hint": "REPLAN_HINT_FILLER" * 200},
            "capability_catalog": {
                "version": 1,
                "mode": "direct_answer",
                "allowed_tools": ["memory.recall"],
                "executable_tools": ["memory.recall"],
                "families": {"conversation": [], "finance": [], "retrieval": []},
                "capabilities": [
                    {
                        "capability_id": "memory.recall",
                        "family": "memory",
                        "status": "enabled",
                        "tool_name": "memory.recall",
                        "side_effect_class": "read",
                    },
                    {
                        "capability_id": "finance.fundamentals_research",
                        "family": "finance",
                        "status": "planned",
                        "tool_name": "retrieval.run",
                        "side_effect_class": "network",
                        "description": "FINANCE_CAPABILITY_FILLER" * 200,
                    },
                ],
                "host_rule": "CATALOG_RULE_FILLER" * 200,
            },
            "host_situation": {
                "schema": "holo.kernel_v3.host_situation.v1",
                "holo_system": {
                    "name": "Holo Kernel v3",
                    "role": "host_owned_single_agent_harness",
                    "operating_principle": "model_proposes_host_validates_executes_journals_verifies_and_stops",
                    "core_boundaries": ["BOUNDARY_FILLER" * 200],
                },
                "task": {"mode": "direct_answer", "task_id": "task-light-1"},
                "permissions": {
                    "allowed_tools": ["memory.recall"],
                    "allowed_permissions": [],
                    "limits": {"max_steps": 4, "max_tool_calls": 2},
                },
                "tools": {"available_tool_names": ["memory.recall"], "network_tool_names": []},
                "retrieval": {"allowed_by_recipe": False, "configured": False, "reason": "retrieval_tool_not_registered"},
                "runtime_capabilities": {
                    "retrieval": {"available_if_routed": True, "live_search_available": True, "network_access": True},
                    "memory": {"active_memory_recall_available": True},
                    "system": {"system_time_available": True},
                    "workspace": {"workspace_root_configured": True},
                },
                "recent_activity": {"attempted_actions": [], "tool_observations": []},
                "failure": {"diagnosis": "non_retrieval_task_incomplete", "retrieval_attempted": False},
                "user_visible_rules": ["RULE_FILLER" * 200],
            },
            "semantic_state_space": {"large_state_space": "STATE_SPACE_FILLER" * 200},
            "semantic_state_profiles": [{"large_profile": "STATE_PROFILE_FILLER" * 200}],
            "semantic_state_profile_summary": {"domains": ["conversation"], "activities": ["answer"]},
        },
        token_budget=4096,
    )

    prompt = _planner_prompt(context, None)
    provider_state = json.loads(prompt)["context"]["state"]

    assert "semantic_state_space" not in provider_state
    assert "semantic_state_profiles" not in provider_state
    assert "task_execution_plan" not in provider_state["agent_recipe"]["metadata"]
    assert "workmethod" not in provider_state["agent_runtime_directive"]
    assert "answer_profile" not in provider_state
    assert "research_mission" not in provider_state
    assert "workmethod" not in provider_state
    assert "retrieval_capability_state" not in provider_state
    assert "agent_retrieval_plan_state" not in provider_state
    assert "agent_replan_hints" not in provider_state
    assert "finance.fundamentals_research" not in {
        item["capability_id"] for item in provider_state["capability_catalog"]["capabilities"]
    }
    assert provider_state["host_situation"]["runtime_capabilities"]["retrieval"]["available_if_routed"] is True
    assert "RULE_FILLER" not in prompt
    assert "PLAN_FILLER" not in prompt
    assert "STATE_SPACE_FILLER" not in prompt
    assert "FINANCE_CAPABILITY_FILLER" not in prompt
    assert "TOP_PROFILE_FILLER" not in prompt
    assert "RETRIEVAL_STATE_FILLER" not in prompt
    assert len(prompt) < 30000
