"""最终报告生成模块。

中文说明
========
本文件对应流水线第 15 步「生成报告」。它把前面各阶段产出的零散结果(攻击基准统计、
打分指标、隐蔽过滤情况、RAG 索引信息、baseline 对照、机制分析、防御实验等)汇总成
两份东西:一份机器可读的 JSON 完整报告,一份人看的 Markdown 摘要。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from .metrics import (
    bootstrap_auc_ci,
    bootstrap_conformal_ci,
    low_fpr_exact_intervals,
    summarize_membership_scores,
)
from ..scoring.calibration import CALIBRATION_GROUP
from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import read_json, read_jsonl, write_json
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def generate_final_report(
    dataset: str,
    benchmark_path: str | Path,
    scores_path: str | Path,
    stealth_manifest_path: str | Path,
    index_manifest_path: str | Path,
    baseline_path: str | Path,
    mechanism_path: str | Path,
    defense_path: str | Path,
    report_json_path: str | Path,
    summary_md_path: str | Path,
    threshold: float = 0.3,
    resume: bool = True,
    force: bool = False,
    coverage_path: str | Path | None = None,
) -> dict[str, Any]:
    """汇总各阶段 manifest 和指标，生成 JSON + Markdown 报告。

    参数:
        dataset:               数据集名。
        benchmark_path:        攻击基准文件(用于统计各分组样本数)。
        scores_path:           打分结果文件。
        stealth_manifest_path: 隐蔽过滤的 manifest。
        index_manifest_path:   RAG 索引的 manifest。
        baseline_path:         baseline 对照结果。
        mechanism_path:        机制分析结果。
        defense_path:          防御实验结果。
        report_json_path:      输出的 JSON 报告路径。
        summary_md_path:       输出的 Markdown 摘要路径。
        threshold:             计算固定阈值指标用的阈值。
        resume:                断点续跑:两份报告都已存在则跳过。
        force:                 强制重跑。
    返回:
        report(字典):完整报告内容;若跳过则带 skipped_existing。
    """
    report_path = Path(report_json_path)
    summary_path = Path(summary_md_path)
    # 断点续跑:JSON 和 Markdown 都在就跳过。
    if resume and not force and report_path.exists() and summary_path.exists():
        LOGGER.info("Skipping existing final report: %s", report_path)
        return {"dataset": dataset, "report_path": str(report_path), "skipped_existing": True}

    benchmark_rows = list(read_jsonl(benchmark_path))
    score_rows = list(read_jsonl(scores_path))
    if score_rows and any(not row.get("source_key") for row in score_rows):
        raise ValueError("Final report requires source-level score rows with source_key")
    coverage_rows = list(read_jsonl(coverage_path)) if coverage_path and Path(coverage_path).exists() else []
    # 自动判断主分数字段:有 pcv_score 就用它,否则退回 cg_cvg(当前 pcv_scorer 产出的
    # context-gain 字段)。原 fallback 名 cg_cms 经查全历史从未被任何版本产出过,是指向
    # 虚构字段的死兜底,故改指真实字段 cg_cvg;当前正常流程必有 pcv_score,此兜底仅防御
    # 缺字段的边缘输入,不影响实际产出的分数。
    score_key = "pcv_score" if score_rows and "pcv_score" in score_rows[0] else "cg_cvg"
    # 评估指标必须排除校准组 Reserve:它是 L1 群体校准的非成员零分布,不是测试样本。
    # 若不排除,会被 roc_auc 当成负类、混入 FPR 分母,使主报告的 AUC/TPR@1%FPR/FPR
    # 与 analyze_feasibility 口径不一致(后者已剔除 Reserve)。
    eval_rows = [row for row in score_rows if str(row.get("group")) != CALIBRATION_GROUP]
    source_keys = sorted({str(row.get("source_key")) for row in eval_rows})
    source_whitelist_hash = sha256_obj(source_keys)
    # 算主攻击指标(在排除 Reserve 后的 source-level 评估样本上)。
    metrics = summarize_membership_scores(eval_rows, score_key=score_key, threshold=threshold)
    metrics["AUC_CI"] = bootstrap_auc_ci(eval_rows, score_key=score_key)
    calibrated = {
        "alpha_0.01": bootstrap_conformal_ci(score_rows, score_key=score_key, alpha=0.01),
        "alpha_0.05": bootstrap_conformal_ci(score_rows, score_key=score_key, alpha=0.05),
    }
    negative_count = sum(1 for row in eval_rows if str(row.get("group")) != "KB_Member")
    # 分组分数分布保留所有组(含 Reserve)用于诊断展示:Reserve 的均值应≈True_Non_Member。
    group_scores = _score_distribution(score_rows)
    report = {
        "dataset": dataset,
        "evaluation_unit": "source",
        "main_score_definition": "pair mean within chunk, then equal chunk mean within source",
        "source_whitelist_hash": source_whitelist_hash,
        "input_provenance": {
            "benchmark": _file_provenance(benchmark_path),
            "source_scores": _file_provenance(scores_path),
            "source_coverage": _file_provenance(coverage_path),
            "stealth_manifest": _file_provenance(stealth_manifest_path),
            "index_manifest": _file_provenance(index_manifest_path),
            "baseline_comparison": _file_provenance(baseline_path),
            "mechanism": _file_provenance(mechanism_path),
            "defense": _file_provenance(defense_path),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_statistics": {
            # 统计基准里各分组各有多少样本。
            "benchmark_counts": dict(Counter(row["group"] for row in benchmark_rows)),
            "num_benchmark_samples": len(benchmark_rows),
            "benchmark_source_counts": {
                group: len({str(row.get("source_key") or row.get("source_id") or row.get("audit_id")) for row in benchmark_rows if row.get("group") == group})
                for group in sorted({str(row.get("group")) for row in benchmark_rows})
            },
            "num_scored_sources": len(score_rows),
            "coverage": {
                "planned_sources": len(coverage_rows),
                "attack_eligible_sources": sum(1 for row in coverage_rows if row.get("attack_eligible")),
                "eligible_sources": sum(1 for row in coverage_rows if row.get("evaluation_eligible")),
                "excluded_sources": sum(1 for row in coverage_rows if not row.get("evaluation_eligible")),
                "by_group": {
                    group: {
                        "planned": sum(1 for row in coverage_rows if row.get("group") == group),
                        "attack_eligible": sum(1 for row in coverage_rows if row.get("group") == group and row.get("attack_eligible")),
                        "eligible": sum(1 for row in coverage_rows if row.get("group") == group and row.get("evaluation_eligible")),
                    }
                    for group in sorted({str(row.get("group")) for row in coverage_rows})
                },
            },
        },
        "rag_index_statistics": _read_optional_json(index_manifest_path),
        "control_group_quality_statistics": {
            "Spoofed_Non_Member": "experimental control group only; see datasets/spoofed/{dataset}/spoof_manifest.json"
        },
        "main_attack_results": metrics,
        "low_fpr_exact_intervals": low_fpr_exact_intervals(negative_count),
        "calibrated_attack_results": calibrated,
        "main_score_key": score_key,
        "score_distributions": group_scores,
        # baseline 文件存在才读,否则给空列表。
        "baseline_comparison": list(read_jsonl(baseline_path)) if Path(baseline_path).exists() else [],
        "mechanism_analysis": _read_optional_json(mechanism_path),
        "defense_privacy_utility_tradeoff": _read_optional_json(defense_path),
        "stealth_filter": _read_optional_json(stealth_manifest_path),
        # 论文必报的几项关键指标,单独再列一份方便查阅。
        "required_report_items": {
            "Oracle TPR@1%FPR": metrics.get("Oracle TPR@1%FPR"),
            "Oracle TPR@5%FPR": metrics.get("Oracle TPR@5%FPR"),
            "Calibrated alpha=1%": calibrated["alpha_0.01"],
            "Calibrated alpha=5%": calibrated["alpha_0.05"],
            "FPR-True_Non_Member": metrics.get("FPR-True_Non_Member"),
            "FPR-Spoofed_Non_Member_control": metrics.get("FPR-Spoofed_Non_Member"),
            "Stealth detection rate": _read_optional_json(stealth_manifest_path).get("stealth_detection_rate"),
            "LLM-only vs RAG context gain": group_scores,
        },
    }
    write_json(report, report_path)
    # 确保摘要目录存在,再写 Markdown。
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(_render_summary(report), encoding="utf-8")
    LOGGER.info("Final report written: %s and %s", report_path, summary_path)
    return report


def _read_optional_json(path: str | Path) -> dict[str, Any]:
    """读取一个 JSON 文件;文件不存在则返回空字典(让缺某阶段产物时也能出报告)。"""
    p = Path(path)
    if not p.exists():
        return {}
    return read_json(p)


def _file_provenance(path: str | Path | None) -> dict[str, Any]:
    """记录报告输入文件的绝对路径、大小和 hash；缺失输入显式保留。"""
    if path is None:
        return {"path": "", "exists": False, "size": None, "sha256": ""}
    p = Path(path).resolve()
    if not p.is_file():
        return {"path": str(p), "exists": False, "size": None, "sha256": ""}
    return {
        "path": str(p),
        "exists": True,
        "size": p.stat().st_size,
        "sha256": sha256_file(p),
    }


def _score_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """按分组统计平均分(cvg_rag / cvg_llm / cg_cvg / pcv_score)。

    成员组的 cg_cvg/pcv_score 应明显高于非成员组——这是攻击有效的直接体现。

    参数:
        rows: 打分记录。
    返回:
        {分组: {count, 各项平均分}} 的字典。
    """
    # 先按分组把记录归桶。
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("group", "unknown"))].append(row)
    out = {}
    for group, group_rows in buckets.items():
        def optional_mean(key: str) -> float | None:
            values = [row.get(key) for row in group_rows]
            if not values or any(value is None for value in values):
                return None
            return mean(float(value) for value in values)

        # 对每个分组求各项分数的平均,均用当前 pcv_scorer 产出的真实字段
        # (cvg_rag / cvg_llm / cg_cvg / pcv_score)。原 cms_* / cg_cms 旧兜底经查全历史从未被
        # 任何版本产出过,是死兜底,已清除;pcv_score 缺失时退回 cg_cvg(真实字段)。
        out[group] = {
            "count": len(group_rows),
            "cvg_rag_avg": mean([float(row.get("cvg_rag", 0.0)) for row in group_rows]) if group_rows else 0.0,
            "cvg_llm_avg": optional_mean("cvg_llm"),
            "cg_cvg_avg": optional_mean("cg_cvg"),
            "attribution_status": (
                "available"
                if group_rows and all(row.get("attribution_status") == "available" for row in group_rows)
                else "unavailable"
            ),
            "pcv_score_avg": mean([float(row.get("pcv_score", row.get("cg_cvg", 0.0))) for row in group_rows]) if group_rows else 0.0,
        }
    return out


def _num(value: Any, digits: int = 4) -> str:
    """把数值格式化成摘要里的字符串:None→"-",float 定点,其它原样。"""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _render_summary(report: dict[str, Any]) -> str:
    """把报告里最关键的几项渲染成一段 Markdown 文本(给人快速浏览)。

    参数:
        report: 完整报告字典。
    返回:
        Markdown 格式的摘要字符串。
    """
    metrics = report.get("main_attack_results", {})
    counts = report.get("data_statistics", {}).get("benchmark_counts", {})
    dist = report.get("score_distributions", {})

    # benchmark counts → Markdown 列表(原来直接 str(dict),很难读)。
    counts_md = "\n".join(f"- {group}: {n}" for group, n in counts.items()) or "- (none)"

    # score_distributions → Markdown 表格(原来直接把整个 dict 糊进去)。
    dist_header = (
        "| group | count | cvg_rag_avg | cvg_llm_avg | cg_cvg_avg | pcv_score_avg |\n"
        "| --- | --- | --- | --- | --- | --- |"
    )
    dist_lines = [
        f"| {group} | {d.get('count', '-')} | {_num(d.get('cvg_rag_avg'))} | "
        f"{_num(d.get('cvg_llm_avg'))} | {_num(d.get('cg_cvg_avg'))} | {_num(d.get('pcv_score_avg'))} |"
        for group, d in dist.items()
    ]
    dist_md = "\n".join([dist_header, *dist_lines]) if dist_lines else "(no scores)"

    return (
        f"# {report['dataset']} PCV-MIA Summary\n\n"
        f"- Created at: {report['created_at']}\n"
        f"- AUC: {_num(metrics.get('AUC'))}\n"
        f"- Accuracy @ threshold {metrics.get('threshold')}: {_num(metrics.get('Accuracy'))}\n"
        f"- Oracle TPR@1%FPR: {_num(metrics.get('Oracle TPR@1%FPR'))}\n"
        f"- Oracle TPR@5%FPR: {_num(metrics.get('Oracle TPR@5%FPR'))}\n"
        f"- Calibrated TPR @ alpha=1%: {_num(report.get('calibrated_attack_results', {}).get('alpha_0.01', {}).get('TPR'))}\n"
        f"- Realized FPR @ alpha=1%: {_num(report.get('calibrated_attack_results', {}).get('alpha_0.01', {}).get('realized_FPR'))}\n"
        f"- FPR True_Non_Member: {_num(metrics.get('FPR-True_Non_Member'))}\n"
        f"- FPR Spoofed_Non_Member control group: {_num(metrics.get('FPR-Spoofed_Non_Member'))}\n\n"
        "## Benchmark counts\n\n"
        f"{counts_md}\n\n"
        "## Score Distributions\n\n"
        f"{dist_md}\n\n"
        "## Notes\n\n"
        "RAG retrieval internals are used only in mechanism analysis, not in black-box membership scoring.\n"
    )
