from __future__ import annotations

from http import HTTPStatus
from typing import Any


def try_acceptance_endpoint(handler: Any, parsed: Any, payload: dict[str, Any]) -> bool:
    service = handler.server.reply_service
    if parsed.path == "/accept-stage10":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage10(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                iterations=int(payload.get("iterations", 3) or 3),
                warmup=int(payload.get("warmup", 1) or 1),
            ),
        )
        return True
    if parsed.path == "/accept-stage12":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage12(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                iterations=int(payload.get("iterations", 1) or 1),
                warmup=int(payload.get("warmup", 1) or 1),
            ),
        )
        return True
    if parsed.path == "/accept-stage13":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage13(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                iterations=int(payload.get("iterations", 1) or 1),
                warmup=int(payload.get("warmup", 1) or 1),
            ),
        )
        return True
    if parsed.path == "/accept-stage14":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage14(
                source_type=str(payload.get("source_type", "synthetic_fixture")).strip() or "synthetic_fixture",
                fixture_path=str(payload.get("fixture_path", "")).strip() or None,
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                limit=int(payload.get("limit", 8) or 8),
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    if parsed.path == "/accept-stage17":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage17(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    if parsed.path == "/accept-stage18":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage18(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    if parsed.path == "/accept-stage19":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage19(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    if parsed.path == "/accept-stage20":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage20(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    if parsed.path == "/accept-stage21":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage21(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    if parsed.path == "/accept-stage22":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage22(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    if parsed.path == "/accept-stage23":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage23(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    if parsed.path == "/accept-stage24":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage24(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    if parsed.path == "/accept-stage25":
        handler._write_json(
            HTTPStatus.OK,
            service.accept_stage25(
                thread_key=str(payload.get("thread_key", "")).strip() or None,
                chat_name=str(payload.get("chat_name", "")).strip() or None,
                channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                sender=str(payload.get("sender", "")).strip() or None,
                artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
            ),
        )
        return True
    return False
