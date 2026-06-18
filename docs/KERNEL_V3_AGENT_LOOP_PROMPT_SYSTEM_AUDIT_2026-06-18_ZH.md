# Kernel v3 Agent Loop Prompt System Audit

Date: 2026-06-18

本文件记录对 Kernel v3 单 agent loop prompt system 的审查结果。范围包括
planner prompt、provider compact payload、deep assistant-turn prompt、streaming
tool-result continuation、finance task compile / slot bind / numeric judge /
finalizer synthesis 等模型可见合同。

## 结论

当前 prompt system 已经把 FB/FQA 需要的关键约束放进真实模型上下文，而不是只写在文档里：

- provider/planner prompt 暴露 `finance_agent_loop_contract`,
  `llm_first_finance_template`, `finance_question_requirements`,
  `answer_output_contract`, `benchmark_solvability_policy`。
- deep assistant-turn prompt 暴露 `single_agent_tool_loop_contract`，并包含
  `answer_output_contract`, `benchmark_solvability_policy`, `stop_rule`。
- 通用 `ASSISTANT_TURN_PROMPT_CONTRACT` 明确要求：如果
  `single_agent_tool_loop_contract` 存在，模型必须遵守其中的 stop/output/replan 规则。
- streaming/native tool continuation 继承首轮 user prompt；工具结果作为 bounded
  tool message 回灌，同时带 `artifact.query` / `artifact.read` hints。
- finalizer 边界仍然是 gate/synthesis，不允许隐藏创建 SEC、slot bind、calculator 或 verifier 结果。

这不是 benchmark 分数；它是 prompt/loop 合同完整性检查。

## Prompt 层级

### 1. Planner / Provider Compact

入口：

- `kernel_v3.agent.runtime._planner_directive`
- `kernel_v3.processors.adapters._planner_prompt`
- `kernel_v3.processors.adapters._compact_runtime_directive_for_provider`

模型可见内容：

- 23 个 allowed tools 的 `tool_selection`。
- `finance_agent_loop_contract`。
- `llm_first_finance_template`。
- `finance_question_requirements`。
- `answer_output_contract`。
- `benchmark_solvability_policy`。

关键约束：

- FB/FQA 风格任务默认 intended-solvable。
- 禁止一次 search/parser/tool miss 后 generic give-up。
- 必须用工具完成证据、表格、计算、verification 后再 final。

### 2. Deep Assistant-Turn Prompt

入口：

- `kernel_v3.deep_loop._assistant_turn_prompt`

模型可见内容：

- 通用 `assistant.turn` JSON 输出格式。
- `single_agent_tool_loop_contract`。
- `continuation_contract`。
- `tool_surface`。
- `tool_call_protocol`。

关键约束：

- 如果 `single_agent_tool_loop_contract` 存在，模型必须遵守其中的
  `stop_rule`, `answer_output_contract`, `benchmark_solvability_policy`。
- feedback 为 `continue` 时，`continuation_contract` 会要求不能在没有新 tool
  observation 的情况下 final。
- 工具失败是 observation，不是失败结论。

### 3. Streaming Tool-Result Continuation

入口：

- `kernel_v3.deep_loop._provider_tool_result_continuation_messages`
- `kernel_v3.deep_loop._provider_tool_result_content`

模型可见内容：

- 首轮 user prompt 原样保留在 continuation message list。
- assistant tool call message。
- bounded tool result message。
- `tool_result_artifact_id`。
- `artifact_query_hint` / `artifact_read_hint`。

关键约束：

- 工具大结果不直接灌爆上下文；模型可用 artifact query/read 继续检查。
- continuation round 不会丢失初始 loop/prompt contract。

### 4. Finance-Specific Model Prompts

入口：

- task compile: `kernel_v3.finance.task_compiler`
- slot bind: `kernel_v3.agent.runtime._finance_slot_bind_prompt`
- numeric judge: `kernel_v3.agent.runtime._finance_numeric_judge_prompt`
- synthesis/finalizer: `kernel_v3.agent.runtime` / `kernel_v3.processors.adapters`

关键约束：

- LLM 做语义判断，host 只做 schema/policy/execution/journal/verifier。
- calculator/table/slot bind/verifier 都必须是 loop 内模型请求结果。
- unsupported numbers、hard thresholds、generic peer benchmark 不允许进入最终答案。
- supported facts/formula traces 足够时，应 repair/answer，不应继续空转。

## 已锁定测试

新增/覆盖的关键检查：

- `test_finance_capability_provider_compact_preserves_one_shot_tool_surface`
- `test_finance_capability_assistant_turn_prompt_exposes_stop_and_answer_contract`
- `test_deep_agent_loop_prompt_blocks_final_when_feedback_requires_tool_work`
- `test_assistant_turn_prompt_exposes_strict_finance_single_agent_loop_contract`
- `test_streaming_loop_injects_tool_results_into_provider_continuation`

验证结果：

- targeted prompt tests: `5 passed`
- deep/profile: `60 passed`
- finance engine: `312 passed`
- finance-tool-audit smoke: `status=ok`, `fb_fqa_required_tool_status=ok`,
  `allowed_tools=23`, `provider_tool_selection=23`, `planner_prompt_tool_selection=23`

## 当前边界

工程上，prompt system 已经对齐到：只要 LLM 足够强，模型可以 one-shot
发现工具、请求工具、读回 artifact、重规划、计算、验证，并按答案合同 final。

仍然不能把这当作能力分数。FinanceBench/FQA 准确率必须来自 live model run，
gold/reference 只能用于 post-run scoring。
