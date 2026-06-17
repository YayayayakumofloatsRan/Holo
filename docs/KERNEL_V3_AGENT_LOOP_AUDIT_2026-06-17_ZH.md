# Kernel v3 2026-06-17 Agent Loop Logic Audit

记录时间：2026-06-17 CST +0800  
分支：`kernel-v3`  
状态：逻辑审查与边界收紧已落地；未启动 live benchmark。

## 1. LangChain / LangGraph 关系澄清

当前 Kernel v3 没有把核心执行 loop 交给 LangChain 或 LangGraph。

实际运行路径仍是 Holo 自有 runtime：

```text
LoopControllerV3
  -> ContextCompiler
  -> Planner / model planner
  -> PolicyGate
  -> ToolRegistry
  -> Observation + Artifact journal
  -> post-observation ContextCompiler
  -> _RecipeEvaluator + WorkloopEvaluator
  -> StopController / result / failure report
```

`langgraph==1.2.5` 已安装，并在工具目录中登记为双层 agent loop 的候选成熟组件。它目前不是 active runtime。这个边界很重要：不能汇报成“已经用 LangGraph 接管了 loop”。更准确的表述是：

- LangChain：参考其模型、工具、检索器、structured output、middleware 和生态接口思想。
- LangGraph：参考其 state graph、durable execution、checkpoint/resume、streaming、interrupt、memory/replay 思想。
- Holo：当前仍拥有 host-owned loop、权限、journal、预算、验证、gold isolation 和最终停止边界。

后续如果接入 LangGraph，应当把 Holo 的不变量包装成 graph nodes，而不是让 LangGraph/LangChain Agent 替代 Holo 的 host 边界。

## 2. Loop 必须满足的不变量

1. Planner 只能提出 action，不能执行 action。
2. 每个 action 执行前必须经过 `PolicyGate`。
3. 每个工具调用必须通过 `ToolRegistry`，不能在 planner/evaluator 中旁路执行。
4. `LoopControllerV3` 不能按具体金融工具名写分支；领域逻辑属于 recipe/evaluator/tool manifest/finance substrate。
5. 每步执行前编译 planner context；工具 observation 写入 journal 后，再重新编译 evaluator context。
6. Budget guard 必须在执行前阻止确定会越界的 action。
7. Tool observation 是模型重规划输入，不是 host 语义结论。
8. 可恢复组件失败进入 replan；policy、权限、预算和安全 guard 保持 host-owned 阻断。
9. Gold/reference 只允许 post-run scoring，不能进入 prompt、tool、retrieval 或 memory。
10. Final answer 必须经过 evidence/citation/numeric/synthesis gate；fake/offline tests 不能作为金融能力证据。

## 3. 本次审查修正

### 3.1 网络预算执行前越界检查

审查发现 `max_network_fetches` 过去只检查“已用 network fetches 是否达到上限”，没有检查“本次 action 的预计 fetch 成本加上已用量是否会越界”。

已修正为 projected-cost guard：

```text
if network_fetches + requested_network_fetches > max_network_fetches:
    block before tool execution
```

这保证声明成本已经超过剩余预算的 network action 不会进入工具执行层。回归覆盖：

- `test_loop_max_network_fetches_guard_blocks_projected_budget_overrun_before_execution`
- `test_phase61_network_budget_does_not_preempt_tool_observation_when_budget_remains`

### 3.2 Evaluator 使用 post-observation context

Loop 当前会在 observation 写入 journal 后重新编译 context，再交给 evaluator。这是正确方向：evaluator 必须看到刚发生的 observation、artifact、tool failure、citation 和 trace，而不是 planner 的旧上下文。

旧测试已更新为检查：

- planner context 是 action 前状态；
- evaluator context 是 observation 后状态；
- 两者 section 结构一致，但 context hash 不应相同。

### 3.3 可恢复工具失败回到模型重规划

金融工具链扩展后，Docling/OpenBB/Trafilatura/DuckDB/SymPy/SEC 等组件可能出现依赖缺失、组件调用失败、URL 不支持、SQL 被拒、route 不在 allowlist 等情况。之前 generic evaluator 会把这些 `failed/blocked` observation 直接变成终局失败。

已新增 recoverable toolchain failure replan：

```text
tool failure observation
  -> _tool_failure_can_replan
  -> Feedback(status="continue", missing_evidence=["tool_failed_replan", ...])
  -> planner sees failed tool diagnostics
  -> model chooses another source family/tool path
```

`policy_block` 不进入这个通道，避免绕过权限和安全边界。

## 4. 当前结论

当前系统的核心 loop 不是 LangChain/LangGraph runtime，而是 Holo 自有 loop。这个状态并不错误，但必须如实认识：我们现在做的是把 LangGraph/Hermes/Semantic Kernel 的原则落到 Holo 自己的 loop 里。

短期更重要的是先把 Holo loop 的逻辑闭环做严：

- planner/evaluator 发包稳定；
- 工具 schema 与权限稳定；
- 预算执行前拦截；
- observation 后 context refresh；
- 可恢复失败 replan；
- 安全失败阻断；
- evidence/numeric/final gates 不被绕过。

只有这些不变量稳定后，再把执行 runtime 迁移或包进 LangGraph 才有意义。否则只是把不清晰的 loop 包进一个开源框架，问题不会消失。

