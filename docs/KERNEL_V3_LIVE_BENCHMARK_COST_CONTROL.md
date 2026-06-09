# Kernel v3 Live Benchmark Cost Control

Kernel v3 live benchmarks are real online agent runs. They call the model stack,
search providers, HTTP fetch providers, SEC/companyfacts endpoints, and source
directory expansion. A full run can become expensive if retrieval is allowed to
expand without byte budgets.

## What Went Wrong

The 2026-06-09 full finance run used:

- `--parallel 5`
- `--live-allow-all-hosts`
- `--live-fetch-discovered-search-hosts`
- `--live-max-network-fetches 100000`
- deep finance retrieval with source-directory and document-link expansion

The run reached thousands of fetch attempts before completion. The issue was not
mainly model output cost; the main network cost came from broad live retrieval:
search result fetching, SEC/companyfacts downloads, discovery-page expansion,
large HTML/PDF bodies, and duplicated downloads across benchmark workers.

## Current Guardrails

The live retrieval stack now has host-owned cost controls:

- Default live network fetch budget: `512`
- Default per retrieval action fetch budget: `128`
- Default per response body cap: `4_000_000` bytes
- Default process/cache-scope download budget: `512_000_000` bytes
- Default shared HTTP cache: `.state/kernel_v3/retrieval/http-cache`
- Benchmark progress output includes fetch count, downloaded MB, cache hits, and
  download-budget blocks.

Cache hits do not count against the live download byte budget. The cache stores
public retrieval response bodies keyed by URL hash; it does not store API keys or
raw secrets.

## Safe Benchmark Practice

For normal iteration, run targeted slices first:

```bash
HOLO_V3_LIVE_MODEL=1 ./holo-v3 bench finance \
  --dataset .state/kernel_v3/bench/finance/finagent_test_0_40.jsonl \
  --offset 19 --limit 2 --parallel 2 \
  --output .state/kernel_v3/bench/finance/latest_slice.jsonl \
  --summary-output .state/kernel_v3/bench/finance/latest_slice.summary.json \
  --online --planner model --evaluator model --synthesizer model \
  --semantic-intake model --turn-router model \
  --research-profile finance_fundamentals --research-depth deep \
  --live-retrieval --live-search-strategy adaptive \
  --generation-mode auto --latency-target quality \
  --context-profile provider --response-language zh
```

Only raise these knobs deliberately:

- `--parallel`
- `--live-max-network-fetches`
- `--live-download-byte-budget`
- `--live-max-bytes`
- `--live-allow-all-hosts`
- `--live-fetch-discovered-search-hosts`

Full benchmark runs should be treated as release-grade evaluations, not default
development loops.

## Remaining Bottlenecks

The latest partial live run finished 30/40 items before interruption:

- 26 passed
- 4 failed

The failures were concentrated in:

- financial metric concept selection, such as total revenue vs sales and other
  operating revenues;
- fiscal/line-item disambiguation;
- sentinel or unavailable-answer boundary handling.

This means the next quality work should focus on finance metric semantics and
document acquisition, not on unbounded crawling.
