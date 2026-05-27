from __future__ import annotations

import json
import re
from typing import Any, Callable

from .common import compact_text, stable_digest
from .stage113_agent_tool_executor import _load_memory_corpus
from .stage151_tool_decision_loop import (
    TIME_OBSERVATION_SCHEMA,
    WEB_OBSERVATION_SCHEMA,
    build_time_observation,
    evaluate_tool_decision_grounding,
    execute_tool_decision,
    repair_tool_decision_grounding,
    web_observations_to_tool_ledger,
)
from .stage171_market_research_action import execute_market_research_pack_action
from .stage174_market_research_report_action import execute_market_research_report_action
from .stage202_market_research_dossier_resume_action import execute_market_research_dossier_resume_action

STAGE152_TOOL_LOOP_SCHEMA = "holo.stage152.deepseek_tool_loop.v1"
STAGE152_LIVE_TRACE_SCHEMA = "holo.stage152.live_trace.v1"

NativeWebSearchFn = Callable[[str], dict[str, Any]]
NativeOpenPageFn = Callable[[str], dict[str, Any]]
NativeMemoryRecallFn = Callable[[dict[str, Any]], dict[str, Any]]
NativeModelCallFn = Callable[[dict[str, Any]], dict[str, Any]]


DEEPSEEK_NATIVE_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "time_observe": {
        "description": "Observe the host local and UTC time. Use for current time, today, or date-sensitive answers.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reason": {"type": "string", "description": "Why current host time is needed."},
            },
        },
    },
    "web_search": {
        "description": "Search the web for current or official evidence before answering.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "Precise search query.", "minLength": 1},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 8},
            },
            "required": ["query"],
        },
    },
    "open_page": {
        "description": "Open a specific web page URL and return a bounded title/snippet observation.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "description": "HTTP or HTTPS URL to open.", "minLength": 1},
            },
            "required": ["url"],
        },
    },
    "find_in_page": {
        "description": "Open a URL and check whether a pattern appears in the bounded page text.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "description": "HTTP or HTTPS URL to open.", "minLength": 1},
                "pattern": {"type": "string", "description": "Text pattern to find in the page.", "minLength": 1},
            },
            "required": ["url", "pattern"],
        },
    },
    "memory_recall": {
        "description": "Read-only recall over Holo memory evidence. Use before claiming prior conversation or user preference.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "Semantic recall query.", "minLength": 1},
                "thread_key": {"type": "string"},
                "chat_name": {"type": "string"},
                "channel": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 12},
            },
            "required": ["query"],
        },
    },
    "market_research_pack": {
        "description": "Build a read-only filing evidence pack before market or financial analysis claims.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "Company, ticker, period, and filing analysis request.", "minLength": 1},
                "entity": {"type": "string"},
                "filing_type": {"type": "string", "description": "SEC filing type, usually 10-K or 10-Q."},
                "filing_text": {"type": "string", "description": "Bounded filing text already retrieved by host evidence."},
                "source_url": {"type": "string"},
                "web_observation_ledger": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["query"],
        },
    },
    "market_research_report": {
        "description": "Generate a read-only filing-grounded market research report from authoritative filing evidence.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "Company, ticker, period, and report request.", "minLength": 1},
                "entity": {"type": "string"},
                "filing_type": {"type": "string", "description": "SEC filing type, usually 10-K or 10-Q."},
                "filing_text": {"type": "string", "description": "Bounded filing text already retrieved by host evidence."},
                "source_url": {"type": "string"},
                "web_observation_ledger": {"type": "array", "items": {"type": "object"}},
                "market_research_pack_ledger": {"type": "array", "items": {"type": "object"}},
                "market_research_pack": {"type": "object"},
            },
            "required": ["query"],
        },
    },
    "market_research_dossier_resume": {
        "description": "Load and resume the latest persisted market-research dossier for the current thread or project.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "thread_key": {"type": "string"},
                "project_key": {"type": "string"},
                "query": {"type": "string"},
                "max_actions": {"type": "integer", "minimum": 0, "maximum": 4},
            },
        },
    },
}


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _tool_schema(name: str) -> dict[str, Any]:
    definition = DEEPSEEK_NATIVE_TOOL_REGISTRY[name]
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": str(definition["description"]),
            "parameters": json.loads(json.dumps(definition["parameters"], ensure_ascii=False)),
        },
    }


def deepseek_native_tool_names() -> tuple[str, ...]:
    return tuple(DEEPSEEK_NATIVE_TOOL_REGISTRY.keys())


def build_deepseek_native_tool_payload(
    tool_names: list[str] | tuple[str, ...] | None = None,
    *,
    tool_choice: Any = "auto",
) -> dict[str, Any]:
    requested = list(tool_names or deepseek_native_tool_names())
    tools = [_tool_schema(name) for name in requested if name in DEEPSEEK_NATIVE_TOOL_REGISTRY]
    if not tools:
        return {"tools": [], "tool_choice": "none"}
    return {"tools": tools, "tool_choice": dict(tool_choice) if isinstance(tool_choice, dict) else str(tool_choice or "auto")}


def _first_choice(decoded: Any) -> dict[str, Any]:
    if not isinstance(decoded, dict):
        return {}
    choices = list(decoded.get("choices", []) or [])
    return dict(choices[0]) if choices and isinstance(choices[0], dict) else {}


def first_choice_message(decoded: Any) -> dict[str, Any]:
    choice = _first_choice(decoded)
    message = choice.get("message", {})
    return dict(message) if isinstance(message, dict) else {}


def _parse_arguments(raw: Any) -> tuple[dict[str, Any], str]:
    if isinstance(raw, dict):
        return dict(raw), ""
    if not isinstance(raw, str):
        return {}, "arguments_not_object"
    try:
        decoded = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}, "arguments_not_json"
    if not isinstance(decoded, dict):
        return {}, "arguments_not_object"
    return decoded, ""


def _validate_call(name: str, arguments: dict[str, Any]) -> str:
    definition = DEEPSEEK_NATIVE_TOOL_REGISTRY.get(name)
    if not definition:
        return "unknown_tool"
    required = list(dict(definition.get("parameters", {})).get("required", []) or [])
    for key in required:
        if key not in arguments or str(arguments.get(key, "") or "").strip() == "":
            return f"missing_required:{key}"
    if name in {"open_page", "find_in_page"}:
        url = str(arguments.get("url", "") or "").strip()
        if url and not re.match(r"^https?://", url, flags=re.IGNORECASE):
            return "url_must_be_http"
    return ""


def parse_deepseek_native_tool_calls(decoded: Any) -> list[dict[str, Any]]:
    message = first_choice_message(decoded)
    parsed: list[dict[str, Any]] = []
    for index, raw_call in enumerate(list(message.get("tool_calls", []) or [])):
        call = dict(raw_call) if isinstance(raw_call, dict) else {}
        function = dict(call.get("function", {})) if isinstance(call.get("function", {}), dict) else {}
        name = str(function.get("name", "") or "").strip()
        arguments, argument_error = _parse_arguments(function.get("arguments", {}))
        error = argument_error or _validate_call(name, arguments)
        parsed.append(
            {
                "id": str(call.get("id", "") or f"stage152_call_{index + 1}"),
                "type": str(call.get("type", "function") or "function"),
                "name": name,
                "arguments": arguments,
                "allowed": not bool(error),
                "status": "rejected" if error else "accepted",
                "error": error,
                "raw_tool_call": call,
            }
        )
    return parsed


def _coerce_usage_payload(payload: Any) -> dict[str, int | bool]:
    if payload is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
            "estimated": True,
        }
    if isinstance(payload, dict):
        prompt_tokens = int(payload.get("prompt_tokens", payload.get("input_tokens", 0)) or 0)
        completion_tokens = int(payload.get("completion_tokens", payload.get("output_tokens", 0)) or 0)
        total_tokens = int(payload.get("total_tokens", prompt_tokens + completion_tokens) or 0)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "prompt_cache_hit_tokens": int(payload.get("prompt_cache_hit_tokens", payload.get("cache_hit_tokens", 0)) or 0),
            "prompt_cache_miss_tokens": int(payload.get("prompt_cache_miss_tokens", payload.get("cache_miss_tokens", 0)) or 0),
            "estimated": bool(payload.get("estimated", False)),
        }
    prompt_tokens = int(getattr(payload, "prompt_tokens", getattr(payload, "input_tokens", 0)) or 0)
    completion_tokens = int(getattr(payload, "completion_tokens", getattr(payload, "output_tokens", 0)) or 0)
    total_tokens = int(getattr(payload, "total_tokens", prompt_tokens + completion_tokens) or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "prompt_cache_hit_tokens": int(getattr(payload, "prompt_cache_hit_tokens", getattr(payload, "cache_hit_tokens", 0)) or 0),
        "prompt_cache_miss_tokens": int(getattr(payload, "prompt_cache_miss_tokens", getattr(payload, "cache_miss_tokens", 0)) or 0),
        "estimated": False,
    }


def _sum_usage(*items: dict[str, int | bool]) -> dict[str, int | bool]:
    return {
        "prompt_tokens": sum(int(item.get("prompt_tokens", 0) or 0) for item in items),
        "completion_tokens": sum(int(item.get("completion_tokens", 0) or 0) for item in items),
        "total_tokens": sum(int(item.get("total_tokens", 0) or 0) for item in items),
        "prompt_cache_hit_tokens": sum(int(item.get("prompt_cache_hit_tokens", 0) or 0) for item in items),
        "prompt_cache_miss_tokens": sum(int(item.get("prompt_cache_miss_tokens", 0) or 0) for item in items),
        "estimated": any(bool(item.get("estimated", False)) for item in items),
    }


def _tool_result_message(call_id: str, observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(observation, ensure_ascii=False, sort_keys=True),
    }


def _assistant_tool_message(message: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    assistant = {
        "role": "assistant",
        "content": str(message.get("content", "") or ""),
        "tool_calls": [dict(call.get("raw_tool_call", {})) for call in calls if isinstance(call.get("raw_tool_call", {}), dict)],
    }
    if not assistant["tool_calls"]:
        assistant["tool_calls"] = [
            {
                "id": str(call.get("id", "") or ""),
                "type": "function",
                "function": {"name": str(call.get("name", "") or ""), "arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False)},
            }
            for call in calls
        ]
    reasoning_content = str(message.get("reasoning_content", "") or "")
    if reasoning_content:
        assistant["reasoning_content"] = reasoning_content
    return assistant


def _memory_recall_default(
    arguments: dict[str, Any],
    *,
    memory_corpus: Any = None,
    memory_corpus_path: str | None = None,
    repo_root: str | None = None,
) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    limit = max(1, min(int(arguments.get("limit", 6) or 6), 12))
    corpus = list(memory_corpus or _load_memory_corpus(memory_corpus_path, repo_root=repo_root))
    query_terms = {token.lower() for token in re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", query) if len(token) >= 2}
    matches: list[dict[str, Any]] = []
    for index, row in enumerate(corpus):
        item = dict(row) if isinstance(row, dict) else {"text": str(row)}
        text = str(item.get("text", "") or item.get("summary", "") or "")
        if not text:
            continue
        lowered = text.lower()
        overlap = sorted(term for term in query_terms if term in lowered)
        if not overlap:
            continue
        score = len(overlap) / max(1, len(query_terms))
        matches.append(
            {
                "id": str(item.get("id", "") or f"memory:{index + 1}"),
                "score": round(score, 4),
                "matched_terms": overlap,
                "text": _compact(text, 360),
                "source": str(item.get("source", "") or ""),
            }
        )
    matches.sort(key=lambda item: (-float(item["score"]), item["id"]))
    selected = matches[:limit]
    return {
        "schema": "holo.memory_observation.v1",
        "status": "ok" if selected else "empty",
        "query": query,
        "matches": selected,
        "summary": _compact("memory recall: " + " | ".join(item["text"] for item in selected[:3]), 420)
        if selected
        else _compact(f"memory recall: no local matches for {query}", 260),
    }


def _memory_tool_ledger(call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status", "") or "empty")
    return {
        "provider_call_id": call_id,
        "tool": "memory_recall",
        "status": "ok" if status == "ok" else status,
        "summary": _compact(payload.get("summary", ""), 420),
        "data_keys": ["query", "matches"],
        "grounding_tags": ["memory"] if status == "ok" and list(payload.get("matches", []) or []) else [],
        "query": str(payload.get("query", "") or ""),
    }


def _time_tool_ledger(call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_call_id": call_id,
        "tool": "time_observe",
        "status": "ok",
        "summary": _compact(f"time observe: local={payload.get('local_time', '')} utc={payload.get('utc_time', '')}"),
        "data_keys": ["local_time", "utc_time", "timezone"],
        "grounding_tags": ["time"],
    }


def execute_deepseek_native_tool_call(
    call: dict[str, Any],
    *,
    network_enabled: bool,
    web_search_fn: NativeWebSearchFn | None = None,
    open_page_fn: NativeOpenPageFn | None = None,
    memory_recall_fn: NativeMemoryRecallFn | None = None,
    memory_corpus: Any = None,
    memory_corpus_path: str | None = None,
    repo_root: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    call_id = str(call.get("id", "") or "stage152_call")
    name = str(call.get("name", "") or "")
    arguments = dict(call.get("arguments", {}) or {})
    if not bool(call.get("allowed", False)):
        return {
            "call_id": call_id,
            "tool": name,
            "status": "rejected",
            "summary": _compact(f"{name} rejected: {call.get('error', '')}"),
            "tool_message": _tool_result_message(call_id, {"tool": name, "status": "rejected", "error": str(call.get("error", "") or "")}),
            "tool_observation_ledger": [
                {
                    "provider_call_id": call_id,
                    "tool": name,
                    "status": "rejected",
                    "summary": _compact(f"tool rejected: {call.get('error', '')}"),
                    "data_keys": ["reason"],
                    "grounding_tags": [],
                }
            ],
        }
    if name == "time_observe":
        time_row = build_time_observation()
        return {
            "call_id": call_id,
            "tool": name,
            "status": "ok",
            "summary": _compact(f"time observe: {time_row.get('local_time', '')}"),
            "time_observation": time_row,
            "tool_message": _tool_result_message(call_id, {"tool": name, "status": "ok", "time_observation": time_row}),
            "tool_observation_ledger": [_time_tool_ledger(call_id, time_row)],
        }
    if name in {"web_search", "open_page", "find_in_page"}:
        action = {"action_type": name, **arguments}
        if name == "web_search":
            action["query"] = str(arguments.get("query", "") or "")
        observations = execute_tool_decision(
            {"selected_actions": [action]},
            network_enabled=network_enabled,
            web_search_fn=web_search_fn,
            open_page_fn=open_page_fn,
        )
        web_rows = [dict(row) for row in observations if isinstance(row, dict)]
        tool_ledger = web_observations_to_tool_ledger(web_rows)
        for row in tool_ledger:
            row["provider_call_id"] = call_id
            row["tool"] = name
        primary = web_rows[0] if web_rows else {"status": "empty", "error": "no_observation"}
        return {
            "call_id": call_id,
            "tool": name,
            "status": str(primary.get("status", "") or "empty"),
            "summary": _compact(f"{name}: {primary.get('status', '')} {primary.get('query', '') or primary.get('url', '')}"),
            "web_observation_ledger": web_rows,
            "tool_message": _tool_result_message(call_id, {"tool": name, "status": str(primary.get("status", "") or ""), "web_observation": primary}),
            "tool_observation_ledger": tool_ledger,
        }
    if name == "memory_recall":
        payload = (
            dict(memory_recall_fn(arguments))
            if callable(memory_recall_fn)
            else _memory_recall_default(arguments, memory_corpus=memory_corpus, memory_corpus_path=memory_corpus_path, repo_root=repo_root)
        )
        ledger = _memory_tool_ledger(call_id, payload)
        memory_row = {
            "schema": "holo.memory_grounding.v1",
            "memory_call_id": call_id,
            "source_family": "durable" if list(payload.get("matches", []) or []) else "none",
            "selected_ids": [str(item.get("id", "")) for item in list(payload.get("matches", []) or []) if isinstance(item, dict)],
            "status": "grounded" if list(payload.get("matches", []) or []) else "missing",
            "summary": str(payload.get("summary", "") or ""),
            "confidence": 0.78 if list(payload.get("matches", []) or []) else 0.0,
            "freshness": "runtime",
            "grounding_tags": ["memory"] if list(payload.get("matches", []) or []) else [],
            "contradiction_flags": [],
            "missing_source": not bool(list(payload.get("matches", []) or [])),
        }
        return {
            "call_id": call_id,
            "tool": name,
            "status": str(payload.get("status", "") or "empty"),
            "summary": _compact(payload.get("summary", ""), 420),
            "memory_observation_ledger": [memory_row],
            "tool_message": _tool_result_message(call_id, {"tool": name, "status": str(payload.get("status", "") or ""), "memory_observation": payload}),
            "tool_observation_ledger": [ledger],
        }
    if name == "market_research_pack":
        result = execute_market_research_pack_action(
            arguments,
            network_enabled=network_enabled,
            web_observation_ledger=arguments.get("web_observation_ledger", []),
            open_page_fn=open_page_fn,
        )
        ledger = [dict(row) for row in list(result.get("market_research_pack_ledger", []) or []) if isinstance(row, dict)]
        tool_ledger = [dict(row) for row in list(result.get("tool_observation_ledger", []) or []) if isinstance(row, dict)]
        for row in tool_ledger:
            row["provider_call_id"] = call_id
            row["tool"] = name
        primary = ledger[0] if ledger else {"status": "missing", "failure_reasons": ["market_research_pack_no_ledger"]}
        return {
            "call_id": call_id,
            "tool": name,
            "status": str(primary.get("status", "") or "missing"),
            "summary": _compact(
                f"{name}: {primary.get('status', '')} pack={primary.get('pack_status', '')} "
                f"failures={','.join(str(x) for x in list(primary.get('failure_reasons', []) or []))}",
                420,
            ),
            "stage169_market_research_pack": dict(result.get("stage169_market_research_pack", {}))
            if isinstance(result.get("stage169_market_research_pack", {}), dict)
            else {},
            "filing_text_retrieval": dict(result.get("filing_text_retrieval", {}))
            if isinstance(result.get("filing_text_retrieval", {}), dict)
            else {},
            "market_research_pack_ledger": ledger,
            "tool_message": _tool_result_message(
                call_id,
                {
                    "tool": name,
                    "status": str(primary.get("status", "") or ""),
                    "market_research_pack_ledger": ledger,
                },
            ),
            "tool_observation_ledger": tool_ledger,
        }
    if name == "market_research_report":
        result = execute_market_research_report_action(
            arguments,
            network_enabled=network_enabled,
            open_page_fn=open_page_fn,
        )
        report_ledger = [dict(row) for row in list(result.get("market_research_report_ledger", []) or []) if isinstance(row, dict)]
        pack_ledger = [dict(row) for row in list(result.get("market_research_pack_ledger", []) or []) if isinstance(row, dict)]
        tool_ledger = [dict(row) for row in list(result.get("tool_observation_ledger", []) or []) if isinstance(row, dict)]
        for row in tool_ledger:
            row["provider_call_id"] = call_id
            row["tool"] = name
        primary = report_ledger[0] if report_ledger else {"status": "missing", "failure_reasons": ["market_research_report_no_ledger"]}
        return {
            "call_id": call_id,
            "tool": name,
            "status": str(primary.get("status", "") or "missing"),
            "summary": _compact(
                f"{name}: {primary.get('status', '')} report={primary.get('report_status', '')} "
                f"sections={primary.get('section_count', 0)} metrics={primary.get('metric_count', 0)} "
                f"failures={','.join(str(x) for x in list(primary.get('failure_reasons', []) or []))}",
                480,
            ),
            "stage169_market_research_pack": dict(result.get("stage169_market_research_pack", {}))
            if isinstance(result.get("stage169_market_research_pack", {}), dict)
            else {},
            "stage173_market_research_report": dict(result.get("stage173_market_research_report", {}))
            if isinstance(result.get("stage173_market_research_report", {}), dict)
            else {},
            "filing_text_retrieval": dict(result.get("filing_text_retrieval", {}))
            if isinstance(result.get("filing_text_retrieval", {}), dict)
            else {},
            "market_research_pack_ledger": pack_ledger,
            "market_research_report_ledger": report_ledger,
            "tool_message": _tool_result_message(
                call_id,
                {
                    "tool": name,
                    "status": str(primary.get("status", "") or ""),
                    "market_research_report_ledger": report_ledger,
                },
            ),
            "tool_observation_ledger": tool_ledger,
        }
    if name == "market_research_dossier_resume":
        result = execute_market_research_dossier_resume_action(
            arguments,
            state_dir=state_dir,
            network_enabled=network_enabled,
            web_search_fn=web_search_fn,
            open_page_fn=open_page_fn,
        )
        ledger = [dict(row) for row in list(result.get("market_research_dossier_resume_ledger", []) or []) if isinstance(row, dict)]
        tool_ledger = [dict(row) for row in list(result.get("tool_observation_ledger", []) or []) if isinstance(row, dict)]
        for row in tool_ledger:
            row["provider_call_id"] = call_id
            row["tool"] = name
        primary = ledger[0] if ledger else {"status": "missing", "summary": "market_research_dossier_resume_no_ledger"}
        return {
            "call_id": call_id,
            "tool": name,
            "status": str(primary.get("status", "") or "missing"),
            "summary": _compact(
                f"{name}: {primary.get('status', '')} lookup={primary.get('lookup_status', '')} "
                f"action={primary.get('selected_action', '')}",
                420,
            ),
            "stage201_market_research_dossier_registry": dict(result.get("stage201_market_research_dossier_registry", {}))
            if isinstance(result.get("stage201_market_research_dossier_registry", {}), dict)
            else {},
            "market_research_dossier_resume_ledger": ledger,
            "tool_message": _tool_result_message(
                call_id,
                {
                    "tool": name,
                    "status": str(primary.get("status", "") or ""),
                    "market_research_dossier_resume_ledger": ledger,
                },
            ),
            "tool_observation_ledger": tool_ledger,
        }
    return {
        "call_id": call_id,
        "tool": name,
        "status": "rejected",
        "summary": f"{name} rejected: unknown_tool",
        "tool_message": _tool_result_message(call_id, {"tool": name, "status": "rejected", "error": "unknown_tool"}),
        "tool_observation_ledger": [],
    }


def _final_text(decoded: Any) -> str:
    return str(first_choice_message(decoded).get("content", "") or "").strip()


def _build_live_trace(
    *,
    purpose: str,
    calls: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    grounding: dict[str, Any],
    stop_reason: str,
    final_text: str,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = [{"event": "purpose", "summary": purpose}]
    for name in deepseek_native_tool_names():
        events.append({"event": "candidate", "action_type": name, "score": 0.5, "required_observations": [name]})
    for call in calls:
        events.append(
            {
                "event": "tool",
                "action_type": str(call.get("name", "") or ""),
                "call_id": str(call.get("id", "") or ""),
                "status": str(call.get("status", "") or ""),
                "query": _compact(dict(call.get("arguments", {}) or {}).get("query", "") or dict(call.get("arguments", {}) or {}).get("url", ""), 180),
            }
        )
    for item in observations:
        events.append(
            {
                "event": "observation",
                "action_type": str(item.get("tool", "") or ""),
                "status": str(item.get("status", "") or ""),
                "summary": _compact(item.get("summary", ""), 220),
                "source_urls": list(item.get("source_urls", []) or [])[:3],
                "result_count": len(list(item.get("results", []) or [])),
            }
        )
    events.append(
        {
            "event": "evaluate",
            "status": str(grounding.get("status", "") or ""),
            "missing_observations": list(grounding.get("missing_observations", []) or []),
        }
    )
    events.append({"event": "stop", "summary": stop_reason})
    events.append({"event": "final", "summary": _compact(final_text, 260)})
    return {
        "schema": STAGE152_LIVE_TRACE_SCHEMA,
        "status": "recorded",
        "event_count": len(events),
        "events": events,
    }


def run_deepseek_native_tool_loop(
    *,
    initial_decoded: dict[str, Any],
    base_payload: dict[str, Any],
    call_model: NativeModelCallFn,
    network_enabled: bool,
    max_rounds: int = 4,
    max_tool_calls: int = 16,
    web_search_fn: NativeWebSearchFn | None = None,
    open_page_fn: NativeOpenPageFn | None = None,
    memory_recall_fn: NativeMemoryRecallFn | None = None,
    memory_corpus: Any = None,
    memory_corpus_path: str | None = None,
    repo_root: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    messages = list(base_payload.get("messages", []) or [])
    current_decoded = dict(initial_decoded)
    usage = _coerce_usage_payload(current_decoded.get("usage"))
    all_calls: list[dict[str, Any]] = []
    executed_results: list[dict[str, Any]] = []
    assistant_messages: list[dict[str, Any]] = []
    tool_messages: list[dict[str, Any]] = []
    tool_observation_ledger: list[dict[str, Any]] = []
    web_observation_ledger: list[dict[str, Any]] = []
    memory_observation_ledger: list[dict[str, Any]] = []
    market_research_pack_ledger: list[dict[str, Any]] = []
    market_research_report_ledger: list[dict[str, Any]] = []
    market_research_dossier_resume_ledger: list[dict[str, Any]] = []
    stage169_market_research_pack: dict[str, Any] = {}
    stage173_market_research_report: dict[str, Any] = {}
    stage201_market_research_dossier_registry: dict[str, Any] = {}
    filing_text_retrieval: dict[str, Any] = {}
    time_observation: dict[str, Any] = {}
    stop_reason = "no_tool_calls"
    final_request_sent = False
    exhausted = False
    reasoning_content_retained_count = 0

    for round_index in range(max(1, min(int(max_rounds or 1), 8))):
        calls = parse_deepseek_native_tool_calls(current_decoded)
        if not calls:
            stop_reason = "no_tool_calls" if round_index == 0 else "model_final_no_tool_calls"
            break
        remaining = max(0, int(max_tool_calls or 0) - len(all_calls))
        if remaining <= 0:
            stop_reason = "tool_call_budget_exceeded"
            exhausted = True
            break
        active_calls = calls[:remaining]
        all_calls.extend(calls)
        current_message = first_choice_message(current_decoded)
        assistant_message = _assistant_tool_message(current_message, active_calls)
        if assistant_message.get("reasoning_content"):
            reasoning_content_retained_count += 1
        assistant_messages.append(assistant_message)
        round_tool_messages: list[dict[str, Any]] = []
        for call in active_calls:
            result = execute_deepseek_native_tool_call(
                call,
                network_enabled=network_enabled,
                web_search_fn=web_search_fn,
                open_page_fn=open_page_fn,
                memory_recall_fn=memory_recall_fn,
                memory_corpus=memory_corpus,
                memory_corpus_path=memory_corpus_path,
                repo_root=repo_root,
                state_dir=state_dir,
            )
            executed_results.append(result)
            round_tool_messages.append(dict(result["tool_message"]))
            tool_observation_ledger.extend([dict(row) for row in list(result.get("tool_observation_ledger", []) or []) if isinstance(row, dict)])
            web_observation_ledger.extend([dict(row) for row in list(result.get("web_observation_ledger", []) or []) if isinstance(row, dict)])
            memory_observation_ledger.extend([dict(row) for row in list(result.get("memory_observation_ledger", []) or []) if isinstance(row, dict)])
            market_research_pack_ledger.extend(
                [dict(row) for row in list(result.get("market_research_pack_ledger", []) or []) if isinstance(row, dict)]
            )
            market_research_report_ledger.extend(
                [dict(row) for row in list(result.get("market_research_report_ledger", []) or []) if isinstance(row, dict)]
            )
            market_research_dossier_resume_ledger.extend(
                [dict(row) for row in list(result.get("market_research_dossier_resume_ledger", []) or []) if isinstance(row, dict)]
            )
            if isinstance(result.get("stage169_market_research_pack", {}), dict) and result.get("stage169_market_research_pack"):
                stage169_market_research_pack = dict(result.get("stage169_market_research_pack", {}))
            if isinstance(result.get("stage173_market_research_report", {}), dict) and result.get("stage173_market_research_report"):
                stage173_market_research_report = dict(result.get("stage173_market_research_report", {}))
            if isinstance(result.get("stage201_market_research_dossier_registry", {}), dict) and result.get("stage201_market_research_dossier_registry"):
                stage201_market_research_dossier_registry = dict(result.get("stage201_market_research_dossier_registry", {}))
            if isinstance(result.get("filing_text_retrieval", {}), dict) and result.get("filing_text_retrieval"):
                filing_text_retrieval = dict(result.get("filing_text_retrieval", {}))
            if isinstance(result.get("time_observation", {}), dict) and result.get("time_observation"):
                time_observation = dict(result.get("time_observation", {}))
        tool_messages.extend(round_tool_messages)
        messages = messages + [assistant_message] + round_tool_messages
        followup_payload = dict(base_payload)
        followup_payload["messages"] = messages
        followup_payload["tool_choice"] = "none" if exhausted or len(all_calls) >= int(max_tool_calls or 0) else "auto"
        current_decoded = dict(call_model(followup_payload))
        final_request_sent = True
        usage = _sum_usage(usage, _coerce_usage_payload(current_decoded.get("usage")))
        if len(all_calls) >= int(max_tool_calls or 0):
            exhausted = True
            stop_reason = "tool_call_budget_exceeded"
            break
    else:
        stop_reason = "max_rounds_reached"
        exhausted = True

    final_text = _final_text(current_decoded)
    grounding = evaluate_tool_decision_grounding(
        final_text,
        web_observation_ledger=web_observation_ledger,
        time_observation=time_observation,
    )
    repaired_final_text = repair_tool_decision_grounding(final_text, grounding, channel="holo_cli") if bool(grounding.get("repair_required", False)) else final_text
    if repaired_final_text != final_text:
        final_text = repaired_final_text
        grounding = evaluate_tool_decision_grounding(final_text, web_observation_ledger=web_observation_ledger, time_observation=time_observation)
    observations_for_trace = []
    for row in tool_observation_ledger:
        item = dict(row)
        if "source_urls" not in item:
            matching = [web for web in web_observation_ledger if str(web.get("action_type", "")) == str(item.get("tool", ""))]
            if matching:
                item["source_urls"] = list(matching[0].get("source_urls", []) or [])
                item["results"] = list(matching[0].get("results", []) or [])
        observations_for_trace.append(item)
    live_trace = _build_live_trace(
        purpose="native_deepseek_tool_loop" if all_calls else "answer_direct",
        calls=all_calls,
        observations=observations_for_trace,
        grounding=grounding,
        stop_reason=stop_reason,
        final_text=final_text,
    )
    return {
        "schema": STAGE152_TOOL_LOOP_SCHEMA,
        "status": "completed" if not exhausted else "stopped",
        "final_decoded": current_decoded,
        "final_text": final_text,
        "messages": messages,
        "assistant_messages_internal": assistant_messages,
        "tool_messages": tool_messages,
        "tool_call_count": len(all_calls),
        "executed_count": len([item for item in executed_results if str(item.get("status", "")) not in {"rejected"}]),
        "round_count": len(assistant_messages),
        "final_request_sent": final_request_sent,
        "stop_reason": stop_reason,
        "exhausted": exhausted,
        "usage": usage,
        "reasoning_content_retained_count": reasoning_content_retained_count,
        "tool_observation_ledger": tool_observation_ledger,
        "web_observation_ledger": web_observation_ledger,
        "memory_observation_ledger": memory_observation_ledger,
        "market_research_pack_ledger": market_research_pack_ledger,
        "market_research_report_ledger": market_research_report_ledger,
        "market_research_dossier_resume_ledger": market_research_dossier_resume_ledger,
        "stage169_market_research_pack": stage169_market_research_pack,
        "stage173_market_research_report": stage173_market_research_report,
        "stage201_market_research_dossier_registry": stage201_market_research_dossier_registry,
        "filing_text_retrieval": filing_text_retrieval,
        "time_observation": time_observation,
        "grounding": grounding,
        "live_trace": live_trace,
        "rounds": [
            {
                "round": index + 1,
                "tool_names": [str(call.get("name", "") or "") for call in parse_deepseek_native_tool_calls({"choices": [{"message": assistant_messages[index]}]})],
                "executed_count": len([msg for msg in tool_messages if msg.get("role") == "tool"]),
            }
            for index in range(len(assistant_messages))
        ],
    }


def format_stage152_live_trace(payload: dict[str, Any]) -> str:
    trace = dict(payload.get("stage152_live_trace", payload.get("stage152_deepseek_tool_loop", {}).get("live_trace", payload))) if isinstance(payload, dict) else {}
    events = list(trace.get("events", []) or []) if isinstance(trace, dict) else []
    lines: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("event", "") or "")
        if kind == "purpose":
            lines.append(f"[purpose] {event.get('summary', '')}")
        elif kind == "candidate":
            need = ",".join(str(item) for item in list(event.get("required_observations", []) or [])) or "-"
            lines.append(f"[candidate] {event.get('action_type', '')} score={event.get('score', 0)} need={need}")
        elif kind in {"tool", "tool_call"}:
            lines.append(f"[tool] {event.get('action_type', '')} id={event.get('call_id', '')} status={event.get('status', '')} query={event.get('query', '')}")
        elif kind in {"observation", "tool_observation"}:
            sources = ",".join(str(url) for url in list(event.get("source_urls", []) or [])[:3])
            source_suffix = f" sources={sources}" if sources else ""
            lines.append(f"[observation] {event.get('action_type', event.get('tool', ''))} status={event.get('status', '')} results={event.get('result_count', 0)}{source_suffix}")
        elif kind in {"evaluate", "grounding"}:
            missing = ",".join(str(item) for item in list(event.get("missing_observations", []) or [])) or "-"
            lines.append(f"[evaluate] status={event.get('status', '') or '-'} missing={missing}")
        elif kind == "stop":
            lines.append(f"[stop] {event.get('summary', '')}")
        elif kind == "final":
            lines.append(f"[final] {event.get('summary', '')}")
    return "\n".join(lines)
