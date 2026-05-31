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
- kept host-owned boundary checks for private reasoning, shell execution, live
  transport control, explicit durable-memory writes, local workspace writes,
  and missing file targets;
- kept chat phrase checks only for command-like thread routing such as
  continue/resume and summary requests;
- changed tests so open-ended semantics are driven by `semantic.intake` JSON
  from a provider, not by known user examples.

This means `holo-v3 agent ... --mode auto` in offline fake mode is deliberately
conservative. Broad intent understanding requires `semantic-intake=model`
with a configured processor fabric, while explicit `--mode retrieval` or
`--mode workspace` still exercises those deterministic recipes without asking
the fake semantic layer to infer intent.
