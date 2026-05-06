# Memory Library Guidelines

This directory contains the local memory and voice-profile tooling for a configurable subject runtime.

## Public Boundary
- Do not commit real subject profile files: `.subject.local.md`, `subject_seed.md`, or `voice_profile.md`.
- Do not commit live memory JSONL, runtime databases, transport receipts, snapshots, or chat exports.
- Public files should describe architecture and templates, not one deployment's private memories or personality.

## Runtime Shape
- Canonical profile templates define the local subject when copied into private files.
- Structured memory tiers are lifecycle stores, not raw prompt dumps.
- Candidate and working memory must be distilled and reviewed before durable prompt eligibility.
- Runtime memory is self-state; do not bolt on a second brain layer.

## Editing Rules
- Preserve deterministic and inspectable memory behavior.
- Keep this library independent from any one operator, contact, transport, or deployment persona.
- Prefer generic examples in public docs and tests unless a test is explicitly checking localization or fixture handling.
