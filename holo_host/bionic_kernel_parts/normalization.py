from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..store import QueueStore
from .contracts import BionicTurnRequest


@dataclass(slots=True)
class NormalizedTurn:
    query: str
    thread_key: str
    chat_name: str
    channel: str
    adapter: str
    record: bool
    context: dict[str, Any]


def normalize_turn_request(request: BionicTurnRequest) -> NormalizedTurn:
    query = str(request.query or "")
    chat_name = str(request.chat_name or "")
    channel = str(request.channel or "cli").strip() or "cli"
    adapter = str(request.adapter or channel).strip() or channel
    thread_key = QueueStore._normalize_wechat_thread_key(
        channel,
        str(request.thread_key or ""),
        subject=chat_name,
        display_name=chat_name,
    )
    context = dict(request.metadata or {})
    context.update({
        "channel": channel,
        "thread_key": thread_key,
        "chat_name": chat_name,
        "sender": chat_name or thread_key,
        "stage29_kernel": True,
        "stage29_adapter": adapter,
        "transport_is_interface": True,
        "transport_decision_authority": False,
    })
    return NormalizedTurn(
        query=query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        adapter=adapter,
        record=bool(request.record),
        context=context,
    )
