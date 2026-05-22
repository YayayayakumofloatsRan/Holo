# Progress 2026-05-22 Stage130 Short Term Working Memory Packet

## Trigger

Live CLI testing showed poor short-term memory and weak context use. Holo did
not reliably preserve immediate user constraints, pending tasks, or correction
signals:

- "please reduce emoji" did not remain active;
- "look into world-model papers" was followed by a low-signal turn that could
  be treated as a generic greeting;
- "???" after a misaligned Minecraft answer became a quiz instead of a repair;
- the Stage124 fast packet saw only the current user text.

## Root Cause

The active-thread design intentionally minimized raw recent history in fast
paths. That kept latency down but left no explicit working-memory layer for
the next packet. `render_chat_prompt` carried scene and predictive continuity,
but not recent style constraints or pending task state. `build_stage124_fast_packet_prompt`
had no short-term context argument at all.

## Changes

- Added `build_short_term_working_memory_lines`.
- Added a `Short Term Working Memory` prompt section before the current turn.
- Passed the same bounded short-term frame into the Stage124 fast packet.
- Extended the Stage124 contextual-follow-up guard for short Chinese follow-ups
  such as look/check, how-is-it, continue, and question-mark-only turns.
- Strengthened Chinese-thread language continuity so the packet explicitly
  blocks English `I` or English-pronoun drift in external speech.
- Added an external-speech normalization guard for Chinese threads because live
  smoke showed the provider could still emit `I` despite the prompt constraint.
- Applied that guard at the reply API service exit as well as the direct
  processor exit, because the live CLI uses the service path.
- Patched the low-signal action gate so contextual follow-ups such as
  look/check, how-is-it, and continue are not selected as silence before the
  short-term working-memory packet can run.
- Preserved the Stage17/18/24/28 rule that ordinary fast prompts must not
  include raw recent-history dumps.

## Verification

Red result:

```powershell
python -m pytest -q tests\test_stage130_short_term_working_memory.py --basetemp=.pytest_tmp_stage130_red
```

```text
ImportError: cannot import name 'build_short_term_working_memory_lines'
```

Green focused result:

```powershell
python -m pytest -q tests\test_stage130_short_term_working_memory.py tests\test_holo_host.py::ReplyServiceTests::test_reply_service_normalizes_english_i_in_chinese_visible_reply --basetemp=.pytest_tmp_stage130_replyapi
```

```text
8 passed in 0.99s
```

Related regression initially caught an over-broad first implementation that
leaked generic `old line two` history into fast prompts. After tightening the
reducer to include recent evidence only for detected constraints/tasks/repair:

```powershell
python -m pytest -q tests\test_stage130_short_term_working_memory.py tests\test_stage17_realtime_runtime.py tests\test_stage18_dual_speed_reflex.py tests\test_stage24_scene_state.py tests\test_stage25_dense_continuity.py tests\test_stage28_multimodal_homeostatic_kernel.py tests\test_stage124_fast_deep_thought_loop.py tests\test_stage128_biomimetic_continuous_thought_flow.py tests\test_holo_host.py::ReplyServiceTests::test_reply_service_normalizes_english_i_in_chinese_visible_reply --basetemp=.pytest_tmp_stage130_replyapi_related
```

```text
38 passed in 11.64s
```

Full suite:

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage130
```

```text
439 passed in 152.67s (0:02:32)
```

`git diff --check` also exited 0.

The first WSL smokes preserved the no-emoji constraint but still produced an
English `I` prefix in Chinese replies. Stage130 therefore tightened the
short-term language frame and added a visible external-speech normalization
guard at both processor and reply-service exits. The next smoke showed that
`look/check` was still intercepted by the low-signal silence gate, so Stage130
now treats those short contextual follow-ups as reply-worthy rather than
acknowledgement pings.

## Live Smoke Plan

Sync WSL and conduct a live CLI smoke against the exact failure pattern:

1. user asks Holo to reduce emoji;
2. user opens a world-model visual-interface thread;
3. user asks a short continuation such as look/check or how-is-it;
4. Holo should preserve the style constraint, resolve the short turn against the
   pending task, and avoid generic greetings or quiz-like teasing.
