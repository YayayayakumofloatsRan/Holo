# Stage146 Biomimetic Replay And Benchmark Bundle

Date: 2026-05-24

## Purpose

Stage139 through Stage145 made Holo's per-turn cognition inspectable through tool grounding, memory grounding, memory-claim alignment, semantic novelty gating, packet-budget reporting, context-economy diagnostics, and prediction-error reaction-kernel shadowing.

Stage146 unifies those per-turn ledgers into a multi-turn biomimetic replay and a publication-style benchmark bundle. The target is trajectory inspection: a reader should be able to see how Holo moved from input, through packet decisions, grounding gates, visible A'/A'' expression, context economy, prediction error, and shadow reaction-kernel delta candidates across several turns.

## Boundaries

Stage146 is read-only over stored reply/eval metadata.

It does not:

- call a provider
- start WeChat
- write memory
- execute tools
- mutate policy
- add a loop
- widen watcher or transport authority

If runtime rows are unavailable, Stage146 falls back to deterministic synthetic fixtures so the CLI and tests remain offline and reproducible.

## Schemas

- Replay: `holo.stage146.biomimetic_replay.v1`
- Benchmark bundle: `holo.stage146.benchmark_bundle.v1`

## Replay Rows

Each derived replay row contains:

- `turn_id`
- `time`
- `input_summary`
- `packet_budget`
- `tool_grounding`
- `memory_grounding`
- `memory_alignment`
- `semantic_novelty`
- `context_economy`
- `outcome_appraisal`
- `reaction_kernel_shadow`
- `visible_bubbles`
- `state_delta_summary`

The replay exporter reads outbound message metadata already written by the reply pipeline and pairs it with the preceding inbound message text when available. It can also export deterministic fixture rows with `--dry-run`.

## CLI

```bash
python -m holo_host export-biomimetic-replay --thread-key cli:Stage146Fixture --limit 20 --output artifacts/stage146/stage146_replay.html --dry-run
python -m holo_host run-biomimetic-benchmark --output artifacts/stage146/stage146_benchmark.html --dry-run
```

Each command writes:

- `.html`
- `.json`
- `.jsonl`

Output paths are checked so artifact writes stay inside the selected repository or working root.

## Benchmark Conditions

The deterministic benchmark compares:

- `single-call baseline`
- `simple RAG baseline`
- `fixed two-bubble baseline`
- `multi-packet without Stage142/143/144/145`
- `full current RK-CSM stack`

## Metrics

- `semantic_novelty`
- `duplicate_rate`
- `unsupported_claim_rate`
- `memory_alignment_support_rate`
- `context_waste`
- `packet_cost_estimate`
- `prediction_error`
- `correction_adoption_proxy`

The benchmark is intentionally fixture-first in this stage. It gives a stable publication-style comparison harness before any live-provider or human-evaluation expansion is considered.

## Research Use

Stage146 makes Holo's cognition observable as a trajectory rather than isolated replies. This supports the reaction-kernel conscious-stream model by showing how bounded working memory, packet policy, grounding gates, novelty gates, and prediction-error shadow deltas interact over time.

It prepares later work on:

- larger replay corpora from stored runtime metadata
- visual/topological replay of multi-turn cognitive state
- human evaluation of duplicate suppression and grounded continuation quality
- Stage147-style replay-driven calibration without direct policy mutation
