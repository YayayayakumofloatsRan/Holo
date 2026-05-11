from __future__ import annotations

from ..config import load_config
from ..reply_api import HoloReplyService
from ..stage43_motivational_dynamics import STAGE43_NAME
from . import bionic as bionic_cli


def accept_stage43_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.accept_stage43(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
        ), "local_process"
    finally:
        bionic_cli.close_reply_service(service)


__all__ = [
    "STAGE43_NAME",
    "accept_stage43_payload",
]
