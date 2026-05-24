# Stage133 Core Problem Research Loop

Date: 2026-05-24

## Purpose

Stage133 turns the V2 proposal into an executable research loop. The research target is the core problem stated in V2:

> When an LLM already has strong language-processing ability, what outer cognitive architecture can organize finite provider calls into a continuous, memorable, actionable, self-correcting, observable human-like mind process?

This stage is not another proposal artifact. It is a deterministic baseline harness for research iteration.

## What It Adds

Stage133 adds `holo_host.stage133_core_problem_research_loop`.

The module defines seven V2 subproblems:

1. state representation
2. packet scheduling
3. memory coordination
4. action loop
5. expression stream
6. learning feedback
7. observability

For each subproblem it generates research probes, simulates the state pressures behind the turn, runs Stage121 packet policy, runs Stage132 progressive stream planning, and exports a redacted payload plus an HTML workbench.

## Research Value

The output is a measurable baseline before live provider experiments:

- whether the system covers all V2 subproblems;
- whether fast-only and deep-continuation paths both occur;
- whether tool and visual paths are represented;
- whether continuation is decided by state rather than hard-coded turns;
- whether semantic novelty and continuity motion are measurable;
- whether the result is safe to publish without raw provider text or private memory.

## CLI

```powershell
python -m holo_host stage133-core-problem-loop --output-dir artifacts/stage133
```

Useful options:

```powershell
python -m holo_host stage133-core-problem-loop --probes-per-subproblem 3 --context-window-tokens 65536 --output-dir artifacts/stage133
```

## Artifacts

Default output:

- `artifacts/stage133/stage133_core_problem_research_loop_payload.json`
- `artifacts/stage133/stage133_core_problem_research_loop.html`

The HTML workbench shows:

- core-problem trajectory;
- subproblem filter;
- state-slice proxy;
- per-probe continuation decision;
- Stage121 stream mode;
- Stage132 fast/deep plan;
- tool requests and semantic novelty.

## Boundaries

Stage133 is a deterministic research baseline. It does not call a provider and does not execute tools. It prepares the measurement surface needed before live provider tests.

The WSL Holo host remains the single brain. Windows, WeChat, camera, and mobile surfaces remain transport or sensor layers.
