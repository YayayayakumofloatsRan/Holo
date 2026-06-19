from __future__ import annotations

from typing import Any

from kernel_v4.contracts import JsonObject

DEEPSEEK_PRICING_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing"
DEEPSEEK_PRICING_OBSERVED_DATE = "2026-06-18"
DEEPSEEK_PRICES_PER_1M: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {
        "input_cache_hit": 0.0028,
        "input_cache_miss": 0.14,
        "output": 0.28,
    },
    "deepseek-v4-pro": {
        "input_cache_hit": 0.003625,
        "input_cache_miss": 0.435,
        "output": 0.87,
    },
}


def estimate_deepseek_cost_usd(
    usage: object,
    *,
    model: object = None,
    provider: object = "deepseek",
) -> JsonObject:
    if not isinstance(usage, dict):
        return {}
    if provider is not None and "deepseek" not in str(provider).lower():
        return {}
    family = _deepseek_pricing_family(model)
    if family is None:
        return {}
    rates = DEEPSEEK_PRICES_PER_1M[family]
    hit_tokens = _nonnegative_int(usage.get("prompt_cache_hit_tokens")) or 0
    miss_tokens = _nonnegative_int(usage.get("prompt_cache_miss_tokens"))
    prompt_tokens = _nonnegative_int(usage.get("prompt_tokens"))
    if miss_tokens is None:
        miss_tokens = max((prompt_tokens or 0) - hit_tokens, 0) if prompt_tokens is not None else 0
    output_tokens = _nonnegative_int(usage.get("completion_tokens")) or 0
    input_cache_hit_usd = hit_tokens * rates["input_cache_hit"] / 1_000_000
    input_cache_miss_usd = miss_tokens * rates["input_cache_miss"] / 1_000_000
    output_usd = output_tokens * rates["output"] / 1_000_000
    return {
        "schema": "holo.kernel_v4.deepseek_cost_estimate.v1",
        "provider": "deepseek",
        "model_pricing_family": family,
        "currency": "USD",
        "pricing_source": DEEPSEEK_PRICING_SOURCE,
        "pricing_observed_date": DEEPSEEK_PRICING_OBSERVED_DATE,
        "rates_per_1m_tokens": dict(rates),
        "tokens": {
            "input_cache_hit": hit_tokens,
            "input_cache_miss": miss_tokens,
            "output": output_tokens,
        },
        "input_cache_hit_usd": input_cache_hit_usd,
        "input_cache_miss_usd": input_cache_miss_usd,
        "output_usd": output_usd,
        "total_usd": input_cache_hit_usd + input_cache_miss_usd + output_usd,
    }


def _deepseek_pricing_family(model: object) -> str | None:
    name = str(model or "").lower()
    if "pro" in name:
        return "deepseek-v4-pro"
    if "flash" in name or name in {"deepseek-chat", "deepseek-reasoner", ""}:
        return "deepseek-v4-flash"
    if name.startswith("deepseek-v4"):
        return "deepseek-v4-flash"
    return None


def _nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
