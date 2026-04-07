from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from holo_host.models import IncomingMessage
from holo_host.store import QueueStore


class QueueStoreThreadingTests(unittest.TestCase):
    def test_record_inbound_succeeds_from_non_owner_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = QueueStore(Path(tmpdir) / "queue.sqlite3")
            try:
                store.initialize()
                message = IncomingMessage(
                    message_id="thread-test",
                    channel="wechat",
                    thread_key="Nemoqi",
                    subject="Nemoqi",
                    sender_email="wechat:Nemoqi",
                    sender_name="Nemoqi",
                    body_text="你在吗",
                )

                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(store.record_inbound, message)
                    record = future.result(timeout=5)

                self.assertFalse(record["duplicate"])
                self.assertEqual(record["thread"]["thread_key"], "Nemoqi")
            finally:
                store.close()
