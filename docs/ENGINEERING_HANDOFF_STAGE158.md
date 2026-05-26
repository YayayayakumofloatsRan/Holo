# Engineering Handoff Stage158

Date: 2026-05-27

## Summary

Stage158 packages Holo as Agent Kernel v1. It adds scaffold-only domain modules, a deterministic readiness report, a CLI entrypoint, and documentation for the stable core boundary.

Because the checkout did not contain Stage156 or Stage157 files at the start of this work, this stage also adds the minimal Stage156 context compiler surface and Stage157 core bench surface needed for readiness to be real rather than a dangling check.

## Files Changed

Added:

```text
holo_host/context_compiler.py
holo_host/holo_core_bench.py
holo_host/domain_modules.py
holo_host/agent_kernel_readiness.py
tests/test_stage157_holo_core_bench.py
tests/test_stage158_agent_kernel.py
docs/STAGE156_CONTEXT_COMPILER_CACHE_DISCIPLINE.md
docs/STAGE157_HOLO_CORE_BENCH.md
docs/STAGE158_AGENT_KERNEL_V1.md
docs/ENGINEERING_HANDOFF_STAGE158.md
docs/DOMAIN_MODULE_TEMPLATE.md
```

Modified:

```text
holo_host/cli.py
HOLO_HANDOFF.md
docs/ROADMAP_REGISTRY.md
```

## New Schemas

```text
holo.stage156.context_compiler.v1
holo.stage157.core_bench.v1
holo.stage158.domain_module.v1
holo.stage158.agent_kernel_readiness.v1
```

## Runtime Propagation

Stage158 adds a CLI readiness command:

```powershell
python -m holo_host agent-kernel-readiness
```

The command prints JSON by default and returns nonzero if any required kernel subsystem is missing.

## Domain Scaffolds

```text
math_research
physics_research
market_research
projecth_ops
```

All scaffolds are `scaffold_only`, `implements_live_work=false`, and have no runtime entrypoint.

## Constraints Preserved

- no provider calls
- no tool execution
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure
- no live domain-module behavior

## Verification

```text
python -m pytest tests\test_stage158_agent_kernel.py tests\test_stage157_holo_core_bench.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage158-targeted
9 passed in 0.33s

python -m holo_host agent-kernel-readiness
status=passed; passed_count=8; failed_count=0

python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
634 passed in 75.90s

python scripts\check_public_release_hygiene.py
Public release hygiene passed

git diff --check
exit 0; only line-ending warnings for touched existing files
```

## Next Suggested Stage

Stage159 should implement one domain module only after defining its evidence ledgers, benchmark categories, and no-hidden-reasoning trace contract.
