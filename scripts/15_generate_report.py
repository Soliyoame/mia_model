"""15: 生成最终的 PCV-MIA JSON 与 Markdown 报告。

中文说明
========
本文件对应流水线第 15 步「出最终报告」,是整条流水线的收尾。它把前面各环节的产物汇到一起
——攻击基准、PCV 分数、隐蔽性筛选 manifest、索引 manifest、baseline 对照结果、机理分析
报告、防御实验结果——交给 `src.evaluation.report_builder.generate_final_report`,
产出两份东西:机器可读的 `{dataset}_final_report.json` 和人读的 `{dataset}_summary.md`。

本脚本只负责按约定目录拼好这一大堆输入路径、配好日志,并把判定阈值 threshold 传进去;
汇总与排版逻辑都在 report_builder 里。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.report_builder import generate_final_report
from src.utils.io import ensure_dir, resolve_path
from src.utils.logger import setup_logging


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、threshold、force、no_resume。
    """
    parser = argparse.ArgumentParser(description="Generate final PCV-MIA report.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """脚本入口:汇总各阶段产物,出 JSON 与 Markdown 两份最终报告。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    logger = setup_logging("pcv_mia", log_file=resolve_path("datasets/logs/report.log"), level="INFO")
    out_dir = ensure_dir(resolve_path("outputs/reports"))
    report = generate_final_report(
        dataset=args.dataset,
        benchmark_path=resolve_path("datasets/benchmarks") / f"{args.dataset}_attack_benchmark.jsonl",
        scores_path=resolve_path("outputs/scores") / f"{args.dataset}_pcv_scores.jsonl",
        stealth_manifest_path=resolve_path("outputs/stealth_filtered_queries") / f"{args.dataset}_paired_queries.manifest.json",
        index_manifest_path=resolve_path("indexes") / args.dataset / "index_manifest.json",
        baseline_path=resolve_path("outputs/baselines") / f"{args.dataset}_baseline_results.jsonl",
        mechanism_path=resolve_path("outputs/mechanisms") / f"{args.dataset}_mechanism_report.json",
        defense_path=resolve_path("outputs/defenses") / f"{args.dataset}_defense_results.json",
        report_json_path=out_dir / f"{args.dataset}_final_report.json",
        summary_md_path=out_dir / f"{args.dataset}_summary.md",
        threshold=args.threshold,
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info("Step 15 finished: %s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
