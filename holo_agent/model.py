from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .prompt_policy import SYSTEM_PROMPT
from .schema import Decision
from .source_authority import classify_source_url


class ModelClient(Protocol):
    def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
        ...

    def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
        ...

    def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
        ...


def lexical_source_evaluation(query: str, source: dict[str, Any], page_text: str) -> dict[str, Any]:
    stop = {
        "search",
        "find",
        "look",
        "lookup",
        "research",
        "official",
        "sources",
        "source",
        "docs",
        "documentation",
        "cite",
        "and",
        "the",
        "a",
        "an",
        "检索",
        "搜索",
        "查找",
        "查一下",
        "联网",
        "官方",
        "官网",
        "文档",
        "来源",
        "给出来源",
    }
    terms = [item.lower() for item in re.findall(r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", query) if item.lower() not in stop]
    lowered = f"{source.get('title', '')} {source.get('url', '')} {page_text}".lower()
    unique_terms = sorted(set(terms))
    hits = [term for term in unique_terms if term in lowered]
    score = len(hits) / max(1, len(unique_terms))
    return {
        "accepted": score >= 0.5,
        "confidence": round(score, 4),
        "reason": "offline fallback lexical evidence check",
        "matched_terms": hits,
    }


def _extract_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        raw = raw[start : end + 1] if start >= 0 and end > start else raw
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _domain(url: str) -> str:
    return urlparse(str(url or "")).netloc.lower().removeprefix("www.")


def _result_allowed_by_search_goal(result: dict[str, Any], search_goal: dict[str, Any]) -> bool:
    url = str(result.get("url", "") or "")
    domain = _domain(url)
    allowed_domains = [str(item).lower() for item in search_goal.get("allowed_domains", []) if str(item).strip()]
    blocked_domains = [str(item).lower() for item in search_goal.get("blocked_domains", []) if str(item).strip()]
    if any(domain == blocked or domain.endswith("." + blocked) for blocked in blocked_domains):
        return False
    if allowed_domains:
        return any(domain == allowed or domain.endswith("." + allowed) for allowed in allowed_domains)
    return bool(classify_source_url(url).get("primary", False)) or bool(url)


def _next_planned_query(context: dict[str, Any]) -> str:
    observations = context.get("observations", [])
    used = {
        str(obs.get("data", {}).get("query", "") or "")
        for obs in observations
        if isinstance(obs, dict) and obs.get("tool") == "web_search"
    }
    for query in context.get("crawl_report", {}).get("plan", {}).get("queries", []) or []:
        candidate = str(query.get("query", "") or "")
        if candidate and candidate not in used:
            return candidate
    return ""


def _first_url(text: str) -> str:
    match = re.search(r"https?://[^\s\]\)>'\"]+", str(text or ""))
    return match.group(0).rstrip(".,;:!?") if match else ""


def _has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _is_capability_question(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in ("what can you do", "capabilities", "what are you able to do")) or any(
        token in str(text or "") for token in ("你现在可以做什么", "你能做什么", "可以做什么", "能力", "能干什么")
    )


def _action_names(context: dict[str, Any]) -> list[str]:
    rows = context.get("action_space", [])
    if not isinstance(rows, list):
        return []
    return [str(item.get("name", "") or "") for item in rows if isinstance(item, dict) and str(item.get("name", "") or "").strip()]


@dataclass(slots=True)
class RuleFallbackModel:
    """Explicit offline fallback for local development.

    The target path is provider-backed model arbitration. This fallback exists
    to keep tests and offline smoke runs deterministic.
    """

    def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
        observations = context.get("observations", [])
        if observations and isinstance(observations, list):
            last = observations[-1]
            if not isinstance(last, dict):
                last = {}
            if last.get("tool") in {"web_search", "open_page", "web_research"} and last.get("status") != "ok":
                next_query = _next_planned_query(context)
                failure_summary = str(last.get("summary", "") or last.get("data", {}).get("provider_health", {}).get("last_status", ""))
                can_refine_query = failure_summary in {"empty_results", "empty", "no search results"}
                if last.get("tool") == "web_search" and next_query and can_refine_query:
                    return Decision(
                        action="web_search",
                        arguments={"query": next_query, "max_results": 5},
                        reason="fallback web search failed; trying the next structured search plan query",
                        confidence=0.45,
                        required_observations=["web_search"],
                    )
                return Decision(
                    action="answer_direct",
                    arguments={},
                    reason="fallback observed a failed web action and should report the failure",
                    confidence=0.6,
                    can_answer=True,
                )
            if last.get("tool") == "web_search" and last.get("status") == "ok":
                results = last.get("data", {}).get("results", [])
                search_goal = context.get("search_goal", {}) if isinstance(context.get("search_goal", {}), dict) else {}
                for result in results:
                    if _result_allowed_by_search_goal(result, search_goal):
                        return Decision(
                            action="open_page",
                            arguments={"url": result.get("url", "")},
                            reason="fallback opens the first source that matches the search goal source policy",
                            confidence=0.5,
                            required_observations=["open_page"],
                        )
                next_query = _next_planned_query(context)
                if next_query:
                    return Decision(
                        action="web_search",
                        arguments={"query": next_query, "max_results": 5},
                        reason="fallback search result did not satisfy source policy; trying next planned query",
                        confidence=0.45,
                        required_observations=["web_search"],
                    )
            if last.get("tool") in {"open_page", "web_research"} and last.get("status") == "ok":
                if last.get("tool") == "open_page" and _first_url(user_text):
                    return Decision(
                        action="answer_direct",
                        arguments={},
                        reason="fallback opened the explicit URL requested by the user and can summarize it",
                        confidence=0.7,
                        can_answer=True,
                    )
                crawl_report = context.get("crawl_report", {}) if isinstance(context.get("crawl_report", {}), dict) else {}
                if last.get("tool") == "open_page" and crawl_report.get("status") not in {"sufficient", None}:
                    next_query = _next_planned_query(context)
                    if next_query:
                        return Decision(
                            action="web_search",
                            arguments={"query": next_query, "max_results": 5},
                            reason="fallback opened page is not sufficient; trying next planned query",
                            confidence=0.45,
                            required_observations=["web_search"],
                        )
                return Decision(
                    action="answer_direct",
                    arguments={},
                    reason="fallback has source evidence and can summarize it",
                    confidence=0.6,
                    can_answer=True,
                )

        explicit_url = _first_url(user_text)
        if explicit_url:
            return Decision(
                action="open_page",
                arguments={"url": explicit_url},
                reason="fallback detected an explicit URL and opens it directly",
                confidence=0.7,
                required_observations=["open_page"],
            )

        next_query = _next_planned_query(context)
        search_goal = context.get("search_goal", {}) if isinstance(context.get("search_goal", {}), dict) else {}
        if next_query and search_goal.get("task_type") in {"official_docs", "api_docs", "financial_filing", "news_current"}:
            return Decision(
                action="web_search",
                arguments={"query": next_query, "max_results": 5},
                reason="fallback starts from the structured search goal plan",
                confidence=0.55,
                required_observations=["web_search"],
            )

        lowered = user_text.lower()
        if any(token in lowered for token in ("search", "latest", "official", "source", "sources", "web", "http")) or any(
            token in user_text for token in ("搜索", "检索", "查一下", "联网", "来源", "官网", "官方")
        ):
            return Decision(
                action="web_search",
                arguments={"query": user_text, "max_results": 5},
                reason="fallback detected an explicit web/source request and starts with web_search",
                confidence=0.55,
                required_observations=["web_search"],
            )
        return Decision(
            action="answer_direct",
            arguments={},
            reason="fallback found no required external observation",
            confidence=0.35,
            can_answer=True,
        )

    def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
        if not observations:
            actions = set(_action_names(context))
            if _is_capability_question(user_text):
                if _has_chinese(user_text):
                    capabilities = [
                        "直接回答不需要外部证据的问题",
                        "按模型决策调用工具并记录 observation ledger",
                    ]
                    if {"web_search", "open_page"} & actions:
                        capabilities.append("进行网页搜索、打开网页、抽取页面正文并报告来源或失败原因")
                    if {"workspace_search", "file_read", "apply_patch", "test_run", "git_diff", "git_status"} & actions:
                        capabilities.append("在工作区内搜索、读文件、修改补丁、运行测试和查看 git diff/status")
                    if "web_research" in actions:
                        capabilities.append("执行有边界的 web research operator，形成 source/citation 证据")
                    return "我现在可以：\n- " + "\n- ".join(capabilities)
                capabilities = [
                    "answer questions that do not require external evidence",
                    "choose tools through the agent loop and record observation ledgers",
                ]
                if {"web_search", "open_page"} & actions:
                    capabilities.append("search the web, open pages, extract text, and report sources or failures")
                if {"workspace_search", "file_read", "apply_patch", "test_run", "git_diff", "git_status"} & actions:
                    capabilities.append("search/read/edit/test the workspace and inspect git state")
                if "web_research" in actions:
                    capabilities.append("run bounded web research with source/citation evidence")
                return "I can:\n- " + "\n- ".join(capabilities)
            if _has_chinese(user_text):
                return "我可以直接回答这类不需要外部证据的问题；如果需要当前事实、网页、文件或测试结果，我会先调用工具并记录观察。"
            return "I can answer directly when no external evidence is needed. For current facts, web, files, or tests, I should call tools and record observations first."

        for obs in reversed(observations):
            if obs.get("tool") == "open_page" and obs.get("status") == "ok":
                url = obs.get("data", {}).get("url", "")
                summary = obs.get("summary") or "page opened"
                return f"Opened source: {url}\nSummary: {summary}"
            if obs.get("tool") in {"web_search", "open_page"} and obs.get("status") != "ok":
                return f"{obs.get('tool')} was attempted but failed: {obs.get('summary') or obs.get('status')}"
            if obs.get("tool") == "web_research" and obs.get("status") == "ok":
                sources = obs.get("data", {}).get("sources", [])
                lines = ["Web research completed. Sources:"]
                for idx, source in enumerate(sources[:5], start=1):
                    title = source.get("title") or source.get("url")
                    lines.append(f"{idx}. {title} - {source.get('url')}")
                return "\n".join(lines)
            if obs.get("tool") == "web_research" and obs.get("status") != "ok":
                return f"web_research was attempted but failed: {obs.get('summary') or obs.get('status')}"
        return "I do not have a tool observation for this request yet."

    def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
        return lexical_source_evaluation(query, source, page_text)


class DeepSeekJsonModel:
    def __init__(self, *, api_key: str | None = None, model: str = "deepseek-chat", base_url: str = "https://api.deepseek.com/chat/completions") -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.model = model
        self.base_url = base_url

    def _call(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")
        body = json.dumps({"model": self.model, "messages": messages, "temperature": temperature}, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url,
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=60) as response:  # nosec B310 - explicit configured provider endpoint
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload.get("choices", [{}])[0].get("message", {}).get("content", "") or "")

    def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
        contract = {
            "action": "one action name from action_space",
            "arguments": {},
            "reason": "short auditable reason, not hidden chain of thought",
            "confidence": 0.0,
            "can_answer": False,
            "required_observations": [],
        }
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"User request:\n{user_text}\n\n"
            f"Context:\n{json.dumps(context, ensure_ascii=False)}\n\n"
            f"Action space:\n{json.dumps(action_space, ensure_ascii=False)}\n\n"
            f"Return JSON only:\n{json.dumps(contract, ensure_ascii=False)}"
        )
        data = _extract_json(self._call([{"role": "user", "content": prompt}]))
        return Decision(
            action=str(data.get("action", "answer_direct") or "answer_direct"),
            arguments=data.get("arguments", {}) if isinstance(data.get("arguments"), dict) else {},
            reason=str(data.get("reason", "") or ""),
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.0) or 0.0))),
            can_answer=bool(data.get("can_answer", False)),
            required_observations=[str(x) for x in data.get("required_observations", []) if str(x).strip()]
            if isinstance(data.get("required_observations"), list)
            else [],
        )

    def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            "Write a concise final answer grounded only in these observations. "
            "If evidence is missing, report the limitation plainly.\n\n"
            f"User request:\n{user_text}\n\n"
            f"Observations:\n{json.dumps(observations, ensure_ascii=False)}"
        )
        return self._call([{"role": "user", "content": prompt}], temperature=0.2).strip()

    def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
        contract = {
            "accepted": False,
            "confidence": 0.0,
            "reason": "short auditable reason, not hidden chain of thought",
            "missing_evidence": [],
            "next_query": "",
        }
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            "Evaluate whether this opened page is sufficient evidence for the user's web research goal. "
            "Use semantic judgment, not keyword counting. Return JSON only. "
            "Accept only if the page directly supports the requested source need.\n\n"
            f"Research goal:\n{query}\n\n"
            f"Candidate source:\n{json.dumps(source, ensure_ascii=False)}\n\n"
            f"Page text excerpt:\n{page_text[:8000]}\n\n"
            f"Prior trajectory:\n{json.dumps(trajectory[-8:], ensure_ascii=False)}\n\n"
            f"JSON contract:\n{json.dumps(contract, ensure_ascii=False)}"
        )
        data = _extract_json(self._call([{"role": "user", "content": prompt}], temperature=0.0))
        return {
            "accepted": bool(data.get("accepted", False)),
            "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.0) or 0.0))),
            "reason": str(data.get("reason", "") or ""),
            "missing_evidence": data.get("missing_evidence", []) if isinstance(data.get("missing_evidence"), list) else [],
            "next_query": str(data.get("next_query", "") or ""),
            "evaluator": self.model,
        }

    def evaluate_action_feedback(
        self,
        *,
        user_text: str,
        decision: dict[str, Any],
        observation: dict[str, Any],
        context: dict[str, Any],
        host_feedback: dict[str, Any],
    ) -> dict[str, Any]:
        contract = {
            "evidence_sufficient": False,
            "recoverable_failure": False,
            "evidence_gap": "short public gap summary",
            "recommended_next_action": "answer_direct | open_page | web_search | ask_clarification | another action name",
            "canonical_stop_reason": "continue | final_answer_ready | tool_failure_report | needs_user_clarification | evidence_exhausted | budget_exhausted",
            "marginal_utility": 0.0,
            "reason": "short auditable reason, not hidden chain of thought",
        }
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            "Evaluate the last host action observation for the agent loop. "
            "Use the structured context, action decision, observation ledger, and host baseline feedback. "
            "Decide whether evidence is sufficient, what gap remains, which next action is useful, and which stop reason applies. "
            "Do not expose hidden chain-of-thought; give only a concise auditable reason. Return JSON only.\n\n"
            f"User request:\n{user_text}\n\n"
            f"Rendered context:\n{str(context.get('rendered_context', ''))[:8000]}\n\n"
            f"Decision:\n{json.dumps(decision, ensure_ascii=False)}\n\n"
            f"Observation:\n{json.dumps(observation, ensure_ascii=False)}\n\n"
            f"Host baseline feedback:\n{json.dumps(host_feedback, ensure_ascii=False)}\n\n"
            f"Return JSON only:\n{json.dumps(contract, ensure_ascii=False)}"
        )
        data = _extract_json(self._call([{"role": "user", "content": prompt}], temperature=0.0))
        return {
            "evidence_sufficient": bool(data.get("evidence_sufficient", False)),
            "recoverable_failure": bool(data.get("recoverable_failure", False)),
            "evidence_gap": str(data.get("evidence_gap", "") or ""),
            "recommended_next_action": str(data.get("recommended_next_action", "") or ""),
            "canonical_stop_reason": str(data.get("canonical_stop_reason", "") or ""),
            "marginal_utility": max(0.0, min(1.0, float(data.get("marginal_utility", 0.0) or 0.0))),
            "reason": str(data.get("reason", "") or ""),
            "evaluator": self.model,
        }
