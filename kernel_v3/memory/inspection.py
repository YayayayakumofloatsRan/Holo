from __future__ import annotations

from typing import TYPE_CHECKING

from kernel_v3.contracts import JsonObject
from kernel_v3.memory.contracts import MemoryItem

if TYPE_CHECKING:
    from kernel_v3.context import ArtifactStore
    from kernel_v3.journal import JournalStore


def inspect_memory_references(
    items: list[MemoryItem],
    *,
    journal: "JournalStore | None",
    artifact_store: "ArtifactStore | None",
    sample_limit: int,
) -> JsonObject:
    consistency: JsonObject = {
        "checked_journal": journal is not None,
        "checked_artifacts": artifact_store is not None,
        "active_items_checked": len(items),
        "items_without_provenance": 0,
        "provenance_refs_checked": 0,
        "missing_provenance_refs": 0,
        "artifact_refs_checked": 0,
        "missing_artifact_refs": 0,
        "missing_artifact_blobs": 0,
        "samples": {
            "items_without_provenance": [],
            "missing_provenance_refs": [],
            "missing_artifact_refs": [],
            "missing_artifact_blobs": [],
        },
    }
    samples = _sample_buckets(consistency)
    for item in sorted(items, key=lambda candidate: (candidate.created_at_ms, candidate.memory_id)):
        if not item.provenance_refs:
            consistency["items_without_provenance"] = int(consistency["items_without_provenance"]) + 1
            _append_sample(
                _sample_bucket(samples, "items_without_provenance"),
                {"memory_id": item.memory_id, "summary": item.summary},
                limit=sample_limit,
            )
        if journal is not None:
            consistency["provenance_refs_checked"] = int(consistency["provenance_refs_checked"]) + len(item.provenance_refs)
            for record_ref in item.provenance_refs:
                if _journal_has_record(journal, record_ref):
                    continue
                consistency["missing_provenance_refs"] = int(consistency["missing_provenance_refs"]) + 1
                _append_sample(
                    _sample_bucket(samples, "missing_provenance_refs"),
                    {"memory_id": item.memory_id, "record_ref": record_ref, "summary": item.summary},
                    limit=sample_limit,
                )
        if artifact_store is not None:
            consistency["artifact_refs_checked"] = int(consistency["artifact_refs_checked"]) + len(item.artifact_refs)
            for artifact_ref in item.artifact_refs:
                artifact = artifact_store.get(artifact_ref)
                if artifact is None:
                    consistency["missing_artifact_refs"] = int(consistency["missing_artifact_refs"]) + 1
                    _append_sample(
                        _sample_bucket(samples, "missing_artifact_refs"),
                        {"memory_id": item.memory_id, "artifact_ref": artifact_ref, "summary": item.summary},
                        limit=sample_limit,
                    )
                    continue
                if not artifact_store.has_blob(artifact_ref):
                    consistency["missing_artifact_blobs"] = int(consistency["missing_artifact_blobs"]) + 1
                    _append_sample(
                        _sample_bucket(samples, "missing_artifact_blobs"),
                        {"memory_id": item.memory_id, "artifact_ref": artifact_ref, "summary": item.summary},
                        limit=sample_limit,
                    )
    return consistency


def inspection_issues(consistency: JsonObject) -> list[JsonObject]:
    issues: list[JsonObject] = []
    items_without_provenance = int(consistency.get("items_without_provenance", 0))
    if items_without_provenance:
        issues.append(
            {
                "severity": "attention",
                "code": "memory_without_provenance",
                "count": items_without_provenance,
                "samples": dict(consistency.get("samples", {})).get("items_without_provenance", []),
            }
        )
    missing_provenance = int(consistency.get("missing_provenance_refs", 0))
    if missing_provenance:
        issues.append(
            {
                "severity": "error",
                "code": "missing_memory_provenance",
                "count": missing_provenance,
                "samples": dict(consistency.get("samples", {})).get("missing_provenance_refs", []),
            }
        )
    missing_artifact_refs = int(consistency.get("missing_artifact_refs", 0))
    missing_artifact_blobs = int(consistency.get("missing_artifact_blobs", 0))
    if missing_artifact_refs or missing_artifact_blobs:
        issues.append(
            {
                "severity": "error",
                "code": "missing_memory_artifacts",
                "missing_refs": missing_artifact_refs,
                "missing_blobs": missing_artifact_blobs,
                "samples": {
                    "missing_artifact_refs": dict(consistency.get("samples", {})).get("missing_artifact_refs", []),
                    "missing_artifact_blobs": dict(consistency.get("samples", {})).get("missing_artifact_blobs", []),
                },
            }
        )
    return issues


def reference_recommendations(issues: list[JsonObject]) -> list[str]:
    actions: list[str] = []
    codes = {str(issue.get("code") or "") for issue in issues}
    if "memory_without_provenance" in codes:
        actions.append("review memory provenance")
    if "missing_memory_provenance" in codes:
        actions.append("memory export <memory_id>")
    if "missing_memory_artifacts" in codes:
        actions.append("repair artifact store or delete affected memory")
    return actions


def inspection_status(*, issues: list[JsonObject], recommended_actions: list[str]) -> str:
    severities = {str(issue.get("severity") or "") for issue in issues}
    if "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    if recommended_actions:
        return "needs_review"
    return "ok"


def _append_sample(samples: object, sample: JsonObject, *, limit: int) -> None:
    if not isinstance(samples, list):
        return
    if len(samples) < max(0, limit):
        samples.append(sample)


def _sample_buckets(consistency: JsonObject) -> JsonObject:
    samples = consistency.get("samples")
    if isinstance(samples, dict):
        return samples
    samples = {}
    consistency["samples"] = samples
    return samples


def _sample_bucket(samples: JsonObject, name: str) -> list[JsonObject]:
    bucket = samples.get(name)
    if isinstance(bucket, list):
        return bucket
    bucket = []
    samples[name] = bucket
    return bucket


def _journal_has_record(journal: "JournalStore", record_id: str) -> bool:
    has_record = getattr(journal, "has_record", None)
    if callable(has_record):
        return bool(has_record(record_id))
    return any(record.record_id == record_id for record in journal.records())
