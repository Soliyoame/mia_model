"""PCV-MIA L1 群体校准(population-level calibration)。

中文说明
========
本模块把"朴素的减法终分" `cg_cvg = cvg_rag - cvg_llm` 升级成"相对非成员零分布的
偏离统计量"。零分布来自 **Reserve 组**:它同分布、非成员、与评估组(KB_Member /
True_Non_Member)source 互斥,随主流水线跑出 `cvg_rag` 后,只用来刻画"一个非成员在
这套 RAG 上 cvg 大致长什么样"。

为什么要校准(对应 cg_cvg 的三个缺陷):
  ① 零点估错:即便 x 非成员,RAG 也可能检索到语义近邻的成员文档,把 cvg_rag 抬高。
     用 Reserve 群体均值 μ 取代"减 cvg_llm",把这部分基线偏移扣掉。
  ② 没校准方差:全局阈值对高方差样本不公平。用 Reserve 群体的离散程度做标准化。
  ③ 点估计不是假设检验:把"差值"换成经验百分位 / z-score,有统计语义。

提供两种校准分(都写回每行)。**默认主分 = z-score**(PRIMARY_CALIBRATED_KEY):它是
source_key 的严格单调线性变换,保序、不制造 ties,故 AUC 与 TPR@FPR 同 source_key 完全一致、
低 FPR 不坍缩,且无量纲可跨集比较、能接 Φ(z) 变 p 值。经验百分位降为辅助:实测它是基于
Reserve 的阶梯函数,所有 source_key 超过 Reserve 上界的样本并列封顶到 1.0(顶端坍缩),既压低
AUC(edgar 0.947→0.919)、又使 1%FPR 取不到阈值(TPR@1%FPR=n/a),故不再当主分。
最终上报选哪档看预训练污染(cvg_llm AUC):干净集用 z-score(不扣先验);污染集用 cg_cvg
(全局扣)或 L2(逐样本扣)。三档在 feasibility 对比表并列。
注意:字段名 `pcv_score_calibrated` 是历史命名;默认 source_key 是 `cvg_rag`，
因此当前含义是 Reserve-calibrated RAG-CVG percentile，而不是对质量加权
`pcv_score` 的直接校准:
  - pcv_score_calibrated   经验百分位:Reserve 中 source_key ≤ 本样本的比例(mid-rank 处理 ties),
                           取值 [0,1],越高越像成员。
  - pcv_score_calibrated_z z-score:(source_key − μ_reserve) / σ_reserve。

L1 = 只用一个全局 (μ, σ) / 一条经验分布,所有待测样本共用(不建 shadow、不逐样本)。
评估指标必须排除 Reserve(它是校准料,不是测试样本),本模块返回的 eval_rows 已剔除它。
"""

from __future__ import annotations

import math
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from ..utils.io import read_jsonl, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)

# 校准依据的原始信号(Reserve 的这个字段构成零分布)。
CALIBRATION_SOURCE_KEY = "cvg_rag"
# 写回每行的校准分字段名。
PERCENTILE_KEY = "pcv_score_calibrated"
ZSCORE_KEY = "pcv_score_calibrated_z"
# L1 默认主校准分:z-score(严格单调保序、低 FPR 不坍缩;经验百分位仅作辅助/直观展示)。
PRIMARY_CALIBRATED_KEY = ZSCORE_KEY
# L2(per-example shadow)校准分字段名。
L2_KEY = "pcv_score_l2"          # 主 L2 分:Φ(z) ∈[0,1],越高越像成员
L2_Z_KEY = "pcv_score_l2_z"      # per-example z-score
# 默认把 Reserve 当校准组。
CALIBRATION_GROUP = "Reserve"


def empirical_percentile(value: float, reference: list[float]) -> float:
    """value 在 reference 经验分布中的百分位(mid-rank 处理 ties)。

    percentile = ( #{r < value} + 0.5 * #{r == value} ) / n。
    与 ROC-AUC 的 ties 计 0.5 口径一致;取值 [0,1],越大说明该值在参考分布里越靠右。

    参数:
        value:     待定位的分数。
        reference: 参考分布(这里是 Reserve 的 cvg_rag 列表)。
    返回:
        百分位 [0,1];reference 为空时返回 0.5(无信息)。
    """
    n = len(reference)
    if n == 0:
        return 0.5
    less = sum(1 for r in reference if r < value)
    equal = sum(1 for r in reference if r == value)
    return (less + 0.5 * equal) / n


def zscore(value: float, mu: float, sigma: float) -> float:
    """标准化:(value − mu) / sigma;sigma 为 0(参考全相同)时返回 0.0。"""
    if sigma <= 0.0:
        return 0.0
    return (value - mu) / sigma


def calibrate_membership_scores(
    score_rows: list[dict[str, Any]],
    *,
    source_key: str = CALIBRATION_SOURCE_KEY,
    calibration_group: str = CALIBRATION_GROUP,
) -> dict[str, Any]:
    """用 Reserve 群体的零分布,给待测样本算校准后的成员分。

    参数:
        score_rows:        第 11 步产出的文档级分数(每行含 group 与 source_key)。
        source_key:        校准依据的原始信号字段(默认 cvg_rag)。
        calibration_group: 充当零分布的组名(默认 Reserve)。
    返回:
        字典:
          eval_rows        剔除校准组后的待测样本行,每行新增 PERCENTILE_KEY / ZSCORE_KEY。
          reference_count  零分布样本数(Reserve 有效样本)。
          mu / sigma       零分布均值 / 总体标准差。
          source_key       本次校准用的原始信号字段。
          degenerate       True 表示零分布为空或方差为 0,校准退化(需告警)。
    """
    reference = [
        float(r.get(source_key, 0.0)) for r in score_rows if str(r.get("group")) == calibration_group
    ]
    mu = mean(reference) if reference else 0.0
    # 总体标准差(pstdev):把 Reserve 当作零分布的全量观测,而非其样本估计。
    sigma = pstdev(reference) if len(reference) > 1 else 0.0
    degenerate = (len(reference) == 0) or (sigma <= 0.0)
    if degenerate:
        LOGGER.warning(
            "校准零分布退化:reference_count=%s sigma=%.4f(Reserve 太少或 cvg_rag 全相同),"
            "校准分将不可靠,请增大 split 的 reserve 目标或检查 Reserve 是否真的跑过 06-11。",
            len(reference),
            sigma,
        )

    eval_rows: list[dict[str, Any]] = []
    for row in score_rows:
        if str(row.get("group")) == calibration_group:
            continue  # 校准组不进评估
        value = float(row.get(source_key, 0.0))
        enriched = dict(row)
        enriched[PERCENTILE_KEY] = empirical_percentile(value, reference)
        enriched[ZSCORE_KEY] = zscore(value, mu, sigma)
        eval_rows.append(enriched)

    LOGGER.info(
        "L1 群体校准完成:reference(%s)=%s, μ=%.4f, σ=%.4f, eval_rows=%s",
        calibration_group,
        len(reference),
        mu,
        sigma,
        len(eval_rows),
    )
    return {
        "eval_rows": eval_rows,
        "reference_count": len(reference),
        "mu": mu,
        "sigma": sigma,
        "source_key": source_key,
        "percentile_key": PERCENTILE_KEY,
        "zscore_key": ZSCORE_KEY,
        "primary_key": PRIMARY_CALIBRATED_KEY,  # 下游应优先用这个当 L1 主分(=z-score)
        "degenerate": degenerate,
    }


def calibrate_scores_file(
    scores_path: str | Path,
    output_path: str | Path | None = None,
    *,
    source_key: str = CALIBRATION_SOURCE_KEY,
    calibration_group: str = CALIBRATION_GROUP,
) -> dict[str, Any]:
    """文件版便捷封装:读分数 jsonl → 校准 → 把 eval_rows 写回(可选)。

    参数:
        scores_path:       第 11 步的 *_pcv_scores.jsonl。
        output_path:       校准后 eval_rows 的输出路径;None 则不落盘只返回。
        source_key:        校准依据字段。
        calibration_group: 零分布组名。
    返回:
        calibrate_membership_scores 的结果字典(若落盘则附 output_path)。
    """
    score_rows = list(read_jsonl(scores_path))
    result = calibrate_membership_scores(
        score_rows, source_key=source_key, calibration_group=calibration_group
    )
    if output_path is not None:
        write_jsonl(result["eval_rows"], output_path)
        result["output_path"] = str(output_path)
    return result


def _normal_cdf(z: float) -> float:
    """标准正态 CDF Φ(z),用 erf 实现(无 scipy 依赖)。"""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def calibrate_l2_shadow(
    main_score_rows: list[dict[str, Any]],
    shadow_score_rows_list: list[list[dict[str, Any]]],
    *,
    source_key: str = CALIBRATION_SOURCE_KEY,
    calibration_group: str = CALIBRATION_GROUP,
    min_shadows_per_example: int = 2,
) -> dict[str, Any]:
    """L2 per-example 校准:用 K 个 shadow 的 cvg_rag 估每个样本自己的非成员零分布。

    对每个评估目标 x:从 K 份 shadow 分数里收集它的 cvg_rag → OUT 分布 (μ_out(x), σ_out(x));
    victim 观测 = 主 run 的 cvg_rag(x)。per-example 标准化:

        z(x) = (cvg_rag_victim(x) − μ_out(x)) / σ_out(x)
        L2 分 = Φ(z)   ∈[0,1]，越高越像成员(offline LiRA 单边,等价 1 − p 值)

    这与 L1(全局单调变换、AUC≡cvg_rag、扣不掉 per-example 先验)本质不同:μ_out(x) 逐样本
    包含了 x 的先验可验证性,故 z 把 per-example 先验扣掉了——能修 L1 修不了的 cvg_llm 泄漏。

    方差兜底(variance flooring,LiRA 常用):σ_out(x) 为 0 或点数不足时,用全体样本 σ_out
    的中位数兜底,避免个别样本 z 爆炸/归零。

    参数:
        main_score_rows:        主 run 的 audit 级分数(含 group 与 source_key)。
        shadow_score_rows_list: K 份 shadow 的 audit 级分数列表。
        source_key:             用作信号的字段(默认 cvg_rag)。
        calibration_group:      评估时要剔除的校准组(默认 Reserve)。
        min_shadows_per_example: 每个样本至少需要多少个 shadow 观测才算 per-example σ。
    返回:
        字典:eval_rows(剔除校准组,每行加 L2_KEY / L2_Z_KEY)、num_shadows、
        sigma_floor、degenerate_examples(用兜底 σ 的样本数)等。
    """
    # 每个 shadow 建 audit_id → cvg_rag 映射。
    shadow_maps = [
        {str(r.get("audit_id")): float(r.get(source_key, 0.0)) for r in rows}
        for rows in shadow_score_rows_list
    ]
    K = len(shadow_maps)

    # 第一遍:收集每个评估样本的 OUT 点,算原始 σ_out,供兜底中位数。
    eval_main = [r for r in main_score_rows if str(r.get("group")) != calibration_group]
    raw_sigmas: list[float] = []
    per_example: dict[str, dict[str, Any]] = {}
    for r in eval_main:
        aid = str(r.get("audit_id"))
        out_vals = [m[aid] for m in shadow_maps if aid in m]
        mu = mean(out_vals) if out_vals else 0.0
        sigma = pstdev(out_vals) if len(out_vals) >= 2 else 0.0
        per_example[aid] = {"out_vals": out_vals, "mu": mu, "sigma": sigma}
        if len(out_vals) >= min_shadows_per_example and sigma > 0.0:
            raw_sigmas.append(sigma)
    # 方差兜底:有效 σ 的中位数;一个都没有则用极小值。
    sigma_floor = median(raw_sigmas) if raw_sigmas else 1e-6

    # 第二遍:逐样本算 z 与 Φ(z)。
    eval_rows: list[dict[str, Any]] = []
    degenerate = 0
    for r in eval_main:
        aid = str(r.get("audit_id"))
        pe = per_example[aid]
        obs = float(r.get(source_key, 0.0))
        n_out = len(pe["out_vals"])
        sigma = pe["sigma"]
        if n_out < min_shadows_per_example or sigma <= 0.0:
            sigma = sigma_floor
            degenerate += 1
        z = (obs - pe["mu"]) / sigma if sigma > 0 else 0.0
        enriched = dict(r)
        enriched[L2_Z_KEY] = z
        enriched[L2_KEY] = _normal_cdf(z)
        enriched["l2_mu_out"] = pe["mu"]
        enriched["l2_sigma_out"] = pe["sigma"]
        enriched["l2_n_shadows"] = n_out
        eval_rows.append(enriched)

    LOGGER.info(
        "L2 shadow 校准完成:K=%s, eval_rows=%s, σ_floor=%.4f, 用兜底σ的样本=%s",
        K, len(eval_rows), sigma_floor, degenerate,
    )
    return {
        "eval_rows": eval_rows,
        "num_shadows": K,
        "sigma_floor": sigma_floor,
        "degenerate_examples": degenerate,
        "source_key": source_key,
        "l2_key": L2_KEY,
        "l2_z_key": L2_Z_KEY,
    }


def calibrate_l2_from_files(
    main_scores_path: str | Path,
    shadow_score_paths: list[str | Path],
    output_path: str | Path | None = None,
    *,
    source_key: str = CALIBRATION_SOURCE_KEY,
    calibration_group: str = CALIBRATION_GROUP,
) -> dict[str, Any]:
    """文件版便捷封装:读主分数 + K 份 shadow 分数 → L2 校准 → 可选写回 eval_rows。"""
    main_rows = list(read_jsonl(main_scores_path))
    shadow_rows_list = [list(read_jsonl(p)) for p in shadow_score_paths]
    result = calibrate_l2_shadow(
        main_rows, shadow_rows_list, source_key=source_key, calibration_group=calibration_group
    )
    if output_path is not None:
        write_jsonl(result["eval_rows"], output_path)
        result["output_path"] = str(output_path)
    return result
