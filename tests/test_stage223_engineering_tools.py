from __future__ import annotations

from pathlib import Path

from holo_agent.tools import (
    ApplyPatchTool,
    FileReadTool,
    GitDiffTool,
    GitStatusTool,
    TestRunTool,
    ToolRegistry,
    WorkspaceSearchTool,
)


def test_file_read_records_line_range_inside_workspace(tmp_path: Path) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("one\n二\n三\nfour\n", encoding="utf-8")

    obs = FileReadTool(tmp_path).run(path="src/app.py", start_line=2, end_line=3)

    assert obs.status == "ok"
    assert obs.data["path"] == "src/app.py"
    assert obs.data["start_line"] == 2
    assert obs.data["end_line"] == 3
    assert "二" in obs.data["text"]


def test_file_read_rejects_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    obs = FileReadTool(tmp_path).run(path="../outside.txt")

    assert obs.status == "rejected"
    assert "outside workspace" in obs.summary


def test_git_status_and_diff_record_commands(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")

    status = GitStatusTool(tmp_path).run()
    diff = GitDiffTool(tmp_path).run(path="README.md")

    assert status.tool == "git_status"
    assert status.data["command"] == ["git", "status", "--short"]
    assert diff.tool == "git_diff"
    assert diff.data["command"] == ["git", "diff", "--", "README.md"]


def test_test_run_allows_pytest_without_shell(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    obs = TestRunTool(tmp_path).run(command="python -m pytest -q test_sample.py", timeout_seconds=20)

    assert obs.status == "ok"
    assert obs.data["shell"] is False
    assert obs.data["command"][:3] == ["python", "-m", "pytest"]


def test_test_run_rejects_shell_chaining(tmp_path: Path) -> None:
    obs = TestRunTool(tmp_path).run(command="python -m pytest -q; echo bad")

    assert obs.status == "rejected"
    assert obs.summary == "command_not_allowlisted"


def test_apply_patch_changes_workspace_file(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("old\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: README.md
@@
-old
+new
*** End Patch
"""

    obs = ApplyPatchTool(tmp_path).run(patch_text=patch)

    assert obs.status == "ok"
    assert target.read_text(encoding="utf-8") == "new\n"
    assert obs.data["files_changed"] == ["README.md"]


def test_apply_patch_rejects_path_escape(tmp_path: Path) -> None:
    patch = """*** Begin Patch
*** Update File: ../outside.txt
@@
-old
+new
*** End Patch
"""

    obs = ApplyPatchTool(tmp_path).run(patch_text=patch)

    assert obs.status == "rejected"
    assert "outside workspace" in obs.summary


def test_default_registry_exposes_engineering_tools(tmp_path: Path) -> None:
    names = {item["name"] for item in ToolRegistry.default(root=tmp_path).specs()}

    assert {
        "workspace_search",
        "file_read",
        "git_status",
        "git_diff",
        "test_run",
        "apply_patch",
    }.issubset(names)
