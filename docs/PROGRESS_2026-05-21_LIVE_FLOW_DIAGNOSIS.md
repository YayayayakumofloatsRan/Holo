# Progress - Live Flow Diagnosis - 2026-05-21

## Context

`/live-readiness` proved whether Holo could speak through the intended DeepSeek
path, but it did not answer whether the whole long-running subject process was
still moving. A single green readiness check can miss stale self-model loops,
memory stream stoppage, queue backlog, or transport heartbeat drift.

For a long-running single-subject Holo instance, the operator needs one compact
surface for the full flow:

- subject continuity
- transport surface, when present
- reply API readiness
- processor/provider usage
- vector and stream memory
- core brain loops
- queued jobs
- operator/self-maintenance state

## Decision

Add a live flow diagnosis surface that sits above readiness without replacing
it.

`/live-readiness` remains the critical speech gate:

- provider path
- no live Codex dependency
- vector readiness
- latest processor usage not error

`/live-flow` is the broader long-running health view:

- status `healthy`, `attention`, or `blocked`
- flow nodes for subject, transport, reply API, processor, memory, brain loops,
  queue, and operator
- critical checks for readiness, latest DeepSeek reply, and bounded provider
  errors
- warning checks for stale core loops, queue backlog, and missing memory stream
  movement
- explicit repair recommendations

## Implementation Notes

- Service method: `HoloReplyService.live_flow()`.
- HTTP endpoint: `GET /live-flow`.
- CLI command: `python3 -m holo_host show-live-flow`.
- `scripts/holo-status.sh` now prints a flow summary after readiness.
- Transport is included as an optional node. Holo must keep working through the
  independent live conversation API even when WeChat is offline.
- The subject node is fixed to `holo_app:HoloSubject` to keep the single-thread
  continuity model explicit.
- Queue samples are compacted so flow output does not dump full job payloads.
- `QueueStore.complete_job()` clears stale `last_error` on successful handoff or
  terminal completion, and `initialize()` repairs older stale handoff errors.
- Mind graph thread/contact nodes now include channel in `source_id`, preventing
  email/wechat aliases from colliding on `mind_nodes(source_store, source_id)`.

## Verification Targets

- `python -m pytest tests/test_holo_host.py::HoloLiveFlowTests -q`
- `python -m pytest tests/test_cli_live_api.py::CliLiveApiRequestTests::test_live_flow_payload_uses_live_http_before_local_process -q`
- `python -m holo_host show-live-flow`
- WSL live restart followed by `GET /live-flow`

## Verified

- `python -m pytest tests\test_holo_host.py::HoloLiveFlowTests -q`: 4
  passed.
- `python -m pytest tests\test_holo_host.py::QueueStoreTests::test_complete_job_clears_previous_retry_error tests\test_holo_host.py::QueueStoreTests::test_initialize_clears_stale_handoff_errors_from_existing_jobs tests\test_holo_host.py::QueueStoreTests::test_record_outcome_appraisal_keeps_canonical_wechat_thread_key -q`:
  3 passed.
- `python -m pytest tests\test_cli_live_api.py -q`: 2 passed.
- `python -m pytest -q`: 271 passed.
- Materialized source duplicate check: `nodes 1158 dups 0`.
- Targeted queue tests verify stale retry errors are cleared on completion and
  repaired during store initialization.
- WSL live restart via `scripts/holo-wsl-restart-all.ps1` succeeded:
  `reply_api` and `daemon` running, WeChat watcher started.
- Live HTTP checks after restart:
  - `/live-readiness`: `ready`; DeepSeek primary available; vector memory
    ready; latest reply usage `ok`.
  - `/live-flow`: `healthy`; latest reply provider `deepseek`; queue
    `active_count=0`; core loops fresh; stream memory visible.
- CLI live check: `python -m holo_host show-live-flow` returned `healthy` with
  all flow checks true and `queue_active=0`.
