from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class PublicReleaseHygieneTests(unittest.TestCase):
    def test_no_private_release_paths_are_tracked(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(repo / "scripts" / "check_public_release_hygiene.py")],
            cwd=repo,
            text=True,
            capture_output=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
