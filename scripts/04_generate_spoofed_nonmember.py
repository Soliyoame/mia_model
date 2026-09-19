"""04: 由 Spoof_Seed 生成 Spoofed_Non_Member。

中文说明
========
本文件对应流水线第 4 步:用 Spoof_Seed 子集做种子,借助"兄弟模型"(sibling)LLM 仿造出
一批以假乱真、但其实不在知识库里的"仿造非成员"(Spoofed_Non_Member),作为实验的对照组。
具体生成/筛选逻辑在 src.spoof.generator。这一步是可选的:默认关闭,只有把环境变量
PCV_ENABLE_SPOOFED_NONMEMBER 设为 true 才会执行,否则直接跳过并返回 0。
"""

from __future__ import annotations

# Spoofed_Non_Member is generated only as an experimental control group.

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.factory import build_sibling_client, load_llm_profiles, resolve_llm_profile_name
from src.rag.embeddings import DEFAULT_EMBEDDING_MODEL
from src.spoof.generator import generate_spoofed_nonmembers
from src.utils.dataset_paths import resolve_dataset_dir
from src.utils.env import env_bool
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、sibling_profile、force、no_resume 等字段。
    """
    parser = argparse.ArgumentParser(description="Generate Spoofed_Non_Member as a PCV-MIA control group.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "spoof_config.yaml"))
    # 指定用于仿造的兄弟模型 profile 名;不给则回落到配置里的 spoof.sibling_profile。
    parser.add_argument("--sibling-profile", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """流水线第 4 步入口:生成仿造非成员对照组(默认关闭)。

    返回:
        进程退出码;被环境变量关闭而跳过时也返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    # 仿造非成员是可选对照组:默认不跑,需在 .env 里显式打开开关才执行。
    if not env_bool("PCV_ENABLE_SPOOFED_NONMEMBER", default=False):
        logger.info("Skipping Spoofed_Non_Member control group. Set PCV_ENABLE_SPOOFED_NONMEMBER=true in .env to enable it.")
        return 0
    profiles = load_llm_profiles(config)
    # 确定兄弟模型用哪个 profile:命令行 > 配置 > 默认,统一由 resolve 决定。
    profile_name = resolve_llm_profile_name(
        "sibling",
        cli_profile=args.sibling_profile,
        config_profile=config["spoof"].get("sibling_profile"),
    )
    client, profile = build_sibling_client(profiles, profile_name=profile_name)
    split_dir = resolve_dataset_dir(config, "splits_dir", args.dataset)
    out_dir = ensure_dir(resolve_path(config["paths"]["spoofed_dir"]) / args.dataset)
    manifest = generate_spoofed_nonmembers(
        dataset=args.dataset,
        spoof_seed_path=split_dir / "spoof_seed.jsonl",
        # 同时给出 kb_member 是为了筛掉与真实成员过于相似的仿造,保证它们确为"非成员"。
        kb_member_path=split_dir / "kb_member.jsonl",
        output_path=out_dir / "spoofed_non_member.jsonl",
        manifest_path=out_dir / "spoof_manifest.json",
        client=client,
        # 每个种子先生成若干候选,经阈值筛选后最多保留 max_per_seed 条。
        candidates_per_seed=int(config["spoof"].get("candidates_per_seed", 3)),
        strategies=config["spoof"].get("strategies"),
        thresholds=config["spoof"].get("thresholds"),
        max_per_seed=int(config["spoof"].get("max_per_seed", 1)),
        embedding_model=str(config.get("statistics", {}).get("embedding_model", DEFAULT_EMBEDDING_MODEL)),
        resume=not args.no_resume,
        force=args.force,
        # 把实际用到的 sibling profile 一并存进快照,便于复现与追溯。
        config_snapshot={**config, "sibling_profile_used": profile},
    )
    logger.info("Step 04 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
