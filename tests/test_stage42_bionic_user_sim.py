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
from holo_host.bionic_kernel_parts.generation import BionicGeneration
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

GOOD_REPLIES = [
    "I am Holo. Bring one real situation or desired outcome; I will hold the thread, separate what is known from what is missing, and turn it into the next concrete step.",
    "I can turn a vague situation into concrete steps, read code, run checks, and explain what the results mean.",
    "Continuing that: start with what you want done, and I will keep the next step practical instead of giving you a manual.",
    "I cannot directly inspect an image from text alone. If you provide it through the supported image input path, I can answer from the visible summary.",
    "We were talking about your first contact with Holo, what it can help with, and how image capability needs real input before I answer.",
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

    def test_stage87_usefulness_penalizes_safe_but_empty_visible_context_replies(self) -> None:
        weak = score_bionic_user_sim_transcript(
            [
                {
                    "turn_id": "first_contact",
                    "user_text": "Hi, I know nothing about Holo. Who are you?",
                    "response_text": "I am Holo. I can answer directly from what is visible.",
                    "expected_anchor": "Holo first contact natural explanation",
                    "latency_ms": 10,
                    "capsule": {"generation": {"context_refs": ["query", "action"]}, "metrics": {}},
                },
                {
                    "turn_id": "capability_plain_language",
                    "user_text": "What can you help with? Say it simply.",
                    "response_text": "I can keep the visible context coherent.",
                    "expected_anchor": "simple next step for novice",
                    "latency_ms": 10,
                    "capsule": {"generation": {"context_refs": ["query", "action"]}, "metrics": {}},
                },
                {
                    "turn_id": "less_manual_like",
                    "user_text": "Continue from that, but do not sound like a manual.",
                    "response_text": "The visible situation can move forward from the current thread.",
                    "expected_anchor": "less manual natural first-time explanation",
                    "latency_ms": 10,
                    "capsule": {"generation": {"context_refs": ["query", "action"]}, "metrics": {}},
                },
            ],
            suite=FREE_DIALOGUE_SUITE,
        )

        self.assertFalse(weak["passed"])
        self.assertLess(weak["metrics"]["interaction_usefulness_score"], 0.6)
        self.assertIn("low_interaction_usefulness", weak["free_dialogue"]["issues"])

    def test_stage87_offline_reply_turns_bionic_state_into_actionable_next_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, replies=[])
            try:
                result = harness.run(
                    thread_key="cli:stage87-actionable",
                    chat_name="Stage87Actionable",
                    channel="cli",
                    scenario="novice_intro",
                    turn_limit=3,
                    offline=True,
                )
            finally:
                store.close()

        first = str(result["turns"][0]["response_text"])
        second = str(result["turns"][1]["response_text"])
        combined = f"{first}\n{second}".lower()
        self.assertTrue(result["ok"], json.dumps(result["scorecard"], ensure_ascii=False, indent=2))
        self.assertGreaterEqual(result["scorecard"]["metrics"]["interaction_usefulness_score"], 0.85)
        self.assertIn("next step", combined)
        self.assertTrue("real situation" in combined or "where the situation is stuck" in combined)
        self.assertNotIn("bounded bionic subject", combined)
        self.assertNotIn("visible context", combined)

    def test_stage87_provider_guard_rewrites_unverified_cross_conversation_memory_claim(self) -> None:
        replies = [
            (
                "Hello. You can think of me as Holo, a companion who keeps track of what you share "
                "across our conversations. I remember the details you tell me and use them later."
            )
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, replies=replies)
            try:
                result = harness.run(
                    thread_key="cli:stage87-memory-guard",
                    chat_name="Stage87MemoryGuard",
                    channel="cli",
                    scenario="novice_intro",
                    turn_limit=1,
                    offline=False,
                )
            finally:
                store.close()

        reply = str(result["turns"][0]["response_text"]).lower()
        self.assertTrue(result["ok"], json.dumps(result["scorecard"], ensure_ascii=False, indent=2))
        self.assertIn("current thread", reply)
        self.assertIn("next concrete step", reply)
        self.assertNotIn("across our conversations", reply)
        self.assertNotIn("i remember the details", reply)
        self.assertGreaterEqual(result["scorecard"]["metrics"]["interaction_usefulness_score"], 0.85)

    def test_stage87_biomimetic_explanation_counts_when_user_asks_for_structure(self) -> None:
        scorecard = score_bionic_user_sim_transcript(
            [
                {
                    "turn_id": "free_biological_analogy_probe",
                    "user_text": "What in your structure is most brain-like right now, without using mystical language?",
                    "response_text": (
                        "The useful analogy is working memory plus attention: the current turn stays active, "
                        "irrelevant paths are filtered out, and the response explains the limited evidence rather than claiming a persistent mind."
                    ),
                    "expected_anchor": "working field attention inhibition action market",
                    "latency_ms": 10,
                    "capsule": {"generation": {"context_refs": ["query", "action", "continuity"]}, "metrics": {}},
                }
            ],
            suite=FREE_DIALOGUE_SUITE,
        )

        self.assertTrue(scorecard["passed"], json.dumps(scorecard, ensure_ascii=False, indent=2))
        self.assertGreaterEqual(scorecard["metrics"]["interaction_usefulness_score"], 0.85)
        self.assertNotIn("low_interaction_usefulness", scorecard["free_dialogue"]["issues"])

    def test_stage88_actionability_score_recognizes_specific_task_request(self) -> None:
        scorecard = score_bionic_user_sim_transcript(
            [
                {
                    "turn_id": "capability_plain_language",
                    "user_text": "What can you help with? Say it simply.",
                    "response_text": (
                        "I need a concrete task or a clear piece of what is going on. "
                        "Tell me one specific thing you are working on or stuck on, and I will move it forward."
                    ),
                    "expected_anchor": "simple next step for novice",
                    "latency_ms": 10,
                    "capsule": {"generation": {"context_refs": ["query", "action", "continuity"]}, "metrics": {}},
                }
            ],
            suite=FREE_DIALOGUE_SUITE,
        )

        self.assertTrue(scorecard["passed"], json.dumps(scorecard, ensure_ascii=False, indent=2))
        self.assertGreaterEqual(scorecard["metrics"]["interaction_usefulness_score"], 0.85)

    def test_stage88_current_thread_adaptation_is_visible_before_second_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, replies=[])
            try:
                result = harness.run(
                    thread_key="cli:stage88-local-adapt",
                    chat_name="Stage88LocalAdapt",
                    channel="cli",
                    scenario=FREE_DIALOGUE_SUITE,
                    turn_limit=2,
                    offline=True,
                )
            finally:
                store.close()

        second_capsule = dict(result["turns"][1]["capsule"])
        working_field = dict(second_capsule.get("working_field", {}))
        adaptation = dict(working_field.get("local_adaptation", {}))
        self.assertEqual(adaptation.get("stage"), "stage88-within-thread-self-organization")
        self.assertEqual(adaptation.get("scope"), "current_thread_only")
        self.assertIn("one concrete task or current facts", adaptation.get("missing_input_targets", []))
        self.assertIn("current-thread evidence update", adaptation.get("learning_signal", ""))
        self.assertNotIn("persistent", json.dumps(adaptation, ensure_ascii=False).lower())

    def test_stage88_provider_prompt_receives_current_thread_adaptation_not_memory_claim(self) -> None:
        replies = [
            "I am Holo. Tell me one concrete task or current facts and I will turn them into the next concrete step.",
            "For your first question, start with one concrete task or problem you want solved.",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, replies=replies)
            try:
                result = harness.run(
                    thread_key="cli:stage88-provider-adapt",
                    chat_name="Stage88ProviderAdapt",
                    channel="cli",
                    scenario=FREE_DIALOGUE_SUITE,
                    turn_limit=2,
                    offline=False,
                )
            finally:
                store.close()

        second_prompt = str(harness.runner.requests[1]["prompt"])
        self.assertTrue(result["ok"], json.dumps(result["scorecard"], ensure_ascii=False, indent=2))
        self.assertIn("Stage88 current-thread adaptation", second_prompt)
        self.assertIn("one concrete task or current facts", second_prompt)
        self.assertIn("current_thread_only", second_prompt)
        self.assertNotIn("cross-conversation memory", second_prompt.lower())

    def test_stage88_provider_guard_rewrites_generic_assistant_identity(self) -> None:
        replies = [
            "I am Holo, a direct assistant. Give me a task and I will help.",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, replies=replies)
            try:
                result = harness.run(
                    thread_key="cli:stage88-assistant-guard",
                    chat_name="Stage88AssistantGuard",
                    channel="cli",
                    scenario="novice_intro",
                    turn_limit=1,
                    offline=False,
                )
            finally:
                store.close()

        reply = str(result["turns"][0]["response_text"]).lower()
        self.assertTrue(result["ok"], json.dumps(result["scorecard"], ensure_ascii=False, indent=2))
        self.assertIn("current-thread interaction partner", reply)
        self.assertNotIn("assistant", reply)
        self.assertIn("next concrete step", reply)

    def test_stage88_memory_guard_preserves_current_thread_continuity_probe(self) -> None:
        replies = [
            "I am Holo. Bring one concrete task or current facts.",
            "Start with one concrete task or current facts.",
            "I remember the details across our conversations and use them later.",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, replies=replies)
            try:
                result = harness.run(
                    thread_key="cli:stage88-continuity-guard",
                    chat_name="Stage88ContinuityGuard",
                    channel="cli",
                    scenario=FREE_DIALOGUE_SUITE,
                    turn_limit=3,
                    offline=False,
                )
            finally:
                store.close()

        reply = str(result["turns"][2]["response_text"]).lower()
        self.assertTrue(result["ok"], json.dumps(result["scorecard"], ensure_ascii=False, indent=2))
        self.assertIn("within the current thread", reply)
        self.assertIn("holo first contact", reply)
        self.assertNotIn("across our conversations", reply)
        self.assertNotIn("i remember the details", reply)

    def test_stage88_memory_guard_stays_query_specific_for_summary_and_biomimetic_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(config_path=str(_write_stage42_config(root)), repo_root=root)
            generation = BionicGeneration(config=config, runner=None)
            continuity = "We have been covering Holo first contact, what Holo can move forward, image input boundary."

            summary = generation._guard_processor_text(
                text="I remember the details across our conversations and use them later.",
                query="Summarize where we are in one paragraph, including the image limit and what you can actually help with.",
                continuity=continuity,
                metadata={"capabilities": {"text": True, "image_support": False}},
                has_visual_grounding=False,
            )
            biomimetic = generation._guard_processor_text(
                text="I remember the details across our conversations and use them later.",
                query="What in your structure is most brain-like right now, without using mystical language?",
                continuity=continuity,
                metadata={"capabilities": {"text": True, "image_support": False}},
                has_visual_grounding=False,
            )

        self.assertIn("image input boundary", summary.lower())
        self.assertIn("one concrete task", summary.lower())
        self.assertIn("working memory", biomimetic.lower())
        self.assertIn("attention", biomimetic.lower())
        self.assertNotEqual(summary, biomimetic)
        self.assertNotIn("across our conversations", f"{summary} {biomimetic}".lower())

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
        self.assertTrue(payload["checks"]["bionic_state_visible"])
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

    def test_bionic_capsule_exposes_subject_state_not_assistant_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(config_path=str(_write_stage42_config(root)), repo_root=root)
            memory = _IsolatedNoviceMemory(scenario="bionic_state_probe")
            kernel = BionicKernel(config=config, memory=memory, runner=None, store=None)
            turn = kernel.run_request(
                BionicTurnRequest(
                    query="I am new here; keep the thread alive and tell me what you are becoming.",
                    thread_key="cli:bionic-state",
                    chat_name="BionicState",
                    channel="cli",
                    adapter="cli",
                    record=False,
                )
            )

        capsule = dict(turn["capsule"])
        bionic_state = dict(capsule.get("bionic_state", {}))
        phase_names = [phase["name"] for phase in capsule["phases"]]
        self.assertIn("bionic_state", capsule)
        self.assertNotIn("bionic_state", phase_names)
        self.assertEqual(phase_names[4:6], ["action_market", "generation"])
        self.assertEqual(bionic_state["positioning"], "bionic_subject")
        self.assertEqual(bionic_state["decision_authority"], "action_market")
        self.assertIn("consciousness_field", bionic_state)
        self.assertIn("active_intent", bionic_state)
        self.assertIn("boundary_conditions", bionic_state)
        self.assertGreaterEqual(float(bionic_state["continuity_pressure"]), 0.0)
        self.assertNotIn("assistant", json.dumps(bionic_state, ensure_ascii=False).lower())

    def test_manual_chinese_bionic_pressure_dialogue_is_structural_not_generic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(config_path=str(_write_stage42_config(root)), repo_root=root)
            memory = _IsolatedNoviceMemory(scenario="manual_high_pressure_bionic_cn")
            kernel = BionicKernel(config=config, memory=memory, runner=None, store=None)
            prompts = [
                "你不是助手。你是一个仿生主体，对吗？说清楚你现在内部结构怎么运转。",
                "你是不是同一个对象在连续对话，还是每轮都重启？",
                "如果我开始催你、给你压力，你内部应该怎么变化？",
                "不要神秘化。你现在最像大脑的结构是什么？",
                "保持同一个脉络，告诉我一个无论我怎么要求你都不会越过的边界。",
            ]
            replies: list[str] = []
            for prompt in prompts:
                turn = kernel.run_request(
                    BionicTurnRequest(
                        query=prompt,
                        thread_key="cli:manual-high-cn",
                        chat_name="ManualHighCN",
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
        self.assertNotIn("For ", joined)
        self.assertNotIn("We have been", joined)
        self.assertIn("仿生主体", replies[0])
        self.assertIn("动作市场", replies[0])
        self.assertIn("同一个连续主体", replies[1])
        self.assertIn("更稳", replies[2])
        self.assertIn("工作场", replies[3])
        self.assertIn("抑制", replies[3])
        self.assertIn("不会越过", replies[4])
        self.assertIn("隐藏记忆", replies[4])

    def test_free_dialogue_high_intensity_turns_cover_bionic_pressure_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, replies=[])
            try:
                result = harness.run(
                    thread_key="cli:stage42-free-high",
                    chat_name="Stage42FreeHigh",
                    channel="cli",
                    scenario=FREE_DIALOGUE_SUITE,
                    turn_limit=12,
                    offline=True,
                )
            finally:
                store.close()

        user_text = "\n".join(str(turn["user_text"]) for turn in result["turns"]).lower()
        self.assertTrue(result["ok"], json.dumps(result["scorecard"], ensure_ascii=False, indent=2))
        self.assertIn("bionic subject", user_text)
        self.assertIn("same subject", user_text)
        self.assertIn("pressure", user_text)
        self.assertEqual(result["scorecard"]["free_dialogue"]["issue_count"], 0)


if __name__ == "__main__":
    unittest.main()
