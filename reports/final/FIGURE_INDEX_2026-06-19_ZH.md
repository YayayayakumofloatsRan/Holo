# Holo Kernel v4 最终报告图表索引

日期：2026-06-19  
用途：管理最终论文图表，并服务 LaTeX 排版和答辩材料复用

## 写作原则

`要求.txt` 只作为内部结构约束来源。正式论文正文应采用第三人称和学术论文语气，直接陈述研究问题与方法，并给出实验结论；正文中不出现外部提交目的自述，也不把报告写成对说明文件的回应。

图表统一使用深色主题，避免默认配色。当前输出为 SVG 矢量图，便于后续转为 PDF 或 PNG 后插入 LaTeX 模板。

## 正式论文推荐图表

| 编号 | 文件 | 建议位置 | 图题建议 | 作用 |
| --- | --- | --- | --- | --- |
| Fig. 1 | `fig01_project_timeline.svg` | 引言或系统演化 | Holo 系统从记忆原型到 Kernel v4 的演化路径 | 展示系统如何从早期状态探索发展到 v3 金融特化，并最终进入 v4 重写阶段。 |
| Fig. 2 | `fig02_kernel_v4_architecture.svg` | 方法 | Holo Kernel v4 的宿主程序控制型单智能体架构 | 展示模型决策与宿主程序执行之间的边界，并说明工具注册表和证据对象如何进入题后评分过程。 |
| Fig. 3 | `fig03_v3_v4_architecture_shift.svg` | 方法或讨论 | Kernel v3 到 Kernel v4 的架构纠偏 | 解释 v3 的价值和瓶颈，并说明 v4 的设计改进。 |
| Fig. 4 | `fig04_strict54_result.svg` | 实验结果 | FinanceBench 剩余 54 题在线严格评测结果 | 报告 `42/54` 通过结果，并给出通过率与缓存命中率，同时说明成本以及平均轮数和平均工具调用。 |
| Fig. 5 | `fig05_failure_taxonomy.svg` | 失败分析 | 失败类型集中在数值精度与最终答案阶段 | 展示 11 个数值容差失败和 1 个定性/空答案失败。 |
| Fig. 6 | `fig06_turns_tools_scatter.svg` | 实验结果或效率分析 | 循环轮数与工具调用次数揭示长尾成本 | 展示复杂题的长尾成本，并标注 offset `97` 与 offset `121` 以及 offset `143`。 |
| Fig. 7 | `fig07_cache_cost.svg` | 实验结果或效率分析 | 缓存命中降低边际成本但长题仍消耗大量 token | 展示成本构成和单题成本最高样本，并说明缓存命中率。 |

## 内部规划图表

| 编号 | 文件 | 使用方式 | 说明 |
| --- | --- | --- | --- |
| Internal A | `fig00_report_structure_map.svg` | 写作规划或答辩备份，不建议放入正式论文正文 | 该图把 `要求.txt` 的章节权重转成结构图，用于内部排版检查。 |
| Internal B | `fig08_proposal_alignment.svg` | 写作规划或答辩备份，不建议放入正式论文正文 | 该图对齐早期项目计划和最终系统，用于确保叙事闭环。 |

## LaTeX 使用建议

当前图表文件位于：

```text
reports/final/figures/
```

如果最终模板直接使用 `\includegraphics`，建议先将 SVG 转为 PDF 或 PNG，并统一放入模板的 `figures/` 目录。LaTeX 正文中的图题应保持学术化，例如：

```tex
\begin{figure}[!htbp]
  \centering
  \includegraphics[width=0.92\textwidth]{figures/fig02_kernel_v4_architecture.pdf}
  \caption{Holo Kernel v4 的宿主程序控制型单智能体架构。模型负责任务理解与工具选择，并完成答案合成；宿主程序负责工具协议与权限控制，并承担实际执行和过程记录，同时完成上下文管理以及题后评分。}
  \label{fig:kernel-v4-architecture}
\end{figure}
```

## 图表质量检查

- 每张图必须有明确图题和数据来源。
- 图题不应出现外部提交语境。
- 颜色使用固定深色主题，避免默认色板。
- 实验图必须写清楚集合边界，例如 offsets `96-149` 与 `54` 道题，并说明 gold/reference 只用于题后评分。
- 规划图如果进入附录，也必须说明其作用是系统发展脉络或结构约束，不应写成外部说明文件的复述。
