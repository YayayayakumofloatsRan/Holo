# Holo Kernel v3 Working Rules

Kernel v3 is a host-owned agent harness.

Hard invariants:
- The model proposes; the host validates, executes, records, and verifies.
- Journal is the source of truth.
- Memory is derived from journal and observations.
- Tools never execute without PolicyGate validation.
- LoopControllerV3 must not dispatch by concrete tool names.
- Transports are not decision makers.
- No live WeChat integration in kernel_v3.
- No long-term memory commits in the runnable skeleton.
- No real model/network calls in unit tests.

Preferred implementation style:
- Typed contracts first.
- Small modules with narrow seams.
- Fake components before live providers.
- Append-only trace for every state transition.
- Tests must prove resume, blocking, generic dispatch, and evaluator-driven continuation.
