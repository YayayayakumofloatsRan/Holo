# Engineering Handoff Stage41

## Status
Stage41 implements a controlled internal engineering agent on top of Stage40. The key change is practical tool authority: Holo can now run a bounded engineering loop from CLI/API, but repository writes remain opt-in and private/runtime paths stay blocked.

## New Files
- `holo_host/engineering_agent.py`
- `holo_host/cli_parts/engineering.py`
- `tests/test_stage41_engineering_agent.py`
- `docs/STAGE41_COMPLETE_ENGINEERING_AGENT.md`
- `docs/ENGINEERING_HANDOFF_STAGE41.md`

## Main Surfaces
- `python -m holo_host engineering-run --goal "..." --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
- `python -m holo_host engineering-trace --trace-id <run_id>`
- `python -m holo_host show-engineering-agent-metrics`
- `python -m holo_host accept-stage41 --thread-key cli:TestUser --chat-name TestUser --channel cli`

## Review Notes
- The executor is intentionally small and local: read, search, repo status, allowlisted tests, and explicit repo-write tools only.
- `--allow-repo-write` is required for `write_file` and `replace_text`.
- Private paths remain blocked even with write authority.
- Successful repo writes require a follow-up allowlisted verification command before the run can be marked complete.
- Verification is part of the run result; failed test actions prevent completion.
- Stage41 run data is operational QueueStore evidence, not self-memory.

## Follow-Up Constraints
- Broaden tools only through explicit mutation classes and tests.
- Add richer repair/eval tasks only after the current gate remains full-green.
- Do not restart WeChat as part of Stage41 hardening.
- Do not route direct provider calls around the processor fabric.
- Do not publish local runtime state, memory, subject profiles, or API keys.
