from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from holo_host.cli import (
    _evaluate_stage16_acceptance,
    _stage16_helper_path_contract,
    _stage16_text_integrity_report,
    _stage16_wsl_fallback_contract,
)


class Stage16ReleaseHardeningTests(unittest.TestCase):
    def test_helper_path_and_wsl_fallback_contracts_are_directional(self) -> None:
        self.assertTrue(_stage16_helper_path_contract()["ok"])
        self.assertTrue(_stage16_wsl_fallback_contract()["ok"])

    def test_policy_and_autobiographical_sources_are_text_clean(self) -> None:
        report = _stage16_text_integrity_report()
        self.assertTrue(report["policy_defaults_ok"])
        self.assertTrue(report["source_files_ok"])

    def test_stage16_acceptance_payload_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = Path(tmpdir) / "summary.json"
            summary.write_text("{}", encoding="utf-8")
            stage12_report = {
                "status": "pass",
                "checks": {"action_market_first_preserved": True},
            }
            stage14_report = {
                "status": "pass",
                "aggregate_metrics": {"risk_mae": 0.1182},
                "artifacts": {"summary_json": str(summary)},
            }
            completed = types.SimpleNamespace(returncode=0, stdout="197 passed", stderr="")
            with mock.patch("holo_host.cli.subprocess.run", return_value=completed):
                report = _evaluate_stage16_acceptance(
                    config_path=str(Path(__file__).resolve().parents[1] / ".holo_host.example.toml"),
                    run_pytest=True,
                    stage12_report=stage12_report,
                    stage14_report=stage14_report,
                )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(bool(value) for value in report["checks"].values()))
        self.assertIn("shadow_launch", report)


if __name__ == "__main__":
    unittest.main()
