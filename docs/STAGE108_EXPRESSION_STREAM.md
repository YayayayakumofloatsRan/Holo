# Stage108 Expression Stream

Stage108 separates internal thought packets from external speech.

Holo should not assume that one internal provider packet equals one visible
message. The external reply can be one sentence, a paragraph, several bubbles,
or a staged follow-up. The mapping must be explicit.

## Core Mapping

```text
Stage107 event
-> expression intent
-> utterance segment
-> bubble / paragraph / delayed bubble
```

Every segment records:

- `segment_role`
- `surface_form`
- `text_budget`
- `delay_ms`
- `source_events`
- `source_phases`
- `content_contract`

This keeps the visible reply tied to the internal loop without dumping internal
state into the user-facing text.

## Segment Roles

`acknowledge`

- Usually driven by a `context_seed` provider return.
- Short opening or grounding sentence.

`semantic_delta`

- Usually driven by a `deliberation_delta` provider return.
- Carries the compressed movement in meaning.

`evidence`

- Driven by `tool_observation`.
- Surfaces observed facts before commitment.

`reply_commit`

- Final visible answer.
- Can be one bubble, a paragraph, or the final part of a multi-bubble reply.

## Granularity

`auto`

- Provider returns become bubbles.
- Tool observations become evidence bubbles.
- Multi-packet loops can become multi-bubble replies.

`single`

- Merge all available internal events into one compact bubble.

`paragraph`

- Merge all available internal events into one paragraph while preserving
  `source_events`.

## Dry Run

```powershell
python -m holo_host stage108-expression-stream --query "回忆任何事情？"
```

If Stage107 has not received a provider return yet, Stage108 produces no
external segments and reports the pending internal packet. This prevents Holo
from speaking before the internal loop has material to externalize.

## Research Meaning

This is the top-level expression layer for the biomimetic flow:

- internal packet stream is working thought;
- delta compression is short-term semantic movement;
- expression segments are externalized speech acts;
- surface granularity is a social and cognitive control variable.

The system can now represent why a response should be one sentence, several
bubbles, or a paragraph, instead of treating reply splitting as a formatting
afterthought.
