from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bionic_kernel_parts import BionicCapsule, BionicPhase, BionicPipeline, BionicTurnRequest, KERNEL_NAME, STAGE29_NAME
from .bionic_kernel_parts.bounded_payload import compact
from .bionic_kernel_parts.contracts import CAPSULE_PHASES, SPEECH_ACTIONS
from .bionic_kernel_parts.pipeline import DeterministicAgentMemory
from .config import HostConfig
from .subject_loop import STAGE30_NAME, SUBJECT_LOOP_NAME, SUBJECT_LOOP_PHASES


class BionicKernel:
    """Public Stage29 facade around the modular bionic subject-kernel pipeline."""

    def __init__(
        self,
        *,
        config: HostConfig,
        memory: Any | None = None,
        runner: Any | None = None,
        store: Any | None = None,
    ) -> None:
        self.config = config
        self.memory = memory or DeterministicAgentMemory()
        self.runner = runner
        self.store = store
        self._pipeline = BionicPipeline(config=config, memory=self.memory, runner=runner)

    def run_turn(
        self,
        *,
        query: str,
        thread_key: str,
        chat_name: str,
        channel: str = "cli",
        record: bool = True,
    ) -> dict[str, Any]:
        return self.run_request(
            BionicTurnRequest(
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                adapter=channel or "cli",
                record=record,
            )
        )

    def run_request(self, request: BionicTurnRequest) -> dict[str, Any]:
        request = self._with_trace_continuity(request)
        result = self._pipeline.run_request(request)
        capsule = result["capsule"]
        trace_id = 0
        if bool(request.record) and self.store is not None:
            trace = self.store.record_bionic_agent_trace(
                channel=str(capsule.get("channel", "") or ""),
                thread_key=str(capsule.get("thread_key", "") or ""),
                chat_name=str(capsule.get("chat_name", "") or ""),
                query_text=str(capsule.get("query", "") or ""),
                capsule=capsule,
                metrics=dict(capsule.get("metrics", {}) or {}),
            )
            trace_id = int(trace.get("id", 0) or 0)
        result["trace_id"] = trace_id
        return result

    def _with_trace_continuity(self, request: BionicTurnRequest) -> BionicTurnRequest:
        if self.store is None:
            return request
        metadata = dict(request.metadata or {})
        if str(metadata.get("bionic_trace_continuity", "") or "").strip():
            return request
        rows = self.store.list_bionic_agent_traces(
            limit=1,
            channel=str(request.channel or "cli"),
            thread_key=str(request.thread_key or ""),
        )
        if not rows:
            return request
        try:
            capsule = json.loads(str(rows[0].get("capsule_json", "{}") or "{}"))
        except json.JSONDecodeError:
            return request
        previous_query = compact(capsule.get("query", ""), limit=120)
        previous_generation = dict(capsule.get("generation", {})) if isinstance(capsule.get("generation", {}), dict) else {}
        previous_text = compact(previous_generation.get("text", ""), limit=180)
        if not previous_query and not previous_text:
            return request
        metadata["bionic_trace_continuity"] = compact(
            f"Previous bionic turn: user asked {previous_query or '<unknown>'}; Holo answered {previous_text or '<no generated text>'}.",
            limit=360,
        )
        return BionicTurnRequest(
            query=request.query,
            thread_key=request.thread_key,
            chat_name=request.chat_name,
            channel=request.channel,
            adapter=request.adapter,
            record=request.record,
            metadata=metadata,
        )

    def export_trace(self, *, trace_id: int, output: str | Path) -> dict[str, Any]:
        if self.store is None:
            raise ValueError("store is required to export a bionic trace")
        rows = self.store.list_bionic_agent_traces(limit=1, trace_id=int(trace_id))
        if not rows:
            return {"ok": False, "stage": STAGE29_NAME, "trace_id": int(trace_id), "error": "trace_not_found"}
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rows[0]["capsule_json"], encoding="utf-8")
        return {"ok": True, "stage": STAGE29_NAME, "trace_id": int(trace_id), "output": str(output_path)}


class BionicAgent(BionicKernel):
    """Backward-compatible name for the Stage29 bionic subject kernel."""

    pass


__all__ = [
    "BionicAgent",
    "BionicCapsule",
    "BionicPhase",
    "BionicKernel",
    "BionicPipeline",
    "BionicTurnRequest",
    "CAPSULE_PHASES",
    "DeterministicAgentMemory",
    "KERNEL_NAME",
    "SPEECH_ACTIONS",
    "STAGE29_NAME",
    "STAGE30_NAME",
    "SUBJECT_LOOP_NAME",
    "SUBJECT_LOOP_PHASES",
]
