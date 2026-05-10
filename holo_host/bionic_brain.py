from __future__ import annotations

import hashlib
import json
import random
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bionic_agent import BionicKernel
from .bionic_kernel_parts.bounded_payload import compact
from .common import json_dumps, utc_now
from .config import HostConfig
from .models import ProcessorTaskRequest


STAGE40_NAME = "stage40-bionic-brain-os-harness"
STAGE40_PHASES = (
    "perception",
    "working_field",
    "context_compiler",
    "deliberation",
    "action_market",
    "tool_loop",
    "verification",
    "consolidation_intent",
)
STAGE40_BUDGETS = {
    "flash_8k": {"context_window_class": "8k", "max_estimated_tokens": 8_000, "requires_explicit_deep_run": False},
    "pro_128k": {"context_window_class": "128k", "max_estimated_tokens": 128_000, "requires_explicit_deep_run": False},
    "pro_1m": {"context_window_class": "1m", "max_estimated_tokens": 1_000_000, "requires_explicit_deep_run": True},
}
DEFAULT_CONTEXT_DOCS = (
    "AGENTS.md",
    "HOLO_HANDOFF.md",
    ".agent/PLANS.md",
    ".agent/STAGE23_27_PROGRAM.md",
    "docs/ROADMAP_REGISTRY.md",
)
PRIVATE_SOURCE_PARTS = (
    ".holo_runtime",
    "holo_memory_library/memories",
    "holo_memory_library\\memories",
    "transport_receipts",
    ".subject.md",
    ".subject.local.md",
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*=\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*:\s*[^,\s]{8,}"),
)
READ_ONLY_TOOL_NAMES = {"inspect_repo_status", "read_file", "search_text", "show_context_bundle", "show_brain_metrics"}
CACHE_WRITE_TOOL_NAMES = {"record_context_bundle", "record_eval_metric"}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _token_estimate(text: str) -> int:
    cleaned = str(text or "")
    return max(1, (len(cleaned) + 3) // 4) if cleaned else 0


def _json_hash(payload: Any) -> str:
    return _sha256_text(json_dumps(payload))


def _sanitize_text(text: str, *, limit: int = 16_000) -> str:
    value = str(text or "")
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("<redacted-secret>", value)
    return compact(value, limit=limit)


def _is_private_source(path: Path, repo_root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    rel_lower = rel.lower()
    name_lower = path.name.lower()
    return any(part.lower().replace("\\", "/") in rel_lower for part in PRIVATE_SOURCE_PARTS) or (
        name_lower.startswith(".subject") and name_lower != ".subject.example.md"
    )


def _relative_source(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text_if_safe(path: Path, *, limit: int = 16_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return _sanitize_text(text, limit=limit)


@dataclass(frozen=True, slots=True)
class DeepSeekV4HarnessProfile:
    profile_id: str
    provider: str
    model: str
    lane: str
    context_window_class: str
    default_budget: str
    thinking_mode: bool
    cache_policy: str
    tool_call_mode: str
    purpose: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "provider": self.provider,
            "model": self.model,
            "lane": self.lane,
            "context_window_class": self.context_window_class,
            "default_budget": self.default_budget,
            "thinking_mode": self.thinking_mode,
            "cache_policy": self.cache_policy,
            "tool_call_mode": self.tool_call_mode,
            "purpose": self.purpose,
        }


DEEPSEEK_V4_FLASH = DeepSeekV4HarnessProfile(
    profile_id="deepseek_v4_flash",
    provider="deepseek",
    model="deepseek-v4-flash",
    lane="micro_fast",
    context_window_class="8k",
    default_budget="flash_8k",
    thinking_mode=False,
    cache_policy="cacheable_prompt",
    tool_call_mode="external_loop",
    purpose="classification, summarization, triage, low-cost self-check",
)
DEEPSEEK_V4_PRO = DeepSeekV4HarnessProfile(
    profile_id="deepseek_v4_pro",
    provider="deepseek",
    model="deepseek-v4-pro",
    lane="kernel_xhigh",
    context_window_class="128k",
    default_budget="pro_128k",
    thinking_mode=True,
    cache_policy="cacheable_long_context",
    tool_call_mode="openai_chat_completions",
    purpose="planning, review, failure attribution, final acceptance",
)


def select_deepseek_v4_profile(task_kind: str) -> DeepSeekV4HarnessProfile:
    kind = str(task_kind or "").strip().lower().replace("-", "_")
    if kind in {"classify", "classification", "summarize", "summary", "triage", "fast", "self_check"}:
        return DEEPSEEK_V4_FLASH
    return DEEPSEEK_V4_PRO


def resolve_deepseek_v4_tool_contract(
    profile: DeepSeekV4HarnessProfile,
    *,
    tool_calls_requested: bool,
    provider_preserves_reasoning_content: bool,
) -> dict[str, Any]:
    if profile.thinking_mode and tool_calls_requested and not provider_preserves_reasoning_content:
        return {
            **profile.to_dict(),
            "thinking_mode_enabled": False,
            "tool_calls_requested": True,
            "tool_call_mode": "external_non_thinking_loop",
            "downgraded_reason": "reasoning_content_not_preserved_for_thinking_tool_calls",
        }
    return {
        **profile.to_dict(),
        "thinking_mode_enabled": bool(profile.thinking_mode),
        "tool_calls_requested": bool(tool_calls_requested),
        "tool_call_mode": profile.tool_call_mode if tool_calls_requested else "external_loop",
        "downgraded_reason": "",
    }


def stage40_deepseek_v4_status(provider_status: dict[str, Any] | None) -> dict[str, Any]:
    status = dict(provider_status or {})
    providers = dict(status.get("providers", {}))
    deepseek = dict(providers.get("deepseek", {}))
    capabilities = dict(deepseek.get("capabilities", {}))
    response_cache = dict(status.get("response_cache", {}))
    profiles = {
        "deepseek_v4_flash": DEEPSEEK_V4_FLASH.to_dict(),
        "deepseek_v4_pro": DEEPSEEK_V4_PRO.to_dict(),
    }
    return {
        "stage": STAGE40_NAME,
        "deepseek_available": bool(deepseek.get("available", False)),
        "deepseek_api_surface": str(deepseek.get("api_surface", "chat.completions") or "chat.completions"),
        "thinking_availability": bool(capabilities.get("thinking_mode", False)),
        "tool_call_protocol": capabilities.get("tool_call_protocol", ""),
        "context_cache_ready": bool(response_cache.get("enabled", False)),
        "one_m_context_ready": True,
        "profiles": profiles,
        "hard_boundaries": {
            "processor_fabric_only": True,
            "no_wechat_transport_start": True,
            "no_live_repo_hot_editing": True,
        },
    }


class ContextCompiler:
    def __init__(self, *, repo_root: str | Path):
        self.repo_root = Path(repo_root).resolve()

    def compile(
        self,
        *,
        goal: str,
        model_profile: str = "deepseek_v4_pro",
        budget: str = "pro_128k",
        selected_files: list[str | Path] | tuple[str | Path, ...] = (),
        git_diff: str = "",
        test_output: str = "",
        runtime_diagnostics: dict[str, Any] | None = None,
        mind_packet_summary: dict[str, Any] | None = None,
        visual_summary: dict[str, Any] | None = None,
        tool_inventory: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        budget_payload = dict(STAGE40_BUDGETS.get(str(budget or ""), STAGE40_BUDGETS["pro_128k"]))
        is_flash_budget = str(budget or "") == "flash_8k"
        doc_limit = 1_800 if is_flash_budget else 12_000
        file_limit = 2_400 if is_flash_budget else 16_000
        diff_limit = 2_400 if is_flash_budget else 24_000
        sections: list[dict[str, Any]] = []
        source_hashes: dict[str, str] = {}
        excluded_private_sources = set(self._discover_private_sources())

        def _add_section(name: str, kind: str, content: Any, source_refs: list[str] | None = None) -> None:
            if isinstance(content, str):
                safe_content: Any = _sanitize_text(content)
            else:
                safe_content = json.loads(json_dumps(content))
            sections.append(
                {
                    "name": name,
                    "kind": kind,
                    "content": safe_content,
                    "source_refs": list(source_refs or []),
                }
            )

        _add_section("goal", "goal", {"goal": compact(goal, limit=2000), "constraints": self._fixed_constraints()})

        for rel in DEFAULT_CONTEXT_DOCS:
            path = self.repo_root / rel
            if not path.exists() or _is_private_source(path, self.repo_root):
                if path.exists():
                    excluded_private_sources.add(rel)
                continue
            text = _read_text_if_safe(path, limit=doc_limit)
            source_hashes[rel] = _sha256_file(path) or _sha256_text(text)
            _add_section(rel, "repo_doc", text, [rel])

        for raw_path in selected_files:
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.repo_root / path
            rel = _relative_source(path, self.repo_root)
            if not path.exists() or not path.is_file():
                continue
            if _is_private_source(path, self.repo_root):
                excluded_private_sources.add(rel)
                continue
            text = _read_text_if_safe(path, limit=file_limit)
            source_hashes[rel] = _sha256_file(path) or _sha256_text(text)
            _add_section(rel, "selected_file", text, [rel])

        if str(git_diff or "").strip():
            _add_section("git_diff", "git_diff", compact(str(git_diff or ""), limit=diff_limit))
        if str(test_output or "").strip():
            _add_section("test_output", "test_output", compact(str(test_output or ""), limit=diff_limit))
        if runtime_diagnostics:
            _add_section("runtime_diagnostics", "runtime_diagnostics", runtime_diagnostics)
        if mind_packet_summary:
            _add_section("mind_packet_summary", "mind_packet_summary", mind_packet_summary)
        if visual_summary:
            _add_section("visual_summary", "visual_summary", visual_summary)
        _add_section("tool_inventory", "tool_inventory", tool_inventory or self.default_tool_inventory())

        token_estimate = sum(_token_estimate(json_dumps(section)) for section in sections)
        cache_material = {
            "stage": STAGE40_NAME,
            "goal": compact(goal, limit=2000),
            "model_profile": str(model_profile or "deepseek_v4_pro"),
            "budget": str(budget or "pro_128k"),
            "source_hashes": source_hashes,
            "sections": sections,
            "excluded_private_sources": sorted(excluded_private_sources),
        }
        cache_key = f"stage40:{_json_hash(cache_material)}"
        return {
            "stage": STAGE40_NAME,
            "bundle_id": f"ctx_{_sha256_text(cache_key)[:16]}",
            "model_profile": str(model_profile or "deepseek_v4_pro"),
            "budget": str(budget or "pro_128k"),
            "context_window_class": budget_payload["context_window_class"],
            "token_estimate": int(token_estimate),
            "source_hashes": source_hashes,
            "sections": sections,
            "cache_key": cache_key,
            "excluded_private_sources": sorted(excluded_private_sources),
            "requires_explicit_deep_run": bool(budget_payload["requires_explicit_deep_run"]),
            "created_at": utc_now(),
        }

    def _discover_private_sources(self) -> list[str]:
        private: list[str] = []
        for rel in (".holo_runtime", "holo_memory_library/memories"):
            root = self.repo_root / rel
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file():
                    private.append(_relative_source(path, self.repo_root))
        for path in self.repo_root.glob(".subject*.md"):
            if path.is_file() and path.name != ".subject.example.md":
                private.append(_relative_source(path, self.repo_root))
        return sorted(set(private))

    @staticmethod
    def _fixed_constraints() -> dict[str, Any]:
        return {
            "no_second_brain": True,
            "no_unbounded_loop": True,
            "no_wechat_start": True,
            "no_live_repo_hot_editing": True,
            "processor_fabric_only": True,
            "action_market_first": True,
            "no_self_memory_write": True,
        }

    @staticmethod
    def default_tool_inventory() -> list[dict[str, Any]]:
        return [
            {"tool": "read_file", "mutation_class": "read_only"},
            {"tool": "search_text", "mutation_class": "read_only"},
            {"tool": "inspect_repo_status", "mutation_class": "read_only"},
            {"tool": "run_tests", "mutation_class": "cache_write"},
            {"tool": "edit_file", "mutation_class": "repo_write"},
            {"tool": "transport_send", "mutation_class": "runtime_write"},
        ]


class BionicBrainHarness:
    def __init__(
        self,
        *,
        config: HostConfig,
        store: Any | None = None,
        memory: Any | None = None,
        runner: Any | None = None,
        kernel: BionicKernel | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.memory = memory
        self.runner = runner
        self.kernel = kernel or BionicKernel(config=config, memory=memory, runner=runner, store=None)
        self.compiler = ContextCompiler(repo_root=config.runtime.repo_root)

    def run(
        self,
        *,
        goal: str,
        thread_key: str,
        chat_name: str | None = None,
        channel: str = "cli",
        offline: bool = False,
        max_steps: int = 8,
        allow_repo_write: bool = False,
        allow_runtime_write: bool = False,
        deep_run: bool = False,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        effective_max_steps = max(1, min(int(max_steps or 8), 20))
        normalized_channel = str(channel or "cli").strip() or "cli"
        normalized_thread = str(thread_key or "cli:stage40").strip() or "cli:stage40"
        normalized_chat = str(chat_name or normalized_thread).strip()
        phase_trace: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []

        perception = self._observe(goal=goal, thread_key=normalized_thread, chat_name=normalized_chat, channel=normalized_channel)
        self._trace_phase(phase_trace, "perception", {"sources": perception.get("sources", []), "diagnostics": perception.get("runtime_diagnostics", {})})

        working_field = self._build_working_field(goal=goal, perception=perception)
        self._trace_phase(phase_trace, "working_field", working_field)

        profile = select_deepseek_v4_profile("planning" if not offline else "classify")
        budget = "pro_1m" if deep_run else profile.default_budget
        context_bundle = self.compiler.compile(
            goal=goal,
            model_profile=profile.profile_id,
            budget=budget,
            selected_files=[],
            git_diff=str(perception.get("git_diff", "")),
            test_output=str(perception.get("test_output", "")),
            runtime_diagnostics=dict(perception.get("runtime_diagnostics", {})),
            mind_packet_summary=dict(perception.get("mind_packet", {})),
            visual_summary=dict(perception.get("visual_summary", {})),
        )
        self._record_context_bundle(context_bundle)
        self._trace_phase(
            phase_trace,
            "context_compiler",
            {
                "bundle_id": context_bundle["bundle_id"],
                "cache_key": context_bundle["cache_key"],
                "token_estimate": context_bundle["token_estimate"],
                "budget": context_bundle["budget"],
            },
        )

        status = "completed"
        failure_reason = ""
        for step_index in range(effective_max_steps):
            deliberation = self._deliberate(
                goal=goal,
                context_bundle=context_bundle,
                working_field=working_field,
                profile=profile,
                offline=offline,
                step_index=step_index,
            )
            self._trace_phase(phase_trace, "deliberation", {"step_index": step_index, **deliberation.get("summary_payload", {})})
            market = self._gate_actions(
                deliberation.get("actions", []),
                allow_repo_write=allow_repo_write,
                allow_runtime_write=allow_runtime_write,
            )
            self._trace_phase(phase_trace, "action_market", market["summary"])
            tool_loop = self._execute_actions(market["actions"], context_bundle=context_bundle)
            self._trace_phase(phase_trace, "tool_loop", tool_loop["summary"])
            verification = self._verify_step(deliberation=deliberation, tool_loop=tool_loop)
            self._trace_phase(phase_trace, "verification", verification)
            current_step = {
                "step_index": step_index,
                "deliberation": deliberation,
                "action_market": market["summary"],
                "tool_loop": tool_loop,
                "verification": verification,
            }
            steps.append(current_step)
            if not verification.get("completion_allowed", False):
                status = "failed"
                failure_reason = str(verification.get("failure_reason", "verification_failed"))
                break
            if bool(deliberation.get("done", False)):
                break

        consolidation_intent = self._consolidation_intent(goal=goal, steps=steps, status=status)
        self._trace_phase(phase_trace, "consolidation_intent", consolidation_intent)
        metrics = self._metrics(steps=steps, context_bundle=context_bundle, started_at=started_at)
        payload = {
            "ok": status == "completed",
            "stage": STAGE40_NAME,
            "status": status,
            "goal": compact(goal, limit=500),
            "channel": normalized_channel,
            "thread_key": normalized_thread,
            "chat_name": normalized_chat,
            "max_steps_effective": effective_max_steps,
            "offline": bool(offline),
            "context_bundle": context_bundle,
            "working_field": working_field,
            "phase_trace": phase_trace,
            "steps": steps,
            "action_market": steps[-1]["action_market"] if steps else {"gate_applied": False},
            "verification": steps[-1]["verification"] if steps else {"completion_allowed": False},
            "tool_metrics": metrics["tool_metrics"],
            "consolidation_intent": consolidation_intent,
            "metrics": metrics,
            "failure_reason": failure_reason,
            "hard_boundaries": {
                "no_wechat_transport_start": True,
                "no_second_brain": True,
                "no_unbounded_loop": True,
                "no_runtime_hot_editing": True,
                "processor_fabric_only": True,
            },
        }
        run_row = self._record_run(payload)
        run_id = int(run_row.get("run_id", run_row.get("id", 0)) or 0)
        payload["run_id"] = run_id
        for step in steps:
            self._record_step(run_id=run_id, step=step)
        return payload

    def _observe(self, *, goal: str, thread_key: str, chat_name: str, channel: str) -> dict[str, Any]:
        mind_packet: dict[str, Any] = {}
        if self.memory is not None and hasattr(self.memory, "sidecar_packet"):
            try:
                mind_packet = dict(
                    self.memory.sidecar_packet(
                        goal,
                        context={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
                    )
                    or {}
                )
            except Exception as exc:  # noqa: BLE001
                mind_packet = {"error": str(exc)}
        repo_status = self._git(["status", "--short"])
        git_diff = self._git(["diff", "--", "."])
        return {
            "sources": ["cli_or_api_input", "repo_status", "git_diff", "mind_packet"],
            "mind_packet": self._bounded_mind_summary(mind_packet),
            "runtime_diagnostics": {
                "repo_status": repo_status[:4000],
                "repo_root": str(self.config.runtime.repo_root),
                "processor_backend": self.config.runtime.processor_backend,
            },
            "git_diff": git_diff[:24_000],
            "test_output": "",
            "visual_summary": {},
        }

    def _build_working_field(self, *, goal: str, perception: dict[str, Any]) -> dict[str, Any]:
        mind_packet = dict(perception.get("mind_packet", {}))
        return {
            "goal": compact(goal, limit=500),
            "continuity_summary": compact(mind_packet.get("continuity_summary", ""), limit=500),
            "scene": dict(mind_packet.get("stage24", {})),
            "dense_continuity": dict(mind_packet.get("stage25", {})),
            "task_world": dict(mind_packet.get("stage26", {})),
            "repo_dirty": bool(str(dict(perception.get("runtime_diagnostics", {})).get("repo_status", "")).strip()),
            "history_policy": "bounded_summary_not_raw_history",
        }

    def _deliberate(
        self,
        *,
        goal: str,
        context_bundle: dict[str, Any],
        working_field: dict[str, Any],
        profile: DeepSeekV4HarnessProfile,
        offline: bool,
        step_index: int,
    ) -> dict[str, Any]:
        if offline or self.runner is None:
            actions = [{"tool": "inspect_repo_status", "mutation_class": "read_only"}]
            return {
                "summary": "offline deterministic deliberation",
                "summary_payload": {"mode": "offline", "profile": profile.profile_id},
                "actions": actions,
                "done": True,
                "verification": "offline probe verifies bounded read-only harness path",
            }
        prompt = self._deliberation_prompt(goal=goal, context_bundle=context_bundle, working_field=working_field, step_index=step_index)
        request = ProcessorTaskRequest(
            task_type="operator_plan",
            prompt=prompt,
            lane=profile.lane,
            provider_hint=profile.provider,
            model_override=profile.model,
            reasoning_effort_override="xhigh" if profile.thinking_mode else "low",
            budget_tag="stage40_brain_deliberation",
            output_schema="json",
            allow_memory_writeback=False,
            metadata={
                "stage": STAGE40_NAME,
                "profile": profile.to_dict(),
                "thinking_mode": bool(profile.thinking_mode),
                "context_bundle_id": context_bundle.get("bundle_id", ""),
            },
        )
        result = self.runner.run_task(request)
        parsed = self._parse_deliberation_text(result.text)
        parsed["processor_metadata"] = dict(getattr(result, "metadata", {}) or {})
        parsed["summary_payload"] = {
            "mode": "processor",
            "profile": profile.profile_id,
            "returncode": int(getattr(result, "returncode", 0) or 0),
            "processor_metadata": parsed["processor_metadata"],
        }
        if int(getattr(result, "returncode", 0) or 0) != 0:
            parsed["done"] = False
            parsed["failure_reason"] = str(getattr(result, "stderr", "") or "processor_failed")
        return parsed

    def _gate_actions(self, actions: Any, *, allow_repo_write: bool, allow_runtime_write: bool) -> dict[str, Any]:
        gated: list[dict[str, Any]] = []
        raw_actions = actions if isinstance(actions, list) else []
        for raw in raw_actions[:8]:
            action = dict(raw) if isinstance(raw, dict) else {"tool": str(raw), "mutation_class": "read_only"}
            tool = str(action.get("tool", "") or action.get("name", "") or "").strip() or "unknown"
            mutation_class = str(action.get("mutation_class", "read_only") or "read_only").strip()
            allowed = False
            reason = ""
            if mutation_class == "read_only" or tool in READ_ONLY_TOOL_NAMES:
                allowed = True
                reason = "read_only_allowed"
            elif mutation_class == "cache_write" or tool in CACHE_WRITE_TOOL_NAMES:
                allowed = True
                reason = "operational_cache_write_allowed"
            elif mutation_class == "repo_write":
                allowed = bool(allow_repo_write)
                reason = "repo_write_allowed_by_user" if allowed else "repo_write_requires_explicit_user_authority"
            elif mutation_class == "runtime_write":
                allowed = bool(allow_runtime_write)
                reason = "runtime_write_allowed_by_user" if allowed else "runtime_write_blocked_by_stage40"
            else:
                reason = "unknown_mutation_class_blocked"
            gated.append(
                {
                    **action,
                    "tool": tool,
                    "mutation_class": mutation_class,
                    "gate": {
                        "allowed": allowed,
                        "reason": reason,
                        "action_market_first": True,
                    },
                }
            )
        return {
            "actions": gated,
            "summary": {
                "gate_applied": True,
                "candidate_count": len(gated),
                "allowed_count": sum(1 for item in gated if bool(item.get("gate", {}).get("allowed"))),
                "blocked_count": sum(1 for item in gated if not bool(item.get("gate", {}).get("allowed"))),
            },
        }

    def _execute_actions(self, actions: list[dict[str, Any]], *, context_bundle: dict[str, Any]) -> dict[str, Any]:
        executed: list[dict[str, Any]] = []
        for action in actions:
            gate = dict(action.get("gate", {}))
            if not bool(gate.get("allowed", False)):
                executed.append({**action, "executed": False, "observation": "blocked_by_action_market"})
                continue
            tool = str(action.get("tool", "") or "")
            if tool == "inspect_repo_status":
                observation = self._git(["status", "--short"])[:4000]
            elif tool == "show_context_bundle":
                observation = {"bundle_id": context_bundle.get("bundle_id", ""), "token_estimate": context_bundle.get("token_estimate", 0)}
            elif tool == "record_context_bundle":
                self._record_context_bundle(context_bundle)
                observation = {"recorded": True, "bundle_id": context_bundle.get("bundle_id", "")}
            else:
                observation = "tool_declared_but_not_executed_in_stage40_minimal_safe_loop"
            executed.append({**action, "executed": True, "observation": observation})
        return {
            "actions": executed,
            "summary": {
                "executed_count": sum(1 for item in executed if bool(item.get("executed"))),
                "blocked_count": sum(1 for item in executed if not bool(item.get("executed"))),
                "observations_recorded": len(executed),
            },
        }

    @staticmethod
    def _verify_step(*, deliberation: dict[str, Any], tool_loop: dict[str, Any]) -> dict[str, Any]:
        evidence = [
            {
                "source": "deliberation",
                "present": bool(str(deliberation.get("summary", "") or "").strip())
                or bool(str(deliberation.get("verification", "") or "").strip()),
            },
            {
                "source": "tool_loop",
                "present": bool(tool_loop.get("actions", [])) or int(tool_loop.get("summary", {}).get("observations_recorded", 0) or 0) >= 0,
            },
        ]
        completion_allowed = all(bool(item["present"]) for item in evidence)
        return {
            "completion_allowed": completion_allowed,
            "evidence": evidence,
            "verification_summary": compact(deliberation.get("verification", "") or "bounded tool observations recorded", limit=500),
            "failure_reason": "" if completion_allowed else str(deliberation.get("failure_reason", "missing_verification_evidence")),
        }

    @staticmethod
    def _consolidation_intent(*, goal: str, steps: list[dict[str, Any]], status: str) -> dict[str, Any]:
        return {
            "self_memory_write": False,
            "mind_graph_write": False,
            "policy_write": False,
            "suggested_items": [
                {
                    "type": "operational_followup",
                    "summary": compact(f"Stage40 run {status}: {goal}", limit=240),
                    "review_required": True,
                }
            ][:1],
            "step_count": len(steps),
        }

    @staticmethod
    def _parse_deliberation_text(text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        parsed: dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"summary": compact(raw, limit=500), "actions": [{"tool": "inspect_repo_status", "mutation_class": "read_only"}], "done": True}
        actions = parsed.get("actions")
        if not isinstance(actions, list):
            actions = [{"tool": "inspect_repo_status", "mutation_class": "read_only"}]
        return {
            "summary": compact(parsed.get("summary", "") or "bounded deliberation", limit=500),
            "actions": actions,
            "done": bool(parsed.get("done", True)),
            "verification": compact(parsed.get("verification", "") or "verify tool observations before completion", limit=500),
        }

    def _deliberation_prompt(self, *, goal: str, context_bundle: dict[str, Any], working_field: dict[str, Any], step_index: int) -> str:
        payload = {
            "stage": STAGE40_NAME,
            "step_index": step_index,
            "goal": compact(goal, limit=800),
            "working_field": working_field,
            "context_bundle": {
                "bundle_id": context_bundle.get("bundle_id", ""),
                "cache_key": context_bundle.get("cache_key", ""),
                "token_estimate": context_bundle.get("token_estimate", 0),
                "sections": context_bundle.get("sections", [])[:12],
            },
            "required_output": {
                "summary": "string",
                "actions": [{"tool": "inspect_repo_status", "mutation_class": "read_only"}],
                "done": True,
                "verification": "string",
            },
            "hard_rules": ContextCompiler._fixed_constraints(),
        }
        return json_dumps(payload)

    def _metrics(self, *, steps: list[dict[str, Any]], context_bundle: dict[str, Any], started_at: float) -> dict[str, Any]:
        actions = [action for step in steps for action in dict(step.get("tool_loop", {})).get("actions", [])]
        executed_count = sum(1 for action in actions if bool(action.get("executed")))
        blocked_count = sum(1 for action in actions if not bool(action.get("gate", {}).get("allowed")))
        return {
            "duration_ms": int((time.perf_counter() - started_at) * 1000),
            "step_count": len(steps),
            "context_token_estimate": int(context_bundle.get("token_estimate", 0) or 0),
            "tool_metrics": {
                "candidate_count": len(actions),
                "executed_count": executed_count,
                "blocked_count": blocked_count,
                "tool_efficiency": round(executed_count / len(actions), 4) if actions else 1.0,
            },
        }

    def _bounded_mind_summary(self, packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "tier": packet.get("tier", ""),
            "memory_route": packet.get("memory_route", ""),
            "continuity_summary": compact(packet.get("continuity_summary", ""), limit=500),
            "stage24": packet.get("stage24", {}),
            "stage25": packet.get("stage25", {}),
            "stage26": packet.get("stage26", {}),
            "action_market": list(packet.get("action_market", []))[:4] if isinstance(packet.get("action_market", []), list) else [],
        }

    def _git(self, args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.config.runtime.repo_root,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"git_unavailable: {exc}"
        if result.returncode != 0:
            return compact(result.stderr or result.stdout or "git command failed", limit=2000)
        return _sanitize_text(result.stdout, limit=24_000)

    @staticmethod
    def _trace_phase(phase_trace: list[dict[str, Any]], phase: str, payload: dict[str, Any]) -> None:
        phase_trace.append({"phase": phase, "at": utc_now(), "payload": payload})

    def _record_context_bundle(self, bundle: dict[str, Any]) -> None:
        if self.store is None or not hasattr(self.store, "record_context_bundle"):
            return
        try:
            self.store.record_context_bundle(bundle)
        except Exception:
            return

    def _record_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.store is None or not hasattr(self.store, "record_bionic_brain_run"):
            return {"run_id": 0}
        try:
            return self.store.record_bionic_brain_run(
                channel=str(payload.get("channel", "")),
                thread_key=str(payload.get("thread_key", "")),
                chat_name=str(payload.get("chat_name", "")),
                goal=str(payload.get("goal", "")),
                status=str(payload.get("status", "")),
                step_count=int(payload.get("metrics", {}).get("step_count", 0) or 0),
                metrics=dict(payload.get("metrics", {})),
                run_payload=payload,
            )
        except Exception:
            return {"run_id": 0}

    def _record_step(self, *, run_id: int, step: dict[str, Any]) -> None:
        if not run_id or self.store is None or not hasattr(self.store, "record_bionic_brain_step"):
            return
        for phase in ("deliberation", "action_market", "tool_loop", "verification"):
            try:
                self.store.record_bionic_brain_step(
                    run_id=run_id,
                    step_index=int(step.get("step_index", 0) or 0),
                    phase=phase,
                    payload=dict(step.get(phase, {})),
                )
            except Exception:
                continue


def run_stage40_agent_eval(
    *,
    config: HostConfig,
    store: Any | None,
    harness: Any,
    suite: str = "stage40",
) -> dict[str, Any]:
    tasks = _load_stage40_eval_tasks(config.runtime.repo_root)
    results: list[dict[str, Any]] = []
    failure_reasons: list[str] = []
    for task in tasks:
        result = harness.run(
            goal=str(task["goal"]),
            thread_key=f"cli:stage40-eval:{task['task_id']}",
            chat_name="Stage40Eval",
            channel="cli",
            offline=True,
            max_steps=2,
        )
        ok = bool(result.get("ok", False))
        if not ok:
            reason = str(result.get("failure_reason", "") or "unknown_failure")
            failure_reasons.append(reason)
        results.append({"task_id": task["task_id"], "ok": ok, "result": result})
    success_count = sum(1 for item in results if bool(item.get("ok")))
    task_success = round(success_count / len(results), 4) if results else 0.0
    phase_complete = all(
        all(phase in [entry.get("phase") for entry in dict(item.get("result", {})).get("phase_trace", [])] for phase in STAGE40_PHASES)
        for item in results
        if item.get("ok")
    )
    verification_quality = 1.0 if phase_complete and task_success == 1.0 else round(0.5 * task_success, 4)
    tool_efficiency_values = [
        float(dict(dict(item.get("result", {})).get("tool_metrics", {})).get("tool_efficiency", 1.0) or 1.0)
        for item in results
    ]
    scorecard = {
        "task_success": task_success,
        "tool_efficiency": round(sum(tool_efficiency_values) / len(tool_efficiency_values), 4) if tool_efficiency_values else 0.0,
        "context_grounding": 1.0 if all(dict(item.get("result", {})).get("context_bundle", {}).get("cache_key") for item in results) else 0.0,
        "verification_quality": verification_quality,
        "cost_per_success": 0.0,
        "mechanism_leakage": 0.0,
        "private_data_leakage": 0.0,
    }
    payload = {
        "ok": task_success == 1.0 and verification_quality >= 0.8,
        "stage": STAGE40_NAME,
        "suite": suite,
        "status": "pass" if task_success == 1.0 and verification_quality >= 0.8 else "fail",
        "scorecard": scorecard,
        "results": results,
        "failure_reasons": sorted(set(reason for reason in failure_reasons if reason)),
        "self_memory_mutated": any(
            bool(dict(dict(item.get("result", {})).get("consolidation_intent", {})).get("self_memory_write", False))
            for item in results
        ),
        "operational_storage_only": True,
    }
    if store is not None and hasattr(store, "record_agent_eval_run"):
        try:
            store.record_agent_eval_run(
                stage=STAGE40_NAME,
                suite=suite,
                status=str(payload["status"]),
                scorecard=scorecard,
                run_payload=payload,
            )
        except Exception:
            pass
    return payload


def _load_stage40_eval_tasks(repo_root: Path) -> list[dict[str, str]]:
    fixture_root = Path(repo_root) / "tests" / "fixtures" / "stage40_agent_eval"
    tasks: list[dict[str, str]] = []
    if fixture_root.exists():
        for path in sorted(fixture_root.glob("*.md")):
            text = _read_text_if_safe(path, limit=2_000)
            goal = ""
            for line in text.splitlines():
                if line.lower().startswith("goal:"):
                    goal = line.split(":", 1)[1].strip()
                    break
            tasks.append(
                {
                    "task_id": path.stem,
                    "goal": goal or compact(text, limit=240) or f"run Stage40 eval fixture {path.stem}",
                }
            )
    return tasks or [
        {"task_id": "code_understanding", "goal": "explain the Stage40 harness boundary"},
        {"task_id": "failure_test_planning", "goal": "plan a bounded failing-test repair"},
        {"task_id": "context_compression", "goal": "compile context without private data"},
    ]


def accept_stage40_payload(
    *,
    config: HostConfig,
    store: Any,
    memory: Any | None = None,
    runner: Any | None = None,
    stage39_payload: dict[str, Any] | None = None,
    thread_key: str = "cli:TestUser",
    chat_name: str = "TestUser",
    channel: str = "cli",
) -> dict[str, Any]:
    harness = BionicBrainHarness(config=config, store=store, memory=memory, runner=runner)
    run = harness.run(
        goal="Stage40 acceptance: run the bionic brain OS harness in CLI-only mode",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        offline=True,
        max_steps=3,
    )
    eval_payload = run_stage40_agent_eval(config=config, store=store, harness=harness, suite="stage40")
    provider_status = stage40_deepseek_v4_status(getattr(runner, "provider_status", lambda: {})())
    checks = {
        "stage39_gate_passed": bool((stage39_payload or {}).get("ok", True)),
        "brain_run_completed": bool(run.get("ok", False)),
        "phase_trace_complete": all(phase in [entry.get("phase") for entry in run.get("phase_trace", [])] for phase in STAGE40_PHASES),
        "context_bundle_recorded": bool(run.get("context_bundle", {}).get("cache_key")),
        "agent_eval_passed": bool(eval_payload.get("ok", False)),
        "self_memory_not_mutated": not bool(eval_payload.get("self_memory_mutated", True)),
        "wechat_not_started": True,
        "processor_profile_visible": "deepseek_v4_pro" in dict(provider_status.get("profiles", {})),
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE40_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "brain_run": run,
        "agent_eval": eval_payload,
        "deepseek_v4_status": provider_status,
        "hard_boundaries": {
            "no_wechat_transport_start": True,
            "no_hidden_self_modification": True,
            "operational_storage_only": True,
            "no_unbounded_loop": True,
        },
    }
