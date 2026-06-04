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

from typing import Any


def safe_div(num: float, den: float) -> float:
    """安全除法:分母为 0 时返回 0.0,避免除零崩溃。"""
    return num / den if den else 0.0


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
    positives = [float(row.get(score_key, 0.0)) for row in rows if row.get("group") == positive_group]
    negatives = [float(row.get(score_key, 0.0)) for row in rows if row.get("group") != positive_group]
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
    # 单趟遍历累计全部计数，避免对同一份 rows 多次扫描
    # （本函数会被 threshold_curve 调用 O(唯一分数) 次）。
    pos_total = tnm_total = spoof_total = 0   # 各类样本总数
    tp = tn_hits = spoof_hits = predicted = correct = 0  # 各类命中数、预测为成员数、判对数
    for row in rows:
        group = str(row.get("group"))
        # 这条是否被判为成员(分数 ≥ 阈值)。
        pred = float(row.get(score_key, 0.0)) >= threshold
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
    scores = sorted({float(row.get(score_key, 0.0)) for row in rows} | {0.0, 0.2, 0.3, 0.4, 0.5, 1.0})
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


def summarize_membership_scores(rows: list[dict[str, Any]], score_key: str = "pcv_score", threshold: float = 0.3) -> dict[str, Any]:
    """把上面各指标打包成一份完整的"成员推理评测摘要"。

    参数:
        rows:      打分记录。
        score_key: 分数字段。
        threshold: 用于固定阈值指标的阈值。
    返回:
        含 AUC、固定阈值下各指标、TPR@1%/5%FPR、以及完整阈值曲线的字典。
    """
    curve = threshold_curve(rows, score_key=score_key)
    fixed = rates_at_threshold(rows, threshold=threshold, score_key=score_key)
    return {
        "AUC": roc_auc(rows, score_key=score_key),
        **fixed,
        "TPR@1%FPR": tpr_at_fpr(curve, 0.01),
        "TPR@5%FPR": tpr_at_fpr(curve, 0.05),
        "threshold_curve": curve,
    }
