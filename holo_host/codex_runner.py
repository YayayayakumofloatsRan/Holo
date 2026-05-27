from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import HostConfig, ProcessorLaneConfig, TaskRoutingConfig
from .models import CodexResult, ProcessorTaskRequest, ProcessorTaskResult, ProcessorUsageRecord
from .stage106_deepseek_tool_adapter import (
    build_tool_payload,
    parse_provider_tool_calls,
    provider_tool_calls_for_message,
    strip_provider_tool_markup,
)
from .stage113_agent_tool_executor import execute_stage113_agent_tools
from .stage152_deepseek_tool_loop import (
    build_deepseek_native_tool_payload,
    deepseek_native_tool_names,
    parse_deepseek_native_tool_calls,
    run_deepseek_native_tool_loop,
)
from .kernel_metadata_sanitizer import build_public_stage152_report
from .tool_grounding import normalize_tool_observation_ledger

PROCESSOR_TASK_SPECS: dict[str, dict[str, Any]] = {
    "reply": {
        "description": "Generate the live user-facing reply.",
        "allow_session_resume": True,
        "allowed_data_layers": (
            "identity_core",
            "relationship_state",
            "recent_dialogue_window",
            "episodic_recall",
            "consciousness_stream",
            "activation_state",
            "vector_hits",
            "reply_constraints",
        ),
        "allow_memory_writeback": False,
        "output_schema": "plain_text",
        "default_reasoning_effort": "",
    },
    "recall_reconstruct": {
        "description": "Reconstruct a human-style recall summary from graph and archive anchors.",
        "allow_session_resume": False,
        "allowed_data_layers": (
            "archive",
            "mind_graph",
            "relationship_state",
            "episodic_recall",
            "consciousness_stream",
            "vector_hits",
            "activation_state",
        ),
        "allow_memory_writeback": False,
        "output_schema": "json_or_text",
        "default_reasoning_effort": "medium",
    },
    "memory_consolidate": {
        "description": "Distill observations into memory or graph updates.",
        "allow_session_resume": False,
        "allowed_data_layers": ("working_memory", "candidate_memory", "mind_graph", "archive"),
        "allow_memory_writeback": True,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "reflect": {
        "description": "Summarize recent internal signals and relationship drift.",
        "allow_session_resume": False,
        "allowed_data_layers": ("thought_stream", "archive", "mind_graph", "emotion_trace"),
        "allow_memory_writeback": True,
        "output_schema": "json_or_text",
        "default_reasoning_effort": "medium",
    },
    "dream": {
        "description": "Run slow associative replay over archive and relationship motifs.",
        "allow_session_resume": False,
        "allowed_data_layers": ("archive", "mind_graph", "callback_candidates", "thought_stream"),
        "allow_memory_writeback": True,
        "output_schema": "json_or_text",
        "default_reasoning_effort": "medium",
    },
    "initiative_plan": {
        "description": "Plan bounded initiative seeds for whitelisted contacts.",
        "allow_session_resume": False,
        "allowed_data_layers": ("relationship_state", "mind_graph", "initiative_candidates", "thought_stream"),
        "allow_memory_writeback": False,
        "output_schema": "json_or_text",
        "default_reasoning_effort": "medium",
    },
    "self_check": {
        "description": "Inspect drafts for identity drift and recall mismatch.",
        "allow_session_resume": False,
        "allowed_data_layers": ("identity_core", "reply_constraints", "mind_graph"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "self_observe": {
        "description": "Observe drift, user corrections, and runtime pain points as bounded self-evidence.",
        "allow_session_resume": False,
        "allowed_data_layers": ("mind_graph", "relationship_state", "activation_state", "recent_dialogue_window"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "self_revision_plan": {
        "description": "Produce a bounded JSON patch over allowed mutable mind parameters.",
        "allow_session_resume": False,
        "allowed_data_layers": ("identity_core", "relationship_state", "mind_graph", "activation_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "self_revision_review": {
        "description": "Review a proposed bounded self-revision patch against fixed probes before applying it.",
        "allow_session_resume": False,
        "allowed_data_layers": ("identity_core", "reply_constraints", "mind_graph", "activation_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "initiative_probe": {
        "description": "Evaluate whether a light proactive move is currently allowed and explain the gating rationale.",
        "allow_session_resume": False,
        "allowed_data_layers": ("relationship_state", "mind_graph", "activation_state", "initiative_candidates"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "self_model_observe": {
        "description": "Observe current self drift, operator needs, and homeostasis pressure as bounded self-model evidence.",
        "allow_session_resume": False,
        "allowed_data_layers": ("mind_graph", "activation_state", "relationship_state", "self_model_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "self_model_plan": {
        "description": "Plan bounded self-model updates and homeostasis goals without editing canonical identity.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "mind_graph", "activation_state", "relationship_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "operator_plan": {
        "description": "Produce a bounded operator task plan, scope, and validation path.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "mind_graph", "activation_state", "relationship_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "operator_execute_shadow": {
        "description": "Execute a bounded operator task in a shadow workspace without touching the live repo.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "mind_graph", "activation_state", "relationship_state"),
        "allow_memory_writeback": False,
        "output_schema": "json_or_text",
        "default_reasoning_effort": "medium",
    },
    "deep_simulation": {
        "description": "Run high-stakes counterfactual simulation over the top candidate actions.",
        "allow_session_resume": False,
        "allowed_data_layers": ("world_state", "relationship_state", "self_model_state", "activation_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "xhigh",
    },
    "autobiographical_consolidation": {
        "description": "Consolidate recent events into autobiographical continuity and chapter updates.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "autobiographical_state", "mind_graph", "archive"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "goal_arbitration": {
        "description": "Arbitrate long-horizon goals and commitments based on current subject state.",
        "allow_session_resume": False,
        "allowed_data_layers": ("goal_state", "self_model_state", "relationship_state", "world_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "world_calibration": {
        "description": "Calibrate the social world model after outcomes and remembered evidence.",
        "allow_session_resume": False,
        "allowed_data_layers": ("world_state", "relationship_state", "mind_graph", "activation_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "operator_review": {
        "description": "Review a bounded operator result and decide whether a state-layer delta may be applied.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "mind_graph", "activation_state", "relationship_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "image_understand": {
        "description": "Understand an image and return a structured memory-oriented description for Holo.",
        "allow_session_resume": False,
        "allowed_data_layers": ("visual_memory", "relationship_state", "activation_state"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "affect_reflect": {
        "description": "Reflect over bounded affect evidence and summarize the current emotional pressure field.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "relationship_state", "activation_state", "mind_graph"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "drive_plan": {
        "description": "Translate affect, goals, commitments, and unfinished threads into bounded drive intensities.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "relationship_state", "activation_state", "mind_graph"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "value_integrate": {
        "description": "Integrate affect, goals, and commitments into a bounded value-state for action selection.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "relationship_state", "activation_state", "mind_graph"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "conflict_arbitrate": {
        "description": "Explain internal conflict between contact, continuity, risk, and identity priorities.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "relationship_state", "activation_state", "mind_graph"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "initiative_compose": {
        "description": "Compose bounded initiative candidates with rationale, drives, and send gating hints.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "relationship_state", "activation_state", "initiative_candidates", "mind_graph"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
    "outcome_appraise": {
        "description": "Appraise the result of initiative, resistance, or self-fix and update bounded future bias hints.",
        "allow_session_resume": False,
        "allowed_data_layers": ("self_model_state", "relationship_state", "activation_state", "mind_graph", "visual_memory"),
        "allow_memory_writeback": False,
        "output_schema": "json",
        "default_reasoning_effort": "medium",
    },
}


def _estimate_text_tokens(text: str) -> int:
    current = str(text or "").strip()
    if not current:
        return 0
    wordish = len(current.split())
    charish = max(1, len(current) // 4)
    return max(wordish, charish)


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
        cache_hit_tokens = int(payload.get("prompt_cache_hit_tokens", payload.get("cache_hit_tokens", 0)) or 0)
        cache_miss_tokens = int(payload.get("prompt_cache_miss_tokens", payload.get("cache_miss_tokens", 0)) or 0)
        estimated = bool(payload.get("estimated", False))
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "prompt_cache_hit_tokens": cache_hit_tokens,
            "prompt_cache_miss_tokens": cache_miss_tokens,
            "estimated": estimated,
        }
    prompt_tokens = int(getattr(payload, "prompt_tokens", getattr(payload, "input_tokens", 0)) or 0)
    completion_tokens = int(getattr(payload, "completion_tokens", getattr(payload, "output_tokens", 0)) or 0)
    total_tokens = int(getattr(payload, "total_tokens", prompt_tokens + completion_tokens) or 0)
    cache_hit_tokens = int(getattr(payload, "prompt_cache_hit_tokens", getattr(payload, "cache_hit_tokens", 0)) or 0)
    cache_miss_tokens = int(getattr(payload, "prompt_cache_miss_tokens", getattr(payload, "cache_miss_tokens", 0)) or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "prompt_cache_hit_tokens": cache_hit_tokens,
        "prompt_cache_miss_tokens": cache_miss_tokens,
        "estimated": False,
    }


def _sum_usage_payloads(*usages: dict[str, int | bool]) -> dict[str, int | bool]:
    return {
        "prompt_tokens": sum(int(usage.get("prompt_tokens", 0) or 0) for usage in usages),
        "completion_tokens": sum(int(usage.get("completion_tokens", 0) or 0) for usage in usages),
        "total_tokens": sum(int(usage.get("total_tokens", 0) or 0) for usage in usages),
        "prompt_cache_hit_tokens": sum(int(usage.get("prompt_cache_hit_tokens", 0) or 0) for usage in usages),
        "prompt_cache_miss_tokens": sum(int(usage.get("prompt_cache_miss_tokens", 0) or 0) for usage in usages),
        "estimated": any(bool(usage.get("estimated", False)) for usage in usages),
    }


def _bounded_int(value: Any, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(parsed, upper))


class ProcessorProvider:
    name = "provider"

    def availability(self) -> dict[str, Any]:
        return {"available": True, "reason": ""}

    def supports_request(self, request: ProcessorTaskRequest) -> bool:
        return True

    def run_task(
        self,
        runner: "CodexRunner",
        request: ProcessorTaskRequest,
        *,
        spec: dict[str, Any],
        lane_name: str,
        lane_config: ProcessorLaneConfig,
    ) -> ProcessorTaskResult:
        raise NotImplementedError


class CodexCliProvider(ProcessorProvider):
    name = "codex_cli"

    def availability(self) -> dict[str, Any]:
        return {"available": True, "reason": ""}

    def run_task(
        self,
        runner: "CodexRunner",
        request: ProcessorTaskRequest,
        *,
        spec: dict[str, Any],
        lane_name: str,
        lane_config: ProcessorLaneConfig,
    ) -> ProcessorTaskResult:
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=False) as handle:
            output_path = Path(handle.name)

        def run_once(*, resumed: bool) -> tuple[subprocess.CompletedProcess[str], list[str]]:
            prefix = runner._codex_invocation_prefix()
            task_prompt = request.prompt
            if request.task_type != "reply" and not bool(request.metadata.get("raw_prompt", False)):
                task_prompt = (
                    "[mind_os_processor_task]\n"
                    f"task_type={request.task_type}\n"
                    f"output_schema={request.output_schema}\n"
                    f"allow_memory_writeback={str(request.allow_memory_writeback).lower()}\n"
                    f"allowed_data_layers={','.join(request.allowed_data_layers)}\n\n"
                    f"{request.prompt}"
                )
                task_prompt = (
                    task_prompt.rstrip()
                    + "\n"
                    + f"workspace_mode={request.workspace_mode or 'live_readonly'}\n"
                    + f"operator_scope={request.operator_scope or ''}\n"
                )
            if resumed:
                command = prefix + [
                    "exec",
                    "resume",
                    "--json",
                    "-o",
                    str(output_path),
                    request.session_id,
                    task_prompt,
                ]
            else:
                command = prefix + [
                    "exec",
                    "--json",
                    "-o",
                    str(output_path),
                    task_prompt,
                ]
            for image_path in request.image_paths:
                current = str(image_path or "").strip()
                if current:
                    command.extend(["-i", current])
            command = runner._apply_runtime_options(
                command,
                resumed=resumed,
                model_override=request.model_override or lane_config.model,
                reasoning_effort_override=request.reasoning_effort_override
                or lane_config.reasoning_effort
                or str(spec.get("default_reasoning_effort", "")),
            )
            if output_path.exists():
                output_path.write_text("", encoding="utf-8")
            workspace_path = str(request.metadata.get("workspace_path", "") or "").strip()
            cwd = runner.config.runtime.repo_root
            if request.workspace_mode == "shadow_write" and workspace_path:
                shadow_path = Path(workspace_path)
                if shadow_path.exists():
                    cwd = shadow_path
            proc = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds or runner.config.runtime.codex_timeout_seconds,
            )
            return proc, command

        started_at = time.perf_counter()
        resumed = bool(
            request.session_id
            and runner.config.runtime.resume_sessions
            and bool(spec.get("allow_session_resume", True))
        )
        proc, command = run_once(resumed=resumed)
        effective_session_id = request.session_id
        if resumed and proc.returncode != 0 and runner._is_missing_resume_rollout(proc.stdout, proc.stderr):
            proc, command = run_once(resumed=False)
            effective_session_id = ""

        reply_text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        new_session_id = runner._parse_thread_id(proc.stdout) or effective_session_id
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        usage = {
            "prompt_tokens": _estimate_text_tokens(request.prompt),
            "completion_tokens": _estimate_text_tokens(reply_text),
            "total_tokens": _estimate_text_tokens(request.prompt) + _estimate_text_tokens(reply_text),
            "estimated": True,
        }
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=reply_text,
            session_id=new_session_id,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            command=command,
            output_schema=request.output_schema or str(spec.get("output_schema", "plain_text")),
            metadata={
                "allowed_data_layers": list(request.allowed_data_layers or tuple(spec.get("allowed_data_layers", ()))),
                "allow_memory_writeback": bool(request.allow_memory_writeback or spec.get("allow_memory_writeback", False)),
                "provider": self.name,
                "lane": lane_name,
                "model": request.model_override or lane_config.model,
                "reasoning_effort": request.reasoning_effort_override
                or lane_config.reasoning_effort
                or str(spec.get("default_reasoning_effort", "")),
                "usage": usage,
                "duration_ms": duration_ms,
                "budget_tag": request.budget_tag,
            },
        )


class _OpenAIResponsesBase(ProcessorProvider):
    base_name = "responses"

    def __init__(self, *, compatible: bool = False):
        self.compatible = compatible
        self.name = "openai_compatible" if compatible else "responses"

    def _base_url(self, runner: "CodexRunner") -> str:
        if self.compatible:
            return (
                runner.config.processor_fabric.openai_compatible_base_url
                or os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "")
                or os.environ.get("OPENAI_BASE_URL", "")
            ).strip()
        return str(os.environ.get("OPENAI_BASE_URL", "") or "").strip()

    def _api_key(self, runner: "CodexRunner") -> str:
        env_name = (
            runner.config.processor_fabric.openai_compatible_api_key_env
            if self.compatible
            else runner.config.processor_fabric.responses_api_key_env
        )
        return str(os.environ.get(env_name, "") or "").strip()

    def availability(self) -> dict[str, Any]:
        if importlib.util.find_spec("openai") is None:
            return {"available": False, "reason": "openai package not installed"}
        if self.compatible:
            return {"available": True, "reason": ""}
        return {"available": True, "reason": ""}

    def supports_request(self, request: ProcessorTaskRequest) -> bool:
        return not bool(request.image_paths)

    def _client(self, runner: "CodexRunner") -> Any:
        if importlib.util.find_spec("openai") is None:
            raise RuntimeError("openai package is not installed")
        api_key = self._api_key(runner)
        if not api_key:
            env_name = (
                runner.config.processor_fabric.openai_compatible_api_key_env
                if self.compatible
                else runner.config.processor_fabric.responses_api_key_env
            )
            raise RuntimeError(f"{env_name} is not set")
        from openai import OpenAI  # type: ignore

        kwargs: dict[str, Any] = {}
        base_url = self._base_url(runner)
        if base_url:
            kwargs["base_url"] = base_url
        kwargs["api_key"] = api_key
        return OpenAI(**kwargs)

    def run_task(
        self,
        runner: "CodexRunner",
        request: ProcessorTaskRequest,
        *,
        spec: dict[str, Any],
        lane_name: str,
        lane_config: ProcessorLaneConfig,
    ) -> ProcessorTaskResult:
        started_at = time.perf_counter()
        client = self._client(runner)
        model = request.model_override or lane_config.model
        if self.compatible:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": request.prompt}],
                max_tokens=request.max_output_tokens or lane_config.max_output_tokens or None,
            )
            choices = list(getattr(response, "choices", []) or [])
            message = getattr(choices[0], "message", None) if choices else None
            text = str(getattr(message, "content", "") or "").strip()
            command = [self.name, "chat.completions.create"]
        else:
            response = client.responses.create(
                model=model,
                input=request.prompt,
                max_output_tokens=request.max_output_tokens or lane_config.max_output_tokens or None,
            )
            text = str(getattr(response, "output_text", "") or "").strip()
            command = [self.name, "responses.create"]
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        usage = _coerce_usage_payload(getattr(response, "usage", None))
        if not usage["total_tokens"]:
            usage = {
                "prompt_tokens": _estimate_text_tokens(request.prompt),
                "completion_tokens": _estimate_text_tokens(text),
                "total_tokens": _estimate_text_tokens(request.prompt) + _estimate_text_tokens(text),
                "estimated": True,
            }
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=text,
            session_id=request.session_id,
            returncode=0,
            stdout="",
            stderr="",
            command=command,
            output_schema=request.output_schema or str(spec.get("output_schema", "plain_text")),
            metadata={
                "allowed_data_layers": list(request.allowed_data_layers or tuple(spec.get("allowed_data_layers", ()))),
                "allow_memory_writeback": bool(request.allow_memory_writeback or spec.get("allow_memory_writeback", False)),
                "provider": self.name,
                "lane": lane_name,
                "model": request.model_override or lane_config.model,
                "reasoning_effort": request.reasoning_effort_override
                or lane_config.reasoning_effort
                or str(spec.get("default_reasoning_effort", "")),
                "usage": usage,
                "duration_ms": duration_ms,
                "budget_tag": request.budget_tag,
            },
        )


class DeepSeekProvider(ProcessorProvider):
    name = "deepseek"

    def _base_url(self, runner: "CodexRunner") -> str:
        return (
            runner.config.processor_fabric.deepseek_base_url
            or os.environ.get("DEEPSEEK_BASE_URL", "")
            or "https://api.deepseek.com"
        ).strip().rstrip("/")

    def _api_key(self, runner: "CodexRunner") -> str:
        env_name = runner.config.processor_fabric.deepseek_api_key_env or "DEEPSEEK_API_KEY"
        return str(os.environ.get(env_name, "") or "").strip()

    def _completion_url(self, runner: "CodexRunner") -> str:
        base_url = self._base_url(runner)
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _thinking_payload(self, effort: str) -> dict[str, str]:
        normalized = str(effort or "").strip().lower()
        if normalized in {"", "none", "minimal", "low", "off", "false", "disabled"}:
            return {"type": "disabled"}
        if normalized in {"xhigh", "max"}:
            return {"type": "enabled", "reasoning_effort": "max"}
        return {"type": "enabled", "reasoning_effort": "high"}

    def supports_request(self, request: ProcessorTaskRequest) -> bool:
        return not bool(request.image_paths)

    def _post_json(self, url: str, api_key: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
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
            with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds or 1))) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek network error: {exc.reason}") from exc
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DeepSeek returned non-JSON response: {raw[:240]}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("DeepSeek returned a non-object response")
        return decoded

    def _tool_observation_messages(self, tool_report: dict[str, Any], tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        observations = {
            str(observation.get("provider_call_id", "") or ""): dict(observation)
            for observation in list(tool_report.get("observations", []) or [])
            if isinstance(observation, dict)
        }
        skipped = {
            str(item.get("provider_call_id", "") or ""): dict(item)
            for item in list(tool_report.get("skipped", []) or [])
            if isinstance(item, dict)
        }
        for call in tool_calls:
            call_id = str(call.get("id", "") or "")
            if not call_id:
                continue
            if call_id in observations:
                observation = observations[call_id]
                content = {
                    "tool": str(observation.get("tool", "") or ""),
                    "status": str(observation.get("status", "") or ""),
                    "summary": str(observation.get("summary", "") or ""),
                    "data": dict(observation.get("data", {}) or {}),
                }
            else:
                rejection = skipped.get(call_id, {})
                reason = str(rejection.get("reason", "") or call.get("error", "") or "not_executed")
                content = {
                    "tool": str(rejection.get("tool", "") or call.get("name", "") or ""),
                    "status": "rejected",
                    "summary": f"tool rejected: {reason}",
                    "data": {"reason": reason},
                }
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(content, ensure_ascii=False, sort_keys=True),
                }
            )
        return messages

    def _usage_for_decoded(
        self,
        decoded: dict[str, Any],
        *,
        prompt_basis: Any,
        completion_text: str,
    ) -> dict[str, int | bool]:
        usage = _coerce_usage_payload(decoded.get("usage"))
        if usage["total_tokens"]:
            return usage
        prompt_text = (
            json.dumps(prompt_basis, ensure_ascii=False, sort_keys=True)
            if not isinstance(prompt_basis, str)
            else prompt_basis
        )
        prompt_tokens = _estimate_text_tokens(prompt_text)
        completion_tokens = _estimate_text_tokens(completion_text)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated": True,
        }

    def _maybe_run_agent_tool_loop(
        self,
        runner: "CodexRunner",
        request: ProcessorTaskRequest,
        *,
        api_key: str,
        payload: dict[str, Any],
        timeout_seconds: int,
        first_decoded: dict[str, Any],
        first_message: dict[str, Any],
        first_usage: dict[str, int | bool],
    ) -> tuple[dict[str, Any], dict[str, int | bool], dict[str, Any]]:
        if not bool(request.metadata.get("auto_execute_provider_tools", False)):
            return first_decoded, first_usage, {}
        initial_tool_calls = parse_provider_tool_calls(first_decoded)
        if not initial_tool_calls:
            return first_decoded, first_usage, {}
        external_lookup_fn = request.metadata.get("external_lookup_fn")
        if not callable(external_lookup_fn):
            external_lookup_fn = None
        max_rounds = _bounded_int(request.metadata.get("max_provider_tool_rounds"), default=4, lower=1, upper=8)
        max_tool_calls = _bounded_int(request.metadata.get("max_provider_tool_calls"), default=16, lower=1, upper=64)
        messages = list(payload.get("messages", []) or [])
        current_decoded = first_decoded
        current_message = dict(first_message)
        usage = dict(first_usage)
        rounds: list[dict[str, Any]] = []
        executed_count = 0
        skipped_count = 0
        total_tool_calls = 0
        final_request_sent = False
        exhausted = False
        tool_observation_ledger: list[dict[str, Any]] = []
        tool_failure_reentry = False

        for round_index in range(max_rounds):
            tool_calls = parse_provider_tool_calls(current_decoded)
            if not tool_calls:
                break
            if total_tool_calls >= max_tool_calls:
                exhausted = True
                break
            remaining_calls = max_tool_calls - total_tool_calls
            active_tool_calls = tool_calls[:remaining_calls]
            budget_skipped = [
                {
                    "provider_call_id": str(call.get("id", "") or ""),
                    "tool": str(call.get("name", "") or ""),
                    "reason": "tool_call_budget_exceeded",
                }
                for call in tool_calls[remaining_calls:]
            ]
            if budget_skipped:
                exhausted = True
            tool_report = execute_stage113_agent_tools(
                active_tool_calls,
                external_lookup_fn=external_lookup_fn,
                memory_corpus=request.metadata.get("tool_memory_corpus"),
                memory_corpus_path=request.metadata.get("tool_memory_corpus_path"),
                repo_root=runner.config.runtime.repo_root,
                network_enabled=bool(runner.config.runtime.network_enabled),
                permission_grants=(
                    request.metadata.get("tool_permission_grants")
                    or request.metadata.get("approved_tool_permissions")
                    or []
                ),
            )
            if budget_skipped:
                tool_report["skipped"] = list(tool_report.get("skipped", []) or []) + budget_skipped
                summary = dict(tool_report.get("summary", {}) or {})
                summary["skipped_count"] = int(summary.get("skipped_count", 0) or 0) + len(budget_skipped)
                tool_report["summary"] = summary
            tool_messages = self._tool_observation_messages(tool_report, active_tool_calls + tool_calls[remaining_calls:])
            round_ledger = normalize_tool_observation_ledger(tool_report)
            round_executed = int(tool_report.get("summary", {}).get("executed_count", 0) or 0)
            round_skipped = int(tool_report.get("summary", {}).get("skipped_count", 0) or 0)
            executed_count += round_executed
            skipped_count += round_skipped
            total_tool_calls += len(tool_calls)
            tool_observation_ledger.extend(round_ledger)
            if round_skipped or any(str(item.get("status", "") or "").lower() in {"rejected", "skipped", "denied", "error"} for item in round_ledger):
                tool_failure_reentry = True
            rounds.append(
                {
                    "round": round_index + 1,
                    "tool_names": [str(call.get("name", "") or "") for call in tool_calls],
                    "executed_count": round_executed,
                    "skipped_count": round_skipped,
                    "observation_summary": str(tool_report.get("summary", {}).get("observation_summary", "") or ""),
                    "tool_observation_ledger": round_ledger,
                }
            )
            if not tool_messages:
                break

            assistant_tool_calls = list(current_message.get("tool_calls", []) or [])
            if not assistant_tool_calls:
                assistant_tool_calls = provider_tool_calls_for_message(tool_calls)
            assistant_message = {
                "role": "assistant",
                "content": strip_provider_tool_markup(current_message.get("content", "")),
                "tool_calls": assistant_tool_calls,
            }
            reasoning_content = str(current_message.get("reasoning_content", "") or "").strip()
            if reasoning_content:
                assistant_message["reasoning_content"] = reasoning_content
            messages = messages + [assistant_message] + tool_messages
            followup_payload = dict(payload)
            followup_payload["messages"] = messages
            exhausted = exhausted or round_index + 1 >= max_rounds or total_tool_calls >= max_tool_calls
            followup_payload["tool_choice"] = "none" if exhausted else "auto"
            current_decoded = self._post_json(self._completion_url(runner), api_key, followup_payload, timeout_seconds)
            final_request_sent = True
            current_message = self._first_choice_message(current_decoded)
            completion_text = str(current_message.get("content", "") or "").strip()
            next_usage = self._usage_for_decoded(
                current_decoded,
                prompt_basis=followup_payload.get("messages", []),
                completion_text=completion_text,
            )
            usage = _sum_usage_payloads(usage, next_usage)

        loop_metadata = {
            "round_count": len(rounds),
            "rounds": rounds,
            "executed_count": executed_count,
            "skipped_count": skipped_count,
            "tool_call_count": total_tool_calls,
            "max_rounds": max_rounds,
            "max_tool_calls": max_tool_calls,
            "final_request_sent": False,
            "exhausted": exhausted,
            "tool_observation_ledger": tool_observation_ledger,
            "tool_failure_reentry": tool_failure_reentry,
        }
        loop_metadata["final_request_sent"] = final_request_sent
        return current_decoded, usage, loop_metadata

    def _first_choice_message(self, decoded: dict[str, Any]) -> dict[str, Any]:
        choices = list(decoded.get("choices", []) or [])
        first_choice = dict(choices[0]) if choices and isinstance(choices[0], dict) else {}
        message = first_choice.get("message", {})
        return dict(message) if isinstance(message, dict) else {}

    def run_task(
        self,
        runner: "CodexRunner",
        request: ProcessorTaskRequest,
        *,
        spec: dict[str, Any],
        lane_name: str,
        lane_config: ProcessorLaneConfig,
    ) -> ProcessorTaskResult:
        api_key = self._api_key(runner)
        if not api_key:
            env_name = runner.config.processor_fabric.deepseek_api_key_env or "DEEPSEEK_API_KEY"
            raise RuntimeError(f"{env_name} is not set")
        started_at = time.perf_counter()
        model = request.model_override or lane_config.model or "deepseek-v4-flash"
        effort = request.reasoning_effort_override or lane_config.reasoning_effort or str(spec.get("default_reasoning_effort", ""))
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": request.max_output_tokens or lane_config.max_output_tokens or None,
            "thinking": self._thinking_payload(effort),
        }
        provider_tool_payload: dict[str, Any] = {}
        stage152_native_enabled = bool(request.metadata.get("stage152_native_tool_loop", False))
        if bool(request.metadata.get("enable_provider_tools", False)):
            if stage152_native_enabled:
                native_names = request.metadata.get("stage152_native_tool_names") or deepseek_native_tool_names()
                provider_tool_payload = build_deepseek_native_tool_payload(
                    list(native_names),
                    tool_choice=request.metadata.get("provider_tool_choice", "auto"),
                )
            else:
                provider_tool_payload = build_tool_payload(
                    request.metadata.get("tool_requests", []),
                    tool_choice=request.metadata.get("provider_tool_choice", "auto"),
                )
            if provider_tool_payload.get("tools"):
                payload.update(provider_tool_payload)
        payload = {key: value for key, value in payload.items() if value is not None}
        timeout_seconds = int(request.timeout_seconds or runner.config.runtime.codex_timeout_seconds or 60)
        decoded = self._post_json(self._completion_url(runner), api_key, payload, timeout_seconds)
        first_decoded = decoded
        choices = list(decoded.get("choices", []) or [])
        first_choice = dict(choices[0]) if choices and isinstance(choices[0], dict) else {}
        message = dict(first_choice.get("message", {})) if isinstance(first_choice.get("message", {}), dict) else {}
        text = strip_provider_tool_markup(message.get("content", ""))
        initial_tool_calls = parse_deepseek_native_tool_calls(first_decoded) if stage152_native_enabled else parse_provider_tool_calls(first_decoded)
        initial_finish_reason = str(first_choice.get("finish_reason", "") or "")
        usage = self._usage_for_decoded(decoded, prompt_basis=request.prompt, completion_text=text)
        stage152_loop: dict[str, Any] = {}
        agent_tool_loop: dict[str, Any] = {}
        if stage152_native_enabled and bool(request.metadata.get("auto_execute_provider_tools", False)):
            external_lookup_fn = request.metadata.get("external_lookup_fn")

            def stage152_web_search(query: str) -> dict[str, Any]:
                if callable(request.metadata.get("web_search_fn")):
                    return dict(request.metadata["web_search_fn"](query))
                if callable(external_lookup_fn):
                    return dict(external_lookup_fn(query, 5))
                return {}

            web_search_fn = stage152_web_search if callable(request.metadata.get("web_search_fn")) or callable(external_lookup_fn) else None
            open_page_fn = request.metadata.get("open_page_fn") if callable(request.metadata.get("open_page_fn")) else None
            memory_recall_fn = request.metadata.get("memory_recall_fn") if callable(request.metadata.get("memory_recall_fn")) else None
            stage152_loop = run_deepseek_native_tool_loop(
                initial_decoded=decoded,
                base_payload=payload,
                call_model=lambda followup_payload: self._post_json(self._completion_url(runner), api_key, followup_payload, timeout_seconds),
                network_enabled=bool(runner.config.runtime.network_enabled),
                max_rounds=_bounded_int(request.metadata.get("max_provider_tool_rounds"), default=4, lower=1, upper=8),
                max_tool_calls=_bounded_int(request.metadata.get("max_provider_tool_calls"), default=16, lower=1, upper=64),
                web_search_fn=web_search_fn,
                open_page_fn=open_page_fn,
                memory_recall_fn=memory_recall_fn,
                memory_corpus=request.metadata.get("tool_memory_corpus"),
                memory_corpus_path=request.metadata.get("tool_memory_corpus_path"),
                repo_root=runner.config.runtime.repo_root,
            )
            decoded = dict(stage152_loop.get("final_decoded", decoded))
            usage = dict(stage152_loop.get("usage", usage))
            agent_tool_loop = {
                "schema": str(stage152_loop.get("schema", "")),
                "round_count": int(stage152_loop.get("round_count", 0) or 0),
                "rounds": list(stage152_loop.get("rounds", []) or []),
                "executed_count": int(stage152_loop.get("executed_count", 0) or 0),
                "skipped_count": len([row for row in list(stage152_loop.get("tool_observation_ledger", []) or []) if str(row.get("status", "") or "") == "rejected"]),
                "tool_call_count": int(stage152_loop.get("tool_call_count", 0) or 0),
                "max_rounds": _bounded_int(request.metadata.get("max_provider_tool_rounds"), default=4, lower=1, upper=8),
                "max_tool_calls": _bounded_int(request.metadata.get("max_provider_tool_calls"), default=16, lower=1, upper=64),
                "final_request_sent": bool(stage152_loop.get("final_request_sent", False)),
                "exhausted": bool(stage152_loop.get("exhausted", False)),
                "stop_reason": str(stage152_loop.get("stop_reason", "") or ""),
                "tool_observation_ledger": list(stage152_loop.get("tool_observation_ledger", []) or []),
                "web_observation_ledger": list(stage152_loop.get("web_observation_ledger", []) or []),
                "memory_observation_ledger": list(stage152_loop.get("memory_observation_ledger", []) or []),
                "time_observation": dict(stage152_loop.get("time_observation", {}) or {}),
                "tool_failure_reentry": any(
                    str(row.get("status", "") or "").lower() in {"rejected", "skipped", "denied", "error"}
                    for row in list(stage152_loop.get("tool_observation_ledger", []) or [])
                    if isinstance(row, dict)
                ),
            }
        else:
            decoded, usage, agent_tool_loop = self._maybe_run_agent_tool_loop(
                runner,
                request,
                api_key=api_key,
                payload=payload,
                timeout_seconds=timeout_seconds,
                first_decoded=decoded,
                first_message=message,
                first_usage=usage,
            )
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        choices = list(decoded.get("choices", []) or [])
        first_choice = dict(choices[0]) if choices and isinstance(choices[0], dict) else {}
        message = dict(first_choice.get("message", {})) if isinstance(first_choice.get("message", {}), dict) else {}
        text = strip_provider_tool_markup(message.get("content", ""))
        if stage152_loop and str(stage152_loop.get("final_text", "") or "").strip():
            text = str(stage152_loop.get("final_text", "") or "").strip()
        reasoning_content = str(message.get("reasoning_content", "") or "").strip()
        tool_calls = parse_deepseek_native_tool_calls(decoded) if stage152_native_enabled else parse_provider_tool_calls(decoded)
        stage152_public = {}
        if stage152_loop:
            stage152_public = build_public_stage152_report(stage152_loop)
        metadata = {
            "allowed_data_layers": list(request.allowed_data_layers or tuple(spec.get("allowed_data_layers", ()))),
            "allow_memory_writeback": bool(request.allow_memory_writeback or spec.get("allow_memory_writeback", False)),
            "provider": self.name,
            "lane": lane_name,
            "model": model,
            "reasoning_effort": effort,
            "usage": usage,
            "duration_ms": duration_ms,
            "budget_tag": request.budget_tag,
            "thinking": dict(payload.get("thinking", {})),
            "reasoning_content_present": bool(reasoning_content),
            "provider_tools_enabled": bool(provider_tool_payload.get("tools")),
            "tool_calls": initial_tool_calls if agent_tool_loop else tool_calls,
            "tool_call_count": len(initial_tool_calls if agent_tool_loop else tool_calls),
            "finish_reason": str(first_choice.get("finish_reason", "") or ""),
            "initial_finish_reason": initial_finish_reason,
        }
        if agent_tool_loop:
            metadata["agent_tool_loop"] = agent_tool_loop
            metadata["final_tool_calls"] = tool_calls
            metadata["tool_observation_ledger"] = list(agent_tool_loop.get("tool_observation_ledger", []) or [])
            metadata["tool_failure_reentry"] = bool(agent_tool_loop.get("tool_failure_reentry", False))
        if stage152_public:
            metadata["stage152_deepseek_tool_loop"] = stage152_public
            metadata["stage152_live_trace"] = dict(stage152_public.get("live_trace", {}) or {})
            metadata["web_observation_ledger"] = list(stage152_public.get("web_observation_ledger", []) or [])
            metadata["memory_observation_ledger"] = list(stage152_public.get("memory_observation_ledger", []) or [])
            if stage152_public.get("time_observation"):
                metadata["time_observation"] = dict(stage152_public.get("time_observation", {}) or {})
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=text,
            session_id=request.session_id,
            returncode=0,
            stdout="",
            stderr="",
            command=[self.name, "chat.completions"],
            output_schema=request.output_schema or str(spec.get("output_schema", "plain_text")),
            metadata=metadata,
        )


class ResponsesProvider(_OpenAIResponsesBase):
    def __init__(self) -> None:
        super().__init__(compatible=False)


class OpenAICompatibleProvider(_OpenAIResponsesBase):
    def __init__(self) -> None:
        super().__init__(compatible=True)


class CodexRunner:
    def __init__(self, config: HostConfig, *, usage_recorder: Any | None = None):
        self.config = config
        self.usage_recorder = usage_recorder
        self._providers: dict[str, ProcessorProvider] = {
            "deepseek": DeepSeekProvider(),
            "codex_cli": CodexCliProvider(),
            "responses": ResponsesProvider(),
            "openai_compatible": OpenAICompatibleProvider(),
        }

    def supported_tasks(self) -> list[dict[str, Any]]:
        routing = self.routing_table()
        tasks: list[dict[str, Any]] = []
        for task_type, payload in PROCESSOR_TASK_SPECS.items():
            current = {"task_type": task_type, **dict(payload)}
            current["routing"] = routing.get(task_type, {})
            tasks.append(current)
        return tasks

    def routing_table(self) -> dict[str, dict[str, Any]]:
        return {
            task_type: {
                "lane": rule.lane,
                "fallback_lane": rule.fallback_lane,
                "budget_tag": rule.budget_tag,
                "upgrade_to_lane": rule.upgrade_to_lane,
                "uncertainty_threshold": rule.uncertainty_threshold,
                "high_conflict_actions": list(rule.high_conflict_actions),
            }
            for task_type, rule in self.config.processor_fabric.processor_routing.items()
        }

    def provider_status(self) -> dict[str, Any]:
        providers = {
            name: {
                "name": name,
                **provider.availability(),
            }
            for name, provider in self._providers.items()
        }
        lanes = {
            lane_name: {
                "primary_provider": lane.primary_provider,
                "backup_provider": lane.backup_provider,
                "model": lane.model,
                "reasoning_effort": lane.reasoning_effort,
                "max_output_tokens": lane.max_output_tokens,
            }
            for lane_name, lane in self.config.processor_fabric.provider_backends.items()
        }
        return {
            "active_backend_alias": self.config.runtime.processor_backend,
            "providers": providers,
            "lanes": lanes,
        }

    def describe_task_dispatch(self, request: ProcessorTaskRequest) -> dict[str, Any]:
        spec = dict(PROCESSOR_TASK_SPECS.get(request.task_type, PROCESSOR_TASK_SPECS["reply"]))
        rule = self._routing_rule_for(request.task_type)
        lane_name = self._resolve_lane_for_request(request, rule)
        lane_config = self._lane_config(lane_name)
        providers = self._provider_chain_for_lane(lane_name, lane_config, request.provider_hint)
        return {
            "task_type": request.task_type,
            "lane": lane_name,
            "fallback_lane": rule.fallback_lane,
            "budget_tag": request.budget_tag or rule.budget_tag or request.task_type,
            "providers": providers,
            "model": request.model_override or lane_config.model,
            "reasoning_effort": request.reasoning_effort_override
            or lane_config.reasoning_effort
            or str(spec.get("default_reasoning_effort", "")),
            "max_output_tokens": request.max_output_tokens or lane_config.max_output_tokens,
            "upgrade_to_lane": rule.upgrade_to_lane,
        }

    @staticmethod
    def _is_missing_resume_rollout(stdout: str, stderr: str) -> bool:
        combined = "\n".join(part for part in (stdout, stderr) if part).lower()
        hints = (
            "thread/resume failed",
            "no rollout found for thread id",
            "no rollout found",
            "failed: no rollout found",
        )
        return any(hint in combined for hint in hints)

    def _resolve_windows_codex_prefix(self) -> list[str] | None:
        try:
            probe = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-Command codex -ErrorAction Stop).Definition",
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except Exception:
            return None
        if probe.returncode != 0:
            return None
        lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
        if not lines:
            return None
        definition = lines[-1]
        if not definition.lower().endswith(".ps1"):
            return None
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", definition]

    def _codex_invocation_prefix(self) -> list[str]:
        explicit = [part.strip() for part in self.config.runtime.codex_command_prefix if str(part).strip()]
        if explicit:
            return explicit

        binary = str(self.config.runtime.codex_binary or "codex").strip() or "codex"
        if binary.lower().endswith(".ps1"):
            return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", binary]

        if os.name == "nt" and binary.lower() == "codex":
            resolved = self._resolve_windows_codex_prefix()
            if resolved:
                return resolved
        return [binary]

    def _apply_runtime_options(
        self,
        command: list[str],
        *,
        resumed: bool,
        model_override: str = "",
        reasoning_effort_override: str = "",
    ) -> list[str]:
        exec_index = command.index("exec")
        insert_at = exec_index + 2 if resumed else exec_index + 1
        options: list[str] = []
        options.extend(str(item).strip() for item in self.config.runtime.codex_extra_args if str(item).strip())
        model = model_override or self.config.runtime.codex_model
        reasoning_effort = reasoning_effort_override or self.config.runtime.codex_reasoning_effort
        if model:
            options.extend(["-m", model])
        if reasoning_effort:
            options.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        if options:
            command[insert_at:insert_at] = options
        return command

    def _routing_rule_for(self, task_type: str) -> TaskRoutingConfig:
        return self.config.processor_fabric.processor_routing.get(task_type) or TaskRoutingConfig(
            lane="subject_main",
            fallback_lane="micro_fast",
            budget_tag=task_type,
        )

    def _lane_config(self, lane_name: str) -> ProcessorLaneConfig:
        return self.config.processor_fabric.provider_backends.get(lane_name) or ProviderLaneConfig(
            primary_provider="codex_cli",
            backup_provider="responses",
            model=str(self.config.runtime.codex_model or "gpt-5.4"),
            reasoning_effort=str(self.config.runtime.codex_reasoning_effort or "medium"),
            max_output_tokens=1800,
        )

    def _resolve_lane_for_request(self, request: ProcessorTaskRequest, rule: TaskRoutingConfig) -> str:
        if str(request.lane or "").strip():
            return str(request.lane).strip()
        lane_name = str(rule.lane or "subject_main").strip() or "subject_main"
        if request.task_type == "reply" and str(rule.upgrade_to_lane or "").strip():
            selected_action = str(
                request.metadata.get("selected_action_type")
                or request.metadata.get("selected_action", "")
                or ""
            ).strip()
            try:
                uncertainty = float(request.metadata.get("uncertainty_level", 0.0) or 0.0)
            except (TypeError, ValueError):
                uncertainty = 0.0
            if selected_action in set(rule.high_conflict_actions) or uncertainty >= float(rule.uncertainty_threshold or 1.0):
                return str(rule.upgrade_to_lane).strip() or lane_name
        return lane_name

    def _provider_chain_for_lane(self, lane_name: str, lane_config: ProcessorLaneConfig, provider_hint: str = "") -> list[str]:
        chain: list[str] = []
        hint = str(provider_hint or "").strip()
        for name in (
            hint,
            lane_config.primary_provider,
            lane_config.backup_provider,
            "deepseek",
            "openai_compatible",
        ):
            current = str(name or "").strip()
            if current and current not in chain:
                chain.append(current)
        backend = str(self.config.runtime.processor_backend or "").strip().lower()
        codex_explicit = "codex_cli" in {str(lane_config.primary_provider or "").strip(), str(lane_config.backup_provider or "").strip(), hint}
        codex_enabled = str(os.environ.get("HOLO_ENABLE_CODEX_FALLBACK", "")).strip().lower() in {"1", "true", "yes", "on"}
        if "codex_cli" not in chain and (backend == "codex_cli" or codex_explicit or codex_enabled):
            chain.append("codex_cli")
        return chain

    def _record_usage(self, request: ProcessorTaskRequest, result: ProcessorTaskResult) -> None:
        if not callable(self.usage_recorder):
            return
        metadata = dict(result.metadata or {})
        usage = _coerce_usage_payload(metadata.get("usage"))
        model = str(metadata.get("model", request.model_override)).strip()
        reasoning_effort = str(metadata.get("reasoning_effort", request.reasoning_effort_override)).strip()
        lane = str(metadata.get("lane", request.lane)).strip()
        provider = str(metadata.get("provider", request.provider_hint)).strip()
        duration_ms = int(metadata.get("duration_ms", 0) or 0)
        thread_key = str(request.metadata.get("thread_key", "") or request.metadata.get("chat_name", "") or "").strip()
        event_id = str(request.metadata.get("event_id", "") or "").strip()
        try:
            self.usage_recorder(
                ProcessorUsageRecord(
                    task_type=request.task_type,
                    lane=lane,
                    provider=provider,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    thread_key=thread_key,
                    event_id=event_id,
                    duration_ms=duration_ms,
                    prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                    completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                    total_tokens=int(usage.get("total_tokens", 0) or 0),
                    estimated=bool(usage.get("estimated", True)),
                    status="ok" if int(result.returncode or 0) == 0 else "error",
                    metadata={
                        "budget_tag": metadata.get("budget_tag", request.budget_tag),
                        "output_schema": result.output_schema,
                        "fallback_provider": metadata.get("fallback_provider", ""),
                    },
                )
            )
        except Exception:
            return

    def run(
        self,
        prompt: str,
        *,
        session_id: str = "",
        lane: str = "",
        provider_hint: str = "",
        model_override: str = "",
        reasoning_effort_override: str = "",
        budget_tag: str = "",
        max_output_tokens: int | None = None,
        timeout_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CodexResult:
        resolved_model_override = model_override
        resolved_reasoning_effort_override = reasoning_effort_override
        backend = str(self.config.runtime.processor_backend or "").strip().lower()
        if not str(lane or "").strip() and backend == "codex_cli":
            if not str(resolved_model_override or "").strip():
                resolved_model_override = str(self.config.runtime.codex_model or "").strip()
            if not str(resolved_reasoning_effort_override or "").strip():
                resolved_reasoning_effort_override = str(self.config.runtime.codex_reasoning_effort or "").strip()
        result = self.run_task(
            ProcessorTaskRequest(
                task_type="reply",
                prompt=prompt,
                session_id=session_id,
                lane=lane,
                provider_hint=provider_hint,
                model_override=resolved_model_override,
                reasoning_effort_override=resolved_reasoning_effort_override,
                budget_tag=budget_tag,
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
                metadata=dict(metadata or {}),
            )
        )
        return result.to_codex_result()

    def run_task(self, request: ProcessorTaskRequest) -> ProcessorTaskResult:
        spec = dict(PROCESSOR_TASK_SPECS.get(request.task_type, PROCESSOR_TASK_SPECS["reply"]))
        resolved_request = ProcessorTaskRequest(
            task_type=request.task_type,
            prompt=request.prompt,
            session_id=request.session_id,
            lane=request.lane,
            provider_hint=request.provider_hint,
            model_override=request.model_override,
            reasoning_effort_override=request.reasoning_effort_override or str(spec.get("default_reasoning_effort", "")),
            budget_tag=request.budget_tag,
            timeout_seconds=request.timeout_seconds,
            output_schema=request.output_schema or str(spec.get("output_schema", "plain_text")),
            allowed_data_layers=request.allowed_data_layers or tuple(spec.get("allowed_data_layers", ())),
            allow_memory_writeback=bool(request.allow_memory_writeback or spec.get("allow_memory_writeback", False)),
            image_paths=request.image_paths,
            workspace_mode=request.workspace_mode,
            operator_scope=request.operator_scope,
            max_output_tokens=request.max_output_tokens,
            metadata=dict(request.metadata),
        )
        rule = self._routing_rule_for(resolved_request.task_type)
        lane_name = self._resolve_lane_for_request(resolved_request, rule)
        lane_config = self._lane_config(lane_name)
        provider_chain = self._provider_chain_for_lane(lane_name, lane_config, resolved_request.provider_hint)
        last_error: str = ""
        provider_errors: list[str] = []
        for index, provider_name in enumerate(provider_chain):
            provider = self._providers.get(provider_name)
            if provider is None:
                last_error = f"unknown provider: {provider_name}"
                provider_errors.append(last_error)
                continue
            availability = provider.availability()
            if not bool(availability.get("available", False)):
                last_error = str(availability.get("reason", f"{provider_name} unavailable"))
                provider_errors.append(f"{provider_name}: {last_error}")
                continue
            if not provider.supports_request(resolved_request):
                last_error = f"{provider_name} does not support task request"
                provider_errors.append(last_error)
                continue
            try:
                result = provider.run_task(
                    self,
                    resolved_request,
                    spec=spec,
                    lane_name=lane_name,
                    lane_config=lane_config,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                provider_errors.append(f"{provider_name}: {last_error}")
                continue
            metadata = dict(result.metadata or {})
            metadata.setdefault("lane", lane_name)
            metadata.setdefault("provider", provider_name)
            metadata.setdefault("model", resolved_request.model_override or lane_config.model)
            metadata.setdefault(
                "reasoning_effort",
                resolved_request.reasoning_effort_override or lane_config.reasoning_effort or str(spec.get("default_reasoning_effort", "")),
            )
            metadata.setdefault("budget_tag", resolved_request.budget_tag or rule.budget_tag or resolved_request.task_type)
            if index > 0:
                metadata["fallback_provider"] = provider_name
            result.metadata = metadata
            self._record_usage(resolved_request, result)
            return result
        failure_detail = " | ".join(provider_errors) if provider_errors else (last_error or "no provider available")
        failed = ProcessorTaskResult(
            task_type=resolved_request.task_type,
            text="",
            session_id=resolved_request.session_id,
            returncode=1,
            stdout="",
            stderr=failure_detail,
            command=[],
            output_schema=resolved_request.output_schema,
            metadata={
                "lane": lane_name,
                "provider": "",
                "model": resolved_request.model_override or lane_config.model,
                "reasoning_effort": resolved_request.reasoning_effort_override
                or lane_config.reasoning_effort
                or str(spec.get("default_reasoning_effort", "")),
                "budget_tag": resolved_request.budget_tag or rule.budget_tag or resolved_request.task_type,
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated": True,
                },
                "duration_ms": 0,
            },
        )
        self._record_usage(resolved_request, failed)
        return failed

    @staticmethod
    def _parse_thread_id(stdout: str) -> str:
        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "thread.started":
                return str(payload.get("thread_id", "")).strip()
        return ""
