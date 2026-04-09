from __future__ import annotations

import unittest

from holo_host.cli import _evaluate_stage12_acceptance


class Stage12AcceptanceTests(unittest.TestCase):
    def test_stage12_acceptance_reports_pass_for_complete_payload(self) -> None:
        report = _evaluate_stage12_acceptance(
            health={"status": "ok"},
            thread_key="wechat:Nemoqi",
            chat_name="Nemoqi",
            reply_result={
                "action": "reply",
                "thread_key": "wechat:Nemoqi",
                "selected_action": {"action_type": "reply_once"},
                "outcome_appraisal": {"status": "ok"},
            },
            defer_result={"action": "defer_reply", "outcome_appraisal": {"status": "ok"}},
            silence_result={"action": "silence", "outcome_appraisal": {"status": "ok"}},
            thread_row={"thread_key": "wechat:Nemoqi"},
            appraisal_rows=[
                {
                    "action_ref": "wechat-out-1",
                    "metadata": {
                        "event_row_id": 7,
                        "message_id": "msg-1",
                        "thread_key": "wechat:Nemoqi",
                        "usage_evidence_refs": ["usage:event_id:7"],
                    },
                }
            ],
            usage_rows=[{"event_id": "7", "total_tokens": 128}],
            subject_after_reload={
                "outcome_memory": {"last_action_ref": "wechat-out-1"},
                "world_state": {"last_post_outcome_calibration": {"action_ref": "wechat-out-1"}},
            },
            helper_contracts={
                "artifact_path": "/mnt/d/Holo/holo/.holo_runtime/wechat-helper/receipts/history.md",
                "wsl_fallback_candidates": ["http://127.0.0.1:8000", "http://172.28.44.15:8000"],
            },
            roadmap_registry={"Primary Track": ["identity continuity"]},
        )

        self.assertEqual(report["status"], "pass")
        self.assertGreaterEqual(report["score"], 9.0)
        self.assertTrue(all(bool(value) for value in report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
