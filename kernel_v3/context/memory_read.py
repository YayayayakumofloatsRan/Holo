from __future__ import annotations

import json
from dataclasses import dataclass

from kernel_v3.context.artifacts import ArtifactStore
from kernel_v3.contracts import ArtifactRef, JsonObject
from kernel_v3.journal import JournalStore


@dataclass(frozen=True, kw_only=True)
class EvidenceItem:
    observation_id: str
    record_ref: str
    task_id: str | None
    run_id: str
    step_id: str | None
    content: JsonObject
    artifact_refs: list[str]

    def to_dict(self) -> JsonObject:
        return {
            "observation_id": self.observation_id,
            "record_ref": self.record_ref,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "content": self.content,
            "artifact_refs": self.artifact_refs,
        }


class MemoryRead:
    def __init__(self, *, journal: JournalStore, artifact_store: ArtifactStore | None = None) -> None:
        self.journal = journal
        self.artifact_store = artifact_store or ArtifactStore.in_memory()

    def query_observations(
        self,
        *,
        query: str = "",
        task_id: str | None = None,
        limit: int = 5,
    ) -> list[EvidenceItem]:
        query_text = query.lower()
        matches: list[EvidenceItem] = []
        for record in self.journal.records(task_id=task_id, kind="observation"):
            encoded = json.dumps(record.data, ensure_ascii=False, sort_keys=True).lower()
            if query_text and query_text not in encoded:
                continue
            observation_id = str(record.data.get("observation_id", record.observation_ref or ""))
            matches.append(
                EvidenceItem(
                    observation_id=observation_id,
                    record_ref=record.record_id,
                    task_id=record.task_id,
                    run_id=record.run_id,
                    step_id=record.step_id,
                    content=record.data,
                    artifact_refs=list(record.artifact_refs),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    def query_artifacts(self, *, query: str = "", limit: int = 5) -> list[ArtifactRef]:
        query_text = query.lower()
        matches: list[ArtifactRef] = []
        for artifact in self.artifact_store.list():
            encoded = json.dumps(artifact.to_dict(), ensure_ascii=False, sort_keys=True).lower()
            if query_text and query_text not in encoded:
                continue
            matches.append(artifact)
            if len(matches) >= limit:
                break
        return matches
