"""15: 生成最终的 PCV-MIA JSON 与 Markdown 报告。

中文说明
========
本文件对应流水线第 15 步「出最终报告」,是整条流水线的收尾。它把前面各环节的产物汇到一起
——攻击基准、PCV 分数、隐蔽性筛选 manifest、索引 manifest、baseline 对照结果、机理分析
报告、防御实验结果——交给 `src.evaluation.report_builder.generate_final_report`,
产出 `{dataset}_final_report.json` 和 `{dataset}_summary.md`(固定名 latest)。

此外每次运行都会**按时间戳归档 + 出一张综合图**(不覆盖历次):
    - outputs/runs/{dataset}/{run_id}/{dataset}_final_report_{run_id}.json + .md + .png
    - outputs/runs/{dataset}/index.jsonl 追加一行(历次总表)
    - outputs/runs/{dataset}/trend_report.png(历次 AUC 趋势)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.plots import plot_final_report, plot_run_trend
from src.evaluation.paper_figures import render_paper_figures
from src.evaluation.report_builder import generate_final_report
from src.llm.generator_registry import resolve_generator_from_pipeline_config
from src.rag.paths import retriever_id_from_config, retriever_index_dir
from src.utils.io import ensure_dir, load_yaml, read_json, read_jsonl, resolve_path, write_json, write_jsonl
from src.utils.logger import setup_logging
from src.utils.run_context import current_run_id, experiment_run_dir, experiment_scoped_dir, local_timestamp


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、threshold、force、no_resume。
    """
    parser = argparse.ArgumentParser(description="Generate final PCV-MIA report.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--rag-config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--attack-config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--retriever-backend", choices=["dense", "bm25", "hybrid"], default=None)
    parser.add_argument("--generator-family", choices=["gemini", "qwen", "gpt", "llama"], default=None)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def _read_scale() -> str:
    """从 data_config.yaml 读当前 split.scale(读不到留空,不阻塞)。"""
    try:
        cfg = load_yaml(resolve_path("configs/data_config.yaml"))
        return str(cfg.get("split", {}).get("scale", ""))
    except Exception:
        return ""


def main() -> int:
    """脚本入口:出最终报告 + 按时间戳归档 + 综合图。

    返回:
        进程退出码,正常结束返回 0。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = parse_args()
    rag_config = load_yaml(args.rag_config)
    attack_config = load_yaml(args.attack_config)
    retriever_backend = args.retriever_backend or str(
        rag_config.get("retrieval", {}).get("backend", "dense")
    )
    generator_identity, _ = resolve_generator_from_pipeline_config(
        rag_config,
        family=args.generator_family,
    )
    retriever_id = retriever_id_from_config(rag_config, retriever_backend)
    scope = {
        "generator_family": generator_identity.generator_family,
        "concrete_model": generator_identity.concrete_model,
        "retriever_id": retriever_id,
    }
    logger = setup_logging("pcv_mia", log_file=resolve_path("artifacts/v20/logs/report.log"), level="INFO")
    out_dir = ensure_dir(
        experiment_scoped_dir(rag_config["paths"]["reports_dir"], args.dataset, **scope)
    )
    scores_dir = experiment_scoped_dir(
        attack_config["paths"]["scores_dir"],
        args.dataset,
        **scope,
    )
    source_scores_path = scores_dir / f"{args.dataset}_pcv_scores_source_scores.jsonl"
    if not source_scores_path.exists():
        raise FileNotFoundError(f"Source-level scores are required for final report: {source_scores_path}")
    scores_path = source_scores_path
    coverage_path = scores_dir / f"{args.dataset}_pcv_scores_source_coverage.jsonl"
    if not coverage_path.exists():
        raise FileNotFoundError(f"Source coverage ledger is required for final report: {coverage_path}")
    report_json_path = out_dir / f"{args.dataset}_final_report.json"
    summary_md_path = out_dir / f"{args.dataset}_summary.md"
    rag_response_dir = experiment_scoped_dir(
        rag_config["paths"]["rag_responses_dir"],
        args.dataset,
        **scope,
    )
    index_manifest_path = (
        rag_response_dir / f"{args.dataset}_rag_responses.manifest.json"
        if retriever_backend == "hybrid"
        else retriever_index_dir(rag_config, args.dataset, retriever_backend)
        / "index_manifest.json"
    )
    baseline_dir = experiment_scoped_dir(
        "artifacts/v20/baselines",
        args.dataset,
        **scope,
    )
    mechanism_dir = experiment_scoped_dir(
        "artifacts/v20/mechanisms",
        args.dataset,
        **scope,
    )
    defense_dir = experiment_scoped_dir(
        "artifacts/v20/defenses",
        args.dataset,
        **scope,
    )
    report = generate_final_report(
        dataset=args.dataset,
        benchmark_path=resolve_path(rag_config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        scores_path=scores_path,
        stealth_manifest_path=resolve_path(rag_config["paths"]["queries_dir"]) / f"{args.dataset}_paired_queries.manifest.json",
        index_manifest_path=index_manifest_path,
        baseline_path=baseline_dir / f"{args.dataset}_baseline_comparison.jsonl",
        mechanism_path=mechanism_dir / f"{args.dataset}_mechanism_report.json",
        defense_path=defense_dir / f"{args.dataset}_defense_results.json",
        report_json_path=report_json_path,
        summary_md_path=summary_md_path,
        threshold=args.threshold,
        resume=not args.no_resume,
        force=args.force,
        coverage_path=coverage_path,
        reserve_roles_path=(
            resolve_path(
                rag_config["paths"].get(
                    "reserve_roles_dir",
                    "artifacts/v20/release_controls/reserve_roles",
                )
            )
            / f"{args.dataset}_reserve_roles.json"
        ),
    )
    logger.info("Step 15 finished: %s", report)

    # ---- 按时间戳归档 + 可视化(每次出报告都出一张图,不覆盖历次)----
    # resume 命中时 generate_final_report 只返回精简 dict,这里读回完整 json 用于画图。
    full_report = read_json(report_json_path) if report_json_path.exists() else report
    run_id = current_run_id()
    generated_at = local_timestamp()
    rdir = experiment_run_dir(
        rag_config["paths"]["runs_dir"],
        args.dataset,
        run_id,
        **scope,
    )
    score_rows = list(read_jsonl(scores_path)) if scores_path.exists() else []

    snap = f"{args.dataset}_final_report_{run_id}"  # 快照文件名带时间戳,单看文件名即知何时/何集
    write_json(full_report, rdir / f"{snap}.json")
    if summary_md_path.exists():
        (rdir / f"{snap}.md").write_text(summary_md_path.read_text(encoding="utf-8"), encoding="utf-8")
    png = plot_final_report(
        full_report,
        score_rows,
        rdir / f"{snap}.png",
        dataset=args.dataset,
        run_id=run_id,
        generated_at=generated_at,
    )

    # ---- 论文级图表(独立于上面的自查仪表盘;整体兜底,画图失败不连累报告归档)----
    baseline_path = baseline_dir / f"{args.dataset}_baseline_comparison.jsonl"
    baseline_rows = list(read_jsonl(baseline_path)) if baseline_path.exists() else []
    try:
        paper_files = render_paper_figures(full_report, score_rows, baseline_rows, rdir, dataset=args.dataset)
    except Exception as exc:  # noqa: BLE001 - 论文图失败不应阻断报告主流程
        logger.warning("paper figures failed: %s", exc)
        paper_files = []

    metrics = full_report.get("main_attack_results", {})
    run_index_path = rdir.parent / "index.jsonl"
    write_jsonl(
        [{
            "run_id": run_id,
            "generated_at": generated_at,
            "kind": "final_report",
            "dataset": args.dataset,
            "scale": _read_scale(),
            "generator_family": generator_identity.generator_family,
            "concrete_model": generator_identity.concrete_model,
            "generator_version": generator_identity.generator_version,
            "retriever_id": retriever_id,
            "auc_pcv": metrics.get("AUC"),
            "oracle_tpr_at_1fpr": metrics.get("Oracle TPR@1%FPR"),
            "oracle_tpr_at_5fpr": metrics.get("Oracle TPR@5%FPR"),
            "calibrated_alpha_1": full_report.get("calibrated_attack_results", {}).get("alpha_0.01"),
        }],
        run_index_path,
        append=True,
    )
    hist = [r for r in read_jsonl(run_index_path) if r.get("kind") == "final_report"]
    trend = plot_run_trend(
        hist, run_index_path.parent / "trend_report.png", dataset=args.dataset
    )

    print(f"[归档] run_id={run_id}  生成时间={generated_at}")
    print(f"    报告(latest): {report_json_path}")
    print(f"    本次快照:     {rdir}")
    if png:
        print(f"    可视化图:     {png}")
    else:
        print("    可视化图:     (未生成 — 未安装 matplotlib)")
    if paper_files:
        print(f"    论文图:       {rdir / 'figures'}  ({len(paper_files)} 文件)")
    print(f"    历次总表:     {run_index_path}")
    if trend:
        print(f"    趋势图:       {trend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
