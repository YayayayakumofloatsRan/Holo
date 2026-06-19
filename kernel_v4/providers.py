from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field

from kernel_v4.contracts import ChatMessage, JsonObject, ModelEvent, ToolCall, ToolManifest

_NATIVE_TOOL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_NATIVE_TOOL_NAME_CHARS = 64


@dataclass(frozen=True, kw_only=True)
class ProviderAvailability:
    available: bool
    reason: str
    provider: str
    model: str
    base_url: str = ""

    def to_dict(self) -> JsonObject:
        return {
            "available": self.available,
            "reason": self.reason,
            "provider": self.provider,
            "model": self.model,
            **({"base_url": self.base_url} if self.base_url else {}),
        }


@dataclass
class NativeToolSurface:
    tools: list[JsonObject]
    name_map: dict[str, str]
    deferred_tools: list[JsonObject] = field(default_factory=list)


class OpenAICompatibleChatProvider:
    """Kernel v4 native tool-call provider for OpenAI-compatible chat APIs."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key_env: str = "OPENAI_COMPATIBLE_API_KEY",
        model: str = "local-model",
        enabled: bool = True,
        timeout_seconds: int = 90,
        max_retries: int = 1,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tool_choice: str | JsonObject = "auto",
        parallel_tool_calls: bool | None = True,
        force_tool_name: str | None = None,
        force_tool_turns: int | None = 1,
        include_usage: bool = True,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.enabled = enabled
        self.base_url = (base_url or os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "")).strip().rstrip("/")
        self.api_key_env = api_key_env
        self.model = model
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_retries = max(0, int(max_retries))
        self.temperature = max(0.0, min(float(temperature), 2.0))
        self.max_tokens = max_tokens
        self.tool_choice = tool_choice
        self.parallel_tool_calls = None if parallel_tool_calls is None else bool(parallel_tool_calls)
        self.force_tool_name = (force_tool_name or "").strip() or None
        self.force_tool_turns = None if force_tool_turns is None else max(1, int(force_tool_turns))
        self.include_usage = bool(include_usage)
        self.thinking = _normalize_thinking(thinking)
        self.reasoning_effort = _normalize_reasoning_effort(reasoning_effort)

    def availability(self) -> ProviderAvailability:
        if not self.enabled:
            return ProviderAvailability(available=False, reason="provider_disabled", provider=self.name, model=self.model)
        if not self.base_url:
            return ProviderAvailability(available=False, reason="missing_base_url", provider=self.name, model=self.model)
        if not self._api_key():
            return ProviderAvailability(
                available=False,
                reason="missing_api_key",
                provider=self.name,
                model=self.model,
                base_url=self._completion_url(),
            )
        return ProviderAvailability(
            available=True,
            reason="available",
            provider=self.name,
            model=self.model,
            base_url=self._completion_url(),
        )

    async def stream(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolManifest],
        system_prompt: str,
        context: JsonObject,
    ):
        available = self.availability()
        if not available.available:
            raise RuntimeError(f"{self.name} unavailable: {available.reason}")
        payload, name_map = self.build_payload(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            context=context,
            stream=True,
        )
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_deltas: dict[int, _StreamingToolCallBuilder] = {}
        usage_chunks: list[JsonObject] = []
        chunk_queue: queue.Queue[object] = queue.Queue()
        sentinel = object()
        producer_thread = threading.Thread(
            target=_produce_sse_chunks,
            args=(
                self._post_sse_json_with_retries(
                    self._completion_url(),
                    self._api_key(),
                    payload,
                    self.timeout_seconds,
                ),
                chunk_queue,
                sentinel,
            ),
            daemon=True,
        )
        producer_thread.start()
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            queued = await _get_thread_queue_item(
                chunk_queue,
                deadline=deadline,
                provider_name=self.name,
                timeout_seconds=self.timeout_seconds,
            )
            if queued is sentinel:
                break
            if isinstance(queued, BaseException):
                raise queued
            chunk = queued if isinstance(queued, dict) else {}
            usage = _normalize_usage(chunk.get("usage"))
            if usage:
                usage_chunks.append(usage)
            for choice in _choices(chunk):
                delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    text_parts.append(content)
                    yield ModelEvent(event_type="text_delta", text=content)
                reasoning_content = delta.get("reasoning_content")
                if isinstance(reasoning_content, str) and reasoning_content:
                    reasoning_parts.append(reasoning_content)
                for raw_tool in _tool_call_deltas(delta.get("tool_calls")):
                    index = _tool_delta_index(raw_tool)
                    builder = tool_deltas.setdefault(index, _StreamingToolCallBuilder(index=index))
                    builder.apply(raw_tool)
                    call = builder.take_if_complete(name_map=name_map)
                    if call is not None:
                        yield ModelEvent(event_type="tool_call", tool_call=call)
                finish_reason = choice.get("finish_reason")
                if isinstance(finish_reason, str) and finish_reason:
                    break
        for index in sorted(tool_deltas):
            builder = tool_deltas[index]
            if builder.emitted:
                continue
            call = builder.to_tool_call(name_map=name_map)
            if call is not None:
                yield ModelEvent(event_type="tool_call", tool_call=call)
        yield ModelEvent(
            event_type="message_stop",
            metadata={
                "provider": self.name,
                "model": payload["model"],
                "text_chars": sum(len(part) for part in text_parts),
                "reasoning_content_chars": sum(len(part) for part in reasoning_parts),
                "tool_call_count": len(tool_deltas),
                **({"reasoning_content": "".join(reasoning_parts)} if reasoning_parts else {}),
                **({"usage": _merge_usage_chunks(usage_chunks)} if usage_chunks else {}),
            },
        )

    def build_payload(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolManifest],
        system_prompt: str,
        context: JsonObject,
        stream: bool,
    ) -> tuple[JsonObject, dict[str, str]]:
        native_surface = openai_native_tool_surface_v4(tools)
        resolve_name_map = {
            **_historical_native_tool_name_map(messages),
            **native_surface.name_map,
        }
        provider_messages = _provider_messages(
            messages,
            system_prompt=system_prompt,
            context=context,
            name_map=native_surface.name_map,
        )
        payload: JsonObject = {
            "model": self.model,
            "messages": provider_messages,
            "stream": bool(stream),
            "temperature": self.temperature,
        }
        if self.thinking:
            payload["thinking"] = {"type": self.thinking}
            if self.thinking == "enabled" and self.reasoning_effort:
                payload["reasoning_effort"] = self.reasoning_effort
        if stream and self.include_usage:
            payload["stream_options"] = {"include_usage": True}
        if self.max_tokens is not None:
            payload["max_tokens"] = max(1, int(self.max_tokens))
        if native_surface.tools:
            forced_tool = self.force_tool_name if self._should_force_tool(context) else None
            payload["tools"] = native_surface.tools
            payload["tool_choice"] = (
                _forced_tool_choice(forced_tool, native_surface.name_map)
                if forced_tool
                else self.tool_choice
            )
            if self.parallel_tool_calls is not None:
                payload["parallel_tool_calls"] = self.parallel_tool_calls
        elif self.force_tool_name:
            raise ValueError(f"forced tool is not visible to provider: {self.force_tool_name}")
        return payload, resolve_name_map

    def _should_force_tool(self, context: JsonObject) -> bool:
        if not self.force_tool_name:
            return False
        if self.force_tool_turns is None:
            return True
        try:
            turn_index = int(context.get("turn_index", 1))
        except (TypeError, ValueError):
            turn_index = 1
        return turn_index <= self.force_tool_turns

    def packet_preview(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolManifest],
        system_prompt: str,
        context: JsonObject,
    ) -> JsonObject:
        payload, name_map = self.build_payload(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            context=context,
            stream=True,
        )
        safe = json.loads(json.dumps(payload, ensure_ascii=False))
        for message in safe.get("messages", []) if isinstance(safe.get("messages"), list) else []:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True)
            message["content"] = {"preview": _preview(text, 640), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "chars": len(text)}
        return {
            "provider": self.name,
            "model": self.model,
            "url": self._completion_url(),
            "api_key": "set" if self._api_key() else "missing",
            "body": safe,
            "native_tool_name_map": dict(name_map),
        }

    def _api_key(self) -> str:
        return str(os.environ.get(self.api_key_env, "") or "").strip()

    def _completion_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _post_sse_json_with_retries(
        self,
        url: str,
        api_key: str,
        payload: JsonObject,
        timeout_seconds: int,
    ) -> Iterable[JsonObject]:
        last_error: RuntimeError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                yield from self._post_sse_json(url, api_key, payload, timeout_seconds)
                return
            except RuntimeError as exc:
                last_error = exc
                if attempt >= self.max_retries or not _retryable_provider_error(str(exc)):
                    raise
        raise last_error or RuntimeError(f"{self.name} request failed")

    def _post_sse_json(self, url: str, api_key: str, payload: JsonObject, timeout_seconds: int) -> Iterable[JsonObject]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
                yield from _iter_sse_json_with_deadline(response, timeout_seconds, provider_name=self.name)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.name} HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{self.name} network error: {exc.reason}") from exc
        except (TimeoutError, http.client.IncompleteRead, http.client.RemoteDisconnected) as exc:
            raise RuntimeError(f"{self.name} network error: {type(exc).__name__}: {exc}") from exc


class DeepSeekChatProvider(OpenAICompatibleChatProvider):
    name = "deepseek"

    def __init__(
        self,
        *,
        model: str | None = None,
        enabled: bool = True,
        timeout_seconds: int = 90,
        max_retries: int = 1,
        tool_choice: str | JsonObject = "auto",
        force_tool_name: str | None = None,
        force_tool_turns: int | None = 1,
        include_usage: bool = True,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        super().__init__(
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "") or "https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY",
            model=model
            or os.environ.get("HOLO_V4_MODEL", "")
            or os.environ.get("DEEPSEEK_MODEL", "")
            or "deepseek-v4-pro",
            enabled=enabled,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            tool_choice=tool_choice,
            parallel_tool_calls=None,
            force_tool_name=force_tool_name,
            force_tool_turns=force_tool_turns,
            include_usage=include_usage,
            thinking=(
                thinking
                if thinking is not None
                else os.environ.get("HOLO_V4_DEEPSEEK_THINKING")
                or os.environ.get("DEEPSEEK_THINKING")
                or "disabled"
            ),
            reasoning_effort=(
                reasoning_effort
                if reasoning_effort is not None
                else os.environ.get("HOLO_V4_DEEPSEEK_REASONING_EFFORT")
                or os.environ.get("DEEPSEEK_REASONING_EFFORT")
                or None
            ),
        )


@dataclass
class _StreamingToolCallBuilder:
    index: int
    tool_call_id: str = ""
    name: str = ""
    arguments: str = ""
    emitted: bool = False

    def apply(self, delta: JsonObject) -> None:
        call_id = delta.get("id")
        if isinstance(call_id, str) and call_id:
            self.tool_call_id = call_id
        function = delta.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str) and name:
                self.name = name
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                self.arguments += arguments

    def to_tool_call(self, *, name_map: dict[str, str]) -> ToolCall | None:
        real_name = _resolve_provider_tool_name(self.name, name_map)
        if not real_name:
            return None
        try:
            parsed = json.loads(self.arguments or "{}")
        except json.JSONDecodeError:
            parsed = {"_raw_arguments": self.arguments, "_parse_error": "json_decode_error"}
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
        return ToolCall(
            tool_call_id=self.tool_call_id or f"tool-call-{self.index}",
            name=real_name,
            input=parsed,
        )

    def take_if_complete(self, *, name_map: dict[str, str]) -> ToolCall | None:
        if self.emitted or not self.name:
            return None
        if not self.arguments.strip():
            return None
        try:
            parsed = json.loads(self.arguments)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
        real_name = _resolve_provider_tool_name(self.name, name_map)
        if not real_name:
            return None
        self.emitted = True
        return ToolCall(
            tool_call_id=self.tool_call_id or f"tool-call-{self.index}",
            name=real_name,
            input=parsed,
        )


def openai_native_tool_surface_v4(manifests: list[ToolManifest]) -> NativeToolSurface:
    tools: list[JsonObject] = []
    name_map: dict[str, str] = {}
    deferred: list[JsonObject] = []
    for manifest in sorted(manifests, key=lambda item: item.name):
        if not manifest.enabled:
            continue
        if manifest.should_defer and not manifest.always_load:
            deferred.append({"name": manifest.name, "description": manifest.description})
            continue
        native_name = _native_tool_name(manifest.name)
        if native_name in name_map and name_map[native_name] != manifest.name:
            native_name = _native_tool_name(manifest.name, force_hash=True)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": native_name,
                    "description": _tool_description(manifest),
                    "parameters": _json_schema_for_input_schema(manifest.input_schema),
                },
            }
        )
        name_map[native_name] = manifest.name
    return NativeToolSurface(tools=tools, name_map=name_map, deferred_tools=deferred)


def _provider_messages(
    messages: list[ChatMessage],
    *,
    system_prompt: str,
    context: JsonObject,
    name_map: dict[str, str],
) -> list[JsonObject]:
    context_text = json.dumps(context, ensure_ascii=False, sort_keys=True)
    result: list[JsonObject] = [
        {
            "role": "system",
            "content": system_prompt.rstrip(),
        }
    ]
    for message in messages:
        if message.role == "system":
            result.append({"role": "system", "content": message.content})
        elif message.role == "user":
            result.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            payload: JsonObject = {"role": "assistant", "content": message.content or None}
            reasoning_content = message.metadata.get("_private_reasoning_content") or message.metadata.get(
                "reasoning_content"
            )
            if isinstance(reasoning_content, str) and reasoning_content:
                payload["reasoning_content"] = reasoning_content
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": call.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": _native_name_for_tool(call.name, name_map),
                            "arguments": json.dumps(call.input, ensure_ascii=False, sort_keys=True),
                        },
                    }
                    for call in message.tool_calls
                ]
            result.append(payload)
        elif message.role == "tool":
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id or "",
                    "content": message.content,
                }
            )
    if context:
        result.append(
            {
                "role": "system",
                "content": (
                    "Runtime context for this assistant turn. This is host metadata, not a new user task. "
                    "Use it to choose tools, respect budgets, avoid repeated tool calls, and decide whether to finalize.\n"
                    + context_text
                ),
            }
        )
    return result


def _native_tool_name(tool_name: str, *, force_hash: bool = False) -> str:
    digest = hashlib.sha256(tool_name.encode("utf-8")).hexdigest()[:8]
    slug = _native_tool_alias(tool_name)
    needs_hash = force_hash or slug != tool_name or len(slug) > _MAX_NATIVE_TOOL_NAME_CHARS
    if not needs_hash:
        return slug
    suffix = "_" + digest
    max_base = max(1, _MAX_NATIVE_TOOL_NAME_CHARS - len(suffix))
    return (slug[:max_base].rstrip("_") or "tool") + suffix


def _native_tool_alias(tool_name: str) -> str:
    slug = _NATIVE_TOOL_NAME_RE.sub("_", str(tool_name or "")).strip("_")
    return re.sub(r"_+", "_", slug) or "tool"


def _historical_native_tool_name_map(messages: list[ChatMessage]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    for message in messages:
        for call in message.tool_calls:
            real_name = str(call.name or "").strip()
            if not real_name:
                continue
            _add_unique_native_name(mapping, ambiguous, _native_tool_name(real_name), real_name)
            _add_unique_native_name(mapping, ambiguous, _native_tool_alias(real_name), real_name)
    return mapping


def _add_unique_native_name(mapping: dict[str, str], ambiguous: set[str], native_name: str, real_name: str) -> None:
    native = str(native_name or "").strip()
    real = str(real_name or "").strip()
    if not native or not real or native in ambiguous:
        return
    existing = mapping.get(native)
    if existing is None:
        mapping[native] = real
        return
    if existing != real:
        mapping.pop(native, None)
        ambiguous.add(native)


def _resolve_provider_tool_name(raw_name: str, name_map: dict[str, str]) -> str:
    """Resolve provider-emitted function names to Kernel v4 tool names.

    Some OpenAI-compatible providers expose the hashed native name in the
    schema but stream back the unsuffixed sanitized alias, e.g.
    ``sec_edgar_financials`` for ``sec.edgar.financials``. Treat those aliases
    as valid only when they map to one registered tool.
    """

    name = str(raw_name or "").strip()
    if not name:
        return ""
    mapped = name_map.get(name)
    if mapped:
        return mapped
    if name in set(name_map.values()):
        return name
    aliases: dict[str, str | None] = {}
    for real_name in name_map.values():
        alias = _native_tool_alias(real_name)
        if alias in aliases and aliases[alias] != real_name:
            aliases[alias] = None
        else:
            aliases[alias] = real_name
    alias_match = aliases.get(name)
    return alias_match or name


def _normalize_thinking(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().casefold()
    if not normalized or normalized in {"auto", "provider-default", "default", "none"}:
        return None
    if normalized not in {"enabled", "disabled"}:
        raise ValueError(f"thinking must be enabled, disabled, or omitted; got {value!r}")
    return normalized


def _normalize_reasoning_effort(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().casefold()
    if not normalized or normalized in {"auto", "provider-default", "default", "none"}:
        return None
    if normalized not in {"low", "medium", "high", "max"}:
        raise ValueError(f"reasoning_effort must be low, medium, high, max, or omitted; got {value!r}")
    return normalized


def _native_name_for_tool(tool_name: str, name_map: dict[str, str]) -> str:
    for native_name, real_name in name_map.items():
        if real_name == tool_name:
            return native_name
    return _native_tool_name(tool_name)


def _forced_tool_choice(tool_name: str | None, name_map: dict[str, str]) -> JsonObject:
    requested = (tool_name or "").strip()
    if not requested:
        return {"type": "auto"}
    native_name = _native_name_for_tool(requested, name_map)
    if name_map.get(native_name) != requested:
        raise ValueError(f"forced tool is not visible to provider: {requested}")
    return {"type": "function", "function": {"name": native_name}}


def _tool_description(manifest: ToolManifest) -> str:
    pieces = [
        f"Holo tool: {manifest.name}.",
        manifest.description,
        f"Side effect class: {manifest.side_effect_class}.",
    ]
    return " ".join(piece for piece in pieces if piece).strip()[:1024]


def _json_schema_for_input_schema(input_schema: JsonObject) -> JsonObject:
    properties: JsonObject = {}
    required: list[str] = []
    for key, raw_spec in sorted(input_schema.items()):
        name = str(key)
        if name.startswith("_"):
            continue
        spec = _schema_spec(raw_spec)
        properties[name] = _json_schema_property(spec)
        if bool(spec.get("required")):
            required.append(name)
    schema: JsonObject = {"type": "object", "properties": properties, "additionalProperties": True}
    if required:
        schema["required"] = required
    return schema


def _schema_spec(raw_spec: object) -> JsonObject:
    if isinstance(raw_spec, dict):
        return {
            "type": str(raw_spec.get("type") or "object"),
            "required": bool(raw_spec.get("required", False)),
            "min_length": raw_spec.get("min_length"),
            "min": raw_spec.get("min"),
            "max": raw_spec.get("max"),
            "description": raw_spec.get("description"),
        }
    text = str(raw_spec)
    return {"type": text.split()[0], "required": "optional" not in text}


def _json_schema_property(spec: JsonObject) -> JsonObject:
    declared = str(spec.get("type") or "object").strip().lower()
    prop = _json_type_for_declared_type(declared)
    description = spec.get("description")
    if isinstance(description, str) and description:
        prop["description"] = description
    min_length = _optional_int(spec.get("min_length"))
    if min_length is not None and prop.get("type") == "string":
        prop["minLength"] = min_length
    minimum = _optional_number(spec.get("min"))
    if minimum is not None and prop.get("type") in {"integer", "number"}:
        prop["minimum"] = minimum
    maximum = _optional_number(spec.get("max"))
    if maximum is not None and prop.get("type") in {"integer", "number"}:
        prop["maximum"] = maximum
    return prop


def _json_type_for_declared_type(declared_type: str) -> JsonObject:
    if declared_type in {"str", "string"}:
        return {"type": "string"}
    if declared_type in {"int", "integer"}:
        return {"type": "integer"}
    if declared_type in {"float", "number", "decimal"}:
        return {"type": "number"}
    if declared_type in {"bool", "boolean"}:
        return {"type": "boolean"}
    if declared_type.startswith("list[") or declared_type in {"list", "array"}:
        return {"type": "array", "items": _array_item_schema(declared_type)}
    return {"type": "object", "additionalProperties": True}


def _array_item_schema(declared_type: str) -> JsonObject:
    if declared_type == "list[str]":
        return {"type": "string"}
    if declared_type == "list[int]":
        return {"type": "integer"}
    if declared_type == "list[object]":
        return {"type": "object", "additionalProperties": True}
    return {}


def _iter_sse_json_with_deadline(response: object, timeout_seconds: int, *, provider_name: str) -> Iterable[JsonObject]:
    timeout = max(1, int(timeout_seconds))
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{provider_name} stream read exceeded {timeout}s")
        _set_response_socket_timeout(response, max(0.001, remaining))
        try:
            line = response.readline()  # type: ignore[attr-defined]
        except (TimeoutError, OSError) as exc:
            raise TimeoutError(f"{provider_name} stream read exceeded {timeout}s") from exc
        if not line:
            break
        text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
        text = text.strip()
        if not text or text.startswith(":") or not text.startswith("data:"):
            continue
        data = text[5:].strip()
        if data == "[DONE]":
            break
        try:
            decoded = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            yield decoded


def _set_response_socket_timeout(response: object, timeout_seconds: float) -> None:
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is None:
        sock = getattr(fp, "sock", None)
    if sock is None or not hasattr(sock, "settimeout"):
        return
    try:
        sock.settimeout(timeout_seconds)
    except OSError:
        return


def _choices(chunk: JsonObject) -> list[JsonObject]:
    choices = chunk.get("choices")
    if not isinstance(choices, list):
        return []
    return [choice for choice in choices if isinstance(choice, dict)]


def _normalize_usage(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    usage = json.loads(json.dumps(value, ensure_ascii=False))
    cache = _cache_summary_from_usage(usage)
    if cache:
        usage["cache"] = cache
    return usage


def _merge_usage_chunks(chunks: list[JsonObject]) -> JsonObject:
    if not chunks:
        return {}
    # Streaming APIs generally send one final usage object. If a provider sends
    # more than one, keep the last raw object and include aggregate cache totals
    # for monitoring.
    merged = dict(chunks[-1])
    aggregate_cache = _aggregate_cache_summaries(chunk.get("cache") for chunk in chunks)
    if aggregate_cache:
        merged["cache"] = aggregate_cache
    return merged


def _cache_summary_from_usage(usage: JsonObject) -> JsonObject:
    prompt_tokens = _optional_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    hit_tokens = _optional_int(
        usage.get("prompt_cache_hit_tokens")
        or usage.get("cache_hit_tokens")
        or usage.get("cached_prompt_tokens")
    )
    miss_tokens = _optional_int(usage.get("prompt_cache_miss_tokens") or usage.get("cache_miss_tokens"))
    prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    input_details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    cached_tokens = _optional_int(
        usage.get("cached_tokens")
        or prompt_details.get("cached_tokens")
        or input_details.get("cached_tokens")
    )
    if hit_tokens is None and cached_tokens is not None:
        hit_tokens = cached_tokens
    cache: JsonObject = {}
    if prompt_tokens is not None:
        cache["prompt_tokens"] = prompt_tokens
    if hit_tokens is not None:
        cache["prompt_cache_hit_tokens"] = hit_tokens
    if miss_tokens is not None:
        cache["prompt_cache_miss_tokens"] = miss_tokens
    if cached_tokens is not None:
        cache["cached_tokens"] = cached_tokens
    denominator = None
    if hit_tokens is not None and miss_tokens is not None and hit_tokens + miss_tokens > 0:
        denominator = hit_tokens + miss_tokens
    elif hit_tokens is not None and prompt_tokens is not None and prompt_tokens > 0:
        denominator = prompt_tokens
    if denominator:
        cache["cache_hit_rate"] = hit_tokens / denominator if hit_tokens is not None else 0.0
    return cache


def _aggregate_cache_summaries(values: Iterable[object]) -> JsonObject:
    hit = miss = prompt = cached = 0
    saw_hit = saw_miss = saw_prompt = saw_cached = False
    for value in values:
        if not isinstance(value, dict):
            continue
        if (parsed := _optional_int(value.get("prompt_cache_hit_tokens"))) is not None:
            hit += parsed
            saw_hit = True
        if (parsed := _optional_int(value.get("prompt_cache_miss_tokens"))) is not None:
            miss += parsed
            saw_miss = True
        if (parsed := _optional_int(value.get("prompt_tokens"))) is not None:
            prompt += parsed
            saw_prompt = True
        if (parsed := _optional_int(value.get("cached_tokens"))) is not None:
            cached += parsed
            saw_cached = True
    result: JsonObject = {}
    if saw_prompt:
        result["prompt_tokens"] = prompt
    if saw_hit:
        result["prompt_cache_hit_tokens"] = hit
    if saw_miss:
        result["prompt_cache_miss_tokens"] = miss
    if saw_cached:
        result["cached_tokens"] = cached
    denominator = None
    if saw_hit and saw_miss and hit + miss > 0:
        denominator = hit + miss
    elif saw_hit and saw_prompt and prompt > 0:
        denominator = prompt
    if denominator:
        result["cache_hit_rate"] = hit / denominator
    return result


def _tool_call_deltas(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _tool_delta_index(delta: JsonObject) -> int:
    try:
        return int(delta.get("index", 0))
    except (TypeError, ValueError):
        return 0


def _retryable_provider_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "network error",
            "timeout",
            "timed out",
            "incompleteread",
            "remote disconnected",
            "remotedisconnected",
            "connection reset",
        )
    )


def _produce_sse_chunks(
    chunks: Iterable[JsonObject],
    chunk_queue: queue.Queue[object],
    sentinel: object,
) -> None:
    try:
        for chunk in chunks:
            chunk_queue.put(chunk)
    except BaseException as exc:  # noqa: BLE001 - provider errors cross the thread boundary as observations.
        chunk_queue.put(exc)
    finally:
        chunk_queue.put(sentinel)


async def _get_thread_queue_item(
    chunk_queue: queue.Queue[object],
    *,
    deadline: float,
    provider_name: str,
    timeout_seconds: int,
) -> object:
    while True:
        try:
            return chunk_queue.get_nowait()
        except queue.Empty:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"{provider_name} stream queue exceeded {timeout_seconds}s without completion")
            await asyncio.sleep(min(0.05, remaining))


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_number(value: object) -> int | float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _preview(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."
