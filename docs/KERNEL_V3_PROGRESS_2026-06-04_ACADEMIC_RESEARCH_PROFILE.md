# Kernel v3 Progress: Academic Research Profile and Source Quality

Date: 2026-06-04

## Why This Change Exists

Live interaction showed that generic retrieval was too easy to derail by weak
web sources. A scholarly query such as frontier research in hyperbolic dynamics
could be treated like ordinary web search and land on dictionary definitions.
That is a harness problem: the model needs a richer state space and the host
needs profile-specific source quality gates.

This change does not add fixed answers or sample-specific routing. It adds a
general academic research capability/profile so model packets can express
scholarly research intent and the host can validate the appropriate source
families.

## Implemented

- Added `academic_research` as a first-class `ResearchProfile`.
- Added scholarly source families:
  - `scholarly_preprint`
  - `scholarly_publisher`
  - `academic_repository`
  - `scholarly_index`
  - weak families `reference_dictionary` and `encyclopedia`
- Added academic source directory entries for arXiv, Semantic Scholar,
  OpenAlex, Crossref, DBLP, mathematics indexes, and publisher search surfaces.
- Added semantic capabilities:
  - `academic.research`
  - `academic.frontier_research`
  - `academic.literature_review`
  - `academic.paper_search`
  - `academic.scholarly_sources`
- Updated task graph normalization so academic semantic labels imply academic
  capabilities when the model omits the capability id.
- Updated runtime profile inference and retrieval payload defaults so academic
  tasks carry:
  - `research_profile=academic_research`
  - `source_authority_requirement=secondary_or_better`
  - scholarly preferred source families
  - aggregate/fresh-live strategy hints
- Updated planner and semantic prompts to steer scholarly/frontier tasks toward
  papers, preprints, publishers, DOI metadata, and academic indexes instead of
  dictionary or encyclopedia pages.
- Added fetch-before source rejection for dictionary/encyclopedia sources under
  `academic_research`.
- Added a live `ArxivApiSearchProvider` that expands academic queries into
  concrete `https://arxiv.org/abs/...` paper candidates instead of only search
  surfaces.
- Marked academic source-directory/search/index pages as discovery-only and
  reject them before fetch/citation, so search interfaces cannot become final
  evidence.
- Added query-topic coverage for research profiles. Evidence must match the
  user's core topic terms, not only generic terms such as `research`, `survey`,
  `frontier`, or `paper`.
- Reduced the default academic retrieval budget from eager deep fan-out to a
  bounded balanced profile:
  - default/balanced: `max_queries=8`, `max_sources=80`, `max_fetches=24`
  - deep: `max_queries=24`, `max_sources=240`, `max_fetches=72`
- Updated answer profile inference so academic frontier/literature tasks default
  to a detailed report contract with academic coverage requirements.

## Verification

Targeted profile/runtime tests:

```bash
.venv/bin/python -m pytest -q \
  tests/test_kernel_v3_phase111_academic_research_profile.py \
  tests/test_kernel_v3_phase102_aggregate_search_provider.py \
  tests/test_kernel_v3_phase103_model_retrieval_feedback.py \
  tests/test_kernel_v3_phase82_research_source_policy.py \
  tests/test_kernel_v3_phase87_research_profile_runtime.py
```

Result:

```text
45 passed
```

Live retrieval smoke:

```bash
./holo-v3 retrieve "hyperbolic dynamics frontier research" \
  --profile academic_research \
  --live-retrieval \
  --live-web-search-provider duckduckgo_html \
  --live-fetch-discovered-search-hosts \
  --live-source-directory-allowlist \
  --live-search-strategy aggregate \
  --max-sources 40 \
  --max-fetches 8 \
  --max-spans-per-document 4
```

Observed result:

```text
status=ok
report.status=sufficient
query_topic_coverage.matched_topic_terms=[hyperbolic, dynamics]
source_authority.weak_source_count=0
source_rejection_reasons.source_discovery_only_for_research_profile=14
rejected_evidence_reasons.query_topic_terms_missing=10
```

Kernel v3 focused regression:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3*.py
```

Result:

```text
658 passed
```

Live agent smoke:

```bash
./holo-v3 chat --thread codex-live-academic-small2 --once \
  "请检索双曲动力学的前沿研究，简要给出3点有证据的发现" \
  --online \
  --profile fast \
  --thinking disabled \
  --response-language zh \
  --research-profile academic_research \
  --research-depth light \
  --live-retrieval \
  --live-web-search-provider duckduckgo_html \
  --live-fetch-discovered-search-hosts \
  --live-source-directory-allowlist \
  --live-search-strategy aggregate \
  --output human \
  --no-color
```

Observed result:

```text
completed task=task-9 run=run-1 route=new_task
final answer cites scholarly evidence for recent hyperbolic-dynamics papers
retrieval used bounded academic budgets: max_queries=4, max_sources=30, max_fetches=12
```

Full repository test run was not a clean signal for kernel v3 because legacy
stage and transport tests failed on current environment constraints: socket
creation is denied, `/mnt/c` is read-only, `python` is absent from PATH, a
legacy stage artifact is missing, and the user-updated root `AGENTS.md` no
longer matches old stage assertions. These failures are outside the kernel v3
focused test set and were not introduced by this change.

## Remaining Work

- Improve broad retrieval strategy beyond profiles: query diversification,
  source-family rotation, citation-aware replan, and compact mission state.
- Add progressive widening so deep retrieval starts with a small high-quality
  batch and expands only when mission assessment finds a real gap. The current
  live agent path can still over-fetch when the planner repeatedly expands
  subgoals instead of accepting sufficient cross-language evidence.
- Improve cross-language coverage assessment. A Chinese answer can be supported
  by English scholarly evidence; the planner should not treat a Chinese search
  subgoal as mandatory when source evidence already covers the original research
  objective.
- Add thread/RAG memory integration so each loop carries the best prior
  observations and rejected-source diagnostics without inflating context.
