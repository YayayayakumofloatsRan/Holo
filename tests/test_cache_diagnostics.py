from __future__ import annotations

import unittest
from types import SimpleNamespace

from holo_host.operator_bus import build_engineering_snapshot, build_homeostasis_state


class _FakeRunner:
    def provider_status(self) -> dict:
        return {
            "active_backend_alias": "deepseek",
            "providers": {
                "deepseek": {"available": True},
                "codex_cli": {"available": True},
            },
            "lanes": {
                "subject_main": {"backup_provider": "codex_cli"},
                "kernel_xhigh": {"backup_provider": "codex_cli"},
                "micro_fast": {"backup_provider": "codex_cli"},
            },
        }

    def routing_table(self) -> dict:
        return {
            "reply": {},
            "recall_reconstruct": {},
            "initiative_probe": {},
            "deep_simulation": {},
            "self_model_observe": {},
            "operator_plan": {},
        }


class _FakeStore:
    def list_processor_usage(self, *, limit: int = 40) -> list[dict]:
        return [
            {
                "task_type": "reply",
                "total_tokens": 10,
                "estimated": 0,
            }
        ]


class _FakeGraph:
    def __init__(self, self_model: dict | None = None):
        self._self_model = dict(self_model or {})

    def operator_status(self) -> dict:
        return {"pending_count": 0}

    def brain_state(self) -> dict:
        return {"metadata": {"operator_planning_state": {}}}

    def self_model_state(self) -> dict:
        return dict(self._self_model)


class _FakeMemory:
    def __init__(self, cache: dict, self_model: dict | None = None):
        self._cache = dict(cache)
        self.graph = _FakeGraph(self_model)

    def brain_status(self) -> dict:
        return {"mode": "full_brain", "cache": dict(self._cache)}


def _config() -> SimpleNamespace:
    lane = SimpleNamespace(primary_provider="deepseek")
    return SimpleNamespace(
        runtime=SimpleNamespace(processor_backend="deepseek"),
        memory=SimpleNamespace(brain_mode_default="full_brain"),
        processor_fabric=SimpleNamespace(
            provider_backends={
                "subject_main": lane,
                "kernel_xhigh": lane,
                "micro_fast": lane,
            }
        ),
    )


class CacheDiagnosticsTests(unittest.TestCase):
    def test_zero_sample_packet_cache_is_not_reported_as_weak_reuse(self) -> None:
        snapshot = build_engineering_snapshot(
            memory=_FakeMemory({"entries": 0, "hits": 0, "misses": 0, "hit_ratio": 0.0}),
            store=_FakeStore(),
            config=_config(),
            runner=_FakeRunner(),
        )

        self.assertNotIn("cache_reuse_weak", snapshot["active_deficits"])
        self.assertEqual(snapshot["cache_state"]["sample_count"], 0)
        self.assertFalse(snapshot["cache_state"]["observation_sufficient"])

    def test_low_reuse_after_sample_floor_is_reported_as_weak(self) -> None:
        snapshot = build_engineering_snapshot(
            memory=_FakeMemory({"entries": 1, "hits": 0, "misses": 6, "hit_ratio": 0.0}),
            store=_FakeStore(),
            config=_config(),
            runner=_FakeRunner(),
        )

        self.assertIn("cache_reuse_weak", snapshot["active_deficits"])
        self.assertEqual(snapshot["cache_state"]["sample_count"], 6)
        self.assertTrue(snapshot["cache_state"]["observation_sufficient"])

    def test_homeostasis_rebases_stale_cache_deficits_on_live_cache_stats(self) -> None:
        stale_self_model = {
            "identity_continuity": 0.87,
            "homeostasis_targets": {},
            "active_deficits": ["stiffness_drift", "cache_coldness", "cache_reuse_weak"],
            "metadata": {
                "engineering_snapshot": {
                    "cache_state": {"entries": 0, "hit_ratio": 0.0, "reuse_pressure": 0.696},
                    "budget_pressure": 0.2,
                }
            },
        }
        memory = _FakeMemory({"entries": 2, "hits": 3, "misses": 4, "hit_ratio": 0.4286}, stale_self_model)

        homeostasis = build_homeostasis_state(memory=memory, config=_config(), self_model=stale_self_model)

        self.assertNotIn("cache_coldness", homeostasis["active_deficits"])
        self.assertNotIn("cache_reuse_weak", homeostasis["active_deficits"])
        self.assertEqual(homeostasis["cache_state"]["hit_ratio"], 0.4286)
        self.assertTrue(homeostasis["cache_state"]["observation_sufficient"])


if __name__ == "__main__":
    unittest.main()
