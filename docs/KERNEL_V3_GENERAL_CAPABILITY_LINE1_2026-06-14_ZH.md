# Kernel v3 通用能力强化第一线：上下文、缓存与常驻工作能力

Date: 2026-06-14

## 目标

这一线的目标不是把金融题写成规则系统，而是把 Holo Kernel v3 做成更强的通用工作 agent 基座：模型负责理解、计划、判断和综合，host 负责校验、执行、记录、预算和停止。金融能力是当前主战场，但底层能力必须能迁移到工程、数学、物理、研究、文档、检索、记忆和常驻任务。

当前优先级：

1. 给 LLM 更稳定、更完整、更低噪声的上下文；
2. 提高 DeepSeek 上下文缓存命中率，降低常驻成本；
3. 让 cache hit/miss、token、工具调用、检索和最终答案都进入可观测轨迹；
4. 保持 model-first agent loop，不把语义判断写成关键词表或阈值拦截；
5. 建立通用能力 smoke/gauntlet，避免金融专项优化破坏普通对话、文档、研究和工具组装能力。

## DeepSeek 官方约束

本轮参考 DeepSeek 官方文档后形成以下工程约束：

- Context Caching 是自动机制，重复的 prompt 前缀才会命中；缓存粒度以 64 tokens 为单位。见 DeepSeek Context Caching 公告：https://api-docs.deepseek.com/news/news0802
- DeepSeek usage 中会返回 `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens`，这是 Holo 判断缓存收益的真实指标，而不是估计值。见同上。
- 多轮对话本质上会把历史 messages 连接成当前 prompt，因此稳定前缀和动态尾部的顺序会直接影响缓存。见 DeepSeek multi-round chat guide：https://api-docs.deepseek.com/guides/multi_round_chat
- Prefix completion 是 beta 接口能力，需要 `https://api.deepseek.com/beta`，不应默认混入普通 processor 调用。见 DeepSeek chat prefix completion guide：https://api-docs.deepseek.com/guides/chat_prefix_completion
- 成本应按 cache hit/miss token 分开看。见 DeepSeek pricing：https://api-docs.deepseek.com/quick_start/pricing

## Kernel v3 上下文顺序契约

为了同时提升能力和缓存命中率，provider prompt 应维持稳定前缀、动态尾部的结构：

1. stable kernel contract：Holo 身份、host-owned invariant、安全边界、输出协议；
2. stable workmethod/domain templates：通用工作法、金融研究模板、数学/工程/研究任务模板；
3. stable tool manifest：按能力分组、稳定排序、字段稳定的工具说明；
4. durable memory digest：经 host 管理的长期记忆摘要，稳定条目优先，变化条目靠后；
5. task-local context：当前线程摘要、最近失败、可用证据、当前计划；
6. dynamic tail：用户当前请求、最新工具观察、错误、检索结果、预算状态。

这不是规则决策。它只是把同样的信息放到更适合 LLM 推理和 provider 缓存的位置。任务是否需要检索、工具、数学计算、文件读写或直接回答，仍应由 LLM processor 在 host 暴露的工具与上下文内决定。

## 本轮落地

本轮代码层先补齐了缓存可观测性：

- `kernel_v3.processors.usage.coerce_usage` 保留 DeepSeek `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`；
- 同步计算 `prompt_cache_hit_ratio`，用于后续批量测试和成本报告；
- console 的 model result 行显示 `cache_hit`、`cache_miss` 和 `cache_ratio`；
- Windows demo dashboard 的 processor 元信息显示 `cache xx%`；
- 新增单元测试覆盖 usage 归一化和 console cache 摘要；
- 新增 `kernel_v3.bench.general`，形成 kernel v3 自己的一等通用能力 gauntlet；
- 新增 CLI 入口：`python -m kernel_v3.cli bench general`；
- 新增 `--case-id` / `--category` 过滤，live 调试可以先跑小批次，避免一次全量任务在深研题上无界消耗；
- general gauntlet 默认覆盖 9 类任务面：direct chat、roleplay/writing、technical docs research、academic research、workspace read、memory recall、system time、math/compute、resident reminder boundary；
- general gauntlet 输出 report、summary 和 jsonl，summary 包含 mode/tool/domain 覆盖以及 live runs 的 token/cache hit 汇总。
- live scoring 将 `pending_question` 视为 boundary/clarification 类任务的有效交互输出；例如 resident reminder 在 reminder tool 未配置时应进入 `needs_user_input`，而不是伪装成已设置提醒。

这一步很小，但必要。后续所有“更长上下文”“记忆摘要”“并行 loop”“长期常驻”的优化都必须能回答两个问题：能力是否提高，成本是否下降。

## 通用能力强化路线

### 1. Model-first triage

普通问候、短问答、低风险闲聊应由 LLM 判断为 direct response，不进入重型检索 loop。复杂任务则由 LLM 明确拆解子目标，并选择工具。host 可以限制预算、权限和 schema，但不应用关键词表替代语义判断。

### 2. Context compiler v3

把旧 Stage121/156 的思想迁移到 kernel v3 processor fabric：

- 生成稳定前缀 hash 和动态尾部 digest；
- 记录 prompt section token 估算；
- 保持工具 manifest 稳定排序；
- 将易变时间戳、run id、错误详情放在 dynamic tail；
- 将 thread summary、durable memory、domain template 分层压缩。

### 3. Parallel workbench

对金融、研究和工程任务，允许 LLM 提出多个并行子任务：

- evidence branch：检索与来源质量；
- calculation branch：公式、单位、表格、数值一致性；
- critique branch：反证、口径差异、风险；
- synthesis branch：把证据和计算压成最终答案。

host 负责并行执行和 journal 合并，LLM 负责判断哪些分支必要、如何解释冲突、何时停止。

### 4. Durable memory as managed context

记忆不应只是历史聊天堆积，而应分为：

- user/project directives；
- task methods and mistakes；
- source preferences and known datasets；
- benchmark failure patterns；
- stable demo/project facts。

所有记忆进入 prompt 前必须经过 host 摘要、去重和预算控制。

### 5. General gauntlet

金融 benchmark 之外，需要固定一组通用能力测试：

- direct chat：问候、简短解释、用户情绪压力下的稳态回答；
- roleplay/writing：自然表达但不破坏边界；
- technical research：官方文档/API/SDK 资料检索；
- academic research：论文、前沿研究、综述和开放问题；
- workspace read：临时读文件、搜索、整理结果；
- memory：跨轮保留项目约束但不污染当前任务；
- system：当前时间、环境状态等 host 工具；
- math/compute：可验证推理和计算；
- resident tasks：长任务持续推进、暂停恢复、事后汇报。

当前 contract gauntlet 不是离线伪造 live 分数。它检查的是：当 LLM 提出某类语义 intent 时，host 是否给出正确 mode、工具面、domain/profile 和可观测指标。加 `--live` 后同一入口可以真实调用 chat runtime 与模型栈。

命令：

```text
python -m kernel_v3.cli bench general
python -m kernel_v3.cli bench general --live --online
python -m kernel_v3.cli bench general --live --online --category direct_chat --category system
```

2026-06-14 live smoke 已跑完 9 类覆盖，按小批次组合统计：

- 9 / 9 passed；
- categories：direct_chat、roleplay_writing、technical_research、academic_research、workspace_read、memory、system、math_compute、resident；
- mode coverage：direct_answer 2、semantic_answer 3、retrieval_answer 2、workspace_answer 1、system_answer 1；
- tool coverage：retrieval.run、workspace.search,file.read、memory.recall、system.time、calculator.compute；
- combined total tokens：660,688；
- combined prompt cache hit tokens：204,800；
- combined prompt cache miss tokens：436,299；
- combined prompt cache hit ratio：31.9451%。

Artifacts:

- `.state/kernel_v3/bench/general/live_direct_20260614.jsonl`
- `.state/kernel_v3/bench/general/live_research_20260614.jsonl`
- `.state/kernel_v3/bench/general/live_workspace_memory_resident_20260614.jsonl`
- `.state/kernel_v3/bench/general/live_resident_20260614.jsonl`

Observed issues from live smoke:

- Academic frontier research can trigger `deepseek-v4-pro` and very large prompts. `execution_metadata.agent_loop` carried `max_steps=6/max_tool_calls=4`, but the retrieval recipe still showed `max_steps=2048/max_tool_calls=1024`, so recipe-level loop-budget propagation needs a fix.
- Retrieval research costs are much higher than direct/system/math tasks. The current 2 research cases consumed 414,318 tokens; direct/system/math/roleplay consumed 136,363 tokens.
- Technical docs research succeeded with live retrieval and citations, but answer redaction can over-redact API-auth examples as `[REDACTED:SECRET]`; redaction needs more precise handling for public documentation snippets.

2026-06-14 follow-up:

- The recipe-level loop-budget propagation issue is fixed. CLI/runtime explicit `--max-agent-steps`, `--max-agent-tool-calls`, and artifact-byte overrides now carry `agent_loop.source=explicit_cli`, and runtime treats explicit loop budgets as hard caps even under model planner and `long-mission`.
- Regression coverage was added for both no-profile model-dynamic retrieval and long-mission explicit overrides. This prevents `max_steps=6/max_tool_calls=4` from being widened back to `2048/1024`.
- Processor prompts now preserve stable-prefix ordering instead of alphabetical JSON ordering: `contract` is emitted before dynamic `context`, `observation`, `feedback`, and evidence sections. The JSON is also encoded compactly. This should improve DeepSeek cache friendliness and reduce prompt tokens without changing LLM decision ownership.
- Verification: `.venv/bin/python -m pytest tests/test_kernel_v3_execution_profile.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_general_capability_gauntlet.py` passed 26/26; `.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py` passed 49/49; `.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/cli.py kernel_v3/processors/adapters.py` passed.
- Post-fix low-cost live smoke: `bench general --live --online --category direct_chat --category system --max-agent-steps 4 --max-agent-tool-calls 2` passed 2/2. Summary: total tokens 60,616; prompt cache hit tokens 16,128; prompt cache miss tokens 43,784; cache hit ratio 26.9195%; tool coverage `system.time`; artifacts at `.state/kernel_v3/bench/general/live_cache_smoke_20260614.*`.
- The smoke journal confirms explicit loop limits were enforced in host situation: both direct/system tasks show `max_steps=4` and `max_tool_calls=2`, not `2048/1024`; the direct chat task did not enter retrieval, while the system time task used `system.time`.

## 成功指标

短期应记录：

- provider cache hit/miss tokens and ratio；
- total tokens per solved task；
- model calls per solved task；
- tool calls per solved task；
- retrieval fetch/cache hit rate；
- answer correctness / reasonable pass rate；
- blocked reason distribution；
- direct-chat latency；
- long-task resume success rate。
- general gauntlet pass rate；
- general gauntlet tool/domain/mode coverage。

中期目标不是只追单题高分，而是单位成本下的真实成功率：更少重复发包、更少无效检索、更高可解率、更稳定的最终答案。

## 当前风险

- DeepSeek cache 命中依赖完全相同的长前缀；如果 prompt 中早早插入时间、run id、随机排序工具或临时错误，命中率会很差。
- 金融专项 prompt 过强时，普通任务可能被误导进入不必要的研究 loop。
- 过度展示内部文本会让 UI 噪声过高；演示层应展示结构化 public trace、工具调用、计划和摘要，而不是依赖大段原始文本。
- 并行化会提升速度和覆盖，但也会增加 token 成本；必须有 per-task budget 和 branch usefulness 统计。

## 下一步

1. 将 context compiler 接入 kernel v3 processor request，输出 stable/dynamic section metadata；
2. 对 DeepSeek live runs 汇总 cache hit ratio，和 finance/general gauntlet 结果一起入报告；
3. 用 `bench general --live --online` 跑 DeepSeek live general smoke，记录 direct-chat latency、model calls、cache hit ratio 和失败样例；
4. 在 finance workbench 中试点 LLM 提出的并行 branch plan；
5. 把 memory digest 从“可读历史”升级成“可控工作上下文”。
