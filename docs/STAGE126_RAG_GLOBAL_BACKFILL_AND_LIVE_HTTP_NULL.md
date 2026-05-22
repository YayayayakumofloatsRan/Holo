# Stage126 RAG Global Backfill And Live HTTP Null

Stage126 fixes a maintenance-path RAG bug exposed immediately after Stage125:
global vector backfill through the live reply API could return
`reason=no_documents` even while the Mind Graph already had materialized nodes.

## Root Cause

The CLI sent optional fields as JSON `null`:

```json
{"channel": null, "thread_key": null, "chat_name": null}
```

The live HTTP handler converted those values with `str(...)`, turning JSON null
into the literal string `"None"`. That changed an unscoped global backfill into
a scoped query for `channel="None"`, which necessarily exported no graph
documents.

## Runtime Contract

Unscoped vector backfill means global maintenance:

1. no channel filter
2. no thread filter
3. export every non-contact, non-thread Mind Graph memory node
4. upsert those documents into vector memory

The CLI now omits absent optional fields from the live HTTP payload. The reply
API also treats JSON null as missing instead of converting it to a string, so
third-party or mobile callers cannot reintroduce the same filter bug.

## Verification

Regression tests cover both layers:

```powershell
python -m pytest -q tests\test_reply_api_auth.py::test_reply_api_backfill_vector_memory_keeps_json_null_unscoped tests\test_memory_fabric.py::MemoryFabricTests::test_backfill_vector_memory_without_scope_exports_all_graph_docs --basetemp=.pytest_tmp_stage125_backfill_scope
```

Result:

```text
2 passed in 1.30s
```

Full repository verification:

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage126_rag_2
```

Result:

```text
424 passed in 62.35s
```

Live WSL verification after deployment:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host backfill-vector-memory"
wsl.exe -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host vector-health"
wsl.exe -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host trace-hybrid-recall --query 'Holo RAG memory stage124 fast packet single brain global vector backfill' --thread-key 'holo_cli:stage126-live-vector' --chat-name 'Stage126LiveVector' --channel holo_cli --limit 8"
```

Observed result:

```text
backfill-vector-memory: status=ok document_count=1123 ready=true
vector-health: available=true ready=true
trace-hybrid-recall: memory_route=hybrid, vector_hits non-empty, top trace source=hybrid with vector_match
```
