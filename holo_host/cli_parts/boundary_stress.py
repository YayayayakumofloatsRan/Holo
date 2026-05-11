from __future__ import annotations

from ..bionic_boundary_stress import (
    BionicBoundaryStressHarness,
    DEFAULT_STAGE46_SUITE,
    STAGE46_NAME,
    show_bionic_boundary_stress_scorecard,
)
from ..config import load_config
from ..reply_api import HoloReplyService
from ..store import QueueStore
from . import bionic as bionic_cli


def run_bionic_boundary_stress_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
    turn_limit: int,
    offline: bool,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        harness = BionicBoundaryStressHarness(
            config=config,
            store=service.store,
            runner=service.runner,
            memory=service.memory,
        )
        return harness.run(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            turn_limit=turn_limit,
            offline=offline,
        ), "local_process"
    finally:
        bionic_cli.close_reply_service(service)


def show_bionic_boundary_stress_scorecard_payload(
    config_path: str | None,
    *,
    suite: str = DEFAULT_STAGE46_SUITE,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        return show_bionic_boundary_stress_scorecard(store=store, suite=suite or DEFAULT_STAGE46_SUITE), "local_process"
    finally:
        store.close()


__all__ = [
    "STAGE46_NAME",
    "run_bionic_boundary_stress_payload",
    "show_bionic_boundary_stress_scorecard_payload",
]
