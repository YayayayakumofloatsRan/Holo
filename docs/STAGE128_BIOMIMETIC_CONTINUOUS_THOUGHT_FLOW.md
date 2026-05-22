# Stage128 Biomimetic Continuous Thought Flow

Stage128 fixes a behavioral failure exposed by live Holo CLI testing:
the fast first packet could terminate a turn with a shallow acknowledgement even
when the user was asking for memory depth, factual self-report, runtime state,
or a short contextual follow-up.

The goal is not to remove shallow replies. The goal is to separate:

1. first reaction: fast, cheap, optionally user-visible
2. internal continuation: deeper packet, tool-capable, state-aware
3. final speech: compact external answer grounded in the deeper packet

## Observed Failure

The live transcript showed three linked problems:

- A memory-depth query received a metaphor-heavy answer instead of a factual
  memory/store/time answer.
- A later "answer is?" style follow-up collapsed into a single-word answer.
- Some turns ended after the `micro_fast` packet; no `subject_main` packet was
  sent.

Live `trace-hybrid-recall` confirmed that the memory layer was retrieving
material, but the top-ranked memories included prior bad answers. The problem
was therefore not just missing retrieval. The reply contract let style and
recent echo dominate over factual memory reporting.

## Runtime Contract

Stage124 now has a deterministic deep-packet guard. Regardless of what the fast
model says, Holo must continue to the deep packet for:

- memory or temporal recall
- self-model or identity questions
- runtime, tool, internal state, or packet-flow questions
- factual correction turns such as "answer honestly" or "do not use metaphor"
- unclear short contextual follow-ups such as "so what is the answer?"

When the guard fires, Holo preserves the shallow reply as the first reaction,
but still sends the deep packet. That keeps the biomimetic first moment without
letting the first moment become the whole mind.

## Prompt Contract

For ordinary chat, Holo still hides internal machinery and answers naturally.

For memory, self-model, runtime, tool, or factual self-report turns, the chat
prompt now injects a `Fact Grounded Self Report` section:

- answer concrete facts before style
- describe Holo as a single-subject agent runtime over local WSL brain state,
  memory stores, tool loops, and provider packets
- do not claim biological consciousness or private human feelings
- name concrete memory stores when available: archive, working memory,
  mind_graph, vector hits, active_thread_state
- if a date/source is not proven by the current packet, say so
- never let shallow first reaction replace the deeper packet

The recall reconstruction prompt also now tells the model to prefer concrete
stores, dates, stages, and source anchors over metaphor when the user asks what
the memory is or when it began.

## Verification

Focused red/green test:

```powershell
python -m pytest -q tests\test_stage128_biomimetic_continuous_thought_flow.py tests\test_stage124_fast_deep_thought_loop.py --basetemp=.pytest_tmp_stage128_fact_green
```

Result:

```text
9 passed in 0.31s
```

Related recall, packet, tool, and reply tests:

```powershell
python -m pytest -q tests\test_stage124_fast_deep_thought_loop.py tests\test_stage128_biomimetic_continuous_thought_flow.py tests\test_stage123_internal_tool_flow.py tests\test_stage121_conscious_packet_scheduler.py tests\test_rag_memory.py --basetemp=.pytest_tmp_stage128_related2
```

Result:

```text
52 passed in 3.94s
```

Full repository verification:

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage128_fact_final
```

Result:

```text
429 passed in 69.19s (0:01:09)
```
