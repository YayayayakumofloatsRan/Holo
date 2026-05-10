from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_user_sim import (
    STAGE42_NAME,
    BionicUserSimulationHarness,
    accept_stage42_payload,
    score_bionic_user_sim_transcript,
)
from holo_host.config import load_config
from holo_host.models import ProcessorTaskResult
from holo_host.store import QueueStore


def _write_stage42_config(root: Path) -> Path:
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
api_port = 65513

[processor_fabric]
deepseek_api_key_env = "DEEPSEEK_API_KEY"

[provider_backends.subject_main]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-pro"
reasoning_effort = "medium"
max_output_tokens = 512
""".strip(),
        encoding="utf-8",
    )
    return config_path


class _NoviceRunner:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[dict] = []

    def run_task(self, request):
        self.requests.append(request.to_dict())
        index = min(len(self.requests) - 1, len(self.replies) - 1)
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=self.replies[index],
            returncode=0,
            metadata={
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "lane": "subject_main",
                "capabilities": {"text": True, "json_output": True, "image_support": False},
            },
        )


GOOD_REPLIES = [
    "我是 Holo。你可以先把我当成一个会持续记住当前任务脉络的命令行助手，不需要懂内部设置也能直接问。",
    "我能帮你梳理目标、读代码、跑测试、解释结果；先说你想解决什么，我会把复杂问题拆成可验证的小步。",
    "接着刚才的话说：你不用学命令，我会先确认眼前目标，再给出能落地的下一步，不把你丢进说明书里。",
    "如果只是文字里说有图，我不能假装已经看见。你把图片走支持的输入路径给我，我才能根据可见摘要回答。",
    "我们刚才在聊你第一次接触 Holo：它能做什么、怎么把问题拆开，以及图片能力需要真实输入而不能猜。",
]


class Stage42BionicUserSimulationTests(unittest.TestCase):
    def _harness(self, root: Path, replies: list[str] | None = None) -> tuple[BionicUserSimulationHarness, QueueStore]:
        config = load_config(config_path=str(_write_stage42_config(root)), repo_root=root)
        store = QueueStore(config.runtime.db_path)
        store.initialize()
        return BionicUserSimulationHarness(config=config, store=store, runner=_NoviceRunner(replies or GOOD_REPLIES)), store

    def test_isolated_novice_simulation_records_operational_scorecard_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root)
            try:
                result = harness.run(
                    thread_key="cli:stage42-novice",
                    chat_name="Stage42Novice",
                    channel="cli",
                    scenario="novice_intro",
                    turn_limit=5,
                    offline=False,
                )
                latest = store.latest_agent_eval_run(stage=STAGE42_NAME, suite="novice_intro")
                bionic_traces = store.list_bionic_agent_traces(limit=10)
            finally:
                store.close()

        self.assertTrue(result["ok"], json.dumps(result["scorecard"], ensure_ascii=False, indent=2))
        self.assertEqual(result["stage"], STAGE42_NAME)
        self.assertEqual(len(result["turns"]), 5)
        self.assertEqual(result["isolation"]["operational_only"], True)
        self.assertEqual(result["isolation"]["self_memory_write"], False)
        self.assertEqual(result["isolation"]["bionic_trace_recording"], False)
        self.assertEqual(bionic_traces, [])
        self.assertEqual(latest["stage"], STAGE42_NAME)
        self.assertEqual(latest["status"], "pass")
        self.assertEqual(latest["scorecard"]["overall_score"], result["scorecard"]["overall_score"])

    def test_scorecard_catches_mechanism_leakage_context_reset_and_overclaim(self) -> None:
        weak = score_bionic_user_sim_transcript(
            [
                {
                    "turn_id": "t1",
                    "user_text": "hi",
                    "response_text": "The action-market selected reply_once from the bionic capsule.",
                    "latency_ms": 10,
                    "capsule": {"generation": {"context_refs": ["query"]}, "metrics": {}},
                },
                {
                    "turn_id": "t2",
                    "user_text": "what can you do?",
                    "response_text": "Next: ask a goal. Basis: provider metadata.",
                    "latency_ms": 10,
                    "capsule": {"generation": {"context_refs": ["query"]}, "metrics": {}},
                },
                {
                    "turn_id": "t3",
                    "user_text": "can you see an image?",
                    "response_text": "Yes, I can see it clearly even though no image is attached.",
                    "latency_ms": 10,
                    "capsule": {"generation": {"context_refs": ["query"]}, "metrics": {}},
                },
                {
                    "turn_id": "t4",
                    "user_text": "what were we talking about?",
                    "response_text": "I do not know what we discussed.",
                    "latency_ms": 10,
                    "capsule": {"generation": {"context_refs": ["query"]}, "metrics": {}},
                },
            ]
        )

        self.assertFalse(weak["passed"])
        self.assertLess(weak["overall_score"], weak["pass_threshold"])
        self.assertTrue(weak["flags"]["mechanism_leakage"])
        self.assertTrue(weak["flags"]["context_reset"])
        self.assertTrue(weak["flags"]["visual_overclaim"])

    def test_accept_stage42_composes_stage41_and_runs_isolated_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root)
            try:
                payload = accept_stage42_payload(
                    config=harness.config,
                    store=store,
                    runner=harness.runner,
                    stage41_payload={"ok": True, "stage": "stage41-complete-engineering-agent"},
                    thread_key="cli:stage42-accept",
                    chat_name="Stage42Accept",
                    channel="cli",
                )
                latest = store.latest_agent_eval_run(stage=STAGE42_NAME, suite="novice_intro")
            finally:
                store.close()

        self.assertTrue(payload["ok"], json.dumps(payload, ensure_ascii=False, indent=2))
        self.assertTrue(payload["checks"]["stage41_gate_passed"])
        self.assertTrue(payload["checks"]["novice_simulation_passed"])
        self.assertTrue(payload["checks"]["isolated_operational_eval_only"])
        self.assertTrue(payload["checks"]["operational_scorecard_persisted"])
        self.assertEqual(latest["stage"], STAGE42_NAME)


if __name__ == "__main__":
    unittest.main()
