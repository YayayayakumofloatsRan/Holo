from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from holo_host.vector_memory import VectorMemory


class _FallbackClient:
    def __init__(self) -> None:
        self.filters: list[str] = []

    def search(self, *, collection_name: str, data: list[list[float]], filter: str, limit: int, output_fields: list[str]) -> list[list[dict[str, Any]]]:
        self.filters.append(filter)
        if 'thread_key == "missing-thread"' in filter:
            return [[]]
        return [
            [
                {
                    "id": "node-global",
                    "distance": 0.82,
                    "entity": {
                        "channel": "wechat",
                        "thread_key": "wechat:TestUser",
                        "chat_name": "TestUser",
                        "memory_class": "episodic_memory",
                        "source_store": "archive",
                        "source_id": "archive-1",
                        "text": "old Holo RAG memory anchor",
                        "importance": 0.9,
                        "confidence": 0.8,
                    },
                }
            ]
        ]


class _FallbackVectorMemory(VectorMemory):
    def __init__(self, repo_root: Path, client: _FallbackClient) -> None:
        super().__init__(repo_root, backend="milvus")
        self._client = client
        self._client_ready = True
        self._available = True

    def _client_instance(self) -> Any:
        return self._client


class VectorMemoryTests(unittest.TestCase):
    def test_search_relaxes_scope_when_exact_thread_has_no_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _FallbackClient()
            vector = _FallbackVectorMemory(Path(tmp), client)

            result = vector.search(
                "Holo RAG memory",
                channel="wechat",
                thread_key="missing-thread",
                chat_name="Missing Thread",
                limit=4,
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["hits"])
            self.assertGreaterEqual(len(client.filters), 2)
            self.assertIn('thread_key == "missing-thread"', client.filters[0])
            self.assertEqual(client.filters[1], 'channel == "wechat"')
            self.assertEqual(result["scope"], "channel")


if __name__ == "__main__":
    unittest.main()
