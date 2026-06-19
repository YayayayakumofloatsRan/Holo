#!/usr/bin/env python3
"""Generate dark-theme SVG figures for the Holo final report.

The script intentionally uses only the Python standard library so the report
figures can be regenerated in the minimal WSL environment used by the project.
"""

from __future__ import annotations

import html
import json
import math
import statistics
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "reports" / "final" / "figures"
SUMMARY_PATH = (
    ROOT
    / ".state"
    / "kernel_v4"
    / "bench"
    / "finance"
    / "fb_strict_o096_o149_aggregate_v39_20260619"
    / "summary.json"
)


BG = "#10131A"
PANEL = "#171B24"
PANEL_2 = "#1D2330"
INK = "#F4F7FB"
MUTED = "#AAB2C0"
SUBTLE = "#788397"
GRID = "#2A3140"
AXIS = "#3A4354"

BLUE = "#A3BEFA"
BLUE_DARK = "#5477C4"
GOLD = "#FFE15B"
GOLD_DARK = "#B8A037"
ORANGE = "#F0986E"
ORANGE_DARK = "#CC6F47"
OLIVE = "#A3D576"
OLIVE_DARK = "#71B436"
PINK = "#F390CA"
PINK_DARK = "#BD569B"

FONT = '"Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", "DejaVu Sans", Arial, sans-serif'
MONO = '"SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace'


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def tag(name: str, attrs: dict[str, object] | None = None, content: str = "") -> str:
    attrs = attrs or {}
    attr_text = "".join(f' {key}="{esc(value)}"' for key, value in attrs.items() if value is not None)
    if content:
        return f"<{name}{attr_text}>{content}</{name}>"
    return f"<{name}{attr_text}/>"


def svg_root(width: int, height: int, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">\n'
        "<defs>\n"
        '  <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">\n'
        '    <feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#000000" flood-opacity="0.25"/>\n'
        "  </filter>\n"
        "</defs>\n"
        + body
        + "\n</svg>\n"
    )


def text(
    x: float,
    y: float,
    value: object,
    *,
    size: int = 20,
    fill: str = INK,
    weight: int | str = 400,
    anchor: str = "start",
    family: str = FONT,
    extra: dict[str, object] | None = None,
) -> str:
    attrs = {
        "x": f"{x:.1f}",
        "y": f"{y:.1f}",
        "fill": fill,
        "font-family": family,
        "font-size": size,
        "font-weight": weight,
        "text-anchor": anchor,
    }
    if extra:
        attrs.update(extra)
    return tag("text", attrs, esc(value))


def wrapped_text(
    x: float,
    y: float,
    value: str,
    *,
    width_chars: int,
    line_height: int,
    size: int = 18,
    fill: str = MUTED,
    weight: int | str = 400,
    anchor: str = "start",
) -> str:
    words: list[str] = []
    # Mixed Chinese/English labels are kept readable by splitting on spaces
    # first, then falling back to fixed-length chunks for long CJK strings.
    for raw in value.split():
        if len(raw) > width_chars:
            words.extend(raw[i : i + width_chars] for i in range(0, len(raw), width_chars))
        else:
            words.append(raw)
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if len(candidate) <= width_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if not lines:
        lines = [value]
    tspans = []
    for idx, line in enumerate(lines):
        dy = 0 if idx == 0 else line_height
        tspans.append(tag("tspan", {"x": f"{x:.1f}", "dy": dy}, esc(line)))
    attrs = {
        "x": f"{x:.1f}",
        "y": f"{y:.1f}",
        "fill": fill,
        "font-family": FONT,
        "font-size": size,
        "font-weight": weight,
        "text-anchor": anchor,
    }
    return tag("text", attrs, "".join(tspans))


def rect(x: float, y: float, w: float, h: float, fill: str, *, stroke: str | None = None, rx: int = 16) -> str:
    return tag(
        "rect",
        {
            "x": f"{x:.1f}",
            "y": f"{y:.1f}",
            "width": f"{w:.1f}",
            "height": f"{h:.1f}",
            "rx": rx,
            "fill": fill,
            "stroke": stroke,
            "stroke-width": 1.2 if stroke else None,
        },
    )


def line(x1: float, y1: float, x2: float, y2: float, *, stroke: str = GRID, width: float = 1.2, dash: str | None = None) -> str:
    return tag(
        "line",
        {
            "x1": f"{x1:.1f}",
            "y1": f"{y1:.1f}",
            "x2": f"{x2:.1f}",
            "y2": f"{y2:.1f}",
            "stroke": stroke,
            "stroke-width": width,
            "stroke-dasharray": dash,
        },
    )


def circle(cx: float, cy: float, r: float, fill: str, *, stroke: str | None = None, width: float = 1.2) -> str:
    return tag(
        "circle",
        {
            "cx": f"{cx:.1f}",
            "cy": f"{cy:.1f}",
            "r": f"{r:.1f}",
            "fill": fill,
            "stroke": stroke,
            "stroke-width": width if stroke else None,
        },
    )


def path(d: str, *, fill: str = "none", stroke: str = GRID, width: float = 1.2, dash: str | None = None) -> str:
    return tag(
        "path",
        {"d": d, "fill": fill, "stroke": stroke, "stroke-width": width, "stroke-dasharray": dash},
    )


def header(title: str, subtitle: str, width: int) -> str:
    return (
        text(42, 54, title, size=30, weight=700)
        + wrapped_text(42, 86, subtitle, width_chars=96, line_height=22, size=16, fill=MUTED)
        + line(42, 118, width - 42, 118, stroke=AXIS, width=1)
    )


def write_svg(name: str, width: int, height: int, body: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / name).write_text(svg_root(width, height, body), encoding="utf-8")


def load_summary() -> dict:
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


def git_commit_counts() -> dict[str, int]:
    out = subprocess.check_output(
        ["git", "log", "--all", "--date=short", "--pretty=format:%ad"],
        cwd=ROOT,
        text=True,
    )
    return dict(Counter(line.strip() for line in out.splitlines() if line.strip()))


def fig00_report_structure() -> None:
    width, height = 1280, 720
    sections = [
        ("引言", 10, "说明问题价值，并概述系统方案和核心结果"),
        ("相关工作", 10, "与已发表工作和成熟框架比较"),
        ("数据", 10, "说明数据来源和规模，并解释系统可访问的信息"),
        ("方法", 30, "论证系统设计为何适合该任务"),
        ("实验", 30, "用评测和消融结果解释系统表现"),
        ("总结", 10, "归纳成果，并说明边界和未来扩展"),
    ]
    colors = [BLUE, GOLD, ORANGE, OLIVE, PINK, BLUE_DARK]
    body = rect(0, 0, width, height, BG, rx=0)
    body += header(
        "最终报告结构与评估维度",
        "内部规范要求报告从摘要进入引言，再展开相关工作与数据说明，随后给出方法和实验，最后完成总结；正式正文应呈现为独立研究论文。",
        width,
    )
    x0, y0, bar_w, bar_h = 130, 175, 930, 44
    body += text(130, 154, "评分结构", size=18, fill=MUTED, weight=600)
    total = sum(v for _, v, _ in sections)
    x = x0
    for idx, (label, value, _) in enumerate(sections):
        w = bar_w * value / total
        body += rect(x, y0, w - 3, bar_h, colors[idx], rx=8)
        body += text(x + w / 2, y0 + 29, f"{label} {value}%", size=16, fill=BG, weight=700, anchor="middle")
        x += w
    body += line(x0, y0 + bar_h + 34, x0 + bar_w, y0 + bar_h + 34, stroke=AXIS)
    body += text(x0, y0 + bar_h + 66, "报告组织原则", size=20, weight=700)
    card_w, card_h = 360, 104
    for idx, (label, value, note) in enumerate(sections):
        row, col = divmod(idx, 3)
        cx, cy = 92 + col * 392, 300 + row * 145
        body += rect(cx, cy, card_w, card_h, PANEL, stroke=GRID, rx=18)
        body += circle(cx + 34, cy + 34, 13, colors[idx], stroke=BG, width=2)
        body += text(cx + 58, cy + 40, f"{label}：{value}%", size=20, weight=700)
        body += wrapped_text(cx + 28, cy + 70, note, width_chars=30, line_height=20, size=15, fill=MUTED)
    body += text(42, 684, "数据来源：要求.txt。图中比例为最终报告建议章节权重。", size=14, fill=SUBTLE)
    write_svg("fig00_report_structure_map.svg", width, height, body)


@dataclass
class Phase:
    label: str
    start: str
    end: str
    note: str
    color: str


def fig01_project_timeline() -> None:
    width, height = 1440, 820
    phases = [
        Phase("记忆与自迭代原型", "04-03", "04-07", "早期系统围绕长期状态和自迭代能力展开", BLUE),
        Phase("仿生状态探索", "05-06", "05-19", "这一阶段强化了状态观测和可视化表达", PINK),
        Phase("模型服务与工具循环", "05-21", "05-28", "系统开始接入 DeepSeek 并记录真实行动", GOLD),
        Phase("Kernel v3 基座", "05-28", "06-01", "v3 开始形成协议化运行时和记忆基础", ORANGE),
        Phase("检索与研究图谱", "06-01", "06-11", "检索结果开始进入可追溯的研究图谱", OLIVE),
        Phase("金融 v3 特化", "06-12", "06-16", "系统围绕 SEC/EDGAR 和财报事实完成金融化", BLUE_DARK),
        Phase("框架转向", "06-16", "06-17", "系统开始吸收 LangGraph 与 Hermes 的成熟思想", GOLD_DARK),
        Phase("Kernel v4 重写", "06-18", "06-19", "v4 以单智能体循环承接在线严格评测", ORANGE_DARK),
    ]
    counts = git_commit_counts()
    body = rect(0, 0, width, height, BG, rx=0)
    body += header(
        "Holo 从原型到 Kernel v4 的发展线",
        "本地 git 可见历史从 2026-04-03 开始；三月材料如在其他仓库或导出包中，需要另行接入。",
        width,
    )
    x0, y0, w, h = 95, 180, 1220, 410
    days = [
        ("04-03", 0),
        ("04-15", 12),
        ("05-01", 28),
        ("05-15", 42),
        ("06-01", 59),
        ("06-12", 70),
        ("06-19", 77),
    ]
    min_day, max_day = 0, 77

    def sx(day: int) -> float:
        return x0 + (day - min_day) / (max_day - min_day) * w

    body += line(x0, y0 + h + 40, x0 + w, y0 + h + 40, stroke=AXIS, width=2)
    for label, day in days:
        xx = sx(day)
        body += line(xx, y0 + h + 28, xx, y0 + h + 52, stroke=AXIS, width=1.5)
        body += text(xx, y0 + h + 82, label, size=15, fill=MUTED, anchor="middle", family=MONO)

    phase_day = {
        "04-03": 0,
        "04-07": 4,
        "05-06": 33,
        "05-19": 46,
        "05-21": 48,
        "05-28": 55,
        "06-01": 59,
        "06-11": 69,
        "06-12": 70,
        "06-16": 74,
        "06-17": 75,
        "06-18": 76,
        "06-19": 77,
    }
    for idx, phase in enumerate(phases):
        py = y0 + idx * 48
        px1, px2 = sx(phase_day[phase.start]), sx(phase_day[phase.end])
        body += line(px1, py + 18, px2, py + 18, stroke=phase.color, width=9)
        body += circle(px1, py + 18, 7, phase.color, stroke=BG, width=2)
        body += circle(px2, py + 18, 7, BG, stroke=phase.color, width=2)
        body += text(95, py + 25, phase.label, size=17, fill=INK, weight=700)
        body += text(320, py + 25, f"{phase.start} 至 {phase.end}", size=14, fill=MUTED, family=MONO)
        body += wrapped_text(455, py + 25, phase.note, width_chars=38, line_height=18, size=14, fill=MUTED)

    max_count = max(counts.values()) if counts else 1
    chart_x, chart_y, chart_w, chart_h = 840, 630, 480, 110
    body += text(chart_x, chart_y - 18, "提交密度节选", size=18, weight=700)
    selected_dates = ["2026-05-31", "2026-06-01", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19"]
    bw = chart_w / len(selected_dates) - 12
    for idx, date in enumerate(selected_dates):
        value = counts.get(date, 0)
        bh = chart_h * value / max_count
        bx = chart_x + idx * (bw + 12)
        by = chart_y + chart_h - bh
        body += rect(bx, by, bw, bh, BLUE if date < "2026-06-18" else GOLD, rx=5)
        body += text(bx + bw / 2, by - 8, value, size=13, fill=INK, anchor="middle", family=MONO)
        body += text(bx + bw / 2, chart_y + chart_h + 22, date[5:], size=12, fill=MUTED, anchor="middle", family=MONO)
    body += text(42, 784, "数据来源：git log --all --date=short；阶段命名来自本地文档和提交主题。", size=14, fill=SUBTLE)
    write_svg("fig01_project_timeline.svg", width, height, body)


def fig02_kernel_v4_architecture() -> None:
    width, height = 1440, 900
    body = rect(0, 0, width, height, BG, rx=0)
    body += header(
        "Kernel v4 的宿主程序控制型单智能体架构",
        "模型负责理解任务并选择工具，随后组织答案；宿主程序负责权限控制和实际执行，并完成过程记录与上下文管理以及题后评分。",
        width,
    )
    boxes = {
        "user": (80, 180, 230, 88, "用户问题", "题面给出公司和期间，并说明指标与约束", BLUE),
        "packet": (380, 180, 260, 88, "无答案任务包", "gold/reference 不进入上下文", GOLD),
        "loop": (735, 160, 310, 128, "单智能体循环", "行动与观察反复推进，最后完成核验和收尾", ORANGE),
        "answer": (1130, 180, 230, 88, "最终答案", "答案写明证据来源和公式，并给出数值与结论", OLIVE),
        "provider": (125, 390, 280, 95, "模型服务适配", "OpenAI-compatible / DeepSeek", BLUE_DARK),
        "executor": (455, 390, 300, 95, "流式工具执行", "工具调用生命周期实时记录", GOLD_DARK),
        "context": (805, 390, 300, 95, "上下文与证据对象", "长文档进入可检索对象", PINK),
        "observer": (1130, 390, 230, 95, "运行事件", "事件记录支持监控和复盘，也生成图表数据", ORANGE_DARK),
        "tools": (105, 610, 1170, 155, "工具注册表", "工具面覆盖 SEC/EDGAR 与文档抽取，并通过证据对象读取支撑表格处理和计算器，也支撑日期工具与数值核验以及金融工具台", OLIVE_DARK),
        "score": (455, 802, 530, 58, "题后评分", "gold/reference 只在此阶段用于 scoring；不进入模型上下文", GOLD),
    }
    for key, (x, y, w, h, title, note, color) in boxes.items():
        body += rect(x, y, w, h, PANEL, stroke=color, rx=18)
        body += rect(x, y, 9, h, color, rx=5)
        body += text(x + 24, y + 36, title, size=22, weight=700)
        body += wrapped_text(x + 24, y + 66, note, width_chars=max(16, int(w / 13)), line_height=19, size=15, fill=MUTED)
    arrows = [
        ("user", "packet"),
        ("packet", "loop"),
        ("loop", "answer"),
        ("loop", "provider"),
        ("loop", "executor"),
        ("executor", "context"),
        ("context", "loop"),
        ("executor", "observer"),
        ("executor", "tools"),
        ("tools", "context"),
        ("answer", "score"),
    ]

    def center(key: str) -> tuple[float, float]:
        x, y, w, h, *_ = boxes[key]
        return x + w / 2, y + h / 2

    for a, b in arrows:
        ax, ay = center(a)
        bx, by = center(b)
        mx, my = (ax + bx) / 2, (ay + by) / 2
        body += path(f"M {ax:.1f} {ay:.1f} Q {mx:.1f} {my:.1f} {bx:.1f} {by:.1f}", stroke=AXIS, width=1.8)
        body += circle(bx, by, 4.5, AXIS)
    body += text(42, 876, "图示依据：kernel_v4/loop.py 与 providers.py，并结合 tooling.py 和 context.py 以及 finance_runner.py。", size=14, fill=SUBTLE)
    write_svg("fig02_kernel_v4_architecture.svg", width, height, body)


def fig03_v3_v4_shift() -> None:
    width, height = 1320, 760
    body = rect(0, 0, width, height, BG, rx=0)
    body += header(
        "v3 到 v4 的核心纠偏",
        "v3 积累了金融状态表示和验证经验；v4 将主循环收敛为更通用的工具调用与证据回灌机制。",
        width,
    )
    left_x, right_x, top_y, card_w, card_h = 80, 720, 170, 520, 430
    body += rect(left_x, top_y, card_w, card_h, PANEL, stroke=ORANGE, rx=22)
    body += rect(right_x, top_y, card_w, card_h, PANEL, stroke=BLUE, rx=22)
    body += text(left_x + 32, top_y + 48, "Kernel v3", size=28, weight=800, fill=ORANGE)
    body += text(right_x + 32, top_y + 48, "Kernel v4", size=28, weight=800, fill=BLUE)
    v3 = [
        ("优势", "事实账本和信息槽提供了金融状态表达，公式轨迹支撑在线评测纪律"),
        ("瓶颈", "语义闸门过多，信息槽绑定容易阻塞行动"),
        ("风险", "失败后继续加局部补丁，规则化倾向增强"),
    ]
    v4 = [
        ("优势", "模型自主选工具，宿主程序稳定执行和记录"),
        ("修复", "证据对象生命周期与工具发现被纳入流式工具执行过程"),
        ("边界", "数值精度仍需提升，最终回答可靠性和长题成本也需要继续优化"),
    ]
    for idx, (label, note) in enumerate(v3):
        y = top_y + 105 + idx * 95
        body += rect(left_x + 32, y, 82, 34, ORANGE_DARK, rx=8)
        body += text(left_x + 73, y + 24, label, size=16, fill=INK, weight=700, anchor="middle")
        body += wrapped_text(left_x + 132, y + 25, note, width_chars=34, line_height=20, size=16, fill=MUTED)
    for idx, (label, note) in enumerate(v4):
        y = top_y + 105 + idx * 95
        body += rect(right_x + 32, y, 82, 34, BLUE_DARK, rx=8)
        body += text(right_x + 73, y + 24, label, size=16, fill=INK, weight=700, anchor="middle")
        body += wrapped_text(right_x + 132, y + 25, note, width_chars=34, line_height=20, size=16, fill=MUTED)
    body += path("M 610 390 C 650 340, 670 340, 710 390", stroke=GOLD, width=3)
    body += circle(710, 390, 6, GOLD)
    body += text(660, 324, "重写", size=20, fill=GOLD, weight=800, anchor="middle")
    body += wrapped_text(390, 650, "报告写法：v3 是必要的中期积累，v4 是对循环边界和工具生命周期的系统性收敛。", width_chars=58, line_height=22, size=17, fill=MUTED)
    body += text(42, 724, "数据来源：v3 PPT 和 KERNEL_V3_* 文档，并参考 KERNEL_V4_SINGLE_AGENT_LOOP_2026-06-18_ZH.md。", size=14, fill=SUBTLE)
    write_svg("fig03_v3_v4_architecture_shift.svg", width, height, body)


def fig04_strict54_result(summary: dict) -> None:
    width, height = 1180, 680
    passed = summary["item_count"] - summary["failed_count"]
    failed = summary["failed_count"]
    rate = passed / summary["item_count"]
    body = rect(0, 0, width, height, BG, rx=0)
    body += header(
        "FinanceBench 剩余 54 题在线严格结果",
        "冻结配置运行 offsets 96-149；gold/reference 仅用于题后评分，不进入模型上下文。",
        width,
    )
    x0, y0, w, h = 130, 250, 920, 76
    pass_w = w * passed / summary["item_count"]
    body += rect(x0, y0, pass_w, h, BLUE, rx=16)
    body += rect(x0 + pass_w, y0, w - pass_w, h, ORANGE, rx=16)
    body += text(x0 + pass_w / 2, y0 + 48, f"通过 {passed}", size=24, fill=BG, weight=800, anchor="middle")
    body += text(x0 + pass_w + (w - pass_w) / 2, y0 + 48, f"失败 {failed}", size=24, fill=BG, weight=800, anchor="middle")
    body += text(130, 210, f"通过率 {rate:.2%}", size=48, fill=GOLD, weight=800)
    body += text(500, 212, f"{passed}/{summary['item_count']}", size=42, fill=INK, weight=800, family=MONO)
    cards = [
        ("缓存命中率", f"{summary['cache_hit_rate']:.2%}", BLUE),
        ("估计总成本", f"${summary['cost_summary']['total_usd']:.4f}", GOLD),
        ("平均轮数", f"{statistics.mean(i['turn_count'] for i in summary['items']):.1f}", PINK),
        ("平均工具调用", f"{statistics.mean(i['tool_call_count'] for i in summary['items']):.1f}", OLIVE),
    ]
    for idx, (label, value, color) in enumerate(cards):
        cx = 130 + idx * 235
        cy = 410
        body += rect(cx, cy, 205, 110, PANEL, stroke=color, rx=18)
        body += text(cx + 20, cy + 38, label, size=16, fill=MUTED, weight=600)
        body += text(cx + 20, cy + 82, value, size=30, fill=color, weight=800, family=MONO)
    body += wrapped_text(130, 584, "报告口径：该结果是剩余未调试公开样本的在线严格证据，不能写作完整 clean test100。", width_chars=84, line_height=22, size=17, fill=MUTED)
    body += text(42, 646, "数据来源：fb_strict_o096_o149_aggregate_v39_20260619/summary.json。", size=14, fill=SUBTLE)
    write_svg("fig04_strict54_result.svg", width, height, body)


def fig05_failure_taxonomy(summary: dict) -> None:
    width, height = 1180, 680
    reasons = [
        ("数值容差失败", summary["failure_reasons"].get("numeric_outside_tolerance", 0), ORANGE),
        ("定性/空答案失败", summary["failure_reasons"].get("source_grounded_qualitative_failed", 0), PINK),
    ]
    body = rect(0, 0, width, height, BG, rx=0)
    body += header(
        "失败类型集中在数值精度与最终答案阶段",
        "12 个失败中，11 个属于数值容差问题，1 个属于有证据但最终答案阶段失败。",
        width,
    )
    x0, y0, max_w = 260, 230, 720
    max_v = max(v for _, v, _ in reasons) or 1
    for idx, (label, value, color) in enumerate(reasons):
        y = y0 + idx * 135
        bar_w = max_w * value / max_v
        body += text(92, y + 42, label, size=24, fill=INK, weight=700)
        body += rect(x0, y, max_w, 58, PANEL_2, stroke=GRID, rx=14)
        body += rect(x0, y, bar_w, 58, color, rx=14)
        body += text(x0 + bar_w + 20, y + 39, value, size=30, fill=color, weight=800, family=MONO)
    body += rect(92, 520, 996, 78, PANEL, stroke=GRID, rx=18)
    body += wrapped_text(
        122,
        552,
        "结论：下一阶段应优先强化财务口径和单位处理，并改进符号方向与期间识别，同时加强公式代入以及最终答案恢复；基础工具面不宜继续无差别扩张。",
        width_chars=78,
        line_height=22,
        size=17,
        fill=MUTED,
    )
    body += text(42, 646, "数据来源：summary.json 中 failure_reasons 与 failed_offsets。", size=14, fill=SUBTLE)
    write_svg("fig05_failure_taxonomy.svg", width, height, body)


def fig06_turns_tools_scatter(summary: dict) -> None:
    width, height = 1280, 760
    items = summary["items"]
    x_min, x_max = 0, max(i["turn_count"] for i in items) + 12
    y_min, y_max = 0, max(i["tool_call_count"] for i in items) + 12
    left, top, plot_w, plot_h = 115, 170, 980, 480

    def sx(v: float) -> float:
        return left + (v - x_min) / (x_max - x_min) * plot_w

    def sy(v: float) -> float:
        return top + plot_h - (v - y_min) / (y_max - y_min) * plot_h

    body = rect(0, 0, width, height, BG, rx=0)
    body += header(
        "循环轮数与工具调用次数揭示长尾成本",
        "每个点是一道 FinanceBench 剩余严格题；点大小表示总 token，颜色表示通过或失败。",
        width,
    )
    body += rect(left, top, plot_w, plot_h, PANEL, stroke=GRID, rx=18)
    for tick in [0, 25, 50, 75, 100, 125]:
        if tick <= x_max:
            xx = sx(tick)
            body += line(xx, top + 20, xx, top + plot_h - 20, stroke=GRID, width=1)
            body += text(xx, top + plot_h + 34, tick, size=13, fill=MUTED, anchor="middle", family=MONO)
    for tick in [0, 25, 50, 75, 100, 125]:
        if tick <= y_max:
            yy = sy(tick)
            body += line(left + 20, yy, left + plot_w - 20, yy, stroke=GRID, width=1)
            body += text(left - 20, yy + 5, tick, size=13, fill=MUTED, anchor="end", family=MONO)
    body += text(left + plot_w / 2, top + plot_h + 70, "循环轮数", size=16, fill=MUTED, anchor="middle")
    body += text(34, top + plot_h / 2, "工具调用次数", size=16, fill=MUTED, anchor="middle", extra={"transform": f"rotate(-90 34 {top + plot_h / 2})"})
    for item in items:
        tokens = item["usage_summary"]["total_tokens"]
        radius = 5 + 13 * math.sqrt(tokens / max(i["usage_summary"]["total_tokens"] for i in items))
        color = BLUE if item["passed"] else ORANGE
        body += circle(sx(item["turn_count"]), sy(item["tool_call_count"]), radius, color, stroke=BG, width=1.8)
    for off in [97, 121, 143]:
        match = next((i for i in items if i["offset"] == off), None)
        if not match:
            continue
        xx, yy = sx(match["turn_count"]), sy(match["tool_call_count"])
        body += line(xx + 12, yy - 12, xx + 72, yy - 56, stroke=GOLD, width=1.2)
        body += text(xx + 78, yy - 58, f"offset {off}", size=14, fill=GOLD, family=MONO)
    body += circle(1138, 210, 8, BLUE, stroke=BG)
    body += text(1160, 216, "通过", size=15, fill=MUTED)
    body += circle(1138, 245, 8, ORANGE, stroke=BG)
    body += text(1160, 251, "失败", size=15, fill=MUTED)
    body += text(42, 724, "数据来源：summary.json 中 turn_count 与 tool_call_count，并使用 usage_summary.total_tokens 表示点大小。", size=14, fill=SUBTLE)
    write_svg("fig06_turns_tools_scatter.svg", width, height, body)


def fig07_cache_cost(summary: dict) -> None:
    width, height = 1280, 760
    cost = summary["cost_summary"]
    parts = [
        ("缓存命中输入", cost["input_cache_hit_usd"], BLUE),
        ("缓存未命中输入", cost["input_cache_miss_usd"], ORANGE),
        ("输出", cost["output_usd"], GOLD),
    ]
    body = rect(0, 0, width, height, BG, rx=0)
    body += header(
        "缓存命中降低边际成本，但长题仍消耗大量 token",
        "DeepSeek v4 flash 在剩余 54 题上的聚合缓存命中率为 89.06%；成本主要来自缓存未命中输入。",
        width,
    )
    x0, y0, w, h = 120, 220, 1000, 68
    total = sum(v for _, v, _ in parts)
    x = x0
    for label, value, color in parts:
        pw = w * value / total
        body += rect(x, y0, pw, h, color, rx=14)
        body += text(x + pw / 2, y0 + 42, f"${value:.3f}", size=18, fill=BG, weight=800, anchor="middle", family=MONO)
        body += text(x + pw / 2, y0 + 96, label, size=14, fill=MUTED, anchor="middle")
        x += pw
    body += text(120, 178, f"估计总成本 ${total:.4f}", size=36, fill=GOLD, weight=800, family=MONO)
    top_items = sorted(summary["items"], key=lambda i: i["cost_estimate"]["total_usd"], reverse=True)[:8]
    chart_x, chart_y, chart_w = 140, 410, 880
    max_cost = max(i["cost_estimate"]["total_usd"] for i in top_items)
    body += text(120, 365, "单题成本最高的 8 个样本", size=22, weight=700)
    for idx, item in enumerate(top_items):
        y = chart_y + idx * 34
        val = item["cost_estimate"]["total_usd"]
        bar_w = chart_w * val / max_cost
        color = BLUE if item["passed"] else ORANGE
        body += text(88, y + 22, item["offset"], size=14, fill=MUTED, anchor="end", family=MONO)
        body += rect(chart_x, y, chart_w, 22, PANEL_2, stroke=GRID, rx=6)
        body += rect(chart_x, y, bar_w, 22, color, rx=6)
        body += text(chart_x + bar_w + 14, y + 18, f"${val:.3f}", size=14, fill=INK, family=MONO)
        body += text(chart_x + chart_w + 95, y + 18, f"{item['usage_summary']['cache_hit_rate']:.1%}", size=14, fill=MUTED, family=MONO)
    body += text(chart_x + chart_w + 72, chart_y - 10, "缓存", size=13, fill=MUTED)
    body += rect(1060, 448, 150, 78, PANEL, stroke=GRID, rx=16)
    body += text(1084, 480, "命中率", size=15, fill=MUTED)
    body += text(1084, 515, f"{summary['cache_hit_rate']:.2%}", size=28, fill=BLUE, weight=800, family=MONO)
    body += text(42, 724, "数据来源：summary.json 中 cost_summary 与 cost_estimate，并结合 usage_summary.cache_hit_rate。", size=14, fill=SUBTLE)
    write_svg("fig07_cache_cost.svg", width, height, body)


def fig08_proposal_alignment() -> None:
    width, height = 1320, 760
    rows = [
        ("完整行动闭环", "v4 单智能体循环支持工具调用，并把观察结果用于核验和最终答案。", BLUE),
        ("金融基本面研究", "以 FinanceBench 公开财报问答作为主要高压验证场景。", GOLD),
        ("数据来源整合", "用户输入和公开文件进入系统，SEC/EDGAR 结果与历史运行记录也参与推理。", ORANGE),
        ("开源项目借鉴", "系统参考 LangGraph 和 Hermes 的成熟框架思想，并重写工具调用生命周期。", OLIVE),
        ("工程指标评估", "实验记录通过率和循环轮数，并跟踪工具调用与 token 用量，同时保留缓存命中率和成本以及失败类型。", PINK),
        ("长期记忆与交互", "v3 已有基础，v4 报告中应作为继承基础和未来加强方向。", BLUE_DARK),
    ]
    body = rect(0, 0, width, height, BG, rx=0)
    body += header(
        "项目建议书承诺与最终系统对齐",
        "早期计划书提出完整行动闭环和金融基本面研究目标，并要求系统结合工具检索与分层记忆以及工程评估。",
        width,
    )
    for idx, (label, note, color) in enumerate(rows):
        y = 166 + idx * 82
        body += rect(96, y, 1128, 60, PANEL, stroke=GRID, rx=16)
        body += rect(96, y, 9, 60, color, rx=5)
        body += text(126, y + 38, label, size=20, fill=color, weight=800)
        body += wrapped_text(350, y + 37, note, width_chars=68, line_height=20, size=16, fill=MUTED)
    body += text(42, 724, "数据来源：项目建议书.docx；最终系统证据来自 README 和 docs，并结合 strict54 summary。", size=14, fill=SUBTLE)
    write_svg("fig08_proposal_alignment.svg", width, height, body)


def main() -> None:
    summary = load_summary()
    fig00_report_structure()
    fig01_project_timeline()
    fig02_kernel_v4_architecture()
    fig03_v3_v4_shift()
    fig04_strict54_result(summary)
    fig05_failure_taxonomy(summary)
    fig06_turns_tools_scatter(summary)
    fig07_cache_cost(summary)
    fig08_proposal_alignment()
    print(f"Wrote SVG figures to {OUT_DIR}")


if __name__ == "__main__":
    main()
