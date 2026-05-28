# Engineering Handoff Stage211

## Summary

Stage211 adds `holo.stage211.persistent_action_recall.v1`, a persisted action-ledger recall path for questions such as "what exactly did you search on the web?"

Stage210 handled this only inside the current interactive CLI process. Stage211 moves the same behavior into `/reply`: after inbound storage and history load, Holo checks recent same-thread outbound metadata for public action ledgers. If found, it answers from the previous crawler/web ledger before memory sidecar, provider generation, or tool execution.

## Files Changed

- Added `holo_host/stage211_persistent_action_recall.py`
- Added `tests/test_stage211_persistent_action_recall.py`
- Added `docs/STAGE211_PERSISTENT_ACTION_LEDGER_RECALL.md`
- Added `docs/ENGINEERING_HANDOFF_STAGE211.md`
- Updated `holo_host/reply_api.py`
- Updated `holo_host/stage210_last_action_recall.py`
- Updated `holo_host/public_thought_stream.py`
- Updated `HOLO_HANDOFF.md`
- Updated `docs/ROADMAP_REGISTRY.md`

## Runtime Propagation

Stage211 reply metadata includes:

- `stage211_persistent_action_recall`
- `stage210_last_action_recall`
- `stage153_agent_event_stream`
- `stage191_public_thought_stream`
- `canonical_stop_reason=final_answer_ready`
- `canonical_stop_source=stage211_persistent_action_recall`

The outbound message stores sanitized Stage210/211 reports so a later process can inspect the same ledger chain.

## Example

Previous persisted outbound metadata contains a Stage186 crawler report:

```text
query 1: Codex CLI
weak source: https://example.com/codex-overview
query 2: official Codex CLI docs
promoted source: https://developers.openai.com/codex/cli
```

Follow-up:

```text
what exactly did you search on the web?
```

Stage211 answers from the persisted ledger without provider generation.

## Verification

Commands run on `2026-05-28`:

```powershell
python -m pytest tests\test_stage211_persistent_action_recall.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage211-green-3
```

Result:

```text
4 passed in 0.24s
```

```powershell
python -m pytest tests\test_stage211_persistent_action_recall.py tests\test_stage210_last_action_recall.py tests\test_stage153_interactive_cli.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage211-targeted
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage211-runtime
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results on `2026-05-28`:

- targeted Stage211/210/153: `15 passed in 0.70s`
- runtime reply/topology: `92 passed in 15.63s`
- full regression: `1036 passed in 130.01s`
- public hygiene: passed
- `git diff --check`: passed with CRLF normalization warnings only

## Constraints Preserved

- no raw hidden reasoning exposure
- no provider call for persistent last-action recall
- no memory write
- no tool execution
- no WeChat start
- no watcher or transport authority widening
- no weak-source promotion

## Next Suggested Stage

Stage212 should strengthen live agent self-inspection by making the public thought/action stream persist across reply metadata and by adding a real CLI smoke that verifies `/thoughts` after a live search turn.
