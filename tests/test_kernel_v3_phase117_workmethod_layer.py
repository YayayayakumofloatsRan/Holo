from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.answer_profile import infer_answer_profile
from kernel_v3.agent.contracts import AgentRuntimeResult, SemanticIntake, TaskExecutionPlan
from kernel_v3.agent.semantics import analyze_goal
from kernel_v3.agent.taskgraph import build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.mission import MissionSupervisor
from kernel_v3.processors.routing import DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO
from kernel_v3.processors.generation import adapt_generation_parameters
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.workmethod import WorkMethodSupervisor


def test_phase117_workmethod_frames_general_research_without_domain_script() -> None:
    goal = "请调研双曲动力学的前沿研究，写详细中文报告"
    intake = SemanticIntake(
        intake_id="intake-general-research",
        goal=goal,
        primary_intent="frontier_research",
        suggested_mode="retrieval_answer",
        compound=False,
        requires_clarification=False,
        intents=[
            {
                "kind": "frontier_research",
                "text": goal,
                "sequence_index": 1,
                "required_capabilities": ["retrieval.run", "academic.frontier_research"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            }
        ],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )
    task_plan = TaskExecutionPlan(
        plan_id="plan-general-research",
        graph_id="graph-general-research",
        status="ready",
        selected_mode="retrieval_answer",
        steps=[
            {
                "step_id": "step-general-research",
                "sequence_index": 1,
                "goal": goal,
                "tool_name": "retrieval.run",
                "required_capabilities": ["retrieval.run"],
            }
        ],
        blocked_capabilities=[],
        warnings=[],
        approval_required=False,
        confirmation_prompt=None,
    )
    profile = infer_answer_profile(goal, semantic_intake=intake, task_plan=task_plan, response_language="zh")

    state = WorkMethodSupervisor().frame_task(
        goal=goal,
        thread_id="thread-workmethod",
        semantic_intake=intake,
        task_plan=task_plan,
        answer_profile=profile,
        execution_metadata={
            "thread_rag_context": {
                "recent_turns": [],
                "recent_results": [{"answer_preview": "上一轮已经确认需要前沿文献。"}],
            }
        },
    )

    assert state.source == "rule"
    assert state.frame["work_type"] == "research"
    assert "source-backed evidence collected" in state.frame["done_criteria"]
    assert state.method["method_name"] == "goal_directed_research"
    assert any("Change source family" in item for item in state.method["failure_moves"])
    assert state.thread_working_set["successful_findings"]


def test_phase117_model_workmethod_packet_overrides_method_shape_without_fixed_answer() -> None:
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "workmethod.frame": {
                "work_frame": {
                    "work_type": "frontier_research",
                    "difficulty": "high",
                    "risk_level": "low",
                    "done_criteria": ["map schools of thought", "cite source families"],
                    "tool_needs": ["retrieval.run"],
                    "memory_needs": ["thread.working_set"],
                },
                "work_method": {
                    "method_name": "literature_scout_then_gap_map",
                    "first_moves": ["identify authoritative indices"],
                    "evidence_strategy": ["compare recent papers and surveys"],
                    "failure_moves": ["switch index or query language"],
                    "stop_policy": ["stop when frontier themes and limits are covered"],
                    "user_interaction_policy": ["ask only for scope or permission"],
                },
                "thread_working_set": {
                    "active_goal": "arbitrary hard research task",
                    "current_method": "literature_scout_then_gap_map",
                    "successful_findings": [],
                    "failed_attempts": [],
                    "open_gaps": ["source family"],
                    "user_preferences": {},
                    "next_intent": None,
                    "trace_refs": [],
                },
            }
        },
        journal=journal,
    )
    goal = "调查一个任意新兴数学领域"
    intake = analyze_goal(goal)
    task_graph = task_graph_from_semantic(intake)
    task_plan = build_task_execution_plan(task_graph, validate_task_graph(task_graph))
    profile = infer_answer_profile(goal, semantic_intake=intake, task_plan=task_plan, response_language="zh")

    state = WorkMethodSupervisor(processor_fabric=fabric, mode="model").frame_task(
        goal=goal,
        thread_id="thread-model-workmethod",
        semantic_intake=intake,
        task_plan=task_plan,
        answer_profile=profile,
        execution_metadata={},
        task_id="task-wm",
        run_id="run-wm",
    )

    assert state.source == "model"
    assert state.method["method_name"] == "literature_scout_then_gap_map"
    assert state.frame["work_type"] == "frontier_research"
    assert journal.records(task_id="task-wm", kind="processor_request")
    assert journal.records(task_id="task-wm", kind="processor_result")


def test_phase117_workmethod_accepts_alias_sections_with_shape_diagnostics() -> None:
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "workmethod.frame": {
                "frame": {
                    "work_type": "research",
                    "difficulty": "medium",
                    "risk_level": "low",
                    "done_criteria": ["answer with sources"],
                },
                "method": {
                    "method_name": "alias_method",
                    "first_moves": ["inspect context"],
                    "evidence_strategy": ["cite known observations"],
                    "failure_moves": ["change source family"],
                    "stop_policy": ["stop when done criteria are covered"],
                    "user_interaction_policy": ["ask only for missing target"],
                },
                "working_set": {
                    "active_goal": "alias goal",
                    "current_method": "alias_method",
                    "successful_findings": [],
                    "failed_attempts": [],
                    "open_gaps": [],
                    "user_preferences": {},
                    "next_intent": None,
                    "trace_refs": [],
                },
            }
        },
        journal=journal,
    )
    goal = "做一个研究任务"
    intake = analyze_goal(goal)
    task_graph = task_graph_from_semantic(intake)
    task_plan = build_task_execution_plan(task_graph, validate_task_graph(task_graph))
    profile = infer_answer_profile(goal, semantic_intake=intake, task_plan=task_plan, response_language="zh")

    state = WorkMethodSupervisor(processor_fabric=fabric, mode="model").frame_task(
        goal=goal,
        thread_id="thread-alias-workmethod",
        semantic_intake=intake,
        task_plan=task_plan,
        answer_profile=profile,
        execution_metadata={},
        task_id="task-wm-alias",
        run_id="run-wm-alias",
    )

    assert state.source == "model"
    assert state.method["method_name"] == "alias_method"
    assert state.diagnostics["model_status"] == "ok"
    assert set(state.diagnostics["accepted_alias_sections"]) == {"frame", "method", "working_set"}


def test_phase117_agent_runtime_journals_workmethod_and_context_receives_it() -> None:
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(journal=journal, artifact_store=ArtifactStore.in_memory())

    result = runtime.run("解释一下什么是工作方法层", mode="direct")

    assert result.status == "completed"
    work_states = journal.records(task_id=result.task_id, kind="workmethod_state")
    assert work_states
    contexts = [
        record.data
        for record in journal.records(task_id=result.task_id, kind="context")
        if record.run_id == result.run_id
    ]
    assert contexts
    assert any("workmethod" in record.get("state", {}) for record in contexts)


def test_phase117_mission_assessment_journals_strategy_shift_for_stalled_work() -> None:
    journal = JournalStore.in_memory()
    mission = MissionSupervisor(journal=journal).start(
        root_goal="调查一个小众组织的规模和运作方式",
        thread_id="thread-mission",
        metadata={},
    )
    journal.append(
        task_id="task-stalled",
        run_id="run-1",
        step_id=None,
        kind="retrieval_report",
        data={
            "report_id": "report-stalled-1",
            "status": "insufficient_evidence",
            "diagnostics": {
                "goal_query": "niche organization size operations",
                "search_summaries": [
                    {"query": "niche organization size operations", "status": "empty", "source_count": 0}
                ],
            },
        },
    )
    result = AgentRuntimeResult(
        status="failed",
        task_id="task-stalled",
        run_id="run-1",
        mode="retrieval_answer",
        recipe_id="recipe-retrieval-answer",
        final_answer=None,
        failure_report={
            "reason": "insufficient_evidence",
            "missing_evidence": ["scale", "operations"],
            "next_possible_action": "refine_query_or_add_sources",
        },
        trace_refs=[],
    )

    _updated, assessment = MissionSupervisor(journal=journal).assess(mission, result, index=1)

    assert assessment.decision == "continue"
    assert assessment.next_directive is not None
    assert assessment.next_directive["metadata"]["strategy_shift"]["new_query_moves"]
    assert journal.records(task_id="task-stalled", kind="work_gap_assessment")
    assert journal.records(task_id="task-stalled", kind="strategy_shift")


def test_phase117_auto_generation_can_upshift_workmethod_only_for_hard_replan() -> None:
    routine = adapt_generation_parameters(
        task_type="workmethod.frame",
        prompt="routine status\n" + ("x" * 1_000),
        parameters={
            "provider": "deepseek",
            "model": DEEPSEEK_V4_FLASH,
            "generation_mode": "auto",
            "latency_target": "balanced",
        },
    )
    assert routine["model"] == DEEPSEEK_V4_FLASH
    assert routine["thinking"] == "disabled"

    replan = adapt_generation_parameters(
        task_type="workmethod.gap",
        prompt='{"agent_replan_hints":{"status":"needs_replan"},"wrong_strategy":["source_authority_gap"]}',
        parameters={
            "provider": "deepseek",
            "model": DEEPSEEK_V4_FLASH,
            "generation_mode": "auto",
            "latency_target": "balanced",
        },
    )
    assert replan["model"] == DEEPSEEK_V4_PRO
    assert replan["thinking"] == "enabled"


def test_phase117_mission_supervisor_does_not_block_host_accepted_final_answer_with_model_gap() -> None:
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "mission.assess": {
                "decision": "continue",
                "coverage_score": 0.1,
                "covered_requirements": [],
                "missing_requirements": ["should_not_be_called"],
                "unsupported_claims": [],
                "next_directive": {"strategy": "should_not_be_called"},
                "confidence": 0.1,
                "reason_summary": "should_not_be_called",
            },
            "workmethod.gap": {
                "covered": [],
                "missing": ["should_not_be_called"],
                "redundant_work": [],
                "stale_context": [],
                "wrong_strategy": [],
                "should_continue": True,
                "should_shift_strategy": True,
                "should_finalize": False,
                "reason": "should_not_be_called",
            },
        },
        journal=journal,
    )
    mission = MissionSupervisor(
        journal=journal,
        processor_fabric=fabric,
        assessor_mode="model",
    ).start(root_goal="解释你的能力", thread_id="thread-final-skip", metadata={})
    result = AgentRuntimeResult(
        status="completed",
        task_id="task-final-skip",
        run_id="run-1",
        mode="direct_answer",
        recipe_id="recipe-direct-answer",
        final_answer={
            "answer": "我可以在主机控制下规划、调用工具、记录证据并给出回答。",
            "citation_refs": [],
            "used_evidence": [],
            "limitations": [],
            "confidence": 0.8,
        },
        failure_report=None,
        trace_refs=[],
    )

    _updated, assessment = MissionSupervisor(
        journal=journal,
        processor_fabric=fabric,
        assessor_mode="model",
    ).assess(mission, result, index=1)

    assert assessment.decision == "final_answer"
    assert not [
        record
        for record in journal.records(task_id="task-final-skip", kind="processor_request")
        if record.data.get("task_type") in {"mission.assess", "workmethod.gap"}
    ]
