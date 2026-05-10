from __future__ import annotations

import unittest
from pathlib import Path

from holo_host.bionic_brain import (
    resolve_deepseek_v4_tool_contract,
    select_deepseek_v4_profile,
    stage40_deepseek_v4_status,
)
from holo_host.codex_runner import CodexRunner
from holo_host.config import load_config


class Stage40DeepSeekV4ProfileTests(unittest.TestCase):
    def test_lane_selection_uses_flash_for_fast_work_and_pro_for_planning_review(self) -> None:
        classify = select_deepseek_v4_profile("classify")
        planning = select_deepseek_v4_profile("planning")
        review = select_deepseek_v4_profile("review")

        self.assertEqual(classify.profile_id, "deepseek_v4_flash")
        self.assertEqual(classify.default_budget, "flash_8k")
        self.assertEqual(planning.profile_id, "deepseek_v4_pro")
        self.assertEqual(review.profile_id, "deepseek_v4_pro")
        self.assertTrue(planning.thinking_mode)
        self.assertFalse(classify.thinking_mode)

    def test_thinking_tool_call_contract_requires_reasoning_content_or_downgrades(self) -> None:
        profile = select_deepseek_v4_profile("planning")
        downgraded = resolve_deepseek_v4_tool_contract(
            profile,
            tool_calls_requested=True,
            provider_preserves_reasoning_content=False,
        )
        supported = resolve_deepseek_v4_tool_contract(
            profile,
            tool_calls_requested=True,
            provider_preserves_reasoning_content=True,
        )

        self.assertFalse(downgraded["thinking_mode_enabled"])
        self.assertEqual(downgraded["tool_call_mode"], "external_non_thinking_loop")
        self.assertIn("reasoning_content_not_preserved", downgraded["downgraded_reason"])
        self.assertTrue(supported["thinking_mode_enabled"])
        self.assertEqual(supported["tool_call_mode"], "openai_chat_completions")

    def test_provider_status_exposes_stage40_v4_harness_readiness(self) -> None:
        config = load_config(repo_root=Path(__file__).resolve().parents[1])
        status = CodexRunner(config).provider_status()
        harness_status = stage40_deepseek_v4_status(status)

        self.assertTrue(harness_status["profiles"]["deepseek_v4_pro"]["context_window_class"] in {"128k", "1m"})
        self.assertEqual(harness_status["profiles"]["deepseek_v4_flash"]["default_budget"], "flash_8k")
        self.assertIn("cache_policy", harness_status["profiles"]["deepseek_v4_pro"])
        self.assertIn("deepseek", status["providers"])


if __name__ == "__main__":
    unittest.main()
