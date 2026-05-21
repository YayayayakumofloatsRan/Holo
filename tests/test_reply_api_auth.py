from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from holo_host.reply_api import _ReplyHTTPServer, _handler_factory


class _FakeReplyService:
    logger = logging.getLogger("test.reply_api_auth")

    def health(self) -> dict:
        return {"status": "ok"}

    def handle_reply(self, payload: dict) -> dict:
        return {"action": "reply", "text": str(payload.get("text", ""))}


def _start_server(*, token: str) -> tuple[_ReplyHTTPServer, str]:
    server = _ReplyHTTPServer(
        ("127.0.0.1", 0),
        _handler_factory(),
        service=_FakeReplyService(),
        bearer_token=token,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def _open_json(url: str, *, token: str = "", data: dict | None = None) -> tuple[int, dict]:
    headers = {}
    payload = None
    method = "GET"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        method = "POST"
        headers["Content-Type"] = "application/json"
        payload = json.dumps(data).encode("utf-8")
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_reply_api_requires_bearer_token_when_configured() -> None:
    server, base_url = _start_server(token="secret")
    try:
        status, payload = _open_json(f"{base_url}/health")
        assert status == HTTPStatus.UNAUTHORIZED
        assert payload["error"] == "unauthorized"

        status, payload = _open_json(f"{base_url}/health", token="secret")
        assert status == HTTPStatus.OK
        assert payload["status"] == "ok"
        assert payload["auth_required"] is True

        status, payload = _open_json(
            f"{base_url}/reply",
            token="secret",
            data={"text": "hello"},
        )
        assert status == HTTPStatus.OK
        assert payload["text"] == "hello"
    finally:
        server.shutdown()
        server.server_close()


def test_reply_api_allows_local_unauthenticated_mode_when_no_token() -> None:
    server, base_url = _start_server(token="")
    try:
        status, payload = _open_json(f"{base_url}/health")
        assert status == HTTPStatus.OK
        assert payload["status"] == "ok"
        assert payload["auth_required"] is False
    finally:
        server.shutdown()
        server.server_close()
