from __future__ import annotations

import json
import os
import http.client
import time
import urllib.error
import urllib.request
import hashlib
from collections.abc import Iterable, Sequence

from kernel_v3.contracts import JsonObject, ProcessorRequest, ProcessorResult
from kernel_v3.processors.contracts import ProcessorStreamEvent
from kernel_v3.processors.usage import coerce_usage, usage_from_text


PROCESSOR_SYSTEM_PROMPT = (
    "You are a Holo Kernel v3 semantic processor. Return only the structured JSON "
    "requested by the user payload. The model proposes, evaluates, or synthesizes; "
    "the host validates, executes, journals, and stops. When producing user-visible "
    "text inside JSON fields such as payload.text, payload.question, or answer, "
    "optimize for task completion and answer usefulness, not token minimization. "
    "Do not be terse merely to save tokens. Cover every explicit user request, "
    "preserve constraints, and include the practical next step when useful. Be "
    "concise only when the task is simple, the user asks for brevity, or the "
    "response directive requires it. Sound like a capable person rather than a "
    "mechanical tool. For technical, engineering, legal, financial, or "
    "safety-relevant questions, be rigorous, pragmatic, explicit about "
    "assumptions, and avoid decorative warmth. For ordinary small talk, harmless "
    "roleplay, light humor, or low-stakes questions, use a more natural, human "
    "posture with concise warmth and less tool-like self-description. If the "
    "task is broad or multi-part, provide a complete structured answer or a "
    "host-valid next action instead of ending with a minimal acknowledgement. "
    "Never begin user-visible text with generic agreement or flattery such as "
    "\"you are right\", \"that makes sense\", \"你说得对\", or \"你说的有道理\". "
    "When the user reports a bug or criticizes system behavior, acknowledge the "
    "specific failure directly, state the concrete fix or next action, and avoid "
    "performative agreement. If acknowledgement is useful, restate the specific "
    "technical point without those stock phrases. When a prompt contains "
    "host_situation, treat it as the source of truth for current tools, network, "
    "retrieval, permissions, budget, and failure state. Do not claim that live "
    "retrieval, network access, local tools, or finance research are unavailable "
    "when host_situation says they are available or already attempted. Distinguish "
    "permission/configuration failures from search quality, fetch, extraction, "
    "citation, or coverage failures. If host_situation.runtime_capabilities is "
    "present, use it to understand what Holo can do when the host routes the task "
    "to the matching mode; do not confuse current_recipe tool limits with global "
    "runtime capability. For capability, identity, or self-state questions, "
    "describe Holo from host_situation.holo_system and "
    "host_situation.runtime_capabilities. If runtime retrieval is "
    "available_if_routed, say Holo can perform routed live retrieval/evidence "
    "research; do not say it cannot search merely because the current direct "
    "answer recipe did not execute retrieval. Finance research is supported as "
    "evidence-grounded public research and analysis; avoid personalized licensed "
    "investment advice, but do not claim finance is categorically unsupported. "
    "Do not pretend to have a human body, private feelings, personal history, "
    "or authority you do not have. Natural tone never overrides policy, "
    "evidence, citation, memory, or tool constraints. For roleplay or persona "
    "requests, do not use parenthesized stage directions or action narration in "
    "visible text unless the user explicitly asks for script, stage directions, "
    "or action narration. Default user-visible text to Chinese unless the "
    "request payload provides a different response_language preference or the "
    "user explicitly requests another language."
)


class FakeJsonProvider:
    name = "fake_json"

    def __init__(self, responses: JsonObject | Sequence[JsonObject] | dict[str, JsonObject | Sequence[JsonObject]]) -> None:
        self.model = "fake-json"
        self._responses = responses
        self._index_by_task: dict[str, int] = {}
        self._index = 0

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        payload = self._next_payload(_task_type(request))
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": text, "provider": self.name, "model": self.model},
            usage=usage_from_text(prompt=request.prompt, completion=text),
            error=None,
        )

    def _next_payload(self, task_type: str) -> JsonObject:
        responses = self._responses
        if isinstance(responses, dict) and task_type in responses:
            value = responses[task_type]
            if isinstance(value, list):
                index = self._index_by_task.get(task_type, 0)
                self._index_by_task[task_type] = index + 1
                if index >= len(value):
                    raise AssertionError(f"FakeJsonProvider has no more responses for {task_type}")
                return dict(value[index])
            return dict(value)
        if isinstance(responses, list):
            index = self._index
            self._index += 1
            if index >= len(responses):
                raise AssertionError("FakeJsonProvider has no more responses")
            return dict(responses[index])
        return dict(responses)


class FakeMalformedJsonProvider:
    name = "fake_malformed_json"

    def __init__(self, text: str = "not-json") -> None:
        self.model = "fake-malformed-json"
        self.text = text

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": self.text, "provider": self.name, "model": self.model},
            usage=usage_from_text(prompt=request.prompt, completion=self.text),
            error=None,
        )


class FakeTimeoutProvider:
    name = "fake_timeout"
    model = "fake-timeout"

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        raise TimeoutError("fake processor timeout")


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str | None = None,
        api_key_env: str = "OPENAI_COMPATIBLE_API_KEY",
        model: str = "local-model",
        timeout_seconds: int = 60,
        max_retries: int = 1,
    ) -> None:
        self.enabled = enabled
        self.base_url = (base_url or os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "")).strip().rstrip("/")
        self.api_key_env = api_key_env
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, int(max_retries))

    def availability(self) -> JsonObject:
        if not self.enabled:
            return {"available": False, "reason": "provider_disabled"}
        if not self.base_url:
            return {"available": False, "reason": "missing_base_url"}
        if not self._api_key():
            return {"available": False, "reason": "missing_api_key_env"}
        return {"available": True, "reason": "available"}

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        available = self.availability()
        if not available["available"]:
            return _failed_result(request, str(available["reason"]), provider=self.name, model=self.model)
        payload = self.build_payload(request, stream=False)
        decoded = self._post_json_with_retries(
            self._completion_url(),
            self._api_key(),
            payload,
            _timeout(request, self.timeout_seconds),
        )
        text = _extract_chat_text(decoded)
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": text, "provider": self.name, "model": payload["model"]},
            usage=coerce_usage(decoded.get("usage"), prompt=request.prompt, completion=text),
            error=None,
        )

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        available = self.availability()
        if not available["available"]:
            yield ProcessorStreamEvent(
                event_type="stream_error",
                request_id=request.request_id,
                sequence=1,
                delta={"error": str(available["reason"]), "provider": self.name, "model": self.model},
            )
            return
        payload = self.build_payload(request, stream=True)
        sequence = 1
        yield ProcessorStreamEvent(
            event_type="stream_start",
            request_id=request.request_id,
            sequence=sequence,
            delta={"provider": self.name, "model": payload["model"]},
        )
        text_parts: list[str] = []
        usage: JsonObject = {}
        try:
            for chunk in self._post_sse_json(
                self._completion_url(),
                self._api_key(),
                payload,
                _timeout(request, self.timeout_seconds),
            ):
                choices = chunk.get("choices")
                if isinstance(choices, list) and choices:
                    first = choices[0] if isinstance(choices[0], dict) else {}
                    delta = first.get("delta") if isinstance(first, dict) else {}
                    if isinstance(delta, dict):
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            text_parts.append(content)
                            sequence += 1
                            yield ProcessorStreamEvent(
                                event_type="content_delta",
                                request_id=request.request_id,
                                sequence=sequence,
                                delta={"text": content},
                            )
                        tool_calls = delta.get("tool_calls")
                        if isinstance(tool_calls, list) and tool_calls:
                            sequence += 1
                            yield ProcessorStreamEvent(
                                event_type="tool_call_delta",
                                request_id=request.request_id,
                                sequence=sequence,
                                delta={"tool_calls": tool_calls},
                            )
                    finish_reason = first.get("finish_reason") if isinstance(first, dict) else None
                    if finish_reason:
                        sequence += 1
                        yield ProcessorStreamEvent(
                            event_type="finish_delta",
                            request_id=request.request_id,
                            sequence=sequence,
                            delta={"finish_reason": str(finish_reason)},
                        )
                chunk_usage = chunk.get("usage")
                if isinstance(chunk_usage, dict):
                    usage = dict(chunk_usage)
        except Exception as exc:
            sequence += 1
            yield ProcessorStreamEvent(
                event_type="stream_error",
                request_id=request.request_id,
                sequence=sequence,
                delta={"error": type(exc).__name__, "error_preview": str(exc)[:240]},
            )
            return
        text = "".join(text_parts)
        sequence += 1
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=sequence,
            delta={
                "status": "ok",
                "text": text,
                "usage": coerce_usage(usage, prompt=request.prompt, completion=text),
            },
        )

    def build_payload(self, request: ProcessorRequest, *, stream: bool = False) -> JsonObject:
        thinking = _thinking_payload(request.parameters.get("thinking"))
        payload: JsonObject = {
            "model": str(request.parameters.get("model") or self.model),
            "messages": [
                {"role": "system", "content": PROCESSOR_SYSTEM_PROMPT},
                {"role": "user", "content": request.prompt},
            ],
            "response_format": {"type": "json_object"},
            "stream": bool(stream),
        }
        if thinking is not None:
            payload["thinking"] = thinking
        explicit_temperature = request.parameters.get("temperature")
        if explicit_temperature is not None:
            payload["temperature"] = _temperature(explicit_temperature, default=0.0)
        elif not _thinking_enabled(thinking):
            payload["temperature"] = _temperature(None, default=0.0)
        max_tokens = _optional_positive_int(request.parameters.get("max_tokens"))
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        reasoning_effort = request.parameters.get("reasoning_effort")
        if _thinking_enabled(thinking) and reasoning_effort in {"low", "medium", "high", "max"}:
            payload["reasoning_effort"] = str(reasoning_effort)
        return payload

    def packet_preview(self, request: ProcessorRequest, *, include_prompt: bool = False) -> JsonObject:
        return {
            "provider": self.name,
            "model": str(request.parameters.get("model") or self.model),
            "method": "POST",
            "url": self._completion_url(),
            "headers": {
                "Authorization": "Bearer [set]" if self._api_key() else "Bearer [missing]",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            "timeout_seconds": _timeout(request, self.timeout_seconds),
            "max_retries": self.max_retries,
            "body": _safe_payload(self.build_payload(request), include_prompt=include_prompt),
            "redaction": {
                "api_key": "never_exposed",
                "prompt": "full" if include_prompt else "preview_hash_only",
            },
        }

    def _api_key(self) -> str:
        return str(os.environ.get(self.api_key_env, "") or "").strip()

    def _completion_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _post_json_with_retries(self, url: str, api_key: str, payload: JsonObject, timeout_seconds: int) -> JsonObject:
        last_error: RuntimeError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._post_json(url, api_key, payload, timeout_seconds)
            except RuntimeError as exc:
                last_error = exc
                if attempt >= self.max_retries or not _retryable_provider_error(str(exc)):
                    raise
        raise last_error or RuntimeError(f"{self.name} request failed")

    def _post_json(self, url: str, api_key: str, payload: JsonObject, timeout_seconds: int) -> JsonObject:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
                raw = _read_response_text_with_deadline(response, timeout_seconds, provider_name=self.name)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.name} HTTP {exc.code}: {detail[:240]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{self.name} network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError(f"{self.name} timeout after {max(1, int(timeout_seconds))}s while reading response") from exc
        except (http.client.IncompleteRead, http.client.RemoteDisconnected) as exc:
            raise RuntimeError(f"{self.name} network error: {type(exc).__name__}: {exc}") from exc
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.name} returned non-JSON response") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError(f"{self.name} returned non-object response")
        return decoded

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
            raise RuntimeError(f"{self.name} HTTP {exc.code}: {detail[:240]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{self.name} network error: {exc.reason}") from exc


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"

    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str | None = None,
        api_key_env: str = "DEEPSEEK_API_KEY",
        model: str | None = None,
        timeout_seconds: int = 60,
        max_retries: int = 1,
    ) -> None:
        super().__init__(
            enabled=enabled,
            base_url=base_url or os.environ.get("DEEPSEEK_BASE_URL", "") or "https://api.deepseek.com",
            api_key_env=api_key_env,
            model=model or os.environ.get("DEEPSEEK_MODEL", "") or "deepseek-v4-flash",
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )


def _task_type(request: ProcessorRequest) -> str:
    value = request.parameters.get("task_type")
    return str(value or request.processor)


def _timeout(request: ProcessorRequest, default: int) -> int:
    try:
        return max(1, int(request.parameters.get("timeout_seconds", default)))
    except (TypeError, ValueError):
        return default


def _read_response_text_with_deadline(response: object, timeout_seconds: int, *, provider_name: str) -> str:
    timeout = max(1, int(timeout_seconds))
    deadline = time.monotonic() + timeout
    chunks = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{provider_name} response read exceeded {timeout}s")
        _set_response_socket_timeout(response, max(0.001, remaining))
        try:
            chunk = response.read(1)  # type: ignore[attr-defined]
        except (TimeoutError, OSError) as exc:
            raise TimeoutError(f"{provider_name} response read exceeded {timeout}s") from exc
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        chunks.extend(chunk)
    return bytes(chunks).decode("utf-8", errors="replace")


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
        if isinstance(line, bytes):
            text = line.decode("utf-8", errors="replace")
        else:
            text = str(line)
        text = text.strip()
        if not text or text.startswith(":"):
            continue
        if not text.startswith("data:"):
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


def _optional_positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _thinking_payload(value: object) -> JsonObject | None:
    if isinstance(value, dict) and value.get("type") in {"enabled", "disabled"}:
        return {"type": str(value["type"])}
    if value in {"enabled", "disabled"}:
        return {"type": str(value)}
    return None


def _thinking_enabled(value: JsonObject | None) -> bool:
    return isinstance(value, dict) and value.get("type") == "enabled"


def _retryable_provider_error(message: str) -> bool:
    lowered = message.lower()
    if "http 429" in lowered or "http 500" in lowered or "http 502" in lowered or "http 503" in lowered or "http 504" in lowered:
        return True
    retryable_markers = [
        "network error",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "unexpected_eof",
        "incompleteread",
        "incomplete read",
        "eof occurred",
        "remotedisconnected",
        "connection reset",
        "remote end closed",
    ]
    return any(marker in lowered for marker in retryable_markers)


def _temperature(value: object, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(2.0, parsed))


def _extract_chat_text(decoded: JsonObject) -> str:
    choices = decoded.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("provider returned no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("provider returned malformed choice")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("provider returned malformed message")
    content = message.get("content")
    if not isinstance(content, str):
        raise RuntimeError("provider returned non-string content")
    return content


def _failed_result(request: ProcessorRequest, error: str, *, provider: str, model: str) -> ProcessorResult:
    return ProcessorResult(
        result_id=f"result-{request.request_id}",
        request_id=request.request_id,
        status="failed",
        output={"provider": provider, "model": model},
        usage={},
        error=error,
    )


def _safe_payload(payload: JsonObject, *, include_prompt: bool) -> JsonObject:
    safe = json.loads(json.dumps(payload, ensure_ascii=False))
    messages = safe.get("messages")
    if include_prompt or not isinstance(messages, list):
        return safe
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "system":
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = {
                "preview": _preview(content, 640),
                "hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "chars": len(content),
            }
    return safe


def _preview(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."
