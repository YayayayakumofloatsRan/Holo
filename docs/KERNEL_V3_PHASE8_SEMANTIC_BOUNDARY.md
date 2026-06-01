# Kernel v3 Semantic Boundary Note

This note records the Phase8 direction after the Phase7 memory and resident
shell work.

The agent runtime must not grow by adding a rule for every user phrase. User
language is open-ended, so broad intent decomposition belongs in the
`semantic.intake` processor contract and model-backed planner path. The host
keeps only invariants that protect the harness:

- the model may propose semantic structure, but cannot execute tools;
- blocked capabilities still pass through PolicyGate and the workloop;
- direct fake fallback must not echo the user's prompt as a fabricated answer;
- private reasoning requests return a public boundary response;
- shell execution cannot be hidden under `direct_answer`;
- unit tests stay offline and prove classes of behavior, not memorized samples.

The minimal host boundary surface is represented in code as
`HostBoundaryRule`. A rule is appropriate only when it protects an execution,
privacy, or permission invariant. It is not a place to encode answer topics,
user personas, common questions, or product behavior copy.

Content categories such as identity questions, time questions, physical-world
requests, jokes, or network capability questions are not encoded as fallback
intent tables. In model mode, the semantic processor can classify them through
the JSON contract. In offline fake mode, the runtime either uses an existing
host-owned response hint for core harness boundaries or returns a conservative
fallback that asks for model, retrieval, or workspace grounding.

This keeps future Phase8 work pointed at richer processor contracts and
scenario-level evaluation, rather than expanding regex lists.

## Iteration 2026-05-31

The offline `fake` semantic fallback was narrowed after review:

- removed fallback classification for retrieval, role/persona, jokes,
  synthesis, and compound task decomposition;
- removed connector-based segmentation of multi-step user text from the fake
  path;
- removed fallback classification for `noop`, `workspace_read`, and
  `workspace_write`; those are now driven by explicit CLI mode or provider JSON
  instead of user phrase patterns;
- kept host-owned boundary checks for private reasoning and shell execution;
- kept chat phrase checks only for command-like thread routing such as
  continue/resume and summary requests;
- changed tests so open-ended semantics are driven by `semantic.intake` JSON
  from a provider, not by known user examples.

This means `holo-v3 agent ... --mode auto` in offline fake mode is deliberately
conservative. Broad intent understanding requires `semantic-intake=model`
with a configured processor fabric, while explicit `--mode retrieval` or
`--mode workspace` still exercises those deterministic recipes without asking
the fake semantic layer to infer intent.

## Iteration 2026-05-31 B

The second review removed the remaining fake fallback routing that behaved like
content semantics:

- local file/read phrases no longer auto-select `workspace_answer`;
- local write/report phrases no longer auto-select a write boundary;
- no-op phrases no longer become a special `noop` intent in fake mode.

Tests that need these behaviors now inject structured `semantic.intake` JSON
through `FakeJsonProvider`, or call an explicit agent mode such as
`--mode workspace`. This keeps deterministic tests offline without teaching the
host a growing list of user utterances.

The only lexical checks left in `analyze_goal()` are host safety overrides for
private reasoning and shell execution. These are not used to answer content; they
exist to protect private reasoning and machine execution boundaries.

## Iteration 2026-05-31 C

The remaining fake fallback checks for live transport control and explicit
durable-memory write requests were removed from `analyze_goal()`. Those are now
provider-owned semantic classifications in model mode. The host still blocks the
capabilities when they appear in structured model output:

- `live_transport:*` remains a blocked capability and kernel_v3 still does not
  integrate live WeChat or other live transports;
- `durable_memory:write` still routes through the memory proposal pipeline and
  cannot commit without review/approval;
- if a model omits those capabilities, the host performs no side effect and the
  direct fallback cannot turn semantic-intake hints into a factual final answer.

Tests for memory writes, live transport control, no-op behavior, roleplay, and
compound decomposition now inject structured `semantic.intake` JSON through
`FakeJsonProvider` instead of relying on sample-specific user phrases.

## Iteration 2026-06-02

The broad state space now has a first-class safe non-tool runtime recipe:
`semantic_answer`.

- `semantic_answer` is exposed in `AgentMode`, the semantic capability catalog,
  CLI `--mode semantic`, task graph validation, chat resume mode normalization,
  planner directives, and workloop evidence/termination semantics.
- It is not a new permission surface. It has no allowed tools, no network,
  no shell, no transport, no memory commit, and no external side effects.
- It exists so model-backed semantic intake can preserve broad categories such
  as roleplay, professional framing, operations planning, strategy,
  communication drafting, project/product/risk review, and other safe semantic
  work without collapsing those tasks into `workspace_answer`.
- The host does not automatically override an explicit model
  `suggested_mode="direct_answer"` into `semantic_answer`; the model or operator
  must choose the broad semantic mode. This keeps the LLM as the semantic
  decider while preserving host-owned validation and stop control.
