"""用一条命令依次跑完 PCV-MIA 的编号流水线脚本（总编排器）。

中文说明
========
本文件是整条 PCV-MIA 实验流水线的总入口/编排器。它本身不做具体计算，而是把
scripts/ 目录下 15 个编号脚本(01~15)按顺序拼成子进程命令逐个调起来，串成完整的
攻击实验流程:

    01 预处理数据 → 02 切分数据集 → 03 建 RAG 索引 → 04 生成可选的伪造非成员 →
    05 构建攻击基准 → 06 抽取事实 → 07 生成成对声明 → 08 生成成对查询 →
    09 过滤隐蔽查询 → 10 跑 RAG 与 LLM-only 生成 → 11 解析立场并打分 →
    12 跑基线 → 13 机制分析 → 14 跑防御 → 15 生成最终报告

每一步用 PipelineStep 描述(编号、配置键、脚本名、说明、命令行参数构造函数)，
再由 main() 依次拼成 `python scripts/NN_xxx.py ...` 子进程执行。

关键命令行参数:
    --dataset            数据集名;不传则取 experiment_config.yaml 里的 default_dataset。
    --from-step/--to-step  只跑某个连续步骤区间(1~15)。
    --only-steps/--skip-steps  逗号/区间列表，精确选跑或跳过某些步骤(如 2-9,11,15)。
    --force/--no-resume  透传给每个被选中的子步骤，控制强制重算/不续跑。
    --dry-run            只打印将要执行的命令而不真正运行，便于检查编排是否正确。
各步骤还可通过 experiment_config.yaml 的 pipeline 段按 key 开关启用/禁用。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.io import load_yaml
from src.utils.run_context import (
    archive_run,
    git_snapshot,
    new_run_id,
    read_scale,
    write_run_manifest,
)


StepArgsBuilder = Callable[[argparse.Namespace], list[str]]


@dataclass(frozen=True)
class PipelineStep:
    """描述流水线中的一个步骤。

    字段:
        number:      步骤编号(1~15)，对应脚本前缀。
        key:         在 experiment_config.yaml 的 pipeline 段里的开关键名。
        script:      scripts/ 目录下的脚本文件名。
        description: 简短中文/英文说明，用于运行时打印。
        build_args:  根据命令行参数构造该步骤子进程参数列表的函数。
    """
    number: int
    key: str
    script: str
    description: str
    build_args: StepArgsBuilder


def _config_arg(path: str) -> list[str]:
    """把一个配置文件路径包装成 `--config <path>` 参数对。"""
    return ["--config", path]


def _common_flags(args: argparse.Namespace) -> list[str]:
    """收集需要透传给每个子步骤的通用开关(--force / --no-resume)。

    参数:
        args: 解析后的命令行参数。
    返回:
        要追加到子进程命令尾部的开关列表。
    """
    flags: list[str] = []
    # --force/--no-resume 是全局意图，统一转发给每个被选中的步骤。
    if args.force:
        flags.append("--force")
    if args.no_resume:
        flags.append("--no-resume")
    return flags


def _dataset_args(args: argparse.Namespace, *extra: str) -> list[str]:
    """构造几乎每个步骤都需要的基础参数:`--dataset` + 额外参数 + 通用开关。

    参数:
        args:  解析后的命令行参数。
        extra: 该步骤特有的额外参数(如各自的 --config)。
    返回:
        完整的子进程参数列表。
    """
    return ["--dataset", args.dataset, *extra, *_common_flags(args)]


def build_steps() -> list[PipelineStep]:
    """声明整条流水线的全部步骤(01~15)及各自的参数构造方式。

    返回:
        按执行顺序排列的 PipelineStep 列表。
    """
    # 注意:每个步骤用 lambda 延迟构造参数，真正取值发生在 main() 拿到 args 之后。
    return [
        PipelineStep(
            1,
            "preprocess",
            "01_preprocess_data.py",
            "preprocess data",
            # 步骤 01 用的是 --datasets(复数)而非 --dataset，参数形态与其它步骤不同，故单独拼。
            lambda args: ["--config", args.data_config, "--datasets", args.dataset, *_common_flags(args)],
        ),
        PipelineStep(
            2,
            "split",
            "02_split_dataset.py",
            "split dataset",
            lambda args: _dataset_args(
                args,
                *_config_arg(args.data_config),
                # 仅当显式指定 --scale 时才透传给切分步骤(small/formal 规模)。
                *(["--scale", args.scale] if args.scale else []),
            ),
        ),
        PipelineStep(
            3,
            "build_rag_index",
            "03_build_rag_index.py",
            "build RAG index",
            lambda args: _dataset_args(args, *_config_arg(args.rag_config)),
        ),
        PipelineStep(
            4,
            "generate_spoofed_nonmember",
            "04_generate_spoofed_nonmember.py",
            "generate optional spoofed non-members",
            lambda args: _dataset_args(
                args,
                *_config_arg(args.spoof_config),
                # 仅当指定 --sibling-profile 时才透传(选用哪个"同源兄弟"画像来伪造非成员)。
                *(["--sibling-profile", args.sibling_profile] if args.sibling_profile else []),
            ),
        ),
        PipelineStep(
            5,
            "build_attack_benchmark",
            "05_build_attack_benchmark.py",
            "build attack benchmark",
            lambda args: _dataset_args(args, "--data-config", args.data_config),
        ),
        PipelineStep(
            6,
            "extract_facts",
            "06_extract_facts.py",
            "extract facts",
            lambda args: _dataset_args(args, *_config_arg(args.pcv_config)),
        ),
        PipelineStep(
            7,
            "generate_paired_claims",
            "07_generate_paired_claims.py",
            "generate paired claims",
            lambda args: _dataset_args(args, *_config_arg(args.pcv_config)),
        ),
        PipelineStep(
            8,
            "generate_paired_queries",
            "08_generate_paired_queries.py",
            "generate paired queries",
            lambda args: _dataset_args(args, *_config_arg(args.pcv_config)),
        ),
        PipelineStep(
            9,
            "filter_stealth_queries",
            "09_filter_stealth_queries.py",
            "filter stealth queries",
            lambda args: _dataset_args(args, *_config_arg(args.pcv_config)),
        ),
        PipelineStep(
            10,
            "run_rag_and_llm_only",
            "10_run_rag_and_llm_only.py",
            "run RAG and LLM-only generation",
            lambda args: _dataset_args(
                args,
                *_config_arg(args.rag_config),
                # 仅当指定 --victim-profile 时才透传(选用哪个受害者 LLM 画像来生成回答)。
                *(["--victim-profile", args.victim_profile] if args.victim_profile else []),
            ),
        ),
        PipelineStep(
            11,
            "parse_stance_and_score",
            "11_parse_stance_and_score.py",
            "parse stance and score",
            lambda args: _dataset_args(args, *_config_arg(args.pcv_config)),
        ),
        PipelineStep(
            12,
            "run_baselines",
            "12_run_baselines.py",
            "run baselines",
            lambda args: _dataset_args(args, *_config_arg(args.baseline_config)),
        ),
        PipelineStep(
            13,
            "mechanism_analysis",
            "13_mechanism_analysis.py",
            "run mechanism analysis",
            lambda args: _dataset_args(args),
        ),
        PipelineStep(
            14,
            "run_defenses",
            "14_run_defenses.py",
            "run defenses",
            lambda args: _dataset_args(args, *_config_arg(args.defense_config)),
        ),
        PipelineStep(
            15,
            "generate_report",
            "15_generate_report.py",
            "generate final report",
            lambda args: _dataset_args(
                args,
                # 仅当指定 --threshold 时才透传(报告里判定成员/非成员所用的打分阈值)。
                *(["--threshold", str(args.threshold)] if args.threshold is not None else []),
            ),
        ),
    ]


def parse_step_list(value: str) -> set[int]:
    """把 "2-9,11,15" 这类逗号/区间字符串解析成步骤编号集合。

    参数:
        value: 形如 "2-9,11,15" 的选择串(可含区间与单点)。
    返回:
        去重后的步骤编号集合;空串返回空集合。
    异常:
        argparse.ArgumentTypeError: 出现非法区间、非数字或超出 1~15 范围时抛出。
    """
    if not value.strip():
        return set()
    selected: set[int] = set()
    # 逐个逗号分段解析;每段要么是单个编号，要么是 "起-止" 区间。
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                # 区间写法:展开成闭区间 [start, end] 内的所有编号。
                start_text, end_text = part.split("-", 1)
                start = int(start_text)
                end = int(end_text)
                if start > end:
                    raise argparse.ArgumentTypeError(f"Invalid step range: {part}")
                selected.update(range(start, end + 1))
            else:
                selected.add(int(part))
        except ValueError as exc:
            # 段里出现非数字内容，转成 argparse 友好的错误。
            raise argparse.ArgumentTypeError(f"Invalid step selector: {part}") from exc
    # 统一校验:所有编号必须落在 1~15 之内。
    bad = sorted(step for step in selected if step < 1 or step > 15)
    if bad:
        raise argparse.ArgumentTypeError(f"Step numbers must be 1-15: {bad}")
    return selected


def parse_args() -> argparse.Namespace:
    """定义并解析本编排脚本的命令行参数。

    返回:
        解析后的 argparse.Namespace。
    """
    parser = argparse.ArgumentParser(description="Run PCV-MIA pipeline stages with one command.")
    parser.add_argument("--dataset", default=None, help="Dataset name. Defaults to configs/experiment_config.yaml.")
    parser.add_argument("--experiment-config", default=str(PROJECT_ROOT / "configs" / "experiment_config.yaml"))
    parser.add_argument("--from-step", type=int, default=1, choices=range(1, 16), metavar="N")
    parser.add_argument("--to-step", type=int, default=15, choices=range(1, 16), metavar="N")
    parser.add_argument("--only-steps", default="", help="Comma/range list, for example: 2-9,11,15.")
    parser.add_argument("--skip-steps", default="", help="Comma/range list to skip, for example: 4,10.")
    parser.add_argument("--scale", choices=["small", "formal"], default=None, help="Forwarded to step 02.")
    parser.add_argument("--victim-profile", default=None, help="Forwarded to step 10.")
    parser.add_argument("--sibling-profile", default=None, help="Forwarded to step 04.")
    parser.add_argument("--threshold", type=float, default=None, help="Forwarded to step 15.")
    parser.add_argument("--data-config", default=str(PROJECT_ROOT / "configs" / "data_config.yaml"))
    parser.add_argument("--rag-config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--pcv-config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--spoof-config", default=str(PROJECT_ROOT / "configs" / "spoof_config.yaml"))
    parser.add_argument("--baseline-config", default=str(PROJECT_ROOT / "configs" / "baseline_config.yaml"))
    parser.add_argument("--defense-config", default=str(PROJECT_ROOT / "configs" / "defense_config.yaml"))
    parser.add_argument("--force", action="store_true", help="Forward --force to every selected stage.")
    parser.add_argument("--no-resume", action="store_true", help="Forward --no-resume to every selected stage.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument(
        "--run-name",
        default=None,
        help="Optional human label appended to the start-time run id, e.g. 20260707-153012_baseline-fix.",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip collecting this run's products into outputs/runs/{dataset}/{run_id}/ at the end.",
    )
    return parser.parse_args()


def selected_steps(args: argparse.Namespace, experiment_config: dict) -> list[PipelineStep]:
    """根据命令行参数与配置，筛选出本次真正要执行的步骤序列。

    四重过滤叠加:--from-step/--to-step 区间、--only-steps 白名单、
    --skip-steps 黑名单，以及 experiment_config 里 pipeline 段对各 key 的开关。

    参数:
        args:              解析后的命令行参数。
        experiment_config: 实验总配置(其 pipeline 段可按 key 禁用步骤)。
    返回:
        按编号顺序排列、确定要跑的 PipelineStep 列表。
    异常:
        ValueError: --from-step 大于 --to-step 时抛出。
    """
    if args.from_step > args.to_step:
        raise ValueError("--from-step cannot be greater than --to-step")

    steps = build_steps()
    only = parse_step_list(args.only_steps)
    skip = parse_step_list(args.skip_steps)
    enabled = experiment_config.get("pipeline", {})

    selected: list[PipelineStep] = []
    for step in steps:
        # 是否落在 --from-step ~ --to-step 区间内。
        in_range = args.from_step <= step.number <= args.to_step
        # 未指定 --only-steps 时默认全选;指定后只保留白名单内的步骤。
        explicitly_selected = not only or step.number in only
        if not in_range or not explicitly_selected or step.number in skip:
            continue
        # 配置里把该步骤显式置为 False 才跳过;缺省视为启用。
        if enabled.get(step.key, True) is False:
            continue
        selected.append(step)
    return selected


def command_for_step(step: PipelineStep, args: argparse.Namespace) -> list[str]:
    """把单个步骤拼成可交给 subprocess 执行的完整命令。

    形如 `[python, scripts/NN_xxx.py, --dataset, ...]`，用当前解释器保证环境一致。

    参数:
        step: 要执行的步骤。
        args: 解析后的命令行参数。
    返回:
        子进程命令的参数列表。
    """
    return [sys.executable, str(PROJECT_ROOT / "scripts" / step.script), *step.build_args(args)]


def _archive_run_products(
    args: argparse.Namespace,
    steps: list[PipelineStep],
    executed: list[int],
    failed_step: int | None,
    run_id: str,
    started: datetime,
) -> None:
    """流水线收尾:把本次全部阶段产物拷进 run 文件夹,并写一份 run_manifest.json。

    --dry-run 或 --no-archive 时直接跳过。无论成功或失败都归档(失败在 manifest 里标注
    steps_failed),便于回看"这次到底跑出了什么"。归档中任何异常都不应连累流水线退出码,
    故整体兜底吞掉并仅告警。

    参数:
        args:        解析后的命令行参数。
        steps:       本次选中的步骤列表(用于记录 steps_selected)。
        executed:    已成功执行的步骤编号。
        failed_step: 首个失败的步骤编号;无失败为 None。
        run_id:      本次运行标识(即 run 文件夹名)。
        started:     流水线启动时刻(用于算耗时)。
    """
    if args.dry_run or args.no_archive:
        return
    finished = datetime.now()
    try:
        manifest: dict = {
            "run_id": run_id,
            "run_name": args.run_name or "",
            "dataset": args.dataset,
            "scale": read_scale(),
            "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": finished.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": round((finished - started).total_seconds(), 1),
            "steps_selected": [s.number for s in steps],
            "steps_run": executed,
            "steps_failed": failed_step,
            "victim_model": os.environ.get("PCV_VICTIM_MODEL", ""),
            "git": git_snapshot(),
            "configs": {
                "experiment": args.experiment_config,
                "data": args.data_config,
                "rag": args.rag_config,
                "pcv": args.pcv_config,
                "spoof": args.spoof_config,
                "baseline": args.baseline_config,
                "defense": args.defense_config,
            },
            "command": "python " + " ".join(sys.argv),
        }
        archive = archive_run(args.dataset, run_id)
        manifest["archive"] = archive
        write_run_manifest(args.dataset, run_id, manifest)
        megabytes = archive["bytes"] / (1024 * 1024)
        print(
            f"[归档] outputs/runs/{args.dataset}/{run_id}/"
            f"  ({archive['files']} 文件, {megabytes:.1f} MB)"
        )
    except Exception as exc:  # noqa: BLE001 - 归档失败不应连累流水线主流程
        print(f"[归档] 跳过(归档时出错,不影响流水线): {exc}", file=sys.stderr)


def main() -> int:
    """编排主流程:解析参数 → 选步骤 → 逐个调起子进程 → 任一步失败即中止。

    返回:
        进程退出码:0 成功;2 表示参数/选择非法;否则透传首个失败步骤的退出码。
    """
    args = parse_args()
    experiment_config = load_yaml(Path(args.experiment_config))
    # 未显式指定数据集时，回退到实验配置里的默认数据集(再兜底为 "enron")。
    args.dataset = args.dataset or str(experiment_config.get("default_dataset", "enron"))
    try:
        steps = selected_steps(args, experiment_config)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        # 参数或步骤选择非法:打印到 stderr 并以退出码 2 退出。
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not steps:
        # 过滤后无任何步骤可跑，视为正常空操作。
        print("No pipeline steps selected.")
        return 0

    print(f"Dataset: {args.dataset}")
    print("Selected steps: " + ", ".join(f"{step.number:02d}" for step in steps))

    # 启动即盖一个"开始时间"戳作为 run_id,并 export 给所有子步骤(subprocess 默认继承本进程
    # 环境)。末端脚本(15/可行性/L2)的 current_run_id() 届时读回同一个 id,整套产物归到同一
    # run 文件夹——这也一并修好了过去"各末端脚本各生成各自时间戳"的老问题。
    run_id = new_run_id(args.run_name)
    started = datetime.now()
    if not args.dry_run:
        os.environ["PCV_RUN_ID"] = run_id
    print(f"Run: {run_id}")

    executed: list[int] = []
    failed_step: int | None = None
    for step in steps:
        command = command_for_step(step, args)
        printable = " ".join(command)
        # 先回显本步骤说明与即将执行的完整命令，便于排查。
        print(f"\n[{step.number:02d}] {step.description}")
        print(printable)
        if args.dry_run:
            # --dry-run 只打印不执行，方便检查编排是否符合预期。
            continue
        # 在项目根目录下同步执行该步骤脚本。
        result = subprocess.run(command, cwd=PROJECT_ROOT)
        if result.returncode != 0:
            # 记录首个失败步骤并中止后续;失败也照常归档(便于回看半成品),退出码原样透传。
            print(f"Step {step.number:02d} failed with exit code {result.returncode}.")
            failed_step = step.number
            _archive_run_products(args, steps, executed, failed_step, run_id, started)
            return result.returncode
        executed.append(step.number)

    _archive_run_products(args, steps, executed, failed_step, run_id, started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
