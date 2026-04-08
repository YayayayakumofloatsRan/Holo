# Engineering Handoff: Stage-9 Live State

This document is the practical handoff for Stage-9 and should be kept short and operational.

## Snapshot
- Date: `2026-04-09`
- Repo of record: `D:\Holo\holo`
- Current live stage: `Stage-9` (adaptive initiative gate rollout)
- Current brain mode: `full_brain`
- Current transport: `pyweixin_dialog`
- Current active processor: `codex_cli`

## Stage-9 Goal
- keep the safety baseline unchanged
- keep safety gates like policy, whitelist, cooldown, thread/contacts state, and flow-rate limits non-overridable
- reduce over-conservative proactive blocking by splitting the gate into hard + soft
- allow main-brain-led scheduling override only on soft-blocked candidates in adaptive mode

## Core Principle
- hard_gate is hard: if it fails, `allowed` stays false and override is forbidden.
- soft_gate is directional: if it is weak, `allowed` may be false but override can still be considered.
- override does not bypass policy/cooldown/whitelist/thread missing/hard block conditions.
- stage-8 behavior must remain recoverable through `initiative_gate_mode=conservative`.

## Gate Rule Boundaries (Stage-9)
- hard_gate triggers:
- initiative gate disabled
- policy denies
- thread disallow proactive
- not in whitelist for the wechat helper mode
- cooldown not ready
- pending initiative ping job exists
- outgoing flow limit exceeded
- contact or thread invalid
- soft_gate scoring:
- trust component weight 0.26
- initiative_window component weight 0.28
- drive_pressure component weight 0.28
- pressure_level penalty component weight 0.18
- stage-9 thresholds:
- soft score >= 0.62 -> allowed
- 0.48 <= soft score < 0.62 -> soft_block with override_eligible=true
- soft score < 0.48 -> soft_block with override_eligible=false

## Expected Data Contract
- `initiative_probe` keeps legacy `allowed` and adds:
- `gate_level` (`allowed|soft_block|hard_block`)
- `hard_block_reasons` (reason list)
- `soft_gate_score` (0..1)
- `soft_gate_components` (`trust`, `initiative_window`, `drive_pressure`, `pressure_penalty`)
- `override_eligible`
- `recommended_action` (`allow|allow_with_override|block`)
- `initiative_status` includes gate summaries and counts:
- `gate_level_summary`
- `hard_block_reason_counts`
- `soft_block_reason_counts`
- `override_applied_count`
- candidate/job metadata fields:
- `gate_level`
- `soft_gate_score`
- `override_eligible`
- `main_brain_override_applied`
- `blocked_reason_code`
- `override_pending` status for soft-blocked candidates that can be reviewed

## Deployment and Rollback
- first run with `initiative_gate_mode=conservative` until command and CLI parity is observed
- then switch default to `initiative_gate_mode=adaptive`
- if behavior drifts, set `initiative_gate_mode=conservative` to recover the Stage-8 gate behavior
- continue monitoring whitelist-only proactive threads and `initiative_probe_blocked` trend

## Acceptance Checklist
- `accept-stage8` should remain passing after Stage-9 changes
- new `accept-stage9` should verify:
- soft-block candidates in adaptive mode are override-eligible when expected
- hard-block candidates never pass override
- policy + cooldown + whitelist boundaries still block
- `override_applied` reasonables are observable in status and candidate views
- existing `initiative_status`, `initiative_probe`, and candidate tables show stable schema fields

## Working Notes
- Stage-9 implementation should not modify desire or relationship model semantics
- this stage only changes gating topology and observability
- priority is stable outbound behavior in existing whitelisted threads

## Read Order for a New Thread
1. `HOLO_HANDOFF.md`
2. `docs/ENGINEERING_HANDOFF_STAGE8.md`
3. `docs/ENGINEERING_HANDOFF_STAGE9.md`
4. `HOLO_SYSTEM.md`
5. `HOLO_HOST.md`
6. `OPERATIONS.md`

## Exit Criteria
- initiative candidates now surface as soft-block/override states instead of all-or-nothing gate outcomes
- main brain can regain proactive agency while safety hard boundaries remain strict
