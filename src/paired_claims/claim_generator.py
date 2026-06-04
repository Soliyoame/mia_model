"""Generate paired true and counterfactual claims for PCV-MIA.

中文说明
========
本文件对应流水线第 07 步「生成成对声明」。它读入上一步抽出的"事实"，为每条事实造出
一对声明：
    - 真实声明(true_claim)：就是原文里的那句事实(与文档一致)。
    - 反事实声明(counterfactual_claim)：把句子里的关键实体替换成"同类型假值"
      (替换逻辑来自 attack.perturbation_generator)，得到一句"看起来很像真的、其实是
      错的"声明。
这一对声明就是后面去问模型、用来判断"它是不是真懂这份文档"的探针。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    # 进度条;没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..attack.perturbation_generator import perturb_entity_value
from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def _replace_once(text: str, old: str, new: str) -> str:
    """把 text 里的 old【只替换第一次出现】为 new;old 为空或不存在则原样返回。

    用"只替换一次"是为了精准替换事实里的那个实体,避免误伤句中其它相同字样。
    """
    if not old or old not in text:
        return text
    return text.replace(old, new, 1)


def generate_paired_claims_file(
    facts_path: str | Path,
    output_path: str | Path,
    perturbation_levels: list[str] | None = None,
    max_pairs_per_fact: int = 1,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Generate one or more true/counterfactual claim pairs per fact.

    中文说明：第 07 步主入口。对每条事实，按指定的扰动强度生成若干对(真实/反事实)声明。
    会跳过那些"实体不在声明里"或"扰动后没产生变化"的异常情况，并记录到错误文件。

    参数:
        facts_path:          上一步产出的事实文件。
        output_path:         成对声明输出路径(并派生 .manifest/.errors)。
        perturbation_levels: 扰动强度列表(如 ["light"]、["light","medium"])。
        max_pairs_per_fact:  每条事实最多造几对声明。
        resume:              断点续跑:产物已存在则跳过。
        force:               强制重跑。
    返回:
        manifest(字典):声明对数量与分布统计;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    error_path = output.with_suffix(".errors.jsonl")
    # 断点续跑。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing paired claims: %s", output)
        return {"output_path": str(output), "skipped_existing": True}

    # 默认只用 light 强度。
    levels = perturbation_levels or ["light"]
    pairs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_group: Counter[str] = Counter()
    by_type: Counter[str] = Counter()

    for fact in tqdm(read_jsonl(facts_path), desc="paired claims", unit="fact"):
        made = 0
        original = str(fact.get("object_entity") or "")        # 真实实体
        # 真实声明:优先用 factual_claim,没有就用支撑句。
        true_claim = str(fact.get("factual_claim") or fact.get("supporting_sentence") or "")
        entity_type = str(fact.get("entity_type") or "")
        # 真实实体必须确实出现在真实声明里,否则没法做替换。
        if not original or original not in true_claim:
            errors.append({"fact_id": fact.get("fact_id"), "error": "original_entity_not_in_claim"})
            continue
        for level in levels:
            # 凑够这条事实的对数就停。
            if made >= max_pairs_per_fact:
                break
            # 生成同类型的假值。
            counterfactual = perturb_entity_value(original, entity_type, level=level)
            # 扰动没产生变化(假值=真值)就跳过并记录。
            if not counterfactual or counterfactual == original:
                errors.append({"fact_id": fact.get("fact_id"), "error": "counterfactual_unchanged", "level": level})
                continue
            # 把真实声明里的真实实体替换成假值,得到反事实声明。
            counterfactual_claim = _replace_once(true_claim, original, counterfactual)
            # 替换若没生效(声明没变),也跳过并记录。
            if counterfactual_claim == true_claim:
                errors.append({"fact_id": fact.get("fact_id"), "error": "claim_replacement_failed", "level": level})
                continue
            # 组装这一对声明。
            pair_id = f"pair_{fact['audit_id']}_{len(pairs):06d}"
            pairs.append(
                {
                    "pair_id": pair_id,
                    "fact_id": fact["fact_id"],
                    "audit_id": fact["audit_id"],
                    "doc_id": fact.get("doc_id"),
                    "dataset": fact["dataset"],
                    "group": fact["group"],
                    "true_claim": true_claim,
                    "counterfactual_claim": counterfactual_claim,
                    "original_entity": original,
                    "counterfactual_entity": counterfactual,
                    "entity_type": entity_type,
                    "perturbation_level": level,
                    "subject": fact.get("subject"),
                    "relation": fact.get("relation"),
                    "context": fact.get("context"),
                }
            )
            made += 1
            by_group[str(fact["group"])] += 1
            by_type[entity_type] += 1

    write_jsonl(pairs, output)
    write_jsonl(errors, error_path)
    manifest = {
        "output_path": str(output),
        "error_path": str(error_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pairs": len(pairs),
        "errors": len(errors),
        "pairs_by_group": dict(by_group),
        "pairs_by_entity_type": dict(by_type),
        "perturbation_levels": levels,
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Generated paired claims: pairs=%s errors=%s", len(pairs), len(errors))
    return manifest
