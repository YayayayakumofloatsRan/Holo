from __future__ import annotations

from holo_host.tool_need import classify_tool_need
from holo_host.stage120_tool_affordance_optimizer import optimize_stage120_tool_requests
from holo_host.stage106_deepseek_tool_adapter import STAGE119_DEFAULT_TOOL_NAMES


def _requests() -> list[dict[str, object]]:
    return [{"name": name, "reason": "library", "payload": {}} for name in STAGE119_DEFAULT_TOOL_NAMES]


def test_tool_need_classifies_workspace_git_tests_lookup_and_mutation() -> None:
    need = classify_tool_need("Read your own directory, run pytest, check git diff, then search the latest paper.")

    assert need["needs_workspace"] is True
    assert need["needs_tests"] is True
    assert need["needs_git"] is True
    assert need["needs_external_lookup"] is True
    assert need["needs_mutation_permission"] is False
    assert set(need["tool_groups"]) >= {"workspace", "tests", "git"}


def test_tool_need_feeds_stage120_bounded_selection() -> None:
    selected = optimize_stage120_tool_requests(
        _requests(),
        query="Read your own directory and run pytest.",
        tool_need=classify_tool_need("Read your own directory and run pytest."),
    )
    names = {item["name"] for item in selected}

    assert {"workspace_inspect", "file_read", "test_runner", "test_discover"}.issubset(names)
    assert len(names) <= 18


def test_tool_need_marks_mutation_tools_without_grant() -> None:
    need = classify_tool_need("write a file and git commit the result")
    selected = optimize_stage120_tool_requests(_requests(), query="write a file and git commit the result", tool_need=need)
    names = {item["name"] for item in selected}

    assert need["needs_mutation_permission"] is True
    assert "workspace_edit" not in names
    assert "command_modify" not in names

