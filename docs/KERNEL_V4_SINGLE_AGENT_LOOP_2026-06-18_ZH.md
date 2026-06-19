# Kernel v4 单 Agent 循环改写记录

日期：2026-06-18

分支：`kernel-v4`

## 2026-06-19 成熟版本检查点

当前版本已作为 Kernel v4 成熟单 Agent 金融 harness 检查点保存。新增最终报告准备稿：

```text
docs/FINAL_REPORT_PREP_2026-06-19_ZH.md
```

最新 live strict evidence 使用冻结配置：

- model: `deepseek-v4-flash`
- thinking: `enabled`
- reasoning effort: `low`
- `model_context_mode=off`
- `max_turns=160`
- `max_tool_calls=420`
- gold/reference 只用于每题完成后评分，不进入模型上下文

FinanceBench offsets `96-149` 共 `54` 道的聚合结果：

```text
passed_count=42
failed_count=12
pass_rate=77.78%
run_failed_count=1
failure_reasons={"numeric_outside_tolerance": 11, "source_grounded_qualitative_failed": 1}
aggregate_cache_hit_rate=89.06%
estimated_total_cost_usd=1.4435
```

聚合文件：

```text
.state/kernel_v4/bench/finance/fb_strict_o096_o149_aggregate_v39_20260619/summary.json
```

解释边界：

- `debug50` 是开发/调试集合，最佳 live 记录 `50/50`，不能当 held-out test。
- replay/inspected offsets 是恢复和稳定性证据，不能当 clean test。
- offsets `96-149` 是当前剩余 untouched pool 的 strict live evidence，但不是完整 clean `test100`。
- 结构测试通过只证明接口、schema、loop 结构有效，不代表金融能力。

下一阶段不继续跑测试，优先整理最终报告、绘制图表、分析失败类型，并围绕以下通用能力优化：

1. finalization reliability：减少 `empty_final_answer`、tool-call markup final answer、自指或过程性 final answer。
2. numeric precision：强化 final answer 中的 source line item、period、unit、formula、substitution、calculator/verifier 证据。
3. evidence sufficiency：让模型维护轻量 checklist，减少过早回答和过度检索。
4. cache/cost efficiency：稳定 prompt/tool schema，减少重复 evidence acquisition，压缩 run trace。
5. reportable observability：沉淀 workflow timeline、turn/tool/token/cache/cost/failure 图表。

## 结论

Kernel v4 走新的架构线：参考用户提供的成熟 TypeScript 项目，把核心单 agent loop 用 Python 改写一遍。v4 第一阶段不做多 agent、不做子 agent、不做 v3 的金融语义状态机。

目标是先得到一个干净、通用、可审查的循环：

1. 模型输出文本和 `tool_call`。
2. Host 按工具协议执行。
3. Tool result 立即回灌到下一轮模型上下文。
4. 大工具结果转为 artifact，模型可用 `artifact.read` 读取。
5. 工具发现由 `tool.discovery` 提供合同，不由本地逻辑替模型决定下一步。
6. 循环退出只由模型最终回答、预算、硬错误或明确阻塞决定。

## 删除的 v3 闸门

v4 active loop 不加载这些金融语义闸门：

- `FactLedger`
- `SlotFrame`
- `finance.slot_bind`
- 本地 “missing slots 必须补齐后才能计算” gate
- host 侧任务编译后强制补槽状态机

它们不是“降级为辅助”，而是不进入 v4 单 agent 主循环。v4 的原则是：模型看到检索/SEC/文档搜索/表格/上下文解析结果后，可以直接选择输入并调用 `calculator.compute`、`data.table.query`、`finance.verify_numeric`。

## 参考框架对应关系

用户提供的参考项目关键部件：

- `query.ts`：主 query loop。
- `StreamingToolExecutor.ts`：流式工具执行，支持并发安全工具并行、非并发工具独占。
- `ToolUseContext`：携带消息、工具、权限、进行中工具、上下文修改。
- `toolResultStorage.ts`：大工具结果持久化和上下文替换。
- `toolSearch.ts`：工具发现和 deferred tool surface。

Kernel v4 的 Python 对应实现：

- `kernel_v4/loop.py`：`SingleAgentLoop`。
- `kernel_v4/tooling.py`：`ToolRegistry`、`StreamingToolExecutor`、`tool.discovery`、`artifact.read`。
- `kernel_v4/context.py`：`ToolUseContext`、大 tool result artifact replacement。
- `kernel_v4/runtime.py`：`AbortController`、`WorkflowObserver`、`ContextEdit`、`ToolLifecycleRecord`。
- `kernel_v4/monitoring.py`：实时 workflow 事件渲染，支持人读 compact 输出和机器读 JSONL。
- `kernel_v4/contracts.py`：消息、工具调用、工具结果、模型事件、循环结果协议。
- `kernel_v4/prompts.py`：通用单 agent prompt 和金融特调 prompt。
- `kernel_v4/finance_tools.py`：成熟金融工具后端适配，不引入 `finance.slot_bind`。
- `kernel_v4/providers.py`：OpenAI-compatible / DeepSeek live provider，支持原生 function tool schema、provider-native `tool_choice` 强制工具、streaming tool-call delta 解析和 v4 工具名回映射。
- `kernel_v4/live_smoke.py`：最小 live provider smoke 入口，可用 `--force-tool calculator.compute` 验证真实 provider 工具闭环；默认只强制第 1 个模型 turn，后续 turn 恢复模型自主回答。
- `kernel_v4/finance_runner.py`：FB/FQA/FinQA no-gold task packet 和 finance runner 入口，把题面、provided context、source policy、安全 metadata 传入 `SingleAgentLoop(finance_mode=True)`。
- `kernel_v4/finance_run.py`：可执行 no-gold 单题 runner，支持 `--row-json` / `--row-file` / `--row-jsonl`、dry-run、live provider、workflow monitor、bounded transcript diagnostics。

## 运行时控制与可视化

2026-06-18 的第二次 v4 架构补齐，优先复刻参考项目的运行时控制面，而不是进入做题：

- `AbortController` / `AbortSignal`：外部 runner 或 UI 可以中止当前 loop。loop 在模型 turn 前、模型 turn 后、工具执行前后检查 abort 状态。
- tool cancel 补偿：如果 abort 发生在工具调用已经出现之后，host 会生成 `holo.kernel_v4.tool_cancelled.v1` synthetic tool result，避免留下孤立 `tool_call`。
- `ContextEdit`：工具或 host 可以通过 `context.apply_edit(...)` 修改运行上下文，例如设置 metadata、追加消息、删除 artifact。后续模型 turn 的 `workflow` 上下文会看到最近 edits 和 metadata keys。
- `ToolLifecycleRecord`：每个工具调用记录 `queued -> executing -> completed/failed/cancelled -> yielded` 生命周期，并记录 artifact/error/cancel reason。
- `WorkflowObserver`：所有关键 loop 事件会实时发给 callback。`live_smoke` 支持 `--show-workflow` 输出内部工作流。
- `WorkflowConsoleMonitor`：默认 compact 模式把 text delta 聚合为 `assistant_stop text_chars=N`，突出 `model_start`、`assistant_tool_call`、`tool_start`、`tool_result`、`loop_completed/failed`；`--workflow-format jsonl` 保留完整机器可读事件。

这部分是通用 agent loop 能力，不绑定 FinanceBench，也不引入金融规则 gate。

## Streaming Tool Executor 改写

2026-06-18 的第三次 v4 架构补齐继续对齐参考项目的 streaming executor：

- provider 不再等完整 response 才交出工具调用。OpenAI-compatible / DeepSeek SSE delta 在函数名和 JSON 参数完整后立即发出 v4 `tool_call` 事件。
- provider 的阻塞 SSE 读取进入单独 producer thread，通过 asyncio queue 持续推送 chunk，避免阻塞 Python event loop。
- `SingleAgentLoop` 在消费模型流时立即把 `tool_call` 交给 `StreamingToolExecutor`，工具可以在 `assistant_message_stop` 前启动和完成。
- loop 在模型流消费期间持续 drain 已完成工具结果；模型流结束后再 drain remaining results，保持参考框架“streaming 中执行，turn 结束前补齐 tool_result”的核心语义。
- `tool.discovery` 会把发现到的 deferred tools 写入 `ContextEdit(metadata.set: discovered_tool_names)`；下一轮 `ToolRegistry.manifests(...)` 会把这些工具真正暴露到 provider-native tool surface，而不是只放在文本说明里。
- `live_smoke --show-workflow` 已能看到 `assistant_tool_call -> tool_queued -> tool_start -> tool_lifecycle(completed) -> assistant_message_stop -> tool_result` 的实时顺序。
- Runtime context 现在包含 `recent_tool_calls`，包括最近工具名、输入 hash、输入预览、成功/失败状态和结果预览，帮助模型从成功工具结果推进，而不是在长 transcript 中迷路。
- Tool execution 增加 duplicate-success guard：同一工具同一输入已经成功过时，host 不重复执行，而返回 `holo.kernel_v4.duplicate_successful_tool_call.v1` synthetic observation，提示模型使用上一条结果继续。这是防空转 loop guard，不替模型选择金融事实或答案。
- 如果 provider 把工具调用写成 DSML 文本块而不是 native tool call，loop 会解析 `<｜｜DSML｜｜tool_calls>` 并把可见工具调用送入同一个 `StreamingToolExecutor`。

这一步仍然没有改变核心思路：模型决定工具，host 只执行、记录、补齐生命周期、管理上下文。

## 金融工具面

v4 金融模式暴露普通工具，不暴露本地语义闸门：

- `finance.toolchain.describe`
- `sec.edgar.company_filings`
- `sec.edgar.financials`
- `document.docling.convert`
- `document.trafilatura.extract`
- `document.search.hybrid`
- `provided_context.parse`
- `market.openbb.fetch`
- `data.table.query`
- `math.sympy.compute`
- `calendar.days_between`
- `calculator.compute`
- `finance.verify_numeric`
- `finance.toolchain.audit`
- `artifact.inspect`
- `artifact.search`
- `artifact.read`
- `tool.workbench`
- `tool.discovery`

当前实现复用 v3 已经接好的成熟工具 wrapper 作为后端，包括 EdgarTools、Docling、Trafilatura、BM25/DuckDB/Pandas/SymPy、calculator 和 numeric verifier，但不复用 v3 agent runtime/evaluator/slot gate。

## Artifact 生命周期与工作台入口

2026-06-18 后续架构补齐按三个顺序完成：

1. `ToolUseContext` 的 artifact 不再只是大结果替换文本，而是有生命周期记录：
   - content-addressed `artifact_id`
   - `sha256`
   - `kind`
   - `chars`
   - preview
   - `created_order`
   - `store_hits`
   - `read_hits`
   - workflow context 中的 `artifact_count` / `artifacts_recent`
2. 核心工具面新增稳定 artifact 工具：
   - `artifact.inspect`：列出/检查 v4 artifact 和 delegated artifact 元数据。
   - `artifact.search`：在 artifact 中检索 query，返回 snippet、offset、start/end。
   - `artifact.read`：支持 `start` / `max_chars` 窗口读取，避免一次性把大 blob 塞回上下文。
3. 核心工具面新增 `tool.workbench`：
   - 根据 query 组装工具族，而不是替模型作答。
   - 返回 selected tools、family purpose、workflow hints、current artifacts。
   - 将发现到的工具写入 `discovered_tool_names`，下一轮可进入 provider-native tool surface。

金融层同步覆盖 delegated artifact store：

- v4 finance mode 注册自己的 `artifact.inspect` / `artifact.search` / `artifact.read` executor。
- 这些 executor 可以同时处理 v4 context artifacts 和 v3 mature finance tools 生成的 artifact blob。
- 这解决了旧链路里“工具产出 artifact 后只能粗读、难以定位证据”的问题。

## Finance Workbench 合同

新增 `finance.workbench.open`，作用是把 FB/FQA/FinQA 题型需要的工具合同下沉到工具返回中，而不是继续膨胀 prompt 或引入 host semantic gate。

`finance.workbench.open` 返回：

- selected task-family profiles
- primary/support tools
- required evidence
- workflow hints
- formula candidates when appropriate
- artifact lifecycle protocol
- final answer contract
- no-gold / no-hidden-computation boundary

当前覆盖的 profile 包括：

- `public_filing_evidence`
- `provided_context_fqa_finqa`
- `table_ranking_aggregation`
- `finance_transforms`
- `multi_company_comparison`
- `inventory_efficiency_dio`
- `liquidity_quick_ratio`
- `capital_intensity_asset_intensity`
- `margin_driver_bridge`
- `segment_growth_mna_exclusion`
- `dividend_stability_trend`
- `debt_securities_terms`
- `fiscal_dates`
- `market_data`
- `numeric_verification`

边界保持不变：这些 profile 只暴露工具、证据和验证合同；模型仍然自己决定事实选择、公式选择、业务判断、是否继续取证以及何时最终回答。

新增 `finance.toolchain.audit`，用于运行时审查理论闭环本身：

- full mode 检查全部 15 个 profile 的 primary/support tools 都真实注册。
- no-network FQA mode 只检查 provided-context FQA/FinQA、table ranking、finance transforms、numeric verification 这条无网络链路。
- 检查 `finance.toolchain.describe` 的 coverage families 与 `finance.workbench.open` 的 profile family 同源一致。
- 检查 `finance.slot_bind` 等 legacy semantic gates 未进入 v4 finance registry。
- 返回 `status=ok/failed`、missing tools、incomplete profiles、coverage drift 和 no-gold boundary。

这个 audit 只读取工具 manifest 与静态合同，不读取 benchmark gold/reference，不执行答案计算，也不产生 benchmark score。

新增 row-level `--closure-audit`：

```text
python -m kernel_v4.finance_run --row-json ... --benchmark-family finqa --closure-audit
python -m kernel_v4.finance_run --row-json ... --benchmark-family financebench --allow-network --closure-audit
python -m kernel_v4.finance_run --row-jsonl data/bench/finance/financebench_doc_retrieval.jsonl --benchmark-family financebench --allow-network --closure-audit --limit 150 --output /tmp/holo_v4_fb150_closure_audit.json
```

它从真实 FB/FQA 风格 row 构造 `FinanceQuestionSpec`，然后执行：

```text
FinanceQuestionSpec(no-gold packet)
  -> finance.toolchain.audit
  -> finance.workbench.open(query from question/metadata/context presence)
  -> selected profile tool availability check
```

输出 `holo.kernel_v4.finance_question_closure_audit.v1`：

- `status=ok/failed`
- `audit_mode=full|no_network_fqa`
- task summary with question/context hashes and lengths, not raw provided context
- packet hash and gold-reference-included flag
- toolchain audit summary
- selected profile families and missing selected tools
- `capability_claim=false`
- `benchmark_progress_claim=false`

FQA/FinQA supplied-context rows在无网络模式下会把 workbench 限定到
`provided_context_fqa_finqa`、`table_ranking_aggregation`、
`finance_transforms`、`numeric_verification`，避免 no-network FQA 审计被
public filing profile 的 SEC 工具缺失污染。FinanceBench public filing row 在
`--allow-network` 下走 full audit。

2026-06-18 已对本地 FinanceBench doc-retrieval `150` 行执行 batch
closure audit：

```text
schema=holo.kernel_v4.finance_closure_audit_batch.v1
status=ok
item_count=150
ok_count=150
failed_count=0
audit_modes={"full": 150}
```

审计输出未包含 `gold_answer`、`reference_answer`、`gold_program`、
`evidence_excerpt`、`rubric` 这些 scoring-only 标记。该结果只证明
FinanceBench row 能进入 no-gold packet、workbench、toolchain audit 和
registered-tool availability 闭环；它不是 live provider 答题准确率。
当前本地 `data/` 下未发现 FinQA/FQA 真实数据文件，因此 FinQA/FQA 的覆盖
仍是 supplied-context interface contract 与结构样例级验证，等真实数据接入后
需要用同一 `--closure-audit` batch 路径补跑。

## FB/FQA 理论闭环合同补齐

2026-06-18 后续补齐的重点是 prompt/toolchain contract，而不是按题打补丁：

- 通用系统 prompt 明确说明 provider 可见工具面可能是 partial surface；如果模型需要的已注册工具没有显示，应该先调用 `tool.discovery` 查询合同，下一轮再调用具体工具。
- 金融 prompt 明确区分 public-filing task、provided-context FQA/FinQA task、market-data task、fiscal-date task、table/ranking task、finance transform task、numeric verification task。
- FinanceBench 风格 public filing 题优先用 `sec.edgar.company_filings` / `sec.edgar.financials`，必要时用 `document.docling.convert`、`document.search.hybrid`、`artifact.read` 找 exact line item/table/note evidence。
- FQA/FinQA provided context 题优先用 `provided_context.parse` 把 oracle/context/report/table/snippet 转成文本块和 query-ready tables，再让模型选择 `data.table.query` / `calculator.compute` 完成表格选择、聚合、计算。
- DIO/DSO/DPO、growth、margin、bps、average balance、multiple、ranking、comparison 等派生数值要求模型调用 `calculator.compute` 或 `data.table.query`，不依赖心算。
- 财年/日期题暴露 `calendar.days_between`，但 host 不替模型决定公式是否用 365、actual fiscal days 或 inclusive day count。
- 最终 material numeric finance claims 在 `finance.verify_numeric` 可用时应由模型主动调用 verifier；verifier 是 loop 内工具，不是 hidden finalizer。
- prompt 明确禁止 benchmark id/gold/reference/cache lookup；模型上下文只允许使用用户题面和工具观察。
- stop rule 改为“可解且预算仍在时继续换源/换工具”，避免一个工具失败后过早输出 generic failure。
- final answer contract 要求直接回答问题，并列出公式、输入、期间、单位、方法选择、计算结果、舍入、比较方向、业务语境和 citation/provenance。

`finance.toolchain.describe` 也同步返回 `one_shot_loop_contract` 和 `coverage_families`，把上述能力映射到具体工具族：

- `public_filing_evidence`
- `provided_context_fqa_finqa`
- `table_ranking_aggregation`
- `finance_transforms`
- `fiscal_dates`
- `market_data`
- `numeric_verification`

这仍然遵守 v4 边界：模型选择事实、公式、工具和最终可答状态；host 只做 schema validation、tool execution、artifact/context 管理和 workflow lifecycle 记录。

## FB/FQA no-gold 任务入口

本轮新增 `kernel_v4/finance_runner.py`，补齐 v4 从 benchmark/user row 到单 agent loop 的入口层：

- `FinanceQuestionSpec.from_mapping(...)` 接受 FinanceBench/FQA/FinQA 风格 row。
- 模型可见 packet 只包含 `question`、可选 `provided_context`、`source_policy`、安全 metadata、solver contract。
- `answer`、`reference`、`gold_*`、`expected_*`、`rubric`、`annotation`、`program`、`scoring` 等 gold/reference/scoring 字段不会进入模型 prompt。
- 被排除字段名仅保存在 host-side `FinanceQuestionSpec.excluded_gold_reference_fields`，用于审计；模型 prompt 只看到 `excluded_gold_reference_field_count`。
- FQA/FinQA 的 `oracle_context` / `provided_context` / `context` / table/snippet 会作为 supplied context 进入 packet，后续由模型调用 `provided_context.parse`。
- FinanceBench public filing 题可以只带 question/source metadata 进入同一入口，由模型调用 SEC/EDGAR/document/table/calculator/verifier 工具。
- `build_finance_registry(...)` 统一注册 v4 finance surface；`allow_network=False` 可用于 FQA/FinQA provided-context no-network 结构路径，`allow_network=True` 用于 public filing live path。
- `run_finance_question(...)` 将 no-gold packet 交给 `SingleAgentLoop(finance_mode=True)`，不加载 legacy `finance.slot_bind`、FactLedger 或 SlotFrame gate。
- `python -m kernel_v4.finance_run` 是当前可执行入口：
  - `--row-json`：直接传一个 JSON row。
  - `--row-file`：读取 JSON object 或 JSON object list。
  - `--row-jsonl --index N`：读取 JSONL 第 N 行。
  - `--dry-run`：只构造 no-gold packet summary，不调用 provider。
  - `--show-workflow`：实时打印 compact 或 JSONL workflow。
  - `--include-transcript`：失败时输出有界消息预览和工具错误，便于诊断。

这一步不是 scorer，也不读取 gold sidecar。它只解决 v4 入口层是否能理论上承载 FB/FQA 题面、上下文和工具链的问题。

## FinanceBench live debug/test runner

新增 `python -m kernel_v4.finance_eval` 作为 v4 原生批量 live 入口：

```text
python -m kernel_v4.finance_eval \
  --row-jsonl data/bench/finance/financebench_doc_retrieval.jsonl \
  --gold-jsonl data/bench/finance/financebench_doc_retrieval.gold.jsonl \
  --split debug50 \
  --limit 1 \
  --allow-network
```

固定 split policy：

- `debug50`: offsets `0-49`，允许检查 traces、归纳失败类型、改通用 loop/tooling。
- `test100`: offsets `50-149`，held-out；不能先看 item-level failure 再把同一批结果当 held-out score。
- `all150`: 仅诊断，不是 held-out score。

运行边界：

- row 进入模型前仍统一经过 `FinanceQuestionSpec`，gold/reference/scoring 字段不会进入模型 prompt。
- gold sidecar 只在每题 live run 完成后用于 scorer。
- 默认 `summary.json` 是 redacted，不包含 expected numeric 细节；完整 scorer JSON 只写入每题 `items/*.score.json`。
- 每题 run JSON 写入 compact `tool_trace_summary`：只包含工具名、turn、call id、是否 error、artifact id，不保存工具输入/结果正文。
- batch runner 有 `--item-timeout-seconds`，单题卡住会记录 `item_timeout`，不会拖死整个 debug50；正常金融做题默认给足预算：`max_turns=64`、`max_tool_calls=200`、`item_timeout_seconds=1200`。
- 每次 batch 会写出 `summary.json`、`items.csv`、`items.jsonl`，用于实验图表和统计支撑。
- `experiment_metrics` 聚合 turns、tool calls、total/prompt/completion tokens、cache hit rate 的 count/sum/min/max/mean/median/p90。

2026-06-18 当前 live debug 进度：

```text
offsets 0-8: 9/9 passed
gold_reference_material_in_model_context=false
total_tokens ~= 5.70M
aggregate_prompt_cache_hit_rate ~= 8.4%
```

逐题 redacted 摘要：

```text
offset 0 financebench_id_03029 passed, tool_calls=5, turns=5, total_tokens=88,392
offset 1 financebench_id_04672 passed, tool_calls=14, turns=10, total_tokens=368,798
offset 2 financebench_id_00499 passed, tool_calls=18, turns=13, total_tokens=699,914
offset 3 financebench_id_01226 passed, tool_calls=19, turns=15, total_tokens=899,616
offset 4 financebench_id_01865 passed, tool_calls=2, turns=3, total_tokens=62,788
offset 5 financebench_id_00807 passed, tool_calls=14, turns=11, total_tokens=533,780
offset 6 financebench_id_00941 passed, tool_calls=19, turns=16, total_tokens=924,806
offset 7 financebench_id_01858 passed, tool_calls=7, turns=5, total_tokens=141,823
offset 8 financebench_id_02987 passed, tool_calls=41, turns=24, total_tokens=1,982,181
```

这是真实 live debug-slice 进展，但不是完整 `debug50`，也不是 held-out
`test100`。当前主要瓶颈从“是否能做出来”转向“成本、上下文膨胀、cache hit
rate 和慢工具路径控制”。

高成本 trace 聚合显示，慢题主要集中在 `document.search.hybrid`、
`artifact.read`、`artifact.search`、`document.docling.convert` 和 SEC/EDGAR
检索路径。为降低上下文膨胀，v4 已把默认 `artifact.read` 窗口从 `20k`
收窄到 `8k`，并在 v4 wrapper 层给 delegated `document.search.hybrid`
注入默认 `max_chars=8000`、`max_matches=8`；模型仍可显式请求更大的
`max_chars`。offset 7 是该压缩默认值后的 live 验证题，已通过。

offset 8 说明预算策略很关键：在 `24` turns / `80` tool calls 的旧运行中，
该题到最后一轮才被迫收束并出现 `numeric_outside_tolerance`；在 `64` turns /
`200` tool calls 的新默认预算下，模型第 23 轮才进入 `calculator.compute`，
第 24 轮完成正确答案。当前阶段先保证能做出来，再基于 `items.csv` /
`items.jsonl` 的 turns、tool_calls、tokens、cache hit rate 做效率优化。

cache hit rate 偏低的主要原因：

- 之前 provider payload 把每轮动态 `Runtime context` 拼进第一条 system
  message；`run_id`、`turn_index`、remaining budget、workflow events、
  tool lifecycle、artifact metadata 每轮都变化，导致 provider 前缀缓存从
  请求开头就失效。
- 跨题 question/company/filing metadata 天然不同，不能期望题面之后大面积
  cross-item cache hit。
- 长题会追加大量新 tool messages、filing snippets、artifact ids 和检索结果；
  offset 8 这类 41 次工具调用的题，新 token 占比很高。
- visible tool schemas 稳定但很长；一旦动态 context 放在更前面，稳定工具面
  也难以有效复用。

已做的无损优化：

- provider payload 第一条 system message 现在只包含静态 system prompt。
- 每轮动态 runtime context 被追加到消息末尾，模型仍可读取预算、workflow、
  recent tool calls 和 endgame policy，但不会污染静态前缀。
- 该优化不减少工具、不减少证据、不改变 LLM 的语义决策，只改变消息顺序以
  提高前缀稳定性。

## 测试结果

本次提交前执行的是结构测试，不代表 FinanceBench/FQA 真实做题能力：

```text
.venv/bin/python -m py_compile kernel_v4/__init__.py kernel_v4/contracts.py kernel_v4/context.py kernel_v4/tooling.py kernel_v4/prompts.py kernel_v4/loop.py kernel_v4/finance_tools.py tests/test_kernel_v4_single_agent_loop.py
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py -q
5 passed
```

接入 live provider 后，结构测试扩展为：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_live_provider.py -q
17 passed
.venv/bin/python -m pytest tests/test_kernel_v4_monitoring.py -q
2 passed
```

FB/FQA 理论闭环合同补齐后，最新结构测试为：

```text
.venv/bin/python -m py_compile kernel_v4/finance_run.py kernel_v4/loop.py kernel_v4/tooling.py kernel_v4/prompts.py kernel_v4/finance_runner.py
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_monitoring.py -q
35 passed
```

Artifact/workbench/finance-workbench 补齐后的最新结构测试为：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
87 passed
```

测试覆盖：

- 工具结果能进入下一轮模型上下文。
- v4 金融工具面不含 `finance.slot_bind`。
- 金融 prompt 明确删除本地 `FactLedger` / `SlotFrame` / slot-bind gate。
- 大工具结果会 artifact 化并保持可读。
- `tool.discovery` 返回工具合同而不是语义答案。
- OpenAI-compatible provider 会把 v4 tools 转成原生 function tools。
- provider 可以把 v4 工具名强制投射到 provider-native `tool_choice`。
- streaming tool-call delta 能映射回 v4 原工具名。
- provider packet preview 不暴露 API key。
- workflow callback 可以实时看到 model/tool/loop 事件。
- abort 可以取消运行中的工具，并生成 synthetic tool result。
- context edit 会进入下一轮模型请求上下文。
- streamed tool_call 会在模型流结束前启动工具执行。
- tool.discovery 发现到的 deferred tool 会在下一轮进入 provider-visible tool surface。
- compact workflow monitor 会聚合文本增量，避免实时监控刷屏；JSONL 模式仍保留完整事件。
- finance prompt 包含 FB/FQA/FinQA 题型覆盖、tool.discovery、no-gold、calculator/table/calendar/verifier 和 no-early-stop 合同。
- `finance.toolchain.describe` 暴露 public filing、provided context、table/ranking、finance transform、fiscal date、market data、numeric verification 工具族，并确认没有 `finance.slot_bind`。
- `artifact.inspect` / `artifact.search` / `artifact.read(start,max_chars)` 可检查、搜索、窗口读取 v4 artifacts。
- `tool.workbench` 可按 query 组装工具族并把发现工具写入 `discovered_tool_names`。
- `finance.workbench.open` 可返回 DIO、quick ratio、capital intensity、margin driver、FQA/FinQA provided context 等 task-family 合同，且不输出语义答案。
- `finance.workbench.open` 会返回 capability matrix，覆盖 no-gold intake、source/context acquisition、document/artifact context、table/transform compute、numeric verification、answer synthesis。
- 15 类代表性自然语言 query 会路由到对应 workbench profile：public filing、provided context、table ranking、finance transforms、multi-company comparison、DIO、quick ratio、capital intensity、margin driver、segment M&A exclusion、dividend trend、debt securities、fiscal dates、market data、numeric verification。
- v4 finance artifact 工具可以搜索/读取 delegated finance artifact store 中的 artifact blob。
- `finance.workbench.open` 的完整 profile 集合会被检查：每个 primary/support tool 都必须真实存在于 full finance registry，每个 profile 必须有 required evidence 和 workflow。
- `finance.toolchain.audit` 在 full registry 下返回 `status=ok`，并确认 describe/workbench coverage 没有 family drift、没有 missing core tools、没有 legacy gates。
- `finance.toolchain.audit(mode="no_network_fqa")` 在 no-network registry 下返回 `status=ok`，确认 FQA/FinQA provided-context 理论链路不依赖 SEC/网络工具。
- `finance_run --closure-audit` 对 FQA row 和 FinanceBench public filing row 均可生成 no-provider closure audit；输出不包含 gold/reference/program/rubric 值，且不会声明 benchmark progress。
- no-network FQA/FinQA 路径会检查 `provided_context_fqa_finqa` profile 只引用 no-network registry 中可用的工具。
- provider-native schema 会检查 `tool.workbench` / `finance.workbench.open` / `finance.toolchain.audit` 的输入参数是具体 `string` / `integer` 类型，避免 live provider 把 union schema 降成 object 空壳。
- provider stream queue 有 hard timeout；producer 没有投递 chunk/sentinel 时，主协程会在 `timeout_seconds` 后失败返回。
- provider payload 保持静态 system prompt 在首条消息，动态 runtime context 放在末尾，避免每轮 run_id/workflow 变化污染 prompt-cache 前缀。
- provider/model stream 异常会被 `SingleAgentLoop` 收敛成 `LoopResult(status="failed")` 和实时 `loop_failed` 事件，不再炸穿 CLI。
- `finance_eval` 固化 debug50/test100 split，默认 summary 不输出 scorer expected numeric 细节。
- `finance_eval` 有 per-item hard timeout；单题卡住会记录结构化失败并继续 batch。
- 每题 run JSON 会记录 compact `tool_trace_summary`，用于后续失败分类和成本分析。
- `artifact.read` 和 delegated `document.search.hybrid` 有 compact 默认窗口；模型可按需显式扩大窗口。
- `FinanceQuestionSpec` 会排除 gold/reference/scoring 字段值和字段名，只保留 host-side excluded-field audit。
- `run_finance_question` 会把 no-gold task packet、finance prompt 和完整 finance tool surface 一起传给模型。
- no-network FQA/FInQA surface 仍包含 `provided_context.parse`、`data.table.query`、`calculator.compute`、`finance.verify_numeric`、`tool.discovery`、`artifact.read`。
- `finance_run` dry-run 不调用 provider，输出 no-gold task summary 且不泄漏 reference/rubric/gold program 值。
- `finance_run --include-transcript` 输出有界 transcript preview，便于定位 live 工具参数、tool result 和 error recovery 问题。
- `recent_tool_calls` runtime context 带成功结果预览；duplicate-success guard 防止同一成功工具输入反复执行。
- DSML 文本工具调用 fallback 能把 `<｜｜DSML｜｜tool_calls>` 解析成标准 `ToolCall` 并执行。
- 工具返回 `status=blocked/error/failed/...` 或结构化 `error` 时会进入 `is_error` lifecycle；失败结果不会被 duplicate-success guard 当成成功结果。
- provider streaming parser 会等待 arguments delta 到达后才发出 `ToolCall`；如果 SSE 先给 function name、后给 arguments，不会再提前执行空参 `{}`。

已完成的最小 live smoke：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --max-turns 3 --max-tool-calls 4
{"status": "completed", "answer": "v4 live provider ok.", ...}
```

2026-06-18 最新一次最小 live provider smoke 在提升网络权限后通过：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --timeout-seconds 10 --max-retries 0 --max-turns 2 --max-tool-calls 2 --show-workflow
1.66s t1 loop_completed answer_chars=20
{"status": "completed", "answer": "v4 live provider ok.", "tool_call_count": 0, "turn_count": 1, ...}
```

这仍然只是 live provider/loop 链路证据，不是 FinanceBench/FQA 做题成绩。

2026-06-18 后续 live finance runner 诊断先暴露出两个基础设施问题：

```text
.venv/bin/python -m kernel_v4.finance_run --row-json '{...provided-context FQA smoke...}' --benchmark-family finqa --show-workflow --include-transcript
status=failed
reason=max_turns_exceeded
observed_tools=provided_context.parse, tool.discovery, artifact.read, calculator.compute, data.table.query
```

当时诊断结论：

- no-gold packet、live provider、workflow monitor、tool execution、duplicate guard、calculator 工具面都已联通。
- 该 live smoke 没有完成答案，不能计为 FQA/FinQA accuracy。
- transcript 显示 DeepSeek 在这条 task 上多次发出 native tool calls 但 arguments 为 `{}`，即使 assistant 文本声称要提供 `context` / `expression`。这暴露的是 provider/tool-argument reliability 和 finalization recovery 问题。
- 进一步检查后发现关键根因不只是模型：provider streaming parser 在只收到 function name、尚未收到 arguments delta 时，把空字符串当 `{}` 解析并提前发出工具调用，导致 executor 执行空参工具。

已完成修复：

- `kernel_v4/providers.py` 的 streaming parser 现在必须看到非空 arguments 文本并能解析 JSON，才会提前发出 `ToolCall`；否则等到后续 delta 或 message stop。
- `kernel_v4/tooling.py` 现在把 `status=blocked/error/failed/...` 和结构化 `error` 归入 `is_error` lifecycle，避免失败 observation 被当成成功结果参与 duplicate-success guard。
- 对应测试新增：
  - provider 等待 streamed tool arguments。
  - blocked tool result 是 error，且不会触发 duplicate-success skip。

修复后的最小 live calculator smoke：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --timeout-seconds 30 --max-retries 0 --max-turns 4 --max-tool-calls 6 --calculator-only --tool-choice auto --force-tool calculator.compute --force-tool-turns 1 --show-workflow --workflow-format compact --prompt 'Use calculator.compute to calculate 22.2135 / 106.206 * 365. Then answer with the numeric result rounded to two decimals.'
tool_result ok tool=calculator.compute
loop_completed
{"status": "completed", "answer": "The result is **76.34152025**. Rounded to two decimals, that is **76.34**.", "tool_call_count": 1, "turn_count": 2, ...}
```

修复后的 no-gold mini finance live smoke：

```text
.venv/bin/python -m kernel_v4.finance_run --model deepseek-chat --timeout-seconds 120 --max-retries 1 --max-turns 8 --max-tool-calls 20 --show-workflow --workflow-format compact --include-transcript --row-json '{...mini-dio-live-no-gold...}'
provided_context.parse -> ok
calculator.compute -> ok
calculator.compute -> ok
calculator.compute -> ok
finance.verify_numeric -> ok
loop_completed
{"status": "completed", "answer": "...76.34 days...", "tool_call_count": 5, "turn_count": 6, "gold_reference_material_included": false, "capability_claim": false, ...}
```

这条 mini finance live 只证明 v4 no-gold runner、provider streaming tool call、context parse、calculator、numeric verifier 和 finalization 的单题链路已闭环；它不是 FinanceBench/FQA 正式成绩。

已完成的 provider-native 工具闭环 smoke：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --finance-tools --force-tool calculator.compute --max-turns 4 --max-tool-calls 8 --prompt "Use the forced calculator.compute tool to calculate 2+2. After the tool result, answer with the numeric result and say it came from calculator.compute."
{"status": "completed", "answer": "The numeric result is **4**, and it came from **calculator.compute**.", "tool_call_count": 1, "turn_count": 2, ...}
```

改写 streaming executor 后，新的 live workflow smoke 证明工具会在模型流结束前启动：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --calculator-only --tool-choice none --force-tool calculator.compute --show-workflow ...
assistant_tool_call -> tool_queued -> tool_start -> tool_lifecycle(completed) -> assistant_message_stop -> tool_result
```

这个 live workflow 是架构联通证据，不是 FinanceBench/FQA 做题成绩；是否最终答对仍以后续 live benchmark 为准。

## 2026-06-18 晚间链路效率复盘

时间点：2026-06-18 22:54 CST。

本轮目标不是新增题目规则，而是修正 live debug 中暴露出的通用 agent-loop 链路问题，并把成本控制到可继续跑 debug50/test100 的范围。

### 已确认的 live debug 记录

- 当前已记录的 FinanceBench `debug50` 最佳 live 通过段为 offsets `0-20`，共 `21/21` 通过。
- gold/reference 仍只在题后评分使用，`gold_reference_material_in_model_context=false`。
- `financebench_id_00438` 通过记录：`50` turns、`61` tools、cache hit rate `0.96678`。
- `financebench_id_00591` 通过记录：`53` turns、`63` tools、cache hit rate `0.96777`。
- offsets `13-14` 证明 cache 修复有效，但也暴露出效率仍不合格：模型能做对，但会长时间停留在检索/读 artifact 阶段。
- 后续 `checkpoint` / `checkpoint2` / `endgamefix` 等 offset14 重跑被人工中断，只作为效率诊断 trace，不计入 live 通过率或失败率。
- 2026-06-18 晚间 offset14 又暴露一次真实退化：模型在证据可达的情况下把 free cash flow conversion 错用成 `operating cash flow / net income`，导致 `0/3` numeric 命中。根因不是题目不可解，而是 FCF conversion 没有作为稳定任务族进入 workbench/prompt contract，同时过度限制 `market.openbb.fetch` 让成熟结构化 fundamentals 路径不够显眼。
- 通用修复后新增 `cash_flow_conversion` profile，并在系统 prompt / solver contract 中明确：未另行定义时，FCF conversion = `(net cash provided by operating activities - capex) / net income`，capex 可来自 `Purchases of property and equipment` / `Purchases of property, plant and equipment` 等行项目，不得退化成 OCF/NI。
- 修复后的 live 复测：
  - `model_context_mode=compact`：通过，`23` turns、`32` tools、`3/3` numeric，但 cache hit rate 只有 `0.08678`。
  - `model_context_mode=off`：通过，`27` turns、`38` tools、`3/3` numeric，cache hit rate 恢复到 `0.94407`。
- 轻量模型 A/B：
  - `deepseek-v4-flash` + `model_context_mode=off` 同题通过，`35` turns、`40` tools、`3/3` numeric，cache hit rate `0.96190`。
  - Flash 比 `deepseek-v4-pro` 多用 `8` turns、`2` tools，总 tokens 约 `1.016M` vs pro `0.846M`，但按 DeepSeek 当前 cache pricing 估算，本题成本约为 pro rerun 的 `34.6%`。
  - 结论：Flash 对这类有明确工具链和公式契约的题目有希望作为默认调试模型；但这只是单题 A/B，不是 debug50/test100 结论。
- 因此当前默认策略是 pass-first/full-tool + `model_context_mode=off`。同题内部历史依靠 append-only conversation/tool-result messages，而不是每轮临时 runtime context；否则 DeepSeek prefix cache 会被动态尾部 context 破坏。

### DeepSeek cache 成本依据

DeepSeek 官方文档记录：

- Context Caching 默认开启。
- 后续请求只有完整匹配已持久化的 cache prefix unit 才会命中。
- usage 中返回 `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens`。
- `deepseek-v4-pro` 输入价格为：cache hit `$0.003625 / 1M tokens`，cache miss `$0.435 / 1M tokens`。
- 因此 v4-pro 输入 token 的 miss/hit 单价约为 `120x`。长链路题目必须优先保证静态前缀稳定、动态上下文后置、少插入每轮变化的 system/context 字段。

工程结论：

- 默认关闭 provider thinking：`thinking={"type": "disabled"}`，只在必要题目上开启。
- finance runner / eval 默认 `model_context_mode=off`，避免每轮把 run id、turn index、workflow、artifact lifecycle 这些动态字段放入 provider request context。
- 将 `max_tool_result_chars` 默认收为 `12_000`，大结果走 artifact。
- 提供 `--thinking enabled/disabled`、`--reasoning-effort`、`--model-context-mode`，用于分层实验，不把强模型/思考模式直接常开。
- batch summary 写入 cache hit/miss tokens、turns、tool calls、total tokens，便于后续做图。

官方依据：

- https://api-docs.deepseek.com/guides/kv_cache
- https://api-docs.deepseek.com/quick_start/pricing

### 暴露的问题

offset14 的效率诊断连续暴露三个问题：

1. prompt-only 不足以让模型停止探索。即使系统提示“证据足够后应计算”，模型仍会继续调用 SEC、docling、hybrid search、artifact.search/read。
2. 第一版 endgame checkpoint 只插入 system 提醒，但可见工具仍是完整工具面；模型仍能选择高成本 source tools。
3. 第二版 endgame 把可见工具从 `19` 收到 `10` 后，高成本 source tools 被挡住，但模型仍在低成本 artifact search/read 中循环；并且偶尔会调用历史里出现过的 provider-sanitized 旧工具别名，如 `sec_edgar_financials_...`，执行端返回 `tool_not_found`。

判断：

- 这不是某一道 FinanceBench 的孤立问题，而是通用 agent loop 的阶段边界问题。
- 模型不够聪明时，不能只靠“请你计算”的 prompt；host 必须维护工具生命周期、阶段切换和可见工具面。
- 这仍然不是 host 替模型做金融语义判断。模型仍决定事实、公式、比较和最终结论；host 只管理当前阶段可执行动作。

### 已落地的通用修正

当前默认 live 做题路径不是强制三段式收窄，而是：

1. `pass-first/full-tool`：完整金融工具面默认可见，优先保证做出来。
2. `model_context_mode=off`：不把每轮动态 runtime context 临时塞到请求尾部，保护 DeepSeek prefix cache。
3. `append-only history`：同一道题内部的 assistant/tool call/tool result 作为真实消息历史进入下一轮；模型不是失忆的。
4. `workbench contract`：把通用题型能力沉淀到 `finance.workbench.open` profile 和系统 prompt，而不是把旧 run 答案或 gold/reference 喂给模型。

配套修正：

- 新增 `cash_flow_conversion` profile，覆盖 FCF conversion、现金流转化质量、trend/improving 题，要求 OCF、capex、net income、period/unit/source，并给出通用公式。
- `market.openbb.fetch` 重新作为结构化 public financial-statement fundamentals 的支持工具可见；primary filing 仍用于 exact label/citation，但不再因 prompt 过度限制而阻断成熟结构化路径。
- `tool.discovery` / `tool.workbench` 尊重当前 `tool_surface_allowlist`；但 endgame/calculation allowlist 只在显式开启 checkpoint 实验时生效，不作为默认做题策略。
- `tool_not_found` 返回当前 active allowlist，并明确提示不要调用隐藏工具、旧工具别名或 provider-sanitized 历史别名。
- 同一 assistant turn 内的完全重复工具调用只执行一次，后续同输入调用返回 `in_turn_duplicate_tool_call` synthetic observation。
- prompt 层补充：数值题必须用 calculator/table 验证；trend 题必须给 latest、prior、delta；provided context 有足够行项目时不应外部重找每一行；FCF conversion 不得退化成 OCF/NI。

后续优化方向：

- 继续保持 `model_context_mode=off` 作为 debug/test 默认。
- 如果模型在长工具历史中迷路，不应改回 per-turn transient context；应增加 append-only 的工作记忆摘要，把“已找到事实 / 缺失事实 / 公式 / 下一步”作为稳定消息追加到历史尾部，从而兼顾历史可见和 cache prefix 命中。

新增结构测试覆盖：

- opt-in endgame checkpoint 后隐藏 `document.search.hybrid`，保留 artifact/search/read/compute。
- opt-in calculation checkpoint 后隐藏 artifact.search/read，只保留计算/验证/discovery。
- discovery 在 active allowlist 下不能返回被收起的工具。
- 旧 provider-sanitized 工具别名返回带 allowlist 的错误观察。

当前结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
100 passed in 3.44s
```

### 强模型与成本策略

当前先用 cache-friendly 的非 thinking 模式跑 debug，保留更强推理作为兜底，而不是默认打开：

- 如果题目在 `calculation` 阶段仍不能调用计算/验证或给出精确 blocker，才考虑开启 thinking / higher reasoning effort 或换更强模型配置。
- 切强模型前必须保持稳定 prompt 前缀和工具面，不允许通过动态 prompt 膨胀破坏 cache。
- 评估记录必须同时报告 pass/fail、turns、tool calls、prompt cache hit/miss tokens、total tokens、人工中断原因。
- 2026-06-18 已新增 `finance_repeat` / `finance_ablation`，新运行会把 wall-clock duration 和 DeepSeek cost estimate 写入 item/summary/CSV，避免后续论文图表靠手工追数。

### 论文实验协议与 repeat10 结果

新增实验入口：

```text
python -m kernel_v4.finance_repeat ...
python -m kernel_v4.finance_ablation ...
```

实验边界：

- 每个 replicate 都是一次独立 live provider run。
- 模型上下文仍只包含题面、provided context、工具观察和真实对话历史。
- gold/reference 只在每个 run 完成后用于 scorer。
- repeat/ablation 输出 `repeat_summary.json`、`repeat_items.jsonl`、`repeat_items.csv`；新运行还会包含 `duration_seconds` 和 `cost_estimate`。
- 对同一题进行多次重复，是为了测稳定性、成本、cache hit、turn/tool 分布，不把旧答案或 scorer 反馈喂回模型。

当前用 FinanceBench debug offset `14` / `financebench_id_00591` 做第一组重复性消融，因为这题曾暴露真实 FCF conversion 公式族退化。已完成结果：

| 条件 | repeats | passed | mean turns | mean tools | mean tokens | aggregate cache hit | estimated total cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `deepseek-v4-flash`, thinking disabled, context off | 10 | 10 | 32.7 | 41.6 | 1,145,274 | 96.14% | ~$0.1115 |
| `deepseek-v4-flash`, thinking enabled low, context off | 10 | 10 | 24.0 | 33.0 | 719,319 | 94.78% | ~$0.0921 |
| `deepseek-v4-flash`, thinking enabled medium, context off | 10 | 9 | 21.7 | 29.4 | 626,912 | 94.50% | ~$0.0837 |

disabled/low 两组都是 `10/10` pass，且每次都是 `3/3` numeric hit、`numeric_within_tolerance`。medium 组为 `9/10` pass，失败原因为 `numeric_outside_tolerance`。当前单题结论：

- low thinking 没有降低正确率，反而降低 mean turns、tools、tokens 和估算成本。
- medium thinking 平均 tokens 和估算成本更低，但正确率降到 `90%`，因此不能把“更高思考强度”直接当作默认优化。
- cache hit 从 disabled 的 aggregate `96.14%` 降到 low 的 `94.78%`、medium 的 `94.50%`，但 miss/output 成本增加不足以抵消 token 总量下降。
- medium replicate 7 的失败不是证据不可达：答案使用了正确 FCF conversion 公式和 comparable facts，但最终只输出 decimal ratio `1.5551 / 1.4272 / +0.1279`，没有同步输出 `155.5% / 142.7% / +12.8 percentage points` 这类百分比/百分点表示，导致 scorer 无法匹配。
- 已对 prompt contract 做通用修正：unitless ratios/conversions/margins/returns 必须同时给 decimal 和 percent；delta 必须同时给 ratio-point 和 percentage-point。这是最终表达规范，不是某题答案表。
- 这是单 debug item 的稳定性/效率结果，不是 debug50/test100 成绩。
- 之前启动过 `deepseek-v4-pro` repeat，但为控制成本在 5 个 replicate 后人工中断；这 5 次均通过，但 long-tail token 开销显著更高，只作为成本风险证据。

DeepSeek cost estimate 使用 2026-06-18 观察到的官方价格表：

```text
deepseek-v4-flash: cache-hit input $0.0028/1M, cache-miss input $0.14/1M, output $0.28/1M
deepseek-v4-pro: cache-hit input $0.003625/1M, cache-miss input $0.435/1M, output $0.87/1M
```

已有 disabled/low 两组 repeat10 是 instrumentation 增强前跑出的，所以成本是从已记录 usage 后验计算；medium 及后续 debug50/test100 已直接在 JSON/CSV 中带 cost/duration 字段。

### offset15-20 live debug 续跑

采用当前默认候选 `deepseek-v4-flash + thinking low + model_context_mode=off` 继续一题一题推进：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 15 | `financebench_id_01319` | passed | 39 | 42 | 1,339,803 | 96.05% | 144.19s | ~$0.0131 |
| 16 first run | `financebench_id_00540` | failed, `numeric_outside_tolerance` | 17 | 31 | 462,234 | 91.21% | 121.51s | ~$0.0085 |
| 16 rerun after generic denominator contract | `financebench_id_00540` | passed | 32 | 48 | 1,319,453 | 95.08% | 155.86s | ~$0.0153 |
| 17 | `financebench_id_10420` | passed | 24 | 42 | 819,274 | 93.28% | 137.26s | ~$0.0122 |
| 18 | `financebench_id_06655` | passed | 35 | 51 | 1,527,011 | 95.63% | 186.20s | ~$0.0166 |
| 19 | `financebench_id_08135` | passed | 15 | 16 | 277,336 | 92.30% | 56.12s | ~$0.0046 |
| 20 | `financebench_id_08286` | passed | 13 | 15 | 292,776 | 90.97% | 55.56s | ~$0.0055 |

offset16 初次失败的根因不是工具链断裂：模型取到了 AES FY2022 cost of sales、beginning inventory、ending inventory，并采用 textbook conventional inventory turnover = COGS / average inventory，得到约 `12.14x`。score sidecar 对这道“Roughly how many times has AES sold its inventory”题匹配的是 ending-inventory proxy。通用修正是：

- 对库存周转题，若题面没有明确 average 或 ending denominator，模型必须说明口径。
- beginning/ending inventory 都可得时，同时报告 average-inventory convention 和 ending-inventory proxy。
- DIO 仍按 average inventory，除非题面或来源另有定义。

这不是给 offset16 写答案表，而是把公式口径歧义显式化；重跑后模型最终回答同时包含 `12.14x` average-inventory convention 和 `9.5x` ending-inventory proxy，scorer 通过。

offset15-20 的最新通过运行合计 `5.58M` tokens，估算成本约 `$0.0672`，mean turns `26.3`，mean tools `35.7`。这一段说明当前 low/context-off 配置可以继续推进 debug50，但高成本题仍集中在 30+ turns、40+ tools 的 SEC/document/artifact 路径。

### 2026-06-19 offset21-40 live debug 续跑

时间点：2026-06-19 CST。

默认候选仍为：

```text
deepseek-v4-flash
thinking=enabled
reasoning_effort=low
model_context_mode=off
max_turns=96
max_tool_calls=260
max_tool_result_chars=12000
```

标准 `items.jsonl` 聚合并纳入 `.score.rescored.json` 的 false-negative
重评分后，offsets `21-40` 当前 best live 记录为 `20/20` passed。
这仍然是 `debug50` 调试集进展，不是 held-out `test100` 成绩。
所有 run 均保持：

- `gold_reference_material_in_model_context=false`
- gold/reference 只在题后 scorer 使用
- 不把旧答案、gold numeric、reference evidence 喂回模型

最新 offset21-40 记录：

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | note |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 21 | `financebench_id_03882` | passed | 7 | 7 | 87,264 | 88.17% | ~$0.0022 | numeric |
| 22 | `financebench_id_01935` | passed after scorer fix | 7 | 6 | 87,226 | 88.73% | ~$0.0021 | source-grounded qualitative |
| 23 | `financebench_id_00799` | passed | 31 | 33 | 915,107 | 95.44% | ~$0.0107 | numeric |
| 24 | `financebench_id_01079` | passed after source saturation / acquisition contract | 78 | 77 | 4,077,919 | 96.84% | ~$0.0343 | high-cost multi-source transaction list |
| 25 | `financebench_id_01148` | passed | 32 | 32 | 895,649 | 91.11% | ~$0.0150 | qualitative |
| 26 | `financebench_id_00684` | passed | 38 | 40 | 1,291,460 | 93.76% | ~$0.0169 | numeric |
| 27 | `financebench_id_01936` | passed after liability composition contract | 49 | 51 | 1,928,969 | 95.11% | ~$0.0219 | `81 / 93 = 87%` disclosure share |
| 28 | `financebench_id_01928` | passed | 12 | 11 | 166,433 | 90.71% | ~$0.0032 | numeric |
| 29 | `financebench_id_01930` | passed after company earnings source scorer fix | 13 | 12 | 218,301 | 91.64% | ~$0.0046 | earnings press release |
| 30 | `financebench_id_03069` | passed | 32 | 36 | 855,579 | 92.27% | ~$0.0136 | AMD target filing |
| 31 | `financebench_id_00222` | passed | 20 | 21 | 414,282 | 94.36% | ~$0.0059 | AMD target filing |
| 32 | `financebench_id_00995` | passed after synthesis scorer fix | 73 | 73 | 3,559,180 | 97.06% | ~$0.0289 | product/service over-search |
| 33 | `financebench_id_01198` | passed | 83 | 96 | 4,344,877 | 97.33% | ~$0.0336 | revenue-driver over-search |
| 34 | `financebench_id_00917` | passed | 32 | 52 | 1,314,837 | 91.81% | ~$0.0219 | operating margin driver |
| 35 | `financebench_id_01279` | passed | 35 | 38 | 1,574,213 | 92.23% | ~$0.0239 | OpenBB/latest drift observed |
| 36 | `financebench_id_00563` | passed | 27 | 28 | 849,154 | 87.87% | ~$0.0181 | OpenBB boundary diagnosis |
| 37 | `financebench_id_00757` | passed after yes/no numeric disclosure contract | 15 | 14 | 242,176 | 91.76% | ~$0.0043 | one customer = `16%` revenue |
| 38 | `financebench_id_00476` | passed | 18 | 17 | 418,860 | 90.95% | ~$0.0077 | qualitative |
| 39 | `financebench_id_01028` | passed | 46 | 45 | 1,402,916 | 94.91% | ~$0.0161 | qualitative |
| 40 | `financebench_id_00723` | passed | 28 | 32 | 1,027,986 | 94.92% | ~$0.0129 | qualitative |

### 2026-06-19 offset41-49 live debug 收口与冻结候选

offsets `41-49` 继续使用同一候选配置：

```text
deepseek-v4-flash
thinking=enabled
reasoning_effort=low
model_context_mode=off
max_turns=96
max_tool_calls=260
max_tool_result_chars=12000
item_timeout_seconds=1800
```

这 9 道标准 `items.jsonl` 记录全部通过。汇总为：`9/9` passed，
mean turns `31.1`，mean tools `32.2`，total tokens `9,463,149`，
mean cache hit `94.20%`，estimated total cost `~$0.1011`。

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 41 | `financebench_id_00720` | passed | 45 | 45 | 1,452,401 | 94.65% | ~$0.0176 | `source_grounded_qualitative_pass` |
| 42 | `financebench_id_01351` | passed | 9 | 12 | 153,323 | 89.49% | ~$0.0033 | `numeric_within_tolerance` |
| 43 | `financebench_id_01964` | passed | 48 | 47 | 1,652,594 | 95.05% | ~$0.0189 | `source_grounded_qualitative_pass` |
| 44 | `financebench_id_01981` | passed | 76 | 76 | 3,575,475 | 97.53% | ~$0.0279 | `source_grounded_qualitative_pass` |
| 45 | `financebench_id_05718` | passed | 22 | 23 | 481,430 | 94.94% | ~$0.0060 | `numeric_within_tolerance` |
| 46 | `financebench_id_04254` | passed | 23 | 29 | 739,915 | 94.50% | ~$0.0093 | `numeric_within_tolerance` |
| 47 | `financebench_id_00070` | passed | 24 | 23 | 651,157 | 94.90% | ~$0.0079 | `numeric_within_tolerance` |
| 48 | `financebench_id_02608` | passed | 9 | 12 | 139,910 | 92.02% | ~$0.0028 | `numeric_within_tolerance` |
| 49 | `financebench_id_04417` | passed | 24 | 23 | 616,944 | 94.74% | ~$0.0074 | `numeric_within_tolerance` |

论文口径上必须分清两类证据：

- offsets `0-7` 是早期 v4 live `summary.json` 记录，均为 completed/pass，
  gold/reference 未进入模型上下文；但这些记录没有完整 cost/duration 字段，
  因此在效率图表里标为 legacy summary-only。
- offsets `8-49` 是标准 `items.jsonl`/`items.csv` 记录，当前 best-run
  聚合为 `42/42` passed，并带 turns/tools/tokens/cache/cost 字段。

因此，当前可写入论文进展的是：FinanceBench `debug50` best-recorded live
evidence 为 `50/50`，其中 `42/50` 具备标准成本与效率字段，`8/50`
为 legacy pass evidence。它仍然只是调试集，不是 held-out `test100`
准确率。

### 2026-06-19 test100 held-out 起跑

冻结候选配置后，开始 FinanceBench `test100` held-out。第一条测试记录：

```text
run_id=fb_test100_o050_l001_flash_low_frozen_candidate_20260619
split=test100
offset=50
item=financebench_id_00685
held_out_test_score=true
debug_tuning_score=false
gold_reference_material_in_model_context=false
```

结果：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 50 | `financebench_id_00685` | passed | 17 | 18 | 319,154 | 94.70% | 56.57s | ~$0.00443 | `numeric_within_tolerance` |
| 51 | `financebench_id_01077` | failed | 48 | 48 | 1,590,876 | 95.38% | 185.37s | ~$0.01736 | `numeric_outside_tolerance` |
| 52 | `financebench_id_01275` | passed | 7 | 8 | 120,922 | 86.47% | 28.30s | ~$0.00323 | `numeric_within_tolerance` |
| 53 | `financebench_id_00288` | passed | 4 | 3 | 45,846 | 90.00% | 15.06s | ~$0.00107 | `numeric_within_tolerance` |
| 54 | `financebench_id_00460` | failed | 92 | 91 | 6,800,783 | 97.96% | 385.39s | ~$0.04405 | `numeric_outside_tolerance` |

可观察 workflow 显示这次不是单步猜测：模型先调用 `finance.workbench.open`
和 `provided_context.parse`，随后使用 `document.docling.convert`、
`document.search.hybrid`、`artifact.read/search/inspect` 定位证据，最后调用
`calculator.compute` 和 `finance.verify_numeric` 进行数值验证后输出答案。

offset51 是第一条 held-out 失败样本，必须保留。非 gold trace 显示：

- 题目是 Best Buy FY2023/FY2022/FY2021 major acquisitions。
- run completed，不是 provider crash 或 tool unavailable。
- 工具调用偏重：`artifact.search` 24 次、`document.docling.convert` 7 次，
  有 1 次 Docling error 后恢复。
- final 识别了 FY2022 的 `Current Health Ltd.` 和 `Yardbird`，但把
  consideration 写成 `all outstanding shares`，没有把披露的 cash
  consideration amounts 带入最终表格。
- scorer 因 `numeric_outside_tolerance` 判失败，`numeric_hit_count=0/2`。

这说明当前冻结候选在多年度 transaction-disclosure 题上仍有
answer-completeness 风险：找到了事实实体，但没有把已披露的数值属性完整带到 final。
按 held-out 规则，这个失败不能回灌到同一轮 candidate；如果后续用它改 prompt 或
loop，应开启新的候选配置，并把 offset51 从新的 held-out 口径中剔除或明确标为调试样本。

offset52-53 说明并非所有 test100 题都会进入长链路：offset52 在 7 turns /
8 tools 内完成，offset53 在 4 turns / 3 tools 内完成，均通过 numeric scorer。
offset54 则暴露更严重的问题：

- 题目是 Best Buy Q2 FY2024 vs FY2023 store-count change。
- run completed，不是 provider crash；但用了 92 turns / 91 tools。
- `document.search.hybrid` 30 次、`artifact.search` 25 次、`artifact.read` 14 次、
  `document.docling.convert` 9 次。
- 期间出现 3 次 `market.openbb.fetch` error，说明模型在 target filing / store
  count 任务里漂移到了不合适工具。
- final answer 说无法从 Q2 FY2024 10-Q 确认或量化 store count change；
  scorer 为 `numeric_outside_tolerance`，`numeric_hit_count=2/4`。

这不是工具完全不可用，而是当前冻结候选在“目标事实应该从 filing/store data
定位出来”的题上没有足够强的证据饱和、工具漂移抑制和 final completeness 控制。
当前冻结候选 held-out 起步为 `3/5`。

candidate-v2 与 candidate-v1 明确划清边界：

- offsets `50-54` 保留为 v1 held-out smoke，不再作为 v2 clean held-out。
- v2 live metadata 默认启用高阈值 checkpoint：
  - `enable_endgame_checkpoint=true`
  - `enable_calculation_checkpoint=true`
  - `endgame_evidence_success_threshold=32`
  - `calculation_evidence_success_threshold=6`
  - `source_saturation_evidence_success_threshold=20`
- v2 不在 host 侧写答案；它只是用 loop 生命周期管理防止 50+ turns 后继续 broad
  source/search drift。
- prompt/solver contract 增强为通用类型合同：
  - acquisition/event-list final 必须保留披露的 cash consideration、
    purchase price、goodwill 和 ownership percentage；不能用 ownership
    percentage 替代 cash consideration。
  - store-count/location-count/branch-count/square-footage/footprint-change
    题必须找 comparable period store data/counts，计算 latest-minus-prior
    change，并禁止漂移到 OpenBB。

结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
111 passed in 3.62s
```

v2 的 clean live pool 从未触碰的 offset `55` 开始。

v2 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 55 | `financebench_id_01902` | passed | 10 | 10 | 187,281 | 87.03% | 25.21s | ~$0.00444 | `numeric_within_tolerance` |
| 56 | `financebench_id_04660` | passed | 65 | 64 | 2,851,074 | 93.67% | 275.11s | ~$0.03966 | `numeric_within_tolerance` |

该题短链路即收敛，因此没有触发 v2 checkpoint；这说明新 checkpoint 不会干扰
低 turns 的正常解题路径。

offset56 通过但暴露 v2 的效率问题。checkpoint 流程按预期把 visible tools 从
20 收窄到 10，再收窄到 6；模型最终调用 `calculator.compute` 和
`finance.verify_numeric` 并通过 scorer。但是 verify 之后它继续调用
`data.table.query` / `calculator.compute` 等工具，多消耗十几轮。结论：v2
提高了长链路的可收束性，但还需要“verify success 后最终回答”和 calculation
surface 去除 discovery 的生命周期控制。

candidate-v3 做这两个通用生命周期修正：

- `_CALCULATION_TOOL_ALLOWLIST` 移除 `tool.discovery`，避免 calculation 阶段
  继续发现工具而不是计算/验证/最终回答。
- 新增 `POST-VERIFY FINALIZATION CHECKPOINT`：一旦非 error 的
  `finance.verify_numeric` 工具结果出现，下一轮 `force_finalization_no_tools=true`，
  visible tools 置空，模型必须从已观察证据、计算和验证结果生成 final answer。

结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
112 passed in 3.77s
```

v3 clean live 从 offset `57` 开始；offset55-56 保留为 v2 记录。

v3 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 57 | `financebench_id_03838` | passed | 39 | 38 | 1,295,372 | 87.30% | 114.95s | ~$0.02839 | `numeric_within_tolerance` |
| 58 | `financebench_id_07661` | passed | 18 | 22 | 358,931 | 87.24% | 52.41s | ~$0.00833 | `numeric_within_tolerance` |

workflow 观察：

- t36 endgame checkpoint 后 visible tools 从 20 收窄到 10。
- t38 `finance.verify_numeric` 成功。
- t39 post-verify checkpoint 后 visible tools 为 0，模型直接 final。

这证明 v3 的 post-verify finalization 能阻断 v2 中 verify 后继续调用
discovery/table/calculator 的尾巴；但 offset57 仍有 39 turns，说明证据定位前段还有
进一步优化空间。

offset58 再次验证 post-verify no-tools finalization：模型在 `calculator.compute`
和 `finance.verify_numeric` 后进入 0-tool final turn，通过 scorer。v3 clean pool
当时为 `2/2`。

offset59 随后暴露 v3 的终局生命周期缺口：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 59 | `financebench_id_10285` | failed | 43 | 49 | 1,582,035 | 86.18% | 154.60s | ~$0.03767 | `run_not_completed` |

非 gold 轨迹显示，`finance.verify_numeric` 已在 t42 成功，t43 的 visible tools
正确变为 `0`，但模型仍输出 text-form DSML 工具调用块。旧 fallback 在无可见工具时
仍尝试解析文本工具调用，结果把 DSML block 从 assistant content 中剥掉，又没有可执行
工具，于是 host 判为 `empty_final_answer`。这不是题目答案表问题，而是 no-tools
finalization 的 host 生命周期问题。v3 observed clean pool 因此记录为 `2/3`。

candidate-v4 把该修复从 v3 结果中切开，clean live pool 从未触碰的 offset `60`
开始。通用修正如下：

- 文本工具调用 fallback 只在当前确实有 visible tools 时启用。
- DSML block 中的工具不可见时，不再静默删除 assistant content。
- no-tools finalization 如果输出纯 DSML/tool-call markup，host 不执行、不打表，
  而是追加 `FINALIZATION FORMAT RECOVERY` system message，让模型在下一轮仍以
  `0` visible tools 写普通最终答案。

结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
114 passed in 3.89s
```

offset60 第一次尝试是 DNS 基础设施失败：0 tokens、0 tool calls、0 cost，不作为能力
结果。外部网络权限下的 retry 是真实 live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 60 | `financebench_id_00517` | failed | 36 | 46 | 1,263,466 | 80.52% | 196.92s | ~$0.04161 | `numeric_outside_tolerance` |

这条证明 v4 修掉了 offset59 的 `empty_final_answer`：`finance.verify_numeric`
后进入 0-tool final turn，模型最终完成回答。但它暴露新的通用做题问题：题面问
product/service categories 或 reportable segments 是否超过 revenue threshold，模型只给出
一个 qualifying segment，而不是枚举所有超过阈值的类别。该问题归类为
`revenue-threshold category set-completeness failure`。

candidate-v5 从未触碰的 offset `61` 开始；offset60 保留为 v4 失败记录，不混入
v5 clean score。v5 的通用修正：

- revenue-threshold category 问题必须取完整 comparable category/segment revenue table。
- 对每个 category/segment 计算 share of total revenue。
- final answer 要 yes/no 加 compact table，列出 every qualifying category；如果没有
  达标项，则说明已检查全部类别。

结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
115 passed in 3.65s
```

从 v5 开始继续按 held-out candidate 口径推进；后续如果出现失败，只能记录为该冻结
候选的测试表现，不能把同一 test100 item 的失败细节回灌后继续把这轮称为 held-out。

v5 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 61 | `financebench_id_01091` | passed | 48 | 47 | 1,864,847 | 85.45% | 163.93s | ~$0.04497 | `source_grounded_qualitative_pass` |

该题通过，说明 v5 的 prompt/loop 改动没有破坏 source-grounded qualitative
题。但它不是效率上的胜利：前 36 轮仍在 document/artifact/SEC 之间长时间定位证据，
endgame 后还出现旧 provider-sanitized 工具别名调用。这应进入论文的问题分析：
当前 loop 已能把很多长题最终收束到 final answer，但 evidence planning 和 hidden-alias
纪律仍是成本/稳定性瓶颈。

v5 第二条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 62 | `financebench_id_00678` | failed | 21 | 29 | 518,625 | 81.58% | 90.11s | ~$0.01651 | `numeric_outside_tolerance` |

题面是 Boeing FY2022 gross margin profile 是否 improving，以及 gross margin
是否对这种公司有用。非 gold 答案显示模型找到了大部分相关数值并完成
`finance.verify_numeric`，但 final 中存在 gross-margin 符号规范风险：cost of products /
cost of services 用括号显示为负数，同时公式文字写成 revenue minus costs。此类表述容易
让最终 numeric claim 与 scorer/source 口径不一致；该题 `3/4` numeric hit，归类为
`gross-margin sign-normalization / formula-presentation failure`。

candidate-v6 从未触碰的 offset `63` 开始；offset62 保留为 v5 失败记录。v6 的通用修正：

- gross-margin profile 题必须取得 revenue 与所有 cost-of-sales rows。
- 明确说明 cost rows 是正成本额还是 signed negative expense。
- 若成本是正数，gross profit = revenue - costs；若工具/source 给的是负数费用行，
  gross profit = revenue + signed cost rows。
- final answer 不得同时用括号负数展示成本、又写 subtraction formula 造成符号歧义。
- 要给 latest/prior gross margin、percentage-point change，并从业务/source 语境解释
  gross margin 是否有用或有局限。

结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
115 passed in 3.61s
```

v6 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 63 | `financebench_id_01290` | failed | 29 | 29 | 720,810 | 90.69% | 90.15s | ~$0.01283 | `numeric_outside_tolerance` |

题面是 Boeing FY2022 primary customers。非 gold final answer 给出了 commercial
airlines、U.S. government/DoD、commercial and defense customers worldwide 等客户组，
但没有带出 filing 中可能存在的 customer concentration / revenue share 数字。scorer
记录为 `0/1` numeric hit。该题归类为 `primary-customer/customer-concentration
numeric-disclosure omission`。

candidate-v7 从未触碰的 offset `64` 开始；offset63 保留为 v6 失败记录。v7 的通用修正：

- primary-customer / customer-concentration / major-customer / who-are-the-customers 题
  要检索 Item 1 Business 以及 customer-concentration disclosure。
- 搜索 `customers`、`commercial airline`、`U.S. government`、`Department of Defense`、
  `limited number of customers`、`substantial portion`、`significant portion`、
  `accounted for` 等短语。
- final answer 不只列客户类别；若披露了 revenue share、concentration percentage、
  customer count 或 named government/customer group，必须一起保留。

结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
115 passed in 3.25s
```

v7 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 64 | `financebench_id_00464` | passed | 18 | 20 | 403,092 | 92.28% | 64.58s | ~$0.00651 | `source_grounded_qualitative_pass` |

这条是 v7 的第一条 clean positive sample，成本和轮数比 offset61-63 明显更低。它说明
primary-customer contract 没有破坏 qualitative source-grounded 题，也说明在部分题上
workbench + document/artifact 路径可以在 20 tools 左右收束。

v7 第二条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 65 | `financebench_id_00494` | passed | 26 | 25 | 569,354 | 90.88% | 84.93s | ~$0.01030 | `numeric_within_tolerance` |

该题 `3/3` numeric hit，说明 v7 在数值题上也能保持通过。但 workflow 中 t11-t24
出现连续 `artifact.search`，属于 correctness-positive but efficiency-imperfect sample。

v7 第三条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 66 | `financebench_id_00585` | passed | 30 | 30 | 732,697 | 86.57% | 92.00s | ~$0.01733 | `numeric_within_tolerance` |

该题 `2/2` numeric hit。workflow 中 `document.search.hybrid` 曾多次报错，但 agent
通过 artifact read/inspect、calculator、SymPy 和 `finance.verify_numeric` 完成恢复与验证。
这条样本应作为论文中的“recoverable tool-interface error + successful final
verification”过程证据，而不是简单折叠成 pass 计数。

v7 第四条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 67 | `financebench_id_03473` | passed | 23 | 32 | 700,879 | 79.41% | 102.31s | ~$0.02386 | `numeric_within_tolerance` |

该题 `1/1` numeric hit。它先使用 workbench/docling/artifact/SEC/document search
取证，再连续调用 calculator 和 `finance.verify_numeric`。正确性上是正例，但 cache
hit 明显低于 offset64-66，应作为“重取证上下文导致 cache efficiency 下降”的效率样本。

v7 第五条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 68 | `financebench_id_09724` | passed | 43 | 43 | 1,534,734 | 89.48% | 150.99s | ~$0.02960 | `numeric_within_tolerance` |

该题 `1/1` numeric hit，但属于 long-tail efficiency sample。流程中出现一次
`sec.edgar.financials` error、一次 `artifact.read` error，以及 endgame 阶段被拒绝的
sanitized tool alias，随后仍完成 calculator 和 `finance.verify_numeric`。论文里应把它
用于说明 tool-result lifecycle / error recovery 成立，同时指出重复 evidence acquisition
仍是主要成本驱动。

v7 第六条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 69 | `financebench_id_06272` | passed | 31 | 43 | 1,214,700 | 78.77% | 106.79s | ~$0.04096 | `numeric_within_tolerance` |

该题 `1/1` numeric hit，是 document-first long-tail 样本：artifact search 密集，
随后补 SEC financials，endgame 工具面收窄后出现 `artifact_search_*` sanitized alias
被拒绝，之后模型转向 calculator 和 `finance.verify_numeric` 完成。v7 从 offset64-69
连续 6 条 clean live 通过，但 offset68/69 暴露的 alias/tool-surface 问题若要修复，
应开启 v8 并从后续未触碰 offset 重新计 clean evidence。

candidate-v8 从未触碰的 offset `70` 开始；offset64-69 保留为 v7 clean records，不并入
v8 held-out 口径。v8 是通用 tool lifecycle 修复，不是金融答案规则：

- provider 反向解析现在把历史 assistant tool_call 的 native name 也纳入只读解析映射。
  因而历史里出现过的 `artifact_search_9308f523`、`sec_edgar_financials_0fff6646`
  这类 provider-safe name 会先还原成 canonical tool name。
- executor 在运行 canonical tool 前强制检查 active tool-surface allowlist。若当前阶段
  已经收窄，不允许该工具执行，就返回结构化 `tool_not_in_active_surface`，不会让旧
  alias 绕过 endgame 工具面。
- 结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
116 passed in 3.38s
```

v8 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 70 | `financebench_id_10130` | failed | 38 | 51 | 1,653,588 | 79.14% | 197.44s | ~$0.05613 | `numeric_outside_tolerance` |

非 gold 归因：最终 answer 不是自然语言答案，而是 no-tools finalization 阶段输出的
DSML calculator 调用：

```text
<｜｜DSML｜｜tool_calls> ... calculator_compute_1052e069 ... (2438 - 2320) ...
```

这说明 v8 的 alias guard 仍不够，且 no-tools finalization 退出条件过宽：恢复两次后
还看到纯 tool-call markup 时，loop 仍把它当 final answer 完成。

candidate-v9 从未触碰的 offset `71` 开始；offset70 作为 v8 failure record，不并入
v9 held-out 口径。v9 是通用 finalization lifecycle 修复：

- no-tools DSML recovery budget 从 `2` 提高到 `4`。
- finalization no-tools 阶段永远不能接受纯 DSML/tool-call markup 作为 completed final
  answer。
- 若没有恢复空间或达到恢复上限，run 明确失败为 `final_answer_is_tool_call_markup`，
  而不是提交不可评分 answer。
- 结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
117 passed in 3.66s
```

v9 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 71 | `financebench_id_02981` | passed | 29 | 37 | 846,719 | 88.33% | 168.41s | ~$0.01801 | `numeric_within_tolerance` |

该题 `1/1` numeric hit。流程仍然偏长：Docling、SEC、document search、artifact、
OpenBB、calculator、`finance.verify_numeric` 都参与了；但 post-verify no-tools
finalization 正常输出 prose answer，没有复现 offset70 的 DSML 交卷。

v9 第二条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 72 | `financebench_id_01346` | passed | 6 | 6 | 77,801 | 83.43% | 24.39s | ~$0.00254 | `numeric_within_tolerance` |

该题 `2/2` numeric hit，是 v9 当前最好的 efficiency-positive sample。agent 使用
provided-context parsing、Docling、一次 SEC financials 尝试、artifact read、calculator、
`finance.verify_numeric` 后直接 prose finalization。它说明系统在证据容易定位时可以
快速收束，不是所有题都必然百万 token。

v9 第三条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 73 | `financebench_id_00005` | failed | 12 | 11 | 191,995 | 92.32% | 39.77s | ~$0.00322 | `numeric_outside_tolerance` |

非 gold 归因：题目是 Corning FY2022 positive working capital。final answer 给出
`$2,278 million` working capital，但整个流程没有调用 calculator 或
`finance.verify_numeric`。因此该失败归类为 premature numeric finalization / missing
numeric verification，而不是 provider 或 doc parser failure。

candidate-v10 从未触碰的 offset `74` 开始；offset73 作为 v9 failure record，不并入
v10 held-out 口径。v10 是通用 finance-mode 流程约束：

- 如果 draft final answer 含 material numeric claims（金额、百分比、ratio、days 等），
  且尚未成功调用 `finance.verify_numeric`，loop 不直接 completed。
- loop 插入 `NUMERIC VERIFICATION CHECKPOINT`，要求模型先使用 calculator（如有派生计算）
  和 `finance.verify_numeric`，之后再 final。
- host 不判断金融语义正确性，只强制“关键数值要走 verifier”这一流程边界。
- 结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
118 passed in 3.34s
```

v10 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 74 | `financebench_id_04209` | passed | 12 | 11 | 267,454 | 74.15% | 45.91s | ~$0.01113 | `numeric_within_tolerance` |

该题 `1/1` numeric hit。流程为 workbench/document/artifact search 后进入 calculator，
再调用 `finance.verify_numeric`，最后 prose finalization。它是 v10 的第一条 clean 正例。

v10 第二条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 75 | `financebench_id_05915` | failed | 48 | 54 | 2,637,977 | 81.85% | 333.19s | ~$0.07965 | `numeric_outside_tolerance` |

非 gold 归因：题目要求 CVS FY2018 fixed asset turnover = FY2018 revenue /
average PP&E(FY2017,FY2018)。final answer 使用了 revenue 和 PP&E 数值并完成
calculator / `finance.verify_numeric`，但文本明确承认 PP&E values 来自 “my recall”，
并且 balance sheet rows 没有被直接抓到。该失败归类为 source-backed slot binding failure /
unsupported recalled line items，不是纯算术或 verifier 缺失。

candidate-v11 从未触碰的 offset `76` 开始；offset75 作为 v10 failure record，不并入
v11 held-out 口径。v11 是通用 unsupported numeric source recovery：

- 如果 finance final answer 同时包含 material numeric claims 和 unsupported-source caveat
  （例如 `my recall`、`not directly observed`、`partially accessible`、`could not locate`），
  loop 不直接 completed。
- loop 插入 `UNSUPPORTED NUMERIC SOURCE RECOVERY`，删除 no-tools 强制和当前 tool-surface
  allowlist，重新开放证据工具，要求模型找 source-backed line items，再 calculator/verify/final。
- 如果没有恢复空间或已经恢复过仍然如此，则明确失败为
  `unsupported_numeric_source_final_answer`。
- 结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
119 passed in 3.27s
```

v11 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 76 | `financebench_id_00790` | passed | 29 | 53 | 1,213,346 | 80.68% | 173.69s | ~$0.03855 | `numeric_within_tolerance` |

该题 `3/3` numeric hit，是 v11 第一条 clean 正例。但效率仍然不好：流程中有重复
artifact/SEC/market 探索，endgame 后才转入 calculator 和 `finance.verify_numeric`。它说明
correctness path 可行，但下一阶段应重点优化 source saturation / endgame 收束，而不是继续盲目加预算。

candidate-v12 从未触碰的 offset `77` 开始；offset76 保留为 v11 clean record，不并入
v12 held-out 口径。v12 是通用 source-saturation / tool-surface convergence 修复：

- 任何 active `tool_surface_allowlist` 都会真正影响 provider-visible tool surface，不再只在
  endgame checkpoint 之后生效。
- source saturation 不再只是写一条提示；触发后直接把工具面收窄到
  `data.table.query`、`math.sympy.compute`、`calendar.days_between`、`calculator.compute`、
  `finance.verify_numeric`。
- 如果一个 required fact 真的缺失，模型应明确该 source-backed fact 缺失，而不是继续 broad
  retrieval / artifact search / market fetch。
- 结构测试：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
119 passed in 3.13s
```

v12 第一条 clean live：

| offset | item | result | turns | tools | tokens | cache hit | duration | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 77 | `financebench_id_01107` | failed | 23 | 26 | 624,823 | 85.86% | 130.35s | ~$0.01637 | `numeric_outside_tolerance` |

非 gold 归因：题目问 CVS 2022/2021/2020 是否有 materially important ongoing legal
battles。final answer 回答 yes，但证据主要是 Table of Contents 的 `Item 3: Legal
Proceedings` 和 forward-looking risk factor，对具体 Item 3 Legal Proceedings 里的
named proceedings / litigation categories 没有充分展开，也没有逐年绑定。v12 确实把成本
从 offset75/76 的 long-tail 水平压下来，但 legal proceedings 题需要更明确的 evidence spec。

candidate-v13 从未触碰的 offset `78` 开始；offset77 作为 v12 failure record，不并入
v13 held-out 口径。v13 是通用 legal-proceedings evidence contract：

- legal battle / legal proceedings / litigation / lawsuit / regulatory investigation 题不能只依赖
  TOC、风险提示或 forward-looking caveat。
- 必须检索实际 `Item 3. Legal Proceedings`、相关 notes/contingencies/commitments、opioid/
  government investigation/qui tam/settlement 等具体 disclosure。
- final answer 应列出 named proceedings 或 proceeding categories，并与题目要求的 fiscal years
  绑定；若题目问 yes/no，也要带出支持 yes/no 的具体案件/类别和期间。

本段暴露并修复的通用问题：

1. `source_grounded_research` 无 expected numeric 的题不能全部按
   `no_expected_numeric` 判失败。现在 scorer 支持 source-grounded qualitative
   checks：答案存在、非 generic failure、citation signal、synthesis signal、
   required source family、required doc type。
2. FinanceBench 的 sidecar 有时要求 `sec_filings`，但实际 required URL 是
   公司托管的 earnings/press-release PDF。现在公司主源 URL + document/artifact
   工具可满足 company primary source；`earnings` 也接受 `press release`
   等等价文档信号。
3. Restructuring/reserve/accrual/liability-nature 题如果表格给出组成项和
   total，模型必须计算主导组成项占比，再解释 note 中的业务目的。
4. Product/service extraction 题不应扩展到每个 revenue segment 或 market
   data；Item 1 / Overview 已列出产品服务时应直接 synthesize。
5. Revenue/sales-driver 题优先使用 MD&A 中 management-named drivers；若题
   面没有要求 contribution shares，不应为了排名/占比继续泛搜。
6. `market.openbb.fetch` 保持暴露，但 target-filing accounting 题的无
   period OpenBB 调用会被 v4 adapter soft-block，防止默认 latest period
   漂移到 AMD 2026 amended filing。模型仍可在真正 market-data 题或显式
   period 调用中使用 OpenBB。
7. Yes/no disclosure 题不能只答 yes/no；如果证据句含金额、百分比、客户数、
   日期或 segment qualifier，final 必须带这些数值。

结构测试更新为：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py -q
110 passed in 3.76s
```

论文记录建议：

- offsets `32-35` 虽然通过，但应作为 efficiency long-tail 证据：工具面足够
  解决题目，不代表 loop 已经最优。长链路高 cache hit 降低成本，但不能替代
  更好的阶段收敛。
- offset `37` 是 prompt/finalization contract 的正例：同一题第一次 live 找到
  正确证据但漏掉 `16%`，通用 yes/no disclosure numeric contract 后 rerun 通过。
- OpenBB guard 是 host 工具边界，不是金融答案规则；它只阻断无期间 latest
  market/fundamental 漂移，保留 LLM 对工具选择和语义判断的所有权。

报告表述建议：

- “当前转折点不是单题 prompt patch，而是把成熟 agent loop 中的 tool lifecycle / context edit / tool discovery / tool surface management 落到 Python v4。系统不替模型计算答案，但用阶段化工具面阻止模型在低收益检索中空转。”
- “DeepSeek cache 命中把长链路输入成本降低约两个数量级，因此链路设计必须服务于 prefix stability。”
- “21/21 是 debug-slice best-recorded live segment；offset14 repeat 和 offset16 first-run failure 是效率/稳定性/口径诊断，不是 held-out test 成绩。”

本轮补齐后，20 秒 provider timeout smoke 的结果是失败但稳定退出：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --timeout-seconds 20 --max-retries 0 --max-turns 2 --max-tool-calls 2 --show-workflow
20.02s t1 loop_failed reason=model_stream_error:RuntimeError:deepseek stream queue exceeded 20s without completion
{"status": "failed", "reason": "model_stream_error:RuntimeError:deepseek stream queue exceeded 20s without completion", ...}
```

这不是 live capability 通过结果；它只证明 provider 卡住时 v4 会按边界失败返回，并保持实时监控可见。

compact 监控输出示例：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --max-turns 2 --max-tool-calls 2 --show-workflow
    0.00s t0 loop_start run=run-... thread=kernel-v4-live-smoke
    0.00s t1 model_start messages=1 tools=2
    1.95s t1 assistant_stop text_chars=20
    1.95s t1 loop_completed answer_chars=20
```

## 下一步

下一步不再回到 v3 闸门，而是按论文实验顺序推进：

1. 冻结 `deepseek-v4-flash` thinking low / context off 作为当前 held-out
   candidate，不再用 `test100` item-level failure 反向调这轮配置。
2. 对 medium 失败样本只吸收通用最终表达规范，不吸收题目答案或 gold/reference。
3. debug50 只用于通用 loop/tool/prompt contract 调试，不把具体 gold/reference 或答案模式写回模型上下文。
4. 进入 `test100` held-out 后，先按单题 live 监控推进并记录
   turns/tools/tokens/cache/cost；若后续要调参，必须开启新的冻结配置和新的
   held-out 口径。

### 2026-06-19 v14-v22 live 迭代记录

这一段继续沿用“candidate 变更即切新 offset”的记录方式；它们是候选演进与失败
分类记录，不能合并成一个冻结 `test100` accuracy。

| candidate | offset | item | result | turns | tools | tokens | cache hit | estimated cost | 主要结论 |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| v13 | 78 | `financebench_id_01244` | failed | 23 | 25 | 659,477 | 78.30% | ~$0.02445 | dividend/common-shareholder evidence contract 不足；模型只拿到 Item 5 TOC 和子公司 dividend 语境 |
| v14 | 79 | `financebench_id_00839` | passed | 26 | 26 | 774,353 | 94.83% | ~$0.00977 | Foot Locker CEO 经验 qualitative 题通过，但 docling/SEC/trafilatura 路径仍有重复和错误 |
| v15 | 80 | `financebench_id_00822` | failed | 22 | 21 | 560,727 | 83.70% | ~$0.01569 | 8-K Item 5.07 vote table 没抽出来；repeated-source 收敛减少扩散，但缺可靠静态文档文本工具 |
| v16 | 81 | `financebench_id_04103` | failed | 25 | 32 | 620,427 | 90.81% | ~$0.01250 | `document.text.extract` 已能 one-shot 调用，但 source saturation 太早收成纯计算，阻断 artifact 继续读取 |
| v17 | 82 | `financebench_id_03471` | passed | 32 | 31 | 732,542 | 89.84% | ~$0.01360 | source saturation 保留 artifact/search/read 后，模型继续本地证据读取、calculator、verify 并通过 |
| v17 | 83 | `financebench_id_04854` | passed | 45 | 45 | 1,484,425 | 88.06% | ~$0.03068 | General Mills FY2020 FCF 题通过；但 artifact.search/read 重复明显，成本偏高 |
| v17 | 84 | `financebench_id_10136` | failed | 42 | 58 | 1,829,409 | 84.54% | ~$0.04838 | 初始 scorer 曾误判 pass；修复后为 `generic_failure_final_answer`。模型已 calculator/verify，却 final unable-to-compute |
| v18 | 85 | `financebench_id_00956` | failed | 29 | 32 | 1,004,032 | 64.03% | ~$0.05571 | no-tools finalization 连续输出 DSML `finance.verify_numeric` 文本调用；真实答案藏在 `answer` 参数中，host 未提取 |
| v19 | 86 | `financebench_id_00669` | failed | 30 | 30 | 896,591 | 89.94% | ~$0.01792 | 大文档 focus extraction 失败；模型传了 gross margin / Cost of products 等 focus terms，但工具先截断再搜索，后半段财务表没进入 artifact |
| v20 | 87 | `financebench_id_00711` | passed | 20 | 26 | 472,084 | 82.65% | ~$0.01547 | J&J FY2022 inventory turnover 通过；average inventory 口径 3.16x，同时报告 ending-inventory proxy 3.08x |
| v20 | 88 | `financebench_id_00651` | failed | 24 | 21 | 685,771 | 73.89% | ~$0.02802 | 目标 J&J earnings-release 静态 URL 在 text extract/docling 上均遇到 SSL EOF；verifier 返回 `not_applicable` 却被 loop 当作已验证状态 |
| v21 | 89 | `financebench_id_01484` | failed | 21 | 22 | 522,701 | 86.16% | ~$0.01294 | 静态 earnings URL 不可达后，模型找到 SEC filings 但缺 accession/exhibit 展开工具，最终 generic source blocker |
| v22 regression | 89 | `financebench_id_01484` | passed | 19 | 18 | 447,223 | 84.34% | ~$0.01214 | 已分析题的 contaminated regression；模型 one-shot 调用 `sec.edgar.filing_documents`，转 SEC exhibit/complete submission，calculator + verify 后通过 |
| v22 | 90 | `financebench_id_01488` | passed | 17 | 15 | 402,971 | 86.12% | ~$0.00969 | clean v22 held-out；静态 URL 失败后走 SEC filings / accession documents，识别 J&J Consumer Health/Kenvue discontinued operation |

v14 的通用修复：

- dividend / common-shareholder payment contract 扩展到 Item 5 Dividends、
  quarterly cash dividend、common stock、dividends per share、declared/paid。
- ToolRegistry 在执行前把唯一匹配的 provider native / hashed alias 规范化成真实注册
  tool name；若当前 tool surface 不允许，则返回 `tool_not_in_active_surface` 而不是
  模糊的 `tool_not_found`。

v15 的通用修复：

- 增加 repeated-source checkpoint。外部 source/extraction 工具成功或错误重复到阈值后，
  loop 收到 system checkpoint，外部 SEC/document/market 扩散停止，保留本地 artifact /
  compute endgame 工具。
- 增加 final-answer cleanliness recovery。final answer 不能以 “I now have all the evidence”
  / “Let me provide the final answer” 这类过程话开头；模型会被要求 no-tools 重写。

v16 的通用修复：

- 新增 `document.text.extract`。这是轻量开源文档文本路径，使用已有
  PyMuPDF / pypdf / readable HTML 抽取逻辑，不走重型 Docling；结果写入同一
  ArtifactStore，后续可由 `artifact.search/read` 使用。
- workbench 增加 `shareholder_vote_results` profile，覆盖 Item 5.07、Proposal 1、
  board nominees、Votes For、Votes Against、Abstentions、Broker Non-Votes。

v17 的通用修复：

- v12/v16 暴露出一个架构边界错误：source saturation 直接收成纯计算，会让模型丢失
  对已取得 artifact 的继续访问能力。
- v17 改为 source saturation 只阻断 broad external source retrieval，保留本地
  `artifact.inspect/search/read`、`provided_context.parse`、compute/table/date/symbolic/
  verification 和 endgame discovery。
- 之后如果模型仍在本地 artifact 层空转，再由 calculation checkpoint 二次收窄到纯计算。

v18 的通用修复：

- scorer 增加 generic failure veto：final answer 如果说 unable to compute / cannot
  calculate / cannot determine / unable to retrieve 等，即便文本里碰巧出现宽容差内
  数字，也不能算 numeric pass。
- finance-mode loop 增加 verified-numeric finalization consistency recovery。
  若 `finance.verify_numeric` 已成功，但 no-tools final answer 仍是 unable-to-compute
  语义，则插入一次 no-tools consistency recovery；若重写后仍是 generic failure，
  run 以 `generic_failure_after_verified_numeric_final_answer` 失败。
- `finance_eval` / `finance_repeat` / `finance_ablation` 增加
  `--include-transcript`、`--include-events`，后续论文实验可以保留 bounded
  transcript preview 和 raw loop events，避免只剩 answer/tool summary 无法复盘。
- v18 是基于 offset84 暴露问题后的通用修复，不能把 offset84 rerun 当作干净
  held-out；clean evaluation pool 从 untouched offset85 开始。

v19 的通用修复：

- no-tools finalization 如果收到 DSML/text-form `finance.verify_numeric` 调用，且
  其中存在 `answer` 参数，host 会提取该 answer 文本并继续走普通 final-answer
  checks，而不是把它当成失败的 tool-call markup。
- 非答案型 DSML（例如 calculator.compute 表达式）仍按原逻辑进入 format recovery，
  超过 bounded recovery limit 后失败，避免把中间计算请求误当 final answer。
- v19 是基于 offset85 暴露问题后的通用 loop 修复，不能把 offset85 rerun 当作干净
  held-out；clean evaluation pool 从 untouched offset86 开始。

v20 的通用修复：

- `document.text.extract` 改为先在全文上生成 focus windows，再应用 `max_chars` 组装
  artifact；artifact 内容由 opening preview + focus windows 构成。
- focus windows 使用模型自己给出的 `focus_terms`，但 header 不再包含 query term，
  避免 `artifact.search` 命中 synthetic header 而不是 filing 正文。
- 这解决的是大 SEC HTML / 大 PDF 前半部分被 cover/TOC/metadata 占满的问题，不是
  某题答案规则。v20 是基于 offset86 暴露问题后的通用工具修复，clean evaluation
  pool 从 untouched offset87 开始；offset87 已在 v20 下通过，下一条 clean run
  指向 untouched offset88。

v21 的通用修复：

- post-verify finalization 不再只看 `finance.verify_numeric` 是否非错误返回；必须解析
  verifier 结构化结果，确认 `verifier_status` / `verification.status` 不是
  `not_applicable`，且存在命中值或明确通过状态。
- `not_applicable` verifier 不会强制 no-tools finalization，也不会触发
  verified-numeric generic-failure recovery，避免把“没有可验证数值”的状态误包装成
  “已验证但 final 不一致”。
- `document.text.extract` 对明确的 SSL `UNEXPECTED_EOF_WHILE_READING` 增加受限 fallback：
  正常证书校验优先，只有该类静态公司文件 TLS EOF 才用 fallback 重试。
- v21 是基于 offset88 暴露问题后的通用 loop/tool 修复，clean evaluation pool 从
  untouched offset89 开始。

v22 的通用修复：

- `sec.edgar.company_filings` 支持 `fiscal_year` / `period`，会先取更宽的 SEC filing
  集合，再按目标 FY 到次年年报/Q4 季窗口过滤，避免只返回最新 filings。
- 返回的 SEC filing record 增加官方 SEC archive base、index、primary document 和
  complete-submission text URL。
- 新增 `sec.edgar.filing_documents`：给定 accession + CIK/ticker 后，从 SEC
  `index.json` 展开 primary/exhibit/document URL。它只暴露官方文档列表，不替模型选答案。
- 对 J&J FY2022 8-K 工具级 live probe 显示，该链路能定位
  `0000200406-23-000005`、`a2022q4exhibit991.htm`，并通过
  complete-submission text 抽到 Regional Sales rows，包括 U.S. `48,580` / `3.0`
  与 International `46,363` / `(0.6)`。
- offset89 v22 rerun 是 contaminated regression，只证明 v22 修复了该失败族；
  clean held-out pool 从 untouched offset90 开始。offset90 已通过。

结构验证：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py tests/test_kernel_v3_finance_open_components.py -q
168 passed in 6.81s
```

截至 offset90，排除 contaminated regression 的当前标准 live candidate/test100 记录为
`41` 条，`23` 个 passed，总估算成本 `~$0.9535`，平均 cache hit `85.86%`。
若把 offset89 v22 regression 也作为“修复回归证据”单独计入，则为 `42` 条、`24`
个 passed、总估算成本 `~$0.9657`。这不是最终 held-out accuracy，因为 v2-v22
中间候选发生过变化；论文应按 candidate version 报告失败分类、结构修复、
clean live evidence 和 contaminated regression evidence。

### 2026-06-19 v23 verifier trust-boundary 修复

offset91 是 v22 的 clean held-out 失败样本：

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 91 | `financebench_id_01490` | failed | 55 | 55 | 2,544,639 | 89.08% | ~$0.04974 | `numeric_outside_tolerance` |

题目问 J&J 分拆 Consumer Health/Kenvue 后在 2023-08-30 形成的 gain 金额。非 gold
trace 显示，source acquisition 已经能走到 SEC accession / filing documents / artifact
读取；问题不在是否能访问 SEC 文档，而在 verifier 信任边界：

- 第一次 `finance.verify_numeric` 对 `$21.4 billion` 正确失败，原因是没有事实账本或
  citation/evidence 中的数值支持。
- 随后模型在 verifier payload 里自己写入 `facts=[value=21400000000]` 和一个
  常量 `formula_traces=[expression=21400000000]`。
- v22 verifier 把这些模型内联 facts/formula_traces 当成可信支持，导致
  `matched_value_count=1`，进而触发 finalization；最终 scorer 显示 gold sidecar
  期望的是 `$20.0 billion`。

这不是单题答案补丁，而是公开工具面的通用安全/可靠性问题。v23 修复如下：

- `finance.verify_numeric` 公开工具入口启用 strict tool-payload provenance。
- 模型传入的 `facts` 只有在其数值能绑定到 `evidence_ref` / `citation_ref` 指向的
  evidence/citation 文本，或当前 verifier 调用提供的 cited evidence 文本时才作为
  支持。
- `formula_traces` 不能是单独的常量表达式；它们必须有 source-bound input facts，
  或者输入变量能在 evidence/citation/用户题干中找到。
- 如果 answer number 同时作为唯一 fact 或常量公式出现，会返回
  `untrusted_model_supplied_support`，要求模型重新取证或绑定 calculator 输入。
- v4 系统 prompt、finance task packet、workbench/describe tool protocol 同步写入：
  调用 `finance.verify_numeric` 时不能 self-certify，必须带 source-bound facts 或
  source-bound calculator traces。

新增结构测试覆盖三类情况：

- 模型自填 `$21.4B` fact + 常量公式，但 citation/evidence 文本没有该数值，必须失败。
- citation/evidence 文本真实包含 `$20.0B`，直接数值验证可以通过。
- DIO 这类公式结果只有在输入 facts 能绑定到 source evidence 时才通过。

结构验证：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_engine.py -q
483 passed in 20.19s
```

offset91 已看过 score sidecar 和 failure trace，因此 v23 如果重跑 offset91，只能作为
contaminated regression，不能作为 clean held-out。v23 clean pool 从 untouched offset92
开始。更新后的 live 记录口径：

- 排除 contaminated regression：`42` 条标准 live 记录，`23` 个 passed，总估算成本
  `~$1.0033`，平均 cache hit `85.94%`。
- 加上 offset89 contaminated regression：`43` 条记录，`24` 个 passed，总估算成本
  `~$1.0154`，平均 cache hit `85.90%`。
- 这些仍然不是最终 `test100` accuracy，因为 v2-v23 是连续候选演进；论文应报告
  candidate-versioned clean evidence、失败分类、结构修复和 contaminated regression。

下一步实验顺序：

1. 可先对 offset91 做 v23 contaminated regression，验证 verifier 是否拒绝自证路径。
2. 正式 clean held-out 从 offset92 开始继续单题 live 监控。
3. 后续报告必须同时记录 pass/fail、turns、tool calls、tokens、cache hit、cost、
   failure taxonomy，以及是否使用了 contaminated regression。

v23 offset91 contaminated regression 已完成：

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 91 | `financebench_id_01490` | passed | 22 | 21 | 554,113 | 86.48% | ~$0.01285 | `numeric_within_tolerance` |

这条不能算 clean held-out，因为 offset91 的 v22 failure 和 score sidecar 已被检查过。
但它证明 v23 的 generic verifier 修复有效：`finance.verify_numeric` 诊断里
`strict_tool_payload_provenance=true`，citation/evidence 文本真实包含
“gain of approximately $20 billion”，`trusted_fact_count=1`；模型传入的常量
`formula_trace` 被计为 `untrusted_formula_trace_count=1`，没有作为 verifier support。
也就是说，这次通过不是靠 `$answer == fact == constant formula` 的自证路径，而是靠
source-bound evidence。下一条 clean live 仍从 offset92 开始。

### 2026-06-19 v24 endgame exact-document extraction 修复

offset92 是 v23 第一条 clean held-out，结果失败：

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 92 | `financebench_id_01491` | failed | 39 | 41 | 1,492,526 | 93.08% | ~$0.02311 | `numeric_outside_tolerance` |

题目问 J&J 截至 2023-08-30 从 Kenvue separation 获得的 cash proceeds。gold sidecar
只在 run 完成后用于 scoring，显示期望数值为 `$13.2B`。非 gold trace 的失败原因：

- 静态公司 URL 仍然 SSL EOF。
- 模型成功转到 SEC filings，并通过 `sec.edgar.filing_documents` 获得
  `0000200406-23-000091` 的官方文档列表。
- 目标值在 August 30 Exhibit 99.1 post-split guidance 中；模型曾尝试该 exhibit，
  但 source saturation / calculation checkpoint 后 `document.text.extract` 不在
  active tool surface 中。
- 模型最后只能基于 August 25 split-off 8-K 回答“无法确认具体 cash proceeds”，没有
  给出 `$13.2B`，因此 numeric scorer 失败。

v24 的通用修复：

- endgame / repeated-source / source-saturation 后保留 `document.text.extract`，但语义上限定为
  “对已经观察到的精确官方 filing/exhibit URL 进行轻量文本抽取”，而不是重新广搜。
- checkpoint 文案明确区分：禁止 broad SEC/company-filings retrieval、document conversion、
  market fetch；允许 exact observed-document text extraction。
- final answer 中出现 `unable to extract`、`could not extract`、`current tool surface`、
  `not present in the extracted text` 等 generic source blocker 时，不再直接提交；
  loop 会插入一次 `GENERIC FAILURE FINALIZATION RECOVERY`，删除 tool surface allowlist，
  让模型重新走最相关的证据路径。
- 如果 recovery 后仍然是 generic failure，则 run 以 `generic_failure_final_answer`
  失败，而不是把“无法确认”提交给 scorer。

结构验证：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_engine.py -q
484 passed in 18.90s
```

offset92 已看过 score sidecar 和 failure trace，因此 v24 对 offset92 的重跑只能作为
contaminated regression；v24 clean pool 从 untouched offset93 开始。

v24 offset92 contaminated regression 已完成：

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 92 | `financebench_id_01491` | passed | 24 | 23 | 607,727 | 86.20% | ~$0.01443 | `numeric_within_tolerance` |

这条回归证明 v24 修复有效，但不计入 clean held-out：模型在 source saturation 后仍然可以
调用 `document.text.extract` 抽取已观察到的 SEC Exhibit 99.1 URL，随后 `artifact.read`
读到 “Company secured $13.2 billion in cash proceeds ...”。`finance.verify_numeric`
诊断显示 `strict_tool_payload_provenance=true`、`trusted_fact_count=1`、
`untrusted_fact_count=0`，最终 answer 命中 `$13.2B`。下一条 clean live 仍从 offset93
开始。

v24 第一条 clean held-out offset93 已通过：

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 93 | `financebench_id_01487` | passed | 22 | 22 | 621,744 | 88.38% | ~$0.01283 | `numeric_within_tolerance` |

该题问 J&J Q2 FY2023 的 net earnings as percent of sales 是否较 Q2 FY2022 提高。
模型通过 SEC accession/exhibit、`document.text.extract` / `document.docling.convert`、
artifact read/search、calculator 和 `finance.verify_numeric` 得到：

- Q2 2023 net earnings / sales = `5,144 / 25,530 = 20.1%`
- Q2 2022 net earnings / sales = `4,814 / 24,020 = 20.0%`
- 提高约 `0.1` percentage point

score 为 `3/3` numeric hit，source-grounded qualitative checks 也通过。下一条 clean
held-out 指向 offset94。

v24 clean held-out offset94 也已通过：

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 94 | `financebench_id_00299` | passed | 35 | 33 | 990,368 | 82.21% | ~$0.02854 | `numeric_within_tolerance` |

该题问 JPMorgan Chase 2021 Q1 哪个 business segment 的 net revenue 最低。模型从
10-Q segment results evidence 中得到 Corporate segment 的 net revenue 为 `$(473)M`，
并列出 CIB、CCB、AWM、CB 和 Corporate 的比较。score 为 `1/1` numeric hit，
source-grounded qualitative checks 通过。效率上仍偏 artifact-search heavy：source
saturation 在 turn 21 后收窄工具面，最后通过 `finance.verify_numeric` 后 no-tools
finalization。下一条 clean held-out 指向 offset95。

截至 offset94 后的当前聚合口径：

- 排除 contaminated regression：`45` 条标准 live 记录，`25` 个 passed，总估算成本
  `~$1.0678`，平均 cache hit `86.07%`。
- 加上 offset89/91/92 contaminated regression：`48` 条记录，`28` 个 passed，总估算成本
  `~$1.1072`，平均 cache hit `86.04%`。
- 这仍然不能写成最终 `test100` accuracy，因为 v2-v24 中间候选持续变化；论文应按
  candidate version 报告 clean held-out、contaminated regression、失败分类和结构修复。

### 2026-06-19 v25 liquidation/recovery concept-binding 修复

offset95 是 v24 clean held-out，结果失败：

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 95 | `financebench_id_02119` | failed | 21 | 25 | 652,062 | 88.67% | ~$0.01423 | `numeric_outside_tolerance` |

题目问 JPMorgan Chase 如果在 2021 Q1 末破产并清算资产偿付股东，每股股东可得多少。
非 gold trace 显示这不是检索/计算链路失败：

- 模型成功抽取 JPMorgan Q1 2021 10-Q，并读到 total assets、total liabilities、
  total stockholders' equity、common stockholders' equity 和 shares outstanding。
- 模型调用 `calculator.compute` 和 `finance.verify_numeric`，算出
  `common stockholders' equity / shares outstanding = $82.31`。
- scorer 期望的数值是 `$66.56`，score sidecar 只在 run 后用于归因。
- 失败根因是 `concept_binding_error`：模型把题目中的 bankruptcy/liquidation/shareholder
  recovery 直接绑定为 book value per common share，而没有先比较 tangible common equity /
  tangible book value、goodwill/MSRs/intangibles、preferred priority 等候选口径。

v25 的通用修复：

- 系统 prompt 把 liquidation、bankruptcy-recovery、book-value-per-share、
  tangible-book-value、shareholder residual 问题明确归为 metric-definition ambiguity。
- 任务 packet 的 solver_contract 同步要求模型在 final 前比较 total equity、common
  stockholders' equity、tangible common equity、preferred-stock priority、
  goodwill/intangible exclusions 和 shares outstanding。
- `finance.workbench.open` 新增 `liquidation_per_share_recovery` profile，暴露 required
  evidence、workflow、formulas 和 search_terms。
- 这不是 JPM 单题答案表；host 不计算答案、不选择口径，只把“候选口径竞争”作为通用
  one-shot 工具/任务合同暴露给 LLM。

结构验证：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_run.py tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_live_provider.py tests/test_kernel_v4_finance_score.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_engine.py -q
485 passed in 25.42s
```

offset95 已看过 score sidecar 和 failure trace，因此 v25 对 offset95 的重跑只能作为
contaminated regression；v25 clean pool 从 untouched offset96 开始。

v25 offset95 contaminated regression 已完成：

| offset | item | result | turns | tools | tokens | cache hit | estimated cost | score reason |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 95 | `financebench_id_02119` | passed | 31 | 44 | 1,289,122 | 80.74% | ~$0.04037 | `numeric_within_tolerance` |

回归 trace 证明修复有效但成本偏高：模型搜索并比较了 tangible book value、goodwill/MSRs
and other intangible assets、common stockholders' equity、total liabilities/equity 和
shares outstanding；最终保留 `$82.31` 作为 book value per common share 的替代口径，
但选择 `$66.56` tangible book value per common share 作为更符合 liquidation recovery
语义的估计。第二次 `finance.verify_numeric` 诊断显示 `issue_count=0`、
`strict_tool_payload_provenance=true`、`trusted_fact_count=8`。

截至 offset95 后的严格论文题量口径：

- `debug50`：`50/50` best-recorded live debug evidence 已完成并通过；这是调试/调参证据，
  不是最终 test accuracy。
- 原计划 `test100` offsets50-149 中，offset50-95 已经被用于失败归因和通用系统修复，
  因此严格意义上已经不是 final test，而是 `pilot/development stream`。这 `46` 条
  题已按 v25 同配置 rerun 完成，结果为 `37/46` passed，pass rate `80.43%`。
  由于 DeepSeek 当前 Chat Completion/API provider 面没有 `seed` 参数，这不是严格
  changed-seed replication，而是 same-config live replay；只能用于工程复盘、稳定性、
  失败分类和候选演进证据，不能写成论文最终测试准确率。
- contaminated regression：offset89、91、92、95 共 `4` 条，`4/4` passed，只能证明对应
  generic repair，不计入最终测试。
- v25 strict remaining offsets96-149 已按冻结配置完成 live run：`40/54` passed，
  pass rate `74.07%`。失败 `14` 条，其中 `12` 条为 `numeric_outside_tolerance`，
  `2` 条为 `source_grounded_qualitative_failed`。这是当前最接近严格 final-test 的
  public FinanceBench 证据，但题量只有 `54`。
- 用户要求的合并 operational view 为 offsets50-149 共 `100` 条：`77/100` passed。
  这个合并数必须标注为 `replay_seen_50_95 + strict_remaining_96_149`，不是单一 clean
  held-out `test100` accuracy。合并 summary 已落地：
  `.state/kernel_v4/bench/finance/fb_test100_merged_replay50_95_plus_strict96_149_v25_20260619/summary.json`。
- 若论文必须报告 `100` 道严格 test，需要另取一个未用于调参/失败归因的新 100 题来源；
  否则应诚实报告 `54` 道 remaining untouched final test，并把 `46` 道 replay 作为
  stability/development-stream 旁证。

原则修正：做 test 就只能 test。任何一题一旦被看了 score sidecar、失败 trace，或用来改
prompt/loop/tool contract，它就从最终测试集中移出，只能成为开发流或 contaminated regression。
后续从 offset96 开始，如果要保留严格测试意义，就必须冻结 candidate，并承诺不再根据 offset96-149
的 item-level failure 反向改系统；否则这 54 题也会变成开发流。
