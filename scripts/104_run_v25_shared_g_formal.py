"""shared-G 正式评估入口：仅解析参数、编排阶段和调用模块。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.shared_g.artifacts import ArtifactStore
from src.shared_g.config import load_config
from src.shared_g.construction import generate, review_packet, save_review, save_assistant_adjudication
from src.shared_g.evaluation import report
from src.shared_g.queries import freeze
from src.shared_g.retrieval import retrieve
from src.shared_g.review import review_ai, review_all
from src.shared_g.sources import prepare
from src.shared_g.victim import run_victim, validate_cell_order


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/v25_shared_g_formal_semantic_review.yaml")
    stages = parser.add_subparsers(dest="stage", required=True)
    preparation = stages.add_parser("prepare", help="本地固定无标签候选顺序；不调用模型")
    preparation.add_argument("--dry-run", action="store_true")
    for name in ("generate", "review-ai", "retrieve", "run-initial", "run-followup"):
        stage = stages.add_parser(name)
        stage.add_argument("--dataset", required=True)
        stage.add_argument("--max-new", type=int, default=200)
    review = stages.add_parser("review-packet", help="输出无 membership 的 Assistant 预审材料")
    review.add_argument("--start", type=int, default=0)
    review.add_argument("--count", type=int, default=20)
    review.add_argument("--dataset")
    importing = stages.add_parser("review-import", help="合并绑定原始构造记录的 Assistant 盲预审决定")
    importing.add_argument("--input", required=True)
    stages.add_parser("freeze")
    stages.add_parser("review-all", help="顺序完成 AI 预审及拒绝后的按序补选；不调用 victim")
    reporting = stages.add_parser("report")
    reporting.add_argument("--dataset")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = load_config(args.config, ROOT)
    store = ArtifactStore(config)
    if args.stage == "prepare":
        result = prepare(config, store, args.dry_run)
    elif args.stage == "generate":
        result = generate(config, store, args.dataset, args.max_new)
    elif args.stage == "review-ai":
        result = review_ai(config, store, args.dataset, args.max_new)
    elif args.stage == "review-all":
        result = review_all(config, store)
    elif args.stage == "review-packet":
        result = review_packet(config, store, args.start, args.count, args.dataset)
    elif args.stage == "review-import":
        review = json.loads(Path(args.input).read_text(encoding="utf-8"))
        if review.get("reviewer_type") != "assistant_membership_blind":
            raise ValueError("assistant_membership_blind_review_required")
        if "assistant_adjudications" in review:
            if "decisions" in review:
                raise ValueError("separate_review_and_adjudication_import_required")
            result = save_assistant_adjudication(config, store, review["assistant_adjudications"])
        else:
            result = save_review(config, store, review["decisions"])
    elif args.stage == "freeze":
        result = freeze(config, store)
    elif args.stage == "retrieve":
        store.validate(frozen=True)
        validate_cell_order(config, store, args.dataset)
        result = retrieve(config, store, args.dataset, args.max_new)
    elif args.stage in ("run-initial", "run-followup"):
        result = run_victim(config, store, args.dataset, args.stage == "run-followup", args.max_new)
    else:
        result = report(config, store, args.dataset)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
