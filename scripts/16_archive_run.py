"""16: 手动把当前工作区的实验产物快照到一个按时间命名的 run 文件夹(可选步骤)。

中文说明
========
本脚本是流水线自动归档(见 run_pipeline.py 收尾处)的手动版补充,不在 01~15 主序列里,
也不注册进 run_pipeline 的 build_steps,以免与末尾自动归档重复触发。

用途:当你按阶段手动迭代(比如只反复重跑第 11 步打分、或单独跑基线),对某一版结果满意
后,想立刻把当前各阶段目录里属于该数据集的全部产物收进
    outputs/runs/{dataset}/{run_id}/
做成一个自包含、按时间命名的存档,并附一份 run_manifest.json(数据集/规模/时间/git/清单)。

run_id 的确定顺序:
    1) 命令行 --run-id 显式给定则用之;
    2) 否则若环境变量 PCV_RUN_ID 已设置(例如正处在一条流水线内)则复用它;
    3) 都没有则用当前时间现生成 YYYYMMDD-HHMMSS(可用 --run-name 追加人类标签)。

真正的拷贝与清单逻辑都在 src.utils.run_context 里,本脚本只负责装配参数与打印结果。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.io import read_json, resolve_path
from src.utils.logger import setup_logging
from src.utils.run_context import (
    CANONICAL_RUN_ROLES,
    P0_PROTOCOL,
    RUN_STATUSES,
    archive_run,
    benchmark_snapshot,
    canonical_eligibility,
    current_run_id,
    git_snapshot,
    local_timestamp,
    new_run_id,
    read_scale,
    register_canonical_run,
    run_dir,
    victim_model_slug,
    write_run_manifest,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、run_id、run_name。
    """
    parser = argparse.ArgumentParser(
        description="Snapshot current workspace products into outputs/runs/{dataset}/{run_id}/."
    )
    parser.add_argument("--dataset", required=True, help="Dataset name, e.g. edgar / enron.")
    parser.add_argument(
        "--run-id",
        default=None,
        help="Explicit run id (folder name). Defaults to $PCV_RUN_ID, else a fresh start-time stamp.",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Optional human label appended when a fresh run id is generated.",
    )
    parser.add_argument(
        "--status",
        choices=tuple(status for status in RUN_STATUSES if status in {"candidate", "canonical", "legacy_feasibility"}),
        default="candidate",
        help="归档状态；canonical 必须同时提供 --suite-id 并通过门禁。",
    )
    parser.add_argument(
        "--suite-id",
        default=None,
        help="canonical suite 标识；仅 --status canonical 时使用。",
    )
    parser.add_argument("--run-role", choices=CANONICAL_RUN_ROLES, default="main")
    return parser.parse_args()


def _resolve_run_id(args: argparse.Namespace) -> str:
    """按"显式 --run-id > 环境变量 PCV_RUN_ID > 现生成时间戳"的顺序确定 run_id。"""
    if args.run_id and args.run_id.strip():
        return args.run_id.strip()
    if os.environ.get("PCV_RUN_ID", "").strip():
        # 复用流水线广播的 id(current_run_id 会读回该环境变量)。
        return current_run_id()
    return new_run_id(args.run_name)


def main() -> int:
    """脚本入口:确定 run_id → 归档各阶段产物 → 写 run_manifest.json → 打印结果。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    logger = setup_logging("pcv_mia", log_file=resolve_path("datasets/logs/archive.log"), level="INFO")
    run_id = _resolve_run_id(args)
    model = victim_model_slug()
    root = run_dir(args.dataset, run_id, model=model)

    # canonical 不是重新抓取“当前工作区 latest”的别名，而是对一个既有 pipeline candidate
    # 做显式晋升；这样 suite 永远绑定到当时已归档且可审计的那次运行。
    if args.status == "canonical":
        if not args.suite_id:
            raise ValueError("--status canonical requires --suite-id")
        existing_path = root / "run_manifest.json"
        if not existing_path.exists():
            raise FileNotFoundError(f"Candidate manifest not found: {existing_path}")
        manifest = read_json(existing_path)
        preregistered_suite = str((manifest.get("preregistration") or {}).get("suite_id") or "")
        if preregistered_suite != args.suite_id:
            raise ValueError(
                f"Suite id {args.suite_id} does not match preregistration {preregistered_suite}"
            )
        if str(manifest.get("run_role") or "main") != args.run_role:
            raise ValueError(
                f"Run role {args.run_role} does not match manifest {manifest.get('run_role')}"
            )
        eligibility = canonical_eligibility(manifest, root)
        manifest["canonical_eligibility"] = eligibility
        if not eligibility["eligible"]:
            write_run_manifest(args.dataset, run_id, manifest, model=model)
            print(f"[晋升] candidate 未通过 canonical 门禁: {', '.join(eligibility['reasons'])}")
            print(f"    清单: {existing_path}")
            return 2
        manifest["status"] = "canonical"
        manifest["suite_id"] = args.suite_id
        manifest["promoted_at"] = local_timestamp()
        manifest_path = write_run_manifest(args.dataset, run_id, manifest, model=model)
        try:
            suite_path = register_canonical_run(args.suite_id, manifest, manifest_path)
        except Exception:
            manifest["status"] = "candidate"
            manifest.pop("suite_id", None)
            manifest.pop("promoted_at", None)
            write_run_manifest(args.dataset, run_id, manifest, model=model)
            raise
        print(f"[晋升] canonical: {manifest_path}")
        print(f"    suite: {suite_path}")
        return 0

    archive = archive_run(args.dataset, run_id, model=model)
    manifest = {
        "run_id": run_id,
        "run_name": args.run_name or "",
        "dataset": args.dataset,
        "scale": read_scale(),
        "archived_at": local_timestamp(),
        "source": "manual (16_archive_run.py)",
        "status": args.status,
        "protocol": P0_PROTOCOL,
        "run_role": args.run_role,
        "victim_model": os.environ.get("PCV_VICTIM_MODEL", "") or model,
        "benchmark": benchmark_snapshot(args.dataset),
        "git": git_snapshot(),
        "archive": archive,
    }
    eligibility = canonical_eligibility(manifest, root)
    manifest["canonical_eligibility"] = eligibility
    manifest_path = write_run_manifest(args.dataset, run_id, manifest, model=model)

    megabytes = archive["bytes"] / (1024 * 1024)
    logger.info(
        "Archived %d files (%.1f MB) into outputs/runs/%s/%s/%s/",
        archive["files"],
        megabytes,
        args.dataset,
        model,
        run_id,
    )
    print(f"[归档] outputs/runs/{args.dataset}/{model}/{run_id}/  ({archive['files']} 文件, {megabytes:.1f} MB)")
    print(f"    清单: {manifest_path}")
    print(f"    状态: {manifest['status']}")
    for stage, count in archive["by_stage"].items():
        print(f"    - {stage}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
