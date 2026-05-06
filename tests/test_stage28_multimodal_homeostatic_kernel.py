from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.models import ProcessorTaskResult, TurnContext
from holo_host.processors import build_attention_state, build_turn_plan, render_chat_prompt
from tests.test_rag_memory import TempMemoryRepo


class _Stage28Runner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_task(self, request):
        self.calls.append(request.to_dict())
        if str(request.task_type) == "image_understand":
            payload = {
                "scene_summary": "界面截图里有一个接口适配面板，左上角显示 provider 状态。",
                "objects": ["接口适配面板", "provider 状态", "右侧按钮"],
                "text_ocr": "Provider OK / Visual pending",
                "mood_imagery": "工程调试截图",
                "thread_relevance": 0.86,
                "visual_anchors": ["左上角 provider 状态", "右侧按钮含义不清"],
                "spatial_refs": ["左上角: provider 状态", "右侧: 未确认按钮"],
                "uncertainty_markers": ["右侧按钮含义不清"],
                "revisit_needed": True,
                "perceptual_density": "dense",
            }
        else:
            payload = {"status": "ok"}
        return ProcessorTaskResult(
            task_type=str(request.task_type),
            text=__import__("json").dumps(payload, ensure_ascii=False),
            stdout="",
            stderr="",
            returncode=0,
        )


class Stage28MultimodalHomeostaticKernelTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo, *, runner=None) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
            runner=runner,
        )

    def _close_bridge(self, bridge: MemoryBridge) -> None:
        bridge.activation.close()
        bridge.graph.close()

    def _seed_multimodal_state(self, bridge: MemoryBridge) -> None:
        bridge.graph.upsert_visual_memory(
            channel="wechat",
            thread_key="wechat:TestUser",
            chat_name="TestUser",
            artifact_path="/tmp/stage28-ui.png",
            media_type="image/png",
            scene_summary="界面截图里有接口适配面板，左上角是 provider 状态。",
            objects=["接口适配面板", "provider 状态", "右侧按钮"],
            text_ocr="Provider OK / Visual pending",
            mood_imagery="工程调试截图",
            thread_relevance=0.84,
            visual_anchors=["左上角 provider 状态", "右侧按钮含义不清"],
            metadata={
                "spatial_refs": ["左上角: provider 状态", "右侧: 未确认按钮"],
                "uncertainty_markers": ["右侧按钮含义不清"],
                "revisit_needed": True,
                "perceptual_density": "dense",
            },
        )
        bridge.update_active_thread_state(
            channel="wechat",
            thread_key="wechat:TestUser",
            chat_name="TestUser",
            direction="inbound",
            text="我们先把视觉和接口适配这条线接上。",
            message_id="stage28-inbound",
            event_row_id=2801,
            metadata={"_stage24_force_scene_hint": True},
        )
        bridge.upsert_task_world_object(
            object_type="task",
            summary="修复 Holo 的视觉读取能力和 API 适配面板",
            thread_key="wechat:TestUser",
            chat_name="TestUser",
            channel="wechat",
            source_ref="stage28:task",
        )

    def test_situational_field_fuses_visual_scene_and_task_world_before_history(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                self._seed_multimodal_state(bridge)
                context = {
                    "channel": "wechat",
                    "thread_key": "TestUser",
                    "chat_name": "TestUser",
                    "attachments": [],
                    "recent_history": [
                        {"direction": "inbound", "body_text": "old line one"},
                        {"direction": "outbound", "body_text": "old line two"},
                    ],
                }
                packet = bridge.sidecar_packet("继续", context=context)
                turn_context = TurnContext(
                    channel="wechat",
                    thread_key="TestUser",
                    chat_name="TestUser",
                    sender="TestUser",
                    user_text="继续",
                    sidecar=packet,
                    mind_packet=packet,
                    attention_state=build_attention_state("继续", channel="wechat", metadata={}),
                    emotion_state=dict(packet.get("state", {}).get("emotion_state", {})),
                    history=list(context["recent_history"]),
                    metadata={},
                    capability_context={},
                )
                prompt = render_chat_prompt(turn_context, turn_plan=build_turn_plan(turn_context, load_config(repo_root=temp.repo_root)))
            finally:
                self._close_bridge(bridge)

        self.assertTrue(packet["stage28"]["situational_field_visible"])
        self.assertTrue(packet["stage28"]["visual_field_visible"])
        self.assertIn("visual", packet["situational_field"]["modalities"])
        self.assertIn("task_world", packet["situational_field"]["modalities"])
        self.assertIn("scene", packet["situational_field"]["modalities"])
        self.assertEqual(packet["situational_field"]["grounding_order"][0], "visual_field")
        self.assertTrue(packet["situational_field"]["open_questions"])
        self.assertLess(prompt.index("Situational Field:"), prompt.index("Recent Thread Window:"))
        self.assertNotIn("old line two", prompt)
        self.assertLessEqual(int(turn_context.metadata.get("history_lines_in_prompt", 0) or 0), 1)

    def test_visual_ingest_preserves_extended_visual_metadata(self) -> None:
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn0rC8AAAAASUVORK5CYII="
        )
        with TempMemoryRepo() as temp, tempfile.TemporaryDirectory() as tmpdir:
            bridge = self._bridge(temp, runner=_Stage28Runner())
            try:
                image_path = Path(tmpdir) / "stage28-ui.png"
                image_path.write_bytes(png)
                report = bridge.ingest_image(
                    str(image_path),
                    note="接口适配截图",
                    source="unit.stage28.visual",
                    tags=["stage28", "visual"],
                    channel="wechat",
                    thread_key="wechat:TestUser",
                    chat_name="TestUser",
                    sync=True,
                )
                visual = bridge.visual_memory_state(thread_key="TestUser", chat_name="TestUser", channel="wechat")
                packet = bridge.sidecar_packet("图右侧那个按钮是什么？", context={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser", "attachments": []})
            finally:
                self._close_bridge(bridge)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(visual["spatial_refs"][0], "左上角: provider 状态")
        self.assertEqual(visual["uncertainty_markers"], ["右侧按钮含义不清"])
        self.assertTrue(visual["revisit_needed"])
        self.assertEqual(visual["perceptual_density"], "dense")
        self.assertTrue(packet["visual_field"]["revisit_needed"])
        self.assertIn("右侧按钮含义不清", packet["visual_field"]["uncertainty_markers"])

    def test_action_market_stage28_overlay_is_inspectable_and_preserves_recall_gate(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                self._seed_multimodal_state(bridge)
                packet = bridge.sidecar_packet(
                    "那右侧按钮我们应该怎么处理？",
                    context={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser", "attachments": []},
                )
                recall_packet = bridge.sidecar_packet(
                    "你还记得之前完整历史里怎么说的吗？",
                    context={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser", "attachments": []},
                )
            finally:
                self._close_bridge(bridge)

        reply_candidate = next(item for item in packet["action_market"] if item["action_type"] == "reply_once")
        self.assertIn("stage28_delta", reply_candidate)
        self.assertIn("stage28_rationale", reply_candidate)
        self.assertIn("visual_uncertainty", reply_candidate["stage28_rationale"])
        self.assertTrue(packet["stage28"]["hard_gate_preserved"])
        self.assertEqual(recall_packet["stage28"]["hard_gate_preserved"], True)
        self.assertIn(str(recall_packet.get("tier", "")), {"recall", "deep_recall"})
        self.assertTrue(str(recall_packet.get("recall_reason", "")).startswith("stage17:"))


if __name__ == "__main__":
    unittest.main()
