# Kernel v3 Progress 2026-06-03: Retrieval Discovery, Evidence, and Live Loop

## What Changed

- Retrieval now distinguishes discovery artifacts from final evidence.
  Discovery sources can move the loop to the next step, but they do not make a
  factual answer safe by themselves.
- SEC ticker-directory, submissions, EDGAR search/browse, and filing-directory
  sources are treated as discovery for finance fundamentals unless the user
  explicitly asks for metadata. They can generate host-owned continuation hints
  for companyfacts or filing-document fetches.
- SEC companyfacts JSON is parsed into compact financial metric rows before
  span ranking. Rows include concept, unit, value, fiscal year/period, form,
  filing date, and accession number. The raw body remains in ArtifactStore.
- The default live fetched-body cap is now `16 MB`, which is large enough for
  common official structured payloads such as SEC companyfacts.
- SEC filing continuation hints are filtered to financial report forms
  (`10-K`, `10-Q`, `20-F`, `40-F`) before being shown to the model planner.
- Finance evidence qualification now rejects weak product pages, generic search
  pages, and SEC discovery metadata as final fundamentals evidence.
- Replan hints now carry candidate/rejected evidence diagnostics, rejected
  reasons, fetch summaries, and missing query facets so the model planner can
  change strategy after a failed retrieval instead of repeating the same action.
- Research-profile policy is now generic. A profile can define source families,
  query templates, discovery source kinds, evidence facets, numeric-fact
  requirements, extraction aliases, and evidence-compaction limits. Finance
  fundamentals is no longer the only concrete profile; technical documentation
  is available as a second profile using the same retrieval loop.
- Evidence compaction now happens before citations are journaled. Retrieval can
  gather many candidate spans, then select a deduped, authority-aware,
  facet-aware evidence package for synthesis.

## Architecture Boundary

The generic loop is unchanged:

```text
planner.propose -> PolicyGate -> ToolRegistry/RetrievalOperator
-> observation -> evaluator.assess -> Workloop/TerminationPolicy
-> continue/final_answer/ask_user/failure_report
```

Profiles live under `retrieval.run`, not as special branches in
`LoopControllerV3`. A profile contributes source directories, structured
providers when needed, authority policy, discovery policy, evidence
qualification, extraction aliases, and evidence compaction. Other deep-research
domains should use the same pattern: add profile-specific source/evidence
policies below the retrieval operator while preserving the generic workloop
feedback path.

## Live Validation

Default deterministic validation:

```bash
.venv/bin/pytest -q tests/test_kernel_v3_*.py
.venv/bin/pytest -q tests/test_kernel_v3_phase108_generic_research_profile_policy.py
```

Latest full run result:

```text
608 passed
```

Live smoke with real DeepSeek calls and real SEC/network retrieval completed an
Apple fundamentals request. The loop first performed SEC discovery, then used
host-derived CIK/companyfacts continuation, fetched a large companyfacts JSON
payload, extracted SEC metric rows, produced citations from
`sec_companyfacts_json`, and finalized with a synthesized answer.

## Remaining Work

- Add metric-aware ranking for finance facts inside the compacted evidence
  package: latest fiscal year, latest
  quarter, requested metric names, and official form priority should be selected
  before final answer synthesis.
- Add more concrete profile instances for domains such as legal, scientific
  literature, product research, and broad market research.
