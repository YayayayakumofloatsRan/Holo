# Stage191 Public Thought Stream

Stage191 makes Holo's internal agent loop easier to inspect in CLI without exposing raw hidden chain-of-thought or provider-private `reasoning_content`.

## Purpose

The operator needs to see how Holo moves from a user request to an action, an observation, a self-feedback appraisal, and a stop decision. A raw model reasoning transcript is not a stable or safe operational interface. Stage191 therefore exposes a public thought stream: a compact, auditable sequence of cards derived from existing event, tool, crawler, feedback, and stop ledgers.

## Schema

`holo.stage191.public_thought_stream.v1`

Each card uses:

`holo.stage191.public_thought_card.v1`

Fields include:

- `phase`: goal, intent, evidence, model_decision, host_decision, action, observation, self_feedback, grounding, stop, final
- `summary`: compact public summary
- `source_event`: source event label from Stage153/160R/190
- `confidence`: bounded public confidence score

## Runtime Behavior

- `InteractiveCliSession.record_turn()` builds `stage191_public_thought_stream` from the sanitized Stage153 event stream.
- `/thoughts` and `/think` render the public thought stream.
- `reply_api` adds `stage191_public_thought_stream` to `ReplyPlan.debug`, outgoing metadata, reply JSON, and archive metadata.

## Boundary

Stage191 does not show raw chain-of-thought. It does not expose DeepSeek `reasoning_content`, raw provider messages, hidden prompts, or internal scratchpads. It only renders public, auditable decision and feedback summaries that are already justified by ledgers.

## Verification

- `python -m pytest tests\test_stage191_public_thought_stream.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage191-green`
