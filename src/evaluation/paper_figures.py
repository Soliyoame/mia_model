"""PCV-MIA 论文级图表(matplotlib)。

中文说明
========
本模块产出**可直接放进论文**的单图(每张聚焦一个论点),与 plots.py 的「自查仪表盘」分工:
    - plots.py       : 2x2 综合仪表盘,给研究者自己快速体检用。
    - paper_figures.py(本文件): 论文级单图,统一样式、色盲安全配色、导出 PDF 矢量图 + 300dpi PNG。

六张图(每张一个函数,各出 {name}.pdf + {name}.png):
    fig_roc         主攻击 ROC(AUC + 低FPR放大 inset + TPR@1%/5%FPR 工作点)。
    fig_separation  member vs non-member 的分数小提琴分布。
    fig_signals     cvg_rag / cvg_llm(阴性对照≈0.5) / cg_cvg / pcv_score 的 AUC 柱状。
    fig_baselines   PCV-MIA vs 各基线 的 AUC / TPR@1%FPR 分组柱状。
    fig_threshold   TPR / FPR / Accuracy 随阈值变化(来自 threshold_curve)。
    fig_calibration 可靠性图:按 pcv_score 分箱看「经验成员占比」,展示分数与成员可能性的校准关系。

约定:
- 图内文字一律英文(指标名本就是 cvg_rag/AUC/FPR),避免中文字体豆腐块;数据集/受害者模型
  用一行浅灰小字脚注写在图底,保证每张图**自描述**(主人明确要求记录测的是哪个数据集/模型)。
- 依赖 matplotlib;未安装则记警告返回空列表,不抛异常(与 plots.py 一致)。
- 复用 metrics.roc_auc / threshold_curve / tpr_at_fpr 与 plots._roc_points,不重算指标。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .metrics import roc_auc, threshold_curve, tpr_at_fpr
from .plots import NEGATIVE_GROUP, POSITIVE_GROUP, _roc_points
from ..utils.logger import get_logger

LOGGER = get_logger(__name__)

# 容错导入 matplotlib:没装也不让主流程崩(返回 [] + 警告)。
try:
    import matplotlib

    matplotlib.use("Agg")  # 无显示环境也能出图
    import matplotlib.pyplot as plt

    _HAS_MPL = True
except Exception:  # pragma: no cover - 仅在未安装 matplotlib 时触发
    plt = None
    _HAS_MPL = False


# ---- Okabe-Ito 色盲安全配色(论文/汇报通用,灰度打印也可区分)----
_OK = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
    "sky": "#56B4E9",
    "yellow": "#F0E442",
    "grey": "#999999",
    "black": "#222222",
}
C_MEMBER = _OK["blue"]      # 成员(正类)统一蓝
C_NONMEMBER = _OK["orange"]  # 非成员(负类)统一橙
C_ACCENT = _OK["green"]     # 主方法/主信号强调绿
C_MUTED = _OK["grey"]       # 弱化灰(chance 线、阴性对照)
C_CALIB = _OK["purple"]     # 校准分紫

# ---- 统一论文样式:用 rc_context 局部生效,不污染 plots.py 的全局设置 ----
_PAPER_RC: dict[str, Any] = {
    "figure.figsize": (3.5, 2.8),   # 单栏宽度
    "figure.dpi": 150,
    "savefig.dpi": 300,             # PNG 300dpi
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.03,
    "font.family": "sans-serif",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 10,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "legend.frameon": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.8,
    "lines.linewidth": 1.6,
    "lines.markersize": 4,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.5,
    "pdf.fonttype": 42,             # TrueType 嵌入,避免出版社字体问题
    "ps.fonttype": 42,
}


def _victim_model(report: dict[str, Any]) -> str:
    """取受害者模型名:环境变量 > 报告 config_snapshot.generation.victim_profile > 兜底。"""
    env = os.environ.get("PCV_VICTIM_MODEL", "").strip()
    if env:
        return env
    vp = (
        report.get("rag_index_statistics", {})
        .get("config_snapshot", {})
        .get("generation", {})
        .get("victim_profile")
    )
    if vp:
        return str(vp)
    return "unspecified"


def _provenance(ax: Any, dataset: str, victim: str) -> None:
    """把「数据集·受害者模型」作为右上角小字副标题——永不与 x 轴标签/图例打架,保证每张图自描述。"""
    ax.set_title(f"{dataset} · {victim}", loc="right", fontsize=6, color=_OK["grey"], pad=3)


def _save(fig: Any, ax: Any, out_dir: Path, name: str, *, dataset: str, victim: str) -> list[Path]:
    """收尾:右上角标注数据集/模型 → 建目录 → 同时导出 {name}.pdf(矢量) 与 {name}.png(300dpi) → 关闭。"""
    _provenance(ax, dataset, victim)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / f"{name}.pdf"
    png = out_dir / f"{name}.png"
    fig.savefig(pdf)
    fig.savefig(png)
    plt.close(fig)
    return [pdf, png]


def _rows_of(score_rows: list[dict[str, Any]], group: str, key: str) -> list[float]:
    """抽某组在某分数字段上的取值序列。"""
    return [float(r.get(key, 0.0)) for r in score_rows if r.get("group") == group]


def _op_point(curve: list[dict[str, Any]], target_fpr: float) -> tuple[float, float] | None:
    """在 FPR≤target 的曲线点里取 TPR 最大者,返回其真实 (FPR, TPR)——保证工作点正好落在 ROC 线上。"""
    feasible = [r for r in curve if float(r["FPR"]) <= target_fpr]
    if not feasible:
        return None
    best = max(feasible, key=lambda r: float(r["TPR"]))
    return float(best["FPR"]), float(best["TPR"])


def _headline(score_rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """从打分行现算主指标(AUC / TPR@1%FPR / TPR@5%FPR / 工作点),作为图与图注的单一事实源。"""
    curve = threshold_curve(score_rows, score_key=key)
    return {
        "AUC": roc_auc(score_rows, score_key=key, positive_group=POSITIVE_GROUP),
        "TPR@1%FPR": tpr_at_fpr(curve, 0.01),
        "TPR@5%FPR": tpr_at_fpr(curve, 0.05),
        "op1": _op_point(curve, 0.01),
        "op5": _op_point(curve, 0.05),
    }


# ============================ 六张论文图 ============================


def fig_roc(report: dict[str, Any], score_rows: list[dict[str, Any]], out_dir: Path, *, dataset: str, victim: str) -> list[Path]:
    """多信号 ROC:主分(PCV-MIA) / cvg_rag / cvg_llm(阴性对照) 三条曲线叠一张,各标 AUC,含低FPR放大 inset。

    一图讲清:主攻击强、检索信号 cvg_rag 强,而纯模型 cvg_llm 贴着对角线(阴性对照),
    与 signals 柱状图相互印证。工作点只标主分,避免拥挤。
    """
    main_key = report.get("main_score_key", "pcv_score")
    # 要叠的曲线(key, 图例名, 颜色, 线宽, 线型);阴性对照虚线弱化。
    wanted = [
        (main_key, "PCV-MIA", C_ACCENT, 2.0, "-"),
        ("cvg_rag", "cvg_rag", C_MEMBER, 1.5, "-"),
        ("cvg_llm", "cvg_llm (ctrl)", C_MUTED, 1.4, "--"),
    ]
    curves = []
    seen: set[str] = set()
    for key, label, color, lw, ls in wanted:
        if key in seen:
            continue
        seen.add(key)
        auc = roc_auc(score_rows, score_key=key, positive_group=POSITIVE_GROUP)
        if auc is None:
            continue
        fpr, tpr = _roc_points(score_rows, key)
        curves.append((key, label, color, lw, ls, float(auc), fpr, tpr))
    if not curves:
        LOGGER.warning("fig_roc: nothing to plot, skip")
        return []
    h = _headline(score_rows, main_key)  # 主分工作点从打分行现算,保证蓝点落在主曲线上
    ops = [pt for pt in (h["op1"], h["op5"]) if pt is not None]

    with plt.rc_context(_PAPER_RC):
        fig, ax = plt.subplots()
        for key, label, color, lw, ls, auc, fpr, tpr in curves:
            ax.plot(fpr, tpr, color=color, lw=lw, ls=ls, label=f"{label} (AUC={auc:.3f})",
                    zorder=5 if key == main_key else 3)
        ax.plot([0, 1], [0, 1], ls=":", color="#cccccc", lw=1.0, zorder=1)  # chance
        for pt in ops:
            ax.plot(pt[0], pt[1], "o", color=C_ACCENT, ms=5, zorder=6, mec="white", mew=0.6)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("False positive rate")
        ax.set_ylabel("True positive rate")
        # 工作点(主分在 1%/5% FPR 的检出率)用图例说明,不再用内嵌小图,避免"图中图"。
        if ops:
            ax.plot([], [], "o", color=C_ACCENT, mec="white", mew=0.6, ms=6, label="PCV-MIA @1% / 5% FPR")
        ax.legend(loc="lower right", fontsize=7.5)
        return _save(fig, ax, out_dir, "roc", dataset=dataset, victim=victim)


def fig_separation(report: dict[str, Any], score_rows: list[dict[str, Any]], out_dir: Path, *, dataset: str, victim: str) -> list[Path]:
    """member vs non-member 的分数小提琴分布(中位线来自小提琴,菱形=均值)。"""
    key = report.get("main_score_key", "pcv_score")
    spec = [(POSITIVE_GROUP, "member", C_MEMBER), (NEGATIVE_GROUP, "non-member", C_NONMEMBER)]
    data: list[list[float]] = []
    labels: list[str] = []
    colors: list[str] = []
    for g, disp, c in spec:
        ys = _rows_of(score_rows, g, key)
        if ys:
            data.append(ys)
            labels.append(f"{disp} (n={len(ys)})")
            colors.append(c)
    if not data:
        LOGGER.warning("fig_separation: no score rows, skip")
        return []

    with plt.rc_context(_PAPER_RC):
        fig, ax = plt.subplots()
        parts = ax.violinplot(data, showmeans=False, showmedians=True, showextrema=False)
        for body, c in zip(parts["bodies"], colors):
            body.set_facecolor(c)
            body.set_alpha(0.45)
            body.set_edgecolor(c)
            body.set_linewidth(1.0)
        if "cmedians" in parts:
            parts["cmedians"].set_color(_OK["black"])
            parts["cmedians"].set_linewidth(1.2)
        for i, ys in enumerate(data, start=1):
            ax.plot(i, float(np.mean(ys)), "D", color=colors[i - 1], ms=5, zorder=5, mec="white", mew=0.6)
        ax.axhline(0.0, ls=":", color=C_MUTED, lw=0.8)
        ax.set_xticks(range(1, len(labels) + 1))
        ax.set_xticklabels(labels)
        ax.set_ylabel(f"{key}")
        # 空数据代理句柄:给图例解释「菱形=均值、竖线=中位数」,不画多余点、也不引额外依赖。
        ax.plot([], [], "D", color=_OK["black"], mec="white", mew=0.5, ms=6, label="mean")
        ax.plot([], [], "-", color=_OK["black"], lw=1.2, label="median")
        ax.legend(loc="upper right", fontsize=7)
        return _save(fig, ax, out_dir, "separation", dataset=dataset, victim=victim)


def fig_signals(report: dict[str, Any], score_rows: list[dict[str, Any]], out_dir: Path, *, dataset: str, victim: str) -> list[Path]:
    """信号拆解 AUC 柱状:cvg_rag(信号) / cvg_llm(阴性对照≈0.5) / cg_cvg / pcv_score(+校准)。"""
    keys = ["cvg_rag", "cvg_llm", "cg_cvg", "pcv_score"]
    # 校准分若真在打分行里则一并展示(本项目部分跑法才有)。
    probe = score_rows[:20]
    for extra in ("pcv_score_calibrated_z", "pcv_score_calibrated"):
        if any(extra in r for r in probe):
            keys.append(extra)
            break

    labels: list[str] = []
    vals: list[float] = []
    colors: list[str] = []
    for k in keys:
        auc = roc_auc(score_rows, score_key=k, positive_group=POSITIVE_GROUP)
        if auc is None:
            continue
        labels.append("calib" if k.startswith("pcv_score_calibrated") else k)
        vals.append(float(auc))
        if k == "cvg_rag":
            colors.append(C_ACCENT)          # 主信号绿
        elif k == "cvg_llm":
            colors.append(C_MUTED)           # 阴性对照灰
        elif k.startswith("pcv_score_calibrated"):
            colors.append(C_CALIB)
        else:
            colors.append(C_MEMBER)
    if not vals:
        LOGGER.warning("fig_signals: no AUC computable, skip")
        return []

    with plt.rc_context(_PAPER_RC):
        fig, ax = plt.subplots()
        bars = ax.bar(labels, vals, color=colors, width=0.68)
        ax.axhline(0.5, ls="--", color=_OK["vermillion"], lw=1.1, label="0.5 (chance)")
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("AUC (member = KB_Member)")
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.3f}", ha="center", va="bottom", fontsize=7)
        # 给阴性对照(cvg_llm)标注一下,审稿人一眼看懂。
        if "cvg_llm" in labels:
            i = labels.index("cvg_llm")
            ax.annotate(
                "negative control",
                (i, vals[i]),
                textcoords="offset points",
                xytext=(0, 16),
                ha="center",
                fontsize=6.5,
                color=C_MUTED,
                arrowprops=dict(arrowstyle="->", color=C_MUTED, lw=0.7),
            )
        ax.legend(loc="upper right")
        ax.tick_params(axis="x", labelsize=8)
        return _save(fig, ax, out_dir, "signals", dataset=dataset, victim=victim)


def fig_baselines(baseline_rows: list[dict[str, Any]], out_dir: Path, *, dataset: str, victim: str) -> list[Path]:
    """PCV-MIA vs 基线 的 AUC 与 TPR@1%FPR 分组柱状(PCV 高亮,按 AUC 降序)。"""
    if not baseline_rows:
        LOGGER.warning("fig_baselines: no baseline rows, skip")
        return []
    rows = sorted(baseline_rows, key=lambda r: (r.get("AUC") if r.get("AUC") is not None else -1.0), reverse=True)
    names = [str(r.get("baseline", "?")) for r in rows]
    auc = [float(r["AUC"]) if r.get("AUC") is not None else 0.0 for r in rows]
    tpr = [float(r["TPR@1%FPR"]) if r.get("TPR@1%FPR") is not None else 0.0 for r in rows]

    with plt.rc_context(_PAPER_RC):
        fig, ax = plt.subplots(figsize=(max(3.5, 0.8 * len(names)), 2.9))
        x = np.arange(len(names))
        w = 0.38
        ax.bar(x - w / 2, auc, w, label="AUC", color=C_MEMBER)
        ax.bar(x + w / 2, tpr, w, label="TPR@1%FPR", color=C_NONMEMBER)
        ax.axhline(0.5, ls="--", color=C_MUTED, lw=0.9)
        ax.set_ylim(0, 1.08)
        ax.set_ylabel("score")
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=20, ha="right")
        # PCV 方法名加粗高亮。
        for lbl, nm in zip(ax.get_xticklabels(), names):
            if nm.upper().startswith("PCV"):
                lbl.set_fontweight("bold")
                lbl.set_color(C_ACCENT)
        ax.legend(loc="upper right", ncol=2)
        return _save(fig, ax, out_dir, "baselines", dataset=dataset, victim=victim)


def fig_threshold(report: dict[str, Any], out_dir: Path, *, dataset: str, victim: str) -> list[Path]:
    """TPR / FPR / Accuracy 随阈值变化(来自 main_attack_results.threshold_curve),标出工作阈值。"""
    curve = report.get("main_attack_results", {}).get("threshold_curve", []) or []
    if not curve:
        LOGGER.warning("fig_threshold: no threshold_curve, skip")
        return []
    curve = sorted(curve, key=lambda r: float(r["threshold"]))
    th = [float(r["threshold"]) for r in curve]

    with plt.rc_context(_PAPER_RC):
        fig, ax = plt.subplots()
        for metric, color in [("TPR", C_MEMBER), ("FPR", C_NONMEMBER), ("Accuracy", C_ACCENT)]:
            ys = [float(r.get(metric, 0.0)) for r in curve]
            ax.plot(th, ys, marker="", lw=1.7, color=color, label=metric)
        thr = report.get("main_attack_results", {}).get("threshold")
        if thr is not None:
            ax.axvline(float(thr), ls="--", color=C_MUTED, lw=1.0, label=f"op. threshold = {float(thr):.2f}")
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("Decision threshold")
        ax.set_ylabel("Rate")
        ax.legend(loc="center right")
        return _save(fig, ax, out_dir, "threshold", dataset=dataset, victim=victim)


def fig_calibration(report: dict[str, Any], score_rows: list[dict[str, Any]], out_dir: Path, *, dataset: str, victim: str, n_bins: int = 8) -> list[Path]:
    """可靠性图:把样本按 pcv_score 分位数分箱,每箱画「经验成员占比」,展示分数与成员可能性的单调校准关系。"""
    key = report.get("main_score_key", "pcv_score")
    rows = [r for r in score_rows if r.get("group") in (POSITIVE_GROUP, NEGATIVE_GROUP)]
    if len(rows) < 4:
        LOGGER.warning("fig_calibration: too few rows, skip")
        return []
    scores = np.array([float(r.get(key, 0.0)) for r in rows])
    y = np.array([1.0 if r.get("group") == POSITIVE_GROUP else 0.0 for r in rows])
    # 分位数分箱边界(去重,避免大量相同分数导致空箱)。
    edges = np.unique(np.quantile(scores, np.linspace(0.0, 1.0, n_bins + 1)))
    if edges.size < 2:
        LOGGER.warning("fig_calibration: degenerate score distribution, skip")
        return []

    xs: list[float] = []
    frac: list[float] = []
    counts: list[int] = []
    for b in range(edges.size - 1):
        lo, hi = edges[b], edges[b + 1]
        last = b == edges.size - 2
        mask = (scores >= lo) & (scores <= hi) if last else (scores >= lo) & (scores < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        xs.append(float(scores[mask].mean()))
        frac.append(float(y[mask].mean()))
        counts.append(n)

    if not xs:
        LOGGER.warning("fig_calibration: no populated bins, skip")
        return []

    with plt.rc_context(_PAPER_RC):
        fig, ax = plt.subplots()
        # 点大小按箱内样本数缩放(sqrt 更均衡)并封顶,避免大箱把点撑爆、被上边界截断。
        cmax = max(counts)
        sizes = [min(150.0, 22.0 + 90.0 * (c / cmax) ** 0.5) for c in counts]
        ax.plot(xs, frac, "-", color=C_CALIB, lw=1.4, zorder=1)
        ax.scatter(xs, frac, s=sizes, color=C_CALIB, alpha=0.85, edgecolors="white", linewidths=0.6, zorder=2)
        ax.axhline(0.5, ls=":", color=C_MUTED, lw=0.8)
        ax.set_ylim(-0.05, 1.08)
        ax.set_xlabel(f"{key} (bin mean)")
        ax.set_ylabel("Empirical member fraction")
        ax.set_title("Score reliability", fontsize=9)
        return _save(fig, ax, out_dir, "calibration", dataset=dataset, victim=victim)


# ============================ 编排 + 图注 ============================


def _write_captions(
    fig_dir: Path,
    report: dict[str, Any],
    score_rows: list[dict[str, Any]],
    dataset: str,
    victim: str,
    names: list[str],
) -> Path:
    """写一份 captions.md:每张图配好带本次真实数字的中英图注,每条开头标明数据集与受害者模型。

    数字与图一致:主指标从 score_rows 现算(同 fig_roc 的单一事实源),不直接取报告字段。
    """
    key = report.get("main_score_key", "pcv_score")
    h = _headline(score_rows, key) if score_rows else {}
    auc = h.get("AUC")
    t1 = h.get("TPR@1%FPR")
    t5 = h.get("TPR@5%FPR")

    def _f(v: Any) -> str:
        return f"{float(v):.3f}" if isinstance(v, (int, float)) else "n/a"

    head = f"dataset={dataset}, victim model={victim}"
    blocks: dict[str, tuple[str, str]] = {
        "roc": (
            f"Membership-inference ROC on {head}. PCV-MIA reaches AUC={_f(auc)}, with "
            f"TPR={_f(t1)} at 1% FPR and TPR={_f(t5)} at 5% FPR (marked dots). "
            f"The retrieval signal cvg_rag and the model-only negative control cvg_llm are "
            f"overlaid; cvg_llm stays near the diagonal, indicating the attack signal comes "
            f"from knowledge-base membership rather than a shortcut.",
            f"成员推理 ROC({head})。PCV-MIA 达到 AUC={_f(auc)},1% 误报率下检出率 {_f(t1)}、"
            f"5% 误报率下 {_f(t5)}(图中圆点)。图中叠加了检索信号 cvg_rag 与纯模型的"
            f"阴性对照 cvg_llm;cvg_llm 贴近对角线,表明攻击信号来自知识库成员身份而非捷径。",
        ),
        "separation": (
            f"Distribution of the PCV membership score for members vs. non-members ({head}). "
            f"Members score markedly higher, explaining the attack's separability.",
            f"成员与非成员的 PCV 成员分数分布({head})。成员分数显著更高,直观解释攻击的可分性。",
        ),
        "signals": (
            f"Signal decomposition by AUC ({head}). The retrieval-grounded signal cvg_rag is "
            f"discriminative, while the model-only cvg_llm stays near 0.5 (negative control), "
            f"showing the signal stems from knowledge-base membership rather than a shortcut.",
            f"各信号的 AUC 拆解({head})。带检索的 cvg_rag 有区分度,而纯模型的 cvg_llm 贴近 0.5"
            f"(阴性对照),说明信号来自知识库成员身份而非捷径。",
        ),
        "baselines": (
            f"Attack comparison of PCV-MIA against baselines by AUC and TPR@1%FPR ({head}).",
            f"PCV-MIA 与各基线在 AUC 和 TPR@1%FPR 上的攻击对比({head})。",
        ),
        "threshold": (
            f"TPR, FPR and Accuracy versus the decision threshold ({head}); dashed line marks the "
            f"operating threshold.",
            f"TPR / FPR / Accuracy 随判定阈值的变化({head});虚线为所选工作阈值。",
        ),
        "calibration": (
            f"Score reliability ({head}): samples binned by PCV score quantiles, plotting the "
            f"empirical member fraction per bin (marker size ∝ bin count).",
            f"分数可靠性图({head}):按 PCV 分数分位数分箱,画每箱的经验成员占比(点大小∝箱内样本数)。",
        ),
    }

    lines = ["# PCV-MIA 论文图注", "", f"- {head}", "", "> 每条可直接粘进 LaTeX `\\caption{...}`。", ""]
    for name in names:
        if name not in blocks:
            continue
        en, zh = blocks[name]
        lines += [f"## {name}", "", f"**EN:** {en}", "", f"**中:** {zh}", ""]
    fig_dir.mkdir(parents=True, exist_ok=True)
    path = fig_dir / "captions.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# 各论文图的名字 → 构造器(闭包在 render 里绑定数据),集中登记便于按需选跑。
_FIGURES = ("roc", "separation", "signals", "baselines", "threshold", "calibration")


def render_paper_figures(
    report: dict[str, Any],
    score_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]] | None,
    out_dir: str | Path,
    *,
    dataset: str,
    figures: list[str] | None = None,
) -> list[Path]:
    """产出论文级单图到 {out_dir}/figures/ 并写 captions.md,返回所有产物路径。

    参数:
        report:        final_report.json 内容(report_builder.generate_final_report 结果)。
        score_rows:    打分行(outputs/scores/{ds}_pcv_scores.jsonl)。
        baseline_rows: 基线对比行(outputs/baselines/{ds}/{ds}_baseline_comparison.jsonl);无则 baselines 图跳过。
        out_dir:       输出根目录(实际写到其下的 figures/ 子目录)。
        dataset:       数据集名(写进脚注/图注)。
        figures:       仅产出这些图名;None 表示全部 _FIGURES。
    返回:
        产出文件路径列表(pdf+png+captions);matplotlib 缺失时返回 []。
    """
    if not _HAS_MPL:
        LOGGER.warning("matplotlib not available; skip paper figures (pip install matplotlib to enable)")
        return []
    victim = _victim_model(report)
    fig_dir = Path(out_dir) / "figures"
    baseline_rows = baseline_rows or []

    builders: dict[str, Callable[[], list[Path]]] = {
        "roc": lambda: fig_roc(report, score_rows, fig_dir, dataset=dataset, victim=victim),
        "separation": lambda: fig_separation(report, score_rows, fig_dir, dataset=dataset, victim=victim),
        "signals": lambda: fig_signals(report, score_rows, fig_dir, dataset=dataset, victim=victim),
        "baselines": lambda: fig_baselines(baseline_rows, fig_dir, dataset=dataset, victim=victim),
        "threshold": lambda: fig_threshold(report, fig_dir, dataset=dataset, victim=victim),
        "calibration": lambda: fig_calibration(report, score_rows, fig_dir, dataset=dataset, victim=victim),
    }
    names = figures or list(_FIGURES)

    produced: list[Path] = []
    for name in names:
        builder = builders.get(name)
        if builder is None:
            LOGGER.warning("unknown paper figure '%s', skip", name)
            continue
        try:
            produced.extend(builder() or [])
        except Exception as exc:  # noqa: BLE001 - 单张图失败不连累其它图与主流程
            LOGGER.warning("paper figure '%s' failed: %s", name, exc)

    produced.append(_write_captions(fig_dir, report, score_rows, dataset, victim, names))
    return produced
