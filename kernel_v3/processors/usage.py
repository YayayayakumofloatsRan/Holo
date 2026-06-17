from __future__ import annotations

from kernel_v3.contracts import JsonObject


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def usage_from_text(*, prompt: str, completion: str) -> JsonObject:
    prompt_tokens = estimate_text_tokens(prompt)
    completion_tokens = estimate_text_tokens(completion)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated": True,
    }


def coerce_usage(value: object, *, prompt: str = "", completion: str = "") -> JsonObject:
    if isinstance(value, dict):
        prompt_tokens = _int(value.get("prompt_tokens"))
        completion_tokens = _int(value.get("completion_tokens"))
        total_tokens = _int(value.get("total_tokens"))
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens
        usage: JsonObject = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated": bool(value.get("estimated", False)),
        }
        cache_hit, cache_miss, cache_present = _prompt_cache_counters(
            value,
            prompt_tokens=prompt_tokens,
        )
        if cache_present:
            usage["prompt_cache_hit_tokens"] = cache_hit
            usage["prompt_cache_miss_tokens"] = cache_miss
            cache_total = cache_hit + cache_miss
            usage["prompt_cache_hit_ratio"] = round(cache_hit / cache_total, 4) if cache_total > 0 else 0.0
        return usage
    return usage_from_text(prompt=prompt, completion=completion)


def summarize_processor_usage(records: list[JsonObject]) -> JsonObject:
    """Aggregate processor_result journal records by processor and provider/model.

    This is observability only. It does not participate in routing, answer
    selection, scoring, or any semantic decision.
    """
    total = _empty_bucket()
    by_task_type: dict[str, JsonObject] = {}
    by_provider_model: dict[str, JsonObject] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        task_type = _text(record.get("task_type") or record.get("processor") or "unknown")
        provider = _text(record.get("provider") or "unknown")
        model = _text(record.get("model") or "unknown")
        provider_model = f"{provider}/{model}"
        _add_processor_usage(total, record)
        _add_processor_usage(by_task_type.setdefault(task_type, _empty_bucket()), record)
        _add_processor_usage(by_provider_model.setdefault(provider_model, _empty_bucket()), record)
    _finalize_bucket(total)
    for bucket in by_task_type.values():
        _finalize_bucket(bucket)
    for bucket in by_provider_model.values():
        _finalize_bucket(bucket)
    return {
        "schema": "holo.kernel_v3.processor_usage_summary.v1",
        "call_count": total["call_count"],
        "ok_count": total["ok_count"],
        "failed_count": total["failed_count"],
        "status_counts": total["status_counts"],
        "error_counts": total["error_counts"],
        "prompt_tokens": total["prompt_tokens"],
        "completion_tokens": total["completion_tokens"],
        "total_tokens": total["total_tokens"],
        "prompt_cache_hit_tokens": total["prompt_cache_hit_tokens"],
        "prompt_cache_miss_tokens": total["prompt_cache_miss_tokens"],
        "prompt_cache_hit_ratio": total["prompt_cache_hit_ratio"],
        "duration_ms": total["duration_ms"],
        "average_duration_ms": total["average_duration_ms"],
        "by_task_type": by_task_type,
        "by_provider_model": by_provider_model,
    }


def aggregate_processor_usage_by_task_type(records: list[object], *, field: str = "processor_usage_by_task_type") -> JsonObject:
    """Merge nested processor usage buckets from benchmark result metrics.

    This is report-only accounting. It does not route work, select answers, or
    influence model decisions.
    """
    buckets: dict[str, JsonObject] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        by_task_type = record.get(field)
        if not isinstance(by_task_type, dict):
            continue
        for task_type, payload in by_task_type.items():
            if not isinstance(payload, dict):
                continue
            bucket = buckets.setdefault(str(task_type), _empty_bucket())
            bucket["call_count"] = _int(bucket.get("call_count")) + _int(payload.get("call_count"))
            bucket["ok_count"] = _int(bucket.get("ok_count")) + _int(payload.get("ok_count"))
            bucket["failed_count"] = _int(bucket.get("failed_count")) + _int(payload.get("failed_count"))
            bucket["prompt_tokens"] = _int(bucket.get("prompt_tokens")) + _int(payload.get("prompt_tokens"))
            bucket["completion_tokens"] = _int(bucket.get("completion_tokens")) + _int(payload.get("completion_tokens"))
            bucket["total_tokens"] = _int(bucket.get("total_tokens")) + _int(payload.get("total_tokens"))
            bucket["prompt_cache_hit_tokens"] = _int(bucket.get("prompt_cache_hit_tokens")) + _int(payload.get("prompt_cache_hit_tokens"))
            bucket["prompt_cache_miss_tokens"] = _int(bucket.get("prompt_cache_miss_tokens")) + _int(payload.get("prompt_cache_miss_tokens"))
            bucket["duration_ms"] = _int(bucket.get("duration_ms")) + _int(payload.get("duration_ms"))
            _merge_count_map(bucket, "status_counts", payload.get("status_counts"))
            _merge_count_map(bucket, "error_counts", payload.get("error_counts"))
    for bucket in buckets.values():
        _finalize_bucket(bucket)
    return dict(sorted(buckets.items()))


def _int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _prompt_cache_counters(value: JsonObject, *, prompt_tokens: int) -> tuple[int, int, bool]:
    """Normalize provider-specific prompt-cache counters.

    DeepSeek exposes top-level prompt_cache_hit_tokens/prompt_cache_miss_tokens.
    OpenAI-compatible APIs commonly expose cached prompt tokens under
    prompt_tokens_details.cached_tokens. This keeps benchmark/report metrics on
    one internal field set without changing provider payloads or scoring.
    """

    cache_hit = _int(value.get("prompt_cache_hit_tokens"))
    cache_miss = _int(value.get("prompt_cache_miss_tokens"))
    present = "prompt_cache_hit_tokens" in value or "prompt_cache_miss_tokens" in value

    if not present:
        details = value.get("prompt_tokens_details")
        if isinstance(details, dict) and "cached_tokens" in details:
            cache_hit = _int(details.get("cached_tokens"))
            cache_miss = max(0, prompt_tokens - cache_hit)
            present = True

    if not present:
        details = value.get("input_token_details")
        if isinstance(details, dict):
            for key in ("cache_read", "cache_read_input_tokens", "cached_tokens"):
                if key in details:
                    cache_hit = _int(details.get(key))
                    cache_miss = max(0, prompt_tokens - cache_hit)
                    present = True
                    break

    if present and "prompt_cache_miss_tokens" not in value and cache_miss <= 0 and prompt_tokens > 0:
        cache_miss = max(0, prompt_tokens - cache_hit)
    return cache_hit, cache_miss, present or cache_hit > 0 or cache_miss > 0


def _text(value: object) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _empty_bucket() -> JsonObject:
    return {
        "call_count": 0,
        "ok_count": 0,
        "failed_count": 0,
        "status_counts": {},
        "error_counts": {},
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "prompt_cache_hit_ratio": None,
        "duration_ms": 0,
        "average_duration_ms": None,
    }


def _add_processor_usage(bucket: JsonObject, record: JsonObject) -> None:
    bucket["call_count"] = _int(bucket.get("call_count")) + 1
    status = _text(record.get("status") or "unknown")
    status_counts = bucket.setdefault("status_counts", {})
    if isinstance(status_counts, dict):
        status_counts[status] = _int(status_counts.get(status)) + 1
    if status == "ok":
        bucket["ok_count"] = _int(bucket.get("ok_count")) + 1
    else:
        bucket["failed_count"] = _int(bucket.get("failed_count")) + 1
        error = _text(record.get("error") or "unknown_error")
        error_counts = bucket.setdefault("error_counts", {})
        if isinstance(error_counts, dict):
            error_counts[error] = _int(error_counts.get(error)) + 1

    usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
    prompt_tokens = _int(usage.get("prompt_tokens")) if isinstance(usage, dict) else 0
    completion_tokens = _int(usage.get("completion_tokens")) if isinstance(usage, dict) else 0
    total_tokens = _int(usage.get("total_tokens")) if isinstance(usage, dict) else 0
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    bucket["prompt_tokens"] = _int(bucket.get("prompt_tokens")) + prompt_tokens
    bucket["completion_tokens"] = _int(bucket.get("completion_tokens")) + completion_tokens
    bucket["total_tokens"] = _int(bucket.get("total_tokens")) + total_tokens
    bucket["prompt_cache_hit_tokens"] = _int(bucket.get("prompt_cache_hit_tokens")) + (
        _int(usage.get("prompt_cache_hit_tokens")) if isinstance(usage, dict) else 0
    )
    bucket["prompt_cache_miss_tokens"] = _int(bucket.get("prompt_cache_miss_tokens")) + (
        _int(usage.get("prompt_cache_miss_tokens")) if isinstance(usage, dict) else 0
    )
    bucket["duration_ms"] = _int(bucket.get("duration_ms")) + _int(record.get("duration_ms"))


def _merge_count_map(bucket: JsonObject, key: str, value: object) -> None:
    if not isinstance(value, dict):
        return
    target = bucket.setdefault(key, {})
    if not isinstance(target, dict):
        return
    for item_key, count in value.items():
        target[str(item_key)] = _int(target.get(str(item_key))) + _int(count)


def _finalize_bucket(bucket: JsonObject) -> None:
    hit = _int(bucket.get("prompt_cache_hit_tokens"))
    miss = _int(bucket.get("prompt_cache_miss_tokens"))
    cache_total = hit + miss
    bucket["prompt_cache_hit_ratio"] = round(hit / cache_total, 6) if cache_total else None
    calls = _int(bucket.get("call_count"))
    bucket["average_duration_ms"] = round(_int(bucket.get("duration_ms")) / calls, 4) if calls else None
