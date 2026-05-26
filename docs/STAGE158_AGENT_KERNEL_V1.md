# Stage158 Agent Kernel v1

Date: 2026-05-27

## Purpose

Stage158 closes the base infrastructure arc by packaging Holo as Agent Kernel v1. The kernel is a stable local host layer around interactive CLI, auditable event streams, tool-loop grounding, engineering actions, project continuity, context compilation, core bench readiness, and domain-module scaffolds.

## What Holo Core Can Do

- run an interactive CLI with auditable events
- preserve a single thread identity through CLI arguments
- expose tool, web, memory, engineering, cache, and stop-reason metadata
- record workspace-scoped engineering action ledgers
- keep project goals, tasks, decisions, open questions, risks, artifacts, and next actions in a local project-state graph
- compile structured context from reusable state, directives, evidence, project state, and current user request
- run a deterministic local core bench
- report Agent Kernel readiness
- load scaffold-only domain modules for future math, physics, market, and ProjectH work

## What It Cannot Yet Do

- implement math, physics, market, or ProjectH domain expert behavior
- prove domain claims without future domain-specific tools and ledgers
- expose hidden provider reasoning
- bypass Stage139-154 grounding rules
- start WeChat from the kernel readiness path
- run provider calls outside processor fabric
- apply durable policy or reaction-kernel changes from readiness output

## CLI

Interactive chat:

```powershell
python -m holo_host chat --thread-key holo_cli:default --chat-name HoloCLI --channel holo_cli
```

Agent Kernel readiness:

```powershell
python -m holo_host agent-kernel-readiness
```

Project state:

```powershell
python -m holo_host project-state --project Holo --summary
python -m holo_host project-state --project Holo --open-loops
python -m holo_host project-state --project Holo --next-actions
```

## Core Bench

```python
from holo_host.holo_core_bench import run_holo_core_bench, render_holo_core_bench

report = run_holo_core_bench(dry_run=True)
print(render_holo_core_bench(report))
```

The bench is local and deterministic. It checks kernel infrastructure availability; it is not a model-quality score.

## Domain Modules

Stage158 adds scaffold-only modules:

```text
math_research
physics_research
market_research
projecth_ops
```

Each module defines:

```text
module_id
module_name
instruction_scope
memory_schema
tool_requirements
bench_categories
report_templates
risk_boundaries
```

Use `docs/DOMAIN_MODULE_TEMPLATE.md` for future module work. Later stages must add implementation, evidence ledgers, tests, and safety boundaries before any domain module performs live work.

## Grounding And Trace Rules

- visible tool claims require tool observations
- visible memory claims require memory observations and alignment
- visible web/current claims require web/time observations
- visible engineering claims require engineering action ledgers
- CLI traces show auditable events only
- raw DeepSeek `reasoning_content` and hidden chain-of-thought remain internal

## Boundary

Stage158 does not add provider calls, execute tools, write memory, start WeChat, widen transport authority, implement approval policy, or create live domain behavior.
