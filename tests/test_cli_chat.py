from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from holo_host import cli


class CliChatTests(unittest.TestCase):
    def test_chat_payload_marks_cli_as_single_subject_non_admin_client(self) -> None:
        payload = cli._chat_payload(
            text="ping",
            channel="holo_cli",
            thread_key="holo_cli:main",
            chat_name="HoloCLI",
            sender="Operator",
        )

        self.assertEqual(payload["channel"], "holo_cli")
        self.assertEqual(payload["thread_key"], "holo_cli:main")
        self.assertEqual(payload["chat_name"], "HoloCLI")
        self.assertEqual(payload["metadata"]["client_context_policy"], "single_subject_thread")
        self.assertFalse(payload["metadata"]["client_capabilities"]["memory_admin"])
        self.assertFalse(payload["metadata"]["client_capabilities"]["subject_settings"])
        self.assertTrue(str(payload["message_id"]).startswith("holo_cli-cli-"))

    def test_chat_once_parser_uses_live_reply_without_local_fallback(self) -> None:
        calls: list[dict] = []

        def fake_live_request(config_path, *, method, path, payload=None, timeout=0, **_kwargs):
            calls.append(
                {
                    "config_path": config_path,
                    "method": method,
                    "path": path,
                    "payload": payload,
                    "timeout": timeout,
                }
            )
            return {"action": "reply", "text": "CLI online"}

        with mock.patch("holo_host.cli._live_api_request", side_effect=fake_live_request), mock.patch(
            "sys.stdout"
        ) as stdout:
            result = cli.main(["chat", "--once", "ping", "--no-local-fallback", "--timeout", "3"])

        self.assertEqual(result, 0)
        self.assertEqual(calls[0]["method"], "POST")
        self.assertEqual(calls[0]["path"], "/reply")
        self.assertEqual(calls[0]["timeout"], 3.0)
        self.assertFalse(calls[0]["payload"]["metadata"]["client_capabilities"]["memory_admin"])
        self.assertIn("CLI online", "".join(call.args[0] for call in stdout.write.call_args_list if call.args))

    def test_chat_response_text_uses_bubbles_and_action_fallbacks(self) -> None:
        self.assertEqual(cli._chat_response_text({"bubbles": [{"text": "a"}, "b"]}), "a\nb")
        self.assertEqual(cli._chat_response_text({"text": "a b", "bubbles": [{"text": "a"}, "b"]}), "a\nb")
        self.assertEqual(cli._chat_response_text({"action": "silence", "reason": "low_salience"}), "[silence: low_salience]")

    def test_chat_response_text_replaces_lone_surrogates_before_printing(self) -> None:
        self.assertEqual(cli._chat_response_text({"text": "bad\ud800"}), "bad?")

    def test_chat_json_print_replaces_lone_surrogates_before_printing(self) -> None:
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            cli._print_chat_json({"text": "bad\ud800"})

        self.assertEqual(json.loads(stdout.getvalue())["text"], "bad?")

    def test_interactive_snapshot_replaces_lone_surrogates_before_printing(self) -> None:
        with mock.patch(
            "holo_host.cli.command_snapshot_memory_payload",
            return_value={"label": "bad\ud800"},
        ), mock.patch("builtins.input", side_effect=["/snapshot", "/quit"]), mock.patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            result = cli.command_chat(
                None,
                thread_key="holo_cli:main",
                chat_name="HoloCLI",
                channel="holo_cli",
                sender="Operator",
                once=None,
                json_output=False,
                no_local_fallback=True,
                timeout=3.0,
            )

        self.assertEqual(result, 0)
        self.assertIn('"label": "bad?"', stdout.getvalue())

    def test_interactive_help_keeps_reset_outside_chat(self) -> None:
        self.assertIn("Reset is intentionally not available inside chat", cli.CHAT_HELP)
        self.assertIn("reset-memory", cli.CHAT_HELP)


if __name__ == "__main__":
    unittest.main()
