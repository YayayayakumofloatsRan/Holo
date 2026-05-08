from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .config import HostConfig, ProcessorLaneConfig, TaskRoutingConfig
from .models import CodexResult, ProcessorTaskRequest, ProcessorTaskResult, ProcessorUsageRecord

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
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated": True}
    if isinstance(payload, dict):
        prompt_tokens = int(payload.get("prompt_tokens", payload.get("input_tokens", 0)) or 0)
        completion_tokens = int(payload.get("completion_tokens", payload.get("output_tokens", 0)) or 0)
        total_tokens = int(payload.get("total_tokens", prompt_tokens + completion_tokens) or 0)
        estimated = bool(payload.get("estimated", False))
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated": estimated,
        }
    prompt_tokens = int(getattr(payload, "prompt_tokens", getattr(payload, "input_tokens", 0)) or 0)
    completion_tokens = int(getattr(payload, "completion_tokens", getattr(payload, "output_tokens", 0)) or 0)
    total_tokens = int(getattr(payload, "total_tokens", prompt_tokens + completion_tokens) or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated": False,
    }


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
        response = client.responses.create(
            model=request.model_override or lane_config.model,
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
                "model": request.model_override or lane_config.model,
                "reasoning_effort": request.reasoning_effort_override
                or lane_config.reasoning_effort
                or str(spec.get("default_reasoning_effort", "")),
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


class DeepSeekProvider(ProcessorProvider):
    name = "deepseek"

    capabilities = {
        "text": True,
        "json_output": True,
        "tool_call_protocol": "openai_chat_completions",
        "thinking_mode": True,
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
        return str(os.environ.get(env_name, "") or "").strip()

    def availability(self) -> dict[str, Any]:
        return {"available": True, "reason": "", "capabilities": dict(self.capabilities)}

    def supports_request(self, request: ProcessorTaskRequest) -> bool:
        return not bool(request.image_paths)

    def _payload(
        self,
        request: ProcessorTaskRequest,
        *,
        spec: dict[str, Any],
        lane_config: ProcessorLaneConfig,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model_override or lane_config.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": False,
        }
        max_tokens = request.max_output_tokens or lane_config.max_output_tokens or None
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        output_schema = str(request.output_schema or spec.get("output_schema", "plain_text"))
        if "json" in output_schema.lower():
            payload["response_format"] = {"type": "json_object"}
        return payload

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> str:
        choices = response.get("choices", [])
        if not choices:
            return ""
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message", {}) if isinstance(first, dict) else {}
        return str(message.get("content", "") or "").strip()

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
        url = f"{self._base_url(runner)}/chat/completions"
        payload = self._payload(request, spec=spec, lane_config=lane_config)
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
                "model": request.model_override or lane_config.model,
                "reasoning_effort": request.reasoning_effort_override
                or lane_config.reasoning_effort
                or str(spec.get("default_reasoning_effort", "")),
                "usage": usage,
                "duration_ms": duration_ms,
                "budget_tag": request.budget_tag,
                "capabilities": dict(self.capabilities),
            },
        )


class CodexRunner:
    def __init__(self, config: HostConfig, *, usage_recorder: Any | None = None):
        self.config = config
        self.usage_recorder = usage_recorder
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
            "openai_compatible",
        ):
            current = str(name or "").strip()
            if current and current not in chain:
                chain.append(current)
        if "codex_cli" not in chain:
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
        for index, provider_name in enumerate(provider_chain):
            provider = self._providers.get(provider_name)
            if provider is None:
                last_error = f"unknown provider: {provider_name}"
                continue
            availability = provider.availability()
            if not bool(availability.get("available", False)):
                last_error = str(availability.get("reason", f"{provider_name} unavailable"))
                continue
            if not provider.supports_request(resolved_request):
                last_error = f"{provider_name} does not support task request"
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
