# Stage160R Depersonalized Agent Loop FSM

Date: 2026-05-27

## Purpose

Stage160R replaces the `holo_cli` companion/persona harness with a deterministic host-owned agent loop:

```text
observe -> decide -> act_or_skip -> observe_result -> evaluate_stop -> repeat_or_final
```

The goal is to make every tool decision auditable. A candidate is no longer enough: mandatory actions must execute, be rejected, or fail with an explicit stop reason before visible final speech.

## Schemas

```text
holo.stage160r.agent_loop_fsm.v1
holo.stage160r.loop_step.v1
holo.stage160r.intent_frame.v1
holo.stage160r.goal_state.v1
holo.stage160r.prompt_policy.v1
```

## Runtime Rules

- `holo_cli`, `engineering`, `research`, `project`, and future domain channels use a depersonalized prompt policy.
- Core agent-kernel prompts strip WeChat/social/persona phrasing, playful teasing, and fixed persona openers.
- Every turn builds an `intent_frame` before provider generation.
- Memory, web, engineering, and project-state intents declare mandatory actions and required observations.
- Follow-up turns such as `还有呢？`, `继续`, `然后呢`, `?`, and `？` inherit the previous open goal when available.
- The host FSM validates mandatory actions independently from DeepSeek tool-call behavior.
- Stage153 event streams render FSM steps as `[goal]`, `[decide]`, `[act]`, `[observe]`, `[evaluate]`, `[stop]`, and `[final]`.
- New turns must not end with canonical stop reason `unknown`.

## Memory Recall

Memory recall is host-owned. If a turn asks for recall, the FSM requires a memory observation ledger. If no grounded source is available, final speech degrades to a failure report such as:

```text
I attempted memory_recall but found no grounded prior-conversation evidence.
```

This prevents Holo from inventing companion-style memories when the retrieval surface did not provide evidence.

## Web Failure Handling

If `web_search`, `open_page`, or `find_in_page` is mandatory and fails, final speech reports the attempted failure and does not say that a search will happen later or still needs to be completed.

Example:

```text
web_search was attempted but failed: timeout. I cannot treat this as current web evidence.
```

## Boundaries Preserved

Stage160R does not add provider calls, memory writes, new tools, transport changes, WeChat starts, domain modules, approval UI, or hidden reasoning exposure. DeepSeek may propose or synthesize; the host FSM controls mandatory action completion and stop reason.

