from __future__ import annotations

from dataclasses import replace

import pytest

from kernel_v3.memory import (
    MemoryItem,
    MemoryPrivacyError,
    MemoryProposal,
    MemoryStore,
    ShadowCandidate,
    stable_candidate_id,
    stable_memory_id,
    stable_proposal_id,
)


def test_phase7_memory_store_commits_lists_and_recalls_active_items():
    store = MemoryStore.in_memory(clock_ms=lambda: 1000)
    item = _memory_item(summary="User prefers concise Chinese answers.")

    committed = store.commit(item)
    recalled = store.recall(query="Chinese", scope={"user_id": "local:user"}, now_ms=1000)

    assert committed == item
    assert store.list_items(scope={"user_id": "local:user"}, now_ms=1000) == [item]
    assert recalled.total == 1
    assert recalled.items[0]["memory_id"] == item.memory_id
    assert recalled.filtered == {"expired": 0, "deleted": 0, "sensitive": 0, "scope": 0, "query": 0}


def test_phase7_memory_store_rebuilds_index_and_state_from_append_only_log(tmp_path):
    log_path = tmp_path / "memory_log.jsonl"
    index_path = tmp_path / "memory_index.sqlite3"
    item = _memory_item(summary="Project uses kernel-v3 branch for harness work.")
    first = MemoryStore(log_path, index_path=index_path, clock_ms=lambda: 1000)

    first.commit(item)
    assert first.index_items()[0]["memory_id"] == item.memory_id

    index_path.unlink()
    rebuilt = MemoryStore(log_path, index_path=index_path, clock_ms=lambda: 2000)

    assert rebuilt.recall(query="kernel-v3", scope={"user_id": "local:user"}, now_ms=2000).total == 1
    assert rebuilt.index_items()[0]["memory_id"] == item.memory_id
    assert rebuilt.audit_records()[0]["event_type"] == "memory_item_committed"


def test_phase7_memory_ttl_excludes_expired_items_from_default_recall():
    store = MemoryStore.in_memory(clock_ms=lambda: 1000)
    item = _memory_item(summary="Temporary task fact.", ttl_policy="expires_at", expires_at_ms=1500)

    store.commit(item)

    assert store.recall(query="temporary", now_ms=1200).total == 1
    assert store.recall(query="temporary", now_ms=1600).total == 0
    assert store.list_items(include_inactive=True, now_ms=1600) == [item]


def test_phase7_memory_tombstone_hides_item_but_preserves_audit():
    store = MemoryStore.in_memory(clock_ms=lambda: 1000)
    item = _memory_item(summary="Delete this preference later.")

    store.commit(item)
    tombstone = store.delete(item.memory_id, reason="user_requested_delete", deleted_at_ms=1200)

    assert tombstone.memory_id == item.memory_id
    assert store.recall(query="delete", now_ms=1300).total == 0
    assert store.get(item.memory_id, include_inactive=True).state == "deleted"
    assert [event["event_type"] for event in store.audit_records()] == [
        "memory_item_committed",
        "memory_tombstone_created",
    ]


def test_phase7_memory_store_rejects_secret_like_content_without_audit_write():
    store = MemoryStore.in_memory(clock_ms=lambda: 1000)
    item = _memory_item(
        summary="Accidental credential.",
        body="api_key=sk-this-secret-value-should-not-be-stored",
    )

    with pytest.raises(MemoryPrivacyError):
        store.commit(item)

    assert store.audit_records() == []
    assert store.recall(query="credential", now_ms=1000).total == 0


def test_phase7_memory_store_only_commits_active_approved_items():
    store = MemoryStore.in_memory(clock_ms=lambda: 1000)
    item = _memory_item(summary="Committed memory must be approved.")

    with pytest.raises(ValueError, match="invalid_memory_commit_state"):
        store.commit(replace(item, state="pending"))
    with pytest.raises(ValueError, match="memory_commit_requires_approval"):
        store.commit(replace(item, approved_by=None))

    assert store.audit_records() == []
    assert store.recall(query="approved", now_ms=1000).total == 0


def test_phase7_memory_store_duplicate_stable_id_is_idempotent():
    store = MemoryStore.in_memory(clock_ms=lambda: 1000)
    item = _memory_item(summary="Stable duplicate item.")

    first = store.commit(item)
    second = store.commit(item)

    assert first == second
    assert len(store.audit_records()) == 1
    changed = _memory_item(memory_id=item.memory_id, summary="Changed value for same id.")
    with pytest.raises(ValueError, match="memory_id_conflict"):
        store.commit(changed)


def test_phase7_memory_store_records_shadow_candidates_and_proposals_idempotently():
    store = MemoryStore.in_memory(clock_ms=lambda: 1000)
    candidate_payload = {"source": "semantic_intake", "text": "remember concise Chinese"}
    candidate = ShadowCandidate(
        candidate_id=stable_candidate_id(candidate_payload),
        source_kind="semantic_intake",
        candidate_text="remember concise Chinese",
        normalized_topic="response_style",
        required_capabilities=["durable_memory:write"],
        blocked_capabilities=[],
        status="open",
        expires_at_ms=None,
        created_at_ms=1000,
        metadata={"source_record_ref": "ledger-1"},
    )
    proposal_payload = {"candidate_id": candidate.candidate_id, "operation": "upsert"}
    proposal = MemoryProposal(
        proposal_id=stable_proposal_id(proposal_payload),
        candidate_id=candidate.candidate_id,
        operation="upsert",
        proposed_item=_memory_item(summary="User prefers concise Chinese answers.").to_dict(),
        rationale="explicit user preference",
        source_task_id="task-1",
        source_run_id="run-1",
        source_thread_id="local:default",
        evidence_record_refs=["ledger-1"],
        artifact_refs=[],
        risk_flags=[],
        approval_policy="needs_review",
        approval_status="pending",
        confidence=0.9,
        created_at_ms=1000,
        decided_at_ms=None,
        metadata={},
    )

    assert store.record_shadow_candidate(candidate) == candidate
    assert store.record_shadow_candidate(candidate) == candidate
    assert store.record_proposal(proposal) == proposal
    assert store.record_proposal(proposal) == proposal
    assert store.shadow_candidates() == [candidate]
    assert store.proposals() == [proposal]
    assert [event["event_type"] for event in store.audit_records()] == [
        "shadow_candidate_recorded",
        "memory_proposal_recorded",
    ]


def _memory_item(
    *,
    memory_id: str | None = None,
    summary: str,
    body: str = "",
    ttl_policy: str = "forever",
    expires_at_ms: int | None = None,
) -> MemoryItem:
    scope = {"user_id": "local:user", "project_id": "holo-kernel-v3"}
    dedupe_key = "preference:response_style"
    return MemoryItem(
        memory_id=memory_id or stable_memory_id(kind="user_preference", scope=scope, dedupe_key=dedupe_key, summary=summary),
        kind="user_preference",
        title="Response style preference",
        summary=summary,
        body=body,
        structured={"language": "zh", "verbosity": "concise"},
        scope=scope,
        privacy_class="project_internal",
        confidence=0.9,
        ttl_policy=ttl_policy,
        expires_at_ms=expires_at_ms,
        dedupe_key=dedupe_key,
        conflict_keys=["preference:language"],
        provenance_refs=["ledger-1"],
        artifact_refs=[],
        state="active",
        approved_by="host_auto",
        created_at_ms=1000,
        updated_at_ms=1000,
        last_accessed_ms=None,
        metadata={},
    )
