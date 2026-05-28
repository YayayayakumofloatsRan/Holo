from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from kernel_v3.contracts import ContextBundle, JsonObject
from kernel_v3.journal import Journal
from kernel_v3.session import TaskState


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, kw_only=True)
class ContextPack:
    context_id: str
    task_id: str
    run_id: str
    thread_id: str
    sections: list[JsonObject]
    source_refs: list[str]
    budget: JsonObject
    redactions: list[str]
    memory_refs: list[str]
    payload_hash: str

    def to_dict(self) -> JsonObject:
        return asdict(self)


class ContextPackCompiler:
    def __init__(
        self,
        *,
        token_budget: int = 4096,
        permission_state: JsonObject | None = None,
    ) -> None:
        self.token_budget = token_budget
        self.permission_state = permission_state or {"mode": "read_write"}

    def compile(
        self,
        task: TaskState,
        journal: Journal,
        *,
        tool_briefs: list[JsonObject] | None = None,
    ) -> ContextPack:
        records = journal.records(task_id=task.task_id)
        event_records = [record for record in records if record.kind in {"event", "resume"}]
        observation_records = [record for record in records if record.kind == "observation"][-3:]
        memory_refs: list[str] = []
        sections: list[JsonObject] = [
            {
                "name": "user_event",
                "records": [record.data for record in event_records[-1:]],
            },
            {
                "name": "active_task_state",
                "task_id": task.task_id,
                "run_id": task.run_id,
                "thread_id": task.thread_id,
                "input_text": task.input_text,
                "status": task.status,
                "step_id": task.step_id,
            },
            {
                "name": "recent_observations",
                "records": [record.data for record in observation_records],
            },
            {
                "name": "tool_briefs",
                "tools": list(tool_briefs or []),
            },
            {
                "name": "permission_state",
                "permission": self.permission_state,
            },
            {
                "name": "memory_refs",
                "refs": memory_refs,
            },
        ]
        source_refs = [record.record_id for record in event_records[-1:] + observation_records]
        budget = {"token_budget": self.token_budget, "section_count": len(sections)}
        payload = {
            "task_id": task.task_id,
            "run_id": task.run_id,
            "thread_id": task.thread_id,
            "sections": sections,
            "source_refs": source_refs,
            "budget": budget,
            "redactions": [],
            "memory_refs": memory_refs,
        }
        return ContextPack(
            context_id=f"ctx-{task.run_id}-{len(records) + 1}",
            task_id=task.task_id,
            run_id=task.run_id,
            thread_id=task.thread_id,
            sections=sections,
            source_refs=source_refs,
            budget=budget,
            redactions=[],
            memory_refs=memory_refs,
            payload_hash=_payload_hash(payload),
        )

    @staticmethod
    def from_dict(data: JsonObject) -> ContextPack:
        return ContextPack(**data)


class ContextCompiler:
    def compile(self, task: TaskState, journal: Journal) -> ContextBundle:
        pack = ContextPackCompiler().compile(task, journal)
        event_ids = [
            str(record.get("event_id"))
            for section in pack.sections
            if section["name"] == "user_event"
            for record in section["records"]
            if "event_id" in record
        ]
        return ContextBundle(
            context_id=pack.context_id,
            thread_key=task.thread_id,
            event_ids=event_ids,
            memory_refs=pack.memory_refs,
            state={
                "task_id": task.task_id,
                "run_id": task.run_id,
                "thread_id": task.thread_id,
                "input_text": task.input_text,
                "context_pack_hash": pack.payload_hash,
            },
            token_budget=int(pack.budget["token_budget"]),
        )
