# Holo Kernel v3 系统梳理与汇报讲义

日期：2026-06-13

本文档用于整理当前本地 Kernel v3 工作状态，并给出可以用于结项汇报、演示录制和后续迭代的统一口径。重点不是把 Holo 描述成已经无所不能，而是准确说明这几个月完成了什么：Holo 已经从早期阶段化实验，推进到一个有可审计 agent loop、工具接口、检索取证、金融事实账本、计算验证、可视化演示和 live benchmark 证据的 Kernel v3 harness。

## 一句话定位

Holo Kernel v3 是一个 host-owned agent harness：LLM 负责语义判断、任务分解、证据选择和答案合成；host 负责工具暴露、权限验证、执行、记录、证据校验、数值验证、停止条件和长期记忆边界。

金融是当前最重要的压力测试场景，但 Kernel v3 的目标不是写一个金融脚本，而是形成可迁移到数学、物理、代码、研究和行业任务的通用高智力工作基座。

## 为什么这几个月没有白干

可以对外展示的成果不是某一道题答对，而是系统工程形态已经成型：

1. Kernel v3 已经与旧 stage line 分离，核心代码集中在 `kernel_v3/`，并且有明确的 host-owned agent invariant。
2. Agent loop 不再是单轮聊天。它包含 semantic intake、task compile、planner、policy gate、tool execution、evaluator、workloop、stop controller、final synthesis、journal。
3. 工具不是随意调用。工具通过 `ToolRegistry` 和 `PolicyGate` 暴露，host 验证工具名、action id、payload schema、权限和执行结果。
4. 检索系统已经从“搜索一下”发展为 retrieval operator/workbench：搜索、抓取、抽取、证据压缩、citation、source quality、workbench judgment、continue/finalize。
5. 金融子系统已经有事实账本、slot frame、transform plan、calculator trace、numeric verifier、synthesis gate 和 benchmark scorer。
6. 当前已有 live benchmark 成绩和失败诊断，而不是只靠离线伪测试。
7. Windows 端可通过 dashboard 观察 agent 运行、工具、事实、引用、pipeline 和 demo case。
8. 最近的迭代方向已经回到正确架构：不是用规则打表，而是让 LLM 做核心语义判断，host 只做取证、排序、验证和记录。

## Kernel v3 核心架构

### 1. 外层运行与状态

主要模块：

- `kernel_v3/chat/`：交互式 chat runtime、线程管理、用户输入、可观察事件流。
- `kernel_v3/journal.py`：全局审计日志，记录任务、工具、模型调用、检索、答案和失败。
- `kernel_v3/session.py`：任务状态。
- `.state/kernel_v3/`：默认状态根目录，包含 journal、thread、bench、artifact、memory 等运行数据。

关键意义：

Holo 不是只返回一个答案，而是保留“为什么走到这个答案”的执行证据。对于演示来说，journal 和 dashboard 能证明系统不是黑箱聊天。

### 2. Agent loop

主要模块：

- `kernel_v3/loop.py`
- `kernel_v3/agent/runtime.py`
- `kernel_v3/agent/workloop.py`
- `kernel_v3/agent/taskgraph.py`
- `kernel_v3/agent/semantics.py`
- `kernel_v3/agent/answer_profile.py`

标准流程：

1. 编译上下文和线程工作集。
2. LLM 进行 semantic intake，理解任务类型、目标和约束。
3. task compiler 形成结构化 task program。
4. planner 选择下一步动作。
5. host 通过 policy gate 验证动作。
6. tool registry 执行工具。
7. evaluator 阅读 observation，判断进展和缺口。
8. workloop 决定继续、修复、请求输入、失败或最终回答。
9. final synthesis 输出答案，host 进行 citation、numeric、schema 和 answer profile 检查。
10. 全过程写入 journal。

核心边界：

LLM 可以提出判断和动作，但不能直接执行系统动作，不能直接写 durable memory，不能绕过证据和工具权限。host 可以验证和拒绝，但不应该替代 LLM 做金融语义裁决。

### 3. Processor fabric

主要模块：

- `kernel_v3/processors/`

职责：

- 统一模型调用接口。
- 支持 fake provider、live provider、JSON repair、routing、usage 记录。
- 把不同模型任务拆成明确 task type，例如 semantic intake、planning、retrieval workbench、finance numeric judge、synthesis。

汇报口径：

Kernel v3 已经不是“直接把问题丢给模型”，而是把模型调用拆成多个受控 processor packet。每个 packet 都有输入、输出 schema、用途和日志。

### 4. Retrieval and evidence

主要模块：

- `kernel_v3/retrieval/`
- `kernel_v3/research/`

能力：

- source directory、query template、crawl、SEC EDGAR、HTTP provider、web search provider。
- evidence extraction、citation、evidence compaction、source ranking。
- retrieval workbench 让 LLM 判断 evidence 是否足够、下一步应查什么、哪些证据可用、哪些缺口仍存在。

当前意义：

金融、研究、政策、代码调查等任务都需要 evidence loop。Kernel v3 的检索系统已经是通用能力，不是金融专用脚本。

### 5. Finance domain pack

主要模块：

- `kernel_v3/finance/`
- `kernel_v3/bench/finance.py`
- `kernel_v3/bench/public_finance.py`

能力：

- 财务事实抽取和 fact ledger。
- target document binding。
- metric disambiguation。
- formula planner。
- calculator trace。
- numeric verifier。
- benchmark import and scoring。
- reasonable judge。

当前重点：

Holo 在金融上不应该只会“找一个数字”，而应该能说明这个数字来自哪里、是否匹配问题口径、是否需要公式、公式如何计算、最终答案是否被 citation 支撑。

### 6. Generic substrate

主要模块：

- `kernel_v3/substrate/`

核心对象：

- `ClaimLedger`
- `SlotFrame`
- `EvidencePolicy`
- `TransformPlan`
- `VerifierGateResult`

意义：

这些对象是把金融经验抽象成通用问题求解骨架。数学证明、物理推导、代码修复和金融研究都需要类似结构：声明要证明/回答什么，缺哪些 slot，有哪些证据，做哪些 transform，怎么验证。

### 7. Memory and long-horizon continuity

主要模块：

- `kernel_v3/memory/`
- `kernel_v3/mission/`
- `kernel_v3/workmethod/`

能力：

- durable memory proposal pipeline。
- read-only `memory.recall` 工具。
- mission supervisor。
- workmethod frame。
- thread RAG 和 task continuity。

意义：

Kernel v3 的长期目标不是每题从零开始，而是能记住项目约束、用户偏好、失败模式和下一步计划。当前已经有结构和接口，后续要强化“从失败中学习”的闭环。

### 8. Demo dashboard

主要模块：

- `kernel_v3/demo_dashboard.py`

当前用途：

- Windows 端可通过 `http://localhost:8787/` 观察 demo。
- 展示 run summary、pipeline、events、facts、citations、verifier、case selector。
- 目前默认 demo 已切到 metric disambiguation live14，同时保留 FinanceBench Activision fixed asset turnover 强 trace。

## 题库覆盖与任务类型

当前本地金融题库不是一个单一集合，而是多个任务族：

1. FinAgent / Finance Agent Benchmark 风格的财报事实题。
2. FinanceBench oracle evidence：给证据片段，考验读证据和计算。
3. FinanceBench doc retrieval：给目标文档或 URL，考验原始文档获取、表格定位和取证。
4. FinQA：表格和文本上的数值推理。
5. FAB / FAB v2：更接近 analyst workflow 的交易、估值、多公司比较、DIO、DCF/LBO 等任务。
6. 自建 dev/test/live slices：用于快速迭代 metric binding、retrieval、calculator、verifier 和 demo。

可以把题目按能力分成 7 类：

1. 单点财报事实抽取：例如某公司 FY2024 revenue、assets、net income。
2. 指标语义消歧：例如 net revenues、operating revenues、sales and other operating revenues、total revenues and other income。
3. 原始文档表格定位：从 10-K/PDF 的具体表格找数。
4. 多步公式计算：margin、growth、turnover、DIO、debt-to-equity。
5. 交易和估值研究：EV/revenue、DCF、LBO、并购交易。
6. 错误前提或信息不足识别：不能硬凑附近数字。
7. 通用表格数学推理：FinQA 风格的公式绑定和表格计算。

## 当前能稳定展示什么

### 稳定展示主线

建议主 demo 展示两个层次：

1. **真实财报事实抽取和指标消歧**
   - 展示 Holo 如何处理 net revenues、operating revenues 等不完全等同于 broad revenue 的问题。
   - 强调 LLM 读候选 fact 和 metric intent，host 只暴露候选、citation、source、verifier。

2. **FinanceBench Activision fixed asset turnover**
   - 展示 Holo 能从真实 10-K 场景完成多 slot 抽取和公式计算。
   - 这是一个好 demo，因为它不是单点 lookup，而是 revenue、FY2018 PP&E、FY2019 PP&E、average PP&E、ratio 的完整链路。

推荐讲法：

Holo 当前最稳定的能力是“source-grounded financial fact extraction + metric disambiguation + auditable calculation trace”。这已经覆盖了金融研究中最基础也最重要的一层：找到正确口径的数，并让结论可追溯。

### 已有 live 证据

可汇报结果：

- FinAgent live metric disambiguation shard：`run_metric_disambiguation_live14_20260613`
  - `11/14`
  - pass rate `78.57%`
  - answer present rate `1.0`
  - citation present rate `1.0`
  - synthesis gate pass rate `1.0`
  - 通过项包括 Goldman Sachs net revenues、NextEra operating revenues 等关键消歧题。

- FinanceBench Activision fixed asset turnover：
  - `run_demo_financebench_activision_fat_live_20260613`
  - strict benchmark passed
  - numeric accuracy `1.0`
  - overall score `1.0`
  - workflow score `1.0`
  - 结果 `24.26`
  - 包含大量 finance facts、claim ledger、transform plan、citation 和 synthesis gate。

- 早期/并行 live10 证据：
  - FinAgent dev/high-score slice 曾达到 `8/10`
  - holdout/test slice 也达到 `8/10`
  - 更宽的 holdout20 暴露真实弱点，不作为 headline，但可作为诚实诊断。

说明：

这些结果不应该包装成“金融全域已解决”。更准确的说法是：Kernel v3 已经在真实金融 live 任务上形成可演示能力，并且失败有可定位原因。

## 当前弱点

当前 Holo 仍然只能攻克一部分题，原因不是一个 prompt 没写好，而是金融任务本身有多个独立困难：

1. SEC companyfacts 和原始 10-K 主表口径可能不一致。
2. 同一个词 `revenue` 在不同行业有不同合法口径。
3. PDF/HTML 表格定位、年份列、单位、caption 容易错。
4. 多步公式题中任何一个 slot 错都会导致最终结果错。
5. 错误前提题需要主动拒绝或说明证据不足，不能选择最近数字。
6. provider 错误、余额、JSON drift、上下文截断都会影响 live run。
7. 当前 final answer discipline 仍需加强，避免答案中同时出现正确数和干扰数。

这也是为什么不能靠打表或阈值规则解决。正确方向是让 LLM 做 semantic binding 和下一步搜索判断，host 做证据组织、工具执行和机械验证。

## 最近本地改动整理

当前未提交代码改动集中在四个方向。

### 1. Finance fact metric intent 排序

涉及文件：

- `kernel_v3/agent/runtime.py`
- `tests/test_kernel_v3_finance_engine.py`

目的：

当问题问的是 `net revenues`、`operating revenues` 等具体口径时，Holo 不应该把所有 revenue 候选平铺给模型。host 现在会把候选 fact 附加 metric intent diagnostics，并按 target binding、metric intent、source authority、citation completeness 排序后暴露给 LLM。

边界：

排序不是答案规则。host 不替 LLM 选择答案，只是把更相关的候选放到模型更容易检查的位置，并把 competing facts 明确暴露出来。

### 2. Companyfacts 抓取预算修复

涉及文件：

- `kernel_v3/retrieval/http_provider.py`
- `kernel_v3/retrieval/fetch_budget.py`
- `tests/test_kernel_v3_retrieval_workbench.py`
- `tests/test_kernel_v3_phase90_http_fetch_provider.py`

目的：

SEC companyfacts payload 可能明显大于普通网页。此前 4MB 截断会导致 Pfizer 等大公司 companyfacts 信息缺失。现在对 companyfacts 提高 max bytes，并且 fetch cache key 包含 `max_bytes`，避免旧的小截断缓存污染大预算请求。

边界：

这是取证能力修复，不是答题规则。

### 3. Dashboard demo 强化

涉及文件：

- `kernel_v3/demo_dashboard.py`

目的：

默认 demo run 切到 `run_metric_disambiguation_live14_20260613`，并加入 Goldman net revenues 等 item-level case。界面增加 auto demo reel，用于不拖动界面的录制场景。

2026-06-13 后续 UI pass：

- Windows 浏览器 demo 保持 `http://localhost:8787/`。
- 界面改为英文为主，统一使用 Times New Roman。
- 首屏改为正式聊天控制台：右侧为大面积 chat transcript 与 composer，用户能持续看到输入、running 状态和最终回复，不再被 trace/tab 切走。
- 工作目录单独展示：workspace root、branch/head、state dir、thread id 与 provider surface 常驻可见，明确 Windows 浏览器正在观察 WSL 主工作区 `/home/ran_yakumo/holo`。
- 用户可以直接在浏览器输入任务，dashboard 后端用真实 `holo-v3 chat --once` 在 WSL 主工作区启动 Kernel v3 agent run。
- 同一界面常驻展示 workspace 状态、图形化 agent topology、processor/search/event signal cards 与 click-through inspector。
- Agent workflow 以 SVG 拓扑图展示 Intake、Plan、Policy、Tools、Search、Evidence、Verify、Answer，并用明确箭头表现执行连接与 verify-to-plan 回路，使观众能直接看到 Holo 的问题解决闭环，而不是只能读线性日志。
- Topology graph 严格按当前 console thread 的 journal 事件渲染；新线程没有事件时只显示 idle 节点，不再用历史 benchmark pipeline 填充当前线程视图。
- Processor / search / activity 不再默认展示长 prompt 或长输出；主界面只显示短标签、状态点、计数和 badges。点击节点或 signal card 后，inspector 才展示 host-visible processor contract、输出摘要、usage、错误状态或检索细节；隐藏 chain-of-thought 不暴露。
- Search branches 从 journal 的 `retrieval_search_attempt` / provider diagnostics 派生，默认展示分支号、source count、accepted source count 和 provider badges。
- Running 状态会先在 transcript 里显示 Kernel v3 正在运行，并在左侧 signal stream 中订阅 live journal；只要 agent 写入 processor/tool/retrieval/verifier 事件，拓扑节点和 signal cards 就实时变化。
- Trace 不再作为会让用户离开聊天上下文的顶部 tab；公开 trace 以图形拓扑、短 signal cards 和 inspector 显示。
- UI 支持 thread selector、New Thread 和 Clear Screen。Clear Screen 只清空本地演示视图，不删除 durable journal。
- 浏览器输入默认使用 Auto Chat：仍然启用模型 `turn-router`、`semantic-intake`、`planner`、`evaluator`、`synthesizer`，由 LLM 判断是普通回复、继续任务还是新任务；host 不做关键词拦截。Auto 只是不强制打开 live retrieval / deep research。Finance Deep 模式和金融快捷题会暴露更大的金融检索与工具预算。
- 快捷题目已换成更稳定的高难度金融案例：Goldman net revenues、Activision fixed asset turnover、3M capital intensity、NextEra operating revenue。
- Topology 和 signal stream 现在只展示当前最新 chat turn 的事件段，并在 terminal answer / failure 后冻结该轮 trace；这避免 Answer 已经输出后 Search/Tools 仍继续增长造成的错觉。
- Dashboard 新增 `/api/live` Server-Sent Events 通道，直接 tail Kernel v3 durable journal。浏览器收到 `chat_turn`、processor、tool、retrieval、evidence、verifier、answer 等记录后立即重绘 topology、signal cards、processor packets 和 transcript，不再等待下一次全量 state。
- `/api/state` 改为低频校准路径，刷新间隔为 5s，负责 workspace、benchmark、command metadata 和历史 trace 的初始化；新 live event 后的短窗口内不会被慢 state 响应反向覆盖，避免拓扑倒退或错序。
- 拓扑主路径改为两层图形结构：Intake -> Plan -> Policy -> Tools 与 Search/Evidence/Verify 分支汇合到 Answer，箭头保持前进方向；节点点击后的 inspector 状态不会被自动刷新抢焦点。
- 渲染层已针对录屏做抗遮挡处理：主视图减少文字，详细文字只在 inspector/局部滚动区域出现，避免长 prompt、长输出或长 URL 被组件遮挡。
- 后台命令执行会在 WSL 环境没有 `DEEPSEEK_API_KEY` 时尝试读取 Windows User/Machine 环境变量，并只注入子进程，不打印、不写日志；如果仍不可见，UI 会立即显示 `live_model_not_enabled`。

### 4. 回归测试

已经通过的关键测试：

- finance metric intent and fact ranking：`8 passed`
- retrieval/companyfacts cap and finance engine focused suite：`10 passed`
- phase90 HTTP fetch provider and cache separation suite：`36 passed`
- targeted cache-key tests：`3 passed`

这些测试证明本轮改动主要在工具取证、候选暴露和可视化，不是打表答题。

## 演示建议

### 录屏结构

1. 打开 dashboard。
2. 展示顶部 summary：run、pass、facts、citations、pipeline。
3. 选择 `Live14 metric disambiguation`。
4. 展示 Goldman Sachs `net revenues` item。
5. 说明系统如何暴露 competing revenue facts，而不是用规则直接选答案。
6. 切到 FinanceBench Activision fixed asset turnover。
7. 展示它不是单点事实，而是公式链：revenue / average PP&E。
8. 最后展示 journal/trace 或 events，证明每一步都被记录。

### 讲义口径

可以这样说：

Holo Kernel v3 已经具备一个高智力 agent harness 的核心闭环。LLM 负责理解问题、选择工具、判断证据和合成答案；host 负责工具执行、日志、引用、数值和安全验证。金融子系统当前已经能稳定处理一批真实财报事实抽取和指标消歧任务，并在 FinanceBench 的多步计算题上形成可追溯成功案例。接下来重点不是写更多规则，而是增强 primary filing/table grounding、multi-step slot filling、错误前提识别和长期自我修正。

## 理想金融 agent 的能力蓝图

如果 Holo 要成为超过人类专家的金融 agent，需要覆盖：

1. 财报事实抽取：10-K、10-Q、8-K、annual report、earnings release。
2. 会计概念理解：GAAP、non-GAAP、segment、行业特殊指标。
3. 多源交叉验证：SEC、公司官网、年报、新闻稿、市场数据。
4. 自动建模：DCF、LBO、comps、transaction multiples、sensitivity。
5. 异常检测：口径变化、重分类、一次性项目、披露变化。
6. 投资研究：行业比较、风险、催化剂、竞争格局。
7. 审计追溯：每个结论都能回到源文件、表格、行项目和计算步骤。
8. 长期学习：记住历史错误和用户偏好，持续优化工作方法。

Holo 当前刚刚完成其中的底座层：取证、事实、slot、transform、verifier、dashboard。它还没有完全达到研究团队级别，但已经不是普通聊天机器人。

## 与通用问题求解的关系

金融、数学、物理、代码和研究任务共享同一个底层结构：

1. 定义目标。
2. 拆成子问题。
3. 明确已知和未知。
4. 获取证据或建立公理/模型。
5. 做变换、计算、证明或实验。
6. 检查每一步是否成立。
7. 输出可验证结论。

区别在于：

- 数学更重形式证明，证据是定义、公理、引理。
- 物理更重模型、量纲、实验和边界条件。
- 代码更重可执行性、测试和接口约束。
- 金融更重真实数据、source grounding、口径判断、披露差异和可审计性。

因此，金融不是孤立方向，而是通用 agent harness 的高噪声真实世界训练场。

## 下一步优先级

### P0：汇报前必须稳定

1. 保持 dashboard 可打开、默认 demo 可读。
2. 保持 live14 和 Activision demo traces 可展示。
3. 文档和 README 指向当前正确口径。
4. 禁止把失败题硬修成规则或答案表。

### P1：真实能力增强

1. primary filing/table extraction。
2. final answer discipline，减少干扰数字。
3. LLM numeric judge 的稳定 JSON packet。
4. metric disambiguation prompt 和 fact ledger 继续增强。
5. 错误前提/信息不足识别。

### P2：跨域迁移

1. 把 SlotFrame、ClaimLedger、TransformPlan 推广到数学/物理/代码任务。
2. 为数学证明引入 proof ledger。
3. 为物理题引入 model/assumption/derivation ledger。
4. 为研究任务引入 source map、claim map、counter-evidence map。

## 当前汇报结论

最稳妥的总结是：

Holo Kernel v3 已经形成一个可运行、可观察、可审计的 LLM+tool agent harness。它在金融领域已经完成了结构化财报事实抽取、指标消歧、多步计算 trace、引用验证和 live demo dashboard 的闭环，并取得了可汇报的 live benchmark 成绩。当前系统尚未完全解决复杂金融研究，但失败已经能被定位到 source grounding、metric binding、table extraction、slot filling 或 provider stability 等具体层面。下一阶段的核心不是增加规则，而是继续强化 LLM 语义判断与工具取证之间的标准化接口，使金融能力成为通用高智力问题求解能力的第一个成熟领域。
