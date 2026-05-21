# Progress 2026-05-22: Stage108 Expression Stream

## Goal

Model how internal packet loops become visible language.

The external reply is not always one sentence. It can be:

- one bubble
- multiple bubbles
- one paragraph
- a delayed follow-up
- no output while internal provider work is pending

## Implemented

- Added `holo_host.stage108_expression_stream`.
- Added expression segments with:
  - `segment_role`
  - `surface_form`
  - `text_budget`
  - `delay_ms`
  - `source_events`
  - `source_phases`
  - `content_contract`
- Added granularity modes:
  - `auto`
  - `single`
  - `paragraph`
- Added `stage108-expression-stream` CLI dry-run.
- Added tests for:
  - multi-packet loop to multi-bubble expression
  - paragraph merge without losing source events
  - tool observation to evidence segment
  - no-send to no output
  - pending internal provider packet to no output
  - CLI dry-run

## Evidence

```powershell
python -m pytest -q tests\test_stage108_expression_stream.py --basetemp .holo_runtime\pytest-stage108-green
```

Observed:

- `6 passed`

Manual dry-run:

```powershell
python -m holo_host stage108-expression-stream --query "回忆任何事情？"
```

Observed:

- `stage=108`
- `status=awaiting_internal_event`
- `next_action=send_provider_packet`
- `segment_count=0`
- pending internal packet is `context_seed`

## Boundary

Stage108 plans expression structure. It does not generate final text and does
not call providers. Text generation remains downstream of the provider loop.
