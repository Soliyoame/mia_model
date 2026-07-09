"""17: 从既有结果刷出论文级图表(可选步骤,不在 01~15 主序列)。

中文说明
========
本脚本把已经跑好的结果(报告 + 打分 + 基线对比)喂给 src.evaluation.paper_figures,产出**论文级**
单图(PDF 矢量 + 300dpi PNG)与一份可直接粘贴的 captions.md。它不在编号流水线里、也不注册进
run_pipeline 的 build_steps——论文图是按需产物,随时手动刷,不必重跑整条流水线。

读取(按数据集):
    outputs/reports/{ds}_final_report.json                    第 15 步的报告
    outputs/scores/{ds}_pcv_scores.jsonl                      第 11 步的打分行
    outputs/baselines/{ds}/{ds}_baseline_comparison.jsonl     第 12 步的基线对比(可选,缺则跳过基线图)

输出目录(优先级):
    1) --out-dir 显式指定;
    2) --run-id 指定 → outputs/runs/{ds}/{run_id}/;
    3) 环境变量 PCV_RUN_ID 已设(处在一条流水线内) → 同上;
    4) 都没有 → outputs/reports/(稳定位置,便于反复刷图,不刷一次建一个 run 目录)。
最终图都落在上述目录的 figures/ 子目录里。

真正的画图逻辑在 paper_figures.py,本脚本只装配路径与打印结果。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.paper_figures import render_paper_figures
from src.utils.io import read_json, read_jsonl, resolve_path
from src.utils.logger import setup_logging
from src.utils.run_context import current_run_id, model_scoped_dir, run_dir


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、run_id、out_dir、figures。
    """
    parser = argparse.ArgumentParser(description="Render publication-quality PCV-MIA figures from existing results.")
    parser.add_argument("--dataset", required=True, help="Dataset name, e.g. edgar / enron.")
    parser.add_argument("--run-id", default=None, help="Archive figures under this run id (outputs/runs/{ds}/{run_id}/).")
    parser.add_argument("--out-dir", default=None, help="Override output root; figures go to its figures/ subdir.")
    parser.add_argument("--figures", default=None, help="Comma list to render a subset, e.g. roc,signals,calibration.")
    return parser.parse_args()


def _resolve_out_dir(args: argparse.Namespace, dataset: str) -> Path:
    """按「--out-dir > --run-id > $PCV_RUN_ID > outputs/reports」的顺序决定输出根目录。"""
    if args.out_dir:
        return resolve_path(args.out_dir)
    if args.run_id and args.run_id.strip():
        return run_dir(dataset, args.run_id.strip())
    if os.environ.get("PCV_RUN_ID", "").strip():
        return run_dir(dataset, current_run_id())
    # 无 run 上下文:落到稳定的 reports/{数据集}/{模型}/ 目录,反复刷图不制造一堆 run 目录。
    return model_scoped_dir("outputs/reports", dataset)


def main() -> int:
    """脚本入口:装配三份输入 → 决定输出目录 → 调 render_paper_figures → 打印产物。

    返回:
        进程退出码:0 成功;1 缺报告或未产出任何图。
    """
    args = parse_args()
    logger = setup_logging("pcv_mia", log_file=resolve_path("datasets/logs/paper_figures.log"), level="INFO")
    ds = args.dataset

    report_path = model_scoped_dir("outputs/reports", ds) / f"{ds}_final_report.json"
    scores_path = model_scoped_dir("outputs/scores", ds) / f"{ds}_pcv_scores.jsonl"
    baseline_path = model_scoped_dir("outputs/baselines", ds) / f"{ds}_baseline_comparison.jsonl"

    if not report_path.exists():
        logger.error("report not found: %s", report_path)
        print(f"错误:找不到报告 {report_path}(请先跑第 15 步)。", file=sys.stderr)
        return 1

    report = read_json(report_path)
    score_rows = list(read_jsonl(scores_path)) if scores_path.exists() else []
    baseline_rows = list(read_jsonl(baseline_path)) if baseline_path.exists() else []
    if not score_rows:
        logger.warning("no score rows at %s; score-based figures will be skipped", scores_path)

    out_dir = _resolve_out_dir(args, ds)
    figures = [s.strip() for s in args.figures.split(",") if s.strip()] if args.figures else None
    produced = render_paper_figures(report, score_rows, baseline_rows, out_dir, dataset=ds, figures=figures)

    fig_dir = Path(out_dir) / "figures"
    if not produced:
        print("没有产出任何图(matplotlib 未安装?试试 pip install matplotlib)。", file=sys.stderr)
        return 1

    logger.info("Rendered %d files into %s", len(produced), fig_dir)
    print(f"[论文图] {fig_dir}")
    for p in produced:
        print(f"    - {Path(p).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
