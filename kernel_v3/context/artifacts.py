from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from kernel_v3.contracts import ArtifactRef


@dataclass(frozen=True, kw_only=True)
class ArtifactBlob:
    artifact_id: str
    kind: str
    mime_type: str
    payload_hash: str
    size_bytes: int
    storage_uri: str
    preview: str
    redaction_status: str
    payload_encoding: str
    payload: str
    metadata: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactBlob":
        return cls(
            artifact_id=str(data["artifact_id"]),
            kind=str(data["kind"]),
            mime_type=str(data["mime_type"]),
            payload_hash=str(data["payload_hash"]),
            size_bytes=int(data["size_bytes"]),
            storage_uri=str(data["storage_uri"]),
            preview=str(data["preview"]),
            redaction_status=str(data.get("redaction_status", "unredacted")),
            payload_encoding=str(data.get("payload_encoding", "utf-8")),
            payload=str(data["payload"]),
            metadata=dict(data.get("metadata", {})),
        )


class ArtifactStore:
    def __init__(self, path: Path | str | None = None, artifacts: list[ArtifactRef] | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._artifacts: dict[str, ArtifactRef] = {}
        self._blobs: dict[str, ArtifactBlob] = {}
        if artifacts:
            for artifact in artifacts:
                self._artifacts[artifact.artifact_id] = artifact
        if self.path is not None and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    raw = json.loads(line)
                    if raw.get("record_type") == "artifact_blob":
                        blob = ArtifactBlob.from_dict(raw["blob"])
                        self._blobs[blob.artifact_id] = blob
                        artifact = ArtifactRef.from_dict(raw["artifact"])
                        self._artifacts[artifact.artifact_id] = artifact
                        continue
                    artifact_data = raw.get("artifact", raw)
                    artifact = ArtifactRef.from_dict(artifact_data)
                    self._artifacts[artifact.artifact_id] = artifact

    @classmethod
    def in_memory(cls, artifacts: list[ArtifactRef] | None = None) -> "ArtifactStore":
        return cls(artifacts=artifacts or [])

    def put(self, artifact: ArtifactRef) -> None:
        self._artifacts[artifact.artifact_id] = artifact
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"record_type": "artifact_ref", "artifact": artifact.to_dict()},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )

    def write_blob(
        self,
        *,
        kind: str,
        payload: str | bytes,
        mime_type: str = "text/plain",
        metadata: dict[str, object] | None = None,
        redaction_status: str = "unredacted",
    ) -> ArtifactRef:
        payload_bytes, payload_text, payload_encoding = _encode_payload(payload)
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()
        artifact_id = f"artifact-{payload_hash[:16]}"
        preview_text = _preview_text(payload_text, limit=256)
        blob = ArtifactBlob(
            artifact_id=artifact_id,
            kind=kind,
            mime_type=mime_type,
            payload_hash=payload_hash,
            size_bytes=len(payload_bytes),
            storage_uri=f"artifact-blob://{artifact_id}",
            preview=preview_text,
            redaction_status=redaction_status,
            payload_encoding=payload_encoding,
            payload=payload_text if payload_encoding == "utf-8" else base64.b64encode(payload_bytes).decode("ascii"),
            metadata=dict(metadata or {}),
        )
        ref_metadata = {
            **dict(metadata or {}),
            "mime_type": mime_type,
            "size_bytes": blob.size_bytes,
            "preview": preview_text,
            "redaction_status": redaction_status,
        }
        ref = ArtifactRef(
            artifact_id=artifact_id,
            kind=kind,
            uri=blob.storage_uri,
            payload_hash=payload_hash,
            metadata=ref_metadata,
        )
        self._artifacts[artifact_id] = ref
        self._blobs[artifact_id] = blob
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "record_type": "artifact_blob",
                            "artifact": ref.to_dict(),
                            "blob": blob.to_dict(),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
        return ref

    def read_blob(self, artifact_id: str) -> str | bytes:
        blob = self._require_blob(artifact_id)
        if blob.payload_encoding == "utf-8":
            return blob.payload
        return base64.b64decode(blob.payload.encode("ascii"))

    def preview(self, artifact_id: str, *, limit: int = 256) -> dict[str, object]:
        blob = self._require_blob(artifact_id)
        payload = self.read_blob(artifact_id)
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
        return {
            "artifact_id": blob.artifact_id,
            "kind": blob.kind,
            "mime_type": blob.mime_type,
            "size_bytes": blob.size_bytes,
            "preview": _preview_text(text, limit=limit),
            "redaction_status": blob.redaction_status,
        }

    def get(self, artifact_id: str) -> ArtifactRef | None:
        return self._artifacts.get(artifact_id)

    def has_blob(self, artifact_id: str) -> bool:
        return artifact_id in self._blobs

    def list(self) -> list[ArtifactRef]:
        return [self._artifacts[key] for key in sorted(self._artifacts)]

    def resolve_many(self, artifact_ids: list[str]) -> list[ArtifactRef]:
        return [artifact for artifact_id in artifact_ids if (artifact := self.get(artifact_id)) is not None]

    def _require_blob(self, artifact_id: str) -> ArtifactBlob:
        blob = self._blobs.get(artifact_id)
        if blob is None:
            raise KeyError(f"unknown artifact blob: {artifact_id}")
        return blob


def _encode_payload(payload: str | bytes) -> tuple[bytes, str, str]:
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            return payload, "", "base64"
        return payload, text, "utf-8"
    return payload.encode("utf-8"), payload, "utf-8"


def _preview_text(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."
