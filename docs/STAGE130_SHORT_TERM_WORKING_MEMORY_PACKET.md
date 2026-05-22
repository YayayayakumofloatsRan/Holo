# Stage130 Short Term Working Memory Packet

Stage130 fixes a live CLI failure where Holo failed to carry immediate context
across adjacent turns:

- the user asked to reduce emoji, but later replies drifted back into emoji;
- a pending "search papers about world models and real-time interaction" thread
  collapsed into a generic greeting or unrelated answer;
- a confused "???" after a misaligned answer was treated as a fresh prompt
  instead of a correction signal;
- the fast first packet only saw the current user text, so short follow-ups
  such as "look into it" or "how is it?" could not resolve against the previous
  task.

The root issue was not simply that recent history was too short. Earlier stages
intentionally kept fast prompts history-light. The missing layer was a bounded
working-memory reducer that extracts only the short-term facts that must govern
the next packet.

## Runtime Contract

Stage130 adds a `Short Term Working Memory` frame before the current turn. It
is not a raw history dump. It only surfaces bounded, high-priority local state:

- recent user style constraints, such as reducing emoji;
- pending local tasks or search/research continuations;
- repair focus after a confused or corrective follow-up;
- language continuity, especially avoiding English pronoun drift in Chinese threads;
- continuation rules for short turns that depend on the previous task.

The same short-term frame is also passed into the Stage124 fast packet. This is
important because the first packet is where many bad turns were born: if the
fast packet sees only "how is it?", it may answer as a new greeting. If it sees
the short-term frame, it can classify the turn as a continuation and force the
deep packet when needed.

Stage130 also adds a small external-speech normalization guard for Chinese
threads: if a provider still emits English `I` directly attached to Chinese
text, the visible reply is normalized to Chinese first-person wording. This is
not a semantic rewrite; it is a channel-visible language consistency guard.
The guard is applied both in the direct processor path and in the reply API
service path, because the live CLI uses the service path.

The action-selection low-signal gate is also patched for contextual follow-up
turns such as "look/check", "how is it", and "continue". These turns are short,
but they are not acknowledgements; they must reach the working-memory and
deep-packet path instead of being selected as silence.

## Boundary

Stage130 deliberately does not reintroduce a raw recent-history block into fast
paths. Stage17, Stage18, Stage24, and Stage28 still require ordinary active
threads to stay compact. The reducer only includes recent evidence when it has
detected a concrete constraint, pending task, or repair signal.

## Verification

Focused red/green and reply-service exit test:

```powershell
python -m pytest -q tests\test_stage130_short_term_working_memory.py tests\test_holo_host.py::ReplyServiceTests::test_reply_service_normalizes_english_i_in_chinese_visible_reply --basetemp=.pytest_tmp_stage130_replyapi
```

Result:

```text
8 passed in 0.99s
```

Related active-thread and thought-loop regression:

```powershell
python -m pytest -q tests\test_stage130_short_term_working_memory.py tests\test_stage17_realtime_runtime.py tests\test_stage18_dual_speed_reflex.py tests\test_stage24_scene_state.py tests\test_stage25_dense_continuity.py tests\test_stage28_multimodal_homeostatic_kernel.py tests\test_stage124_fast_deep_thought_loop.py tests\test_stage128_biomimetic_continuous_thought_flow.py tests\test_holo_host.py::ReplyServiceTests::test_reply_service_normalizes_english_i_in_chinese_visible_reply --basetemp=.pytest_tmp_stage130_replyapi_related
```

Result:

```text
38 passed in 11.64s
```

Full suite:

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage130
```

Result:

```text
439 passed in 152.67s (0:02:32)
```
