# Stage38: Visual Provider Bridge

Stage38 closes the immediate internal image-reading gap for the bionic CLI path. Raw image understanding stays inside the processor fabric through `image_understand`; bionic dialogue consumes the resulting visual-memory summary instead of letting a text-only reply provider claim direct image access.

This stage does not start WeChat, add a watcher path, add a second brain, or bypass action-market-first selection.

## Implemented Surfaces
- `agent-run` accepts `--image-path` and ingests up to three explicit local images before the bionic turn.
- `MemoryBridge.ingest_image()` now returns and stores `image_understand` provider metadata, including provider, lane, model, capabilities, return code, and image path count.
- Bionic capsules expose `perception.stage38` with image input count, image-understand provider, image-support flag, bounded path visibility, and visual summary.
- Processor generation prompts receive a bounded visual-grounding line when image-understand output is available.
- Stage37 capability-honesty guard still blocks unsupported visual claims when no visual-memory summary exists, but no longer blocks text generation that is grounded in an inspectable image-understand summary.
- CLI visual probes that select internal `visual_recall` are demoted to the best speech candidate already present in the action market.
- `accept-stage38` verifies Stage37, image-capable provider metadata, bionic visual grounding, text-provider honesty, and transport-interface boundaries.

## Boundary
- DeepSeek remains text-only for image support in this repo configuration.
- `codex_cli` is the configured image-capable processor fallback for explicit `image_understand` requests.
- Text generation may describe visual-memory summaries; it must not claim that the text-only generation provider directly read raw image pixels.

## Validation
```powershell
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
pytest -q tests/test_stage38_visual_provider_bridge.py
pytest -q tests/test_stage38_visual_provider_bridge.py tests/test_stage37_bionic_self_eval.py tests/test_stage34_debt_closure.py tests/test_stage28_multimodal_homeostatic_kernel.py tests/test_stage29_bionic_cli_agent.py
python -m holo_host --config .holo_host.toml accept-stage38 --thread-key cli:TestUser --chat-name TestUser --channel cli
pytest -q
python scripts/check_public_release_hygiene.py
git diff --check
```

Verified on `2026-05-10`: the targeted Stage38 suite passed, `accept-stage38` passed, full `pytest -q` passed with `301` tests, public-release hygiene passed, and `git diff --check` reported no whitespace errors.

## Stop Rules
- Stop if text-only providers claim direct raw image reading without an `image_understand` summary.
- Stop if image input starts WeChat, grants transport authority, or mutates live policy.
- Stop if `visual_recall` produces an empty CLI reply instead of using a speech candidate from the action market.

## Rollback
Fall back to Stage37 capability honesty: keep image input explicit, preserve visual-memory records, and refuse unsupported direct-image claims until `accept-stage38` is green again.
