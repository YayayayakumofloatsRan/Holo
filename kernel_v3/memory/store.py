from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.memory.contracts import (
    MemoryItem,
    MemoryPrivacyError,
    MemoryProposal,
    MemoryRecallResult,
    MemoryTombstone,
    ShadowCandidate,
)
from kernel_v3.memory.privacy import validate_memory_item


def stable_memory_id(*, kind: str, scope: JsonObject, dedupe_key: str, summary: str = "") -> str:
    payload = {"kind": kind, "scope": scope, "dedupe_key": dedupe_key, "summary": summary}
    return "mem-" + _hash(payload)[:16]


def stable_proposal_id(payload: JsonObject) -> str:
    return "memprop-" + _hash(payload)[:16]


def stable_candidate_id(payload: JsonObject) -> str:
    return "memcand-" + _hash(payload)[:16]


class MemoryStore:
    SCHEMA_VERSION = 1

    def __init__(
        self,
        log_path: Path | str | None = None,
        *,
        index_path: Path | str | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.log_path = Path(log_path) if log_path is not None else None
        self.index_path = Path(index_path) if index_path is not None else None
        self.clock_ms = clock_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self._events: list[JsonObject] = []
        self._items: dict[str, MemoryItem] = {}
        self._proposals: dict[str, MemoryProposal] = {}
        self._candidates: dict[str, ShadowCandidate] = {}
        self._tombstones: dict[str, MemoryTombstone] = {}
        if self.log_path is not None and self.log_path.exists():
            self._events = [
                json.loads(line)
                for line in self.log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self._replay_events()
        if self.index_path is not None:
            self.rebuild_index()

    @classmethod
    def in_memory(cls, *, clock_ms: Callable[[], int] | None = None) -> "MemoryStore":
        return cls(clock_ms=clock_ms)

    def commit(self, item: MemoryItem) -> MemoryItem:
        decision = validate_memory_item(item)
        if not decision.allowed:
            raise MemoryPrivacyError(decision.reason)
        existing = self._items.get(item.memory_id)
        if existing is not None:
            if existing.to_dict() == item.to_dict():
                return existing
            raise ValueError(f"memory_id_conflict:{item.memory_id}")
        self._items[item.memory_id] = item
        self._append_event("memory_item_committed", item.to_dict())
        self._upsert_item_index(item)
        return item

    def record_proposal(self, proposal: MemoryProposal) -> MemoryProposal:
        existing = self._proposals.get(proposal.proposal_id)
        if existing is not None:
            if existing.to_dict() == proposal.to_dict():
                return existing
            if (
                existing.candidate_id == proposal.candidate_id
                and existing.operation == proposal.operation
                and existing.proposed_item.get("memory_id") == proposal.proposed_item.get("memory_id")
            ):
                return existing
            raise ValueError(f"memory_proposal_conflict:{proposal.proposal_id}")
        self._proposals[proposal.proposal_id] = proposal
        self._append_event("memory_proposal_recorded", proposal.to_dict())
        self._upsert_proposal_index(proposal)
        return proposal

    def proposal(self, proposal_id: str) -> MemoryProposal | None:
        return self._proposals.get(proposal_id)

    def decide_proposal(
        self,
        proposal_id: str,
        *,
        approval_status: str,
        decided_at_ms: int | None = None,
        metadata: JsonObject | None = None,
    ) -> MemoryProposal:
        if approval_status not in {"pending", "approved", "rejected", "expired"}:
            raise ValueError(f"invalid_memory_proposal_status:{approval_status}")
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"unknown proposal_id: {proposal_id}")
        timestamp = decided_at_ms if decided_at_ms is not None else self._now_ms()
        decided = replace(
            proposal,
            approval_status=approval_status,
            decided_at_ms=timestamp,
            metadata={**dict(proposal.metadata), **dict(metadata or {})},
        )
        self._proposals[proposal_id] = decided
        self._append_event("memory_proposal_decided", decided.to_dict())
        self._upsert_proposal_index(decided)
        return decided

    def record_shadow_candidate(self, candidate: ShadowCandidate) -> ShadowCandidate:
        existing = self._candidates.get(candidate.candidate_id)
        if existing is not None:
            if existing.to_dict() == candidate.to_dict():
                return existing
            if (
                existing.source_kind == candidate.source_kind
                and existing.candidate_text == candidate.candidate_text
                and existing.normalized_topic == candidate.normalized_topic
            ):
                return existing
            raise ValueError(f"shadow_candidate_conflict:{candidate.candidate_id}")
        self._candidates[candidate.candidate_id] = candidate
        self._append_event("shadow_candidate_recorded", candidate.to_dict())
        self._upsert_candidate_index(candidate)
        return candidate

    def delete(
        self,
        memory_id: str,
        *,
        reason: str,
        deleted_by: str = "user",
        deleted_at_ms: int | None = None,
        provenance_refs: list[str] | None = None,
        metadata: JsonObject | None = None,
    ) -> MemoryTombstone:
        item = self._items.get(memory_id)
        if item is None:
            raise KeyError(f"unknown memory_id: {memory_id}")
        existing = self._tombstones.get(memory_id)
        if existing is not None:
            return existing
        timestamp = deleted_at_ms if deleted_at_ms is not None else self._now_ms()
        tombstone = MemoryTombstone(
            tombstone_id="memdel-" + _hash({"memory_id": memory_id, "deleted_at_ms": timestamp})[:16],
            memory_id=memory_id,
            reason=reason,
            deleted_by=deleted_by,
            deleted_at_ms=timestamp,
            provenance_refs=list(provenance_refs or item.provenance_refs),
            metadata=dict(metadata or {}),
        )
        self._items[memory_id] = replace(item, state="deleted", updated_at_ms=timestamp)
        self._tombstones[memory_id] = tombstone
        self._append_event("memory_tombstone_created", tombstone.to_dict())
        self._upsert_item_index(self._items[memory_id])
        self._upsert_tombstone_index(tombstone)
        return tombstone

    def get(self, memory_id: str, *, include_inactive: bool = False, now_ms: int | None = None) -> MemoryItem | None:
        item = self._items.get(memory_id)
        if item is None:
            return None
        if include_inactive or self._is_recallable(item, now_ms=now_ms):
            return item
        return None

    def list_items(
        self,
        *,
        scope: JsonObject | None = None,
        include_inactive: bool = False,
        now_ms: int | None = None,
    ) -> list[MemoryItem]:
        items = []
        for item in self._items.values():
            if scope is not None and not _scope_matches(item.scope, scope):
                continue
            if include_inactive or self._is_recallable(item, now_ms=now_ms):
                items.append(item)
        return sorted(items, key=lambda item: (item.created_at_ms, item.memory_id))

    def recall(
        self,
        *,
        query: str | None = None,
        scope: JsonObject | None = None,
        include_sensitive: bool = False,
        limit: int = 20,
        now_ms: int | None = None,
    ) -> MemoryRecallResult:
        normalized_query = " ".join((query or "").lower().split())
        filtered = {"expired": 0, "deleted": 0, "sensitive": 0, "scope": 0, "query": 0}
        matches: list[MemoryItem] = []
        for item in self._items.values():
            if item.state == "deleted":
                filtered["deleted"] += 1
                continue
            if self._is_expired(item, now_ms=now_ms):
                filtered["expired"] += 1
                continue
            if scope is not None and not _scope_matches(item.scope, scope):
                filtered["scope"] += 1
                continue
            if item.privacy_class == "sensitive" and not include_sensitive:
                filtered["sensitive"] += 1
                continue
            if normalized_query and normalized_query not in _search_text(item):
                filtered["query"] += 1
                continue
            matches.append(item)
        matches = sorted(matches, key=lambda item: (-item.confidence, item.created_at_ms, item.memory_id))[: max(0, limit)]
        return MemoryRecallResult(
            query=query,
            scope=dict(scope or {}),
            items=[item.to_dict() for item in matches],
            total=len(matches),
            filtered=filtered,
            generated_at_ms=now_ms if now_ms is not None else self._now_ms(),
        )

    def proposals(self) -> list[MemoryProposal]:
        return sorted(self._proposals.values(), key=lambda item: (item.created_at_ms, item.proposal_id))

    def shadow_candidates(self) -> list[ShadowCandidate]:
        return sorted(self._candidates.values(), key=lambda item: (item.created_at_ms, item.candidate_id))

    def tombstones(self) -> list[MemoryTombstone]:
        return sorted(self._tombstones.values(), key=lambda item: (item.deleted_at_ms, item.tombstone_id))

    def audit_records(self) -> list[JsonObject]:
        return [dict(event) for event in self._events]

    def index_items(self) -> list[JsonObject]:
        if self.index_path is None:
            raise RuntimeError("index_path is not configured")
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                SELECT memory_id, kind, title, summary, scope_json, privacy_class,
                       state, dedupe_key, expires_at_ms, updated_at_ms
                FROM memory_items
                ORDER BY created_at_ms, memory_id
                """
            )
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def rebuild_index(self) -> None:
        if self.index_path is None:
            return
        conn = self._connect()
        try:
            _create_schema(conn)
            conn.execute("DELETE FROM memory_items")
            conn.execute("DELETE FROM memory_proposals")
            conn.execute("DELETE FROM shadow_candidates")
            conn.execute("DELETE FROM memory_tombstones")
            for item in self._items.values():
                self._upsert_item_index(item, conn=conn)
            for proposal in self._proposals.values():
                self._upsert_proposal_index(proposal, conn=conn)
            for candidate in self._candidates.values():
                self._upsert_candidate_index(candidate, conn=conn)
            for tombstone in self._tombstones.values():
                self._upsert_tombstone_index(tombstone, conn=conn)
            conn.commit()
        finally:
            conn.close()

    def _replay_events(self) -> None:
        self._items = {}
        self._proposals = {}
        self._candidates = {}
        self._tombstones = {}
        for event in self._events:
            event_type = str(event.get("event_type") or "")
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            if event_type == "memory_item_committed":
                item = MemoryItem.from_dict(payload)
                self._items[item.memory_id] = item
            elif event_type == "memory_proposal_recorded":
                proposal = MemoryProposal.from_dict(payload)
                self._proposals[proposal.proposal_id] = proposal
            elif event_type == "memory_proposal_decided":
                proposal = MemoryProposal.from_dict(payload)
                self._proposals[proposal.proposal_id] = proposal
            elif event_type == "shadow_candidate_recorded":
                candidate = ShadowCandidate.from_dict(payload)
                self._candidates[candidate.candidate_id] = candidate
            elif event_type == "memory_tombstone_created":
                tombstone = MemoryTombstone.from_dict(payload)
                item = self._items.get(tombstone.memory_id)
                if item is not None:
                    self._items[tombstone.memory_id] = replace(item, state="deleted", updated_at_ms=tombstone.deleted_at_ms)
                self._tombstones[tombstone.memory_id] = tombstone

    def _append_event(self, event_type: str, payload: JsonObject) -> None:
        event = {
            "schema_version": self.SCHEMA_VERSION,
            "event_id": f"memory-event-{len(self._events) + 1}",
            "event_type": event_type,
            "recorded_at_ms": self._now_ms(),
            "payload": payload,
            "payload_hash": _hash(payload),
        }
        self._events.append(event)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical_json(event) + "\n")

    def _upsert_item_index(self, item: MemoryItem, *, conn: sqlite3.Connection | None = None) -> None:
        if self.index_path is None and conn is None:
            return
        owns_conn = conn is None
        connection = conn or self._connect()
        try:
            _create_schema(connection)
            connection.execute(
                """
                INSERT OR REPLACE INTO memory_items (
                    memory_id, kind, title, summary, body, scope_json, privacy_class,
                    confidence, ttl_policy, expires_at_ms, dedupe_key, state,
                    approved_by, created_at_ms, updated_at_ms, last_accessed_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.memory_id,
                    item.kind,
                    item.title,
                    item.summary,
                    item.body,
                    _canonical_json(item.scope),
                    item.privacy_class,
                    item.confidence,
                    item.ttl_policy,
                    item.expires_at_ms,
                    item.dedupe_key,
                    item.state,
                    item.approved_by,
                    item.created_at_ms,
                    item.updated_at_ms,
                    item.last_accessed_ms,
                ),
            )
            if owns_conn:
                connection.commit()
        finally:
            if owns_conn:
                connection.close()

    def _upsert_proposal_index(self, proposal: MemoryProposal, *, conn: sqlite3.Connection | None = None) -> None:
        if self.index_path is None and conn is None:
            return
        owns_conn = conn is None
        connection = conn or self._connect()
        try:
            _create_schema(connection)
            connection.execute(
                """
                INSERT OR REPLACE INTO memory_proposals (
                    proposal_id, candidate_id, operation, approval_policy,
                    approval_status, confidence, created_at_ms, decided_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.proposal_id,
                    proposal.candidate_id,
                    proposal.operation,
                    proposal.approval_policy,
                    proposal.approval_status,
                    proposal.confidence,
                    proposal.created_at_ms,
                    proposal.decided_at_ms,
                ),
            )
            if owns_conn:
                connection.commit()
        finally:
            if owns_conn:
                connection.close()

    def _upsert_candidate_index(self, candidate: ShadowCandidate, *, conn: sqlite3.Connection | None = None) -> None:
        if self.index_path is None and conn is None:
            return
        owns_conn = conn is None
        connection = conn or self._connect()
        try:
            _create_schema(connection)
            connection.execute(
                """
                INSERT OR REPLACE INTO shadow_candidates (
                    candidate_id, source_kind, normalized_topic, status,
                    expires_at_ms, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.source_kind,
                    candidate.normalized_topic,
                    candidate.status,
                    candidate.expires_at_ms,
                    candidate.created_at_ms,
                ),
            )
            if owns_conn:
                connection.commit()
        finally:
            if owns_conn:
                connection.close()

    def _upsert_tombstone_index(self, tombstone: MemoryTombstone, *, conn: sqlite3.Connection | None = None) -> None:
        if self.index_path is None and conn is None:
            return
        owns_conn = conn is None
        connection = conn or self._connect()
        try:
            _create_schema(connection)
            connection.execute(
                """
                INSERT OR REPLACE INTO memory_tombstones (
                    tombstone_id, memory_id, reason, deleted_by, deleted_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    tombstone.tombstone_id,
                    tombstone.memory_id,
                    tombstone.reason,
                    tombstone.deleted_by,
                    tombstone.deleted_at_ms,
                ),
            )
            if owns_conn:
                connection.commit()
        finally:
            if owns_conn:
                connection.close()

    def _connect(self) -> sqlite3.Connection:
        if self.index_path is None:
            raise RuntimeError("index_path is not configured")
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.index_path)

    def _is_recallable(self, item: MemoryItem, *, now_ms: int | None) -> bool:
        return item.state == "active" and not self._is_expired(item, now_ms=now_ms)

    def _is_expired(self, item: MemoryItem, *, now_ms: int | None) -> bool:
        return item.expires_at_ms is not None and item.expires_at_ms <= (now_ms if now_ms is not None else self._now_ms())

    def _now_ms(self) -> int:
        return int(self.clock_ms())


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_items (
            memory_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            body TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            privacy_class TEXT NOT NULL,
            confidence REAL NOT NULL,
            ttl_policy TEXT NOT NULL,
            expires_at_ms INTEGER,
            dedupe_key TEXT NOT NULL,
            state TEXT NOT NULL,
            approved_by TEXT,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            last_accessed_ms INTEGER
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_scope ON memory_items(scope_json)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_state ON memory_items(state)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_dedupe ON memory_items(dedupe_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_expires ON memory_items(expires_at_ms)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_proposals (
            proposal_id TEXT PRIMARY KEY,
            candidate_id TEXT,
            operation TEXT NOT NULL,
            approval_policy TEXT NOT NULL,
            approval_status TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at_ms INTEGER NOT NULL,
            decided_at_ms INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shadow_candidates (
            candidate_id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            normalized_topic TEXT NOT NULL,
            status TEXT NOT NULL,
            expires_at_ms INTEGER,
            created_at_ms INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_tombstones (
            tombstone_id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            deleted_by TEXT NOT NULL,
            deleted_at_ms INTEGER NOT NULL
        )
        """
    )


def _scope_matches(item_scope: JsonObject, requested_scope: JsonObject) -> bool:
    for key, value in requested_scope.items():
        if item_scope.get(key) != value:
            return False
    return True


def _search_text(item: MemoryItem) -> str:
    return " ".join(
        [
            item.kind,
            item.title,
            item.summary,
            item.body,
            item.dedupe_key,
            _canonical_json(item.structured),
        ]
    ).lower()


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
