from __future__ import annotations

import tempfile
import sys
from pathlib import Path

from holo_host.agent_event_stream import render_agent_event_stream
from holo_host.config import load_config
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning
from holo_host.reply_api import HoloReplyService
from holo_host.store import QueueStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_holo_host import FakeMemory, FakeRunner, close_service_handles


def _service(tmp_root: Path) -> HoloReplyService:
    config = load_config(repo_root=tmp_root)
    config.runtime.network_enabled = True
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    return HoloReplyService(
        config,
        store=store,
        runner=FakeRunner("I can do financial research if you give me a ticker."),
        memory=FakeMemory(),
    )


def test_market_research_prompt_executes_operator_action_in_reply_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(Path(tmpdir))
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Operator",
                    "text": "请对 NVIDIA AI infrastructure 做一个基于 SEC 10-K 的基本面市场研究",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:stage215",
                    "message_id": "stage215-market-operator-1",
                    "metadata": {"stage215_market_research_operator_dry_run": True},
                }
            )
        finally:
            close_service_handles(service)

    operator_action = result["stage215_market_research_operator_action"]
    operator_run = result["stage214_market_research_operator_run"]

    assert operator_action["status"] == "executed"
    assert operator_action["selected_action"] == "market_research_operator_run"
    assert operator_run["status"] == "ready"
    assert operator_run["stage198_market_research_finalization_gate"]["status"] == "finalized"
    assert result["text"].startswith("Market research report:")
    assert "NVIDIA" in result["text"]
    assert "I can do financial research" not in result["text"]
    assert result["canonical_stop_reason"] == "final_answer_ready"
    ok, paths = assert_no_private_reasoning(result)
    assert ok, paths


def test_market_operator_trace_renders_operator_phases() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(Path(tmpdir))
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Operator",
                    "text": "Do a filing-grounded market research report on NVIDIA AI infrastructure.",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:stage215-trace",
                    "message_id": "stage215-market-operator-trace-1",
                    "metadata": {"stage215_market_research_operator_dry_run": True},
                }
            )
        finally:
            close_service_handles(service)

    rendered = render_agent_event_stream(result["stage153_agent_event_stream"])

    assert "[market_operator] phase=plan status=planned" in rendered
    assert "[market_operator] phase=crawl status=sufficient" in rendered
    assert "[market_operator] phase=finalize status=finalized" in rendered
    assert "[final]" in rendered
    assert "Market research report:" in rendered
