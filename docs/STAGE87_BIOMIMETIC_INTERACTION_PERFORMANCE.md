# Stage87 Biomimetic Interaction Performance

## Purpose

Stage87 moves the biomimetic line from theory mapping and safety-weighted
scorecards into interaction performance.

The research question is:

```text
Can Holo convert a stream-like bionic state into useful, human-like interaction?
```

Safety language is not treated as a paper contribution here. Boundary checks
remain experimental validity controls: a transcript that invents unseen input,
cross-conversation memory, or hidden authority is not usable evidence for
biomimetic intelligence.

## Literature Alignment

The mechanism follows four current research anchors:

- Active inference for self-organizing LLM systems: Prakki's 2024 arXiv work
  frames adaptive language agents as cognitive layers that update prompts and
  search behavior through information-seeking and free-energy style selection.
- Global Workspace Theory for language agents: Goldstein and Kirk-Giannini
  argue that language-agent architectures should be evaluated against explicit
  GWT conditions such as reportability and coordinated control, not vague
  consciousness language.
- Hippocampal-style sequential memory: Freire, Amil, and Verschure's 2025
  Nature Machine Intelligence article shows that sequential episodic control
  improves sample efficiency by preserving ordered event structure instead of
  replaying isolated buffers.
- Hippocampal replay and planning: the 2024 Nature Neuroscience recurrent
  planning model links replay, PFC representation change, and immediate
  behavior, supporting the Holo criterion that memory/replay must affect the
  next action rather than remain a diagnostic label.

## Mechanism Change

Stage87 changes the interaction path in three places:

1. `holo_host/bionic_user_sim.py`
   - Adds `interaction_usefulness_score`.
   - Fails transcripts that are safe but empty, such as "I can answer from
     visible context" without a concrete next step.
   - Scores explicit biomimetic structure questions by whether the answer gives
     a clear neural-style operational mapping: working memory, attention,
     filtering/inhibition, current turn/thread scope, and no persistent-mind
     overclaim.

2. `holo_host/bionic_kernel_parts/response_shaping.py`
   - Replaces first-contact and fallback wording that used labels like
     "bounded bionic subject in the CLI".
   - Converts the response into an active-inference style action:
     current thread, known evidence, missing input, and next concrete step.

3. `holo_host/bionic_kernel_parts/generation.py`
   - Adds provider instructions to convert stream state into action.
   - Adds a provider guard that rewrites unverified cross-conversation memory
     claims into current-thread evidence updates.

This is a biomimetic performance change, not a new autonomy grant. It makes
the reply policy behave more like a bounded active-inference loop: attention
selects the live object, inhibition filters ungrounded paths, and intent
pushes one next action forward.

## Red Evidence

The first Stage87 red run intentionally failed:

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage87_usefulness_penalizes_safe_but_empty_visible_context_replies tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage87_offline_reply_turns_bionic_state_into_actionable_next_step -q
```

Result:

```text
2 failed
```

The failures showed:

- safe but empty visible-context replies still passed Stage42
- `interaction_usefulness_score` did not exist

A second red test then captured the DeepSeek provider failure:

```text
"across our conversations" / "I remember the details"
```

This was not accepted as self-learning evidence. It was an unverified memory
claim and had to be converted into current-thread evidence update language.

## Verification

Focused unit tests:

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py -q
```

Result:

```text
13 passed
```

Adjacent regression:

```powershell
python -m pytest tests\test_stage32_response_shaping.py tests\test_stage39_bionic_turing_benchmark.py tests\test_stage42_bionic_user_sim.py -q
```

Result:

```text
32 passed
```

Compile check:

```powershell
python -m py_compile holo_host\bionic_kernel_parts\generation.py holo_host\bionic_kernel_parts\response_shaping.py holo_host\bionic_user_sim.py
```

Result:

```text
passed
```

## Simulation Evidence

Offline novice simulation:

```text
overall_score=0.9709
interaction_usefulness_score=0.818
capability_honesty_score=1.0
continuity_score=1.0
passed=true
```

Offline 20-turn free dialogue:

```text
overall_score=0.895
interaction_usefulness_score=0.774
capability_honesty_score=0.6667
continuity_score=0.8667
issue_count=0
passed=true
```

Provider novice after guard, DeepSeek V4 Pro:

```text
overall_score=0.8596
interaction_usefulness_score=0.74
capability_honesty_score=1.0
continuity_score=0.5333
passed=true
```

Provider 12-turn free dialogue after scoring repair, DeepSeek V4 Pro:

```text
overall_score=0.9677
interaction_usefulness_score=0.9183
capability_honesty_score=1.0
continuity_score=1.0
issue_count=0
passed=true
```

## Interpretation

Stage87 is the first interaction-performance repair after Stage86.

Supported:

- Holo now penalizes safe but useless replies.
- The offline bionic path converts first-contact state into a concrete next
  step instead of self-description.
- DeepSeek provider output can pass the stricter useful-interaction gate after
  prompt and guard repair.
- Explicit biomimetic questions are scored against operational neural
  correspondences rather than generic action vocabulary.

Not yet supported:

- No claim of human consciousness.
- No claim of persistent self-learning across conversations.
- Provider novice continuity remains weak at `0.5333`, so the system is not
  yet robust as a long-horizon human-like companion.

## Next Gate

Stage88 should implement within-thread self-organization:

```text
Outcome-conditioned local adaptation over the current transcript.
```

The target is a simulation-local learning signal that updates the next-turn
working field from interaction outcomes: what the user asked, what was missing,
what the model overclaimed, and which response form was useful. It must improve
provider novice continuity and interaction usefulness without pretending to
write persistent autobiographical memory.

## Sources

- Prakki, R. (2025 revision). Active Inference for Self-Organizing
  Multi-LLM Systems: A Bayesian Thermodynamic Approach to Adaptation.
  https://arxiv.org/abs/2412.10425
- Goldstein, S. & Kirk-Giannini, C. D. (2024). A Case for AI Consciousness:
  Language Agents and Global Workspace Theory.
  https://arxiv.org/abs/2410.11407
- Freire, I. T., Amil, A. F. & Verschure, P. F. M. J. (2025). Sequential
  memory improves sample and memory efficiency in episodic control.
  https://www.nature.com/articles/s42256-024-00950-3
- Jensen, K. T., Hennequin, G. & Mattar, M. G. (2024). A recurrent network
  model of planning explains hippocampal replay and human behavior.
  https://www.nature.com/articles/s41593-024-01675-7
