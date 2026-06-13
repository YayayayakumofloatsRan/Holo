from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.processors.contracts import JsonSchema
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.processors.providers import DeepSeekProvider
from kernel_v3.processors.routing import deepseek_v4_router


REASONABLE_JUDGE_SCHEMA = JsonSchema(
    name="finance.numeric_judge",
    required={
        "decision": "str",
        "reason_summary": "str",
        "answer_addresses_question": "bool",
        "reasonable_given_reference": "bool",
        "source_grounded": "bool",
        "core_numeric_claims": "list",
        "non_core_numeric_claims": "list",
        "unsupported_core_values": "list",
        "repair_instruction": "str",
        "requires_more_work": "bool",
    },
    optional={
        "confidence": "str|number",
        "accepted_numbers": "list",
        "rejected_numbers": "list",
        "material_issues": "str|list",
    },
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-run LLM reasonableness judge for finance benchmark outputs.")
    parser.add_argument("--results", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    args = parser.parse_args()

    dataset = _load_dataset(Path(args.dataset), limit=args.limit, offset=args.offset)
    results = _load_jsonl(Path(args.results))
    fabric = _fabric(Path(args.output).with_suffix(".judge.journal.jsonl"), profile=args.profile)
    judged = []
    for index, result in enumerate(results, start=1):
        item_id = _text(result.get("item_id") or result.get("id"))
        item = dataset.get(item_id, {})
        prompt = _judge_prompt(item=item, result=result)
        outcome = fabric.run_json(
            task_type="finance.numeric_judge",
            run_id=f"reasonable-judge-{int(time.time())}",
            context_id=f"reasonable-judge-{index}",
            task_id=f"reasonable-judge-{item_id or index}",
            prompt=prompt,
            schema=REASONABLE_JUDGE_SCHEMA,
            timeout_seconds=90,
        )
        parsed = outcome.parsed if isinstance(outcome.parsed, dict) else {}
        decision = str(parsed.get("decision") or "").strip().lower()
        reasonable = decision in {"pass", "passed", "reasonable", "accept", "accepted"} or (
            parsed.get("answer_addresses_question") is True
            and parsed.get("reasonable_given_reference") is True
            and parsed.get("source_grounded") is True
        )
        judged.append(
            {
                "item_id": item_id,
                "strict_status": result.get("status"),
                "reasonable_status": "passed" if reasonable else "failed",
                "judge": parsed,
                "provider_status": outcome.result.status,
                "provider": outcome.provider,
                "model": outcome.model,
                "duration_ms": outcome.duration_ms,
            }
        )
    passed = sum(1 for row in judged if row["reasonable_status"] == "passed")
    payload = {
        "schema": "holo.kernel_v3.finance_reasonable_judge_summary.v1",
        "results": str(args.results),
        "dataset": str(args.dataset),
        "item_count": len(judged),
        "passed_count": passed,
        "failed_count": len(judged) - passed,
        "pass_rate": round(passed / len(judged), 4) if judged else None,
        "items": judged,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("item_count", "passed_count", "failed_count", "pass_rate")}, ensure_ascii=False))


def _fabric(journal_path: Path, *, profile: str) -> ProcessorFabric:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY is required for reasonable judge")
    return ProcessorFabric(
        providers={"deepseek": DeepSeekProvider(enabled=True, max_retries=2)},
        router=deepseek_v4_router(profile=profile, generation_mode="auto", latency_target="balanced"),
        journal=JournalStore(journal_path, index_path=journal_path.with_suffix(".sqlite")),
    )


def _judge_prompt(*, item: JsonObject, result: JsonObject) -> str:
    metrics = result.get("trace_metrics") if isinstance(result.get("trace_metrics"), dict) else {}
    scorecard = result.get("scorecard") if isinstance(result.get("scorecard"), dict) else {}
    answer = _candidate_answer(result)
    packet = {
        "question": item.get("question") or result.get("question"),
        "reference_answer_post_run_only": item.get("gold_answer") or item.get("answer"),
        "candidate_answer": answer,
        "strict_scorecard": {
            "status": result.get("status"),
            "reason": scorecard.get("reason"),
        },
        "source_trace": {
            "citation_count": metrics.get("citation_count") or metrics.get("retrieval_citation_count"),
            "claim_count": metrics.get("claim_count"),
            "source_uris": list(metrics.get("source_uris") or [])[:12],
            "source_hosts": list(metrics.get("source_hosts") or [])[:12],
            "numeric_verifier_status": metrics.get("numeric_verifier_status"),
            "synthesis_gate_status": metrics.get("synthesis_gate_status"),
            "answer_numeric_support_rate": metrics.get("answer_numeric_support_rate"),
        },
    }
    return (
        "You are a strict but fair post-run finance benchmark judge. "
        "The model did not see the reference answer during solving. Use it only now to judge equivalence. "
        "Mark passed when the candidate directly answers the question, is materially consistent with the reference "
        "or a defensible source-grounded correction, and has no material unsupported contradiction. "
        "Accept scale/wording differences such as millions vs billions when numerically equivalent. "
        "Return JSON only with decision pass or fail, reason_summary, answers_question, "
        "answer_addresses_question, reasonable_given_reference, source_grounded, core_numeric_claims, "
        "non_core_numeric_claims, unsupported_core_values, repair_instruction, requires_more_work, "
        "material_issues, confidence, accepted_numbers, rejected_numbers.\n\n"
        f"{json.dumps(packet, ensure_ascii=False, indent=2)}"
    )


def _load_dataset(path: Path, *, limit: int | None, offset: int) -> dict[str, JsonObject]:
    records = _load_jsonl(path)
    selected = records[max(0, offset) :]
    if limit is not None:
        selected = selected[: max(0, limit)]
    return {_text(row.get("id") or row.get("item_id") or row.get("question_id")): row for row in selected}


def _load_jsonl(path: Path) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _candidate_answer(result: JsonObject) -> str:
    final_answer = result.get("final_answer")
    if isinstance(result.get("answer"), str) and result["answer"].strip():
        return result["answer"].strip()
    if isinstance(final_answer, dict):
        for key in ("answer", "text", "final"):
            value = final_answer.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(final_answer, str) and final_answer.strip():
        return final_answer.strip()
    return ""


def _text(value: Any) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    main()
