from __future__ import annotations

import re
from typing import Any


FINAL_ANSWER_CONTRACT_SCHEMA = "holo.stage231.final_answer_contract.v1"


def _has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _is_capability_question(user_text: str) -> bool:
    lowered = str(user_text or "").lower()
    return any(token in lowered for token in ("what can you do", "capabilities", "what are you able to do")) or any(
        token in str(user_text or "") for token in ("你现在可以做什么", "你能做什么", "可以做什么", "能力", "能干什么")
    )


def _is_capability_statement(final_text: str) -> bool:
    text = str(final_text or "")
    lowered = text.lower()
    can_markers = ("i can", "i am able to", "i should call", "我现在可以", "我可以", "能够", "能在")
    completed_markers = (
        "i read",
        "i patched",
        "i modified",
        "tests passed",
        "我已读取",
        "我已经读取",
        "我已修改",
        "测试通过",
    )
    return any(marker in lowered or marker in text for marker in can_markers) and not any(
        marker in lowered or marker in text for marker in completed_markers
    )


def _is_failure_report(final_text: str, observations: list[dict[str, Any]]) -> bool:
    lowered = str(final_text or "").lower()
    has_failed_observation = any(str(obs.get("status", "")) != "ok" for obs in observations)
    return has_failed_observation and any(token in lowered for token in ("failed", "error", "forbidden", "失败", "错误"))


def _has_completed_result_claim(final_text: str) -> bool:
    lowered = str(final_text or "").lower()
    return bool(
        re.search(r"\b(i|we)\s+(read|opened|inspected|patched|modified|changed|edited|fixed|ran)\b", lowered)
        or re.search(r"\btests? (passed|pass)|pytest passed\b", lowered)
        or any(token in str(final_text or "") for token in ("我已", "我已经", "已读取", "已修改", "测试通过"))
    )


def _successful_tools(observations: list[dict[str, Any]]) -> set[str]:
    return {str(obs.get("tool", "")) for obs in observations if str(obs.get("status", "")) == "ok"}


def _failed_tools(observations: list[dict[str, Any]]) -> set[str]:
    return {str(obs.get("tool", "")) for obs in observations if str(obs.get("status", "")) != "ok"}


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered or term in text for term in terms)


def _claim_obligations(final_text: str, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract host-verifiable obligations from visible claims.

    This is not the agent's semantic brain. It is a public-surface validation
    contract: visible claims that say work was completed must point to ledgers;
    capability descriptions and plans do not create completion obligations.
    """

    text = str(final_text or "")
    lowered = text.lower()
    success = _successful_tools(observations)
    failed = _failed_tools(observations)
    rows: list[dict[str, Any]] = []

    def add(kind: str, required_tools: set[str], obligation_type: str, claim_text: str) -> None:
        available = failed if obligation_type == "failure" else success
        satisfied = bool(required_tools & available)
        rows.append(
            {
                "claim_family": kind,
                "claim_text": claim_text,
                "required_tools": sorted(required_tools),
                "obligation_type": obligation_type,
                "satisfied": satisfied,
                "missing_tools": [] if satisfied else sorted(required_tools),
            }
        )

    if _contains_any(text, ("i read", "i opened file", "inspected file", "读取了", "已读取", "查看了文件")):
        add("file_read", {"file_read"}, "completion", "visible claim says a file was read or inspected")
    if re.search(r"\b(patched|modified|changed|edited|fixed)\b", lowered) or _contains_any(
        text, ("已修改", "已修复", "打了补丁")
    ):
        add("apply_patch", {"apply_patch"}, "completion", "visible claim says workspace files were changed")
    if re.search(r"\btests? (passed|pass)|pytest passed\b", lowered) or _contains_any(text, ("测试通过",)):
        add("test_run", {"test_run"}, "completion", "visible claim says tests passed")
    if _contains_any(text, ("git status", "git diff", "diff clean", "查看 git", "工作区干净")):
        add("git_state", {"git_diff", "git_status"}, "completion", "visible claim says git state or diff was inspected")
    if _contains_any(text, ("opened source:", "opened page", "打开了网页", "已打开网页")):
        add("open_page", {"open_page"}, "completion", "visible claim says a web page was opened")
    if _contains_any(text, ("searched", "web search completed", "搜索完成", "已经搜索")):
        add("web_search", {"web_search"}, "completion", "visible claim says search completed")
    if _contains_any(text, ("was attempted but failed", "attempted and failed", "尝试", "失败")) and _contains_any(
        text, ("web_search", "open_page", "file_read", "test_run", "搜索", "打开")
    ):
        tool_candidates = {tool for tool in ("web_search", "open_page", "file_read", "test_run", "apply_patch") if tool in lowered}
        if "搜索" in text:
            tool_candidates.add("web_search")
        if "打开" in text:
            tool_candidates.add("open_page")
        add("attempted_failure", tool_candidates or {"web_search", "open_page"}, "failure", "visible claim reports attempted tool failure")
    return rows


def build_final_answer_contract(
    *,
    user_text: str,
    final_text: str,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    capability_context = _is_capability_question(user_text) or _is_capability_statement(final_text)
    completed_claim = _has_completed_result_claim(final_text)
    if _is_failure_report(final_text, observations):
        answer_type = "failure_report"
    elif capability_context and not completed_claim:
        answer_type = "capability_statement"
    elif completed_claim:
        answer_type = "completed_result_claim"
    else:
        answer_type = "direct_explanation" if _has_chinese(user_text + final_text) else "direct_answer"
    obligations = [] if answer_type == "capability_statement" else _claim_obligations(final_text, observations)
    missing = [tool for row in obligations for tool in row.get("missing_tools", [])]
    return {
        "schema": FINAL_ANSWER_CONTRACT_SCHEMA,
        "answer_type": answer_type,
        "claim_obligations": obligations,
        "requires_completion_ledgers": any(row.get("obligation_type") == "completion" for row in obligations),
        "missing_required_tools": sorted(set(missing)),
        "all_obligations_satisfied": not missing,
        "observation_count": len(observations),
        "visible_language": "zh" if _has_chinese(user_text + final_text) else "en",
    }
