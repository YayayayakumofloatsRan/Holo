# Engineering Handoff Stage207

## Summary

Stage207 adds a CLI-oriented agent console renderer over existing Stage153 event streams and Stage191 public thought cards. It improves operator visibility without changing tool authority, provider calls, memory writes, or transport behavior.

## Files Changed

- `holo_host/agent_console_renderer.py`
  - New Stage207 renderer and metadata report.
  - Renders user text, public system/action/thought lines, and final answer as separate CLI sections.
- `holo_host/interactive_cli.py`
  - Stores `stage207_agent_console` metadata on each turn.
  - Adds `render_console_turn()` and `/console`.
- `holo_host/cli.py`
  - `chat --trace` now prints the Stage207 console view.
  - Adds `/console` help entry and ANSI-faint support for TTY trace rows.
- `holo_host/public_thought_stream.py`
  - Adds candidate events as public `model_decision` cards.
  - Changes the public thought header to avoid printing the phrase `raw hidden reasoning`.
- `tests/test_stage207_agent_console_renderer.py`
  - Covers system/final separation, ANSI faint trace rows, public thought rendering, hidden-reasoning redaction, and CLI `chat --trace` integration.

## Runtime Propagation

Each interactive CLI turn now has:

- `stage153_agent_event_stream`
- `stage191_public_thought_stream`
- `stage207_agent_console`

The visible console output is assembled from those sanitized public surfaces.

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage207_agent_console_renderer.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage207-targeted
```

Result: `3 passed in 0.20s`.

Neighbor:

```powershell
python -m pytest tests\test_stage207_agent_console_renderer.py tests\test_stage153_interactive_cli.py tests\test_stage191_public_thought_stream.py tests\test_stage206_live_crawler_reply_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage207-neighbor
```

Result: `17 passed in 1.43s`.

Runtime:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage207-runtime
```

Result: `92 passed in 8.25s`.

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `1025 passed in 133.73s`.

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
- No new provider calls.
- No new tool execution path.
- No memory writes.
- No WeChat start.
- No transport authority widening.

## Next Suggested Stage

Stage208 should run live CLI smoke tests against real network search turns and compare the Stage207 console output against a Codex-like expected transcript, including retry/stop behavior.
