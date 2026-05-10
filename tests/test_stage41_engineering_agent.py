from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from holo_host.config import load_config
from holo_host.engineering_agent import EngineeringAgentHarness
from holo_host.models import ProcessorTaskResult
from holo_host.store import QueueStore


def _write_stage41_config(root: Path) -> Path:
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
api_port = 65512

[processor_fabric]
deepseek_api_key_env = "DEEPSEEK_API_KEY"

[provider_backends.kernel_xhigh]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-pro"
reasoning_effort = "xhigh"
max_output_tokens = 512
""".strip(),
        encoding="utf-8",
    )
    return config_path


class _EngineeringRunner:
    def __init__(self, actions: list[dict]) -> None:
        self.actions = actions
        self.requests: list[dict] = []

    def run_task(self, request):
        self.requests.append(request.to_dict())
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=json.dumps(
                {
                    "summary": "execute bounded engineering loop",
                    "actions": self.actions,
                    "done": True,
                    "verification": "read, test, and write results must be checked",
                },
                ensure_ascii=False,
            ),
            returncode=0,
            output_schema="json",
            metadata={"provider": "deepseek", "model": "deepseek-v4-pro", "lane": "kernel_xhigh"},
        )


class Stage41EngineeringAgentTests(unittest.TestCase):
    def _repo(self) -> tempfile.TemporaryDirectory[str]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "tests").mkdir(parents=True)
        (root / ".holo_runtime").mkdir(parents=True)
        (root / "sample.txt").write_text("before\nneedle\n", encoding="utf-8")
        (root / "tests" / "test_sample.py").write_text("def test_sample():\n    assert True\n", encoding="utf-8")
        return tmp

    def _harness(self, root: Path, actions: list[dict]) -> tuple[EngineeringAgentHarness, QueueStore]:
        config = load_config(config_path=str(_write_stage41_config(root)), repo_root=root)
        store = QueueStore(config.runtime.db_path)
        store.initialize()
        return EngineeringAgentHarness(config=config, store=store, runner=_EngineeringRunner(actions)), store

    def test_tool_loop_executes_read_search_and_test_actions(self) -> None:
        with self._repo() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(
                root,
                [
                    {"tool": "read_file", "mutation_class": "read_only", "path": "sample.txt"},
                    {"tool": "search_text", "mutation_class": "read_only", "pattern": "needle", "glob": "*.txt"},
                    {
                        "tool": "run_tests",
                        "mutation_class": "cache_write",
                        "command": [sys.executable, "-m", "pytest", "-q", "tests/test_sample.py"],
                    },
                ],
            )
            try:
                result = harness.run(goal="verify sample", thread_key="cli:stage41", max_steps=2)
            finally:
                store.close()

        actions = result["steps"][0]["tool_loop"]["actions"]
        self.assertTrue(result["ok"], result)
        self.assertEqual([action["tool"] for action in actions], ["read_file", "search_text", "run_tests"])
        self.assertTrue(all(action["gate"]["allowed"] for action in actions))
        self.assertIn("before", actions[0]["observation"]["content"])
        self.assertGreaterEqual(actions[1]["observation"]["match_count"], 1)
        self.assertEqual(actions[2]["observation"]["returncode"], 0)
        self.assertTrue(result["verification"]["tests_observed"])

    def test_repo_write_is_denied_by_default_and_allowed_explicitly(self) -> None:
        action = {
            "tool": "replace_text",
            "mutation_class": "repo_write",
            "path": "sample.txt",
            "old": "before",
            "new": "after",
        }
        with self._repo() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(root, [action])
            try:
                denied = harness.run(goal="try write", thread_key="cli:stage41-denied", max_steps=1)
                self.assertIn("before", (root / "sample.txt").read_text(encoding="utf-8"))
                allowed = harness.run(
                    goal="write with authority",
                    thread_key="cli:stage41-allowed",
                    allow_repo_write=True,
                    max_steps=1,
                )
                final_text = (root / "sample.txt").read_text(encoding="utf-8")
            finally:
                store.close()

        self.assertFalse(denied["steps"][0]["tool_loop"]["actions"][0]["gate"]["allowed"])
        self.assertEqual(denied["steps"][0]["tool_loop"]["actions"][0]["gate"]["reason"], "repo_write_requires_explicit_user_authority")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["verification"]["failure_reason"], "blocked_action")
        self.assertTrue(allowed["steps"][0]["tool_loop"]["actions"][0]["gate"]["allowed"])
        self.assertFalse(allowed["ok"])
        self.assertEqual(allowed["verification"]["failure_reason"], "repo_write_requires_verification_tests")
        self.assertIn("after", final_text)

    def test_repo_write_requires_followup_verification(self) -> None:
        with self._repo() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(
                root,
                [
                    {
                        "tool": "replace_text",
                        "mutation_class": "repo_write",
                        "path": "sample.txt",
                        "old": "before",
                        "new": "after",
                    },
                    {
                        "tool": "run_tests",
                        "mutation_class": "cache_write",
                        "command": [sys.executable, "-m", "pytest", "-q", "tests/test_sample.py"],
                    },
                ],
            )
            try:
                result = harness.run(
                    goal="write and verify",
                    thread_key="cli:stage41-write-verified",
                    allow_repo_write=True,
                    max_steps=1,
                )
            finally:
                store.close()

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["verification"]["successful_repo_write_count"], 1)
        self.assertTrue(result["verification"]["tests_observed"])

    def test_repo_write_without_declared_mutation_class_still_requires_verification(self) -> None:
        with self._repo() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(
                root,
                [
                    {
                        "tool": "replace_text",
                        "path": "sample.txt",
                        "old": "before",
                        "new": "after",
                    }
                ],
            )
            try:
                result = harness.run(
                    goal="write without mutation declaration",
                    thread_key="cli:stage41-write-default",
                    allow_repo_write=True,
                    max_steps=1,
                )
            finally:
                store.close()

        action = result["steps"][0]["tool_loop"]["actions"][0]
        self.assertEqual(action["mutation_class"], "repo_write")
        self.assertFalse(result["ok"])
        self.assertEqual(result["verification"]["failure_reason"], "repo_write_requires_verification_tests")

    def test_private_runtime_paths_remain_blocked_even_with_repo_write_authority(self) -> None:
        with self._repo() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(
                root,
                [
                    {
                        "tool": "write_file",
                        "mutation_class": "repo_write",
                        "path": ".holo_runtime/secret.txt",
                        "content": "should-not-write",
                    }
                ],
            )
            try:
                result = harness.run(
                    goal="try private write",
                    thread_key="cli:stage41-private",
                    allow_repo_write=True,
                    max_steps=1,
                )
            finally:
                store.close()

        action = result["steps"][0]["tool_loop"]["actions"][0]
        self.assertFalse(action["gate"]["allowed"])
        self.assertEqual(action["gate"]["reason"], "private_or_unsafe_path_blocked")
        self.assertFalse(result["ok"])
        self.assertEqual(result["verification"]["failure_reason"], "blocked_action")
        self.assertFalse((root / ".holo_runtime" / "secret.txt").exists())

    def test_tool_identity_cannot_be_downgraded_by_declared_mutation_class(self) -> None:
        with self._repo() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(
                root,
                [
                    {
                        "tool": "write_file",
                        "mutation_class": "read_only",
                        "path": "downgrade.txt",
                        "content": "should-not-write",
                    }
                ],
            )
            try:
                result = harness.run(goal="try mutation downgrade", thread_key="cli:stage41-downgrade", max_steps=1)
            finally:
                store.close()

        action = result["steps"][0]["tool_loop"]["actions"][0]
        self.assertFalse(action["gate"]["allowed"])
        self.assertEqual(action["gate"]["reason"], "repo_write_requires_explicit_user_authority")
        self.assertFalse(result["ok"])
        self.assertEqual(result["verification"]["failure_reason"], "blocked_action")
        self.assertFalse((root / "downgrade.txt").exists())


if __name__ == "__main__":
    unittest.main()
