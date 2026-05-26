from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.config import load_config
from holo_host.models import TurnContext
from holo_host.processors import CodexCliProcessor, _should_run_recall_reconstruct, build_attention_state
from holo_host.stage132_progressive_conscious_stream import plan_stage132_progressive_stream
from holo_host.stage135_i_state_topology import (
    STAGE135_SCHEMA,
    build_stage135_i_state_topology,
    write_stage135_i_state_topology_artifacts,
)
from holo_host.stage143_packet_budget import STAGE143_SCHEMA, build_stage143_packet_budget


def _config(root: Path):
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
network_enabled = false

[processor_fabric]
deepseek_base_url = "https://api.deepseek.com"
deepseek_api_key_env = "TEST_DEEPSEEK_API_KEY"

[provider_backends.micro_fast]
primary_provider = "deepseek"
backup_provider = "openai_compatible"
model = "deepseek-v4-flash"
reasoning_effort = "low"
max_output_tokens = 900

[provider_backends.subject_main]
primary_provider = "deepseek"
backup_provider = "openai_compatible"
model = "deepseek-v4"
reasoning_effort = "medium"
max_output_tokens = 4096
""".strip(),
        encoding="utf-8",
    )
    return load_config(str(config_path), repo_root=root)


def _context(text: str) -> TurnContext:
    packet = {
        "selected_action": {"action_type": "reply_once", "score": 0.86},
        "recent_dialogue_window": {
            "lines": [
                "user: distinguish my words from your internal state",
                "holo: I need a visible topology of the thought flow",
            ]
        },
        "active_thread_state": {
            "continuity_summary": "Stage135 builds an endogenous I-state topology",
            "scene_state": {"shared_frame": "live provider thought-flow visualization"},
        },
    }
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:stage135",
        chat_name="Stage135",
        sender="Operator",
        user_text=text,
        sidecar=packet,
        mind_packet=packet,
        attention_state=build_attention_state(text, channel="holo_cli"),
        emotion_state={"arousal": 0.38, "valence": 0.58},
        history=[],
        metadata={"event_id": "evt-stage135"},
        capability_context={
            "tool_requests": [
                {"name": "workspace_inspect", "reason": "inspect host directory", "payload": {"mode": "readonly"}},
            ],
            "tool_permission_grants": [{"tool": "workspace_inspect", "mode": "readonly"}],
        },
        uncertainty_level=0.68,
    )


class _Stage135Runner:
    def __init__(self, *, deep_needed: bool = True) -> None:
        self.deep_needed = deep_needed
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"prompt": prompt, **kwargs})
        if str(kwargs.get("budget_tag", "")) == "stage124_fast_packet":
            return SimpleNamespace(
                reply_text=json.dumps(
                    {
                        "intent": "i_state_topology",
                        "scene": "stage135 live trace",
                        "deep_packet_needed": self.deep_needed,
                        "shallow_reply": "I will mark the first reaction and then decide whether to continue.",
                        "speak_now": True,
                        "continue_until": "the I-state topology has enough new state",
                    },
                    ensure_ascii=False,
                ),
                session_id="stage135-fast",
                returncode=0,
                stdout="",
                stderr="",
                metadata={"provider": "fake", "lane": "micro_fast", "model": "fake-flash", "usage": {"prompt_tokens": 120}},
            )
        return SimpleNamespace(
            reply_text="The deeper packet adds a state delta, separates inner flow from visible speech, and keeps tools inside the WSL brain.",
            session_id="stage135-deep",
            returncode=0,
            stdout="",
            stderr="",
            metadata={
                "provider": "fake",
                "lane": "subject_main",
                "model": "fake-pro",
                "usage": {"prompt_tokens": 520, "completion_tokens": 90},
                "agent_tool_loop": {"round_count": 1, "executed_tools": ["workspace_inspect"]},
            },
        )


def _node(payload: dict[str, object], node_id: str) -> dict[str, object]:
    for node in payload["nodes"]:  # type: ignore[index]
        item = dict(node)
        if item["id"] == node_id:
            return item
    raise AssertionError(f"missing node {node_id}")


def test_stage135_topology_separates_user_inner_visible_tool_and_memory_channels() -> None:
    stream_plan = plan_stage132_progressive_stream(
        fast_packet={
            "intent": "i_state_topology",
            "scene": "cli",
            "deep_packet_needed": True,
            "shallow_reply": "First I catch the intent.",
            "speak_now": True,
            "continue_until": "new state stops changing",
        },
        continuation_lane="subject_main",
        continuation_lane_reason="high_uncertainty",
        selected_action_type="reply_once",
        uncertainty_level=0.68,
        channel="holo_cli",
        expression_budget=3,
        agent_tool_requests=[{"name": "workspace_inspect", "reason": "read-only self inspection", "payload": {}}],
        fast_context_frame={"cache_hint": "stage135:test", "line_count": 8, "char_count": 1100},
    )

    payload = build_stage135_i_state_topology(
        context=_context("把内部思考流做成拓扑结构"),
        fast_packet={"deep_packet_needed": True, "shallow_reply": "First I catch the intent.", "intent": "topology"},
        stream_plan=stream_plan,
        packet_policy={"continuity": {"stream_mode": "continuous_thought"}, "target_input_tokens": 48000},
        tool_loop={"round_count": 1, "executed_tools": ["workspace_inspect"]},
        visible_segments=[
            {"role": "fast_reaction", "text": "First I catch the intent."},
            {"role": "deep_continuation", "text": "Now I update state and continue only if useful."},
        ],
    )

    assert payload["schema"] == STAGE135_SCHEMA
    assert payload["stage"] == 135
    assert payload["subject"]["subject_id"] == "holo"
    assert payload["single_brain_boundary"]["decision_authority"] == "wsl_holo_host"
    assert _node(payload, "holo_self")["channel"] == "i_state"
    assert _node(payload, "external_user_input")["channel"] == "external_user"
    assert _node(payload, "fast_packet")["channel"] == "holo_inner"
    assert _node(payload, "visible_fast_reaction")["channel"] == "holo_visible"
    assert _node(payload, "tool_workspace_inspect")["channel"] == "tool_result"
    assert _node(payload, "memory_delta")["channel"] == "memory_delta"
    assert any(edge["source"] == "external_user_input" and edge["target"] == "holo_self" for edge in payload["edges"])
    assert any(edge["source"] == "state_delta" and edge["target"] == "continue_gate" for edge in payload["edges"])
    assert payload["metrics"]["channel_count"] >= 6
    assert payload["continue_gate"]["decision"] == "continue"


def test_stage135_topology_uses_actual_tool_observation_ledger_nodes() -> None:
    payload = build_stage135_i_state_topology(
        context=_context("show the actual tool observations"),
        fast_packet={"deep_packet_needed": True, "intent": "tool_grounded_trace"},
        stream_plan={"deep_packet_needed": True},
        tool_loop={
            "tool_observation_ledger": [
                {
                    "provider_call_id": "call_workspace",
                    "tool": "workspace_inspect",
                    "status": "ok",
                    "summary": "workspace list_dir: docs, holo_host",
                    "data_keys": ["entries", "path"],
                    "grounding_tags": ["workspace"],
                }
            ]
        },
    )

    observation = _node(payload, "tool_observation_call_workspace")
    assert observation["channel"] == "tool_observation"
    assert observation["kind"] == "tool_observation"
    assert "workspace list_dir" in observation["summary"]
    assert any(edge["source"] == "tool_observation_call_workspace" and edge["target"] == "state_delta" for edge in payload["edges"])


def test_stage135_topology_uses_actual_memory_observation_ledger_nodes() -> None:
    payload = build_stage135_i_state_topology(
        context=_context("show the actual memory observations"),
        fast_packet={"deep_packet_needed": True, "intent": "memory_grounded_trace"},
        stream_plan={"deep_packet_needed": True},
        memory_observation_ledger=[
            {
                "schema": "holo.memory_grounding.v1",
                "memory_call_id": "selected_memory_origin",
                "source_family": "archive",
                "selected_ids": ["archive:turn-1"],
                "status": "grounded",
                "summary": "origin turn selected from archive",
                "confidence": 0.84,
                "freshness": "graph-led",
                "grounding_tags": ["memory", "archive"],
                "contradiction_flags": [],
                "missing_source": False,
            }
        ],
    )

    observation = _node(payload, "memory_observation_selected_memory_origin")
    assert observation["channel"] == "memory_observation"
    assert observation["kind"] == "memory_observation"
    assert "origin turn" in observation["summary"]
    assert payload["metrics"]["memory_observation_node_count"] == 1
    assert any(edge["source"] == "memory_observation_selected_memory_origin" and edge["target"] == "memory_delta" for edge in payload["edges"])


def test_stage135_topology_includes_memory_alignment_gate() -> None:
    payload = build_stage135_i_state_topology(
        context=_context("show memory claim alignment"),
        fast_packet={"deep_packet_needed": True, "intent": "memory_alignment_trace"},
        stream_plan={"deep_packet_needed": True},
        memory_observation_ledger=[
            {
                "schema": "holo.memory_grounding.v1",
                "memory_call_id": "selected_preference",
                "source_family": "durable",
                "selected_ids": ["memory:preference-emoji"],
                "status": "grounded",
                "summary": "user preference: fewer emoji",
                "confidence": 0.9,
                "freshness": "test",
                "grounding_tags": ["memory", "durable"],
                "contradiction_flags": [],
                "missing_source": False,
            }
        ],
        memory_alignment={
            "schema": "holo.memory_alignment.v1",
            "status": "aligned",
            "claim_count": 1,
            "aligned_claim_count": 1,
            "weak_claim_count": 0,
            "unsupported_claim_count": 0,
            "contradicted_claim_count": 0,
            "claims": [
                {
                    "claim_id": "claim:emoji",
                    "claim_family": "preference",
                    "claim_text": "I remember you prefer fewer emoji.",
                    "key_terms": ["preference", "fewer", "emoji"],
                    "evidence_ids": ["selected_preference"],
                    "evidence_source_families": ["durable"],
                    "alignment_score": 0.94,
                    "missing_terms": [],
                    "contradiction_flags": [],
                    "status": "aligned",
                }
            ],
            "repair_required": False,
            "repair_reason": "",
        },
    )

    assert _node(payload, "memory_alignment_gate")["channel"] == "memory_alignment"
    assert payload["metrics"]["memory_alignment_node_count"] >= 1
    assert payload["metrics"]["memory_alignment_claim_count"] == 1
    assert payload["metrics"]["memory_alignment_unsupported_count"] == 0
    assert payload["metrics"]["memory_alignment_status"] == "aligned"
    assert any(edge["target"] == "memory_alignment_gate" for edge in payload["edges"])
    assert any(edge["source"] == "memory_alignment_gate" and edge["target"] == "memory_delta" for edge in payload["edges"])


def test_stage135_topology_includes_semantic_novelty_gate() -> None:
    payload = build_stage135_i_state_topology(
        context=_context("show semantic novelty gating"),
        fast_packet={"deep_packet_needed": True, "intent": "novelty_trace"},
        stream_plan={"deep_packet_needed": True},
        visible_segments=[
            {"role": "fast_reaction", "text": "First I catch the intent."},
            {"role": "deep_continuation", "text": "Then I add the concrete next step."},
        ],
        stage142_semantic_novelty={
            "schema": "holo.stage142.semantic_novelty_gate.v1",
            "candidate_count": 2,
            "emitted_count": 2,
            "suppressed_count": 0,
            "repaired_count": 0,
            "evaluations": [],
            "status": "passed",
        },
    )

    assert _node(payload, "semantic_novelty_gate")["channel"] == "semantic_novelty"
    assert payload["metrics"]["semantic_novelty_node_count"] == 1
    assert payload["metrics"]["semantic_novelty_status"] == "passed"
    assert any(edge["source"] == "continue_gate" and edge["target"] == "semantic_novelty_gate" for edge in payload["edges"])
    assert any(edge["source"] == "semantic_novelty_gate" and edge["target"] == "visible_deep_continuation" for edge in payload["edges"])


def test_stage135_topology_includes_packet_budget_gate() -> None:
    packet_budget = build_stage143_packet_budget(
        stage132_stream_plan={"deep_packet_needed": False, "stop_reason": "provider_fast_packet_said_fast_answer_enough"},
        stage132_fast_context_frame={"cache_hint": "stage132:stage135-budget", "char_count": 800},
        stage124_thought_loop={"deep_packet_sent": False, "fast_packet_ms": 17},
        timing_ms={"processor_ms": 24},
    )
    payload = build_stage135_i_state_topology(
        context=_context("show packet budget gate"),
        fast_packet={"deep_packet_needed": False, "intent": "packet_budget_trace"},
        stream_plan={"deep_packet_needed": False, "stop_reason": "provider_fast_packet_said_fast_answer_enough"},
        stage143_packet_budget=packet_budget,
    )

    assert packet_budget["schema"] == STAGE143_SCHEMA
    assert _node(payload, "packet_budget_gate")["channel"] == "packet_budget"
    assert payload["metrics"]["packet_budget_node_count"] == 1
    assert payload["metrics"]["packet_budget_packet_count"] == 2
    assert payload["metrics"]["packet_budget_stop_reason"] == "provider_fast_packet_said_fast_answer_enough"
    assert any(edge["target"] == "packet_budget_gate" for edge in payload["edges"])


def test_stage135_topology_includes_context_economy_gate() -> None:
    packet_budget = build_stage143_packet_budget(
        stage132_stream_plan={"deep_packet_needed": True, "stop_reason": "stage142:suppressed_duplicate"},
        stage132_fast_context_frame={"cache_hint": "stage132:stage135-context", "char_count": 800},
        stage124_thought_loop={"deep_packet_sent": True, "fast_packet_ms": 17},
        stage142_semantic_novelty={"status": "suppressed_duplicate", "candidate_count": 2, "suppressed_count": 1},
        timing_ms={"processor_ms": 90},
    )
    context_economy = {
        "schema": "holo.stage144.context_economy.v1",
        "working_set_slots": [
            {
                "slot_id": "packet_budget:test",
                "slot_type": "packet_budget",
                "summary": "deep ran but Stage142 suppressed duplicate continuation",
                "priority": 0.8,
                "freshness": "current_turn",
                "confidence": 0.8,
                "token_estimate": 12,
                "include_reason": "packet budget exposes cost and stop reason",
                "eviction_reason": "",
            }
        ],
        "context_sufficiency_score": 0.52,
        "context_waste_score": 0.78,
        "packet_policy_recommendation": "skip: deep packet produced low-novelty duplicate visible content.",
        "recommended_deep_policy": "skip",
        "confidence": 0.78,
        "reason": "deep packet produced low-novelty duplicate visible content.",
        "shadow_only": True,
    }
    payload = build_stage135_i_state_topology(
        context=_context("show context economy gate"),
        fast_packet={"deep_packet_needed": True, "intent": "context_economy_trace"},
        stream_plan={"deep_packet_needed": True, "stop_reason": "stage142:suppressed_duplicate"},
        stage142_semantic_novelty={"status": "suppressed_duplicate", "candidate_count": 2, "suppressed_count": 1},
        stage143_packet_budget=packet_budget,
        stage144_context_economy=context_economy,
    )

    assert _node(payload, "context_economy_gate")["channel"] == "context_economy"
    assert payload["metrics"]["context_economy_node_count"] == 1
    assert payload["metrics"]["context_economy_recommended_deep_policy"] == "skip"
    assert payload["metrics"]["context_economy_shadow_only"] is True
    assert any(edge["source"] == "packet_budget_gate" and edge["target"] == "context_economy_gate" for edge in payload["edges"])
    assert any(edge["source"] == "context_economy_gate" and edge["target"] == "continue_gate" for edge in payload["edges"])


def test_stage135_topology_includes_reaction_kernel_shadow_node() -> None:
    packet_budget = build_stage143_packet_budget(
        stage132_stream_plan={"deep_packet_needed": True, "stop_reason": "stage142:suppressed_duplicate"},
        stage132_fast_context_frame={"cache_hint": "stage132:stage135-reaction", "char_count": 800},
        stage124_thought_loop={"deep_packet_sent": True, "fast_packet_ms": 17},
        stage142_semantic_novelty={"status": "suppressed_duplicate", "candidate_count": 2, "suppressed_count": 1},
        timing_ms={"processor_ms": 90},
    )
    context_economy = {
        "schema": "holo.stage144.context_economy.v1",
        "context_sufficiency_score": 0.44,
        "context_waste_score": 0.78,
        "recommended_deep_policy": "skip",
        "shadow_only": True,
    }
    outcome_appraisal = {
        "schema": "holo.stage145.outcome_appraisal.v1",
        "predicted_user_need": "nonredundant_continuation",
        "prediction_error": 0.72,
        "observed_stage142_status": "suppressed_duplicate",
        "observed_packet_waste": 0.78,
        "shadow_only": True,
    }
    reaction_kernel = {
        "schema": "holo.stage145.reaction_kernel_shadow.v1",
        "prediction_error": 0.72,
        "kernel_delta_candidates": [{"parameter": "novelty_threshold", "delta": 0.12, "applied": False}],
        "delta_count": 1,
        "shadow_only": True,
        "applied": False,
    }
    payload = build_stage135_i_state_topology(
        context=_context("show reaction kernel gate"),
        fast_packet={"deep_packet_needed": True, "intent": "reaction_kernel_trace"},
        stream_plan={"deep_packet_needed": True, "stop_reason": "stage142:suppressed_duplicate"},
        stage142_semantic_novelty={"status": "suppressed_duplicate", "candidate_count": 2, "suppressed_count": 1},
        stage143_packet_budget=packet_budget,
        stage144_context_economy=context_economy,
        stage145_outcome_appraisal=outcome_appraisal,
        stage145_reaction_kernel_shadow=reaction_kernel,
    )

    assert _node(payload, "reaction_kernel_shadow")["channel"] == "reaction_kernel"
    assert payload["metrics"]["reaction_kernel_node_count"] == 1
    assert payload["metrics"]["reaction_kernel_delta_count"] == 1
    assert payload["metrics"]["reaction_kernel_shadow_only"] is True
    assert any(edge["target"] == "reaction_kernel_shadow" for edge in payload["edges"])
    assert any(edge["source"] == "reaction_kernel_shadow" and edge["target"] == "holo_self" for edge in payload["edges"])


def test_stage135_topology_includes_context_memory_fabric_node() -> None:
    fabric = {
        "schema": "holo.stage150.context_memory_fabric.v1",
        "working_context_packet": {
            "reusable_state_slots": [
                {"slot_id": "current", "slot_type": "current_user_constraint", "summary": "no emoji"},
                {"slot_id": "task", "slot_type": "active_task", "summary": "build structured context"},
            ],
            "open_loops": [{"summary": "finish Stage150 verification"}],
        },
        "background_compact": {"user_visible": False},
        "evidence_discipline": {"unverified_claim_families": ["test"]},
    }
    payload = build_stage135_i_state_topology(
        context=_context("show context memory fabric"),
        stage150_context_memory_fabric=fabric,
    )

    assert _node(payload, "context_memory_fabric")["channel"] == "context_memory_fabric"
    assert payload["metrics"]["context_memory_fabric_node_count"] == 1
    assert payload["metrics"]["context_memory_fabric_slot_count"] == 2
    assert payload["metrics"]["context_memory_fabric_open_loop_count"] == 1


def test_stage135_processor_debug_carries_i_state_topology_for_deep_and_fast_only_paths(tmp_path: Path) -> None:
    config = _config(tmp_path)
    deep_runner = _Stage135Runner(deep_needed=True)
    deep_processor = CodexCliProcessor(config, deep_runner)  # type: ignore[arg-type]
    deep_plan = deep_processor.generate(_context("请把内部思考流可视化"), session_id="stage135")

    topology = deep_plan.debug["stage135_i_state_topology"]
    assert topology["schema"] == STAGE135_SCHEMA
    assert deep_plan.debug["memory_observation_ledger"]
    assert topology["continue_gate"]["decision"] == "continue"
    assert _node(topology, "deep_packet")["channel"] == "holo_inner"
    assert _node(topology, "visible_deep_continuation")["channel"] == "holo_visible"
    assert any(node["channel"] == "tool_result" for node in topology["nodes"])
    assert "Stage135 I-State Frame" in str(deep_runner.calls[0]["prompt"])
    assert "Stage135 I-State Contract" in str(deep_runner.calls[1]["prompt"])
    assert deep_plan.debug["stage135_i_state_prompt_frame"]["marker"] == "Stage135 I-State Frame"
    assert deep_plan.debug["stage143_packet_budget"]["schema"] == STAGE143_SCHEMA
    assert topology["metrics"]["packet_budget_node_count"] == 1
    assert deep_plan.debug["stage144_context_economy"]["schema"] == "holo.stage144.context_economy.v1"
    assert topology["metrics"]["context_economy_node_count"] == 1
    assert deep_plan.debug["stage145_outcome_appraisal"]["schema"] == "holo.stage145.outcome_appraisal.v1"
    assert deep_plan.debug["stage145_reaction_kernel_shadow"]["schema"] == "holo.stage145.reaction_kernel_shadow.v1"
    assert topology["metrics"]["reaction_kernel_node_count"] == 1

    fast_runner = _Stage135Runner(deep_needed=False)
    fast_processor = CodexCliProcessor(config, fast_runner)  # type: ignore[arg-type]
    fast_plan = fast_processor.generate(_context("收到就好"), session_id="stage135-fast")
    fast_topology = fast_plan.debug["stage135_i_state_topology"]
    assert fast_topology["continue_gate"]["decision"] == "stop"
    assert fast_plan.debug["memory_observation_ledger"]
    assert "deep_packet" not in {node["id"] for node in fast_topology["nodes"]}
    assert _node(fast_topology, "visible_fast_reaction")["channel"] == "holo_visible"
    assert "Stage135 I-State Frame" in str(fast_runner.calls[0]["prompt"])
    assert fast_plan.debug["stage143_packet_budget"]["skipped_count"] == 1
    assert fast_topology["metrics"]["packet_budget_node_count"] == 1
    assert fast_plan.debug["stage144_context_economy"]["shadow_only"] is True
    assert fast_topology["metrics"]["context_economy_node_count"] == 1
    assert fast_plan.debug["stage145_reaction_kernel_shadow"]["shadow_only"] is True
    assert fast_topology["metrics"]["reaction_kernel_node_count"] == 1


def test_stage135_i_state_trace_does_not_trigger_recall_reconstruct_without_memory_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    context = _context("show the current I-state topology and packet flow")
    packet = dict(context.mind_packet)
    packet.update(
        {
            "tier": "deep_recall",
            "query_focus": "i_state_topology",
            "recall_reason": "stage135_i_state_trace",
            "activation_trace_ids": ["archive:recent-turn"],
            "episodic_recall": {"lines": ["recent packet asked for topology"], "items": []},
        }
    )
    context.mind_packet = packet
    context.sidecar = packet

    assert _should_run_recall_reconstruct(context, config) is False


def test_stage135_explicit_memory_query_still_triggers_recall_reconstruct(tmp_path: Path) -> None:
    config = _config(tmp_path)
    context = _context("\u56de\u5fc6\u4e00\u4e0b\u6700\u65e9\u7684\u8bb0\u5fc6\u662f\u4ec0\u4e48")
    packet = dict(context.mind_packet)
    packet.update(
        {
            "tier": "deep_recall",
            "query_focus": "memory",
            "recall_reason": "stage17:explicit_memory_query",
            "activation_trace_ids": ["archive:origin-turn"],
            "episodic_recall": {"lines": ["origin memory candidate"], "items": []},
        }
    )
    context.mind_packet = packet
    context.sidecar = packet

    assert _should_run_recall_reconstruct(context, config) is True


def test_stage135_artifact_html_renders_topology_network(tmp_path: Path) -> None:
    report = write_stage135_i_state_topology_artifacts(
        tmp_path,
        output_dir=tmp_path / "artifacts" / "stage135",
        sample_query="把 Holo 的我状态用拓扑图显示出来",
    )

    html_path = Path(report["html_path"])
    payload_path = Path(report["payload_path"])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8")

    assert report["stage"] == 135
    assert html_path.exists()
    assert payload_path.exists()
    assert payload["schema"] == STAGE135_SCHEMA
    assert "stage135Topology" in html
    assert "<canvas id=\"topology\"" in html
    assert "holo_self" in html
    assert "continue_gate" in html
    assert payload["privacy"]["raw_provider_content_included"] is False


def test_stage135_cli_dispatches_and_writes_artifacts(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )

    result = cli.main(
        [
            "stage135-i-state-topology",
            "--output-dir",
            str(tmp_path / "artifacts" / "stage135"),
            "--sample-query",
            "显示 Holo 主体的拓扑思考流",
        ]
    )

    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stage"] == 135
    assert Path(report["html_path"]).exists()
    assert Path(report["payload_path"]).exists()
