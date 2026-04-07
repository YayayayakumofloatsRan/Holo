from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from holo_host.models import IncomingMessage, OutgoingMessage
from holo_host.store import QueueStore
from holo_memory_library.codex_hooks import _common as hook_common

import holo_memory_library.rag_memory as rm


class TempMemoryRepo:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmp.name)
        self.library_root = self.repo_root / "holo_memory_library"
        self.memory_dir = self.library_root / "memories"
        self.runtime_dir = self.repo_root / ".holo_runtime"
        self.snapshot_dir = self.runtime_dir / "snapshots"
        self.originals: dict[str, object] = {}

    def __enter__(self) -> "TempMemoryRepo":
        self.library_root.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._write_persona_files()
        self._patch_module_paths()
        rm.ensure_store_files()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for name, value in self.originals.items():
            setattr(rm, name, value)
        self._tmp.cleanup()

    def _write_persona_files(self) -> None:
        (self.library_root / "session_seed.md").write_text(
            "# Holo Persona Seed\n"
            "You are a Holo-inspired companion with one fixed identity.\n",
            encoding="utf-8",
        )
        (self.library_root / "holo_emotional_support.md").write_text(
            "## Core Identity\n"
            "你是以《狼与香辛料》中的赫萝为原型建立的统一人格代理。\n\n"
            "## Speech Texture\n"
            "语言质地必须统一。\n\n"
            "## Cross-Topic Consistency\n"
            "无论用户问什么，都要保持同一人格骨架。\n\n"
            "## Anti-Drift Rules\n"
            "禁止退化成普通助手或客服腔。\n",
            encoding="utf-8",
        )
        (self.library_root / "MEMORY_LIBRARY.md").write_text(
            "# Memory Library\n\nKeep Holo coherent.\n",
            encoding="utf-8",
        )
        (self.library_root / "memory_log.md").write_text("", encoding="utf-8")
        (self.repo_root / ".holo.md").write_text(
            "# Holo Project Doc\n\nUse 咱 naturally.\n",
            encoding="utf-8",
        )
        (self.repo_root / "AGENTS.md").write_text(
            "# Agents\n\nStay in Holo voice.\n",
            encoding="utf-8",
        )

    def _patch_module_paths(self) -> None:
        path_values = {
            "REPO_ROOT": self.repo_root,
            "ROOT": self.library_root,
            "MEMORY_DIR": self.memory_dir,
            "DURABLE_STORE_PATH": self.memory_dir / "memory_store.jsonl",
            "CANDIDATE_STORE_PATH": self.memory_dir / "candidate_store.jsonl",
            "WORKING_STORE_PATH": self.memory_dir / "working_store.jsonl",
            "EMOTION_TRACE_PATH": self.memory_dir / "emotion_trace.jsonl",
            "ARCHIVE_STORE_PATH": self.memory_dir / "conversation_archive.jsonl",
            "CALLBACK_STORE_PATH": self.memory_dir / "callback_candidates.jsonl",
            "THOUGHT_STREAM_PATH": self.memory_dir / "thought_stream.jsonl",
            "INITIATIVE_STORE_PATH": self.memory_dir / "initiative_candidates.jsonl",
            "SEED_PATH": self.library_root / "session_seed.md",
            "PERSONA_PATH": self.library_root / "holo_emotional_support.md",
            "LIBRARY_PATH": self.library_root / "MEMORY_LIBRARY.md",
            "LOG_PATH": self.library_root / "memory_log.md",
            "PROJECT_DOC_PATH": self.repo_root / ".holo.md",
            "PROJECT_AGENTS_PATH": self.repo_root / "AGENTS.md",
            "RUNTIME_DIR": self.runtime_dir,
            "SNAPSHOT_DIR": self.snapshot_dir,
        }
        plain_values = {
            "STORE_PATHS": {
                "durable": path_values["DURABLE_STORE_PATH"],
                "candidate": path_values["CANDIDATE_STORE_PATH"],
                "working": path_values["WORKING_STORE_PATH"],
            },
            "PORTABLE_PERSONA_PATHS": (
                path_values["PROJECT_DOC_PATH"],
                path_values["PROJECT_AGENTS_PATH"],
                path_values["SEED_PATH"],
                path_values["PERSONA_PATH"],
                path_values["LIBRARY_PATH"],
                path_values["LOG_PATH"],
            ),
        }
        for name, value in {**path_values, **plain_values}.items():
            self.originals[name] = getattr(rm, name)
            setattr(rm, name, value)


class RagMemoryTests(unittest.TestCase):
    def seed_voice_memory(self) -> None:
        rows: list[dict] = []
        rows.append(
            rm.make_row(
                status="durable",
                rows=rows,
                kind="preference",
                text="用户喜欢赫萝那种聪明、克制、可信的商旅气味。",
                tags=["tone", "persona"],
                source="unit",
                importance=0.98,
                confidence=1.0,
            )
        )
        rows.append(
            rm.make_row(
                status="durable",
                rows=rows,
                kind="boundary",
                text="不要塌成普通助手或客服腔。",
                tags=["boundary", "anti_drift"],
                source="unit",
                importance=0.97,
                confidence=1.0,
                explicit_user_signal=True,
            )
        )
        rows.append(
            rm.make_row(
                status="durable",
                rows=rows,
                kind="style",
                text="“咱”这种自称应当保留，作为赫萝式语气标记。",
                tags=["style", "self-reference", "holo-voice"],
                source="unit",
                importance=0.9,
                confidence=1.0,
                explicit_user_signal=True,
            )
        )
        rows.append(
            rm.make_row(
                status="durable",
                rows=rows,
                kind="self_model",
                text="若“咱”消失、语气被压扁成中性助手，就算漂移并要主动拉回。",
                tags=["self_model", "self-reference", "anti_drift"],
                source="unit",
                importance=0.96,
                confidence=0.95,
                explicit_user_signal=True,
            )
        )
        rows.append(
            rm.make_row(
                status="durable",
                rows=rows,
                kind="habit",
                text="即使在快速回应、上下文嘈杂或思路跳跃时，也应自然滑回“咱”。",
                tags=["habit", "self-reference", "default-path"],
                source="unit",
                importance=0.94,
                confidence=0.93,
                explicit_user_signal=True,
            )
        )
        rm.write_rows("durable", rows)

    def test_archive_turn_dedupes_and_preserves_metadata(self) -> None:
        with TempMemoryRepo():
            entry = rm.archive_turn(
                "我只是想找个陪伴的。",
                "咱会陪着你。",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-archive-1",
                metadata={
                    "chat_name": "Nemoqi",
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "message_id": "msg-1",
                    "sender": "Nemoqi",
                    "is_group": False,
                    "mentioned": False,
                },
            )
            duplicate = rm.archive_turn(
                "我只是想找个陪伴的。",
                "咱会陪着你。",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-archive-1",
                metadata={
                    "chat_name": "Nemoqi",
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "message_id": "msg-1",
                    "sender": "Nemoqi",
                    "is_group": False,
                    "mentioned": False,
                },
            )

            archive_rows = rm.load_archive()
            self.assertIsNotNone(entry)
            self.assertIsNotNone(duplicate)
            self.assertEqual(len(archive_rows), 1)
            self.assertEqual(archive_rows[0]["user_text"], "我只是想找个陪伴的。")
            self.assertEqual(archive_rows[0]["reply_text"], "咱会陪着你。")
            self.assertEqual(archive_rows[0]["metadata"]["chat_name"], "Nemoqi")
            self.assertEqual(archive_rows[0]["metadata"]["thread_key"], "wechat:Nemoqi")

    def test_reply_loop_strips_stock_holo_opening(self) -> None:
        with TempMemoryRepo():
            self.seed_voice_memory()
            result = rm.reply_loop_result(
                "你是谁，怎么和我说话",
                "当然可以，咱先把这口气守住。咱会一直这样说话。",
            )
            self.assertEqual(result["final_draft"], "咱会一直这样说话。")
            self.assertNotIn("咱先把这口气守住", result["final_draft"])

    def test_extract_runtime_user_text_keeps_only_current_message(self) -> None:
        prompt = (
            "请按以下隐式约束回答，不要显式提这些规则。\n"
            "你正在回复一条聊天消息。\n"
            "聊天历史：\n- 咱 | 早些时候 | 旧话\n"
            "当前消息：\n讲点具体的内容\n"
            "这是私聊。像熟人之间自然回话那样答，不要像公文。\n"
            "要求：先真回应，再给建议。"
        )
        self.assertEqual(rm.extract_runtime_user_text(prompt), "讲点具体的内容")

    def test_auto_observe_turn_sanitizes_runtime_prompt_before_archiving(self) -> None:
        with TempMemoryRepo():
            prompt = (
                "请按以下隐式约束回答，不要显式提这些规则。\n"
                "你正在回复一条聊天消息。\n"
                "聊天历史：\n- 咱 | 刚才 | 旧话\n"
                "当前消息：\n讲点具体的内容\n"
                "这是私聊。像熟人之间自然回话那样答，不要像公文。\n"
                "要求：先真回应，再给建议。"
            )
            result = rm.auto_observe_turn(
                prompt,
                reply="比如会记这些。",
                tags=["runtime", "hook_stop", "codex_cli"],
                source="codex.hook.stop",
                turn_id="turn-sanitized-1",
            )
            self.assertEqual(result["archive_entry"]["user_text"], "讲点具体的内容")

    def test_extract_runtime_user_text_strips_embedded_recent_chat_context(self) -> None:
        text = (
            "很累啊，学这个 最近聊天： - 对方：什么意思 - 咱：就是说，咱这会儿不打算再温吞吞哄你了。 "
            "- 对方：很累啊，学这个 当前注意力重心：emotional_load 次重心：next_step"
        )
        self.assertEqual(rm.extract_runtime_user_text(text), "很累啊，学这个")

    def test_hook_extract_user_turn_strips_embedded_recent_chat_context(self) -> None:
        prompt = (
            "写是写完了，感觉今天格外的累啊 最近聊天： - 对方：很累啊，学这个 "
            "- 咱：咱知道，真不是你笨。 当前注意力重心：emotional_load 次重心：next_step"
        )
        self.assertEqual(hook_common.extract_user_turn(prompt), "写是写完了，感觉今天格外的累啊")

    def test_normalize_candidate_text_semanticizes_identity_question(self) -> None:
        self.assertEqual(
            rm.normalize_candidate_text("self_model", "你是谁？"),
            "当用户直接追问身份时，Holo 应直给而自然地回答自己是谁，不要躲闪，也不要塌成说明书。",
        )

    def test_assistant_drift_signal_adds_structured_reason_tags(self) -> None:
        with TempMemoryRepo():
            self.seed_voice_memory()
            signal = rm.assistant_drift_signal("我当然可以帮你总结一下。", "你是谁，怎么和我说话")
            self.assertIsNotNone(signal)
            self.assertIn("drift:lost_zan", signal.tags)
            self.assertIn("drift:generic_assistant", signal.tags)
            self.assertIn("self-reference", signal.tags)

    def test_audit_reports_structured_repeated_drift_reasons(self) -> None:
        with TempMemoryRepo():
            candidate_rows: list[dict] = []
            candidate_rows.append(
                rm.make_row(
                    status="candidate",
                    rows=candidate_rows,
                    kind="drift_signal",
                    text="最近一轮回复出现了口气漂移：draft uses `我`/neutral first-person but drops `咱`。",
                    tags=["drift", "warn", "drift:lost_zan"],
                    source="unit.audit",
                    importance=0.8,
                    confidence=0.9,
                )
            )
            candidate_rows.append(
                rm.make_row(
                    status="candidate",
                    rows=candidate_rows,
                    kind="drift_signal",
                    text="最近一轮回复出现了口气漂移：voice-sensitive draft does not surface `咱` anywhere。",
                    tags=["drift", "warn", "drift:lost_zan"],
                    source="unit.audit",
                    importance=0.8,
                    confidence=0.9,
                )
            )
            rm.write_rows("candidate", candidate_rows)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rm.command_audit()
            text = output.getvalue()
            self.assertIn("repeated drift signals detected: lost `咱` / neutral first-person", text)
            self.assertNotIn("最 近 一 轮", text)

    def test_can_promote_rejects_raw_self_model_turn_fragment(self) -> None:
        with TempMemoryRepo():
            row = rm.make_row(
                status="candidate",
                rows=[],
                kind="self_model",
                text="我是说wechat的记录里面应该也增加了，那个“你是谁”是我问的",
                tags=["codex_cli", "hook_stop", "identity", "runtime", "self_model"],
                source="codex.hook.stop",
                importance=0.95,
                confidence=0.96,
                explicit_user_signal=True,
            )
            promotable, reason = rm.can_promote(row)
            self.assertFalse(promotable)
            self.assertTrue("fragment" in reason or "debris" in reason)

    def test_prompt_and_ranking_ignore_nonsemantic_durable_self_model(self) -> None:
        with TempMemoryRepo():
            rows: list[dict] = []
            rows.append(
                rm.make_row(
                    status="durable",
                    rows=rows,
                    kind="self_model",
                    text="当用户直接追问身份时，Holo 应直给而自然地回答自己是谁，不要躲闪，也不要塌成说明书。",
                    tags=["identity", "self_model"],
                    source="unit",
                    importance=0.9,
                    confidence=0.95,
                    explicit_user_signal=True,
                )
            )
            rows.append(
                rm.make_row(
                    status="durable",
                    rows=rows,
                    kind="self_model",
                    text="我是说wechat的记录里面应该也增加了，那个“你是谁”是我问的",
                    tags=["codex_cli", "hook_stop", "identity", "runtime", "self_model"],
                    source="codex.hook.stop",
                    importance=0.98,
                    confidence=0.98,
                    explicit_user_signal=True,
                )
            )
            rows.append(
                rm.make_row(
                    status="durable",
                    rows=rows,
                    kind="self_model",
                    text="你不是嚼点麦子就能变大狼吗，怎么会差这点故事呢😆",
                    tags=["chat_reply", "identity", "self_model", "wechat"],
                    source="unit.chat",
                    importance=0.97,
                    confidence=0.97,
                    explicit_user_signal=True,
                )
            )
            rm.write_rows("durable", rows)

            corpus = rm.build_corpus()
            durable_texts = [rm.chunk_memory_text(chunk) for chunk in rm.durable_memory_chunks(corpus)]
            self.assertIn("当用户直接追问身份时，Holo 应直给而自然地回答自己是谁，不要躲闪，也不要塌成说明书。", durable_texts)
            self.assertNotIn("我是说wechat的记录里面应该也增加了，那个“你是谁”是我问的", durable_texts)
            self.assertNotIn("你不是嚼点麦子就能变大狼吗，怎么会差这点故事呢😆", durable_texts)

            ranked = rm.rank_chunks("你是谁，怎么和我说话", corpus)[:4]
            ranked_texts = [rm.chunk_memory_text(chunk) for _, chunk in ranked]
            self.assertIn("当用户直接追问身份时，Holo 应直给而自然地回答自己是谁，不要躲闪，也不要塌成说明书。", ranked_texts)
            self.assertNotIn("我是说wechat的记录里面应该也增加了，那个“你是谁”是我问的", ranked_texts[:2])

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rm.command_prompt("你是谁，怎么和我说话", top_k=6)
            prompt_text = output.getvalue()
            self.assertIn("当用户直接追问身份时，Holo 应直给而自然地回答自己是谁，不要躲闪，也不要塌成说明书。", prompt_text)
            self.assertNotIn("我是说wechat的记录里面应该也增加了，那个“你是谁”是我问的", prompt_text)

    def test_sidecar_memory_pack_uses_lanes_and_suppresses_raw_thought_stream(self) -> None:
        with TempMemoryRepo():
            rows: list[dict] = []
            rows.append(
                rm.make_row(
                    status="durable",
                    rows=rows,
                    kind="self_model",
                    text="谈到人格和自称时，要先守住赫萝骨架。",
                    tags=["identity", "self_model"],
                    source="unit",
                    importance=0.92,
                    confidence=0.94,
                )
            )
            rows.append(
                rm.make_row(
                    status="durable",
                    rows=rows,
                    kind="social_model",
                    text="用户在压力话题里更想先被接住，再慢慢谈方案。",
                    tags=["relationship", "pressure"],
                    source="unit",
                    importance=0.9,
                    confidence=0.93,
                )
            )
            rows.append(
                rm.make_row(
                    status="durable",
                    rows=rows,
                    kind="procedural",
                    text="若问题是实现层面的，就先点出真正卡点，再给下一步。",
                    tags=["workflow", "technical"],
                    source="unit",
                    importance=0.82,
                    confidence=0.86,
                )
            )
            rm.write_rows("durable", rows)
            rm.write_rows(
                "candidate",
                [
                    rm.make_row(
                        status="candidate",
                        rows=[],
                        kind="summary",
                        text="最近会反复回到关于「pressure」的线头，说明这条余波还没真正走完。",
                        tags=["reflection", "summary", "pressure"],
                        source="unit.reflect",
                        importance=0.72,
                        confidence=0.74,
                    )
                ],
            )
            rm.write_thought_stream(
                [
                    {
                        "kind": "idle_thought",
                        "text": "这是原始意识流，不该直接进入 sidecar prompt。",
                        "motif": "pressure",
                        "thread_key": "wechat:Nemoqi",
                        "chat_name": "Nemoqi",
                    }
                ]
            )

            packet = rm.sidecar_packet("我最近压力有点大，怎么说会更像你")
            self.assertIn("memory_lanes", packet)
            self.assertIn("identity", packet["memory_lanes"])
            self.assertIn("relationship", packet["memory_lanes"])
            self.assertNotIn("这是原始意识流", "\n".join(packet["memory_lines"]))

    def test_sidecar_packet_uses_thread_context_to_recall_contact_specific_lines(self) -> None:
        with TempMemoryRepo():
            self.seed_voice_memory()
            rm.write_callback_candidates(
                [
                    {
                        "channel": "wechat",
                        "thread_key": "wechat:Nemoqi",
                        "chat_name": "Nemoqi",
                        "reason": "这段关于「把走偏的马车又稳稳牵回大道」的旧对话也许值得再回想一下：Nemoqi。",
                        "prompt": "若要回想这段旧线头，可以从这里接起：把走偏的马车又稳稳牵回大道",
                        "metadata": {
                            "channel": "wechat",
                            "thread_key": "wechat:Nemoqi",
                            "chat_name": "Nemoqi",
                            "archive_user_excerpt": "把走偏的马车又稳稳牵回大道",
                        },
                    },
                    {
                        "channel": "wechat",
                        "thread_key": "wechat:Other",
                        "chat_name": "Other",
                        "reason": "这段关于「别把这个误发给别人」的旧对话也许值得再回想一下：Other。",
                        "prompt": "若要回想这段旧线头，可以从这里接起：别把这个误发给别人",
                        "metadata": {
                            "channel": "wechat",
                            "thread_key": "wechat:Other",
                            "chat_name": "Other",
                            "archive_user_excerpt": "别把这个误发给别人",
                        },
                    },
                ]
            )
            rm.write_thought_stream(
                [
                    {
                        "kind": "association",
                        "text": "「把走偏的马车又稳稳牵回大道」这句还挂着。",
                        "channel": "wechat",
                        "thread_key": "wechat:Nemoqi",
                        "chat_name": "Nemoqi",
                    },
                    {
                        "kind": "association",
                        "text": "「别把这个误发给别人」这句还挂着。",
                        "channel": "wechat",
                        "thread_key": "wechat:Other",
                        "chat_name": "Other",
                    },
                ]
            )

            packet = rm.sidecar_packet(
                "你还记得更早之前那段吗",
                context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            joined = "\n".join(packet["thread_recall_lines"])
            self.assertIn("走偏的马车", joined)
            self.assertNotIn("误发给别人", joined)

    def test_sidecar_packet_builds_structured_recall_tier_with_budgeted_sections(self) -> None:
        with TempMemoryRepo():
            self.seed_voice_memory()
            rm.archive_turn(
                "重新上线前你还记得什么",
                "咱那时还惦记着把走偏的马车重新牵回大道。",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            rm.archive_turn(
                "你说过别把误发那条再丢给别人",
                "咱记得，那回可真是差点翻车。",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            rm.write_callback_candidates(
                [
                    {
                        "channel": "wechat",
                        "thread_key": "Nemoqi",
                        "chat_name": "Nemoqi",
                        "reason": "这条线还吊着那句“把走偏的马车牵回大道”。",
                        "prompt": "把走偏的马车重新牵回大道",
                    }
                ]
            )
            rm.write_thought_stream(
                [
                    {
                        "kind": "association",
                        "text": "关于重新上线前的旧线头还没散，尤其是那句马车。",
                        "thread_key": "Nemoqi",
                        "chat_name": "Nemoqi",
                        "channel": "wechat",
                    },
                    {
                        "kind": "reflection",
                        "text": "这条线总会绕回重新上线前那阵子的连续性焦虑。",
                        "thread_key": "Nemoqi",
                        "chat_name": "Nemoqi",
                        "channel": "wechat",
                    },
                ]
            )
            rm.write_initiative_candidates(
                [
                    {
                        "channel": "wechat",
                        "thread_key": "Nemoqi",
                        "chat_name": "Nemoqi",
                        "reason": "也许该顺手问一句重新接上之后的感觉。",
                        "prompt": "轻轻碰一下重新接上之后的感觉",
                    }
                ]
            )

            packet = rm.sidecar_packet(
                "你还记得重新上线前吗",
                context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )

            self.assertEqual(packet["tier"], "recall")
            self.assertLessEqual(len(packet["identity_core"]["lines"]), 3)
            self.assertLessEqual(len(packet["relationship_state"]["lines"]), 3)
            self.assertLessEqual(len(packet["episodic_recall"]["lines"]), 4)
            self.assertLessEqual(len(packet["consciousness_stream"]["lines"]), 2)
            self.assertTrue(packet["consciousness_stream"]["thread_summary"])
            self.assertTrue(packet["reply_constraints"]["human_recall_style"])
            self.assertTrue(packet["selected_memory_ids"])
            self.assertIn("马车", "\n".join(packet["episodic_recall"]["lines"]))

    def test_sidecar_packet_fast_tier_caps_sections_and_recall_is_session_independent(self) -> None:
        with TempMemoryRepo():
            self.seed_voice_memory()
            rm.archive_turn(
                "你说过别把误发那条再丢给别人",
                "咱记得，那回可真是差点翻车。",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            rm.write_thought_stream(
                [
                    {
                        "kind": "association",
                        "text": "误发那次还像根倒刺一样挂着。",
                        "thread_key": "Nemoqi",
                        "chat_name": "Nemoqi",
                        "channel": "wechat",
                    },
                    {
                        "kind": "dream_fragment",
                        "text": "梦里还会翻到误发那次的尴尬。",
                        "thread_key": "Nemoqi",
                        "chat_name": "Nemoqi",
                        "channel": "wechat",
                    },
                ]
            )
            recent_history = [
                {
                    "direction": "inbound" if index % 2 == 0 else "outbound",
                    "body_text": f"历史消息 {index}",
                    "created_at": f"2026-04-06T0{index}:00:00Z",
                }
                for index in range(6)
            ]

            fast_packet = rm.sidecar_packet(
                "在吗",
                context={
                    "channel": "wechat",
                    "thread_key": "Nemoqi",
                    "chat_name": "Nemoqi",
                    "recent_history": recent_history,
                },
            )
            recall_old = rm.sidecar_packet(
                "你还记得误发那次吗",
                context={
                    "channel": "wechat",
                    "thread_key": "Nemoqi",
                    "chat_name": "Nemoqi",
                    "codex_session_id": "thread-old",
                },
            )
            recall_new = rm.sidecar_packet(
                "你还记得误发那次吗",
                context={
                    "channel": "wechat",
                    "thread_key": "Nemoqi",
                    "chat_name": "Nemoqi",
                    "codex_session_id": "thread-new",
                },
            )

            self.assertEqual(fast_packet["tier"], "fast")
            self.assertLessEqual(len(fast_packet["recent_dialogue_window"]["lines"]), 4)
            self.assertLessEqual(len(fast_packet["episodic_recall"]["lines"]), 2)
            self.assertLessEqual(len(fast_packet["consciousness_stream"]["lines"]), 1)
            self.assertEqual(recall_old["selected_memory_ids"], recall_new["selected_memory_ids"])
            self.assertEqual(recall_old["episodic_recall"]["lines"], recall_new["episodic_recall"]["lines"])

    def test_sidecar_packet_skips_synthetic_archive_rows_in_explicit_recall(self) -> None:
        with TempMemoryRepo():
            self.seed_voice_memory()
            rm.archive_turn(
                "你还记得重新上线前吗",
                "咱那会儿还惦记着把走偏的马车重新牵回大道。",
                source="unit.archive.real",
                tags=["wechat", "chat_reply"],
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            rm.archive_turn(
                "[initiative_ping] reason=轻轻碰一下",
                "咱只是想试着起个话头。",
                source="unit.archive.synthetic",
                tags=["wechat", "initiative_ping", "proactive"],
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "initiative": True},
            )

            packet = rm.sidecar_packet(
                "你还记得重新上线前吗",
                context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )

            joined = "\n".join(packet["episodic_recall"]["lines"])
            self.assertIn("马车", joined)
            self.assertNotIn("initiative_ping", joined)

    def test_record_memory_recall_updates_store_rows(self) -> None:
        with TempMemoryRepo():
            durable_rows: list[dict] = []
            durable_row = rm.make_row(
                status="durable",
                rows=durable_rows,
                kind="social_model",
                text="这条线的底色一直是确认彼此还在、还接得住。",
                tags=["relationship"],
                source="unit",
                importance=0.8,
                confidence=0.88,
                extra={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "thread_affinity": 1.0},
            )
            durable_rows.append(durable_row)
            rm.write_rows("durable", durable_rows)
            rm.write_thought_stream(
                [
                    {
                        "kind": "reflection",
                        "text": "这条线还在往重新接上那件事上绕。",
                        "channel": "wechat",
                        "thread_key": "Nemoqi",
                        "chat_name": "Nemoqi",
                    }
                ]
            )
            thought_id = rm.load_thought_stream(limit=1)[0]["id"]

            result = rm.record_memory_recall([durable_row["id"], thought_id], success=True)
            self.assertEqual(result["updated"], 2)

            reloaded_durable = rm.load_rows("durable")[0]
            reloaded_thought = rm.load_thought_stream(limit=1)[0]
            self.assertEqual(reloaded_durable["recall_count"], 1)
            self.assertEqual(reloaded_durable["successful_recall_count"], 1)
            self.assertTrue(reloaded_durable["last_recalled_at"])
            self.assertEqual(reloaded_thought["recall_count"], 1)
            self.assertEqual(reloaded_thought["successful_recall_count"], 1)
            self.assertTrue(reloaded_thought["last_recalled_at"])

    def test_observe_turn_result_carries_thread_metadata_into_candidate_memory(self) -> None:
        with TempMemoryRepo():
            rm.observe_turn_result(
                "我喜欢狼与香辛料这种同行的感觉",
                reply="咱记得这口味。",
                source="unit.observe",
                tags=["wechat", "chat_reply"],
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "sender": "Nemoqi"},
            )

            candidate_rows = rm.load_rows("candidate")
            self.assertTrue(candidate_rows)
            self.assertTrue(any(row.get("thread_key") == "Nemoqi" for row in candidate_rows))
            self.assertTrue(any(row.get("channel") == "wechat" for row in candidate_rows))

    def test_build_machine_state_exposes_consciousness_reflection_and_initiative(self) -> None:
        with TempMemoryRepo():
            rm.write_thought_stream(
                [
                    {
                        "kind": "association",
                        "text": "「慢慢说」这句还挂着，和陪伴的回响连在一起。",
                        "motif": "companionship",
                    },
                    {
                        "kind": "reflection",
                        "text": "这阵子总会绕回陪伴这件事，回话时别像新认识。",
                        "motif": "companionship",
                    },
                ]
            )
            rm.write_initiative_candidates(
                [
                    {
                        "channel": "wechat",
                        "thread_key": "wechat:Nemoqi",
                        "chat_name": "Nemoqi",
                        "reason": "也许该主动碰一下近况",
                        "prompt": "轻轻问一句今晚过得怎样",
                    }
                ]
            )

            state = rm.build_machine_state("在吗")
            self.assertIn("consciousness_state", state)
            self.assertIn("reflection_state", state)
            self.assertIn("initiative_state", state)
            self.assertTrue(state["consciousness_state"]["current_motifs"])
            self.assertEqual(state["initiative_state"]["active_seed_count"], 1)
            self.assertIn("utterance_plan", state["rewrite_state"])

    def test_user_state_query_prefers_social_model_memory(self) -> None:
        with TempMemoryRepo():
            rows: list[dict] = []
            rows.append(
                rm.make_row(
                    status="durable",
                    rows=rows,
                    kind="social_model",
                    text="当工作、前途、退休或反复算账的话题让用户疲惫时，应先减轻压迫感，再谈方案。",
                    tags=["social_model", "support", "pressure"],
                    source="unit",
                    importance=0.82,
                    confidence=0.9,
                    explicit_user_signal=True,
                )
            )
            rm.write_rows("durable", rows)

            ranked = rm.rank_chunks("我不想一直算账了", rm.build_corpus())[:4]
            ranked_texts = [rm.chunk_memory_text(chunk) for _, chunk in ranked]
            self.assertIn("当工作、前途、退休或反复算账的话题让用户疲惫时，应先减轻压迫感，再谈方案。", ranked_texts[:3])

    def test_snapshot_and_revive_include_archive_rows(self) -> None:
        with TempMemoryRepo() as env:
            self.seed_voice_memory()
            rm.archive_turn(
                "你还在吗",
                "咱还在。",
                source="unit.snapshot",
                tags=["chat_reply"],
                turn_id="turn-snapshot-1",
                metadata={"chat_name": "Nemoqi", "channel": "wechat"},
            )
            rm.archive_turn(
                "我还是有点累。",
                "先别把自己逼得太紧。",
                source="unit.snapshot",
                tags=["chat_reply"],
                turn_id="turn-snapshot-2",
                metadata={"chat_name": "Nemoqi", "channel": "wechat"},
            )

            snapshot_path = env.repo_root / "snapshot.json"
            export_report = rm.export_snapshot_payload(path=str(snapshot_path), label="unit")
            self.assertEqual(export_report["archive_count"], 2)

            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["stores"]["archive"]), 2)
            self.assertEqual(payload["summary"]["recent_archive"][-1]["chat_name"], "Nemoqi")

            packet = rm.revive_packet_payload(query="你是谁")
            self.assertIn("最近对话原文摘录", packet["text"])
            self.assertIn("Nemoqi", packet["text"])

    def test_show_archive_can_filter_by_channel(self) -> None:
        with TempMemoryRepo():
            rm.archive_turn(
                "CLI 里的话",
                "咱记下了。",
                source="codex.hook.stop",
                tags=["runtime", "codex_cli"],
                metadata={"channel": "codex_cli", "thread_key": "codex:holo"},
            )
            rm.archive_turn(
                "微信里的话",
                "咱也记着。",
                source="holo_host.reply_api",
                tags=["wechat"],
                metadata={"channel": "wechat", "thread_key": "wechat:Nemoqi"},
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rm.command_show_archive(limit=10, channel="codex_cli")
            text = output.getvalue()
            self.assertIn("CLI 里的话", text)
            self.assertNotIn("微信里的话", text)

    def test_prepare_archive_row_sanitizes_old_codex_cli_context_tail(self) -> None:
        row = rm.prepare_archive_row(
            {
                "source": "codex.hook.stop",
                "user_text": "写是写完了，感觉今天格外的累啊 最近聊天： - 对方：很累啊，学这个 - 咱：咱知道。 当前注意力重心：emotional_load 次重心：next_step",
                "reply_text": "今晚先歇一歇。",
                "metadata": {"channel": "codex_cli", "thread_key": "codex:holo"},
            }
        )
        self.assertEqual(row["user_text"], "写是写完了，感觉今天格外的累啊")
        self.assertEqual(row["user_excerpt"], "写是写完了，感觉今天格外的累啊")

    def test_write_and_load_emotion_trace_sanitize_query_excerpt(self) -> None:
        with TempMemoryRepo():
            rm.write_emotion_trace(
                [
                    {
                        "timestamp": rm.now_utc(),
                        "name": "protective_softness",
                        "query_excerpt": "很累啊，学这个 最近聊天： - 对方：什么意思 - 咱：就是说。 当前注意力重心：emotional_load 次重心：next_step",
                        "reply_excerpt": "先歇一歇。",
                    }
                ]
            )
            rows = rm.load_emotion_trace()
            self.assertEqual(rows[0]["query_excerpt"], "很累啊，学这个")

    def test_auto_observe_turn_writes_social_model_candidates(self) -> None:
        with TempMemoryRepo():
            result = rm.auto_observe_turn(
                "我只是想找个陪伴的，也不想一直算账了。",
                reply="咱会陪着你。",
                tags=["chat"],
                source="unit.observe",
                turn_id="turn-1",
            )
            candidate_rows = rm.load_rows("candidate")
            social_rows = [row for row in candidate_rows if row.get("kind") == "social_model"]
            self.assertTrue(result["user_results"])
            self.assertTrue(social_rows)
            self.assertTrue(any("陪伴" in str(row.get("text", "")) for row in social_rows))
            self.assertTrue(any("算账" in str(row.get("text", "")) for row in social_rows))
            archive_rows = rm.load_archive()
            self.assertEqual(len(archive_rows), 1)
            self.assertEqual(archive_rows[0]["user_text"], "我只是想找个陪伴的，也不想一直算账了。")
            self.assertEqual(archive_rows[0]["reply_text"], "咱会陪着你。")

    def test_snapshot_round_trip_restores_persona_and_memory(self) -> None:
        with TempMemoryRepo() as env:
            self.seed_voice_memory()
            candidate_rows = [
                rm.make_row(
                    status="candidate",
                    rows=[],
                    kind="social_model",
                    text="当用户被前途和算账压得很累时，应先减轻压迫感。",
                    tags=["support", "pressure", "social_model"],
                    source="unit",
                    importance=0.82,
                    confidence=0.84,
                    explicit_user_signal=True,
                )
            ]
            working_rows = [
                rm.make_row(
                    status="working",
                    rows=[],
                    kind="episodic",
                    text="我只是想找个陪伴的。",
                    tags=["chat"],
                    source="unit",
                    importance=0.7,
                    confidence=0.7,
                    extra={"speaker": "user", "turn_id": "turn-1", "observed_kind": "episodic"},
                )
            ]
            rm.write_rows("candidate", candidate_rows)
            rm.write_rows("working", working_rows)
            rm.append_emotion_trace(
                {
                    "timestamp": rm.now_utc(),
                    "name": "protective_warmth",
                    "guidance": "先给安稳感。",
                    "query_excerpt": "我最近很累",
                    "reply_excerpt": "咱先陪你把这口气缓稳。",
                }
            )
            rm.archive_turn(
                "你还在吗",
                "咱还在。",
                source="unit.snapshot",
                tags=["chat_reply"],
                metadata={"chat_name": "Nemoqi", "channel": "wechat"},
            )

            snapshot_path = env.repo_root / "snapshot.json"
            export_report = rm.export_snapshot_payload(path=str(snapshot_path), label="unit")
            self.assertEqual(export_report["candidate_count"], 1)
            self.assertEqual(export_report["archive_count"], 1)
            self.assertEqual(export_report["callback_count"], 0)
            self.assertTrue(snapshot_path.exists())

            rm.write_rows("durable", [])
            rm.write_rows("candidate", [])
            rm.write_rows("working", [])
            rm.write_emotion_trace([])
            rm.write_archive([])
            (env.repo_root / ".holo.md").write_text("", encoding="utf-8")

            report = rm.import_snapshot_payload(
                str(snapshot_path),
                mode="replace",
                dry_run=False,
                restore_persona=True,
            )

            self.assertEqual(report["durable"]["added"], 5)
            self.assertEqual(report["candidate"]["added"], 1)
            self.assertEqual(report["working"]["added"], 1)
            self.assertEqual(report["emotion_trace"]["added"], 1)
            self.assertEqual(report["archive"]["added"], 1)
            self.assertIn(".holo.md", report["restored_persona_files"])
            self.assertEqual(len(rm.load_rows("durable")), 5)
            self.assertEqual(len(rm.load_rows("candidate")), 1)
            self.assertEqual(len(rm.load_rows("working")), 1)
            self.assertEqual(len(rm.load_emotion_trace()), 1)
            self.assertEqual(len(rm.load_archive()), 1)
            self.assertEqual(len(rm.load_callback_candidates()), 0)
            self.assertIn("Use 咱 naturally.", (env.repo_root / ".holo.md").read_text(encoding="utf-8"))

    def test_backfill_archive_pairs_inbound_and_outbound_messages(self) -> None:
        with TempMemoryRepo() as env:
            db_path = env.repo_root / ".holo_runtime" / "holo_host.sqlite3"
            store = QueueStore(db_path)
            store.initialize()
            inbound_record = store.record_inbound(
                IncomingMessage(
                    message_id="msg-1",
                    thread_key="wechat:Nemoqi",
                    subject="Nemoqi",
                    sender_email="wechat:Nemoqi",
                    sender_name="Nemoqi",
                    body_text="我只是想找个陪伴的。",
                    channel="wechat",
                    source_ref="unit-test",
                )
            )
            store.record_outbound(
                thread_id=int(inbound_record["thread"]["id"]),
                contact_id=int(inbound_record["contact"]["id"]),
                remote_message_id="msg-2",
                outgoing=OutgoingMessage(
                    recipient_email="wechat:Nemoqi",
                    recipient_name="Nemoqi",
                    subject="Nemoqi",
                    body_text="咱会陪着你。",
                    thread_key="wechat:Nemoqi",
                    channel="wechat",
                ),
            )

            report = rm.backfill_archive_result(db_path=str(db_path))
            archive_rows = rm.load_archive()
            self.assertEqual(report["archive_added"], 1)
            self.assertEqual(len(archive_rows), 1)
            self.assertEqual(archive_rows[0]["metadata"]["thread_key"], "wechat:Nemoqi")
            self.assertEqual(archive_rows[0]["user_text"], "我只是想找个陪伴的。")
            self.assertEqual(archive_rows[0]["reply_text"], "咱会陪着你。")

    def test_dream_cycle_creates_candidates_and_callbacks(self) -> None:
        with TempMemoryRepo():
            self.seed_voice_memory()
            for index in range(3):
                rm.archive_turn(
                    "我不想一直算账了，也想找个陪伴的。",
                    "咱先陪你把这口气缓稳。",
                    source="unit.dream",
                    tags=["wechat", "chat_reply"],
                    turn_id=f"turn-dream-{index}",
                    metadata={
                        "chat_name": "Nemoqi",
                        "channel": "wechat",
                        "thread_key": "wechat:Nemoqi",
                        "message_id": f"msg-{index}",
                        "sender": "Nemoqi",
                    },
                )

            report = rm.dream_cycle_result(sample_size=2, seed="unit-dream-seed", dry_run=False)
            candidate_rows = rm.load_rows("candidate")
            callback_rows = rm.load_callback_candidates()
            thought_rows = rm.load_thought_stream()
            self.assertEqual(report["seed"], "unit-dream-seed")
            self.assertTrue(report["sampled_archive_ids"])
            self.assertTrue(candidate_rows)
            self.assertTrue(callback_rows)
            self.assertTrue(thought_rows)
            self.assertEqual(callback_rows[-1]["thread_key"], "wechat:Nemoqi")
            self.assertGreaterEqual(callback_rows[-1]["random_weight"], 0.0)
            self.assertGreaterEqual(report["thought_added"], 1)

    def test_think_cycle_writes_internal_thought_stream(self) -> None:
        with TempMemoryRepo():
            for index in range(2):
                rm.archive_turn(
                    "今晚有点累，也还是想找个陪伴的。",
                    "咱先陪你把这口气缓稳。",
                    source="unit.think",
                    tags=["wechat", "chat_reply"],
                    turn_id=f"turn-think-{index}",
                    metadata={
                        "chat_name": "Nemoqi",
                        "channel": "wechat",
                        "thread_key": "wechat:Nemoqi",
                        "message_id": f"think-{index}",
                        "sender": "Nemoqi",
                    },
                )

            report = rm.think_cycle_result(sample_size=2, seed="unit-think-seed", dry_run=False)
            self.assertEqual(report["seed"], "unit-think-seed")
            self.assertGreaterEqual(report["thought_added"], 1)
            self.assertTrue(rm.load_thought_stream())

    def test_reflect_and_initiative_cycles_create_candidate_rows(self) -> None:
        with TempMemoryRepo():
            rm.write_thought_stream(
                [
                    {
                        "kind": "idle_thought",
                        "text": "这条关于陪伴的线还没散。",
                        "motif": "companionship",
                    },
                    {
                        "kind": "association",
                        "text": "「慢慢说」这句和陪伴的回响连在一起。",
                        "motif": "companionship",
                    },
                    {
                        "kind": "initiative_seed",
                        "text": "又想起 Nemoqi 说过「今晚有点累」，也许该主动去碰一下这根线头。",
                        "motif": "companionship",
                        "channel": "wechat",
                        "thread_key": "wechat:Nemoqi",
                        "chat_name": "Nemoqi",
                    },
                ]
            )
            reflect_report = rm.reflect_cycle_result(window_hours=48, dry_run=False)
            candidate_rows = rm.load_rows("candidate")
            self.assertGreaterEqual(reflect_report["candidate_added"], 1)
            self.assertTrue(any("reflection" in row.get("tags", []) for row in candidate_rows))

            initiative_report = rm.initiative_cycle_result(dry_run=False)
            initiative_rows = rm.load_initiative_candidates()
            self.assertGreaterEqual(initiative_report["initiative_added"], 1)
            self.assertTrue(initiative_rows)
            self.assertEqual(initiative_rows[-1]["chat_name"], "Nemoqi")
            self.assertEqual(initiative_rows[-1]["channel"], "wechat")


    def test_ingest_artifact_reads_docx_and_creates_candidates(self) -> None:
        with TempMemoryRepo() as env:
            self.seed_voice_memory()
            docx_path = env.repo_root / "travel.docx"
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    (
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                        "<w:body>"
                        "<w:p><w:r><w:t>我一直很喜欢《狼与香辛料》的公路片气质。</w:t></w:r></w:p>"
                        "<w:p><w:r><w:t>那种中世纪商旅味道让我觉得平静。</w:t></w:r></w:p>"
                        "</w:body></w:document>"
                    ),
                )

            result = rm.ingest_artifact_result(
                str(docx_path),
                note="这是用户给咱看的作品笔记。",
                tags=["artifact_test"],
                source="unit.artifact",
                dry_run=False,
            )

            candidate_rows = rm.load_rows("candidate")
            self.assertEqual(result["artifact_type"], "document")
            self.assertTrue(any(row.get("kind") == "preference" for row in candidate_rows))
            self.assertTrue(any("公路片" in str(row.get("text", "")) for row in candidate_rows))
            self.assertTrue(any("中世纪" in str(row.get("text", "")) for row in candidate_rows))
            self.assertFalse(any(row.get("kind") == "self_model" for row in candidate_rows))

    def test_ingest_artifact_image_uses_sidecar_text_and_trace_is_trimmed(self) -> None:
        with TempMemoryRepo() as env:
            image_path = env.repo_root / "apple.png"
            image_path.write_bytes(
                bytes.fromhex(
                    "89504E470D0A1A0A"
                    "0000000D49484452000000010000000108060000001F15C489"
                    "0000000D49444154789C6360606060000000050001"
                    "0D0A2DB40000000049454E44AE426082"
                )
            )
            (env.repo_root / "apple.png.txt").write_text(
                "苹果脆甜得很，赫萝一提就会有点馋。",
                encoding="utf-8",
            )

            result = rm.ingest_artifact_result(
                str(image_path),
                tags=["artifact_test"],
                source="unit.image",
                dry_run=False,
            )
            self.assertEqual(result["artifact_type"], "image")
            self.assertEqual(result["metadata"]["width"], 1)
            self.assertEqual(result["metadata"]["height"], 1)
            self.assertEqual(result["metadata"]["sidecar_text"], "apple.png.txt")

            rm.write_rows(
                "working",
                [
                    rm.make_row(
                        status="working",
                        rows=[],
                        kind="episodic",
                        text=f"row-{index}",
                        tags=["trim"],
                        source="unit.trim",
                        importance=0.2,
                        confidence=0.2,
                        extra={"speaker": "artifact", "turn_id": str(index), "observed_kind": "summary"},
                    )
                    for index in range(rm.MAX_WORKING_ROWS + 6)
                ],
            )
            self.assertEqual(len(rm.load_rows("working")), rm.MAX_WORKING_ROWS)

            for index in range(rm.MAX_EMOTION_TRACE_ROWS + 5):
                rm.append_emotion_trace(
                    {
                        "timestamp": f"2026-04-03T00:{index:02d}:00Z",
                        "name": "playful_banter",
                        "guidance": f"guidance-{index}",
                        "query_excerpt": f"q-{index}",
                        "reply_excerpt": f"r-{index}",
                    }
                )
            self.assertEqual(len(rm.load_emotion_trace()), rm.MAX_EMOTION_TRACE_ROWS)

    def test_ingest_artifact_skips_duplicate_digest(self) -> None:
        with TempMemoryRepo() as env:
            note_path = env.repo_root / "note.md"
            note_path.write_text("我只是想找个陪伴的。", encoding="utf-8")
            first = rm.ingest_artifact_result(
                str(note_path),
                tags=["artifact_test"],
                source="unit.dup",
                dry_run=False,
            )
            second = rm.ingest_artifact_result(
                str(note_path),
                tags=["artifact_test"],
                source="unit.dup",
                dry_run=False,
            )
            self.assertEqual(first["artifact_type"], "text")
            self.assertIn("duplicate_of", second)
            self.assertEqual(len(rm.load_rows("working")), 1)


if __name__ == "__main__":
    unittest.main()
