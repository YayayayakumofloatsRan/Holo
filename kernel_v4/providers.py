from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import os
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
        tool_deltas: dict[int, _StreamingToolCallBuilder] = {}
        chunk_queue: asyncio.Queue[object] = asyncio.Queue()
        sentinel = object()
        loop = asyncio.get_running_loop()
        producer_thread = threading.Thread(
            target=_produce_sse_chunks,
            args=(
                self._post_sse_json_with_retries(
                    self._completion_url(),
                    self._api_key(),
                    payload,
                    self.timeout_seconds,
                ),
                loop,
                chunk_queue,
                sentinel,
            ),
            daemon=True,
        )
        producer_thread.start()
        while True:
            queued = await chunk_queue.get()
            if queued is sentinel:
                break
            if isinstance(queued, BaseException):
                raise queued
            chunk = queued if isinstance(queued, dict) else {}
            for choice in _choices(chunk):
                delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    text_parts.append(content)
                    yield ModelEvent(event_type="text_delta", text=content)
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
                "tool_call_count": len(tool_deltas),
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
        return payload, native_surface.name_map

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
    ) -> None:
        super().__init__(
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "") or "https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY",
            model=model
            or os.environ.get("HOLO_V4_MODEL", "")
            or os.environ.get("DEEPSEEK_MODEL", "")
            or "deepseek-chat",
            enabled=enabled,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            tool_choice=tool_choice,
            parallel_tool_calls=None,
            force_tool_name=force_tool_name,
            force_tool_turns=force_tool_turns,
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
        real_name = name_map.get(self.name, self.name)
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
        try:
            parsed = json.loads(self.arguments or "{}")
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
        real_name = name_map.get(self.name, self.name)
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
            "content": system_prompt.rstrip() + "\n\nRuntime context:\n" + context_text,
        }
    ]
    for message in messages:
        if message.role == "system":
            result.append({"role": "system", "content": message.content})
        elif message.role == "user":
            result.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            payload: JsonObject = {"role": "assistant", "content": message.content or None}
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
    return result


def _native_tool_name(tool_name: str, *, force_hash: bool = False) -> str:
    digest = hashlib.sha256(tool_name.encode("utf-8")).hexdigest()[:8]
    slug = _NATIVE_TOOL_NAME_RE.sub("_", tool_name).strip("_")
    slug = re.sub(r"_+", "_", slug) or "tool"
    needs_hash = force_hash or slug != tool_name or len(slug) > _MAX_NATIVE_TOOL_NAME_CHARS
    if not needs_hash:
        return slug
    suffix = "_" + digest
    max_base = max(1, _MAX_NATIVE_TOOL_NAME_CHARS - len(suffix))
    return (slug[:max_base].rstrip("_") or "tool") + suffix


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
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[object],
    sentinel: object,
) -> None:
    try:
        for chunk in chunks:
            loop.call_soon_threadsafe(queue.put_nowait, chunk)
    except BaseException as exc:  # noqa: BLE001 - provider errors cross the thread boundary as observations.
        loop.call_soon_threadsafe(queue.put_nowait, exc)
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, sentinel)


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
