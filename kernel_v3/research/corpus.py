from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.memory.privacy import contains_secret_like_content
from kernel_v3.research.contracts import CorpusDocument, CorpusInspection, CorpusSearchResult, CorpusStatus, SourceAssessment
from kernel_v3.research.profiles import profile_by_id

if TYPE_CHECKING:
    from kernel_v3.context import ArtifactStore
    from kernel_v3.retrieval.contracts import FetchedDocument, SearchGoal, SearchSource


CORPUS_SEARCH_LIMIT_CAP = 50
CORPUS_SAMPLE_LIMIT_CAP = 20


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
        document = replace(document, metadata=_safe_json(dict(document.metadata)))
        existing = self._documents.get(document.document_id)
        if existing is not None:
            if existing.to_dict() == document.to_dict():
                return existing
            if _same_document_identity(existing, document):
                refreshed = _merge_reobserved_document(existing, document)
                self._documents[refreshed.document_id] = refreshed
                self._append_event(
                    "corpus_document_reobserved",
                    {
                        "document_id": refreshed.document_id,
                        "uri": refreshed.uri,
                        "payload_hash": refreshed.payload_hash,
                        "artifact_id": refreshed.artifact_id,
                        "previous_fetched_at_ms": existing.fetched_at_ms,
                        "observed_fetched_at_ms": document.fetched_at_ms,
                        "fetched_at_ms": refreshed.fetched_at_ms,
                        "task_id": document.task_id,
                        "run_id": document.run_id,
                        "goal_id": document.goal_id,
                        "research_profile_id": document.research_profile_id,
                        "metadata": _safe_json(document.metadata),
                        "document": refreshed.to_dict(),
                    },
                )
                self._upsert_document_index(refreshed)
                return refreshed
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
        exclude_stale: bool = False,
        now_ms: int | None = None,
        record_access: bool = False,
        access_context: JsonObject | None = None,
    ) -> CorpusSearchResult:
        terms = _terms(query or "")
        effective_limit = _clamp_limit(limit, cap=CORPUS_SEARCH_LIMIT_CAP)
        scored: list[tuple[float, CorpusDocument]] = []
        timestamp = self._now_ms() if now_ms is None else now_ms
        for document in self.documents(profile_id=profile_id):
            if exclude_stale and _document_is_stale(document, now_ms=timestamp):
                continue
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
            )[:effective_limit]
        ]
        result = CorpusSearchResult(
            query=query,
            profile_id=profile_id,
            documents=[document.to_dict() for document in ordered],
            total=len(ordered),
            generated_at_ms=timestamp,
        )
        if record_access:
            self._record_search_access(
                result,
                terms=terms,
                requested_limit=limit,
                effective_limit=effective_limit,
                exclude_stale=exclude_stale,
                searched_at_ms=timestamp,
                access_context=access_context,
            )
        return result

    def freshness_summary(
        self,
        *,
        profile_id: str | None = None,
        sample_limit: int = 5,
        now_ms: int | None = None,
    ) -> JsonObject:
        documents = self.documents(profile_id=profile_id)
        timestamp = self._now_ms() if now_ms is None else now_ms
        effective_sample_limit = _clamp_limit(sample_limit, cap=CORPUS_SAMPLE_LIMIT_CAP)
        stale = [document for document in documents if _document_is_stale(document, now_ms=timestamp)]
        stale = sorted(stale, key=lambda document: (document.fetched_at_ms, document.document_id))
        max_ages = _freshness_max_ages(documents)
        summary = {
            "checked": True,
            "generated_at_ms": timestamp,
            "profile_id": profile_id,
            "document_count": len(documents),
            "stale_count": len(stale),
            "max_age_ms_by_profile": max_ages,
            "oldest_age_ms": max(0, timestamp - stale[0].fetched_at_ms) if stale else 0,
            "document_ids": [document.document_id for document in stale[:effective_sample_limit]],
        }
        if effective_sample_limit != sample_limit:
            summary["requested_sample_limit"] = sample_limit
            summary["sample_limit"] = effective_sample_limit
            summary["sample_limit_cap"] = CORPUS_SAMPLE_LIMIT_CAP
            summary["sample_limit_clamped"] = True
        return summary

    def audit_records(self) -> list[JsonObject]:
        return [dict(event) for event in self._events]

    def status(self) -> CorpusStatus:
        documents = list(self._documents.values())
        fetched_times = [document.fetched_at_ms for document in documents]
        return CorpusStatus(
            generated_at_ms=self._now_ms(),
            log_path=str(self.log_path) if self.log_path is not None else None,
            index_path=str(self.index_path) if self.index_path is not None else None,
            document_count=len(documents),
            total_size_bytes=sum(max(0, int(document.size_bytes)) for document in documents),
            profile_counts=_count_by(documents, lambda document: document.research_profile_id or "unprofiled"),
            provider_counts=_count_by(documents, lambda document: document.provider or "unknown"),
            source_family_counts=_count_by(documents, lambda document: str(_assessment(document).get("source_family") or "unknown")),
            authority_level_counts=_count_by(
                documents,
                lambda document: str(_assessment(document).get("authority_level") or "unknown"),
            ),
            primary_usable_count=sum(1 for document in documents if bool(_assessment(document).get("usable_as_primary"))),
            audit_record_count=len(self._events),
            latest_fetched_at_ms=max(fetched_times) if fetched_times else None,
        )

    def inspect(self, *, sample_limit: int = 5, artifact_store: "ArtifactStore | None" = None) -> CorpusInspection:
        status = self.status()
        documents = self.documents()
        effective_sample_limit = _clamp_limit(sample_limit, cap=CORPUS_SAMPLE_LIMIT_CAP)
        issues: list[JsonObject] = []
        actions: list[str] = []
        artifact_consistency = _artifact_consistency(
            documents,
            artifact_store=artifact_store,
            sample_limit=effective_sample_limit,
        )
        freshness_issues = _freshness_issues(
            documents,
            now_ms=status.generated_at_ms,
            sample_limit=effective_sample_limit,
        )
        if status.document_count == 0:
            issues.append(
                {
                    "severity": "info",
                    "code": "empty_corpus",
                    "message": "No research corpus documents are indexed.",
                }
            )
            actions.append("retrieve <query> --index-corpus")
        elif status.primary_usable_count == 0:
            issues.append(
                {
                    "severity": "warning",
                    "code": "no_primary_usable_sources",
                    "document_count": status.document_count,
                }
            )
            actions.append("retrieve <query> --profile finance_fundamentals --index-corpus")
        unprofiled_count = int(status.profile_counts.get("unprofiled", 0))
        if unprofiled_count:
            issues.append(
                {
                    "severity": "info",
                    "code": "unprofiled_documents",
                    "count": unprofiled_count,
                }
            )
            actions.append("corpus list --profile finance_fundamentals")
        for issue in freshness_issues:
            issues.append(issue)
            profile_id = str(issue.get("profile_id") or "finance_fundamentals")
            actions.append(f"retrieve <query> --profile {profile_id} --index-corpus")
        if artifact_consistency.get("checked"):
            missing_ref_count = int(artifact_consistency.get("missing_artifact_ref_count") or 0)
            missing_blob_count = int(artifact_consistency.get("missing_artifact_blob_count") or 0)
            if missing_ref_count or missing_blob_count:
                issues.append(
                    {
                        "severity": "error",
                        "code": "missing_corpus_artifacts",
                        "missing_artifact_ref_count": missing_ref_count,
                        "missing_artifact_blob_count": missing_blob_count,
                        "document_ids": artifact_consistency.get("affected_document_ids", []),
                    }
                )
                actions.append("repair artifact store or re-index affected corpus documents")
        if any(issue["severity"] == "error" for issue in issues):
            health = "error"
        elif any(issue["severity"] == "warning" for issue in issues):
            health = "warning"
        elif issues:
            health = "attention"
        else:
            health = "ok"
        return CorpusInspection(
            status=health,
            generated_at_ms=status.generated_at_ms,
            issues=issues,
            recommended_actions=_ordered_unique(actions),
            corpus_status=status.to_dict(),
            artifact_consistency=artifact_consistency,
            samples=_inspection_samples(
                documents,
                requested_sample_limit=sample_limit,
                effective_sample_limit=effective_sample_limit,
            ),
        )

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
            event_type = event.get("event_type")
            payload = event.get("payload")
            if event_type == "corpus_document_recorded" and isinstance(payload, dict):
                document = CorpusDocument.from_dict(payload)
                self._documents[document.document_id] = document
            elif event_type == "corpus_document_reobserved" and isinstance(payload, dict):
                document_payload = payload.get("document")
                if isinstance(document_payload, dict):
                    document = CorpusDocument.from_dict(document_payload)
                    self._documents[document.document_id] = document
                    continue
                document_id = payload.get("document_id")
                existing = self._documents.get(document_id) if isinstance(document_id, str) else None
                if existing is not None:
                    self._documents[existing.document_id] = _legacy_reobserved_document(existing, payload)

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

    def _record_search_access(
        self,
        result: CorpusSearchResult,
        *,
        terms: list[str],
        requested_limit: int,
        effective_limit: int,
        exclude_stale: bool,
        searched_at_ms: int,
        access_context: JsonObject | None,
    ) -> None:
        documents = [
            document
            for document in result.documents
            if isinstance(document, dict)
        ]
        payload = {
            "searched_at_ms": searched_at_ms,
            "query_hash": _hash({"query": result.query or ""}),
            "query_term_count": len(terms),
            "profile_id": result.profile_id,
            "limit": effective_limit,
            "exclude_stale": exclude_stale,
            "total": result.total,
            "document_ids": [
                str(document.get("document_id"))
                for document in documents
                if isinstance(document.get("document_id"), str)
            ],
            "access_context": _safe_json(dict(access_context or {})),
            "redaction": {"query": "hash_only", "documents": "ids_only"},
        }
        if effective_limit != requested_limit:
            payload["requested_limit"] = requested_limit
            payload["limit_cap"] = CORPUS_SEARCH_LIMIT_CAP
            payload["limit_clamped"] = True
        self._append_event("corpus_documents_searched", payload)

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
    )


def _merge_reobserved_document(existing: CorpusDocument, observed: CorpusDocument) -> CorpusDocument:
    base = observed if observed.fetched_at_ms >= existing.fetched_at_ms else existing
    metadata = {
        **dict(existing.metadata),
        **dict(observed.metadata),
        "last_reobserved_at_ms": max(existing.fetched_at_ms, observed.fetched_at_ms),
        "reobservation_count": _metadata_int(existing.metadata, "reobservation_count") + 1,
    }
    return replace(
        base,
        fetched_at_ms=max(existing.fetched_at_ms, observed.fetched_at_ms),
        research_profile_id=base.research_profile_id or existing.research_profile_id or observed.research_profile_id,
        source_assessment=base.source_assessment or existing.source_assessment or observed.source_assessment,
        metadata=_safe_json(metadata),
    )


def _legacy_reobserved_document(existing: CorpusDocument, payload: JsonObject) -> CorpusDocument:
    fetched_at_ms = _positive_int(payload.get("fetched_at_ms"), default=existing.fetched_at_ms)
    fetched_at_ms = max(existing.fetched_at_ms, fetched_at_ms)
    metadata_value = payload.get("metadata")
    metadata = {
        **dict(existing.metadata),
        **_safe_json(dict(metadata_value) if isinstance(metadata_value, dict) else {}),
        "last_reobserved_at_ms": fetched_at_ms,
        "reobservation_count": _metadata_int(existing.metadata, "reobservation_count") + 1,
    }
    return replace(
        existing,
        fetched_at_ms=fetched_at_ms,
        task_id=_optional_string(payload.get("task_id"), default=existing.task_id),
        run_id=_optional_string(payload.get("run_id"), default=existing.run_id) or existing.run_id,
        goal_id=_optional_string(payload.get("goal_id"), default=existing.goal_id) or existing.goal_id,
        research_profile_id=_optional_string(payload.get("research_profile_id"), default=existing.research_profile_id),
        metadata=_safe_json(metadata),
    )


def _metadata_int(metadata: JsonObject, key: str) -> int:
    value = metadata.get(key)
    return int(value) if isinstance(value, int) and value >= 0 else 0


def _optional_string(value: object, *, default: str | None) -> str | None:
    return value if isinstance(value, str) and value else default


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0:
        return int(value)
    return default


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


def _count_by(documents: list[CorpusDocument], key_fn) -> dict[str, int]:
    counts: dict[str, int] = {}
    for document in documents:
        key = str(key_fn(document) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _clamp_limit(value: int, *, cap: int) -> int:
    return min(max(0, int(value)), cap)


def _inspection_samples(
    documents: list[CorpusDocument],
    *,
    requested_sample_limit: int,
    effective_sample_limit: int,
) -> JsonObject:
    samples: JsonObject = {
        "documents": [_document_sample(document) for document in documents[:effective_sample_limit]],
    }
    if effective_sample_limit != requested_sample_limit:
        samples["requested_sample_limit"] = requested_sample_limit
        samples["sample_limit"] = effective_sample_limit
        samples["sample_limit_cap"] = CORPUS_SAMPLE_LIMIT_CAP
        samples["sample_limit_clamped"] = True
    return samples


def _document_sample(document: CorpusDocument) -> JsonObject:
    assessment = _assessment(document)
    return {
        "document_id": document.document_id,
        "uri": document.uri,
        "title": document.title,
        "provider": document.provider,
        "artifact_id": document.artifact_id,
        "payload_hash": document.payload_hash,
        "research_profile_id": document.research_profile_id,
        "source_family": assessment.get("source_family"),
        "authority_level": assessment.get("authority_level"),
        "usable_as_primary": bool(assessment.get("usable_as_primary")),
        "fetched_at_ms": document.fetched_at_ms,
    }


def _artifact_consistency(
    documents: list[CorpusDocument],
    *,
    artifact_store,
    sample_limit: int,
) -> JsonObject:
    if artifact_store is None:
        return {"checked": False}
    missing_refs: list[str] = []
    missing_blobs: list[str] = []
    affected: list[str] = []
    for document in documents:
        artifact = artifact_store.get(document.artifact_id)
        if artifact is None:
            missing_refs.append(document.artifact_id)
            affected.append(document.document_id)
            continue
        if not artifact_store.has_blob(document.artifact_id):
            missing_blobs.append(document.artifact_id)
            affected.append(document.document_id)
    return {
        "checked": True,
        "document_count": len(documents),
        "missing_artifact_ref_count": len(missing_refs),
        "missing_artifact_blob_count": len(missing_blobs),
        "missing_artifact_refs": _ordered_unique(missing_refs)[: max(0, sample_limit)],
        "missing_artifact_blobs": _ordered_unique(missing_blobs)[: max(0, sample_limit)],
        "affected_document_ids": _ordered_unique(affected)[: max(0, sample_limit)],
    }


def _freshness_issues(documents: list[CorpusDocument], *, now_ms: int, sample_limit: int) -> list[JsonObject]:
    issues: list[JsonObject] = []
    by_profile: dict[str, list[CorpusDocument]] = {}
    for document in documents:
        profile_id = document.research_profile_id
        if not profile_id:
            continue
        by_profile.setdefault(profile_id, []).append(document)
    for profile_id, profile_documents in sorted(by_profile.items()):
        profile = profile_by_id(profile_id)
        if profile is None:
            continue
        max_age_ms = _freshness_max_age_ms(profile.metadata)
        if max_age_ms is None:
            continue
        stale = [
            document
            for document in profile_documents
            if now_ms - document.fetched_at_ms > max_age_ms
        ]
        if not stale:
            continue
        stale = sorted(stale, key=lambda document: (document.fetched_at_ms, document.document_id))
        issues.append(
            {
                "severity": "warning",
                "code": "stale_research_corpus_documents",
                "profile_id": profile_id,
                "stale_count": len(stale),
                "document_count": len(profile_documents),
                "max_age_ms": max_age_ms,
                "oldest_age_ms": max(0, now_ms - stale[0].fetched_at_ms),
                "document_ids": [document.document_id for document in stale[: max(0, sample_limit)]],
            }
        )
    return issues


def _document_is_stale(document: CorpusDocument, *, now_ms: int) -> bool:
    profile_id = document.research_profile_id
    if not profile_id:
        return False
    profile = profile_by_id(profile_id)
    if profile is None:
        return False
    max_age_ms = _freshness_max_age_ms(profile.metadata)
    return max_age_ms is not None and now_ms - document.fetched_at_ms > max_age_ms


def _freshness_max_ages(documents: list[CorpusDocument]) -> JsonObject:
    result: JsonObject = {}
    for document in documents:
        profile_id = document.research_profile_id
        if not profile_id or profile_id in result:
            continue
        profile = profile_by_id(profile_id)
        if profile is None:
            continue
        max_age_ms = _freshness_max_age_ms(profile.metadata)
        if max_age_ms is not None:
            result[profile_id] = max_age_ms
    return result


def _freshness_max_age_ms(metadata: JsonObject) -> int | None:
    value = metadata.get("freshness_max_age_ms")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0:
        return int(value)
    return None


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _safe_json(data: JsonObject) -> JsonObject:
    safe: JsonObject = {}
    for key, value in data.items():
        lowered = key.lower()
        if _unsafe_metadata_key(lowered):
            safe[key] = "[omitted]"
        elif isinstance(value, str):
            safe[key] = "[omitted]" if contains_secret_like_content(value) else _preview(value, 160)
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
        return "[omitted]" if contains_secret_like_content(value) else _preview(value, 160)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return _safe_json(value)
    if isinstance(value, list):
        return [_safe_list_item(item) for item in value[:10]]
    return str(value)[:160]


def _unsafe_metadata_key(lowered_key: str) -> bool:
    if "body" in lowered_key or "raw" in lowered_key:
        return True
    sensitive_terms = (
        "api_key",
        "apikey",
        "secret",
        "token",
        "authorization",
        "cookie",
        "password",
        "private_key",
        "credential",
    )
    return any(term in lowered_key for term in sensitive_terms)


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
