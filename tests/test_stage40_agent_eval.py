from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_brain import BionicBrainHarness, run_stage40_agent_eval
from holo_host.config import load_config
from holo_host.store import QueueStore

from tests.test_stage40_bionic_brain_harness import _ScriptedRunner, _Stage40Memory, _write_stage40_config


class Stage40AgentEvalTests(unittest.TestCase):
    def test_agent_eval_scorecard_is_repeatable_and_operational_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixtures = root / "tests" / "fixtures" / "stage40_agent_eval"
            fixtures.mkdir(parents=True)
            (fixtures / "code_understanding.md").write_text("understand this bounded harness task", encoding="utf-8")
            config = load_config(config_path=str(_write_stage40_config(root)), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            harness = BionicBrainHarness(
                config=config,
                store=store,
                memory=_Stage40Memory(),
                runner=_ScriptedRunner(),
            )

            try:
                first = run_stage40_agent_eval(config=config, store=store, harness=harness, suite="stage40")
                second = run_stage40_agent_eval(config=config, store=store, harness=harness, suite="stage40")
                latest = store.latest_agent_eval_run(stage="stage40-bionic-brain-os-harness", suite="stage40")
            finally:
                store.close()

        self.assertTrue(first["ok"], first)
        self.assertEqual(first["scorecard"], second["scorecard"])
        self.assertEqual(first["scorecard"]["task_success"], 1.0)
        self.assertGreaterEqual(first["scorecard"]["verification_quality"], 0.8)
        self.assertEqual(first["scorecard"]["private_data_leakage"], 0.0)
        self.assertFalse(first["self_memory_mutated"])
        self.assertEqual(latest["suite"], "stage40")
        self.assertEqual(latest["status"], "pass")

    def test_failed_eval_task_reports_explainable_failure(self) -> None:
        class _FailingHarness:
            def run(self, **_kwargs):
                return {
                    "ok": False,
                    "phase_trace": [],
                    "verification": {"completion_allowed": False, "evidence": []},
                    "context_bundle": {"cache_key": "none"},
                    "tool_metrics": {"executed_count": 0},
                    "consolidation_intent": {"self_memory_write": False},
                    "failure_reason": "deliberation_failed",
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(config_path=str(_write_stage40_config(root)), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                result = run_stage40_agent_eval(config=config, store=store, harness=_FailingHarness(), suite="stage40")
            finally:
                store.close()

        self.assertFalse(result["ok"])
        self.assertIn("deliberation_failed", result["failure_reasons"])
        self.assertLess(result["scorecard"]["task_success"], 1.0)


if __name__ == "__main__":
    unittest.main()
