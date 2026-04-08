from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .common import utc_now


@dataclass(slots=True)
class IncomingMessage:
    message_id: str
    thread_key: str
    subject: str
    sender_email: str
    body_text: str
    sender_name: str = ""
    reply_to_email: str = ""
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    body_html: str = ""
    received_at: str = field(default_factory=utc_now)
    channel: str = "email"
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def event_id(self) -> str:
        return f"{self.channel}:{self.message_id}"


@dataclass(slots=True)
class OutgoingMessage:
    recipient_email: str
    subject: str
    body_text: str
    thread_key: str
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    recipient_name: str = ""
    body_html: str = ""
    channel: str = "email"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CodexResult:
    reply_text: str
    session_id: str = ""
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProcessorTaskRequest:
    task_type: str
    prompt: str
    session_id: str = ""
    model_override: str = ""
    reasoning_effort_override: str = ""
    timeout_seconds: int | None = None
    output_schema: str = "plain_text"
    allowed_data_layers: tuple[str, ...] = ()
    allow_memory_writeback: bool = False
    image_paths: tuple[str, ...] = ()
    workspace_mode: str = "live_readonly"
    operator_scope: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "prompt": self.prompt,
            "session_id": self.session_id,
            "model_override": self.model_override,
            "reasoning_effort_override": self.reasoning_effort_override,
            "timeout_seconds": self.timeout_seconds,
            "output_schema": self.output_schema,
            "allowed_data_layers": list(self.allowed_data_layers),
            "allow_memory_writeback": self.allow_memory_writeback,
            "image_paths": list(self.image_paths),
            "workspace_mode": self.workspace_mode,
            "operator_scope": self.operator_scope,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ProcessorTaskResult:
    task_type: str
    text: str
    session_id: str = ""
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)
    output_schema: str = "plain_text"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_codex_result(self) -> CodexResult:
        return CodexResult(
            reply_text=self.text,
            session_id=self.session_id,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
            command=list(self.command),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "text": self.text,
            "session_id": self.session_id,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "command": list(self.command),
            "output_schema": self.output_schema,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    priority: int
    risk_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AttentionState:
    primary_focus: str
    secondary_focus: str = ""
    reply_goal: str = ""
    pressure_level: str = "low"
    salience_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_focus": self.primary_focus,
            "secondary_focus": self.secondary_focus,
            "reply_goal": self.reply_goal,
            "pressure_level": self.pressure_level,
            "salience_sources": list(self.salience_sources),
        }


@dataclass(slots=True)
class TurnPlan:
    route: str = "main"
    fast_path: bool = False
    reply_goal: str = ""
    history_window: int = 6
    bubble_target: int = 2
    tool_mode: str = "bounded"
    latency_tier: str = "normal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "fast_path": self.fast_path,
            "reply_goal": self.reply_goal,
            "history_window": self.history_window,
            "bubble_target": self.bubble_target,
            "tool_mode": self.tool_mode,
            "latency_tier": self.latency_tier,
        }


@dataclass(slots=True)
class ReplyBubble:
    text: str
    delay_ms: int = 0
    purpose: str = "reply"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "delay_ms": self.delay_ms,
            "purpose": self.purpose,
        }


@dataclass(slots=True)
class ToolRequest:
    name: str
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "reason": self.reason, "payload": dict(self.payload)}


@dataclass(slots=True)
class TurnContext:
    channel: str
    thread_key: str
    chat_name: str
    sender: str
    user_text: str
    sidecar: dict[str, Any]
    attention_state: AttentionState
    emotion_state: dict[str, Any]
    history: list[dict[str, Any]]
    mind_packet: dict[str, Any] = field(default_factory=dict)
    utterance_plan: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    capability_context: dict[str, Any] = field(default_factory=dict)
    route_hint: str = ""
    persona_blend: dict[str, Any] = field(default_factory=dict)
    brain_state: dict[str, Any] = field(default_factory=dict)
    game_state: dict[str, Any] = field(default_factory=dict)
    stream_influence: dict[str, Any] = field(default_factory=dict)
    self_revision_state: dict[str, Any] = field(default_factory=dict)
    self_model: dict[str, Any] = field(default_factory=dict)
    homeostasis_state: dict[str, Any] = field(default_factory=dict)
    operator_state: dict[str, Any] = field(default_factory=dict)
    visual_memory: dict[str, Any] = field(default_factory=dict)
    affect_state: dict[str, Any] = field(default_factory=dict)
    drive_state: dict[str, Any] = field(default_factory=dict)
    value_state: dict[str, Any] = field(default_factory=dict)
    conflict_state: dict[str, Any] = field(default_factory=dict)
    initiative_candidates: list[dict[str, Any]] = field(default_factory=list)
    resistance_posture: dict[str, Any] = field(default_factory=dict)
    outcome_memory: dict[str, Any] = field(default_factory=dict)
    intent_state: dict[str, Any] = field(default_factory=dict)
    action_market: list[dict[str, Any]] = field(default_factory=list)
    selected_action: dict[str, Any] = field(default_factory=dict)
    expression_budget: int = 0
    silence_reason: str = ""
    defer_reason: str = ""
    action_rationale: str = ""

    def __post_init__(self) -> None:
        if not self.mind_packet:
            self.mind_packet = self.sidecar
        elif not self.sidecar:
            self.sidecar = self.mind_packet
        packet = dict(self.mind_packet or self.sidecar or {})
        if not self.persona_blend:
            self.persona_blend = dict(packet.get("persona_blend", {}))
        if not self.brain_state:
            self.brain_state = dict(packet.get("brain_state", {}))
        if not self.game_state:
            self.game_state = dict(packet.get("game_state", {}))
        if not self.stream_influence:
            self.stream_influence = dict(packet.get("stream_influence", {}))
        if not self.self_revision_state:
            self.self_revision_state = dict(packet.get("self_revision_state", {}))
        if not self.self_model:
            self.self_model = dict(packet.get("self_model", {}))
        if not self.homeostasis_state:
            self.homeostasis_state = dict(packet.get("homeostasis_state", {}))
        if not self.operator_state:
            self.operator_state = dict(packet.get("operator_state", {}))
        if not self.visual_memory:
            self.visual_memory = dict(packet.get("visual_memory", {}))
        if not self.affect_state:
            self.affect_state = dict(packet.get("affect_state", {}))
        if not self.drive_state:
            self.drive_state = dict(packet.get("drive_state", {}))
        if not self.value_state:
            self.value_state = dict(packet.get("value_state", {}))
        if not self.conflict_state:
            self.conflict_state = dict(packet.get("conflict_state", {}))
        if not self.initiative_candidates:
            self.initiative_candidates = list(packet.get("initiative_candidates", []))
        if not self.resistance_posture:
            self.resistance_posture = dict(packet.get("resistance_posture", {}))
        if not self.outcome_memory:
            self.outcome_memory = dict(packet.get("outcome_memory", {}))
        if not self.intent_state:
            self.intent_state = dict(packet.get("intent_state", {}))
        if not self.action_market:
            self.action_market = list(packet.get("action_market", []))
        if not self.selected_action:
            self.selected_action = dict(packet.get("selected_action", {}))
        if not self.expression_budget:
            try:
                self.expression_budget = int(packet.get("expression_budget", 0) or 0)
            except (TypeError, ValueError):
                self.expression_budget = 0
        if not self.silence_reason:
            self.silence_reason = str(packet.get("silence_reason", "") or "")
        if not self.defer_reason:
            self.defer_reason = str(packet.get("defer_reason", "") or "")
        if not self.action_rationale:
            self.action_rationale = str(packet.get("action_rationale", "") or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "thread_key": self.thread_key,
            "chat_name": self.chat_name,
            "sender": self.sender,
            "user_text": self.user_text,
            "sidecar": self.sidecar,
            "mind_packet": self.mind_packet,
            "attention_state": self.attention_state.to_dict(),
            "emotion_state": dict(self.emotion_state),
            "history": list(self.history),
            "utterance_plan": dict(self.utterance_plan),
            "metadata": dict(self.metadata),
            "capability_context": dict(self.capability_context),
            "route_hint": self.route_hint,
            "persona_blend": dict(self.persona_blend),
            "brain_state": dict(self.brain_state),
            "game_state": dict(self.game_state),
            "stream_influence": dict(self.stream_influence),
            "self_revision_state": dict(self.self_revision_state),
            "self_model": dict(self.self_model),
            "homeostasis_state": dict(self.homeostasis_state),
            "operator_state": dict(self.operator_state),
            "visual_memory": dict(self.visual_memory),
            "affect_state": dict(self.affect_state),
            "drive_state": dict(self.drive_state),
            "value_state": dict(self.value_state),
            "conflict_state": dict(self.conflict_state),
            "initiative_candidates": list(self.initiative_candidates),
            "resistance_posture": dict(self.resistance_posture),
            "outcome_memory": dict(self.outcome_memory),
            "intent_state": dict(self.intent_state),
            "action_market": list(self.action_market),
            "selected_action": dict(self.selected_action),
            "expression_budget": int(self.expression_budget),
            "silence_reason": self.silence_reason,
            "defer_reason": self.defer_reason,
            "action_rationale": self.action_rationale,
        }


@dataclass(slots=True)
class ReplyPlan:
    text: str
    bubbles: list[ReplyBubble] = field(default_factory=list)
    attention_state: AttentionState | None = None
    turn_plan: TurnPlan | None = None
    emotion_state: dict[str, Any] = field(default_factory=dict)
    utterance_plan: dict[str, Any] = field(default_factory=dict)
    random_state: dict[str, Any] = field(default_factory=dict)
    tool_requests: list[ToolRequest] = field(default_factory=list)
    route: str = "main"
    processor: str = "codex_cli"
    session_id: str = ""
    raw_text: str = ""
    timing_ms: dict[str, int] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)

    def bubble_texts(self) -> list[str]:
        return [bubble.text for bubble in self.bubbles if bubble.text.strip()]

    def cadence_ms(self) -> list[int]:
        return [max(0, int(bubble.delay_ms)) for bubble in self.bubbles if bubble.text.strip()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bubbles": [bubble.to_dict() for bubble in self.bubbles],
            "attention_state": self.attention_state.to_dict() if self.attention_state else {},
            "turn_plan": self.turn_plan.to_dict() if self.turn_plan else {},
            "emotion_state": dict(self.emotion_state),
            "utterance_plan": dict(self.utterance_plan),
            "random_state": dict(self.random_state),
            "tool_requests": [request.to_dict() for request in self.tool_requests],
            "route": self.route,
            "processor": self.processor,
            "session_id": self.session_id,
            "raw_text": self.raw_text,
            "timing_ms": dict(self.timing_ms),
            "debug": dict(self.debug),
        }
