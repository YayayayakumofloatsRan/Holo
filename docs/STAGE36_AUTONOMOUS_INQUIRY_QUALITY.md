# Stage36: Autonomous Inquiry Quality

Stage36 closes the offline-verifiable autonomous-inquiry debt left after Stage32. The deterministic bionic-kernel fallback now asks at most one grounded question, removes label-template prefixes, and exposes inquiry-quality metrics without adding a new autonomy path.

This stage does not start WeChat, widen send rights, mutate self-memory, add a second brain, or bypass action-market-first generation.

## Implemented Surfaces
- `shape_deterministic_reply(...)` now emits compact natural fallback text instead of `Next:` / `Basis:` / `Open:` / `Context:` blocks.
- Deterministic generation exposes `inquiry_quality` with `score`, `question_count`, `label_marker_count`, and `grounded_question`.
- Bionic metrics expose `inquiry_quality_score`, `formatting_pressure_score`, and `question_count`.
- Bionic capsule phases now keep full payloads at top level while phase entries carry compact diagnostics, keeping noisy capsules bounded.
- `accept-stage36` composes `accept-stage35`, then probes a bounded offline inquiry turn through the same bionic kernel and subject-loop contract.

## Inquiry Contract
- The selected action remains the action-market output.
- Generation stays downstream of action-market selection.
- At most one grounded question should appear in the deterministic fallback.
- Label-template markers are formatting debt and should score as pressure.
- Transport remains an interface only; Stage36 acceptance must not start or depend on WeChat.

## Validation
```powershell
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
pytest -q tests/test_stage36_inquiry_quality.py
pytest -q tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py tests/test_stage35_internal_runtime_readiness.py
python -m holo_host --config .holo_host.toml accept-stage36 --thread-key cli:TestUser --chat-name TestUser --channel cli
pytest -q
```

## Stop Rules
- Stop if inquiry generation reintroduces label-template prefixes.
- Stop if a fallback asks multiple questions for one bounded turn.
- Stop if inquiry composition bypasses action-market-first generation.
- Stop if Stage36 starts WeChat, mutates self-memory, or creates a new loop or planner.
- Stop if DeepSeek readiness or local secret hygiene from Stage35 regresses.

## Rollback
Fall back to Stage35 internal runtime readiness and Stage32 response shaping. Keep the autonomous-inquiry debt visible in `show-debt-registry` until `accept-stage36` is green again.
