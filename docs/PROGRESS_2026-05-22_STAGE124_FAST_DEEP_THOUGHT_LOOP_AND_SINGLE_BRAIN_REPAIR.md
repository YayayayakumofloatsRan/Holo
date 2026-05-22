# Progress 2026-05-22: Stage124 Fast-Deep Thought Loop And Single-Brain Repair

## Root Cause

Live simulation showed Holo had two divergent code surfaces:

- running live API: `/home/holo/holo`
- current development/public branch: `/mnt/d/Holo/holo`

The live API was still on:

```text
cb69e9f Document biomimetic dialogue boundary test
```

The current development checkout was on:

```text
711242a Document Holo live continuous simulation
```

That explained why live dialogue could not see Stage123 even though the
development checkout implemented it. There must be one WSL brain, so the fix is
to align `/home/holo/holo` from the current checkout and restart only the WSL
reply API/daemon.

## Stage124 Change

Implemented `holo_host/stage124_fast_deep_thought_loop.py` and wired
`CodexCliProcessor.generate()` so every turn first sends a fast packet:

- lane: `micro_fast`
- budget tag: `stage124_fast_packet`
- output: compact triage JSON

If the fast packet says no deeper packet is needed and provides a shallow reply,
Holo returns that reply. If deeper thinking is needed, Holo appends the fast
packet as `Stage124 Deep Packet Context`, then continues through:

- recall reconstruction
- Stage121 packet scheduling
- Stage122 internal/external channel boundary
- Stage123 internal tool-flow bridge
- normal provider/tool loop

## Verification So Far

Red test before implementation:

```powershell
python -m pytest -q tests\test_stage124_fast_deep_thought_loop.py --basetemp=.pytest_tmp_stage124_red
```

Result:

```text
ModuleNotFoundError: No module named 'holo_host.stage124_fast_deep_thought_loop'
```

Targeted test after implementation:

```powershell
python -m pytest -q tests\test_stage124_fast_deep_thought_loop.py --basetemp=.pytest_tmp_stage124
```

Result:

```text
5 passed in 0.22s
```

Session continuity regression:

```powershell
python -m pytest -q tests\test_holo_host.py::ReplyServiceTests::test_reply_service_uses_codex_runner_and_tracks_thread_session tests\test_stage124_fast_deep_thought_loop.py --basetemp=.pytest_tmp_stage124_session
```

Result:

```text
6 passed in 0.38s
```

Tool-loop regression:

```powershell
python -m pytest -q tests\test_stage115_deepseek_agent_tool_loop.py tests\test_stage116_multiround_agent_tools.py tests\test_stage117_complete_agent_tooling.py tests\test_stage118_tool_expansion.py tests\test_stage119_tool_library_expansion.py tests\test_stage120_tool_affordance_optimizer.py tests\test_stage121_conscious_packet_scheduler.py tests\test_stage122_channel_boundary.py tests\test_stage123_internal_tool_flow.py tests\test_stage124_fast_deep_thought_loop.py tests\test_holo_host.py::ReplyServiceTests::test_reply_service_uses_codex_runner_and_tracks_thread_session --basetemp=.pytest_tmp_stage124_tool_regression
```

Result:

```text
42 passed in 11.26s
```

Full suite:

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage124
```

Result:

```text
419 passed in 65.34s (0:01:05)
```

During full-suite verification, a session-continuity regression surfaced: the
fast packet introduced an additional provider call, so the old test observed
the first turn's deep packet at the previous "second call" index. The fix was
to pass the fast packet's returned session id into the deep packet. That keeps
fast and deep packets inside one subject thread.

## Operational Plan

After tests pass:

1. Commit and push Stage124 from `/mnt/d/Holo/holo`.
2. Stop only WSL `reply_api` and `daemon`; do not touch WeChat watcher.
3. Run `scripts/holo-wsl-align.ps1` to replace `/home/holo/holo` with the
   current checkout while preserving `.holo_runtime`, `.holo_host.toml`, private
   subject files, and memory JSONL.
4. Start only WSL `reply_api` and `daemon`.
5. Verify `/home/holo/holo` has Stage123/Stage124 files and the live smoke
   response comes from the aligned single brain.
