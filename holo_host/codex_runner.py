from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .common import json_dumps
from .config import HostConfig, ProcessorLaneConfig, TaskRoutingConfig
from .context_scheduler import estimate_tokens, split_provider_cache_prompt
from .models import CodexResult, ProcessorTaskRequest, ProcessorTaskResult, ProcessorUsageRecord
from .provider_substrate import analyze_provider_substrate_conflicts


def _windows_registry_env_value(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
    except Exception:
        return ""
    targets = (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    )
    for hive, path in targets:
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _kind = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        current = str(value or "").strip()
        if current:
            return current
    return ""


def _environment_value_with_source(name: str) -> tuple[str, str]:
    current = str(os.environ.get(name, "") or "").strip()
    if current:
        return current, "process"
    current = _windows_registry_env_value(name)
    if current:
        return current, "windows_registry"
    return "", ""


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


def _coerce_usage_payload(payload: Any) -> dict[str, int | bool | float]:
    if payload is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
            "prompt_cache_hit_ratio": 0.0,
            "estimated": True,
        }
    if isinstance(payload, dict):
        prompt_tokens = int(payload.get("prompt_tokens", payload.get("input_tokens", 0)) or 0)
        completion_tokens = int(payload.get("completion_tokens", payload.get("output_tokens", 0)) or 0)
        total_tokens = int(payload.get("total_tokens", prompt_tokens + completion_tokens) or 0)
        hit_tokens = int(payload.get("prompt_cache_hit_tokens", 0) or 0)
        miss_tokens = int(payload.get("prompt_cache_miss_tokens", 0) or 0)
        if hit_tokens and not miss_tokens and prompt_tokens >= hit_tokens:
            miss_tokens = prompt_tokens - hit_tokens
        estimated = bool(payload.get("estimated", False))
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "prompt_cache_hit_tokens": hit_tokens,
            "prompt_cache_miss_tokens": miss_tokens,
            "prompt_cache_hit_ratio": round(hit_tokens / (hit_tokens + miss_tokens), 4)
            if (hit_tokens + miss_tokens)
            else 0.0,
            "estimated": estimated,
        }
    prompt_tokens = int(getattr(payload, "prompt_tokens", getattr(payload, "input_tokens", 0)) or 0)
    completion_tokens = int(getattr(payload, "completion_tokens", getattr(payload, "output_tokens", 0)) or 0)
    total_tokens = int(getattr(payload, "total_tokens", prompt_tokens + completion_tokens) or 0)
    hit_tokens = int(getattr(payload, "prompt_cache_hit_tokens", 0) or 0)
    miss_tokens = int(getattr(payload, "prompt_cache_miss_tokens", 0) or 0)
    if hit_tokens and not miss_tokens and prompt_tokens >= hit_tokens:
        miss_tokens = prompt_tokens - hit_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "prompt_cache_hit_tokens": hit_tokens,
        "prompt_cache_miss_tokens": miss_tokens,
        "prompt_cache_hit_ratio": round(hit_tokens / (hit_tokens + miss_tokens), 4)
        if (hit_tokens + miss_tokens)
        else 0.0,
        "estimated": False,
    }


class ProcessorProvider:
    name = "provider"
    api_surface = "provider"
    capabilities: dict[str, Any] = {
        "text": True,
        "json_output": False,
        "image_support": False,
    }

    def availability(self) -> dict[str, Any]:
        return {"available": True, "reason": ""}

    def supports_request(self, request: ProcessorTaskRequest) -> bool:
        return True

    def provider_contract(self, runner: "CodexRunner") -> dict[str, Any]:
        availability = runner._provider_availability(self.name, self)
        return {
            "name": self.name,
            "api_surface": self.api_surface,
            "available": bool(availability.get("available", False)),
            "availability_reason": str(availability.get("reason", "") or ""),
            "capabilities": dict(self.capabilities),
            "processor_fabric_only": True,
        }

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
    api_surface = "codex.exec"
    capabilities = {
        "text": True,
        "json_output": True,
        "image_support": True,
    }

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
        effective_model = runner._provider_model(self.name, lane_name, lane_config, request)
        effective_reasoning_effort = runner._provider_reasoning_effort(
            self.name,
            lane_name,
            lane_config,
            request,
            spec,
        )

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
                model_override=effective_model,
                reasoning_effort_override=effective_reasoning_effort,
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
                "model": effective_model,
                "reasoning_effort": effective_reasoning_effort,
                "usage": usage,
                "duration_ms": duration_ms,
                "budget_tag": request.budget_tag,
                "capabilities": dict(self.capabilities),
                "image_path_count": len([path for path in request.image_paths if str(path or "").strip()]),
            },
        )


class _OpenAIResponsesBase(ProcessorProvider):
    base_name = "responses"
    api_surface = "responses.create"
    capabilities = {
        "text": True,
        "json_output": True,
        "image_support": False,
    }

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
        from openai import OpenAI  # type: ignore

        kwargs: dict[str, Any] = {}
        base_url = self._base_url(runner)
        if base_url:
            kwargs["base_url"] = base_url
        api_key = self._api_key(runner)
        if api_key:
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
        effective_model = runner._provider_model(self.name, lane_name, lane_config, request)
        effective_reasoning_effort = runner._provider_reasoning_effort(
            self.name,
            lane_name,
            lane_config,
            request,
            spec,
        )
        response = client.responses.create(
            model=effective_model,
            input=request.prompt,
            max_output_tokens=request.max_output_tokens or lane_config.max_output_tokens or None,
        )
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        text = str(getattr(response, "output_text", "") or "").strip()
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
            command=[self.name, "responses.create"],
            output_schema=request.output_schema or str(spec.get("output_schema", "plain_text")),
            metadata={
                "allowed_data_layers": list(request.allowed_data_layers or tuple(spec.get("allowed_data_layers", ()))),
                "allow_memory_writeback": bool(request.allow_memory_writeback or spec.get("allow_memory_writeback", False)),
                "provider": self.name,
                "lane": lane_name,
                "model": effective_model,
                "reasoning_effort": effective_reasoning_effort,
                "usage": usage,
                "duration_ms": duration_ms,
                "budget_tag": request.budget_tag,
            },
        )


class ResponsesProvider(_OpenAIResponsesBase):
    def __init__(self) -> None:
        super().__init__(compatible=False)


class OpenAICompatibleProvider(_OpenAIResponsesBase):
    def __init__(self) -> None:
        super().__init__(compatible=True)
        self.api_surface = "chat.completions"

    @staticmethod
    def _extract_chat_text(response: Any) -> str:
        choices = getattr(response, "choices", None)
        if choices is None and isinstance(response, dict):
            choices = response.get("choices", [])
        if not choices:
            return ""
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message", {})
            return str(message.get("content", "") if isinstance(message, dict) else "").strip()
        message = getattr(first, "message", None)
        return str(getattr(message, "content", "") or "").strip()

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
        effective_model = runner._provider_model(self.name, lane_name, lane_config, request)
        effective_reasoning_effort = runner._provider_reasoning_effort(
            self.name,
            lane_name,
            lane_config,
            request,
            spec,
        )
        payload: dict[str, Any] = {
            "model": effective_model,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        max_tokens = request.max_output_tokens or lane_config.max_output_tokens or None
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        output_schema = str(request.output_schema or spec.get("output_schema", "plain_text"))
        if "json" in output_schema.lower():
            payload["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**payload)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        text = self._extract_chat_text(response)
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
            command=[self.name, "chat.completions.create"],
            output_schema=output_schema,
            metadata={
                "allowed_data_layers": list(request.allowed_data_layers or tuple(spec.get("allowed_data_layers", ()))),
                "allow_memory_writeback": bool(request.allow_memory_writeback or spec.get("allow_memory_writeback", False)),
                "provider": self.name,
                "lane": lane_name,
                "model": effective_model,
                "reasoning_effort": effective_reasoning_effort,
                "usage": usage,
                "duration_ms": duration_ms,
                "budget_tag": request.budget_tag,
                "capabilities": dict(self.capabilities),
            },
        )


class DeepSeekProvider(ProcessorProvider):
    name = "deepseek"
    api_surface = "chat.completions"

    capabilities = {
        "text": True,
        "json_output": True,
        "tool_call_protocol": "openai_chat_completions",
        "thinking_mode": True,
        "reasoning_content_preserved": True,
        "image_support": False,
    }

    def _base_url(self, runner: "CodexRunner") -> str:
        return (
            runner.config.processor_fabric.deepseek_base_url
            or os.environ.get("DEEPSEEK_BASE_URL", "")
            or "https://api.deepseek.com"
        ).strip().rstrip("/")

    def _api_key(self, runner: "CodexRunner") -> str:
        env_name = runner.config.processor_fabric.deepseek_api_key_env or "DEEPSEEK_API_KEY"
        value, _source = _environment_value_with_source(env_name)
        return value

    def availability(self) -> dict[str, Any]:
        return {"available": True, "reason": "", "capabilities": dict(self.capabilities)}

    def supports_request(self, request: ProcessorTaskRequest) -> bool:
        return not bool(request.image_paths)

    @staticmethod
    def _messages_for_request(request: ProcessorTaskRequest) -> tuple[list[dict[str, str]], dict[str, Any]]:
        single = [{"role": "user", "content": request.prompt}]
        context_schedule = (
            dict(request.metadata.get("context_schedule", {}))
            if isinstance(request.metadata.get("context_schedule", {}), dict)
            else {}
        )
        scheduled_prefix_tokens = int(context_schedule.get("provider_cache_prefix_tokens", 0) or 0)
        if scheduled_prefix_tokens < 512:
            return single, {"mode": "single_user", "reason": "prefix_below_threshold"}
        prefix, dynamic = split_provider_cache_prompt(request.prompt)
        if not prefix.strip() or not dynamic.strip():
            return single, {"mode": "single_user", "reason": "unsplittable_prompt"}
        prefix_tokens = estimate_tokens(prefix)
        if prefix_tokens < 512:
            return single, {"mode": "single_user", "reason": "computed_prefix_below_threshold"}
        return (
            [
                {"role": "system", "content": prefix.rstrip()},
                {"role": "user", "content": dynamic.lstrip()},
            ],
            {
                "mode": "stable_prefix_messages",
                "provider_cache_prefix_digest": str(context_schedule.get("provider_cache_prefix_digest", "") or ""),
                "provider_cache_prefix_tokens": prefix_tokens,
                "provider_cache_dynamic_tokens": estimate_tokens(dynamic),
            },
        )

    def _payload(
        self,
        request: ProcessorTaskRequest,
        *,
        spec: dict[str, Any],
        lane_config: ProcessorLaneConfig,
        model: str,
        reasoning_effort: str,
        messages: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        effective_effort = str(reasoning_effort or "").strip().lower()
        request_messages = messages if messages is not None else self._messages_for_request(request)[0]
        payload: dict[str, Any] = {
            "model": model,
            "messages": request_messages,
            "stream": False,
        }
        if effective_effort in {"high", "xhigh", "max"}:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "max" if effective_effort in {"xhigh", "max"} else "high"
        else:
            payload["thinking"] = {"type": "disabled"}
        max_tokens = request.max_output_tokens or lane_config.max_output_tokens or None
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        output_schema = str(request.output_schema or spec.get("output_schema", "plain_text"))
        if "json" in output_schema.lower():
            payload["response_format"] = {"type": "json_object"}
        return payload

    @staticmethod
    def _extract_message(response: dict[str, Any]) -> dict[str, Any]:
        choices = response.get("choices", [])
        if not choices:
            return {}
        first = choices[0] if isinstance(choices[0], dict) else {}
        return first.get("message", {}) if isinstance(first, dict) and isinstance(first.get("message", {}), dict) else {}

    @classmethod
    def _extract_text(cls, response: dict[str, Any]) -> str:
        message = cls._extract_message(response)
        return str(message.get("content", "") or "").strip()

    @classmethod
    def _extract_reasoning_content(cls, response: dict[str, Any]) -> str:
        message = cls._extract_message(response)
        return str(message.get("reasoning_content", "") or "").strip()

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
        api_key = self._api_key(runner)
        if not api_key:
            raise RuntimeError(f"{runner.config.processor_fabric.deepseek_api_key_env} is not set")
        effective_model = runner._provider_model(self.name, lane_name, lane_config, request)
        effective_reasoning_effort = runner._provider_reasoning_effort(
            self.name,
            lane_name,
            lane_config,
            request,
            spec,
        )
        url = f"{self._base_url(runner)}/chat/completions"
        messages, prompt_partition = self._messages_for_request(request)
        payload = self._payload(
            request,
            spec=spec,
            lane_config=lane_config,
            model=effective_model,
            reasoning_effort=effective_reasoning_effort,
            messages=messages,
        )
        http_request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        timeout = float(request.timeout_seconds or runner.config.runtime.codex_timeout_seconds or 900)
        with urlopen(http_request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        text = self._extract_text(response_payload)
        reasoning_content = self._extract_reasoning_content(response_payload)
        usage = _coerce_usage_payload(response_payload.get("usage"))
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
            command=[self.name, "chat.completions.create"],
            output_schema=request.output_schema or str(spec.get("output_schema", "plain_text")),
            metadata={
                "allowed_data_layers": list(request.allowed_data_layers or tuple(spec.get("allowed_data_layers", ()))),
                "allow_memory_writeback": bool(request.allow_memory_writeback or spec.get("allow_memory_writeback", False)),
                "provider": self.name,
                "lane": lane_name,
                "model": effective_model,
                "reasoning_effort": effective_reasoning_effort,
                "usage": usage,
                "duration_ms": duration_ms,
                "budget_tag": request.budget_tag,
                "capabilities": dict(self.capabilities),
                "reasoning_content": reasoning_content,
                "reasoning_content_present": bool(reasoning_content),
                "prompt_partition": prompt_partition,
            },
        )


class CodexRunner:
    _RESPONSE_CACHE_PROVIDERS = {"responses", "openai_compatible", "deepseek"}

    def __init__(self, config: HostConfig, *, usage_recorder: Any | None = None, response_cache_store: Any | None = None):
        self.config = config
        self.usage_recorder = usage_recorder
        self.response_cache_store = response_cache_store
        self._providers: dict[str, ProcessorProvider] = {
            "codex_cli": CodexCliProvider(),
            "responses": ResponsesProvider(),
            "openai_compatible": OpenAICompatibleProvider(),
            "deepseek": DeepSeekProvider(),
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

    def _provider_availability(self, provider_name: str, provider: ProcessorProvider) -> dict[str, Any]:
        availability = dict(provider.availability())
        if provider_name == "deepseek":
            env_name = self.config.processor_fabric.deepseek_api_key_env or "DEEPSEEK_API_KEY"
            api_key, source = _environment_value_with_source(env_name)
            availability["api_key_env"] = env_name
            availability["base_url"] = self.config.processor_fabric.deepseek_base_url or "https://api.deepseek.com"
            availability["api_key_source"] = source
            if not api_key:
                availability["available"] = False
                availability["reason"] = f"{env_name} is not set"
        return availability

    def provider_status(self) -> dict[str, Any]:
        providers = {
            name: {
                "name": name,
                **self._provider_availability(name, provider),
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
        try:
            from .bionic_brain import stage40_deepseek_v4_status
        except Exception:  # noqa: BLE001
            stage40_status = {}
        else:
            stage40_status = stage40_deepseek_v4_status(
                {
                    "providers": providers,
                    "lanes": lanes,
                    "response_cache": self.response_cache_stats(),
                }
            )
        return {
            "active_backend_alias": self.config.runtime.processor_backend,
            "providers": providers,
            "lanes": lanes,
            "response_cache": self.response_cache_stats(),
            "stage40_deepseek_v4": stage40_status,
        }

    def provider_substrate_status(self) -> dict[str, Any]:
        provider_status = self.provider_status()
        report = analyze_provider_substrate_conflicts(provider_status)
        return {
            "stage": "stage47-provider-substrate-conflict-monitor",
            "provider_status": provider_status,
            **report,
        }

    def provider_contracts(self) -> dict[str, Any]:
        providers = {
            name: provider.provider_contract(self)
            for name, provider in self._providers.items()
        }
        lane_contracts = {}
        for lane_name, lane in self.config.processor_fabric.provider_backends.items():
            lane_contracts[lane_name] = {
                "primary_provider": lane.primary_provider,
                "backup_provider": lane.backup_provider,
                "model": lane.model,
                "reasoning_effort": lane.reasoning_effort,
                "provider_chain": self._provider_chain_for_lane(lane_name, lane),
            }
        return {
            "stage": "stage33-provider-api-contracts",
            "providers": providers,
            "lanes": lane_contracts,
            "hard_boundaries": {
                "processor_fabric_only": True,
                "no_raw_hot_path_provider_calls": True,
                "transport_has_no_provider_authority": True,
                "no_live_call_required": True,
            },
        }

    def visual_provider_readiness(self) -> dict[str, Any]:
        probe_request = ProcessorTaskRequest(
            task_type="image_understand",
            prompt="Stage34 visual readiness probe. Do not execute; inspect provider support only.",
            image_paths=("stage34_visual_probe.png",),
            output_schema="json",
        )
        dispatch = self.describe_task_dispatch(probe_request)
        provider_rows: dict[str, dict[str, Any]] = {}
        for name, provider in self._providers.items():
            contract = provider.provider_contract(self)
            provider_rows[name] = {
                "name": name,
                "api_surface": contract.get("api_surface", ""),
                "capabilities": dict(contract.get("capabilities", {})),
                "image_request_supported": bool(provider.supports_request(probe_request)),
                "available": bool(contract.get("available", False)),
                "availability_reason": str(contract.get("availability_reason", "") or ""),
            }
        text_api_provider_names = ("responses", "openai_compatible", "deepseek")
        text_api_reject_images = all(
            provider_rows.get(name, {}).get("image_request_supported") is False
            for name in text_api_provider_names
        )
        image_capable = [
            name
            for name, payload in provider_rows.items()
            if bool(payload.get("image_request_supported", False))
        ]
        routing_visible = "image_understand" in PROCESSOR_TASK_SPECS and bool(dispatch.get("providers"))
        return {
            "stage": "stage34-debt-registry-and-visual-readiness",
            "providers": provider_rows,
            "routing": {
                "image_understand": dispatch,
            },
            "checks": {
                "image_task_routing_visible": routing_visible,
                "text_api_providers_reject_image_requests": text_api_reject_images,
                "image_capable_path_visible": bool(image_capable),
                "no_visual_overclaim": text_api_reject_images,
            },
            "image_capable_providers": image_capable,
            "hard_boundaries": {
                "no_live_call_required": True,
                "processor_fabric_only": True,
                "no_transport_send_right_change": True,
                "no_self_memory_mutation": True,
            },
        }

    def describe_task_dispatch(self, request: ProcessorTaskRequest) -> dict[str, Any]:
        spec = dict(PROCESSOR_TASK_SPECS.get(request.task_type, PROCESSOR_TASK_SPECS["reply"]))
        rule = self._routing_rule_for(request.task_type)
        lane_name = self._resolve_lane_for_request(request, rule)
        lane_config = self._lane_config(lane_name)
        providers = self._provider_chain_for_lane(lane_name, lane_config, request.provider_hint)
        first_provider = providers[0] if providers else ""
        return {
            "task_type": request.task_type,
            "lane": lane_name,
            "fallback_lane": rule.fallback_lane,
            "budget_tag": request.budget_tag or rule.budget_tag or request.task_type,
            "providers": providers,
            "model": self._provider_model(first_provider, lane_name, lane_config, request),
            "reasoning_effort": self._provider_reasoning_effort(first_provider, lane_name, lane_config, request, spec),
            "provider_models": {
                provider_name: self._provider_model(provider_name, lane_name, lane_config, request)
                for provider_name in providers
            },
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
            "openai_compatible",
        ):
            current = str(name or "").strip()
            if current and current not in chain:
                chain.append(current)
        if "codex_cli" not in chain:
            chain.append("codex_cli")
        return chain

    @staticmethod
    def _uses_fast_model(lane_name: str) -> bool:
        current = str(lane_name or "").strip().lower()
        return current == "micro_fast" or current.endswith("_fast") or "fast" in current

    def _provider_model(
        self,
        provider_name: str,
        lane_name: str,
        lane_config: ProcessorLaneConfig,
        request: ProcessorTaskRequest,
    ) -> str:
        explicit = str(request.model_override or "").strip()
        if explicit:
            return explicit
        provider = str(provider_name or "").strip()
        lane_model = str(lane_config.model or "").strip()
        use_fast = self._uses_fast_model(lane_name)
        if provider == "codex_cli":
            preferred = self.config.runtime.fast_model if use_fast else self.config.runtime.codex_model
            return str(preferred or lane_model or "").strip()
        if provider == "responses":
            preferred = self.config.runtime.responses_fast_model if use_fast else self.config.runtime.responses_model
            return str(preferred or lane_model or "").strip()
        if provider == "deepseek":
            preferred = (
                self.config.processor_fabric.deepseek_fast_model
                if use_fast
                else self.config.processor_fabric.deepseek_model
            )
            if lane_config.primary_provider == "deepseek":
                return str(lane_model or preferred or "").strip()
            return str(preferred or lane_model or "").strip()
        if provider == "openai_compatible":
            if lane_config.primary_provider == "openai_compatible":
                return lane_model
            preferred = self.config.runtime.responses_fast_model if use_fast else self.config.runtime.responses_model
            return str(preferred or lane_model or "").strip()
        return lane_model

    def _provider_reasoning_effort(
        self,
        provider_name: str,
        lane_name: str,
        lane_config: ProcessorLaneConfig,
        request: ProcessorTaskRequest,
        spec: dict[str, Any],
    ) -> str:
        explicit = str(request.reasoning_effort_override or "").strip()
        if explicit:
            return explicit
        provider = str(provider_name or "").strip()
        if provider == "codex_cli":
            if self._uses_fast_model(lane_name) and str(self.config.runtime.fast_reasoning_effort or "").strip():
                return str(self.config.runtime.fast_reasoning_effort or "").strip()
            if str(self.config.runtime.codex_reasoning_effort or "").strip():
                return str(self.config.runtime.codex_reasoning_effort or "").strip()
        return str(lane_config.reasoning_effort or spec.get("default_reasoning_effort", "") or "").strip()

    def response_cache_stats(self) -> dict[str, Any]:
        enabled = bool(getattr(self.config.processor_fabric, "response_cache_enabled", True))
        if not enabled or not hasattr(self.response_cache_store, "processor_response_cache_stats"):
            return {
                "enabled": enabled,
                "available": False,
                "cache_mode": "exact_response",
                "entries": 0,
                "hits": 0,
                "misses": 0,
                "hit_ratio": 0.0,
            }
        try:
            stats = dict(self.response_cache_store.processor_response_cache_stats())
        except Exception:
            return {
                "enabled": enabled,
                "available": False,
                "cache_mode": "exact_response",
                "entries": 0,
                "hits": 0,
                "misses": 0,
                "hit_ratio": 0.0,
            }
        stats.setdefault("entries", 0)
        stats.setdefault("hits", 0)
        stats.setdefault("misses", 0)
        stats.setdefault("hit_ratio", 0.0)
        stats["enabled"] = enabled
        stats["available"] = True
        stats["cache_mode"] = "exact_response"
        stats["diagnostic_note"] = "Chat replies miss unless the full rendered prompt is identical; context_schedule metadata tracks stable and volatile prompt digests for processor-context reuse work."
        return stats

    def _response_cache_enabled_for(
        self,
        request: ProcessorTaskRequest,
        *,
        provider_name: str,
    ) -> bool:
        if not bool(getattr(self.config.processor_fabric, "response_cache_enabled", True)):
            return False
        if provider_name not in self._RESPONSE_CACHE_PROVIDERS:
            return False
        if not hasattr(self.response_cache_store, "get_processor_response_cache"):
            return False
        if not hasattr(self.response_cache_store, "put_processor_response_cache"):
            return False
        if bool(request.metadata.get("cache_bypass", False)):
            return False
        if bool(request.allow_memory_writeback):
            return False
        if request.image_paths:
            return False
        if str(request.workspace_mode or "live_readonly").strip() != "live_readonly":
            return False
        return True

    def _response_cache_key(
        self,
        request: ProcessorTaskRequest,
        *,
        provider_name: str,
        lane_name: str,
        lane_config: ProcessorLaneConfig,
        spec: dict[str, Any],
    ) -> str:
        model = self._provider_model(provider_name, lane_name, lane_config, request)
        reasoning_effort = self._provider_reasoning_effort(provider_name, lane_name, lane_config, request, spec)
        payload = {
            "version": 2,
            "provider": provider_name,
            "task_type": request.task_type,
            "lane": lane_name,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "output_schema": request.output_schema,
            "max_output_tokens": request.max_output_tokens or lane_config.max_output_tokens or 0,
            "allowed_data_layers": list(request.allowed_data_layers),
            "workspace_mode": request.workspace_mode,
            "operator_scope": request.operator_scope,
            "prompt": request.prompt,
        }
        return hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()

    def _cached_result_from_payload(self, *, cached: dict[str, Any], cache_key: str) -> ProcessorTaskResult:
        payload = dict(cached.get("payload", {})) if isinstance(cached.get("payload", {}), dict) else {}
        metadata = dict(payload.get("metadata", {})) if isinstance(payload.get("metadata", {}), dict) else {}
        original_usage = _coerce_usage_payload(metadata.get("usage"))
        metadata["cached_usage"] = original_usage
        metadata["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated": True}
        metadata["duration_ms"] = 0
        metadata["processor_usage_status"] = "cache_hit"
        metadata["cache"] = {
            "hit": True,
            "source": "processor_response_cache",
            "cache_key": cache_key,
            "cached_at": str(cached.get("created_at", "") or ""),
            "hit_count": int(cached.get("hit_count", 0) or 0),
        }
        command = payload.get("command", [])
        return ProcessorTaskResult(
            task_type=str(payload.get("task_type", "") or "reply"),
            text=str(payload.get("text", "") or ""),
            session_id=str(payload.get("session_id", "") or ""),
            returncode=int(payload.get("returncode", 0) or 0),
            stdout=str(payload.get("stdout", "") or ""),
            stderr=str(payload.get("stderr", "") or ""),
            command=list(command) if isinstance(command, list) else [],
            output_schema=str(payload.get("output_schema", "") or "plain_text"),
            metadata=metadata,
        )

    @staticmethod
    def _cacheable_payload_from_result(result: ProcessorTaskResult) -> dict[str, Any]:
        metadata = dict(result.metadata or {})
        metadata.pop("cache", None)
        metadata.pop("processor_usage_status", None)
        return {
            "task_type": result.task_type,
            "text": result.text,
            "session_id": result.session_id,
            "returncode": int(result.returncode or 0),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": list(result.command),
            "output_schema": result.output_schema,
            "metadata": metadata,
        }

    def _store_response_cache(
        self,
        *,
        cache_key: str,
        result: ProcessorTaskResult,
        provider_name: str,
        request: ProcessorTaskRequest,
        lane_name: str,
        lane_config: ProcessorLaneConfig,
        spec: dict[str, Any],
    ) -> None:
        if int(result.returncode or 0) != 0 or not str(result.text or "").strip():
            return
        if not hasattr(self.response_cache_store, "put_processor_response_cache"):
            return
        try:
            self.response_cache_store.put_processor_response_cache(
                cache_key=cache_key,
                payload=self._cacheable_payload_from_result(result),
                provider=provider_name,
                task_type=request.task_type,
                lane=lane_name,
                model=str(result.metadata.get("model", self._provider_model(provider_name, lane_name, lane_config, request)) or ""),
                reasoning_effort=str(
                    result.metadata.get(
                        "reasoning_effort",
                        self._provider_reasoning_effort(provider_name, lane_name, lane_config, request, spec),
                    )
                    or ""
                ),
                ttl_seconds=int(getattr(self.config.processor_fabric, "response_cache_ttl_seconds", 3600) or 3600),
                max_entries=int(getattr(self.config.processor_fabric, "response_cache_max_entries", 512) or 512),
                miss_count=1,
                metadata={"output_schema": result.output_schema, "budget_tag": result.metadata.get("budget_tag", "")},
            )
        except Exception:
            return

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
        status = str(metadata.get("processor_usage_status", "") or "").strip()
        if not status:
            status = "ok" if int(result.returncode or 0) == 0 else "error"
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
                    status=status,
                    metadata={
                        "budget_tag": metadata.get("budget_tag", request.budget_tag),
                        "output_schema": result.output_schema,
                        "fallback_provider": metadata.get("fallback_provider", ""),
                        "usage": dict(usage),
                        "cache": metadata.get("cache", {}),
                        "cached_usage": metadata.get("cached_usage", {}),
                        "cache_mode": "exact_response",
                        "context_schedule": dict(request.metadata.get("context_schedule", {}))
                        if isinstance(request.metadata.get("context_schedule", {}), dict)
                        else {},
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
        metadata: dict[str, Any] | None = None,
    ) -> CodexResult:
        resolved_model_override = model_override
        resolved_reasoning_effort_override = reasoning_effort_override
        if not str(lane or "").strip():
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
        provider_failures: list[dict[str, Any]] = []
        for index, provider_name in enumerate(provider_chain):
            provider = self._providers.get(provider_name)
            if provider is None:
                last_error = f"unknown provider: {provider_name}"
                provider_failures.append({"provider": provider_name, "reason": last_error})
                continue
            availability = provider.availability()
            if not bool(availability.get("available", False)):
                last_error = str(availability.get("reason", f"{provider_name} unavailable"))
                provider_failures.append({"provider": provider_name, "reason": last_error})
                continue
            if not provider.supports_request(resolved_request):
                last_error = f"{provider_name} does not support task request"
                provider_failures.append({"provider": provider_name, "reason": last_error})
                continue
            cache_key = ""
            if self._response_cache_enabled_for(resolved_request, provider_name=provider_name):
                cache_key = self._response_cache_key(
                    resolved_request,
                    provider_name=provider_name,
                    lane_name=lane_name,
                    lane_config=lane_config,
                    spec=spec,
                )
                try:
                    cached = self.response_cache_store.get_processor_response_cache(cache_key)
                except Exception:
                    cached = None
                if cached:
                    result = self._cached_result_from_payload(cached=cached, cache_key=cache_key)
                    metadata = dict(result.metadata or {})
                    metadata.setdefault("lane", lane_name)
                    metadata.setdefault("provider", provider_name)
                    metadata.setdefault("model", self._provider_model(provider_name, lane_name, lane_config, resolved_request))
                    metadata.setdefault(
                        "reasoning_effort",
                        self._provider_reasoning_effort(provider_name, lane_name, lane_config, resolved_request, spec),
                    )
                    metadata.setdefault("budget_tag", resolved_request.budget_tag or rule.budget_tag or resolved_request.task_type)
                    if provider_failures:
                        metadata["provider_failures"] = list(provider_failures)
                    result.metadata = metadata
                    self._record_usage(resolved_request, result)
                    return result
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
                provider_failures.append({"provider": provider_name, "reason": last_error})
                continue
            metadata = dict(result.metadata or {})
            metadata.setdefault("lane", lane_name)
            metadata.setdefault("provider", provider_name)
            metadata.setdefault("model", self._provider_model(provider_name, lane_name, lane_config, resolved_request))
            metadata.setdefault(
                "reasoning_effort",
                self._provider_reasoning_effort(provider_name, lane_name, lane_config, resolved_request, spec),
            )
            metadata.setdefault("budget_tag", resolved_request.budget_tag or rule.budget_tag or resolved_request.task_type)
            if index > 0:
                metadata["fallback_provider"] = provider_name
            if provider_failures:
                metadata["provider_failures"] = list(provider_failures)
            if cache_key:
                metadata["cache"] = {
                    "hit": False,
                    "source": "processor_response_cache",
                    "cache_key": cache_key,
                }
            result.metadata = metadata
            if cache_key:
                self._store_response_cache(
                    cache_key=cache_key,
                    result=result,
                    provider_name=provider_name,
                    request=resolved_request,
                    lane_name=lane_name,
                    lane_config=lane_config,
                    spec=spec,
                )
            self._record_usage(resolved_request, result)
            return result
        failed = ProcessorTaskResult(
            task_type=resolved_request.task_type,
            text="",
            session_id=resolved_request.session_id,
            returncode=1,
            stdout="",
            stderr=last_error or "no provider available",
            command=[],
            output_schema=resolved_request.output_schema,
            metadata={
                "lane": lane_name,
                "provider": "",
                "model": self._provider_model(provider_chain[0] if provider_chain else "", lane_name, lane_config, resolved_request),
                "reasoning_effort": self._provider_reasoning_effort(
                    provider_chain[0] if provider_chain else "",
                    lane_name,
                    lane_config,
                    resolved_request,
                    spec,
                ),
                "budget_tag": resolved_request.budget_tag or rule.budget_tag or resolved_request.task_type,
                "provider_failures": list(provider_failures),
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
