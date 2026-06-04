# Kernel v3 Progress: Open Research Loop and Thread Attention

Date: 2026-06-04

## Problem Observed

Live academic retrieval could find useful scholarly evidence, but the agent loop
kept pursuing every planned retrieval subgoal as a hard requirement. For
open-ended research tasks this caused repeated searches for soft gaps such as
language-specific coverage or auxiliary angles, even after the root objective
was answerable with citations.

Another live issue was answer shape drift: a user could ask for a detailed
report, while the host-inferred answer profile still fell back to a short
normal answer contract if semantic intake omitted `answer_profile_hint`.

## Changes

- Added host-side adaptive retrieval coverage for open research tasks.
  - It can treat incomplete planned subgoals as soft limitations only when
    enough citable evidence exists and at least one planned subgoal completed.
  - It avoids soft completion for finance, policy, and hard factual metrics
    such as revenue, employee count, market cap, and valuation.
  - It no longer depends only on a retrieval profile id. It reads signals from
    the recipe, semantic intake, answer profile, research mission, task plan,
    and root goal.
- Added explicit answer-shape preservation in `infer_answer_profile`.
  - This is limited to output shape: brief answer, detailed report, deep report,
    or memo.
  - It does not decide content, sources, tool actions, or final claims.
- Added thread attention blocks to the journal-derived thread working context.
  - Recent failures, current evidence/citations, latest task state, and final
    answers are compacted into prioritized blocks for future loop context.
- Strengthened processor prompt contracts so semantic intake and planner keep
  open-research output contracts and reason like a capable researcher when soft
  gaps remain.

## Live Validation

Command used:

```bash
./holo-v3 chat --thread codex-sim-academic-softgap3-0604 --once "请检索双曲动力学的前沿研究，按 摘要/关键文献/研究方向/开放问题/局限 写一份详细中文报告，不要只给几条短要点。" --online --profile fast --thinking disabled --response-language zh --research-depth light --live-retrieval --live-web-search-provider duckduckgo_html --live-fetch-discovered-search-hosts --live-source-directory-allowlist --live-search-strategy aggregate --output human --no-color
```

Observed result:

- `semantic.intake` classified the task as `frontier_research`.
- Planner proposed `retrieval.run` with 8 queries and up to 80 ranked sources.
- Retrieval fetched arXiv scholarly sources and produced citations.
- Workloop evidence sufficiency returned
  `open_research_soft_subgoals_can_be_limited`.
- Termination moved directly to `final_answer` after the first evidence-rich
  retrieval instead of repeating similar searches.
- Synthesizer produced a sectioned Chinese report with summary, background,
  key findings, evidence, analysis, risks/limitations, and next steps.

## Tests

Focused regression run:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase103_model_retrieval_feedback.py tests/test_kernel_v3_phase109_mission_supervisor.py tests/test_kernel_v3_phase109_research_employee_core.py tests/test_kernel_v3_phase110_active_memory_recall.py tests/test_kernel_v3_phase111_academic_research_profile.py tests/test_kernel_v3_phase61_workloop.py tests/test_kernel_v3_phase5_semantic_processors.py
```

Result: 107 passed.

## Remaining Work

- Retrieval quality still needs broader source-family strategies beyond
  academic/arXiv and finance profiles.
- Long-term memory is present but still needs stronger user-facing admin and
  promotion workflows.
- Thread attention blocks are now available, but future phases should connect
  them with memory recall, compaction, and long-session context budgeting.
- Live runs still depend on network/DNS availability; provider failures must
  remain observations for replanning, not hidden hard stops.
