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
    mode: str | None = None
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
    "finance_agent_v2_public": PublicFinanceBenchmarkSpec(
        benchmark_id="finance_agent_v2_public",
        display_name="Finance Agent v2 public set",
        homepage_url="https://www.vals.ai/benchmarks/fabv2",
        dataset_url="https://raw.githubusercontent.com/vals-ai/finance-agent-v2/main/data/public.txt",
        default_scoring="behavioral_without_public_gold",
        notes=[
            "Public development questions for Finance Agent v2; no gold answer is included in the agent prompt.",
            "Use behavior metrics such as calculator usage, numeric verifier status, citation coverage, and loop budget.",
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
    "financebench": PublicFinanceBenchmarkSpec(
        benchmark_id="financebench",
        display_name="FinanceBench",
        homepage_url="https://github.com/patronus-ai/financebench",
        dataset_url="https://huggingface.co/datasets/PatronusAI/financebench",
        default_scoring="gold_answer_and_evidence",
        notes=[
            "Gold-backed 150-question financial filing QA benchmark from PatronusAI.",
            "Answer and justification fields are scoring-only and must never enter the agent prompt.",
            "Use oracle_evidence, doc_retrieval, or question_only import modes to separate evidence use from retrieval ability.",
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
    mode: str | None = None,
) -> PublicFinanceBenchmarkImportSummary:
    benchmark_id = _normalize_benchmark_id(benchmark)
    spec = PUBLIC_FINANCE_BENCHMARK_SPECS.get(benchmark_id)
    if spec is None:
        supported = ", ".join(sorted(PUBLIC_FINANCE_BENCHMARK_SPECS))
        raise ValueError(f"unsupported public finance benchmark: {benchmark}. Supported: {supported}")

    source = Path(input_path)
    output = Path(output_path)
    records = _load_public_records(source, benchmark_id=spec.benchmark_id)
    selected = records[max(0, int(offset)) :]
    if limit is not None:
        selected = selected[: max(0, int(limit))]

    normalized: list[JsonObject] = []
    skipped = 0
    warnings: list[str] = []
    for index, record in enumerate(selected, start=max(0, int(offset)) + 1):
        try:
            normalized.append(_normalize_public_finance_record(spec, record, index=index, mode=mode))
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
        mode=_effective_import_mode(spec.benchmark_id, mode),
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
                "provided_context_in_prompt": _provided_context_in_prompt(spec.benchmark_id, mode),
                "import_mode": _effective_import_mode(spec.benchmark_id, mode),
            },
            "normalized_schema": {
                "id": "stable benchmark item id",
                "question": "user-visible question",
                "gold_answer": "scoring-only reference answer",
                "evidence_excerpt": "scoring/audit evidence excerpt",
                "source": "public benchmark id",
                "type": "question/category type",
                "metadata": "provenance, prompt_context, source_refs, workflow annotation, scoring notes",
                "workflow_annotation": [
                    "metadata.workflow_type",
                    "metadata.required_slots",
                    "metadata.evidence_policy",
                    "metadata.required_transforms",
                    "metadata.dealbreakers",
                    "metadata.expected_trace",
                    "metadata.failure_taxonomy",
                ],
            },
        }
        manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


def _normalize_public_finance_record(
    spec: PublicFinanceBenchmarkSpec,
    record: JsonObject,
    *,
    index: int,
    mode: str | None,
) -> JsonObject:
    if spec.benchmark_id == "finance_agent_benchmark":
        return _normalize_finance_agent_benchmark(spec, record, index=index)
    if spec.benchmark_id == "finance_agent_v2_public":
        return _normalize_finance_agent_v2_public(spec, record, index=index)
    if spec.benchmark_id == "secque":
        return _normalize_secque(spec, record, index=index, mode=mode)
    if spec.benchmark_id == "financeqa":
        return _normalize_financeqa(spec, record, index=index, mode=mode)
    if spec.benchmark_id == "finqa":
        return _normalize_finqa(spec, record, index=index, mode=mode)
    if spec.benchmark_id == "financebench":
        return _normalize_financebench(spec, record, index=index, mode=mode)
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


def _normalize_finance_agent_v2_public(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int) -> JsonObject:
    question = _text(_first_present(record, "question", "Question", "prompt", "text"))
    if not question:
        raise ValueError("missing question")
    category = _finance_agent_v2_category(question)
    workflow = _finance_agent_v2_workflow_annotation(question)
    metadata: JsonObject = _base_metadata(spec, record)
    metadata.update(
        {
            "category": category,
            **workflow,
            "requires": _finance_agent_v2_required_capabilities(question),
            "expected_capabilities": ["retrieval.run", "calculator.compute", "finance.verify_numeric"],
            "gold_policy": "public_set_has_no_gold_answer",
            "evaluation_policy": "score behavior and numeric verification until official rubric/gold is available",
        }
    )
    return _normalized_item(
        spec,
        item_id=_item_id(record, index=index, prefix="fabv2-public"),
        question=question,
        gold_answer=None,
        category=category,
        evidence_excerpt=None,
        required_tools=["retrieval.run", "calculator.compute", "finance.verify_numeric"],
        metadata=metadata,
    )


def _normalize_secque(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int, mode: str | None) -> JsonObject:
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
    import_mode = _effective_import_mode(spec.benchmark_id, mode)
    metadata["import_mode"] = import_mode
    if context and import_mode != "question_only":
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


def _normalize_financeqa(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int, mode: str | None) -> JsonObject:
    question = _text(_first_present(record, "question", "Question", "query"))
    if not question:
        raise ValueError("missing question")
    context = _prompt_context(record, "context", "Context", "filing_context")
    source_refs = _source_refs(record, url_keys=("file_link", "url", "source_url"), extra_keys=("company", "file_name", "question_type"))
    metadata = _base_metadata(spec, record)
    import_mode = _effective_import_mode(spec.benchmark_id, mode)
    metadata["import_mode"] = import_mode
    if context and import_mode != "question_only":
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


def _normalize_finqa(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int, mode: str | None) -> JsonObject:
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
    import_mode = _effective_import_mode(spec.benchmark_id, mode)
    metadata["import_mode"] = import_mode
    if context and import_mode != "question_only":
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


def _normalize_financebench(spec: PublicFinanceBenchmarkSpec, record: JsonObject, *, index: int, mode: str | None) -> JsonObject:
    question = _text(_first_present(record, "question", "Question", "query", "prompt"))
    if not question:
        raise ValueError("missing question")
    import_mode = _effective_import_mode(spec.benchmark_id, mode)
    financebench_id = _text_or_none(
        _first_present(record, "financebench_id", "FinanceBench ID", "id", "ID", "question_id", "benchmark_id")
    )
    company = _text_or_none(_first_present(record, "company", "Company"))
    doc_name = _text_or_none(_first_present(record, "doc_name", "document_name", "Document Name", "doc"))
    question_type = _text_or_none(_first_present(record, "question_type", "Question Type", "type", "category"))
    question_reasoning = _text_or_none(_first_present(record, "question_reasoning", "Question Reasoning", "reasoning"))
    answer = _text_or_none(_first_present(record, "answer", "Answer", "gold_answer", "reference_answer"))
    justification = _text_or_none(_first_present(record, "justification", "Justification", "rationale", "reference_reasoning"))
    evidence = _text_or_none(_first_present(record, "evidence", "Evidence", "supporting_evidence", "evidence_text"))
    gics_sector = _text_or_none(_first_present(record, "gics_sector", "GICS Sector", "sector"))
    doc_type = _text_or_none(_first_present(record, "doc_type", "Document Type", "filing_type"))
    doc_period = _text_or_none(_first_present(record, "doc_period", "Document Period", "period", "filing_period"))
    doc_link = _text_or_none(_first_present(record, "doc_link", "Document Link", "url", "source_url", "filing_url"))
    metadata = _base_metadata(spec, record)
    metadata.update(
        {
            "import_mode": import_mode,
            "financebench_id": financebench_id,
            "company": company,
            "doc_name": doc_name,
            "question_type": question_type,
            "question_reasoning": question_reasoning,
            "gics_sector": gics_sector,
            "doc_type": doc_type,
            "doc_period": doc_period,
            "doc_link": doc_link,
            "reference_justification_available": justification is not None,
            "reference_justification_policy": "scoring_only_not_prompted",
            "reference_evidence_available": evidence is not None,
            "reference_evidence_policy": "prompted_as_oracle_evidence" if import_mode == "oracle_evidence" else "scoring_only_not_prompted",
            "gold_policy": "answer_and_justification_scoring_only",
        }
    )
    workflow = _financebench_workflow_annotation(
        question=question,
        question_type=question_type,
        question_reasoning=question_reasoning,
        doc_type=doc_type,
    )
    metadata.update(workflow)
    source_refs = _financebench_source_refs(
        company=company,
        doc_name=doc_name,
        doc_type=doc_type,
        doc_period=doc_period,
        doc_link=doc_link,
        gics_sector=gics_sector,
    )
    if source_refs:
        metadata["source_refs"] = source_refs
    prompt_context = _financebench_prompt_context(
        mode=import_mode,
        company=company,
        doc_name=doc_name,
        doc_type=doc_type,
        doc_period=doc_period,
        doc_link=doc_link,
        evidence=evidence,
    )
    if prompt_context:
        metadata["prompt_context"] = prompt_context
    required_tools = ["retrieval.run", "calculator.compute", "finance.verify_numeric"]
    if import_mode == "oracle_evidence":
        required_tools = ["provided_evidence_context", "calculator.compute", "finance.verify_numeric"]
    return _normalized_item(
        spec,
        item_id=financebench_id or _item_id(record, index=index, prefix="financebench"),
        question=question,
        gold_answer=answer,
        category=question_type or str(workflow.get("workflow_type") or "financebench"),
        evidence_excerpt=evidence,
        required_tools=required_tools,
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


def _load_public_records(path: Path, *, benchmark_id: str | None = None) -> list[JsonObject]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if benchmark_id == "finance_agent_v2_public" or suffix == ".txt":
        return [
            {"id": f"fabv2-public-{index:05d}", "question": line.strip()}
            for index, line in enumerate(text.splitlines(), start=1)
            if line.strip()
        ]
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
        "fabv2": "finance_agent_v2_public",
        "finance_agent_v2": "finance_agent_v2_public",
        "finance_agent_v2_public": "finance_agent_v2_public",
        "financeagentv2": "finance_agent_v2_public",
        "secque_benchmark": "secque",
        "finance_qa": "financeqa",
        "finance_bench": "financebench",
        "financebench150": "financebench",
        "financebench_150": "financebench",
        "patronusai_financebench": "financebench",
        "patronus_financebench": "financebench",
    }
    return aliases.get(normalized, normalized)


def _effective_import_mode(benchmark_id: str, mode: str | None) -> str:
    requested = str(mode or "").strip().lower().replace("-", "_").replace(" ", "_")
    if benchmark_id == "financebench":
        if not requested:
            return "oracle_evidence"
        aliases = {"oracle": "oracle_evidence", "evidence": "oracle_evidence", "doc": "doc_retrieval", "document": "doc_retrieval"}
        normalized = aliases.get(requested, requested)
        if normalized not in {"oracle_evidence", "doc_retrieval", "question_only"}:
            raise ValueError("unsupported FinanceBench import mode: " + str(mode))
        return normalized
    if benchmark_id in {"secque", "financeqa", "finqa"}:
        if not requested:
            return "oracle_context"
        aliases = {"oracle": "oracle_context", "context": "oracle_context"}
        normalized = aliases.get(requested, requested)
        if normalized not in {"oracle_context", "question_only"}:
            raise ValueError(f"unsupported {benchmark_id} import mode: {mode}")
        return normalized
    return requested or "question_only"


def _provided_context_in_prompt(benchmark_id: str, mode: str | None) -> bool:
    effective = _effective_import_mode(benchmark_id, mode)
    return effective in {"oracle_context", "oracle_evidence", "doc_retrieval"}


def _financebench_source_refs(
    *,
    company: str | None,
    doc_name: str | None,
    doc_type: str | None,
    doc_period: str | None,
    doc_link: str | None,
    gics_sector: str | None,
) -> list[JsonObject]:
    ref: JsonObject = {}
    if doc_link:
        ref["url"] = doc_link
    for key, value in (
        ("company", company),
        ("doc_name", doc_name),
        ("doc_type", doc_type),
        ("doc_period", doc_period),
        ("gics_sector", gics_sector),
    ):
        if value:
            ref[key] = value
    return [ref] if ref else []


def _financebench_prompt_context(
    *,
    mode: str,
    company: str | None,
    doc_name: str | None,
    doc_type: str | None,
    doc_period: str | None,
    doc_link: str | None,
    evidence: str | None,
) -> str | None:
    if mode == "question_only":
        return None
    lines: list[str] = []
    if mode == "doc_retrieval":
        lines.append("FinanceBench target document metadata follows. Use it to acquire evidence; it is not answer evidence by itself.")
    elif mode == "oracle_evidence":
        lines.append("FinanceBench provided evidence follows. Use it as source evidence; do not treat the reference answer or justification as prompt context.")
    for label, value in (
        ("Company", company),
        ("Document", doc_name),
        ("Document type", doc_type),
        ("Document period", doc_period),
        ("Document link", doc_link),
    ):
        if value:
            lines.append(f"{label}: {value}")
    if mode == "oracle_evidence" and evidence:
        lines.append("")
        lines.append("Provided evidence excerpt:")
        lines.append(evidence)
    return "\n".join(lines).strip() or None


def _financebench_workflow_annotation(
    *,
    question: str,
    question_type: str | None,
    question_reasoning: str | None,
    doc_type: str | None,
) -> JsonObject:
    combined = " ".join(item for item in (question, question_type or "", question_reasoning or "", doc_type or "") if item)
    workflow = dict(_finance_agent_v2_workflow_annotation(combined))
    workflow.setdefault("workflow_type", "source_grounded_research")
    workflow.setdefault("required_slots", ["entity", "period", "source"])
    workflow.setdefault("required_transforms", [])
    workflow.setdefault("dealbreakers", ["citation_required", "synthesis_gate_pass_required"])
    workflow.setdefault(
        "expected_trace",
        ["retrieval.run", "claim_ledger", "slot_frame", "transform_plan", "verifier_gate", "synthesis_gate", "citation"],
    )
    workflow.setdefault("failure_taxonomy", ["source_acquisition", "claim_extraction", "synthesis_gate"])
    policy = workflow.get("evidence_policy") if isinstance(workflow.get("evidence_policy"), dict) else {}
    required_families = list(policy.get("required_source_families") or ["provided_evidence_or_company_filing"])
    if doc_type and "company_filing" not in required_families:
        required_families.append("company_filing")
    workflow["evidence_policy"] = {
        **policy,
        "required_source_families": required_families,
        "authority": policy.get("authority") or "benchmark_evidence_or_primary_filing",
    }
    return workflow


def _finance_agent_v2_category(question: str) -> str:
    text = question.lower()
    if any(marker in text for marker in ("dcf", "discounted cash flow", "lbo", "irr", "moic")):
        return "financial_modeling"
    if any(marker in text for marker in ("transaction", "acquisition", "merger", "purchase price", "enterprise value")):
        return "transaction_analysis"
    if any(marker in text for marker in ("cagr", "basis points", "bps", "margin", "multiple", "ratio", "dio", "coverage")):
        return "numeric_reasoning"
    if any(marker in text for marker in ("8-k", "10-k", "10-q", "filing", "disclosure")):
        return "filing_research"
    return "finance_research"


def _finance_agent_v2_required_capabilities(question: str) -> list[str]:
    text = question.lower()
    capabilities = ["sec_filings", "retrieval"]
    if any(marker in text for marker in ("calculate", "cagr", "basis points", "bps", "dcf", "lbo", "irr", "moic", "multiple", "ratio", "margin", "dio")):
        capabilities.extend(["calculator", "numeric_verifier"])
    if any(marker in text for marker in ("share price", "closing share", "market prices", "stock price")):
        capabilities.append("market_data")
    return sorted(set(capabilities))


def _finance_agent_v2_workflow_annotation(question: str) -> JsonObject:
    text = question.lower()
    base_trace = [
        "retrieval.run",
        "claim_ledger",
        "slot_frame",
        "transform_plan",
        "verifier_gate",
        "synthesis_gate",
        "citation",
    ]
    policy: JsonObject = {
        "required_source_families": ["sec_filings"],
        "forbidden_source_families": ["generic_search_only"],
        "authority": "primary_or_structured",
    }
    if any(marker in text for marker in ("dio", "inventory outstanding", "inventory efficiency")):
        return {
            "workflow_type": "multi_entity_compute_compare",
            "required_slots": ["entity_a", "entity_b", "period", "inventory_begin", "inventory_end", "cogs", "fiscal_days"],
            "evidence_policy": {**policy, "required_terms": ["inventory", "cost of revenue"]},
            "required_transforms": ["dio", "difference"],
            "dealbreakers": ["citation_required", "calculator_trace_required", "no_missing_slots", "synthesis_gate_pass_required"],
            "expected_trace": [*base_trace, "calculator.compute", "finance_numeric_verification"],
            "failure_taxonomy": ["source_acquisition", "slot_filling", "formula_binding", "unit_period_mismatch"],
        }
    if any(marker in text for marker in ("adjusted ebitda", "add-back", "addback", "bridge")):
        return {
            "workflow_type": "reconciliation",
            "required_slots": ["entity", "period", "base_metric", "adjustment_items", "reconciled_metric", "source_table"],
            "evidence_policy": {**policy, "required_terms": ["adjusted ebitda", "reconciliation"]},
            "required_transforms": ["adjusted_ebitda_bridge"],
            "dealbreakers": ["citation_required", "calculator_trace_required", "synthesis_gate_pass_required"],
            "expected_trace": [*base_trace, "calculator.compute", "finance_numeric_verification"],
            "failure_taxonomy": ["source_acquisition", "table_extraction", "formula_binding", "synthesis_gate"],
        }
    if any(marker in text for marker in ("acquisition", "transaction", "merger")):
        workflow_type = "event_transaction"
        required_slots = ["issuer", "target", "event_period", "transaction_value"]
        transforms = ["ev_revenue"] if "revenue" in text or "multiple" in text else ["event_terms"]
        if "purchase price allocation" in text or "goodwill" in text:
            workflow_type = "purchase_price_allocation"
            required_slots = ["issuer", "target", "consideration_paid", "assets_acquired", "liabilities_assumed", "goodwill_or_intangibles"]
            transforms = ["purchase_price_allocation"]
        return {
            "workflow_type": workflow_type,
            "required_slots": required_slots,
            "evidence_policy": {**policy, "required_source_families": ["sec_filings", "transaction_disclosure"], "required_terms": ["8-k"]},
            "required_transforms": transforms,
            "dealbreakers": ["citation_required", "no_missing_slots", "synthesis_gate_pass_required"],
            "expected_trace": [*base_trace, "calculator.compute", "finance_numeric_verification"],
            "failure_taxonomy": ["event_source_resolver", "slot_filling", "formula_binding", "synthesis_gate"],
        }
    if any(marker in text for marker in ("dcf", "discounted cash flow")):
        return {
            "workflow_type": "modeling_lite",
            "required_slots": ["entity", "base_cash_flow", "growth_assumptions", "discount_rate", "terminal_value_assumption"],
            "evidence_policy": {**policy, "required_terms": ["cash flow"]},
            "required_transforms": ["dcf", "assumption_separation"],
            "dealbreakers": ["citation_required", "assumptions_labeled", "synthesis_gate_pass_required"],
            "expected_trace": [*base_trace, "calculator.compute", "finance_numeric_verification"],
            "failure_taxonomy": ["assumption_labeling", "formula_binding", "unsupported_numeric_claim"],
        }
    if any(marker in text for marker in ("lbo", "irr", "moic")):
        return {
            "workflow_type": "modeling_lite",
            "required_slots": ["entity", "entry_value", "debt_assumption", "cash_flow_or_ebitda", "exit_assumption"],
            "evidence_policy": {**policy, "required_terms": ["ebitda"]},
            "required_transforms": ["lbo", "assumption_separation"],
            "dealbreakers": ["citation_required", "assumptions_labeled", "synthesis_gate_pass_required"],
            "expected_trace": [*base_trace, "calculator.compute", "finance_numeric_verification"],
            "failure_taxonomy": ["assumption_labeling", "formula_binding", "unsupported_numeric_claim"],
        }
    if "fixed charge" in text or "coverage" in text:
        return {
            "workflow_type": "coverage_ratio",
            "required_slots": ["entity_a", "entity_b", "period", "earnings_or_ebitdar", "fixed_charges"],
            "evidence_policy": {**policy, "required_terms": ["interest", "lease"]},
            "required_transforms": ["fixed_charge_coverage"],
            "dealbreakers": ["citation_required", "calculator_trace_required", "synthesis_gate_pass_required"],
            "expected_trace": [*base_trace, "calculator.compute", "finance_numeric_verification"],
            "failure_taxonomy": ["slot_filling", "formula_binding", "unit_period_mismatch"],
        }
    if "ev / ebitda" in text or "ev/ebitda" in text:
        return {
            "workflow_type": "valuation_multiple",
            "required_slots": ["entity_a", "entity_b", "market_cap", "debt", "cash", "ebitda"],
            "evidence_policy": {**policy, "required_source_families": ["sec_filings", "market_data"], "required_terms": ["ebitda"]},
            "required_transforms": ["ev_ebitda"],
            "dealbreakers": ["citation_required", "calculator_trace_required", "synthesis_gate_pass_required"],
            "expected_trace": [*base_trace, "calculator.compute", "finance_numeric_verification"],
            "failure_taxonomy": ["source_acquisition", "market_data", "formula_binding", "unsupported_numeric_claim"],
        }
    if "mlr" in text or "medical loss ratio" in text:
        return {
            "workflow_type": "regulatory_ratio",
            "required_slots": ["entity", "period", "ratio_definition", "numerator", "denominator", "rebate_basis"],
            "evidence_policy": {**policy, "required_source_families": ["sec_filings", "regulatory_disclosure"], "required_terms": ["medical loss ratio"]},
            "required_transforms": ["mlr_rebate"],
            "dealbreakers": ["citation_required", "synthesis_gate_pass_required"],
            "expected_trace": [*base_trace, "calculator.compute", "finance_numeric_verification"],
            "failure_taxonomy": ["regulatory_source", "slot_filling", "formula_binding"],
        }
    return {
        "workflow_type": "source_grounded_research",
        "required_slots": ["entity", "period", "source"],
        "evidence_policy": policy,
        "required_transforms": [],
        "dealbreakers": ["citation_required", "synthesis_gate_pass_required"],
        "expected_trace": base_trace,
        "failure_taxonomy": ["source_acquisition", "claim_extraction", "synthesis_gate"],
    }


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
