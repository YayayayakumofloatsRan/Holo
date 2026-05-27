# Stage185 CLI Introspection And Search Intent

Stage185 fixes live CLI failures found in manual testing after Stage184.

The failure modes were:

```text
current stage was not visible in the CLI trace
new turns could render [stop] unknown
Chinese search/crawler intent such as 检索 did not reliably select web_search
non-eager network turns did not show a planned web_search tool request
the trace showed tool facts but not a command-line friendly public internal flow
```

## What Changed

Stage185 adds public, auditable introspection to the existing Stage153 event stream:

```text
[state] milestone=...
[think] intent: ...
[think] evidence: ...
[think] action: ...
[think] stop_check: ...
```

These lines are not hidden chain-of-thought. They are deterministic summaries derived from public metadata: tool candidates, selected actions, observation counts, grounding status, and current milestone from `HOLO_HANDOFF.md`.

Stage185 also hardens Chinese intent handling for search/current-source work:

```text
联网 / 外网 / 上网 / 检索 / 搜索 / 查一下 / 爬虫 / 抓取 / 最新 / 官方 / 官网 / 文档 / 论文 / 财报 / 年报
```

This makes a turn such as:

```text
你应该可以自己检索，挑一个金融方向，先想一想，然后去做
```

select `web_search` instead of silently falling through to `answer_direct`.

## Stop Reason

New CLI turns must not display:

```text
[stop] unknown
```

If imported legacy metadata says `unknown`, Stage185 renders a safe public stop reason such as `final_answer_ready` unless a more specific live surface provides a better reason.

## Boundaries

Stage185 does not expose raw provider reasoning, `reasoning_content`, or private chain-of-thought. It does not add provider calls, memory writes, WeChat startup, transport widening, or live-network test requirements.

## Acceptance

Stage185 is accepted when:

- current milestone appears in CLI trace;
- direct and FSM turns do not render unknown stop;
- Chinese search/crawler terms select `web_search`;
- non-eager search turns still record a planned `web_search` tool request;
- CLI trace includes multiple public `[think]` steps;
- hidden reasoning remains private.
