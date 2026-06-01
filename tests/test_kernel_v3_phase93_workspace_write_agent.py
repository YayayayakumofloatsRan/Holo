import json
import hashlib

from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric


def test_phase93_workspace_write_recipe_writes_file_and_redacts_action_body(tmp_path):
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    body = "# Holo write test\n\n" + "generated paragraph " * 40
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "workspace_write",
                "suggested_mode": "workspace_write",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "workspace_write",
                        "text": "write a generated report",
                        "sequence_index": 1,
                        "required_capabilities": ["workspace.write"],
                        "risk": "write",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "workspace.write": {"path": "reports/write-test.md", "text": body}
                            }
                        },
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=artifacts,
        processor_fabric=fabric,
        workspace_root=tmp_path,
    ).run("write the test report", mode="auto", semantic_mode="model")

    assert result.status == "completed"
    assert result.mode == "workspace_write"
    assert (tmp_path / "reports" / "write-test.md").read_text(encoding="utf-8") == body

    write_action = [
        record for record in journal.records(task_id=result.task_id, kind="action")
        if record.data.get("name") == "workspace.write"
    ][0]
    payload = write_action.data["payload"]
    assert "text" not in payload
    assert payload["text_hash"] == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert payload["text_chars"] == len(body)
    assert payload["text_redaction"] == "preview_hash_only"
    encoded_action = json.dumps(write_action.data, ensure_ascii=False)
    assert body not in encoded_action
    assert len(payload["text_preview"]) < len(body)

    observations = journal.records(task_id=result.task_id, kind="observation")
    write_observation = [record for record in observations if record.data.get("source") == "tool:workspace.write"][0]
    assert write_observation.data["status"] == "ok"
    assert write_observation.artifact_refs
    progress = journal.records(task_id=result.task_id, kind="progress_assessment")[-1].data
    assert progress["progress_type"] == "new_file_write"
    evidence = journal.records(task_id=result.task_id, kind="evidence_sufficiency")[-1].data
    assert evidence["sufficient"] is True
    assert evidence["diagnostics"]["workspace_write_count"] == 1


def test_phase93_workspace_write_can_read_before_writing(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "input.md").write_text("source fact: write-chain-ok", encoding="utf-8")
    journal = JournalStore.in_memory()
    body = "# Derived\n\nObserved source fact: write-chain-ok\n"
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "workspace_write",
                "suggested_mode": "workspace_write",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "workspace_write",
                        "text": "read input then write output",
                        "sequence_index": 1,
                        "required_capabilities": ["workspace.search", "file.read", "workspace.write"],
                        "risk": "write",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "workspace.search": {"query": "write-chain-ok"},
                                "file.read": {"path": "notes/input.md"},
                                "workspace.write": {"path": "reports/derived.md", "text": body},
                            }
                        },
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )

    result = AgentRuntime(
        journal=journal,
        processor_fabric=fabric,
        workspace_root=tmp_path,
    ).run("read notes/input.md and write reports/derived.md", mode="auto", semantic_mode="model")

    assert result.status == "completed"
    assert (tmp_path / "reports" / "derived.md").read_text(encoding="utf-8") == body
    actions = [record.data["name"] for record in journal.records(task_id=result.task_id, kind="action")]
    assert actions == ["workspace.search", "file.read", "workspace.write"]
    assert [record.data["status"] for record in journal.records(task_id=result.task_id, kind="observation")] == [
        "ok",
        "ok",
        "ok",
    ]
