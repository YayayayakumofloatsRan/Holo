from __future__ import annotations

import json
import threading
import time

from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import CandidateAction, Observation, PolicyDecision, ToolManifest
from kernel_v3.policy import PolicyGate
from kernel_v3.tool_result_budget import (
    ToolResultReplacementState,
    apply_provider_message_replacement_view,
    apply_tool_result_replacement_budget,
)
from kernel_v3.tool_use import (
    ARTIFACT_QUERY_NAME,
    ARTIFACT_READ_NAME,
    TOOL_DISCOVERY_NAME,
    StreamingToolExecutor,
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


def test_tool_discovery_select_query_loads_exact_tools_and_reports_missing() -> None:
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
            runtime={"concurrency_safe": True, "read_only": True, "should_defer": True},
        ),
    )
    register_tool_discovery(
        registry,
        allowed_tool_names={TOOL_DISCOVERY_NAME, "sec.edgar.financials"},
    )

    action = CandidateAction(
        action_id="act-select-discover",
        kind="tool",
        name=TOOL_DISCOVERY_NAME,
        description="select SEC tool",
        score=1.0,
        payload={"query": "select:sec.edgar.financials,missing.tool"},
        reasons=["need_exact_tool_schema"],
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
    assert result.content["query_mode"] == "select"
    assert result.content["requested_tool_names"] == ["sec.edgar.financials", "missing.tool"]
    assert result.content["matched_tool_names"] == ["sec.edgar.financials"]
    assert result.content["missing_tool_names"] == ["missing.tool"]
    assert result.content["tools"][0]["input_schema"]["ticker"]["required"] is True


def test_invalid_tool_payload_points_model_to_tool_discovery_recovery() -> None:
    registry = ToolRegistry.with_builtin_respond()
    registry.register(
        "finance.metric.fetch",
        _noop_tool,
        manifest=ToolManifest(
            name="finance.metric.fetch",
            version="1",
            resource_kind="finance",
            operator_kind="fetch",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Fetch a typed finance metric.",
            input_schema={"ticker": {"type": "str", "required": True, "min_length": 1}},
            runtime={"should_defer": True, "read_only": True},
        ),
    )

    observation = _execute_with_policy(
        registry,
        CandidateAction(
            action_id="act-invalid-payload",
            kind="tool",
            name="finance.metric.fetch",
            description="fetch without required ticker",
            score=1.0,
            payload={},
            reasons=["need_metric"],
            side_effect_class="read",
        ),
    )

    assert observation.status == "blocked"
    assert observation.content["reason"] == "invalid_tool_payload"
    assert observation.content["schema_available_via"] == TOOL_DISCOVERY_NAME
    assert "select:finance.metric.fetch" in observation.content["recovery_hint"]


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
    assert context["runtime_spec"]["failure_cancels_siblings"] is False
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


def test_streaming_tool_executor_bounds_concurrent_safe_batch() -> None:
    executor = StreamingToolExecutor(max_concurrency=2)
    active = 0
    peak = 0
    lock = threading.Lock()

    def execute_one(item: int) -> dict[str, object]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"status": "ok", "item": item}

    outcomes = executor.execute_batches(
        list(range(6)),
        execute_one=execute_one,
        is_concurrency_safe=lambda _item: True,
        is_failed=lambda outcome: outcome["status"] != "ok",
    )

    assert len(outcomes) == 6
    assert peak <= 2


def test_streaming_tool_executor_incremental_mode_gates_exclusive_tools() -> None:
    executor = StreamingToolExecutor(max_concurrency=2)
    trace: list[str] = []

    def execute_one(item: str) -> dict[str, object]:
        trace.append(f"start:{item}")
        if item == "slow-safe":
            time.sleep(0.05)
        if item == "exclusive":
            time.sleep(0.01)
        trace.append(f"end:{item}")
        return {"status": "ok", "item": item}

    executor.begin_incremental(
        execute_one=execute_one,
        is_concurrency_safe=lambda item: item != "exclusive",
        is_failed=lambda outcome: outcome["status"] != "ok",
    )
    try:
        executor.add_item("slow-safe")
        executor.add_item("fast-safe")
        time.sleep(0.02)
        outcomes = executor.drain_completed()
        executor.add_item("exclusive")
        executor.add_item("after-safe")
        outcomes.extend(executor.finish_remaining())
    finally:
        executor.close()

    assert {outcome["item"] for outcome in outcomes} == {"slow-safe", "fast-safe", "exclusive", "after-safe"}
    assert trace.index("start:fast-safe") < trace.index("end:slow-safe")
    assert trace.index("end:slow-safe") < trace.index("start:exclusive")
    assert trace.index("end:exclusive") < trace.index("start:after-safe")


def test_streaming_tool_executor_failure_cancel_callback_can_keep_independent_reads() -> None:
    executor = StreamingToolExecutor(max_concurrency=1)
    calls: list[str] = []

    def execute_one(item: str) -> dict[str, object]:
        calls.append(item)
        return {"status": "failed" if item == "read-fail" else "ok", "item": item}

    outcomes = executor.execute_batches(
        ["read-fail", "after-read"],
        execute_one=execute_one,
        is_concurrency_safe=lambda _item: True,
        cancel_pending_on_failure=True,
        is_failed=lambda outcome: outcome["status"] != "ok",
        failure_cancels_siblings=lambda _item, _outcome: False,
        cancel_one=lambda item, reason: {"status": "cancelled", "item": item, "reason": reason},
    )

    assert calls == ["read-fail", "after-read"]
    assert [outcome["status"] for outcome in outcomes] == ["failed", "ok"]


def test_streaming_tool_executor_abort_callback_reaches_running_siblings() -> None:
    executor = StreamingToolExecutor(max_concurrency=2)
    slow_started = threading.Event()
    abort_requested = threading.Event()
    abort_calls: list[tuple[str, str]] = []

    def execute_one(item: str) -> dict[str, object]:
        if item == "slow":
            slow_started.set()
            while not abort_requested.wait(0.01):
                pass
            return {"status": "cancelled", "item": item}
        assert slow_started.wait(1)
        return {"status": "failed", "item": item}

    def abort_one(item: str, reason: str) -> None:
        abort_calls.append((item, reason))
        if item == "slow":
            abort_requested.set()

    outcomes = executor.execute_batches(
        ["slow", "fail"],
        execute_one=execute_one,
        is_concurrency_safe=lambda _item: True,
        cancel_pending_on_failure=True,
        is_failed=lambda outcome: outcome["status"] != "ok",
        failure_cancels_siblings=lambda _item, _outcome: True,
        cancel_one=lambda item, reason: {"status": "cancelled", "item": item, "reason": reason},
        abort_one=abort_one,
    )

    assert abort_calls == [("slow", "sibling_tool_failed")]
    assert {outcome["item"] for outcome in outcomes} == {"slow", "fail"}
    assert {outcome["status"] for outcome in outcomes} == {"cancelled", "failed"}


def test_streaming_tool_executor_converts_host_exception_to_outcome() -> None:
    executor = StreamingToolExecutor(max_concurrency=1)

    def execute_one(item: str) -> dict[str, object]:
        raise RuntimeError(f"host failure: {item}")

    outcomes = executor.execute_batches(
        ["bad"],
        execute_one=execute_one,
        is_concurrency_safe=lambda _item: True,
        is_failed=lambda outcome: outcome["status"] != "ok",
        exception_one=lambda item, exc: {
            "status": "failed",
            "item": item,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
    )

    assert outcomes == [
        {
            "status": "failed",
            "item": "bad",
            "error_type": "RuntimeError",
            "error_message": "host failure: bad",
        }
    ]


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


def test_artifact_query_selects_json_path_without_full_blob_context() -> None:
    artifact_store = ArtifactStore.in_memory()
    artifact = artifact_store.write_blob(
        kind="tool_result_full",
        payload=json.dumps(
            {
                "schema": "holo.kernel_v3.tool_result_full.v1",
                "observation": {
                    "content": {
                        "records": [
                            {"company": "HD", "dio": 76.34},
                            {"company": "LOW", "dio": 112.20},
                        ]
                    }
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        mime_type="application/json",
    )
    registry = ToolRegistry.with_builtin_respond()
    register_artifact_tools(registry, artifact_store=artifact_store)

    observation = _execute_with_policy(
        registry,
        CandidateAction(
            action_id="act-artifact-query-json",
            kind="tool",
            name=ARTIFACT_QUERY_NAME,
            description="query artifact json",
            score=1.0,
            payload={"artifact_id": artifact.artifact_id, "path": "observation.content.records", "query": "LOW"},
            reasons=["need_low_row"],
            side_effect_class="read",
        ),
    )

    assert observation.status == "ok"
    assert observation.kind == "artifact_query_result"
    assert observation.content["mode"] == "json"
    assert observation.content["selected_count"] == 1
    assert observation.content["matches"][0]["path"].endswith("[1]")
    assert observation.content["matches"][0]["value"]["company"] == "LOW"
    assert observation.content["matches"][0]["value"]["dio"] == 112.20
    assert "model-owned" in observation.content["host_boundary"]


def test_artifact_query_returns_json_shape_for_path_without_query() -> None:
    artifact_store = ArtifactStore.in_memory()
    artifact = artifact_store.write_blob(
        kind="sec_candidates",
        payload=json.dumps({"facts": {"Revenue": [1, 2, 3]}}, sort_keys=True),
        mime_type="application/json",
    )
    registry = ToolRegistry.with_builtin_respond()
    register_artifact_tools(registry, artifact_store=artifact_store)

    observation = _execute_with_policy(
        registry,
        CandidateAction(
            action_id="act-artifact-query-shape",
            kind="tool",
            name=ARTIFACT_QUERY_NAME,
            description="inspect artifact shape",
            score=1.0,
            payload={"artifact_id": artifact.artifact_id, "path": "$.facts.Revenue"},
            reasons=["need_shape"],
            side_effect_class="read",
        ),
    )

    assert observation.status == "ok"
    assert observation.content["matches"][0]["shape"]["type"] == "array"
    assert observation.content["matches"][0]["value"] == [1, 2, 3]


def test_artifact_query_searches_text_lines() -> None:
    artifact_store = ArtifactStore.in_memory()
    artifact = artifact_store.write_blob(
        kind="filing_text",
        payload="Revenue was 100\nInventory increased to 23.451B\nCost of sales was 106.206B\n",
    )
    registry = ToolRegistry.with_builtin_respond()
    register_artifact_tools(registry, artifact_store=artifact_store)

    observation = _execute_with_policy(
        registry,
        CandidateAction(
            action_id="act-artifact-query-text",
            kind="tool",
            name=ARTIFACT_QUERY_NAME,
            description="search text artifact",
            score=1.0,
            payload={"artifact_id": artifact.artifact_id, "query": "cost sales", "max_matches": 5},
            reasons=["need_cost_line"],
            side_effect_class="read",
        ),
    )

    assert observation.status == "ok"
    assert observation.content["mode"] == "text"
    assert observation.content["matches"] == [{"line": 3, "text_preview": "Cost of sales was 106.206B"}]


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
