# Engineering Handoff Stage201

## Summary

Stage201 adds a runtime market-research dossier registry. Holo now records the latest Stage199 dossier and Stage200 resume report by thread/project under `.holo_runtime`, can load the latest dossier without transcript reconstruction, and can resume it through the Stage200 path.

## Files Changed

- `holo_host/market_research_dossier_registry.py`
- `holo_host/cli.py`
- `holo_host/agent_event_stream.py`
- `holo_host/public_thought_stream.py`
- `holo_host/reply_api.py`
- `holo_host/stage135_i_state_topology.py`
- `tests/test_stage201_market_research_dossier_registry.py`
- `docs/STAGE201_MARKET_RESEARCH_DOSSIER_REGISTRY.md`
- `docs/ENGINEERING_HANDOFF_STAGE201.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schemas

- `holo.stage201.market_research_dossier_registry.v1`
- `holo.stage201.market_research_dossier_record.v1`
- `holo.stage201.market_research_dossier_lookup.v1`
- `holo.stage201.market_research_dossier_registry_bundle.v1`

## Runtime Propagation

When reply runtime builds a Stage199 dossier, Stage201 records it under `config.runtime.state_dir / "market_research_dossiers"`. The registry report is attached to sidecar, reply debug, capability context, outgoing metadata, archive metadata, Stage153 event stream, Stage191 public thought stream, and Stage135 topology.

## CLI

```powershell
python -m holo_host market-research-dossier-state --state-dir .holo_runtime --thread-key holo_cli:default
python -m holo_host market-research-dossier-state --state-dir .holo_runtime --thread-key holo_cli:default --output artifacts\stage201\stage201_registry.html --dry-run
```

## Examples

Found latest dossier:

```text
lookup.status=found
status=planned|resumed|already_complete
```

Missing latest dossier:

```text
status=missing
canonical_stop_reason=needs_user_clarification
```

## Verification

Executed on 2026-05-28:

```powershell
python -m pytest tests\test_stage201_market_research_dossier_registry.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage201-targeted
python -m pytest tests\test_stage201_market_research_dossier_registry.py tests\test_stage200_market_research_dossier_resume.py tests\test_stage199_market_research_dossier.py tests\test_stage198_market_research_finalization_gate.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage201-neighbor
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage201-runtime
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results:

- Stage201 targeted: `7 passed in 0.50s`
- Stage201 neighbor market stack: `41 passed in 1.69s`
- Runtime regression: `92 passed in 8.70s`
- CLI smoke: `market-research-dossier-state` wrote `artifacts\stage201\stage201_registry.html`, `.json`, and `.jsonl`
- Full regression: `997 passed in 127.77s`
- Public hygiene: passed
- `git diff --check`: exit 0 with CRLF normalization warnings only

## Constraints Preserved

- No provider calls
- No memory writes
- No WeChat start
- No transport authority widening
- No raw hidden reasoning exposure
- No unbounded loop

## Next Suggested Stage

Stage202 should make the model-first live agent loop consume Stage201 registry state as a structured tool/observation surface, so a user follow-up such as "continue this market research" can choose `market_research_dossier_resume` through model arbitration rather than host-only heuristics.
