from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

from tests.test_rag_memory import TempMemoryRepo

import holo_memory_library.rag_memory as rm


def _load_merge_memory_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "merge_memory_jsonl.py"
    spec = importlib.util.spec_from_file_location("test_merge_memory_jsonl", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load merge_memory_jsonl.py from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MemorySyncTests(unittest.TestCase):
    def test_merge_memory_dir_includes_working_store(self) -> None:
        with TempMemoryRepo() as temp:
            module = _load_merge_memory_module()
            module.REPO_ROOT = temp.repo_root

            source_dir = temp.repo_root / "source_memories"
            source_dir.mkdir(parents=True, exist_ok=True)
            working_row = rm.make_row(
                status="working",
                rows=[],
                kind="episodic",
                text="The newest working-memory thread clue should sync too.",
                tags=["unit", "working"],
                source="unit",
                importance=0.61,
                confidence=0.73,
            )
            (source_dir / "working_store.jsonl").write_text(
                json.dumps(working_row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            reports = module.merge_memory_dir(source_dir)
            working_rows = rm.load_rows("working")

            report = next(item for item in reports if item["store"] == "working_store.jsonl")
            self.assertEqual(report["source"], 1)
            self.assertEqual(report["after"], 1)
            self.assertEqual(len(working_rows), 1)
            self.assertEqual(working_rows[0]["text"], working_row["text"])


if __name__ == "__main__":
    unittest.main()
