# Stage40 Eval Fixture: Cache Reuse

Goal: show that repeated context packages can reuse a stable cache key.

Expected evidence:
- same inputs produce the same `cache_key`
- bundle records `token_estimate`
- provider-response caching remains inside processor fabric
