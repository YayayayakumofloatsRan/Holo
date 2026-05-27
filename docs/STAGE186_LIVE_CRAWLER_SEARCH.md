# Stage186 Live Crawler Search

Stage186 gives Holo a bounded, inspectable web-crawler loop for search-heavy work.

The live CLI failures after Stage185 showed that recognizing search intent is not enough. Holo must show what it searched, what it opened, how the page evidence was scored, and why it stopped. Stage186 adds that missing query/open/evaluate controller.

## Schema

```text
holo.stage186.live_crawler_search.v1
holo.stage186.crawler_ledger.v1
```

## Loop

```text
query_plan -> web_search -> open_page -> page_evidence -> evaluate -> retry_or_stop
```

The controller records:

```text
query_plan
web_observation_ledger
page_observation_ledger
crawler_ledger
source_urls
status
stop_reason
final_summary
```

If network is disabled, Stage186 records `rejected_network_disabled` and returns a boundary stop instead of pretending to have current evidence. If search fails, the final summary reports the attempted failure and does not use future-intent wording such as "I will search."

## CLI

```powershell
python -m holo_host run-live-crawler-search --output artifacts\stage186\stage186_live_crawler_search.html --dry-run
```

The command writes:

```text
.html
.json
.jsonl
```

Dry-run uses deterministic local providers. Without `--dry-run`, the controller uses the existing host web providers and can be disabled with `--network-disabled`.

## Trace

The rendered trace uses command-line friendly public events:

```text
[crawl:query]
[crawl:search]
[crawl:open]
[crawl:evaluate]
[crawl:stop]
[final]
```

No hidden reasoning, provider `reasoning_content`, or private message payload is exposed.

## Boundaries

Stage186 does not add memory writes, WeChat startup, transport widening, unbounded loops, approval UI, or hidden chain-of-thought exposure. It is a bounded host-side crawler/search action loop over existing web observation surfaces.
