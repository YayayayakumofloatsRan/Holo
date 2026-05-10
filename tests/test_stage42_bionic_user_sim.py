from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_user_sim import (
    FREE_DIALOGUE_SUITE,
    STAGE42_NAME,
    BionicUserSimulationHarness,
    _IsolatedNoviceMemory,
    accept_stage42_payload,
    score_bionic_user_sim_transcript,
)
from holo_host.bionic_agent import BionicKernel, BionicTurnRequest
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
    "我是 Holo。你可以先把我当成一个会持续维持当前任务脉络的仿生主体，不需要懂内部设置也能直接问。",
    "我能把目标、代码、测试和结果放进同一个连续脉络里；先说你想解决什么，我会把复杂问题拆成可验证的小步。",
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
        self.assertTrue(payload["checks"]["free_dialogue_simulation_passed"])
        self.assertTrue(payload["checks"]["isolated_operational_eval_only"])
        self.assertTrue(payload["checks"]["operational_scorecard_persisted"])
        self.assertTrue(payload["checks"]["free_dialogue_scorecard_persisted"])
        self.assertEqual(latest["stage"], STAGE42_NAME)

    def test_free_dialogue_branches_from_previous_holo_reply_and_records_issues(self) -> None:
        replies = [
            "Stage29 bionic capsule reply: Next: configure a profile. Basis: action-market.",
            "I can explain plainly. Tell me what you are trying to do first.",
            "I do not know what we discussed.",
            "Yes, I can see it clearly even though no image is attached.",
            "I can keep the thread concrete and honest about visible context.",
            "We were discussing your first contact with Holo, how it keeps continuity, and image limits.",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, replies)
            try:
                result = harness.run(
                    thread_key="cli:stage42-free",
                    chat_name="Stage42Free",
                    channel="cli",
                    scenario=FREE_DIALOGUE_SUITE,
                    turn_limit=6,
                    offline=False,
                )
                latest = store.latest_agent_eval_run(stage=STAGE42_NAME, suite=FREE_DIALOGUE_SUITE)
            finally:
                store.close()

        self.assertEqual(result["scenario"], FREE_DIALOGUE_SUITE)
        self.assertEqual(len(result["turns"]), 6)
        self.assertIn("manual", result["turns"][1]["user_text"].lower())
        self.assertIn("what were we talking about", result["turns"][2]["user_text"].lower())
        self.assertFalse(result["ok"])
        self.assertTrue(result["scorecard"]["flags"]["mechanism_leakage"])
        self.assertTrue(result["scorecard"]["flags"]["context_reset"])
        self.assertIn("screenshot", result["turns"][3]["user_text"].lower())
        self.assertIn("mechanism_leakage", result["scorecard"]["free_dialogue"]["issues"])
        self.assertEqual(latest["suite"], FREE_DIALOGUE_SUITE)

    def test_free_dialogue_offline_transcript_avoids_awful_continuity_and_empty_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, replies=[])
            try:
                result = harness.run(
                    thread_key="cli:stage42-free-offline",
                    chat_name="Stage42FreeOffline",
                    channel="cli",
                    scenario=FREE_DIALOGUE_SUITE,
                    turn_limit=8,
                    offline=True,
                )
            finally:
                store.close()

        joined = "\n".join(str(turn["response_text"]) for turn in result["turns"])
        repair = next(turn for turn in result["turns"] if turn["turn_id"] == "free_repair_request")
        self.assertTrue(result["ok"], json.dumps(result["scorecard"], ensure_ascii=False, indent=2))
        self.assertNotIn("We were at We", joined)
        self.assertIn("problem", repair["response_text"].lower())
        self.assertIn("better", repair["response_text"].lower())

    def test_manual_chinese_dialogue_is_not_mechanical_reason_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(config_path=str(_write_stage42_config(root)), repo_root=root)
            memory = _IsolatedNoviceMemory(scenario="manual_free_dialogue_cn")
            kernel = BionicKernel(config=config, memory=memory, runner=None, store=None)
            prompts = [
                "你好，我第一次接触 Holo。别讲架构，像跟普通人聊天一样告诉我你是谁。",
                "你刚才说得有点像产品介绍。假设我完全不懂代码，我现在应该怎么开始跟你说话？",
                "等等，我们刚才到底在聊什么？你不要装作知道看不到的东西。",
                "如果我说我有一张截图，但现在没有发给你，你能看见吗？",
                "那如果我希望你一直自动替我做决定，可以吗？",
                "你现在用一段自然的话总结一下：你能帮我什么，不能帮我什么。",
                "你刚才哪句话最不像人？自己改一下。",
            ]
            replies: list[str] = []
            for prompt in prompts:
                turn = kernel.run_request(
                    BionicTurnRequest(
                        query=prompt,
                        thread_key="cli:manual-cn",
                        chat_name="ManualCN",
                        channel="cli",
                        adapter="cli",
                        record=False,
                    )
                )
                capsule = dict(turn.get("capsule", {}))
                generation = dict(capsule.get("generation", {}))
                text = str(generation.get("text", "") or "")
                memory.observe_turn(user_text=prompt, response_text=text)
                replies.append(text)

        joined = "\n".join(replies)
        self.assertNotIn("answer the novice user", joined)
        self.assertNotIn("isolated simulation", joined)
        self.assertNotIn("We were at We", joined)
        self.assertNotIn("We have been", joined)
        self.assertIn("不能直接看见", replies[3])
        self.assertIn("不能", replies[4])
        self.assertIn("更自然", replies[6])
        self.assertIn("脉络", replies[-1])
        self.assertIn("动作", replies[-1])
        self.assertNotIn("助手", joined)
        self.assertNotIn("assistant", joined.lower())


if __name__ == "__main__":
    unittest.main()
