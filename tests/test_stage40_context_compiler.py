from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_brain import ContextCompiler


class Stage40ContextCompilerTests(unittest.TestCase):
    def _repo_root(self) -> tempfile.TemporaryDirectory[str]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "docs").mkdir(parents=True)
        (root / ".agent").mkdir(parents=True)
        (root / ".holo_runtime").mkdir(parents=True)
        (root / "holo_memory_library" / "memories").mkdir(parents=True)
        (root / "holo_host").mkdir(parents=True)
        (root / "AGENTS.md").write_text("public agent contract", encoding="utf-8")
        (root / "HOLO_HANDOFF.md").write_text("Stage39 complete; Stage40 pending", encoding="utf-8")
        (root / ".agent" / "PLANS.md").write_text("Stage40 bionic brain OS", encoding="utf-8")
        (root / "docs" / "ROADMAP_REGISTRY.md").write_text("Stage40 planned", encoding="utf-8")
        (root / "holo_host" / "sample.py").write_text("def answer():\n    return 'ok'\n", encoding="utf-8")
        (root / ".holo_runtime" / "secret.txt").write_text("runtime private memory", encoding="utf-8")
        (root / "holo_memory_library" / "memories" / "private.jsonl").write_text(
            '{"secret":"memory"}\n',
            encoding="utf-8",
        )
        return tmp

    def test_bundle_records_hashes_cache_key_and_excludes_private_sources(self) -> None:
        with self._repo_root() as tmpdir:
            root = Path(tmpdir)
            compiler = ContextCompiler(repo_root=root)
            bundle = compiler.compile(
                goal="build stage40 harness",
                model_profile="deepseek_v4_pro",
                budget="pro_128k",
                selected_files=[root / "holo_host" / "sample.py", root / ".holo_runtime" / "secret.txt"],
                git_diff="diff --git a/x b/x\n+token = 'redaction-fixture-token-1234567890abcdef'",
                test_output="pytest failed once",
                runtime_diagnostics={"provider": "deepseek", "cache": {"misses": 2}},
                mind_packet_summary={"stage": "stage39"},
                visual_summary={"image": "not provided"},
            )
            repeat = compiler.compile(
                goal="build stage40 harness",
                model_profile="deepseek_v4_pro",
                budget="pro_128k",
                selected_files=[root / "holo_host" / "sample.py", root / ".holo_runtime" / "secret.txt"],
                git_diff="diff --git a/x b/x\n+token = 'redaction-fixture-token-1234567890abcdef'",
                test_output="pytest failed once",
                runtime_diagnostics={"provider": "deepseek", "cache": {"misses": 2}},
                mind_packet_summary={"stage": "stage39"},
                visual_summary={"image": "not provided"},
            )

        serialized = json.dumps(bundle, ensure_ascii=False)
        self.assertEqual(bundle["stage"], "stage40-bionic-brain-os-harness")
        self.assertTrue(bundle["bundle_id"].startswith("ctx_"))
        self.assertGreater(bundle["token_estimate"], 0)
        self.assertEqual(bundle["cache_key"], repeat["cache_key"])
        self.assertIn("AGENTS.md", bundle["source_hashes"])
        self.assertIn("holo_host/sample.py", bundle["source_hashes"])
        self.assertIn(".holo_runtime/secret.txt", bundle["excluded_private_sources"])
        self.assertIn("holo_memory_library/memories/private.jsonl", bundle["excluded_private_sources"])
        self.assertNotIn("runtime private memory", serialized)
        self.assertNotIn("redaction-fixture-token-1234567890abcdef", serialized)
        self.assertIn("<redacted-secret>", serialized)

    def test_budget_controls_context_window_class_without_defaulting_to_1m(self) -> None:
        with self._repo_root() as tmpdir:
            compiler = ContextCompiler(repo_root=Path(tmpdir))
            flash = compiler.compile(goal="triage", model_profile="deepseek_v4_flash", budget="flash_8k")
            pro = compiler.compile(goal="review", model_profile="deepseek_v4_pro", budget="pro_128k")
            deep = compiler.compile(goal="whole repo review", model_profile="deepseek_v4_pro", budget="pro_1m")

        self.assertEqual(flash["budget"], "flash_8k")
        self.assertEqual(flash["context_window_class"], "8k")
        self.assertLessEqual(flash["token_estimate"], 8_000)
        self.assertEqual(pro["context_window_class"], "128k")
        self.assertEqual(deep["context_window_class"], "1m")
        self.assertFalse(flash["requires_explicit_deep_run"])
        self.assertFalse(pro["requires_explicit_deep_run"])
        self.assertTrue(deep["requires_explicit_deep_run"])


if __name__ == "__main__":
    unittest.main()
