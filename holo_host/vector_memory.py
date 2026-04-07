from __future__ import annotations

import hashlib
import importlib.util
import math
import re
import threading
from pathlib import Path
from typing import Any, Iterable

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(str(text or ""))]


def _normalize(vec: list[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in vec))
    if length <= 1e-9:
        return vec
    return [value / length for value in vec]


def hashed_embedding(text: str, *, dim: int = 192) -> list[float]:
    tokens = _tokenize(text) or [str(text or "").strip().lower() or "<empty>"]
    vec = [0.0] * dim
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for offset in range(16):
            left = digest[offset]
            right = digest[offset + 16]
            index = (left + offset * 31) % dim
            sign = 1.0 if (right % 2 == 0) else -1.0
            magnitude = 0.35 + (left / 255.0)
            vec[index] += sign * magnitude
    return _normalize(vec)


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_list = list(left)
    right_list = list(right)
    if not left_list or not right_list or len(left_list) != len(right_list):
        return 0.0
    return float(sum(lv * rv for lv, rv in zip(left_list, right_list, strict=False)))


class VectorMemory:
    def __init__(
        self,
        repo_root: Path,
        *,
        backend: str = "milvus",
        uri: str = "",
        collection_prefix: str = "holo_memory",
        dimension: int = 192,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.backend = str(backend or "milvus").strip().lower() or "milvus"
        self.uri = self._resolve_uri(uri)
        self.collection_prefix = str(collection_prefix or "holo_memory").strip() or "holo_memory"
        self.dimension = max(32, int(dimension or 192))
        self.collection_name = f"{self.collection_prefix}_mind_nodes"
        self._client: Any | None = None
        self._client_ready = False
        self._lock = threading.RLock()
        self._last_error = ""
        self._available = bool(importlib.util.find_spec("pymilvus")) and self.backend == "milvus"

    def _resolve_uri(self, raw: str) -> str:
        current = str(raw or "").strip()
        if not current:
            return str((self.repo_root / ".holo_runtime" / "milvus" / "memory_fabric.db").resolve())
        path = Path(current)
        if path.is_absolute():
            return str(path)
        return str((self.repo_root / path).resolve())

    def health(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "uri": self.uri,
            "collection_name": self.collection_name,
            "dimension": self.dimension,
            "available": self._available,
            "ready": self._client_ready,
            "last_error": self._last_error,
        }

    def _client_instance(self) -> Any | None:
        if not self._available:
            self._last_error = "pymilvus is not installed"
            return None
        if self._client is not None and self._client_ready:
            return self._client
        with self._lock:
            if self._client is not None and self._client_ready:
                return self._client
            client = None
            try:
                from pymilvus import DataType, MilvusClient  # type: ignore

                uri_path = Path(self.uri)
                if not str(self.uri).startswith(("http://", "https://", "tcp://")):
                    uri_path.parent.mkdir(parents=True, exist_ok=True)
                client = MilvusClient(uri=self.uri)
                collections = set(client.list_collections())
                if self.collection_name not in collections:
                    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
                    schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=256)
                    schema.add_field(field_name="channel", datatype=DataType.VARCHAR, max_length=64)
                    schema.add_field(field_name="thread_key", datatype=DataType.VARCHAR, max_length=256)
                    schema.add_field(field_name="chat_name", datatype=DataType.VARCHAR, max_length=256)
                    schema.add_field(field_name="memory_class", datatype=DataType.VARCHAR, max_length=64)
                    schema.add_field(field_name="source_store", datatype=DataType.VARCHAR, max_length=64)
                    schema.add_field(field_name="source_id", datatype=DataType.VARCHAR, max_length=256)
                    schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=8192)
                    schema.add_field(field_name="importance", datatype=DataType.FLOAT)
                    schema.add_field(field_name="confidence", datatype=DataType.FLOAT)
                    schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=self.dimension)
                    index_params = client.prepare_index_params()
                    index_params.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")
                    client.create_collection(
                        collection_name=self.collection_name,
                        schema=schema,
                        index_params=index_params,
                    )
                self._client = client
                self._client_ready = True
                self._last_error = ""
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                if "already exist" in message.lower():
                    self._client = client
                    self._client_ready = True
                    self._last_error = ""
                else:
                    self._client = None
                    self._client_ready = False
                    self._last_error = message
        return self._client

    def _row_from_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text", "")).strip()
        return {
            "id": str(payload.get("id", "")).strip()[:256],
            "channel": str(payload.get("channel", "")).strip()[:64],
            "thread_key": str(payload.get("thread_key", "")).strip()[:256],
            "chat_name": str(payload.get("chat_name", "")).strip()[:256],
            "memory_class": str(payload.get("memory_class", "")).strip()[:64],
            "source_store": str(payload.get("source_store", "")).strip()[:64],
            "source_id": str(payload.get("source_id", "")).strip()[:256],
            "text": text[:8192],
            "importance": float(payload.get("importance", 0.0) or 0.0),
            "confidence": float(payload.get("confidence", 0.0) or 0.0),
            "embedding": hashed_embedding(text, dim=self.dimension),
        }

    def upsert_documents(self, documents: Iterable[dict[str, Any]]) -> dict[str, Any]:
        docs = [self._row_from_document(doc) for doc in documents if str(doc.get("id", "")).strip()]
        if not docs:
            return {"status": "skipped", "reason": "no_documents", **self.health()}
        client = self._client_instance()
        if client is None:
            return {"status": "unavailable", "document_count": len(docs), **self.health()}
        try:
            client.upsert(collection_name=self.collection_name, data=docs)
            return {"status": "ok", "document_count": len(docs), **self.health()}
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._client_ready = False
            return {"status": "error", "document_count": len(docs), **self.health()}

    @staticmethod
    def _escape_filter_value(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    def _filter_expression(self, *, channel: str, thread_key: str, chat_name: str) -> str:
        clauses = [f'channel == "{self._escape_filter_value(channel)}"']
        scoped: list[str] = []
        if thread_key:
            scoped.append(f'thread_key == "{self._escape_filter_value(thread_key)}"')
        if chat_name and chat_name != thread_key:
            scoped.append(f'chat_name == "{self._escape_filter_value(chat_name)}"')
        if scoped:
            clauses.append("(" + " or ".join(scoped) + ")")
        return " and ".join(clauses)

    def search(
        self,
        query: str,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        limit: int = 6,
    ) -> dict[str, Any]:
        client = self._client_instance()
        if client is None:
            return {"status": "unavailable", "hits": [], **self.health()}
        expr = self._filter_expression(channel=channel, thread_key=thread_key, chat_name=chat_name)
        try:
            results = client.search(
                collection_name=self.collection_name,
                data=[hashed_embedding(query, dim=self.dimension)],
                filter=expr,
                limit=max(1, int(limit)),
                output_fields=[
                    "channel",
                    "thread_key",
                    "chat_name",
                    "memory_class",
                    "source_store",
                    "source_id",
                    "text",
                    "importance",
                    "confidence",
                ],
            )
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._client_ready = False
            return {"status": "error", "hits": [], **self.health()}
        hits: list[dict[str, Any]] = []
        search_rows = results[0] if isinstance(results, list) and results else results
        for item in search_rows or []:
            entity = dict(item.get("entity", {})) if isinstance(item, dict) else {}
            node_id = str(item.get("id", entity.get("id", ""))) if isinstance(item, dict) else ""
            score = float(item.get("distance", item.get("score", 0.0)) or 0.0) if isinstance(item, dict) else 0.0
            hits.append(
                {
                    "node_id": node_id,
                    "score": round(score, 4),
                    "channel": str(entity.get("channel", "")),
                    "thread_key": str(entity.get("thread_key", "")),
                    "chat_name": str(entity.get("chat_name", "")),
                    "memory_class": str(entity.get("memory_class", "")),
                    "source_store": str(entity.get("source_store", "")),
                    "source_id": str(entity.get("source_id", "")),
                    "text": str(entity.get("text", "")),
                    "importance": float(entity.get("importance", 0.0) or 0.0),
                    "confidence": float(entity.get("confidence", 0.0) or 0.0),
                }
            )
        return {"status": "ok", "hits": hits[: max(1, int(limit))], **self.health()}
