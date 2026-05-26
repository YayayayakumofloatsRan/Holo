# Stage157 Holo Core Bench

Date: 2026-05-27

## Purpose

Stage157 adds a deterministic dry-run bench for the Holo Core infrastructure. It verifies that the main Agent Kernel surfaces are importable and inspectable without live providers, tool execution, memory mutation, or transport startup.

## Schema

```text
holo.stage157.core_bench.v1
```

## Bench Categories

```text
interactive_cli
tool_loop
engineering_actions
project_state
context_compiler
domain_scaffold
```

Each category reports a local availability score. The bench is readiness-oriented; it is not a quality benchmark for model reasoning.

## Boundary

Stage157 does not:

- call providers
- execute tools
- write memory
- start WeChat
- widen transport authority
- apply policy or reaction-kernel changes

## Python API

```python
from holo_host.holo_core_bench import run_holo_core_bench, render_holo_core_bench

report = run_holo_core_bench(dry_run=True)
print(render_holo_core_bench(report))
```
