from __future__ import annotations

from typing import Any

from ..config import HostConfig
from ..models import ProcessorTaskRequest
from .bounded_payload import bounded_dict, compact
from .contracts import SPEECH_ACTIONS, STAGE29_NAME
from .response_shaping import shape_deterministic_reply


class BionicGeneration:
    def __init__(self, *, config: HostConfig, runner: Any | None = None) -> None:
        self.config = config
        self.runner = runner

    def generate(
        self,
        *,
        query: str,
        packet: dict[str, Any],
        selected_action: dict[str, Any],
        channel: str,
        adapter: str,
        thread_key: str,
    ) -> dict[str, Any]:
        action_type = str(selected_action.get("action_type", "") or "")
        if action_type not in SPEECH_ACTIONS:
            return {
                "mode": "action_no_generation",
                "text": "",
                "provider": "",
                "model": "",
                "reason": f"selected action {action_type or '<unknown>'} is not a speech action",
            }
        if self.runner is None:
            shaped = shape_deterministic_reply(query=query, packet=packet, selected_action=selected_action)
            return {
                "mode": "deterministic_fallback",
                "text": shaped["text"],
                "provider": "deterministic",
                "model": "",
                "shape": shaped["shape"],
                "context_refs": shaped["context_refs"],
                "inquiry_quality": shaped["inquiry_quality"],
            }
        prompt = "\n".join(
            [
                "Answer as a bounded Holo bionic kernel turn without label-template prefixes.",
                "If asking, ask at most one grounded question tied to the current continuity.",
                f"Selected action: {selected_action.get('action_type', 'reply_once')}",
                f"Continuity: {compact(packet.get('continuity_summary', ''), limit=280)}",
                f"User query: {query}",
            ]
        )
        request = ProcessorTaskRequest(
            task_type="reply",
            prompt=prompt,
            provider_hint=str(self.config.runtime.processor_backend or ""),
            metadata={"stage": STAGE29_NAME, "channel": channel, "adapter": adapter, "thread_key": thread_key},
        )
        result = self.runner.run_task(request)
        metadata = bounded_dict(result.metadata or {}, depth=3)
        return {
            "mode": "processor_fabric",
            "text": str(result.text or ""),
            "provider": str(metadata.get("provider", "") or ""),
            "model": str(metadata.get("model", "") or ""),
            "metadata": metadata,
        }
