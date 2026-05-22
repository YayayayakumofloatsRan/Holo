from __future__ import annotations

import json
import logging
import threading
from types import SimpleNamespace
from pathlib import Path
from http import HTTPStatus
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from holo_host.reply_api import _ReplyHTTPServer, _handler_factory


class _FakeReplyService:
    logger = logging.getLogger("test.reply_api_auth")

    def __init__(self) -> None:
        self.backfill_calls: list[dict] = []

    def health(self) -> dict:
        return {"status": "ok"}

    def handle_reply(self, payload: dict) -> dict:
        return {"action": "reply", "text": str(payload.get("text", ""))}

    def backfill_vector_memory(
        self,
        *,
        channel: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
    ) -> dict:
        call = {"channel": channel, "thread_key": thread_key, "chat_name": chat_name}
        self.backfill_calls.append(call)
        return {"status": "ok", **call}


class _TelemetryReplyService(_FakeReplyService):
    def __init__(self, repo_root: Path) -> None:
        self.config = SimpleNamespace(runtime=SimpleNamespace(repo_root=repo_root))


class _TelemetryDiagnosticService(_TelemetryReplyService):
    def trace_hybrid_recall(
        self,
        *,
        query: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
    ) -> dict:
        return {
            "query": query,
            "channel": channel,
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "tier": "deep_recall",
            "memory_route": "hybrid",
            "retrieval_mode": "graph-led",
            "recall_confidence": 0.8,
            "graph_confidence": 0.6,
            "trace": [
                {
                    "node_id": "raw-node-1",
                    "hybrid_score": 1.2,
                    "memory_class": "episodic_memory",
                    "source": "hybrid",
                    "text": "private memory text",
                }
            ],
            "vector_hits": [
                {
                    "node_id": "raw-node-2",
                    "score": 0.7,
                    "memory_class": "durable_memory",
                    "text": "private vector text",
                }
            ],
        }


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


def _start_server_with_service(service, *, token: str = "") -> tuple[_ReplyHTTPServer, str]:
    server = _ReplyHTTPServer(
        ("127.0.0.1", 0),
        _handler_factory(),
        service=service,
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


def test_reply_api_backfill_vector_memory_keeps_json_null_unscoped() -> None:
    service = _FakeReplyService()
    server, base_url = _start_server_with_service(service, token="")
    try:
        status, payload = _open_json(
            f"{base_url}/backfill-vector-memory",
            data={"channel": None, "thread_key": None, "chat_name": None},
        )
        assert status == HTTPStatus.OK
        assert payload == {"status": "ok", "channel": None, "thread_key": None, "chat_name": None}
        assert service.backfill_calls == [{"channel": None, "thread_key": None, "chat_name": None}]
    finally:
        server.shutdown()
        server.server_close()


def test_reply_api_records_redacted_biomimetic_telemetry(tmp_path: Path) -> None:
    server, base_url = _start_server_with_service(_TelemetryReplyService(tmp_path), token="")
    try:
        status, payload = _open_json(
            f"{base_url}/reply",
            data={"text": "private input", "chat_name": "ResearchThread", "thread_key": "holo_cli:main", "channel": "holo_cli"},
        )
        assert status == HTTPStatus.OK
        assert payload["biomimetic_telemetry"]["frame_id"].startswith("bf-")
        telemetry_path = tmp_path / ".holo_runtime" / "biomimetic_frames.jsonl"
        text = telemetry_path.read_text(encoding="utf-8")
        assert "private input" not in text
        frame = json.loads(text.strip())
        assert frame["event_type"] == "reply"
        assert frame["context"]["thread_key"] == "holo_cli:main"
    finally:
        server.shutdown()
        server.server_close()


def test_reply_api_records_redacted_hybrid_recall_telemetry(tmp_path: Path) -> None:
    server, base_url = _start_server_with_service(_TelemetryDiagnosticService(tmp_path), token="")
    try:
        status, payload = _open_json(
            f"{base_url}/trace-hybrid-recall?query=private+diagnostic+query&thread_key=holo_cli:main&chat_name=Main&channel=holo_cli"
        )
        assert status == HTTPStatus.OK
        assert payload["biomimetic_telemetry"]["frame_id"].startswith("bf-")
        telemetry_path = tmp_path / ".holo_runtime" / "biomimetic_frames.jsonl"
        text = telemetry_path.read_text(encoding="utf-8")
        assert "private diagnostic query" not in text
        assert "private memory text" not in text
        assert "raw-node-1" not in text
        frame = json.loads(text.strip())
        assert frame["event_type"] == "hybrid_recall_trace"
        assert frame["context"]["thread_key"] == "holo_cli:main"
        assert frame["recall_trajectory"]["candidate_count"] == 2
    finally:
        server.shutdown()
        server.server_close()
