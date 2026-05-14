import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


class _FakeStage59Runner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> dict:
        self.calls.append(dict(kwargs))
        execute = bool(kwargs.get("execute", False))
        model = str(kwargs.get("model", "") or "")
        lane = str(kwargs.get("lane", "") or "")
        turns = int(kwargs.get("turns", 0) or 0)
        runs = int(kwargs.get("runs", 0) or 0)
        collected_turns = runs * turns if execute else 0
        observed_tokens = collected_turns * 900
        is_pro = "pro" in model.lower()
        score = 0.88 if is_pro else 0.74
        cache_hits = collected_turns * (360 if is_pro else 180)
        cache_misses = max(0, observed_tokens - cache_hits)
        return {
            "ok": True,
            "stage": "stage59-provider-longform-trace",
            "status": "complete" if execute else "dry_run",
            "provider_provenance": {
                "requested_provider_hint": str(kwargs.get("provider_hint", "") or ""),
                "requested_model": model,
                "requested_lane": lane,
                "actual_providers": ["deepseek"] if execute else [],
                "actual_models": [model] if execute else [],
                "journal_path": str(kwargs.get("checkpoint_path", "") or ""),
                "state_isolation": {
                    "mode": str(kwargs.get("state_isolation", "") or ""),
                    "state_root": str(kwargs.get("state_root", "") or ""),
                },
            },
            "provider_trace_set": {
                "real_provider_trace": execute,
                "planned_run_count": runs,
                "planned_turns_per_run": turns,
                "planned_total_turns": runs * turns,
                "collected_run_count": runs if execute else 0,
                "collected_turn_count": collected_turns,
                "resumed_turn_count": 0,
                "stage57_trace_run_count": runs if execute else 0,
                "new_thread_per_run": True,
            },
            "budget_guard": {
                "max_total_tokens": int(kwargs.get("max_total_tokens", 0) or 0),
                "observed_total_tokens": observed_tokens,
                "remaining_tokens": max(
                    0, int(kwargs.get("max_total_tokens", 0) or 0) - observed_tokens
                ),
                "stopped_reason": "completed" if execute else "dry_run_not_executed",
                "budget_exhausted": False,
            },
            "generated_runs": [
                {
                    "run_id": f"{model}-run",
                    "status": "pass",
                    "turn_count": collected_turns,
                    "overall_score": score,
                    "total_tokens": observed_tokens,
                    "prompt_cache_hit_tokens": cache_hits,
                    "prompt_cache_miss_tokens": cache_misses,
                }
            ]
            if execute
            else [],
            "stage57_calibration": {
                "trace_set": {"total_points": collected_turns, "run_count": runs},
                "predictive_probe": {
                    "geometry_score_correlation": 0.41 if is_pro else 0.18
                },
            },
            "provider_evidence_gate": {
                "real_provider_trace": execute,
                "stage57_calibration_ready": execute,
                "trace_depth_sufficient": execute and collected_turns >= 4,
                "predictive_gate_passed": execute and is_pro,
                "do_not_claim_real_manifold": not (execute and is_pro),
                "reason": "fake",
            },
            "scorecard": {"overall_score": score, "passed": score >= 0.8},
        }


def _fake_stage59_artifact_writer(report: dict, output_path: str | Path) -> dict:
    html_path = Path(output_path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<html>stage59</html>", encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_provider_trace.png")
    png_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return {"html": html_path, "json": json_path, "provider_trace_png": png_path}


class Stage60TraceCampaignTests(unittest.TestCase):
    def test_default_campaign_models_are_pro_first_for_capability_validation(
        self,
    ) -> None:
        from holo_host.consciousness_trace_campaign import run_provider_trace_campaign

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "campaign"
            runner = _FakeStage59Runner()
            report = run_provider_trace_campaign(
                execute=False,
                output_root=output_root,
                campaign_id="stage60-defaults",
                models=None,
                runs_per_model=1,
                turns=2,
                max_total_tokens_per_cell=4000,
                trace_runner=runner,
                artifact_writer=_fake_stage59_artifact_writer,
            )

        self.assertEqual(
            report["campaign_plan"]["models"],
            ["deepseek-v4-pro", "deepseek-v4-flash"],
        )
        self.assertEqual(
            [call["model"] for call in runner.calls],
            ["deepseek-v4-pro", "deepseek-v4-flash"],
        )
        self.assertEqual(
            [call["lane"] for call in runner.calls],
            ["kernel_xhigh", "micro_fast"],
        )

    def test_dry_run_builds_campaign_manifest_without_provider_execution(self) -> None:
        from holo_host.consciousness_trace_campaign import run_provider_trace_campaign

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "campaign"
            runner = _FakeStage59Runner()
            report = run_provider_trace_campaign(
                execute=False,
                output_root=output_root,
                campaign_id="stage60-test",
                models=["deepseek-v4-flash", "deepseek-v4-pro"],
                runs_per_model=2,
                turns=8,
                max_total_tokens_per_cell=12000,
                trace_runner=runner,
                artifact_writer=_fake_stage59_artifact_writer,
            )
            manifest = json.loads(
                (output_root / "campaign_manifest.json").read_text(encoding="utf-8")
            )
            events = (output_root / "campaign_events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(report["stage"], "stage60-longrun-provider-campaign")
        self.assertEqual(report["status"], "dry_run")
        self.assertEqual(len(runner.calls), 2)
        self.assertTrue(all(not call["execute"] for call in runner.calls))
        self.assertEqual(report["aggregate"]["planned_cell_count"], 2)
        self.assertEqual(report["aggregate"]["planned_total_turns"], 32)
        self.assertEqual(report["aggregate"]["real_provider_cell_count"], 0)
        self.assertTrue(report["breakthrough_gate"]["do_not_claim_major_breakthrough"])
        self.assertIn("dry_run_has_no_provider_evidence", report["breakthrough_gate"]["reasons"])
        self.assertEqual(manifest["campaign_id"], "stage60-test")
        self.assertGreaterEqual(len(events), 4)

    def test_execute_campaign_passes_resume_and_unique_cell_paths(self) -> None:
        from holo_host.consciousness_trace_campaign import run_provider_trace_campaign

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "campaign"
            runner = _FakeStage59Runner()
            report = run_provider_trace_campaign(
                execute=True,
                output_root=output_root,
                campaign_id="stage60-exec",
                models=["deepseek-v4-flash", "deepseek-v4-pro"],
                runs_per_model=1,
                turns=5,
                max_total_tokens_per_cell=9000,
                resume=True,
                trace_runner=runner,
                artifact_writer=_fake_stage59_artifact_writer,
            )

        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(runner.calls), 2)
        self.assertTrue(all(call["resume"] for call in runner.calls))
        self.assertTrue(all(call["checkpoint_path"] for call in runner.calls))
        self.assertEqual(
            len({str(call["checkpoint_path"]) for call in runner.calls}), 2
        )
        self.assertEqual(
            len({str(call["thread_key_prefix"]) for call in runner.calls}), 2
        )
        self.assertEqual(report["aggregate"]["real_provider_cell_count"], 2)
        self.assertEqual(report["aggregate"]["collected_turn_count"], 10)
        self.assertEqual(report["aggregate"]["observed_total_tokens"], 9000)
        self.assertEqual(report["ranking"]["top_model"], "deepseek-v4-pro")
        self.assertEqual(report["ranking"]["top_score"], 0.88)
        self.assertTrue(report["breakthrough_gate"]["do_not_claim_major_breakthrough"])
        self.assertIn("trace_depth_below_breakthrough_floor", report["breakthrough_gate"]["reasons"])

    def test_writes_campaign_html_json_and_png_artifacts(self) -> None:
        from holo_host.consciousness_trace_campaign import (
            run_provider_trace_campaign,
            write_provider_trace_campaign_artifacts,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "campaign"
            report = run_provider_trace_campaign(
                execute=True,
                output_root=output_root,
                campaign_id="stage60-artifacts",
                models=["deepseek-v4-flash", "deepseek-v4-pro"],
                runs_per_model=1,
                turns=4,
                trace_runner=_FakeStage59Runner(),
                artifact_writer=_fake_stage59_artifact_writer,
            )
            output_path = output_root / "campaign.html"
            artifacts = write_provider_trace_campaign_artifacts(report, output_path)
            payload = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["campaign_png"].read_bytes()[:8]
            html = artifacts["html"].read_text(encoding="utf-8")

        self.assertEqual(payload["stage"], "stage60-longrun-provider-campaign")
        self.assertIn("deepseek-v4-pro", html)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_dry_run_writes_campaign_artifacts_without_provider_calls(self) -> None:
        from holo_host.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                f"""
[runtime]
state_dir = "{(root / ".holo_runtime").as_posix()}"
db_path = "{(root / ".holo_runtime" / "holo_host.sqlite3").as_posix()}"
log_dir = "{(root / ".holo_runtime" / "logs").as_posix()}"
api_port = 65516
processor_backend = "deepseek"
""".strip(),
                encoding="utf-8",
            )
            output_root = root / "artifacts" / "stage60" / "cli"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "run-consciousness-trace-campaign",
                        "--campaign-id",
                        "stage60-cli",
                        "--runs-per-model",
                        "1",
                        "--turns",
                        "2",
                        "--max-total-tokens-per-cell",
                        "4000",
                        "--output-root",
                        str(output_root),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["campaign_png_path"]).read_bytes()[:8]
            campaign_json = json.loads(
                Path(payload["campaign_json_path"]).read_text(encoding="utf-8")
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(payload["campaign_id"], "stage60-cli")
        self.assertEqual(payload["observatory"]["planned_cell_count"], 2)
        self.assertEqual(payload["observatory"]["real_provider_cell_count"], 0)
        self.assertTrue(payload["observatory"]["do_not_claim_major_breakthrough"])
        self.assertEqual(
            campaign_json["campaign_plan"]["models"],
            ["deepseek-v4-pro", "deepseek-v4-flash"],
        )
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")
