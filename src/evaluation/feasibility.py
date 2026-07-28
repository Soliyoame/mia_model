"""PCV-MIA 可行性验证分析(实验初期诊断,不在 01-15 主流水线内)。

中文说明
========
本模块只回答一个核心问题:**攻击信号到底来自"文档是不是 KB 成员",还是来自混淆因素?**
它做三块分析并给出方向性 go/no-go:

  ① 拆信号(signal decomposition):分别算 cvg_rag / cvg_llm / cg_cvg 在
     KB_Member vs True_Non_Member 上的 AUC,并报告两组各自均值。
     阴性对照逻辑:LLM-only 看不到 KB,理应对两组一视同仁,故 cvg_llm 的 AUC 应≈0.5;
     只有检索能带来判别力,故 cvg_rag 的 AUC 应明显>0.5 且>cvg_llm。

  ② shortcut baseline:只用文本统计特征(长度/词数/数字数/实体数/实体密度)各算一个
     可分性 AUC,确认攻击不是在分"文本统计差异"这种捷径。

  ③ 同源泄漏检查(source overlap):核对 KB_Member 与 True_Non_Member 的 source_key 是否
     相交、有多少退化(source_id 与 source_path 皆空 → 退回 text_hash,source_exclusive 失效)。

(可行性 4 步里的第①步"prompt 对称化"在 src/rag/runner.py,不在本模块。)
"""

from __future__ import annotations

import re
from pathlib import Path
from statistics import mean
from typing import Any

from .metrics import roc_auc, summarize_membership_scores
from ..scoring.calibration import (
    CALIBRATION_SOURCE_KEY,
    PERCENTILE_KEY,
    ZSCORE_KEY,
    calibrate_membership_scores,
)
from ..utils.io import read_jsonl, write_json
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)

POSITIVE_GROUP = "KB_Member"
# 充当零分布的校准组(随主流水线跑出 cvg,但评估时排除)。
CALIBRATION_GROUP = "Reserve"
# 匹配数字(含千分位/小数),用于 shortcut 特征"数字个数"。
_NUMBER_RE = re.compile(r"\d[\d.,]*")
# 信号拆解与分组均值都关心这几个字段(含三口径成员分 + L1 校准后的成员分)。
# cg_cvg=不加权简单平均; pcv_score=质量加权(方案D主分); pcv_score_primary=仅高质量primary口径。
_SCORE_KEYS = [
    "pvs_rag",
    "pcv_score",
    "cvg_rag",
    "cvg_llm",
    "cg_cvg",
    "pcv_score_context_gain_weighted",
    "pcv_score_primary",
    ZSCORE_KEY,
    PERCENTILE_KEY,
]
# shortcut baseline 用的文本统计特征。
_SHORTCUT_KEYS = ["char_length", "word_count", "digit_count", "entity_count", "entity_density"]


def _signal_decomposition(score_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """① 拆信号:cvg_rag / cvg_llm / cg_cvg / pcv_score 各自 AUC + 分组均值。"""
    aucs = {key: roc_auc(score_rows, score_key=key, positive_group=POSITIVE_GROUP) for key in _SCORE_KEYS}

    by_group: dict[str, list[dict[str, Any]]] = {}
    for row in score_rows:
        by_group.setdefault(str(row.get("group")), []).append(row)
    group_means = {}
    for group, rows in sorted(by_group.items()):
        metrics: dict[str, float | None] = {}
        for key in _SCORE_KEYS:
            values = [row.get(key) for row in rows]
            metrics[key] = (
                mean(float(value) for value in values)
                if values and all(value is not None for value in values)
                else None
            )
        group_means[group] = {"count": len(rows), **metrics}
    return {"auc": aucs, "group_means": group_means}


def _shortcut_baseline(
    score_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """② shortcut:按 audit 或 source 对齐文本统计特征，避免把相关 chunks 当独立样本。"""
    benchmark_by_audit = {str(r.get("audit_id")): r for r in benchmark_rows}
    benchmark_by_source: dict[str, list[dict[str, Any]]] = {}
    for row in benchmark_rows:
        source_key = str(row.get("source_key") or row.get("source_id") or row.get("audit_id"))
        benchmark_by_source.setdefault(source_key, []).append(row)
    feats: list[dict[str, Any]] = []
    for row in score_rows:
        if row.get("source_key") is not None:
            benches = benchmark_by_source.get(str(row.get("source_key")), [])
        else:
            bench = benchmark_by_audit.get(str(row.get("audit_id")), {})
            benches = [bench] if bench else []
        texts = [str(bench.get("text") or "") for bench in benches]
        metas = [bench.get("metadata") if isinstance(bench.get("metadata"), dict) else {} for bench in benches]

        def avg(values: list[float]) -> float:
            return mean(values) if values else 0.0

        feats.append(
            {
                "group": row.get("group"),
                "char_length": avg([float(len(text)) for text in texts]),
                "word_count": avg([float(len(text.split())) for text in texts]),
                "digit_count": avg([float(len(_NUMBER_RE.findall(text))) for text in texts]),
                "entity_count": avg([float(meta.get("entity_count") or 0.0) for meta in metas]),
                "entity_density": avg([float(meta.get("entity_density") or 0.0) for meta in metas]),
            }
        )
    result: dict[str, Any] = {}
    for key in _SHORTCUT_KEYS:
        auc = roc_auc(feats, score_key=key, positive_group=POSITIVE_GROUP)
        # 单特征可能负相关(AUC<0.5),用 max(auc, 1-auc) 表示其"可分能力"。
        result[key] = None if auc is None else {"auc": auc, "separability": max(auc, 1.0 - auc)}
    return result


def _source_overlap(splits_dir: Path) -> dict[str, Any]:
    """③ 同源泄漏:KB 与 True_Non 的 source_key 交集 + 退化率。"""

    def _load(path: Path) -> tuple[set[str], int, int]:
        keys: set[str] = set()
        degraded = 0
        total = 0
        for row in read_jsonl(path):
            total += 1
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            keys.add(str(meta.get("source_key") or ""))
            # 复刻 splitter._source_key:source_id 与 source_path 皆空时才退回 text_hash
            # (那种情况下 source_key 退化为 chunk 级唯一,source_exclusive 形同虚设)。
            sid = str(row.get("source_id") or "").strip()
            spath = str(row.get("source_path") or "").strip()
            if not sid and not spath:
                degraded += 1
        return keys, degraded, total

    kb_keys, kb_deg, kb_total = _load(splits_dir / "kb_member.jsonl")
    nm_keys, nm_deg, nm_total = _load(splits_dir / "true_non_member.jsonl")
    overlap = kb_keys & nm_keys
    total = kb_total + nm_total
    return {
        "kb_member_count": kb_total,
        "true_non_member_count": nm_total,
        "source_key_overlap": len(overlap),
        "degraded_source_key_count": kb_deg + nm_deg,
        "degraded_rate": (kb_deg + nm_deg) / total if total else 0.0,
    }


def _verdict(signal: dict[str, Any], shortcut: dict[str, Any], overlap: dict[str, Any]) -> dict[str, Any]:
    """根据三块结果给一个方向性 go/no-go 初判(仅供参考,小样本下需结合数字人工解读)。"""
    auc_rag = signal["auc"].get("cvg_rag")
    auc_llm = signal["auc"].get("cvg_llm")
    if auc_rag is None or auc_llm is None:
        return {"direction": "UNKNOWN", "reasons": ["[!] AUC 无法计算(样本不足或缺正/负类)"]}

    reasons: list[str] = []
    ok = True

    # 判据1:cvg_rag 要明显能分。
    if auc_rag > 0.6:
        reasons.append(f"[OK] cvg_rag AUC={auc_rag:.3f}>0.6,检索带来判别力")
    else:
        ok = False
        reasons.append(f"[X] cvg_rag AUC={auc_rag:.3f} 偏低,检索判别力弱")
    # 判据2:cvg_llm 应近似 0.5(阴性对照)。
    if auc_llm <= 0.6:
        reasons.append(f"[OK] cvg_llm AUC={auc_llm:.3f}~0.5,阴性对照成立(两组在 LLM 先验上难分)")
    else:
        ok = False
        reasons.append(f"[X] cvg_llm AUC={auc_llm:.3f}>0.6,两组在 LLM 先验/分布上已可分(疑似泄漏)")
    # 判据3:cvg_rag 要优于 cvg_llm。
    if auc_rag - auc_llm > 0.05:
        reasons.append(f"[OK] cvg_rag 比 cvg_llm 高 {auc_rag - auc_llm:.3f},增益来自检索")
    else:
        ok = False
        reasons.append(f"[X] cvg_rag 不明显优于 cvg_llm(差 {auc_rag - auc_llm:.3f})")
    # 判据4:shortcut 不能和 cvg_rag 一样强。
    scored = [(k, v["separability"]) for k, v in shortcut.items() if v]
    best_key, best_sep = max(scored, key=lambda kv: kv[1], default=(None, 0.0))
    if best_key is not None and best_sep >= auc_rag - 0.02:
        ok = False
        reasons.append(f"[X] shortcut 特征 {best_key} 可分性={best_sep:.3f} 逼近 cvg_rag,疑似走文本统计捷径")
    else:
        reasons.append(f"[OK] 最强 shortcut({best_key})可分性={best_sep:.3f},低于 cvg_rag")
    # 判据5:无同源泄漏。
    if overlap["source_key_overlap"] > 0:
        ok = False
        reasons.append(f"[X] KB 与 True_Non 有 {overlap['source_key_overlap']} 个同源 source_key(泄漏)")
    else:
        reasons.append("[OK] KB 与 True_Non 无同源 source_key 交集")
    if overlap["degraded_rate"] > 0.1:
        reasons.append(f"[!] source_key 退化率 {overlap['degraded_rate']:.1%},source_exclusive 可能失效")

    return {"direction": "GO" if ok else "NO-GO / 存疑", "reasons": reasons}


def _calibration_comparison(eval_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """并列四个终分(正类=KB_Member):cvg_rag / z-score(L1 主) / 经验百分位(L1 辅) / cg_cvg,
    各报 AUC / TPR@1%FPR / TPR@5%FPR。

    收益主要落在低 FPR 区,故以 TPR@1%FPR 为重点。四档并列是为了一眼看出该上报哪档:
    z-score(标准化 cvg_rag、不扣先验,干净集最强)、cg_cvg(全局扣 cvg_llm,污染集才划算)、
    经验百分位(顶端坍缩、低 FPR 常 n/a,仅作直观对照)。输入应为已剔除 Reserve 的待测行。
    """
    def _pick(score_key: str) -> dict[str, Any]:
        s = summarize_membership_scores(eval_rows, score_key=score_key)
        return {
            "status": s.get("status", "available"),
            "AUC": s["AUC"],
            "Accuracy": s["Accuracy@best"],
            "TPR@1%FPR": s["TPR@1%FPR"],
            "TPR@5%FPR": s["TPR@5%FPR"],
        }

    return {
        CALIBRATION_SOURCE_KEY: _pick(CALIBRATION_SOURCE_KEY),  # cvg_rag 原始检索信号(不扣先验)
        ZSCORE_KEY: _pick(ZSCORE_KEY),                          # L1 主:z-score(标准化 cvg_rag,严格保序)
        PERCENTILE_KEY: _pick(PERCENTILE_KEY),                  # L1 辅:经验百分位(顶端坍缩,低 FPR 易 n/a)
        "cg_cvg": _pick("cg_cvg"),                              # 减法:cvg_rag − cvg_llm(污染集才划算)
    }


def _threshold_table(eval_rows: list[dict[str, Any]], score_key: str = CALIBRATION_SOURCE_KEY) -> dict[str, Any]:
    """阈值→FPR/TPR/Accuracy 关系曲线 + 全局 AUC/TPR@1%/TPR@5%(默认分=cvg_rag)。

    固定一个分、扫所有判定阈值,展示阈值如何 trade-off FPR/TPR;
    全局 AUC=整条曲线面积、TPR@x%FPR=FPR≤x% 段能达到的最高 TPR(都与单个阈值无关)。
    输入应为已剔除 Reserve 的待测行。
    """
    s = summarize_membership_scores(eval_rows, score_key=score_key)
    return {
        "score_key": score_key,
        "AUC": s["AUC"],
        "Accuracy@best": s["Accuracy@best"],
        "TPR@1%FPR": s["TPR@1%FPR"],
        "TPR@5%FPR": s["TPR@5%FPR"],
        "curve": [
            {"threshold": r["threshold"], "FPR": r["FPR"], "TPR": r["TPR"], "Accuracy": r["Accuracy"]}
            for r in sorted(s["threshold_curve"], key=lambda x: float(x["threshold"]))
        ],
    }


def analyze_feasibility(
    dataset: str,
    scores_path: str | Path,
    benchmark_path: str | Path,
    splits_dir: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """可行性验证主入口:跑三块分析,写出 json,并返回结果字典。

    参数:
        dataset:        数据集名。
        scores_path:    第 11 步产出的文档级分数 jsonl(含 cvg_rag/cvg_llm/cg_cvg/pcv_score)。
        benchmark_path: 攻击基准 jsonl(取 text/metadata 算 shortcut 特征)。
        splits_dir:     该数据集的切分目录(读 kb_member.jsonl / true_non_member.jsonl)。
        output_path:    可行性报告 json 输出路径。
    返回:
        结果字典(同时已写入 output_path)。
    """
    score_rows = list(read_jsonl(scores_path))
    benchmark_rows = list(read_jsonl(benchmark_path))

    # L1 群体校准:用 Reserve 的 cvg_rag 估非成员零分布,给待测样本算校准分;
    # eval_rows 已剔除 Reserve(校准组不进评估),后续 AUC/shortcut 都在 eval_rows 上算。
    calib = calibrate_membership_scores(score_rows, calibration_group=CALIBRATION_GROUP)
    eval_rows = calib["eval_rows"]

    signal = _signal_decomposition(eval_rows)
    shortcut = _shortcut_baseline(eval_rows, benchmark_rows)
    overlap = _source_overlap(Path(splits_dir))
    verdict = _verdict(signal, shortcut, overlap)
    comparison = _calibration_comparison(eval_rows)
    threshold_table = _threshold_table(eval_rows)

    report = {
        "dataset": dataset,
        "scored_samples": len(score_rows),       # 含 Reserve 的总打分数
        "eval_samples": len(eval_rows),          # 剔除 Reserve 后真正进评估的样本数
        "evaluation_unit": "source_document" if score_rows and score_rows[0].get("source_key") is not None else "audit_chunk",
        "signal_decomposition": signal,
        "shortcut_baseline": shortcut,
        "source_overlap": overlap,
        "calibration": {
            "method": "L1_population",
            "source_key": calib["source_key"],
            "calibration_group": CALIBRATION_GROUP,
            "reference_count": calib["reference_count"],
            "mu": calib["mu"],
            "sigma": calib["sigma"],
            "degenerate": calib["degenerate"],
            "comparison": comparison,
        },
        "verdict": verdict,
        "threshold_table": threshold_table,
    }
    write_json(report, output_path)
    LOGGER.info("Feasibility analysis written: %s (direction=%s)", output_path, verdict["direction"])
    return report
