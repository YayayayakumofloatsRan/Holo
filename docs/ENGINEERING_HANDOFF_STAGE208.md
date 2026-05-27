# Engineering Handoff Stage208

## Summary

Stage208 adds an artifact-producing live smoke for the agent console. It exercises the actual `HoloReplyService` reply path with a deterministic local runner and deterministic crawler broker, then renders the resulting turn through Stage207.

This closes the gap between renderer-level tests and operator-facing CLI behavior: the smoke proves a web-search request can trigger crawler execution, record observations, repair future-intent text, render crawl events, and produce a grounded final answer.

## Files Changed

- `holo_host/agent_console_live_smoke.py`
  - New Stage208 smoke harness.
  - Runs `HoloReplyService` with a local deterministic runner, memory stub, and crawler broker.
  - Builds HTML/JSON/JSONL artifacts.
  - Scores reply path execution, crawler evidence, console trace, source grounding, stop reason, and privacy.
- `holo_host/cli.py`
  - Adds `run-agent-console-live-smoke`.
- `tests/test_stage208_agent_console_live_smoke.py`
  - Covers successful crawler-grounded reply path, failed search attempted-failure reporting, and CLI artifact writing.
- `docs/STAGE208_AGENT_CONSOLE_LIVE_SMOKE.md`
  - Operator-facing description and command.
- `docs/ENGINEERING_HANDOFF_STAGE208.md`
  - This handoff.
- `HOLO_HANDOFF.md`
  - Adds Stage208 to the current reading/state section.
- `docs/ROADMAP_REGISTRY.md`
  - Records the Stage208 milestone.

## Runtime Propagation

The smoke stores these public surfaces per result:

- `reply_result`
- `stage153_agent_event_stream`
- `stage191_public_thought_stream`
- `stage207_agent_console`
- `stage186_live_crawler_search`
- `web_observation_ledger`
- `rendered_console`
- `canonical_stop_reason`

## Examples

Successful fixture:

```text
holo> search official Codex CLI docs and cite sources
[crawl:query] ...
[crawl:open] status=ok url=https://developers.openai.com/codex/cli
[crawl:stop] status=sufficient reason=sufficient_evidence
...
https://developers.openai.com/codex/cli
```

Failed fixture:

```text
attempted web_search but failed: simulated_search_failure
[crawl:stop] status=failed reason=tool_failure_report
```

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage208_agent_console_live_smoke.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage208-targeted
```

Result: `3 passed in 1.39s`.

Neighbor:

```powershell
python -m pytest tests\test_stage208_agent_console_live_smoke.py tests\test_stage207_agent_console_renderer.py tests\test_stage206_live_crawler_reply_loop.py tests\test_stage187_live_crawler_chat_integration.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage208-neighbor
```

Result: `10 passed in 2.62s`.

Runtime:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage208-runtime
```

Result: `92 passed in 14.88s`.

CLI artifact smoke:

```powershell
python -m holo_host run-agent-console-live-smoke --output artifacts\stage208\stage208_agent_console_live_smoke.html --dry-run
```

Result: passed and wrote `.html`, `.json`, and `.jsonl`.

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `1028 passed in 136.30s`.

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
```

Result: passed.

Diff check:

```powershell
git diff --check
```

Result: passed with CRLF normalization warnings only.

## Constraints Preserved

- No raw hidden chain-of-thought exposure.
- No provider `reasoning_content` exposure.
- No new provider path.
- No WeChat start.
- No transport authority widening.
- No runtime policy mutation.

## Next Suggested Stage

Stage209 should make the live CLI search turn itself use the same Stage208 smoke expectations as an online operator canary: multi-query continuation, failed-tool retry budget, and source sufficiency before finalization.
