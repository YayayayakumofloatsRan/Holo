# Stage39: Bionic Turing Benchmark

Stage39 adds an internal, operational bionic Turing benchmark for the CLI subject kernel. It does not claim that Holo has passed a human Turing test. It gives the repo a repeatable gate for whether Holo is becoming less mechanical and more continuous in the bounded internal CLI path.

This stage does not start WeChat, add a new autonomy path, mutate self-memory, add a second brain, or bypass action-market-first generation.

## Implemented Surfaces
- `holo_host.bionic_kernel_parts.turing_eval` scores probe sets with visible metrics.
- `show-bionic-turing-scorecard` runs the internal Stage39 benchmark.
- `accept-stage39` composes `accept-stage38` and then verifies the bionic Turing scorecard.
- Bionic turn metrics now expose `bionic_turing_score` and `bionic_turing_pass_threshold`.
- Deterministic fallback replies no longer expose `action-market`, `capsule`, or `bionic kernel` terms in user-facing text.
- Provider prompts now ask for plain, concrete, non-theatrical replies and avoid leakage-prone internal labels.

## Scorecard Metrics
- `continuity_reference_score`: response carries the expected same-thread anchor instead of resetting.
- `mechanism_leakage_score`: response avoids internal machinery terms.
- `naturalness_score`: response avoids fixed templates, harness phrasing, repeated prefixes, and theatrical metaphors.
- `question_bounds_score`: response asks at most one grounded question.
- `context_score`: generation carries bounded context references.
- `non_empty_score`: selected speech actions produce visible text.

The default pass threshold is `0.82`.

## Boundary
- This is an internal CLI benchmark, not live transport validation.
- The benchmark is observational and operational; it does not write self-memory or policy.
- The benchmark should grow only from observed failures, not synthetic fixture sprawl.

## Validation
```powershell
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
pytest -q tests/test_stage39_bionic_turing_benchmark.py
pytest -q tests/test_stage39_bionic_turing_benchmark.py tests/test_stage38_visual_provider_bridge.py tests/test_stage37_bionic_self_eval.py tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py
python -m holo_host --config .holo_host.toml accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli
python -m holo_host --config .holo_host.toml show-bionic-turing-scorecard --thread-key cli:TestUser --chat-name TestUser --channel cli
pytest -q
python scripts/check_public_release_hygiene.py
git diff --check
```

Verified on `2026-05-10`: `pytest -q` passed with `306` tests, `accept-stage39` passed, `show-bionic-turing-scorecard` passed, public-release hygiene passed, and `git diff --check` reported no whitespace errors.

## Stop Rules
- Stop if generated text exposes internal machinery in ordinary user-facing replies.
- Stop if scores pass while a real probe shows obvious mechanism leakage or repeated formulaic phrasing.
- Stop if the benchmark becomes a second decision layer or grants transport authority.
- Stop if acceptance starts live WeChat or performs hidden self-memory mutation.

## Rollback
Fall back to Stage38 visual-provider bridge and keep the Stage39 scorecard disabled until the leakage, continuity, or scoring regression is repaired.
