"""01: 数据清洗与标准化。

中文说明
========
本文件对应流水线第 1 步:把各数据集的原始文件清洗成统一的 jsonl。具体读取/清洗/
切分/过滤的实现都在 src.data.preprocess 里,这里只负责命令行入口:读 data_config.yaml、
设随机种子、逐个数据集调用 preprocess_dataset,最后把每个数据集的统计写进
preprocess_manifest.json。输入是配置里各数据集的 input_path,输出是 processed_dir 下的
<dataset>.jsonl 以及一份 manifest。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.preprocess import preprocess_dataset
from src.utils.io import ensure_dir, load_yaml, resolve_path, write_json
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 config、datasets、force、no_resume 等字段。
    """
    parser = argparse.ArgumentParser(description="Preprocess local datasets for PCV-MIA.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "data_config.yaml"))
    # 不指定 --datasets 时默认处理配置里的全部数据集。
    parser.add_argument("--datasets", nargs="*", help="Datasets to process. Defaults to all configured datasets.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """流水线第 1 步入口:逐个数据集做预处理并落盘 manifest。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    # 先固定随机种子,保证清洗/采样这类带随机性的步骤可复现。
    set_seed_from_config(config)
    logger = setup_logging(
        "pcv_mia",
        log_file=resolve_path(config.get("logging", {}).get("file", "datasets/logs/preprocess.log")),
        level=config.get("logging", {}).get("level", "INFO"),
    )
    processed_dir = ensure_dir(resolve_path(config["paths"]["processed_dir"]))
    params = config.get("preprocess", {})
    # 未通过命令行指定时,处理配置中声明的全部数据集。
    dataset_names = args.datasets or list(config["datasets"].keys())
    stats = {}
    for dataset in dataset_names:
        ds_cfg = config["datasets"][dataset]
        # 逐个数据集清洗:正文长度/实体/数字等过滤参数都从 preprocess 配置段取,缺省给默认值。
        stats[dataset] = preprocess_dataset(
            dataset=dataset,
            input_path=resolve_path(ds_cfg["input_path"]),
            output_path=processed_dir / f"{dataset}.jsonl",
            min_chars=int(params.get("min_chars", 300)),
            max_chars=int(params.get("max_chars", 2000)),
            target_chars=int(params.get("target_chars", 1000)),
            limit=ds_cfg.get("limit"),
            require_entity=bool(params.get("require_entity", True)),
            require_numeric=bool(params.get("require_numeric", False)),
            min_entities=int(params.get("min_entities", 2)),
            resume=not args.no_resume,
            force=args.force,
        )
    write_json(stats, processed_dir / "preprocess_manifest.json")
    logger.info("Step 01 finished: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
