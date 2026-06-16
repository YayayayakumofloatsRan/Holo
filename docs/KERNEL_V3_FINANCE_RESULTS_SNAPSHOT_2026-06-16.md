# Kernel v3 Finance Results Snapshot - 2026-06-16

Purpose: record the finance problem-solving evidence that is already supported
by local benchmark artifacts, and separate it from claims that still need fresh
live reruns.

## Bottom Line

Finance problem-solving remains the core objective. The strongest local evidence
is still the 2026-06-14 live FinAgent/FAB-family run record, not today's code
changes alone.

Current fresh live rerun status on 2026-06-16: blocked by missing model
credentials. The latest smoke summary
`.state/kernel_v3/bench/finance/run_live_smoke_current_o000_l001_20260616.summary.json`
records `processor_error_counts={"missing_api_key_env": 1}`, `tokens=0`,
`retrieval_runs=0`, and `0/1` pass. This is an environment/configuration block,
not a capability score.

## Evidence-Backed Results

| Run | Dataset / Slice | Result | Notes |
| --- | --- | ---: | --- |
| `run_finagent_full40_after_nonitemized_headline_live_20260614` | FinAgent full40 live | `38/40` (`95.0%`) | Avg tokens `242,333.75`, avg retrieval runs `2.75`, citations present `100%`. |
| `run_finagent_full40_after_nonitemized_headline_live_20260614.rescored` | Same full40, rescored | `39/40` (`97.5%`) | Same live outputs, updated scoring. |
| `run_full40_previous_failures_after_nonitemized_headline_live` | Historical full40 failures regression | `12/12` (`100%`) | Shows previously failing items were closed in that live regression. |
| `run_fabv2_dev10_capability_parallel10_judgefix` | Curated FAB v2 dev10 | dev annotation overall `0.8752`, numeric `1.0000` | Not a strict pass/fail benchmark score; all 10 still carry dealbreaker annotations. Avg tokens `511,061.2`. |
| `run_stable4_latest_after_pfe_acquisition_fixes` | Four representative workflow tasks | dev annotation overall `0.9603`, numeric `1.0000` | HD/LOW DIO, KHC adjusted EBITDA bridge, PFE/SGEN transaction multiple, WSC add-back trend style coverage. |
| `run_public27_workflow_v1` | FAB public-style 27 workflow slice | no public gold score | Structural telemetry only: avg tokens `87,928.37`, avg retrieval runs `2.2593`; cannot claim accuracy. |
| `run_fb_debug_o000_l001_htmlcol_fact_20260615_v1` | FinanceBench debug row 0 | `1/1` | 3M FY2022 capital-intensity style row solved with annotation overall `1.0000`. |
| `run_fb_debug_o000_l001_wide_slotbind_20260615_v1` | FinanceBench debug row 0 rerun | `1/1` | Same row, annotation overall `1.0000`; useful smoke, not broad FinanceBench proof. |
| `run_fb_eval_o010_l003_htmlcol_fact_20260615_v1` | FinanceBench offset 10 limit 3 probe | `0/3` | Exposes Adobe-source acquisition/binding failures; annotation overall `0.2929`, numeric `0.0000`. |

## What Is Not Proven Yet

- The post-2026-06-16 code changes do not yet have a fresh live accuracy number.
  The current shell has no model API key, so a live smoke produced
  `missing_api_key_env`.
- FinanceBench public 150 has not produced a valid held-out `test100` score.
  The project policy is still: use rows `0-49` as `debug50`; freeze the system;
  then run rows `50-149` as `test100` / `holdout100`.
- FinanceBench `debug50` snippets are useful for capability debugging, but they
  must not be reported as the held-out FinanceBench score.
- FAB public-style 27 has no public gold in the local artifact, so report
  workflow telemetry only unless a separate scoring reference is added.

## Next Real Benchmark Step

When a model key is available again, run this as the next honest measurement:

```bash
HOLO_V3_LIVE_MODEL=1 HOLO_V3_LIVE_FINANCE=1 \
.venv/bin/python -m kernel_v3.cli bench finance \
  --dataset data/bench/finance/financebench_doc_retrieval.jsonl \
  --split debug50 \
  --output .state/kernel_v3/bench/finance/run_fb_debug50_live_20260616.jsonl \
  --summary-output .state/kernel_v3/bench/finance/run_fb_debug50_live_20260616.summary.json \
  --execution-profile finance-fact-fast \
  --mission off \
  --parallel 1 \
  --research-profile finance_fundamentals \
  --thread-prefix fb-debug50-live-20260616
```

Only after reviewing `debug50` as the tuning slice and freezing the configuration:

```bash
HOLO_V3_LIVE_MODEL=1 HOLO_V3_LIVE_FINANCE=1 \
.venv/bin/python -m kernel_v3.cli bench finance \
  --dataset data/bench/finance/financebench_doc_retrieval.jsonl \
  --split test100 \
  --output .state/kernel_v3/bench/finance/run_fb_test100_live_20260616.jsonl \
  --summary-output .state/kernel_v3/bench/finance/run_fb_test100_live_20260616.summary.json \
  --execution-profile finance-fact-fast \
  --mission off \
  --parallel 1 \
  --research-profile finance_fundamentals \
  --thread-prefix fb-test100-live-20260616
```

That `test100` run is the number to put on the project scoreboard.
