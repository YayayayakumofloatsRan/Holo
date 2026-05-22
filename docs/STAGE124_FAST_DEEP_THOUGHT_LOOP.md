# Stage124 Fast-Deep Thought Loop

Stage124 implements the first production cut of Holo's continuous packet flow:
every external input first enters a fast provider packet, and only then moves
into deeper packets when the fast packet says more work is needed.

## Contract

For any channel input, including CLI, app, or WeChat:

1. Holo sends a `micro_fast` fast packet.
2. The fast packet returns compact JSON:
   - `intent`
   - `scene`
   - `deep_packet_needed`
   - `shallow_reply`
   - `speak_now`
   - `continue_until`
3. If `deep_packet_needed=false` and `shallow_reply` is present, Holo can return
   the shallow reply immediately.
4. If `deep_packet_needed=true`, Holo appends the fast packet as
   `Stage124 Deep Packet Context`, runs recall/tool/deep context assembly, and
   sends the deeper provider packet.
5. External speech is committed when the answer is sufficient.

The fast packet is not raw hidden reasoning. It is structured triage metadata
used to decide whether to answer shallowly or continue into deeper packets.

## Runtime Integration

`CodexCliProcessor.generate()` now runs:

1. `stage124_fast_packet` on `micro_fast`
2. optional shallow return
3. recall reconstruction only if deeper work is needed
4. normal Stage121/122/123 deep packet flow with appended Stage124 context

The existing boundaries remain:

- Stage121 controls budget and depth for the deep packet.
- Stage122 separates internal intent, local processing, and external speech.
- Stage123 allows internal tool flow through provider `tool_calls`, with local
  execution remaining in WSL Stage113.

## Why This Matters

This gives Holo a more human-like cadence:

- quick first appraisal
- optional immediate surface expression
- slower internal continuation when needed
- deeper retrieval/tool grounding before final expression

It also prevents trivial turns from always paying the cost of deep recall.

## Verification

```powershell
python -m pytest -q tests\test_stage124_fast_deep_thought_loop.py --basetemp=.pytest_tmp_stage124
```
