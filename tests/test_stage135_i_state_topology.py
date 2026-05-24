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


def test_stage135_processor_debug_carries_i_state_topology_for_deep_and_fast_only_paths(tmp_path: Path) -> None:
    config = _config(tmp_path)
    deep_runner = _Stage135Runner(deep_needed=True)
    deep_processor = CodexCliProcessor(config, deep_runner)  # type: ignore[arg-type]
    deep_plan = deep_processor.generate(_context("请把内部思考流可视化"), session_id="stage135")

    topology = deep_plan.debug["stage135_i_state_topology"]
    assert topology["schema"] == STAGE135_SCHEMA
    assert topology["continue_gate"]["decision"] == "continue"
    assert _node(topology, "deep_packet")["channel"] == "holo_inner"
    assert _node(topology, "visible_deep_continuation")["channel"] == "holo_visible"
    assert any(node["channel"] == "tool_result" for node in topology["nodes"])
    assert "Stage135 I-State Frame" in str(deep_runner.calls[0]["prompt"])
    assert "Stage135 I-State Contract" in str(deep_runner.calls[1]["prompt"])
    assert deep_plan.debug["stage135_i_state_prompt_frame"]["marker"] == "Stage135 I-State Frame"

    fast_runner = _Stage135Runner(deep_needed=False)
    fast_processor = CodexCliProcessor(config, fast_runner)  # type: ignore[arg-type]
    fast_plan = fast_processor.generate(_context("收到就好"), session_id="stage135-fast")
    fast_topology = fast_plan.debug["stage135_i_state_topology"]
    assert fast_topology["continue_gate"]["decision"] == "stop"
    assert "deep_packet" not in {node["id"] for node in fast_topology["nodes"]}
    assert _node(fast_topology, "visible_fast_reaction")["channel"] == "holo_visible"
    assert "Stage135 I-State Frame" in str(fast_runner.calls[0]["prompt"])


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
