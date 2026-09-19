"""17: 从既有结果刷出论文级图表(可选步骤,不在 01~15 主序列)。

中文说明
========
本脚本把已经跑好的结果(报告 + 打分 + 基线对比)喂给 src.evaluation.paper_figures,产出**论文级**
单图(PDF 矢量 + 300dpi PNG)与一份可直接粘贴的 captions.md。它不在编号流水线里、也不注册进
run_pipeline 的 build_steps——论文图是按需产物,随时手动刷,不必重跑整条流水线。

读取(按数据集):
    outputs/reports/{ds}_final_report.json                    第 15 步的报告
    outputs/scores/{ds}/{model}/{ds}_pcv_scores_source_scores.jsonl  第 11 步的 source 主分
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
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.paper_figures import render_paper_figures
from src.utils.io import read_json, read_jsonl, resolve_path
from src.utils.logger import setup_logging
from src.utils.run_context import model_scoped_dir, resolve_suite_run, victim_model_slug


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、run_id、out_dir、figures。
    """
    parser = argparse.ArgumentParser(description="Render publication-quality PCV-MIA figures from existing results.")
    parser.add_argument("--dataset", required=True, help="Dataset name, e.g. edgar / enron.")
    parser.add_argument("--suite-id", default=None, help="显式 canonical suite id；正式论文图必须使用。")
    parser.add_argument("--run-role", default="main", help="Suite 内的 run role，默认 main。")
    parser.add_argument("--run-id", default=None, help="显式归档 run id；输入和输出都绑定该 run。")
    parser.add_argument("--model", default=None, help="与 --run-id 配合使用的模型目录 slug。")
    parser.add_argument("--workspace", action="store_true", help="显式允许读取可覆盖工作区，仅用于诊断。")
    parser.add_argument("--out-dir", default=None, help="Override output root; figures go to its figures/ subdir.")
    parser.add_argument("--figures", default=None, help="Comma list to render a subset, e.g. roc,signals,baselines.")
    return parser.parse_args()


def _resolve_run_root(args: argparse.Namespace, dataset: str) -> Path | None:
    """解析显式 suite/run 输入；绝不按修改时间或 glob 选择 latest。"""
    selectors = int(bool(args.suite_id)) + int(bool(args.run_id)) + int(bool(args.workspace))
    if selectors != 1:
        raise ValueError("Exactly one of --suite-id, --run-id, or --workspace is required")
    if args.suite_id:
        root, _, _ = resolve_suite_run(args.suite_id, dataset=dataset, run_role=args.run_role)
        return root
    if args.run_id:
        model = args.model or victim_model_slug()
        root = resolve_path("outputs/runs") / dataset / model / args.run_id
        if not root.is_dir():
            raise FileNotFoundError(f"Run directory not found: {root}")
        return root
    return None


def _resolve_out_dir(args: argparse.Namespace, dataset: str, run_root: Path | None) -> Path:
    """正式 suite 图写入 release；候选 run/诊断工作区写入各自显式目录。"""
    if args.out_dir:
        return resolve_path(args.out_dir)
    if args.suite_id:
        return resolve_path("outputs/releases") / args.suite_id / dataset
    if run_root is not None:
        return run_root
    return model_scoped_dir("outputs/reports", dataset)


def main() -> int:
    """脚本入口:装配三份输入 → 决定输出目录 → 调 render_paper_figures → 打印产物。

    返回:
        进程退出码:0 成功;1 缺报告或未产出任何图。
    """
    args = parse_args()
    logger = setup_logging("pcv_mia", log_file=resolve_path("datasets/logs/paper_figures.log"), level="INFO")
    ds = args.dataset

    try:
        run_root = _resolve_run_root(args, ds)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if run_root is None:
        report_path = model_scoped_dir("outputs/reports", ds) / f"{ds}_final_report.json"
        scores_path = model_scoped_dir("outputs/scores", ds) / f"{ds}_pcv_scores_source_scores.jsonl"
        baseline_path = model_scoped_dir("outputs/baselines", ds) / f"{ds}_baseline_comparison.jsonl"
    else:
        report_path = run_root / "reports" / f"{ds}_final_report.json"
        scores_path = run_root / "scores" / f"{ds}_pcv_scores_source_scores.jsonl"
        baseline_path = run_root / "baselines" / f"{ds}_baseline_comparison.jsonl"

    if not report_path.exists():
        logger.error("report not found: %s", report_path)
        print(f"错误:找不到报告 {report_path}(请先跑第 15 步)。", file=sys.stderr)
        return 1

    report = read_json(report_path)
    if not scores_path.exists():
        logger.error("source-level scores not found: %s", scores_path)
        print(f"错误:找不到 source-level 分数 {scores_path}(请强制重跑第 11 步)。", file=sys.stderr)
        return 1
    score_rows = list(read_jsonl(scores_path))
    baseline_rows = list(read_jsonl(baseline_path)) if baseline_path.exists() else []
    if not score_rows:
        logger.warning("no score rows at %s; score-based figures will be skipped", scores_path)

    out_dir = _resolve_out_dir(args, ds, run_root)
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
