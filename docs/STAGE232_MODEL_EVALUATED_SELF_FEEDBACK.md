# Stage232 Model-Evaluated Self Feedback

Kernel version remains `2.1.0`.

## Purpose

Stage230 introduced host-generated self-feedback reports. Stage232 adds a model
evaluation step after each action observation, closer to a Codex-style loop:

```text
model_decide
-> host executes tool
-> observation ledger
-> host baseline feedback
-> model_evaluate
-> host guardrail normalization
-> next model decision or final
```

The model can judge whether evidence is sufficient, what gap remains, which
next action has value, and what stop reason applies. The host still prevents
invalid public state transitions.

## Schema

```text
holo.stage232.model_self_feedback.v1
```

Reports include:

- host baseline feedback
- model feedback
- evaluator: `model`, `model_guarded`, `host`, or `host_after_model_error`
- evidence sufficiency
- evidence gap
- recommended next action
- canonical stop reason
- marginal utility
- guardrail flags

## Guardrails

The model does not get unchecked authority over runtime truth.

- A failed observation cannot become `evidence_sufficient=true`.
- A failed observation cannot stop as `final_answer_ready`.
- A bare `web_search` result cannot be treated as final source evidence without
  opened-page evidence.
- If the model evaluation call fails, the host baseline feedback is used and
  the error is recorded.

This keeps the loop model-first in semantic evaluation while preserving
ledger-based authority.

## DeepSeek Path

`DeepSeekJsonModel.evaluate_action_feedback()` now prompts DeepSeek with:

- rendered context pack
- action decision
- observation ledger row
- host baseline feedback
- JSON contract

The returned JSON is normalized by the host. The prompt explicitly asks for an
auditable public reason, not hidden chain-of-thought.

## CLI Trace

The event stream now includes:

```text
[model_evaluate] evaluator=<host|model|model_guarded> next=<action> stop=<reason>
[self_feedback] <tool> sufficient=<true|false> next=<action> stop=<reason>
```

Fallback mode reports `evaluator=host`; provider-backed models can report
`evaluator=model` when they implement the evaluation method.

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage232_model_self_feedback.py tests\test_stage230_self_feedback_loop.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage232-green3
```

Result:

```text
9 passed
```

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\base
```

Result:

```text
89 passed
```

WSL trace:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo-agent-kernel && python3 -m holo_agent run 'open https://docs.python.org/3/library/asyncio.html and summarize source' --trace --model fallback"
```

Observed:

```text
[model_evaluate] evaluator=host next=answer_direct stop=final_answer_ready
```

Fallback has no provider evaluation call, so host baseline is expected there.
