# Stage213 Market Research Action Journal Smoke

Stage213 adds a deterministic market-research smoke that binds the live crawler, source promotion, report grounding, and Stage212 action journal into one reproducible artifact bundle.

## Purpose

The agent must be able to run a bounded research trajectory, reject weak early evidence, promote primary sources, and leave an inspectable action trail. This stage verifies that behavior on a financial-research fixture without requiring live provider calls or network access.

## Schema

```text
holo.stage213.market_research_action_journal_smoke.v1
holo.stage213.market_research_action_journal_result.v1
holo.stage213.market_research_action_journal_scorecard.v1
```

## Smoke Scenario

The dry-run fixture asks for an NVIDIA AI infrastructure capex research path. The mocked search surface returns:

- first: a weak third-party commentary source
- second: an official SEC Form 10-K filing

The crawler must continue after the weak source, open the SEC filing, promote only sufficient authority evidence, and assemble a minimal grounded report.

## CLI

```powershell
python -m holo_host run-market-research-action-journal-smoke --output artifacts\stage213\stage213_market_research_action_journal.html --dry-run
```

The command writes:

```text
.html
.json
.jsonl
```

## Scorecard

The scorecard checks:

- crawler reached `sufficient`
- more than one query was needed
- SEC authority source was promoted
- weak source was not promoted
- Stage212 journal rendered crawl and feedback rows
- report remained grounded with zero unsupported claims
- public artifacts contain no private reasoning/provider internals

## Boundary

Stage213 is a smoke/evaluation layer. It does not call providers, does not require real network by default, does not execute arbitrary tools, does not write memory, does not start WeChat, and does not expose hidden chain-of-thought. It shows public action and feedback traces only.
