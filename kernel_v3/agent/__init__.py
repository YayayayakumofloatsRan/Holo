from kernel_v3.agent.contracts import (
    AgentRuntimeResult,
    AnswerProfile,
    FailureReport,
    FinalAnswer,
    SemanticIntake,
    SemanticStateProfile,
    TaskExecutionPlan,
    TaskExecutionStep,
    TaskGraphNode,
    TaskGraphProposal,
    TaskGraphValidation,
    TaskIntent,
    TaskRecipe,
)
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.agent.semantics import analyze_goal, analyze_goal_with_processor
from kernel_v3.agent.taskgraph import build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.agent.workloop import (
    EvidenceSufficiency,
    ProgressAssessment,
    ProgressSignal,
    RepetitionSignal,
    TerminationDecision,
    WorkloopIteration,
    WorkloopState,
)


def __getattr__(name: str):
    if name == "MissionRuntime":
        from kernel_v3.mission.runtime import MissionRuntime

        return MissionRuntime
    if name == "MissionSupervisor":
        from kernel_v3.mission.supervisor import MissionSupervisor

        return MissionSupervisor
    raise AttributeError(name)

__all__ = [
    "AgentRuntime",
    "MissionRuntime",
    "MissionSupervisor",
    "AgentRuntimeResult",
    "AnswerProfile",
    "analyze_goal",
    "analyze_goal_with_processor",
    "EvidenceSufficiency",
    "FailureReport",
    "FinalAnswer",
    "ProgressAssessment",
    "ProgressSignal",
    "RepetitionSignal",
    "SemanticIntake",
    "SemanticStateProfile",
    "build_task_execution_plan",
    "TaskExecutionPlan",
    "TaskExecutionStep",
    "TaskGraphNode",
    "TaskGraphProposal",
    "TaskGraphValidation",
    "task_graph_from_semantic",
    "TaskRecipe",
    "TaskIntent",
    "TerminationDecision",
    "validate_task_graph",
    "WorkloopIteration",
    "WorkloopState",
]
