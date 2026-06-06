from __future__ import annotations

from kernel_v3.processors.contracts import JsonSchema


WORKMETHOD_FRAME_SCHEMA = JsonSchema(
    name="workmethod.frame",
    required={},
    optional={
        "work_frame": "dict",
        "work_method": "dict",
        "thread_working_set": "dict",
        "frame": "dict",
        "method": "dict",
        "working_set": "dict",
        "thread_memory": "dict",
        "diagnostics": "dict",
    },
)


WORKMETHOD_GAP_SCHEMA = JsonSchema(
    name="workmethod.gap",
    required={
        "covered": "list",
        "missing": "list",
        "redundant_work": "list",
        "stale_context": "list",
        "wrong_strategy": "list",
        "should_continue": "bool",
        "should_shift_strategy": "bool",
        "should_finalize": "bool",
        "reason": "str",
    },
    optional={"strategy_shift": "dict|null"},
)


WORKMETHOD_FRAME_PROMPT_CONTRACT = """Return one JSON object matching workmethod.frame.
Fields: work_frame dict, work_method dict, thread_working_set dict, optional diagnostics dict.

Think as a reliable human worker, not as a domain template. Decide the way to
work from the user's goal, task plan, available tools, thread context, and
output requirements. The output is a work method packet for the host; it does
not execute tools and does not authorize anything.

work_frame must include:
- user_goal, inferred_goal, work_type, difficulty, risk_level
- expected_output object with format/detail/language when known
- done_criteria string array
- tool_needs string array
- memory_needs string array
- assumptions string array

work_method must include:
- method_name
- first_moves string array
- evidence_strategy string array
- failure_moves string array
- stop_policy string array
- user_interaction_policy string array
- notes string array

thread_working_set must include:
- active_goal
- current_method
- successful_findings string array
- failed_attempts string array
- open_gaps string array
- user_preferences object
- next_intent string or null
- trace_refs string array

Do not ask the user just because the task is broad. Ask only when a critical
target, permission, private boundary, or required output destination is missing.
Do not encode finance/math/physics as fixed scripts. If the task is research,
describe a general research method and let the planner choose concrete actions.
Do not include private chain-of-thought; provide concise public work state.

Return this exact top-level shape; fill the values from the current task:
{
  "work_frame": {
    "user_goal": "...",
    "inferred_goal": "...",
    "work_type": "direct_answer|research|workspace|write|chat",
    "difficulty": "low|medium|high",
    "risk_level": "low|medium|high",
    "expected_output": {"format": "...", "detail": "...", "language": "..."},
    "done_criteria": ["..."],
    "tool_needs": ["..."],
    "memory_needs": ["..."],
    "assumptions": ["..."]
  },
  "work_method": {
    "method_name": "...",
    "first_moves": ["..."],
    "evidence_strategy": ["..."],
    "failure_moves": ["..."],
    "stop_policy": ["..."],
    "user_interaction_policy": ["..."],
    "notes": ["..."]
  },
  "thread_working_set": {
    "active_goal": "...",
    "current_method": "...",
    "successful_findings": [],
    "failed_attempts": [],
    "open_gaps": [],
    "user_preferences": {},
    "next_intent": null,
    "trace_refs": []
  },
  "diagnostics": {"confidence": 0.0}
}"""


WORKMETHOD_GAP_PROMPT_CONTRACT = """Return one JSON object matching workmethod.gap.
Compare the root goal, current work method, latest run delta, and agent result.
Judge like a capable human supervisor:
- What did this run actually cover?
- What remains missing?
- Was work repeated or low-value?
- Is the current strategy stale or wrong?
- Should the next loop continue, shift strategy, finalize, ask user, or stop?

The model only assesses and proposes a strategy shift. The host still validates
policy, repetition, evidence sufficiency, budgets, and termination.

If should_shift_strategy is true, strategy_shift should include:
- shift_reason
- next_method
- avoid_repeating string array
- new_source_families string array
- new_query_moves string array
- new_tool_plan_hint object
- confidence number 0..1

Do not invent evidence, sources, tools, memory writes, or permissions. Do not
require a perfect answer when enough evidence exists and remaining gaps can be
disclosed as limitations. Do not continue repetitive work without a materially
different strategy."""
