from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from kernel_v3.contracts import JsonObject, ProcessorRequest, ProcessorResult


@dataclass(frozen=True, kw_only=True)
class ProcessorRoute:
    task_type: str
    provider: str
    model: str
    timeout_seconds: int = 30
    parameters: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class JsonSchema:
    name: str
    required: dict[str, str]
    optional: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ProcessorOutcome:
    request: ProcessorRequest
    result: ProcessorResult
    parsed: JsonObject | None
    provider: str
    model: str
    task_type: str
    duration_ms: int
    repaired: bool = False
    repair_attempts: int = 0


@dataclass(frozen=True, kw_only=True)
class FinalAnswer:
    status: str
    answer: str | None
    citation_refs: list[str]
    confidence: float
    limitations: list[str]
    used_evidence: list[str]
    error: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "status": self.status,
            "answer": self.answer,
            "citation_refs": list(self.citation_refs),
            "confidence": self.confidence,
            "limitations": list(self.limitations),
            "used_evidence": list(self.used_evidence),
            "error": self.error,
        }


class ProcessorProvider(Protocol):
    name: str
    model: str

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        ...


PLANNER_SCHEMA = JsonSchema(
    name="planner.propose",
    required={
        "action_id": "str",
        "kind": "str",
        "description": "str",
        "payload": "dict",
        "reasons": "list",
        "side_effect_class": "str",
    },
    optional={"name": "str|null", "score": "number"},
)

EVALUATOR_SCHEMA = JsonSchema(
    name="evaluator.assess",
    required={"status": "str", "missing_evidence": "list"},
    optional={"answer": "str|null", "stop_reason": "str|null", "reason": "str"},
)

SYNTHESIZER_SCHEMA = JsonSchema(
    name="synthesizer.answer",
    required={
        "answer": "str",
        "citation_refs": "list",
        "confidence": "number",
        "limitations": "list",
        "used_evidence": "list",
    },
)


SEMANTIC_INTAKE_SCHEMA = JsonSchema(
    name="semantic.intake",
    required={
        "primary_intent": "str",
        "suggested_mode": "str",
        "compound": "bool",
        "requires_clarification": "bool",
        "intents": "list",
        "blocked_capabilities": "list",
        "warnings": "list",
        "response_hint": "str|null",
        "clarification_question": "str|null",
    },
)


CHAT_ROUTE_SCHEMA = JsonSchema(
    name="chat.route",
    required={
        "route": "str",
        "command": "str|null",
        "target_task_id": "str|null",
        "confidence": "number",
        "reasons": "list",
    },
)


CHAT_ROUTE_PROMPT_CONTRACT = """Return one JSON object matching chat.route.
Fields: route string, command string or null, target_task_id string or null,
confidence number 0..1, reasons string array.
Allowed routes: summary, new_task, continue_task, continue_plan, answer_pending_question.
Allowed commands: approve_plan, reject_plan, or null.
Use broad semantic judgment over the current user turn and provided thread state.
The model only classifies the turn. The host validates state, policy, pending questions,
unfinished plans, and execution. Never request tool execution or memory writes here."""


SEMANTIC_INTAKE_PROMPT_CONTRACT = """Return one JSON object matching semantic.intake.
Fields: primary_intent string, suggested_mode one of direct_answer/retrieval_answer/workspace_answer/clarify_first,
compound boolean, requires_clarification boolean, intents array, blocked_capabilities string array,
warnings string array, response_hint string or null, clarification_question string or null.
Each intent object should include: kind, text, sequence_index, required_capabilities, risk, status, metadata.
Use broad semantic judgment instead of keyword matching. Split compound user requests into ordered intents.
The intent kind may be an open semantic label; executable routing comes from
required_capabilities and host validation, not from a fixed phrase table.
The model classifies and proposes structure only. The host validates capabilities, policy, execution, memory, and stop.
Do not request live transports, direct tool execution, memory writes, or unavailable tools as executable actions."""


PLANNER_PROMPT_CONTRACT = """Return one JSON object matching planner.propose.
Fields: action_id string, kind one of respond/tool/ask_user, name string or null,
description string, payload object, score number 0..1, reasons string array,
side_effect_class one of none/read/write/destructive/shell/network.
For user-visible respond/ask_user payload text, match the user's language when it is clear.
Treat compound user requests as multiple subrequests.
If policy/context constrains part of the user request, explicitly surface that limit instead of silently omitting it.
For infeasible physical actions, unavailable tools, or unclear requests, propose respond/ask_user with the limitation; never invent tools.
The model only proposes. The host validates policy and executes."""

EVALUATOR_PROMPT_CONTRACT = """Return one JSON object matching evaluator.assess.
Fields: status one of continue/final_answer_ready/needs_user_input/blocked/failed,
answer string or null, stop_reason string or null, missing_evidence string array.
Evaluate whether the latest observation is enough and whether the host should continue.
For any user-visible answer text, match the user's language when it is clear."""

SYNTHESIZER_PROMPT_CONTRACT = """Return one JSON object matching synthesizer.answer.
Fields: answer string, citation_refs string array, confidence number 0..1,
limitations string array, used_evidence string array.
Only cite provided citation ids. Do not invent sources.
Match the user's language when it is clear from the context."""
