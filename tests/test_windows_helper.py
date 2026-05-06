from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from windows_helper.wechat_helper import (
    ChatTurn,
    HelperConfig,
    JsonInboxAdapter,
    PyweixinReplyAdapter,
    StateStore,
    annotate_pyweixin_message,
    best_contact_match,
    chat_turn_from_wcf_msg,
    contact_match_score,
    export_history_markdown,
    latest_pyweixin_dialog_turn,
    latest_pyweixin_turn,
    maybe_ingest_turn_artifact,
    parse_turn,
    parse_pyweixin_session_unread,
    command_watch_live,
    command_watch_pyweixin_dialog,
    process_one_turn,
    queue_send_task,
    scan_pyweixin_new_messages,
    send_via_pyweixin,
    load_config,
    _is_pyweixin_transient_error,
    pyweixin_is_foreground,
    pyweixin_open_main,
    sync_history_payload_to_memory,
    visible_pyweixin_unread_map,
    wcf_runtime_info,
    write_transport_state,
)


class FakeClient:
    def __init__(self, action: str = "reply", text: str = "I记着了。"):
        self.action = action
        self.text = text
        self.calls: list[dict] = []
        self.artifact_calls: list[dict] = []

    def reply(self, turn: ChatTurn) -> dict:
        self.calls.append(turn.to_payload())
        if self.action == "ignore":
            return {"action": "ignore", "reason": "manual"}
        return {"action": "reply", "text": self.text, "thread_key": turn.thread_key or turn.chat_name}

    def ingest_artifact(self, payload: dict) -> dict:
        self.artifact_calls.append(dict(payload))
        return {"ok": True, "path": payload.get("path", ""), "artifact_type": "document"}


class WindowsHelperTests(unittest.TestCase):
    def test_contact_match_prefers_exact_remark(self) -> None:
        contacts = [
            {"wxid": "wxid_alice", "name": "Alice", "remark": "", "code": "alice_1"},
            {"wxid": "wxid_nemo", "name": "TestUser", "remark": "TestUser", "code": "nemo_qi"},
            {"wxid": "wxid_other", "name": "Nemo", "remark": "", "code": "nemo"},
        ]
        match = best_contact_match(contacts, "TestUser")
        self.assertIsNotNone(match)
        self.assertEqual(match["wxid"], "wxid_nemo")
        self.assertGreater(contact_match_score(match, "TestUser"), 0)

    def test_chat_turn_from_wcf_msg_maps_group_fields(self) -> None:
        class FakeMsg:
            type = 1
            id = "msg-1"
            ts = 123456
            sender = "wxid_friend"
            roomid = "123@chatroom"
            content = "晚上吃什么"

            def is_text(self) -> bool:
                return True

            def from_self(self) -> bool:
                return False

            def from_group(self) -> bool:
                return True

            def is_at(self, wxid: str) -> bool:
                return wxid == "wxid_self"

        turn = chat_turn_from_wcf_msg(
            FakeMsg(),
            contacts_by_wxid={
                "wxid_friend": {"wxid": "wxid_friend", "remark": "TestUser", "name": "TestUser", "code": "nemo_qi"},
                "123@chatroom": {"wxid": "123@chatroom", "remark": "", "name": "测试群", "code": ""},
            },
            self_wxid="wxid_self",
        )
        self.assertIsNotNone(turn)
        assert turn is not None
        self.assertEqual(turn.chat_name, "测试群")
        self.assertEqual(turn.sender, "TestUser")
        self.assertEqual(turn.thread_key, "123@chatroom")
        self.assertTrue(turn.is_group)
        self.assertTrue(turn.mentioned)

    def test_parse_turn_and_state_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = StateStore(Path(tmpdir) / "state.json")
            turn = parse_turn({"chat_name": "测试联系人", "text": "晚上吃什么", "message_id": "m-1"})
            self.assertFalse(state.already_seen(turn))
            state.remember(turn)
            state.save()

            loaded = StateStore(Path(tmpdir) / "state.json")
            self.assertTrue(loaded.already_seen(turn))

    def test_state_store_stable_message_id_ignores_ts_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = StateStore(Path(tmpdir) / "state.json")
            first = ChatTurn(chat_name="TestUser", text="在吗", message_id="msg-1", thread_key="TestUser", ts=111)
            second = ChatTurn(chat_name="TestUser", text="在吗", message_id="msg-1", thread_key="TestUser", ts=999)
            state.remember(first)
            self.assertTrue(state.already_seen(second))

    def test_state_store_tracks_history_sync_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = StateStore(Path(tmpdir) / "state.json")
            self.assertEqual(state.last_history_sync_digest("TestUser"), "")
            state.mark_history_synced("TestUser", digest="abc123", export_path="C:/wechat-helper/export.md", now=123)
            state.save()
            loaded = StateStore(Path(tmpdir) / "state.json")
            self.assertEqual(loaded.last_history_sync_digest("TestUser"), "abc123")

    def test_state_store_quarantines_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            path.write_text("{broken", encoding="utf-8")
            state = StateStore(path)
            self.assertEqual(state.data["seen_by_chat"], {})
            quarantined = list(Path(tmpdir).glob("state.json.corrupt-*"))
            self.assertEqual(len(quarantined), 1)
            self.assertFalse(path.exists())

    def test_json_inbox_adapter_moves_processed_and_writes_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(
                inbox_dir=root / "inbox",
                processed_dir=root / "processed",
                outbox_file=root / "outbox.jsonl",
            )
            adapter = JsonInboxAdapter(config)
            source = config.inbox_dir / "turn-1.json"
            source.write_text(
                json.dumps({"chat_name": "测试联系人", "text": "你好", "message_id": "m-1"}, ensure_ascii=False),
                encoding="utf-8",
            )
            turns = adapter.poll_turns()
            self.assertEqual(len(turns), 1)
            turn, path = turns[0]
            self.assertEqual(turn.chat_name, "测试联系人")
            adapter.send_reply(turn, "I在。", draft_only=True)
            adapter.mark_processed(path)
            self.assertFalse(source.exists())
            self.assertTrue((config.processed_dir / "turn-1.json").exists())
            self.assertTrue(config.outbox_file.exists())

    def test_process_one_turn_respects_whitelist_and_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(
                whitelist=["测试联系人"],
                cooldown_seconds=30,
                state_file=root / "state.json",
                inbox_dir=root / "inbox",
                processed_dir=root / "processed",
                outbox_file=root / "outbox.jsonl",
            )
            adapter = JsonInboxAdapter(config)
            state = StateStore(config.state_file)
            client = FakeClient(text="I看得出你有些累。")
            turn = ChatTurn(chat_name="测试联系人", text="我有点累", message_id="m-1")

            first = process_one_turn(turn, client=client, state=state, adapter=adapter, config=config)
            self.assertEqual(first["action"], "reply")
            second = process_one_turn(turn, client=client, state=state, adapter=adapter, config=config)
            self.assertEqual(second["action"], "ignore")
            self.assertEqual(second["reason"], "cooldown")

            other = ChatTurn(chat_name="陌生人", text="你好", message_id="m-2")
            blocked = process_one_turn(other, client=client, state=state, adapter=adapter, config=config)
            self.assertEqual(blocked["reason"], "not_whitelisted")

    def test_process_one_turn_uses_bubbles_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(
                whitelist=["TestUser"],
                cooldown_seconds=0,
                state_file=root / "state.json",
            )
            state = StateStore(config.state_file)

            class BubbleClient(FakeClient):
                def reply(self, turn: ChatTurn) -> dict:
                    payload = super().reply(turn)
                    payload["bubbles"] = ["I在。", "慢慢说。"]
                    payload["cadence_ms"] = [0, 420]
                    return payload

            class BubbleAdapter:
                def __init__(self) -> None:
                    self.calls: list[tuple[list[str], list[int], bool]] = []

                def send_bubbles(self, turn: ChatTurn, bubbles: list[str], *, cadence_ms: list[int] | None = None, draft_only: bool) -> dict[str, object]:
                    self.calls.append((list(bubbles), list(cadence_ms or []), draft_only))
                    return {"send_result": {"ok": True}}

            adapter = BubbleAdapter()
            turn = ChatTurn(chat_name="TestUser", text="在吗", message_id="m-bubbles")
            result = process_one_turn(turn, client=BubbleClient(text="ignored"), state=state, adapter=adapter, config=config)
            self.assertEqual(result["action"], "reply")
            self.assertEqual(adapter.calls[0][0], ["I在。", "慢慢说。"])
            self.assertEqual(adapter.calls[0][1], [0, 420])

    def test_process_one_turn_does_not_remember_failed_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(
                whitelist=["TestUser"],
                draft_only=False,
                cooldown_seconds=5,
                state_file=root / "state.json",
            )
            state = StateStore(config.state_file)
            client = FakeClient(text="I在。")

            class FailingAdapter:
                def send_reply(self, turn: ChatTurn, text: str, *, draft_only: bool) -> dict[str, object]:
                    return {"send_result": {"ok": False, "error": "bad_target"}}

            turn = ChatTurn(chat_name="TestUser", text="在吗", message_id="m-2")
            result = process_one_turn(turn, client=client, state=state, adapter=FailingAdapter(), config=config)
            self.assertEqual(result["reason"], "send_failed")
            self.assertFalse(state.already_seen(turn))

    def test_queue_send_task_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(
                send_queue_dir=root / "send_queue",
                pywinauto_process_path=r"D:\Weixin\Weixin.exe",
            )
            result = queue_send_task(config, chat_name="TestUser", text="I来找你了。")
            self.assertTrue(result["queued"])
            task_path = Path(result["path"])
            self.assertTrue(task_path.exists())
            payload = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["chat_name"], "TestUser")
            self.assertEqual(payload["search"], "TestUser")

    def test_parse_pyweixin_session_unread_extracts_chat_and_count(self) -> None:
        parsed = parse_pyweixin_session_unread("session_item_TestUser", "TestUser\n[3条]\nbring holo back!")
        self.assertEqual(parsed, ("TestUser", 3))
        muted = parse_pyweixin_session_unread("session_item_TestUser", "TestUser\n消息免打扰\n[2条]")
        self.assertIsNone(muted)

    def test_load_config_maps_windows_paths_on_posix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "wechat_helper.json"
            config_path.write_text(
                json.dumps(
                    {
                        "send_queue_dir": "C:/wechat-helper/send_queue",
                        "sent_dir": "C:/wechat-helper/sent",
                        "failed_dir": "C:/wechat-helper/failed",
                        "receipt_dir": "C:/wechat-helper/receipts",
                        "state_file": "C:/wechat-helper/state.json",
                        "transport_state_file": "C:/wechat-helper/transport_state.live.json",
                        "pyweixin_repo_path": "//wsl.localhost/Ubuntu/tmp/pywechat-upstream",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(str(config_path))
            self.assertEqual(str(config.send_queue_dir), "/mnt/c/wechat-helper/send_queue")
            self.assertEqual(str(config.sent_dir), "/mnt/c/wechat-helper/sent")
            self.assertEqual(str(config.failed_dir), "/mnt/c/wechat-helper/failed")
            self.assertEqual(str(config.receipt_dir), "/mnt/c/wechat-helper/receipts")
            self.assertEqual(str(config.state_file), "/mnt/c/wechat-helper/state.json")
            self.assertEqual(str(config.transport_state_file), "/mnt/c/wechat-helper/transport_state.live.json")
            self.assertEqual(config.pyweixin_repo_path, "//wsl.localhost/Ubuntu/tmp/pywechat-upstream")

    def test_load_config_prefers_env_default_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "wechat_helper.live.json"
            config_path.write_text(
                json.dumps({"draft_only": False, "whitelist": ["TestUser"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            previous = os.environ.get("HOLO_WECHAT_HELPER_CONFIG")
            os.environ["HOLO_WECHAT_HELPER_CONFIG"] = str(config_path)
            try:
                config = load_config(None)
            finally:
                if previous is None:
                    os.environ.pop("HOLO_WECHAT_HELPER_CONFIG", None)
                else:
                    os.environ["HOLO_WECHAT_HELPER_CONFIG"] = previous
            self.assertFalse(config.draft_only)
            self.assertEqual(config.whitelist, ["TestUser"])

    def test_wcf_runtime_info_flags_weixin_4x_against_39x(self) -> None:
        fake_module = types.SimpleNamespace(__version__="39.5.2.0")
        config = HelperConfig(pywinauto_process_path=r"D:\Weixin\Weixin.exe")
        with mock.patch.dict(sys.modules, {"wcferry": fake_module}), mock.patch(
            "windows_helper.wechat_helper._windows_file_version",
            return_value="4.1.8.29",
        ):
            info = wcf_runtime_info(config)
        self.assertEqual(info["compatibility"], "incompatible")
        self.assertIn("39.5.2.0", info["reason"])
        self.assertIn("4.1.8.29", info["reason"])

    def test_load_config_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "broken.json"
            config_path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid helper config"):
                load_config(str(config_path))

    def test_load_config_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "wechat_helper.json"
            config_path.write_text(
                json.dumps(
                    {
                        "agent_url": "http://127.0.0.1:8004",
                        "transport_state_file": str(Path(tmpdir) / "transport_state.json"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8-sig",
            )
            config = load_config(str(config_path))
            self.assertEqual(config.agent_url, "http://127.0.0.1:8004")

    def test_latest_pyweixin_turn_prefers_latest_non_timestamp_row(self) -> None:
        import windows_helper.wechat_helper as helper

        original = helper.read_pyweixin_visible_messages
        try:
            helper.read_pyweixin_visible_messages = lambda loaded, chat_name, limit=40, capture_dir=None: {
                "chat_name": chat_name,
                "messages": [
                    {"kind": "timestamp", "text": "16:16", "timestamp": "16:16"},
                    {"kind": "text", "text": "第一句", "timestamp": "2026年4月3日 16:16"},
                    {
                        "kind": "image_ref",
                        "text": "图片 2026年4月3日 16:17",
                        "timestamp": "2026年4月3日 16:17",
                        "capture_path": "/tmp/capture.png",
                        "direction": "incoming",
                        "direction_confidence": 0.93,
                        "is_self": False,
                        "sender_hint": "TestUser",
                    },
                ],
            }
            turn = latest_pyweixin_turn({}, chat_name="TestUser", unread_count=2)
            self.assertIsNotNone(turn)
            assert turn is not None
            self.assertEqual(turn.chat_name, "TestUser")
            self.assertEqual(turn.text, "图片 2026年4月3日 16:17")
            self.assertEqual(turn.metadata["unread_count"], 2)
            self.assertEqual(turn.metadata["pyweixin_kind"], "image_ref")
            self.assertEqual(turn.metadata["capture_path"], "/tmp/capture.png")
            self.assertEqual(turn.metadata["direction"], "incoming")
            self.assertEqual(turn.sender, "TestUser")
            self.assertTrue(turn.metadata["visible_digest"])
        finally:
            helper.read_pyweixin_visible_messages = original

    def test_annotate_pyweixin_message_uses_sender_hint_when_available(self) -> None:
        payload = annotate_pyweixin_message(
            {
                "kind": "text",
                "text": "你好呀",
                "button_texts": ["TestUser"],
                "content_bounds": {"left": 40, "right": 260},
            },
            chat_name="TestUser",
            list_rect={"left": 0, "right": 600, "width": 600, "center_x": 300},
        )
        self.assertEqual(payload["direction"], "incoming")
        self.assertFalse(payload["is_self"])
        self.assertEqual(payload["sender_hint"], "TestUser")

    def test_annotate_pyweixin_message_uses_geometry_for_outgoing(self) -> None:
        payload = annotate_pyweixin_message(
            {
                "kind": "text",
                "text": "I在。",
                "button_texts": [],
                "content_bounds": {"left": 420, "right": 560},
            },
            chat_name="TestUser",
            list_rect={"left": 0, "right": 600, "width": 600, "center_x": 300},
        )
        self.assertEqual(payload["direction"], "outgoing")
        self.assertTrue(payload["is_self"])

    def test_latest_pyweixin_turn_prefers_latest_incoming_row_over_newer_outgoing(self) -> None:
        import windows_helper.wechat_helper as helper

        original = helper.read_pyweixin_visible_messages
        try:
            helper.read_pyweixin_visible_messages = lambda loaded, chat_name, limit=40, capture_dir=None: {
                "chat_name": chat_name,
                "messages": [
                    {"kind": "text", "text": "你先前那句", "timestamp": "2026年4月3日 16:20", "direction": "incoming", "is_self": False, "sender_hint": "TestUser"},
                    {"kind": "text", "text": "I刚回过的话", "timestamp": "2026年4月3日 16:21", "direction": "outgoing", "is_self": True, "sender_hint": "self"},
                ],
            }
            turn = latest_pyweixin_turn({}, chat_name="TestUser", unread_count=1)
            self.assertIsNotNone(turn)
            assert turn is not None
            self.assertEqual(turn.text, "你先前那句")
            self.assertEqual(turn.metadata["direction"], "incoming")
            self.assertFalse(turn.metadata["is_self"])
        finally:
            helper.read_pyweixin_visible_messages = original

    def test_pyweixin_open_main_retries_before_success(self) -> None:
        calls = {"count": 0}

        class Navigator:
            @staticmethod
            def open_weixin(is_maximize: bool = False) -> object:
                calls["count"] += 1
                if calls["count"] < 3:
                    raise RuntimeError("uia transient failure")
                return object()

        result = pyweixin_open_main({"Navigator": Navigator})
        self.assertIsNotNone(result)
        self.assertEqual(calls["count"], 3)

    def test_visible_pyweixin_unread_map_returns_empty_on_open_error(self) -> None:
        self.assertEqual(visible_pyweixin_unread_map({"Navigator": object()}), {})

    def test_scan_pyweixin_new_messages_returns_empty_on_fallback_error(self) -> None:
        import windows_helper.wechat_helper as helper

        original_visible = helper.visible_pyweixin_unread_map
        try:
            helper.visible_pyweixin_unread_map = lambda _loaded: (_ for _ in ()).throw(RuntimeError("boom"))

            class Utils:
                @staticmethod
                def scan_for_new_messages(is_maximize: bool = False, close_weixin: bool = False) -> None:
                    return None

            self.assertEqual(scan_pyweixin_new_messages({"utils": Utils()}), {})
        finally:
            helper.visible_pyweixin_unread_map = original_visible

    def test_pyweixin_is_foreground_returns_false_without_windows_modules(self) -> None:
        self.assertFalse(pyweixin_is_foreground(r"D:\Weixin\Weixin.exe"))

    def test_pyweixin_reply_adapter_records_draft_and_optional_send(self) -> None:
        import windows_helper.wechat_helper as helper

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(outbox_file=root / "outbox.jsonl")
            adapter = PyweixinReplyAdapter(config)
            turn = ChatTurn(chat_name="TestUser", text="你好", sender="TestUser", message_id="m-1")

            draft_record = adapter.send_reply(turn, "I在。", draft_only=True)
            self.assertEqual(draft_record["draft_only"], True)
            self.assertTrue(config.outbox_file.exists())

            original = helper.send_via_pyweixin
            try:
                helper.send_via_pyweixin = lambda *_args, **_kwargs: {"ok": True, "chat_name": "TestUser"}
                sent_record = adapter.send_reply(turn, "I还在。", draft_only=False)
                self.assertEqual(sent_record["send_result"]["ok"], True)
            finally:
                helper.send_via_pyweixin = original

    def test_watch_live_prefers_wcf_and_falls_back_to_pyweixin(self) -> None:
        import windows_helper.wechat_helper as helper

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "wechat_helper.json"
            config_path.write_text(
                json.dumps(
                    {
                        "watch_mode": "auto",
                        "allow_transport_fallback": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original_wcf = helper.command_watch_wcf
            original_pyweixin = helper.command_watch_pyweixin
            try:
                helper.command_watch_wcf = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("wcf down"))
                helper.command_watch_pyweixin = lambda *_args, **_kwargs: 0
                self.assertEqual(command_watch_live(str(config_path), once=True, max_messages=1), 0)
            finally:
                helper.command_watch_wcf = original_wcf
                helper.command_watch_pyweixin = original_pyweixin

    def test_watch_live_dispatches_pyweixin_dialog_mode(self) -> None:
        import windows_helper.wechat_helper as helper

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "wechat_helper.json"
            config_path.write_text(
                json.dumps(
                    {
                        "watch_mode": "pyweixin_dialog",
                        "allow_transport_fallback": False,
                        "whitelist": ["TestUser"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original_dialog = helper.command_watch_pyweixin_dialog
            try:
                helper.command_watch_pyweixin_dialog = lambda *_args, **_kwargs: 0
                self.assertEqual(command_watch_live(str(config_path), once=True, max_messages=1), 0)
            finally:
                helper.command_watch_pyweixin_dialog = original_dialog

    def test_is_pyweixin_transient_error_matches_login_and_com_failures(self) -> None:
        self.assertTrue(_is_pyweixin_transient_error(RuntimeError("微信未登录,请先点击登录后再使用pyweixin!")))
        self.assertTrue(_is_pyweixin_transient_error(RuntimeError("unable to open dedicated dialog for TestUser: 事件无法调用任何订户")))
        self.assertFalse(_is_pyweixin_transient_error(RuntimeError("some other failure")))

    def test_watch_pyweixin_dialog_once_degrades_instead_of_raising_for_transient_error(self) -> None:
        import windows_helper.wechat_helper as helper

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "wechat_helper.json"
            config_path.write_text(
                json.dumps(
                    {
                        "watch_mode": "pyweixin_dialog",
                        "allow_transport_fallback": False,
                        "whitelist": ["TestUser"],
                        "state_file": str(root / "state.json"),
                        "outbox_file": str(root / "outbox.jsonl"),
                        "transport_state_file": str(root / "transport_state.json"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original_import = helper.import_pyweixin
            original_agent = helper.AgentClient
            original_store = helper.StateStore
            original_adapter = helper.PyweixinDialogAdapter
            try:
                helper.import_pyweixin = lambda _repo="": {"Monitor": object()}
                helper.AgentClient = lambda *_args, **_kwargs: object()
                helper.StateStore = lambda *_args, **_kwargs: types.SimpleNamespace(save=lambda: None)

                class FailingAdapter:
                    def __init__(self, *_args, **_kwargs):
                        pass

                    def ensure_dialog(self, _chat_name: str) -> object:
                        raise RuntimeError("微信未登录,请先点击登录后再使用pyweixin!")

                    def close(self) -> None:
                        return None

                helper.PyweixinDialogAdapter = FailingAdapter
                self.assertEqual(command_watch_pyweixin_dialog(str(config_path), once=True, max_messages=1), 0)
                payload = json.loads((root / "transport_state.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["status"], "stopped")
            finally:
                helper.import_pyweixin = original_import
                helper.AgentClient = original_agent
                helper.StateStore = original_store
                helper.PyweixinDialogAdapter = original_adapter

    def test_watch_pyweixin_dialog_once_processes_latest_visible_turn(self) -> None:
        import windows_helper.wechat_helper as helper

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "wechat_helper.json"
            config_path.write_text(
                json.dumps(
                    {
                        "watch_mode": "pyweixin_dialog",
                        "allow_transport_fallback": False,
                        "whitelist": ["TestUser"],
                        "state_file": str(root / "state.json"),
                        "outbox_file": str(root / "outbox.jsonl"),
                        "transport_state_file": str(root / "transport_state.json"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original_import = helper.import_pyweixin
            original_agent = helper.AgentClient
            original_adapter = helper.PyweixinDialogAdapter
            original_latest = helper.latest_pyweixin_dialog_turn
            try:
                helper.import_pyweixin = lambda _repo="": {"MenuItems": object()}
                helper.AgentClient = lambda *_args, **_kwargs: FakeClient(text="I在。")

                class ReadyAdapter:
                    def __init__(self, config, loaded):
                        self.config = config
                        self.loaded = loaded

                    def ensure_dialog(self, _chat_name: str) -> object:
                        return object()

                    def close(self) -> None:
                        return None

                    def send_bubbles(self, turn, bubbles, *, cadence_ms=None, draft_only=False):
                        return {"send_result": {"ok": True}, "text": " ".join(bubbles)}

                helper.PyweixinDialogAdapter = ReadyAdapter
                helper.latest_pyweixin_dialog_turn = lambda *_args, **_kwargs: ChatTurn(
                    chat_name="TestUser",
                    text="你在吗",
                    sender="TestUser",
                    message_id="msg-1",
                    thread_key="TestUser",
                    metadata={"visible_digest": "abc123"},
                )

                self.assertEqual(command_watch_pyweixin_dialog(str(config_path), once=True, max_messages=1), 0)
                state = json.loads((root / "state.json").read_text(encoding="utf-8"))
                self.assertTrue(state["seen_by_chat"]["TestUser"])
            finally:
                helper.import_pyweixin = original_import
                helper.AgentClient = original_agent
                helper.PyweixinDialogAdapter = original_adapter
                helper.latest_pyweixin_dialog_turn = original_latest

    def test_agent_client_tries_wsl_fallback_when_localhost_unreachable(self) -> None:
        import windows_helper.wechat_helper as helper

        class FakeResponse:
            def __init__(self, payload: dict[str, object]):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

        attempted: list[str] = []

        def fake_open(req, timeout=0):
            attempted.append(req.full_url)
            if req.full_url.startswith("http://127.0.0.1:8004"):
                raise helper.error.URLError("boom")
            return FakeResponse({"status": "ok"})

        client = helper.AgentClient("http://127.0.0.1:8004", timeout_seconds=1)
        with mock.patch.object(helper, "_resolve_wsl_agent_base_url", return_value="http://172.28.44.15:8004"), mock.patch(
            "windows_helper.wechat_helper.request.build_opener",
            return_value=types.SimpleNamespace(open=fake_open),
        ), mock.patch("windows_helper.wechat_helper.request.urlopen", side_effect=fake_open):
            payload = client.get_json("/health")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            attempted,
            [
                "http://127.0.0.1:8004/health",
                "http://172.28.44.15:8004/health",
            ],
        )

    def test_agent_client_skips_wsl_fallback_for_remote_base_url(self) -> None:
        import windows_helper.wechat_helper as helper

        client = helper.AgentClient("http://example.test:8004", timeout_seconds=1)
        with mock.patch.object(helper, "_resolve_wsl_agent_base_url", return_value="http://172.28.44.15:8004"):
            self.assertEqual(
                client._candidate_base_urls(helper.parse.urlparse("http://example.test:8004/health")),
                ["http://example.test:8004"],
            )

    def test_watch_pyweixin_dialog_agent_unreachable_degrades_without_crash(self) -> None:
        import windows_helper.wechat_helper as helper

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "wechat_helper.json"
            config_path.write_text(
                json.dumps(
                    {
                        "watch_mode": "pyweixin_dialog",
                        "allow_transport_fallback": False,
                        "whitelist": ["TestUser"],
                        "state_file": str(root / "state.json"),
                        "outbox_file": str(root / "outbox.jsonl"),
                        "transport_state_file": str(root / "transport_state.json"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original_import = helper.import_pyweixin
            original_agent = helper.AgentClient
            original_adapter = helper.PyweixinDialogAdapter
            original_latest = helper.latest_pyweixin_dialog_turn
            statuses: list[dict[str, object]] = []

            def fake_write_transport_state(config, **kwargs):
                payload = {"status": kwargs.get("status", ""), "detail": kwargs.get("detail", "")}
                statuses.append(payload)
                return payload

            try:
                helper.import_pyweixin = lambda _repo="": {"MenuItems": object()}

                class UnreachableClient:
                    def reply(self, _turn):
                        raise RuntimeError("agent unreachable: test")

                helper.AgentClient = lambda *_args, **_kwargs: UnreachableClient()

                class ReadyAdapter:
                    def __init__(self, config, loaded):
                        self.config = config
                        self.loaded = loaded

                    def ensure_dialog(self, _chat_name: str) -> object:
                        return object()

                    def close(self) -> None:
                        return None

                helper.PyweixinDialogAdapter = ReadyAdapter
                helper.latest_pyweixin_dialog_turn = lambda *_args, **_kwargs: ChatTurn(
                    chat_name="TestUser",
                    text="你在吗",
                    sender="TestUser",
                    message_id="msg-1",
                    thread_key="TestUser",
                    metadata={"visible_digest": "abc123"},
                )
                with mock.patch("windows_helper.wechat_helper.write_transport_state", side_effect=fake_write_transport_state):
                    self.assertEqual(command_watch_pyweixin_dialog(str(config_path), once=True, max_messages=1), 0)
            finally:
                helper.import_pyweixin = original_import
                helper.AgentClient = original_agent
                helper.PyweixinDialogAdapter = original_adapter
                helper.latest_pyweixin_dialog_turn = original_latest

            self.assertTrue(any(str(item.get("status")) == "degraded" for item in statuses))

    def test_latest_pyweixin_dialog_turn_uses_visible_rows(self) -> None:
        import windows_helper.wechat_helper as helper

        original_find = helper.pyweixin_find_message_list
        original_collect = helper.collect_pyweixin_visible_rows
        try:
            helper.pyweixin_find_message_list = lambda _dialog: object()
            helper.collect_pyweixin_visible_rows = lambda *_args, **_kwargs: (
                {},
                [
                    {"kind": "timestamp", "text": "刚刚", "timestamp": "刚刚"},
                    {
                        "kind": "text",
                        "text": "I在",
                        "timestamp": "刚刚",
                        "direction": "incoming",
                        "direction_confidence": 0.9,
                        "is_self": False,
                        "sender_hint": "TestUser",
                    },
                ],
            )
            turn = latest_pyweixin_dialog_turn({"MenuItems": object()}, dialog_window=object(), chat_name="TestUser")
            self.assertIsNotNone(turn)
            assert turn is not None
            self.assertEqual(turn.text, "I在")
            self.assertEqual(turn.source_ref, "pyweixin_dialog:TestUser")
            self.assertTrue(turn.metadata["visible_digest"])
        finally:
            helper.pyweixin_find_message_list = original_find
            helper.collect_pyweixin_visible_rows = original_collect

    def test_latest_pyweixin_dialog_turn_prefers_incoming_when_newest_visible_is_outgoing(self) -> None:
        import windows_helper.wechat_helper as helper

        original_find = helper.pyweixin_find_message_list
        original_collect = helper.collect_pyweixin_visible_rows
        try:
            helper.pyweixin_find_message_list = lambda _dialog: object()
            helper.collect_pyweixin_visible_rows = lambda *_args, **_kwargs: (
                {},
                [
                    {
                        "kind": "text",
                        "text": "你在吗",
                        "timestamp": "刚刚",
                        "direction": "incoming",
                        "direction_confidence": 0.9,
                        "is_self": False,
                        "sender_hint": "TestUser",
                    },
                    {
                        "kind": "text",
                        "text": "I在。",
                        "timestamp": "刚刚",
                        "direction": "outgoing",
                        "direction_confidence": 0.9,
                        "is_self": True,
                        "sender_hint": "self",
                    },
                ],
            )
            turn = latest_pyweixin_dialog_turn({"MenuItems": object()}, dialog_window=object(), chat_name="TestUser")
            self.assertIsNotNone(turn)
            assert turn is not None
            self.assertEqual(turn.text, "你在吗")
            self.assertEqual(turn.metadata["direction"], "incoming")
            self.assertFalse(turn.metadata["is_self"])
        finally:
            helper.pyweixin_find_message_list = original_find
            helper.collect_pyweixin_visible_rows = original_collect

    def test_write_transport_state_persists_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(transport_state_file=root / "transport_state.json", watch_mode="wcf")
            payload = write_transport_state(
                config,
                status="online",
                mode="live",
                transport="wcf",
                detail="receiving messages",
                extra={"last_chat_name": "TestUser"},
            )
            self.assertEqual(payload["status"], "online")
            written = json.loads(config.transport_state_file.read_text(encoding="utf-8"))
            self.assertEqual(written["transport"], "wcf")
            self.assertEqual(written["last_chat_name"], "TestUser")

    def test_write_transport_state_retries_transient_replace_permission_error(self) -> None:
        import windows_helper.wechat_helper as helper

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(transport_state_file=root / "transport_state.json", watch_mode="pyweixin_dialog")
            original_replace = helper.os.replace
            calls = {"count": 0}

            def flaky_replace(src: os.PathLike[str] | str, dst: os.PathLike[str] | str) -> None:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise PermissionError(5, "Access is denied")
                original_replace(src, dst)

            with mock.patch.object(helper.os, "replace", side_effect=flaky_replace), mock.patch.object(
                helper.time, "sleep"
            ) as sleep_mock:
                payload = write_transport_state(
                    config,
                    status="online",
                    mode="live",
                    transport="pyweixin_dialog",
                    detail="idle",
                )

            self.assertEqual(payload["status"], "online")
            self.assertGreaterEqual(calls["count"], 2)
            sleep_mock.assert_called_once()
            written = json.loads(config.transport_state_file.read_text(encoding="utf-8"))
            self.assertEqual(written["detail"], "idle")

    def test_send_via_pyweixin_requires_current_chat_match(self) -> None:
        import windows_helper.wechat_helper as helper

        class DummyGlobalConfig:
            close_weixin = False
            is_maximize = False
            clear = True
            search_pages = 0
            send_delay = 0.25

        original_import = helper.import_pyweixin
        original_navigate = helper.pyweixin_navigate_visible_chat
        original_current = helper.pyweixin_current_chat_name
        original_send_current = helper.send_current_chat_via_pyweixin
        original_probe = helper.probe_pyweixin_state
        try:
            helper.import_pyweixin = lambda _repo="": {"repo_path": "//repo", "GlobalConfig": DummyGlobalConfig}
            helper.pyweixin_navigate_visible_chat = lambda _loaded, _chat: object()
            helper.pyweixin_current_chat_name = lambda _main: "TestUser"
            helper.send_current_chat_via_pyweixin = lambda **_kwargs: {"used_current_chat_fallback": True}
            helper.probe_pyweixin_state = lambda _config: {"ok": True}
            result = send_via_pyweixin(HelperConfig(pyweixin_repo_path="//repo"), chat_name="TestUser", text="I在。")
            self.assertTrue(result["ok"])
            self.assertEqual(result["send_mode"], "current_chat_only")
            self.assertEqual(result["resolved_chat"], "TestUser")
        finally:
            helper.import_pyweixin = original_import
            helper.pyweixin_navigate_visible_chat = original_navigate
            helper.pyweixin_current_chat_name = original_current
            helper.send_current_chat_via_pyweixin = original_send_current
            helper.probe_pyweixin_state = original_probe

    def test_send_via_pyweixin_refuses_chat_mismatch(self) -> None:
        import windows_helper.wechat_helper as helper

        class DummyGlobalConfig:
            close_weixin = False
            is_maximize = False
            clear = True
            search_pages = 0
            send_delay = 0.25

        original_import = helper.import_pyweixin
        original_navigate = helper.pyweixin_navigate_visible_chat
        original_current = helper.pyweixin_current_chat_name
        original_send_current = helper.send_current_chat_via_pyweixin
        original_probe = helper.probe_pyweixin_state
        try:
            helper.import_pyweixin = lambda _repo="": {"repo_path": "//repo", "GlobalConfig": DummyGlobalConfig}
            helper.pyweixin_navigate_visible_chat = lambda _loaded, _chat: object()
            helper.pyweixin_current_chat_name = lambda _main: "别的聊天"
            helper.send_current_chat_via_pyweixin = lambda **_kwargs: {"used_current_chat_fallback": True}
            helper.probe_pyweixin_state = lambda _config: {"ok": True}
            result = send_via_pyweixin(HelperConfig(pyweixin_repo_path="//repo"), chat_name="TestUser", text="I在。")
            self.assertFalse(result["ok"])
            self.assertIn("expected current chat TestUser", result["error"])
        finally:
            helper.import_pyweixin = original_import
            helper.pyweixin_navigate_visible_chat = original_navigate
            helper.pyweixin_current_chat_name = original_current
            helper.send_current_chat_via_pyweixin = original_send_current
            helper.probe_pyweixin_state = original_probe

    def test_export_history_markdown_includes_rows(self) -> None:
        content = export_history_markdown(
            HelperConfig(receipt_dir=Path(tempfile.mkdtemp())),
            "文件传输助手",
            [
                {"kind": "timestamp", "timestamp": "星期三 22:59", "text": "星期三 22:59"},
                {"kind": "text", "timestamp": "2026年4月3日 16:16", "text": "I在这里。"},
                {"kind": "image_ref", "timestamp": "2026年4月3日 16:17", "text": "图片", "capture_path": "C:/captures/001.png"},
            ],
        )
        self.assertTrue(content.exists())
        text = content.read_text(encoding="utf-8")
        self.assertIn("Weixin History Export: 文件传输助手", text)
        self.assertIn("I在这里。", text)
        self.assertIn("capture_path: C:/captures/001.png", text)

    def test_sync_history_payload_to_memory_sends_export_and_captures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(receipt_dir=root / "receipts")
            client = FakeClient()
            state = StateStore(root / "state.json")
            capture = root / "receipts" / "history_captures" / "shot.png"
            capture.parent.mkdir(parents=True, exist_ok=True)
            capture.write_bytes(b"fake")
            report = sync_history_payload_to_memory(
                config,
                client,
                chat_name="TestUser",
                payload={
                    "messages": [
                        {"kind": "text", "timestamp": "2026年4月3日 16:16", "text": "我最近有点累"},
                        {"kind": "image_ref", "timestamp": "2026年4月3日 16:17", "text": "图片", "capture_path": str(capture)},
                    ]
                },
                state=state,
                include_captures=True,
                dry_run=False,
            )
            self.assertEqual(report["chat_name"], "TestUser")
            self.assertEqual(report["status"], "ingested")
            self.assertEqual(len(client.artifact_calls), 2)
            export_name = Path(client.artifact_calls[0]["path"]).name
            self.assertIn("_TestUser_", export_name)
            self.assertTrue(export_name.endswith("_history.md"))
            self.assertEqual(client.artifact_calls[1]["path"], str(capture))
            self.assertTrue(state.last_history_sync_digest("TestUser"))

            again = sync_history_payload_to_memory(
                config,
                client,
                chat_name="TestUser",
                payload={
                    "messages": [
                        {"kind": "text", "timestamp": "2026年4月3日 16:16", "text": "我最近有点累"},
                        {"kind": "image_ref", "timestamp": "2026年4月3日 16:17", "text": "图片", "capture_path": str(capture)},
                    ]
                },
                state=state,
                include_captures=True,
                dry_run=False,
            )
            self.assertEqual(again["status"], "skipped_duplicate_history")
            self.assertEqual(len(client.artifact_calls), 2)

    def test_maybe_ingest_turn_artifact_only_for_rich_media(self) -> None:
        client = FakeClient()
        plain = ChatTurn(chat_name="TestUser", text="你好", metadata={"pyweixin_kind": "text"})
        self.assertIsNone(maybe_ingest_turn_artifact(plain, client=client))

        rich = ChatTurn(
            chat_name="TestUser",
            text="图片 2026年4月3日 16:17",
            metadata={
                "pyweixin_kind": "image_ref",
                "capture_path": "/tmp/fake.png",
                "visible_timestamp": "2026年4月3日 16:17",
            },
        )
        report = maybe_ingest_turn_artifact(rich, client=client, dry_run=True)
        self.assertIsNotNone(report)
        self.assertEqual(len(client.artifact_calls), 1)
        self.assertEqual(client.artifact_calls[0]["path"], "/tmp/fake.png")

    def test_process_one_turn_ignores_self_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(
                whitelist=["TestUser"],
                state_file=root / "state.json",
                outbox_file=root / "outbox.jsonl",
            )
            adapter = JsonInboxAdapter(
                HelperConfig(
                    inbox_dir=root / "inbox",
                    processed_dir=root / "processed",
                    outbox_file=root / "outbox.jsonl",
                )
            )
            state = StateStore(config.state_file)
            client = FakeClient()
            turn = ChatTurn(chat_name="TestUser", text="I刚说的话", metadata={"is_self": True})
            result = process_one_turn(turn, client=client, state=state, adapter=adapter, config=config)
            self.assertEqual(result["reason"], "self_message")
            self.assertEqual(len(client.calls), 0)

    def test_process_one_turn_ignores_recent_outbound_echo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(
                whitelist=["TestUser"],
                state_file=root / "state.json",
                outbox_file=root / "outbox.jsonl",
            )
            adapter = JsonInboxAdapter(
                HelperConfig(
                    inbox_dir=root / "inbox",
                    processed_dir=root / "processed",
                    outbox_file=root / "outbox.jsonl",
                )
            )
            state = StateStore(config.state_file)
            client = FakeClient()
            visible_digest = "digest-001"
            state.remember_outbound("TestUser", text="I在。", digest=visible_digest, now=123)
            turn = ChatTurn(chat_name="TestUser", text="I在。", metadata={"visible_digest": visible_digest})
            result = process_one_turn(turn, client=client, state=state, adapter=adapter, config=config)
            self.assertEqual(result["reason"], "outbound_echo")
            self.assertEqual(len(client.calls), 0)

    def test_process_one_turn_ignores_recent_outbound_echo_by_bubble_text_when_direction_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = HelperConfig(
                whitelist=["TestUser"],
                state_file=root / "state.json",
                outbox_file=root / "outbox.jsonl",
            )
            adapter = JsonInboxAdapter(
                HelperConfig(
                    inbox_dir=root / "inbox",
                    processed_dir=root / "processed",
                    outbox_file=root / "outbox.jsonl",
                )
            )
            state = StateStore(config.state_file)
            client = FakeClient()
            state.remember_outbound(
                "TestUser",
                text="I在。 慢慢说。",
                bubbles=["I在。", "慢慢说。"],
                now=123,
            )
            turn = ChatTurn(
                chat_name="TestUser",
                text="慢慢说。",
                metadata={"direction": "unknown", "direction_confidence": 0.0},
            )
            with mock.patch("windows_helper.wechat_helper.time.time", return_value=130):
                result = process_one_turn(turn, client=client, state=state, adapter=adapter, config=config)
            self.assertEqual(result["reason"], "outbound_echo")
            self.assertEqual(len(client.calls), 0)


if __name__ == "__main__":
    unittest.main()
