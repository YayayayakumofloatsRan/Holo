# Kernel v3 FB/FAB Live Experiment Split Policy - 2026-06-15

This document records the split policy for the next finance-capability experiments.
It is intentionally strict because Kernel v3 is being tuned under benchmark pressure.

## Hard invariants

- The model decides the problem-solving plan. The host may validate schemas, execute tools, journal evidence, and verify provenance/numeric support.
- No benchmark gold answer, scorer annotation, reference calculation, or expected numeric value is allowed in the runtime prompt, memory, retrieval context, or tool context.
- Gold and annotation sidecars are scoring-only artifacts and may be used only after a run has produced an answer.
- Debug items and evaluation items must be reported separately.
- FinanceBench/FB and Finance Agent Benchmark/FAB are separate tracks. Their scores must not be merged.

## Local benchmark inventory

| Track | Path | Count | Gold/annotation status | Use |
| --- | --- | ---: | --- | --- |
| FB / FinanceBench doc retrieval | `data/bench/finance/financebench_doc_retrieval.jsonl` | 150 | `data/bench/finance/financebench_doc_retrieval.gold.jsonl` | Primary large finance benchmark |
| FAB v2 public | `data/bench/finance/fabv2_public.jsonl` | 27 | no public gold | Public FAB capability trace / manual review |
| FAB dev10 | `data/bench/finance/fabv2_dev10.jsonl` | 10 | `data/bench/finance/fabv2_dev10.gold.jsonl` | Small scored FAB development set |
| Holo workflow challenge | `data/bench/finance/holo_finance_workflow_challenge.jsonl` | 50 | no gold | Stress/demo challenge set |

Checked-in primary prompt total: 237 items. Scored local items: 160 items
(150 FB + 10 FAB dev).

## FB split

FB uses `data/bench/finance/financebench_doc_retrieval.jsonl`.

- **FB debug/system-tuning split:** offsets `0-49`, named
  `financebench_debug50` / `debug50`.
  These 50 rows are the only FinanceBench public rows allowed for system tuning:
  prompt-contract cleanup, retrieval/workbench improvements, slot binding,
  synthesis repair, verifier behavior, cache behavior, loop efficiency, and
  failure taxonomy. They are not held-out evaluation.
- **FB evaluation/test split:** offsets `50-149`, named
  `financebench_test100` / `test100` / `holdout100`.
  These 100 rows are held out for accuracy measurement after the current system
  configuration is frozen. Do not inspect item-level failures from this split and
  feed those fixes back into the same reported score; any post-test tuning must
  start a new versioned evaluation cycle.
- **Reporting rule:** report FB debug and FB eval in separate tables. Never present
  debug accuracy as held-out accuracy.
- **CLI rule:** prefer `holo-v3 bench finance --split debug50` and
  `holo-v3 bench finance --split test100`; do not combine named splits with
  manual `--offset` or `--limit`.

## FAB split

FAB is reported separately from FB.

- `fabv2_dev10` is the small scored development set.
- `fabv2_public` is the 27-question public set without public gold in this repo.
- The `.state` imports from `vals-ai/finance_agent_benchmark` are state artifacts,
  not replacements for the checked-in FAB v2 public set. If used, label them as
  state-import FAB runs and do not mix them with the checked-in FAB v2 public count.

## Next experiment gate

Before any held-out FB eval run:

1. Iterate only on `--split debug50` until the system behavior is stable.
2. Confirm semantic intake no longer records shell execution as a user-requested subtask.
3. Confirm answers are final answers or honest supported limitations, not accidental failure-report passes.
4. Confirm numeric verifier failures provide model-actionable correction reasons.
5. Freeze the run configuration before measuring `--split test100`.
6. Report the 100-row test accuracy separately from debug50 and from any previous
   live10/full40/FinAgent-style run.
