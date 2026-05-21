from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from holo_host import cli
from holo_host.codex_runner import CodexRunner, DeepSeekProvider
from holo_host.config import load_config
from holo_host.models import ProcessorTaskRequest
from holo_host.stage105_provider_packet_stream import stage105_packet_stream_plan
from holo_host.stage106_deepseek_tool_adapter import (
    build_stage106_deepseek_adapter_plan,
    build_tool_payload,
    parse_provider_tool_calls,
)


LOOKUP_QUERY = "\u67e5\u4e00\u4e0b\u6700\u65b0\u72b6\u6001"


def _stage105_lookup_plan() -> dict:
    return stage105_packet_stream_plan(
        {
            "uncertainty_level": 0.82,
            "selected_action": {"action_type": "external_lookup", "why_now": "needs current evidence"},
        },
        query=LOOKUP_QUERY,
        max_packets=4,
    )


def test_stage106_translates_stage105_tool_request_to_deepseek_tools() -> None:
    stage105 = _stage105_lookup_plan()

    plan = build_stage106_deepseek_adapter_plan(stage105["tool_requests"], query=LOOKUP_QUERY)

    assert plan["schema"] == "holo.stage106.deepseek_tool_adapter.v1"
    assert plan["stage"] == 106
    assert plan["tool_count"] == 1
    assert plan["provider_payload"]["tool_choice"] == "auto"
    tool = plan["provider_payload"]["tools"][0]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "external_lookup"
    assert "query" in tool["function"]["parameters"]["required"]


def test_stage106_rejects_unknown_provider_tool_call() -> None:
    decoded = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "shell_exec", "arguments": "{\"cmd\":\"whoami\"}"},
                        }
                    ]
                }
            }
        ]
    }

    calls = parse_provider_tool_calls(decoded)

    assert calls[0]["status"] == "rejected"
    assert calls[0]["allowed"] is False
    assert calls[0]["error"] == "unknown_tool"


def test_stage106_rejects_non_object_tool_arguments() -> None:
    decoded = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "external_lookup", "arguments": "[\"bad\"]"},
                        }
                    ]
                }
            }
        ]
    }

    calls = parse_provider_tool_calls(decoded)

    assert calls[0]["status"] == "rejected"
    assert calls[0]["allowed"] is False
    assert calls[0]["error"] == "arguments_not_object"


def test_stage106_parses_allowed_deepseek_tool_call() -> None:
    decoded = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_lookup_1",
                            "type": "function",
                            "function": {
                                "name": "external_lookup",
                                "arguments": json.dumps({"query": LOOKUP_QUERY, "max_results": 3}, ensure_ascii=False),
                            },
                        }
                    ],
                },
            }
        ]
    }

    calls = parse_provider_tool_calls(decoded)

    assert calls == [
        {
            "id": "call_lookup_1",
            "type": "function",
            "name": "external_lookup",
            "arguments": {"query": LOOKUP_QUERY, "max_results": 3},
            "allowed": True,
            "status": "accepted",
            "error": "",
        }
    ]


def test_deepseek_provider_attaches_tools_only_when_explicitly_enabled() -> None:
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

[processor_fabric]
deepseek_base_url = "https://api.deepseek.com"
deepseek_api_key_env = "TEST_DEEPSEEK_API_KEY"

[provider_backends.micro_fast]
primary_provider = "deepseek"
backup_provider = "openai_compatible"
model = "deepseek-v4-flash"
reasoning_effort = "low"
max_output_tokens = 128
""".strip(),
            encoding="utf-8",
        )
        config = load_config(str(config_path), repo_root=root)
        runner = CodexRunner(config)
        provider = DeepSeekProvider()
        captured: dict[str, object] = {}

        def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_lookup_1",
                                    "type": "function",
                                    "function": {
                                        "name": "external_lookup",
                                        "arguments": "{\"query\":\"latest status\"}",
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            }

        with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
            with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                result = provider.run_task(
                    runner,
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="need current status",
                        lane="micro_fast",
                        metadata={
                            "enable_provider_tools": True,
                            "tool_requests": _stage105_lookup_plan()["tool_requests"],
                        },
                    ),
                    spec={"output_schema": "plain_text"},
                    lane_name="micro_fast",
                    lane_config=config.processor_fabric.provider_backends["micro_fast"],
                )

        payload = captured["payload"]
        assert isinstance(payload, dict)
        assert payload["tool_choice"] == "auto"
        assert payload["tools"] == build_tool_payload(_stage105_lookup_plan()["tool_requests"])["tools"]
        assert result.metadata["tool_call_count"] == 1
        assert result.metadata["tool_calls"][0]["name"] == "external_lookup"
        assert result.metadata["finish_reason"] == "tool_calls"


def test_stage106_cli_builds_dry_run_adapter_plan(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "_inspect_mind_payload",
        lambda *args, **kwargs: (
            {
                "mind_packet": {
                    "uncertainty_level": 0.82,
                    "selected_action": {"action_type": "external_lookup", "why_now": "needs current evidence"},
                }
            },
            "test",
        ),
    )

    result = cli.main(["stage106-deepseek-tool-adapter", "--query", LOOKUP_QUERY])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 106
    assert payload["source"] == "test"
    assert payload["provider_payload"]["tools"][0]["function"]["name"] == "external_lookup"
