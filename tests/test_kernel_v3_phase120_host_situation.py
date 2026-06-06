import json

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import TaskRecipe
from kernel_v3.agent.host_situation import build_host_situation
from kernel_v3.agent.runtime import _compact_thread_rag_context_for_prompt
from kernel_v3.chat import ChatRuntime
from kernel_v3.chat.runtime import _recent_task_trace_context
from kernel_v3.chat.runtime import _failure_answer_text
from kernel_v3.contracts import ToolManifest
from kernel_v3.journal import JournalStore
from kernel_v3.mission.thread_rag import ThreadWorkingMemoryProvider
from kernel_v3.processors.adapters import _synthesizer_prompt
from kernel_v3.retrieval.contracts import RetrievalReport
from kernel_v3.trace import TraceRenderer


def test_phase120_host_situation_distinguishes_live_retrieval_from_quality_failure() -> None:
    journal = JournalStore.in_memory()
    recipe = _retrieval_recipe()
    manifest = _live_retrieval_manifest()
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="action",
        data={"name": "retrieval.run", "payload": {"query": "AAPL fundamentals"}},
    )
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_fetch_attempt",
        data={"source_id": "source-1", "status": "ok", "size_bytes": 1024},
    )
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_report",
        data={"status": "insufficient_evidence", "reason": "missing_citation_refs"},
    )

    situation = build_host_situation(
        journal=journal,
        task_id="task-1",
        run_id="run-1",
        recipe=recipe,
        tool_manifests=[manifest],
        failure_report={
            "reason": "missing_citation_refs",
            "missing_evidence": ["citation_refs"],
            "next_possible_action": "collect_more_evidence",
        },
    )

    assert situation["retrieval"]["configured"] is True
    assert situation["retrieval"]["live_search_available"] is True
    assert situation["retrieval"]["live_fetch_available"] is True
    assert situation["failure"]["failure_is_permission_or_configuration_issue"] is False
    assert situation["failure"]["failure_is_evidence_or_quality_issue"] is True
    assert situation["failure"]["diagnosis"] == "citation_coverage_insufficient"


def test_phase120_failure_answer_uses_host_situation_not_generic_live_permission_claim() -> None:
    situation = {
        "retrieval": {
            "configured": True,
            "live_search_available": True,
            "live_fetch_available": True,
            "network_budget_available": True,
        },
        "failure": {
            "diagnosis": "evidence_extraction_or_coverage_issue",
            "failure_is_permission_or_configuration_issue": False,
        },
    }
    text = _failure_answer_text(
        {
            "reason": "planned_retrieval_subgoals_incomplete",
            "attempted_actions": ["retrieval.run", "retrieval.run"],
            "missing_evidence": ["sufficient_retrieval_evidence"],
            "last_observations": [],
            "next_possible_action": "change_search_strategy",
            "host_situation": situation,
        },
        user_goal="比较 Apple 和 Oracle 基本面",
    )

    assert "不是缺少 live retrieval 权限" in text
    assert "如果你允许 live retrieval" not in text
    assert "配置可用检索源" not in text


def test_phase120_non_retrieval_failure_is_not_reported_as_missing_retrieval_tool() -> None:
    situation = {
        "task": {"mode": "semantic_answer"},
        "retrieval": {"configured": False, "live_search_available": False, "live_fetch_available": False},
        "recent_activity": {
            "latest_processor_error": "deepseek network error: temporary failure in name resolution",
        },
        "failure": {
            "diagnosis": "processor_or_planning_failure",
            "failure_is_permission_or_configuration_issue": False,
        },
    }
    text = _failure_answer_text(
        {
            "reason": "model_planner_processor_failed",
            "attempted_actions": ["ask_user"],
            "missing_evidence": ["planner_action"],
            "last_observations": [],
            "next_possible_action": "retry_model_planner_or_reduce_context",
            "host_situation": situation,
        },
        user_goal="你能做什么？",
    )

    assert "模型/API处理或规划步骤失败" in text
    assert "temporary failure in name resolution" in text
    assert "检索工具或检索源没有配置" not in text
    assert "没有拿到足够证据" not in text


def test_phase120_host_situation_captures_processor_failure_preview() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-processor",
        run_id="run-1",
        step_id=None,
        kind="processor_result",
        data={
            "task_type": "planner.propose",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "status": "failed",
            "error": "RuntimeError",
            "output": {"error_message_preview": "deepseek network error: temporary failure in name resolution"},
        },
    )

    situation = build_host_situation(
        journal=journal,
        task_id="task-processor",
        run_id="run-1",
        recipe=_semantic_recipe(),
        failure_report={"reason": "model_planner_processor_failed", "missing_evidence": ["planner_action"]},
    )

    assert situation["recent_activity"]["failed_processor_results"] == 1
    assert "temporary failure" in situation["recent_activity"]["latest_processor_error"]
    assert situation["failure"]["diagnosis"] == "processor_or_planning_failure"


def test_phase120_host_situation_uses_provider_circuit_previous_error_preview() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-circuit",
        run_id="run-1",
        step_id=None,
        kind="processor_result",
        data={
            "task_type": "planner.propose",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "status": "failed",
            "error": "provider_circuit_open",
            "output": {
                "circuit": "provider_unavailable",
                "previous_error_preview": "deepseek network error: temporary failure in name resolution",
            },
        },
    )

    situation = build_host_situation(
        journal=journal,
        task_id="task-circuit",
        run_id="run-1",
        recipe=_semantic_recipe(),
        failure_report={"reason": "model_planner_processor_failed", "missing_evidence": ["planner_action"]},
    )

    assert "temporary failure" in situation["recent_activity"]["latest_processor_error"]


def test_phase120_synthesizer_prompt_carries_host_situation() -> None:
    host_situation = {
        "schema": "holo.kernel_v3.host_situation.v1",
        "retrieval": {"configured": True, "live_search_available": True},
        "failure": {"diagnosis": "citation_coverage_insufficient"},
    }
    report = RetrievalReport(
        report_id="report-1",
        goal_id="goal-1",
        status="insufficient_evidence",
        query_plan_id="plan-1",
        search_attempt_ids=[],
        fetch_attempt_ids=[],
        evidence_ids=[],
        citation_ids=[],
        evaluation_id="eval-1",
        artifact_refs=[],
        preview="Need more citations.",
        diagnostics={
            "task_goal": "调查 Apple 和 Oracle 基本面",
            "host_situation": host_situation,
        },
    )

    payload = json.loads(_synthesizer_prompt(report, [], []))

    assert payload["host_situation"]["schema"] == "holo.kernel_v3.host_situation.v1"
    assert payload["host_situation"]["retrieval"]["live_search_available"] is True
    assert any("host_situation" in item for item in payload["answer_requirements"])


def test_phase120_agent_runtime_context_result_and_failure_journal_host_situation() -> None:
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run("research AAPL revenue", mode="retrieval")

    context = journal.records(task_id=result.task_id, kind="context")[0].data
    failure_records = journal.records(task_id=result.task_id, kind="agent_failure_report")
    host_records = journal.records(task_id=result.task_id, kind="host_situation")
    assert context["state"]["host_situation"]["schema"] == "holo.kernel_v3.host_situation.v1"
    assert result.host_situation["schema"] == "holo.kernel_v3.host_situation.v1"
    assert result.failure_report is not None
    assert result.failure_report["host_situation"]["schema"] == "holo.kernel_v3.host_situation.v1"
    assert failure_records[-1].data["host_situation"]["schema"] == "holo.kernel_v3.host_situation.v1"
    assert host_records[-1].data["schema"] == "holo.kernel_v3.host_situation.v1"


def test_phase120_agent_runtime_journals_completed_host_situation() -> None:
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run("你是谁？", mode="direct")

    host_records = journal.records(task_id=result.task_id, kind="host_situation")
    assert result.status == "completed"
    assert result.host_situation["schema"] == "holo.kernel_v3.host_situation.v1"
    assert host_records[-1].state_delta["host_situation"] == "completed"
    assert host_records[-1].data["task"]["mode"] == "direct_answer"
    assert host_records[-1].record_id in result.trace_refs

    trace = TraceRenderer(journal).render_task(result.task_id)
    assert "host_situation phase=completed" in trace
    assert "mode=direct_answer" in trace
    assert "host_retrieval configured=" in trace
    assert "host_failure diagnosis=" in trace


def test_phase120_thread_memory_carries_host_situation_into_next_prompt_context() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-host-context",
        run_id="run-1",
        step_id=None,
        kind="host_situation",
        data={
            "schema": "holo.kernel_v3.host_situation.v1",
            "task": {
                "task_id": "task-host-context",
                "run_id": "run-1",
                "thread_id": "thread-host-context",
                "mode": "retrieval_answer",
                "citations_required": True,
            },
            "retrieval": {
                "configured": True,
                "live_search_available": True,
                "live_fetch_available": True,
                "network_budget_available": True,
            },
            "recent_activity": {
                "retrieval_runs": 3,
                "search_attempts": 9,
                "fetch_attempts": 12,
                "successful_fetches": 8,
                "latest_retrieval_status": "insufficient_evidence",
            },
            "failure": {
                "diagnosis": "evidence_extraction_or_coverage_issue",
                "reason": "planned_retrieval_subgoals_incomplete",
                "next_possible_action": "change_search_strategy",
            },
        },
        state_delta={"host_situation": "failure"},
    )

    thread_memory = ThreadWorkingMemoryProvider().compile(
        journal,
        thread_id="thread-host-context",
        task_id="task-host-context",
    )
    prompt_context = _compact_thread_rag_context_for_prompt(thread_memory)
    chat_trace = _recent_task_trace_context(journal, "task-host-context", limit=8)

    rag_host_items = [item for item in thread_memory["recent_task_trace"] if item["kind"] == "host_situation"]
    prompt_host_items = [item for item in prompt_context["recent_task_trace"] if item["kind"] == "host_situation"]
    chat_host_items = [item for item in chat_trace if item["kind"] == "host_situation"]
    assert rag_host_items[-1]["failure_diagnosis"] == "evidence_extraction_or_coverage_issue"
    assert rag_host_items[-1]["retrieval_runs"] == 3
    assert prompt_host_items[-1]["next_possible_action"] == "change_search_strategy"
    assert prompt_host_items[-1]["live_search_available"] is True
    assert chat_host_items[-1]["failure_reason"] == "planned_retrieval_subgoals_incomplete"


def test_phase120_chat_agent_result_persists_host_situation_for_thread_memory() -> None:
    journal = JournalStore.in_memory()
    runtime = ChatRuntime(journal=journal)

    result = runtime.receive("你是谁？", thread_id="thread-chat-host")

    chat_records = journal.records(kind="chat_agent_result")
    thread_memory = ThreadWorkingMemoryProvider().compile(
        journal,
        thread_id="thread-chat-host",
        task_id=result.task_id,
    )
    recent_result_host = thread_memory["recent_results"][-1]["host_situation"]
    assert result.status == "completed"
    assert result.host_situation["schema"] == "holo.kernel_v3.host_situation.v1"
    assert chat_records[-1].data["host_situation"]["schema"] == "holo.kernel_v3.host_situation.v1"
    assert recent_result_host["task_mode"] == "direct_answer"
    assert recent_result_host["retrieval_configured"] is False


def _retrieval_recipe() -> TaskRecipe:
    return TaskRecipe(
        recipe_id="recipe-retrieval",
        allowed_tools=["respond", "retrieval.run"],
        max_steps=64,
        max_tool_calls=64,
        max_network_fetches=1024,
        max_total_artifact_bytes=1_000_000,
        permission_profile="networked",
        citations_required=True,
        finalizer="retrieval",
        context_budget_mode="large",
        mode="retrieval_answer",
        metadata={
            "thread_id": "thread-1",
            "execution_metadata": {"allowed_permissions": ["network:fetch"]},
        },
    )


def _semantic_recipe() -> TaskRecipe:
    return TaskRecipe(
        recipe_id="recipe-semantic",
        allowed_tools=["respond"],
        max_steps=4,
        max_tool_calls=1,
        max_network_fetches=0,
        max_total_artifact_bytes=128_000,
        permission_profile="read_only",
        citations_required=False,
        finalizer="direct",
        context_budget_mode="truncate",
        mode="semantic_answer",
        metadata={"thread_id": "thread-processor"},
    )


def _live_retrieval_manifest() -> ToolManifest:
    return ToolManifest(
        name="retrieval.run",
        version="1",
        resource_kind="retrieval",
        operator_kind="run",
        side_effect_class="network",
        permissions_required=["network:fetch"],
        enabled=True,
        description="Run retrieval.",
        input_schema={
            "_network_access": True,
            "_provider_capabilities": [
                {
                    "provider_id": "live_web_search",
                    "provider_kind": "search",
                    "live_network": True,
                    "profile_aware": True,
                },
                {
                    "provider_id": "http_fetch",
                    "provider_kind": "fetch",
                    "live_network": True,
                    "profile_aware": False,
                },
            ],
        },
    )
