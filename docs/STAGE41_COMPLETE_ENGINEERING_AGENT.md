# Stage41: Complete Engineering Agent

## Goal
Stage41 turns the Stage40 brain OS harness into a controlled engineering agent that can execute a real CLI/API engineering loop: observe the repository, compile context, deliberate through the processor fabric, gate tool actions through an action market, execute allowed tools, verify outcomes, and leave an inspectable trace.

This stage is not a WeChat rollout and not a personality/memory milestone. It is the internal engineering-agent substrate needed before any broader autonomous work is credible.

## Public Surfaces
- `engineering-run --goal ... --thread-key ... [--offline] [--max-steps N] [--allow-repo-write]`
- `engineering-trace --trace-id ...`
- `show-engineering-agent-metrics --limit ...`
- `accept-stage41`
- HTTP mirrors:
  - `POST /engineering-run`
  - `GET /engineering-trace?trace_id=...`
  - `GET /engineering-agent-metrics?limit=...`
  - `POST /accept-stage41`

## Loop Contract
Every Stage41 run records these bounded phases:
- `observe`: repository status and runtime inputs.
- `context_compile`: Stage40 `ContextCompiler` bundle with private-source exclusions.
- `deliberate`: model-backed or offline action proposal.
- `action_market`: mutation class gate before execution.
- `tool_loop`: bounded execution of allowed tools.
- `verification`: explicit test/result checks before completion.
- `review`: write summary and manual-review requirement when repo writes occurred.

## Tool Authority
Supported tools are intentionally narrow:
- `inspect_repo_status`: read-only repository status.
- `read_file`: bounded UTF-8 file read.
- `search_text`: bounded repository text search.
- `run_tests`: allowlisted verification commands only.
- `write_file`: repo write, denied unless `--allow-repo-write` is supplied.
- `replace_text`: repo write, denied unless `--allow-repo-write` is supplied.

Mutation classes are explicit:
- `read_only`: allowed by default.
- `cache_write`: allowed only for allowlisted test/hygiene commands.
- `repo_write`: denied by default and allowed only with explicit operator authority.
- `runtime_write`: not supported by Stage41.
- Any successful repo write must be followed by an observed allowlisted verification command before the run can complete.

## Hard Boundaries
- Do not start WeChat or any transport watcher.
- Do not mutate Mind Graph self-memory or private subject memory.
- Do not read or write `.holo_runtime/`, live memory JSONL, private subject profile files, API keys, or transport receipts.
- Do not let model output execute directly; every action must pass the Stage41 gate first.
- Do not permit runtime hot-editing by default.
- Keep model calls inside the processor fabric.

## Persistence
Stage41 uses the Stage40 operational tables:
- `context_bundles`
- `bionic_brain_runs`
- `bionic_brain_steps`

Runs are stored with stage `stage41-complete-engineering-agent`. This is operational evidence only and is not self-memory.

## Acceptance
`accept-stage41` composes `accept-stage40`, runs an offline engineering smoke loop, verifies phase trace visibility, and probes that repo writes are denied by default and private paths remain blocked even with write authority.

Required validation:
- `pytest -q tests/test_stage41_engineering_agent.py`
- `python -m holo_host --config .holo_host.toml engineering-run --goal "stage41 smoke" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2`
- `python -m holo_host --config .holo_host.toml accept-stage41 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
- `git diff --check`
