import json
import subprocess
import sys
from pathlib import Path

from kernel_v3.context import ArtifactStore, ContextCompiler, ContextPackCompiler
from kernel_v3.context.budgeter import measure_units
from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, Observation, ToolManifest
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.session import SessionEngine
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry
from kernel_v3.trace import TraceRenderer


class RecordingEvaluator:
    def __init__(self, feedbacks: list[dict[str, object]]) -> None:
        self.feedbacks = list(feedbacks)
        self.contexts: list[ContextBundle] = []
        self.observations: list[Observation] = []

    def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
        self.contexts.append(context)
        self.observations.append(observation)
        if not self.feedbacks:
            raise AssertionError("RecordingEvaluator has no more feedback")
        data = self.feedbacks.pop(0)
        return Feedback(
            feedback_id=f"fb-{len(self.contexts)}",
            run_id=str(context.state["run_id"]),
            status=str(data["status"]),
            stop_reason=data.get("stop_reason") if isinstance(data.get("stop_reason"), str) else None,
            answer=data.get("answer") if isinstance(data.get("answer"), str) else None,
            missing_evidence=list(data.get("missing_evidence", [])),
        )


class StepClock:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def __call__(self) -> int:
        if not self.values:
            raise AssertionError("StepClock exhausted")
        return self.values.pop(0)


def test_context_bundle_state_carries_full_context_pack_sections_to_planner_and_evaluator():
    planner = FakePlanner.respond_once("I can operate through the kernel.")
    evaluator = RecordingEvaluator(
        [
            {
                "status": "final_answer_ready",
                "stop_reason": "completed",
                "answer": "I can operate through the kernel.",
                "missing_evidence": [],
            }
        ]
    )
    loop = LoopControllerV3(
        journal=JournalStore.in_memory(),
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=evaluator,
    )

    result = loop.run("what can you do?")

    assert result.status == "completed"
    planner_state = planner.calls[0].state
    evaluator_state = evaluator.contexts[0].state
    section_names = [section["name"] for section in planner_state["sections"]]
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
    assert planner_state["source_refs"] == ["ledger-1"]
    assert planner_state["redactions"] == []
    assert planner_state["budget"]["within_budget"] is True
    assert [section["name"] for section in evaluator_state["sections"]] == section_names
    evaluator_observations = next(
        section["records"]
        for section in evaluator_state["sections"]
        if section["name"] == "recent_observations"
    )
    assert evaluator_observations[0]["content"]["text"] == "I can operate through the kernel."
    assert evaluator_state["context_pack_hash"] != planner_state["context_pack_hash"]


def test_policy_blocks_disabled_network_fetch_even_with_network_permission():
    root = Path("kernel_v3/.test-phase31-network")
    _reset_dir(root)
    action = CandidateAction(
        action_id="act-network",
        kind="tool",
        name="network.fetch",
        description="fetch remote page",
        score=1.0,
        payload={"url": "https://example.invalid/"},
        reasons=["phase4 will add live fetch later"],
        side_effect_class="network",
    )
    try:
        registry = ToolRegistry.with_permissioned_workspace(root=root)
        journal = JournalStore.in_memory()
        loop = LoopControllerV3(
            journal=journal,
            context_compiler=ContextCompiler(),
            planner=FakePlanner([action]),
            policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
            tool_registry=registry,
            evaluator=FakeEvaluator.stop_on_block(),
        )

        result = loop.run("fetch example")

        policy = journal.records(task_id=result.task_id, kind="policy_decision")[0]
        observation = journal.records(task_id=result.task_id, kind="observation")[0]
        assert result.status == "blocked"
        assert policy.data["allowed"] is False
        assert policy.data["reason"] == "tool_disabled"
        assert observation.data["status"] == "blocked"
        assert observation.data["content"]["reason"] == "tool_disabled"
        assert registry.executed_actions == []
    finally:
        _remove_dir(root)


def test_loop_redacts_secret_like_input_and_action_payload_before_journal_and_context():
    secret_url = "https://example.invalid/report?access_token=loop-secret-token-1234567890"
    action = CandidateAction(
        action_id="act-secret-network",
        kind="tool",
        name="network.fetch",
        description="fetch remote page",
        score=1.0,
        payload={"url": secret_url},
        reasons=["test secret redaction"],
        side_effect_class="network",
    )
    journal = JournalStore.in_memory()
    planner = FakePlanner([action])
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator.stop_on_block(),
    )

    result = loop.run(f"fetch {secret_url}")

    assert result.status == "blocked"
    planner_state = planner.calls[0].state
    assert planner_state["input_text"] == "[REDACTED:SECRET]"
    assert "SECRET" in planner_state["redactions"]
    event = journal.records(task_id=result.task_id, kind="event")[0]
    task = journal.records(task_id=result.task_id, kind="task")[0]
    action_record = journal.records(task_id=result.task_id, kind="action")[0]
    assert event.data["payload"]["text"] == "[REDACTED:SECRET]"
    assert task.data["input_text"] == "[REDACTED:SECRET]"
    assert action_record.data["payload"]["url"] == "[REDACTED:SECRET]"
    assert action_record.data["redaction"]["journal_data"] == "secret_like_fields_redacted"
    encoded = json.dumps([record.to_dict() for record in journal.records(task_id=result.task_id)], ensure_ascii=False)
    assert "loop-secret-token" not in encoded
    assert "access_token" not in encoded


def test_loop_max_steps_guard_journals_auditable_stop_after_continue_feedback():
    actions = [
        CandidateAction(
            action_id="act-1",
            kind="respond",
            name=None,
            description="first response",
            score=1.0,
            payload={"text": "first"},
            reasons=[],
            side_effect_class="none",
        ),
        CandidateAction(
            action_id="act-2",
            kind="respond",
            name=None,
            description="second response",
            score=1.0,
            payload={"text": "second"},
            reasons=[],
            side_effect_class="none",
        ),
    ]
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner(actions),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator(
            [
                {"status": "continue", "stop_reason": None, "answer": None, "missing_evidence": ["more"]},
                {"status": "final_answer_ready", "stop_reason": "completed", "answer": "second", "missing_evidence": []},
            ]
        ),
        max_steps=1,
    )

    result = loop.run("continue forever")

    assert result.status == "step_limit_exceeded"
    assert result.stop_reason == "max_steps"
    assert [record.data["action_id"] for record in journal.records(task_id=result.task_id, kind="action")] == ["act-1"]
    assert [record.data["status"] for record in journal.records(task_id=result.task_id, kind="feedback")] == [
        "continue",
        "step_limit_exceeded",
    ]
    guard = journal.records(task_id=result.task_id, kind="guard")[0]
    assert guard.state_delta == {"status": "step_limit_exceeded", "stop_reason": "max_steps"}


def test_loop_max_steps_allows_terminal_feedback_at_limit():
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner.respond_once("done"),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator.final_answer("done"),
        max_steps=1,
    )

    result = loop.run("finish in one step")

    assert result.status == "completed"
    assert result.stop_reason == "completed"
    assert journal.records(task_id=result.task_id, kind="guard") == []


def test_loop_max_tool_calls_guard_stops_before_next_tool_executes():
    first = CandidateAction(
        action_id="act-search-1",
        kind="tool",
        name="workspace.search",
        description="first search",
        score=1.0,
        payload={"query": "Holo"},
        reasons=[],
        side_effect_class="read",
    )
    second = CandidateAction(
        action_id="act-search-2",
        kind="tool",
        name="workspace.search",
        description="second search",
        score=1.0,
        payload={"query": "Kernel"},
        reasons=[],
        side_effect_class="read",
    )
    registry = ToolRegistry.with_fake_workspace_tools(files={"README.md": "Holo Kernel"})
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([first, second]),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator(
            [
                {"status": "continue", "stop_reason": None, "answer": None, "missing_evidence": ["more"]},
                {"status": "final_answer_ready", "stop_reason": "completed", "answer": "second", "missing_evidence": []},
            ]
        ),
        max_tool_calls=1,
    )

    result = loop.run("search twice")

    observations = journal.records(task_id=result.task_id, kind="observation")
    assert result.status == "step_limit_exceeded"
    assert result.stop_reason == "max_tool_calls"
    assert registry.executed_actions == [first]
    assert [record.data["status"] for record in observations] == ["ok", "blocked"]
    assert observations[-1].data["content"]["reason"] == "max_tool_calls"


def test_loop_max_duration_guard_uses_injected_clock_for_deterministic_stop():
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner.respond_once("still working"),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator(
            [{"status": "continue", "stop_reason": None, "answer": None, "missing_evidence": ["time"]}]
        ),
        max_duration_ms=10,
        clock_ms=StepClock([100, 111]),
    )

    result = loop.run("duration guard")

    assert result.status == "step_limit_exceeded"
    assert result.stop_reason == "max_duration_ms"
    assert journal.records(task_id=result.task_id, kind="guard")[0].data["elapsed_ms"] == 11


def test_loop_max_network_fetches_guard_stops_network_action_before_execution():
    action = CandidateAction(
        action_id="act-network",
        kind="tool",
        name="network.fetch",
        description="network fetch",
        score=1.0,
        payload={"url": "https://example.invalid/"},
        reasons=[],
        side_effect_class="network",
    )
    registry = ToolRegistry()
    registry.register(
        "network.fetch",
        lambda candidate: Observation(
            observation_id=f"obs-{candidate.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source="tool:network.fetch",
            content={"url": candidate.payload["url"]},
            observed_at_ms=0,
            action_id=candidate.action_id,
            tool_call_id=None,
        ),
    )
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator(
            [{"status": "continue", "stop_reason": None, "answer": None, "missing_evidence": ["network"]}]
        ),
        max_network_fetches=0,
    )

    result = loop.run("fetch")

    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    assert result.status == "step_limit_exceeded"
    assert result.stop_reason == "max_network_fetches"
    assert registry.executed_actions == []
    assert observation.data["status"] == "blocked"
    assert observation.data["content"]["reason"] == "max_network_fetches"


def test_loop_max_network_fetches_guard_blocks_projected_budget_overrun_before_execution():
    action = CandidateAction(
        action_id="act-network-overrun",
        kind="tool",
        name="network.expensive",
        description="network action whose declared cost exceeds remaining budget",
        score=1.0,
        payload={"max_fetches": 2},
        reasons=[],
        side_effect_class="network",
    )
    registry = ToolRegistry()
    registry.register(
        "network.expensive",
        lambda candidate: Observation(
            observation_id=f"obs-{candidate.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source="tool:network.expensive",
            content={"max_fetches": candidate.payload["max_fetches"]},
            observed_at_ms=0,
            action_id=candidate.action_id,
            tool_call_id=None,
        ),
        manifest=ToolManifest(
            name="network.expensive",
            version="1",
            resource_kind="network",
            operator_kind="expensive",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description="network.expensive",
            input_schema={
                "max_fetches": {"type": "int", "required": True, "min": 1, "max": 10},
                "network_fetch_cost_field": "max_fetches",
                "default_network_fetch_cost": 1,
            },
        ),
    )
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
        tool_registry=registry,
        evaluator=FakeEvaluator(
            [{"status": "continue", "stop_reason": None, "answer": None, "missing_evidence": ["network"]}]
        ),
        max_network_fetches=1,
    )

    result = loop.run("fetch too much")

    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    guard = journal.records(task_id=result.task_id, kind="guard")[0]
    assert result.status == "step_limit_exceeded"
    assert result.stop_reason == "max_network_fetches"
    assert registry.executed_actions == []
    assert observation.data["status"] == "blocked"
    assert observation.data["content"]["reason"] == "max_network_fetches"
    assert guard.data["requested_network_fetches"] == 2
    assert guard.data["projected_network_fetches"] == 2
    assert guard.data["max_network_fetches"] == 1


def test_loop_max_total_artifact_bytes_guard_stops_after_oversized_artifact_is_recorded():
    action = CandidateAction(
        action_id="act-read",
        kind="tool",
        name="file.read",
        description="read large file",
        score=1.0,
        payload={"path": "large.txt"},
        reasons=[],
        side_effect_class="read",
    )
    registry = ToolRegistry.with_fake_workspace_tools(files={"large.txt": "x" * 128})
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator(
            [{"status": "continue", "stop_reason": None, "answer": None, "missing_evidence": ["smaller artifact"]}]
        ),
        max_total_artifact_bytes=16,
    )

    result = loop.run("read large")

    observations = journal.records(task_id=result.task_id, kind="observation")
    guard = journal.records(task_id=result.task_id, kind="guard")[0]
    assert result.status == "step_limit_exceeded"
    assert result.stop_reason == "max_total_artifact_bytes"
    assert observations[0].artifact_refs
    assert guard.data["artifact_bytes"] > 16


def test_loop_artifact_byte_guard_overrides_terminal_feedback_for_resource_safety():
    action = CandidateAction(
        action_id="act-read",
        kind="tool",
        name="file.read",
        description="read large file",
        score=1.0,
        payload={"path": "large.txt"},
        reasons=[],
        side_effect_class="read",
    )
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_fake_workspace_tools(files={"large.txt": "x" * 128}),
        evaluator=FakeEvaluator.final_answer("large file read"),
        max_total_artifact_bytes=16,
    )

    result = loop.run("read large")

    assert result.status == "step_limit_exceeded"
    assert result.stop_reason == "max_total_artifact_bytes"
    assert [record.data["status"] for record in journal.records(task_id=result.task_id, kind="feedback")] == [
        "final_answer_ready",
        "step_limit_exceeded",
    ]


def test_artifact_store_writes_reads_previews_and_reloads_blob_payload():
    root = Path("kernel_v3/.test-phase31-artifacts")
    _reset_dir(root)
    store_path = root / "artifacts.jsonl"
    try:
        store = ArtifactStore(store_path)

        ref = store.write_blob(
            kind="search_results",
            payload="alpha beta gamma delta",
            mime_type="text/plain",
            metadata={"query": "alpha"},
        )

        assert ref.kind == "search_results"
        assert ref.uri == f"artifact-blob://{ref.artifact_id}"
        assert ref.metadata["mime_type"] == "text/plain"
        assert ref.metadata["size_bytes"] == len("alpha beta gamma delta".encode("utf-8"))
        assert store.read_blob(ref.artifact_id) == "alpha beta gamma delta"
        assert store.preview(ref.artifact_id, limit=10) == {
            "artifact_id": ref.artifact_id,
            "kind": "search_results",
            "mime_type": "text/plain",
            "size_bytes": len("alpha beta gamma delta".encode("utf-8")),
            "preview": "alpha beta...",
            "redaction_status": "unredacted",
        }

        reloaded = ArtifactStore(store_path)
        assert reloaded.get(ref.artifact_id) == ref
        assert reloaded.read_blob(ref.artifact_id) == "alpha beta gamma delta"
    finally:
        _remove_dir(root)


def test_artifact_store_can_audit_blob_reads_without_raw_payload_leakage():
    root = Path("kernel_v3/.test-phase31-artifacts")
    _reset_dir(root)
    store_path = root / "artifacts.jsonl"
    raw_only_sentinel = "ARTIFACT_RAW_ONLY_SECRET"
    try:
        store = ArtifactStore(store_path, clock_ms=lambda: 1234)
        ref = store.write_blob(
            kind="retrieval_fetched_document",
            payload=f"raw page body {raw_only_sentinel}",
            mime_type="text/plain",
            metadata={"uri": "https://example.test/doc"},
        )

        assert store.read_blob(
            ref.artifact_id,
            record_access=True,
            access_context={
                "surface": "test",
                "provider_id": "fake",
                "raw_body": raw_only_sentinel,
                "operator_note": raw_only_sentinel,
            },
        ).endswith(raw_only_sentinel)

        audit = store.audit_records()
        assert audit[-1]["event_type"] == "artifact_blob_read"
        assert audit[-1]["artifact_id"] == ref.artifact_id
        assert audit[-1]["payload_hash"] == ref.payload_hash
        assert audit[-1]["payload_size_bytes"] == len(f"raw page body {raw_only_sentinel}".encode("utf-8"))
        assert audit[-1]["redaction"]["blob"] == "not_embedded"
        assert audit[-1]["access_context"]["raw_body"] == "[omitted]"
        assert audit[-1]["access_context"]["operator_note"]["redacted"] is True

        encoded_audit = json.dumps(audit, ensure_ascii=False)
        assert raw_only_sentinel not in encoded_audit

        reloaded = ArtifactStore(store_path)
        encoded_reloaded_audit = json.dumps(reloaded.audit_records(), ensure_ascii=False)
        assert raw_only_sentinel not in encoded_reloaded_audit
        assert reloaded.audit_records()[-1]["artifact_id"] == ref.artifact_id
    finally:
        _remove_dir(root)


def test_context_compiler_truncates_oversized_sections_when_budget_mode_is_truncate():
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

    pack = ContextPackCompiler(token_budget=768, section_budget=80, budget_mode="truncate").compile(
        task,
        journal,
        step_id="step-1",
    )

    recent = next(section for section in pack.sections if section["name"] == "recent_observations")
    encoded = json.dumps(recent, ensure_ascii=False)
    assert pack.budget["within_budget"] is True
    assert pack.budget["compaction"] == {
        "mode": "truncate",
        "applied": True,
        "sections": ["recent_observations"],
    }
    assert "x" * 400 not in encoded
    assert "..." in encoded


def test_context_compiler_truncation_budget_units_match_materialized_sections():
    journal = JournalStore.in_memory()
    task = SessionEngine.from_journal(journal).start("many observations", thread_id="thread-a", journal=journal)
    for index in range(8):
        journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=f"step-{index}",
            kind="observation",
            data={
                "observation_id": f"obs-{index}",
                "content": {
                    "text": "long observation payload " * 60,
                    "detail": "secondary field " * 60,
                },
            },
            observation_ref=f"obs-{index}",
        )

    pack = ContextPackCompiler(token_budget=512, section_budget=96, budget_mode="truncate").compile(
        task,
        journal,
        step_id="step-8",
    )

    actual_units = [measure_units({key: value for key, value in section.items() if key != "name"}) for section in pack.sections]
    assert pack.budget["section_units"] == actual_units
    assert all(units <= 96 for units in actual_units)
    assert sum(actual_units) == pack.budget["total_units"]


def test_trace_renderer_verbose_evidence_artifacts_and_retrieval_views():
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="action",
        data={"action_id": "act-search", "kind": "tool", "name": "workspace.search", "payload": {"query": "Holo"}},
        action_ref="act-search",
        state_delta={"action_kind": "tool"},
    )
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="policy_decision",
        data={"allowed": True, "reason": "allowed"},
        action_ref="act-search",
        state_delta={"policy_allowed": True},
    )
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="observation",
        data={
            "observation_id": "obs-search",
            "kind": "tool_result",
            "status": "ok",
            "source": "tool:workspace.search",
            "content": {"matches": [{"path": "README.md", "text": "Holo is host-owned"}]},
        },
        action_ref="act-search",
        observation_ref="obs-search",
        state_delta={"observation_status": "ok"},
        artifact_refs=["artifact-obs-search"],
    )
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="feedback",
        data={"status": "continue", "missing_evidence": ["need file.read"], "stop_reason": None},
        action_ref="act-search",
        observation_ref="obs-search",
        feedback_ref="fb-1",
        state_delta={"feedback_status": "continue"},
    )

    renderer = TraceRenderer(journal)
    verbose = renderer.render_task("task-1", verbose=True)
    evidence = renderer.render_evidence("task-1")
    artifacts = renderer.render_artifacts("task-1")
    retrieval = renderer.render_retrieval_trace("task-1")

    assert "policy allowed=True reason=allowed" in verbose
    assert "observation status=ok source=tool:workspace.search" in verbose
    assert "feedback status=continue missing_evidence=['need file.read']" in verbose
    assert "Evidence task-1" in evidence
    assert "obs-search tool_result ok tool:workspace.search" in evidence
    assert "artifact-obs-search" in artifacts
    assert "Retrieval Trace task-1" in retrieval
    assert "query=Holo" in retrieval
    assert "why_continue=need file.read" in retrieval


def test_trace_renderer_redacts_secret_like_dynamic_fields():
    journal = JournalStore.in_memory()
    secret_url = "https://example.test/report?access_token=trace-secret-token-1234567890"
    secret_text = "api_key=trace-secret-key-1234567890"
    journal.append(
        task_id="task-secret-trace",
        run_id="run-1",
        step_id="step-1",
        kind="action",
        data={
            "action_id": "act-secret-url",
            "kind": "tool",
            "name": "network.fetch",
            "payload": {"url": secret_url},
        },
        action_ref="act-secret-url",
        state_delta={"url": secret_url},
    )
    journal.append(
        task_id="task-secret-trace",
        run_id="run-1",
        step_id="step-1",
        kind="feedback",
        data={"status": "continue", "missing_evidence": [secret_url], "stop_reason": secret_text},
        feedback_ref="fb-secret",
    )
    journal.append(
        task_id="task-secret-trace",
        run_id="run-1",
        step_id="retrieval-search",
        kind="retrieval_search_attempt",
        data={
            "attempt_id": "search-secret",
            "status": "ok",
            "query": secret_text,
            "sources": [],
        },
    )
    journal.append(
        task_id="task-secret-trace",
        run_id="run-1",
        step_id="retrieval-fetch",
        kind="retrieval_fetch_attempt",
        data={
            "fetch_id": "fetch-secret",
            "status": "failed",
            "uri": secret_url,
            "artifact_id": None,
            "payload_hash": None,
            "size_bytes": 0,
            "preview": secret_text,
        },
    )
    journal.append(
        task_id="task-secret-trace",
        run_id="run-1",
        step_id="retrieval-evidence",
        kind="retrieval_evidence",
        data={
            "evidence_id": "ev-secret",
            "source_id": "src",
            "artifact_id": "artifact-secret",
            "score": 1,
            "text": secret_text,
        },
    )
    journal.append(
        task_id="task-secret-trace",
        run_id="run-1",
        step_id="retrieval-citation",
        kind="retrieval_citation",
        data={
            "citation_id": "cite-secret",
            "evidence_id": "ev-secret",
            "artifact_id": "artifact-secret",
            "quote": secret_text,
        },
    )

    renderer = TraceRenderer(journal)
    trace = renderer.render_task("task-secret-trace", verbose=True)
    retrieval = renderer.render_retrieval_trace("task-secret-trace")
    dumped = trace + "\n" + retrieval

    assert "trace-secret-token" not in dumped
    assert "trace-secret-key" not in dumped
    assert "access_token" not in dumped
    assert "api_key" not in dumped
    assert "[REDACTED:SECRET]" in dumped


def test_holo_v3_trace_cli_exposes_verbose_evidence_artifact_and_retrieval_views():
    journal_path = Path("kernel_v3/.test-phase31-cli-journal.jsonl")
    index_path = Path("kernel_v3/.test-phase31-cli-journal.sqlite")
    for path in [journal_path, index_path]:
        if path.exists():
            path.unlink()
    try:
        run = _run_cli("--journal", str(journal_path), "--index", str(index_path), "run", "phase31")
        task_id = json.loads(run.stdout)["task_id"]

        verbose = _run_cli("--journal", str(journal_path), "--index", str(index_path), "trace", task_id, "--verbose")
        evidence = _run_cli("--journal", str(journal_path), "--index", str(index_path), "evidence", task_id)
        artifacts = _run_cli("--journal", str(journal_path), "--index", str(index_path), "artifacts", task_id)
        retrieval = _run_cli("--journal", str(journal_path), "--index", str(index_path), "retrieval-trace", task_id)

        assert "policy allowed=True reason=allowed" in verbose.stdout
        assert f"Evidence {task_id}" in evidence.stdout
        assert "obs-act-respond respond_result ok respond" in evidence.stdout
        assert "artifact-obs-act-respond" in artifacts.stdout
        assert f"Retrieval Trace {task_id}" in retrieval.stdout
        assert "why_stop=completed" in retrieval.stdout
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


def _reset_dir(path: Path) -> None:
    _remove_dir(path)
    path.mkdir(parents=True)


def _remove_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()
