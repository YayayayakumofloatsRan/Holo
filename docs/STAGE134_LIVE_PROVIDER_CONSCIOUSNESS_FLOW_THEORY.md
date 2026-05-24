# Stage134 Live Provider Consciousness Flow Theory

Date: 2026-05-24

## 核心转向

Stage133 的价值只在于把 V2 的核心问题拆成可观测维度。它不能证明 Holo 真的形成了连续思考，因为它没有接触真实 provider，没有真实模型返回，没有真实工具 proposal，没有真实延迟、缓存、费用、语言偏移和失败模式。

Stage134 的理论重心转到真实 provider 交互。Holo 的意识流研究必须把 LLM 当作在线语言处理模块来观察：每一次发包都是一次状态变换实验，每一次返回都是系统状态的新观测，每一次工具调用都是外部世界对内部状态的反作用。

## 中心命题

Holo 的宏观心智表现来自一个在线闭环：

```text
外部输入 -> 第一反应包 -> provider 返回 -> 状态增量
        -> 继续门控 -> 工具/记忆/视觉动作
        -> 新状态 -> 下一包 -> 外显表达或停止
```

这个闭环的关键点在于：provider 返回不能只被当作“答案”。它要被当作一个语义事件，进入本地主脑的状态更新。Holo 真正需要研究的对象，是连续语义事件如何被组织为一个稳定主体的过程。

## Provider 的理论位置

在 Holo 理论中，provider 是语言处理芯片。它擅长在有限上下文中完成语义压缩、推理、表达、工具调用 proposal 和不确定性表达。Holo 主脑负责把有限上下文组织成合适的输入包，并把返回压缩成状态增量。

因此，Holo 的理论问题可以写成：

```text
P_i = BuildPacket(S_i, Goal_i, Memory_i, ToolState_i, VisualState_i, Budget_i)
R_i = Provider(P_i)
O_i = Observe(R_i, ToolCalls_i, VisibleText_i, Uncertainty_i)
S_{i+1} = Update(S_i, O_i)
G_{i+1} = ContinueGate(S_{i+1})
```

其中：

- `S_i` 是当前认知状态；
- `P_i` 是第 `i` 个 provider 包；
- `R_i` 是 provider 返回；
- `O_i` 是经过本地主脑解析后的可观测语义事件；
- `S_{i+1}` 是写回后的新状态；
- `G_{i+1}` 决定继续发包、调用工具、外显回复、后台沉积或停止。

这个公式比“多轮对话”更严格。多轮对话只记录文本轮次；Holo 要记录状态变换。

## 第一反应包

人类的第一反应通常来自当前语境、短期工作记忆、长期记忆、情绪/驱动状态和身体感知的快速合成。Holo 的第一反应包应承担同样功能。

第一包应包含：

- 当前用户输入；
- 最近对话窗口；
- 短期工作记忆约束；
- 当前任务和开放回路；
- 少量高置信长期记忆；
- 工具与视觉能力摘要；
- 风险、成本和延迟约束；
- 明确要求 provider 输出结构化判断。

第一包的返回应至少包含：

- 用户意图；
- 场景判断；
- 是否需要外显浅回复；
- 是否需要继续深层处理；
- 是否需要工具；
- 是否需要记忆检索；
- 是否需要视觉观察；
- 当前回答可能出现的风险。

第一包可以产生 A'，也可以只产生内部状态增量。A' 的价值是人类式即时反应：让系统显得在线、敏捷、有主体连续性。A' 结束后，Holo 的思考仍可继续。

## 状态增量

provider 返回后，Holo 必须写入状态增量。状态增量的理论结构如下：

```text
Delta S_i = {
  intent_delta,
  memory_delta,
  affect_delta,
  tool_delta,
  visual_delta,
  risk_delta,
  expression_delta,
  uncertainty_delta,
  closure_delta
}
```

每一项都不要求保存 provider 原文。真正需要保存的是可复用的状态变化。

例如：

- 用户刚要求减少 emoji，应写入短期表达约束；
- 用户问“你去看看”，应触发外部检索或工具 proposal；
- 用户指出记忆错误，应提高 memory_conflict 和 correction_pressure；
- provider 给出不确定回答，应提高 uncertainty_delta；
- 工具返回文件列表，应写入 tool_observation_summary；
- 摄像头算法返回场景变化，应写入 visual_delta。

## 继续门控

继续门控是 Holo 区别于普通聊天壳的关键。它决定系统是否继续思考、是否继续说话、是否调用工具、是否进入后台沉积。

继续门控应综合以下因素：

```text
Continue = f(
  unresolved_intent,
  uncertainty_delta,
  semantic_novelty,
  tool_need,
  memory_conflict,
  visual_need,
  user_wait_cost,
  risk,
  budget,
  expression_value
)
```

继续门控的输出包括：

- `stop`: 当前表达已经足够；
- `speak_now`: 外显 A' 或 A''；
- `deep_packet`: 调用更深模型；
- `tool_packet`: 让 provider 选择工具或解释工具需求；
- `execute_tool`: 本地主脑执行已批准工具；
- `memory_recall`: 读取记忆；
- `visual_observe`: 调用视觉算法；
- `background_consolidate`: 不打扰用户，后台沉积状态。

这使 Holo 的连续性来自状态，而非固定轮次。A''、A''' 只能在它们带来新语义功能时出现。

## 工具与行动

工具调用是 Holo 从语言系统走向 agent 的分水岭。provider 可以提出工具调用，Holo 主脑执行权限判断和实际动作。工具返回结果再次进入状态增量，并影响下一包。

工具链理论结构：

```text
Provider proposes tool_call
-> Holo validates permission
-> Holo executes local tool
-> tool_observation enters state
-> next packet receives tool_observation_summary
-> provider uses observation to answer or continue
```

这条链路能降低幻觉，因为 provider 不再只依赖内部参数猜测世界。它获得了外部观测。

修改性工具必须保留许可门控。读目录、读日志、记忆召回、视觉摘要属于低风险观察；写文件、发消息、改记忆、执行命令属于高风险动作。

## 记忆

Holo 的记忆要服务发包，而非堆积文本。记忆系统要回答三个问题：

1. 现在这句话需要哪些短期约束？
2. 哪些长期事实会改变理解？
3. 当前返回会沉积成什么新记忆？

短期记忆用于保持刚刚发生的约束，例如“不要用 emoji”“别一直重复”“先不要动 WeChat”。长期记忆用于稳定身份、关系、偏好和历史任务。候选记忆用于记录还没有确认但可能重要的状态变化。

记忆进入 provider 包时应以摘要、证据、置信度和冲突提示出现。provider 返回后，Holo 应记录它使用了哪些记忆，以及哪些记忆被纠正或降权。

## 视觉与世界状态

DeepSeek 在当前 Holo 链路中主要作为文本/推理模块。实时图像信息应由外置视觉算法先转化为 scene-state delta。

视觉链路理论结构：

```text
camera/frame/window
-> local visual algorithm
-> scene objects / event delta / uncertainty
-> Holo visual state
-> provider packet
```

这让视觉成为状态输入，而非把原始画面粗暴塞进 prompt。视觉输入的价值在于给 Holo 增加“世界接口”：桌面状态、对象变化、用户环境、实验过程、任务进展都可以被转为可推理的状态。

## 可视化

Stage134 的可视化对象应从离线 probe 变成在线事件流。

每次真实交互都应产生一条 redacted trace：

```text
turn_id
packet_id
packet_role
model_tier
prompt_tokens
cache_hit_tokens
cache_miss_tokens
provider_latency_ms
provider_return_type
intent_delta
memory_delta
tool_delta
visual_delta
continue_decision
visible_segment_role
stop_reason
```

仿生 CT 的目标是显示状态变迁，而非展示隐藏思维文本。研究者需要看到：

- 第一包是否拿到了足够上下文；
- provider 是否判断需要继续；
- 第二包是否真的利用了第一包返回；
- 工具结果是否改变了下一包；
- 记忆是否被正确召回和写回；
- 可见回复是否存在重复；
- 系统停止的原因是否合理。

## 评价指标

Stage134 的理论评价重点转向真实在线数据。

核心指标：

- `first_packet_context_sufficiency`: 第一包是否包含理解意图所需的关键状态；
- `continuation_precision`: 继续发包是否真的带来新语义功能；
- `duplicate_segment_rate`: A'' 与 A' 的同义复述率；
- `state_delta_utilization`: 后一包是否使用前一包状态增量；
- `tool_grounding_success`: 工具结果是否进入后续回答；
- `short_term_constraint_retention`: 用户刚提出的约束是否被保持；
- `memory_conflict_repair`: 记忆冲突后是否能修复；
- `cache_efficiency`: 稳定前缀是否带来缓存命中；
- `latency_cost_quality`: 延迟、费用、回答质量的折中；
- `closure_quality`: 停止时任务是否真的闭合。

这些指标直接对应 V2 的七个问题。

## 研究假设

Stage134 提出以下可检验假设：

1. 第一包上下文越充分，后续偏题和语言风格漂移越少。
2. 将 provider 返回写成状态增量后，A'' 的同质化会下降。
3. 工具 observation 进入下一包后，幻觉率会下降。
4. 短期表达约束进入工作记忆后，刚刚纠正过的语言习惯会保持更久。
5. 视觉 scene-state delta 进入状态场后，Holo 对现实任务的 grounded response 会提升。
6. 继续门控以 semantic_novelty 和 unresolved_intent 为核心时，过度吐话会减少。
7. 缓存稳定前缀与动态尾部拆分后，成本会下降，长上下文质量会提高。

## 下一步工程含义

下一步不应继续扩展离线仿真。应实现 Stage134 的在线 trace：

1. 在真实 CLI/provider 调用中记录每个 packet 的 metadata。
2. 记录 provider 返回后的状态增量，而非只记录可见回复。
3. 将工具 proposal、工具执行、工具 observation 串成同一 turn trace。
4. 将短期记忆约束和长期记忆证据写入 trace。
5. 将 A'、A''、A''' 标注为不同 visible_segment_role。
6. 在 CT 中按真实时间播放 packet/state/tool/memory 的变化。
7. 用真实对话 probe 测试重复率、短期记忆保持、工具 grounding 和 closure quality。

Stage134 的最终目标是让每一次真实 Holo 对话都能回答一个问题：

**这一轮回复是怎样从输入、记忆、provider 返回、工具观察和状态更新中形成的？**

这才是 Holo 从“聊天壳”走向“仿生 agent 主体”的理论基础。
