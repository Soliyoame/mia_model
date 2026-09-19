"""Offline IA query and shadow-answer freezing for PCV-MIA v21."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable

from ..llm.openai_compatible import ChatResult
from ..llm.response_validation import strict_response_metadata_error
from ..utils.hash import sha256_obj, sha256_text
from ..utils.io import ensure_dir, read_json, write_json


IA_SHADOW_PROTOCOL_VERSION = "pcv-mia-ia-shadow-v21"
IA_SUMMARY_PROMPT_VERSION = "ia-summary-luna-v21"
IA_QUESTION_PROMPT_VERSION = "ia-questions-30-luna-v21"
IA_SHADOW_PROMPT_VERSION = "ia-shadow-yes-no-qwen-v21"
IA_CANDIDATE_COUNT = 30
IA_SELECTED_COUNT = 5


def build_summary_prompt(text: str) -> str:
    return (
        "Return one concise topic summary grounded only in the candidate document. "
        "Do not mention the document or passage. Return plain text only.\n\n"
        f"Candidate document:\n{text}\n\nSummary:"
    )


def build_question_prompt(text: str) -> str:
    return (
        "Generate exactly 30 distinct yes/no questions answerable from the candidate "
        "document. Questions must cover different facts, preserve acronyms, avoid asking "
        "whether the document says something, and contain no answer. Return a JSON object "
        "only with schema {\"questions\":[\"...\"]}.\n\n"
        f"Candidate document:\n{text}"
    )


def build_shadow_prompt(text: str, question: str) -> str:
    return (
        "Use only the candidate document. Answer with exactly one of: Yes, No, "
        "I don't know. Do not explain.\n\n"
        f"Candidate document:\n{text}\n\nQuestion: {question}\nAnswer:"
    )


def _call_metadata(result: ChatResult) -> dict[str, Any]:
    return asdict(result)


def _validate_result(
    result: ChatResult,
    *,
    expected_model_id: str,
    model_version: str,
    role: str,
) -> None:
    error = strict_response_metadata_error(
        result.content,
        provider_model_id=result.provider_model_id,
        provider_request_id=result.provider_request_id,
        called_at=result.called_at,
        expected_model_id=expected_model_id,
        configured_model_version=model_version,
    )
    if error:
        raise RuntimeError(f"{role} response rejected: {error}")


def parse_exact_questions(content: str) -> list[str]:
    try:
        payload = json.loads(str(content).strip())
    except json.JSONDecodeError as exc:
        raise ValueError("IA question response must be a JSON object") from exc
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list):
        raise ValueError("IA question response is missing questions[]")
    normalized = [" ".join(str(question).split()) for question in questions]
    if len(normalized) != IA_CANDIDATE_COUNT:
        raise ValueError("IA requires exactly 30 candidate questions")
    if any(not question or not question.endswith("?") for question in normalized):
        raise ValueError("Every IA candidate must be a non-empty question")
    if len({question.casefold() for question in normalized}) != IA_CANDIDATE_COUNT:
        raise ValueError("IA candidate questions must be unique")
    return normalized


def normalize_shadow_answer(content: str) -> str | None:
    value = " ".join(str(content or "").strip().strip('"\'').split())
    value = value.rstrip(".!").casefold()
    if value == "yes":
        return "Yes"
    if value == "no":
        return "No"
    if value in {"i don't know", "i dont know"}:
        return "I don't know"
    return None


def source_artifact_name(source_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(source_id)).strip("-._")[:80]
    return f"{slug or 'source'}-{sha256_text(str(source_id))[:12]}.json"


def prepare_source_bundle(
    target: dict[str, Any],
    *,
    dataset: str,
    query_call: Callable[[str], ChatResult],
    shadow_call: Callable[[str], ChatResult],
    relevance_scores: Callable[[list[str], str], list[float]],
    query_model_id: str,
    query_model_version: str,
    shadow_model_id: str,
    shadow_model_version: str,
) -> dict[str, Any]:
    """Prepare one source without making any victim call."""

    source_id = str(
        target.get("source_key")
        or target.get("source_id")
        or target.get("doc_id")
        or ""
    )
    text = str(target.get("text") or "")
    if not source_id or not text.strip():
        raise ValueError("IA source_id and candidate text are required")
    source_hash = sha256_text(text)

    summary_prompt = build_summary_prompt(text)
    summary_result = query_call(summary_prompt)
    _validate_result(
        summary_result,
        expected_model_id=query_model_id,
        model_version=query_model_version,
        role="IA Luna summary",
    )
    summary = " ".join(summary_result.content.split())

    question_prompt = build_question_prompt(text)
    question_result = query_call(question_prompt)
    _validate_result(
        question_result,
        expected_model_id=query_model_id,
        model_version=query_model_version,
        role="IA Luna questions",
    )
    questions = parse_exact_questions(question_result.content)
    scores = list(relevance_scores(questions, text))
    if len(scores) != IA_CANDIDATE_COUNT:
        raise RuntimeError("IA relevance ranker returned the wrong number of scores")
    ranked = sorted(
        [
            {
                "question_id": f"q{index:02d}",
                "question": question,
                "question_hash": sha256_text(question),
                "relevance_score": float(scores[index - 1]),
            }
            for index, question in enumerate(questions, start=1)
        ],
        key=lambda row: (-row["relevance_score"], row["question_hash"]),
    )
    for rank, row in enumerate(ranked, start=1):
        row["candidate_rank"] = rank

    attempts: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for candidate in ranked:
        prompt = build_shadow_prompt(text, str(candidate["question"]))
        result = shadow_call(prompt)
        _validate_result(
            result,
            expected_model_id=shadow_model_id,
            model_version=shadow_model_version,
            role="IA Qwen shadow",
        )
        answer = normalize_shadow_answer(result.content)
        if answer is None:
            raise RuntimeError("IA Qwen shadow response has an invalid answer schema")
        attempt = {
            **candidate,
            "shadow_answer": answer,
            "shadow_model": shadow_model_id,
            "shadow_model_version": shadow_model_version,
            "shadow_prompt_hash": sha256_text(prompt),
            "request_id": result.provider_request_id,
            "actual_model_id": result.provider_model_id,
            "generated_at": result.called_at,
            "validation_status": "valid",
            "generation": _call_metadata(result),
        }
        attempts.append(attempt)
        if answer != "I don't know":
            selected.append(attempt)
        if len(selected) == IA_SELECTED_COUNT:
            break

    status = (
        "ready"
        if len(selected) == IA_SELECTED_COUNT
        else "ia_shadow_insufficient_valid_answers"
    )
    query_manifest = {
        "attack": "IA",
        "source_id": source_id,
        "summary_prompt_hash": sha256_text(summary_prompt),
        "question_prompt_hash": sha256_text(question_prompt),
        "query_generator_model": query_model_id,
        "model_version": query_model_version,
        "summary_generation": _call_metadata(summary_result),
        "question_generation": _call_metadata(question_result),
        "response_validation_status": "valid",
    }
    bundle = {
        "protocol_version": IA_SHADOW_PROTOCOL_VERSION,
        "dataset": str(dataset),
        "source_id": source_id,
        "doc_id": str(target.get("doc_id") or ""),
        "group": str(target.get("group") or ""),
        "source_hash": source_hash,
        "status": status,
        "summary": summary,
        "query_manifest": query_manifest,
        "ranker": {
            "rule": "frozen_bge_cosine_desc_question_hash_tiebreak",
            "candidate_count": IA_CANDIDATE_COUNT,
        },
        "candidates": ranked,
        "shadow_attempts": attempts,
        "selected_pairs": selected,
        "call_ledger": {
            "luna_logical_calls": 2,
            "luna_physical_calls": sum(
                1 + int(result.retry_count)
                for result in (summary_result, question_result)
            ),
            "luna_retry_calls": sum(
                int(result.retry_count)
                for result in (summary_result, question_result)
            ),
            "qwen_shadow_logical_calls": len(attempts),
            "qwen_shadow_physical_calls": sum(
                1 + int(row["generation"].get("retry_count") or 0)
                for row in attempts
            ),
            "qwen_shadow_retry_calls": sum(
                int(row["generation"].get("retry_count") or 0)
                for row in attempts
            ),
        },
    }
    bundle["query_hash"] = sha256_obj(
        {
            "summary": summary,
            "questions": questions,
            "query_manifest": query_manifest,
        }
    )
    bundle["bundle_hash"] = sha256_obj(bundle)
    return bundle


def write_source_bundle(bundle: dict[str, Any], root: str | Path) -> Path:
    dataset_dir = ensure_dir(Path(root) / str(bundle["dataset"]))
    path = dataset_dir / source_artifact_name(str(bundle["source_id"]))
    if path.exists():
        existing = read_json(path)
        if existing != bundle:
            raise RuntimeError(f"IA shadow bundle drift; overwrite refused: {path}")
        return path
    write_json(bundle, path)
    return path


def load_source_bundle(
    root: str | Path,
    dataset: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    source_id = str(
        target.get("source_key")
        or target.get("source_id")
        or target.get("doc_id")
        or ""
    )
    path = Path(root) / dataset / source_artifact_name(source_id)
    if not path.is_file():
        raise FileNotFoundError(f"Frozen IA shadow bundle missing: {path}")
    bundle = read_json(path)
    recorded_hash = str(bundle.get("bundle_hash") or "")
    unhashed = dict(bundle)
    unhashed.pop("bundle_hash", None)
    if recorded_hash != sha256_obj(unhashed):
        raise RuntimeError(f"IA shadow bundle hash mismatch: {path}")
    if bundle.get("status") != "ready":
        raise RuntimeError(f"IA shadow bundle is not ready: {source_id}")
    if str(bundle.get("source_id")) != source_id:
        raise RuntimeError(f"IA shadow source identity drift: {source_id}")
    if str(bundle.get("source_hash")) != sha256_text(str(target.get("text") or "")):
        raise RuntimeError(f"IA shadow source hash drift: {source_id}")
    selected = list(bundle.get("selected_pairs") or [])
    if len(selected) != IA_SELECTED_COUNT:
        raise RuntimeError(f"IA shadow requires exactly five selected pairs: {source_id}")
    if any(row.get("shadow_answer") not in {"Yes", "No"} for row in selected):
        raise RuntimeError(f"IA shadow selected pair is invalid: {source_id}")
    return bundle


def build_dataset_manifest(
    root: str | Path,
    dataset: str,
    targets: Iterable[dict[str, Any]],
    *,
    query_identity: dict[str, Any],
    shadow_identity: dict[str, Any],
) -> dict[str, Any]:
    bundles = [load_source_bundle(root, dataset, target) for target in targets]
    bundles.sort(key=lambda row: str(row["source_id"]))
    ledger_keys = (
        "luna_logical_calls",
        "luna_physical_calls",
        "luna_retry_calls",
        "qwen_shadow_logical_calls",
        "qwen_shadow_physical_calls",
        "qwen_shadow_retry_calls",
    )
    ledger = {
        key: sum(int(bundle["call_ledger"][key]) for bundle in bundles)
        for key in ledger_keys
    }
    manifest = {
        "protocol_version": IA_SHADOW_PROTOCOL_VERSION,
        "dataset": dataset,
        "status": "frozen",
        "source_count": len(bundles),
        "query_identity": query_identity,
        "shadow_identity": shadow_identity,
        "query_hash": sha256_obj(
            [(bundle["source_id"], bundle["query_hash"]) for bundle in bundles]
        ),
        "ia_shadow_manifest_hash": sha256_obj(
            [(bundle["source_id"], bundle["bundle_hash"]) for bundle in bundles]
        ),
        "ia_shadow_model_version": shadow_identity.get("model_version"),
        "call_ledger": ledger,
        "effective_answer_rate": (
            IA_SELECTED_COUNT * len(bundles)
            / max(1, ledger["qwen_shadow_logical_calls"])
        ),
        "average_shadow_calls_per_source": (
            ledger["qwen_shadow_logical_calls"] / max(1, len(bundles))
        ),
        "sources": [
            {
                "source_id": bundle["source_id"],
                "source_hash": bundle["source_hash"],
                "bundle_hash": bundle["bundle_hash"],
                "path": source_artifact_name(str(bundle["source_id"])),
            }
            for bundle in bundles
        ],
    }
    write_json(manifest, Path(root) / dataset / "dataset_manifest.json")
    return manifest
