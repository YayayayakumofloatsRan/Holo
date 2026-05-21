# Stage110 Theory-Guided Packets Design

## Context

Stage109 defines the theory. Stage105 plans packets. The missing step is a
policy layer that translates theoretical constraints into practical provider
packet guidance.

## Design

Stage110 takes:

- Stage105 packet plan;
- Stage109 theory frame.

It emits:

- recommended packet count;
- recommended packet budget;
- applied axioms;
- packet rules;
- tool policy;
- expression policy;
- measurement hooks.

## Guidance Rules

- Broad recall or multiple attractors preserve a three-packet stream and expand
  budget.
- Lookup or tool-first plans require local tool execution before reply commit.
- No-send plans preserve stop control and recommend zero packets.
- Expression cannot emit before provider return or tool observation.
- Measurement hooks require packet budget, delta retention, grounding, and
  expression-fit recording.

## Tests

- Broad recall expands budget.
- Lookup is tool-first.
- No-send remains stopped.
- Ready-to-continue waits for internal return before expression.
- CLI emits Stage110 and Stage109 linkage.
