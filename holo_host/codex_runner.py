from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import HostConfig
from .models import CodexResult, ProcessorTaskRequest, ProcessorTaskResult

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
}


class CodexRunner:
    def __init__(self, config: HostConfig):
        self.config = config

    @staticmethod
    def supported_tasks() -> list[dict[str, Any]]:
        return [{"task_type": task_type, **dict(payload)} for task_type, payload in PROCESSOR_TASK_SPECS.items()]

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

    def run(
        self,
        prompt: str,
        *,
        session_id: str = "",
        model_override: str = "",
        reasoning_effort_override: str = "",
    ) -> CodexResult:
        result = self.run_task(
            ProcessorTaskRequest(
                task_type="reply",
                prompt=prompt,
                session_id=session_id,
                model_override=model_override,
                reasoning_effort_override=reasoning_effort_override,
            )
        )
        return result.to_codex_result()

    def run_task(self, request: ProcessorTaskRequest) -> ProcessorTaskResult:
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=False) as handle:
            output_path = Path(handle.name)
        spec = dict(PROCESSOR_TASK_SPECS.get(request.task_type, PROCESSOR_TASK_SPECS["reply"]))

        def run_once(*, resumed: bool) -> tuple[subprocess.CompletedProcess[str], list[str]]:
            prefix = self._codex_invocation_prefix()
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
            command = self._apply_runtime_options(
                command,
                resumed=resumed,
                model_override=request.model_override,
                reasoning_effort_override=request.reasoning_effort_override or str(spec.get("default_reasoning_effort", "")),
            )
            if output_path.exists():
                output_path.write_text("", encoding="utf-8")
            workspace_path = str(request.metadata.get("workspace_path", "") or "").strip()
            cwd = self.config.runtime.repo_root
            if request.workspace_mode == "shadow_write" and workspace_path:
                shadow_path = Path(workspace_path)
                if shadow_path.exists():
                    cwd = shadow_path
            proc = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds or self.config.runtime.codex_timeout_seconds,
            )
            return proc, command

        resumed = bool(request.session_id and self.config.runtime.resume_sessions and bool(spec.get("allow_session_resume", True)))
        proc, command = run_once(resumed=resumed)
        effective_session_id = request.session_id
        if resumed and proc.returncode != 0 and self._is_missing_resume_rollout(proc.stdout, proc.stderr):
            proc, command = run_once(resumed=False)
            effective_session_id = ""

        reply_text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        new_session_id = self._parse_thread_id(proc.stdout) or effective_session_id
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
            },
        )

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
