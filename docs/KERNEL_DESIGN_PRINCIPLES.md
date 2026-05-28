# Holo Agent Kernel Design Principles

Kernel version: `2.1.0`

This document is runtime architecture guidance, not a stage log. Stage files
record iteration history; kernel files define stable product behavior.

## Primary Principle

LLM proposes and judges semantic work. The host constrains, executes, records,
and verifies.

The kernel should not grow a keyword-rule brain. Deterministic code is allowed
for:

- action-space rendering
- context assembly
- tool execution
- safety and boundary checks
- retry and budget control
- observation ledgers
- public metadata sanitization
- fallback behavior when no model is configured

Deterministic code should not be the primary mechanism for semantic decisions
such as:

- whether a source is relevant enough
- whether more search is needed
- whether a task is complete
- whether a final answer satisfies the user goal
- which tool should be used next
- whether conflicting evidence changes the conclusion

Those decisions belong to the model, with the host requiring auditable JSON
contracts and validating claims against ledgers.

If no model provider is configured, the kernel may use explicit fallback logic
for development. Fallback output must be labeled by configuration and must not
be treated as the target intelligence path.

## Agent Workflow

The intended loop is:

```text
observe -> compile context -> expose action space -> model_decide
-> host_validate -> act_or_skip -> observe_result
-> model_evaluate -> stop_or_continue -> final
```

The host can reject unsafe or invalid actions. The model decides the next
meaningful action within that bounded action space.

## Web Research Loop

For research tasks, the kernel must not be just a single `web_research()`
function. The host exposes a bounded research crawler contract:

```text
SearchGoal -> SearchPlan -> search/open observations
-> source graph -> evidence items -> citations -> CrawlReport
```

The model still decides meaningful next actions. The host records the research
state in structured objects so the model can see source policy, evidence gaps,
consulted sources, rejected sources, and citations without inventing them.

The interactive path is:

```text
model_decide -> web_search -> observation
model_decide -> open_page -> observation
model_decide -> answer_direct | continue_search | ask_clarification
```

Lexical scores are fallback diagnostics only. They are not the authority for
accepting a source when a model evaluator is available.

Research contexts should expose source authority. Primary evidence such as
regulatory filings, company investor-relations pages, official documentation,
and official repositories must be distinguishable from secondary commentary.

Final citations should be built from evidence items, not free-form model text.

## Failure Rule

If a tool was attempted and failed, final output must report the attempted
failure. It must not claim future intent such as "I will search" after the
search already failed.

## Engineering Tool Rule

Engineering actions should be primitive and ledgered:

```text
workspace_search -> file_read -> apply_patch -> test_run -> git_diff/status
```

The model decides which action is next. The host enforces workspace boundaries,
safe command allowlists, and public observation records.

For engineering changes, the model receives explicit workflow policy in the
context. Final engineering claims are checked against observation ledgers before
delivery.

## Public Trace

The CLI should show auditable workflow events:

```text
[goal]
[context]
[action_space]
[model_decide]
[tool_call]
[observation]
[evaluate]
[stop]
[final]
```

It should not expose hidden chain-of-thought. It should expose decisions,
actions, observations, and stop reasons.
