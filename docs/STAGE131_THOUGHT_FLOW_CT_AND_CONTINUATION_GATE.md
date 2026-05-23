# Stage131 Thought Flow CT And Continuation Gate

Stage131 addresses two live CLI failures that Stage130 did not fully close:

- short Chinese reference questions such as `what process` were still classified
  as low-signal because the question detector depended on stale mojibake hints;
- a short acknowledgement such as `ok` after Holo asked an open continuation
  question could still be selected as silence;
- the user-visible no-emoji preference remained prompt-only and could be missed
  by the provider;
- background processor usage was visible only through raw ledgers, not as a
  practical packet-flow view.

The core design choice is that biomimetic improvement must be observable at the
packet boundary. Holo still uses the provider as a bounded language processor,
so the local subject runtime must show what it sent, why it sent it, and whether
background calls are consuming budget without changing visible behavior.

## Runtime Contract

Stage131 adds a continuation gate over the Stage5 action market:

- Chinese question hints are normalized with real Unicode terms, so reference
  questions are not treated as fast pings.
- A short acknowledgement is reply-worthy when the immediately previous Holo
  turn contains an open continuation cue.
- The active-thread fast packet keeps only the last two dialogue lines, so the
  real-time path can still see the cue without restoring a raw history dump.
- The short-term working memory packet records this as `pending_open_loop`,
  which reaches both normal reply prompts and the Stage124 fast/deep loop.
- When this gate fires, action selection cannot force the turn into silence or
  defer solely because the text is short.

Stage131 also hardens the visible output guard:

- if the current or recent Chinese thread includes a no/reduce-emoji correction,
  visible replies are scrubbed for emoji after provider generation;
- this is a channel guard, not a semantic rewrite.

## CLI CT

Stage131 adds a read-only CLI packet-flow view:

```powershell
python -m holo_host trace-thought-flow --thread-key holo_cli:main --chat-name HoloCLI --channel holo_cli --limit 8
```

Inside the interactive CLI:

```text
/ct
```

The CT view renders:

- action gate selections from the consciousness ledger;
- whether a fast packet and deep packet were observed;
- reply packet usage by lane, provider, model, token count, and latency;
- background processor calls such as reflection, operator planning, or
  self-model observation.

This is intentionally not a chain-of-thought dump. It is the operational
packet trace needed to improve biomimetic scheduling without depending on
private model internals.

## Verification

Focused Stage131 regression:

```powershell
python -m pytest tests\test_stage131_thought_flow_trace.py -q
```

Result:

```text
7 passed in 0.58s
```

Stage130 and reply-service regression:

```powershell
python -m pytest tests\test_stage130_short_term_working_memory.py -q
python -m pytest tests\test_holo_host.py::ReplyServiceTests::test_reply_service_can_choose_silence_as_a_first_class_action tests\test_holo_host.py::ReplyServiceTests::test_reply_service_normalizes_english_i_in_chinese_visible_reply -q
```

Result:

```text
7 passed in 0.65s
2 passed in 0.70s
```

Full suite:

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage131c
```

Result:

```text
446 passed in 150.79s (0:02:30)
```
