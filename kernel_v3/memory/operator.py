from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from kernel_v3.contracts import CandidateAction, JsonObject, Observation, ToolManifest
from kernel_v3.journal import JournalStore
from kernel_v3.memory.structured import structured_memory_summary
from kernel_v3.memory.store import MEMORY_RECALL_LIMIT_CAP, MemoryStore
from kernel_v3.tools import ToolRegistry


MEMORY_RECALL_TOOL_NAME = "memory.recall"
MEMORY_RECALL_DEFAULT_LIMIT = 12
MEMORY_RECALL_PREVIEW_CHARS = 320

_DEFAULT_USER_ID = "local:user"
_DEFAULT_PROJECT_ID = "holo-kernel-v3"
_SCOPE_MODES = {"workspace", "project", "thread", "both", "all"}


@dataclass(frozen=True, kw_only=True)
class MemoryRecallOperator:
    store: MemoryStore
    journal: JournalStore | None = None
    user_id: str = _DEFAULT_USER_ID
    project_id: str = _DEFAULT_PROJECT_ID
    include_sensitive: bool = False
    default_limit: int = MEMORY_RECALL_DEFAULT_LIMIT

    def execute(self, action: CandidateAction) -> Observation:
        host_context = _dict(action.payload.get("_host_context"))
        query = _query(action.payload, host_context=host_context)
        limit = _limit(action.payload.get("limit"), default=self.default_limit)
        scope_mode = _scope_mode(action.payload.get("scope_mode") or action.payload.get("scope"))
        user_id = _string(action.payload.get("user_id")) or self.user_id
        project_id = _string(action.payload.get("project_id")) or self.project_id
        thread_id = _string(action.payload.get("thread_id")) or _string(host_context.get("thread_id")) or _DEFAULT_THREAD_ID
        task_id = _string(host_context.get("task_id"))
        run_id = _string(host_context.get("run_id"))
        step_id = _string(host_context.get("step_id"))

        scopes = _scopes(scope_mode=scope_mode, user_id=user_id, project_id=project_id, thread_id=thread_id)
        results: JsonObject = {}
        fallback_scopes: list[str] = []
        for label, scope in scopes:
            result, used_fallback = _recall_scope(
                self.store,
                query=query,
                scope=scope,
                include_sensitive=self.include_sensitive,
                limit=limit,
                access_context={
                    "usage": "tool:memory.recall",
                    "scope_label": label,
                    "task_id": task_id,
                    "run_id": run_id,
                    "step_id": step_id,
                    "thread_id": thread_id,
                    "project_id": project_id,
                    "query_hash": _hash_text(query) if query else None,
                },
            )
            if used_fallback:
                fallback_scopes.append(label)
            results[label] = _compact_recall_result(result.to_dict(), query=query, fallback_ranked=used_fallback)

        memory_ids = _ordered_unique(
            [
                str(item.get("memory_id"))
                for result in results.values()
                if isinstance(result, dict)
                for item in result.get("items", [])
                if isinstance(item, dict) and item.get("memory_id")
            ]
        )
        content: JsonObject = {
            "query_preview": _preview(query, MEMORY_RECALL_PREVIEW_CHARS),
            "query_hash": _hash_text(query) if query else None,
            "scope_mode": scope_mode,
            "limit_per_scope": limit,
            "results": results,
            "combined": {
                "total": len(memory_ids),
                "memory_ids": memory_ids,
            },
            "diagnostics": {
                "memory_store_configured": True,
                "include_sensitive": self.include_sensitive,
                "fallback_ranked_scopes": fallback_scopes,
                "project_id": project_id,
                "thread_id": thread_id,
            },
        }
        return Observation(
            observation_id=f"obs-{action.action_id}-memory-recall",
            run_id="",
            kind="memory_recall",
            status="ok",
            source=f"tool:{MEMORY_RECALL_TOOL_NAME}",
            content=content,
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )


def register_memory_tools(
    registry: ToolRegistry,
    *,
    store: MemoryStore,
    journal: JournalStore | None = None,
    user_id: str = _DEFAULT_USER_ID,
    project_id: str = _DEFAULT_PROJECT_ID,
    include_sensitive: bool = False,
) -> ToolRegistry:
    operator = MemoryRecallOperator(
        store=store,
        journal=journal,
        user_id=user_id,
        project_id=project_id,
        include_sensitive=include_sensitive,
    )
    registry.register(MEMORY_RECALL_TOOL_NAME, operator.execute, manifest=memory_recall_manifest())
    return registry


def memory_recall_manifest() -> ToolManifest:
    return ToolManifest(
        name=MEMORY_RECALL_TOOL_NAME,
        version="1",
        resource_kind="memory",
        operator_kind="recall",
        side_effect_class="read",
        permissions_required=[],
        enabled=True,
        description=(
            "Recall committed durable memory by workspace/project scope, thread scope, or both. "
            "Returns safe previews and refs only; models cannot write memory."
        ),
        input_schema={
            "query": {
                "type": "str",
                "required": False,
                "min_length": 1,
                "aliases": ["goal", "text"],
                "description": "Optional memory search query. If omitted, recent scoped memory is recalled.",
            },
            "scope_mode": {
                "type": "str",
                "required": False,
                "min_length": 1,
                "description": "workspace/project, thread, both, or all. Defaults to both.",
            },
            "limit": {
                "type": "int",
                "required": False,
                "min": 1,
                "max": MEMORY_RECALL_LIMIT_CAP,
                "description": "Maximum memory items per scope.",
            },
            "thread_id": {"type": "str", "required": False, "min_length": 1},
            "project_id": {"type": "str", "required": False, "min_length": 1},
        },
    )


_DEFAULT_THREAD_ID = "local:default"


def _recall_scope(
    store: MemoryStore,
    *,
    query: str | None,
    scope: JsonObject,
    include_sensitive: bool,
    limit: int,
    access_context: JsonObject,
):
    exact = store.recall(
        query=query or None,
        scope=scope,
        include_sensitive=include_sensitive,
        limit=limit,
        record_access=False,
        rank_query=query,
    )
    if exact.total > 0 or not query:
        return (
            store.recall(
                query=query or None,
                scope=scope,
                include_sensitive=include_sensitive,
                limit=limit,
                record_access=True,
                access_context=access_context,
                rank_query=query,
            ),
            False,
        )
    fallback = store.recall(
        query=None,
        scope=scope,
        include_sensitive=include_sensitive,
        limit=limit,
        record_access=True,
        access_context={**access_context, "fallback_ranked_recall": True},
        rank_query=query,
    )
    return fallback, True


def _compact_recall_result(result: JsonObject, *, query: str | None, fallback_ranked: bool) -> JsonObject:
    return {
        "query_hash": _hash_text(str(result.get("query"))) if result.get("query") else None,
        "scope": _dict(result.get("scope")),
        "total": result.get("total", 0),
        "filtered": _dict(result.get("filtered")),
        "generated_at_ms": result.get("generated_at_ms"),
        "diagnostics": {
            "fallback_ranked_recall": fallback_ranked,
            "match_query_hash": _hash_text(query) if query else None,
        },
        "items": [_compact_memory_item(item, query=query) for item in _list_of_dicts(result.get("items"))],
    }


def _compact_memory_item(item: JsonObject, *, query: str | None = None) -> JsonObject:
    body = _string(item.get("body")) or ""
    structured_summary = structured_memory_summary(_dict(item.get("structured")))
    payload = {
        "memory_id": item.get("memory_id"),
        "kind": item.get("kind"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "body_preview": _preview(body, MEMORY_RECALL_PREVIEW_CHARS) if body else "",
        "body_hash": _hash_text(body) if body else None,
        "scope": _dict(item.get("scope")),
        "privacy_class": item.get("privacy_class"),
        "confidence": item.get("confidence"),
        "structured_summary": structured_summary,
        "match_diagnostics": _memory_match_diagnostics(item, query=query, structured_summary=structured_summary),
        "provenance_refs": _string_list(item.get("provenance_refs")),
        "artifact_refs": _string_list(item.get("artifact_refs")),
        "updated_at_ms": item.get("updated_at_ms"),
        "last_accessed_ms": item.get("last_accessed_ms"),
    }
    return {key: value for key, value in payload.items() if value not in (None, [], {})}


def _memory_match_diagnostics(item: JsonObject, *, query: str | None, structured_summary: JsonObject) -> JsonObject:
    terms = _query_terms(query)
    if not terms:
        return {}
    fields = {
        "title": _string(item.get("title")) or "",
        "summary": _string(item.get("summary")) or "",
        "body": _string(item.get("body")) or "",
        "dedupe_key": _string(item.get("dedupe_key")) or "",
        "structured": _structured_match_text(structured_summary),
    }
    matched_fields: list[str] = []
    matched_terms: list[str] = []
    for field, text in fields.items():
        lowered = text.lower()
        field_terms = [term for term in terms if term in lowered]
        if not field_terms:
            continue
        matched_fields.append(field)
        matched_terms.extend(field_terms)
    structured_keys = _structured_hit_keys(structured_summary, terms=terms)
    if not matched_terms and not structured_keys:
        return {}
    return {
        "matched_terms": _ordered_unique(matched_terms)[:12],
        "matched_fields": _ordered_unique(matched_fields)[:8],
        "structured_hit_keys": structured_keys[:12],
        "match_score": len(_ordered_unique(matched_terms)) + len(structured_keys),
    }


def _scopes(*, scope_mode: str, user_id: str, project_id: str, thread_id: str) -> list[tuple[str, JsonObject]]:
    workspace = ("workspace", {"user_id": user_id, "project_id": project_id})
    thread = ("thread", {"user_id": user_id, "thread_id": thread_id})
    if scope_mode in {"workspace", "project", "all"}:
        return [workspace]
    if scope_mode == "thread":
        return [thread]
    return [workspace, thread]


def _query(payload: JsonObject, *, host_context: JsonObject) -> str | None:
    for key in ("query", "goal", "text"):
        value = _string(payload.get(key))
        if value:
            return value
    value = _string(host_context.get("input_text"))
    return value or None


def _scope_mode(value: object) -> str:
    text = _string(value)
    if not text:
        return "both"
    normalized = text.lower().replace("-", "_")
    aliases = {
        "global": "workspace",
        "project": "workspace",
        "workspace": "workspace",
        "workspace_memory": "workspace",
        "project_memory": "workspace",
        "thread_memory": "thread",
        "current_thread": "thread",
        "both": "both",
        "all": "all",
    }
    return aliases.get(normalized, normalized if normalized in _SCOPE_MODES else "both")


_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "how",
    "in",
    "is",
    "of",
    "please",
    "should",
    "the",
    "to",
    "use",
    "what",
    "you",
    "your",
}


def _query_terms(value: str | None) -> list[str]:
    if not value:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[\w\u4e00-\u9fff]+", value.lower()):
        for term in _expanded_query_terms(raw):
            if not term or term in seen or term in _QUERY_STOPWORDS:
                continue
            seen.add(term)
            terms.append(term)
    return terms


def _expanded_query_terms(term: str) -> list[str]:
    if not re.search(r"[\u4e00-\u9fff]", term):
        return [term]
    expanded = [term]
    if len(term) > 2:
        expanded.extend(term[index : index + 2] for index in range(0, len(term) - 1))
    return expanded


def _structured_match_text(summary: JsonObject) -> str:
    values = summary.get("values") if isinstance(summary.get("values"), dict) else {}
    parts: list[str] = []
    for key, value in values.items():
        parts.append(str(key))
        if isinstance(value, list):
            parts.extend(str(item) for item in value if isinstance(item, (str, int, float, bool)))
        elif isinstance(value, (str, int, float, bool)):
            parts.append(str(value))
    return " ".join(parts)


def _structured_hit_keys(summary: JsonObject, *, terms: list[str]) -> list[str]:
    values = summary.get("values") if isinstance(summary.get("values"), dict) else {}
    hits: list[str] = []
    for key, value in values.items():
        parts = [str(key)]
        if isinstance(value, list):
            parts.extend(str(item) for item in value if isinstance(item, (str, int, float, bool)))
        elif isinstance(value, (str, int, float, bool)):
            parts.append(str(value))
        text = " ".join(parts).lower()
        if any(term in text for term in terms):
            hits.append(str(key))
    return _ordered_unique(hits)


def _limit(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, MEMORY_RECALL_LIMIT_CAP))


def _preview(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)] + "..."


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dict(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _list_of_dicts(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
