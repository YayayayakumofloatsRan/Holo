from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from kernel_v3.contracts import Contract, JsonObject, JsonValue


@dataclass(frozen=True, kw_only=True)
class PublicFinanceBenchmarkSpec(Contract):
    benchmark_id: str
    display_name: str
    homepage_url: str
    dataset_url: str
    default_scoring: str
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PublicFinanceBenchmarkImportSummary(Contract):
    schema: str
    status: str
    benchmark: str
    input_path: str
    output_path: str
    manifest_path: str | None
    item_count: int
    skipped_count: int
    source_format: str
    source_url: str | None
    warnings: list[str] = field(default_factory=list)


PUBLIC_FINANCE_BENCHMARK_SPECS: dict[str, PublicFinanceBenchmarkSpec] = {
    "finance_agent_benchmark": PublicFinanceBenchmarkSpec(
        benchmark_id="finance_agent_benchmark",
        display_name="Finance Agent Benchmark",
        homepage_url="https://huggingface.co/datasets/vals-ai/finance_agent_benchmark",
        dataset_url="https://huggingface.co/datasets/vals-ai/finance_agent_benchmark",
        default_scoring="rubric_or_numeric",
        notes=[
            "Public viewer exposes a sample table; paper describes a larger finance research benchmark.",
            "Gold rubrics are for scoring only and must never enter the agent prompt.",
        ],
    ),
    "secque": PublicFinanceBenchmarkSpec(
        benchmark_id="secque",
        display_name="SECQUE",
        homepage_url="https://huggingface.co/datasets/nogabenyoash/SecQue",
        dataset_url="https://huggingface.co/datasets/nogabenyoash/SecQue",
        default_scoring="secque_judge_or_text",
        notes=[
            "SEC filing long-context benchmark with question, answer, context/supporting data, and filing metadata.",
            "Provided context can be used as benchmark context; answer and judge fields are scoring-only.",
        ],
    ),
    "financeqa": PublicFinanceBenchmarkSpec(
        benchmark_id="financeqa",
        display_name="FinanceQA",
        homepage_url="https://github.com/AfterQuery/FinanceQA",
        dataset_url="https://huggingface.co/datasets/AfterQuery/FinanceQA",
        default_scoring="text_or_llm_judge",
        notes=[
            "Question answering over company filing contexts.",
            "Chain-of-thought/reference reasoning fields are not included in model prompts.",
        ],
    ),
    "finqa": PublicFinanceBenchmarkSpec(
        benchmark_id="finqa",
        display_name="FinQA",
        homepage_url="https://finqasite.github.io/",
        dataset_url="https://finqasite.github.io/",
        default_scoring="program_or_numeric",
        notes=[
            "Financial numerical reasoning dataset with report text, tables, answer, and program-style reasoning.",
            "Reasoning/program annotations are scoring-only unless explicitly used by an evaluator outside agent prompts.",
        ],
    ),
}


def convert_public_finance_benchmark(
    *,
    benchmark: str,
    input_path: Path | str,
    output_path: Path | str,
    manifest_path: Path | str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> PublicFinanceBenchmarkImportSummary:
    benchmark_id = _normalize_benchmark_id(benchmark)
    spec = PUBLIC_FINANCE_BENCHMARK_SPECS.get(benchmark_id)
    if spec is None:
        supported = ", ".join(sorted(PUBLIC_FINANCE_BENCHMARK_SPECS))
        raise ValueError(f"unsupported public finance benchmark: {benchmark}. Supported: {supported}")

    source = Path(input_path)
    output = Path(output_path)
    records = _load_public_records(source)
    selected = records[max(0, int(offset)) :]
    if limit is not None:
        selected = selected[: max(0, int(limit))]

    normalized: list[JsonObject] = []
    skipped = 0
    warnings: list[str] = []
    for index, record in enumerate(selected, start=max(0, int(offset)) + 1):
        try:
            normalized.append(_normalize_public_finance_record(spec, record, index=index))
        except ValueError as exc:
            skipped += 1
            warnings.append(f"row {index}: {exc}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in normalized) + ("\n" if normalized else ""),
        encoding="utf-8",
    )

    manifest_output = Path(manifest_path) if manifest_path is not None else None
    summary = PublicFinanceBenchmarkImportSummary(
        schema="holo.kernel_v3.public_finance_benchmark_import.v1",
        status="ok",
        benchmark=spec.benchmark_id,
        input_path=str(source),
        output_path=str(output),
        manifest_path=str(manifest_output) if manifest_output is not None else None,
        item_count=len(normalized),
        skipped_count=skipped,
        source_format=_source_format(source),
        source_url=spec.dataset_url,
        warnings=warnings[:128],
    )
    if manifest_output is not None:
        manifest_output.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            **summary.to_dict(),
            "benchmark_spec": spec.to_dict(),
            "prompt_policy": {
                "gold_answer_in_prompt": False,
                "rubric_in_prompt": False,
                "reference_reasoning_in_prompt": False,
                "provided_context_in_prompt": True,
            },
            "normalized_schema": {
                "id": "stable benchmark item id",
                "question": "user-visible question",
                "gold_answer": "scoring-only reference answer",
                "evidence_excerpt": "scoring/audit evidence excerpt",
                "source": "public benchmark id",
                "type": "question/category type",
                "metadata": "provenance, prompt_context, source_refs, scoring notes",
            },
        }
        manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


def _normalize_public_finance_record(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int) -> JsonObject:
    if spec.benchmark_id == "finance_agent_benchmark":
        return _normalize_finance_agent_benchmark(spec, record, index=index)
    if spec.benchmark_id == "secque":
        return _normalize_secque(spec, record, index=index)
    if spec.benchmark_id == "financeqa":
        return _normalize_financeqa(spec, record, index=index)
    if spec.benchmark_id == "finqa":
        return _normalize_finqa(spec, record, index=index)
    raise ValueError(f"unsupported benchmark: {spec.benchmark_id}")


def _normalize_finance_agent_benchmark(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int) -> JsonObject:
    question = _text(_first_present(record, "Question", "question", "prompt"))
    if not question:
        raise ValueError("missing question")
    item_id = _item_id(record, index=index, prefix="fab")
    rubric = _text_or_none(_first_present(record, "Rubric", "rubric"))
    metadata: JsonObject = _base_metadata(spec, record)
    if rubric:
        metadata["rubric"] = rubric
    expert_time = _first_present(record, "Expert time (mins)", "expert_time_mins", "Expert Time")
    if expert_time not in (None, ""):
        metadata["expert_time_mins"] = _json_safe(expert_time)
    return _normalized_item(
        spec,
        item_id=item_id,
        question=question,
        gold_answer=_text_or_none(_first_present(record, "Answer", "answer", "gold_answer")),
        category=_text_or_none(_first_present(record, "Question Type", "question_type", "type")),
        evidence_excerpt=None,
        required_tools=["web_search", "sec_edgar"],
        metadata=metadata,
    )


def _normalize_secque(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int) -> JsonObject:
    question = _text(_first_present(record, "question", "Question", "query"))
    if not question:
        raise ValueError("missing question")
    context = _prompt_context(record, "context", "Context", "supporting_data", "supporting_context", "filing_context")
    source_refs = _source_refs(
        record,
        url_keys=("url", "filing_url", "source_url"),
        extra_keys=("accession", "page", "item", "section", "company", "ticker", "filing_type"),
    )
    metadata = _base_metadata(spec, record)
    if context:
        metadata["prompt_context"] = context
    if source_refs:
        metadata["source_refs"] = source_refs
    return _normalized_item(
        spec,
        item_id=_item_id(record, index=index, prefix="secque"),
        question=question,
        gold_answer=_text_or_none(_first_present(record, "answer", "Answer", "ground_truth", "gold_answer")),
        category=_text_or_none(_first_present(record, "question_type", "Question Type", "type", "category")),
        evidence_excerpt=_text_or_none(_first_present(record, "evidence", "supporting_evidence", "rationale_excerpt")),
        required_tools=["sec_filing_context"],
        metadata=metadata,
    )


def _normalize_financeqa(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int) -> JsonObject:
    question = _text(_first_present(record, "question", "Question", "query"))
    if not question:
        raise ValueError("missing question")
    context = _prompt_context(record, "context", "Context", "filing_context")
    source_refs = _source_refs(record, url_keys=("file_link", "url", "source_url"), extra_keys=("company", "file_name", "question_type"))
    metadata = _base_metadata(spec, record)
    if context:
        metadata["prompt_context"] = context
    if source_refs:
        metadata["source_refs"] = source_refs
    if _first_present(record, "chain_of_thought", "reasoning", "cot") is not None:
        metadata["reference_reasoning_available"] = True
        metadata["reference_reasoning_policy"] = "scoring_only_not_prompted"
    return _normalized_item(
        spec,
        item_id=_item_id(record, index=index, prefix="financeqa"),
        question=question,
        gold_answer=_text_or_none(_first_present(record, "answer", "Answer", "gold_answer")),
        category=_text_or_none(_first_present(record, "question_type", "Question Type", "type")),
        evidence_excerpt=None,
        required_tools=["provided_filing_context"],
        metadata=metadata,
    )


def _normalize_finqa(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int) -> JsonObject:
    qa = record.get("qa") if isinstance(record.get("qa"), dict) else {}
    question = _text(_first_present(record, "question", "Question", "query") or _first_present(qa, "question"))
    if not question:
        raise ValueError("missing question")
    context_parts: list[str] = []
    for key in ("pre_text", "post_text", "table", "context"):
        value = record.get(key)
        if value not in (None, "", []):
            context_parts.append(f"{key}: {_text(value)}")
    context = "\n\n".join(context_parts).strip()
    metadata = _base_metadata(spec, record)
    if context:
        metadata["prompt_context"] = context
    if _first_present(record, "program", "derivation") is not None or _first_present(qa, "program") is not None:
        metadata["reference_program_available"] = True
        metadata["reference_program_policy"] = "scoring_only_not_prompted"
    return _normalized_item(
        spec,
        item_id=_item_id(record, index=index, prefix="finqa"),
        question=question,
        gold_answer=_text_or_none(_first_present(record, "answer", "Answer", "gold_answer") or _first_present(qa, "answer")),
        category=_text_or_none(_first_present(record, "question_type", "type", "category")),
        evidence_excerpt=None,
        required_tools=["provided_report_context", "calculator"],
        metadata=metadata,
    )


def _normalized_item(
    spec: PublicFinanceBenchmarkSpec,
    *,
    item_id: str,
    question: str,
    gold_answer: str | None,
    category: str | None,
    evidence_excerpt: str | None,
    required_tools: list[str],
    metadata: JsonObject,
) -> JsonObject:
    return {
        "id": item_id,
        "question": question,
        "gold_answer": gold_answer,
        "evidence_excerpt": evidence_excerpt,
        "required_tools": required_tools,
        "type": category,
        "source": spec.benchmark_id,
        "metadata": metadata,
    }


def _load_public_records(path: Path) -> list[JsonObject]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if suffix in {".jsonl", ".ndjson"}:
        return [payload for payload in (_json_object(line) for line in text.splitlines() if line.strip()) if payload is not None]
    payload = json.loads(stripped)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "data", "items", "questions", "test", "train", "validation"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [_hf_row_payload(item) for item in rows if isinstance(item, dict)]
        if "question" in payload or "Question" in payload:
            return [payload]
    raise ValueError(f"unsupported public benchmark input format: {path}")


def _hf_row_payload(item: JsonObject) -> JsonObject:
    row = item.get("row")
    if isinstance(row, dict):
        return dict(row)
    return dict(item)


def _json_object(text: str) -> JsonObject | None:
    payload = json.loads(text)
    return dict(payload) if isinstance(payload, dict) else None


def _source_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "unknown"


def _normalize_benchmark_id(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fab": "finance_agent_benchmark",
        "financeagent": "finance_agent_benchmark",
        "finance_agent": "finance_agent_benchmark",
        "secque_benchmark": "secque",
        "finance_qa": "financeqa",
    }
    return aliases.get(normalized, normalized)


def _base_metadata(spec: PublicFinanceBenchmarkSpec, record: JsonObject) -> JsonObject:
    return {
        "benchmark": spec.benchmark_id,
        "benchmark_homepage": spec.homepage_url,
        "benchmark_dataset_url": spec.dataset_url,
        "default_scoring": spec.default_scoring,
        "raw_keys": sorted(str(key) for key in record.keys()),
    }


def _item_id(record: JsonObject, *, index: int, prefix: str) -> str:
    text = _text(_first_present(record, "id", "ID", "qid", "question_id", "benchmark_id", "item_id"))
    return text or f"{prefix}-{index:05d}"


def _prompt_context(record: JsonObject, *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value in (None, "", []):
            continue
        text = _text(value)
        if text:
            return text
    return None


def _source_refs(record: JsonObject, *, url_keys: tuple[str, ...], extra_keys: tuple[str, ...]) -> list[JsonObject]:
    ref: JsonObject = {}
    for key in url_keys:
        value = _text_or_none(record.get(key))
        if value:
            ref["url"] = value
            break
    for key in extra_keys:
        value = _text_or_none(record.get(key))
        if value:
            ref[key] = value
    return [ref] if ref else []


def _first_present(data: JsonObject, *keys: str) -> JsonValue:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _text_or_none(value: JsonValue | object) -> str | None:
    text = _text(value)
    return text or None


def _text(value: JsonValue | object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_safe(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)
