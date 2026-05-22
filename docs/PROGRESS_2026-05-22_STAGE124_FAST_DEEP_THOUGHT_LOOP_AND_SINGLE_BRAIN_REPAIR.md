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

## Operational Result

Stage124 was committed and pushed as:

```text
066a609 Add Holo fast deep thought loop
```

The WSL kernel was stopped with `scripts/holo-wsl-offline.ps1`, which stopped
only:

```text
daemon
reply_api
```

No WeChat watcher was started or stopped.

`scripts/holo-wsl-align.ps1` then replaced `/home/holo/holo` from
`/mnt/d/Holo/holo`, preserving runtime/private paths and backing up the
previous live repo at:

```text
/home/holo/holo.pre-align-20260522-170217
```

The live WSL repo was verified at:

```text
066a609 Add Holo fast deep thought loop
STAGE123_PRESENT
STAGE124_PRESENT
```

The WSL kernel was restarted with `scripts/holo-wsl-online.ps1`; the active
processes are only:

```text
python3 -m holo_host --config /home/holo/holo/.holo_host.toml serve-api --host 0.0.0.0
python3 -m holo_host --config /home/holo/holo/.holo_host.toml daemon
```

Health/readiness passed, while transport remained stopped.

## Live Smoke

Fast-only smoke:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host chat --thread-key 'holo_cli:stage124-fix-smoke' --chat-name 'Stage124FixSmoke' --channel holo_cli --sender CodexSim --timeout 180 --once 'Smoke after single-brain alignment: answer briefly. Confirm you will first do a fast triage packet, then deepen only if needed.'"
```

Result:

```text
Understood. Fast triage packet done; no deeper packet needed for now.
```

Usage ledger confirmed:

```text
id=1051 task_type=reply lane=micro_fast provider=deepseek model=deepseek-v4-flash
thread_key=holo_cli:stage124-fix-smoke
metadata_json={"budget_tag": "stage124_fast_packet", ...}
```

Deep-path smoke:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host chat --thread-key 'holo_cli:stage124-deep-smoke' --chat-name 'Stage124DeepSmoke' --channel holo_cli --sender CodexSim --timeout 240 --once 'Stage124 deep-path smoke: explain, in Chinese, how Holo should handle a user message with one fast triage packet and then deeper packets only if needed. Include the single-brain rule, memory recall, and tool-call decision boundary. This is a complex architecture question, so do not answer as a one-line acknowledgement.'"
```

Usage ledger confirmed one event with:

```text
id=1054 task_type=reply lane=micro_fast budget_tag=stage124_fast_packet event_id=58
id=1057 task_type=recall_reconstruct lane=subject_main budget_tag=recall_reconstruct event_id=58
id=1058 task_type=reply lane=subject_main budget_tag=chat_reply event_id=58
```

This proves the live path now performs fast triage first, then recalls/deepens
only when needed.

The live `/home` Python environment does not include `pytest`, so runtime-side
unit verification used direct Python import/assert checks instead:

```text
stage124 import/parse smoke ok
```

## Memory Sync Report Hardening

During `holo-wsl-online.ps1`, the memory merge report appeared to double some
stores before the writer trimmed them. The persisted files did not actually
grow to those report counts, but the report was misleading during operations.

`scripts/merge_memory_jsonl.py` now reports `after` as the final persisted row
count and includes `merged` only when the pre-trim merge candidate count differs
from the final persisted count. This keeps WSL memory sync auditable without
mistaking bounded trim behavior for RAG duplication.
