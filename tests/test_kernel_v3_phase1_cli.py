import json
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "kernel_v3.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def test_holo_v3_cli_surfaces_run_trace_resume_context_tools_and_tail():
    journal_path = Path("kernel_v3/.test-cli-journal.jsonl")
    index_path = Path("kernel_v3/.test-cli-journal.sqlite")
    _unlink(journal_path, index_path)
    try:
        run = _run_cli("--journal", str(journal_path), "--index", str(index_path), "run", "hello")
        run_payload = json.loads(run.stdout)
        task_id = run_payload["task_id"]
        assert run_payload["status"] == "completed"

        trace = _run_cli("--journal", str(journal_path), "--index", str(index_path), "trace", task_id)
        assert f"Trace {task_id}" in trace.stdout
        assert "feedback" in trace.stdout

        context = _run_cli("--journal", str(journal_path), "--index", str(index_path), "context", task_id)
        context_payload = json.loads(context.stdout)
        assert context_payload["task_id"] == task_id
        assert context_payload["payload_hash"]

        tools = _run_cli("--journal", str(journal_path), "--index", str(index_path), "tools")
        assert "respond" in tools.stdout
        assert "workspace.search" in tools.stdout
        assert "file.read" in tools.stdout

        resume = _run_cli("--journal", str(journal_path), "--index", str(index_path), "resume", task_id, "more")
        resume_payload = json.loads(resume.stdout)
        assert resume_payload["task_id"] == task_id
        assert resume_payload["status"] == "completed"

        tail = _run_cli("--journal", str(journal_path), "--index", str(index_path), "journal", "tail")
        assert "result" in tail.stdout
    finally:
        _unlink(journal_path, index_path)


def _unlink(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()
