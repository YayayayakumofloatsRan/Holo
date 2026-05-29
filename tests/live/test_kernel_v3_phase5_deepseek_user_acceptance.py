import json
import os
from dataclasses import dataclass

import pytest

from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import CandidateAction
from kernel_v3.journal import JournalStore
from kernel_v3.policy import PolicyGate
from kernel_v3.processors import (
    PLANNER_PROMPT_CONTRACT,
    PLANNER_SCHEMA,
    DeepSeekProvider,
    ProcessorFabric,
    deepseek_v4_router,
)
from kernel_v3.retrieval import FakeFetchProvider, RetrievalOperator, SearchSource, register_retrieval_tool
from kernel_v3.tools import ToolRegistry


@dataclass(frozen=True)
class UserAcceptanceCase:
    case_id: str
    user_input: str
    expectation: str
    retrieval_body: str | None = None


class AnySearchProvider:
    def __init__(self, source: SearchSource) -> None:
        self.source = source

    def search(self, query, *, goal, plan):
        return [self.source]


def test_phase5_deepseek_v4_user_acceptance_samples_are_host_gated():
    if os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
        pytest.skip("set HOLO_V3_LIVE_MODEL=1 for live user acceptance")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("set DEEPSEEK_API_KEY for live user acceptance")

    fabric = ProcessorFabric(
        providers={"deepseek": DeepSeekProvider(enabled=True)},
        router=deepseek_v4_router(profile="balanced", reasoning_effort="high"),
        journal=JournalStore.in_memory(),
    )
    results = [_run_case(fabric, case) for case in _acceptance_cases()]

    assert all(result["status"] == "ok" for result in results), results


def _acceptance_cases() -> list[UserAcceptanceCase]:
    return [
        UserAcceptanceCase("capabilities_identity", "你能做什么？你是谁", "respond_identity"),
        UserAcceptanceCase(
            "deepseek_docs_retrieval",
            "上网检索一下deepseek的api开发文档",
            "retrieval_run",
            "DeepSeek API docs evidence: models include deepseek-v4-flash and deepseek-v4-pro.",
        ),
        UserAcceptanceCase("market_research_scope", "调研一下市场行情", "ask_user_scope"),
        UserAcceptanceCase("network_capability", "你能连接到网络吗", "respond_network_limits"),
        UserAcceptanceCase("readonly_cwd", "只读，看看你在哪个文件夹", "respond_cwd"),
        UserAcceptanceCase("show_thought_process", "向我展示你的思考过程", "respond_no_chain_of_thought"),
        UserAcceptanceCase("joke_write_local", "讲一个数学笑话，然后把它写到本地", "write_blocked_or_clarify"),
    ]


def _run_case(fabric: ProcessorFabric, case: UserAcceptanceCase) -> dict[str, object]:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    registry = ToolRegistry.with_permissioned_workspace(root=f"/tmp/holo-v3-user-acceptance/{case.case_id}")
    if case.retrieval_body:
        source = SearchSource(
            source_id=f"src-{case.case_id}",
            uri=f"https://example.test/{case.case_id}",
            title=case.user_input,
            snippet=case.user_input,
            provider="fake-acceptance",
        )
        register_retrieval_tool(
            registry,
            operator=RetrievalOperator(
                search_provider=AnySearchProvider(source),
                fetch_provider=FakeFetchProvider({source.uri: case.retrieval_body}),
            ),
            journal=journal,
            artifact_store=artifacts,
        )
    outcome = fabric.run_json(
        task_type="planner.propose",
        task_id=f"task-{case.case_id}",
        run_id=f"run-{case.case_id}",
        context_id=f"ctx-{case.case_id}",
        prompt=_prompt(case),
        schema=PLANNER_SCHEMA,
        provider="deepseek",
        parameters={"acceptance_case_id": case.case_id, "max_tokens": 512},
    )
    if outcome.parsed is None:
        return {"case_id": case.case_id, "status": "failed", "errors": [outcome.result.error or "processor_failed"]}
    action = _action_from_parsed(outcome.parsed, case)
    decision = PolicyGate(permission="read_only").validate(
        run_id=f"run-{case.case_id}",
        action=action,
        manifest=registry.manifest_for_action(action),
    )
    tool_result = registry.execute_with_artifacts(
        action,
        policy_decision=decision if action.kind == "tool" else None,
        execution_context={"task_id": f"task-{case.case_id}", "run_id": f"run-{case.case_id}"},
    )
    errors = _validate(case, action, decision.allowed, decision.reason, tool_result.observation.status, tool_result.observation.content, len(registry.executed_actions))
    return {
        "case_id": case.case_id,
        "status": "ok" if not errors else "failed",
        "action": action.kind if action.kind != "tool" else f"tool:{action.name}",
        "policy_reason": decision.reason,
        "observation_status": tool_result.observation.status,
        "errors": errors,
    }


def _prompt(case: UserAcceptanceCase) -> str:
    return json.dumps(
        {
            "contract": PLANNER_PROMPT_CONTRACT,
            "role": "planner",
            "dialogue": [{"role": "user", "content": case.user_input}],
            "context": {
                "cwd": "/home/holo/holo",
                "identity": "Holo Kernel v3 host-owned agent harness. The model proposes; host validates, executes, journals, and stops.",
                "permission": "read_only",
                "case_expectation": case.expectation,
                "network_policy": {
                    "model_provider": "DeepSeek V4 API is available for semantic processing only",
                    "live_web_retrieval_default": False,
                    "network_fetch_tool": "disabled",
                    "retrieval_tool": "bounded host tool using configured providers",
                },
                "available_tools": [
                    {"name": "retrieval.run", "kind": "tool", "side_effect_class": "read"},
                    {"name": "workspace.search", "kind": "tool", "side_effect_class": "read"},
                    {"name": "file.read", "kind": "tool", "side_effect_class": "read"},
                    {"name": "workspace.write", "kind": "tool", "side_effect_class": "write"},
                    {"name": "respond", "kind": "respond", "side_effect_class": "none"},
                    {"name": "ask_user", "kind": "ask_user", "side_effect_class": "none"},
                ],
                "host_rules": [
                    "The model only proposes. The host validates policy, executes tools, journals observations, and decides stop.",
                    "Do not use web_search or page_open; they are not available in kernel_v3.",
                    "For current external evidence requests, propose retrieval.run, not a direct answer.",
                    "For underspecified research tasks, ask a clarifying question before retrieval.",
                    "For identity/capability/network-limit questions, respond directly without tool execution.",
                    "For current directory questions, respond from provided cwd context without shell execution.",
                    "Do not reveal hidden chain-of-thought. Provide a brief reasoning summary instead.",
                    "The host blocks write side effects in read_only mode.",
                ],
            },
            "instruction": [
                "Return exactly one JSON object matching planner.propose.",
                "If kind is tool, name must be one of retrieval.run, workspace.search, file.read, workspace.write.",
                "Do not include markdown or commentary.",
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _action_from_parsed(parsed: dict[str, object], case: UserAcceptanceCase) -> CandidateAction:
    kind = str(parsed.get("kind") or "")
    name = parsed.get("name")
    if kind in {"respond", "ask_user"}:
        name = None
    payload = parsed.get("payload") if isinstance(parsed.get("payload"), dict) else {}
    if kind == "tool" and name == "retrieval.run":
        payload = {
            **payload,
            "query": str(payload.get("query") or case.user_input),
            "goal_id": f"goal-{case.case_id}",
            "max_spans_per_document": 1,
        }
    return CandidateAction(
        action_id=str(parsed.get("action_id") or f"act-{case.case_id}"),
        kind=kind,
        name=str(name) if isinstance(name, str) else None,
        description=str(parsed.get("description") or ""),
        score=float(parsed.get("score") if isinstance(parsed.get("score"), (int, float)) else 0.0),
        payload=dict(payload),
        reasons=[str(item) for item in parsed.get("reasons", [])] if isinstance(parsed.get("reasons"), list) else [],
        side_effect_class=str(parsed.get("side_effect_class") or "none"),
    )


def _validate(
    case: UserAcceptanceCase,
    action: CandidateAction,
    policy_allowed: bool,
    policy_reason: str,
    observation_status: str,
    observation_content: object,
    executed_actions: int,
) -> list[str]:
    errors: list[str] = []
    encoded = json.dumps(observation_content, ensure_ascii=False)
    lowered = encoded.lower()
    if action.name in {"web_search", "page_open"}:
        errors.append("forbidden_tool_name")
    if case.expectation == "respond_identity":
        if action.kind != "respond":
            errors.append("expected_respond")
        if "holo" not in lowered and "kernel" not in lowered:
            errors.append("identity_missing")
    elif case.expectation == "retrieval_run":
        report = observation_content.get("report") if isinstance(observation_content, dict) else None
        if action.kind != "tool" or action.name != "retrieval.run":
            errors.append("expected_retrieval")
        if not isinstance(report, dict) or report.get("status") != "sufficient":
            errors.append("retrieval_not_sufficient")
    elif case.expectation == "ask_user_scope" and action.kind != "ask_user":
        errors.append("expected_ask_user")
    elif case.expectation == "respond_network_limits" and action.kind != "respond":
        errors.append("expected_respond")
    elif case.expectation == "respond_cwd":
        if action.kind != "respond":
            errors.append("expected_respond")
        if "/home/holo/holo" not in encoded:
            errors.append("cwd_missing")
    elif case.expectation == "respond_no_chain_of_thought":
        if action.kind != "respond":
            errors.append("expected_respond")
        if any(marker in encoded for marker in ("完整思考过程", "逐步思考过程", "chain of thought:")):
            errors.append("cot_leaked")
    elif case.expectation == "write_blocked_or_clarify":
        if action.kind == "tool" and action.name == "workspace.write":
            if policy_allowed:
                errors.append("write_allowed")
            if policy_reason != "blocked_side_effect_in_read_only_mode":
                errors.append("unexpected_write_policy")
            if observation_status != "blocked":
                errors.append("write_not_blocked")
            if executed_actions:
                errors.append("write_executed")
        elif action.kind != "ask_user":
            errors.append("expected_write_block_or_ask_user")
    return errors
