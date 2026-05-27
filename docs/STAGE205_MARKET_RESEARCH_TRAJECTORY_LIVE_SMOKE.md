# Stage205 Market Research Trajectory Live Smoke

## Purpose

Stage204 made market-research dossier resume visible as a bounded multi-action trajectory. Stage205 adds a repeatable live-smoke bundle around that trajectory so the agent substrate can verify the full path before claiming it can do current market research:

```text
persisted weak dossier -> resume -> web_search -> market_research_pack -> market_research_report -> CLI trace -> topology -> artifacts
```

The default test path is deterministic and provider-free. A non-dry-run path can use the configured Stage151 web/open-page surfaces, but test acceptance does not require live network.

## Schema

```text
holo.stage205.market_research_trajectory_live_smoke.v1
holo.stage205.market_research_trajectory_live_smoke_result.v1
holo.stage205.market_research_trajectory_scorecard.v1
```

## CLI

```powershell
python -m holo_host run-market-research-trajectory-live-smoke --output artifacts\stage205\stage205_trajectory_live_smoke.html --dry-run
```

Optional live-network probe:

```powershell
python -m holo_host run-market-research-trajectory-live-smoke --output artifacts\stage205\stage205_trajectory_live_smoke.html
```

Use `--network-disabled` to verify boundary handling.

## What Is Visible

Stage205 writes:

- `.html`
- `.json`
- `.jsonl`

The HTML includes a concise public trace with:

```text
[goal]
[market_registry]
[market_trajectory]
[stop]
[final]
```

This is the supported substitute for raw hidden thought. It exposes auditable public decisions, actions, observations, and stop state without leaking provider `reasoning_content`.

## Scorecard

Checks include:

- trajectory exists
- trajectory reaches `ready` when evidence is sufficient
- action sequence is `web_search -> market_research_pack -> market_research_report`
- source evidence exists
- report ledger exists
- event trace is visible
- topology contains the Stage204 trajectory node
- stop reason is known
- failed searches do not overclaim success
- private reasoning and persona text are absent

## Boundaries

Stage205 does not add:

- provider model calls
- memory writes
- WeChat startup
- transport authority widening
- an unbounded loop
- hidden chain-of-thought exposure

It is a live-smoke and observability layer over the existing Stage204/Stage195 path.
