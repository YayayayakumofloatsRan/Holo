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

## Remaining Quality Gap

Discovery expansion now reaches real scholarly metadata, but extraction over
raw XML/JSON is still noisy. The next retrieval-quality pass should add
source-specific scholarly metadata extraction:

- arXiv Atom -> paper entries with title, authors, abstract, id, pdf URL
- OpenAlex JSON -> work title, abstract/inverted index, DOI, OA PDF URL,
  publication date, concepts, cited-by count
- Crossref JSON -> title, DOI, publisher, date, container title, URL
- Semantic Scholar JSON -> title, abstract, year, venue, external IDs, OA PDF
- publisher result pages -> article links/DOI extraction before evidence gate

That should reduce cases where JSON/XML boilerplate or unrelated API records
become evidence spans.

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

- Targeted tests: `55 passed`
- Kernel v3 tests: `715 passed`

Full `tests/` still includes older stage/Windows/socket/environment tests that
are outside the active kernel-v3 regression target in this WSL sandbox.
