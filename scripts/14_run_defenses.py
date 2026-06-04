"""14: 跑 PCV-MIA 防御实验骨架。

中文说明
========
本文件对应流水线第 14 步「防御实验」。读入第 11 步产出的 PCV 分数,交给
`src.defenses.runner.run_defense_experiments`,在不同防御设定下重新评估攻击效果,
看防御措施能把攻击的检出能力压低到什么程度,产出 `{dataset}_defense_results.json`。
目前是实验骨架,把接口和输出结构先搭好、日后逐步填实防御策略。

本脚本只负责读配置、设种子、拼输出路径并把判定阈值 threshold 传进去。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.defenses.runner import run_defense_experiments
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、force、no_resume。
    """
    parser = argparse.ArgumentParser(description="Run PCV-MIA defense experiments.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "defense_config.yaml"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """脚本入口:在各防御设定下重评攻击效果并写盘。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    out_dir = ensure_dir(resolve_path(config["paths"]["defenses_dir"]))
    report = run_defense_experiments(
        dataset=args.dataset,
        scores_path=resolve_path(config["paths"]["scores_dir"]) / f"{args.dataset}_pcv_scores.jsonl",
        output_path=out_dir / f"{args.dataset}_defense_results.json",
        # 判定成员/非成员的阈值,默认 0.5。
        threshold=float(config.get("defense", {}).get("threshold", 0.5)),
        resume=not args.no_resume,
        force=args.force,
        # 整份配置作为快照写进结果,便于复现。
        config_snapshot=config,
    )
    logger.info("Step 14 finished: %s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
