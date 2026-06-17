from __future__ import annotations

from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import CandidateAction, Observation, PolicyDecision, ToolManifest
from kernel_v3.policy import PolicyGate
from kernel_v3.tool_result_budget import (
    ToolResultReplacementState,
    apply_provider_message_replacement_view,
    apply_tool_result_replacement_budget,
)
from kernel_v3.tool_use import (
    ARTIFACT_READ_NAME,
    TOOL_DISCOVERY_NAME,
    ToolAbortSignal,
    ToolExecutionEvent,
    emit_tool_progress,
    project_tool_result_content,
    register_artifact_tools,
    register_tool_discovery,
    tool_abort_requested,
    tool_execution_control,
    tool_use_context_for_action,
)
from kernel_v3.tools import ToolRegistry


def test_tool_discovery_returns_allowed_manifest_contracts() -> None:
    registry = ToolRegistry.with_builtin_respond()
    registry.register(
        "sec.edgar.financials",
        _noop_tool,
        manifest=ToolManifest(
            name="sec.edgar.financials",
            version="1",
            resource_kind="finance",
            operator_kind="sec_edgar",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description="Retrieve SEC EDGAR filing facts and source lines.",
            input_schema={"ticker": {"type": "str", "required": True}},
            runtime={"concurrency_safe": True, "read_only": True, "open_world": True, "max_result_size_chars": 12000},
        ),
    )
    registry.register("math.sympy.compute", _noop_tool)
    register_tool_discovery(
        registry,
        allowed_tool_names={TOOL_DISCOVERY_NAME, "sec.edgar.financials"},
    )

    action = CandidateAction(
        action_id="act-discover",
        kind="tool",
        name=TOOL_DISCOVERY_NAME,
        description="find SEC tools",
        score=1.0,
        payload={"query": "sec financials"},
        reasons=["need_tool_schema"],
        side_effect_class="read",
    )
    manifest = registry.manifest_for_action(action)
    decision = PolicyGate(permission="read_write").validate(run_id="run-1", action=action, manifest=manifest)
    result = registry.execute_with_artifacts(
        action,
        policy_decision=decision,
        execution_context={"task_id": "task-1", "run_id": "run-1"},
    ).observation

    assert result.status == "ok"
    tools = result.content["tools"]
    assert [tool["name"] for tool in tools] == ["sec.edgar.financials"]
    assert result.content["schema"] == "holo.kernel_v3.tool_discovery.v1"
    assert tools[0]["runtime"]["concurrency_safe"] is True
    assert tools[0]["runtime"]["open_world"] is True
    assert tools[0]["runtime"]["max_result_size_chars"] == 12000


def test_tool_use_context_exposes_runtime_spec_to_executors() -> None:
    action = CandidateAction(
        action_id="act-runtime",
        kind="tool",
        name="finance.table.query",
        description="query table",
        score=1.0,
        payload={"sql": "select 1"},
        reasons=["need_table"],
        side_effect_class="read",
    )
    manifest = ToolManifest(
        name="finance.table.query",
        version="1",
        resource_kind="finance",
        operator_kind="table_query",
        side_effect_class="read",
        permissions_required=[],
        enabled=True,
        description="Query a finance evidence table.",
        input_schema={"sql": {"type": "str", "required": True}},
        runtime={"concurrency_safe": True, "read_only": True, "interrupt_behavior": "cancel"},
    )
    context = tool_use_context_for_action(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        thread_id="local:default",
        input_text="query",
        tool_call_id="tc-1",
        action=action,
        manifest=manifest,
        policy_decision=PolicyDecision(
            decision_id="pd-1",
            run_id="run-1",
            action_id="act-runtime",
            allowed=True,
            reason="allowed",
            constraints={"tool_name": "finance.table.query", "side_effect_class": "read"},
        ),
        allowed_tool_names=["finance.table.query"],
        progress_channel_id="progress-1",
        abort_signal_id="abort-1",
        timeout_seconds=7,
    ).to_execution_context()

    assert context["runtime_spec"]["concurrency_safe"] is True
    assert context["runtime_spec"]["interrupt_behavior"] == "cancel"
    assert context["runtime_spec"]["read_only"] is True
    assert context["progress_channel_id"] == "progress-1"
    assert context["abort_signal_id"] == "abort-1"
    assert context["timeout_seconds"] == 7


def test_tool_progress_helpers_emit_progress_and_read_abort_signal() -> None:
    events: list[ToolExecutionEvent] = []
    abort_signal = ToolAbortSignal(signal_id="abort-progress")
    payload = {
        "_host_context": {
            "schema": "holo.kernel_v3.tool_use_context.v1",
            "progress_channel_id": "progress-channel",
            "abort_signal_id": "abort-progress",
            "tool_call_id": "tc-progress",
            "action_id": "act-progress",
            "tool_name": "alpha.read",
        }
    }

    with tool_execution_control(
        progress_channel_id="progress-channel",
        abort_signal=abort_signal,
        emit_event=events.append,
    ):
        assert emit_tool_progress(payload, status="running", detail={"stage": "fetch"}) is True
        assert tool_abort_requested(payload) is False
        abort_signal.request("user_interrupt")
        assert tool_abort_requested(payload) is True

    assert events[0].event_type == "progress"
    assert events[0].tool_call_id == "tc-progress"
    assert events[0].detail == {"stage": "fetch"}


def test_tool_result_projection_preserves_shape_and_budget_state() -> None:
    projection = project_tool_result_content(
        {
            "source": "sec",
            "rows": [{"line_item": "Revenue", "value": "x" * 500}],
        },
        limit=120,
    ).to_dict()

    assert projection["truncated"] is True
    assert projection["estimated_chars"] > projection["preview_chars"]
    assert projection["shape"]["type"] == "object"
    assert "rows" in projection["shape"]["keys"]


def test_tool_result_replacement_state_reapplies_byte_stable_replacements() -> None:
    state = ToolResultReplacementState()
    large = {
        "tool_call_id": "tc-large",
        "content_preview": "x" * 5000,
        "content_projection": {"estimated_chars": 100000, "preview": "x" * 100, "truncated": True, "shape": {"type": "object"}},
        "artifact_refs": ["artifact-large"],
    }
    small = {
        "tool_call_id": "tc-small",
        "content_preview": "ok",
        "content_projection": {"estimated_chars": 2, "preview": "ok", "truncated": False, "shape": {"type": "str"}},
        "artifact_refs": [],
    }

    first, records = apply_tool_result_replacement_budget([large, small], state, limit_chars=1000)
    assert len(records) == 1
    assert first[0]["content_replacement_applied"] is True
    replacement = first[0]["content_replacement"]
    assert replacement["artifact_refs"] == ["artifact-large"]

    second, second_records = apply_tool_result_replacement_budget(
        [{**large, "content_preview": "changed", "content_projection": {"estimated_chars": 1}}],
        state,
        limit_chars=1_000_000,
    )
    assert second_records == []
    assert second[0]["content_replacement"] == replacement


def test_provider_message_replacement_view_sanitizes_replaced_tool_results() -> None:
    payload = {
        "context": {
            "recent_observations": {
                "records": [
                    {
                        "content": {
                            "results": [
                                    {
                                        "tool_call_id": "tc-large",
                                        "content": "RAW-CONTENT-" + "z" * 5000,
                                        "raw_content": "RAW-RAW-" + "r" * 5000,
                                        "content_preview": "RAW-" + "x" * 5000,
                                        "content_projection": {
                                            "preview": "PROJECTED-" + "y" * 5000,
                                        "estimated_chars": 100000,
                                    },
                                    "content_replacement": {
                                        "schema": "holo.kernel_v3.tool_result_replacement.v1",
                                        "tool_call_id": "tc-large",
                                        "replacement_preview": "bounded replacement",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        }
    }

    sanitized = apply_provider_message_replacement_view(payload)
    result = sanitized["context"]["recent_observations"]["records"][0]["content"]["results"][0]

    assert result["content_preview"] == "bounded replacement"
    assert result["content_projection"]["preview"] == "bounded replacement"
    assert result["content"]["omitted"] is True
    assert result["raw_content"]["omitted"] is True
    assert "RAW-CONTENT" not in str(sanitized)
    assert "RAW-RAW" not in str(sanitized)
    assert result["content_replacement_applied"] is True
    assert result["provider_message_replacement_applied"] is True


def test_artifact_read_returns_bounded_preview_and_text() -> None:
    artifact_store = ArtifactStore.in_memory()
    artifact = artifact_store.write_blob(
        kind="sec_table",
        payload="Revenue table body " + "x" * 100,
        metadata={"source": "sec"},
    )
    registry = ToolRegistry.with_builtin_respond()
    register_artifact_tools(registry, artifact_store=artifact_store)

    preview = _execute_with_policy(
        registry,
        CandidateAction(
            action_id="act-artifact-preview",
            kind="tool",
            name=ARTIFACT_READ_NAME,
            description="preview artifact",
            score=1.0,
            payload={"artifact_id": artifact.artifact_id, "mode": "preview", "max_chars": 12},
            reasons=["need_preview"],
            side_effect_class="read",
        ),
    )
    read = _execute_with_policy(
        registry,
        CandidateAction(
            action_id="act-artifact-read",
            kind="tool",
            name=ARTIFACT_READ_NAME,
            description="read artifact",
            score=1.0,
            payload={"artifact_id": artifact.artifact_id, "mode": "read", "max_chars": 24},
            reasons=["need_body"],
            side_effect_class="read",
        ),
    )

    assert preview.status == "ok"
    assert preview.content["mode"] == "preview"
    assert preview.content["blob_available"] is True
    assert read.status == "ok"
    assert read.content["mode"] == "read"
    assert read.content["truncated"] is True
    assert len(read.content["text"]) <= 24
    assert artifact_store.audit_records()[0]["artifact_id"] == artifact.artifact_id


def _execute_with_policy(registry: ToolRegistry, action: CandidateAction) -> Observation:
    manifest = registry.manifest_for_action(action)
    decision = PolicyGate(permission="read_write").validate(run_id="run-1", action=action, manifest=manifest)
    return registry.execute_with_artifacts(
        action,
        policy_decision=decision,
        execution_context={"task_id": "task-1", "run_id": "run-1"},
    ).observation


def _noop_tool(action: CandidateAction) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="tool_result",
        status="ok",
        source=f"tool:{action.name}",
        content={},
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )
