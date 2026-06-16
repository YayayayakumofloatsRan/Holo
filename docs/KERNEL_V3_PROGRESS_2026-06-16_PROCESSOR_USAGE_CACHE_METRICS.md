# Kernel v3 Progress: Processor Usage, Cache, and Benchmark Observability

日期：2026-06-16  
范围：金融做题能力、通用能力基座、成本/cache 可观测性  
状态：已落地本地实现与测试

---

## 1. 本次改进

本次从 LangGraph / Semantic Kernel / Hermes 审阅结论中落地了一个底座能力：把 processor 层的 token、cache、耗时、错误和 task type 分布做成统一统计口径。

新增能力：

- `kernel_v3.processors.usage.summarize_processor_usage`
- `finance.trace_metrics` 中新增 processor 级分解
- `general capability gauntlet` live usage 中复用同一统计口径
- `finance benchmark summary` 汇总 processor cache hit/miss、task type counts、processor error counts

这属于 observability/runtime metrics，不参与答案选择、路由判断或 benchmark scoring。

---

## 2. 为什么这对今晚目标重要

用户已经明确：cache 命中率直接决定成本和速度；金融能力仍是第一优先级，通用能力基座也必须保住。

过去的问题是：我们能看到单题总 token 和部分 retrieval 指标，但很难回答：

- `task.compile` 花了多少？
- `finance.slot_bind` 是否是最大失败点？
- `finance.numeric_judge` 是否频繁 repair？
- `synthesizer.answer` 是否 cache 命中低？
- 一道题失败到底是模型处理器失败、工具失败、检索失败，还是 verifier 失败？
- 通用 gauntlet 和金融 benchmark 是否使用同一套成本统计？

现在每道题的 `trace_metrics` 可以暴露 processor 层分解，便于后续大规模 FB/FAB/FinAgent live run 做真正的瓶颈诊断。

---

## 3. 新增指标

单题金融 trace metrics 新增：

```text
processor_prompt_cache_hit_tokens
processor_prompt_cache_miss_tokens
processor_prompt_cache_hit_ratio
processor_usage_by_task_type
processor_usage_by_provider_model
processor_status_counts
processor_error_counts
```

金融 benchmark summary 新增：

```text
processor_prompt_cache_hit_tokens
processor_prompt_cache_miss_tokens
processor_prompt_cache_hit_ratio
processor_task_type_counts
processor_error_counts
```

通用 capability summary 新增：

```text
processor_call_count
processor_duration_ms
processor_task_type_counts
```

---

## 4. 与 Kernel v3 原则的关系

这次改动遵守 Kernel v3 的硬约束：

- 没有增加关键词规则。
- 没有增加阈值规则。
- 没有让 host 选择金融答案。
- 没有读取 gold/reference。
- 没有改变 LLM-owned slot binding、numeric judge 或 synthesizer 的语义职责。

host 的角色仍然是：

- 记录 processor 调用。
- 汇总 usage/cache/latency/error。
- 为后续 benchmark 分析提供证据。

这和 LangGraph 的 observability、Semantic Kernel 的 telemetry、Hermes 的显式 tool loop 思想一致。

---

## 5. 对后续金融迭代的直接用法

下一次跑 FB/FAB/FinAgent 时，应在 summary 里重点看：

1. `processor_prompt_cache_hit_ratio`
   - 判断 prompt prefix 是否稳定。
   - 判断 task.compile / slot_bind / numeric_judge 是否需要进一步 freeze stable contract。

2. `processor_task_type_counts`
   - 判断是否出现过度 repair 或重复 synthesis。
   - 判断简单题是否陷入不必要的长 loop。

3. `processor_error_counts`
   - 定位 JSON invalid、provider failed、budget exceeded、schema failed。

4. `processor_usage_by_task_type`
   - 对单题进行诊断：是 retrieval workbench 太贵，还是 slot_bind 太贵，还是 final synthesis 太贵。

这些指标会服务于下一阶段三条线：

- 金融能力：找出 FB/FAB 错题的真实 bottleneck。
- 通用能力：保证普通任务不会被金融长 loop 污染。
- 成本/cache：用数据推动 prompt prefix freeze 和上下文压缩。

---

## 6. 验证

已运行：

```bash
.venv/bin/python -m py_compile kernel_v3/processors/usage.py kernel_v3/bench/finance.py kernel_v3/bench/general.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_general_capability_gauntlet.py

.venv/bin/python -m pytest tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_general_capability_gauntlet.py tests/test_kernel_v3_finance_benchmark.py -q
```

结果：

```text
55 passed in 279.14s
```

---

## 7. 追加落地：CLI/Report Processor Breakdown

同日追加完成：

- `bench finance` 实时 progress 行现在显示：
  - `proc_cache`
  - `proc_hit`
  - `proc_miss`
  - `proc_tasks`
  - `proc_errors`
- `bench finance-report` 现在聚合并渲染：
  - `processor_call_count`
  - `processor_error_count`
  - `processor_prompt_cache_hit_tokens`
  - `processor_prompt_cache_miss_tokens`
  - `processor_prompt_cache_hit_ratio`
  - `processor_task_type_counts`
  - `processor_provider_model_counts`
  - `processor_status_counts`
  - `processor_error_counts`

这使下一轮 FB/FAB live run 不需要事后手工挖 journal，就能直接看到 `task.compile`、`finance.slot_bind`、`synthesizer.answer`、`finance.numeric_judge` 等 processor 的调用分布、cache 状态和错误簇。

该改动仍只属于观测与报告层：

- 不参与 planner 路由。
- 不参与金融事实选择。
- 不参与 score/pass 判定。
- 不读取 gold/reference。
- 不改变 LLM-owned slot binding 或 synthesis。

追加验证：

```bash
.venv/bin/python -m py_compile kernel_v3/cli.py kernel_v3/bench/report.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py

.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py tests/test_kernel_v3_finance_benchmark.py -q
```

结果：

```text
48 passed in 233.43s
```

---

## 8. 下一步

建议下一步继续围绕金融能力推进：

1. 跑一次小规模 FB debug live，用新增 processor breakdown 判断当前瓶颈。
2. 如果 `finance.slot_bind` 仍是错误集中点，优先改 slot binding prompt packet 和 JSON repair。
3. 如果 `synthesizer.answer` 仍产生 unsupported number，继续强化 AnswerCleanlinessVerifier/repair loop。
4. 如果 cache ratio 低，冻结 processor prompt stable prefix，把动态 facts/context 后置。
5. 再进入 FB holdout / FAB public 的更大规模 live 统计。

---

## 9. 追加落地：FormulaTrace Support Index

同日继续补强金融答案合成链路：

- `RetrievalReport.diagnostics` 现在可以携带 `finance_formula_trace_support`。
- 该字段把每个 `FormulaTrace` 显式连接到：
  - `input_fact_ids`
  - compact input facts
  - `evidence_refs`
  - `citation_refs`
  - raw source fields such as concept/label/form/fp/source_uri
- `synthesizer.answer` prompt 现在会收到该字段，并被明确要求用它把 calculator output 连接回输入事实、证据和引用。
- `finance.numeric_judge` prompt 现在也收到同一 `formula_trace_support`，用于判断核心数字是否由 FormulaTrace 输入事实、证据和引用支撑。
- compact finance synthesis rescue packet 也携带同一 support index。

这解决一个真实能力问题：过去模型虽然能看到 formula trace 和 fact ledger，但需要自己在长上下文里反查 `formula.input_fact_ids -> facts -> citations`。现在这个拓扑关系被 host 结构化暴露给 LLM，使 final synthesis 和 finance.numeric_judge 更容易围绕“计算值 + 公式输入 + 证据引用”达成一致。

边界保持不变：

- host 不选择最终答案。
- host 不判断哪个 metric/period 是正确答案。
- host 不读取 gold/reference。
- support index 只暴露已有 trace/fact/citation/evidence 关系。
- 最终语义判断仍由 LLM synthesis / finance.numeric_judge 完成。

追加验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/processors/adapters.py tests/test_kernel_v3_finance_engine.py

.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "formula_trace_support or formula_trace_policy or numeric_judge_prompt_preserves_capital_intensity_roa_trace_context"

.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "retrieval_finalization_repairs_unsupported_finance_numbers_with_calculator_trace or source_grounded_finance_fallback_uses_cited_evidence_when_synthesizer_adds_unsupported_number or retrieval_finalization_fallback_preserves_dcf_model_outputs_and_assumptions or finance_numeric_judge"

.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "numeric_judge_prompt_preserves_capital_intensity_roa_trace_context or formula_trace_support"
```

结果：

```text
4 passed, 191 deselected
6 passed, 189 deselected
3 passed, 192 deselected
4 passed, 191 deselected
```

---

## 10. 追加落地：FormulaTrace Support Coverage Metrics

同日继续把 FormulaTrace support index 从 prompt 能力推进到 benchmark 可观测指标。

新增 per-item trace metrics：

```text
formula_trace_support_count
formula_trace_fact_linked_count
formula_trace_citation_linked_count
formula_trace_evidence_linked_count
formula_trace_input_fact_missing_count
formula_trace_fact_link_rate
formula_trace_citation_link_rate
formula_trace_evidence_link_rate
```

新增 finance benchmark summary/report 指标：

```text
average_formula_trace_support_count
formula_trace_fact_link_rate
formula_trace_citation_link_rate
formula_trace_evidence_link_rate
```

`bench finance` 实时 progress 行现在也显示：

```text
trace_link=<percent>
trace_cite=<percent>
```

意义：

- 过去只能看到 `formula_trace_count`，即“有没有 calculator trace”。
- 现在可以看到 FormulaTrace 是否真的连到 input facts、citations、evidence。
- 下一轮 FB/FAB live run 可以判断失败到底是没有计算、计算没有事实支撑、还是最终 synthesis/numeric_judge 没用好已有支撑。

边界：

- 这些是 observability metrics。
- 不参与答案选择。
- 不参与 scorer pass/fail。
- 不读取 gold/reference。
- 不改变 LLM-owned slot binding 或 final synthesis。

追加验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py kernel_v3/bench/report.py kernel_v3/cli.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py

.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "trace_metrics_include_substrate_and_source_data or summary_includes_generic_substrate_rates or progress_prints_processor_breakdown"

.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q -k "processor_breakdown"

.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q
```

结果：

```text
3 passed, 39 deselected
1 passed, 5 deselected
48 passed in 238.52s
```

---

## 11. 追加落地：FormulaTrace Support Gap Recommendations

`bench finance-report` 的推荐逻辑现在会读取 FormulaTrace support coverage：

- 当 `formula_trace_fact_link_rate < 90%`，提示检查 `FormulaTrace.input_fact_ids` 与 `finance_fact_ledger` id 是否对齐。
- 当 `formula_trace_citation_link_rate < 90%`，提示修复 computed values 到 citation refs 的 provenance。
- 当 `formula_trace_evidence_link_rate < 90%`，提示修复 computed values 到 evidence refs 的 provenance。

这让下一轮 live benchmark 的报告能直接区分：

- 没有 calculator trace；
- 有 calculator trace，但没有连回模型选中的 facts；
- 有计算和 facts，但 citation/evidence provenance 不完整；
- provenance 已完整，问题转向 synthesis / numeric_judge 是否正确使用已有支撑。

该逻辑仍只用于报告建议，不参与运行时答案选择或评分。

追加验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/report.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q -k "processor_breakdown"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q
```

结果：

```text
1 passed, 5 deselected
6 passed in 67.51s
```

---

## 12. 追加落地：Weak Item Trace-Support Columns

`bench finance-report` 的 weak item 表现在新增：

```text
Trace link
Trace cite
Trace evidence
```

这让每一道弱项题都能直接显示：

- FormulaTrace 是否连回 `finance_fact_ledger` facts；
- FormulaTrace 是否连到 citation refs；
- FormulaTrace 是否连到 evidence refs。

实际排查时不再只能看全局平均值；可以在弱项列表里直接筛出 provenance 缺失的具体题目，再打开对应 behavior graph / trace refs 做下一步修复。

追加验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/report.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q -k "processor_breakdown"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q
```

结果：

```text
1 passed, 5 deselected
6 passed in 69.42s
```

---

## 13. 追加落地：Benchmark Behavior Graph Trace Provenance

`bench finance-graph` 现在也会把 FormulaTrace provenance 纳入图级诊断。

新增 benchmark graph diagnostics：

```text
average_formula_trace_support_count
formula_trace_fact_link_rate
formula_trace_citation_link_rate
formula_trace_evidence_link_rate
formula_trace_input_fact_missing_count
```

每个 `benchmark_item` 节点 metadata 也新增：

```text
formula_trace_support_count
formula_trace_fact_link_rate
formula_trace_citation_link_rate
formula_trace_evidence_link_rate
formula_trace_input_fact_missing_count
```

DOT 输出新增 metric nodes：

```text
Avg trace support
Trace fact link
Trace citation link
Trace evidence link
Missing trace facts
```

意义：

- `finance-report` 可以从表格定位弱项；
- `finance-graph` 可以从拓扑/节点层定位 provenance 断点；
- 下一轮 live benchmark 可以直接判断：问题是没有 FormulaTrace、FormulaTrace 没有 input facts、还是 facts 没有 citation/evidence 链接。

边界：

- 该改动只读取已有 `trace_metrics`。
- 不参与答案选择。
- 不参与评分。
- 不读取 gold/reference。
- 不改变 LLM-owned slot binding、planner 或 synthesis。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/behavior_graph.py tests/test_kernel_v3_behavior_graph.py
.venv/bin/python -m pytest tests/test_kernel_v3_behavior_graph.py -q
```

结果：

```text
6 passed in 66.39s
```

---

## 14. 追加落地：Benchmark Behavior Graph Processor/Cache Topology

`bench finance-graph` 现在进一步接入 processor/cache 层的图级诊断和节点。

新增 benchmark graph diagnostics：

```text
processor_prompt_cache_hit_tokens
processor_prompt_cache_miss_tokens
processor_prompt_cache_hit_ratio
processor_task_type_counts
processor_provider_model_counts
processor_status_counts
processor_error_counts
```

每个 `benchmark_item` 节点 metadata 也新增：

```text
processor_prompt_cache_hit_tokens
processor_prompt_cache_miss_tokens
processor_prompt_cache_hit_ratio
processor_task_types
processor_error_counts
```

新增图节点类型：

```text
benchmark_processor_task_type
benchmark_processor_error
```

新增图边：

```text
benchmark_item -> benchmark_processor_task_type: uses_processor
benchmark_item -> benchmark_processor_error: processor_failed_with
benchmark -> benchmark_processor_task_type: has_processor_task_type
benchmark -> benchmark_processor_error: has_processor_error
```

意义：

- 图上可以直接看到 `task.compile`、`finance.slot_bind`、`synthesizer.answer` 等 LLM processor 是否集中失败；
- 可以把弱项题连接到具体 processor error cluster，例如 `json_invalid`；
- 可以同时观察 processor cache 命中率，服务后续成本优化和 prompt 稳定排序；
- 这让 `finance-graph` 更接近真实 agent loop 拓扑：模型处理节点、工具/证据链、验证链和最终结果都能被同一张图诊断。

边界：

- 该改动只消费每题已有 `trace_metrics`；
- 不参与答案选择；
- 不参与评分；
- 不读取 gold/reference；
- 不改变 LLM planner、slot binding、numeric judge 或 synthesis。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/behavior_graph.py tests/test_kernel_v3_behavior_graph.py
.venv/bin/python -m pytest tests/test_kernel_v3_behavior_graph.py -q
```

结果：

```text
6 passed in 64.59s
```

---

## 15. 追加落地：Finance Slot-Bind Structured Repair Feedback

`finance.slot_bind` 的模型修复链路现在会把 host schema/JSON 校验错误结构化后反馈给模型。

新增 repair feedback schema：

```text
holo.kernel_v3.finance_slot_bind_repair_feedback.v1
```

字段包括：

```text
error_code
category
field
expected_type
required_fields
optional_fields
allowed_decisions
repair_checklist
host_role
model_role
```

支持的错误分类：

```text
missing_required_field
invalid_field_type
json_root_not_object
malformed_json
schema_or_parse_error
```

这会进入：

- `finance.slot_bind` repair prompt 的 `previous_failure.structured_feedback`；
- `finance_slot_bind` journal record 的 `repair_feedback`。

意义：

- 如果第一次 `finance.slot_bind` 输出坏 JSON、缺字段或字段类型错，第二次模型能看到明确的 schema 修复清单；
- host 不替模型做 fact-to-slot binding，也不选择事实或公式；
- host 只把 JSON/schema 层错误转成可恢复的 observation；
- 这更接近标准 agent loop：模型输出 -> host 校验 -> observation -> 模型修复 -> host 执行。

边界：

- 不参与答案选择；
- 不参与评分；
- 不读取 gold/reference；
- 不添加金融语义关键词规则；
- 不让 host 选择 metric、period、fact row 或公式含义。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "slot_bind_repairs_malformed_json"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "task_compiler_retries_invalid_model_json or slot_bind_repairs_malformed_json or finance_slot_bind_prompt_exposes_raw_fields"
```

结果：

```text
1 passed, 194 deselected in 0.73s
3 passed, 192 deselected in 0.29s
```

---

## 16. 追加落地：Finance Task-Compile Structured Retry Feedback

`task.compile` 的模型重编译链路现在也会把 host JSON/schema 校验错误结构化后反馈给模型。

新增 retry feedback schema：

```text
holo.kernel_v3.task_compile_repair_feedback.v1
```

字段包括：

```text
error_code
category
field
expected_type
required_fields
optional_fields
repair_checklist
host_role
model_role
```

支持的错误分类：

```text
missing_required_field
invalid_field_type
json_root_not_object
malformed_json
schema_or_parse_error
```

这会进入 `task.compile` retry prompt 的：

```text
previous_failure.structured_feedback
```

意义：

- `task.compile` 是金融 agent 的上游编译节点，决定 evidence specs、transform specs、slot frame 和 tool chain plan；
- 如果第一次模型输出坏 JSON 或 schema 不匹配，第二次重编译能看到明确的修复清单；
- host 仍不替模型判断任务语义，不选择指标、期间、来源或最终公式含义；
- 这把 `task.compile -> host schema validation -> model retry` 做成更标准的 observation loop。

边界：

- 不参与答案选择；
- 不参与评分；
- 不读取 gold/reference；
- 不新增金融语义关键词规则；
- 不让 host semantic fallback 覆盖模型编译判断。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/finance/task_compiler.py kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "task_compiler_retry_prompt_has_structured_feedback or task_compiler_retries_invalid_model_json or slot_bind_repairs_malformed_json"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "finance_task_compile_prompt or task_compiler_retry_prompt_has_structured_feedback or task_compiler_retries_invalid_model_json or slot_bind_repairs_malformed_json or finance_slot_bind_prompt_exposes_raw_fields"
```

结果：

```text
3 passed, 193 deselected in 0.71s
6 passed, 190 deselected in 0.30s
```

---

## 17. 追加落地：Structured Repair Metrics for Benchmark Runs

`bench finance` / `bench finance-report` 现在会统计结构化输出恢复链路是否真正生效。

新增 per-item trace metrics：

```text
task_compile_retry_count
task_compile_retry_success_count
finance_slot_bind_repair_attempt_count
finance_slot_bind_repair_success_count
synthesizer_json_repair_attempt_count
synthesizer_json_repair_success_count
structured_repair_attempt_count
structured_repair_success_count
structured_repair_success_rate
```

新增 finance benchmark summary/report 指标：

```text
task_compile_retry_count
task_compile_retry_success_count
finance_slot_bind_repair_attempt_count
finance_slot_bind_repair_success_count
synthesizer_json_repair_attempt_count
synthesizer_json_repair_success_count
structured_repair_attempt_count
structured_repair_success_count
structured_repair_success_rate
```

`bench finance` progress 行新增：

```text
repair=<success_rate>
repair_n=<successes>/<attempts>
json_repair=<synthesizer_json_repair_successes>/<synthesizer_json_repair_attempts>
```

意义：

- 能直接观察 `task.compile` retry 是否把坏 JSON/schema 错误恢复成可执行 program；
- 能直接观察 `finance.slot_bind` repair 是否把坏 JSON/schema 错误恢复成可执行 formula plan；
- 能直接观察 `synthesizer.answer` JSON repair 是否把坏 final synthesis JSON/schema 恢复成可用 final answer；
- 如果 processor error 很多但 structured repair 成功率高，说明 agent loop 有自恢复能力；
- 如果 structured repair 成功率低，应先修 schema feedback / prompt contract，而不是直接扩大题量。

边界：

- 这些是观测指标；
- 不参与答案选择；
- 不参与评分；
- 不读取 gold/reference；
- 不改变 LLM task.compile、slot binding、numeric judge 或 synthesis 的语义判断。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py kernel_v3/bench/report.py kernel_v3/cli.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "trace_metrics_include_structured_repair_recovery or summary_includes_generic_substrate_rates or progress_prints_processor_breakdown"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q -k "processor_breakdown"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q
```

结果：

```text
3 passed, 40 deselected in 0.39s
1 passed, 5 deselected in 0.35s
6 passed in 70.70s
```

同日追加把 `synthesizer.answer` JSON repair 纳入 structured repair metrics，最新聚焦验证：

```text
3 passed, 40 deselected in 0.36s
1 passed, 5 deselected in 0.34s
6 passed in 70.97s
```

---

## 18. 追加落地：Synthesizer Structured Repair Feedback

`synthesizer.answer` 的 JSON/schema repair retry 现在会收到结构化 `repair_feedback`，与 `task.compile` 和 `finance.slot_bind` 的结构化 repair 口径对齐。

新增 retry prompt 字段：

```text
repair_feedback.schema = holo.kernel_v3.synthesizer_repair_feedback.v1
repair_feedback.category
repair_feedback.error_code
repair_feedback.required_fields
repair_feedback.optional_fields
repair_feedback.host_role
repair_feedback.model_role
repair_feedback.repair_checklist
```

覆盖的错误类型：

```text
missing_required_field
invalid_field_type
json_root_not_object
malformed_json
schema_or_parse_error
```

意义：

- final answer 合成如果因为坏 JSON、缺字段、字段类型错误失败，模型会收到明确的结构化修复反馈；
- host 只暴露 schema/parse 失败原因，不选择答案、不选择事实、不生成金融语义结论；
- repair request 的 processor parameters 记录 `repair_feedback_schema` 和 `repair_feedback_category`，后续可纳入 benchmark processor 统计；
- `bench finance` / `bench finance-report` 已纳入 `synthesizer_json_repair_attempt_count` 和 `synthesizer_json_repair_success_count`；
- 对金融题尤其重要，因为 final synthesis 是 FormulaTrace、fact ledger、citation refs、limitations 汇合点，坏 JSON 不应直接浪费一次 live 题目。

边界：

- 不增加关键词规则；
- 不增加阈值规则；
- 不读取 gold/reference；
- 不让 host 选择最终数字、事实、metric 或 period；
- repair checklist 只要求模型返回合法 JSON 并保持引用/evidence id 合规。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/processors/adapters.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q -k "synthesizer_retries_invalid_json_once"
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q -k "synthesizer"
```

结果：

```text
1 passed, 48 deselected in 0.37s
5 passed, 44 deselected in 0.32s
```

---

## 19. 追加落地：Finance Synthesis Unsupported Threshold Guard

复核 `fb_debug_o002_l001_strict_20260615_v9/v17/v18/v19/v20` 后，发现同一道 3M FY2022 capital-intensity 题的主要不稳定点不是事实完全找不到，而是 final synthesis 偶尔引入无来源的行业阈值、comparison cutoff、benchmark percentage 或 rule-of-thumb number，例如把资本密集判断写成依赖某个未被证据支持的百分比门槛。

这会触发 `finance.numeric_judge` 和 numeric verifier 的 `unsupported_answer_number`，导致可解题在最后阶段失败。

本次改动：

- 把已有 runtime diagnostics 中的 unsupported comparison-number policy 前置到 `synthesizer.answer` 首轮 `answer_requirements`；
- 明确要求金融 benchmark-style 答案不得引入 generic industry thresholds、comparison cutoffs、benchmark percentages、multiples、ranges 或 rule-of-thumb numbers，除非这些数字出现在 provided facts/evidence/citations/FormulaTrace values；
- 对 capital intensity 这类定性分类，要求模型使用 supported FormulaTrace lenses and values；如果没有 source-backed threshold，则用文字做定性判断，不额外添加 unsupported threshold percentages。

边界：

- 这不是 host 阈值规则；
- host 不判断“多少百分比才是 capital intensive”；
- LLM 仍然负责语义判断；
- host 只把 numeric provenance contract 提前暴露给 synthesizer，减少坏答案进入 verifier repair loop。

动机：

- 提升 FB/FAB 中定性金融判断题的稳定性；
- 降低 synthesis gate repair 次数和 token 成本；
- 避免通过无来源经验阈值导致答案被 numeric verifier 拒绝。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/processors/adapters.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q -k "synthesizer_prompt_uses_evidence_and_citation_previews_not_raw_bodies"
```

结果：

```text
1 passed, 48 deselected in 0.36s
```

---

## 20. 追加落地：Synthesizer Prompt Cache-Friendly Layout

当前 live debug 显示，金融题可以被解出，但 token 消耗仍然偏高。例如 `fb_debug_o002_l001_strict_20260615_v20` 单题通过，平均 total tokens 为 537,178。这说明能力链条已经能闭合，但成本/cache 仍是核心瓶颈。

本次改动：

- 将 `synthesizer.answer` prompt 的静态大段内容前置；
- prompt 顶层字段顺序从动态 task/evidence 先行，调整为：

```text
contract
answer_requirements
task_goal
interaction_preferences
...
retrieval_report
evidence
citations
```

意义：

- `contract` 与 `answer_requirements` 在同类题目间高度稳定，适合作为 provider prompt cache 前缀；
- 动态 `task_goal`、retrieval report、evidence、citations 后置，减少每题一开始就破坏 prefix cache 的概率；
- 不改变答案选择、不改变评分、不改变工具调用，只改变 prompt layout；
- 与 LangChain middleware / LangGraph node contract / Semantic Kernel filter 的共同方向一致：稳定 contract 前缀，动态工作集后置。

边界：

- 不加入关键词或阈值规则；
- 不让 host 做语义判断；
- 不裁剪 evidence 本身，只重排 prompt 的静态与动态区块。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/processors/adapters.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q -k "synthesizer"
```

结果：

```text
5 passed, 44 deselected in 0.38s
```

Live 状态：

- 当前 WSL shell 未暴露 `DEEPSEEK_API_KEY`，因此本轮没有启动新的 DeepSeek live benchmark；
- 下一次 live run 应优先重跑 `financebench_id_00499` 或 `--offset 2 --limit 1` 的 FB debug 项，观察 unsupported threshold 是否减少、synthesis gate repair 次数是否下降、processor prompt cache ratio 是否开始出现。

---

## 21. 追加落地：Provider-Agnostic Prompt Cache Usage Normalization

`kernel_v3.processors.usage.coerce_usage` 原先已经保留 DeepSeek 顶层字段：

```text
prompt_cache_hit_tokens
prompt_cache_miss_tokens
```

本次补齐了 OpenAI-compatible / provider-compatible 常见字段：

```text
prompt_tokens_details.cached_tokens
input_token_details.cache_read
input_token_details.cache_read_input_tokens
input_token_details.cached_tokens
```

归一化后统一写入：

```text
prompt_cache_hit_tokens
prompt_cache_miss_tokens
prompt_cache_hit_ratio
```

当 provider 只返回 cached prompt tokens、没有显式 miss tokens 时，Holo 使用：

```text
prompt_cache_miss_tokens = max(prompt_tokens - cached_tokens, 0)
```

意义：

- 后续即使 DeepSeek / OpenAI-compatible / local compatible provider 的 usage 字段不同，finance benchmark、general gauntlet、report、CLI progress 仍然使用同一套 cache 指标；
- 更适合做跨 provider 的成本实验；
- 让 `synthesizer.answer` / `task.compile` 的 stable-prefix 优化能在 report 里被观察到；
- 补充测试固定 `planner.propose` 与 `evaluator.assess` 的 stable-prefix prompt 顺序，避免后续把动态 context/observation 提前破坏 cache；
- 补充测试固定 `task.compile` retry 与 `finance.slot_bind` repair 的 stable-prefix 顺序，确保结构化修复链路仍然是 contract/output_schema 在前，previous_failure 与动态 packet 在后；
- 该改动只属于 usage normalization，不参与答案选择、路由、评分、slot binding 或 verifier 判断。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/processors/usage.py tests/test_kernel_v3_processor_usage.py
.venv/bin/python -m pytest tests/test_kernel_v3_processor_usage.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "trace_metrics_include_processor_usage_breakdown or summary_includes_generic_substrate_rates or progress_prints_processor_breakdown"
.venv/bin/python -m pytest tests/test_kernel_v3_general_capability_gauntlet.py -q -k "usage or cache or summary"
```

结果：

```text
9 passed in 0.29s
2 passed, 41 deselected in 0.27s
2 passed, 5 deselected in 0.29s
10 passed in 0.34s
2 passed, 194 deselected in 0.76s
6 passed, 190 deselected in 0.29s
```

---

## 24. 追加落地：Strict-Failed / Internal-Verifier-Passed 诊断

金融 benchmark 的后续论文/报告需要区分两类失败：

1. agent 真的没有解决问题；
2. agent 输出有内部数值/验证支持，但 strict scorer、格式、单位、最终合成或 scoring normalization 没有对齐。

本次新增纯 post-run analytics 指标：

```text
strict_failed_internal_verifier_passed_count
strict_failed_internal_verifier_passed_rate
```

定义：

- benchmark item 的严格 `status == failed`；
- `scorecard.answer_present == true`；
- `trace_metrics.numeric_verifier_status == passed` 或 `trace_metrics.verifier_gate_status == passed`。

含义：

- 这是人工复核/能力诊断候选；
- 不改变 pass/fail；
- 不放宽 scorer；
- 不进入 prompt；
- 不读取 gold 进入运行时；
- 不让 host 替模型选择答案；
- 不构成规则刷分。

落地位置：

- `FinanceBenchmarkSummary` 新增上述两个字段；
- `bench finance-report` 的 markdown/html/json report 新增同一 summary 指标；
- Weak Items 表新增 `Internal support` 列；
- `behavior_graph` benchmark diagnostics 也暴露同一指标；
- report recommendations 会提示复核这类严格失败项，帮助分离真实能力失败和 scoring/format/synthesis 对齐失败。

这对下一轮金融大规模跑题很重要：如果 strict failed 中有一批内部 verifier 已经通过，就应该优先检查 final answer formatting、requested unit normalization、citation preservation 或 scorer false negative；如果 strict failed 且内部 verifier 也失败，才是更纯粹的 retrieval/slot binding/calculation 能力问题。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py kernel_v3/bench/report.py kernel_v3/behavior_graph.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "strict_failures_with_internal_verifier_support or summary_includes_generic_substrate_rates"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q -k "processor_breakdown or strict_failures_with_internal_verifier_support"
.venv/bin/python -m pytest tests/test_kernel_v3_behavior_graph.py -q -k "benchmark or finance"
```

结果：

```text
py_compile passed
2 passed, 42 deselected in 0.35s
2 passed, 5 deselected in 0.28s
3 passed, 3 deselected in 70.51s
```

---

## 25. 追加落地：Failure Layer Counts

为下一轮 FB/FAB 大规模跑题新增失败层级诊断：

```text
failure_layer_counts
```

该字段只对 strict `failed` item 做 post-run 分类，帮助快速判断失败主要集中在哪一层：

| Layer | 含义 |
| --- | --- |
| `scoring_alignment_review` | strict failed，但内部 numeric/verifier gate 已通过，应人工复核格式、单位、scorer 或 synthesis alignment |
| `processor_failure` | processor/structured-output 层失败 |
| `empty_answer` | 没有可评分答案 |
| `failure_report` | agent 最终给出 failure report 而不是 final answer |
| `retrieval_or_evidence` | retrieval/search/fetch/source/evidence 相关失败 |
| `citation_grounding` | 答案缺少 citation grounding |
| `calculation_or_formula_trace` | 数值题缺 calculator / FormulaTrace 支撑 |
| `numeric_verifier` | numeric verifier 或 verifier gate 失败 |
| `synthesis_gate` | synthesis gate 失败 |
| `strict_scoring` | 其余 strict scorer 数值/文本不匹配 |
| `unknown` | 现有 trace 不足以归因 |

落地位置：

- `FinanceBenchmarkSummary.failure_layer_counts`
- `bench finance-report` 的 `Failure Layers` 表；
- weak items 表新增 `Layer` 列；
- `behavior_graph` benchmark diagnostics 和 `benchmark_failure_layer` 节点；
- report recommendation 会提示优先处理最大 failure layer。

边界：

- 不改变 pass/fail；
- 不改变 scorer；
- 不进入 runtime prompt；
- 不读取 gold 到 agent loop；
- 不让 host 替模型选择事实或答案；
- 只把已经失败的结果聚成可调试、可汇报的 post-run 统计。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py kernel_v3/bench/report.py kernel_v3/behavior_graph.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py tests/test_kernel_v3_behavior_graph.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "strict_failures_with_internal_verifier_support or summary_includes_generic_substrate_rates"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q -k "processor_breakdown or strict_failures_with_internal_verifier_support"
.venv/bin/python -m pytest tests/test_kernel_v3_behavior_graph.py -q -k "benchmark_result_graph_summarizes_scores_and_failure_modes"
```

结果：

```text
py_compile passed
2 passed, 42 deselected in 0.37s
2 passed, 5 deselected in 0.30s
1 passed, 5 deselected in 0.28s
```

---

## 26. 追加落地：Benchmark Diagnostics Shared Module

上一节的 `failure_layer_counts` 和 `strict_failed_internal_verifier_passed_*` 最初分别在 finance summary、finance report、behavior graph 中实现。为了避免后续三处口径漂移，本次抽取共享 post-run diagnostics 模块：

```text
kernel_v3/benchmark_diagnostics.py
```

核心函数：

```text
strict_failed_internal_verifier_passed(...)
finance_failure_layer(...)
```

使用位置：

- `kernel_v3/bench/finance.py`
- `kernel_v3/bench/report.py`
- `kernel_v3/behavior_graph.py`

意义：

- failure layer 语义集中维护；
- summary JSON、markdown/html report、behavior graph diagnostics 使用同一口径；
- 这是 LangChain / Semantic Kernel 式组件边界在 benchmark analytics 层的落地；
- 不影响 runtime prompt；
- 不影响 LLM 决策；
- 不影响 pass/fail；
- 不影响 gold 隔离；
- 只提升后续金融跑题统计、论文表格和调试路径的一致性。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/benchmark_diagnostics.py kernel_v3/bench/finance.py kernel_v3/bench/report.py kernel_v3/behavior_graph.py tests/test_kernel_v3_benchmark_diagnostics.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py tests/test_kernel_v3_behavior_graph.py
.venv/bin/python -m pytest tests/test_kernel_v3_benchmark_diagnostics.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py tests/test_kernel_v3_behavior_graph.py -q -k "benchmark_diagnostics or strict_failures_with_internal_verifier_support or summary_includes_generic_substrate_rates or processor_breakdown or benchmark_result_graph_summarizes_scores_and_failure_modes"
```

结果：

```text
py_compile passed
8 passed, 51 deselected in 0.46s
```

---

## 27. 追加落地：General Gauntlet Failure/Processor Diagnostics

通用能力基座需要和金融 benchmark 一样具备可诊断性。此前 `bench general` 已能汇总 pass rate、mode/tool/domain coverage、tokens/cache 和 processor task type；本次补齐：

```text
failed_category_counts
failure_check_counts
processor_status_counts
processor_error_counts
```

含义：

- `failed_category_counts`：失败 case 集中在哪类通用能力，例如 direct chat、workspace、memory、math、system、research；
- `failure_check_counts`：失败来自哪个通用能力 check，例如 `mode`、`expected_tools_present`、`forbidden_tools_absent`、`expected_domains_present`、`live_output_present`；
- `processor_status_counts` / `processor_error_counts`：通用 live runs 中 processor 层的 ok/failed/error cluster。

这让通用能力线可以回答：

- 简单对话是否误进 retrieval/tool loop；
- 工具是否缺失或误用；
- workspace/memory/system/math 等 domain 是否被正确识别；
- live provider 是否出现 structured-output 或 processor 错误；
- cache 命中和 processor 失败是否同时恶化。

边界：

- 不改变 general gauntlet 的评分；
- 不改变 task graph 选择；
- 不改变 LLM 决策；
- 不进入 runtime prompt；
- 只提升 post-run summary 对通用能力失败的定位能力。

同时修正了共享 benchmark diagnostics 的模块位置：

```text
kernel_v3/benchmark_diagnostics.py
```

原因是放在 `kernel_v3/bench/diagnostics.py` 会触发 `behavior_graph -> bench.__init__ -> report -> behavior_graph` 的循环导入。共享诊断现在位于 bench 包外，finance summary、finance report、behavior graph 共同引用该纯工具模块。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/benchmark_diagnostics.py kernel_v3/bench/general.py kernel_v3/bench/finance.py kernel_v3/bench/report.py kernel_v3/behavior_graph.py tests/test_kernel_v3_benchmark_diagnostics.py tests/test_kernel_v3_general_capability_gauntlet.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py tests/test_kernel_v3_behavior_graph.py
.venv/bin/python -m pytest tests/test_kernel_v3_general_capability_gauntlet.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_benchmark_diagnostics.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py tests/test_kernel_v3_behavior_graph.py -q -k "benchmark_diagnostics or strict_failures_with_internal_verifier_support or summary_includes_generic_substrate_rates or processor_breakdown or benchmark_result_graph_summarizes_scores_and_failure_modes"
```

结果：

```text
py_compile passed
7 passed in 34.58s
8 passed, 51 deselected in 0.42s
```

---

## 28. 追加落地：Processor Cache By Task Type

Cache 命中率不是只看整题总量就够。金融和通用任务里，真正破坏缓存的通常是某个 processor 的动态前缀提前、上下文过大、repair packet 过于变化，或者某个 task type 出现异常重试。因此本次把 processor usage 的 task-type cache breakdown 提升到 summary/report 层。

新增共享函数：

```text
kernel_v3.processors.usage.aggregate_processor_usage_by_task_type(...)
```

新增/暴露字段：

```text
processor_cache_by_task_type
```

每个 task type 包含：

- `call_count`
- `ok_count`
- `failed_count`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `prompt_cache_hit_tokens`
- `prompt_cache_miss_tokens`
- `prompt_cache_hit_ratio`
- `duration_ms`
- `average_duration_ms`
- `status_counts`
- `error_counts`

使用位置：

- `bench finance` summary；
- `bench finance-report` 的 `Processor Cache By Task Type` 表；
- `bench general` summary。

意义：

- 金融题可以直接看到 `task.compile`、`finance.slot_bind`、`finance.numeric_judge`、`synthesizer.answer` 谁的 cache ratio 最差；
- 通用 gauntlet 可以直接看到 `semantic.intake`、`planner.propose`、`evaluator.assess` 等通用 processor 的 cache 表现；
- 后续优化 stable prefix、context page-in、repair packet、parallel workbench 时有可量化反馈；
- 这是成本优化和能力优化的交叉点，因为更稳定的 processor packet 通常也更少 JSON 失败和重复 repair。

边界：

- 不改变 runtime prompt；
- 不改变 processor 调用；
- 不改变 agent loop；
- 不改变 scoring；
- 只做 post-run usage aggregation。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/processors/usage.py kernel_v3/bench/general.py kernel_v3/bench/finance.py kernel_v3/bench/report.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_general_capability_gauntlet.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_general_capability_gauntlet.py -q -k "processor_usage or cache_usage or general_capability_summary"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q -k "summary_includes_generic_substrate_rates or processor_breakdown"
```

结果：

```text
py_compile passed
12 passed, 6 deselected in 0.45s
3 passed, 48 deselected in 0.44s
```

---

## 23. 追加落地：Requested-Unit Numeric Scoring Noise Cleanup

复核历史 live artifact `fb_debug_o000_l003_strict_20260615_v1.jsonl` 时，发现 `financebench_id_03029` 的答案：

```text
The FY2018 capital expenditure ... was $1,577 million
```

在旧 run 中被标为 `numeric_outside_tolerance`，但当前 scorer 重放同一答案会通过：

```text
expected = 1577.0
matched_value = 1577.0
status = passed
```

原因是当前 scorer 已支持题干 requested reporting unit，例如 `in USD millions`。不过重放时仍看到一个统计噪声：`FY2018` 这个年份被 requested scale 除以 1,000,000，生成 `0.002018` 这样的无意义候选值。

本次清理：

- `_numeric_values_for_scoring` 仍保留年份原值用于必要场景；
- 但 requested-unit scale conversion 不再应用到年份候选；
- 例如题干要求 USD millions 时，`$1,577 million` 会提供 `1577.0` 作为可匹配值，但 `FY2018` 不再生成 `0.002018`。

边界：

- 不读取 gold 进入运行时；
- 不改变 agent 答案；
- 不改变 LLM 判断；
- 不把任何题目答案打表；
- 只是让 post-run numeric scoring 的单位归一化更干净，避免历史 false negative 和统计噪声影响报告可信度。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py tests/test_kernel_v3_finance_benchmark.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "numeric_scoring_respects_requested_reporting_unit or trace_metrics_include_processor_usage_breakdown or summary_includes_generic_substrate_rates"
```

结果：

```text
3 passed, 40 deselected in 0.36s
```

---

## 22. 追加落地：Finance Repair Prompt Stable-Prefix Guards

`task.compile` 与 `finance.slot_bind` 是金融题中最关键的两个模型处理器：

- `task.compile` 决定任务结构、证据槽位、transform specs 和 tool chain；
- `finance.slot_bind` 决定哪些事实填入哪些槽位，以及哪些 calculator formula 应执行。

它们的语义判断必须由 LLM 完成，host 只做 schema validation、fact_id 存在性、calculator execution 和 journal 记录。为了避免后续把动态错误内容提前导致 prompt cache 失效，本次补了 repair prompt 顺序护栏：

```text
task.compile retry:
contract -> output_schema -> previous_failure -> task_packet

finance.slot_bind repair:
contract -> output_schema -> previous_failure -> slot_bind_packet
```

意义：

- repair chain 仍保留稳定 prefix；
- `previous_failure` 是必要的结构化反馈，但不会排在 contract/schema 之前；
- 动态 facts、compiled program、raw output preview 都保持在后段；
- 这有利于后续同类金融题批量跑时提升 processor prompt cache 命中；
- 不改变 LLM 的 slot binding、task decomposition 或 formula planning 职责。

验证：

```bash
.venv/bin/python -m py_compile tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "task_compiler_retry_prompt_has_structured_feedback or slot_bind_repairs_malformed_json"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "finance_task_compile_prompt or task_compiler_retry_prompt_has_structured_feedback or finance_slot_bind_prompt or slot_bind_repairs_malformed_json"
```

结果：

```text
2 passed, 194 deselected in 0.76s
6 passed, 190 deselected in 0.29s
```

---

## 29. 追加落地：Runtime Graph Delta Projection

结合 LangGraph 的 state delta / streaming 思路，本次把 dashboard 里原本手工维护的 agent-loop topology 分组抽成 `kernel_v3.runtime_graph`。

新增能力：

- `RuntimeGraphDelta`
- `RuntimeTopologyProjection`
- `runtime_graph_delta_stream(records)`
- `runtime_topology_projection(records)`
- `records_until_terminal(records)`
- `runtime_stage_for_kind(kind)`

它们把 journal 记录投影为稳定的 agent-loop 阶段：

```text
Intake -> Plan -> Policy -> Tools -> Search -> Evidence -> Verify -> Answer -> Intake
```

每个 delta 只携带 typed metadata，例如 `request_id`、`task_type`、`action_id`、`status`、`decision`、`stop_reason`，不携带 raw prompt、raw query、gold answer 或长 evidence body。Dashboard 的 `loop_topology_state()` 已改为复用同一投影层，SSE payload 也新增 `graph_deltas`，后续 UI 可以直接订阅真实 runtime delta，而不是再次从事件文本里拼图。

意义：

- 为后续 AgentGraphRuntime 做铺垫；
- 减少 dashboard topology 与后端实际 journal 的口径漂移；
- finalized turn 会在 terminal record 处冻结，post-final diagnostics 不再进入 current-turn graph projection；
- graph delta 可以同时服务 UI、benchmark trace、debugger 和报告；
- 这是可观测性/runtime 基础设施，不参与语义判断、金融事实选择或评分。

边界：

- 不改变 planner；
- 不改变 tool execution；
- 不改变 verifier；
- 不改变 scorer；
- 不引入关键词/阈值金融判题逻辑；
- 不暴露 raw prompt 或 gold/reference。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/runtime_graph.py kernel_v3/demo_dashboard.py tests/test_kernel_v3_runtime_graph.py tests/test_kernel_v3_demo_dashboard.py
.venv/bin/python -m pytest tests/test_kernel_v3_runtime_graph.py tests/test_kernel_v3_demo_dashboard.py -q
```

结果：

```text
py_compile passed
6 passed in 0.12s
```

---

## 30. 追加落地：Structured Final Answer Display Precedence

复核 demo 和 chat 输出链路时确认一个展示层风险：runtime payload 可能同时存在顶层 `answer` 与结构化 `final_answer.answer`。金融题在合成器侧已经形成干净结构化答案时，如果展示层优先读取顶层 `answer`，就可能出现“synthesizer 正常但最终展示文本异常”的现象。

本次已确认并验证：

- `kernel_v3.chat.console.chat_answer_text()` 优先读取 `final_answer.answer`；
- `kernel_v3.demo_dashboard._chat_result_answer_text()` 优先读取 `final_answer.answer` / `text` / `result`；
- 顶层 `answer` 只作为 fallback；
- 该逻辑只影响 public payload / UI display，不改变 runtime agent loop、模型调用、金融判断、scoring 或 verifier。

意义：

- demo UI 和 CLI 更稳定地展示 synthesizer 的结构化最终答案；
- 避免 malformed top-level answer 覆盖 authoritative structured final answer；
- 对金融问题尤其重要，因为最终答案通常包含单位、期间、引用和结论说明。

边界：

- 不改变 LLM 输出；
- 不改变 scorer；
- 不改变合成器 prompt；
- 不把任何 benchmark reference 放入运行时；
- 只是展示/public payload 的答案字段优先级修正。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/chat/console.py tests/test_kernel_v3_phase62_chat_runtime.py
.venv/bin/python -m pytest tests/test_kernel_v3_phase62_chat_runtime.py tests/test_kernel_v3_demo_dashboard.py -q -k "structured_final_answer_text or prefers_structured_final_answer_text"
```

结果：

```text
py_compile passed
2 passed, 51 deselected in 0.45s
```

---

## 31. 追加落地：Finance Verifier-as-Tool

结合 HERMES Math Agent 的 verifier-as-tool 思路，本次把金融 numeric verifier 从“只有 runtime 内部后验调用”推进为标准工具面能力。

新增/调整：

- `FINANCE_VERIFY_NUMERIC_TOOL_NAME = "finance.verify_numeric"`
- `register_finance_tools()` 现在注册：
  - `calculator.compute`
  - `finance.verify_numeric`
- `finance.verify_numeric` manifest：
  - `side_effect_class = read`
  - `permissions_required = []`
  - 输入：`answer`、`facts`、`formula_traces`、`citations`、`evidence`、`question`、`target_binding`
  - 输出：`finance_numeric_verification` observation，包含 `verification.status`、issues、matched values、missing values 等
- `capability_catalog` 现在把 `finance.verify_numeric` 暴露为 safe capability / data tool capability。
- `taskgraph` 现在能把 LLM semantic intake 中的 `required_capabilities=["finance.verify_numeric"]` 映射为标准 tool step。
- `AgentRuntime` 的 finance profile recipe 在需要 numeric verifier 时同时暴露 `calculator.compute` 和 `finance.verify_numeric`。
- Planner-facing tool selection 中加入 `finance.verify_numeric` 的 use_when / payload requirements。

意义：

- 这更接近目标 agent loop：模型观察、判断、调用工具、观察 verifier feedback、再判断；
- 金融 verifier 成为模型可见的工具，而不是只能在 host final gate 后发生；
- 公开题库中已经出现的 `finance.verify_numeric` expected capability 现在有真实工具面对应；
- 后续可以让模型在答案草稿、repair、slot binding 后主动请求 verifier feedback；
- 这为金融能力提升服务，因为错误数字、错误单位、错误公式支持可以更早进入 loop。

边界：

- Verifier 只验证给定 answer/facts/formula/citation/evidence 的支持关系；
- Host 不替模型选择最终 answer；
- Host 不根据关键词选择 metric/period/fact；
- Gold/reference 不进入工具；
- 工具调用仍经过 `PolicyGate`；
- `observation.status == "ok"` 只表示工具执行成功，真正结论在 `content.verification.status`。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/finance/calculator.py kernel_v3/finance/__init__.py kernel_v3/capabilities.py kernel_v3/agent/taskgraph.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_phase81_taskgraph_router.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_phase81_taskgraph_router.py -q -k "finance_numeric_verifier_is_registered_as_read_only_tool or finance_fast_recipe_exposes_composable_toolchain_tools or semantic_intake_prompt_uses_compact_capability_catalog_for_cache or finance_verify_numeric_is_standard_tool_capability"
```

结果：

```text
py_compile passed
4 passed, 229 deselected in 0.89s
```

---

## 32. 追加落地：Verifier Tool Observations Enter Benchmark Metrics

补完 `finance.verify_numeric` 工具化后的闭环：如果模型真的通过 tool protocol 调用 `finance.verify_numeric`，runtime journal 中通常表现为：

```text
kind = observation
data.kind = finance_numeric_verification
data.source = tool:finance.verify_numeric
data.content.verification.status = passed|failed|not_applicable
```

旧 `trace_metrics()` 只读取直接 `kind=finance_numeric_verification` 的 journal record，因此会漏掉通过标准工具面产生的 verifier observation。这会造成两个问题：

- benchmark trace 低估 verifier-as-tool 的实际使用；
- `expected_trace = finance.verify_numeric` 的 public/FAB workflow 可能无法从真实 tool observation 中得到 credit。

本次修复：

- `trace_metrics()` 现在按 journal 顺序合并：
  - 内部 `finance_numeric_verification` record；
  - `tool:finance.verify_numeric` observation 中的 `content.verification`；
- 新增 metrics：
  - `finance_verify_numeric_tool_call_count`
  - `finance_verify_numeric_tool_error_count`
- `numeric_verifier_status`、`numeric_verifier_passed`、`answer_numeric_support_rate` 现在能从 verifier tool observation 中计算。

边界：

- 不改变 runtime agent loop；
- 不改变模型输出；
- 不改变工具执行；
- 不改变评分阈值或 gold handling；
- 只是 post-run observability，使真实工具调用被 benchmark/trace 统计看见。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py tests/test_kernel_v3_finance_benchmark.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "verify_numeric_tool_observation or trace_metrics_include_substrate_and_source_data"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase81_taskgraph_router.py tests/test_kernel_v3_finance_benchmark.py -q -k "finance_numeric_verifier_is_registered_as_read_only_tool or finance_fast_recipe_exposes_composable_toolchain_tools or finance_verify_numeric_is_standard_tool_capability or verify_numeric_tool_observation"
```

结果：

```text
py_compile passed
2 passed, 43 deselected in 0.41s
4 passed, 263 deselected in 0.41s
```

---

## 33. 追加落地：Verifier Tool Schema and Planner Prompt Contract

补完 `finance.verify_numeric` 工具化后的接口严谨性。

发现的问题：

- `ToolRegistry` 的 schema validator 原先只严格校验 `list[str]`；
- `finance.verify_numeric` manifest 使用 `list[FinanceFact]`、`list[FormulaTrace]`、`list[CitationItem]`、`list[EvidenceItem]`；
- 如果不补通用 `list[...]` 校验，模型传入错误形状的 fact rows 时，错误可能在 executor 深处才出现，不利于标准化 tool protocol；
- planner contract 里已有 retrieval/calculator 示例，但还缺一个 verifier-as-tool 示例，模型不容易模仿正确 payload。

本次修复：

- `_coerce_schema_value()` 现在支持 generic `list[...]`：
  - `list[str]` 仍严格要求字符串；
  - `list[FinanceFact]` 等非字符串列表要求 list of object；
  - invalid payload 会在工具 schema validation 阶段返回 `invalid_tool_payload`；
- `PLANNER_PROMPT_CONTRACT` 增加 `finance.verify_numeric` 示例，展示：
  - draft answer；
  - formula traces；
  - facts/citations/evidence slots；
  - side effect class read；
  - 使用场景是“答案草稿存在，需要先验证 numeric support 再 finalizing”。

意义：

- 工具接口更标准化，符合 Hermes Function Calling 的 schema tool-call loop；
- verifier-as-tool 不只是 registry 名字，而是模型可模仿的真实调用协议；
- 错误 payload 更早被 host schema boundary 拦住；
- 这有利于金融题中答案草稿 -> verifier feedback -> synthesis repair 的自然 agent loop。

边界：

- 不改变金融事实选择；
- 不改变 period/metric 语义判断；
- 不改变 scoring；
- 不引入关键词/阈值判题；
- host 只做 schema validation 和工具执行，LLM 仍是语义决策者。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/tools.py kernel_v3/processors/contracts.py kernel_v3/bench/finance.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_finance_benchmark.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_finance_benchmark.py -q -k "finance_numeric_verifier_tool_schema or finance_numeric_verifier_is_registered_as_read_only_tool or finance_prompt_exposes_numeric_verifier_tool_example or verify_numeric_tool_observation"
```

结果：

```text
py_compile passed
4 passed, 289 deselected in 0.49s
```

---

## 34. 追加落地：Planner Allowed-Tool Surface for Finance Verifier

继续补完 verifier-as-tool 的 runtime 闭环。本次确认并加测试保护：

- `finance-fact-fast` / numeric-verifier profile 的 recipe 会把 `finance.verify_numeric` 放进 `allowed_tools`；
- `_planner_allowed_tool_names(recipe)` 包含 `finance.verify_numeric`；
- `_planner_directive(recipe)` 的 `tool_selection` 会向模型展示 `finance.verify_numeric`；
- `ModelPlanner` 在该 allowed-tool surface 下可以合法返回 `finance.verify_numeric` action；
- 该 action 经过 `PolicyGate` 和 `ToolRegistry` 后能产生 `tool:finance.verify_numeric` observation。

这一步很重要：前面已经完成 registry、schema、prompt contract、metrics，但如果 planner allowed-tool surface 不包含该工具，模型仍然会在真实 agent loop 中被拒绝。本次补的是“模型能不能真的选择它”的闭环证据。

边界：

- 不强迫模型调用 verifier；
- 不让 host 替模型选择最终 answer；
- 不改变 finance scoring；
- 不引入关键词或阈值判题；
- 只保证当 LLM 判断需要 verifier feedback 时，这个工具在当前 finance recipe 中是合法可选的。

验证：

```bash
.venv/bin/python -m py_compile tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "finance_fast_model_planner_can_select_verify_numeric_tool or finance_fast_planner_directive_shows_composable_toolchain or finance_numeric_verifier_is_registered_as_read_only_tool"
```

结果：

```text
py_compile passed
3 passed, 196 deselected in 0.79s
```

---

## 35. 追加落地：Framework Review 总成文档与 Verifier Tool 汇总指标

本次把开源框架审阅和 Holo 自身开发过程梳理收束成一份新的报告级主文档：

- `docs/KERNEL_V3_FRAMEWORK_AND_DEVELOPMENT_REVIEW_2026-06-16_ZH.md`

该文档把 LangChain、LangGraph、Semantic Kernel / Microsoft Agent Framework、
Hermes Function Calling、HERMES Math Agent 的可借鉴点，和 Kernel v3 已有的
agent loop、processor fabric、retrieval workbench、finance pack、memory/RAG、
benchmark、UI 迭代逐一对齐。核心结论是：

- Holo 不应成为任何现成框架的 wrapper；
- 下一阶段应落成 host-owned、LLM-driven、tool-coupled、memory-aware、
  graph-observable 的通用 AgentGraph Runtime；
- finance pack 是第一个高压 domain pack，但 agent loop 必须保持通用；
- verifier-as-tool、tool protocol、graph delta、cache/usage metrics、debug/holdout
  split 是后续能力提升和论文报告的关键抓手。

同时补齐 `finance.verify_numeric` 在 benchmark summary/report 层的汇总指标：

- `finance_verify_numeric_tool_call_count`
- `finance_verify_numeric_tool_error_count`
- `finance_verify_numeric_tool_used_rate`
- `finance_verify_numeric_tool_error_rate`

意义：

- 单题 trace 已能看到 `tool:finance.verify_numeric` observation；
- 多题 summary/report 现在能统计模型主动使用 verifier tool 的真实频率和错误率；
- 后续 FB/FAB/FinAgent 大规模 run 不需要手工翻 journal，即可判断 verifier-as-tool
  是否真正进入 agent loop。

边界：

- 不改变 planner 决策；
- 不改变 slot binding；
- 不改变 score/pass 判定；
- 不读取 gold/reference；
- 只做观测和报告，不参与金融答案选择。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py kernel_v3/bench/report.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q -k "generic_substrate_rates or processor_breakdown or verify_numeric_tool_observation"
```

结果：

```text
py_compile passed
4 passed, 48 deselected in 0.51s
```

---

## 36. 追加落地：Agent Loop Stage Coverage Metrics for Finance Runs

继续把 LangGraph 式 runtime observability 落到金融 benchmark。此前
`kernel_v3/runtime_graph.py` 已经能把 journal 事件投影为 Agent Loop stages：

```text
Intake -> Plan -> Policy -> Tools -> Search -> Evidence -> Verify -> Answer
```

本次把该投影接入 `finance.trace_metrics`、`FinanceBenchmarkSummary` 和
`finance-report`，新增观测指标：

```text
agent_loop_stage_counts
agent_loop_visited_stage_count
agent_loop_stage_total_count
agent_loop_stage_coverage_rate
agent_loop_terminal
agent_loop_latest_stage
agent_loop_delta_count
agent_loop_transition_count
agent_loop_tool_stage_present
agent_loop_search_stage_present
agent_loop_evidence_stage_present
agent_loop_verify_stage_present
agent_loop_answer_stage_present
```

多题 summary/report 新增：

```text
average_agent_loop_stage_coverage_rate
agent_loop_terminal_rate
agent_loop_tool_stage_rate
agent_loop_search_stage_rate
agent_loop_verify_stage_rate
average_agent_loop_delta_count
average_agent_loop_transition_count
agent_loop_stage_counts
```

意义：

- 后续 FB/FAB/FinAgent 大规模 run 不只看 pass rate；
- 可以直接看到每题是否真的走过工具、检索、证据、验证和回答阶段；
- 可以诊断简单题是否陷入过长 loop，或复杂金融题是否跳过 Verify；
- UI、benchmark 和报告逐步使用同源 runtime graph projection，避免 demo 图和真实执行脱节。

边界：

- 不改变 planner 决策；
- 不改变 scoring；
- 不改变 slot binding 或 financial answer selection；
- 不引入关键词/阈值规则；
- 只从 journal 真实事件做阶段统计和报告。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py kernel_v3/bench/report.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q -k "substrate_and_source_data or generic_substrate_rates or processor_breakdown or verify_numeric_tool_observation"
.venv/bin/python -m pytest tests/test_kernel_v3_runtime_graph.py -q
```

结果：

```text
py_compile passed
5 passed, 47 deselected in 0.53s
3 passed in 0.07s
```

---

## 44. 追加落地：Dashboard Consumes Runtime Graph Tool Diagnostics

本节把上一轮 `runtime_graph_delta_stream()` 产出的 compact tool observation diagnostics 真正接入 demo/debug UI。

问题：

- 后端 SSE 已经发送 `graph_deltas`，但前端此前只消费 `topology` stage count；
- 因此 verifier/tool diagnostics 虽然存在于 delta 中，用户在 graph inspector 里仍看不到；
- `/api/state` 刷新路径此前也没有返回 `graph_deltas`，刷新后 graph 只剩计数；
- 这会削弱金融调试能力：很难从 UI 上直观看到失败是 numeric verifier、missing formula input、tool error、repair option 还是 citation/value gap。

变更：

- `console_state()` 现在返回：
  - `graph_deltas: runtime_graph_delta_stream(visible_turn)[-32:]`
- dashboard 前端新增 `latestGraphDeltas` 缓存；
- SSE live payload 和 `/api/state` refresh payload 都会更新同一份 graph delta 缓存；
- `renderPipeline()` 按 stage 归并最近的 `observation_diagnostics`；
- node click inspector 和自动 Finance Debug inspector 会渲染 compact diagnostic panel：
  - verifier status；
  - issue count；
  - issue codes；
  - repair options；
  - missing value examples；
  - host boundary；
  - compact error/reason。

边界：

- UI 只渲染 runtime graph delta 中已有的 compact diagnostics；
- 不展示 raw tool body；
- 不展示 hidden chain-of-thought；
- 不读取 benchmark gold/reference；
- 不用关键词或阈值选择答案；
- 不改变 planner、slot binding、calculator、verifier 或 synthesis 的语义职责。

意义：

- 金融做题失败时，界面能直接显示 verifier 给模型的修复信号；
- 后续迭代 FB/FAB/FinanceBench 时，可以更快定位失败层；
- 这把 LangGraph-style state delta observability 往 Holo 自有 dashboard 上推进了一步；
- 当前收益是调试效率和可解释性，不是伪造更高分。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/demo_dashboard.py tests/test_kernel_v3_demo_dashboard.py tests/test_kernel_v3_runtime_graph.py
.venv/bin/python -m pytest tests/test_kernel_v3_demo_dashboard.py tests/test_kernel_v3_runtime_graph.py -q
```

结果：

```text
py_compile passed
8 passed in 0.12s
```

---

## 45. 追加落地：Toolchain Payload Summary and Repetition Groups

本节继续强化 LLM-owned agent loop 的上下文质量，目标是减少金融题和通用任务里的无效重复工具调用。

问题：

- `toolchain_state` 之前已经告诉模型哪些 tool 被调用、哪些 observation 失败、哪些 payload fingerprint 重复；
- 但 fingerprint 本身不可读，LLM 很难判断“重复的是哪类动作”；
- 这会导致 hard finance 题里重复检索、重复 calculator、重复 verifier 的概率升高；
- 如果直接把 payload 原文塞进 prompt，又会增加 token、泄露大文本或把 calculator expression/variables 原文反复暴露。

变更：

- `recent_tool_actions[*]` 新增 compact `payload_summary`；
- 新增 `repeated_action_groups`，按 payload fingerprint 聚合重复工具动作；
- 每个 repeated group 包含：
  - `tool`
  - `payload_fingerprint`
  - `attempt_count`
  - recent `action_ids`
  - compact `payload_summary`
  - `latest_observation_status`
  - optional `latest_observation_diagnostics`
- Planner/evaluator prompt contract 现在明确解释：
  - `payload_summary`
  - `repeated_action_groups`
  - 这些字段是 observation/context，不是 host-selected semantic answer。

Payload summary 边界：

- `retrieval.run` 可暴露 bounded query/source/strategy/evidence slot 摘要；
- `calculator.compute` 不暴露 raw `expression` 或 `variables` 值，只暴露：
  - `formula_name`
  - `unit`
  - `expression_fingerprint`
  - `variable_names`
  - `input_fact_ids`
- `finance.verify_numeric` 只暴露 question preview 和 facts/formula/citation/evidence counts；
- `memory.recall` 只暴露 query preview、scope mode、limit；
- generic tools 只暴露安全短字段和 payload keys；
- 不读取 gold/reference，不选择答案，不改变工具决策权。

意义：

- LLM 现在能看出重复的是同一类检索、同一 calculator payload、同一 verifier payload；
- 对失败工具，可结合 `observation_diagnostics.repair_options` 决定修复、换源、计算、验证或回答；
- 这让 agent loop 更接近 LangGraph/Hermes 的 observe-act-repair 闭环；
- 提升的是上下文质量和循环效率，不是关键词/阈值规则。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/processors/contracts.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "toolchain_state"
```

结果：

```text
py_compile passed
7 passed, 260 deselected in 0.36s
```

---

## 44. 追加落地：Finance Verifier Repair Options in Working State

本节从“可观测”进一步推进到“真实做题能力”的工作台改进：把 `finance_numeric_verification` 的失败信息压缩为模型可读的 repair working set。

问题：

- 之前 `finance_working_state.numeric_verification` 已经包含 `status`、`issue_codes`、matched/missing counts；
- 但模型只能看到“验证失败”，很难快速判断下一步应当是修合成、重新计算、补检索，还是修 period/unit/source binding；
- 这会导致 agent loop 在金融题上更容易重复搜索或过早失败。

变更：

- `_compact_finance_verification_state()` 新增：
  - `missing_value_examples`
  - `repair_options`
- `repair_options` 由 host verifier issue code 生成通用诊断提示，例如：
  - unsupported answer numbers -> 让 synthesis 删除或替换 unsupported numbers；
  - missing formula trace -> 由模型决定是否调用 `calculator.compute`；
  - missing ledger / ledger gap -> 继续获取权威 finance evidence；
  - primary source binding failed -> 检查 target document / period / source / unit binding；
  - period/unit mismatch -> 修正期间或单位口径。
- planner/evaluator prompt contract 明确说明：
  - `repair_options` 是 verifier-derived diagnostic hints；
  - 不是 host-selected answer；
  - 模型仍负责 metric binding、period binding、formula intent、next action、final finance judgment。

能力意义：

- 模型更容易从 verifier 失败中自然进入 repair loop；
- 减少“只知道失败但不知道怎么修”的无效 agent loop；
- 对 WSC add-backs / DIO / EV-revenue / capital intensity 等复杂题，失败后更容易选择正确工具链分支；
- 仍保持 LLM 主导，不引入关键词答案表或阈值裁决。

边界：

- 不改变 `verify_finance_answer()` 的判定逻辑；
- 不改变 benchmark scoring；
- 不读取 gold/reference；
- 不选择最终数字；
- 不用 host 规则替模型做 row/metric/period/final answer 语义判断。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/processors/contracts.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_working_state or contracts_explain_finance_working_state or model_planner_prompt_preserves_compact_finance_working_state or model_evaluator_prompt_preserves_compact_finance_working_state"
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q
```

结果：

```text
py_compile passed
9 passed, 255 deselected in 1.05s
57 passed in 0.60s
```

### 44.1 Verifier-as-Tool Observation Bridge

继续补齐一个真实 agent-loop 缺口：`finance.verify_numeric` 作为工具返回时，verification 原本主要存在于 tool observation 中；`finance_working_state` 更偏向读取独立 `finance_numeric_verification` journal 记录。这会导致下一轮 planner/evaluator 少看到 verifier-as-tool 的最新反馈。

变更：

- `_finance_working_state_for_prompt()` 现在同时读取：
  - 独立 `finance_numeric_verification` records；
  - `observation` records 中的 `source="tool:finance.verify_numeric"` / `kind="finance_numeric_verification"` payload。
- tool observation 中的 `content.verification` 会被压缩进同一个 `numeric_verification` working-state packet；
- tool observation status/id 会进入 diagnostics，便于审计来源；
- 前一节新增的 `missing_value_examples` / `repair_options` 同样适用于 verifier-as-tool observation。

意义：

- LLM 在调用 `finance.verify_numeric` 后，下一轮 context 可以直接看到 verifier 结果；
- evaluator 的 post-observation context refresh 现在对 verifier-as-tool 也有效；
- 这更符合 Hermes/HERMES 的标准闭环：model calls verifier tool -> host returns observation -> model observes verification feedback -> model repairs or finalizes；
- 不要求 host 自动写额外 verification record，也不让 host 替模型选择答案。

边界：

- 不改变 `finance.verify_numeric` 工具输出；
- 不改变 verifier 判定逻辑；
- 不改变 scoring；
- 不读取 gold/reference；
- 不把 repair options 当最终答案。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "finance_working_state or verify_numeric_tool_observation or finance_numeric_verifier_tool"
.venv/bin/python -m py_compile kernel_v3/processors/contracts.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_working_state or contracts_explain_finance_working_state"
```

结果：

```text
py_compile passed
7 passed, 201 deselected in 0.80s
py_compile passed
4 passed, 53 deselected in 0.30s
```

### 44.2 Tool Observation Repair Guidance

继续把 verifier-as-tool 闭环前移：上一节让下一轮 `finance_working_state` 能看到 `finance.verify_numeric` 的 observation；本节让工具 observation 本身直接带 compact repair guidance，方便 UI、console、evaluator 和下一轮 context 都读取同一个结构化提示。

变更：

- `kernel_v3.finance.numeric_verifier` 新增 `finance_numeric_repair_guidance()`；
- `finance.verify_numeric` tool observation 的 `content` 新增：
  - `repair_guidance`
  - `repair_options`
  - `missing_value_examples`
- `runtime._compact_finance_verification_state()` 复用同一个 finance-layer guidance，而不是在 runtime 中维护另一套 repair option 逻辑；
- `kernel_v3.finance.__init__` 导出 guidance，后续 benchmark report/UI/processor prompt 可以复用。

意义：

- 模型调用 verifier tool 后，工具返回当场就包含“为什么失败、缺哪些数字、下一步可考虑什么”；
- UI/console 可以在 tool result 行直接显示 repair options，不必等下一次 context 编译；
- runtime working state 与 tool observation 的 repair 口径一致；
- 更接近 Hermes/HERMES 的标准工作流：model tool call -> host observation -> model repair/finalize。

边界：

- guidance 是 verifier-derived diagnostic hint；
- 不改变 `verify_finance_answer()` 的判定逻辑；
- 不改变 scoring；
- 不读取 gold/reference；
- 不选择最终事实、公式或答案；
- LLM 仍负责 semantic repair、metric/period binding、formula intent 和 final finance judgment。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/finance/numeric_verifier.py kernel_v3/finance/calculator.py kernel_v3/finance/__init__.py kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "finance_numeric_verifier_tool or finance_working_state or verifier_repair_options"
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_working_state or contracts_explain_finance_working_state"
```

结果：

```text
py_compile passed
8 passed, 201 deselected in 0.93s
4 passed, 53 deselected in 0.42s
```

### 44.3 Toolchain Observation Diagnostics

上一节让 `finance.verify_numeric` 的 tool observation 直接携带 `repair_guidance`。本节把这类结构化诊断纳入通用 `toolchain_state`，让 planner/evaluator/UI 在工具链摘要中直接看到关键 observation diagnostics，而不是只能看到 `content_keys`。

变更：

- `_toolchain_state_for_prompt()` 的 `recent_tool_observations` 新增可选 `observation_diagnostics`；
- 目前压缩字段包括：
  - verifier status；
  - issue/matched/missing counts；
  - guidance schema；
  - issue codes；
  - repair options；
  - compact missing value examples；
  - tool error/reason；
  - guidance host boundary；
- `model_attention` 新增提示：存在 observation diagnostics 时，模型应先检查诊断再重复、修复或 final。

意义：

- 这把 Hermes-style tool response loop 做得更自然：模型不只看到工具“调用过”，还能看到工具返回的结构化失败原因；
- `finance.verify_numeric` 的修复建议可以同时进入 finance working state 和 toolchain state；
- UI/console 后续可直接渲染每个工具 observation 的诊断摘要；
- 对通用能力也有帮助，因为 tool error/reason 不再只隐藏在 content keys 后面。

边界：

- 只压缩工具 observation 已经返回的诊断信息；
- 不读取 raw evidence / raw provider body；
- 不读取 gold/reference；
- 不改变工具执行和 scoring；
- 不做语义答案选择。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "toolchain_state or finance_numeric_verifier_tool or finance_working_state"
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q -k "toolchain_state or finance_working_state"
```

结果：

```text
py_compile passed
12 passed, 198 deselected in 0.98s
7 passed, 50 deselected in 0.38s
```

### 44.4 Prompt Contract for Tool Observation Diagnostics

上一节让 `toolchain_state` 携带 `observation_diagnostics`。本节补齐 processor prompt contract，让 planner/evaluator 明确知道这些字段的语义和边界。

变更：

- `PLANNER_PROMPT_CONTRACT` 说明：
  - `recent_tool_observations` 可能包含 `observation_diagnostics`；
  - 诊断字段可包括 verifier status、issue codes、repair options、compact missing value examples、tool errors；
  - 模型可用它们判断 retry/repair/finalize；
  - 它们不是 host-selected semantic answers。
- `EVALUATOR_PROMPT_CONTRACT` 说明：
  - evaluator 应用 diagnostics 判断最新 observation 是否关闭 gap；
  - diagnostics 只能作为 observation summary；
  - 不能把 repair options 当作最终答案。
- phase5 prompt 测试确认 `observation_diagnostics`、`issue_codes`、`repair_options`、`missing_value_examples` 会进入 planner prompt。

意义：

- 让新增字段不只是 UI/trace 可见，而是真正成为 LLM 可用的 agent-loop working protocol；
- `finance.verify_numeric` 的失败修复提示能自然影响下一步 planner/evaluator 判断；
- 这强化的是 LLM 驾驭工具的能力，不是 host 规则裁决。

边界：

- 不改工具执行；
- 不改 scoring；
- 不读取 gold/reference；
- 不替模型选择语义答案。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/processors/contracts.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q -k "toolchain_state or contracts_explain_toolchain_state or finance_working_state"
```

结果：

```text
py_compile passed
7 passed, 50 deselected in 0.48s
```

### 44.5 Benchmark Metrics for Tool Observation Diagnostics

上一节让 planner/evaluator prompt 明确理解 `observation_diagnostics`。本节把这条链路纳入 finance benchmark/report 统计，方便后续多题 run 判断工具诊断是否实际生成并进入 context。

变更：

- `trace_metrics()` 新增：
  - `tool_observation_diagnostics_count`
  - `tool_observation_repair_guidance_count`
  - `tool_observation_diagnostics_rate`
  - `tool_observation_repair_guidance_rate`
  - `tool_observation_diagnostic_issue_code_counts`
  - `context_toolchain_observation_diagnostics_present_count`
  - `context_toolchain_observation_diagnostics_prompt_eligible_rate`
  - `latest_context_toolchain_observation_diagnostics_present`
- `FinanceBenchmarkSummary` 聚合上述 tool observation diagnostics / repair guidance / issue code metrics；
- `finance-report` Markdown 主表新增 diagnostics rate 与 repair-guidance rate；
- `Context Hygiene` 表新增 toolchain observation diagnostics prompt-eligible rate；
- report 新增 `Tool Observation Diagnostic Issue Codes` 计数表。

意义：

- 多题跑分时可以看到 verifier/tool diagnostics 是否真的产生；
- 可以区分“工具有返回诊断，但没有进入 prompt context”和“工具根本没有诊断”；
- 论文/报告可以用这些指标说明 agent loop 的工具反馈闭环，而不仅是答案分数；
- 这仍然是观测层，不参与答案生成或评分。

边界：

- 不改变 runtime 决策；
- 不改变 scoring；
- 不读取 gold/reference；
- 不根据 issue code 选择最终答案；
- issue code counts 只用于 post-run diagnostics。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py kernel_v3/bench/report.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "trace_metrics_include_substrate or verify_numeric_tool_observation or summary_exposes_workflow_metrics"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q -k "processor_breakdown"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q
```

结果：

```text
py_compile passed
2 passed, 43 deselected in 0.44s
1 passed, 6 deselected in 0.33s
7 passed in 69.27s
```

### 44.6 Runtime Graph Projection for Tool Observation Diagnostics

上一节把 tool observation diagnostics 纳入 benchmark/report；本节让 runtime graph delta 也能直接携带 compact diagnostics，方便 Windows demo UI、CLI trace、graph inspector 和 post-run review 从同一条 delta stream 中看到工具反馈。

变更：

- `runtime_graph_delta_stream()` 对 tool observation 提取 compact `observation_diagnostics`；
- `node_updates[0].observation_diagnostics` 和 `metadata.observation_diagnostics` 同步携带该摘要；
- 摘要字段包括：
  - verifier status；
  - issue/missing counts；
  - guidance schema；
  - issue codes；
  - repair options；
  - compact missing value examples；
  - host boundary；
  - tool error/reason；
- raw verification body、raw evidence、raw provider body 不进入 graph delta。

意义：

- UI 可以在 tool/verify 节点上直接显示“unsupported answer number / repair answer / missing value”等状态；
- runtime graph 不再只显示“Tools 阶段发生了”，而能显示工具 observation 的可操作诊断；
- 这把 LangGraph-style streaming state delta 和 Hermes-style tool response 更紧地连起来；
- 对金融题失败复盘尤其有用：可以直接看到 verifier 反馈是否在 graph 上出现。

边界：

- 只改 graph projection；
- 不改变 runtime 执行；
- 不改变 planner/evaluator prompt；
- 不改变 scoring；
- 不读取 gold/reference；
- 不暴露 raw tool bodies。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/runtime_graph.py tests/test_kernel_v3_runtime_graph.py kernel_v3/demo_dashboard.py tests/test_kernel_v3_demo_dashboard.py
.venv/bin/python -m pytest tests/test_kernel_v3_runtime_graph.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_demo_dashboard.py -q
```

结果：

```text
py_compile passed
4 passed in 0.08s
3 passed in 0.08s
```

---

## 37. 追加落地：Toolchain and Post-Final Compliance Metrics

继续把金融 benchmark 从“只看答案分数”推进到“能解释 agent loop 质量”。本次新增两类观测指标：

### 37.1 Toolchain metrics

单题 `finance.trace_metrics` 新增：

```text
tool_action_count
tool_action_unique_count
tool_action_repeated_count
tool_action_repetition_rate
tool_observation_count
tool_observation_source_counts
tool_observation_error_count
tool_observation_error_rate
toolchain_depth
retrieval_tool_present
calculator_tool_present
finance_verify_tool_present
retrieval_calculator_verifier_chain_present
```

多题 summary/report 新增：

```text
average_toolchain_depth
retrieval_calculator_verifier_chain_rate
average_tool_observation_error_rate
average_tool_action_repetition_rate
tool_observation_source_counts
```

意义：

- 可以统计模型是否真的通过标准工具协议使用 retrieval / calculator / verifier；
- 可以看到工具 observation 的错误率；
- 可以量化重复工具动作，不依赖主观翻 trace；
- 对 FB/FAB 大规模跑题有帮助：错题不只分为答错，还能看到是没检索、没计算、没验证、工具失败，还是重复 loop。

### 37.2 Post-final compliance metrics

单题 `finance.trace_metrics` 新增：

```text
post_final_record_count
post_final_record_kind_counts
post_final_clean
```

多题 summary/report 新增：

```text
post_final_clean_rate
average_post_final_record_count
post_final_record_kind_counts
```

意义：

- 直接量化 UI 曾经暴露的问题：answer complete 后同一 turn/task 是否仍追加记录；
- 当前 runtime graph 会在 terminal record 后冻结当前可视图，但 benchmark 层仍需要统计 post-final activity；
- 后续可以区分 current-turn graph 与 post-run diagnostics / memory proposal，避免 demo/UI 与真实执行状态脱节。

边界：

- 不参与 scoring；
- 不影响 planner；
- 不改变工具选择；
- 不改变 final answer；
- 不读取 gold/reference；
- 只做真实 journal 事件的事后统计。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py kernel_v3/bench/report.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q -k "substrate_and_source_data or generic_substrate_rates or processor_breakdown or verify_numeric_tool_observation"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark_report.py -q
```

结果：

```text
py_compile passed
5 passed, 47 deselected in 0.43s
7 passed in 68.40s
```

---

## 38. 追加落地：Planner-Visible Compact Toolchain State

前面几节已经把工具链质量做成 benchmark/report 指标；本节把同一类信息推进到
planner/evaluator 可见的 context packet，使 LLM 在下一步决策时能看到已经发生过的工具链状态。

新增：

- `_toolchain_state_for_prompt(journal, task_id, run_id)`
- `_AgentContextCompiler.compile()` 注入 `state["toolchain_state"]`

`toolchain_state` 是 compact observation packet，包含：

```text
action_count
observation_count
tool_source_counts
failed_tool_count
failed_tools
recent_tool_actions
recent_tool_observations
repeated_tool_names
repeated_action_fingerprints
toolchain_presence
terminal_seen
post_final_record_count
post_final_record_kind_counts
model_attention
host_boundary
```

关键设计：

- 只暴露工具名、状态、observation id、action id、content keys、错误摘要和 payload fingerprint；
- 不把完整 payload 塞回 prompt，避免上下文膨胀和 cache 破坏；
- 不告诉模型“必须调用哪个工具”，只告诉它已有 retrieval / calculator / finance.verify_numeric 是否出现；
- 对失败工具和重复 payload 给出 attention hint，仍由模型决定下一步；
- terminal 后记录只作为 diagnostics，不让模型误以为当前 turn 仍在 running。

意义：

- 让 LLM 更自然地利用已有工具结果，减少重复检索和重复 calculator payload；
- 支持金融任务中的自然链路：retrieval -> calculator -> finance.verify_numeric -> answer；
- 也服务通用能力，因为该 packet 是 domain-general toolchain state，不是金融关键词规则；
- 与 LangGraph state、Semantic Kernel middleware/filter、Hermes tool response loop 的思想一致。

边界：

- 不改变 planner 的选择权；
- 不改变 host policy；
- 不改变 scoring；
- 不读取 gold/reference；
- 不引入关键词/阈值判题；
- host 只压缩和暴露真实 journal 事件。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "toolchain_state_for_prompt or agent_context_compiler_injects_compact_toolchain_state or finance_fast_model_planner_can_select_verify_numeric_tool or finance_fast_planner_directive_shows_composable_toolchain"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q -k "substrate_and_source_data or generic_substrate_rates or processor_breakdown or verify_numeric_tool_observation"
```

结果：

```text
py_compile passed
4 passed, 197 deselected in 0.77s
5 passed, 47 deselected in 0.33s
```

---

## 39. 追加落地：Toolchain State Reaches Provider Prompt

上一节将 `toolchain_state` 注入 `ContextBundle.state`。本节补齐 provider prompt 链路：

- `kernel_v3/processors/adapters.py` 的 `_compact_context_state_for_provider()` 现在保留 `toolchain_state`；
- `PLANNER_PROMPT_CONTRACT` 明确说明如何使用 `context.state.toolchain_state`；
- `EVALUATOR_PROMPT_CONTRACT` 明确说明 evaluator 应用它判断最新 observation 是否推进了任务；
- 测试确认 planner provider prompt 中实际出现压缩后的 `toolchain_state`。

模型现在能看到：

```text
toolchain_presence
failed_tools
recent_tool_observations
repeated_tool_names
repeated_action_fingerprints
post_final_record_count
host_boundary
```

这一步比单纯 benchmark/report observability 更接近真实能力提升：

- planner 能基于已有 retrieval/calculator/verifier observation 决定下一步；
- evaluator 能判断最新工具结果是进展、失败、重复，还是已可 final；
- 对金融任务，模型更容易自然形成 retrieval -> calculator -> finance.verify_numeric -> answer 的链路；
- 对通用任务，模型也能避免重复工具 payload 和 post-final 状态误判。

边界：

- `toolchain_state` 是 observation，不是规则表；
- 不强制调用 calculator 或 verifier；
- 不让 host 选择金融答案；
- 不读取 gold/reference；
- 不改变 scoring；
- 不塞完整 payload，使用 `payload_fingerprint` 控制 prompt 噪声和 cache 成本。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/processors/contracts.py kernel_v3/processors/adapters.py kernel_v3/agent/runtime.py tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_finance_engine.py -q -k "toolchain_state_packet or toolchain_state_for_prompt or agent_context_compiler_injects_compact_toolchain_state or model_planner_prompt_preserves_compact_toolchain_state or finance_fast_model_planner_can_select_verify_numeric_tool"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q -k "substrate_and_source_data or generic_substrate_rates or processor_breakdown or verify_numeric_tool_observation"
```

结果：

```text
py_compile passed
5 passed, 248 deselected in 0.44s
5 passed, 47 deselected in 0.32s
```

---

## 40. 追加落地：Finance Working State Provider Packet

上一节让模型看到通用 `toolchain_state`。本节继续补齐金融专用但不打表的工作台状态：`finance_working_state`。

新增：

- `_finance_working_state_for_prompt(journal, task_id, run_id)`
- `_AgentContextCompiler.compile()` 注入 `state["finance_working_state"]`
- `_compact_context_state_for_provider()` 保留该 packet
- `PLANNER_PROMPT_CONTRACT` 和 `EVALUATOR_PROMPT_CONTRACT` 明确说明其用途与边界

该 packet 汇总当前 run 中已经由 host 记录的金融工作状态：

```text
ledger_count
fact_count
facts
slot_frame
transform_plan
formula_trace_count
formula_traces
formula_trace_support
numeric_verification
presence
missing_slots
model_attention
host_boundary
```

能力意义：

- planner 可以看到已有 finance facts、slot 缺口、FormulaTrace、verifier 结果；
- evaluator 可以判断最新 observation 是否推进了金融任务，而不是只看工具是否返回；
- 模型更容易自然决定下一步是继续 retrieval、calculator.compute、finance.verify_numeric、final answer，还是写 limitation；
- `formula_trace_support` 把 calculator 输出连接到 input facts、evidence refs、citation refs，减少 final synthesis 里“算对但引用脱节”的问题；
- 这是从 LangGraph state、Hermes tool-response loop、HERMES verifier-as-tool 中吸收的工程思想。

边界保持不变：

- 不读取 benchmark gold/reference；
- 不使用答案表；
- 不用关键词/阈值选择 metric、period、row 或 final number；
- host 不替模型做公式意图或最终金融判断；
- packet 只压缩 journal 中已有的 facts、traces、slot/transform/verifier 状态；
- 模型仍负责 metric binding、period binding、formula intent、下一步动作和最终答案。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/processors/adapters.py kernel_v3/processors/contracts.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_working_state or toolchain_state_for_prompt or agent_context_compiler_injects_compact_toolchain_state or toolchain_state_packet or model_planner_prompt_preserves_compact_toolchain_state or model_planner_prompt_preserves_compact_finance_working_state"
```

结果：

```text
py_compile passed
8 passed, 249 deselected in 0.90s
```

### 40.1 Context Hygiene Follow-Up

同节追加收紧：`finance_working_state` 现在只在当前 run 真的存在金融工作状态时进入 provider prompt。

触发条件来自 typed runtime state，而不是用户问题关键词：

- `finance_fact_ledger`；
- calculator `FormulaTrace`；
- `finance_numeric_verification`；
- 或 `slot_frame` / `transform_plan` 明确标记 `domain=finance` / `source=finance_fact_ledger`。

如果只有普通 source-grounded research 的 slot/transform，helper 返回 `{}`，provider prompt 会过滤该字段。

意义：

- 避免普通 chat、文档总结、通用研究任务被金融上下文污染；
- 保护 prompt cache：非金融任务不会因为空 finance packet 破坏稳定前缀/动态区；
- 保留金融任务所需的 facts / slots / traces / verifier 状态；
- 仍然不引入关键词路由或 host 语义判题。

追加验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/processors/adapters.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_working_state or model_planner_prompt_omits_empty_finance_working_state"
```

结果：

```text
py_compile passed
6 passed, 253 deselected in 0.94s
```

### 40.2 Loop-Level Context Refresh Verification

同节继续追加一个 loop-level 回归：`LoopControllerV3` 每个 step 开始都会调用 `context_compiler.compile(task, journal)`。因此第一步工具写入的 `finance_fact_ledger` 和 calculator `FormulaTrace` 会在第二步 planner context 中出现，而不是只存在于初始 prompt。

新增测试：

- 第一轮 planner 收到的 `finance_working_state` 为空；
- fake 工具执行时向同一 journal 写入 `finance_fact_ledger` 与 calculator `FormulaTrace`；
- evaluator 返回 `continue`；
- 第二轮 planner 收到重新编译后的 context，并能看到 `finance_working_state.presence.finance_facts=True` 和 `presence.formula_trace=True`；
- journal 中第二条 `context` 记录也包含刷新后的 finance state。

意义：

- 证明该 packet 是 agent loop 的动态工作状态，而不是静态初始化提示词；
- 让 planner 可以基于上一轮 retrieval/calculator/verifier observation 自然选择下一步；
- 对齐 LangGraph state refresh / Hermes observation loop 的架构思想；
- 不改变 LoopControllerV3 的工具无关性。

追加验证：

```bash
.venv/bin/python -m py_compile tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "loop_recompiles_context_so_second_planner_step_sees_finance_working_state"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_working_state or model_planner_prompt_omits_empty_finance_working_state"
```

结果：

```text
py_compile passed
1 passed, 204 deselected in 0.84s
7 passed, 253 deselected in 0.40s
```

### 40.3 Evaluator Uses Post-Observation Refreshed Context

继续收紧 agent loop 时序：`LoopControllerV3` 现在在 action 执行并写入 observation 后，会重新编译一次 context，再交给 evaluator。

旧时序：

```text
compile context
-> planner proposes action
-> host executes action
-> observation appended
-> evaluator receives pre-action context + observation
```

新时序：

```text
compile planning context
-> planner proposes action
-> host executes action
-> observation appended
-> compile evaluation context from updated journal
-> evaluator receives post-observation context + observation
```

意义：

- evaluator 能看到刚刚由工具写入的 `finance_fact_ledger`、calculator `FormulaTrace`、`finance_numeric_verification`；
- 对金融任务，evaluator 可以更准确判断 observation 是否闭合了 slot/formula/verifier 缺口；
- 对通用任务，evaluator 也能看到最新 memory/retrieval/toolchain state；
- planner 仍使用动作前 context，evaluator 使用动作后 context，符合人类工作流；
- 不新增 journal context 记录，避免破坏现有 trace 顺序和 UI 假事件。

新增回归已证明：

- 第一轮 planner context 中 `finance_working_state` 为空；
- 第一轮工具写入 finance ledger 与 FormulaTrace；
- 第一轮 evaluator 立刻看到 refreshed `finance_working_state.presence.formula_trace=True`；
- 第二轮 planner 也看到同一刷新状态。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/loop.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "loop_recompiles_context_so_second_planner_step_sees_finance_working_state"
.venv/bin/python -m pytest tests/test_kernel_v3_loop_direct_answer.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "direct_answer_uses_full_loop or model_evaluator_final_answer_ready_stops_loop"
.venv/bin/python -m pytest tests/test_kernel_v3_loop_direct_answer.py tests/test_kernel_v3_feedback_continue.py tests/test_kernel_v3_phase5_semantic_processors.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_working_state or model_planner_prompt_omits_empty_finance_working_state"
```

结果：

```text
py_compile passed
1 passed, 204 deselected in 0.87s
2 passed, 54 deselected in 0.33s
57 passed in 0.74s
7 passed, 253 deselected in 0.39s
```

### 40.4 ModelEvaluator Prompt Carries Refreshed Finance State

继续补齐 provider 链路测试：`ModelEvaluator` 的 provider prompt 现在被明确验证会保留 compact `finance_working_state`。

覆盖点：

- `context.state.finance_working_state` 进入 `_evaluator_prompt()`；
- `_compact_context_state_for_provider()` 不会丢弃非空 finance state；
- provider prompt 中包含 `facts`、`slot_frame`、`formula_trace_support`、`numeric_verification`；
- observation 仍作为单独字段进入 prompt，模型同时看到“最新 observation”和“observation 后的工作台状态”。

意义：

- loop 级 post-observation context refresh 不只是 Python 内部对象变化，live 模型 evaluator 也能看到；
- evaluator 可以用 updated finance state 判断是否继续、repair、verify 或 final；
- 这强化了 `observe -> update state -> evaluate -> continue/finalize` 的通用 agent loop。

验证：

```bash
.venv/bin/python -m py_compile tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_working_state or model_evaluator_prompt_preserves_compact_finance_working_state"
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q
```

结果：

```text
py_compile passed
4 passed, 52 deselected in 0.45s
56 passed in 0.84s
```

---

## 41. 追加落地：Empty Toolchain State Prompt Hygiene

在 `finance_working_state` 完成空状态过滤后，本节继续收紧通用 `toolchain_state`。

变更：

- `_toolchain_state_for_prompt()` 在没有 tool actions、tool observations、post-final diagnostics 时返回 `{}`；
- provider prompt 通过既有空值过滤机制省略空 `toolchain_state`；
- 一旦存在真实工具动作、工具 observation、失败工具、重复工具 payload 或 post-final diagnostics，`toolchain_state` 仍然照常出现。

意义：

- 普通 chat、直接回答、简单 system answer 不再携带空工具链 schema 包；
- 减少动态上下文噪声，提高 prompt cache 稳定性；
- 保留工具任务需要的失败、重复、presence、post-final 状态；
- 这属于 context hygiene，不参与 planner 路由、不改变 scoring、不读取 gold/reference。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "toolchain_state or finance_working_state or model_planner_prompt_omits_empty_toolchain_state or model_planner_prompt_omits_empty_finance_working_state"
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py -q
```

结果：

```text
py_compile passed
14 passed, 249 deselected in 1.04s
57 passed in 0.88s
```

---

## 42. 追加落地：Benchmark Context Hygiene Metrics

本节把前面已经实现的 `toolchain_state` / `finance_working_state` prompt hygiene 接入 finance benchmark/report 统计。

背景：

- provider prompt 已经会过滤空 `toolchain_state` / `finance_working_state`；
- journal 中仍会保留完整 context 审计记录；
- 后续跑 FB/FAB/FinAgent live batch 时，需要直接看到动态状态到底何时进入上下文、空包是否仍在审计层出现、以及非空状态占比是否合理。

新增单题 `trace_metrics` 字段：

```text
context_record_count
context_dynamic_state_present_count
context_dynamic_state_present_rate
context_toolchain_state_present_count
context_toolchain_state_empty_count
context_toolchain_state_prompt_eligible_rate
context_finance_working_state_present_count
context_finance_working_state_empty_count
context_finance_working_state_prompt_eligible_rate
latest_context_toolchain_state_present
latest_context_finance_working_state_present
```

新增 summary/report 字段：

```text
context_record_count
average_context_record_count
context_dynamic_state_present_count
context_dynamic_state_present_rate
context_dynamic_state_item_rate
context_toolchain_state_present_count
context_toolchain_state_empty_count
context_toolchain_state_prompt_eligible_rate
context_finance_working_state_present_count
context_finance_working_state_empty_count
context_finance_working_state_prompt_eligible_rate
```

`bench finance-report` 现在渲染 `Context Hygiene` 小节，并在 Score Summary 中显示：

- total / average context records；
- dynamic-state context rate 和 item rate；
- toolchain state prompt-eligible rate；
- finance working-state prompt-eligible rate；
- empty-state counts。

边界：

- 这是 observability，不参与 scoring；
- 不改变 planner/evaluator/synthesizer 决策；
- 不读取 benchmark gold/reference；
- 不用关键词或阈值决定金融答案；
- 只帮助后续分析 context、cache、agent-loop 状态是否健康。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/bench/finance.py kernel_v3/bench/report.py tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q -k "processor_breakdown or trace_metrics or context_hygiene or summary_exposes_workflow_metrics"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q
```

结果：

```text
py_compile passed
5 passed, 47 deselected in 0.57s
52 passed in 212.49s
```

---

## 43. 追加落地：Runtime Graph Freeze Diagnostics and Loop Metadata

本节继续把 LangGraph/AgentGraph Runtime 的经验落到 Holo 自有 runtime graph，不改变执行逻辑，只增强可观测性。

问题：

- UI 和报告需要清楚知道当前 turn graph 是否已经 terminal/frozen；
- terminal answer 之后可能还有 processor diagnostics、memory proposal 或 report event；
- 这些 late records 不应该继续改动当前 turn topology，但需要被统计为 ignored/post-terminal diagnostics；
- graph delta 需要携带 loop iteration/stage index，便于前端后续画出更清晰的 agent-loop 拓扑，而不是只看线性事件流。

变更：

- `runtime_topology_projection()` diagnostics 新增：
  - `raw_record_count`
  - `record_count`
  - `frozen_at_record_id`
  - `frozen_at_ms`
  - `ignored_post_terminal_record_count`
  - `ignored_post_terminal_record_kind_counts`
- `runtime_graph_delta_stream()` 的 node update 和 metadata 新增：
  - `stage_index`
  - `loop_iteration`
- edge update 也带 `loop_iteration`。

意义：

- 当前 turn terminal 后，graph freeze 变成可审计事实；
- UI 可以明确显示 late records 被忽略，而不是让 topology 在 answer complete 后继续跳；
- 后续二维/环状 agent-loop graph 可以按 `stage_index` 和 `loop_iteration` 布局；
- 这是 runtime observability，不参与 planner 路由、不影响工具调用、不影响金融答案和 scoring。

验证：

```bash
.venv/bin/python -m py_compile kernel_v3/runtime_graph.py tests/test_kernel_v3_runtime_graph.py kernel_v3/bench/finance.py kernel_v3/bench/report.py
.venv/bin/python -m pytest tests/test_kernel_v3_runtime_graph.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q -k "processor_breakdown or trace_metrics or context_hygiene or summary_exposes_workflow_metrics"
.venv/bin/python -m py_compile kernel_v3/demo_dashboard.py tests/test_kernel_v3_demo_dashboard.py
.venv/bin/python -m pytest tests/test_kernel_v3_demo_dashboard.py -q
```

结果：

```text
py_compile passed
3 passed in 0.08s
5 passed, 47 deselected in 0.40s
py_compile passed
3 passed in 0.07s
```

---

## 44. 追加落地：Model-Owned Slot-Bind Period/Line-Item Basis

本节继续推进金融做题能力，但不把语义判断转移给 host。目标是让模型在
`finance.slot_bind` 阶段不仅给出 fact_id 和 formula request，还把自己选择
期间和行项目的依据结构化写出来，方便后续 numeric judge、synthesizer、报告和
错题分析复用。

问题：

- SEC companyfacts / filing evidence 中经常同时出现 FY、季度、TTM、期末余额、
  duration flow、later-filed restatement、target filing accession 等候选；
- 旧的 `reason_summary` 太短，无法稳定表达每个 slot 为什么选这个 period /
  line item；
- host 不能用规则替模型选事实，但应该完整记录模型做出 period/line-item 判断时
  参考了哪些 raw fields。

变更：

- `finance.slot_bind` schema 新增可选字段：
  - `period_basis`
  - `line_item_basis`
- slot-bind prompt 要求模型在 period/line-item 有竞争时输出 compact basis：
  - `slot_name`
  - `fact_id`
  - `selected_period` / `selected_line_item`
  - `raw_fields_used`
  - `reason`
- runtime 只做 schema/compact 转存：
  - journal `finance_slot_bind` 记录保留 `period_basis` / `line_item_basis`；
  - `FinanceFormulaPlan.payload.diagnostics` 保留 `model_period_basis` /
    `model_line_item_basis`；
  - `FinanceFormulaPlan.diagnostics` 同步保留这些字段。

边界：

- host 不根据这些 basis 重新选择 fact；
- host 不用这些 basis 生成答案；
- 它们是模型语义判断的 provenance，而不是规则 fallback；
- 老模型不输出这些字段也不会被 schema 拒绝。

验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py::test_finance_slot_bind_plans_use_model_selected_fact_ids_only tests/test_kernel_v3_finance_engine.py::test_finance_slot_bind_plans_preserve_model_period_and_line_item_basis tests/test_kernel_v3_finance_engine.py::test_finance_slot_bind_plans_accept_model_selected_imperfect_metric_identity_formula tests/test_kernel_v3_finance_engine.py::test_model_finance_slot_bind_repairs_malformed_json_without_host_semantic_binding -q
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/processors/contracts.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_retrieval_workbench.py -q
```

结果：

```text
4 passed in 0.80s
py_compile passed
243 passed in 2.46s
```

---

## 45. 追加落地：Slot-Bind Basis Enters Finance Working State

上一节让模型在 `finance.slot_bind` 输出 period/line-item basis。本节把这些依据接入
下一轮 agent loop 可见的 `finance_working_state`，避免模型第一轮做出的绑定依据只
停留在 journal 和 FormulaTrace diagnostics 中。

问题：

- 多步金融题经常需要先绑定事实，再计算，再验证，再最终合成；
- 如果第二轮 planner/evaluator 只看到 facts、FormulaTrace、verifier issues，却看不到
  第一轮模型为什么选择某个 FY / line item，就容易重复检索、误判冲突或在 synthesis 中
  丢掉 period/line-item 口径；
- host 仍不能接管语义判断，但可以把模型自己的依据作为工作状态转交给下一轮模型。

变更：

- `_finance_working_state_for_prompt()` 新增 `slot_bind` 子状态：
  - `status`
  - `decision`
  - `accepted_formula_plan_count`
  - `missing_slots`
  - `next_action`
  - `period_basis`
  - `line_item_basis`
  - `reason_summary`
- `presence` 新增 `slot_bind`；
- 当 slot-bind basis 存在时，`model_attention` 会提示：
  - 后续模型应显式保留或基于新证据修正该 basis；
- 只有 `finance_slot_bind` 记录存在时，也可以形成一个 compact finance working state，
  防止中间轮依据被过滤掉。

边界：

- host 只转存模型生成的 basis；
- host 不根据 basis 改写 fact selection、formula request 或 final answer；
- planner/evaluator/synthesizer 仍由模型决定是否保留、修正、继续检索或输出限制；
- 空状态过滤仍保留，普通非金融 slot/transform 不会污染 prompt。

验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py::test_finance_working_state_for_prompt_summarizes_facts_traces_and_verifier_without_deciding_answer tests/test_kernel_v3_finance_engine.py::test_finance_working_state_includes_slot_bind_basis_without_fact_ledger tests/test_kernel_v3_finance_engine.py::test_agent_context_compiler_injects_compact_finance_working_state_for_model_planner tests/test_kernel_v3_phase5_semantic_processors.py::test_phase5_model_planner_prompt_preserves_compact_finance_working_state tests/test_kernel_v3_phase5_semantic_processors.py::test_phase5_model_evaluator_prompt_preserves_compact_finance_working_state -q
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_working_state or slot_bind_basis or model_planner_prompt_preserves_compact_finance_working_state or model_evaluator_prompt_preserves_compact_finance_working_state"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_retrieval_workbench.py -q
```

结果：

```text
5 passed in 1.03s
py_compile passed
11 passed, 258 deselected in 0.45s
244 passed in 2.63s
```

---

## 46. 追加落地：Slot-Bind Basis Reaches Synthesis and Numeric Judge

上一节让 `finance_working_state` 能把模型的 slot-bind basis 交给下一轮
planner/evaluator。本节继续补齐最后一段链路：普通 synthesizer、compact synthesis
rescue packet、以及 `finance.numeric_judge` 都能看到同一份 period/line-item basis。

问题：

- 最终回答阶段最容易丢失“为什么选择这个 FY / line item”的口径；
- Numeric verifier 失败后的 LLM judge/repair 如果只看到 unsupported numbers 和
  FormulaTrace，而看不到 slot-bind basis，容易修掉正确口径或引入新口径；
- `finance_slot_bind_state` 已经是模型自己的判断依据，应该贯穿最终合成和修复链路。

变更：

- `_report_with_finance_formula_traces()` 新增：
  - `finance_slot_bind_state`
  - `finance_slot_bind_basis_policy`
- `_compact_finance_synthesis_rescue_packet()` 同步携带上述字段；
- `_finance_numeric_judge_prompt()` 和 legacy prompt 从 report diagnostics 读取
  `finance_slot_bind_state` 并放入 judge packet；
- `_synthesizer_prompt()` 的 compact retrieval report 白名单新增：
  - `finance_slot_bind_state`
  - `finance_slot_bind_basis_policy`
- synthesizer answer requirements 增加说明：
  - 把 `finance_slot_bind_state.period_basis` / `line_item_basis` 视为模型先前的
    binding rationale；
  - 后续证据仍支持时保留；
  - 后续证据冲突时显式修正，而不是静默丢弃。

边界：

- host 不把 basis 当成答案真值；
- host 不根据 basis 做 fact selection；
- basis 进入 prompt 是为了让模型连续地管理自己的 period/line-item 判断；
- 后续模型仍可根据新的 facts/citations 修正 basis。

验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py::test_finance_formula_trace_support_links_traces_to_fact_citations_in_synthesizer_prompt tests/test_kernel_v3_finance_engine.py::test_compact_finance_synthesis_rescue_packet_exposes_formula_trace_support tests/test_kernel_v3_finance_engine.py::test_finance_numeric_judge_prompt_compacts_dynamic_context_for_cache -q
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/processors/adapters.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py -q -k "finance_formula_trace_support or compact_finance_synthesis_rescue_packet or finance_numeric_judge_prompt or finance_working_state or synthesizer"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_retrieval_workbench.py -q
```

结果：

```text
3 passed in 0.36s
py_compile passed
21 passed, 248 deselected in 0.68s
244 passed in 3.40s
```

---

## 47. 追加落地：Slot-Bind Competing Fact Clusters

本节针对 noisy SEC companyfacts / filing table 的通用问题：同一公司、同一期间、相近
指标下经常出现多个候选值，例如季度库存 vs 年度库存、operating revenue vs total
revenues and other income、capex outflow vs PP&E net。模型原本可以从 `raw_facts`
中自己发现冲突，但长列表下容易漏看。本节增加 compact attention index，不改变语义
决策归属。

变更：

- `finance.slot_bind` prompt contract 明确：
  - `slot_bind_packet.competing_fact_clusters` 是 host-built attention index；
  - candidate order 是 raw facts source order，不是 semantic ranking；
  - 模型必须仍从 raw fields 自己做 period/line-item 判断。
- `_finance_slot_bind_packet()` 新增：
  - `competing_fact_clusters`
- cluster 内容包括：
  - `entity_key`
  - `period_key`
  - `metric_family_hint`
  - `candidate_count`
  - `distinct_value_count`
  - `host_role = attention_grouping_only_no_semantic_preference`
  - `candidate_ordering = source_order_from_raw_facts`
  - compact candidates with fact_id, value, period, citation_ref, raw_fields。

边界：

- host 只按实体/期间/粗粒度指标聚类；
- host 不选择 best fact；
- host 不改变 raw facts 顺序；
- host 不把 cluster 当答案依据；
- cluster 的唯一目标是让 LLM 更容易发现“这里有冲突候选，需要显式判断”。

验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py::test_finance_slot_bind_prompt_exposes_raw_fields_not_host_period_labels tests/test_kernel_v3_finance_engine.py::test_finance_slot_bind_prompt_keeps_late_large_ledger_candidates_visible -q
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_retrieval_workbench.py -q
```

结果：

```text
2 passed in 1.04s
py_compile passed
244 passed in 3.29s
```
