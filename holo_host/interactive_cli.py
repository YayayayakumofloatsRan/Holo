from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_event_stream import (
    build_agent_event_stream,
    render_agent_event_stream,
    render_compact_status,
    render_tool_observations,
    safe_json_dumps,
)

INTERACTIVE_CLI_SESSION_SCHEMA = "holo.stage153.interactive_cli_session.v1"


@dataclass(slots=True)
class InteractiveCliSession:
    thread_key: str
    chat_name: str
    channel: str
    sender: str = "Operator"
    last_payload: dict[str, Any] = field(default_factory=dict)
    last_event_stream: dict[str, Any] = field(default_factory=dict)
    last_user_text: str = ""
    last_transport: str = ""
    turn_count: int = 0

    def record_turn(self, payload: dict[str, Any], *, user_text: str, transport: str = "") -> dict[str, Any]:
        self.turn_count += 1
        self.last_payload = dict(payload or {})
        self.last_user_text = str(user_text or "")
        self.last_transport = str(transport or "")
        self.last_event_stream = build_agent_event_stream(
            self.last_payload,
            user_text=self.last_user_text,
            thread_key=self.thread_key,
            chat_name=self.chat_name,
            channel=self.channel,
            transport=self.last_transport,
        )
        self.last_payload["stage153_agent_event_stream"] = self.last_event_stream
        self.last_payload["stage153_interactive_cli_session"] = self.to_metadata()
        return self.last_event_stream

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema": INTERACTIVE_CLI_SESSION_SCHEMA,
            "thread_key": self.thread_key,
            "chat_name": self.chat_name,
            "channel": self.channel,
            "sender": self.sender,
            "turn_count": self.turn_count,
            "last_transport": self.last_transport,
            "has_last_turn": bool(self.last_payload),
        }

    def render_trace(self) -> str:
        if not self.last_event_stream:
            return "[trace] no turns yet"
        return render_agent_event_stream(self.last_event_stream)

    def render_json(self) -> str:
        if not self.last_payload:
            return "{}"
        return safe_json_dumps(self.last_payload)

    def render_tools(self) -> str:
        return render_tool_observations(self.last_payload)

    def render_compact(self) -> str:
        return render_compact_status(self.last_payload)

    def handle_command(self, command_line: str) -> str:
        command, _, _rest = str(command_line or "").partition(" ")
        command = command.strip().lower()
        if command == "/trace":
            return self.render_trace()
        if command == "/json":
            return self.render_json()
        if command == "/tools":
            return self.render_tools()
        if command == "/compact":
            return self.render_compact()
        return f"unknown command: {command}"
