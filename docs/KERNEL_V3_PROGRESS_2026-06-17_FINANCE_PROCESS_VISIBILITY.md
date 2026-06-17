# Kernel v3 2026-06-17 Finance Process Visibility

记录时间：2026-06-17 10:43:16 CST +0800
分支：`kernel-v3`
状态：已实现并通过本地工程回归；包含一条 live FinanceBench debug row 结果。

## 1. 背景

2026-06-17 的成熟组件化转向之后，Kernel v3 已经接入 EdgarTools
路径并完成 SEC live smoke。随后重新跑 FinanceBench debug row offset 3
时，UbuntuHolo 的稳定性问题变得更明显：单题 live run 可能持续数分钟，
全局 journal 已超过 1.3GB，如果仍靠手动 `ps`、`tail`、全量 JSONL scan
观察进度，监控本身会成为系统负担。

因此本次迭代把“进程可视化”纳入正式 CLI，而不是临时排查动作。

## 2. 新能力

`bench finance-progress` 现在支持：

```bash
.venv/bin/python -m kernel_v3.cli bench finance-progress \
  --thread-prefix finance-bench-0001 \
  --run-root /tmp/holo-kv3-live-debug/fb-o003-l001-edgartools-20260617 \
  --tail-bytes 64000000 \
  --limit-events 8
```

关键变化：

- 默认只读 journal 尾部 `64MB`，避免每次进度查询都扫描完整
  `.state/kernel_v3/journal/global.jsonl`。
- `--tail-bytes 0` 保留完整历史扫描能力，用于查看很老的 task。
- `--run-root` 汇总 benchmark run 目录：
  - `results.jsonl` 是否存在、大小、行数、mtime；
  - `summary.json` 是否可解析、`passed_count`、`failed_count`、
    `pass_rate`、`average_total_tokens`；
  - `http-cache` 文件数、总字节、最新 mtime；
  - worker state 目录状态；
  - `/proc` 中匹配当前 run-root 且为真实 `bench finance` 的进程。
- 文本 renderer 直接显示 journal tail 是否截断、run-root 状态、PID/RSS、
  agent loop 阶段、open processor、latest error、counters、diagnostics 和
  recent events。

这不是金融分数优化；它是长跑 live benchmark 的控制面。

## 3. Live FinanceBench debug row 结果

本次在修复 runtime 空值容错后，重新跑了之前失败的 FinanceBench debug
row offset 3：

```text
item_id: financebench_id_01226
question: What drove operating margin change as of FY2022 for 3M?
provider/model: deepseek/deepseek-v4-flash
execution_profile: finance-capability
live_retrieval: on, SEC hosts allowlisted
run_root: /tmp/holo-kv3-live-debug/fb-o003-l001-edgartools-20260617
status: passed
passed_count: 1
failed_count: 0
pass_rate: 1.0
total_tokens: 448778
processor_calls: 17
fetch_attempts: 12
fetch_bytes: 8129285
synthesis_gate_status: passed
score_reason: numeric_within_tolerance
```

Gold/reference policy:

- `data/bench/finance/financebench_doc_retrieval.gold.jsonl` 只通过
  `--dev-gold` 用于 post-run scoring。
- Gold/reference 没有进入 runtime prompt、retrieval context、tool
  context 或 memory。
- 这是一条 debug row live 验证结果，不代表 test100 held-out 分数。

## 4. 暴露出的下一步问题

可视化让本题的残留问题更清楚：

- 单题平均 tokens 仍高，本次约 `448,778` tokens。
- `finance_numeric_verification` 仍报告过
  `unsupported_answer_number / ledger_extraction_gap /
  primary_source_numeric_binding_failed`，最终由 synthesis gate 修复后通过。
- `calculator_result` 和 `finance.verify_numeric` 在这条 disclosure analysis
  题中没有实际调用；这不影响本题通过，但说明 slot/frame/formula
  绑定还需要继续收敛。
- 全局 journal 体积已达到 GB 级，后续应继续推进 journal rotation 或按
  run/thread 分片的长期治理。

## 5. 工程回归

本次新增：

```text
tests/test_kernel_v3_finance_progress_monitor.py
```

覆盖内容：

- tail-bounded JSONL scan 能找到最新 finance task；
- `--run-root` 能汇总 `results.jsonl`、`summary.json`、`http-cache`；
- renderer 能显示 run-root、open processor 和 summary token 指标。

已运行检查：

```bash
.venv/bin/python -m py_compile kernel_v3/cli.py kernel_v3/agent/runtime.py tests/test_kernel_v3_finance_progress_monitor.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_progress_monitor.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py::test_finance_formula_name_from_program_like_tolerates_missing_line_item -q
```

结果：py_compile 通过，新增 progress monitor 测试 `1 passed`，runtime
空值容错测试 `1 passed`。
