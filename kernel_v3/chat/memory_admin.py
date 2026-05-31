from __future__ import annotations

from kernel_v3.contracts import JsonObject


def memory_list_text(payload: JsonObject) -> str:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return "No active durable memory for this thread."
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(f"{item.get('memory_id')}: {item.get('summary')}")
    return "\n".join(lines) or "No active durable memory for this thread."


def memory_recall_command_result(payload: JsonObject) -> JsonObject:
    items = payload.get("items")
    items = items if isinstance(items, list) else []
    return {
        "total": payload.get("total", 0),
        "filtered": payload.get("filtered") if isinstance(payload.get("filtered"), dict) else {},
        "generated_at_ms": payload.get("generated_at_ms"),
        "items": [memory_item_command_preview(item) for item in items if isinstance(item, dict)],
        "redaction": {
            "item_body": "not_journaled",
            "item_structured": "not_journaled",
            "item_metadata": "not_journaled",
        },
    }


def memory_item_command_preview(item: JsonObject) -> JsonObject:
    return {
        "memory_id": item.get("memory_id"),
        "kind": item.get("kind"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "scope": item.get("scope") if isinstance(item.get("scope"), dict) else {},
        "privacy_class": item.get("privacy_class"),
        "confidence": item.get("confidence"),
        "ttl_policy": item.get("ttl_policy"),
        "expires_at_ms": item.get("expires_at_ms"),
        "state": item.get("state"),
        "provenance_refs": item.get("provenance_refs") if isinstance(item.get("provenance_refs"), list) else [],
        "artifact_refs": item.get("artifact_refs") if isinstance(item.get("artifact_refs"), list) else [],
        "last_accessed_ms": item.get("last_accessed_ms"),
    }


def proposal_list_text(payload: JsonObject) -> str:
    proposals = payload.get("proposals")
    if not isinstance(proposals, list) or not proposals:
        return "No pending durable memory proposals for this thread."
    lines = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        lines.append(
            f"{proposal.get('proposal_id')}: "
            f"{proposal.get('approval_status')} {proposal.get('approval_policy')}"
        )
    return "\n".join(lines) or "No pending durable memory proposals for this thread."


def memory_proposals_command_result(payload: JsonObject) -> JsonObject:
    proposals = payload.get("proposals")
    proposals = proposals if isinstance(proposals, list) else []
    return {
        "proposals": [
            memory_proposal_command_preview(proposal)
            for proposal in proposals
            if isinstance(proposal, dict)
        ],
        "redaction": {"proposed_item_body": "not_journaled", "proposal_metadata": "not_journaled"},
    }


def memory_proposal_command_preview(proposal: JsonObject) -> JsonObject:
    proposed_item = proposal.get("proposed_item")
    proposed_item = proposed_item if isinstance(proposed_item, dict) else {}
    return {
        "proposal_id": proposal.get("proposal_id"),
        "candidate_id": proposal.get("candidate_id"),
        "operation": proposal.get("operation"),
        "approval_policy": proposal.get("approval_policy"),
        "approval_status": proposal.get("approval_status"),
        "confidence": proposal.get("confidence"),
        "source_task_id": proposal.get("source_task_id"),
        "source_run_id": proposal.get("source_run_id"),
        "source_thread_id": proposal.get("source_thread_id"),
        "risk_flags": proposal.get("risk_flags") if isinstance(proposal.get("risk_flags"), list) else [],
        "proposed_item": memory_item_command_preview(proposed_item),
    }


def memory_pipeline_command_result(payload: JsonObject) -> JsonObject:
    shadow_candidates = payload.get("shadow_candidates")
    proposals = payload.get("proposals")
    committed_items = payload.get("committed_items")
    rejected = payload.get("rejected")
    shadow_candidates = shadow_candidates if isinstance(shadow_candidates, list) else []
    proposals = proposals if isinstance(proposals, list) else []
    committed_items = committed_items if isinstance(committed_items, list) else []
    rejected = rejected if isinstance(rejected, list) else []
    return {
        "shadow_candidate_ids": [
            candidate.get("candidate_id")
            for candidate in shadow_candidates
            if isinstance(candidate, dict) and candidate.get("candidate_id")
        ],
        "proposals": [
            memory_proposal_command_preview(proposal)
            for proposal in proposals
            if isinstance(proposal, dict)
        ],
        "committed_items": [
            memory_item_command_preview(item)
            for item in committed_items
            if isinstance(item, dict)
        ],
        "rejected": [item for item in rejected if isinstance(item, dict)],
        "redaction": {
            "candidate_text": "not_journaled",
            "proposed_item_body": "not_journaled",
            "committed_item_body": "not_journaled",
        },
    }


def memory_export_command_result(payload: JsonObject) -> JsonObject:
    item = payload.get("item")
    item = item if isinstance(item, dict) else {}
    proposals = payload.get("proposals")
    audit_records = payload.get("audit_records")
    return {
        "memory_id": payload.get("memory_id"),
        "item": memory_item_command_preview(item),
        "proposal_count": len(proposals) if isinstance(proposals, list) else 0,
        "has_tombstone": isinstance(payload.get("tombstone"), dict),
        "audit_record_count": len(audit_records) if isinstance(audit_records, list) else 0,
        "redaction": {"export_payload": "not_journaled"},
    }


def memory_inspection_text(payload: JsonObject) -> str:
    proposal_counts = payload.get("proposal_counts")
    proposal_counts = proposal_counts if isinstance(proposal_counts, dict) else {}
    actions = payload.get("recommended_actions")
    actions = actions if isinstance(actions, list) else []
    return "\n".join(
        [
            f"Memory status: {payload.get('status')}",
            f"Active: {payload.get('active_count', 0)}",
            f"Pending proposals: {proposal_counts.get('pending', 0)}",
            f"Deleted: {payload.get('deleted_count', 0)}",
            f"Expired: {payload.get('expired_count', 0)}",
            "Recommended actions: " + (", ".join(str(action) for action in actions) if actions else "none"),
        ]
    )
