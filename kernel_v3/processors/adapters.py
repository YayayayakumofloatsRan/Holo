from __future__ import annotations

import hashlib
import json

from kernel_v3.context.redaction import Redactor
from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, JsonObject, Observation
from kernel_v3.processors.contracts import (
    EVALUATOR_PROMPT_CONTRACT,
    EVALUATOR_SCHEMA,
    PLANNER_PROMPT_CONTRACT,
    PLANNER_SCHEMA,
    SYNTHESIZER_PROMPT_CONTRACT,
    SYNTHESIZER_SCHEMA,
    FinalAnswer,
)
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, RetrievalReport

SYNTHESIS_EVIDENCE_PREVIEW_CHARS = 4096
SYNTHESIS_CITATION_PREVIEW_CHARS = 2048


class ModelPlanner:
    def __init__(
        self,
        *,
        fabric: ProcessorFabric,
        provider: str | None = None,
        model: str | None = None,
        allowed_tool_names: set[str] | None = None,
    ) -> None:
        self.fabric = fabric
        self.provider = provider
        self.model = model
        self.allowed_tool_names = set(allowed_tool_names or set())
        self.calls: list[ContextBundle] = []

    def propose(self, context: ContextBundle, feedback: Feedback | None = None) -> CandidateAction:
        self.calls.append(context)
        task_id = _task_id(context)
        run_id = _run_id(context)
        outcome = self.fabric.run_json(
            task_type="planner.propose",
            task_id=task_id,
            run_id=run_id,
            context_id=context.context_id,
            prompt=_planner_prompt(context, feedback),
            schema=PLANNER_SCHEMA,
            provider=self.provider,
            model=self.model,
            parameters={"adapter": "ModelPlanner"},
        )
        if outcome.parsed is None:
            return _planner_fallback(run_id, "processor_failed")
        action = _action_from_json(outcome.parsed)
        unsafe_reason = self._unsafe_reason(action)
        if unsafe_reason is not None:
            return _planner_fallback(run_id, unsafe_reason)
        return action

    def _unsafe_reason(self, action: CandidateAction) -> str | None:
        if action.kind not in {"respond", "tool", "ask_user"}:
            return "unsupported_action_kind"
        if action.kind == "tool":
            if not action.name:
                return "tool_name_required"
            if self.allowed_tool_names and action.name not in self.allowed_tool_names:
                return "tool_not_allowlisted"
        if action.side_effect_class not in {"none", "read", "write", "destructive", "shell", "network"}:
            return "unsupported_side_effect_class"
        return None


class ModelEvaluator:
    def __init__(
        self,
        *,
        fabric: ProcessorFabric,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.fabric = fabric
        self.provider = provider
        self.model = model
        self.calls: list[Observation] = []

    def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
        self.calls.append(observation)
        task_id = _task_id(context)
        run_id = _run_id(context)
        outcome = self.fabric.run_json(
            task_type="evaluator.assess",
            task_id=task_id,
            run_id=run_id,
            context_id=context.context_id,
            prompt=_evaluator_prompt(context, observation),
            schema=EVALUATOR_SCHEMA,
            provider=self.provider,
            model=self.model,
            parameters={"adapter": "ModelEvaluator", "observation_id": observation.observation_id},
        )
        if outcome.parsed is None:
            return Feedback(
                feedback_id=f"fb-{run_id}-model-evaluator-failed-{len(self.calls)}",
                run_id=run_id,
                status="failed",
                stop_reason="processor_failed",
                answer=None,
                missing_evidence=["model_evaluator_failed"],
            )
        return _feedback_from_json(outcome.parsed, run_id=run_id, index=len(self.calls))


class Synthesizer:
    def __init__(
        self,
        *,
        fabric: ProcessorFabric,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.fabric = fabric
        self.provider = provider
        self.model = model

    def synthesize(
        self,
        *,
        run_id: str,
        context_id: str,
        report: RetrievalReport,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
        task_id: str | None = None,
    ) -> FinalAnswer:
        outcome = self.fabric.run_json(
            task_type="synthesizer.answer",
            task_id=task_id,
            run_id=run_id,
            context_id=context_id,
            prompt=_synthesizer_prompt(report, evidence, citations),
            schema=SYNTHESIZER_SCHEMA,
            provider=self.provider,
            model=self.model,
            parameters={"adapter": "Synthesizer", "retrieval_report_id": report.report_id},
        )
        if outcome.parsed is None:
            return FinalAnswer(
                status="failed",
                answer=None,
                citation_refs=[],
                confidence=0.0,
                limitations=[],
                used_evidence=[],
                error="processor_failed",
            )
        answer = _final_answer_from_json(outcome.parsed, citations=citations, evidence=evidence)
        if answer.error == "missing_citation_refs" and citations:
            retry = self.fabric.run_json(
                task_type="synthesizer.answer",
                task_id=task_id,
                run_id=run_id,
                context_id=f"{context_id}-citation-repair",
                prompt=_synthesizer_prompt(
                    report,
                    evidence,
                    citations,
                    retry_instruction=(
                        "Previous synthesizer output omitted citation_refs. "
                        "Return a corrected JSON object. citation_refs must include one or more ids "
                        "from required_citation_refs, and used_evidence must include matching evidence ids."
                    ),
                ),
                schema=SYNTHESIZER_SCHEMA,
                provider=self.provider,
                model=self.model,
                parameters={
                    "adapter": "Synthesizer",
                    "retrieval_report_id": report.report_id,
                    "repair_reason": "missing_citation_refs",
                },
            )
            if retry.parsed is not None:
                return _final_answer_from_json(retry.parsed, citations=citations, evidence=evidence)
        return answer


def _planner_prompt(context: ContextBundle, feedback: Feedback | None) -> str:
    payload = {
        "contract": PLANNER_PROMPT_CONTRACT,
        "context": _compact_context(context),
        "feedback": feedback.to_dict() if feedback is not None else None,
    }
    return json.dumps(_redacted_prompt_payload(payload), ensure_ascii=False, sort_keys=True)


def _evaluator_prompt(context: ContextBundle, observation: Observation) -> str:
    payload = {
        "contract": EVALUATOR_PROMPT_CONTRACT,
        "context": _compact_context(context),
        "observation": _compact_observation_for_provider(observation),
    }
    return json.dumps(_redacted_prompt_payload(payload), ensure_ascii=False, sort_keys=True)


def _synthesizer_prompt(
    report: RetrievalReport,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    *,
    retry_instruction: str | None = None,
) -> str:
    preferences = _interaction_preferences_from_report(report)
    evidence_preview_chars = _positive_int(
        report.diagnostics.get("synthesis_evidence_preview_chars") if isinstance(report.diagnostics, dict) else None,
        default=SYNTHESIS_EVIDENCE_PREVIEW_CHARS,
    )
    citation_preview_chars = _positive_int(
        report.diagnostics.get("synthesis_citation_preview_chars") if isinstance(report.diagnostics, dict) else None,
        default=SYNTHESIS_CITATION_PREVIEW_CHARS,
    )
    payload = {
        "contract": SYNTHESIZER_PROMPT_CONTRACT,
        "task_goal": _task_goal_from_report(report),
        "interaction_preferences": preferences,
        "response_language": preferences.get("response_language"),
        "answer_profile": _json_object(report.diagnostics.get("answer_profile")) if isinstance(report.diagnostics, dict) else {},
        "research_mission": _json_object(report.diagnostics.get("research_mission")) if isinstance(report.diagnostics, dict) else {},
        "host_situation": _json_object(report.diagnostics.get("host_situation")) if isinstance(report.diagnostics, dict) else {},
        "required_citation_refs": [item.citation_id for item in citations],
        "required_evidence_refs": [item.evidence_id for item in evidence],
        "answer_requirements": [
            "Answer every explicit question or subtask in task_goal when supported by provided evidence.",
            "If any part is unsupported, include it in limitations.",
            "Use only provided citation_refs and evidence ids.",
            "If required_citation_refs is non-empty, citation_refs must include at least one provided citation id.",
            "Use the response_language preference as the default user-visible language unless the user explicitly requested another language.",
            "If answer_profile.format is detailed_report, deep_report, or memo, write a sectioned report that covers answer_profile.target_sections and answer_profile.minimum_coverage.",
            "If the evidence does not support a required section, include that section with a clear limitation instead of collapsing the whole answer into a short summary.",
            "For finance research, distinguish facts, source-backed metrics, analysis, risks, and limitations; do not rely on generic product or encyclopedia pages as if they were financial statements.",
            "Use host_situation as the source of truth for whether live retrieval, tools, permissions, and finance research are available.",
            "Do not say live retrieval, network access, or finance research is unavailable unless host_situation.retrieval or host_situation.failure says so.",
            "If host_situation says retrieval was attempted but evidence is insufficient, describe the real failure as search/fetch/extraction/citation/coverage quality instead of a permission problem.",
        ],
        "retrieval_report": report.to_dict(),
        "evidence": [_compact_evidence_for_provider(item, preview_chars=evidence_preview_chars) for item in evidence],
        "citations": [_compact_citation_for_provider(item, preview_chars=citation_preview_chars) for item in citations],
    }
    if retry_instruction:
        payload["retry_instruction"] = retry_instruction
    return json.dumps(_redacted_prompt_payload(payload), ensure_ascii=False, sort_keys=True)


def _redacted_prompt_payload(payload: JsonObject) -> JsonObject:
    redacted, _markers = Redactor().redact(payload)
    return redacted if isinstance(redacted, dict) else {"value": redacted}


def _compact_context(context: ContextBundle) -> JsonObject:
    return {
        "context_id": context.context_id,
        "thread_key": context.thread_key,
        "event_ids": list(context.event_ids),
        "memory_refs": list(context.memory_refs),
        "state": context.state,
        "token_budget": context.token_budget,
    }


def _task_goal_from_report(report: RetrievalReport) -> str:
    diagnostics = report.diagnostics if isinstance(report.diagnostics, dict) else {}
    for key in ("task_goal", "goal_query", "query"):
        value = diagnostics.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return report.preview


def _interaction_preferences_from_report(report: RetrievalReport) -> JsonObject:
    diagnostics = report.diagnostics if isinstance(report.diagnostics, dict) else {}
    preferences = diagnostics.get("interaction_preferences")
    if isinstance(preferences, dict):
        return dict(preferences)
    response_language = diagnostics.get("response_language")
    if isinstance(response_language, str) and response_language:
        return {"response_language": response_language}
    return {}


def _compact_observation_for_provider(observation: Observation) -> JsonObject:
    data = observation.to_dict()
    data["content"] = _compact_prompt_value(observation.content)
    return data


def _compact_evidence_for_provider(item: EvidenceItem, *, preview_chars: int = SYNTHESIS_EVIDENCE_PREVIEW_CHARS) -> JsonObject:
    data = item.to_dict()
    text = str(data.pop("text", ""))
    data["text_preview"] = _preview(text, preview_chars)
    data["text_hash"] = _hash_text(text)
    data["text_chars"] = len(text)
    return data


def _compact_citation_for_provider(item: CitationItem, *, preview_chars: int = SYNTHESIS_CITATION_PREVIEW_CHARS) -> JsonObject:
    data = item.to_dict()
    quote = str(data.pop("quote", ""))
    data["quote_preview"] = _preview(quote, preview_chars)
    data["quote_hash"] = _hash_text(quote)
    data["quote_chars"] = len(quote)
    return data


def _compact_prompt_value(value):
    if isinstance(value, str):
        if len(value) <= 512:
            return value
        return {"preview": _preview(value, 512), "hash": _hash_text(value), "chars": len(value)}
    if isinstance(value, list):
        return [_compact_prompt_value(item) for item in value[:20]]
    if isinstance(value, dict):
        compacted = {}
        for key, item in value.items():
            if isinstance(item, str) and key in {"text", "quote", "body", "raw", "content"}:
                compacted[f"{key}_preview"] = _preview(item, 512)
                compacted[f"{key}_hash"] = _hash_text(item)
                compacted[f"{key}_chars"] = len(item)
                continue
            compacted[key] = _compact_prompt_value(item)
        return compacted
    return value


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _action_from_json(data: JsonObject) -> CandidateAction:
    kind = str(data["kind"])
    name = data.get("name")
    if kind in {"respond", "ask_user"}:
        name = None
    elif name is not None:
        name = str(name)
    payload = data.get("payload")
    reasons = data.get("reasons")
    return CandidateAction(
        action_id=str(data["action_id"]),
        kind=kind,
        name=name if isinstance(name, str) else None,
        description=str(data["description"]),
        score=_score(data.get("score", 1.0)),
        payload=dict(payload) if isinstance(payload, dict) else {},
        reasons=[str(item) for item in reasons] if isinstance(reasons, list) else [],
        side_effect_class=str(data["side_effect_class"]),
    )


def _feedback_from_json(data: JsonObject, *, run_id: str, index: int) -> Feedback:
    status = str(data["status"])
    if status not in {"continue", "final_answer_ready", "needs_user_input", "blocked", "failed"}:
        return Feedback(
            feedback_id=f"fb-{run_id}-model-evaluator-invalid-{index}",
            run_id=run_id,
            status="failed",
            stop_reason="invalid_feedback_status",
            answer=None,
            missing_evidence=["invalid_feedback_status"],
        )
    answer = data.get("answer")
    stop_reason = data.get("stop_reason")
    missing = data.get("missing_evidence")
    if status == "continue":
        normalized_stop_reason = None
    elif isinstance(stop_reason, str) and stop_reason:
        normalized_stop_reason = stop_reason
    elif status == "final_answer_ready":
        normalized_stop_reason = "completed"
    else:
        normalized_stop_reason = status
    return Feedback(
        feedback_id=f"fb-{run_id}-model-evaluator-{index}",
        run_id=run_id,
        status=status,
        stop_reason=normalized_stop_reason,
        answer=answer if isinstance(answer, str) else None,
        missing_evidence=[str(item) for item in missing] if isinstance(missing, list) else [],
    )


def _final_answer_from_json(
    data: JsonObject,
    *,
    citations: list[CitationItem],
    evidence: list[EvidenceItem],
) -> FinalAnswer:
    known_citations = {item.citation_id for item in citations}
    known_evidence = {item.evidence_id for item in evidence}
    citation_refs = _string_list(data.get("citation_refs"))
    used_evidence = _string_list(data.get("used_evidence"))
    unknown_citations = sorted(set(citation_refs) - known_citations)
    unknown_evidence = sorted(set(used_evidence) - known_evidence)
    if unknown_citations:
        return FinalAnswer(
            status="failed",
            answer=None,
            citation_refs=citation_refs,
            confidence=0.0,
            limitations=[],
            used_evidence=used_evidence,
            error="unknown_citation_refs:" + ",".join(unknown_citations),
        )
    if unknown_evidence:
        return FinalAnswer(
            status="failed",
            answer=None,
            citation_refs=citation_refs,
            confidence=0.0,
            limitations=[],
            used_evidence=used_evidence,
            error="unknown_evidence_refs:" + ",".join(unknown_evidence),
        )
    if not citation_refs:
        return FinalAnswer(
            status="needs_user_input",
            answer=None,
            citation_refs=[],
            confidence=0.0,
            limitations=["missing_citation_refs"],
            used_evidence=used_evidence,
            error="missing_citation_refs",
        )
    return FinalAnswer(
        status="ok",
        answer=str(data["answer"]),
        citation_refs=citation_refs,
        confidence=_score(data.get("confidence", 0.0)),
        limitations=_string_list(data.get("limitations")),
        used_evidence=used_evidence,
        error=None,
    )


def _planner_fallback(run_id: str, reason: str) -> CandidateAction:
    return CandidateAction(
        action_id=f"act-{run_id}-planner-fallback",
        kind="ask_user",
        name=None,
        description="model planner fallback",
        score=0.0,
        payload={"question": f"Planner could not produce a safe action: {reason}"},
        reasons=[reason],
        side_effect_class="none",
    )


def _task_id(context: ContextBundle) -> str | None:
    value = context.state.get("task_id")
    return value if isinstance(value, str) else None


def _run_id(context: ContextBundle) -> str:
    value = context.state.get("run_id")
    return str(value or "")


def _score(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, parsed))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _preview(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
