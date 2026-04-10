# Stage21 Policy Sedimentation And Negotiated Will

## Goal

Stage21 turns repeated outcomes and explicit negotiation into bounded policy sediment:

- what Holo has learned is usually welcome
- what Holo should resist
- what should require more caution
- what the user has explicitly negotiated

The result should make Holo's will more stable without making policy mutable in unsafe ways.

## Boundary

- Hard policy constraints remain hard.
- Owner shutdown remains final.
- No self-modifying policy code.
- No secret/auth/policy self-escalation.
- No manipulative initiative expansion.
- No transport-side decision logic.
- Preserve action-market-first deliberation.

## Runtime Shape

Stage21 should layer soft sediment over existing policy and action simulation:

1. hard policy gate
2. canonical safety and owner constraints
3. negotiated policy sediment as reversible soft bias
4. action-market simulation and selection
5. outcome appraisal writes new evidence

Sediment can increase or decrease the score of actions such as:

- `reply_once`
- `reply_multi`
- `defer_reply`
- `silence`
- `push_back`
- `counter_offer`
- `continuity_defense`
- `initiative_ping`

Sediment cannot make a hard-blocked action allowed.

## Data Contract

Minimum `policy_sediment` fields:

```json
{
  "sediment_id": "",
  "channel": "wechat",
  "thread_key": "wechat:Nemoqi",
  "scope": "thread",
  "policy_key": "",
  "preference": "",
  "bias_delta": 0.0,
  "confidence": 0.0,
  "status": "active",
  "evidence_refs": [],
  "counterevidence_refs": [],
  "created_at": "",
  "updated_at": ""
}
```

Allowed scopes:

- `thread`
- `contact`
- `global_soft`

Forbidden scopes:

- `hard_policy`
- `owner_shutdown`
- `secrets`
- `auth`

`mind_packet.stage21` should include:

```json
{
  "sediments_visible": false,
  "sediment_bias_applied": false,
  "applied_policy_keys": [],
  "hard_gate_preserved": true,
  "negotiated_will_mode": "observe"
}
```

## Negotiated Will Contract

Negotiated will means Holo can prefer, resist, or counter-offer with evidence.

It does not mean:

- overriding explicit refusal
- bypassing cooldowns
- escalating autonomy
- treating a single ambiguous outcome as a permanent rule
- turning style preference into safety policy

Sediment must be reversible. Counterevidence should lower confidence or mark the sediment superseded.

## Acceptance Checklist

Closure command:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage21 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The acceptance gate should verify:

- Stage20 remains green.
- Positive repeated outcomes create soft sediment with evidence refs.
- Explicit correction creates counterevidence or a revised sediment.
- Sediment biases action-market scores but does not select directly.
- Hard policy denial remains denied even with positive sediment.
- Resistance actions can be favored only when risk and evidence allow them.
- Reversal/supersession is observable.
- Stage14 policy regret replay remains green.

Recommended regression commands:

```bash
pytest -q tests/test_stage21_policy_sedimentation.py
pytest -q tests/test_stage20_temporal_commitments.py
python -m holo_host --config .holo_host.example.toml replay-policy-regret --fixture-path tests/fixtures/stage14
python -m holo_host --config .holo_host.example.toml accept-stage21 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
pytest -q
```

## Regression Risks

- Soft sediment becomes a hard policy override.
- A single outcome ossifies into a broad preference.
- Resistance becomes over-eager or adversarial.
- Initiative is allowed through sediment instead of whitelist/cooldown/policy gates.
- Sediment records leak across contacts.
- Replay policy regret worsens without an observable reason.

## Rollback

Stage21 should degrade by ignoring sediment rows and returning to Stage20 action-market behavior. Hard policy behavior must be identical with or without Stage21 sediment.
