# Handoff Checklist

Use this checklist when a new thread takes over Holo work.

## 1. Read Order

1. `HOLO_HANDOFF.md`
2. `docs/WECHAT_WATCHER_INTERFACE_CONTRACT.md`
3. `docs/HOLO_ARCHITECTURE_MAP.md`
4. `docs/WHEEL_CATALOG.md`
5. `docs/PROCESSOR_ROUTING_AND_COST_POLICY.md`
6. `docs/PROVIDER_COMPATIBILITY_CONTRACT.md`
7. current stage handoff doc
8. current stage cost/intelligence doc

If Stage-10 is the active work item, read:
- `docs/ENGINEERING_HANDOFF_STAGE10.md`
- `docs/STAGE10_ENGINEERING_AWARENESS_AND_CODEX_COST.md`

## 2. Baseline Commands

- `./scripts/holo-status.sh`
- `python3 -m holo_host show-provider-status`
- `python3 -m holo_host show-processor-routing`
- `python3 -m holo_host show-usage-ledger --limit 50`
- `python3 -m holo_host show-brain-status`

## 3. If WeChat Is Broken

1. read watcher contract first
2. inspect:
   - `.holo_runtime/wechat-helper/transport_state.live.json`
   - `.holo_runtime/wechat-helper/receipts/pyweixin_watcher.log`
3. confirm runtime config came from:
   - `windows_helper/start_holo_wechat.ps1`
4. do not hand-edit runtime config as the first fix

## 4. If Replies Feel Wrong

Inspect:
- `show-intent-state`
- `show-action-market`
- `trace-action-selection`
- `trace-deliberation-ledger`
- `show-world-state`
- `show-goal-state`

## 5. If Costs Feel Wrong

Inspect:
- `show-usage-ledger --limit 100`
- `show-processor-routing`
- `show-provider-status`

Look for:
- too many `reply` calls
- frequent `kernel_xhigh` upgrades
- background loops not staying on `micro_fast`
- repeated recall reconstruction

## 6. Before Editing

- confirm whether Holo should remain online
- run only targeted tests first
- avoid watcher changes unless absolutely necessary
- avoid direct provider call additions

## 7. After Editing

- rerun relevant tests
- rerun:
  - `accept-processor-fabric`
  - any stage acceptance gate touched by the change
- update docs if:
  - routing changed
  - provider semantics changed
  - watcher behavior changed
  - runtime observability changed

## 8. Hard No-Go Areas

- hand-editing watcher runtime config as a normal workflow
- adding direct `codex exec` subprocess calls outside the processor runner
- adding direct HTTP model calls outside provider classes
- treating autobiographical/goal/world state as display-only
- publishing runtime state or live memory to the public repo
