from __future__ import annotations

from ..config import load_config
from ..engineering_agent import EngineeringAgentHarness, accept_stage41_payload as build_accept_stage41_payload
from ..reply_api import HoloReplyService
from ..store import QueueStore
from . import bionic as bionic_cli
from . import brain as brain_cli


def engineering_run_payload(
    config_path: str | None,
    *,
    goal: str,
    thread_key: str,
    chat_name: str,
    channel: str,
    offline: bool,
    max_steps: int,
    allow_repo_write: bool,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        harness = EngineeringAgentHarness(
            config=config,
            store=service.store,
            runner=None if offline else service.runner,
        )
        return harness.run(
            goal=goal,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            offline=offline,
            max_steps=max_steps,
            allow_repo_write=allow_repo_write,
        ), "local_process"
    finally:
        bionic_cli.close_reply_service(service)


def engineering_trace_payload(config_path: str | None, *, trace_id: int) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        run = store.get_bionic_brain_run(run_id=trace_id)
        if not run:
            return {"ok": False, "stage": "stage41-complete-engineering-agent", "trace_id": trace_id, "error": "trace_not_found"}, "local_process"
        return {
            "ok": True,
            "stage": "stage41-complete-engineering-agent",
            "trace_id": trace_id,
            "run": run,
            "steps": store.list_bionic_brain_steps(run_id=trace_id),
        }, "local_process"
    finally:
        store.close()


def engineering_metrics_payload(config_path: str | None, *, limit: int) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        return store.latest_bionic_brain_metrics(limit=limit, stage="stage41-complete-engineering-agent"), "local_process"
    finally:
        store.close()


def accept_stage41_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    stage40_payload, _transport = brain_cli.accept_stage40_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        payload = build_accept_stage41_payload(
            config=config,
            store=service.store,
            runner=service.runner,
            stage40_payload=stage40_payload,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
        )
        return payload, "local_process"
    finally:
        bionic_cli.close_reply_service(service)
