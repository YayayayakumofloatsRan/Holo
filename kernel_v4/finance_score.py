from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]


def load_json_object(path: str | Path) -> JsonObject:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def load_gold_annotations(path: str | Path) -> dict[str, JsonObject]:
    annotations: dict[str, JsonObject] = {}
    for index, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            continue
        item_id = _first_text(payload, ("item_id", "id", "question_id", "benchmark_id", "qid")) or f"item-{index}"
        annotations[item_id] = payload
    return annotations


def score_run_payload(payload: JsonObject, annotation: JsonObject) -> JsonObject:
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    item_id = str(task.get("task_id") or annotation.get("item_id") or "")
    answer = str(payload.get("answer") or "")
    expectations = _expected_numeric_annotations(annotation.get("expected_numeric"))
    matches = [_score_expected_numeric(answer, expectation, payload=payload, annotation=annotation) for expectation in expectations]
    numeric_scored_count = sum(1 for item in matches if item.get("scored") is True)
    numeric_hit_count = sum(1 for item in matches if item.get("passed") is True)
    run_completed = payload.get("status") == "completed"
    generic_failure_check = _check_no_generic_failure(answer)
    generic_failure = generic_failure_check.get("passed") is False
    qualitative_score = _score_source_grounded_qualitative(payload=payload, annotation=annotation, answer=answer)
    qualitative_scored = bool(qualitative_score.get("scored"))
    numeric_passed = bool(
        run_completed
        and numeric_scored_count
        and numeric_hit_count == numeric_scored_count
        and not generic_failure
    )
    qualitative_passed = bool(run_completed and qualitative_scored and qualitative_score.get("passed") is True)
    passed = numeric_passed or (not numeric_scored_count and qualitative_passed)
    reason = _score_reason(
        run_completed=run_completed,
        numeric_passed=numeric_passed,
        matches=matches,
        qualitative_score=qualitative_score,
        generic_failure=generic_failure,
    )
    return {
        "schema": "holo.kernel_v4.finance_score.v1",
        "item_id": item_id,
        "source": annotation.get("source"),
        "workflow_type": annotation.get("workflow_type"),
        "run_status": payload.get("status"),
        "passed": passed,
        "reason": reason,
        "numeric_scored_count": numeric_scored_count,
        "numeric_unscored_count": sum(1 for item in matches if item.get("scored") is False),
        "numeric_hit_count": numeric_hit_count,
        "numeric_matches": matches,
        "qualitative_score": qualitative_score,
        "gold_reference_material_used_for_scoring_only": True,
        "gold_reference_material_in_model_context": bool(payload.get("gold_reference_material_included")),
        "capability_claim": False,
    }


def score_run_file(*, run_output: str | Path, gold_jsonl: str | Path, item_id: str | None = None) -> JsonObject:
    payload = load_json_object(run_output)
    annotations = load_gold_annotations(gold_jsonl)
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    resolved_item_id = item_id or str(task.get("task_id") or "")
    if not resolved_item_id:
        raise ValueError("item id is required when run output has no task.task_id")
    annotation = annotations.get(resolved_item_id)
    if annotation is None:
        raise KeyError(f"gold annotation not found for item_id={resolved_item_id}")
    score = score_run_payload(payload, annotation)
    return {
        "schema": "holo.kernel_v4.finance_score_file.v1",
        "run_output": str(run_output),
        "gold_jsonl": str(gold_jsonl),
        "score": score,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Post-run score one Kernel v4 finance live output against a gold sidecar.")
    parser.add_argument("--run-output", required=True)
    parser.add_argument("--gold-jsonl", required=True)
    parser.add_argument("--item-id", default=None)
    parser.add_argument("--output", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = score_run_file(run_output=args.run_output, gold_jsonl=args.gold_jsonl, item_id=args.item_id)
    except Exception as exc:  # noqa: BLE001 - scorer should return a structured setup failure.
        payload = {
            "schema": "holo.kernel_v4.finance_score_file.v1",
            "status": "failed",
            "reason": f"setup_error:{type(exc).__name__}:{str(exc)[:500]}",
            "capability_claim": False,
        }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    score = payload.get("score") if isinstance(payload.get("score"), dict) else {}
    return 0 if score.get("passed") is True else 1


def _expected_numeric_annotations(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    result: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        expected = _optional_float(item.get("value"))
        if expected is None:
            continue
        result.append(
            {
                "name": _first_text(item, ("name",)) or f"numeric-{len(result) + 1}",
                "value": expected,
                "tolerance": _optional_float(item.get("tolerance")),
            }
        )
    return result


def _score_expected_numeric(
    answer: str,
    expectation: JsonObject,
    *,
    payload: JsonObject,
    annotation: JsonObject,
) -> JsonObject:
    expected = _optional_float(expectation.get("value"))
    tolerance = _optional_float(expectation.get("tolerance"))
    values = _extract_numeric_values(answer)
    if expected is None:
        return {"name": expectation.get("name"), "scored": False, "passed": None, "expected": None, "tolerance": None, "matched_value": None, "values": values[:32]}
    if _is_likely_entity_name_numeric_noise(expected, payload=payload, annotation=annotation):
        return {
            "name": expectation.get("name"),
            "scored": False,
            "passed": None,
            "expected": expected,
            "tolerance": tolerance,
            "matched_value": None,
            "values": values[:32],
            "reason": "likely_entity_name_numeric_noise",
        }
    if _is_likely_year_suffix_numeric_noise(expected, payload=payload, annotation=annotation):
        return {
            "name": expectation.get("name"),
            "scored": False,
            "passed": None,
            "expected": expected,
            "tolerance": tolerance,
            "matched_value": None,
            "values": values[:32],
            "reason": "likely_year_suffix_numeric_noise",
        }
    candidates = _expected_numeric_candidates(expected, tolerance)
    matched = None
    matched_expected = None
    matched_tolerance = None
    matched_normalization = None
    close_values: list[tuple[float, float, float, float, str | None]] = []
    for candidate_expected, candidate_tolerance, normalization in candidates:
        close_values.extend(
            (abs(value - candidate_expected), value, candidate_expected, candidate_tolerance, normalization)
            for value in values
            if abs(value - candidate_expected) <= candidate_tolerance
        )
    if close_values:
        _, matched, matched_expected, matched_tolerance, matched_normalization = min(close_values, key=lambda item: item[0])
    tol = abs(tolerance) if tolerance is not None else max(abs(expected) * 0.01, 1e-9)
    return {
        "name": expectation.get("name"),
        "scored": True,
        "passed": matched is not None,
        "expected": expected,
        "tolerance": tol,
        "matched_value": matched,
        "matched_expected": matched_expected,
        "matched_tolerance": matched_tolerance,
        **({"expected_normalization": matched_normalization} if matched_normalization else {}),
        "values": values[:32],
        "expected_candidates": [
            {"expected": item[0], "tolerance": item[1], **({"normalization": item[2]} if item[2] else {})}
            for item in candidates[:8]
        ],
    }


def _is_likely_entity_name_numeric_noise(expected: float, *, payload: JsonObject, annotation: JsonObject) -> bool:
    # The source gold sidecar is generated from benchmark prose. Company names
    # such as "3M" can be incorrectly normalized as 3,000,000. Keep the scorer
    # honest by marking that artifact as unscored instead of treating it as a
    # required finance fact.
    if abs(expected - 3_000_000.0) > 1e-6:
        return False
    context = _scoring_context_text(payload, annotation)
    return bool(re.search(r"\b3M\b", context))


def _is_likely_year_suffix_numeric_noise(expected: float, *, payload: JsonObject, annotation: JsonObject) -> bool:
    if expected < 20 or expected > 30 or abs(expected - round(expected)) > 1e-9:
        return False
    context = _scoring_context_text(payload, annotation)
    full_year = f"20{int(expected):02d}"
    apostrophe_year = rf"(?:FY|Q[1-4]|Jun|June|Dec|December|Mar|March|Sep|Sept|September)?\s*['’]{int(expected):02d}\b"
    return full_year in context or bool(re.search(apostrophe_year, context, flags=re.IGNORECASE))


def _expected_numeric_candidates(expected: float, tolerance: float | None) -> list[tuple[float, float, str | None]]:
    base_tolerance = abs(tolerance) if tolerance is not None else max(abs(expected) * 0.01, 1e-9)
    candidates: list[tuple[float, float, str | None]] = [(expected, base_tolerance, None)]
    if expected < 0:
        _append_unique_candidate(candidates, abs(expected), base_tolerance, "expected_abs_magnitude")
    # Some generated sidecars normalize prose decimals or B/M/K shorthand into
    # raw magnitude incorrectly, e.g. 0.96 -> 960,000,000. Score against the
    # model answer after trying common financial display scales.
    if abs(expected) >= 1_000:
        for label, scale in (("billions", 1_000_000_000.0), ("millions", 1_000_000.0), ("thousands", 1_000.0)):
            scaled = expected / scale
            if abs(scaled) > 1_000_000:
                continue
            scaled_tolerance = base_tolerance / scale
            if scaled_tolerance <= 0:
                scaled_tolerance = max(abs(scaled) * 0.01, 1e-9)
            _append_unique_candidate(candidates, scaled, scaled_tolerance, f"expected_scaled_from_{label}")
    return candidates


def _append_unique_candidate(
    candidates: list[tuple[float, float, str | None]],
    expected: float,
    tolerance: float,
    normalization: str,
) -> None:
    for existing, _, _ in candidates:
        if abs(existing - expected) <= max(abs(expected) * 1e-12, 1e-12):
            return
    candidates.append((expected, tolerance, normalization))


def _scoring_context_text(payload: JsonObject, annotation: JsonObject) -> str:
    parts = [str(payload.get("answer") or ""), str(annotation.get("item_id") or "")]
    task = payload.get("task")
    if isinstance(task, dict):
        parts.extend(str(value) for value in task.values() if isinstance(value, (str, int, float)))
    for key in ("question", "gold_answer", "answer", "category"):
        value = annotation.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def _extract_numeric_values(text: str) -> list[float]:
    values: list[float] = []
    seen: set[float] = set()
    pattern = re.compile(r"(?P<prefix>[$€£])?\s*(?P<value>-?\(?\d[\d,]*(?:\.\d+)?\)?)(?P<percent>\s*%)?")
    for match in pattern.finditer(text):
        raw = match.group("value").replace(",", "").strip()
        negative = raw.startswith("(") and raw.endswith(")")
        raw = raw.strip("()")
        try:
            value = float(raw)
        except ValueError:
            continue
        if negative:
            value = -value
        for candidate in _candidate_scales(value, is_percent=bool(match.group("percent"))):
            if candidate in seen:
                continue
            seen.add(candidate)
            values.append(candidate)
    return values


def _candidate_scales(value: float, *, is_percent: bool) -> list[float]:
    values = [value]
    if value < 0:
        values.append(abs(value))
    if is_percent:
        values.append(value / 100.0)
        if value < 0:
            values.append(abs(value) / 100.0)
    return values


def _failure_reason(run_completed: bool, matches: list[JsonObject]) -> str:
    if not run_completed:
        return "run_not_completed"
    if not matches:
        return "no_expected_numeric"
    return "numeric_outside_tolerance"


def _score_reason(
    *,
    run_completed: bool,
    numeric_passed: bool,
    matches: list[JsonObject],
    qualitative_score: JsonObject,
    generic_failure: bool = False,
) -> str:
    if numeric_passed:
        return "numeric_within_tolerance"
    if run_completed and generic_failure:
        return "generic_failure_final_answer"
    if matches:
        return _failure_reason(run_completed, matches)
    if qualitative_score.get("passed") is True:
        return str(qualitative_score.get("reason") or "source_grounded_qualitative_pass")
    if qualitative_score.get("scored") is True:
        return str(qualitative_score.get("reason") or "source_grounded_qualitative_failed")
    return _failure_reason(run_completed, matches)


def _score_source_grounded_qualitative(*, payload: JsonObject, annotation: JsonObject, answer: str) -> JsonObject:
    if not _source_grounded_qualitative_applicable(annotation):
        return {"scored": False, "passed": None, "reason": "not_source_grounded_qualitative"}
    checks = [
        _check_answer_present(answer),
        _check_no_generic_failure(answer),
    ]
    dealbreakers = _string_list(annotation.get("dealbreakers"))
    if "citation_required" in {item.lower() for item in dealbreakers}:
        checks.append(_check_citation_signal(payload=payload, annotation=annotation, answer=answer))
    if "synthesis_gate_pass_required" in {item.lower() for item in dealbreakers}:
        checks.append(_check_synthesis_signal(answer))
    evidence_policy = annotation.get("evidence_policy") if isinstance(annotation.get("evidence_policy"), dict) else {}
    for family in _string_list(evidence_policy.get("required_source_families")):
        checks.append(_check_source_family_supported(family, payload=payload, annotation=annotation, answer=answer))
    required_sources = _string_list(annotation.get("required_sources"))
    doc_type_terms = [term for term in required_sources if term.lower() in {"8k", "8-k", "10k", "10-k", "10q", "10-q", "earnings"}]
    if doc_type_terms:
        checks.append(_check_any_required_doc_type(doc_type_terms, answer=answer))
    passed = all(check.get("passed") is True for check in checks)
    return {
        "schema": "holo.kernel_v4.source_grounded_qualitative_score.v1",
        "scored": True,
        "passed": passed,
        "reason": "source_grounded_qualitative_pass" if passed else "source_grounded_qualitative_failed",
        "checks": checks,
    }


def _source_grounded_qualitative_applicable(annotation: JsonObject) -> bool:
    if str(annotation.get("workflow_type") or "").lower() == "source_grounded_research":
        return True
    if annotation.get("dealbreakers") or annotation.get("evidence_policy") or annotation.get("required_sources"):
        return True
    return False


def _check_answer_present(answer: str) -> JsonObject:
    text = answer.strip()
    return {
        "name": "answer_present",
        "passed": len(text) >= 80,
        "observed_chars": len(text),
    }


def _check_no_generic_failure(answer: str) -> JsonObject:
    lowered = answer.lower()
    bad_phrases = (
        "i cannot determine",
        "i can't determine",
        "cannot determine",
        "can't determine",
        "could not determine",
        "cannot be determined",
        "not enough information",
        "unable to answer",
        "cannot answer",
        "can't answer",
        "cannot be answered",
        "unable to compute",
        "unable to calculate",
        "cannot compute",
        "can't compute",
        "could not compute",
        "cannot calculate",
        "can't calculate",
        "could not calculate",
        "cannot be calculated",
        "unable to retrieve",
        "could not retrieve",
        "insufficient information",
        "no answer",
    )
    matched = [phrase for phrase in bad_phrases if phrase in lowered]
    return {
        "name": "no_generic_failure",
        "passed": not matched,
        "matched_phrases": matched,
    }


def _check_citation_signal(*, payload: JsonObject, annotation: JsonObject, answer: str) -> JsonObject:
    haystack = _source_haystack(payload=payload, annotation=annotation, answer=answer)
    signals = ("sec", "form 8-k", "8-k", "form 10-k", "10-k", "form 10-q", "10-q", "filing", "annual report", "current report", "source", "artifact", "http")
    matched = [signal for signal in signals if signal in haystack]
    return {
        "name": "citation_signal",
        "passed": bool(matched),
        "matched_signals": matched[:8],
    }


def _check_synthesis_signal(answer: str) -> JsonObject:
    text = answer.strip()
    lowered = text.lower()
    has_direct_answer = bool(
        re.search(
            r"\b(answer|in summary|the key|therefore|conclusion|based on|from\b|here are|the company|"
            r"major products|major services|reportable segments)\b",
            lowered,
        )
        or re.search(r"(?is)^\s*(?:[#>*_\-\s]*\**)?(?:yes|no)\b", text)
        or re.search(r"(?is)\b(?:yes|no),?\s+[^.\n]{0,120}\b(?:had|has|was|were|is|are|did|does|do)\b", text)
    )
    bullet_rows = len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.)]|\*\*)", text))
    table_rows = len(re.findall(r"(?m)^\s*\|[^|\n]+(?:\|[^|\n]+)+\|\s*$", text))
    has_structured_list = bullet_rows >= 3 or table_rows >= 3
    return {
        "name": "synthesis_signal",
        "passed": len(text) >= 120 and (has_direct_answer or has_structured_list),
        "has_direct_answer_signal": has_direct_answer,
        "has_structured_list_signal": has_structured_list,
    }


def _check_source_family_supported(family: str, *, payload: JsonObject, annotation: JsonObject, answer: str) -> JsonObject:
    normalized = family.lower().strip()
    haystack = _source_haystack(payload=payload, annotation=annotation, answer=answer)
    tools = _tool_names(payload)
    document_tool_used = any(tool.startswith("document.") or tool.startswith("artifact.") for tool in tools)
    sec_tool_used = any(tool.startswith("sec.edgar.") for tool in tools)
    company_primary_source_used = document_tool_used and _annotation_allows_company_primary_source(annotation)
    if normalized == "sec_filings":
        passed = (
            sec_tool_used
            or company_primary_source_used
            or bool(re.search(r"\b(sec|form\s+8-k|8-k|form\s+10-k|10-k|form\s+10-q|10-q|filing)\b", haystack))
        )
    elif normalized == "company_filing":
        passed = company_primary_source_used or document_tool_used or bool(re.search(r"\b(filing|annual report|current report|10-k|10-q|8-k|earnings|press release)\b", haystack))
    else:
        passed = normalized in haystack
    return {
        "name": f"required_source_family:{family}",
        "passed": passed,
        "tools": tools[:16],
        "company_primary_source_used": company_primary_source_used,
    }


def _check_any_required_doc_type(terms: list[str], *, answer: str) -> JsonObject:
    lowered = answer.lower()
    matched = [term for term in terms if _source_term_present(term, lowered)]
    return {
        "name": "required_doc_type_signal",
        "passed": bool(matched),
        "required_terms": terms,
        "matched_terms": matched,
    }


def _source_term_present(term: str, lowered_text: str) -> bool:
    normalized = term.lower().replace("_", "-")
    variants = {normalized, normalized.replace("-", ""), normalized.replace("k", "-k"), normalized.replace("q", "-q")}
    if normalized == "earnings":
        variants.update({"earnings release", "press release", "results release", "quarterly results", "annual results"})
    return any(variant and variant in lowered_text for variant in variants)


def _annotation_allows_company_primary_source(annotation: JsonObject) -> bool:
    required_sources = [item.lower() for item in _string_list(annotation.get("required_sources"))]
    required_urls = [item.lower() for item in _string_list(annotation.get("required_source_urls"))]
    if any(item in {"company_filing", "earnings"} for item in required_sources):
        return True
    if any("press" in item or "earnings" in item or "investor" in item for item in required_sources):
        return True
    for url in required_urls:
        if not url:
            continue
        if "sec.gov" not in url:
            return True
    return False


def _source_haystack(*, payload: JsonObject, annotation: JsonObject, answer: str) -> str:
    parts = [answer]
    for key in ("required_sources", "required_source_urls"):
        parts.extend(_string_list(annotation.get(key)))
    trace = payload.get("tool_trace_summary") if isinstance(payload.get("tool_trace_summary"), dict) else {}
    by_tool = trace.get("by_tool") if isinstance(trace.get("by_tool"), dict) else {}
    parts.extend(str(tool) for tool in by_tool)
    return "\n".join(parts).lower()


def _tool_names(payload: JsonObject) -> list[str]:
    trace = payload.get("tool_trace_summary") if isinstance(payload.get("tool_trace_summary"), dict) else {}
    by_tool = trace.get("by_tool") if isinstance(trace.get("by_tool"), dict) else {}
    return sorted(str(tool) for tool in by_tool)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def _optional_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
