# Processor Routing And Cost Policy

This document freezes the processor fabric policy.

The goal is simple:
- use the strongest reasoning only where it matters
- let cheaper/faster lanes carry low-density cognition
- keep cost visible and attributable

## 1. Lane Policy

### `kernel_xhigh`

Default:
- model: `gpt-5.4`
- reasoning: `xhigh`

Use for:
- deep simulation
- operator planning and review
- self-revision planning and review
- high-conflict or high-uncertainty reply override

Do not use for:
- ordinary chat
- routine background loops
- simple probes

### `subject_main`

Default:
- model: `gpt-5.4`
- reasoning: `medium`

Use for:
- reply
- recall reconstruction
- goal arbitration
- autobiographical consolidation
- world calibration
- single-image synchronous understanding

### `micro_fast`

Default:
- model: `gpt-5.4-mini`
- reasoning: `low`

Use for:
- lightweight background cognition
- initiative probes
- affect/drive/value/conflict helper tasks
- outcome appraisal
- async or batch image understanding

## 2. Default Task Routing

### kernel_xhigh

- `deep_simulation`
- `operator_plan`
- `operator_review`
- `self_revision_plan`
- `self_revision_review`
- `reply` only when action conflict or uncertainty crosses threshold

### subject_main

- `reply`
- `recall_reconstruct`
- `goal_arbitration`
- `autobiographical_consolidation`
- `world_calibration`
- synchronous `image_understand`

### micro_fast

- `self_model_observe`
- `initiative_probe`
- `affect_reflect`
- `drive_plan`
- `value_integrate`
- `conflict_arbitrate`
- `outcome_appraise`
- async or bulk `image_understand`

## 3. Override Rules

- `reply` starts in `subject_main`
- upgrade to `kernel_xhigh` only if:
  - selected action is high-conflict
  - or uncertainty is above configured threshold
- `operator_execute_shadow` follows the plan lane; it is not automatically downgraded

## 4. Budget Discipline

- ordinary low-pressure chat:
  - one `subject_main reply`
- recall-heavy turn:
  - `recall_reconstruct` only when recall or deep-recall actually triggered
- `kernel_xhigh`:
  - never on a blind fixed timer
- background loops:
  - prefer `micro_fast`
- image understanding:
  - default async
  - sync only for single-image threshold-safe cases

## 5. Cost Ledger Policy

All processor calls should write to `processor_usage_ledger` with:
- task type
- lane
- provider
- model
- reasoning effort
- timing
- prompt/completion/total tokens
- `estimated=true|false`
- status

If provider returns real usage:
- record it directly

If provider does not:
- estimate usage
- mark `estimated=true`

## 6. What To Inspect Before Changing Routing

- `python3 -m holo_host show-processor-routing`
- `python3 -m holo_host show-provider-status`
- `python3 -m holo_host show-usage-ledger --limit 100`
- `python3 -m holo_host accept-processor-fabric`

## 7. Forbidden Routing Regressions

- do not route every task to one giant `codex exec` bucket
- do not let low-density loops drift onto `kernel_xhigh`
- do not add direct model call sites that bypass the runner and usage ledger
- do not silently alter provider fallback semantics
