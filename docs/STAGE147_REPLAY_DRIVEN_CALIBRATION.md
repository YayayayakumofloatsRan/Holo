# Stage147 Replay-Driven Calibration

Date: 2026-05-24

## Purpose

Stage146 made Holo's cognition inspectable as multi-turn replay rows. Stage147 turns those rows into a deterministic shadow calibration report for two earlier surfaces:

- Stage144 packet-policy recommendations
- Stage145 reaction-kernel delta candidates

The goal is to ask whether a recommendation or delta was supported by the replay outcome, without applying any policy or mutating the system.

## Boundary

Stage147 is analysis only.

It does not:

- call providers
- execute tools
- write memory
- mutate policy
- apply reaction-kernel deltas
- start WeChat
- change watcher or transport authority
- create a second loop

All promotion candidates are `shadow_only=true`, and the full report has `do_not_apply_live=true`.

## Schema

`holo.stage147.replay_calibration.v1`

Top-level fields:

- `schema`
- `row_count`
- `policy_recommendation_accuracy`
- `kernel_delta_support_rate`
- `calibration_findings`
- `promotion_candidates`
- `do_not_apply_live=true`

## CLI

```powershell
python -m holo_host evaluate-replay-calibration --replay-json artifacts\stage146\stage146_replay.json --output artifacts\stage147\stage147_calibration.html --dry-run
```

If `--dry-run` is set, or if `--replay-json` is missing/unavailable, the command uses deterministic Stage146 synthetic rows.

The command writes:

- `.html`
- `.json`
- `.jsonl`

## Calibration Rules

Packet-policy support:

- `skip` is supported when Stage142 suppressed a duplicate or context waste was high.
- `memory_first` is supported when memory alignment was unsupported or contradicted.
- `tool_first` is supported when tool grounding reported `ungrounded_tool_claim`.

Reaction-kernel support:

- `novelty_threshold` or `continuation_threshold` is supported when Stage142 suppressed a duplicate.
- `memory_trust` or `correction_sensitivity` is supported when memory alignment failed.
- `tool_preference` or `risk_aversion` is supported when a tool claim was ungrounded.
- Clean grounded turns that still produce deltas are counted as counterexamples.

## Output

The HTML report shows:

- summary metrics
- supported findings
- counterexamples
- promotion candidates
- an explicit shadow-only warning

The JSON and JSONL artifacts preserve the same evidence in machine-readable form for later replay-driven evaluation.

## Research Role

Stage147 is the first step from observability to controlled calibration. It turns a replay trajectory into evidence about whether packet-policy and reaction-kernel adjustments would have been justified. It deliberately stops before applying changes, so later stages can add stronger promotion gates and human review without losing the single-brain authority model.
