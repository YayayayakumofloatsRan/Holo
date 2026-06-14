from kernel_v3.chat.console import processor_usage_tail
from kernel_v3.processors.usage import coerce_usage


def test_coerce_usage_preserves_deepseek_prompt_cache_counters() -> None:
    usage = coerce_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 64,
            "prompt_cache_miss_tokens": 36,
        }
    )

    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 20
    assert usage["total_tokens"] == 120
    assert usage["estimated"] is False
    assert usage["prompt_cache_hit_tokens"] == 64
    assert usage["prompt_cache_miss_tokens"] == 36
    assert usage["prompt_cache_hit_ratio"] == 0.64


def test_processor_usage_tail_shows_prompt_cache_ratio() -> None:
    tail = processor_usage_tail(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 64,
            "prompt_cache_miss_tokens": 36,
        }
    )

    assert "tokens=120" in tail
    assert "cache_hit=64" in tail
    assert "cache_miss=36" in tail
    assert "cache_ratio=64.0%" in tail
