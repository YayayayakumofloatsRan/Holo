from __future__ import annotations

from holo_agent.final_answer_contract import build_final_answer_contract
from holo_agent.workflow_policy import verify_engineering_final


def test_capability_statement_is_not_treated_as_completed_engineering_result() -> None:
    text = "我现在可以搜索网页、读取文件、运行测试和查看 git diff/status。"

    contract = build_final_answer_contract(user_text="你现在可以做什么？", final_text=text, observations=[])

    assert contract["answer_type"] == "capability_statement"
    assert contract["requires_completion_ledgers"] is False
    assert verify_engineering_final(text, [], answer_contract=contract)["status"] == "ok"


def test_completed_engineering_claim_still_requires_ledgers() -> None:
    text = "I read README.md, patched it, and tests passed."

    contract = build_final_answer_contract(user_text="Patch README.md and run tests", final_text=text, observations=[])
    report = verify_engineering_final(text, [], answer_contract=contract)

    assert contract["answer_type"] == "completed_result_claim"
    assert contract["requires_completion_ledgers"] is True
    assert report["status"] == "unverified_engineering_claim"
    assert "file_read" in report["missing_observations"]
    assert "test_run" in report["missing_observations"]


def test_failure_report_is_allowed_to_reference_attempted_tool_without_success_ledger() -> None:
    text = "open_page was attempted but failed: HTTP Error 403: Forbidden"
    observations = [{"tool": "open_page", "status": "error", "summary": "HTTP Error 403: Forbidden"}]

    contract = build_final_answer_contract(user_text="open the URL", final_text=text, observations=observations)

    assert contract["answer_type"] == "failure_report"
    assert contract["requires_completion_ledgers"] is False
    assert verify_engineering_final(text, observations, answer_contract=contract)["status"] == "ok"
