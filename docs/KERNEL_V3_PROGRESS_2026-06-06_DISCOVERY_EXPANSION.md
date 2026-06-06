# Kernel v3 Progress 2026-06-06: Discovery Expansion

## Summary

This pass strengthens deep retrieval without adding fixed-answer simulations or
tool-name branches in `LoopControllerV3`.

The retrieval operator now treats discovery/search surfaces as acquisition
inputs, not dead ends. It can compile arXiv, OpenAlex, Crossref, Semantic
Scholar, Springer, and Cambridge discovery entries into concrete fetchable
document/API candidates before ranking, fetching, extraction, evidence
qualification, and citation generation.

## Changes

- Added `kernel_v3/retrieval/discovery.py`.
- Added retrieval contracts for:
  - `DiscoveryExpansion`
  - `RetrievalNextAction`
  - `ResearchGraph`
- Retrieval reports now include:
  - `next_tool_actions`
  - `operator_critic`
  - `research_graph`
  - discovery expansion counts
- Added `retrieval_operator_critic` journal records after every retrieval
  evaluation decision.
- Added host-bounded fetch allowance for discovery expansion sources through
  `fetch_allowed_hosts`, without opening arbitrary network access.
- Added `holo-v3 retrieval-benchmark <task_id>` for live behavior metrics:
  query count, repetition rate, fetch success, evidence/citation counts, final
  answer length, latest failure mode, next actions, and graph summary.
- Workspace list/search/read now hides Holo internal state surfaces:
  `.state`, `.codex`, `.agents`, `.holo-v3-*`, SQLite indexes, and cache dirs.
- WorkMethod framing now accepts common live-model alias sections
  (`frame`, `method`, `working_set`) with diagnostics, while preserving
  fallback behavior when required sections are absent.

## Live Smoke

Command shape used:

```bash
./holo-v3 --journal /tmp/holo-v3-discovery-live.jsonl \
  --index /tmp/holo-v3-discovery-live.sqlite \
  --artifact-log /tmp/holo-v3-discovery-artifacts.jsonl \
  retrieve "hyperbolic dynamics frontier research open problems" \
  --profile academic_research \
  --live-retrieval \
  --live-allow-all-hosts \
  --live-search-strategy aggregate \
  --max-queries 1 \
  --max-sources 12 \
  --max-fetches 12 \
  --max-spans-per-document 3
```

Observed result:

- Live retrieval reached `status=ok`.
- Report status was `sufficient`.
- Discovery expansion produced arXiv API, OpenAlex, Crossref, Semantic Scholar,
  and publisher result actions.
- Fetches included arXiv abs, arXiv API, OpenAlex API, and Crossref API.
- Report included `next_tool_actions`, `operator_critic`, and `research_graph`.

## Biomimetic Live Validation Follow-up

A later live validation pass exercised Holo as a working agent rather than a
fixed-answer test fixture:

- System-time question: the first live run exposed a real model-intent alias
  mismatch. DeepSeek returned `system_time_query`; without normalization Holo
  routed to `semantic_answer`, did not call `system.time`, and the model
  claimed a tool source it had not used. `system_time_query` and
  `current_time_query` now normalize to `system_time`, and the live retest
  returned the host `system.time` observation with `mode=system_answer`.
- Resident reminder/priority: a high-priority reminder message was claimed
  before a lower-priority background message, created an active schedule, and
  wrote a ready outbox acknowledgement.
- Safe workspace professional task: using a synthetic non-private workspace
  document, Holo routed to `workspace_answer`, read the file, produced
  workspace evidence/citation, and summarized component responsibilities plus a
  concrete operator-visibility weak point.
- Technical public research task: a live DeepSeek API documentation task ran
  four retrieval loops, produced 18 search attempts, 15 successful fetches, 12
  evidence/citation items, and a structured cited answer. The benchmark showed
  useful completion, but also a high repeated-fetch-source rate, which remains
  a retrieval-quality metric to improve.
- Academic frontier task: a live Anosov-flow task reached a cited report from
  scholarly sources without falling back to dictionary/encyclopedia pages. The
  run used 8 distinct queries, 24 fetch attempts, 20 successful fetches, 14
  evidence/citation items, and zero query/fetch-source repetition in the
  benchmark.

The pass also tightened retrieval termination semantics: when
`EvidenceEvaluationDecision.sufficient` is true, `RetrievalOperator` no longer
publishes `next_tool_actions` from discovery expansion or fetch warnings. Those
actions remain available only for insufficient reports, where they are needed
for strategy shifts such as arXiv API expansion, OpenAlex/Crossref/Semantic
Scholar queries, alternate source families, or diversified acquisition plans.
This keeps successful research runs from feeding redundant "continue
acquisition" signals back into the agent loop while preserving failure-driven
replanning.

## Scholarly Metadata Extraction Pass

The follow-up pass closes the raw XML/JSON extraction gap for scholarly
discovery sources without adding fixed-answer fixtures or domain-specific
question tables.

Changes:

- `readable_document_text()` now detects scholarly metadata sources by safe
  source metadata, known scholarly API hosts, and scholarly JSON/XML structure.
- arXiv Atom feeds are converted into paper-level records with title, authors,
  abstract, id, year, venue, category, and DOI fields when present.
- OpenAlex works JSON is converted into work-level records with title,
  reconstructed abstract from `abstract_inverted_index`, authors, DOI, venue,
  publication date, concepts, and cited-by count.
- Crossref works JSON is converted into bibliographic records with title, DOI,
  publisher/container, date, URL, authors, subjects, and markup-stripped
  abstract.
- Semantic Scholar paper-search JSON is converted into paper records with
  title, abstract, year, venue, authors, external IDs, citation count, and open
  access PDF URL.
- Scholarly metadata extraction uses structured-line ranking and topic-anchor
  gating. Generic words such as `research`, `review`, `paper`, `frontier`, and
  `open problem` are not enough to create evidence unless the line also matches
  the user goal's core topic terms.
- Header-only structured metadata, including empty arXiv feeds, no longer
  creates evidence spans.
- `RetrievalOperator` now carries safe `source_metadata` into
  `FetchedDocument.metadata` so extraction can distinguish discovery-expanded
  scholarly APIs while raw fetched bodies still stay in `ArtifactStore`.

Observed live smoke after this pass:

- Query: `hyperbolic dynamics frontier research open problems`
- Profile: `academic_research`
- Mode: live aggregate retrieval with source-directory crawl and discovered
  search-host fetches enabled.
- Result: `status=sufficient`
- Fetches: 12
- Candidate spans: 29
- Evidence/citations: 2 / 2
- Selected evidence came from arXiv paper content for the target topic; the
  previous OpenAlex generic `research/review` neighbor-noise was not selected
  as evidence.

Remaining retrieval-quality work:

- Deduplicate repeated citations to the same paper/span more aggressively.
- Compile publisher search/result pages into article-level URLs and DOI
  candidates instead of treating result pages as evidence surfaces.
- Feed retrieval `next_tool_actions` into the mission/planner loop more
  forcefully so a failed source family triggers a concrete acquisition switch,
  not just a new keyword attempt.
- Add behavior benchmarks that track source-family diversity, effective
  document count, topic-anchor hit rate, final answer coverage, and citation
  uniqueness across live tasks.

## Validation

```bash
.venv/bin/pytest -q \
  tests/test_kernel_v3_phase111_academic_research_profile.py \
  tests/test_kernel_v3_phase115_deep_retrieval_system.py \
  tests/test_kernel_v3_phase90_http_fetch_provider.py \
  tests/test_kernel_v3_phase117_workmethod_layer.py

.venv/bin/pytest -q tests/test_kernel_v3_*.py
```

Result:

- Targeted tests before scholarly extraction: `55 passed`
- Scholarly extraction targeted tests: `8 passed`
- Kernel v3 tests after scholarly extraction: `721 passed`

Full `tests/` still includes older stage/Windows/socket/environment tests that
are outside the active kernel-v3 regression target in this WSL sandbox.
