from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass

from kernel_v3.context.artifacts import ArtifactStore
from kernel_v3.context.budgeter import BudgetExceeded, measure_units, validate_section_budget
from kernel_v3.context.memory_read import MemoryRead
from kernel_v3.context.redaction import Redactor
from kernel_v3.context.validator import deterministic_hash
from kernel_v3.contracts import ContextBundle, JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.session import TaskState


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
        artifact_ids: list[str] = []
        for record in observation_records:
            artifact_ids.extend(record.artifact_refs)
        artifact_ids = _ordered_unique(artifact_ids)
        resolved_artifacts = {artifact.artifact_id: artifact for artifact in self.artifact_store.resolve_many(artifact_ids)}
        evidence = memory_read.query_observations(task_id=task.task_id, limit=3, order="recent")
        citations = memory_read.query_citations(task_id=task.task_id, limit=3, order="recent")
        memory_refs = [item.observation_id for item in evidence]
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
        redacted_sections, redactions = self.redactor.redact(sections)
        section_units, compacted_section_names = self._enforce_section_budgets(redacted_sections, budget_views)
        total_units = sum(section_units)
        if total_units > self.token_budget:
            if self.budget_mode == "fail":
                raise BudgetExceeded("bundle", total_units, self.token_budget)
            total_units = self._truncate_bundle(redacted_sections, section_units, total_units, compacted_section_names)
        source_refs = [record.record_id for record in event_records[-1:] + observation_records]
        source_refs.extend(artifact_ids)
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
        droppable = ["tool_briefs", "citations", "memory_refs", "recent_observations", "project_profile"]
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
        elif name == "citations":
            items = section.get("items")
            if isinstance(items, list):
                del items[1:]
        elif name == "tool_briefs":
            tools = section.get("tools")
            if isinstance(tools, list):
                del tools[1:]
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
        elif name == "citations":
            items = section.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        item["quote"] = _compact_text(str(item.get("quote", "")), limit=8)

    @staticmethod
    def from_dict(data: JsonObject) -> ContextPack:
        return ContextPack(**data)


class ContextCompiler:
    def compile(self, task: TaskState, journal: JournalStore) -> ContextBundle:
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
                "sections": pack.sections,
                "source_refs": pack.source_refs,
                "redactions": pack.redactions,
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


def _compact_observation(data: JsonObject) -> JsonObject:
    content = data.get("content")
    compacted: JsonObject = {
        "observation_id": data.get("observation_id"),
        "kind": data.get("kind"),
        "status": data.get("status"),
        "source": data.get("source"),
    }
    if isinstance(content, dict):
        compacted["content"] = _compact_content(content)
    else:
        compacted["content"] = content
    return compacted


def _compact_content(content: JsonObject) -> JsonObject:
    compacted: JsonObject = {}
    for key, value in content.items():
        if isinstance(value, str):
            compacted[key] = _compact_text(value, limit=256)
        else:
            compacted[key] = value
    return compacted


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


def _compact_tool_brief(brief: JsonObject) -> JsonObject:
    return {
        "name": brief.get("name"),
        "side_effect": brief.get("side_effect"),
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


def _observation_budget_view(data: JsonObject) -> JsonObject:
    content = data.get("content")
    if isinstance(content, dict):
        content_view = {key: value for key, value in content.items() if isinstance(value, str)}
    elif isinstance(content, str):
        content_view = {"text": content}
    else:
        content_view = {"value": content}
    return {
        "observation_id": data.get("observation_id"),
        "content": content_view,
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
