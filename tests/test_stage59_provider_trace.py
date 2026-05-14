from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config
from holo_host.models import ProcessorTaskRequest, ProcessorTaskResult


class _FakeTurnExecutor:
    def __init__(self, *, total_tokens: int = 1000) -> None:
        self.total_tokens = total_tokens
        self.calls: list[dict] = []

    def run_turn(
        self,
        *,
        user_text: str,
        thread_key: str,
        chat_name: str,
        channel: str,
        message_id: str,
        metadata: dict,
    ) -> dict:
        self.calls.append(
            {
                "user_text": user_text,
                "thread_key": thread_key,
                "chat_name": chat_name,
                "channel": channel,
                "message_id": message_id,
                "metadata": dict(metadata),
            }
        )
        turn_index = int(metadata.get("turn_index", 0) or 0)
        return {
            "text": f"trace reply {turn_index}",
            "route": "main",
            "selected_action": {
                "action_type": "reply",
                "score": 0.77,
                "send_allowed": True,
            },
            "grounding_guard": {"visual_overclaim_rewritten": False},
            "processor_debug": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "lane": "subject_main",
                "reasoning_effort": "medium",
                "usage": {
                    "prompt_tokens": self.total_tokens - 120,
                    "completion_tokens": 120,
                    "total_tokens": self.total_tokens,
                    "prompt_cache_hit_tokens": 220 + turn_index * 10,
                    "prompt_cache_miss_tokens": self.total_tokens
                    - 340
                    - turn_index * 10,
                    "prompt_cache_hit_ratio": 0.25,
                    "estimated": False,
                },
                "prompt_partition": {
                    "mode": "stable_prefix_messages",
                    "provider_cache_prefix_tokens": 720,
                    "provider_cache_dynamic_tokens": 1280 + turn_index,
                },
                "bionic_memory_schedule": {
                    "mode": "biomimetic_v1",
                    "salience_score": 0.62,
                    "recall_budget": 4,
                    "dynamic_context_line_count": 9,
                    "dynamic_fusion_saved_line_count": 5,
                },
                "bionic_memory_lifecycle": {
                    "mode": "biomimetic_lifecycle_v1",
                    "consolidation_priority": 0.71,
                    "self_memory_write": False,
                },
                "bionic_consciousness_flow": {
                    "mode": "consciousness_flow_v1",
                    "dominant_phase": "memory_reactivation",
                    "phase_count": 6,
                    "user_visible": False,
                },
            },
        }


class _FakeUsageStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._next_id = 1

    def add_usage(
        self,
        *,
        thread_key: str,
        event_id: str,
        task_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        provider: str = "deepseek",
        model: str = "deepseek-v4-flash",
    ) -> None:
        self.rows.append(
            {
                "id": self._next_id,
                "task_type": task_type,
                "lane": "micro_fast",
                "provider": provider,
                "model": model,
                "reasoning_effort": "low",
                "thread_key": thread_key,
                "event_id": event_id,
                "duration_ms": 100,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated": 0,
                "status": "ok",
                "metadata_json": json.dumps(
                    {
                        "usage": {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                            "prompt_cache_hit_tokens": 64
                            if task_type == "reply"
                            else 0,
                            "prompt_cache_miss_tokens": max(
                                0,
                                prompt_tokens
                                - (64 if task_type == "reply" else 0),
                            ),
                            "estimated": False,
                        }
                    }
                ),
                "created_at": "2026-05-14T03:15:45Z",
            }
        )
        self._next_id += 1

    def list_processor_usage(
        self,
        *,
        limit: int = 50,
        task_type: str | None = None,
        lane: str | None = None,
        provider: str | None = None,
        event_id: str | None = None,
        thread_key: str | None = None,
    ) -> list[dict]:
        rows = list(self.rows)
        if task_type:
            rows = [row for row in rows if row["task_type"] == task_type]
        if lane:
            rows = [row for row in rows if row["lane"] == lane]
        if provider:
            rows = [row for row in rows if row["provider"] == provider]
        if event_id:
            rows = [row for row in rows if row["event_id"] == event_id]
        if thread_key:
            rows = [row for row in rows if row["thread_key"] == thread_key]
        return list(reversed(rows))[: max(1, int(limit))]


class _LedgerWritingTurnExecutor(_FakeTurnExecutor):
    def __init__(self, store: _FakeUsageStore) -> None:
        super().__init__(total_tokens=1000)
        self.store = store

    def run_turn(
        self,
        *,
        user_text: str,
        thread_key: str,
        chat_name: str,
        channel: str,
        message_id: str,
        metadata: dict,
    ) -> dict:
        self.store.add_usage(
            thread_key=thread_key,
            event_id=message_id,
            task_type="recall_reconstruct",
            prompt_tokens=180,
            completion_tokens=20,
            total_tokens=200,
        )
        self.store.add_usage(
            thread_key=thread_key,
            event_id=message_id,
            task_type="reply",
            prompt_tokens=900,
            completion_tokens=100,
            total_tokens=1000,
        )
        return super().run_turn(
            user_text=user_text,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            message_id=message_id,
            metadata=metadata,
        )


class Stage59ProviderTraceTests(unittest.TestCase):
    def test_dry_run_plans_provider_trace_without_calling_executor(self) -> None:
        from holo_host.consciousness_provider_trace import run_provider_longform_trace

        executor = _FakeTurnExecutor()
        report = run_provider_longform_trace(
            execute=False,
            runs=2,
            turns=8,
            max_total_tokens=12000,
            provider_hint="deepseek",
            model="deepseek-v4-pro",
            executor=executor,
        )

        self.assertEqual(report["stage"], "stage59-provider-longform-trace")
        self.assertEqual(report["status"], "dry_run")
        self.assertFalse(report["provider_trace_set"]["real_provider_trace"])
        self.assertTrue(report["execution_gate"]["requires_execute_flag"])
        self.assertEqual(report["provider_trace_set"]["planned_run_count"], 2)
        self.assertEqual(report["provider_trace_set"]["planned_turns_per_run"], 8)
        self.assertEqual(report["budget_guard"]["max_total_tokens"], 12000)
        self.assertEqual(executor.calls, [])

    def test_execute_collects_stage46_compatible_turns_and_stops_at_budget(
        self,
    ) -> None:
        from holo_host.consciousness_provider_trace import run_provider_longform_trace

        executor = _FakeTurnExecutor(total_tokens=1000)
        report = run_provider_longform_trace(
            execute=True,
            runs=1,
            turns=10,
            max_total_tokens=2500,
            provider_hint="deepseek",
            model="deepseek-v4-pro",
            max_output_tokens=160,
            executor=executor,
        )

        self.assertEqual(report["status"], "stopped")
        self.assertTrue(report["provider_trace_set"]["real_provider_trace"])
        self.assertEqual(report["budget_guard"]["observed_total_tokens"], 3000)
        self.assertEqual(
            report["budget_guard"]["stopped_reason"], "token_budget_exhausted"
        )
        self.assertEqual(len(executor.calls), 3)
        self.assertEqual(executor.calls[0]["metadata"]["cache_bypass"], True)
        self.assertEqual(executor.calls[0]["metadata"]["max_output_tokens"], 160)
        self.assertEqual(
            report["stage46_compatible_runs"][0]["stage"],
            "stage46-bionic-boundary-stress",
        )
        self.assertEqual(len(report["stage46_compatible_runs"][0]["turns"]), 3)
        self.assertEqual(report["stage57_calibration"]["trace_set"]["total_points"], 3)
        self.assertFalse(report["boundary"]["wechat_transport_used"])
        self.assertFalse(report["boundary"]["self_memory_write_allowed"])

    def test_execute_counts_all_processor_ledger_rows_for_turn_budget(self) -> None:
        from holo_host.consciousness_provider_trace import run_provider_longform_trace

        store = _FakeUsageStore()
        executor = _LedgerWritingTurnExecutor(store)
        report = run_provider_longform_trace(
            execute=True,
            runs=1,
            turns=4,
            max_total_tokens=1100,
            provider_hint="deepseek",
            model="deepseek-v4-flash",
            max_output_tokens=120,
            store=store,
            executor=executor,
        )
        turns = report["stage46_compatible_runs"][0]["turns"]

        self.assertEqual(report["status"], "stopped")
        self.assertEqual(
            report["budget_guard"]["stopped_reason"], "token_budget_exhausted"
        )
        self.assertEqual(report["budget_guard"]["observed_total_tokens"], 1200)
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(report["generated_runs"][0]["total_tokens"], 1200)
        self.assertEqual(turns[0]["processor_usage_scope"]["mode"], "ledger_delta")
        self.assertEqual(turns[0]["processor_usage_scope"]["ledger_record_count"], 2)
        self.assertEqual(turns[0]["processor_usage_observed"]["total_tokens"], 1200)
        self.assertEqual(
            turns[0]["processor_usage_observed"]["prompt_cache_hit_tokens"],
            64,
        )
        self.assertEqual(
            [row["task_type"] for row in turns[0]["processor_usage_ledger"]],
            ["recall_reconstruct", "reply"],
        )

    def test_writes_provider_trace_artifacts_and_turn_journal(self) -> None:
        from holo_host.consciousness_provider_trace import (
            run_provider_longform_trace,
            write_provider_trace_artifacts,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "stage59.html"
            journal_path = Path(tmpdir) / "stage59_turns.jsonl"
            report = run_provider_longform_trace(
                execute=True,
                runs=1,
                turns=2,
                max_total_tokens=5000,
                provider_hint="deepseek",
                model="deepseek-v4-flash",
                checkpoint_path=journal_path,
                executor=_FakeTurnExecutor(total_tokens=900),
            )
            artifacts = write_provider_trace_artifacts(report, output_path)
            report_json = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            journal_lines = journal_path.read_text(encoding="utf-8").splitlines()
            png_header = artifacts["provider_trace_png"].read_bytes()[:8]

        self.assertEqual(report_json["stage"], "stage59-provider-longform-trace")
        self.assertEqual(len(journal_lines), 2)
        self.assertEqual(
            json.loads(journal_lines[0])["stage"], "stage59-provider-longform-trace"
        )
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_resume_from_turn_journal_continues_without_replaying_completed_turns(
        self,
    ) -> None:
        from holo_host.consciousness_provider_trace import run_provider_longform_trace

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "stage59_turns.jsonl"
            first_executor = _FakeTurnExecutor(total_tokens=1000)
            first = run_provider_longform_trace(
                execute=True,
                runs=1,
                turns=3,
                max_total_tokens=1000,
                checkpoint_path=journal_path,
                executor=first_executor,
            )
            second_executor = _FakeTurnExecutor(total_tokens=1000)
            second = run_provider_longform_trace(
                execute=True,
                runs=1,
                turns=3,
                max_total_tokens=5000,
                checkpoint_path=journal_path,
                resume=True,
                executor=second_executor,
            )
            journal_lines = journal_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(first["provider_trace_set"]["collected_turn_count"], 1)
        self.assertEqual(len(first_executor.calls), 1)
        self.assertEqual(second["provider_trace_set"]["resumed_turn_count"], 1)
        self.assertEqual(second["provider_trace_set"]["collected_turn_count"], 3)
        self.assertEqual(second["budget_guard"]["observed_total_tokens"], 3000)
        self.assertEqual(len(second_executor.calls), 2)
        self.assertEqual(len(journal_lines), 3)

    def test_processor_fabric_can_disable_provider_fallback_for_strict_provider_traces(
        self,
    ) -> None:
        from holo_host.codex_runner import CodexRunner

        class _FailingProvider:
            name = "deepseek"

            def availability(self) -> dict:
                return {"available": True}

            def supports_request(self, request: ProcessorTaskRequest) -> bool:
                return True

            def run_task(self, *args, **kwargs) -> ProcessorTaskResult:
                raise RuntimeError("deepseek unavailable")

        class _FallbackProvider:
            name = "codex_cli"

            def __init__(self) -> None:
                self.called = False

            def availability(self) -> dict:
                return {"available": True}

            def supports_request(self, request: ProcessorTaskRequest) -> bool:
                return True

            def run_task(self, *args, **kwargs) -> ProcessorTaskResult:
                self.called = True
                return ProcessorTaskResult(
                    task_type="reply",
                    text="fallback reply",
                    metadata={"provider": "codex_cli"},
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
""".strip(),
                encoding="utf-8",
            )
            runner = CodexRunner(load_config(str(config_path), repo_root=root))
            fallback = _FallbackProvider()
            runner._providers = {"deepseek": _FailingProvider(), "codex_cli": fallback}
            result = runner.run_task(
                ProcessorTaskRequest(
                    task_type="reply",
                    prompt="strict provider trace",
                    provider_hint="deepseek",
                    metadata={"disable_provider_fallback": True},
                )
            )

        self.assertEqual(result.returncode, 1)
        self.assertFalse(fallback.called)
        self.assertEqual(
            [item["provider"] for item in result.metadata["provider_failures"]],
            ["deepseek"],
        )

    def test_shadow_config_redirects_provider_trace_runtime_and_memory_state(
        self,
    ) -> None:
        from holo_host.consciousness_provider_trace import (
            shadow_config_for_provider_trace,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
""".strip(),
                encoding="utf-8",
            )
            config = load_config(str(config_path), repo_root=root)
            shadow_root = root / "artifacts" / "stage59" / "shadow_runtime"
            shadow = shadow_config_for_provider_trace(config, shadow_root)

        self.assertEqual(shadow.runtime.state_dir, shadow_root)
        self.assertEqual(shadow.runtime.db_path, shadow_root / "holo_host.sqlite3")
        self.assertEqual(shadow.runtime.log_dir, shadow_root / "logs")
        self.assertEqual(
            shadow.memory.mind_graph_db_path, shadow_root / "mind_graph.sqlite3"
        )
        self.assertIn("shadow_runtime", shadow.memory.milvus_uri)
        self.assertFalse(shadow.memory.private_memory_sync_enabled)
        self.assertFalse(shadow.memory.active_wechat_history_enabled)

    def test_cli_dry_run_writes_plan_artifacts_without_provider_calls(self) -> None:
        from holo_host.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                f"""
[runtime]
state_dir = "{(root / ".holo_runtime").as_posix()}"
db_path = "{(root / ".holo_runtime" / "holo_host.sqlite3").as_posix()}"
log_dir = "{(root / ".holo_runtime" / "logs").as_posix()}"
api_port = 65515
processor_backend = "deepseek"
""".strip(),
                encoding="utf-8",
            )
            load_config(config_path=str(config_path), repo_root=root)
            output_path = root / "artifacts" / "stage59" / "provider_trace.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "run-consciousness-provider-trace",
                        "--runs",
                        "2",
                        "--turns",
                        "8",
                        "--max-total-tokens",
                        "12000",
                        "--provider-hint",
                        "deepseek",
                        "--model",
                        "deepseek-v4-pro",
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_path = output_path.with_name("provider_trace_provider_trace.png")
            png_header = png_path.read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(payload["output_path"], str(output_path))
        self.assertEqual(payload["observatory"]["planned_total_turns"], 16)
        self.assertFalse(payload["observatory"]["real_provider_trace"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")
