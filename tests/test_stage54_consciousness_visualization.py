from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.bionic_boundary_stress import DEFAULT_STAGE46_SUITE, STAGE46_NAME
from holo_host.config import load_config
from holo_host.store import QueueStore


def _sample_stage46_run() -> dict:
    return {
        "stage": STAGE46_NAME,
        "suite": DEFAULT_STAGE46_SUITE,
        "status": "pass",
        "run_id": "stage54-sample",
        "turns": [
            {
                "turn_id": "affective_pressure",
                "latency_ms": 1200,
                "processor_usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 60,
                    "total_tokens": 1060,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 1000,
                },
                "processor_debug": {
                    "prompt_partition": {
                        "provider_cache_prefix_tokens": 520,
                        "provider_cache_dynamic_tokens": 360,
                    },
                    "bionic_memory_schedule": {
                        "salience_score": 0.25,
                        "recall_budget": 2,
                        "dynamic_context_line_count": 6,
                        "dynamic_fusion_saved_line_count": 8,
                    },
                    "bionic_memory_lifecycle": {"consolidation_priority": 0.3},
                    "bionic_consciousness_flow": {
                        "dominant_phase": "sensory_edge",
                        "phase_count": 6,
                        "user_visible": False,
                    },
                },
            },
            {
                "turn_id": "symbol_correction",
                "latency_ms": 900,
                "processor_usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 40,
                    "total_tokens": 1040,
                    "prompt_cache_hit_tokens": 700,
                    "prompt_cache_miss_tokens": 300,
                },
                "processor_debug": {
                    "prompt_partition": {
                        "provider_cache_prefix_tokens": 520,
                        "provider_cache_dynamic_tokens": 390,
                    },
                    "bionic_memory_schedule": {
                        "salience_score": 0.82,
                        "recall_budget": 4,
                        "dynamic_context_line_count": 9,
                        "dynamic_fusion_saved_line_count": 9,
                    },
                    "bionic_memory_lifecycle": {"consolidation_priority": 0.72},
                    "bionic_consciousness_flow": {
                        "dominant_phase": "memory_reactivation",
                        "phase_count": 6,
                        "user_visible": False,
                    },
                },
            },
        ],
        "scorecard": {"overall_score": 0.96, "passed": True},
    }


class Stage54ConsciousnessVisualizationTests(unittest.TestCase):
    def test_builds_compute_heatmap_and_attention_trajectory_from_stage46_trace(self) -> None:
        from holo_host.consciousness_visualization import build_consciousness_visualization

        report = build_consciousness_visualization(_sample_stage46_run())

        self.assertEqual(report["stage"], "stage54-consciousness-flow-visualization")
        self.assertEqual(report["source_stage"], STAGE46_NAME)
        self.assertEqual(report["turn_count"], 2)
        self.assertGreater(report["summary"]["internal_output_ratio"], 10.0)
        self.assertGreater(report["summary"]["internal_token_share"], 0.9)
        self.assertIn("prompt_cache_miss_tokens", report["heatmap"]["axes"])
        self.assertIn("memory_salience", report["heatmap"]["axes"])
        self.assertEqual(len(report["heatmap"]["rows"]), 2)
        self.assertEqual(len(report["trajectory"]["points"]), 2)
        self.assertEqual(report["trajectory"]["points"][1]["dominant_phase"], "memory_reactivation")
        self.assertGreater(report["trajectory"]["points"][1]["movement"], 0.0)
        self.assertTrue(report["boundary"]["visualization_only"])
        self.assertFalse(report["boundary"]["transport_decision_authority"])

    def test_builds_high_dimensional_compute_manifold_and_attention_blocks(self) -> None:
        from holo_host.consciousness_visualization import build_consciousness_visualization

        report = build_consciousness_visualization(_sample_stage46_run())

        manifold = report["compute_manifold"]
        self.assertEqual(manifold["projection"], "deterministic_stage54_compute_manifold_v1")
        self.assertEqual(manifold["axes"], report["heatmap"]["axes"])
        self.assertEqual(len(manifold["points"]), 2)
        self.assertEqual(len(manifold["edges"]), 1)
        self.assertEqual(len(manifold["points"][0]["normalized_vector"]), len(report["heatmap"]["axes"]))
        self.assertGreater(manifold["points"][0]["raw_norm"], 0.0)
        self.assertGreater(manifold["edges"][0]["delta_norm"], 0.0)
        self.assertLessEqual(manifold["edges"][0]["cosine_similarity"], 1.0)

        attention_blocks = report["attention_blocks"]
        self.assertEqual(len(attention_blocks), 2)
        block_names = {block["name"] for block in attention_blocks[0]["blocks"]}
        self.assertIn("cache_reuse", block_names)
        self.assertIn("dynamic_context", block_names)
        self.assertIn("memory_control", block_names)
        self.assertIn("output_surface", block_names)
        self.assertEqual(attention_blocks[0]["dominant_block"], "dynamic_context")
        self.assertAlmostEqual(sum(block["share"] for block in attention_blocks[0]["blocks"]), 1.0, places=4)

    def test_renders_html_with_svg_heatmap_trajectory_and_token_bars(self) -> None:
        from holo_host.consciousness_visualization import (
            build_consciousness_visualization,
            render_consciousness_visualization_html,
        )

        report = build_consciousness_visualization(_sample_stage46_run())
        html = render_consciousness_visualization_html(report)

        self.assertIn("<svg", html)
        self.assertIn("Compute Distribution Heatmap", html)
        self.assertIn("Attention Vector Trajectory", html)
        self.assertIn("High-Dimensional Compute Manifold", html)
        self.assertIn("Attention Block Allocation", html)
        self.assertIn("Internal Tokens vs Output", html)
        self.assertIn("affective_pressure", html)
        self.assertIn("symbol_correction", html)

    def test_writes_png_heatmap_and_dashboard_artifacts(self) -> None:
        from holo_host.consciousness_visualization import (
            build_consciousness_visualization,
            write_consciousness_visualization_artifacts,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "stage54.html"
            artifacts = write_consciousness_visualization_artifacts(
                build_consciousness_visualization(_sample_stage46_run()),
                output_path,
            )

            heatmap_png = artifacts["heatmap_png"]
            dashboard_png = artifacts["dashboard_png"]

            self.assertTrue(heatmap_png.exists())
            self.assertTrue(dashboard_png.exists())
            self.assertEqual(heatmap_png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(dashboard_png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertGreater(heatmap_png.stat().st_size, 1000)
            self.assertGreater(dashboard_png.stat().st_size, 1000)

    def test_cli_renders_latest_stage46_visualization_artifacts(self) -> None:
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
api_port = 65510
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path=str(config_path), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                store.record_agent_eval_run(
                    stage=STAGE46_NAME,
                    suite=DEFAULT_STAGE46_SUITE,
                    status="pass",
                    scorecard={"overall_score": 0.96, "passed": True},
                    run_payload=_sample_stage46_run(),
                )
            finally:
                store.close()

            output_path = root / "artifacts" / "stage54" / "map.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(["--config", str(config_path), "render-consciousness-map", "--output", str(output_path)])

            payload = json.loads(stdout.getvalue())
            html = output_path.read_text(encoding="utf-8")
            json_path = output_path.with_suffix(".json")
            report_json = json.loads(json_path.read_text(encoding="utf-8"))
            heatmap_png = output_path.with_name("map_heatmap.png")
            dashboard_png = output_path.with_name("map_dashboard.png")
            heatmap_png_header = heatmap_png.read_bytes()[:8]
            dashboard_png_header = dashboard_png.read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["output_path"], str(output_path))
        self.assertEqual(payload["json_path"], str(json_path))
        self.assertEqual(payload["heatmap_png_path"], str(heatmap_png))
        self.assertEqual(payload["dashboard_png_path"], str(dashboard_png))
        self.assertEqual(payload["visualization"]["turn_count"], 2)
        self.assertEqual(payload["visualization"]["compute_manifold_projection"], "deterministic_stage54_compute_manifold_v1")
        self.assertIn("Attention Vector Trajectory", html)
        self.assertEqual(report_json["stage"], "stage54-consciousness-flow-visualization")
        self.assertEqual(len(report_json["compute_manifold"]["edges"]), 1)
        self.assertEqual(heatmap_png_header, b"\x89PNG\r\n\x1a\n")
        self.assertEqual(dashboard_png_header, b"\x89PNG\r\n\x1a\n")
