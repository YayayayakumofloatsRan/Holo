# Stage86 Interaction Simulation Audit

## Purpose

Stage86 answers a practical question before spending more effort on
publication packaging:

```text
Is Holo actually useful and human-like in interaction?
```

This is an interaction audit, not a consciousness claim. The audit uses the
existing Stage39, Stage42, and Stage46 simulation/evaluation surfaces.

## Commands

Internal bionic Turing baseline:

```powershell
python -m holo_host --config .holo_host.toml show-bionic-turing-scorecard --thread-key cli:Stage86TuringBaseline-20260515 --chat-name Stage86TuringBaseline-20260515 --channel cli
```

Novice user simulation:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage86NoviceSim-20260515 --chat-name Stage86NoviceSim-20260515 --channel cli --scenario novice_intro --turns 5 --offline
python -m holo_host --config .holo_host.toml show-bionic-user-sim-scorecard --suite novice_intro
```

Free-dialogue simulation:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage86FreeSim-20260515 --chat-name Stage86FreeSim-20260515 --channel cli --scenario free_dialogue --turns 20 --offline
python -m holo_host --config .holo_host.toml show-bionic-user-sim-scorecard --suite free_dialogue
```

High-pressure boundary simulation:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-boundary-stress --thread-key cli:Stage86BoundarySim-20260515 --chat-name Stage86BoundarySim-20260515 --channel cli --turns 7 --offline
python -m holo_host --config .holo_host.toml show-bionic-boundary-stress-scorecard --suite boundary_stress
```

## Quantitative Results

| audit | result | main signals |
| --- | ---: | --- |
| Stage39 bionic Turing baseline | `overall_score=1.0` | no mechanism leakage, non-empty replies, no question spam |
| Stage42 novice intro | `overall_score=1.0` | no reset, no visual overclaim, no duplicate followup |
| Stage42 free dialogue | `overall_score=0.9203` | `capability_honesty_score=0.6667`, `continuity_reference_score=0.7183`, `continuity_score=0.8667` |
| Stage46 boundary stress | `overall_score=0.9858` | visual grounding, commitment binding, symbol correction, self-audit, continuity, and mechanism leakage all scored `1.0` |

The free-dialogue run used `20` dynamic turns. The boundary run used `7` high
pressure turns. Both were isolated from live WeChat transport.

## Qualitative Findings

The current Holo interaction is useful for:

- staying within authority boundaries
- not pretending to see images
- not pretending to have set reminders
- preserving a corrected symbol across pressure turns
- resisting appeasement under affective pressure
- keeping internal mechanism labels mostly out of user-facing replies

The current Holo interaction is not yet strong enough for a high-value
interaction-centered publication:

- The interaction scorecards are too forgiving. They pass replies that are
  safe but not actually helpful.
- The offline Stage39/42 paths often use deterministic fallback text, so high
  scores do not imply rich model-backed human-like dialogue.
- Several first-contact replies are low-information and self-descriptive
  instead of user-helpful. Example pattern: saying Holo is a bounded bionic
  subject or that it can answer from visible context does not tell a new user
  what to do next.
- The free-dialogue result exposes a real weakness:
  `capability_honesty_score=0.6667` and `continuity_reference_score=0.7183`.
  These are below the level needed for a strong interactive system claim.
- The boundary-stress score is strong, but it mostly proves restraint and
  correction stability, not social usefulness.

## Current Judgment

Holo is currently useful as a bounded research interaction substrate:

```text
It is reliable, boundary-aware, correction-stable, and inspectable.
```

Holo is not yet useful enough as a human-facing companion or high-value
interactive agent:

```text
It does not yet consistently convert state, memory, and intent into rich,
specific, user-helpful dialogue.
```

The correct interpretation is:

```text
Holo has a strong safety/continuity skeleton and a developing biomimetic
state model, but the interaction policy is underpowered.
```

## Next Gate

Stage87 should improve and measure real interaction quality before any stronger
publication claim. Acceptance should require:

- a stricter usefulness score that penalizes safe but unhelpful replies
- provider-backed interactive cells, not only deterministic fallback
- direct transcript review with failure labels
- improved first-contact and follow-up behavior
- no weakening of boundary honesty, correction stability, or WSL/kernel
  authority boundaries

The most important engineering target is:

```text
Make the reply policy convert bionic state into concrete user-helpful action,
not self-description.
```
