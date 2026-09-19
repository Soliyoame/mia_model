"""PCV-MIA 结果可视化(matplotlib)。

中文说明
========
把评估结果画成图,便于直观查看与放进论文/汇报。本模块只画图、不算指标——
数据来自 feasibility / final_report 报告字典与打分行(score_rows)。

三个入口:
    plot_feasibility(...)  可行性体检综合图:信号拆解AUC / ROC / 分数分布 / shortcut。
    plot_final_report(...) step15 正式报告综合图:ROC / 分数分布 / 机制指标 / 阈值曲线。
    plot_run_trend(...)    历次运行的 AUC 趋势折线(配合 outputs/runs/{ds}/index.jsonl)。

说明:
- 图内文字一律用英文(指标名本就是 cvg_rag/AUC/FPR 等),避免 matplotlib 默认字体
  渲染中文出现豆腐块;中文信息(数据集、时间)用 ASCII 拼在标题里。
- 依赖 matplotlib;若未安装,plot_* 只记一条警告并返回 None,不抛异常——
  让分析/报告流程在没装画图库时也能跑完。
- ROC 曲线点直接复用 metrics.threshold_curve(换 score_key),不重算。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .metrics import roc_auc, threshold_curve
from ..utils.logger import get_logger

LOGGER = get_logger(__name__)

# 容错导入 matplotlib:没装也不让主流程崩(返回 None + 警告)。
try:
    import matplotlib

    matplotlib.use("Agg")  # 无显示环境也能出图
    import matplotlib.pyplot as plt

    _HAS_MPL = True
except Exception:  # pragma: no cover - 仅在未安装 matplotlib 时触发
    plt = None
    _HAS_MPL = False


POSITIVE_GROUP = "KB_Member"
NEGATIVE_GROUP = "True_Non_Member"

# 统一配色:正类绿、负类红、强调蓝、弱化灰、校准紫。
_C_POS = "#1b8a5a"
_C_NEG = "#be4b49"
_C_ACCENT = "#2454a6"
_C_MUTED = "#8a8f98"
_C_CALIB = "#6a4ca6"


def _warn_no_mpl(func: str) -> None:
    """matplotlib 缺失时统一记一条警告。"""
    LOGGER.warning("matplotlib not available; skip %s (pip install matplotlib to enable plots)", func)


def _roc_points(score_rows: list[dict[str, Any]], score_key: str) -> tuple[list[float], list[float]]:
    """从 threshold_curve 抽 (FPR, TPR) 序列,补端点 (0,0)/(1,1) 并按 FPR 升序。

    metrics.threshold_curve 内部正类固定 KB_Member、分数≥阈值判成员,故换 score_key
    即可得到该信号的一组 (FPR, TPR) 点;这里只做端点补全与排序,不重算。
    """
    curve = threshold_curve(score_rows, score_key=score_key)
    pts = {(round(float(r["FPR"]), 6), round(float(r["TPR"]), 6)) for r in curve}
    pts |= {(0.0, 0.0), (1.0, 1.0)}
    ordered = sorted(pts)  # 先按 FPR 再按 TPR 升序
    return [p[0] for p in ordered], [p[1] for p in ordered]


def _ax_signal_auc(ax: Any, report: dict[str, Any]) -> None:
    """子图:信号拆解 AUC 柱状(cvg_rag/cvg_llm/cg_cvg/pcv_score/calib)+ 0.5 基准线。"""
    auc = report.get("signal_decomposition", {}).get("auc", {})
    keys = ["cvg_rag", "cvg_llm", "cg_cvg", "pcv_score", "pcv_score_calibrated_z"]
    labels = ["cvg_rag", "cvg_llm", "cg_cvg", "pcv_score", "calib(z)"]
    vals = [float(auc.get(k) or 0.0) for k in keys]
    # cvg_rag 绿、cvg_llm(阴性对照)灰、calib(L1 校准分)紫、其余蓝。
    def _color(k: str) -> str:
        if k == "cvg_rag":
            return _C_POS
        if k == "cvg_llm":
            return _C_MUTED
        if k == "pcv_score_calibrated_z":
            return _C_CALIB
        return _C_ACCENT
    colors = [_color(k) for k in keys]
    bars = ax.bar(labels, vals, color=colors)
    ax.axhline(0.5, ls="--", color=_C_NEG, lw=1, label="0.5 (chance)")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("AUC (positive = KB_Member)")
    ax.set_title("(1) Signal decomposition AUC")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.3f}", ha="center", va="bottom", fontsize=8)
    ax.legend(fontsize=8, loc="upper right")
    ax.tick_params(axis="x", labelsize=8)


def _ax_roc(ax: Any, score_rows: list[dict[str, Any]], keys: list[str]) -> None:
    """子图:对每个 score_key 画一条 ROC(标注 AUC)+ 对角线。"""
    palette = {
        "cvg_rag": _C_POS,
        "cvg_llm": _C_MUTED,
        "pcv_score": _C_ACCENT,
        "cg_cvg": "#d08a1b",
        "pcv_score_calibrated": _C_CALIB,
    }
    drew = False
    for k in keys:
        auc = roc_auc(score_rows, score_key=k, positive_group=POSITIVE_GROUP)
        if auc is None:
            continue
        fpr, tpr = _roc_points(score_rows, k)
        ax.plot(fpr, tpr, marker=".", ms=4, lw=1.6, color=palette.get(k, _C_ACCENT), label=f"{k} (AUC={auc:.3f})")
        drew = True
    ax.plot([0, 1], [0, 1], ls="--", color=_C_MUTED, lw=1)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("FPR")
    ax.set_ylabel("TPR")
    ax.set_title("(2) ROC curves")
    if drew:
        ax.legend(fontsize=8, loc="lower right")


def _ax_score_dist(ax: Any, score_rows: list[dict[str, Any]], score_key: str) -> None:
    """子图:KB_Member vs True_Non_Member 在 score_key 上的分布(strip 散点 + 均值线)。"""
    groups = [POSITIVE_GROUP, NEGATIVE_GROUP]
    colors = [_C_POS, _C_NEG]
    for i, (g, c) in enumerate(zip(groups, colors)):
        ys = [float(r.get(score_key, 0.0)) for r in score_rows if r.get("group") == g]
        n = len(ys)
        if n == 0:
            continue
        # 确定性的横向抖动,避免点重叠(不用随机数,保证可复现)。
        offs = np.linspace(-0.18, 0.18, n) if n > 1 else np.array([0.0])
        ax.scatter(np.full(n, i) + offs, ys, s=26, alpha=0.65, color=c, edgecolors="none")
        m = float(np.mean(ys))
        ax.hlines(m, i - 0.28, i + 0.28, color=c, lw=2.2)
        ax.text(i, m, f"  mean={m:.2f} (n={n})", va="center", fontsize=8, color=c)
    ax.axhline(0.0, ls=":", color=_C_MUTED, lw=1)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(groups, fontsize=9)
    ax.set_ylabel(score_key)
    ax.set_title(f"(3) {score_key} distribution by group")


def _ax_shortcut(ax: Any, report: dict[str, Any], ref_auc: float | None) -> None:
    """子图:各文本统计特征的可分性 vs cvg_rag 可分性(越逼近越危险)。"""
    sc = report.get("shortcut_baseline", {})
    keys = [k for k in sc if isinstance(sc.get(k), dict)]
    seps = [float(sc[k]["separability"]) for k in keys]
    bars = ax.bar(keys, seps, color=_C_MUTED)
    for b, v in zip(bars, seps):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.2f}", ha="center", va="bottom", fontsize=8)
    if ref_auc is not None:
        ax.axhline(float(ref_auc), ls="--", color=_C_POS, lw=1.4, label=f"cvg_rag AUC={float(ref_auc):.3f}")
        ax.legend(fontsize=8, loc="upper right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("separability = max(auc, 1-auc)")
    ax.set_title("(4) Shortcut separability vs cvg_rag")
    ax.tick_params(axis="x", rotation=30, labelsize=8)


def _ax_mechanism(ax: Any, report: dict[str, Any]) -> None:
    """子图:机制指标横向柱状(来自 final_report 的 mechanism_analysis)。"""
    mech = report.get("mechanism_analysis", {}) or {}
    keys = [
        "Retrieval Exposure Rate",
        "Entity Evidence Rate",
        "True Claim Support Rate",
        "Counterfactual Correction Rate",
        "False Acceptance Rate",
    ]
    vals = [float(mech.get(k) or 0.0) for k in keys]
    short = [k.replace(" Rate", "").replace("Counterfactual", "CF") for k in keys]
    ax.barh(short, vals, color=_C_ACCENT)
    for y, v in enumerate(vals):
        ax.text(v + 0.01, y, f"{v:.2f}", va="center", fontsize=8)
    ax.set_xlim(0, 1.05)
    ax.invert_yaxis()
    title = "(3) Mechanism rates" if mech else "(3) Mechanism rates (no step13 data)"
    ax.set_title(title)


def _ax_threshold(ax: Any, report: dict[str, Any]) -> None:
    """子图:Accuracy/TPR/FPR 随阈值变化(来自 final_report 的 threshold_curve)。"""
    curve = report.get("main_attack_results", {}).get("threshold_curve", []) or []
    if not curve:
        ax.set_title("(4) Metrics vs threshold (no data)")
        return
    order = sorted(range(len(curve)), key=lambda i: float(curve[i]["threshold"]))
    th = [float(curve[i]["threshold"]) for i in order]
    for metric, color in [("Accuracy", _C_ACCENT), ("TPR", _C_POS), ("FPR", _C_NEG)]:
        ys = [float(curve[i].get(metric, 0.0)) for i in order]
        ax.plot(th, ys, marker=".", lw=1.5, color=color, label=metric)
    ax.set_xlabel("threshold")
    ax.set_ylim(0, 1.02)
    ax.set_title("(4) Metrics vs threshold")
    ax.legend(fontsize=8, loc="best")


def _finalize(fig: Any, output_path: str | Path, suptitle: str) -> Path:
    """统一收尾:加总标题、紧凑布局、建目录、存盘、关闭。"""
    fig.suptitle(suptitle, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def plot_feasibility(
    report: dict[str, Any],
    score_rows: list[dict[str, Any]],
    output_path: str | Path,
    *,
    dataset: str,
    run_id: str,
    generated_at: str,
) -> Path | None:
    """可行性体检综合图(2x2):信号拆解AUC / ROC / 分数分布 / shortcut。

    参数:
        report:       feasibility.analyze_feasibility 的返回字典。
        score_rows:   打分行(outputs/scores/{ds}_pcv_scores.jsonl)。
        output_path:  PNG 输出路径。
        dataset/run_id/generated_at: 标题信息。
    返回:
        PNG 路径;matplotlib 未安装时返回 None。
    """
    if not _HAS_MPL:
        _warn_no_mpl("plot_feasibility")
        return None
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    _ax_signal_auc(axes[0][0], report)
    _ax_roc(axes[0][1], score_rows, ["cvg_rag", "cg_cvg", "pcv_score_calibrated"])
    _ax_score_dist(axes[1][0], score_rows, "cvg_rag")
    ref = report.get("signal_decomposition", {}).get("auc", {}).get("cvg_rag")
    _ax_shortcut(axes[1][1], report, ref)
    verdict = report.get("verdict", {}).get("direction", "")
    suptitle = f"PCV-MIA feasibility | {dataset} | run {run_id} | {generated_at} | verdict: {verdict}"
    return _finalize(fig, output_path, suptitle)


def plot_final_report(
    report: dict[str, Any],
    score_rows: list[dict[str, Any]],
    output_path: str | Path,
    *,
    dataset: str,
    run_id: str,
    generated_at: str,
) -> Path | None:
    """step15 正式报告综合图(2x2):ROC / 分数分布 / 机制指标 / 阈值曲线。

    参数:
        report:      final_report.json 的内容(report_builder.generate_final_report 结果)。
        score_rows:  打分行(outputs/scores/{ds}_pcv_scores.jsonl)。
        output_path: PNG 输出路径。
    返回:
        PNG 路径;matplotlib 未安装时返回 None。
    """
    if not _HAS_MPL:
        _warn_no_mpl("plot_final_report")
        return None
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    score_key = report.get("main_score_key", "pcv_score")
    _ax_roc(axes[0][0], score_rows, [score_key, "cvg_rag"])
    _ax_score_dist(axes[0][1], score_rows, score_key)
    _ax_mechanism(axes[1][0], report)
    _ax_threshold(axes[1][1], report)
    auc = report.get("main_attack_results", {}).get("AUC")
    auc_text = f"AUC={float(auc):.3f}" if auc is not None else "AUC=n/a"
    suptitle = f"PCV-MIA report | {dataset} | run {run_id} | {generated_at} | {auc_text}"
    return _finalize(fig, output_path, suptitle)


def plot_run_trend(
    index_rows: list[dict[str, Any]],
    output_path: str | Path,
    *,
    dataset: str,
) -> Path | None:
    """历次运行 AUC 趋势折线(cvg_rag / pcv_score / cvg_llm,缺失自动跳过)。

    参数:
        index_rows:  outputs/runs/{ds}/index.jsonl 读出的行(已按需过滤 kind)。
        output_path: PNG 输出路径。
    返回:
        PNG 路径;matplotlib 未安装或无数据时返回 None。
    """
    if not _HAS_MPL:
        _warn_no_mpl("plot_run_trend")
        return None
    if not index_rows:
        LOGGER.warning("plot_run_trend: empty index, skip")
        return None
    x = list(range(len(index_rows)))
    labels = [str(r.get("run_id", i)) for i, r in enumerate(index_rows)]
    series = [
        ("auc_cvg_rag", _C_POS, "cvg_rag"),
        ("auc_pcv", _C_ACCENT, "pcv_score"),
        ("auc_cvg_llm", _C_MUTED, "cvg_llm"),
    ]
    fig, ax = plt.subplots(figsize=(max(7.0, len(x) * 0.7), 5.0))
    drew = False
    for key, color, name in series:
        xs = [i for i in x if index_rows[i].get(key) is not None]
        ys = [float(index_rows[i][key]) for i in xs]
        if ys:
            ax.plot(xs, ys, marker="o", lw=1.6, color=color, label=name)
            drew = True
    ax.axhline(0.5, ls="--", color=_C_MUTED, lw=1, label="0.5 (chance)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("AUC")
    ax.set_title(f"AUC trend across runs | {dataset}")
    if drew:
        ax.legend(fontsize=8, loc="best")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out
