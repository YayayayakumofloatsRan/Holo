# Progress 2026-05-23 Stage131 Thought Flow CT And Continuation Gate

## Context

The Stage130 live smoke improved short-term memory, but a later operator test
still showed weak continuity:

- `ok` after an open continuation prompt was silenced;
- `what process` was silenced;
- emoji returned after the user asked Holo to stop using emoji;
- background API use was visible only through raw usage ledgers.

## Changes

- Added `holo_host.stage131_continuation` for Unicode-safe Chinese question
  detection and short-acknowledgement continuation gating.
- Patched `MemoryBridge._query_signal` so real Chinese reference questions clear
  the low-signal flag.
- Patched Stage5 action selection so contextual short acknowledgements cannot
  be forced to silence or defer solely because they are short.
- Patched the active-thread fast packet to carry only the last two dialogue
  lines, preserving the speed path while giving the continuation gate real
  short-term evidence.
- Added `pending_open_loop` to the short-term working-memory packet.
- Added a visible-reply emoji scrubber when the current or recent Chinese thread
  contains an explicit reduce/no-emoji correction.
- Added `holo_host.stage131_thought_flow_trace` plus CLI command
  `trace-thought-flow`.
- Added interactive CLI command `/ct` for the current single-subject CLI thread.

## Operator Commands

Read-only packet-flow CT:

```powershell
wsl.exe -d HoloUbuntu --cd /home/holo/holo --exec python3 -m holo_host trace-thought-flow --thread-key holo_cli:main --chat-name HoloCLI --channel holo_cli --limit 8
```

Interactive CLI:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host chat"
```

Then run:

```text
/ct
```

## Verification So Far

```powershell
python -m pytest tests\test_stage131_thought_flow_trace.py -q
python -m pytest tests\test_stage130_short_term_working_memory.py -q
python -m pytest tests\test_holo_host.py::ReplyServiceTests::test_reply_service_can_choose_silence_as_a_first_class_action tests\test_holo_host.py::ReplyServiceTests::test_reply_service_normalizes_english_i_in_chinese_visible_reply -q
python -m holo_host trace-thought-flow --thread-key holo_cli:stage131 --chat-name HoloCLIStage131 --channel holo_cli --limit 2
```

Observed:

```text
7 passed in 0.58s
7 passed in 0.65s
2 passed in 0.70s
12 passed in 4.74s
STAGE131 BIOMIMETIC CT rendered usage, lanes, flow, action, and background rows.
```

Full suite:

```text
446 passed in 150.79s (0:02:30)
```

WSL live smoke found one additional bug: action selection receives a thin
runtime `context`, while recent dialogue lives in the full packet. The fix now
checks both layers before allowing a short acknowledgement to be silenced.
Live smoke then found the active-thread fast path still emitted an empty recent
window. The second fix carries a two-line recent window in that path only.

## WSL Live Smoke

Runtime after alignment:

```text
aligned_head=f2acd6fd082f95e149755fa9d48f51f647056ba5
reply_api: running
daemon: running
transport: stopped
health: ok
readiness: ready
flow: healthy
```

Open-loop continuation smoke:

```text
user: 请只回复这一句：好，继续。
holo: 好，继续。
user: 行
holo: 继续。
user: 什么流程
holo: 你刚才说了"行"，我说"继续"，指的就是我们在沿着 Stage104 那条线往前走——记忆该怎么从工作区压进更耐久的层里，而不是堆完就散。你要我回放一下现在走到哪一步吗？
```

Emoji guard smoke:

```text
user: 你可以试着不要再用这么多emoji，可以吗？
holo: 可以，我收着。之前是不是有点花里胡哨过头了？
user: 说了不要用emoji了
holo: 好，记住了，以后不主动用。
```

CT smoke:

```text
STAGE131 BIOMIMETIC CT
FLOW sensory_input -> action_gate -> FAST packet=off -> DEEP packet=on -> tool_loop -> expression
ACTION reply_once entry=execute_action
PACKET reply lane=subject_main provider=deepseek model=deepseek-v4-pro
BACKGROUND operator_execute_shadow
BACKGROUND self_revision_review
```
