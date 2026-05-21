# Holo Memory System Optimization Progress - 2026-05-21

## Objective

Holo's memory system needs to move from "can recall" toward a biomimetic substrate that can be audited as a continuous subject:

- episodic flow: conversation and event archive
- semantic consolidation: durable distilled memories
- affective/homeostatic traces: pressure, affect, drive, salience
- active-thread continuity: fast working set for the current subject thread
- topology and vector substrate: graph/vector retrieval without turning transport into a second brain

The first optimization is a read-only memory doctor. It creates a repeatable health baseline before any consolidation, pruning, or vector-topology work.

## Implemented

Added `python -m holo_host memory-doctor`.

The command emits JSON with no raw conversation text or memory body:

- JSONL store integrity: valid rows, invalid rows, blank rows, exact duplicate rows, duplicate ids, top channels and thread keys.
- SQLite integrity and table counts for `.holo_runtime/mind_graph.sqlite3` and `.holo_runtime/holo_host.sqlite3`.
- Static vector substrate check for `.holo_runtime/milvus/memory_fabric.db`.
- Reply route latency summary from `.holo_runtime/logs/reply_api.log`, with adjacent duplicate log lines de-duplicated.
- Archive metadata pressure: metadata keys, route counts, timing distribution, largest timing rows by id/line only.
- Thread identity continuity: detects bare WeChat aliases versus canonical `wechat:<name>` splits.
- Biomimetic health summary:
  - substrate integrity
  - semantic consolidation freshness
  - episodic/semantic balance
  - deep-recall pressure
  - active-thread fast-lane evidence
  - thread-continuity fragmentation
  - archive metadata pressure
  - vector index presence

Optional vector open probe:

```powershell
python -m holo_host memory-doctor --include-vector-open
```

Default mode is static-only so the doctor can be run while the WSL brain is live without trying to open an active vector store.

## Verification

Local tests:

```powershell
pytest -q tests/test_memory_doctor.py --basetemp .holo_runtime\pytest-tmp
```

Result:

```text
4 passed
```

Local command smoke:

```powershell
python -m holo_host memory-doctor | Out-File -FilePath .holo_runtime\memory_doctor.windows.json -Encoding utf8
python -c "import json, pathlib; data=json.loads(pathlib.Path('.holo_runtime/memory_doctor.windows.json').read_text(encoding='utf-8-sig')); print(data['schema']); print(data['privacy']['raw_text_included'])"
```

Result:

```text
holo.memory_doctor.v1
False
```

WSL brain command smoke:

```bash
cd /home/holo/holo
python3 -m holo_host memory-doctor > .holo_runtime/memory_doctor.wsl.json
python3 - <<'PY'
import json
from pathlib import Path
data = json.loads(Path(".holo_runtime/memory_doctor.wsl.json").read_text(encoding="utf-8"))
print(data["schema"])
print(data["privacy"]["raw_text_included"])
print(data["biomimetic_health"]["substrate_integrity"]["status"])
print(data["biomimetic_health"]["semantic_consolidation"]["status"])
PY
```

Result:

```text
holo.memory_doctor.v1
False
ok
critical
```

WSL note: `pytest` is not installed in the current WSL Python environment, so test execution was verified on Windows and WSL was verified by CLI smoke.

## Next Biomimetic Frontier

The next work should be driven by the doctor report, not by adding isolated features:

1. Episodic-to-semantic consolidation gate.
   Convert archive pressure into durable semantic memories with explicit promotion budgets, freshness checks, and provenance.

2. Operational-ledger split.
   Keep timing, recall reconstruction, route traces, and debug payloads outside the autobiographical archive so episodic memory stays compact and biologically plausible.

3. Canonical identity backfill.
   Repair any `wechat:<name>` versus bare-name split before more long-horizon learning. Subject continuity depends on stable identity keys.

4. Deep-recall pressure control.
   Treat heavy recall as slow cortical reconstruction, not the default reflex. Ordinary continuity should prefer active-thread summaries and current salience.

5. Semantic-vector motion telemetry.
   Record low-dimensional semantic movement, affect vector drift, and graph activation deltas per turn for the stage99-style visualization. This should be derived from the brain's memory packet, not from transport shells.

6. Sleep/replay consolidation.
   Add bounded offline replay that promotes stable motifs and weakens stale/noisy candidates, analogous to sleep consolidation while preserving auditability.

## Boundary

This does not claim real emotion, consciousness, or human subjective experience. It is an engineering substrate for simulating continuous affective-semantic memory dynamics while preserving Holo's current architecture:

- WSL remains the authoritative brain.
- Windows, mobile, and WeChat remain transports.
- Reset stays WSL-only.
- The doctor is read-only and does not mutate memory.
