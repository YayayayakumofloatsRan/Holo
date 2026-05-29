from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Sequence

from kernel_v3.contracts import JsonObject, ProcessorRequest, ProcessorResult
from kernel_v3.processors.usage import coerce_usage, usage_from_text


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
    ) -> None:
        self.enabled = enabled
        self.base_url = (base_url or os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "")).strip().rstrip("/")
        self.api_key_env = api_key_env
        self.model = model
        self.timeout_seconds = timeout_seconds

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
        payload = {
            "model": str(request.parameters.get("model") or self.model),
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        max_tokens = _optional_positive_int(request.parameters.get("max_tokens"))
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        thinking = _thinking_payload(request.parameters.get("thinking"))
        if thinking is not None:
            payload["thinking"] = thinking
        reasoning_effort = request.parameters.get("reasoning_effort")
        if reasoning_effort in {"high", "max"}:
            payload["reasoning_effort"] = reasoning_effort
        decoded = self._post_json(self._completion_url(), self._api_key(), payload, _timeout(request, self.timeout_seconds))
        text = _extract_chat_text(decoded)
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": text, "provider": self.name, "model": payload["model"]},
            usage=coerce_usage(decoded.get("usage"), prompt=request.prompt, completion=text),
            error=None,
        )

    def _api_key(self) -> str:
        return str(os.environ.get(self.api_key_env, "") or "").strip()

    def _completion_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

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
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.name} HTTP {exc.code}: {detail[:240]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{self.name} network error: {exc.reason}") from exc
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.name} returned non-JSON response") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError(f"{self.name} returned non-object response")
        return decoded


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
    ) -> None:
        super().__init__(
            enabled=enabled,
            base_url=base_url or os.environ.get("DEEPSEEK_BASE_URL", "") or "https://api.deepseek.com",
            api_key_env=api_key_env,
            model=model or os.environ.get("DEEPSEEK_MODEL", "") or "deepseek-v4-flash",
            timeout_seconds=timeout_seconds,
        )


def _task_type(request: ProcessorRequest) -> str:
    value = request.parameters.get("task_type")
    return str(value or request.processor)


def _timeout(request: ProcessorRequest, default: int) -> int:
    try:
        return max(1, int(request.parameters.get("timeout_seconds", default)))
    except (TypeError, ValueError):
        return default


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
