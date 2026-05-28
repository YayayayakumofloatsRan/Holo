from pathlib import Path

from kernel_v3.context import ArtifactStore, MemoryRead
from kernel_v3.contracts import ArtifactRef
from kernel_v3.journal import JournalStore


def test_memory_read_queries_historical_observations_and_artifacts():
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="observation",
        data={
            "observation_id": "obs-1",
            "kind": "tool_result",
            "status": "ok",
            "source": "tool:file.read",
            "content": {"path": "README.md", "text": "Holo Kernel v3"},
        },
        observation_ref="obs-1",
        artifact_refs=["artifact-obs-1"],
    )
    journal.append(
        task_id="task-2",
        run_id="run-1",
        step_id="step-1",
        kind="observation",
        data={
            "observation_id": "obs-2",
            "kind": "tool_result",
            "status": "ok",
            "source": "tool:workspace.search",
            "content": {"matches": [{"path": "notes.md", "text": "Phase3 context"}]},
        },
        observation_ref="obs-2",
        artifact_refs=["artifact-obs-2"],
    )
    store = ArtifactStore.in_memory(
        [
            ArtifactRef(
                artifact_id="artifact-obs-1",
                kind="observation_payload",
                uri="journal://observations/obs-1",
                payload_hash="hash-1",
                metadata={"path": "README.md", "observation_id": "obs-1"},
            ),
            ArtifactRef(
                artifact_id="artifact-obs-2",
                kind="observation_payload",
                uri="journal://observations/obs-2",
                payload_hash="hash-2",
                metadata={"path": "notes.md", "observation_id": "obs-2"},
            ),
        ]
    )

    memory = MemoryRead(journal=journal, artifact_store=store)

    observations = memory.query_observations(query="Phase3", limit=5)
    artifacts = memory.query_artifacts(query="README", limit=5)

    assert [item.observation_id for item in observations] == ["obs-2"]
    assert observations[0].record_ref == "ledger-2"
    assert observations[0].artifact_refs == ["artifact-obs-2"]
    assert [artifact.artifact_id for artifact in artifacts] == ["artifact-obs-1"]


def test_memory_read_filters_by_task_and_preserves_journal_order():
    journal = JournalStore.in_memory()
    for index, task_id in enumerate(["task-a", "task-b", "task-a"], start=1):
        journal.append(
            task_id=task_id,
            run_id="run-1",
            step_id=f"step-{index}",
            kind="observation",
            data={
                "observation_id": f"obs-{index}",
                "kind": "tool_result",
                "status": "ok",
                "content": {"text": f"shared query value {index}"},
            },
            observation_ref=f"obs-{index}",
        )

    observations = MemoryRead(journal=journal).query_observations(
        query="shared query",
        task_id="task-a",
        limit=5,
    )

    assert [item.observation_id for item in observations] == ["obs-1", "obs-3"]
    assert [item.record_ref for item in observations] == ["ledger-1", "ledger-3"]


def test_artifact_store_roundtrips_jsonl_without_private_file_access():
    path = Path("kernel_v3/.test-phase3-artifacts.jsonl")
    if path.exists():
        path.unlink()
    try:
        store = ArtifactStore(path)
        artifact = ArtifactRef(
            artifact_id="artifact-1",
            kind="observation_payload",
            uri="journal://observations/obs-1",
            payload_hash="hash-1",
            metadata={"path": "README.md"},
        )

        store.put(artifact)

        reloaded = ArtifactStore(path)
        assert reloaded.get("artifact-1") == artifact
        assert reloaded.list() == [artifact]
    finally:
        if path.exists():
            path.unlink()
