# Stage214 Market Research Operator Run

Stage214 connects the crawler/action-journal smoke to an end-to-end market-research operator run.

## Purpose

Holo needs to behave like a research operator, not a search-result paraphraser. A market-research task should become a bounded action trajectory:

```text
plan -> crawl -> promote_source -> build_pack -> build_report -> assemble_report -> finalize -> action_journal
```

Each phase must leave public, inspectable metadata. The final answer must be backed by promoted source evidence and a report assembly gate.

## Schemas

```text
holo.stage214.market_research_operator_run.v1
holo.stage214.market_research_operator_run_bundle.v1
holo.stage214.market_research_operator_phase.v1
holo.stage214.market_research_operator_scorecard.v1
```

## Runtime Surface

```powershell
python -m holo_host run-market-research-operator-run --output artifacts\stage214\stage214_market_research_operator_run.html --dry-run
```

The command writes:

```text
.html
.json
.jsonl
```

## Pipeline

The dry-run fixture:

1. Plans the task as a filing-grounded NVIDIA AI infrastructure research note.
2. Runs Stage186 crawler search.
3. Forces a weak first third-party source.
4. Continues to an official SEC filing.
5. Promotes the SEC filing through Stage196 source promotion.
6. Builds a Stage169 market research pack from filing sections and metrics.
7. Builds a Stage173 analyst-style report.
8. Assembles/finalizes through Stage197/198 gates.
9. Renders the Stage212 action journal with crawl and feedback rows.

## Scorecard

Stage214 checks:

- the complete operator phase sequence exists
- crawler used multiple steps and reached sufficient evidence
- SEC authority source was promoted
- market research pack is ready
- report is assembled/finalized with zero unsupported claims
- action journal is visible
- public artifacts contain no hidden reasoning/provider internals

## Boundary

Stage214 is deterministic by default. It does not require provider calls, live network, memory writes, WeChat startup, transport widening, or hidden reasoning exposure. The dry-run fixture uses mocked search/open-page functions, while the pipeline shape is the same one a live run should use.
