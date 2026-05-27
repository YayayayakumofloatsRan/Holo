# Stage202 Market Research Dossier Resume Action

## Purpose

Stage201 made market-research dossiers durable. Stage202 makes that durable state actionable in the live agent loop.

Holo can now expose `market_research_dossier_resume` as a model-visible action. The model may choose it when a user asks to continue an existing market-research task, and the host executes the action through the Stage201 registry and Stage200 resume path.

## Schemas

- `holo.stage202.market_research_dossier_resume_action.v1`
- Existing Stage201 registry schemas remain the persisted state surface.

## Action Space

`market_research_dossier_resume` is now part of the Stage161 tool action space.

Inputs:

- `thread_key`
- `project_key`
- `query`
- `max_actions`

Observation:

- `market_research_dossier_resume_ledger`

The action is read-oriented over runtime state. It does not require network by itself, although the resumed Stage200 next action may use network if allowed by runtime policy.

## DeepSeek Native Tool Loop

Stage152 now registers and executes `market_research_dossier_resume`.

When called, the host:

1. Loads the latest Stage201 dossier for the supplied thread/project.
2. Runs the Stage200 resume path.
3. Records `stage201_market_research_dossier_registry`.
4. Records `market_research_dossier_resume_ledger`.
5. Emits a tool message back into the provider tool loop.

The provider remains proposer. The host remains executor and ledger authority.

## FSM

Stage160R accepts `market_research_dossier_resume` as a mandatory model-selected action. A resumable or already-complete dossier can stop with `final_answer_ready`. Missing persisted dossier state stops with `needs_user_clarification`.

## Observability

Stage153 continues to render:

```text
[market_registry] status=resumed lookup=found action=web_search stop=final_answer_ready
```

The action ledger is also preserved in Stage152 public metadata and reply/archive metadata.

## Boundaries

Stage202 does not:

- call provider models by itself
- write memory
- start WeChat
- widen transport authority
- expose raw hidden reasoning
- add an unbounded loop
