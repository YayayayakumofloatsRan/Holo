from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass

from kernel_v3.context.artifacts import ArtifactStore
from kernel_v3.context.budgeter import BudgetExceeded, measure_units, validate_section_budget
from kernel_v3.context.memory_read import MemoryRead
from kernel_v3.context.redaction import Redactor
from kernel_v3.context.validator import deterministic_hash
from kernel_v3.contracts import ContextBundle, JsonObject, LedgerRecord
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryStore
from kernel_v3.memory.structured import structured_memory_summary
from kernel_v3.session import TaskState


CONTEXT_DURABLE_MEMORY_LIMIT_CAP = 10
AGENT_TRACE_RECORD_LIMIT = 16
AGENT_TRACE_KINDS = {
    "assistant_turn",
    "action",
    "policy_decision",
    "tool_execution_event",
    "observation",
    "feedback",
    "guard",
    "result",
}


@dataclass(frozen=True, kw_only=True)
class ProjectProfile:
    project_id: str
    root: str
    summary: str
    constraints: list[str]
    redaction_markers: list[str]

    @classmethod
    def empty(cls) -> "ProjectProfile":
        return cls(project_id="local", root="", summary="", constraints=[], redaction_markers=[])

    def to_dict(self) -> JsonObject:
        return asdict(self)


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
        artifact_store: ArtifactStore | None = None,
        memory_read: MemoryRead | None = None,
        project_profile: ProjectProfile | None = None,
        token_budget: int = 4096,
        section_budget: int = 1024,
        permission_state: JsonObject | None = None,
        redactor: Redactor | None = None,
        budget_mode: str = "fail",
        durable_memory_store: MemoryStore | None = None,
        durable_memory_limit: int = 5,
        include_sensitive_memory: bool = False,
        durable_memory_user_id: str = "local:user",
    ) -> None:
        if budget_mode not in {"fail", "truncate"}:
            raise ValueError("budget_mode must be 'fail' or 'truncate'")
        self.artifact_store = artifact_store or ArtifactStore.in_memory()
        self.memory_read = memory_read
        self.project_profile = project_profile or ProjectProfile.empty()
        self.token_budget = token_budget
        self.section_budget = section_budget
        self.permission_state = permission_state or {"mode": "read_write"}
        self.redactor = redactor or Redactor(private_path_markers=self.project_profile.redaction_markers)
        self.budget_mode = budget_mode
        self.durable_memory_store = durable_memory_store
        self.durable_memory_limit = _clamp_limit(durable_memory_limit, cap=CONTEXT_DURABLE_MEMORY_LIMIT_CAP)
        self.requested_durable_memory_limit = durable_memory_limit
        self.include_sensitive_memory = include_sensitive_memory
        self.durable_memory_user_id = durable_memory_user_id

    def compile(
        self,
        task: TaskState,
        journal: JournalStore,
        *,
        tool_briefs: list[JsonObject] | None = None,
        step_id: str | None = None,
    ) -> ContextPack:
        target_step = step_id or task.step_id
        memory_read = self.memory_read or MemoryRead(journal=journal, artifact_store=self.artifact_store)
        records = journal.records(task_id=task.task_id)
        event_records = [record for record in records if record.kind in {"event", "resume"}]
        observation_records = [record for record in records if record.kind == "observation"][-3:]
        agent_trace_limit = _agent_trace_record_limit(
            token_budget=self.token_budget,
            section_budget=self.section_budget,
        )
        agent_trace_records = _recent_agent_trace_records(records, limit=agent_trace_limit)
        artifact_ids: list[str] = []
        for record in observation_records:
            artifact_ids.extend(record.artifact_refs)
        artifact_ids = _ordered_unique(artifact_ids)
        resolved_artifacts = {artifact.artifact_id: artifact for artifact in self.artifact_store.resolve_many(artifact_ids)}
        evidence = memory_read.query_observations(task_id=task.task_id, limit=3, order="recent")
        citations = memory_read.query_citations(task_id=task.task_id, limit=3, order="recent")
        memory_refs = [item.observation_id for item in evidence]
        durable_memory_enabled = self.durable_memory_store is not None
        durable_memory: JsonObject = {}
        durable_memory_items: list[JsonObject] = []
        durable_memory_context: JsonObject = {}
        if durable_memory_enabled:
            durable_memory = _recall_durable_memory_views(
                self.durable_memory_store,
                task=task,
                user_id=self.durable_memory_user_id,
                project_id=self.project_profile.project_id,
                limit=self.durable_memory_limit,
                include_sensitive=self.include_sensitive_memory,
                context_id=f"ctx-{task.task_id}-{task.run_id}-{target_step}",
                step_id=target_step,
            )
            durable_memory_items = [
                _compact_durable_memory_item(item)
                for item in durable_memory.get("items", [])
                if isinstance(item, dict)
            ]
            durable_memory_context = _durable_memory_context(durable_memory, durable_memory_items)
        sections: list[JsonObject] = [
            {"name": "user_event", "records": [_compact_event(record.data) for record in event_records[-1:]]},
            {"name": "active_task_state", **_compact_task_state(task, target_step)},
            {"name": "project_profile", "profile": _compact_project_profile(self.project_profile.to_dict())},
            {
                "name": "recent_observations",
                "records": [_compact_observation(record.data) for record in observation_records],
            },
            {
                "name": "artifact_references",
                "artifacts": [
                    _compact_artifact_ref(artifact_id, resolved_artifacts.get(artifact_id))
                    for artifact_id in artifact_ids
                ],
            },
            {"name": "memory_refs", "refs": [_compact_evidence(item) for item in evidence]},
            {"name": "citations", "items": [_compact_citation(item) for item in citations]},
            {"name": "tool_briefs", "tools": [_compact_tool_brief(item) for item in list(tool_briefs or [])]},
            {"name": "permission_state", "permission": _compact_permission_state(self.permission_state)},
        ]
        if agent_trace_limit > 0:
            sections.insert(
                3,
                {
                    "name": "agent_trace",
                    "records": [_compact_agent_trace_record(record) for record in agent_trace_records],
                    "record_limit": agent_trace_limit,
                    "purpose": "model-visible assistant/tool/result trajectory for the next agent turn",
                },
            )
        if durable_memory_enabled:
            sections.insert(
                7,
                {
                    "name": "durable_memory",
                    "items": durable_memory_items,
                    "scope": durable_memory.get("scope", {}),
                    "views": durable_memory.get("views", {}),
                    "combined": durable_memory.get("combined", {}),
                    "context": durable_memory_context,
                    "total": durable_memory.get("total", 0),
                    "filtered": durable_memory.get("filtered", {}),
                    "limit": durable_memory.get("limit", self.durable_memory_limit),
                    **_limit_section_diagnostics(
                        requested_limit=self.requested_durable_memory_limit,
                        effective_limit=self.durable_memory_limit,
                        limit_cap=CONTEXT_DURABLE_MEMORY_LIMIT_CAP,
                    ),
                },
            )
        budget_views = {
            "user_event": {"records": [_event_budget_view(record.data) for record in event_records[-1:]]},
            "active_task_state": _compact_task_state(task, target_step),
            "project_profile": _compact_project_profile(self.project_profile.to_dict()),
            "recent_observations": {
                "records": [_observation_budget_view(record.data) for record in observation_records]
            },
            "artifact_references": {
                "artifacts": [_artifact_budget_view(artifact_id, resolved_artifacts.get(artifact_id)) for artifact_id in artifact_ids]
            },
            "memory_refs": {"refs": [_evidence_budget_view(item) for item in evidence]},
            "citations": {"items": [_citation_budget_view(item) for item in citations]},
            "tool_briefs": {"tools": [_compact_tool_brief(item) for item in list(tool_briefs or [])]},
            "permission_state": {"permission": _compact_permission_state(self.permission_state)},
        }
        if agent_trace_limit > 0:
            budget_views["agent_trace"] = {
                "records": [_agent_trace_budget_view(record) for record in agent_trace_records],
                "record_limit": agent_trace_limit,
            }
        if durable_memory_enabled:
            budget_views["durable_memory"] = {
                "items": [_durable_memory_budget_view(item) for item in durable_memory_items],
                "context": _durable_memory_context_budget_view(durable_memory_context),
            }
        redacted_sections, redactions = self.redactor.redact(sections)
        section_units, compacted_section_names = self._enforce_section_budgets(redacted_sections, budget_views)
        total_units = sum(section_units)
        if total_units > self.token_budget:
            if self.budget_mode == "fail":
                raise BudgetExceeded("bundle", total_units, self.token_budget)
            total_units = self._truncate_bundle(redacted_sections, section_units, total_units, compacted_section_names)
        source_refs = [record.record_id for record in event_records[-1:] + observation_records]
        source_refs.extend(artifact_ids)
        source_refs.extend(
            _ordered_unique(
                [
                    str(ref)
                    for item in durable_memory_items
                    for ref in [item.get("memory_id"), *list(item.get("provenance_refs", []))]
                    if ref
                ]
            )
        )
        budget = {
            "token_budget": self.token_budget,
            "section_limit": self.section_budget,
            "section_count": len(redacted_sections),
            "section_units": section_units,
            "total_units": total_units,
            "within_budget": True,
        }
        if self.budget_mode == "truncate" or compacted_section_names:
            budget["compaction"] = {
                "mode": self.budget_mode,
                "applied": bool(compacted_section_names),
                "sections": compacted_section_names,
            }
        payload = {
            "task_id": task.task_id,
            "run_id": task.run_id,
            "thread_id": task.thread_id,
            "sections": redacted_sections,
            "source_refs": source_refs,
            "budget": budget,
            "redactions": redactions,
            "memory_refs": memory_refs,
        }
        return ContextPack(
            context_id=f"ctx-{task.task_id}-{task.run_id}-{target_step}",
            task_id=task.task_id,
            run_id=task.run_id,
            thread_id=task.thread_id,
            sections=redacted_sections,
            source_refs=source_refs,
            budget=budget,
            redactions=redactions,
            memory_refs=memory_refs,
            payload_hash=deterministic_hash(payload),
        )

    def _enforce_section_budgets(
        self,
        redacted_sections: list[JsonObject],
        budget_views: dict[str, JsonObject],
    ) -> tuple[list[int], list[str]]:
        section_units: list[int] = []
        compacted: list[str] = []
        for section in redacted_sections:
            name = str(section["name"])
            budget_view = budget_views[name]
            try:
                validate_section_budget(name, budget_view, self.section_budget)
                if self.budget_mode == "truncate":
                    section_units.append(self._compact_section_to_limit(section))
                else:
                    section_units.append(measure_units(_section_payload(section)))
                continue
            except BudgetExceeded:
                if self.budget_mode == "fail":
                    raise
            self._truncate_section(section)
            section_units.append(self._compact_section_to_limit(section))
            compacted.append(name)
        return section_units, compacted

    def _truncate_bundle(
        self,
        redacted_sections: list[JsonObject],
        section_units: list[int],
        total_units: int,
        compacted_section_names: list[str],
    ) -> int:
        droppable = [
            "tool_briefs",
            "citations",
            "durable_memory",
            "memory_refs",
            "agent_trace",
            "recent_observations",
            "project_profile",
        ]
        for name in droppable:
            if total_units <= self.token_budget:
                break
            section = next((item for item in redacted_sections if item.get("name") == name), None)
            if section is None:
                continue
            index = redacted_sections.index(section)
            before = section_units[index]
            self._truncate_section(section, aggressive=True)
            after = self._compact_section_to_limit(section, aggressive=True)
            section_units[index] = after
            total_units -= max(0, before - after)
            if name not in compacted_section_names:
                compacted_section_names.append(name)
        if total_units > self.token_budget:
            raise BudgetExceeded("bundle", total_units, self.token_budget)
        return total_units

    def _truncate_section(self, section: JsonObject, *, aggressive: bool = False) -> None:
        name = str(section.get("name", ""))
        text_limit = 24 if aggressive else 64
        if name == "user_event":
            _truncate_text_values(section, limit=96)
            return
        if name in {"active_task_state", "permission_state"}:
            return
        if name == "artifact_references":
            for artifact in section.get("artifacts", []):
                if isinstance(artifact, dict) and isinstance(artifact.get("metadata"), dict):
                    artifact["metadata"] = _truncate_json(artifact["metadata"], limit=24)
            return
        _truncate_text_values(section, limit=text_limit)

    def _compact_section_to_limit(self, section: JsonObject, *, aggressive: bool = False) -> int:
        text_limit = 64 if not aggressive else 24
        while measure_units(_section_payload(section)) > self.section_budget and text_limit > 8:
            text_limit = max(8, text_limit // 2)
            _truncate_text_values(section, limit=text_limit)
            self._truncate_lists(section, limit=2 if not aggressive else 1)
        used = measure_units(_section_payload(section))
        if used <= self.section_budget:
            return used
        self._drop_optional_items(section)
        used = measure_units(_section_payload(section))
        if used > self.section_budget:
            raise BudgetExceeded(str(section.get("name", "")), used, self.section_budget)
        return used

    def _truncate_lists(self, value, *, limit: int) -> None:
        if isinstance(value, dict):
            for item in value.values():
                self._truncate_lists(item, limit=limit)
            return
        if isinstance(value, list):
            del value[limit:]
            for item in value:
                self._truncate_lists(item, limit=limit)

    def _drop_optional_items(self, section: JsonObject) -> None:
        name = str(section.get("name", ""))
        if name == "recent_observations":
            records = section.get("records")
            if isinstance(records, list):
                del records[1:]
        elif name == "memory_refs":
            refs = section.get("refs")
            if isinstance(refs, list):
                del refs[1:]
        elif name == "durable_memory":
            items = section.get("items")
            if isinstance(items, list):
                del items[1:]
            context = section.get("context")
            if isinstance(context, dict):
                section["context"] = _durable_memory_context_budget_view(context)
        elif name == "citations":
            items = section.get("items")
            if isinstance(items, list):
                del items[1:]
        elif name == "tool_briefs":
            tools = section.get("tools")
            if isinstance(tools, list):
                del tools[1:]
        elif name == "agent_trace":
            records = section.get("records")
            if isinstance(records, list):
                del records[4:]
        _truncate_text_values(section, limit=8)
        if name == "recent_observations":
            records = section.get("records")
            if isinstance(records, list):
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    record["content"] = {"preview": _compact_text(str(record.get("content", "")), limit=8)}
        elif name == "memory_refs":
            refs = section.get("refs")
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, dict):
                        ref.pop("artifact_refs", None)
        elif name == "durable_memory":
            items = section.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        item.pop("scope", None)
                        item["summary"] = _compact_text(str(item.get("summary", "")), limit=8)
            context = section.get("context")
            if isinstance(context, dict):
                section["context"] = {
                    "kind": context.get("kind"),
                    "enabled": context.get("enabled"),
                    "total": context.get("total"),
                    "combined_memory_ids": list(context.get("combined_memory_ids", []))[:4]
                    if isinstance(context.get("combined_memory_ids"), list)
                    else [],
                    "view_totals": dict(context.get("view_totals", {})) if isinstance(context.get("view_totals"), dict) else {},
                    "host_boundary": "safe summaries and refs only",
                }
        elif name == "citations":
            items = section.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        item["quote"] = _compact_text(str(item.get("quote", "")), limit=8)
        elif name == "agent_trace":
            records = section.get("records")
            if isinstance(records, list):
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    for key in ("assistant_turn", "action", "observation", "feedback"):
                        payload = record.get(key)
                        if isinstance(payload, dict):
                            record[key] = _compact_nested_content(payload)

    @staticmethod
    def from_dict(data: JsonObject) -> ContextPack:
        return ContextPack(**data)


class ContextCompiler:
    def __init__(self, *, artifact_store: ArtifactStore | None = None) -> None:
        self.artifact_store = artifact_store or ArtifactStore.in_memory()

    def compile(self, task: TaskState, journal: JournalStore) -> ContextBundle:
        pack = ContextPackCompiler(artifact_store=self.artifact_store).compile(task, journal)
        safe_input_text, input_redactions = Redactor().redact(task.input_text)
        redactions = _ordered_unique([*pack.redactions, *input_redactions])
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
                "input_text": str(safe_input_text),
                "context_pack_hash": pack.payload_hash,
                "sections": pack.sections,
                "source_refs": pack.source_refs,
                "redactions": redactions,
                "budget": pack.budget,
            },
            token_budget=int(pack.budget["token_budget"]),
        )


def _section_payload(section: JsonObject) -> JsonObject:
    return {key: value for key, value in section.items() if key != "name"}


def _compact_text(text: str, *, limit: int = 256) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _truncate_json(value, *, limit: int):
    copied = deepcopy(value)
    _truncate_text_values(copied, limit=limit)
    return copied


def _clamp_limit(value: int, *, cap: int) -> int:
    return min(max(0, int(value)), cap)


def _limit_section_diagnostics(*, requested_limit: int, effective_limit: int, limit_cap: int) -> JsonObject:
    if requested_limit == effective_limit:
        return {}
    return {
        "requested_limit": requested_limit,
        "limit_cap": limit_cap,
        "limit_clamped": True,
    }


def _truncate_text_values(value, *, limit: int) -> None:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key == "name":
                continue
            if isinstance(item, str):
                value[key] = _compact_text(item, limit=limit)
            else:
                _truncate_text_values(item, limit=limit)
        return
    if isinstance(value, list):
        for item in value:
            _truncate_text_values(item, limit=limit)


def _compact_event(data: JsonObject) -> JsonObject:
    payload = data.get("payload")
    text = ""
    if isinstance(payload, dict):
        text = str(payload.get("text", ""))
    elif isinstance(data.get("text"), str):
        text = str(data.get("text", ""))
    return {
        "event_id": data.get("event_id"),
        "text": _compact_text(text, limit=128),
    }


def _compact_task_state(task: TaskState, step_id: str) -> JsonObject:
    return {
        "task_id": task.task_id,
        "run_id": task.run_id,
        "step_id": step_id,
        "status": task.status,
    }


def _compact_project_profile(profile: JsonObject) -> JsonObject:
    return {
        "project_id": profile.get("project_id"),
        "summary": _compact_text(str(profile.get("summary", "")), limit=256),
        "constraints": list(profile.get("constraints", [])),
        "redaction_markers": list(profile.get("redaction_markers", [])),
    }


def _recent_agent_trace_records(records: list[LedgerRecord], *, limit: int) -> list[LedgerRecord]:
    trace = [record for record in records if _include_agent_trace_record(record)]
    return trace[-max(0, int(limit)) :]


def _include_agent_trace_record(record: LedgerRecord) -> bool:
    if record.kind not in AGENT_TRACE_KINDS:
        return False
    data = record.data if isinstance(record.data, dict) else {}
    if record.kind == "policy_decision" and data.get("allowed") is True:
        return False
    if record.kind == "tool_execution_event" and data.get("event_type") == "progress":
        return False
    return True


def _agent_trace_record_limit(*, token_budget: int, section_budget: int) -> int:
    if token_budget < 2048 or section_budget < 192:
        return 0
    if section_budget < 384:
        return min(2, AGENT_TRACE_RECORD_LIMIT)
    if section_budget < 1536:
        return min(4, AGENT_TRACE_RECORD_LIMIT)
    return AGENT_TRACE_RECORD_LIMIT


def _compact_agent_trace_record(record: LedgerRecord) -> JsonObject:
    data = record.data if isinstance(record.data, dict) else {}
    compacted: JsonObject = {
        "record_id": record.record_id,
        "run_id": record.run_id,
        "step_id": record.step_id,
        "kind": record.kind,
    }
    if record.action_ref:
        compacted["action_ref"] = record.action_ref
    if record.observation_ref:
        compacted["observation_ref"] = record.observation_ref
    if record.feedback_ref:
        compacted["feedback_ref"] = record.feedback_ref
    if record.artifact_refs:
        compacted["artifact_refs"] = record.artifact_refs[:8]

    if record.kind == "assistant_turn":
        compacted["assistant_turn"] = _compact_agent_trace_assistant_turn(data)
    elif record.kind == "action":
        compacted["action"] = _compact_agent_trace_action(data)
    elif record.kind == "policy_decision":
        compacted["policy_decision"] = _compact_agent_trace_policy(data)
    elif record.kind == "tool_execution_event":
        compacted["tool_execution_event"] = _compact_agent_trace_tool_event(data)
    elif record.kind == "observation":
        compacted["observation"] = _compact_agent_trace_observation(data)
    elif record.kind == "feedback":
        compacted["feedback"] = _compact_agent_trace_feedback(data)
    elif record.kind == "guard":
        compacted["guard"] = _compact_nested_content(data)
    elif record.kind == "result":
        compacted["result"] = _compact_agent_trace_result(data)
    else:
        compacted["data"] = _compact_nested_content(data)
    return compacted


def _compact_agent_trace_assistant_turn(data: JsonObject) -> JsonObject:
    raw_tool_calls = data.get("tool_calls")
    tool_calls = raw_tool_calls if isinstance(raw_tool_calls, list) else []
    raw_parse_errors = data.get("parse_errors")
    parse_errors = raw_parse_errors if isinstance(raw_parse_errors, list) else []
    return {
        "turn_id": data.get("turn_id"),
        "message": _compact_optional_text(data.get("message"), limit=320),
        "tool_call_count": data.get("tool_call_count", len(tool_calls)),
        "tool_calls": [
            _compact_agent_trace_tool_call(item)
            for item in tool_calls[:8]
            if isinstance(item, dict)
        ],
        "final_answer": _compact_optional_text(data.get("final_answer"), limit=360),
        "stop_reason": data.get("stop_reason"),
        "reasons": _string_list(data.get("reasons"))[:8],
        "parse_errors": [
            _compact_nested_content(item)
            for item in parse_errors[:4]
            if isinstance(item, dict)
        ],
    }


def _compact_agent_trace_tool_call(item: JsonObject) -> JsonObject:
    arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
    return {
        "tool_call_id": item.get("tool_call_id") or item.get("id"),
        "name": item.get("name") or item.get("tool"),
        "arguments": _compact_nested_content(arguments),
        "reason": _compact_optional_text(item.get("reason") or item.get("description"), limit=200),
        "side_effect_class": item.get("side_effect_class"),
    }


def _compact_agent_trace_action(data: JsonObject) -> JsonObject:
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    return {
        "action_id": data.get("action_id"),
        "kind": data.get("kind"),
        "name": data.get("name"),
        "description": _compact_optional_text(data.get("description"), limit=240),
        "payload": _compact_nested_content(payload),
        "payload_keys": [str(key) for key in payload.keys()][:24],
        "reasons": _string_list(data.get("reasons"))[:8],
        "side_effect_class": data.get("side_effect_class"),
    }


def _compact_agent_trace_policy(data: JsonObject) -> JsonObject:
    return {
        "action_id": data.get("action_id"),
        "allowed": data.get("allowed"),
        "reason": data.get("reason"),
        "permissions_required": list(data.get("permissions_required", []))
        if isinstance(data.get("permissions_required"), list)
        else [],
        "side_effect_class": data.get("side_effect_class"),
    }


def _compact_agent_trace_tool_event(data: JsonObject) -> JsonObject:
    detail = data.get("detail") if isinstance(data.get("detail"), dict) else {}
    return {
        "event_type": data.get("event_type"),
        "tool_call_id": data.get("tool_call_id"),
        "action_id": data.get("action_id"),
        "tool_name": data.get("tool_name"),
        "status": data.get("status"),
        "detail": _compact_nested_content(detail),
    }


def _compact_agent_trace_observation(data: JsonObject) -> JsonObject:
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    compacted: JsonObject = {
        "observation_id": data.get("observation_id"),
        "kind": data.get("kind"),
        "status": data.get("status"),
        "source": data.get("source"),
    }
    if data.get("action_id") is not None:
        compacted["action_id"] = data.get("action_id")
    if data.get("tool_call_id") is not None:
        compacted["tool_call_id"] = data.get("tool_call_id")
    if data.get("kind") == "tool_batch_result":
        raw_results = content.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        compacted["tool_batch"] = {
            "turn_id": content.get("turn_id"),
            "tool_call_count": content.get("tool_call_count"),
            "results": [
                {
                    "tool_call_id": item.get("tool_call_id"),
                    "tool": item.get("tool"),
                    "status": item.get("status"),
                    "kind": item.get("kind"),
                    "observation_id": item.get("observation_id"),
                    "artifact_refs": [str(ref) for ref in item.get("artifact_refs", [])[:4]]
                    if isinstance(item.get("artifact_refs"), list)
                    else [],
                }
                for item in results[:8]
                if isinstance(item, dict)
            ],
        }
    elif content:
        compacted["content_keys"] = [str(key) for key in content.keys() if not str(key).startswith("_host_")][:16]
    elif data.get("content") is not None:
        compacted["content_preview"] = _compact_text(str(data.get("content")), limit=160)
    return compacted


def _compact_agent_trace_feedback(data: JsonObject) -> JsonObject:
    return {
        "feedback_id": data.get("feedback_id"),
        "status": data.get("status"),
        "stop_reason": data.get("stop_reason"),
        "answer": _compact_optional_text(data.get("answer"), limit=360),
        "missing_evidence": _string_list(data.get("missing_evidence"))[:24],
    }


def _compact_agent_trace_result(data: JsonObject) -> JsonObject:
    return {
        "task_id": data.get("task_id"),
        "run_id": data.get("run_id"),
        "status": data.get("status"),
        "answer": _compact_optional_text(data.get("answer"), limit=360),
        "stop_reason": data.get("stop_reason"),
    }


def _compact_optional_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return _compact_text(value, limit=limit)


def _compact_observation(data: JsonObject) -> JsonObject:
    content = data.get("content")
    compacted: JsonObject = {
        "observation_id": data.get("observation_id"),
        "kind": data.get("kind"),
        "status": data.get("status"),
        "source": data.get("source"),
    }
    if data.get("action_id") is not None:
        compacted["action_id"] = data.get("action_id")
    if data.get("tool_call_id") is not None:
        compacted["tool_call_id"] = data.get("tool_call_id")
    if isinstance(content, dict):
        if data.get("kind") == "tool_batch_result":
            compacted["content"] = _compact_tool_batch_content(content)
        else:
            compacted["content"] = _compact_content(content)
    else:
        compacted["content"] = content
    return compacted


def _compact_tool_batch_content(content: JsonObject) -> JsonObject:
    raw_results = content.get("results")
    results = raw_results if isinstance(raw_results, list) else []
    return {
        "schema": content.get("schema"),
        "turn_id": content.get("turn_id"),
        "tool_call_count": content.get("tool_call_count"),
        "results": [
            _compact_tool_batch_result(item)
            for item in results[:16]
            if isinstance(item, dict)
        ],
        "result_truncated": len(results) > 16,
    }


def _compact_tool_batch_result(item: JsonObject) -> JsonObject:
    projection = item.get("content_projection") if isinstance(item.get("content_projection"), dict) else {}
    compact_projection = _compact_content_projection(projection)
    compacted = {
        "tool_call_id": item.get("tool_call_id"),
        "action_id": item.get("action_id"),
        "tool": item.get("tool"),
        "status": item.get("status"),
        "source": item.get("source"),
        "kind": item.get("kind"),
        "observation_id": item.get("observation_id"),
        "policy": item.get("policy"),
        "artifact_refs": [str(ref) for ref in item.get("artifact_refs", [])[:8]] if isinstance(item.get("artifact_refs"), list) else [],
        "content_projection": compact_projection,
    }
    replacement = item.get("content_replacement")
    if isinstance(replacement, dict):
        compacted["content_replacement_applied"] = bool(item.get("content_replacement_applied"))
        compacted["content_replacement"] = _compact_tool_result_replacement(replacement)
    return compacted


def _compact_tool_result_replacement(replacement: JsonObject) -> JsonObject:
    return {
        "schema": replacement.get("schema"),
        "tool_call_id": replacement.get("tool_call_id"),
        "reason": replacement.get("reason"),
        "original_estimated_chars": replacement.get("original_estimated_chars"),
        "artifact_refs": [str(ref) for ref in replacement.get("artifact_refs", [])[:8]] if isinstance(replacement.get("artifact_refs"), list) else [],
        "replacement_preview": _compact_text(str(replacement.get("replacement_preview") or ""), limit=480),
        "read_hint": _compact_text(str(replacement.get("read_hint") or ""), limit=360),
    }


def _compact_content_projection(projection: JsonObject) -> JsonObject:
    shape = projection.get("shape") if isinstance(projection.get("shape"), dict) else {}
    return {
        "preview": _compact_text(str(projection.get("preview") or ""), limit=360),
        "preview_chars": projection.get("preview_chars"),
        "truncated": projection.get("truncated"),
        "estimated_chars": projection.get("estimated_chars"),
        "shape": _compact_nested_content(shape),
    }


def _compact_content(content: JsonObject) -> JsonObject:
    compacted: JsonObject = {}
    for key, value in content.items():
        if str(key).startswith("_host_"):
            continue
        if isinstance(value, str):
            compacted[key] = _compact_text(value, limit=256)
        elif key == "report" and isinstance(value, dict):
            compacted[key] = _compact_retrieval_report_content(value)
        elif isinstance(value, dict):
            compacted[key] = _compact_nested_content(value)
        elif isinstance(value, list):
            compacted[key] = [_compact_nested_content(item) if isinstance(item, dict) else item for item in value[:8]]
        else:
            compacted[key] = value
    return compacted


def _compact_nested_content(value: JsonObject) -> JsonObject:
    result: JsonObject = {}
    for key, item in list(value.items())[:24]:
        if str(key).startswith("_host_"):
            continue
        if isinstance(item, str):
            result[key] = _compact_text(item, limit=160)
        elif isinstance(item, (int, float, bool)) or item is None:
            result[key] = item
        elif isinstance(item, list):
            result[key] = [
                _compact_nested_content(child) if isinstance(child, dict) else _compact_text(str(child), limit=80)
                for child in item[:8]
            ]
        elif isinstance(item, dict):
            result[key] = _compact_nested_content(item)
    return result


def _compact_retrieval_report_content(report: JsonObject) -> JsonObject:
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), dict) else {}
    evaluation = diagnostics.get("evaluation_diagnostics") if isinstance(diagnostics.get("evaluation_diagnostics"), dict) else {}
    return {
        "report_id": report.get("report_id"),
        "goal_id": report.get("goal_id"),
        "status": report.get("status"),
        "preview": _compact_text(str(report.get("preview") or ""), limit=360),
        "evidence_count": diagnostics.get("evidence_count", report.get("evidence_count")),
        "citation_count": diagnostics.get("citation_count", len(report.get("citation_ids", [])) if isinstance(report.get("citation_ids"), list) else None),
        "fetch_attempt_count": diagnostics.get("fetch_attempt_count"),
        "search_attempt_count": diagnostics.get("search_attempt_count"),
        "reason": diagnostics.get("reason"),
        "missing_query_facets": _string_list(evaluation.get("missing_query_facets"))[:12],
        "missing_finance_facets": _string_list(evaluation.get("missing_finance_facets"))[:12],
        "missing_profile_facets": _string_list(evaluation.get("missing_profile_facets"))[:12],
        "source_authority": _compact_source_authority(evaluation.get("source_authority")),
        "rejected_evidence_count": diagnostics.get("rejected_evidence_count"),
        "rejected_evidence_reasons": _compact_rejection_reasons(diagnostics.get("rejected_evidence_reasons")),
    }


def _compact_source_authority(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    families = value.get("source_families")
    return {
        "best_authority_score": value.get("best_authority_score"),
        "primary_source_count": value.get("primary_source_count"),
        "secondary_source_count": value.get("secondary_source_count"),
        "weak_source_count": value.get("weak_source_count"),
        "source_families": [str(item) for item in families[:8]] if isinstance(families, list) else [],
    }


def _compact_rejection_reasons(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {str(key): value[key] for key in list(value)[:8]}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _compact_artifact(artifact: JsonObject) -> JsonObject:
    return {
        "artifact_id": artifact.get("artifact_id"),
        "kind": artifact.get("kind"),
        "uri": artifact.get("uri"),
        "payload_hash": artifact.get("payload_hash"),
        "metadata": artifact.get("metadata", {}),
        "status": "resolved",
    }


def _compact_artifact_ref(artifact_id: str, artifact) -> JsonObject:
    if artifact is not None:
        return _compact_artifact(artifact.to_dict())
    return {
        "artifact_id": artifact_id,
        "kind": "unresolved",
        "uri": f"journal://artifacts/{artifact_id}",
        "payload_hash": "",
        "metadata": {},
        "status": "unresolved",
    }


def _compact_evidence(item) -> JsonObject:
    return {
        "observation_id": item.observation_id,
        "record_ref": item.record_ref,
        "artifact_refs": list(item.artifact_refs),
        "status": item.content.get("status") if isinstance(item.content, dict) else None,
        "source": item.content.get("source") if isinstance(item.content, dict) else None,
    }


def _compact_citation(item) -> JsonObject:
    return {
        "citation_id": item.citation_id,
        "record_ref": item.record_ref,
        "artifact_ref": item.artifact_ref,
        "uri": item.uri,
        "quote": _compact_text(item.quote, limit=256),
        "metadata": dict(item.metadata),
    }


def _recall_durable_memory(
    store: MemoryStore | None,
    *,
    task: TaskState,
    user_id: str,
    project_id: str,
    limit: int,
    include_sensitive: bool,
    context_id: str,
    step_id: str,
) -> JsonObject:
    if store is None or limit <= 0:
        return {"query": None, "scope": {"thread_id": task.thread_id}, "items": [], "total": 0, "filtered": {}, "limit": 0}
    scope = _durable_memory_recall_scope(task=task, user_id=user_id, project_id=project_id)
    result = store.recall(
        query=None,
        scope=scope,
        include_sensitive=include_sensitive,
        limit=limit,
        record_access=True,
        rank_query=task.input_text,
        access_context={
            "usage": "context_pack",
            "context_id": context_id,
            "task_id": task.task_id,
            "run_id": task.run_id,
            "thread_id": task.thread_id,
            "step_id": step_id,
            "rank_query_hash": deterministic_hash({"text": task.input_text}),
            "durable_memory_limit": max(0, int(limit)),
        },
    ).to_dict()
    result["limit"] = max(0, int(limit))
    return result


def _recall_durable_memory_views(
    store: MemoryStore | None,
    *,
    task: TaskState,
    user_id: str,
    project_id: str,
    limit: int,
    include_sensitive: bool,
    context_id: str,
    step_id: str,
) -> JsonObject:
    primary = _recall_durable_memory(
        store,
        task=task,
        user_id=user_id,
        project_id=project_id,
        limit=limit,
        include_sensitive=include_sensitive,
        context_id=context_id,
        step_id=step_id,
    )
    if store is None or limit <= 0:
        return {**primary, "views": {}, "combined": {"memory_ids": [], "total": 0}}
    views: JsonObject = {}
    primary_scope = primary.get("scope") if isinstance(primary.get("scope"), dict) else {}
    if project_id and project_id != "local":
        views["project"] = _durable_memory_view(primary, label="project")
        thread_scope: JsonObject = {"user_id": user_id, "thread_id": task.thread_id} if user_id else {"thread_id": task.thread_id}
        thread_probe = store.recall(
            query=None,
            scope=thread_scope,
            include_sensitive=include_sensitive,
            limit=limit,
            record_access=False,
            rank_query=task.input_text,
        )
        if thread_probe.total > 0:
            thread_result = store.recall(
                query=None,
                scope=thread_scope,
                include_sensitive=include_sensitive,
                limit=limit,
                record_access=True,
                rank_query=task.input_text,
                access_context={
                    "usage": "context_pack",
                    "context_id": context_id,
                    "task_id": task.task_id,
                    "run_id": task.run_id,
                    "thread_id": task.thread_id,
                    "step_id": step_id,
                    "rank_query_hash": deterministic_hash({"text": task.input_text}),
                    "durable_memory_limit": max(0, int(limit)),
                    "scope_label": "thread",
                },
            ).to_dict()
        else:
            thread_result = thread_probe.to_dict()
        thread_result["limit"] = max(0, int(limit))
        views["thread"] = _durable_memory_view(thread_result, label="thread")
        item_by_id: dict[str, JsonObject] = {}
        for item in [*primary.get("items", []), *thread_result.get("items", [])]:
            if isinstance(item, dict) and item.get("memory_id"):
                item_by_id.setdefault(str(item["memory_id"]), item)
        return {
            **primary,
            "items": list(item_by_id.values()),
            "total": len(item_by_id),
            "scope": primary_scope,
            "views": views,
            "combined": {"memory_ids": list(item_by_id), "total": len(item_by_id)},
        }
    views["thread"] = _durable_memory_view(primary, label="thread")
    memory_ids = [
        str(item.get("memory_id"))
        for item in primary.get("items", [])
        if isinstance(item, dict) and item.get("memory_id")
    ]
    return {
        **primary,
        "views": views,
        "combined": {"memory_ids": _ordered_unique(memory_ids), "total": len(_ordered_unique(memory_ids))},
    }


def _durable_memory_view(result: JsonObject, *, label: str) -> JsonObject:
    items = [
        _compact_durable_memory_item(item)
        for item in result.get("items", [])
        if isinstance(item, dict)
    ]
    return {
        "label": label,
        "scope": result.get("scope", {}),
        "items": items,
        "total": result.get("total", 0),
        "filtered": result.get("filtered", {}),
        "limit": result.get("limit", 0),
    }


def _durable_memory_context(result: JsonObject, items: list[JsonObject]) -> JsonObject:
    views = result.get("views") if isinstance(result.get("views"), dict) else {}
    view_contexts = {
        str(label): _durable_memory_view_context(view)
        for label, view in views.items()
        if isinstance(view, dict)
    }
    return {
        "kind": "durable_memory_context",
        "enabled": True,
        "total": result.get("total", len(items)),
        "combined_memory_ids": [
            str(memory_id)
            for memory_id in list((result.get("combined") or {}).get("memory_ids") or [])[:16]
            if memory_id
        ] if isinstance(result.get("combined"), dict) else [str(item.get("memory_id")) for item in items[:16] if item.get("memory_id")],
        "view_totals": {label: view.get("total", 0) for label, view in view_contexts.items()},
        "views": view_contexts,
        "top_items": [_durable_memory_item_context(item) for item in items[:3]],
        "active_recall_hint": (
            "Use paged memory summaries when they cover the task; otherwise propose memory.recall if available."
        ),
        "host_boundary": (
            "Passive scoped memory snapshot; safe summaries and refs only; no memory writes."
        ),
    }


def _durable_memory_view_context(view: JsonObject) -> JsonObject:
    items = [item for item in view.get("items", []) if isinstance(item, dict)]
    return {
        "label": view.get("label"),
        "total": view.get("total", len(items)),
        "memory_ids": [str(item.get("memory_id")) for item in items[:12] if item.get("memory_id")],
        "kinds": _ordered_unique([str(item.get("kind")) for item in items if item.get("kind")]),
        "filtered": dict(view.get("filtered", {})) if isinstance(view.get("filtered"), dict) else {},
    }


def _durable_memory_item_context(item: JsonObject) -> JsonObject:
    structured_summary = item.get("structured_summary") if isinstance(item.get("structured_summary"), dict) else {}
    if not structured_summary:
        structured_summary = structured_memory_summary(item.get("structured") if isinstance(item.get("structured"), dict) else {})
    payload = {
        "memory_id": item.get("memory_id"),
        "kind": item.get("kind"),
        "title": _compact_text(str(item.get("title") or ""), limit=72),
        "summary": _compact_text(str(item.get("summary") or ""), limit=120),
        "privacy_class": item.get("privacy_class"),
        "confidence": item.get("confidence"),
        "payload_hash": item.get("payload_hash"),
        "provenance_refs": list(item.get("provenance_refs", []))[:2] if isinstance(item.get("provenance_refs"), list) else [],
    }
    if structured_summary:
        payload["structured_summary"] = structured_summary
    return payload


def _durable_memory_context_budget_view(context: JsonObject) -> JsonObject:
    return {
        "kind": context.get("kind"),
        "enabled": context.get("enabled"),
        "total": context.get("total"),
        "combined_memory_ids": list(context.get("combined_memory_ids", []))[:8]
        if isinstance(context.get("combined_memory_ids"), list)
        else [],
        "view_totals": dict(context.get("view_totals", {})) if isinstance(context.get("view_totals"), dict) else {},
    }


def _durable_memory_recall_scope(*, task: TaskState, user_id: str, project_id: str) -> JsonObject:
    base_scope: JsonObject = {"user_id": user_id} if user_id else {}
    if project_id and project_id != "local":
        return {**base_scope, "project_id": project_id}
    return {**base_scope, "thread_id": task.thread_id}


def _compact_durable_memory_item(item: JsonObject) -> JsonObject:
    stable_payload = {
        "memory_id": item.get("memory_id"),
        "kind": item.get("kind"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "scope": item.get("scope"),
        "privacy_class": item.get("privacy_class"),
        "confidence": item.get("confidence"),
        "dedupe_key": item.get("dedupe_key"),
        "provenance_refs": item.get("provenance_refs"),
        "artifact_refs": item.get("artifact_refs"),
        "state": item.get("state"),
        "updated_at_ms": item.get("updated_at_ms"),
    }
    structured_summary = structured_memory_summary(item.get("structured") if isinstance(item.get("structured"), dict) else {})
    payload = {
        "memory_id": item.get("memory_id"),
        "kind": item.get("kind"),
        "title": _compact_text(str(item.get("title", "")), limit=96),
        "summary": _compact_text(str(item.get("summary", "")), limit=240),
        "scope": dict(item.get("scope", {})) if isinstance(item.get("scope"), dict) else {},
        "privacy_class": item.get("privacy_class"),
        "confidence": item.get("confidence"),
        "dedupe_key": item.get("dedupe_key"),
        "provenance_refs": list(item.get("provenance_refs", [])) if isinstance(item.get("provenance_refs"), list) else [],
        "artifact_refs": list(item.get("artifact_refs", [])) if isinstance(item.get("artifact_refs"), list) else [],
        "payload_hash": deterministic_hash(stable_payload),
    }
    if structured_summary:
        payload["structured_summary"] = structured_summary
    return payload


def _compact_tool_brief(brief: JsonObject) -> JsonObject:
    return {
        "name": brief.get("name"),
        "side_effect": brief.get("side_effect"),
        "input_schema": brief.get("input_schema", {}),
    }


def _compact_permission_state(permission_state: JsonObject) -> JsonObject:
    return {
        "mode": permission_state.get("mode"),
        "allowed_permissions": list(permission_state.get("allowed_permissions", [])),
    }


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _event_budget_view(data: JsonObject) -> JsonObject:
    payload = data.get("payload")
    if isinstance(payload, dict):
        return {"event_id": data.get("event_id"), "payload": payload}
    if isinstance(data.get("text"), str):
        return {"event_id": data.get("event_id"), "payload": {"text": data.get("text")}}
    return {"event_id": data.get("event_id"), "payload": payload}


def _agent_trace_budget_view(record: LedgerRecord) -> JsonObject:
    data = record.data if isinstance(record.data, dict) else {}
    kind = record.kind
    budget_view: JsonObject = {
        "r": record.record_id,
        "s": record.step_id,
        "k": kind,
    }
    if record.action_ref:
        budget_view["a"] = record.action_ref
    if record.observation_ref:
        budget_view["o"] = record.observation_ref
    if record.feedback_ref:
        budget_view["f"] = record.feedback_ref
    if kind == "assistant_turn":
        raw_calls = data.get("tool_calls") if isinstance(data.get("tool_calls"), list) else []
        budget_view["t"] = [
            {
                "id": item.get("tool_call_id") or item.get("id"),
                "n": item.get("name") or item.get("tool"),
            }
            for item in raw_calls[:6]
            if isinstance(item, dict)
        ]
    elif kind == "action":
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        budget_view["n"] = data.get("name")
        budget_view["pk"] = [str(key) for key in payload.keys()][:12]
    elif kind == "observation":
        budget_view["st"] = data.get("status")
        budget_view["src"] = data.get("source")
    elif kind == "feedback":
        budget_view["st"] = data.get("status")
        missing = data.get("missing_evidence") if isinstance(data.get("missing_evidence"), list) else []
        budget_view["m"] = [str(item) for item in missing[:8]]
    elif kind == "tool_execution_event":
        budget_view["e"] = data.get("event_type")
        budget_view["tc"] = data.get("tool_call_id")
        budget_view["tn"] = data.get("tool_name")
        budget_view["st"] = data.get("status")
    elif kind in {"policy_decision", "result", "guard"}:
        budget_view["st"] = data.get("status")
        budget_view["reason"] = data.get("reason") or data.get("stop_reason")
    return budget_view


def _observation_budget_view(data: JsonObject) -> JsonObject:
    content = data.get("content")
    if data.get("kind") == "tool_batch_result" and isinstance(content, dict):
        content_view = _tool_batch_budget_view(content)
    elif isinstance(content, dict):
        content_view = _compact_content(content)
    elif isinstance(content, str):
        content_view = {"text": content}
    else:
        content_view = {"value": content}
    return {
        "observation_id": data.get("observation_id"),
        "content": content_view,
    }


def _tool_batch_budget_view(content: JsonObject) -> JsonObject:
    raw_results = content.get("results")
    results = raw_results if isinstance(raw_results, list) else []
    return {
        "schema": content.get("schema"),
        "tool_call_count": content.get("tool_call_count"),
        "results": [
            {
                "tool": item.get("tool"),
                "status": item.get("status"),
                "kind": item.get("kind"),
                "projection": _compact_content_projection(
                    item.get("content_projection") if isinstance(item.get("content_projection"), dict) else {}
                ),
                "replacement": _compact_tool_result_replacement(item.get("content_replacement"))
                if isinstance(item.get("content_replacement"), dict)
                else {},
            }
            for item in results[:16]
            if isinstance(item, dict)
        ],
    }


def _artifact_budget_view(artifact_id: str, artifact) -> JsonObject:
    if artifact is None:
        return {"artifact_id": artifact_id, "uri": f"journal://artifacts/{artifact_id}", "payload_hash": ""}
    data = artifact.to_dict()
    return {
        "artifact_id": data.get("artifact_id"),
        "uri": data.get("uri"),
        "payload_hash": data.get("payload_hash"),
        "metadata": data.get("metadata", {}),
    }


def _evidence_budget_view(item) -> JsonObject:
    return {
        "observation_id": item.observation_id,
        "record_ref": item.record_ref,
        "artifact_refs": list(item.artifact_refs),
    }


def _citation_budget_view(item) -> JsonObject:
    return {
        "citation_id": item.citation_id,
        "record_ref": item.record_ref,
        "artifact_ref": item.artifact_ref,
        "uri": item.uri,
    }


def _durable_memory_budget_view(item: JsonObject) -> JsonObject:
    return {
        "memory_id": item.get("memory_id"),
        "kind": item.get("kind"),
        "summary": item.get("summary"),
        "provenance_refs": list(item.get("provenance_refs", [])) if isinstance(item.get("provenance_refs"), list) else [],
    }
