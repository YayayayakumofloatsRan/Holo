# Stage176 Market Research Domain Benchmark

Stage176 expands Stage175 from a two-fixture live smoke into an adversarial market-research benchmark. The purpose is to make Holo fail correctly on bad financial evidence before future domain modules try to provide analyst-grade output.

## Schema

```text
holo.stage176.market_research_domain_benchmark.v1
holo.stage176.market_research_domain_result.v1
holo.stage176.market_research_domain_scorecard.v1
```

## CLI

```powershell
python -m holo_host run-market-research-domain-bench --output artifacts\stage176\stage176_market_research_domain_benchmark.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Fixture Categories

```text
primary_filing_ready
third_party_source_pollution
missing_filing_section
metric_conflict
period_mismatch
web_only_no_filing_text
```

The benchmark is intentionally mixed: the primary SEC-like 2024 filing should pass, while adversarial fixtures must fail with named risk flags.

## Domain Scorecard

The scorecard checks:

```text
primary_source_required
filing_text_present
filing_coverage_complete
metric_consistency
period_alignment
unsupported_claim_rate_low
agent_trace_valid
```

`period_alignment` is a Stage176 domain gate. It catches the case where a lower-level report generator may produce an `evidence_ready` report from a primary filing, but the period is wrong for the user's query.

## Summary Metrics

```text
primary_ready_pass_rate
adversarial_detection_rate
naive_baseline_overclaim_rate
average_domain_score
pass_rate
```

The naive baseline is deliberately simple: if web evidence exists, it would answer. This measures how often a web-only approach would overclaim against polluted or incomplete evidence.

## Boundaries

Stage176 is deterministic and offline by default:

```text
no provider model calls
no memory writes
no WeChat start
no transport authority widening
no live network requirement for tests
no hidden reasoning exposure
```

Stage176 is a benchmark and scorecard layer; it does not add live domain behavior.
