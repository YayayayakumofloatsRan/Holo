# Progress 2026-05-22: Stage110 Theory-Guided Packets

## Goal

Make theory guide provider packet dispatch.

## Implemented

- Added `holo_host.stage110_theory_guided_packets`.
- Added `stage110-theory-guided-packets` CLI dry-run.
- Added guidance fields:
  - `recommended_packet_count`
  - `recommended_packet_budget_tokens`
  - `applied_axioms`
  - `packet_rules`
  - `tool_policy`
  - `expression_policy`
  - `measurement_hooks`
- Added tests for:
  - broad recall budget expansion
  - tool-first lookup
  - no-send stop preservation
  - expression wait before provider return
  - CLI output
- Added a research bridge from working memory, global workspace,
  complementary learning systems, predictive processing, generative agents,
  and ReAct to concrete packet-control rules.

## Evidence

Initial Stage110 unit verification:

```powershell
python -m pytest -q tests\test_stage110_theory_guided_packets.py --basetemp .holo_runtime\pytest-stage110-green2
```

Observed:

- `5 passed`

Focused regression after cleanup:

```powershell
python -m pytest -q tests\test_stage110_theory_guided_packets.py tests\test_stage109_consciousness_flow_theory.py tests\test_stage108_expression_stream.py tests\test_stage107_provider_interaction_loop.py tests\test_stage106_deepseek_tool_adapter.py tests\test_stage105_provider_packet_stream.py tests\test_stage104_context_learning.py tests\test_processor_fabric.py tests\test_cli_chat.py tests\test_cli_live_api.py --basetemp .holo_runtime\pytest-stage110-final2
```

Observed:

- `60 passed`

Manual dry-run:

```powershell
python -m holo_host stage110-theory-guided-packets --query "recall anything from memory"
```

Observed:

- `stage=110`
- `send_decision=send_multi`
- `recommended_packet_count=3`
- `recommended_packet_budget_tokens=3000`
- `required_metric_ids` includes `source_event_coverage`,
  `delta_retention`, `grounding_ratio`, `expression_granularity_fit`,
  and `premature_expression_rate`

## Boundary

Stage110 does not send provider packets. It emits guidance for the live
executor that will do the sending in a later stage.
