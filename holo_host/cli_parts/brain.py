from __future__ import annotations

from ..bionic_brain import BionicBrainHarness, accept_stage40_payload as build_accept_stage40_payload, run_stage40_agent_eval
from ..config import load_config
from ..reply_api import HoloReplyService
from ..store import QueueStore
from . import bionic as bionic_cli


def brain_run_payload(
    config_path: str | None,
    *,
    goal: str,
    thread_key: str,
    chat_name: str,
    channel: str,
    offline: bool,
    max_steps: int,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        harness = BionicBrainHarness(
            config=config,
            store=service.store,
            memory=service.memory,
            runner=None if offline else service.runner,
        )
        return harness.run(
            goal=goal,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            offline=offline,
            max_steps=max_steps,
        ), "local_process"
    finally:
        bionic_cli.close_reply_service(service)


def brain_trace_payload(config_path: str | None, *, trace_id: int) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        run = store.get_bionic_brain_run(run_id=trace_id)
        if not run:
            return {"ok": False, "stage": "stage40-bionic-brain-os-harness", "trace_id": trace_id, "error": "trace_not_found"}, "local_process"
        return {
            "ok": True,
            "stage": "stage40-bionic-brain-os-harness",
            "trace_id": trace_id,
            "run": run,
            "steps": store.list_bionic_brain_steps(run_id=trace_id),
        }, "local_process"
    finally:
        store.close()


def show_context_bundle_payload(config_path: str | None, *, bundle_id: str) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        bundle = store.get_context_bundle(bundle_id=bundle_id)
        if not bundle:
            return {"ok": False, "stage": "stage40-bionic-brain-os-harness", "bundle_id": bundle_id, "error": "bundle_not_found"}, "local_process"
        return {"ok": True, "stage": "stage40-bionic-brain-os-harness", "bundle": bundle}, "local_process"
    finally:
        store.close()


def brain_metrics_payload(config_path: str | None, *, limit: int) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        return store.latest_bionic_brain_metrics(limit=limit), "local_process"
    finally:
        store.close()


def agent_eval_payload(config_path: str | None, *, suite: str) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        harness = BionicBrainHarness(config=config, store=service.store, memory=service.memory, runner=None)
        return run_stage40_agent_eval(config=config, store=service.store, harness=harness, suite=suite), "local_process"
    finally:
        bionic_cli.close_reply_service(service)


def accept_stage40_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    stage39_payload, _transport = bionic_cli.accept_stage39_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        payload = build_accept_stage40_payload(
            config=config,
            store=service.store,
            memory=service.memory,
            runner=service.runner,
            stage39_payload=stage39_payload,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
        )
        return payload, "local_process"
    finally:
        bionic_cli.close_reply_service(service)
