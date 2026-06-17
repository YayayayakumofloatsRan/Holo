from __future__ import annotations

from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import CandidateAction, Observation
from kernel_v3.policy import PolicyGate
from kernel_v3.tool_use import (
    ARTIFACT_READ_NAME,
    TOOL_DISCOVERY_NAME,
    project_tool_result_content,
    register_artifact_tools,
    register_tool_discovery,
)
from kernel_v3.tools import ToolRegistry


def test_tool_discovery_returns_allowed_manifest_contracts() -> None:
    registry = ToolRegistry.with_builtin_respond()
    registry.register("sec.edgar.financials", _noop_tool)
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
