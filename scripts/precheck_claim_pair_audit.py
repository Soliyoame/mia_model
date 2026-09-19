"""对正式双盲样本做不替代人工标签的本地预审。"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.attack.entity_extractor import is_likely_bad_identifier  # noqa: E402
from src.paired_claims.validator import validate_claim_pair  # noqa: E402
from src.utils.hash import sha256_file  # noqa: E402
from src.utils.io import ensure_dir, read_jsonl, resolve_path, write_json, write_jsonl  # noqa: E402


DATASETS = ("edgar", "enron", "pubmed")
_TERMINAL_RE = re.compile(r"[.!?;:。！？；：\)\]\}\"'”’]$")
_EMAIL_METADATA_RE = re.compile(
    r"(?:Content-Transfer-Encoding|Content-Type|Message-ID|Mime-Version|"
    r"X-(?:From|To|cc|bcc|Folder|Origin|FileName))\s*:",
    re.IGNORECASE,
)
_ENCODING_ARTIFACT_RE = re.compile(r"(?:=20|=09|quoted-printable|\\[A-Za-z_]+_[A-Za-z]+\d{4})", re.IGNORECASE)
_SECTION_WORDS = {
    "abstract",
    "aim",
    "aims",
    "background",
    "conclusion",
    "conclusions",
    "discussion",
    "figure",
    "introduction",
    "material",
    "materials",
    "method",
    "methods",
    "objective",
    "objectives",
    "purpose",
    "result",
    "results",
    "study",
    "table",
}
_CONNECTORS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_NAMED_TYPES = {"PERSON", "ORG", "LOCATION", "PRODUCT", "PROJECT_NAME"}
_SEMANTIC_REVIEW_TYPES = {
    "PERSON",
    "ORG",
    "LOCATION",
    "CONTRACT_TERM",
    "PRODUCT",
    "PROJECT_NAME",
}
_NON_PERSON_WORDS = {
    "agreement",
    "airlines",
    "annual",
    "announcements",
    "assessment",
    "assignments",
    "business",
    "card",
    "cash",
    "center",
    "clinical",
    "combination",
    "contributions",
    "credit",
    "division",
    "factors",
    "flow",
    "hybridization",
    "items",
    "lien",
    "offering",
    "officer",
    "partner",
    "permeability",
    "recognition",
    "release",
    "revenue",
    "risk",
    "sale",
    "studio",
    "supply",
    "test",
    "timing",
    "updated",
}
_GENERIC_PROJECT_ENDINGS = {
    "advisors",
    "agreement",
    "an",
    "appropriation",
    "cost",
    "enrolment",
    "flexibility",
    "leader",
    "liquidity",
    "loan",
    "loans",
    "management",
    "optimization",
    "partners",
    "phase",
    "report",
    "standardizes",
    "table",
    "testing",
    "the",
}


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def _markdown_cell(value: Any, limit: int = 180) -> str:
    compact = _compact(value).replace("|", "\\|")
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def precheck_signals(row: dict[str, Any]) -> tuple[str, list[str]]:
    """返回预审风险等级；结果不是人工 pass/fail 标签。"""

    true_claim = _compact(row.get("true_claim"))
    counterfactual_claim = _compact(row.get("counterfactual_claim"))
    original = _compact(row.get("original_entity"))
    counterfactual = _compact(row.get("counterfactual_entity"))
    entity_type = _compact(row.get("entity_type")).upper()
    high: list[str] = []
    review: list[str] = []

    validation = validate_claim_pair(
        true_claim,
        counterfactual_claim,
        original,
        counterfactual,
        entity_type,
    )
    if not validation.valid:
        high.extend(f"validator:{reason}" for reason in validation.reasons)

    if entity_type in _SEMANTIC_REVIEW_TYPES:
        review.append("semantic_entity_type_requires_manual_review")

    if not _TERMINAL_RE.search(true_claim):
        review.append("claim_missing_terminal_punctuation")
        last_word = re.search(r"([A-Za-z]{2,})$", true_claim)
        if last_word and len(last_word.group(1)) <= 7:
            high.append("possible_mid_word_or_sentence_truncation")

    if _EMAIL_METADATA_RE.search(true_claim):
        review.append("email_metadata_contamination")
        if not _TERMINAL_RE.search(true_claim):
            high.append("email_metadata_with_truncated_body")

    if _ENCODING_ARTIFACT_RE.search(true_claim):
        review.append("raw_encoding_or_mailbox_artifact")

    entity_words = re.findall(r"[A-Za-z]+", original.casefold())
    if entity_type == "PERSON":
        if any(word in _SECTION_WORDS for word in entity_words):
            high.append("person_entity_contains_section_heading")
        if entity_words and entity_words[-1] in _CONNECTORS:
            high.append("person_entity_ends_with_connector")
        if entity_words and any(word in {"this", "these", "those", "we", "our"} for word in entity_words):
            high.append("person_entity_contains_sentence_function_word")
        if any(word in _NON_PERSON_WORDS for word in entity_words):
            high.append("person_entity_looks_like_role_heading_or_product")

    if entity_type in _NAMED_TYPES:
        if entity_words and entity_words[-1] in _CONNECTORS:
            review.append("named_entity_ends_with_connector")
        if len(entity_words) > 8:
            review.append("named_entity_unusually_long")
        if re.search(r"[,;:!?]", original):
            review.append("named_entity_contains_clause_punctuation")

    if entity_type == "PROJECT_NAME" and entity_words and entity_words[-1] in _GENERIC_PROJECT_ENDINGS:
        high.append("project_entity_looks_like_generic_phrase")

    if entity_type == "URL" and re.search(r"[,.;:]$", original):
        high.append("url_entity_captures_trailing_punctuation")

    if entity_type == "IDENTIFIER":
        if not re.search(r"[0-9]", original):
            high.append("identifier_has_no_identifier_shape")
        if is_likely_bad_identifier(original) and re.search(r"[0-9][a-z]{3,}\b", original):
            high.append("identifier_looks_like_quantity_phrase")
        elif re.search(r"[0-9][A-Za-z]", original):
            review.append("identifier_has_alphanumeric_payload")

    if (
        entity_type == "NUMERIC_VALUE"
        and re.fullmatch(r"(?:19|20)[0-9]{2}", original)
        and not re.fullmatch(r"(?:19|20)[0-9]{2}", counterfactual)
    ):
        high.append("year_changed_as_generic_numeric_value")

    original_index = true_claim.find(original)

    duration_match = re.fullmatch(r"1(?:\.0+)?\s+([A-Za-z]+)", original)
    counter_duration_match = re.fullmatch(r"([2-9][0-9]*(?:\.[0-9]+)?)\s+([A-Za-z]+)", counterfactual)
    if duration_match and counter_duration_match and original_index >= 0:
        suffix = true_claim[original_index + len(original) :].lstrip()
        if duration_match.group(1).casefold() == counter_duration_match.group(2).casefold() and (
            not suffix or suffix[0] in ",.;:!?)]}"
        ):
            high.append("counterfactual_breaks_number_unit_agreement")

    if len(true_claim) > 500:
        review.append("claim_unusually_long")
    if re.search(r"(?:<[^>]+>|&(?:lt|gt|amp|nbsp);)", true_claim, re.IGNORECASE):
        review.append("markup_artifact")
    if true_claim.startswith(("•", "▪", "◦")):
        review.append("list_or_heading_surface")

    signals = list(dict.fromkeys(high + review))
    if high:
        return "high_risk", signals
    if review:
        return "needs_review", signals
    return "low_risk", []


def _load_unique_samples(
    audit_dir: Path,
    dataset: str,
    expected_sample_size: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path_a = audit_dir / f"{dataset}_claim_pair_audit_annotator_a.jsonl"
    path_b = audit_dir / f"{dataset}_claim_pair_audit_annotator_b.jsonl"
    rows_a = list(read_jsonl(path_a))
    rows_b = list(read_jsonl(path_b))
    ids_a = [str(row.get("audit_id") or "") for row in rows_a]
    ids_b = [str(row.get("audit_id") or "") for row in rows_b]
    if expected_sample_size <= 0:
        raise ValueError("expected_sample_size must be positive")
    if len(rows_a) != expected_sample_size or len(rows_b) != expected_sample_size:
        raise RuntimeError(
            f"{dataset}: expected {expected_sample_size} rows per annotator, "
            f"found A={len(rows_a)}, B={len(rows_b)}"
        )
    if len(set(ids_a)) != expected_sample_size or set(ids_a) != set(ids_b):
        raise RuntimeError(
            f"{dataset}: A/B audit IDs are not the same "
            f"{expected_sample_size} unique samples"
        )
    for row in rows_a + rows_b:
        if str(row.get("human_pair_valid") or "").strip():
            raise RuntimeError(f"{dataset}: human labels already exist; precheck refuses to mix roles")
    return rows_a, {
        "annotator_a_hash": sha256_file(path_a),
        "annotator_b_hash": sha256_file(path_b),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Locally precheck claim-pair audit samples without human labels")
    parser.add_argument(
        "--audit-dir",
        default="artifacts/v6_3/audits/claim_pair_release_200_attack_first_rc2_formal",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/v6_3/audits/assistant_claim_precheck_attack_first_rc2_formal",
    )
    parser.add_argument(
        "--expected-sample-size",
        type=int,
        default=200,
        help="Expected rows in each annotator file for every dataset (for example RC=100, Release=200).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit_dir = resolve_path(args.audit_dir)
    output_dir = ensure_dir(resolve_path(args.output_dir))
    all_rows: list[dict[str, Any]] = []
    datasets: dict[str, Any] = {}

    for dataset in DATASETS:
        rows, hashes = _load_unique_samples(
            audit_dir,
            dataset,
            args.expected_sample_size,
        )
        output_rows: list[dict[str, Any]] = []
        for row in rows:
            tier, signals = precheck_signals(row)
            output_rows.append({
                "audit_id": row["audit_id"],
                "dataset": dataset,
                "source_key": row.get("source_key"),
                "entity_type": row.get("entity_type"),
                "original_entity": row.get("original_entity"),
                "counterfactual_entity": row.get("counterfactual_entity"),
                "true_claim": row.get("true_claim"),
                "counterfactual_claim": row.get("counterfactual_claim"),
                "assistant_precheck_tier": tier,
                "assistant_precheck_signals": signals,
                "human_pair_valid": "",
                "notice": "AI预审提示，不是人工标注，不得复制到A/B标签。",
            })
        output_rows.sort(
            key=lambda row: (
                {"high_risk": 0, "needs_review": 1, "low_risk": 2}[row["assistant_precheck_tier"]],
                row["audit_id"],
            )
        )
        output_path = output_dir / f"{dataset}_assistant_precheck.jsonl"
        write_jsonl(output_rows, output_path)
        counts = Counter(row["assistant_precheck_tier"] for row in output_rows)
        signal_counts = Counter(
            signal for row in output_rows for signal in row["assistant_precheck_signals"]
        )
        datasets[dataset] = {
            **hashes,
            "rows": len(output_rows),
            "tier_counts": dict(counts),
            "signal_counts": dict(signal_counts),
            "output_path": str(output_path),
            "output_hash": sha256_file(output_path),
        }
        all_rows.extend(output_rows)

    summary = {
        "status": "assistant_precheck_only",
        "human_quality_gate_status": "pending_human_annotation",
        "formal_annotation_files_modified": False,
        "api_calls_performed": 0,
        "expected_sample_size_per_dataset": args.expected_sample_size,
        "unique_pair_count": len(all_rows),
        "tier_counts": dict(Counter(row["assistant_precheck_tier"] for row in all_rows)),
        "datasets": datasets,
        "interpretation": (
            "高风险和需复查条目用于缩小人工复查范围；低风险也不能自动计为pass。"
            "本报告不得提供给两位正式盲标者。"
        ),
    }
    priority_path = output_dir / "PRIORITY_REVIEW.md"
    lines = [
        "# Claim pair AI 预审重点清单",
        "",
        "> 该文件只供项目负责人复查，不是人工标注，不得发给 A/B 正式标注者。",
        "",
        f"- 唯一 pair：{len(all_rows)}",
        f"- 高风险：{summary['tier_counts'].get('high_risk', 0)}",
        f"- 需复查：{summary['tier_counts'].get('needs_review', 0)}",
        f"- 低风险：{summary['tier_counts'].get('low_risk', 0)}（仍不能自动计为 pass）",
        "",
    ]
    for dataset in DATASETS:
        dataset_rows = [row for row in all_rows if row["dataset"] == dataset]
        for tier, title in (("high_risk", "高风险"), ("needs_review", "需复查")):
            selected = [row for row in dataset_rows if row["assistant_precheck_tier"] == tier]
            lines.extend(
                [
                    f"## {dataset} — {title}（{len(selected)}）",
                    "",
                    "| audit_id | 类型 | 实体替换 | 信号 | true claim 摘要 |",
                    "|---|---|---|---|---|",
                ]
            )
            for row in selected:
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            _markdown_cell(row["audit_id"], 80),
                            _markdown_cell(row["entity_type"], 40),
                            _markdown_cell(
                                f"{row['original_entity']} → {row['counterfactual_entity']}", 100
                            ),
                            _markdown_cell(", ".join(row["assistant_precheck_signals"]), 160),
                            _markdown_cell(row["true_claim"]),
                        ]
                    )
                    + " |"
                )
            lines.append("")
    priority_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary["priority_review_path"] = str(priority_path)
    summary["priority_review_hash"] = sha256_file(priority_path)
    write_json(summary, output_dir / "summary.json")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
