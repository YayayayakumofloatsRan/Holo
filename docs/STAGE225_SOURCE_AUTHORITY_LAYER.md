# Stage225 Source Authority Layer

Stage225 adds source-authority metadata to Holo Agent Kernel `2.1.0`.

## Purpose

Market research, financial analysis, literature review, and domain analysis
depend on source quality. The agent must know whether it has primary evidence
or only weak secondary material.

## Added Runtime Evidence

Every model decision context now includes:

```text
source_authority
```

The report is derived from current observations and includes:

- `source_count`
- `primary_source_count`
- `opened_primary_source_count`
- `authority_counts`
- per-source authority labels

Current authority labels:

- `regulatory_filing`
- `company_official`
- `official`
- `official_repository`
- `repository`
- `secondary`

## Role In The Agent Loop

This is not a replacement for model judgment. It is structured evidence for
the model:

```text
observations -> source_authority -> model_decide/finalize
```

The model still decides whether evidence is enough, but it now sees whether the
evidence set contains primary sources.

## Financial Research Direction

For market and fundamental research, the next layers should add:

- filing/source discovery tools
- ticker/company identity resolution
- filing extraction and section reading
- metrics ledger
- report assembler with citation requirements
- model-based final report evaluator
