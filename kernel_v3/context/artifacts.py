from __future__ import annotations

import json
from pathlib import Path

from kernel_v3.contracts import ArtifactRef


class ArtifactStore:
    def __init__(self, path: Path | str | None = None, artifacts: list[ArtifactRef] | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._artifacts: dict[str, ArtifactRef] = {}
        if artifacts:
            for artifact in artifacts:
                self._artifacts[artifact.artifact_id] = artifact
        if self.path is not None and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    artifact = ArtifactRef.from_dict(json.loads(line))
                    self._artifacts[artifact.artifact_id] = artifact

    @classmethod
    def in_memory(cls, artifacts: list[ArtifactRef] | None = None) -> "ArtifactStore":
        return cls(artifacts=artifacts or [])

    def put(self, artifact: ArtifactRef) -> None:
        self._artifacts[artifact.artifact_id] = artifact
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(artifact.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def get(self, artifact_id: str) -> ArtifactRef | None:
        return self._artifacts.get(artifact_id)

    def list(self) -> list[ArtifactRef]:
        return [self._artifacts[key] for key in sorted(self._artifacts)]

    def resolve_many(self, artifact_ids: list[str]) -> list[ArtifactRef]:
        return [artifact for artifact_id in artifact_ids if (artifact := self.get(artifact_id)) is not None]
