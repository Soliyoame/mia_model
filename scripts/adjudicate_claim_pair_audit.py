"""生成 claim pair 的独立 AI 辅助裁决产物。

该脚本不会修改正式 A/B 标注文件，也不会把 AI 判断写成人类标签。它把逐条复核中
确认的失败样本编码为可重放决策，其余样本在完整阅读后标为通过，并保留原始人工标签
作为来源证据。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.hash import sha256_file  # noqa: E402
from src.utils.io import ensure_dir, read_jsonl, resolve_path, write_json, write_jsonl  # noqa: E402


DATASETS = ("edgar", "enron", "pubmed")
MACHINE_FIELDS = (
    "audit_id",
    "dataset",
    "source_key",
    "entity_type",
    "original_entity",
    "counterfactual_entity",
    "true_claim",
    "counterfactual_claim",
)
HUMAN_FIELDS = ("human_pair_valid", "human_failure_reason", "audit_notes")
PROTOCOL_VERSION = "v19_ai_adjudication_2026-07-23"


def _ids(value: str) -> tuple[str, ...]:
    """把便于审阅的空白分隔 ID 块转换为不可变序列。"""

    return tuple(item for item in value.split() if item)


# 每个 ID 只出现一次，使用最主要、最容易复核的失败原因。
FAILURE_GROUPS: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "edgar": (
        (
            "entity_type_or_boundary_error",
            "实体在当前语境中的类型错误，或 span 只是更长实体、编号、金额、项目名的一部分。",
            _ids(
                """
                pair_edgar_audit_017379_040881
                pair_edgar_audit_021737_051459
                pair_edgar_audit_041925_098720
                pair_edgar_audit_048206_113359
                pair_edgar_audit_053175_125147
                pair_edgar_audit_066149_155633
                pair_edgar_audit_068149_160366
                pair_edgar_audit_002301_005310
                pair_edgar_audit_056943_134319
                pair_edgar_audit_076250_179436
                pair_edgar_audit_008300_019441
                pair_edgar_audit_073682_173450
                pair_edgar_audit_075002_176333
                pair_edgar_audit_026632_062717
                pair_edgar_audit_067697_159379
                pair_edgar_audit_000633_001561
                pair_edgar_audit_008016_018821
                pair_edgar_audit_010136_023822
                pair_edgar_audit_027995_065744
                pair_edgar_audit_028445_066644
                pair_edgar_audit_035704_083752
                pair_edgar_audit_050838_119641
                pair_edgar_audit_053011_124782
                pair_edgar_audit_056194_132562
                pair_edgar_audit_065728_154563
                pair_edgar_audit_071300_167897
                pair_edgar_audit_076213_179342
                pair_edgar_audit_077886_183321
                pair_edgar_audit_001092_002572
                pair_edgar_audit_004345_010178
                pair_edgar_audit_006999_016374
                pair_edgar_audit_015603_036931
                pair_edgar_audit_039633_093002
                pair_edgar_audit_044407_104629
                pair_edgar_audit_052565_123747
                pair_edgar_audit_056608_133596
                pair_edgar_audit_070764_166669
                pair_edgar_audit_073796_173673
                pair_edgar_audit_074097_174367
                pair_edgar_audit_076617_180402
                pair_edgar_audit_008936_020944
                pair_edgar_audit_014612_034551
                pair_edgar_audit_014918_035339
                pair_edgar_audit_022216_052414
                pair_edgar_audit_032008_074985
                pair_edgar_audit_051560_121358
                pair_edgar_audit_052312_123100
                pair_edgar_audit_052898_124547
                pair_edgar_audit_061861_145765
                pair_edgar_audit_069762_164103
                pair_edgar_audit_072702_171211
                pair_edgar_audit_076757_180672
                pair_edgar_audit_077683_182878
                pair_edgar_audit_004566_010695
                pair_edgar_audit_044649_105252
                pair_edgar_audit_004687_010969
                pair_edgar_audit_012556_029665
                pair_edgar_audit_044110_103943
                pair_edgar_audit_064056_150582
                pair_edgar_audit_066991_157684
                pair_edgar_audit_023265_054748
                pair_edgar_audit_038189_089715
                pair_edgar_audit_056509_133356
                pair_edgar_audit_066549_156625
                pair_edgar_audit_067274_158356
                """
            ),
        ),
        (
            "claim_fragment_or_truncation",
            "声明是句中残片、表格残片，或在缩写、金额、机构名等位置明显截断。",
            _ids(
                """
                pair_edgar_audit_030729_072113
                pair_edgar_audit_058013_136636
                pair_edgar_audit_069023_162330
                pair_edgar_audit_006492_015234
                pair_edgar_audit_010315_024180
                pair_edgar_audit_024698_058172
                pair_edgar_audit_067870_159674
                pair_edgar_audit_071002_167176
                pair_edgar_audit_066755_157046
                pair_edgar_audit_017777_041820
                pair_edgar_audit_029730_069703
                pair_edgar_audit_054942_129414
                pair_edgar_audit_060970_143606
                pair_edgar_audit_067018_157740
                pair_edgar_audit_021669_051299
                pair_edgar_audit_052782_124271
                pair_edgar_audit_023600_055500
                pair_edgar_audit_025423_059944
                pair_edgar_audit_032575_076172
                pair_edgar_audit_033164_077741
                pair_edgar_audit_050426_118725
                pair_edgar_audit_061272_144299
                pair_edgar_audit_069614_163698
                pair_edgar_audit_031205_073257
                pair_edgar_audit_039241_092034
                pair_edgar_audit_067630_159247
                pair_edgar_audit_021174_050170
                pair_edgar_audit_024308_057198
                pair_edgar_audit_031088_072981
                pair_edgar_audit_046348_109170
                pair_edgar_audit_069328_163056
                pair_edgar_audit_074895_176089
                pair_edgar_audit_076541_180170
                pair_edgar_audit_005115_012046
                """
            ),
        ),
        (
            "abnormal_structure_or_artifact",
            "声明含不成对引号或其他明显异常结构，不适合作为完整 claim。",
            _ids("pair_edgar_audit_044891_105738"),
        ),
    ),
    "enron": (
        (
            "entity_type_or_boundary_error",
            "实体在当前语境中的类型错误，或 span 只是地名、机构名、编号、范围的一部分。",
            _ids(
                """
                pair_enron_audit_003448_006514
                pair_enron_audit_005999_011528
                pair_enron_audit_006740_012884
                pair_enron_audit_003252_006108
                pair_enron_audit_000270_000468
                pair_enron_audit_001025_001864
                pair_enron_audit_004987_009541
                pair_enron_audit_005372_010364
                pair_enron_audit_005409_010454
                pair_enron_audit_005459_010576
                pair_enron_audit_006291_012165
                pair_enron_audit_001202_002265
                pair_enron_audit_003028_005701
                pair_enron_audit_005477_010606
                pair_enron_audit_005829_011242
                pair_enron_audit_006336_012259
                pair_enron_audit_006746_012903
                pair_enron_audit_003409_006457
                pair_enron_audit_003890_007422
                pair_enron_audit_001773_003358
                pair_enron_audit_000924_001702
                pair_enron_audit_005736_011074
                pair_enron_audit_005858_011297
                pair_enron_audit_001142_002150
                """
            ),
        ),
        (
            "claim_fragment_or_truncation",
            "声明是标题、列表或句中残片，或在日期、域名、缩写、数字等位置明显截断。",
            _ids(
                """
                pair_enron_audit_001650_003126
                pair_enron_audit_001792_003390
                pair_enron_audit_002564_004711
                pair_enron_audit_003516_006640
                pair_enron_audit_004676_008887
                pair_enron_audit_006498_012533
                pair_enron_audit_000122_000202
                pair_enron_audit_000390_000686
                pair_enron_audit_002819_005292
                pair_enron_audit_004843_009263
                pair_enron_audit_005331_010236
                pair_enron_audit_000373_000652
                pair_enron_audit_002295_004305
                pair_enron_audit_002954_005526
                pair_enron_audit_003866_007387
                pair_enron_audit_006048_011625
                pair_enron_audit_006657_012741
                pair_enron_audit_002172_004098
                pair_enron_audit_000589_001045
                pair_enron_audit_001469_002766
                pair_enron_audit_003831_007309
                pair_enron_audit_005389_010398
                pair_enron_audit_006444_012485
                pair_enron_audit_006714_012828
                pair_enron_audit_000275_000479
                pair_enron_audit_001002_001821
                pair_enron_audit_002628_004814
                pair_enron_audit_004764_009083
                pair_enron_audit_005809_011212
                pair_enron_audit_006062_011659
                pair_enron_audit_006674_012758
                pair_enron_audit_001443_002725
                pair_enron_audit_001885_003561
                pair_enron_audit_004342_008268
                pair_enron_audit_005347_010285
                pair_enron_audit_006049_011626
                pair_enron_audit_006596_012624
                pair_enron_audit_006706_012814
                pair_enron_audit_004131_007883
                pair_enron_audit_004385_008344
                pair_enron_audit_004983_009529
                pair_enron_audit_006412_012431
                pair_enron_audit_001405_002649
                pair_enron_audit_001486_002794
                pair_enron_audit_003853_007366
                pair_enron_audit_005784_011173
                pair_enron_audit_006305_012195
                pair_enron_audit_006693_012799
                pair_enron_audit_001620_003069
                pair_enron_audit_003791_007232
                pair_enron_audit_005927_011442
                pair_enron_audit_006122_011756
                pair_enron_audit_006325_012234
                pair_enron_audit_001143_002155
                pair_enron_audit_002961_005553
                pair_enron_audit_005543_010715
                pair_enron_audit_000643_001186
                pair_enron_audit_002473_004624
                pair_enron_audit_003876_007406
                pair_enron_audit_004216_008044
                pair_enron_audit_005062_009709
                pair_enron_audit_006193_011938
                pair_enron_audit_006758_012926
                pair_enron_audit_000100_000160
                pair_enron_audit_002253_004229
                pair_enron_audit_005189_009923
                pair_enron_audit_003038_005712
                pair_enron_audit_003316_006237
                pair_enron_audit_006332_012246
                pair_enron_audit_002663_004889
                pair_enron_audit_005524_010677
                pair_enron_audit_005941_011473
                """
            ),
        ),
        (
            "abnormal_structure_or_artifact",
            "声明包含邮件收件人列表、转发头、编码残片、截断 URL 或其他明显结构污染。",
            _ids(
                """
                pair_enron_audit_006396_012398
                pair_enron_audit_004168_007963
                pair_enron_audit_000110_000184
                pair_enron_audit_000710_001342
                pair_enron_audit_001514_002844
                pair_enron_audit_001844_003481
                pair_enron_audit_003782_007213
                pair_enron_audit_004020_007698
                pair_enron_audit_004044_007758
                pair_enron_audit_005021_009622
                pair_enron_audit_005530_010686
                pair_enron_audit_005571_010759
                pair_enron_audit_006036_011606
                pair_enron_audit_002188_004122
                pair_enron_audit_002632_004821
                pair_enron_audit_003608_006815
                """
            ),
        ),
    ),
    "pubmed": (
        (
            "entity_type_or_boundary_error",
            "实体在当前语境中的类型错误，或 span 只是比值、机构名、范围、表格字段的一部分。",
            _ids(
                """
                pair_pubmed_audit_002133_003312
                pair_pubmed_audit_004260_006642
                pair_pubmed_audit_004451_006948
                pair_pubmed_audit_005911_009287
                pair_pubmed_audit_006517_010235
                pair_pubmed_audit_007341_011524
                pair_pubmed_audit_009133_014470
                pair_pubmed_audit_009489_014991
                pair_pubmed_audit_010841_017038
                pair_pubmed_audit_014827_023136
                pair_pubmed_audit_015702_024458
                pair_pubmed_audit_015836_024646
                pair_pubmed_audit_016210_025200
                pair_pubmed_audit_016437_025577
                pair_pubmed_audit_004140_006421
                pair_pubmed_audit_013046_020437
                pair_pubmed_audit_000724_001109
                pair_pubmed_audit_005537_008732
                pair_pubmed_audit_009101_014405
                pair_pubmed_audit_015965_024844
                pair_pubmed_audit_001628_002466
                pair_pubmed_audit_002308_003596
                pair_pubmed_audit_004468_006982
                pair_pubmed_audit_004689_007342
                pair_pubmed_audit_005163_008114
                pair_pubmed_audit_007050_011069
                pair_pubmed_audit_008610_013613
                pair_pubmed_audit_012300_019341
                pair_pubmed_audit_013205_020711
                pair_pubmed_audit_013942_021766
                pair_pubmed_audit_014206_022207
                pair_pubmed_audit_014301_022340
                pair_pubmed_audit_015319_023799
                pair_pubmed_audit_000030_000065
                pair_pubmed_audit_002840_004406
                pair_pubmed_audit_006844_010740
                pair_pubmed_audit_009618_015187
                pair_pubmed_audit_011520_018132
                pair_pubmed_audit_013897_021696
                pair_pubmed_audit_013950_021779
                pair_pubmed_audit_015431_023995
                pair_pubmed_audit_001812_002780
                pair_pubmed_audit_002742_004247
                pair_pubmed_audit_006096_009570
                pair_pubmed_audit_006602_010375
                pair_pubmed_audit_006691_010496
                pair_pubmed_audit_008781_013887
                pair_pubmed_audit_011334_017839
                pair_pubmed_audit_011543_018172
                pair_pubmed_audit_013779_021530
                pair_pubmed_audit_014002_021851
                pair_pubmed_audit_000606_000940
                pair_pubmed_audit_001551_002345
                pair_pubmed_audit_002684_004176
                pair_pubmed_audit_004234_006577
                pair_pubmed_audit_014749_023000
                pair_pubmed_audit_015607_024287
                pair_pubmed_audit_016478_025638
                pair_pubmed_audit_015476_024066
                pair_pubmed_audit_000364_000553
                pair_pubmed_audit_009604_015166
                pair_pubmed_audit_016905_026297
                pair_pubmed_audit_002298_003572
                pair_pubmed_audit_002328_003622
                pair_pubmed_audit_006839_010732
                pair_pubmed_audit_007621_011967
                pair_pubmed_audit_010737_016881
                pair_pubmed_audit_013838_021600
                pair_pubmed_audit_014030_021912
                pair_pubmed_audit_014985_023349
                pair_pubmed_audit_017189_026712
                pair_pubmed_audit_006719_010534
                pair_pubmed_audit_000209_000346
                pair_pubmed_audit_007152_011223
                pair_pubmed_audit_009694_015289
                pair_pubmed_audit_013350_020907
                """
            ),
        ),
        (
            "claim_fragment_or_truncation",
            "声明是表格、标题或句中残片，或在数值、引文、机构名等位置明显截断。",
            _ids(
                """
                pair_pubmed_audit_008627_013642
                pair_pubmed_audit_005766_009093
                pair_pubmed_audit_015450_024030
                pair_pubmed_audit_011293_017759
                pair_pubmed_audit_012330_019389
                pair_pubmed_audit_015465_024048
                pair_pubmed_audit_006784_010636
                pair_pubmed_audit_002124_003292
                pair_pubmed_audit_010180_016019
                pair_pubmed_audit_007951_012543
                pair_pubmed_audit_009896_015599
                pair_pubmed_audit_004286_006701
                pair_pubmed_audit_003198_004951
                """
            ),
        ),
    ),
}


def failure_decisions(dataset: str) -> dict[str, dict[str, str]]:
    """展开并校验单个数据集的失败决策。"""

    decisions: dict[str, dict[str, str]] = {}
    for reason_code, reason, audit_ids in FAILURE_GROUPS[dataset]:
        for audit_id in audit_ids:
            if audit_id in decisions:
                raise ValueError(f"{dataset}: duplicate AI decision for {audit_id}")
            decisions[audit_id] = {
                "reason_code": reason_code,
                "reason": reason,
            }
    return decisions


def _index_rows(rows: Iterable[dict[str, Any]], dataset: str, role: str) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        audit_id = str(row.get("audit_id") or "")
        if not audit_id or audit_id in by_id:
            raise ValueError(f"{dataset}/{role}: missing or duplicate audit_id {audit_id!r}")
        if str(row.get("dataset") or "") != dataset:
            raise ValueError(f"{dataset}/{role}: dataset mismatch for {audit_id}")
        by_id[audit_id] = row
    if len(by_id) != 200:
        raise ValueError(f"{dataset}/{role}: expected 200 rows, got {len(by_id)}")
    return by_id


def build_adjudication_rows(
    dataset: str,
    rows_a: Iterable[dict[str, Any]],
    rows_b: Iterable[dict[str, Any]],
    decisions: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """合并来源证据并生成 200 条独立 AI 裁决。"""

    by_a = _index_rows(rows_a, dataset, "A")
    by_b = _index_rows(rows_b, dataset, "B")
    if set(by_a) != set(by_b):
        raise ValueError(f"{dataset}: annotator A/B audit ID sets differ")

    failures = failure_decisions(dataset) if decisions is None else decisions
    unknown = sorted(set(failures) - set(by_a))
    if unknown:
        raise ValueError(f"{dataset}: AI decisions contain unknown IDs: {unknown}")

    output: list[dict[str, Any]] = []
    for audit_id in sorted(by_a):
        left = by_a[audit_id]
        right = by_b[audit_id]
        for field in MACHINE_FIELDS:
            if left.get(field) != right.get(field):
                raise ValueError(f"{dataset}: A/B machine field {field!r} differs for {audit_id}")

        failure = failures.get(audit_id)
        ai_pair_valid = "fail" if failure else "pass"
        output.append(
            {
                **{field: left.get(field) for field in MACHINE_FIELDS},
                "ai_pair_valid": ai_pair_valid,
                "ai_failure_reason_code": failure["reason_code"] if failure else "",
                "ai_failure_reason": failure["reason"] if failure else "",
                "ai_review_confidence": "high",
                "ai_reviewer": "Codex AI assistant",
                "adjudication_protocol_version": PROTOCOL_VERSION,
                "human_annotation_a": {
                    field: left.get(field, "") for field in HUMAN_FIELDS
                },
                "human_annotation_b": {
                    field: right.get(field, "") for field in HUMAN_FIELDS
                },
            }
        )
    return output


def _compact(value: Any, limit: int = 150) -> str:
    text = " ".join(str(value or "").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _write_failure_review(rows: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# Claim pair AI 辅助裁决失败清单",
        "",
        "> 该清单是独立 AI 辅助裁决，不是两位真人盲标结果。",
        "",
    ]
    for dataset in DATASETS:
        failed = [
            row for row in rows if row["dataset"] == dataset and row["ai_pair_valid"] == "fail"
        ]
        lines.extend(
            [
                f"## {dataset}（{len(failed)} / 200）",
                "",
                "| audit_id | 类型 | 实体替换 | 失败原因 | true claim 摘要 |",
                "|---|---|---|---|---|",
            ]
        )
        for row in failed:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _compact(row["audit_id"], 80),
                        _compact(row["entity_type"], 30),
                        _compact(
                            f"{row['original_entity']} → {row['counterfactual_entity']}", 90
                        ),
                        _compact(row["ai_failure_reason"], 130),
                        _compact(row["true_claim"]),
                    ]
                )
                + " |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_readme(datasets: dict[str, Any], path: Path) -> None:
    lines = [
        "# Claim pair AI 辅助裁决",
        "",
        "本目录保存对冻结审计样本的逐条 AI 辅助裁决。正式的 A/B 人工标注文件和 "
        "manifest 均未修改。",
        "",
        "## 结果",
        "",
        "| 数据集 | pass | fail | pass rate |",
        "|---|---:|---:|---:|",
    ]
    for dataset in DATASETS:
        result = datasets[dataset]
        lines.append(
            f"| {dataset} | {result['pass']} | {result['fail']} | "
            f"{result['pass_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 字段",
            "",
            "- `ai_pair_valid`：AI 最终裁决，值为 `pass` 或 `fail`。",
            "- `ai_failure_reason_code`：可聚合的失败类型。",
            "- `ai_failure_reason`：中文失败理由。",
            "- `human_annotation_a/b`：原始人工标签快照，仅用于追溯。",
            "- `adjudication_protocol_version`：本次裁决协议版本。",
            "",
            "## 使用边界",
            "",
            "- 该结果可以用于定位 validator 漏检、重新生成 claims 和形成误差分析。",
            "- 该结果不是两位真人独立盲标，不能据此报告 Cohen’s κ 或宣称人工门禁通过。",
            "- 论文和 artifact 中应明确写作 `AI-assisted adjudication`。",
            "- 全过程只使用本地冻结文件，API 调用数为 0。",
            "",
            "完整失败列表见 `FAILURE_REVIEW.md`，机器可读汇总见 `summary.json`。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate independent AI claim-pair adjudication")
    parser.add_argument(
        "--audit-dir",
        default="artifacts/v6_3/audits/claim_pair_release_200_attack_first_rc2_formal",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/v6_3/audits/claim_pair_ai_adjudication_attack_first_rc2_formal",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit_dir = resolve_path(args.audit_dir)
    output_dir = ensure_dir(resolve_path(args.output_dir))
    all_rows: list[dict[str, Any]] = []
    datasets: dict[str, Any] = {}

    for dataset in DATASETS:
        path_a = audit_dir / f"{dataset}_claim_pair_audit_annotator_a.jsonl"
        path_b = audit_dir / f"{dataset}_claim_pair_audit_annotator_b.jsonl"
        rows = build_adjudication_rows(
            dataset,
            read_jsonl(path_a),
            read_jsonl(path_b),
        )
        output_path = output_dir / f"{dataset}_claim_pair_ai_adjudication.jsonl"
        write_jsonl(rows, output_path)
        counts = Counter(row["ai_pair_valid"] for row in rows)
        reason_counts = Counter(
            row["ai_failure_reason_code"] for row in rows if row["ai_pair_valid"] == "fail"
        )
        datasets[dataset] = {
            "rows": len(rows),
            "pass": counts["pass"],
            "fail": counts["fail"],
            "pass_rate": counts["pass"] / len(rows),
            "failure_reason_counts": dict(sorted(reason_counts.items())),
            "annotator_a_path": str(path_a),
            "annotator_a_hash": sha256_file(path_a),
            "annotator_b_path": str(path_b),
            "annotator_b_hash": sha256_file(path_b),
            "output_path": str(output_path),
            "output_hash": sha256_file(output_path),
        }
        all_rows.extend(rows)

    failure_review_path = output_dir / "FAILURE_REVIEW.md"
    _write_failure_review(all_rows, failure_review_path)
    readme_path = output_dir / "README.md"
    _write_readme(datasets, readme_path)
    summary = {
        "status": "ai_assisted_adjudication_complete",
        "protocol_version": PROTOCOL_VERSION,
        "api_calls_performed": 0,
        "formal_annotation_files_modified": False,
        "satisfies_two_human_blind_annotation_gate": False,
        "unique_pair_count": len(all_rows),
        "pass": sum(row["ai_pair_valid"] == "pass" for row in all_rows),
        "fail": sum(row["ai_pair_valid"] == "fail" for row in all_rows),
        "datasets": datasets,
        "failure_review_path": str(failure_review_path),
        "failure_review_hash": sha256_file(failure_review_path),
        "readme_path": str(readme_path),
        "readme_hash": sha256_file(readme_path),
        "interpretation": (
            "该产物可用于修复 validator 和重建受影响 claims，但必须在论文和 artifact 中"
            "如实称为 AI 辅助裁决，不能宣称满足两位真人独立盲标或 Cohen's kappa 门禁。"
        ),
    }
    write_json(summary, output_dir / "summary.json")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
