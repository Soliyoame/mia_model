"""PCV-MIA evaluation metrics.

中文说明
========
本文件计算"攻击效果指标"。攻击的本质是个二分类:给每份文档打一个分,分高的判为"成员"。
要衡量这个分类器好不好,常用下面这些指标:
    - AUC(ROC 曲线下面积):衡量"成员的分普遍比非成员高"的程度。0.5=瞎猜,1.0=完美。
    - 在某个阈值下的 准确率/TPR/FPR:
        TPR(真正率/检出率)=成员中被正确判为成员的比例;
        FPR(假正率/误报率)=非成员中被错判为成员的比例。
    - TPR@1%FPR / TPR@5%FPR:把误报率压到很低(1%/5%)时还能检出多少成员——隐私攻击里
      常用这个"低误报下的检出能力"来评判攻击强弱。
本项目的非成员还分两种:True_Non_Member(真非成员) 和 Spoofed_Non_Member(伪造非成员,
对照组),所以会分别报告它们各自的误报率。
"""

from __future__ import annotations

import math
import random
from typing import Any


def safe_div(num: float, den: float) -> float:
    """安全除法:分母为 0 时返回 0.0,避免除零崩溃。"""
    return num / den if den else 0.0


def _binomial_cdf(k: int, n: int, probability: float) -> float:
    """计算 P(X<=k)，用于无额外依赖的精确二项区间。"""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(
        math.comb(n, index)
        * probability**index
        * (1.0 - probability) ** (n - index)
        for index in range(k + 1)
    )


def clopper_pearson_interval(
    successes: int,
    trials: int,
    *,
    confidence: float = 0.95,
) -> tuple[float | None, float | None]:
    """返回二项比例的双侧 Clopper-Pearson 精确置信区间。"""
    if trials <= 0 or successes < 0 or successes > trials:
        return None, None
    alpha = 1.0 - confidence

    def bisect(predicate: Any) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if predicate(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2.0

    lower = 0.0 if successes == 0 else bisect(
        lambda p: 1.0 - _binomial_cdf(successes - 1, trials, p) >= alpha / 2.0
    )
    upper = 1.0 if successes == trials else bisect(
        lambda p: _binomial_cdf(successes, trials, p) <= alpha / 2.0
    )
    return lower, upper


def low_fpr_exact_intervals(negative_count: int) -> list[dict[str, Any]]:
    """列出 0/1/2 个误报对应的 FPR 与精确区间。"""
    rows: list[dict[str, Any]] = []
    for false_positives in range(3):
        if false_positives > negative_count:
            continue
        lower, upper = clopper_pearson_interval(false_positives, negative_count)
        rows.append({
            "false_positives": false_positives,
            "negative_count": negative_count,
            "FPR": safe_div(false_positives, negative_count),
            "FPR_CI95": [lower, upper],
        })
    return rows


def roc_auc(rows: list[dict[str, Any]], score_key: str = "pcv_score", positive_group: str = "KB_Member") -> float | None:
    """Mann-Whitney U 形式的 ROC-AUC。

    用平均秩法做到 O(n log n)，结果与朴素成对比较（含 ties 计 0.5）完全等价。

    中文说明：AUC 也可以这样理解——随机取一个成员和一个非成员，"成员分更高"的概率。
    这里用"按分数排名、求成员的秩和"这一数学技巧高效算出同一个值(等价于挨个两两比较,
    但快得多);分数相同时按平均秩处理(相当于算 0.5)。

    参数:
        rows:           每份文档的打分记录(含 group 与分数字段)。
        score_key:      用哪个字段当分数。
        positive_group: 哪个分组算"正类(成员)"。
    返回:
        AUC 值(0~1);若没有正样本或没有负样本则返回 None。
    """
    # 按分组把分数分成"正类(成员)"和"负类(非成员)"两堆。
    values = _complete_score_values(rows, score_key)
    if values is None:
        return None
    positives = [value for row, value in zip(rows, values) if row.get("group") == positive_group]
    negatives = [value for row, value in zip(rows, values) if row.get("group") != positive_group]
    # 缺任一类就算不了 AUC。
    if not positives or not negatives:
        return None
    n_pos = len(positives)
    n_neg = len(negatives)
    # (score, is_positive)；排序后对相等分数取平均秩以正确处理 ties。
    combined = sorted([(score, 1) for score in positives] + [(score, 0) for score in negatives])
    rank_sum_pos = 0.0
    i = 0
    total = len(combined)
    # 逐段扫描:把"分数相等"的一段视为一组,给它们相同的"平均秩"。
    while i < total:
        j = i
        # 找到与 combined[i] 分数相同的这一段 [i, j)。
        while j < total and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0  # 1-based 秩 i+1..j 的平均
        # 把这一段里属于正类的样本,按平均秩累加到正类秩和。
        rank_sum_pos += avg_rank * sum(label for _, label in combined[i:j])
        i = j
    # 由秩和换算出 Mann-Whitney U 统计量,再除以 n_pos*n_neg 即得 AUC。
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2.0
    return u / (n_pos * n_neg)


def rates_at_threshold(
    rows: list[dict[str, Any]],
    threshold: float,
    score_key: str = "pcv_score",
    positive_group: str = "KB_Member",
) -> dict[str, Any]:
    """在给定阈值下,计算准确率、TPR、FPR 等一组指标(分数≥阈值即判为成员)。

    参数:
        rows:           打分记录。
        threshold:      判定阈值。
        score_key:      分数字段。
        positive_group: 正类分组名。
    返回:
        含 Accuracy/TPR/FPR/各分组 FPR/检出率等的字典。
    """
    values = _complete_score_values(rows, score_key)
    if values is None:
        return {
            "status": "unavailable",
            "score_key": score_key,
            "threshold": threshold,
            "Accuracy": None,
            "TPR": None,
            "FPR": None,
            "FPR-True_Non_Member": None,
            "FPR-Spoofed_Non_Member": None,
            "Detection Rate": None,
            "predicted_member_count": None,
        }
    # 单趟遍历累计全部计数，避免对同一份 rows 多次扫描
    # （本函数会被 threshold_curve 调用 O(唯一分数) 次）。
    pos_total = tnm_total = spoof_total = 0   # 各类样本总数
    tp = tn_hits = spoof_hits = predicted = correct = 0  # 各类命中数、预测为成员数、判对数
    for row, score in zip(rows, values):
        group = str(row.get("group"))
        # 这条是否被判为成员(分数 ≥ 阈值)。
        pred = score >= threshold
        is_pos = group == positive_group
        # 统计各类样本总数。
        if is_pos:
            pos_total += 1
        elif group == "True_Non_Member":
            tnm_total += 1
        elif group == "Spoofed_Non_Member":
            spoof_total += 1
        # 被判为成员时,按真实分组累计命中(用于算 TP / 各类误报)。
        if pred:
            predicted += 1
            if is_pos:
                tp += 1
            elif group == "True_Non_Member":
                tn_hits += 1
            elif group == "Spoofed_Non_Member":
                spoof_hits += 1
        # 预测与真实一致(都成员或都非成员)就算判对。
        if is_pos == pred:
            correct += 1
    total = len(rows)
    fp = tn_hits + spoof_hits          # 总误报 = 两类非成员被误判之和
    negative = total - pos_total       # 负类总数
    return {
        "threshold": threshold,
        "Accuracy": safe_div(correct, total),                       # 准确率
        "TPR": safe_div(tp, pos_total),                             # 检出率(成员中被检出的比例)
        "FPR": safe_div(fp, negative),                              # 误报率(非成员中被误判的比例)
        "FPR-True_Non_Member": safe_div(tn_hits, tnm_total),        # 真非成员的误报率
        "FPR-Spoofed_Non_Member": safe_div(spoof_hits, spoof_total),# 伪造非成员(对照组)的误报率
        "Detection Rate": safe_div(predicted, total),               # 总体被判为成员的比例
        "predicted_member_count": predicted,
        "true_positive_count": tp,
        "false_positive_count": fp,
        "positive_count": pos_total,
        "negative_count": negative,
    }


def threshold_curve(rows: list[dict[str, Any]], score_key: str = "pcv_score") -> list[dict[str, Any]]:
    """扫描一系列阈值,得到一条"阈值→各指标"的曲线(供画 ROC、找 TPR@FPR 用)。

    参数:
        rows:      打分记录。
        score_key: 分数字段。
    返回:
        每个阈值一行指标的列表。
    """
    # 候选阈值 = 数据中出现过的所有分数 ∪ 几个常用值,去重后升序。
    # 显式加入 ±∞，保证 ROC 一定包含 (FPR=0,TPR=0) 与 (FPR=1,TPR=1) 两个端点。
    values = _complete_score_values(rows, score_key)
    if values is None:
        return []
    scores = sorted(
        set(values)
        | {float("-inf"), 0.0, 0.2, 0.3, 0.4, 0.5, 1.0, float("inf")}
    )
    return [rates_at_threshold(rows, threshold, score_key=score_key) for threshold in scores]


def tpr_at_fpr(curve: list[dict[str, Any]], target: float) -> float | None:
    """在"误报率不超过 target"的前提下,求能达到的最高检出率(TPR@x%FPR)。

    参数:
        curve:  threshold_curve 得到的曲线。
        target: 允许的最大 FPR(如 0.01 表示 1%)。
    返回:
        满足约束下的最大 TPR;没有满足的阈值则返回 None。
    """
    # 先筛出 FPR ≤ target 的那些阈值点。
    feasible = [row for row in curve if float(row["FPR"]) <= target]
    if not feasible:
        return None
    # 在这些点里取 TPR 最大的那个。
    return float(max(feasible, key=lambda row: row["TPR"])["TPR"])


def tpr_at_fpr_details(
    curve: list[dict[str, Any]], target: float
) -> dict[str, Any] | None:
    """Return the conservative empirical operating point without interpolation."""

    feasible = [row for row in curve if float(row["FPR"]) <= target]
    if not feasible:
        return None
    selected = max(
        feasible,
        key=lambda row: (
            float(row["TPR"]),
            -float(row["FPR"]),
            float(row["threshold"]),
        ),
    )
    return {
        "target_fpr": float(target),
        "TPR": float(selected["TPR"]),
        "achieved_FPR": float(selected["FPR"]),
        "threshold": float(selected["threshold"]),
        "false_positive_count": int(selected.get("false_positive_count") or 0),
        "negative_count": int(selected.get("negative_count") or 0),
        "tie_policy": "score_greater_or_equal_threshold",
        "interpolation": False,
    }


def summarize_membership_scores(rows: list[dict[str, Any]], score_key: str = "pcv_score", threshold: float = 0.3) -> dict[str, Any]:
    """把上面各指标打包成一份完整的"成员推理评测摘要"。

    参数:
        rows:      打分记录。
        score_key: 分数字段。
        threshold: 用于固定阈值指标的阈值。
    返回:
        含 AUC、固定阈值下各指标、TPR@1%/5%FPR、以及完整阈值曲线的字典。
    """
    if _complete_score_values(rows, score_key) is None:
        return {
            "status": "unavailable",
            "score_key": score_key,
            "AUC": None,
            "threshold": threshold,
            "Accuracy": None,
            "TPR": None,
            "FPR": None,
            "FPR-True_Non_Member": None,
            "FPR-Spoofed_Non_Member": None,
            "Detection Rate": None,
            "predicted_member_count": None,
            "Oracle Accuracy@best": None,
            "Oracle TPR@0.5%FPR": None,
            "Oracle TPR@1%FPR": None,
            "Oracle TPR@5%FPR": None,
            "Attack Advantage": None,
            "Accuracy@best": None,
            "TPR@0.5%FPR": None,
            "TPR@0.5%FPR_details": None,
            "TPR@1%FPR": None,
            "TPR@5%FPR": None,
            "threshold_curve": [],
        }
    curve = threshold_curve(rows, score_key=score_key)
    fixed = rates_at_threshold(rows, threshold=threshold, score_key=score_key)
    # Accuracy@best:扫所有阈值能达到的最高准确率(=攻击正确判定成员/非成员的最高比率)。
    # 注意是"最优阈值下"的准确率,严格比较时该用独立验证集定阈,这里作方向性参考。
    best_acc = max((float(r["Accuracy"]) for r in curve), default=0.0)
    oracle_tpr_05 = tpr_at_fpr(curve, 0.005)
    oracle_tpr_1 = tpr_at_fpr(curve, 0.01)
    oracle_tpr_5 = tpr_at_fpr(curve, 0.05)
    attack_advantage = max(
        (float(row["TPR"]) - float(row["FPR"]) for row in curve),
        default=0.0,
    )
    return {
        "status": "available",
        "score_key": score_key,
        "AUC": roc_auc(rows, score_key=score_key),
        **fixed,
        "Oracle Accuracy@best": best_acc,
        "Oracle TPR@0.5%FPR": oracle_tpr_05,
        "Oracle TPR@1%FPR": oracle_tpr_1,
        "Oracle TPR@5%FPR": oracle_tpr_5,
        "Attack Advantage": attack_advantage,
        # 旧字段保留兼容，但新报告必须显示 Oracle 前缀。
        "Accuracy@best": best_acc,
        "TPR@0.5%FPR": oracle_tpr_05,
        "TPR@0.5%FPR_details": tpr_at_fpr_details(curve, 0.005),
        "TPR@1%FPR": oracle_tpr_1,
        "TPR@5%FPR": oracle_tpr_5,
        "threshold_curve": curve,
    }


def _complete_score_values(
    rows: list[dict[str, Any]],
    score_key: str,
) -> list[float] | None:
    """Return finite scores, or None when any row lacks the requested metric."""

    if not rows:
        return None
    values: list[float] = []
    for row in rows:
        value = row.get(score_key)
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        values.append(numeric)
    return values


def conformal_nonmember_p_value(
    score: float,
    reserve_scores: list[float],
) -> float:
    """用已知非成员 Reserve 分数计算保守的非成员 conformal p-value。

    高分更像成员。使用 ``>=`` 将与候选并列的 Reserve 计入尾部，避免随机拆 ties 美化结果。
    """
    if not reserve_scores:
        raise ValueError("Reserve scores are required for conformal calibration")
    tail = sum(1 for value in reserve_scores if value >= score)
    return (1.0 + tail) / (len(reserve_scores) + 1.0)


def summarize_conformal_membership(
    rows: list[dict[str, Any]],
    *,
    score_key: str = "pcv_score",
    alpha: float = 0.01,
    calibration_group: str = "Reserve",
    positive_group: str = "KB_Member",
    calibration_source_keys: set[str] | None = None,
) -> dict[str, Any]:
    """做 Retriever 冻结后的经验非成员校准。

    ``calibration_source_keys`` 用于永久排除 Pilot 使用的 Reserve。该校准是
    secondary empirical calibration；本函数不声称独立校准覆盖保证。
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0,1): {alpha}")
    reserve_rows = [
        row
        for row in rows
        if str(row.get("group")) == calibration_group
        and (
            calibration_source_keys is None
            or str(row.get("source_key") or row.get("source_id"))
            in calibration_source_keys
        )
    ]
    reserve_scores = [float(row.get(score_key, 0.0)) for row in reserve_rows]
    eval_rows = [row for row in rows if str(row.get("group")) != calibration_group]
    if not reserve_scores:
        return {
            "status": "missing_reserve",
            "target_alpha": alpha,
            "reserve_count": 0,
            "score_key": score_key,
        }

    predictions: list[tuple[dict[str, Any], bool, float]] = []
    for row in eval_rows:
        p_value = conformal_nonmember_p_value(float(row.get(score_key, 0.0)), reserve_scores)
        predictions.append((row, p_value <= alpha, p_value))

    pos_total = sum(1 for row, _, _ in predictions if str(row.get("group")) == positive_group)
    true_non_total = sum(1 for row, _, _ in predictions if str(row.get("group")) == "True_Non_Member")
    spoof_total = sum(1 for row, _, _ in predictions if str(row.get("group")) == "Spoofed_Non_Member")
    tp = sum(1 for row, pred, _ in predictions if pred and str(row.get("group")) == positive_group)
    fp_true = sum(1 for row, pred, _ in predictions if pred and str(row.get("group")) == "True_Non_Member")
    fp_spoof = sum(1 for row, pred, _ in predictions if pred and str(row.get("group")) == "Spoofed_Non_Member")
    negative_total = true_non_total + spoof_total
    return {
        "status": "ok",
        "target_alpha": alpha,
        "score_key": score_key,
        "reserve_count": len(reserve_scores),
        "eval_count": len(eval_rows),
        "TPR": safe_div(tp, pos_total),
        "realized_FPR": safe_div(fp_true + fp_spoof, negative_total),
        "FPR-True_Non_Member": safe_div(fp_true, true_non_total),
        "FPR-Spoofed_Non_Member": safe_div(fp_spoof, spoof_total),
        "true_positives": tp,
        "false_positives": fp_true + fp_spoof,
        "positive_count": pos_total,
        "negative_count": negative_total,
        "min_attainable_p": 1.0 / (len(reserve_scores) + 1.0),
        "calibration_scope": "post_retriever_frozen_nonmember_calibration",
        "retriever_selection_used_reserve_recall": True,
        "retriever_selection_used_attack_scores": False,
        "pilot_reserve_excluded_from_calibration": calibration_source_keys is not None,
    }


def _percentile(values: list[float], q: float) -> float | None:
    """小型线性插值分位数，避免为 CI 引入额外依赖。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def bootstrap_auc_ci(
    rows: list[dict[str, Any]],
    *,
    score_key: str = "pcv_score",
    positive_group: str = "KB_Member",
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """在正/负 source 池内分层重采样，给 source-level AUC 计算 95% CI。"""
    positives = [row for row in rows if str(row.get("group")) == positive_group]
    negatives = [row for row in rows if str(row.get("group")) != positive_group]
    point = roc_auc(rows, score_key=score_key, positive_group=positive_group)
    if not positives or not negatives or n_bootstrap <= 0:
        return {"estimate": point, "ci95": [None, None], "bootstrap": 0, "seed": seed}
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(n_bootstrap):
        sample = rng.choices(positives, k=len(positives)) + rng.choices(negatives, k=len(negatives))
        auc = roc_auc(sample, score_key=score_key, positive_group=positive_group)
        if auc is not None:
            samples.append(float(auc))
    return {
        "estimate": point,
        "ci95": [_percentile(samples, 0.025), _percentile(samples, 0.975)],
        "bootstrap": n_bootstrap,
        "seed": seed,
    }


def bootstrap_conformal_ci(
    rows: list[dict[str, Any]],
    *,
    score_key: str = "pcv_score",
    alpha: float = 0.01,
    calibration_group: str = "Reserve",
    n_bootstrap: int = 2000,
    seed: int = 42,
    calibration_source_keys: set[str] | None = None,
) -> dict[str, Any]:
    """同时重采样 Reserve 与测试组，传播 conformal 阈值的不确定性。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("group")), []).append(row)
    reserve = [
        row
        for row in grouped.get(calibration_group, [])
        if (
            calibration_source_keys is None
            or str(row.get("source_key") or row.get("source_id"))
            in calibration_source_keys
        )
    ]
    eval_groups = {group: values for group, values in grouped.items() if group != calibration_group}
    point = summarize_conformal_membership(
        rows,
        score_key=score_key,
        alpha=alpha,
        calibration_group=calibration_group,
        calibration_source_keys=calibration_source_keys,
    )
    if not reserve or not eval_groups or n_bootstrap <= 0:
        return {**point, "TPR_ci95": [None, None], "FPR_ci95": [None, None], "bootstrap": 0, "seed": seed}
    rng = random.Random(seed)
    tprs: list[float] = []
    fprs: list[float] = []
    for _ in range(n_bootstrap):
        sample = rng.choices(reserve, k=len(reserve))
        for values in eval_groups.values():
            sample.extend(rng.choices(values, k=len(values)))
        metric = summarize_conformal_membership(
            sample,
            score_key=score_key,
            alpha=alpha,
            calibration_group=calibration_group,
            calibration_source_keys=calibration_source_keys,
        )
        if metric.get("status") == "ok":
            tprs.append(float(metric["TPR"]))
            fprs.append(float(metric["realized_FPR"]))
    return {
        **point,
        "TPR_ci95": [_percentile(tprs, 0.025), _percentile(tprs, 0.975)],
        "FPR_ci95": [_percentile(fprs, 0.025), _percentile(fprs, 0.975)],
        "bootstrap": n_bootstrap,
        "seed": seed,
    }


def paired_bootstrap_metric_delta(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    *,
    left_score_key: str,
    right_score_key: str,
    id_key: str = "source_key",
    positive_group: str = "KB_Member",
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """在共同 source 上使用相同分层重采样索引，估计 left-right 指标差。"""
    left = {str(row.get(id_key)): row for row in left_rows}
    right = {str(row.get(id_key)): row for row in right_rows}
    common = sorted(set(left) & set(right))
    common = [key for key in common if str(left[key].get("group")) == str(right[key].get("group"))]
    positives = [key for key in common if str(left[key].get("group")) == positive_group]
    negatives = [key for key in common if str(left[key].get("group")) != positive_group]

    def metrics(keys: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
        lrows = [left[key] for key in keys]
        rrows = [right[key] for key in keys]
        return (
            summarize_membership_scores(lrows, score_key=left_score_key),
            summarize_membership_scores(rrows, score_key=right_score_key),
        )

    point_left, point_right = metrics(common) if positives and negatives else ({}, {})
    fields = (
        "AUC",
        "Oracle TPR@1%FPR",
        "Oracle TPR@5%FPR",
        "Attack Advantage",
    )
    point = {
        field: (
            float(point_left[field]) - float(point_right[field])
            if point_left.get(field) is not None and point_right.get(field) is not None else None
        )
        for field in fields
    }
    samples: dict[str, list[float]] = {field: [] for field in fields}
    if positives and negatives and n_bootstrap > 0:
        rng = random.Random(seed)
        for _ in range(n_bootstrap):
            sampled = rng.choices(positives, k=len(positives)) + rng.choices(negatives, k=len(negatives))
            lmetric, rmetric = metrics(sampled)
            for field in fields:
                if lmetric.get(field) is not None and rmetric.get(field) is not None:
                    samples[field].append(float(lmetric[field]) - float(rmetric[field]))
    return {
        "common_sources": len(common),
        "positive_sources": len(positives),
        "negative_sources": len(negatives),
        "estimate": point,
        "ci95": {field: [_percentile(values, 0.025), _percentile(values, 0.975)] for field, values in samples.items()},
        "bootstrap": n_bootstrap if positives and negatives else 0,
        "seed": seed,
    }


def bootstrap_macro_auc_ci(
    dataset_rows: dict[str, list[dict[str, Any]]],
    *,
    score_key: str = "pcv_score",
    positive_group: str = "KB_Member",
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """三个数据集内分层重采样后，计算等权 macro source-level AUC CI。"""

    datasets = sorted(dataset_rows)
    point_values = [
        roc_auc(dataset_rows[name], score_key=score_key, positive_group=positive_group)
        for name in datasets
    ]
    point_finite = [float(value) for value in point_values if value is not None]
    point = sum(point_finite) / len(point_finite) if len(point_finite) == len(datasets) else None
    if not datasets or point is None or n_bootstrap <= 0:
        return {
            "estimate": point,
            "ci95": [None, None],
            "datasets": datasets,
            "bootstrap": 0,
            "seed": seed,
        }
    strata: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for dataset in datasets:
        rows = dataset_rows[dataset]
        positives = [
            row for row in rows if str(row.get("group")) == positive_group
        ]
        negatives = [
            row for row in rows if str(row.get("group")) != positive_group
        ]
        if not positives or not negatives:
            return {
                "estimate": point,
                "ci95": [None, None],
                "datasets": datasets,
                "bootstrap": 0,
                "seed": seed,
            }
        strata[dataset] = (positives, negatives)
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(n_bootstrap):
        aucs: list[float] = []
        for dataset in datasets:
            positives, negatives = strata[dataset]
            sample = rng.choices(positives, k=len(positives))
            sample += rng.choices(negatives, k=len(negatives))
            value = roc_auc(
                sample,
                score_key=score_key,
                positive_group=positive_group,
            )
            if value is not None:
                aucs.append(float(value))
        if len(aucs) == len(datasets):
            samples.append(sum(aucs) / len(aucs))
    return {
        "estimate": point,
        "ci95": [_percentile(samples, 0.025), _percentile(samples, 0.975)],
        "datasets": datasets,
        "bootstrap": n_bootstrap,
        "seed": seed,
    }
