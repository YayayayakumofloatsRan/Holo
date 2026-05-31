import json
import subprocess
import sys
from pathlib import Path

from kernel_v3.context import ArtifactStore, BudgetExceeded, ContextPackCompiler, Redactor
from kernel_v3.journal import JournalStore
from kernel_v3.session import SessionEngine


def test_redactor_masks_secret_values_and_private_runtime_paths():
    redactor = Redactor(private_path_markers=["D:/Holo/holo/.holo_runtime"])

    redacted, markers = redactor.redact(
        {
            "api_key": "sk-test-secret",
            "path": "D:/Holo/holo/.holo_runtime/live.json",
            "nested": [
                "token=abc123",
                "https://example.test/report?access_token=live-secret-token-1234567890",
                "safe",
            ],
        }
    )

    encoded = json.dumps(redacted, ensure_ascii=False)
    assert "sk-test-secret" not in encoded
    assert "abc123" not in encoded
    assert "live-secret-token" not in encoded
    assert "access_token" not in encoded
    assert "D:/Holo/holo/.holo_runtime" not in encoded
    assert sorted(markers) == ["PRIVATE_PATH", "SECRET"]


def test_context_budget_validator_rejects_oversized_sections():
    journal = JournalStore.in_memory()
    task = SessionEngine.from_journal(journal).start("large", thread_id="thread-a", journal=journal)
    journal.append(
        task_id=task.task_id,
        run_id=task.run_id,
        step_id="step-1",
        kind="observation",
        data={"observation_id": "obs-1", "content": {"text": "x" * 400}},
        observation_ref="obs-1",
    )
    compiler = ContextPackCompiler(token_budget=768, section_budget=80)

    try:
        compiler.compile(task, journal, step_id="step-1")
    except BudgetExceeded as exc:
        assert exc.section_name == "recent_observations"
        assert exc.limit == 80
    else:
        raise AssertionError("expected BudgetExceeded")


def test_context_compiler_redacts_private_paths_inside_sections():
    journal = JournalStore.in_memory()
    task = SessionEngine.from_journal(journal).start("inspect runtime", thread_id="thread-a", journal=journal)
    journal.append(
        task_id=task.task_id,
        run_id=task.run_id,
        step_id="step-1",
        kind="observation",
        data={
            "observation_id": "obs-1",
            "kind": "tool_result",
            "status": "ok",
            "content": {"path": "D:/Holo/holo/.holo_runtime/live.json"},
        },
        observation_ref="obs-1",
    )

    pack = ContextPackCompiler(
        redactor=Redactor(private_path_markers=["D:/Holo/holo/.holo_runtime"]),
        token_budget=768,
        section_budget=128,
    ).compile(task, journal, step_id="step-1")
    encoded = json.dumps(pack.to_dict(), ensure_ascii=False)

    assert "D:/Holo/holo/.holo_runtime" not in encoded
    assert "[REDACTED:PRIVATE_PATH]" in encoded
    assert pack.redactions == ["PRIVATE_PATH"]


def test_context_compiler_redacts_secret_like_artifact_metadata():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    task = SessionEngine.from_journal(journal).start("inspect artifact", thread_id="thread-a", journal=journal)
    artifact = artifacts.write_blob(
        kind="retrieval_fetched_document",
        payload="artifact payload",
        metadata={"uri": "https://example.test/report?access_token=live-secret-token-1234567890"},
    )
    journal.append(
        task_id=task.task_id,
        run_id=task.run_id,
        step_id="step-1",
        kind="observation",
        data={
            "observation_id": "obs-1",
            "kind": "tool_result",
            "status": "ok",
            "content": {"artifact_id": artifact.artifact_id},
        },
        observation_ref="obs-1",
        artifact_refs=[artifact.artifact_id],
    )

    pack = ContextPackCompiler(
        artifact_store=artifacts,
        token_budget=1024,
        section_budget=256,
    ).compile(task, journal, step_id="step-1")
    encoded = json.dumps(pack.to_dict(), ensure_ascii=False)

    assert "live-secret-token" not in encoded
    assert "access_token" not in encoded
    assert "[REDACTED:SECRET]" in encoded
    assert pack.redactions == ["SECRET"]


def test_holo_v3_context_inspection_commands_and_golden_transcript():
    journal_path = Path("kernel_v3/.test-phase3-cli-journal.jsonl")
    index_path = Path("kernel_v3/.test-phase3-cli-journal.sqlite")
    for path in [journal_path, index_path]:
        if path.exists():
            path.unlink()
    try:
        run = _run_cli("--journal", str(journal_path), "--index", str(index_path), "run", "phase3")
        task_id = json.loads(run.stdout)["task_id"]

        dump = _run_cli("--journal", str(journal_path), "--index", str(index_path), "context", "dump", task_id)
        sections = _run_cli("--journal", str(journal_path), "--index", str(index_path), "context", "sections", task_id)
        artifacts = _run_cli("--journal", str(journal_path), "--index", str(index_path), "context", "artifacts", task_id)

        dump_payload = json.loads(dump.stdout)
        assert dump_payload["context_id"] == f"ctx-{task_id}-run-1-step-1"
        assert json.loads(sections.stdout) == [
            "user_event",
            "active_task_state",
            "project_profile",
            "recent_observations",
            "artifact_references",
            "memory_refs",
            "citations",
            "tool_briefs",
            "permission_state",
        ]
        assert json.loads(artifacts.stdout) == [
            {
                "artifact_id": "artifact-obs-act-respond",
                "kind": "unresolved",
                "metadata": {},
                "payload_hash": "",
                "status": "unresolved",
                "uri": "journal://artifacts/artifact-obs-act-respond",
            }
        ]
        assert dump_payload == _golden_cli_context(task_id)
    finally:
        for path in [journal_path, index_path]:
            if path.exists():
                path.unlink()


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "holo-v3", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def _golden_cli_context(task_id: str) -> dict[str, object]:
    return {
        "budget": {
            "section_count": 9,
            "section_limit": 1024,
            "section_units": [32, 42, 38, 63, 75, 66, 89, 109, 24],
            "token_budget": 4096,
            "total_units": 538,
            "within_budget": True,
        },
        "context_id": f"ctx-{task_id}-run-1-step-1",
        "memory_refs": ["obs-act-respond"],
        "payload_hash": "1e6fae0d5ad9e6c948bb1e99f4b703ab625a5691a21a3be179d5931bff2b2400",
        "redactions": [],
        "run_id": "run-1",
        "sections": [
            {"name": "user_event", "records": [{"event_id": "evt-run-1-input", "text": "phase3"}]},
            {
                "name": "active_task_state",
                "run_id": "run-1",
                "status": "completed",
                "step_id": "step-1",
                "task_id": task_id,
            },
            {
                "name": "project_profile",
                "profile": {"constraints": [], "project_id": "local", "redaction_markers": [], "summary": ""},
            },
            {
                "name": "recent_observations",
                "records": [
                    {
                        "content": {"text": "respond: phase3"},
                        "kind": "respond_result",
                        "observation_id": "obs-act-respond",
                        "source": "respond",
                        "status": "ok",
                    }
                ],
            },
            {
                "artifacts": [
                    {
                        "artifact_id": "artifact-obs-act-respond",
                        "kind": "unresolved",
                        "metadata": {},
                        "payload_hash": "",
                        "status": "unresolved",
                        "uri": "journal://artifacts/artifact-obs-act-respond",
                    }
                ],
                "name": "artifact_references",
            },
            {
                "name": "memory_refs",
                "refs": [
                    {
                        "artifact_refs": ["artifact-obs-act-respond"],
                        "observation_id": "obs-act-respond",
                        "record_ref": "ledger-7",
                        "source": "respond",
                        "status": "ok",
                    }
                ],
            },
            {
                "items": [
                    {
                        "artifact_ref": "artifact-obs-act-respond",
                        "citation_id": "cite-ledger-7-artifact-obs-act-respond",
                        "metadata": {},
                        "quote": "respond: phase3",
                        "record_ref": "ledger-7",
                        "uri": "journal://records/ledger-7",
                    }
                ],
                "name": "citations",
            },
            {
                "name": "tool_briefs",
                "tools": [
                    {"name": "respond", "side_effect": "none"},
                    {"name": "ask_user", "side_effect": "none"},
                    {"name": "workspace.search", "side_effect": "read"},
                    {"name": "file.read", "side_effect": "read"},
                    {"name": "blocked_external_write", "side_effect": "destructive"},
                ],
            },
            {"name": "permission_state", "permission": {"allowed_permissions": [], "mode": "read_write"}},
        ],
        "source_refs": ["ledger-1", "ledger-7", "artifact-obs-act-respond"],
        "task_id": task_id,
        "thread_id": "local:default",
    }
