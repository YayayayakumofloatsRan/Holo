from __future__ import annotations

import json

from holo_host import cli
from holo_host.models import TurnContext
from holo_host.processors import _agent_tool_requests, build_attention_state
from holo_host.stage106_deepseek_tool_adapter import STAGE119_DEFAULT_TOOL_NAMES, build_tool_payload


def _context(text: str, *, capability_context: dict | None = None) -> TurnContext:
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="User",
        user_text=text,
        sidecar={},
        mind_packet={"selected_action": {"action_type": "reply_once", "score": 0.9}},
        attention_state=build_attention_state(text, channel="holo_cli"),
        emotion_state={},
        history=[],
        metadata={},
        capability_context=dict(capability_context or {}),
    )


def _payload_chars(tool_names: list[str]) -> int:
    payload = build_tool_payload([{"name": name, "reason": "test", "payload": {}} for name in tool_names])
    return len(json.dumps(payload, ensure_ascii=False))


def test_stage120_keeps_full_library_but_sends_bounded_working_set() -> None:
    full_chars = _payload_chars(list(STAGE119_DEFAULT_TOOL_NAMES))
    requests = _agent_tool_requests(_context("普通聊天，先回忆一下我们刚才在做什么"))
    names = [item["name"] for item in requests]
    selected_chars = _payload_chars(names)

    assert len(STAGE119_DEFAULT_TOOL_NAMES) >= 40
    assert 6 <= len(names) <= 18
    assert selected_chars < full_chars * 0.55
    assert "memory_recall" in names
    assert "workspace_inspect" in names


def test_stage120_selects_topic_specific_code_test_and_git_tools() -> None:
    requests = _agent_tool_requests(
        _context("检查 processors.py 的工具选择算法，修改测试，然后运行 pytest 并查看 git diff")
    )
    names = {item["name"] for item in requests}

    assert len(names) <= 18
    assert {"file_read", "file_search", "symbol_search", "test_runner", "test_discover", "git_diff", "git_status"}.issubset(names)
    assert "artifact_list" not in names


def test_stage120_preserves_explicit_requests_and_permission_grants() -> None:
    requests = _agent_tool_requests(
        _context(
            "把结果写入文档并 git add",
            capability_context={
                "tool_requests": [
                    {"name": "memory_warehouse_search", "reason": "explicit audit", "payload": {"query": "Stage119"}}
                ],
                "tool_permission_grants": [
                    {"tool": "file_write"},
                    {"tool": "command_modify", "argv_prefix": ["git", "add"]},
                ],
            },
        )
    )
    names = [item["name"] for item in requests]

    assert len(names) <= 18
    assert "memory_warehouse_search" in names
    assert "file_write" in names
    assert "command_modify" in names
    assert names.index("memory_warehouse_search") < 6


def test_stage120_can_request_full_tool_scope_for_diagnostics() -> None:
    requests = _agent_tool_requests(
        _context("列出完整工具库", capability_context={"tool_scope": "full"})
    )
    names = {item["name"] for item in requests}

    assert len(names) >= 40
    assert set(STAGE119_DEFAULT_TOOL_NAMES).issubset(names)


def test_stage120_cli_reports_bounded_tool_selection(capsys) -> None:
    result = cli.main(["stage120-tool-affordance", "--query", "run pytest and git diff"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 120
    assert payload["library_tool_count"] >= 40
    assert payload["selected_tool_count"] <= 18
    assert "test_runner" in payload["selected_tools"]
    assert "git_diff" in payload["selected_tools"]
