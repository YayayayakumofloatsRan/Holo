import json
from pathlib import Path

from kernel_v3.context import ArtifactStore, ContextPackCompiler, MemoryRead, ProjectProfile, verify_hash
from kernel_v3.contracts import ArtifactRef
from kernel_v3.journal import JournalStore
from kernel_v3.session import SessionEngine


def test_context_pack_reads_journal_artifacts_task_state_memory_and_profile_deterministically():
    journal, artifacts, task = _seed_context_inputs()
    profile = ProjectProfile(
        project_id="holo",
        root="D:/Holo/holo",
        summary="Kernel v3 host-owned harness",
        constraints=["no live transports", "offline tests"],
        redaction_markers=["D:/Holo/holo/.holo_runtime"],
    )
    compiler = ContextPackCompiler(
        artifact_store=artifacts,
        memory_read=MemoryRead(journal=journal, artifact_store=artifacts),
        project_profile=profile,
        token_budget=768,
        section_budget=128,
        permission_state={"mode": "read_only"},
    )

    pack = compiler.compile(task, journal, tool_briefs=[{"name": "file.read", "side_effect": "read"}], step_id="step-1")
    same_pack = compiler.compile(task, journal, tool_briefs=[{"name": "file.read", "side_effect": "read"}], step_id="step-1")

    section_names = [section["name"] for section in pack.sections]
    assert section_names == [
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
    assert pack.payload_hash == same_pack.payload_hash
    assert verify_hash(
        {
            "task_id": pack.task_id,
            "run_id": pack.run_id,
            "thread_id": pack.thread_id,
            "sections": pack.sections,
            "source_refs": pack.source_refs,
            "budget": pack.budget,
            "redactions": pack.redactions,
            "memory_refs": pack.memory_refs,
        },
        pack.payload_hash,
    )
    assert pack.budget["token_budget"] == 768
    assert pack.budget["within_budget"] is True
    assert pack.source_refs == ["ledger-2", "ledger-3", "artifact-obs-1"]
    assert pack.memory_refs == ["obs-1"]
    citations = next(section for section in pack.sections if section["name"] == "citations")
    assert citations["items"] == [
        {
            "artifact_ref": "artifact-obs-1",
            "citation_id": "cite-ledger-3-artifact-obs-1",
            "metadata": {"observation_id": "obs-1", "path": "README.md"},
            "quote": "Kernel context from [REDACTED:PRIVATE_PATH]/private.log",
            "record_ref": "ledger-3",
            "uri": "journal://observations/obs-1",
        }
    ]
    assert "D:/Holo/holo/.holo_runtime" not in json.dumps(pack.to_dict(), ensure_ascii=False)
    assert "[REDACTED:PRIVATE_PATH]" in json.dumps(pack.to_dict(), ensure_ascii=False)


def test_context_pack_is_task_and_step_aware_for_resume():
    journal, artifacts, task = _seed_context_inputs()
    journal.append(
        task_id=task.task_id,
        run_id="run-2",
        step_id="step-1",
        kind="resume",
        data={"event_id": "evt-run-2-resume", "payload": {"text": "continue"}},
        event_ref="evt-run-2-resume",
    )
    resumed = SessionEngine.from_journal(journal).resume(
        task.task_id,
        "continue",
        run_index=2,
        thread_id=task.thread_id,
        record_state=False,
    )
    compiler = ContextPackCompiler(
        artifact_store=artifacts,
        memory_read=MemoryRead(journal=journal, artifact_store=artifacts),
        token_budget=768,
        section_budget=128,
    )

    pack = compiler.compile(resumed, journal, step_id="step-1")

    state_section = next(section for section in pack.sections if section["name"] == "active_task_state")
    assert state_section["run_id"] == "run-2"
    assert state_section["step_id"] == "step-1"
    assert pack.context_id == "ctx-task-1-run-2-step-1"


def test_context_pack_hash_changes_when_source_journal_changes():
    journal, artifacts, task = _seed_context_inputs()
    compiler = ContextPackCompiler(
        artifact_store=artifacts,
        memory_read=MemoryRead(journal=journal, artifact_store=artifacts),
        token_budget=768,
        section_budget=128,
    )
    before = compiler.compile(task, journal, step_id="step-1")

    journal.append(
        task_id=task.task_id,
        run_id=task.run_id,
        step_id="step-2",
        kind="observation",
        data={
            "observation_id": "obs-2",
            "kind": "tool_result",
            "status": "ok",
            "content": {"path": "README.md", "text": "additional evidence"},
        },
        observation_ref="obs-2",
    )
    after = compiler.compile(task, journal, step_id="step-2")

    assert before.payload_hash != after.payload_hash
    assert after.source_refs == ["ledger-2", "ledger-3", "ledger-4", "artifact-obs-1"]


def test_context_pack_compacts_retrieval_report_observation_content():
    journal, artifacts, task = _seed_context_inputs()
    huge_provider_diagnostics = {
        "provider_capabilities": [{"provider_id": f"provider-{index}", "diagnostics": {"long": "x" * 1000}} for index in range(50)],
        "evaluation_diagnostics": {
            "missing_finance_facets": ["revenue", "balance_sheet", "numeric_financial_fact"],
            "missing_query_facets": ["official source"],
            "source_authority": {"primary_source_count": 1, "source_families": ["structured_regulatory_data"]},
        },
        "rejected_evidence_reasons": {"target_entity_mismatch": 12},
        "fetch_attempt_count": 2,
        "search_attempt_count": 1,
        "reason": "insufficient_evidence",
    }
    journal.append(
        task_id=task.task_id,
        run_id=task.run_id,
        step_id="step-2",
        kind="observation",
        data={
            "observation_id": "obs-retrieval",
            "kind": "tool_result",
            "status": "ok",
            "source": "tool:retrieval.run",
            "content": {
                "report": {
                    "report_id": "report-1",
                    "goal_id": "goal-1",
                    "status": "insufficient_evidence",
                    "preview": "short preview",
                    "diagnostics": huge_provider_diagnostics,
                }
            },
        },
        observation_ref="obs-retrieval",
    )

    pack = ContextPackCompiler(
        artifact_store=artifacts,
        memory_read=MemoryRead(journal=journal, artifact_store=artifacts),
        token_budget=1000000,
        section_budget=200000,
    ).compile(task, journal, step_id="step-2")

    encoded = json.dumps(pack.to_dict(), ensure_ascii=False)
    recent = next(section for section in pack.sections if section["name"] == "recent_observations")
    report = recent["records"][-1]["content"]["report"]
    assert report["status"] == "insufficient_evidence"
    assert report["missing_finance_facets"] == ["revenue", "balance_sheet", "numeric_financial_fact"]
    assert "provider_capabilities" not in encoded
    assert "x" * 200 not in encoded


def test_context_pack_recent_observations_memory_refs_and_citations_use_same_window():
    journal = JournalStore.in_memory()
    task = SessionEngine.from_journal(journal).start("inspect sequence", thread_id="thread-a", journal=journal)
    journal.append(
        task_id=task.task_id,
        run_id=task.run_id,
        step_id=task.step_id,
        kind="event",
        data={"event_id": "evt-1", "payload": {"text": "inspect sequence"}},
        event_ref="evt-1",
    )
    artifacts = []
    for index in range(1, 6):
        observation_id = f"obs-{index}"
        artifact_id = f"artifact-{index}"
        journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=f"step-{index}",
            kind="observation",
            data={
                "observation_id": observation_id,
                "kind": "tool_result",
                "status": "ok",
                "source": "tool:file.read",
                "content": {"text": f"observation {index}"},
            },
            observation_ref=observation_id,
            artifact_refs=[artifact_id],
        )
        artifacts.append(
            ArtifactRef(
                artifact_id=artifact_id,
                kind="observation_payload",
                uri=f"journal://observations/{observation_id}",
                payload_hash=f"hash-{index}",
                metadata={"observation_id": observation_id},
            )
        )

    pack = ContextPackCompiler(
        artifact_store=ArtifactStore.in_memory(artifacts),
        memory_read=MemoryRead(journal=journal, artifact_store=ArtifactStore.in_memory(artifacts)),
        token_budget=1024,
        section_budget=256,
    ).compile(task, journal, step_id="step-5")

    recent = next(section for section in pack.sections if section["name"] == "recent_observations")
    memory_refs = next(section for section in pack.sections if section["name"] == "memory_refs")
    citations = next(section for section in pack.sections if section["name"] == "citations")

    assert [record["observation_id"] for record in recent["records"]] == ["obs-3", "obs-4", "obs-5"]
    assert [ref["observation_id"] for ref in memory_refs["refs"]] == ["obs-3", "obs-4", "obs-5"]
    assert [item["record_ref"] for item in citations["items"]] == ["ledger-5", "ledger-6", "ledger-7"]
    assert pack.source_refs == ["ledger-2", "ledger-5", "ledger-6", "ledger-7", "artifact-3", "artifact-4", "artifact-5"]


def _seed_context_inputs():
    journal = JournalStore.in_memory()
    task = SessionEngine.from_journal(journal).start("read README", thread_id="thread-a", journal=journal)
    journal.append(
        task_id=task.task_id,
        run_id=task.run_id,
        step_id="step-0",
        kind="event",
        data={"event_id": "evt-1", "payload": {"text": "read README"}},
        event_ref="evt-1",
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
            "content": {
                "path": "README.md",
                "text": "Kernel context from D:/Holo/holo/.holo_runtime/private.log",
            },
        },
        event_ref="evt-1",
        observation_ref="obs-1",
        artifact_refs=["artifact-obs-1"],
    )
    artifacts = ArtifactStore.in_memory(
        [
            ArtifactRef(
                artifact_id="artifact-obs-1",
                kind="observation_payload",
                uri="journal://observations/obs-1",
                payload_hash="hash-obs-1",
                metadata={"path": "README.md", "observation_id": "obs-1"},
            )
        ]
    )
    return journal, artifacts, task
