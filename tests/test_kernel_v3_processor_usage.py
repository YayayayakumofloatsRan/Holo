import json

from kernel_v3.chat.console import processor_usage_tail
from kernel_v3.contracts import ContextBundle
from kernel_v3.processors.adapters import _planner_prompt
from kernel_v3.processors.usage import coerce_usage


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
