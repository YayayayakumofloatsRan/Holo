from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import CorpusDocument, CorpusSearchResult, SourceAssessment

if TYPE_CHECKING:
    from kernel_v3.retrieval.contracts import FetchedDocument, SearchGoal, SearchSource


def stable_corpus_document_id(*, uri: str, payload_hash: str) -> str:
    return "webdoc-" + _hash({"uri": uri, "payload_hash": payload_hash})[:16]


def corpus_document_from_retrieval(
    *,
    document: "FetchedDocument",
    source: "SearchSource",
    goal: "SearchGoal",
    task_id: str | None,
    run_id: str,
    fetched_at_ms: int,
    source_assessment: SourceAssessment | None = None,
) -> CorpusDocument:
    return CorpusDocument(
        document_id=stable_corpus_document_id(uri=document.uri, payload_hash=document.payload_hash),
        uri=document.uri,
        title=document.title,
        source_id=document.source_id,
        provider=source.provider,
        artifact_id=document.artifact_id,
        payload_hash=document.payload_hash,
        preview=document.preview,
        mime_type=str(document.metadata.get("mime_type", "text/plain")),
        size_bytes=document.size_bytes,
        fetched_at_ms=fetched_at_ms,
        task_id=task_id,
        run_id=run_id,
        goal_id=goal.goal_id,
        research_profile_id=_research_profile_id(goal),
        source_assessment=source_assessment.to_dict() if source_assessment is not None else None,
        metadata={
            "retrieval_document_id": document.document_id,
            "source_metadata": _safe_json(dict(source.metadata)),
        },
    )


class ResearchCorpusStore:
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
        self._documents: dict[str, CorpusDocument] = {}
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
    def in_memory(cls, *, clock_ms: Callable[[], int] | None = None) -> "ResearchCorpusStore":
        return cls(clock_ms=clock_ms)

    def record_document(self, document: CorpusDocument) -> CorpusDocument:
        existing = self._documents.get(document.document_id)
        if existing is not None:
            if existing.to_dict() == document.to_dict():
                return existing
            if _same_document_identity(existing, document):
                self._append_event(
                    "corpus_document_reobserved",
                    {
                        "document_id": existing.document_id,
                        "uri": existing.uri,
                        "payload_hash": existing.payload_hash,
                        "artifact_id": existing.artifact_id,
                        "task_id": document.task_id,
                        "run_id": document.run_id,
                        "goal_id": document.goal_id,
                        "fetched_at_ms": document.fetched_at_ms,
                        "research_profile_id": document.research_profile_id,
                        "metadata": _safe_json(document.metadata),
                    },
                )
                return existing
            raise ValueError(f"corpus_document_id_conflict:{document.document_id}")
        self._documents[document.document_id] = document
        self._append_event("corpus_document_recorded", document.to_dict())
        self._upsert_document_index(document)
        return document

    def record_retrieval_document(
        self,
        *,
        document: "FetchedDocument",
        source: "SearchSource",
        goal: "SearchGoal",
        task_id: str | None,
        run_id: str,
        source_assessment: SourceAssessment | None = None,
    ) -> CorpusDocument:
        return self.record_document(
            corpus_document_from_retrieval(
                document=document,
                source=source,
                goal=goal,
                task_id=task_id,
                run_id=run_id,
                fetched_at_ms=self._now_ms(),
                source_assessment=source_assessment,
            )
        )

    def get(self, document_id: str) -> CorpusDocument | None:
        return self._documents.get(document_id)

    def documents(self, *, profile_id: str | None = None) -> list[CorpusDocument]:
        result = [
            document
            for document in self._documents.values()
            if profile_id is None or document.research_profile_id == profile_id
        ]
        return sorted(result, key=lambda item: (item.fetched_at_ms, item.document_id))

    def search(
        self,
        query: str | None = None,
        *,
        profile_id: str | None = None,
        limit: int = 20,
    ) -> CorpusSearchResult:
        terms = _terms(query or "")
        scored: list[tuple[float, CorpusDocument]] = []
        for document in self.documents(profile_id=profile_id):
            haystack = _search_text(document)
            hits = sum(1 for term in terms if term in haystack)
            if terms and hits == 0:
                continue
            authority = _authority_score(document)
            score = (hits / max(1, len(terms))) + authority
            scored.append((score, document))
        ordered = [
            document
            for _, document in sorted(
                scored,
                key=lambda item: (-item[0], -_authority_score(item[1]), item[1].fetched_at_ms, item[1].document_id),
            )[: max(0, limit)]
        ]
        return CorpusSearchResult(
            query=query,
            profile_id=profile_id,
            documents=[document.to_dict() for document in ordered],
            total=len(ordered),
            generated_at_ms=self._now_ms(),
        )

    def audit_records(self) -> list[JsonObject]:
        return [dict(event) for event in self._events]

    def index_documents(self) -> list[JsonObject]:
        if self.index_path is None:
            raise RuntimeError("index_path is not configured")
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                SELECT document_id, uri, title, source_id, provider, artifact_id,
                       payload_hash, research_profile_id, source_family,
                       authority_level, authority_score, usable_as_primary,
                       fetched_at_ms
                FROM corpus_documents
                ORDER BY fetched_at_ms, document_id
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
            conn.execute("DELETE FROM corpus_documents")
            for document in self._documents.values():
                self._upsert_document_index(document, conn=conn)
            conn.commit()
        finally:
            conn.close()

    def _replay_events(self) -> None:
        self._documents = {}
        for event in self._events:
            if event.get("event_type") != "corpus_document_recorded":
                continue
            payload = event.get("payload")
            if isinstance(payload, dict):
                document = CorpusDocument.from_dict(payload)
                self._documents[document.document_id] = document

    def _append_event(self, event_type: str, payload: JsonObject) -> None:
        event = {
            "schema_version": self.SCHEMA_VERSION,
            "event_id": f"corpus-event-{len(self._events) + 1}",
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

    def _upsert_document_index(
        self,
        document: CorpusDocument,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        if self.index_path is None and conn is None:
            return
        owns_conn = conn is None
        connection = conn or self._connect()
        assessment = _assessment(document)
        try:
            _create_schema(connection)
            connection.execute(
                """
                INSERT OR REPLACE INTO corpus_documents (
                    document_id, uri, title, source_id, provider, artifact_id,
                    payload_hash, preview, mime_type, size_bytes, fetched_at_ms,
                    task_id, run_id, goal_id, research_profile_id,
                    source_family, authority_level, authority_score,
                    usable_as_primary, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    document.uri,
                    document.title,
                    document.source_id,
                    document.provider,
                    document.artifact_id,
                    document.payload_hash,
                    document.preview,
                    document.mime_type,
                    document.size_bytes,
                    document.fetched_at_ms,
                    document.task_id,
                    document.run_id,
                    document.goal_id,
                    document.research_profile_id,
                    assessment.get("source_family"),
                    assessment.get("authority_level"),
                    assessment.get("authority_score"),
                    int(bool(assessment.get("usable_as_primary"))),
                    _canonical_json(document.metadata),
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

    def _now_ms(self) -> int:
        return int(self.clock_ms())


def _research_profile_id(goal: "SearchGoal") -> str | None:
    value = goal.metadata.get("research_profile_id", goal.metadata.get("research_profile"))
    return value if isinstance(value, str) and value else None


def _assessment(document: CorpusDocument) -> JsonObject:
    return dict(document.source_assessment or {})


def _same_document_identity(left: CorpusDocument, right: CorpusDocument) -> bool:
    return (
        left.document_id == right.document_id
        and left.uri == right.uri
        and left.payload_hash == right.payload_hash
        and left.artifact_id == right.artifact_id
    )


def _authority_score(document: CorpusDocument) -> float:
    value = _assessment(document).get("authority_score")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _search_text(document: CorpusDocument) -> str:
    assessment = _assessment(document)
    return " ".join(
        [
            document.uri,
            document.title,
            document.source_id,
            document.provider,
            document.preview,
            str(document.research_profile_id or ""),
            str(assessment.get("source_family") or ""),
            str(assessment.get("authority_level") or ""),
        ]
    ).lower()


def _terms(text: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for term in text.lower().replace("-", " ").split():
        if not term or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def _safe_json(data: JsonObject) -> JsonObject:
    safe: JsonObject = {}
    for key, value in data.items():
        lowered = key.lower()
        if "body" in lowered or "raw" in lowered:
            safe[key] = "[omitted]"
        elif isinstance(value, str):
            safe[key] = _preview(value, 160)
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, list):
            safe[key] = [_safe_list_item(item) for item in value[:10]]
        elif isinstance(value, dict):
            safe[key] = _safe_json(value)
        else:
            safe[key] = str(value)[:160]
    return safe


def _safe_list_item(value):
    if isinstance(value, str):
        return _preview(value, 160)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return _safe_json(value)
    return str(value)[:160]


def _preview(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS corpus_documents (
            document_id TEXT PRIMARY KEY,
            uri TEXT NOT NULL,
            title TEXT NOT NULL,
            source_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            preview TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            fetched_at_ms INTEGER NOT NULL,
            task_id TEXT,
            run_id TEXT NOT NULL,
            goal_id TEXT NOT NULL,
            research_profile_id TEXT,
            source_family TEXT,
            authority_level TEXT,
            authority_score REAL,
            usable_as_primary INTEGER NOT NULL,
            metadata_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_corpus_documents_uri ON corpus_documents(uri)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_corpus_documents_profile ON corpus_documents(research_profile_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_corpus_documents_family ON corpus_documents(source_family)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_corpus_documents_payload ON corpus_documents(payload_hash)")


def _canonical_json(payload: JsonObject) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(payload: JsonObject) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
