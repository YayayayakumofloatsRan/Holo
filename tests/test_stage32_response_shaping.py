from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_agent import BionicKernel
from holo_host.cli_parts.bionic import accept_stage32_payload
from holo_host.config import load_config


class _ShapingMemory:
    def sidecar_packet(self, query, *, context=None):
        return {
            "tier": "fast",
            "memory_route": "active_thread",
            "continuity_summary": "We are tightening the bionic workflow after a debt burn-down.",
            "situational_field": {
                "modalities": ["text", "scene"],
                "grounding_order": ["query", "continuity_summary", "open_questions"],
                "open_questions": ["which technical debt should be closed first?"],
                "history_reliance": "low",
                "inquiry_style": "grounded_continuation",
            },
            "stage28": {"situational_field_visible": True, "hard_gate_preserved": True},
            "action_market": [
                {
                    "action_type": "reply_once",
                    "score": 0.82,
                    "reason": "answer directly without reopening history",
                    "why_now": "the user asked for continued implementation",
                },
                {"action_type": "silence", "score": 0.05, "reason": "not enough silence pressure"},
            ],
        }


class Stage32ResponseShapingTests(unittest.TestCase):
    def test_deterministic_fallback_uses_context_without_fixed_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            kernel = BionicKernel(config=config, memory=_ShapingMemory(), runner=None)
            result = kernel.run_turn(
                query="继续，把技术债清掉",
                thread_key="cli:shape",
                chat_name="Shape",
                channel="cli",
                record=False,
            )

        capsule = result["capsule"]
        text = capsule["generation"]["text"]
        self.assertEqual(capsule["generation"]["mode"], "deterministic_fallback")
        self.assertNotIn("I read this as a bounded Holo turn:", text)
        self.assertNotIn("Stage29 bionic capsule reply:", text)
        self.assertIn("技术债", text)
        self.assertIn("answer directly", text)
        self.assertEqual(capsule["metrics"]["template_pressure_score"], 0.0)
        self.assertGreater(capsule["metrics"]["context_shaping_score"], 0.0)

    def test_fallback_reply_varies_when_open_question_is_absent(self) -> None:
        class _NoQuestionMemory(_ShapingMemory):
            def sidecar_packet(self, query, *, context=None):
                payload = super().sidecar_packet(query, context=context)
                payload["situational_field"]["open_questions"] = []
                return payload

        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            kernel = BionicKernel(config=config, memory=_NoQuestionMemory(), runner=None)
            result = kernel.run_turn(
                query="continue implementation",
                thread_key="cli:shape2",
                chat_name="Shape",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"]
        self.assertIn("I would continue with continue implementation", text)
        self.assertNotIn("Next:", text)
        self.assertNotIn("which technical debt should be closed first?", text)

    def test_accept_stage32_checks_response_shaping_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "stage32.toml"
            config_path.write_text(
                """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
""".strip(),
                encoding="utf-8",
            )
            payload, _transport = accept_stage32_payload(
                str(config_path),
                thread_key="cli:stage32",
                chat_name="Stage32",
                channel="cli",
            )

        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["checks"]["stage31_gate_passed"])
        self.assertTrue(payload["checks"]["fixed_template_removed"])
        self.assertTrue(payload["checks"]["context_shaping_metric_visible"])


if __name__ == "__main__":
    unittest.main()
