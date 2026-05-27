from __future__ import annotations

import subprocess
from pathlib import Path

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.engineering_action_fabric import (
    evaluate_engineering_claim_grounding,
    normalize_engineering_action_ledger,
)
from holo_host.engineering_workspace_tools import (
    apply_patch as apply_workspace_patch,
    file_read,
    git_diff,
    git_status,
    test_run,
    workspace_search,
)
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "demo.py").write_text("VALUE = 'old'\nprint(VALUE)\n", encoding="utf-8")
    (root / "README.md").write_text("Stage154 engineering fabric\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return root


def test_workspace_search_records_ledger(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    row = workspace_search(repo, query="Stage154", glob="*.md")

    assert row["schema"] == "holo.stage154.engineering_action.v1"
    assert row["action_type"] == "workspace_search"
    assert row["status"] == "ok"
    assert row["files_read"] == ["README.md"]
    assert "README.md" in row["stdout_summary"]


def test_file_read_records_path_and_line_evidence(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    row = file_read(repo, "src/demo.py", start_line=1, end_line=1)

    assert row["action_type"] == "file_read"
    assert row["status"] == "ok"
    assert row["files_read"] == ["src/demo.py"]
    assert "1: VALUE = 'old'" in row["stdout_summary"]


def test_apply_patch_records_changed_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = """diff --git a/src/demo.py b/src/demo.py
--- a/src/demo.py
+++ b/src/demo.py
@@ -1,2 +1,2 @@
-VALUE = 'old'
+VALUE = 'new'
 print(VALUE)
"""

    row = apply_workspace_patch(repo, patch)

    assert row["action_type"] == "apply_patch"
    assert row["status"] == "ok"
    assert row["files_changed"] == ["src/demo.py"]
    assert "VALUE = 'new'" in (repo / "src" / "demo.py").read_text(encoding="utf-8")


def test_test_run_records_command_and_status(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "test_stage154_smoke.py").write_text("def test_stage154_ok():\n    assert True\n", encoding="utf-8")
    command = "python -m pytest test_stage154_smoke.py -q"

    row = test_run(repo, command)

    assert row["action_type"] == "test_run"
    assert row["status"] == "ok"
    assert row["commands_run"] == [command]
    assert row["tests_run"] == [command]
    assert "passed" in row["stdout_summary"]


def test_final_engineering_claim_without_ledger_is_unverified() -> None:
    report = evaluate_engineering_claim_grounding("I read the file, patched it, and tests passed.", [])

    assert report["schema"] == "holo.stage154.engineering_verification_ledger.v1"
    assert report["status"] == "unverified_engineering_claim"
    assert report["repair_required"] is True
    assert set(report["missing_families"]) >= {"read", "patch", "test"}


def test_final_engineering_claim_with_ledger_is_grounded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "test_stage154_smoke.py").write_text("def test_stage154_ok():\n    assert True\n", encoding="utf-8")
    command = "python -m pytest test_stage154_smoke.py -q"
    ledger = normalize_engineering_action_ledger(
        [
            file_read(repo, "src/demo.py", start_line=1, end_line=1),
            apply_workspace_patch(
                repo,
                """diff --git a/src/demo.py b/src/demo.py
--- a/src/demo.py
+++ b/src/demo.py
@@ -1,2 +1,2 @@
-VALUE = 'old'
+VALUE = 'new'
 print(VALUE)
""",
            ),
            test_run(repo, command),
            git_status(repo),
            git_diff(repo, "src/demo.py"),
        ]
    )

    report = evaluate_engineering_claim_grounding("I read the file, patched it, tests passed, and checked the diff.", ledger)

    assert report["status"] == "grounded"
    assert report["repair_required"] is False
    assert report["missing_families"] == []


def test_dangerous_command_is_rejected_without_approval_ui(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    row = test_run(repo, "git reset --hard")

    assert row["status"] == "rejected"
    assert row["commands_run"] == []
    assert row["stderr_summary"] == "command_not_allowlisted"


def test_cli_event_stream_shows_engineering_actions(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    ledger = [workspace_search(repo, query="Stage154", glob="*.md"), file_read(repo, "README.md")]

    stream = build_agent_event_stream(
        {
            "text": "I read README.md.",
            "engineering_action_ledger": ledger,
            "engineering_claim_grounding": evaluate_engineering_claim_grounding("I read README.md.", ledger),
        },
        user_text="read README.md",
        thread_key="holo_cli:stage154",
        chat_name="HoloCLI",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "[eng:search] status=ok" in rendered
    assert "[eng:read] status=ok" in rendered
    assert "[grounding] status=grounded" in rendered


def test_stage135_topology_includes_engineering_action_fabric_node(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    ledger = [workspace_search(repo, query="Stage154", glob="*.md")]

    topology = build_stage135_i_state_topology(
        user_text="search repo",
        thread_key="holo_cli:stage154",
        chat_name="HoloCLI",
        channel="holo_cli",
        engineering_action_ledger=ledger,
    )

    assert topology["metrics"]["engineering_action_fabric_node_count"] == 1
    assert topology["metrics"]["engineering_action_count"] == 1
