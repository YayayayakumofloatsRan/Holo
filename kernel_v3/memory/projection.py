from __future__ import annotations

import hashlib
import json

from kernel_v3.contracts import JsonObject
from kernel_v3.memory.contracts import MemoryItem, MemoryProposal, MemoryTombstone, ShadowCandidate


MEMORY_TEXT_PREVIEW_CHARS = 160
MEMORY_MANIFEST_KEY_CAP = 40


def shadow_candidate_event(candidate: ShadowCandidate) -> JsonObject:
    return {
        "candidate_id": candidate.candidate_id,
        "source_kind": candidate.source_kind,
        "normalized_topic": candidate.normalized_topic,
        "required_capabilities": list(candidate.required_capabilities),
        "blocked_capabilities": list(candidate.blocked_capabilities),
        "status": candidate.status,
        "expires_at_ms": candidate.expires_at_ms,
        "created_at_ms": candidate.created_at_ms,
        **_text_projection(prefix="candidate_text", text=candidate.candidate_text),
        "metadata": _json_object_manifest(candidate.metadata),
        "redaction": {"candidate_text": "preview_hash_only", "metadata": "manifest_only"},
    }


def memory_proposal_event(proposal: MemoryProposal) -> JsonObject:
    proposed = proposal.proposed_item
    return {
        "proposal_id": proposal.proposal_id,
        "candidate_id": proposal.candidate_id,
        "operation": proposal.operation,
        "source_task_id": proposal.source_task_id,
        "source_run_id": proposal.source_run_id,
        "source_thread_id": proposal.source_thread_id,
        "evidence_record_refs": list(proposal.evidence_record_refs),
        "artifact_refs": list(proposal.artifact_refs),
        "risk_flags": list(proposal.risk_flags),
        "approval_policy": proposal.approval_policy,
        "approval_status": proposal.approval_status,
        "review_nonblocking": proposal.metadata.get("review_nonblocking") is True,
        "source_proposal_ids": _string_list(proposal.metadata.get("source_proposal_ids"))[:16],
        "source_proposal_count": proposal.metadata.get("source_proposal_count"),
        "confidence": proposal.confidence,
        "created_at_ms": proposal.created_at_ms,
        "decided_at_ms": proposal.decided_at_ms,
        "proposed_item": _proposed_item_manifest(proposed),
        **_text_projection(prefix="rationale", text=proposal.rationale),
        "metadata": _json_object_manifest(proposal.metadata),
        "redaction": {
            "proposed_item": "manifest_only",
            "rationale": "preview_hash_only",
            "metadata": "manifest_only",
        },
    }


def memory_item_event(item: MemoryItem) -> JsonObject:
    return {
        "memory_id": item.memory_id,
        "kind": item.kind,
        "structured": _json_object_manifest(item.structured),
        "scope": dict(item.scope),
        "privacy_class": item.privacy_class,
        "confidence": item.confidence,
        "ttl_policy": item.ttl_policy,
        "expires_at_ms": item.expires_at_ms,
        "dedupe_key": item.dedupe_key,
        "conflict_keys": list(item.conflict_keys),
        "provenance_refs": list(item.provenance_refs),
        "artifact_refs": list(item.artifact_refs),
        "state": item.state,
        "approved_by": item.approved_by,
        "created_at_ms": item.created_at_ms,
        "updated_at_ms": item.updated_at_ms,
        "last_accessed_ms": item.last_accessed_ms,
        **_text_projection(prefix="title", text=item.title),
        **_text_projection(prefix="summary", text=item.summary),
        **_text_projection(prefix="body", text=item.body),
        "metadata": _json_object_manifest(item.metadata),
        "redaction": {
            "title": "preview_hash_only",
            "summary": "preview_hash_only",
            "body": "preview_hash_only",
            "structured": "manifest_only",
            "metadata": "manifest_only",
        },
    }


def memory_tombstone_event(tombstone: MemoryTombstone) -> JsonObject:
    return {
        "tombstone_id": tombstone.tombstone_id,
        "memory_id": tombstone.memory_id,
        "reason": tombstone.reason[:MEMORY_TEXT_PREVIEW_CHARS],
        "deleted_by": tombstone.deleted_by,
        "deleted_at_ms": tombstone.deleted_at_ms,
        "provenance_refs": list(tombstone.provenance_refs),
        **_text_projection(prefix="reason", text=tombstone.reason),
        "metadata": _json_object_manifest(tombstone.metadata),
        "redaction": {"reason": "preview_hash_only", "metadata": "manifest_only"},
    }


def _proposed_item_manifest(payload: JsonObject) -> JsonObject:
    return {
        "memory_id": payload.get("memory_id"),
        "kind": payload.get("kind"),
        "scope": dict(payload.get("scope") or {}) if isinstance(payload.get("scope"), dict) else {},
        "privacy_class": payload.get("privacy_class"),
        "confidence": payload.get("confidence"),
        "ttl_policy": payload.get("ttl_policy"),
        "expires_at_ms": payload.get("expires_at_ms"),
        "dedupe_key": payload.get("dedupe_key"),
        "conflict_keys": _string_list(payload.get("conflict_keys")),
        "provenance_refs": _string_list(payload.get("provenance_refs")),
        "artifact_refs": _string_list(payload.get("artifact_refs")),
        "state": payload.get("state"),
        "approved_by": payload.get("approved_by"),
        "created_at_ms": payload.get("created_at_ms"),
        "updated_at_ms": payload.get("updated_at_ms"),
        "last_accessed_ms": payload.get("last_accessed_ms"),
        **_text_projection(prefix="title", text=str(payload.get("title") or "")),
        **_text_projection(prefix="summary", text=str(payload.get("summary") or "")),
        **_text_projection(prefix="body", text=str(payload.get("body") or "")),
        "structured": _json_object_manifest(payload.get("structured") if isinstance(payload.get("structured"), dict) else {}),
        "metadata": _json_object_manifest(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        "redaction": {
            "title": "preview_hash_only",
            "summary": "preview_hash_only",
            "body": "preview_hash_only",
            "structured": "manifest_only",
            "metadata": "manifest_only",
        },
    }


def _text_projection(*, prefix: str, text: str) -> JsonObject:
    return {
        f"{prefix}_preview": text[:MEMORY_TEXT_PREVIEW_CHARS],
        f"{prefix}_length": len(text),
        f"{prefix}_hash": _hash_text(text),
        f"{prefix}_truncated": len(text) > MEMORY_TEXT_PREVIEW_CHARS,
    }


def _json_object_manifest(payload: JsonObject) -> JsonObject:
    sorted_items = sorted(((str(key), value) for key, value in payload.items()), key=lambda item: item[0])
    visible_items = sorted_items[:MEMORY_MANIFEST_KEY_CAP]
    return {
        "key_count": len(sorted_items),
        "keys": [key for key, _value in visible_items],
        "keys_truncated": len(sorted_items) > MEMORY_MANIFEST_KEY_CAP,
        "hash": _hash_json(payload),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _hash_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash_text(encoded)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
