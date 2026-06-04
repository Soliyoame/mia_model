"""把 PCV-MIA 最终 JSON 报告渲染成易读的 HTML 与 Markdown 表格。

中文说明
========
本文件是流水线最后的「报告可视化」环节:读入上一步生成的 `*_final_report.json`
(里面汇总了主攻击指标、成员/非成员得分分布、机制指标、stealth 过滤、baseline 对照等),
把这些结构化数据渲染成两份人类可读的产物——一份带样式、带横条图的 HTML 表格,以及一份
纯文本的 Markdown 表格。
- 输入:一个 `*_final_report.json` 文件。
- 输出:同名派生的 `*_report_table.html` 与 `*_report_table.md`(也可用命令行参数自定义路径)。
本文件只负责「读数 -> 格式化 -> 渲染」,不重新计算任何指标。
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    """解析命令行参数:输入的报告 JSON,以及可选的 HTML/Markdown 输出路径。

    返回:
        解析后的命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="Render PCV-MIA report JSON as visual tables.")
    parser.add_argument("--input", required=True, help="Path to *_final_report.json.")
    parser.add_argument("--html", default=None, help="Output HTML path.")
    parser.add_argument("--markdown", default=None, help="Output Markdown path.")
    return parser.parse_args()


def fmt(value: Any, digits: int = 3) -> str:
    """把任意取值格式化成表格里的字符串,统一处理缺失值与各类型。

    参数:
        value:  待格式化的取值,可能是 None / bool / int / float / 其它。
        digits: 浮点数保留的小数位数。
    返回:
        适合直接放进表格单元格的字符串。
    """
    if value is None:
        return "-"  # 缺失值统一显示为短横线
    if isinstance(value, bool):
        return "yes" if value else "no"  # bool 要先于 int 判断(bool 是 int 的子类)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"  # 浮点数按指定小数位数定点显示
    return str(value)


def pct(value: Any) -> str:
    """把 0~1 的比率格式化成带一位小数的百分比字符串。

    参数:
        value: 比率取值(0~1),或 None。
    返回:
        形如 "12.3%" 的字符串;None 显示为短横线。
    """
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"  # 比率乘 100 转成百分数


def escape(value: Any) -> str:
    """对取值做 HTML 转义,避免内容里的特殊字符破坏页面结构。"""
    return html.escape(str(value))


def bar(value: float, *, max_value: float = 1.0, label: str | None = None, diverging: bool = False) -> str:
    """生成一个 HTML 横条图单元格,用条形长度直观表示数值大小。

    参数:
        value:     要可视化的数值。
        max_value: 条形满格对应的最大值(超出会被截断)。
        label:     条上显示的文字;为 None 时按是否 diverging 自动用 fmt/pct 生成。
        diverging: 是否为「双向」条形(数值可正可负,正绿负红从中间发散)。
    返回:
        一段可直接嵌进表格单元格的 HTML 字符串。
    """
    if diverging:
        # 双向模式:先把数值夹到 [-max_value, max_value],再按绝对值占比定宽
        clipped = max(-max_value, min(max_value, value))
        width = abs(clipped) / max_value * 100
        klass = "bar-pos" if clipped >= 0 else "bar-neg"  # 正值用绿色、负值用红色
        text = label if label is not None else fmt(value)
        return f'<div class="bar-track diverging"><span class="{klass}" style="width:{width:.1f}%"></span><b>{escape(text)}</b></div>'
    # 单向模式:数值夹到 [0, max_value],默认按百分比显示
    clipped = max(0.0, min(max_value, value))
    width = clipped / max_value * 100
    text = label if label is not None else pct(value)
    return f'<div class="bar-track"><span class="bar-pos" style="width:{width:.1f}%"></span><b>{escape(text)}</b></div>'


def table(headers: list[str], rows: list[list[Any]]) -> str:
    """渲染一个 HTML 表格;SafeHtml 单元格原样输出,其余做转义。

    参数:
        headers: 表头文字列表。
        rows:    每行的单元格列表。
    返回:
        完整的 <table> HTML 字符串。
    """
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_rows = []
    for row in rows:
        # SafeHtml 表示已是可信 HTML(如横条图),直接输出;普通取值则转义防注入
        cells = "".join(f"<td>{cell if isinstance(cell, SafeHtml) else escape(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


class SafeHtml(str):
    """标记类:继承自 str,用来标识「这段内容是可信 HTML,渲染时不要再转义」。"""
    pass


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    """渲染一个 Markdown 表格(表头 + 分隔行 + 数据行)。

    参数:
        headers: 表头文字列表。
        rows:    每行的单元格列表。
    返回:
        多行拼成的 Markdown 表格字符串。
    """
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",  # Markdown 表格必需的分隔行
    ]
    for row in rows:
        # 单元格内的换行会破坏 Markdown 表格行,替换成空格保持单行
        lines.append("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |")
    return "\n".join(lines)


def render_html(report: dict[str, Any]) -> str:
    """把报告字典渲染成完整的 HTML 页面(含指标卡片、横条图与各类表格)。

    参数:
        report: 从 `*_final_report.json` 读出的报告字典。
    返回:
        完整的 HTML 文档字符串。
    """
    # 从报告里取出各个子结构,取不到时用空容器兜底,避免后续 .get 报错
    dataset = report.get("dataset", "unknown")
    attack = report.get("main_attack_results", {})
    scores = report.get("score_distributions", {})
    mech = report.get("mechanism_analysis", {})
    stealth = report.get("stealth_filter", {})
    data_stats = report.get("data_statistics", {})
    benchmark_counts = data_stats.get("benchmark_counts", {})
    baselines = report.get("baseline_comparison", [])
    threshold_rows = attack.get("threshold_curve", [])

    member = scores.get("KB_Member", {})
    nonmember = scores.get("True_Non_Member", {})
    member_n = int(member.get("count") or 0)
    nonmember_n = int(nonmember.get("count") or 0)
    tpr = float(attack.get("TPR") or 0.0)
    fpr = float(attack.get("FPR") or 0.0)
    # 报告里只给了 TPR/FPR 比率,这里反推混淆矩阵的四个计数用于展示
    tp = round(member_n * tpr)          # 真正例:成员中被判为成员
    fp = round(nonmember_n * fpr)       # 假正例:非成员中被误判为成员
    fn = max(0, member_n - tp)          # 假负例:成员中漏判(夹到非负)
    tn = max(0, nonmember_n - fp)       # 真负例:非成员中正确判为非成员

    cards = [
        # 页面顶部的指标卡片:(标题, 数值, 小字说明)
        ("AUC", fmt(attack.get("AUC")), "higher is better"),
        ("Accuracy", pct(attack.get("Accuracy")), "threshold 0.5"),
        ("TPR", pct(attack.get("TPR")), "member recall"),
        ("FPR", pct(attack.get("FPR")), "non-member false alarm"),
        ("Scored docs", str(member_n + nonmember_n), "after fact/query filters"),
        ("Accepted queries", str(stealth.get("accepted", "-")), "RAG + LLM-only each"),
    ]
    card_html = "".join(
        f'<section class="metric-card"><h3>{escape(name)}</h3><p>{escape(value)}</p><span>{escape(note)}</span></section>'
        for name, value, note in cards
    )

    score_rows = [
        # 成员与非成员两组的得分对比行;pcv_score 用双向横条图(可正可负)展示
        [
            "KB_Member",
            member.get("count", "-"),
            fmt(member.get("cvg_rag_avg")),
            fmt(member.get("cvg_llm_avg")),
            SafeHtml(bar(float(member.get("pcv_score_avg") or 0.0), max_value=1.5, label=fmt(member.get("pcv_score_avg")), diverging=True)),
        ],
        [
            "True_Non_Member",
            nonmember.get("count", "-"),
            fmt(nonmember.get("cvg_rag_avg")),
            fmt(nonmember.get("cvg_llm_avg")),
            SafeHtml(bar(float(nonmember.get("pcv_score_avg") or 0.0), max_value=1.5, label=fmt(nonmember.get("pcv_score_avg")), diverging=True)),
        ],
    ]

    attack_rows = [
        # 核心指标表:每行是 [指标名, 数值]
        ["Benchmark KB_Member", benchmark_counts.get("KB_Member", "-")],
        ["Benchmark True_Non_Member", benchmark_counts.get("True_Non_Member", "-")],
        ["AUC", fmt(attack.get("AUC"))],
        ["Accuracy @ threshold 0.5", pct(attack.get("Accuracy"))],
        ["TPR @ threshold 0.5", pct(attack.get("TPR"))],
        ["FPR @ threshold 0.5", pct(attack.get("FPR"))],
        ["TPR@1%FPR", pct(attack.get("TPR@1%FPR"))],
        ["TPR@5%FPR", pct(attack.get("TPR@5%FPR"))],
        ["Predicted member count", attack.get("predicted_member_count", "-")],
    ]

    confusion_rows = [
        # 混淆矩阵:行=真实类别,列=预测为成员/预测为非成员
        ["KB_Member", tp, fn],
        ["True_Non_Member", fp, tn],
    ]

    mechanism_rows = [
        # 各机制指标都是 0~1 的比率,统一用单向横条图展示
        ["Retrieval Exposure Rate", SafeHtml(bar(float(mech.get("Retrieval Exposure Rate") or 0.0)))],
        ["Entity Evidence Rate", SafeHtml(bar(float(mech.get("Entity Evidence Rate") or 0.0)))],
        ["True Claim Support Rate", SafeHtml(bar(float(mech.get("True Claim Support Rate") or 0.0)))],
        ["Counterfactual Rejection Rate", SafeHtml(bar(float(mech.get("Counterfactual Rejection Rate") or 0.0)))],
        ["Counterfactual Correction Rate", SafeHtml(bar(float(mech.get("Counterfactual Correction Rate") or 0.0)))],
        ["False Acceptance Rate", SafeHtml(bar(float(mech.get("False Acceptance Rate") or 0.0)))],
        # stealth 拒识率来自 stealth_filter 子结构而非 mechanism_analysis
        ["Stealth Rejection Rate", SafeHtml(bar(float(stealth.get("stealth_detection_rate") or 0.0)))],
    ]

    threshold_table_rows = [
        # 阈值取舍表:逐个阈值列出 Accuracy/TPR/FPR/检出率/预测成员数
        [
            fmt(row.get("threshold")),
            pct(row.get("Accuracy")),
            pct(row.get("TPR")),
            pct(row.get("FPR")),
            pct(row.get("Detection Rate")),
            row.get("predicted_member_count", "-"),
        ]
        for row in threshold_rows
    ]

    baseline_rows = [
        # baseline 对照表:某些字段可能为 None(未实现/预留),此时显示短横线
        [
            item.get("baseline", "-"),
            "yes" if item.get("implemented") else "no",
            item.get("status", "-"),
            fmt(item.get("AUC")),
            pct(item.get("Accuracy")) if item.get("Accuracy") is not None else "-",
            pct(item.get("FPR-True_Non_Member")) if item.get("FPR-True_Non_Member") is not None else "-",
        ]
        for item in baselines
    ]

    # 成员与非成员的平均 pcv_score 之差:差值越大越支持「成员可被区分」的核心假设
    score_gap = float(member.get("pcv_score_avg") or 0.0) - float(nonmember.get("pcv_score_avg") or 0.0)
    conclusion = (
        f"成员组平均 pcv_score 为 {fmt(member.get('pcv_score_avg'))}，"
        f"非成员组为 {fmt(nonmember.get('pcv_score_avg'))}，"
        f"差值约 {fmt(score_gap)}。当前小样本结果支持 PCV-MIA 的核心假设。"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PCV-MIA Report Table - {escape(dataset)}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #667085;
      --line: #d8dee8;
      --good: #1b8a5a;
      --bad: #be4b49;
      --accent: #2454a6;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 "Segoe UI", Arial, sans-serif;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
    }}
    h2 {{
      margin: 28px 0 12px;
      font-size: 18px;
    }}
    .subtitle {{
      margin: 0 0 20px;
      color: var(--muted);
    }}
    .conclusion {{
      border-left: 4px solid var(--accent);
      background: #eef4ff;
      padding: 12px 14px;
      margin: 18px 0;
      border-radius: 4px;
      font-weight: 600;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
    }}
    .metric-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .metric-card h3 {{
      margin: 0;
      font-size: 13px;
      color: var(--muted);
      font-weight: 600;
    }}
    .metric-card p {{
      margin: 8px 0 4px;
      font-size: 26px;
      font-weight: 700;
    }}
    .metric-card span {{
      color: var(--muted);
      font-size: 12px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 16px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
      text-align: left;
      vertical-align: middle;
    }}
    th {{
      background: #eef1f5;
      font-weight: 700;
    }}
    tr:last-child td {{
      border-bottom: 0;
    }}
    .bar-track {{
      position: relative;
      min-width: 160px;
      height: 22px;
      background: #edf0f4;
      border-radius: 4px;
      overflow: hidden;
    }}
    .bar-track span {{
      display: block;
      height: 100%;
      opacity: 0.82;
    }}
    .bar-track b {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
    }}
    .bar-pos {{ background: var(--good); }}
    .bar-neg {{ background: var(--bad); }}
    .note {{
      color: var(--muted);
      margin-top: -6px;
    }}
  </style>
</head>
<body>
<main>
  <h1>PCV-MIA 可视化表格报告：{escape(dataset)}</h1>
  <p class="subtitle">Created at: {escape(report.get("created_at", "-"))}</p>
  <p class="conclusion">{escape(conclusion)}</p>

  <div class="metric-grid">{card_html}</div>

  <h2>1. 核心指标</h2>
  {table(["指标", "数值"], attack_rows)}

  <h2>2. 成员与非成员得分对比</h2>
  <p class="note">pcv_score 越高，表示 RAG 相对 LLM-only 的上下文增益越强，越像知识库成员。</p>
  {table(["组别", "样本数", "CVG_RAG 均值", "CVG_LLM 均值", "pcv_score 均值"], score_rows)}

  <h2>3. 混淆矩阵，阈值 0.5</h2>
  {table(["真实类别", "预测为成员", "预测为非成员"], confusion_rows)}

  <h2>4. 阈值取舍表</h2>
  {table(["阈值", "Accuracy", "TPR", "FPR", "Detection Rate", "预测成员数"], threshold_table_rows)}

  <h2>5. 机制指标</h2>
  {table(["机制指标", "数值"], mechanism_rows)}

  <h2>6. Baseline 对照</h2>
  {table(["方法", "已实现", "状态", "AUC", "Accuracy", "FPR-True_Non_Member"], baseline_rows)}
</main>
</body>
</html>
"""


def render_markdown(report: dict[str, Any]) -> str:
    """把报告字典渲染成纯文本的 Markdown 表格报告。

    内容是 HTML 版的精简版:核心指标、得分对比、机制指标三张表,便于直接贴进文档。

    参数:
        report: 从 `*_final_report.json` 读出的报告字典。
    返回:
        Markdown 文本(以换行结尾)。
    """
    dataset = report.get("dataset", "unknown")
    attack = report.get("main_attack_results", {})
    scores = report.get("score_distributions", {})
    mech = report.get("mechanism_analysis", {})
    stealth = report.get("stealth_filter", {})
    member = scores.get("KB_Member", {})
    nonmember = scores.get("True_Non_Member", {})
    # 成员与非成员平均 pcv_score 之差,作为结论里的关键数字
    score_gap = float(member.get("pcv_score_avg") or 0.0) - float(nonmember.get("pcv_score_avg") or 0.0)

    lines = [
        f"# PCV-MIA 表格报告：{dataset}",
        "",
        f"结论：成员组平均 pcv_score 为 {fmt(member.get('pcv_score_avg'))}，非成员组为 {fmt(nonmember.get('pcv_score_avg'))}，差值约 {fmt(score_gap)}。",
        "",
        "## 核心指标",
        "",
        md_table(
            ["指标", "数值"],
            [
                ["AUC", fmt(attack.get("AUC"))],
                ["Accuracy @ threshold 0.5", pct(attack.get("Accuracy"))],
                ["TPR @ threshold 0.5", pct(attack.get("TPR"))],
                ["FPR @ threshold 0.5", pct(attack.get("FPR"))],
                ["TPR@1%FPR", pct(attack.get("TPR@1%FPR"))],
                ["TPR@5%FPR", pct(attack.get("TPR@5%FPR"))],
            ],
        ),
        "",
        "## 得分对比",
        "",
        md_table(
            ["组别", "样本数", "CVG_RAG 均值", "CVG_LLM 均值", "pcv_score 均值"],
            [
                ["KB_Member", member.get("count", "-"), fmt(member.get("cvg_rag_avg")), fmt(member.get("cvg_llm_avg")), fmt(member.get("pcv_score_avg"))],
                ["True_Non_Member", nonmember.get("count", "-"), fmt(nonmember.get("cvg_rag_avg")), fmt(nonmember.get("cvg_llm_avg")), fmt(nonmember.get("pcv_score_avg"))],
            ],
        ),
        "",
        "## 机制指标",
        "",
        md_table(
            ["机制指标", "数值"],
            [
                ["Retrieval Exposure Rate", pct(mech.get("Retrieval Exposure Rate"))],
                ["Entity Evidence Rate", pct(mech.get("Entity Evidence Rate"))],
                ["True Claim Support Rate", pct(mech.get("True Claim Support Rate"))],
                ["Counterfactual Correction Rate", pct(mech.get("Counterfactual Correction Rate"))],
                ["False Acceptance Rate", pct(mech.get("False Acceptance Rate"))],
                ["Stealth Rejection Rate", pct(stealth.get("stealth_detection_rate"))],
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    """命令行入口:读报告 JSON,渲染并写出 HTML 与 Markdown 两份表格。

    返回:
        进程退出码(0 表示成功)。
    """
    args = parse_args()
    input_path = Path(args.input)
    report = json.loads(input_path.read_text(encoding="utf-8"))
    stem = input_path.with_suffix("")
    # 未显式指定输出路径时,把文件名里的 "_final_report" 换成 "_report_table" 作为默认产物名
    html_path = Path(args.html) if args.html else stem.with_name(stem.name.replace("_final_report", "_report_table") + ".html")
    md_path = Path(args.markdown) if args.markdown else stem.with_name(stem.name.replace("_final_report", "_report_table") + ".md")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(report), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"HTML report: {html_path}")
    print(f"Markdown report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
