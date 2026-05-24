# Stage140 Memory Answer Grounding

Date: 2026-05-24

## Purpose

Stage140 applies the Stage139 grounding pattern to memory answers. Holo may still use provider language freely, but visible speech is no longer allowed to confidently claim memory unless the turn carries a normalized local memory evidence ledger.

The practical rule is simple: if Holo says "I remember", "you told me before", "we discussed", "from memory", or equivalent Chinese phrasing, the final reply must be backed by a `memory_observation_ledger`. When the evidence is weak or absent, visible language is softened or repaired before delivery and archive.

## What Landed

### Memory Observation Ledger

`holo_host/memory_grounding.py` defines `holo.memory_grounding.v1` rows with:

- `memory_call_id`
- `source_family`: `working`, `durable`, `candidate`, `archive`, `mind_graph`, `vector`, `current_context`, or `none`
- `selected_ids`
- `status`: `grounded`, `weak`, `missing`, or `contradicted`
- `summary`
- `confidence`
- `freshness`
- `grounding_tags`
- `contradiction_flags`
- `missing_source`

The normalizer reads existing Holo evidence without writing memory:

- selected memory ids and activation trace ids from the sidecar;
- recall reconstruction metadata;
- vector hits;
- memory-related tool observations;
- current-context fallback;
- active history refresh reports;
- explicit missing-source rows for direct memory questions with no source.

### Visible Claim Gate

The memory claim scanner covers English and Chinese claim families:

- `I remember`
- `you told me before`
- `from our previous conversation`
- `your preference was`
- `我记得`
- `你之前说过`
- `我们聊过`
- `从记忆里`
- `你以前的偏好`

Ungrounded memory claims are marked as `ungrounded_memory_claim` and repaired. Weak memory sources are marked as `weak_memory_source` and turned into bounded, tentative language.

### Runtime Propagation

`CodexCliProcessor` now adds `memory_observation_ledger` to `ReplyPlan.debug` on both fast-only and deep paths.

`HoloReplyService` now attaches `memory_observation_ledger` and `memory_grounding` to:

- outgoing message metadata;
- archive and observe metadata;
- final reply JSON.

Stage139 tool grounding still handles tool claims. If the only missing tool family is `memory`, Stage140 takes over the visible memory repair so the user sees one coherent limitation rather than a tool-specific false-negative.

### Stage135 Topology

Stage135 now renders actual `memory_observation_*` nodes. These nodes connect into `holo_self` and `memory_delta`, making the visible topology show whether a recall statement was grounded by archive, durable memory, vector hits, current context, or a missing source.

## Operator Contract

Stage140 is read-only with respect to memory. It does not introduce self-memory writes, background reflection loops, transport-side authority, or a new provider call path.

The execution order remains:

1. Processor fabric builds reply and debug metadata.
2. Tool observations are normalized.
3. Memory observations are normalized from existing sidecar/tool/debug evidence.
4. Tool grounding repairs non-memory tool claims.
5. Memory grounding repairs visible memory claims.
6. The repaired reply is bubbled, delivered, archived, and exposed in JSON.

## Verification

Targeted tests:

```powershell
python -m pytest tests\test_memory_grounding.py tests\test_tool_grounding.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage140-targeted
```

Observed result:

```text
16 passed in 0.69s
```

Reply API regression:

```powershell
python -m pytest tests\test_holo_host.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage140-holo-host
```

Observed result:

```text
74 passed in 27.86s
```

## Remaining Work

Stage140 blocks confident false recall claims, but it does not yet prove that selected memory content is semantically sufficient for every detailed claim. The next useful layer is claim-to-source alignment: compare the concrete entity, preference, date, and event mentioned in the answer against the selected memory summaries and selected ids.

After that, the A' to A'' stream should use memory grounding as a continuation feature: weak or missing memory should trigger clarification or bounded recall rather than a confident second bubble.
