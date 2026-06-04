"""06: 从攻击基准中抽取可验证的事实单元(fact unit)。

中文说明
========
本文件对应流水线第 06 步:读入第 05 步产出的攻击基准 `{dataset}_attack_benchmark.jsonl`,
对每篇文档抽取若干"可被独立核验"的事实单元(谁、在何处、做了什么、数值多少等),
写到 `{dataset}_facts.jsonl`。这些事实单元是后续配对断言(第 07 步)的原材料。

具体抽取与打分逻辑都在 `src.fact_extraction.fact_extractor` 里,本脚本只负责:
读配置、设随机种子、把配置里的各项阈值(重要性 / 可替换性 / 隐私特异性等)传进去,
再把返回的 manifest 记到日志。输入是基准 jsonl,输出是事实单元 jsonl。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.fact_extraction.fact_extractor import extract_facts_file
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset(数据集名)、config(配置文件路径)、
        force(忽略已有产出强制重跑)、no_resume(关闭断点续跑)。
    """
    parser = argparse.ArgumentParser(description="Extract PCV-MIA fact units.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """脚本入口:抽取事实单元并写盘。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    fact_cfg = config.get("fact_extraction", {})
    # 产出目录不存在时自动创建。
    out_dir = ensure_dir(resolve_path(config["paths"]["facts_dir"]))
    manifest = extract_facts_file(
        benchmark_path=resolve_path(config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        output_path=out_dir / f"{args.dataset}_facts.jsonl",
        max_facts_per_doc=int(fact_cfg.get("max_facts_per_doc", 2)),
        max_entities_per_doc=int(fact_cfg.get("max_entities_per_doc", 8)),
        max_samples=fact_cfg.get("max_samples"),
        # 三个阈值用于过滤"不值得验证"的事实:重要性、可替换性、隐私特异性都要达标。
        min_importance=float(fact_cfg.get("min_importance", 0.6)),
        min_replaceability=float(fact_cfg.get("min_replaceability", 0.6)),
        min_privacy_specificity=float(fact_cfg.get("min_privacy_specificity", 0.5)),
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info("Step 06 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
