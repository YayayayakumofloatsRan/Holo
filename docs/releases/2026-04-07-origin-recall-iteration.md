# Prerelease Note

## Title
Mind graph recall now prefers earliest substantive thread anchors

## What Changed
- origin/deep recall now keeps one lightweight opening context when useful, but prioritizes the earliest substantive WeChat thread events over low-signal greetings or emoji-only rows
- origin dialogue windows are rebuilt from those substantive anchors, so recall prompts carry earlier preferences and corrections like "简短一点" and "开头过于公式化了"
- graph-led origin queries now stay focused on the active thread instead of drifting across broader recent memory
- publish hygiene was tightened so runtime memory JSONL, live configs, Codex local state, and temp smoke artifacts are excluded from public repo snapshots

## Why
- Holo could reach early history, but the retrieval path still over-weighted low-signal opening events and later meta-memory questions
- public publishing needed a safe default that does not leak runtime memory or private live configs

## Validation
- `python -m unittest tests.test_mind_graph tests.test_holo_host.ReplyServiceTests.test_refresh_wechat_history_origin_query_uses_deeper_budget tests.test_holo_host.ReplyServiceTests.test_reply_probe_compares_graph_led_and_legacy_drafts`
- live WSL `trace-recall` and `reply-probe` on the active WeChat thread for `最开始的时候，你还记得什么`
