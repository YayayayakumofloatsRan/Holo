# Roadmap Registry

This registry exists so Holo planning does not collapse into a single forced choice every stage.

## Primary Track
- autobiographical continuity
- long-horizon goals
- identity/goal-led deliberation

## Secondary Tracks
- richer desire shaping
- stronger negotiated will

## Next Subject-Runtime Arc

This arc follows Stage17 thread-resident realtime runtime. Its purpose is to make Holo more continuous without turning continuity into a second brain or an unbounded loop.

Stage18: dual-speed reflex and predictive continuity
- Implemented bounded next-turn predictive continuity inside `ActiveThreadState`.
- Uses existing `micro_fast` only as a conservative generation lane after action-market selection.
- Keeps explicit memory/history/factual requests on recall escalation paths.

Stage19: bounded background continuity and attention frontier
- Implemented as a bounded Mind Graph `attention_frontier` fed only by `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`.
- Ingress hydrates same-thread active state from one frontier row before heavier recall.
- Bound entries by count, expiry, evidence refs, and canonical thread key; do not expand initiative sending rights.

Stage20: temporal commitments and interruption recovery
- Persist deferrals, promises, interrupted actions, and restart recovery as temporal commitments.
- Keep `QueueStore` responsible for timing and Mind Graph responsible for subject meaning.
- Route recovery through the action market.

Stage21: policy sedimentation and negotiated will
- Turn repeated outcomes and explicit negotiation into reversible soft policy sediment.
- Bias action-market scoring without weakening hard policy gates.
- Keep owner shutdown, secrets, auth, and safety boundaries outside sediment scope.

## Parked Hypotheses
- broader multi-agent social world
- deeper imagination beyond current recall

## Deferred Experiments
- open-ended world modeling
- explicit multi-step planning
- richer subjective report layer

## Constitutional Constraints
- owner shutdown remains final
- no self-escalation around secrets, auth, or policy
- live repo code is not hot-edited by runtime state loops
- policy boundaries stay hard
- public repos never carry live memory/runtime state
- no second brain layer
- no new unbounded always-on loop
- memory is the self
- processor is replaceable compute
- transport is eyes and hands
- action-market-first deliberation remains the decision path
