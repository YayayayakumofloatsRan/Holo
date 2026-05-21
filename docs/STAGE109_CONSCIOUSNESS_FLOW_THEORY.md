# Stage109 Consciousness Flow Theory

Stage109 formalizes the theory behind the recent implementation work.

## Thesis

For provider-above agents, a consciousness-like flow is not produced by one
large prompt. It is produced by controlling:

1. finite context packets;
2. local memory and semantic attractor selection;
3. provider-return compression;
4. tool observations;
5. external expression granularity.

This makes the system publishable as a mechanistic architecture rather than a
metaphysical claim about subjective consciousness.

## Five Axioms

`A1_finite_context`

Every provider call receives a bounded packet. There is no infinite context.

`A2_local_continuity`

Continuity is local. It is carried by selected memory, semantic attractors, and
compressed deltas.

`A3_compressive_recurrence`

The stream is recurrent: packet, return, compression, next packet.

`A4_grounded_perturbation`

Tools insert observations into the loop before commitment. This is how Holo
reduces hallucination pressure without retraining the provider.

`A5_expression_decoupling`

Visible speech is not equal to internal packets. One internal event can become
several bubbles; several internal events can merge into one paragraph.

## Stage Mapping

| Stage | Mechanism | Theoretical Role |
| --- | --- | --- |
| 104 | semantic attractors | Long-term local compression into reusable meaning basins |
| 105 | finite provider packet stream | Decide whether to send, how many packets to send, and when to stop |
| 106 | provider tool affordance adapter | Let provider propose tools while Holo keeps execution authority |
| 107 | packet-return-delta loop | Advance packet, return, distill, observation, and stop phases |
| 108 | expression stream realization | Map internal events to bubbles, paragraphs, delayed segments, or no output |

## Falsifiable Hypotheses

`H1_attractor_stability`

Stable semantic attractors improve continuity under finite context budgets.

`H2_compression_continuity`

Provider-return delta compression preserves enough semantic movement for the
next packet.

`H3_grounded_tool_perturbation`

Tool observations reduce hallucination pressure when inserted before reply
commitment.

`H4_expression_granularity`

External granularity should follow internal event topology and social pressure.

`H5_stop_control`

Explicit no-send and wait states prevent compulsive provider calls and
premature speech.

## Measurement Plan

`source_event_coverage`

Fraction of external segments with at least one Stage107 source event.

`delta_retention`

Overlap between provider-return semantic claims and the next packet's
`previous_delta`.

`grounding_ratio`

Share of factual claims supported by tool observations or selected memory.

`expression_granularity_fit`

Agreement between internal event topology and the chosen surface form.

`premature_expression_rate`

Rate of external segments emitted before a provider return or tool observation
is available. Expected value: `0`.

## Literature Bridge

Stage109 connects Holo to several primary research lines:

- Chain-of-Thought prompting: intermediate reasoning steps can improve model
  behavior.
- ReAct: reasoning and acting can be interleaved.
- Toolformer: language models can learn when tool use helps.
- Reflexion: verbal feedback and memory can improve later behavior.
- Generative Agents: observation, memory, reflection, and planning can produce
  believable continuity.
- Self-Refine: iterative feedback and refinement can improve outputs without
  new training.

Holo's contribution is a provider-above version of these ideas: the base model
remains external, while finite packets, tool observations, compression, memory,
and expression control are handled locally and made observable.

## CLI

```powershell
python -m holo_host stage109-consciousness-theory --query "回忆任何事情？"
```

The command returns a structured theory frame with axioms, stage mapping,
hypotheses, metrics, literature bridge, and publication contribution.
