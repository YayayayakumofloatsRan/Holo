from __future__ import annotations

import hashlib
import re

from kernel_v3.agent.contracts import AnswerProfile, SemanticIntake, TaskExecutionPlan
from kernel_v3.contracts import JsonObject


_FINANCE_MARKERS = ("基本面", "财务", "估值", "市盈率", "现金流", "资产负债", "fundamental", "financial", "valuation", "cash flow", "balance sheet")
_POLICY_MARKERS = ("政策", "监管", "法规", "央行", "证监会", "policy", "regulation", "regulatory", "central bank")


def infer_answer_profile(
    goal: str,
    *,
    semantic_intake: SemanticIntake | None = None,
    task_plan: TaskExecutionPlan | None = None,
    execution_metadata: JsonObject | None = None,
    response_language: str | None = None,
) -> AnswerProfile:
    explicit = _explicit_profile(execution_metadata)
    if explicit is not None:
        return explicit
    hinted = _profile_from_semantic_hint(semantic_intake, response_language=response_language)
    if hinted is not None:
        return hinted
    text = _normalized_text(goal)
    capabilities = _capabilities(semantic_intake=semantic_intake, task_plan=task_plan)
    domain = _domain(text, capabilities)
    strict_shape = _strict_output_shape(text)
    explicit_shape = _explicit_output_shape(text)
    format_name, detail_level = explicit_shape or _default_shape(domain=domain, capabilities=capabilities)
    sections = _target_sections(format_name=format_name, domain=domain)
    min_chars, min_sections = _minimum_shape(detail_level, format_name=format_name)
    quality_gate = _default_quality_gate(
        domain=domain,
        format_name=format_name,
        strict_shape=strict_shape,
        capabilities=capabilities,
    )
    profile_id = "answer-profile-" + _short_hash(
        {
            "goal": text[:512],
            "domain": domain,
            "format": format_name,
            "detail_level": detail_level,
            "sections": sections,
        }
    )
    return AnswerProfile(
        profile_id=profile_id,
        format=format_name,
        detail_level=detail_level,
        target_sections=sections,
        citation_density=_citation_density(format_name=format_name, detail_level=detail_level),
        minimum_coverage=_minimum_coverage(domain=domain, format_name=format_name),
        language=response_language,
        min_answer_chars=min_chars,
        min_section_count=min_sections,
        metadata={
            "domain": domain,
            "source": "host_inferred_answer_profile",
            "quality_gate": quality_gate,
            "explicit_output_shape": explicit_shape is not None,
        },
    )


def answer_profile_from_dict(value: object) -> AnswerProfile | None:
    if not isinstance(value, dict):
        return None
    try:
        return AnswerProfile.from_dict(value)
    except Exception:
        return None


def answer_quality_gaps(
    answer: str,
    *,
    profile: AnswerProfile | None,
    citation_refs: list[str] | None = None,
    used_evidence: list[str] | None = None,
) -> list[str]:
    if profile is None or not _profile_requires_quality_gate(profile):
        return []
    text = " ".join(str(answer or "").split())
    gaps: list[str] = []
    if len(text) < profile.min_answer_chars:
        gaps.append(f"answer_min_chars:{profile.min_answer_chars}")
    section_count = _section_count(answer)
    if section_count < profile.min_section_count:
        gaps.append(f"answer_min_sections:{profile.min_section_count}")
    if profile.citation_density in {"normal", "high"} and not citation_refs:
        gaps.append("citation_refs")
    if not used_evidence:
        gaps.append("used_evidence")
    coverage_gaps = _coverage_gaps(answer, profile=profile)
    gaps.extend(coverage_gaps)
    return _ordered_unique(gaps)


def research_mission_metadata(
    goal: str,
    *,
    answer_profile: AnswerProfile,
    semantic_intake: SemanticIntake | None = None,
    task_plan: TaskExecutionPlan | None = None,
) -> JsonObject:
    capabilities = _capabilities(semantic_intake=semantic_intake, task_plan=task_plan)
    domain = str(answer_profile.metadata.get("domain") or _domain(_normalized_text(goal), capabilities))
    return {
        "mission_kind": "research_employee_core",
        "root_goal": goal,
        "domain": domain,
        "target_entities": _target_entities(goal),
        "answer_profile": answer_profile.to_dict(),
        "requirements": [
            {"requirement_id": f"req-{index}", "text": item, "status": "open"}
            for index, item in enumerate(answer_profile.minimum_coverage, start=1)
        ],
        "operating_rules": [
            "Treat tool failures as observations for replanning, not as direct task termination.",
            "Use memory.recall when prior workspace/thread knowledge could affect the task.",
            "Prefer primary and high-authority sources when the task is factual or analytical.",
            "Do not finalize detailed research until the answer profile coverage is satisfied.",
        ],
    }


def _explicit_profile(metadata: JsonObject | None) -> AnswerProfile | None:
    if not isinstance(metadata, dict):
        return None
    direct = answer_profile_from_dict(metadata.get("answer_profile"))
    if direct is not None:
        return direct
    nested = metadata.get("output")
    if isinstance(nested, dict):
        return answer_profile_from_dict(nested.get("answer_profile"))
    return None


def _profile_from_semantic_hint(semantic_intake: SemanticIntake | None, *, response_language: str | None) -> AnswerProfile | None:
    if semantic_intake is None:
        return None
    for intent in semantic_intake.intents:
        if not isinstance(intent, dict):
            continue
        metadata = intent.get("metadata")
        if not isinstance(metadata, dict):
            continue
        hint = metadata.get("answer_profile_hint")
        if not isinstance(hint, dict):
            continue
        format_name = str(hint.get("format") or "")
        detail_level = str(hint.get("detail_level") or "")
        if format_name not in {"brief_answer", "answer", "detailed_report", "deep_report", "memo"}:
            continue
        if detail_level not in {"brief", "normal", "detailed", "deep"}:
            detail_level = "detailed" if format_name in {"detailed_report", "memo"} else "deep" if format_name == "deep_report" else "normal"
        domain = str(metadata.get("domain") or "")
        if not domain:
            domain = _domain(_normalized_text(str(intent.get("text") or semantic_intake.goal)), set(_string_list(intent.get("required_capabilities"))))
        sections = [str(item) for item in hint.get("target_sections", []) if isinstance(item, str)] if isinstance(hint.get("target_sections"), list) else []
        if not sections:
            sections = _target_sections(format_name=format_name, domain=domain)
        min_chars, min_sections = _minimum_shape(detail_level, format_name=format_name)
        return AnswerProfile(
            profile_id="answer-profile-" + _short_hash({"hint": hint, "goal": semantic_intake.goal[:512]}),
            format=format_name,
            detail_level=detail_level,
            target_sections=sections,
            citation_density=_citation_density(format_name=format_name, detail_level=detail_level),
            minimum_coverage=_minimum_coverage(domain=domain, format_name=format_name),
            language=response_language,
            min_answer_chars=min_chars,
            min_section_count=min_sections,
            metadata={
                "domain": domain,
                "source": "semantic_answer_profile_hint",
                "quality_gate": _valid_quality_gate(hint.get("quality_gate"), format_name=format_name, detail_level=detail_level),
            },
        )
    return None


def _domain(text: str, capabilities: set[str]) -> str:
    if any(item.startswith("finance.") for item in capabilities) or _contains_any(text, _FINANCE_MARKERS):
        return "finance"
    if any(item.startswith("academic.") for item in capabilities):
        return "academic"
    if _contains_any(text, _POLICY_MARKERS):
        return "policy"
    if any(item.startswith("technical.") for item in capabilities):
        return "technical"
    return "general_research" if _contains_any(text, ("调研", "调查", "研究", "research", "investigate")) else "general"


def _default_shape(*, domain: str, capabilities: set[str]) -> tuple[str, str]:
    if domain == "academic" and any(
        capability in capabilities
        for capability in {"academic.frontier_research", "academic.literature_review", "academic.research"}
    ):
        return "detailed_report", "detailed"
    if domain == "finance" and "finance.fundamentals_research" in capabilities:
        return "detailed_report", "detailed"
    return "answer", "normal"


def _explicit_output_shape(text: str) -> tuple[str, str] | None:
    """Infer only the answer shape from explicit user wording.

    This does not decide the task semantics or answer content. It is a host
    guardrail so a clear request for a report, memo, deep research, or brief
    answer survives model variance in semantic.intake.
    """

    if _contains_any(
        text,
        (
            "短答",
            "简短",
            "简要",
            "brief",
            "short answer",
            "concise",
        ),
    ):
        return "brief_answer", "brief"
    strict_shape = _strict_output_shape(text)
    if strict_shape is not None:
        return strict_shape
    if _contains_any(
        text,
        (
            "详细",
            "完整",
            "全面",
            "调研",
            "调查",
            "研究",
            "分析",
            "detailed",
            "thorough",
            "comprehensive",
            "investigate",
            "analysis",
        ),
    ):
        return "detailed_report", "detailed"
    return None


def _strict_output_shape(text: str) -> tuple[str, str] | None:
    if _contains_any(
        text,
        (
            "深度报告",
            "深度调研",
            "深入调研",
            "深入研究",
            "deep report",
            "deep research",
            "in-depth report",
        ),
    ):
        return "deep_report", "deep"
    if _contains_any(
        text,
        (
            "详细报告",
            "完整报告",
            "全面报告",
            "研究报告",
            "调研报告",
            "详细中文报告",
            "detailed report",
            "complete report",
            "comprehensive report",
            "research report",
            "memo",
        ),
    ):
        return "detailed_report", "detailed"
    return None


def _target_sections(*, format_name: str, domain: str) -> list[str]:
    if format_name == "brief_answer":
        return ["answer", "limitations"]
    if domain == "finance":
        return [
            "结论摘要",
            "公司与业务",
            "财务表现",
            "资产负债与现金流",
            "估值与市场数据",
            "增长驱动与风险",
            "证据质量与局限",
        ]
    if domain == "policy":
        return ["结论摘要", "政策原文与发布主体", "时间线", "适用对象", "影响路径", "风险与不确定性", "证据质量与局限"]
    if domain == "technical":
        return ["结论摘要", "官方事实", "关键接口或机制", "使用约束", "示例或操作建议", "证据质量与局限"]
    if domain == "academic":
        return ["结论摘要", "研究问题与范围", "关键文献与来源", "前沿方向", "方法与结果", "争议与开放问题", "证据质量与局限"]
    if format_name in {"detailed_report", "deep_report", "memo"}:
        return ["结论摘要", "背景", "关键发现", "证据", "分析", "风险与局限", "下一步"]
    return ["answer", "limitations"]


def _minimum_coverage(*, domain: str, format_name: str) -> list[str]:
    if domain == "finance":
        return [
            "business_overview",
            "financial_performance",
            "cash_flow_or_balance_sheet",
            "valuation_or_market_data",
            "risks_or_limitations",
            "source_quality",
        ]
    if domain == "policy":
        return ["policy_source", "issuing_body", "timeline", "impact_path", "uncertainty"]
    if domain == "academic":
        return ["scholarly_sources", "research_scope", "key_findings", "frontier_or_open_questions", "limitations"]
    if format_name in {"detailed_report", "deep_report", "memo"}:
        return ["summary", "evidence", "analysis", "limitations"]
    return ["answer"]


def _minimum_shape(detail_level: str, *, format_name: str) -> tuple[int, int]:
    if detail_level == "deep" or format_name == "deep_report":
        return 2200, 6
    if detail_level == "detailed" or format_name in {"detailed_report", "memo"}:
        return 1200, 5
    if detail_level == "brief":
        return 80, 0
    return 180, 0


def _citation_density(*, format_name: str, detail_level: str) -> str:
    if detail_level == "deep" or format_name in {"deep_report", "memo"}:
        return "high"
    if detail_level == "detailed" or format_name == "detailed_report":
        return "normal"
    return "light"


def _coverage_gaps(answer: str, *, profile: AnswerProfile) -> list[str]:
    if profile.format not in {"detailed_report", "deep_report", "memo"}:
        return []
    text = _normalized_text(answer)
    domain = str(profile.metadata.get("domain") or "")
    checks: dict[str, tuple[str, ...]]
    if domain == "finance":
        checks = {
            "business_overview": ("业务", "公司", "business", "segment"),
            "financial_performance": ("营收", "收入", "利润", "revenue", "income", "earnings"),
            "cash_flow_or_balance_sheet": ("现金流", "资产", "负债", "cash flow", "assets", "liabilities", "balance sheet"),
            "valuation_or_market_data": ("估值", "市值", "股价", "市盈率", "valuation", "market cap", "p/e", "pe ratio"),
            "risks_or_limitations": ("风险", "局限", "不确定", "risk", "limitation", "uncertain"),
            "source_quality": ("来源", "证据", "引用", "sec", "edgar", "companyfacts", "annual report", "10-k", "evidence", "source"),
        }
    elif domain == "policy":
        checks = {
            "policy_source": ("政策", "文件", "原文", "policy", "document"),
            "issuing_body": ("发布", "部门", "机构", "issuer", "agency", "authority"),
            "timeline": ("时间", "日期", "生效", "timeline", "date", "effective"),
            "impact_path": ("影响", "路径", "impact", "mechanism"),
            "uncertainty": ("风险", "不确定", "局限", "uncertain", "limitation"),
        }
    elif domain == "academic":
        checks = {
            "scholarly_sources": ("论文", "文献", "期刊", "预印本", "paper", "article", "journal", "preprint", "arxiv", "doi"),
            "research_scope": ("范围", "问题", "背景", "scope", "question", "background"),
            "key_findings": ("发现", "结果", "方法", "定理", "findings", "result", "method", "theorem"),
            "frontier_or_open_questions": ("前沿", "开放问题", "争议", "frontier", "open problem", "debate"),
            "limitations": ("局限", "不确定", "limitations", "uncertain"),
        }
    else:
        checks = {
            "summary": ("摘要", "结论", "summary", "conclusion"),
            "evidence": ("证据", "来源", "evidence", "source"),
            "analysis": ("分析", "判断", "analysis", "assessment"),
            "limitations": ("局限", "限制", "limitations", "uncertain"),
        }
    gaps = []
    for key in profile.minimum_coverage:
        markers = checks.get(key)
        if markers and not _contains_any(text, markers):
            gaps.append(f"coverage:{key}")
    return gaps


def _section_count(answer: str) -> int:
    count = 0
    for line in str(answer or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            count += 1
        elif re.match(r"^\*\*[^*]{2,60}\*\*", stripped):
            count += 1
        elif re.match(r"^\d+[.、]\s*[^。]{2,40}$", stripped):
            count += 1
    return count


def _profile_requires_quality_gate(profile: AnswerProfile) -> bool:
    return str(profile.metadata.get("quality_gate") or "") == "strict"


def _default_quality_gate(
    *,
    domain: str,
    format_name: str,
    strict_shape: tuple[str, str] | None,
    capabilities: set[str],
) -> str:
    if format_name not in {"detailed_report", "deep_report", "memo"}:
        return "advisory"
    if strict_shape is not None:
        return "strict"
    if domain in {"finance", "academic", "policy"}:
        return "strict"
    if any(
        capability.startswith(("finance.", "academic.", "policy.", "technical.research"))
        for capability in capabilities
    ):
        return "strict"
    return "advisory"


def _valid_quality_gate(value: object, *, format_name: str, detail_level: str) -> str:
    if value in {"off", "advisory", "strict"}:
        return str(value)
    if format_name in {"detailed_report", "deep_report", "memo"} or detail_level in {"detailed", "deep"}:
        return "strict"
    return "advisory"


def _capabilities(*, semantic_intake: SemanticIntake | None, task_plan: TaskExecutionPlan | None) -> set[str]:
    result: set[str] = set()
    if semantic_intake is not None:
        for intent in semantic_intake.intents:
            if isinstance(intent, dict):
                values = intent.get("required_capabilities")
                if isinstance(values, list):
                    result.update(str(item) for item in values if isinstance(item, str))
    if task_plan is not None:
        for step in task_plan.steps:
            if isinstance(step, dict):
                values = step.get("required_capabilities")
                if isinstance(values, list):
                    result.update(str(item) for item in values if isinstance(item, str))
    return result


def _target_entities(goal: str) -> list[str]:
    entities: list[str] = []
    for match in re.finditer(r"\b[A-Z][A-Z0-9.&-]{1,12}\b", goal):
        token = match.group(0)
        if token not in {"API", "JSON", "PDF", "HTML"}:
            entities.append(token)
    for match in re.finditer(r"[\u4e00-\u9fffA-Za-z0-9.&-]{2,40}(?:公司|集团|银行|证券|科技|股份)", goal):
        entities.append(match.group(0))
    return _ordered_unique(entities)[:8]


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(marker.lower() in lower for marker in markers)


def _normalized_text(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _short_hash(value: object) -> str:
    return hashlib.sha256(repr(value).encode("utf-8", errors="replace")).hexdigest()[:12]
