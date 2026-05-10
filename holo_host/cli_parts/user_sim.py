from __future__ import annotations

from ..bionic_user_sim import (
    BionicUserSimulationHarness,
    DEFAULT_STAGE42_SUITE,
    STAGE42_NAME,
    show_bionic_user_sim_scorecard,
)
from ..config import load_config
from ..reply_api import HoloReplyService
from ..store import QueueStore
from . import bionic as bionic_cli


def run_bionic_user_sim_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
    scenario: str,
    turn_limit: int,
    offline: bool,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        harness = BionicUserSimulationHarness(
            config=config,
            store=service.store,
            runner=None if offline else service.runner,
        )
        return harness.run(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            scenario=scenario or DEFAULT_STAGE42_SUITE,
            turn_limit=turn_limit,
            offline=offline,
        ), "local_process"
    finally:
        bionic_cli.close_reply_service(service)


def show_bionic_user_sim_scorecard_payload(
    config_path: str | None,
    *,
    suite: str = DEFAULT_STAGE42_SUITE,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        return show_bionic_user_sim_scorecard(store=store, suite=suite or DEFAULT_STAGE42_SUITE), "local_process"
    finally:
        store.close()


def accept_stage42_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.accept_stage42(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
        ), "local_process"
    finally:
        bionic_cli.close_reply_service(service)


__all__ = [
    "STAGE42_NAME",
    "run_bionic_user_sim_payload",
    "show_bionic_user_sim_scorecard_payload",
    "accept_stage42_payload",
]
