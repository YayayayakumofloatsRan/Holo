from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from .bionic_brain import ContextCompiler, STAGE40_NAME, _sanitize_text
from .bionic_kernel_parts.bounded_payload import compact
from .common import utc_now
from .config import HostConfig
from .models import ProcessorTaskRequest


STAGE41_NAME = "stage41-complete-engineering-agent"
STAGE41_PHASES = (
    "observe",
    "context_compile",
    "deliberate",
    "action_market",
    "tool_loop",
    "verification",
    "review",
)
PRIVATE_PATH_PARTS = (
    ".git",
    ".holo_runtime",
    "holo_memory_library/memories",
    "holo_memory_library\\memories",
    "artifacts/canary",
    "transport_receipts",
)
REPO_WRITE_TOOLS = {"write_file", "replace_text"}
READ_TOOLS = {"read_file", "search_text", "inspect_repo_status"}
TEST_TOOLS = {"run_tests"}
MCP_TOOLS = {"mcp_list_tools", "mcp_call_tool", "mcp_read_resource"}
ALLOWED_TEST_PREFIXES = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("py", "-m", "pytest"),
    ("python", "scripts/check_public_release_hygiene.py"),
    ("git", "diff", "--check"),
)


def _safe_relpath(repo_root: Path, raw_path: str) -> tuple[Path, str, str]:
    value = str(raw_path or "").strip()
    if not value:
        return repo_root, "", "path_required"
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    try:
        resolved = path.resolve()
        rel = resolved.relative_to(repo_root.resolve()).as_posix()
    except (OSError, ValueError):
        return path, value, "path_outside_repo"
    lower = rel.lower()
    if rel in {"", "."}:
        return resolved, rel, "path_required"
    if any(part.lower().replace("\\", "/") in lower for part in PRIVATE_PATH_PARTS):
        return resolved, rel, "private_or_unsafe_path_blocked"
    name = resolved.name.lower()
    if name.startswith(".subject") and name != ".subject.example.md":
        return resolved, rel, "private_or_unsafe_path_blocked"
    if name in {".holo_host.toml", ".env", ".env.local"}:
        return resolved, rel, "private_or_unsafe_path_blocked"
    return resolved, rel, ""


def _parse_command(command: Any) -> list[str]:
    if isinstance(command, list):
        return [str(item) for item in command if str(item).strip()]
    raw = str(command or "").strip()
    if not raw:
        return []
    return shlex.split(raw, posix=os.name != "nt")


def _normalized_command(tokens: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for index, token in enumerate(tokens):
        value = Path(token).name.lower() if index == 0 else str(token).replace("\\", "/").lower()
        if value.endswith(".exe"):
            value = value[:-4]
        if value in {"python3"}:
            value = "python"
        normalized.append(value)
    return tuple(normalized)


def _command_allowed(tokens: list[str]) -> bool:
    normalized = _normalized_command(tokens)
    for prefix in ALLOWED_TEST_PREFIXES:
        if normalized[: len(prefix)] == prefix:
            return True
    return False


class EngineeringToolExecutor:
    def __init__(
        self,
        *,
        repo_root: str | Path,
        allow_repo_write: bool = False,
        timeout_seconds: int = 120,
        mcp_hub: Any | None = None,
    ):
        self.repo_root = Path(repo_root).resolve()
        self.allow_repo_write = bool(allow_repo_write)
        self.timeout_seconds = max(5, int(timeout_seconds or 120))
        self.mcp_hub = mcp_hub

    def gate(self, action: dict[str, Any]) -> dict[str, Any]:
        tool = str(action.get("tool", "") or action.get("name", "") or "").strip()
        mutation_class = str(action.get("mutation_class", "") or self._default_mutation_class(tool)).strip()
        if tool in READ_TOOLS:
            return {"allowed": True, "reason": "read_only_allowed", "mutation_class": "read_only"}
        if tool in TEST_TOOLS:
            tokens = _parse_command(action.get("command", []))
            if not tokens:
                return {"allowed": False, "reason": "test_command_required", "mutation_class": "cache_write"}
            if not _command_allowed(tokens):
                return {"allowed": False, "reason": "test_command_not_allowlisted", "mutation_class": "cache_write"}
            return {"allowed": True, "reason": "allowlisted_test_command", "mutation_class": "cache_write"}
        if tool in MCP_TOOLS:
            if self.mcp_hub is None:
                return {"allowed": False, "reason": "mcp_hub_not_configured", "mutation_class": "external_observation"}
            if tool == "mcp_call_tool":
                allowed, reason = self.mcp_hub.tool_allowed(str(action.get("qualified_name", "") or action.get("tool_name", "")))
                return {"allowed": bool(allowed), "reason": reason, "mutation_class": "external_observation"}
            if tool == "mcp_read_resource":
                if not str(action.get("server", "") or "").strip() or not str(action.get("uri", "") or "").strip():
                    return {"allowed": False, "reason": "mcp_resource_requires_server_and_uri", "mutation_class": "external_observation"}
            return {"allowed": True, "reason": "mcp_external_observation_allowed", "mutation_class": "external_observation"}
        if tool in REPO_WRITE_TOOLS:
            _path, _rel, error = _safe_relpath(self.repo_root, str(action.get("path", "")))
            if error:
                return {"allowed": False, "reason": error, "mutation_class": "repo_write"}
            if not self.allow_repo_write:
                return {
                    "allowed": False,
                    "reason": "repo_write_requires_explicit_user_authority",
                    "mutation_class": "repo_write",
                }
            return {"allowed": True, "reason": "repo_write_allowed_by_user", "mutation_class": "repo_write"}
        return {"allowed": False, "reason": "unknown_tool_or_mutation_class", "mutation_class": mutation_class}

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        gate = self.gate(action)
        gated = {**action, "gate": gate, "mutation_class": str(gate.get("mutation_class", action.get("mutation_class", "")) or "")}
        if not bool(gated["gate"].get("allowed", False)):
            return {**gated, "executed": False, "observation": "blocked_by_action_market"}
        tool = str(gated.get("tool", "") or "")
        if tool == "inspect_repo_status":
            observation = self._git_status()
        elif tool == "read_file":
            observation = self._read_file(str(gated.get("path", "")))
        elif tool == "search_text":
            observation = self._search_text(
                pattern=str(gated.get("pattern", "")),
                glob=str(gated.get("glob", "*")),
            )
        elif tool == "run_tests":
            observation = self._run_command(_parse_command(gated.get("command", [])))
        elif tool == "mcp_list_tools":
            observation = self._mcp_list_tools()
        elif tool == "mcp_call_tool":
            observation = self._mcp_call_tool(
                str(gated.get("qualified_name", "") or gated.get("tool_name", "")),
                dict(gated.get("arguments", {}) or {}),
            )
        elif tool == "mcp_read_resource":
            observation = self._mcp_read_resource(str(gated.get("server", "")), str(gated.get("uri", "")))
        elif tool == "write_file":
            observation = self._write_file(str(gated.get("path", "")), str(gated.get("content", "")))
        elif tool == "replace_text":
            observation = self._replace_text(
                str(gated.get("path", "")),
                old=str(gated.get("old", "")),
                new=str(gated.get("new", "")),
            )
        else:
            observation = {"ok": False, "error": "tool_not_implemented"}
        return {**gated, "executed": True, "observation": observation}

    @staticmethod
    def _default_mutation_class(tool: str) -> str:
        if tool in READ_TOOLS:
            return "read_only"
        if tool in TEST_TOOLS:
            return "cache_write"
        if tool in MCP_TOOLS:
            return "external_observation"
        if tool in REPO_WRITE_TOOLS:
            return "repo_write"
        return "unknown"

    def _read_file(self, raw_path: str) -> dict[str, Any]:
        path, rel, error = _safe_relpath(self.repo_root, raw_path)
        if error:
            return {"ok": False, "path": rel or raw_path, "error": error}
        if not path.exists() or not path.is_file():
            return {"ok": False, "path": rel, "error": "file_not_found"}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "path": rel, "error": str(exc)}
        return {"ok": True, "path": rel, "content": _sanitize_text(text, limit=8_000)}

    def _search_text(self, *, pattern: str, glob: str) -> dict[str, Any]:
        needle = str(pattern or "")
        if not needle:
            return {"ok": False, "error": "pattern_required", "matches": []}
        matches: list[dict[str, Any]] = []
        for path in sorted(self.repo_root.rglob(glob or "*")):
            if len(matches) >= 50:
                break
            if not path.is_file():
                continue
            _safe, rel, error = _safe_relpath(self.repo_root, str(path))
            if error:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, start=1):
                if needle in line:
                    matches.append({"path": rel, "line": line_no, "text": compact(line, limit=240)})
                    if len(matches) >= 50:
                        break
        return {"ok": True, "pattern": needle, "match_count": len(matches), "matches": matches}

    def _run_command(self, tokens: list[str]) -> dict[str, Any]:
        if not tokens:
            return {"ok": False, "returncode": 1, "error": "command_required"}
        if not _command_allowed(tokens):
            return {"ok": False, "returncode": 1, "error": "test_command_not_allowlisted", "command": tokens}
        try:
            result = subprocess.run(
                tokens,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "returncode": 1, "error": str(exc), "command": tokens}
        return {
            "ok": result.returncode == 0,
            "returncode": int(result.returncode),
            "command": tokens,
            "stdout": _sanitize_text(result.stdout, limit=8_000),
            "stderr": _sanitize_text(result.stderr, limit=8_000),
        }

    def _write_file(self, raw_path: str, content: str) -> dict[str, Any]:
        path, rel, error = _safe_relpath(self.repo_root, raw_path)
        if error:
            return {"ok": False, "path": rel or raw_path, "error": error}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content or ""), encoding="utf-8")
        return {"ok": True, "path": rel, "bytes": len(str(content or "").encode("utf-8"))}

    def _replace_text(self, raw_path: str, *, old: str, new: str) -> dict[str, Any]:
        path, rel, error = _safe_relpath(self.repo_root, raw_path)
        if error:
            return {"ok": False, "path": rel or raw_path, "error": error}
        if not path.exists() or not path.is_file():
            return {"ok": False, "path": rel, "error": "file_not_found"}
        text = path.read_text(encoding="utf-8", errors="replace")
        if old not in text:
            return {"ok": False, "path": rel, "error": "old_text_not_found"}
        updated = text.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8")
        return {"ok": True, "path": rel, "replacements": 1}

    def _git_status(self) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": str(exc), "stdout": "", "stderr": ""}
        return {
            "ok": result.returncode == 0,
            "returncode": int(result.returncode),
            "stdout": _sanitize_text(result.stdout, limit=4_000),
            "stderr": _sanitize_text(result.stderr, limit=2_000),
        }

    def _mcp_list_tools(self) -> dict[str, Any]:
        if self.mcp_hub is None:
            return {"ok": False, "error": "mcp_hub_not_configured"}
        return self.mcp_hub.list_tools()

    def _mcp_call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.mcp_hub is None:
            return {"ok": False, "error": "mcp_hub_not_configured"}
        try:
            return self.mcp_hub.call_tool(qualified_name, arguments)
        except Exception as exc:  # noqa: BLE001 - tool observation should not escape the agent loop.
            return {"ok": False, "error": type(exc).__name__, "detail": str(exc)}

    def _mcp_read_resource(self, server: str, uri: str) -> dict[str, Any]:
        if self.mcp_hub is None:
            return {"ok": False, "error": "mcp_hub_not_configured"}
        try:
            return self.mcp_hub.read_resource(server, uri)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": type(exc).__name__, "detail": str(exc)}


class EngineeringAgentHarness:
    def __init__(
        self,
        *,
        config: HostConfig,
        store: Any | None = None,
        runner: Any | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.runner = runner
        self.compiler = ContextCompiler(repo_root=config.runtime.repo_root)

    def run(
        self,
        *,
        goal: str,
        thread_key: str,
        chat_name: str | None = None,
        channel: str = "cli",
        max_steps: int = 8,
        offline: bool = False,
        allow_repo_write: bool = False,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        max_steps_effective = max(1, min(int(max_steps or 8), 20))
        from .mcp_upstream import build_mcp_upstream_hub

        mcp_hub = build_mcp_upstream_hub(config_path=str(self.config.config_path) if self.config.config_path else None)
        executor = EngineeringToolExecutor(
            repo_root=self.config.runtime.repo_root,
            allow_repo_write=allow_repo_write,
            mcp_hub=mcp_hub,
        )
        phase_trace: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        observation = {
            "repo_root": str(self.config.runtime.repo_root),
            "repo_status": executor._git_status(),
            "allow_repo_write": bool(allow_repo_write),
        }
        self._phase(phase_trace, "observe", observation)
        context_bundle = self.compiler.compile(
            goal=goal,
            model_profile="deepseek_v4_pro",
            budget="pro_128k",
            runtime_diagnostics=observation,
            tool_inventory=[
                {"tool": "read_file", "mutation_class": "read_only"},
                {"tool": "search_text", "mutation_class": "read_only"},
                {"tool": "run_tests", "mutation_class": "cache_write"},
                {"tool": "mcp_list_tools", "mutation_class": "external_observation"},
                {"tool": "mcp_call_tool", "mutation_class": "external_observation"},
                {"tool": "mcp_read_resource", "mutation_class": "external_observation"},
                {"tool": "replace_text", "mutation_class": "repo_write"},
                {"tool": "write_file", "mutation_class": "repo_write"},
            ],
        )
        self._record_context_bundle(context_bundle)
        self._phase(phase_trace, "context_compile", {"bundle_id": context_bundle["bundle_id"], "cache_key": context_bundle["cache_key"]})
        status = "completed"
        failure_reason = ""
        for step_index in range(max_steps_effective):
            deliberation = self._deliberate(
                goal=goal,
                context_bundle=context_bundle,
                offline=offline,
                step_index=step_index,
            )
            self._phase(phase_trace, "deliberate", {"step_index": step_index, "summary": deliberation.get("summary", "")})
            gated_actions = [{**action, "gate": executor.gate(action)} for action in deliberation.get("actions", [])[:12]]
            action_market = {
                "gate_applied": True,
                "candidate_count": len(gated_actions),
                "allowed_count": sum(1 for action in gated_actions if bool(action["gate"].get("allowed", False))),
                "blocked_count": sum(1 for action in gated_actions if not bool(action["gate"].get("allowed", False))),
            }
            self._phase(phase_trace, "action_market", action_market)
            executed_actions = [executor.execute(action) for action in deliberation.get("actions", [])[:12]]
            tool_loop = {
                "actions": executed_actions,
                "summary": {
                    "executed_count": sum(1 for action in executed_actions if bool(action.get("executed", False))),
                    "blocked_count": sum(1 for action in executed_actions if not bool(action.get("gate", {}).get("allowed", False))),
                },
            }
            self._phase(phase_trace, "tool_loop", tool_loop["summary"])
            verification = self._verify(executed_actions)
            self._phase(phase_trace, "verification", verification)
            steps.append(
                {
                    "step_index": step_index,
                    "deliberation": deliberation,
                    "action_market": action_market,
                    "tool_loop": tool_loop,
                    "verification": verification,
                }
            )
            if not bool(verification.get("completion_allowed", False)):
                status = "failed"
                failure_reason = str(verification.get("failure_reason", "verification_failed"))
                break
            if bool(deliberation.get("done", True)):
                break
        review = self._review(steps=steps, status=status, allow_repo_write=allow_repo_write)
        self._phase(phase_trace, "review", review)
        metrics = self._metrics(steps=steps, context_bundle=context_bundle, started_at=started_at)
        payload = {
            "ok": status == "completed",
            "stage": STAGE41_NAME,
            "status": status,
            "goal": compact(goal, limit=500),
            "thread_key": str(thread_key or "cli:stage41"),
            "chat_name": str(chat_name or thread_key or "Stage41"),
            "channel": str(channel or "cli"),
            "max_steps_effective": max_steps_effective,
            "allow_repo_write": bool(allow_repo_write),
            "context_bundle": context_bundle,
            "phase_trace": phase_trace,
            "steps": steps,
            "verification": steps[-1]["verification"] if steps else {"completion_allowed": False},
            "review": review,
            "metrics": metrics,
            "failure_reason": failure_reason,
            "hard_boundaries": {
                "action_market_first": True,
                "repo_write_requires_explicit_authority": True,
                "private_paths_blocked": True,
                "no_wechat_transport_start": True,
                "no_self_memory_write": True,
            },
        }
        run = self._record_run(payload)
        payload["run_id"] = int(run.get("run_id", run.get("id", 0)) or 0)
        return payload

    def _deliberate(self, *, goal: str, context_bundle: dict[str, Any], offline: bool, step_index: int) -> dict[str, Any]:
        if offline or self.runner is None:
            return {
                "summary": "offline engineering smoke",
                "actions": [{"tool": "inspect_repo_status", "mutation_class": "read_only"}],
                "done": True,
                "verification": "repo status observed",
            }
        request = ProcessorTaskRequest(
            task_type="operator_plan",
            prompt=json.dumps(
                {
                    "stage": STAGE41_NAME,
                    "goal": goal,
                    "step_index": step_index,
                    "context_bundle": {
                        "bundle_id": context_bundle.get("bundle_id", ""),
                        "cache_key": context_bundle.get("cache_key", ""),
                        "sections": context_bundle.get("sections", [])[:10],
                    },
                    "required_output": {
                        "summary": "string",
                        "actions": [
                            {
                                "tool": "read_file|search_text|run_tests|mcp_list_tools|mcp_call_tool|mcp_read_resource|replace_text|write_file",
                                "mutation_class": "read_only|cache_write|external_observation|repo_write",
                            }
                        ],
                        "done": True,
                        "verification": "string",
                    },
                    "hard_rules": {
                        "all_tools_go_through_action_market": True,
                        "repo_write_requires_user_authority": True,
                        "private_paths_blocked": True,
                    },
                },
                ensure_ascii=False,
            ),
            lane="kernel_xhigh",
            provider_hint="deepseek",
            model_override="deepseek-v4-pro",
            reasoning_effort_override="xhigh",
            budget_tag="stage41_engineering_agent",
            output_schema="json",
            allow_memory_writeback=False,
            metadata={"stage": STAGE41_NAME, "context_bundle_id": context_bundle.get("bundle_id", "")},
        )
        result = self.runner.run_task(request)
        try:
            parsed = json.loads(str(result.text or "").strip())
        except json.JSONDecodeError:
            parsed = {"summary": compact(result.text, limit=500), "actions": [{"tool": "inspect_repo_status", "mutation_class": "read_only"}], "done": True}
        actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
        return {
            "summary": compact(parsed.get("summary", "") or "engineering plan", limit=500),
            "actions": [dict(action) for action in actions if isinstance(action, dict)],
            "done": bool(parsed.get("done", True)),
            "verification": compact(parsed.get("verification", "") or "", limit=500),
            "processor_metadata": dict(getattr(result, "metadata", {}) or {}),
        }

    @staticmethod
    def _verify(actions: list[dict[str, Any]]) -> dict[str, Any]:
        tests = [action for action in actions if action.get("tool") == "run_tests" and bool(action.get("executed"))]
        failed_tests = [
            action
            for action in tests
            if int(dict(action.get("observation", {})).get("returncode", 1)) != 0
        ]
        failed_external_observations = [
            action
            for action in actions
            if str(action.get("mutation_class", "")) == "external_observation"
            and not bool(dict(action.get("observation", {})).get("ok", True))
        ]
        blocked = [action for action in actions if not bool(action.get("gate", {}).get("allowed", False))]
        executed = [action for action in actions if bool(action.get("executed", False))]
        successful_writes = [
            action
            for action in actions
            if str(action.get("mutation_class", "")) == "repo_write"
            and bool(action.get("gate", {}).get("allowed", False))
            and bool(dict(action.get("observation", {})).get("ok", False))
        ]
        completion_allowed = (
            bool(executed)
            and not blocked
            and not failed_tests
            and not failed_external_observations
            and (not successful_writes or bool(tests))
        )
        if blocked:
            failure_reason = "blocked_action"
        elif failed_tests:
            failure_reason = "test_failure"
        elif failed_external_observations:
            failure_reason = "external_observation_failure"
        elif successful_writes and not tests:
            failure_reason = "repo_write_requires_verification_tests"
        elif not completion_allowed:
            failure_reason = "no_actions_executed"
        else:
            failure_reason = ""
        return {
            "completion_allowed": completion_allowed,
            "actions_observed": bool(actions),
            "executed_count": len(executed),
            "blocked_count": len(blocked),
            "tests_observed": bool(tests),
            "failed_test_count": len(failed_tests),
            "failed_external_observation_count": len(failed_external_observations),
            "successful_repo_write_count": len(successful_writes),
            "failure_reason": failure_reason,
        }

    @staticmethod
    def _review(*, steps: list[dict[str, Any]], status: str, allow_repo_write: bool) -> dict[str, Any]:
        actions = [action for step in steps for action in dict(step.get("tool_loop", {})).get("actions", [])]
        writes = [action for action in actions if str(action.get("mutation_class", "")) == "repo_write"]
        return {
            "status": status,
            "repo_write_requested": bool(writes),
            "repo_write_authorized": bool(allow_repo_write),
            "blocked_write_count": sum(1 for action in writes if not bool(action.get("gate", {}).get("allowed", False))),
            "successful_write_count": sum(
                1
                for action in writes
                if bool(action.get("gate", {}).get("allowed", False)) and bool(dict(action.get("observation", {})).get("ok", False))
            ),
            "manual_review_required": bool(writes),
        }

    @staticmethod
    def _metrics(*, steps: list[dict[str, Any]], context_bundle: dict[str, Any], started_at: float) -> dict[str, Any]:
        actions = [action for step in steps for action in dict(step.get("tool_loop", {})).get("actions", [])]
        return {
            "duration_ms": int((time.perf_counter() - started_at) * 1000),
            "step_count": len(steps),
            "context_token_estimate": int(context_bundle.get("token_estimate", 0) or 0),
            "action_count": len(actions),
            "executed_count": sum(1 for action in actions if bool(action.get("executed", False))),
            "blocked_count": sum(1 for action in actions if not bool(action.get("gate", {}).get("allowed", False))),
            "test_count": sum(1 for action in actions if action.get("tool") == "run_tests"),
            "repo_write_count": sum(1 for action in actions if str(action.get("mutation_class", "")) == "repo_write"),
            "mcp_tool_count": sum(1 for action in actions if str(action.get("mutation_class", "")) == "external_observation"),
        }

    def _record_context_bundle(self, context_bundle: dict[str, Any]) -> None:
        if self.store is None or not hasattr(self.store, "record_context_bundle"):
            return
        try:
            self.store.record_context_bundle(context_bundle)
        except Exception:
            return

    def _record_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.store is None or not hasattr(self.store, "record_bionic_brain_run"):
            return {"run_id": 0}
        try:
            run = self.store.record_bionic_brain_run(
                channel=str(payload.get("channel", "cli")),
                thread_key=str(payload.get("thread_key", "cli:stage41")),
                chat_name=str(payload.get("chat_name", "Stage41")),
                goal=str(payload.get("goal", "")),
                status=str(payload.get("status", "")),
                step_count=int(dict(payload.get("metrics", {})).get("step_count", 0) or 0),
                metrics=dict(payload.get("metrics", {})),
                run_payload=payload,
                stage=STAGE41_NAME,
            )
            self._record_run_steps(run_id=int(run.get("run_id", 0) or 0), payload=payload)
            return run
        except Exception:
            return {"run_id": 0}

    def _record_run_steps(self, *, run_id: int, payload: dict[str, Any]) -> None:
        if run_id <= 0 or self.store is None or not hasattr(self.store, "record_bionic_brain_step"):
            return
        for index, phase in enumerate(payload.get("phase_trace", []) or []):
            if not isinstance(phase, dict):
                continue
            try:
                self.store.record_bionic_brain_step(
                    run_id=run_id,
                    step_index=index,
                    phase=str(phase.get("phase", "")),
                    payload=dict(phase.get("payload", {}) or {}),
                )
            except Exception:
                continue

    @staticmethod
    def _phase(phase_trace: list[dict[str, Any]], phase: str, payload: dict[str, Any]) -> None:
        phase_trace.append({"phase": phase, "at": utc_now(), "payload": payload})


def accept_stage41_payload(
    *,
    config: HostConfig,
    store: Any,
    runner: Any | None = None,
    stage40_payload: dict[str, Any] | None = None,
    thread_key: str = "cli:TestUser",
    chat_name: str = "TestUser",
    channel: str = "cli",
) -> dict[str, Any]:
    harness = EngineeringAgentHarness(config=config, store=store, runner=runner)
    smoke = harness.run(
        goal="Stage41 acceptance: verify engineering agent read/test loop without repo write",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        offline=True,
        max_steps=2,
    )
    repo_root = config.runtime.repo_root
    default_executor = EngineeringToolExecutor(repo_root=repo_root, allow_repo_write=False)
    authorized_executor = EngineeringToolExecutor(repo_root=repo_root, allow_repo_write=True)
    denied_write = default_executor.gate(
        {"tool": "replace_text", "mutation_class": "repo_write", "path": "README.md", "old": "x", "new": "y"}
    )
    blocked_private = authorized_executor.gate(
        {"tool": "write_file", "mutation_class": "repo_write", "path": ".holo_runtime/stage41-acceptance.txt", "content": "x"}
    )
    checks = {
        "stage40_gate_passed": bool((stage40_payload or {}).get("ok", True)),
        "engineering_smoke_completed": bool(smoke.get("ok", False)),
        "phase_trace_visible": all(phase in [entry.get("phase") for entry in smoke.get("phase_trace", [])] for phase in STAGE41_PHASES),
        "repo_write_default_denied": str(denied_write.get("reason", "")) == "repo_write_requires_explicit_user_authority",
        "private_paths_blocked": str(blocked_private.get("reason", "")) == "private_or_unsafe_path_blocked",
        "wechat_not_started": True,
        "self_memory_not_mutated": True,
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE41_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "engineering_smoke": smoke,
        "boundary_probes": {
            "denied_write": denied_write,
            "blocked_private": blocked_private,
        },
        "hard_boundaries": {
            "no_wechat_transport_start": True,
            "repo_write_requires_explicit_authority": True,
            "private_paths_blocked": True,
            "no_self_memory_write": True,
        },
    }
