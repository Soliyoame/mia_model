"""05: 构建 Attack Benchmark。

中文说明
========
本文件对应流水线第 5 步:把前面准备好的子集拼成一份固定不变的攻击基准(attack benchmark)。
它合并 KB_Member(标签为成员)与 True_Non_Member(标签为非成员),若开关打开还会并入第 4 步
的 Spoofed_Non_Member 对照组,统一打标签后写成一份 jsonl,供后续所有攻击/评测步骤共用。
具体构建逻辑在 src.prepare.benchmark_builder,这里只做命令行入口。输出落在
datasets/benchmarks 下,并附带哈希与 benchmark manifest 以保证基准可固定、可追溯。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.benchmark_builder import build_pcv_attack_benchmark
from src.utils.env import env_bool
from src.utils.io import ensure_dir, load_yaml, read_json, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、data_config、force、no_resume 等字段。
    """
    parser = argparse.ArgumentParser(description="Build PCV-MIA attack benchmark.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--data-config", default=str(PROJECT_ROOT / "configs" / "data_config.yaml"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """流水线第 5 步入口:合并子集、打标签,生成固定的攻击基准。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.data_config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    split_dir = resolve_path(config["paths"]["splits_dir"]) / args.dataset
    spoofed_dir = resolve_path("datasets/spoofed") / args.dataset
    out_dir = ensure_dir(resolve_path("datasets/benchmarks"))
    split_manifest = read_json(split_dir / "split_manifest.json")
    # 是否并入仿造非成员对照组,与第 4 步同一个开关保持一致。
    include_spoofed = env_bool("PCV_ENABLE_SPOOFED_NONMEMBER", default=False)
    # 是否并入 Reserve 校准组(L1 群体校准的零分布来源),默认开启;评估时会被排除。
    include_reserve = env_bool("PCV_ENABLE_RESERVE_CALIBRATION", default=True)
    manifest = build_pcv_attack_benchmark(
        dataset=args.dataset,
        kb_member_path=split_dir / "kb_member.jsonl",
        true_non_member_path=split_dir / "true_non_member.jsonl",
        spoofed_non_member_path=spoofed_dir / "spoofed_non_member.jsonl",
        include_spoofed_nonmember=include_spoofed,
        reserve_path=split_dir / "reserve.jsonl",
        include_reserve=include_reserve,
        output_path=out_dir / f"{args.dataset}_attack_benchmark.jsonl",
        config_snapshot=config,
        # 透传切分时的随机种子,把基准和它依赖的切分关联起来,便于追溯。
        split_seed=split_manifest.get("seed"),
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info("Step 05 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
