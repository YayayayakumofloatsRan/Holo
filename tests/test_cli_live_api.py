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


if __name__ == "__main__":
    unittest.main()
