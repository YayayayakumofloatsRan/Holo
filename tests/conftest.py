from __future__ import annotations

import gc
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
repo_root_str = str(REPO_ROOT)
if repo_root_str not in sys.path:
    sys.path.insert(0, repo_root_str)

from holo_host.store import QueueStore


@pytest.fixture(autouse=True)
def _close_queue_store_handles() -> None:
    yield
    for obj in gc.get_objects():
        if isinstance(obj, QueueStore):
            try:
                obj.close()
            except Exception:  # noqa: BLE001
                continue
