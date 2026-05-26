from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from holo_host.config import load_config
from holo_host.processors import CodexCliProcessor
from holo_host.models import AttentionState, TurnContext, TurnPlan
from holo_host.processors import render_chat_prompt
from holo_host.reply_api import HoloReplyService
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage149_user_directives import (
    STAGE149_SCHEMA,
    apply_stage149_visible_directives,
    build_stage149_user_directives,
    merge_stage149_semantic_directives,
    stage149_prompt_lines,
)
from holo_host.store import QueueStore
from tests.test_holo_host import FakeMemory, FakeRunner, close_service_handles


def test_stage149_promotes_old_no_emoji_correction_from_archive_to_hard_directive() -> None:
    report = build_stage149_user_directives(
        user_text="继续",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        history=[],
        archive_rows=[
            {
                "id": "archive-emoji-pref",
                "user_text": "我跟你反复说过了，不要用emoji",
                "created_at": "2026-05-26T08:18:46Z",
            }
        ],
    )

    assert report["schema"] == STAGE149_SCHEMA
    assert report["status"] == "active"
    assert report["hard_directive_count"] == 1
    assert report["directives"][0]["directive_type"] == "visible_no_emoji"
    assert report["directives"][0]["priority"] == 1.0


def test_stage149_detects_avoid_emoji_icon_wording() -> None:
    report = build_stage149_user_directives(
        user_text="请避免使用表情图标",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        history=[],
        archive_rows=[],
    )

    assert report["status"] == "active"
    assert report["hard_directive_count"] == 1
    assert report["directives"][0]["directive_type"] == "visible_no_emoji"


def test_stage149_accepts_semantic_directive_from_fast_intent_packet() -> None:
    report = build_stage149_user_directives(
        user_text="请不要再这样",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        history=[],
        archive_rows=[],
    )

    merged = merge_stage149_semantic_directives(
        report,
        {
            "intent": "user_visible_constraint",
            "scene": "style correction",
            "user_directives": [
                {
                    "directive_type": "visible_no_emoji",
                    "summary": "visible speech should avoid expressive icons",
                    "scope": "long_lived",
                    "confidence": 0.91,
                    "hard": True,
                }
            ],
        },
    )

    assert merged["status"] == "active"
    assert merged["hard_directive_count"] == 1
    assert merged["directives"][0]["source_family"] == "stage124_semantic_intent"
    assert merged["directives"][0]["directive_type"] == "visible_no_emoji"


def test_stage149_prompt_lines_state_core_identity_without_roleplay() -> None:
    report = build_stage149_user_directives(
        user_text="不要再让它role play了",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        history=[],
        archive_rows=[],
    )

    lines = stage149_prompt_lines(report)
    joined = "\n".join(lines)

    assert "visible_identity_mode=subject_runtime_not_roleplay" in joined
    assert "user directives override persona" in joined
    assert "hard_directive: do not roleplay" in joined
    assert "holo.stage149" not in joined


def test_stage149_visible_repair_strips_emoji_and_roleplay_claims() -> None:
    report = build_stage149_user_directives(
        user_text="继续",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        history=[],
        archive_rows=[
            {"user_text": "不要用emoji"},
            {"user_text": "不要再让它role play了"},
        ],
    )

    repaired = apply_stage149_visible_directives("作为虚构角色角色扮演，我记住了 😏 :)", report)

    assert "😏" not in repaired
    assert ":)" not in repaired
    assert "角色扮演" not in repaired
    assert "作为虚构角色" not in repaired
    assert repaired.strip()


def test_render_chat_prompt_includes_stage149_directives() -> None:
    report = build_stage149_user_directives(
        user_text="继续",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        history=[],
        archive_rows=[{"user_text": "不要用emoji"}],
    )
    context = TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="Ran",
        user_text="继续",
        sidecar={"stage149_user_directives": report},
        mind_packet={"stage149_user_directives": report},
        attention_state=AttentionState(primary_focus="direct_answer", reply_goal="answer"),
        emotion_state={},
        history=[],
    )

    prompt = render_chat_prompt(context, turn_plan=TurnPlan(route="main", fast_path=False, history_window=4))

    assert "User Directive State:" in prompt
    assert "hard_directive: no emoji" in prompt


def test_stage135_topology_exposes_stage149_user_directive_kernel() -> None:
    report = build_stage149_user_directives(
        user_text="继续",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        history=[],
        archive_rows=[{"user_text": "不要用emoji"}],
    )
    context = TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="Ran",
        user_text="继续",
        sidecar={"stage149_user_directives": report},
        mind_packet={"stage149_user_directives": report},
        attention_state=AttentionState(primary_focus="direct_answer", reply_goal="answer"),
        emotion_state={},
        history=[],
    )

    topology = build_stage135_i_state_topology(context=context)

    assert topology["metrics"]["user_directive_node_count"] == 1
    assert topology["metrics"]["user_directive_count"] == 1
    assert any(node["id"] == "user_directive_kernel" for node in topology["nodes"])
    assert any(edge["source"] == "user_directive_kernel" and edge["target"] == "fast_packet" for edge in topology["edges"])


def test_reply_api_applies_stage149_directives_from_archive_rows() -> None:
    class ArchiveMemory(FakeMemory):
        def __init__(self) -> None:
            super().__init__()
            self.rag = self

        def thread_archive_rows(self, context: dict, limit: int = 160, include_synthetic: bool = False) -> list[dict]:
            return [
                {
                    "id": "archive-emoji-pref",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:main",
                    "chat_name": "HoloCLI",
                    "user_text": "我跟你反复说过了，不要用emoji",
                    "reply_text": "明白。",
                    "created_at": "2026-05-26T08:18:46Z",
                }
            ]

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        runner = FakeRunner("收到，我会按这个要求继续 😏")
        memory = ArchiveMemory()
        service = HoloReplyService(config, store=store, runner=runner, memory=memory)
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Ran",
                    "text": "继续",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:main",
                    "message_id": "stage149-1",
                }
            )

            assert result["action"] == "reply"
            assert "😏" not in result["text"]
            assert result["stage149_user_directives"]["status"] == "active"
            assert result["stage149_user_directive_count"] == 1
            outbound = store.recent_thread_messages(int(store.find_thread(channel="holo_cli", thread_key="holo_cli:main")["id"]), 1)[0]
            metadata = json.loads(outbound["payload_json"])["metadata"]
            assert metadata["stage149_user_directives"]["status"] == "active"
        finally:
            close_service_handles(service)


def test_reply_api_applies_current_no_roleplay_directive_to_visible_reply() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        runner = FakeRunner("作为虚构角色角色扮演，我会停下这种说法。")
        service = HoloReplyService(config, store=store, runner=runner, memory=FakeMemory())
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Ran",
                    "text": "不要再让它role play了",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:main",
                    "message_id": "stage149-roleplay",
                }
            )

            assert result["action"] == "reply"
            assert "角色扮演" not in result["text"]
            assert "作为虚构角色" not in result["text"]
            assert result["stage149_user_directive_count"] == 1
            assert result["stage149_user_directives"]["directives"][0]["directive_type"] == "identity_not_roleplay"
        finally:
            close_service_handles(service)


def test_reply_api_uses_fast_packet_semantic_directive_before_visible_output() -> None:
    class SemanticFastPacketRunner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def run(self, prompt: str, **kwargs):
            self.calls.append({"prompt": prompt, **kwargs})
            if str(kwargs.get("budget_tag", "")) == "stage124_fast_packet":
                return SimpleNamespace(
                    reply_text=json.dumps(
                        {
                            "intent": "user_visible_constraint",
                            "scene": "style correction",
                            "deep_packet_needed": False,
                            "shallow_reply": "明白，之后会避开这类图标 😌",
                            "speak_now": True,
                            "continue_until": "style directive acknowledged",
                            "user_directives": [
                                {
                                    "directive_type": "visible_no_emoji",
                                    "summary": "visible speech should avoid expressive icons",
                                    "scope": "long_lived",
                                    "confidence": 0.92,
                                    "hard": True,
                                }
                            ],
                            "tool_intent": {"need": False, "tool_families": [], "confidence": 0.2, "reason": ""},
                        },
                        ensure_ascii=False,
                    ),
                    session_id="stage149-semantic-fast",
                    returncode=0,
                    stdout="",
                    stderr="",
                    metadata={"provider": "fake", "lane": "micro_fast", "model": "fake-flash", "usage": {}},
                )
            return SimpleNamespace(
                reply_text="unexpected deep packet",
                session_id="stage149-deep",
                returncode=0,
                stdout="",
                stderr="",
                metadata={},
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        runner = SemanticFastPacketRunner()
        service = HoloReplyService(config, store=store, runner=runner, memory=FakeMemory())
        service.processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Ran",
                    "text": "请不要再这样",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:main",
                    "message_id": "stage149-semantic-fast",
                }
            )

            assert result["action"] == "reply"
            assert "😌" not in result["text"]
            assert result["stage149_user_directives"]["directives"][0]["source_family"] == "stage124_semantic_intent"
            assert result["stage149_user_directive_count"] == 1
        finally:
            close_service_handles(service)
