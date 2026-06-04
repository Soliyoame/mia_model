"""12: 跑各 baseline 接口,算出与 PCV-MIA 横向对照的指标。

中文说明
========
本文件对应流水线第 12 步「跑 baseline 对照」。读入第 11 步产出的 PCV 分数文件,交给
`src.baselines.runner.run_baselines`,对若干攻击方法(本项目方法、Direct RAG-MIA、IA
审问式攻击,以及一批暂时只预留接口的方法)各算一行指标(AUC、准确率、各 FPR 下检出率等),
统一写成 `{dataset}_baseline_results.jsonl`,方便最后填进论文对照表。

本脚本只负责读配置、设种子、拼输出路径并把判定阈值 threshold 传进去;指标计算与"已实现/
预留"的区分都在 runner 里。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.baselines.runner import run_baselines
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、force、no_resume。
    """
    parser = argparse.ArgumentParser(description="Run PCV-MIA baselines.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "baseline_config.yaml"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """脚本入口:跑 baseline 对照并写出结果 jsonl。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    out_dir = ensure_dir(resolve_path(config["paths"]["baselines_dir"]))
    manifest = run_baselines(
        dataset=args.dataset,
        scores_path=resolve_path(config["paths"]["scores_dir"]) / f"{args.dataset}_pcv_scores.jsonl",
        output_path=out_dir / f"{args.dataset}_baseline_results.jsonl",
        # 把分数转成成员/非成员判定时用的阈值,默认 0.5。
        threshold=float(config.get("baseline", {}).get("threshold", 0.5)),
        resume=not args.no_resume,
        force=args.force,
        # 整份配置作为快照写进 manifest,便于结果复现。
        config_snapshot=config,
    )
    logger.info("Step 12 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
