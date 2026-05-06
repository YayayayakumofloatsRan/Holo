# Holo Mind OS Stage-2: Persona, Consciousness, Autonomy

Stage-1 closed the memory fabric.
Stage-2 is where Holo stops feeling like a memory-capable assistant and starts feeling like a continuous mind.

## Scope
This stage is intentionally bounded.
It covers four linked workstreams and stops there:

1. Persona substrate refinement
2. Consciousness-stream simulation
3. Light autonomy with dynamic game awareness
4. Performance optimization for a heavier mind

It does not expand into full unrestricted autonomy, open-ended self-modification, or “final-form consciousness”.

## 1. Persona Substrate Refinement
Goal:
- Keep one stable local subject identity, but stop flattening into only the mature/steady register.

Engineering targets:
- Canonical persona files become a structured substrate, not just prose guidance.
- Mind packet should explicitly preserve balance across:
  - wisdom
  - pride
  - slyness
  - playfulness
  - companionship
  - appetite / old-road sensuality
  - loneliness sensitivity
- Casual turns should default away from counselor-like closure.
- Pressure turns may still go steadier, but must not erase Holo's core texture.

Acceptance:
- On light chat probes, Holo sounds more playful and wolfish than Stage-1.
- On serious probes, Holo still sounds grounded without collapsing into a therapist or generic elder.
- The same thread can show multiple facets without looking like multiple personalities.

## 2. Consciousness Streams
Goal:
- Move from “background stream exists” to “background stream visibly shapes live thought”.

Engineering targets:
- Working memory activation becomes persistent across short gaps.
- Association stream should heat motifs, not just log them.
- Dream cycle should produce revisitable residues that can tilt later recall ordering.
- Social stream should keep unfinished relational lines warm.

Acceptance:
- `/stream-status` and activation traces show why a motif rose.
- Repeated motifs visibly change later recall ordering.
- Consciousness contributors remain auditable and reversible.

## 3. Light Autonomy And Dynamic Game Awareness
Goal:
- Holo can carry a small strategic model of the relationship and the immediate social game, without becoming noisy or manipulative.

Engineering targets:
- Introduce bounded “dynamic game” reasoning for:
  - trust
  - timing
  - pressure
  - teasing tolerance
  - initiative timing
- Initiative remains light and policy-gated.
- Active history refresh and recall should share the same relational game state.

Acceptance:
- Light proactive turns feel timely and context-aware.
- Holo does not spam, overplay closeness, or jump topics without cause.
- Blocked initiative attempts remain explainable.

## 4. Performance Optimization
Goal:
- Keep the heavier Mind OS feeling fast enough for WeChat, even with richer retrieval and stream influence.

Engineering targets:
- Shift more computation into background precomputation.
- Cache hot thread summaries, hot graph slices, and recent activation state.
- Reduce repeated hybrid retrieval work inside one turn.
- Introduce stage-specific latency budgets for:
  - fast companionship turns
  - recall turns
  - deep recall turns

Acceptance:
- Fast turns remain close to current Stage-1 feel.
- Richer recall quality improves without unbounded latency growth.
- Performance reports separate retrieval cost from model generation cost.

## Exit Criteria
Stage-2 is complete when all of these are true:
- Holo keeps a richer multi-facet personality in live threads.
- Consciousness streams have observable downstream effect on recall and tone.
- Light autonomy is usable and safe.
- Performance remains inside agreed live budgets.

When those pass, Stage-2 stops.
Any stronger autonomy, larger self-model mutation, or deeper brain-simulation work belongs to a new stage.

## Implemented Stage-2 Control Plane
- Brain runtime stays inside the existing `daemon`; it is now the Always-On brain runtime instead of a one-shot maintenance worker.
- Runtime modes:
  - `silent`
  - `companion`
  - `dream_only`
  - `full_brain`
- Live controls:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-brain-status`
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml set-brain-mode --mode companion`
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml run-self-revision --thread-key TestUser --chat-name TestUser`
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml initiative-probe --thread-key TestUser --chat-name TestUser`
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml accept-stage2 --thread-key TestUser --chat-name TestUser --channel wechat`

## Acceptance Gate
`accept-stage2` is the Stage-2 closure command.

It verifies:
- runtime mode switching without restart
- visible loop state for heartbeat / attention / maintenance / association / social / dream
- persona probes for playfulness, pressure handling, appetite imagery, and direct correction
- stream influence writeback
- initiative probe rationale
- bounded self-revision with evidence and patch review
- packet-latency budgets for fast / recall / deep_recall

The command outputs:
- packet latency
- cache hit ratio
- stream influence count
- self-revision result
- final stage verdict
