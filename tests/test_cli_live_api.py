from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from holo_host import cli


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class CliLiveApiRequestTests(unittest.TestCase):
    def test_bind_all_host_also_adds_loopback_client_url(self) -> None:
        config = SimpleNamespace(runtime=SimpleNamespace(api_bind_host="0.0.0.0", api_port=8004))

        with mock.patch("holo_host.cli.os.name", "posix"):
            urls = cli._live_api_base_urls(config)

        self.assertEqual(urls[0], "http://127.0.0.1:8004")
        self.assertIn("http://localhost:8004", urls)
        self.assertNotIn("http://0.0.0.0:8004", urls)

    def test_windows_live_request_falls_back_to_standard_wsl_port(self) -> None:
        config = SimpleNamespace(runtime=SimpleNamespace(api_bind_host="127.0.0.1", api_port=8000))
        opened_urls: list[str] = []

        def fake_urlopen(request, timeout):
            del timeout
            opened_urls.append(request.full_url)
            if request.full_url == "http://127.0.0.1:8004/live-readiness":
                return _FakeResponse({"status": "ready"})
            raise cli.URLError("offline")

        with mock.patch("holo_host.cli.load_config", return_value=config), mock.patch(
            "holo_host.cli.os.name", "nt"
        ), mock.patch.dict(
            "holo_host.cli.os.environ",
            {"HOLO_WSL_DISTRO": "", "HOLO_LIVE_API_URL": ""},
            clear=False,
        ), mock.patch(
            "holo_host.cli.urlopen", side_effect=fake_urlopen
        ):
            payload = cli._live_api_request(None, method="GET", path="/live-readiness")

        self.assertEqual(payload, {"status": "ready"})
        self.assertIn("http://127.0.0.1:8000/live-readiness", opened_urls)
        self.assertIn("http://127.0.0.1:8004/live-readiness", opened_urls)

    def test_wsl_live_request_falls_back_to_standard_live_port(self) -> None:
        config = SimpleNamespace(runtime=SimpleNamespace(api_bind_host="127.0.0.1", api_port=8000))
        opened_urls: list[str] = []

        def fake_urlopen(request, timeout):
            del timeout
            opened_urls.append(request.full_url)
            if request.full_url == "http://127.0.0.1:8004/live-readiness":
                return _FakeResponse({"status": "ready"})
            raise cli.URLError("offline")

        with mock.patch("holo_host.cli.load_config", return_value=config), mock.patch(
            "holo_host.cli.os.name", "posix"
        ), mock.patch.dict(
            "holo_host.cli.os.environ",
            {"WSL_DISTRO_NAME": "HoloUbuntu", "HOLO_LIVE_API_URL": ""},
            clear=False,
        ), mock.patch(
            "holo_host.cli.urlopen", side_effect=fake_urlopen
        ):
            payload = cli._live_api_request(None, method="GET", path="/live-readiness")

        self.assertEqual(payload, {"status": "ready"})
        self.assertIn("http://127.0.0.1:8000/live-readiness", opened_urls)
        self.assertIn("http://127.0.0.1:8004/live-readiness", opened_urls)

    def test_live_flow_payload_uses_live_http_before_local_process(self) -> None:
        def fake_live_api_request(config_path, *, method, path, **_kwargs):
            self.assertIsNone(config_path)
            self.assertEqual(method, "GET")
            self.assertEqual(path, "/live-flow")
            return {"status": "healthy"}

        with mock.patch("holo_host.cli._live_api_request", side_effect=fake_live_api_request):
            payload, transport = cli._live_flow_payload(None)

        self.assertEqual(payload, {"status": "healthy"})
        self.assertEqual(transport, "live_http")

    def test_live_request_sends_configured_bearer_token(self) -> None:
        config = SimpleNamespace(
            runtime=SimpleNamespace(
                api_bind_host="127.0.0.1",
                api_port=8004,
                api_bearer_token_env="HOLO_TEST_TOKEN",
            )
        )
        seen_authorization: list[str | None] = []

        def fake_urlopen(request, timeout):
            del timeout
            seen_authorization.append(request.get_header("Authorization"))
            return _FakeResponse({"status": "ready"})

        with mock.patch("holo_host.cli.load_config", return_value=config), mock.patch.dict(
            "holo_host.cli.os.environ",
            {"HOLO_TEST_TOKEN": "secret-token", "HOLO_LIVE_API_URL": ""},
            clear=False,
        ), mock.patch("holo_host.cli.urlopen", side_effect=fake_urlopen):
            payload = cli._live_api_request(None, method="GET", path="/live-readiness")

        self.assertEqual(payload, {"status": "ready"})
        self.assertEqual(seen_authorization, ["Bearer secret-token"])

    def test_live_request_replaces_lone_surrogates_before_utf8_encoding(self) -> None:
        config = SimpleNamespace(
            runtime=SimpleNamespace(
                api_bind_host="127.0.0.1",
                api_port=8004,
                api_bearer_token_env="",
            )
        )
        seen_data: list[bytes | None] = []

        def fake_urlopen(request, timeout):
            del timeout
            seen_data.append(request.data)
            return _FakeResponse({"status": "ok"})

        with mock.patch("holo_host.cli.load_config", return_value=config), mock.patch.dict(
            "holo_host.cli.os.environ",
            {"HOLO_LIVE_API_URL": ""},
            clear=False,
        ), mock.patch("holo_host.cli.urlopen", side_effect=fake_urlopen):
            payload = cli._live_api_request(None, method="POST", path="/reply", payload={"text": "bad\ud800"})

        self.assertEqual(payload, {"status": "ok"})
        self.assertEqual(json.loads(seen_data[0].decode("utf-8"))["text"], "bad?")


if __name__ == "__main__":
    unittest.main()
