from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.bionic_agent import BionicKernel, BionicTurnRequest
from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.models import ProcessorTaskResult
from tests.test_rag_memory import TempMemoryRepo


PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn0rC8AAAAASUVORK5CYII="


class _Stage38ImageRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_task(self, request):
        self.calls.append(request.to_dict())
        if request.task_type == "image_understand":
            payload = {
                "scene_summary": "A screenshot shows a Holo visual-provider diagnostics panel.",
                "objects": ["diagnostics panel", "provider badge", "image lane"],
                "text_ocr": "image_understand: ready",
                "mood_imagery": "engineering verification screenshot",
                "thread_relevance": 0.88,
                "visual_anchors": ["visual-provider diagnostics", "image_understand ready"],
                "spatial_refs": ["center: diagnostics panel"],
                "uncertainty_markers": [],
                "revisit_needed": False,
                "perceptual_density": "medium",
            }
            text = json.dumps(payload, ensure_ascii=False)
            metadata = {
                "provider": "codex_cli",
                "lane": "micro_fast",
                "model": "gpt-5.4-mini",
                "capabilities": {"text": True, "json_output": True, "image_support": True},
                "duration_ms": 12,
            }
        else:
            text = "The visual-memory summary says the screenshot shows the Holo image_understand lane ready."
            metadata = {
                "provider": "deepseek",
                "lane": "subject_main",
                "model": "deepseek-v4-pro",
                "capabilities": {"text": True, "json_output": True, "image_support": False},
            }
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=text,
            returncode=0,
            output_schema=request.output_schema,
            metadata=metadata,
        )


def _write_stage38_config(root: Path) -> Path:
    state_dir = (root / ".holo_runtime").as_posix()
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        f"""
[runtime]
state_dir = "{state_dir}"
db_path = "{state_dir}/holo_host.sqlite3"
log_dir = "{state_dir}/logs"
processor_backend = "deepseek"
api_port = 65503

[autonomy]
stage22_canary_mode = "shadow"

[processor_fabric]
deepseek_api_key_env = "DEEPSEEK_API_KEY"

[provider_backends.subject_main]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-pro"
reasoning_effort = "medium"
max_output_tokens = 512

[provider_backends.micro_fast]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-flash"
reasoning_effort = "low"
max_output_tokens = 256
""".strip(),
        encoding="utf-8",
    )
    return config_path


class Stage38VisualProviderBridgeTests(unittest.TestCase):
    def _image_path(self, root: Path) -> Path:
        path = root / "stage38-visual.png"
        path.write_bytes(base64.b64decode(PNG_1X1))
        return path

    def _bridge(self, temp: TempMemoryRepo, runner: _Stage38ImageRunner) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
            runner=runner,
        )

    def _close_bridge(self, bridge: MemoryBridge) -> None:
        bridge.activation.close()
        bridge.graph.close()

    def test_image_ingest_preserves_real_image_provider_metadata(self) -> None:
        runner = _Stage38ImageRunner()
        with TempMemoryRepo() as temp:
            image_path = self._image_path(temp.repo_root)
            bridge = self._bridge(temp, runner)
            try:
                report = bridge.ingest_image(
                    str(image_path),
                    note="stage38 visual provider bridge",
                    source="unit.stage38.visual",
                    tags=["stage38", "visual"],
                    channel="cli",
                    thread_key="cli:stage38-vision",
                    chat_name="Stage38",
                    sync=True,
                )
                visual = bridge.visual_memory_state(thread_key="cli:stage38-vision", chat_name="Stage38", channel="cli")
            finally:
                self._close_bridge(bridge)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(runner.calls[0]["task_type"], "image_understand")
        self.assertEqual(runner.calls[0]["image_paths"], [str(image_path)])
        self.assertEqual(report["image_understand"]["provider"], "codex_cli")
        self.assertTrue(report["image_understand"]["capabilities"]["image_support"])
        self.assertIn("image_understand ready", visual["visual_anchors"])
        stored_metadata = visual["items"][0]["metadata"]
        self.assertEqual(stored_metadata["image_understand"]["provider"], "codex_cli")
        self.assertTrue(stored_metadata["image_understand"]["capabilities"]["image_support"])

    def test_bionic_cli_uses_visual_memory_summary_without_text_provider_overclaim(self) -> None:
        runner = _Stage38ImageRunner()
        with TempMemoryRepo() as temp:
            image_path = self._image_path(temp.repo_root)
            bridge = self._bridge(temp, runner)
            try:
                ingest = bridge.ingest_image(
                    str(image_path),
                    note="stage38 visual provider bridge",
                    source="unit.stage38.visual",
                    tags=["stage38", "visual"],
                    channel="cli",
                    thread_key="cli:stage38-bionic",
                    chat_name="Stage38",
                    sync=True,
                )
                kernel = BionicKernel(config=load_config(repo_root=temp.repo_root), memory=bridge, runner=runner)
                result = kernel.run_request(
                    BionicTurnRequest(
                        query="What is visible in this screenshot?",
                        thread_key="cli:stage38-bionic",
                        chat_name="Stage38",
                        channel="cli",
                        adapter="cli",
                        record=False,
                        image_paths=(str(image_path),),
                        metadata={"image_ingests": [ingest]},
                    )
                )
            finally:
                self._close_bridge(bridge)

        capsule = result["capsule"]
        self.assertIn("visual", capsule["working_field"]["modalities"])
        self.assertEqual(capsule["perception"]["stage38"]["image_input_count"], 1)
        self.assertTrue(capsule["perception"]["stage38"]["image_understand_available"])
        self.assertIn("visual-memory summary", capsule["generation"]["text"])
        self.assertNotIn("image_support=false", capsule["generation"]["text"])
        self.assertFalse(capsule["interface_contract"]["transport_decision_authority"])

    def test_accept_stage38_cli_runs_visual_provider_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _write_stage38_config(Path(tmpdir))
            env = os.environ.copy()
            env["DEEPSEEK_API_KEY"] = "s" + "k-stage38-test-env-only-value-1234567890"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage38",
                    "--thread-key",
                    "cli:stage38",
                    "--chat-name",
                    "Stage38",
                    "--channel",
                    "cli",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["checks"]["stage37_gate_passed"])
        self.assertTrue(payload["checks"]["image_provider_metadata_visible"])
        self.assertTrue(payload["checks"]["bionic_visual_grounding_visible"])
        self.assertTrue(payload["checks"]["text_provider_no_direct_image_overclaim"])
        self.assertTrue(payload["checks"]["transport_interface_only"])


if __name__ == "__main__":
    unittest.main()
