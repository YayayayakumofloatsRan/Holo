# Stage125 RAG Scope And Thread Canonicalization

Stage125 fixes two RAG failure modes found during live diagnosis after
Stage124:

1. Vector recall could be available and ready while returning no hits, because
   search was scoped only to the exact current thread/chat.
2. Some consciousness streams stored WeChat thread keys as bare contact names,
   while archive/callback rows used canonical `wechat:*` keys.

## Root Cause

The live `vector-health` command showed the vector backend is ready. The
problem was not Milvus availability.

`trace-hybrid-recall` showed:

```text
memory_route=hybrid
graph_hits>0
vector_hits=0
```

For a new CLI test thread, vector search only used the current exact scope. That
is too narrow for autobiographical and cross-channel recall, where the query
often needs old Holo memories from other threads or media.

`memory-doctor` also reported one thread fragmentation candidate:

```text
canonical_key=wechat:TestUser
raw_thread_keys=wechat:TestUser,TestUser
```

Archive and callback rows were canonicalized, but thought and initiative rows
were not.

## Runtime Contract

Vector search now tries scopes in order:

1. exact channel/thread/chat scope
2. channel scope
3. global scope

The result includes `scope` so diagnostics can tell whether recall came from an
exact thread, same channel, or the whole subject memory fabric.

Thought and initiative rows now canonicalize WeChat thread keys through the
same `_canonical_archive_thread_key()` path used by archive/callback memory.

## Why This Matters

Holo is one subject across CLI, app, and WeChat. A new channel thread must not
lose access to older autobiographical memory just because the immediate
transport thread is new. Exact thread evidence still wins first, but broader
semantic recall can now contribute when exact scope is cold.

## Verification

```powershell
python -m pytest -q tests\test_vector_memory.py tests\test_rag_memory.py tests\test_memory_fabric.py --basetemp=.pytest_tmp_stage125_rag
```

Result:

```text
44 passed in 9.88s
```
