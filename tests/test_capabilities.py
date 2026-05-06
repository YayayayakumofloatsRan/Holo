import unittest
from unittest import mock

from holo_host.capabilities import CapabilityBroker
from holo_host.config import load_config


class CapabilityBrokerTests(unittest.TestCase):
    def test_external_lookup_is_used_for_explicit_search_turns(self) -> None:
        config = load_config(repo_root="D:/Holo/holo")
        broker = CapabilityBroker(config)
        with mock.patch.object(
            CapabilityBroker,
            "_external_lookup",
            return_value={
                "query": "transcendence movie",
                "status": "ok",
                "results": [
                    {
                        "title": "Transcendence (film)",
                        "url": "https://example.com/transcendence",
                        "snippet": "A science fiction film starring Johnny Depp.",
                    }
                ],
            },
        ) as lookup:
            payload = broker.summarize_turn("帮我查一下 transcendence 这部电影", {})
        self.assertTrue(lookup.called)
        self.assertEqual(payload["tool_requests"][0]["name"], "external_lookup")
        self.assertIn("external lookup", payload["tool_context_lines"][0])

    def test_memory_question_does_not_force_external_lookup(self) -> None:
        config = load_config(repo_root="D:/Holo/holo")
        broker = CapabilityBroker(config)
        with mock.patch.object(CapabilityBroker, "_external_lookup") as lookup:
            payload = broker.summarize_turn("你还记得我们之前聊的电影吗", {})
        self.assertFalse(lookup.called)
        self.assertEqual(payload["tool_requests"], [])


if __name__ == "__main__":
    unittest.main()
