# Stage226 Web Research Kernel v2

Kernel version remains `2.1.0`. Stage226 is a research log for the new web
research foundation.

## Problem

The kernel should not depend on a black-box `web_research()` host function.
Research quality depends on a bounded crawler operator with explicit source
policy, source graph, evidence items, citations, and stop conditions.

## Added Runtime Contract

`holo_agent.web_research_kernel` adds:

- `SearchGoal`
- `SearchPlan`
- `QueryAttempt`
- `EvidenceItem`
- `Citation`
- `CrawlReport`
- `CitationBuilder`
- `build_search_goal()`
- `build_search_plan()`
- `build_crawl_report()`

The agent context now includes:

- `search_goal`
- `crawl_report`

The final metadata also includes both fields.

## Design Rule

Semantic research decisions still belong to the model. Deterministic code is
used for structure, source policy defaults, ledgers, and citation assembly.
This avoids treating keyword routing as the agent brain while still making web
research inspectable.

## Source Buckets

`CrawlReport.source_graph` separates:

- `candidate_sources`
- `opened_sources`
- `consulted_sources`
- `supporting_sources`
- `cited_sources`
- `rejected_sources`

This is the base for later source-graph visualization and research benchmark
metrics.

## Task Policies

Stage226 starts with policies for:

- official documentation
- API documentation
- financial filing / company IR research
- quick lookup fallback

Examples:

- OpenAI Codex CLI docs require official documentation and prefer
  `developers.openai.com`.
- DeepSeek tool-calling docs prefer `api-docs.deepseek.com`.
- Apple 10-K / net-sales tasks require regulatory filing or company official
  evidence and prefer `sec.gov` / `investor.apple.com`.

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage226_web_research_kernel.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage226-green1
```

Result:

```text
6 passed
```

Full suite is expected to pass after updating the stage-record assertion from
Stage225 to Stage226.
