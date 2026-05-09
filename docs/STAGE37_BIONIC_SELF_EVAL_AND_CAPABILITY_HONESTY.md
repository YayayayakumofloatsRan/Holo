# Stage37: Bionic Self-Eval And Capability Honesty

Stage37 is an internal blackbox repair pass driven by direct bionic-kernel dialogue probes. It fixes three observed failures: processor hallucination when continuity is empty, overclaiming image-reading ability through a text-only provider, and empty CLI replies when the action market selects a non-executable internal action.

This stage does not add a new subject feature, start WeChat, mutate self-memory, add a second brain, or bypass action-market-first selection.

## Implemented Surfaces
- Same-thread `bionic_agent_traces` are reused as bounded operational continuity for later CLI bionic turns.
- Processor prompts now include explicit grounding and capability-honesty rules.
- Processor output is guarded when a visual query is answered through a provider whose metadata says `image_support=false`.
- CLI self-evaluation probes demote non-executable internal actions, such as `operator_self_fix`, to the highest speech candidate already present in the action market.
- Processor text is lightly bounded after generation: markdown emphasis is stripped and extra question marks are converted to statements.
- Processor generation now exposes `inquiry_quality`, so existing metrics can score question pressure and formatting pressure for both deterministic and provider-backed turns.
- `accept-stage37` verifies Stage36, visual honesty, same-thread trace continuity, speech fallback, style bounds, and transport-interface boundaries.

## Self-Eval Findings
- Context continuity failure: with empty continuity, the model invented unrelated technical work. Stage37 now either supplies same-thread trace continuity or refuses to invent prior work.
- Capability honesty failure: the model claimed direct screenshot reading despite `image_support=false`. Stage37 now replaces that output with the correct `ingest-image` / visual-memory route.
- Empty reply failure: self-eval prompts could select `operator_self_fix`, which is not a speech action. Stage37 now keeps action-market-first semantics while selecting a speech candidate for CLI dialogue.

## Validation
Verified on `2026-05-09`: targeted Stage37 tests, the Stage37 acceptance gate, full `pytest -q` with `298` tests, and public release hygiene all passed.

```powershell
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
pytest -q tests/test_stage37_bionic_self_eval.py
pytest -q tests/test_stage37_bionic_self_eval.py tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py tests/test_stage35_internal_runtime_readiness.py
python -m holo_host --config .holo_host.toml accept-stage37 --thread-key cli:TestUser --chat-name TestUser --channel cli
pytest -q
```

## Stop Rules
- Stop if a text-only provider claims direct image reading.
- Stop if a same-thread "what were we doing" query invents work not present in continuity or bionic traces.
- Stop if a CLI self-evaluation prompt returns an empty generation because an internal non-speech action won the market.
- Stop if Stage37 starts WeChat, mutates self-memory, or creates a new planner or loop.

## Rollback
Fall back to Stage36 inquiry quality while keeping Stage37 failures visible. Do not claim image understanding beyond the configured provider capability matrix.
