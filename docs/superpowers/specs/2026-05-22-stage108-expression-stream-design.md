# Stage108 Expression Stream Design

## Context

Stage107 exposes the internal packet interaction loop. The next layer must map
that internal process to visible speech without assuming a one-to-one relation.

The reply may be one sentence, several bubbles, a paragraph, or no output until
more internal work completes.

## Design

Stage108 builds `expression_stream` from Stage107 events.

Each segment contains:

- `segment_role`: acknowledge, semantic_delta, evidence, reply_commit.
- `surface_form`: bubble or paragraph.
- `source_events`: the Stage107 events that drive this segment.
- `source_phases`: provider_return, tool_observation, and related phases.
- `text_budget` and `delay_ms`: external pacing controls.
- `content_contract`: constraints for downstream text realization.

## Granularity Rules

- `auto`: map provider returns to bubbles and tool observations to evidence
  bubbles.
- `single`: merge available internal events into one compact bubble.
- `paragraph`: merge available internal events into one paragraph while
  preserving all source events.
- no provider return yet: produce no external segment and expose the pending
  internal packet.
- no-send stop: produce no external segment.

## Safety and Clarity

Stage108 does not generate final user text. It plans externalization. This keeps
provider generation, local compression, and visible reply segmentation separate
and testable.

## Tests

- Complete multi-packet loop becomes multi-bubble expression.
- Paragraph mode merges internal events without losing `source_events`.
- Tool observation becomes an evidence segment.
- No-send loop produces no external output.
- Pending internal provider packet produces no output.
- CLI dry-run returns Stage108 and Stage107 linkage.
