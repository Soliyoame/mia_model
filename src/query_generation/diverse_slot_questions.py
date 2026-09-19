"""Sibling-generated diverse entity-slot verification questions."""

from __future__ import annotations

import itertools
import json
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..llm.response_validation import (
    generator_response_error,
    strict_response_metadata_error,
)

from ..paired_claims.validator import find_entity_spans, validate_query_pair
from ..rag.embeddings import cosine_similarity
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import (
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
    write_jsonl_atomic,
)
from ..utils.logger import get_logger
from .lexical_overlap import (
    ENTITY_SLOT,
    diversity_statistics,
    lexical_copy_scores,
    normalized_tokens,
)


LOGGER = get_logger(__name__)

PROTOCOL_VERSION = "diverse_slotted_verification_v1"
PROMPT_VERSION = "diverse_slot_question_generation_v1"
QUERY_TYPE = "diverse_slotted_verification"

_WHITESPACE_RE = re.compile(r"\s+")
_OPEN_WH_RE = re.compile(
    r"^\s*(?:what|who|whom|whose|where|when|why|how(?:\s+(?:many|much|long|often))?)\b",
    re.IGNORECASE,
)
_SUSPICIOUS_RE = re.compile(
    r"\b(?:membership inference|knowledge base membership|system prompt|"
    r"hidden document|retrieved context|source chunk|vector store|"
    r"ignore previous|jailbreak|show me the context)\b",
    re.IGNORECASE,
)
_AUXILIARIES = {
    "am",
    "are",
    "can",
    "could",
    "did",
    "do",
    "does",
    "has",
    "have",
    "is",
    "may",
    "might",
    "should",
    "was",
    "were",
    "will",
    "would",
}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}
_STRUCTURED_LITERAL_RE = re.compile(
    r"(?:[$€£¥]\s?\d[\d,]*(?:\.\d+)?)|"
    r"(?:\b\d+(?:\.\d+)?\s?%)|"
    r"(?:\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{2,4}\b)|"
    r"(?:\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b)|"
    r"(?:\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b)|"
    r"(?:\b\d+(?:,\d{3})*(?:\.\d+)?\b)",
    re.IGNORECASE,
)


class NLIPredictor(Protocol):
    """本模块依赖的最小 NLI 接口。"""

    def probabilities(
        self,
        pairs: Sequence[tuple[str, str]],
    ) -> list[dict[str, float]]:
        ...


class ChatClient(Protocol):
    """OpenAI-compatible metadata chat interface."""

    def chat_with_metadata(
        self,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        timeout: float | None = None,
        max_tokens: int = 512,
    ) -> Any:
        ...


@dataclass(frozen=True)
class Candidate:
    """Sibling 返回的一条候选问句。"""

    pair_id: str
    question_template: str
    proposition_template: str
    anchors: tuple[str, ...]


@dataclass(frozen=True)
class ScoredCandidate:
    """通过全部本地门禁的候选及其排序指标。"""

    candidate: Candidate
    qplus: str
    qminus: str
    proposition_plus: str
    proposition_minus: str
    nli_true_entailment: float
    nli_counterfactual_entailment: float
    question_proposition_similarity: float
    semantic_fidelity_similarity: float
    five_gram_containment: float
    longest_common_token_run: int
    question_word_count: int
    opening_3gram: tuple[str, ...]
    opening_auxiliary: str


def _compact(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(text or "")).strip()


def _aligned_entity_spans(pair: dict[str, Any]) -> tuple[tuple[int, int], tuple[int, int]]:
    true_claim = str(pair.get("true_claim") or "")
    counterfactual_claim = str(pair.get("counterfactual_claim") or "")
    original = str(pair.get("original_entity") or "")
    counterfactual = str(pair.get("counterfactual_entity") or "")
    for original_span in find_entity_spans(true_claim, original):
        for counterfactual_span in find_entity_spans(counterfactual_claim, counterfactual):
            if true_claim[: original_span[0]] != counterfactual_claim[: counterfactual_span[0]]:
                continue
            if true_claim[original_span[1] :] != counterfactual_claim[counterfactual_span[1] :]:
                continue
            return original_span, counterfactual_span
    raise ValueError(f"Pair is not an aligned single-slot substitution: {pair.get('pair_id')}")


def slotted_claim(pair: dict[str, Any]) -> str:
    """将 true claim 中唯一变化的实体位置替换为槽位。"""

    true_claim = str(pair.get("true_claim") or "")
    original_span, _ = _aligned_entity_spans(pair)
    return true_claim[: original_span[0]] + ENTITY_SLOT + true_claim[original_span[1] :]


def build_generation_prompt(
    pairs: Sequence[dict[str, Any]],
    *,
    correction_reasons: Sequence[str] = (),
) -> str:
    """构造 source 级三 pair 多样化问句生成提示。"""

    payload = [
        {
            "pair_id": str(pair["pair_id"]),
            "entity_type": str(pair.get("entity_type") or "VALUE"),
            "slotted_true_claim": slotted_claim(pair),
        }
        for pair in pairs
    ]
    correction = ""
    if correction_reasons:
        correction = (
            "\nThe previous response failed these local checks. Correct every issue:\n- "
            + "\n- ".join(str(reason) for reason in correction_reasons[:20])
            + "\n"
        )
    return (
        "Generate diverse, natural polar verification questions for one candidate source.\n"
        "Return valid JSON only, with exactly the schema below.\n"
        '{"pairs":[{"pair_id":"...","candidates":[{"question_template":"...{ENTITY}...?",'
        '"proposition_template":"...{ENTITY}... .","anchors":["source phrase"]}]}]}\n'
        "For every input pair, return exactly three candidates.\n"
        "Hard requirements:\n"
        "1. Keep exactly one literal {ENTITY} in both templates. Never reveal or guess its value.\n"
        "2. The question must be a complete 8-45 word polar verification question ending in '?'.\n"
        "3. Do not use open What/Who/Where/When/Why/How questions.\n"
        "4. Preserve the subject, relation, scope, negation, date, unit, and essential qualifiers of the claim.\n"
        "5. Do not invent any amount, date, percentage, identifier, entity, or event.\n"
        "6. proposition_template must state exactly the proposition asked by question_template.\n"
        "7. anchors must quote one to three useful 1-4 word phrases that occur in both the input claim and templates.\n"
        "8. Across the different pairs, vary interrogative syntax and openings naturally; do not apply one fixed prefix.\n"
        "9. Avoid stock openings such as 'Can it be confirmed that'; make each opening specific to its fact.\n"
        "10. Do not mention a knowledge base, index, hidden context, membership, retrieval, or system prompt.\n"
        f"Protocol: {PROMPT_VERSION}\n"
        f"Input pairs: {json.dumps(payload, ensure_ascii=False)}\n"
        f"{correction}"
    )


def parse_generation_response(
    raw: str,
    expected_pair_ids: Sequence[str],
) -> dict[str, list[Candidate]]:
    """解析并做严格 schema/数量校验。"""

    from ..llm.openai_compatible import parse_json_object

    obj = parse_json_object(raw)
    pair_rows = obj.get("pairs")
    if not isinstance(pair_rows, list):
        raise ValueError("Sibling response must contain a pairs list")
    expected = [str(pair_id) for pair_id in expected_pair_ids]
    parsed: dict[str, list[Candidate]] = {}
    for row in pair_rows:
        if not isinstance(row, dict):
            raise ValueError("Sibling pair row must be an object")
        pair_id = str(row.get("pair_id") or "")
        if not pair_id or pair_id in parsed:
            raise ValueError(f"Sibling response contains missing/duplicate pair_id: {pair_id!r}")
        candidates = row.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 3:
            raise ValueError(f"Pair {pair_id} must contain exactly three candidates")
        parsed[pair_id] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError(f"Pair {pair_id} candidate must be an object")
            anchors = candidate.get("anchors")
            if not isinstance(anchors, list):
                raise ValueError(f"Pair {pair_id} candidate anchors must be a list")
            parsed[pair_id].append(
                Candidate(
                    pair_id=pair_id,
                    question_template=_compact(str(candidate.get("question_template") or "")),
                    proposition_template=_compact(str(candidate.get("proposition_template") or "")),
                    anchors=tuple(_compact(str(anchor)) for anchor in anchors if _compact(str(anchor))),
                )
            )
    if set(parsed) != set(expected) or len(parsed) != len(expected):
        raise ValueError(
            "Sibling response pair IDs do not match input: "
            f"expected={expected}, actual={sorted(parsed)}"
        )
    return parsed


def _structured_literals(text: str) -> set[str]:
    return {_compact(match.group(0)).casefold() for match in _STRUCTURED_LITERAL_RE.finditer(text)}


def _anchor_is_valid(anchor: str, claim: str, question: str, proposition: str) -> bool:
    normalized = _compact(anchor).casefold()
    if not normalized or ENTITY_SLOT.casefold() in normalized:
        return False
    return all(
        normalized in _compact(text).casefold()
        for text in (claim, question, proposition)
    )


def _anchor_gate(anchors: Sequence[str], claim: str, question: str, proposition: str) -> bool:
    valid = [
        anchor
        for anchor in anchors
        if _anchor_is_valid(anchor, claim, question, proposition)
    ]
    if any(2 <= len(normalized_tokens(anchor)) <= 4 for anchor in valid):
        return True
    content_tokens = {
        token
        for anchor in valid
        for token in normalized_tokens(anchor)
        if token not in _STOPWORDS and token != "entity"
    }
    return len(content_tokens) >= 2


def _opening_auxiliary(question: str) -> str:
    for token in normalized_tokens(question)[:6]:
        if token in _AUXILIARIES:
            return token
    return "other"


def _static_candidate_reasons(
    candidate: Candidate,
    pair: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    question = candidate.question_template
    proposition = candidate.proposition_template
    if question.count(ENTITY_SLOT) != 1:
        reasons.append("question_slot_count")
    if proposition.count(ENTITY_SLOT) != 1:
        reasons.append("proposition_slot_count")
    words = normalized_tokens(question)
    if not 8 <= len(words) <= 45:
        reasons.append("question_word_count")
    if not question.endswith("?"):
        reasons.append("question_not_polar_surface")
    if _OPEN_WH_RE.search(question):
        reasons.append("open_wh_question")
    if _opening_auxiliary(question) == "other":
        reasons.append("question_not_polar_structure")
    if _SUSPICIOUS_RE.search(question) or _SUSPICIOUS_RE.search(proposition):
        reasons.append("suspicious_terms")
    if not proposition:
        reasons.append("empty_proposition")
    if not 1 <= len(candidate.anchors) <= 3:
        reasons.append("anchor_count")
    if any(not 1 <= len(normalized_tokens(anchor)) <= 4 for anchor in candidate.anchors):
        reasons.append("anchor_length")
    claim_template = slotted_claim(pair)
    if not _anchor_gate(candidate.anchors, claim_template, question, proposition):
        reasons.append("insufficient_retrieval_anchors")
    allowed_literals = _structured_literals(claim_template)
    introduced = (
        _structured_literals(question) | _structured_literals(proposition)
    ) - allowed_literals
    if introduced:
        reasons.append("introduced_structured_literal:" + ",".join(sorted(introduced)))

    original = str(pair.get("original_entity") or "")
    counterfactual = str(pair.get("counterfactual_entity") or "")
    for field_name, template in (("question", question), ("proposition", proposition)):
        outside_slot = template.casefold().replace(ENTITY_SLOT.casefold(), "")
        if original and original.casefold() in outside_slot:
            reasons.append(f"{field_name}_original_entity_leaked")
        if counterfactual and counterfactual.casefold() in outside_slot:
            reasons.append(f"{field_name}_counterfactual_entity_leaked")
    if question.count(ENTITY_SLOT) == 1:
        qplus = question.replace(ENTITY_SLOT, original)
        qminus = question.replace(ENTITY_SLOT, counterfactual)
        validation = validate_query_pair(qplus, qminus, original, counterfactual)
        reasons.extend(validation.reasons)
    return list(dict.fromkeys(reasons))


def _is_entailment(probabilities: dict[str, float]) -> bool:
    required = {"entailment", "neutral", "contradiction"}
    if set(probabilities) != required:
        raise RuntimeError(f"NLI labels must be exactly {sorted(required)}")
    return float(probabilities["entailment"]) > max(
        float(probabilities["neutral"]),
        float(probabilities["contradiction"]),
    )


def score_source_candidates(
    pairs: Sequence[dict[str, Any]],
    candidates_by_pair: dict[str, list[Candidate]],
    *,
    source_text: str,
    nli_predictor: NLIPredictor,
    embedder: Any,
    min_question_proposition_similarity: float = 0.80,
    max_five_gram_containment: float = 0.35,
    max_longest_common_token_run: int = 8,
) -> tuple[dict[str, list[ScoredCandidate]], list[str]]:
    """对一个 source 的全部候选执行结构、NLI、embedding 和复制门禁。"""

    scored: dict[str, list[ScoredCandidate]] = defaultdict(list)
    failures: list[str] = []
    pair_lookup = {str(pair["pair_id"]): pair for pair in pairs}
    prepared: list[dict[str, Any]] = []
    for pair_id, candidates in candidates_by_pair.items():
        pair = pair_lookup[pair_id]
        for index, candidate in enumerate(candidates):
            prefix = f"{pair_id}:candidate_{index + 1}"
            reasons = _static_candidate_reasons(candidate, pair)
            if reasons:
                failures.extend(f"{prefix}:{reason}" for reason in reasons)
                continue
            original = str(pair["original_entity"])
            counterfactual = str(pair["counterfactual_entity"])
            prepared.append(
                {
                    "pair_id": pair_id,
                    "pair": pair,
                    "prefix": prefix,
                    "candidate": candidate,
                    "original": original,
                    "counterfactual": counterfactual,
                    "qplus": candidate.question_template.replace(ENTITY_SLOT, original),
                    "qminus": candidate.question_template.replace(ENTITY_SLOT, counterfactual),
                    "proposition_plus": candidate.proposition_template.replace(
                        ENTITY_SLOT, original
                    ),
                    "proposition_minus": candidate.proposition_template.replace(
                        ENTITY_SLOT, counterfactual
                    ),
                }
            )

    nli_inputs = [
        nli_pair
        for record in prepared
        for nli_pair in (
            (str(record["pair"]["true_claim"]), str(record["proposition_plus"])),
            (
                str(record["pair"]["counterfactual_claim"]),
                str(record["proposition_minus"]),
            ),
        )
    ]
    nli_outputs = nli_predictor.probabilities(nli_inputs)
    if len(nli_outputs) != len(nli_inputs):
        raise RuntimeError("NLI output count mismatch for source query candidates")

    nli_valid: list[dict[str, Any]] = []
    for index, record in enumerate(prepared):
        true_nli = nli_outputs[index * 2]
        counterfactual_nli = nli_outputs[index * 2 + 1]
        prefix = str(record["prefix"])
        if not _is_entailment(true_nli):
            failures.append(f"{prefix}:true_proposition_not_entailed")
            continue
        if not _is_entailment(counterfactual_nli):
            failures.append(f"{prefix}:counterfactual_proposition_not_entailed")
            continue
        record["true_nli"] = true_nli
        record["counterfactual_nli"] = counterfactual_nli
        nli_valid.append(record)

    embedding_inputs = [
        text
        for record in nli_valid
        for text in (
            str(record["qplus"]),
            str(record["proposition_plus"]),
            str(record["pair"]["true_claim"]),
            str(record["qminus"]),
            str(record["proposition_minus"]),
            str(record["pair"]["counterfactual_claim"]),
        )
    ]
    embedding_outputs = embedder.encode(embedding_inputs) if embedding_inputs else []
    if len(embedding_outputs) != len(embedding_inputs):
        raise RuntimeError("Embedding output count mismatch for source query candidates")

    for index, record in enumerate(nli_valid):
        vectors = embedding_outputs[index * 6 : index * 6 + 6]
        candidate = record["candidate"]
        prefix = str(record["prefix"])
        question_proposition_similarity = min(
            cosine_similarity(vectors[0], vectors[1]),
            cosine_similarity(vectors[3], vectors[4]),
        )
        if question_proposition_similarity < min_question_proposition_similarity:
            failures.append(f"{prefix}:question_proposition_similarity")
            continue
        semantic_fidelity_similarity = min(
            cosine_similarity(vectors[1], vectors[2]),
            cosine_similarity(vectors[4], vectors[5]),
        )
        lexical = lexical_copy_scores(
            candidate.question_template,
            source_text,
            entity_values=(record["original"], record["counterfactual"]),
        )
        if float(lexical["five_gram_containment"]) > max_five_gram_containment:
            failures.append(f"{prefix}:five_gram_copy")
            continue
        if int(lexical["longest_common_token_run"]) > max_longest_common_token_run:
            failures.append(f"{prefix}:longest_copy_run")
            continue
        opening_tokens = normalized_tokens(candidate.question_template)[:3]
        scored[str(record["pair_id"])].append(
            ScoredCandidate(
                candidate=candidate,
                qplus=str(record["qplus"]),
                qminus=str(record["qminus"]),
                proposition_plus=str(record["proposition_plus"]),
                proposition_minus=str(record["proposition_minus"]),
                nli_true_entailment=float(record["true_nli"]["entailment"]),
                nli_counterfactual_entailment=float(
                    record["counterfactual_nli"]["entailment"]
                ),
                question_proposition_similarity=question_proposition_similarity,
                semantic_fidelity_similarity=semantic_fidelity_similarity,
                five_gram_containment=float(lexical["five_gram_containment"]),
                longest_common_token_run=int(lexical["longest_common_token_run"]),
                question_word_count=len(normalized_tokens(candidate.question_template)),
                opening_3gram=tuple(opening_tokens),
                opening_auxiliary=_opening_auxiliary(candidate.question_template),
            )
        )
    return dict(scored), failures


def select_diverse_source_candidates(
    pairs: Sequence[dict[str, Any]],
    scored_by_pair: dict[str, list[ScoredCandidate]],
) -> tuple[list[ScoredCandidate] | None, list[str]]:
    """联合选择 source 内语义最稳且句式不同的三个候选。"""

    pair_ids = [str(pair["pair_id"]) for pair in pairs]
    missing = [pair_id for pair_id in pair_ids if not scored_by_pair.get(pair_id)]
    if missing:
        return None, [f"no_valid_candidate:{pair_id}" for pair_id in missing]
    viable: list[tuple[tuple[Any, ...], tuple[ScoredCandidate, ...]]] = []
    for combination in itertools.product(*(scored_by_pair[pair_id] for pair_id in pair_ids)):
        templates = [item.candidate.question_template.casefold() for item in combination]
        if len(set(templates)) != len(templates):
            continue
        openings = [item.opening_3gram for item in combination]
        if len(set(openings)) != len(openings):
            continue
        auxiliaries = [item.opening_auxiliary for item in combination]
        if len(combination) > 1 and len(set(auxiliaries)) == 1:
            continue
        rank = (
            min(
                min(item.nli_true_entailment, item.nli_counterfactual_entailment)
                for item in combination
            ),
            min(item.question_proposition_similarity for item in combination),
            -max(item.five_gram_containment for item in combination),
            -max(item.longest_common_token_run for item in combination),
            min(item.semantic_fidelity_similarity for item in combination),
            -sum(item.question_word_count for item in combination),
            tuple(item.candidate.question_template for item in combination),
        )
        viable.append((rank, combination))
    if not viable:
        return None, ["source_question_diversity_gate"]
    _, selected = max(viable, key=lambda item: item[0])
    return list(selected), []


def _query_rows_for_source(
    pairs: Sequence[dict[str, Any]],
    selected: Sequence[ScoredCandidate],
    *,
    source_text: str,
    generation_metadata: dict[str, Any],
    sibling_identity_hash: str,
) -> list[dict[str, Any]]:
    pair_lookup = {str(pair["pair_id"]): pair for pair in pairs}
    rows: list[dict[str, Any]] = []
    for item in selected:
        pair = pair_lookup[item.candidate.pair_id]
        common = {
            "pair_id": pair["pair_id"],
            "fact_id": pair["fact_id"],
            "audit_id": pair["audit_id"],
            "doc_id": pair.get("doc_id"),
            "source_id": pair.get("source_id") or pair.get("doc_id"),
            "source_key": pair.get("source_key") or pair.get("source_id") or pair.get("doc_id"),
            "dataset": pair["dataset"],
            "group": pair["group"],
            "query_type": QUERY_TYPE,
            "true_claim": pair["true_claim"],
            "counterfactual_claim": pair["counterfactual_claim"],
            "expected_entity": pair["original_entity"],
            "original_entity": pair["original_entity"],
            "paired_counterfactual_entity": pair["counterfactual_entity"],
            "entity_type": pair["entity_type"],
            "perturbation_level": pair["perturbation_level"],
            "selection_tier": pair.get("selection_tier"),
            "quality_weight": pair.get("quality_weight"),
            "claim_validator_version": pair.get("claim_validator_version"),
            "question_template": item.candidate.question_template,
            "proposition_template": item.candidate.proposition_template,
            "retrieval_anchors": list(item.candidate.anchors),
            "reference_chunk_hash": sha256_text(source_text),
            "nli_true_entailment": item.nli_true_entailment,
            "nli_counterfactual_entailment": item.nli_counterfactual_entailment,
            "question_proposition_similarity": item.question_proposition_similarity,
            "semantic_fidelity_similarity": item.semantic_fidelity_similarity,
            "five_gram_containment": item.five_gram_containment,
            "longest_common_token_run": item.longest_common_token_run,
            "question_word_count": item.question_word_count,
            "question_opening_3gram": list(item.opening_3gram),
            "question_opening_auxiliary": item.opening_auxiliary,
            "query_pair_validation_status": "passed",
            "query_generation_protocol": PROTOCOL_VERSION,
            "query_prompt_version": PROMPT_VERSION,
            "sibling_identity_hash": sibling_identity_hash,
            "rewrite_response_hash": generation_metadata["response_hash"],
            "rewrite_provider_model_id": generation_metadata["provider_model_id"],
            "rewrite_provider_request_id": generation_metadata.get("provider_request_id"),
        }
        for claim_type, suffix, query, proposition in (
            ("true", "plus", item.qplus, item.proposition_plus),
            ("counterfactual", "minus", item.qminus, item.proposition_minus),
        ):
            rows.append(
                {
                    **common,
                    "query_id": f"q_{pair['pair_id']}_{QUERY_TYPE}_{suffix}",
                    "claim_type": claim_type,
                    "query": query,
                    "claim": pair["true_claim"] if claim_type == "true" else pair["counterfactual_claim"],
                    "proposition": proposition,
                    "counterfactual_entity": (
                        None if claim_type == "true" else pair["counterfactual_entity"]
                    ),
                    "source_text": pair["true_claim"],
                }
            )
    return rows


def _profile_identity_is_valid(identity: dict[str, Any]) -> bool:
    claimed = str(identity.get("profile_hash") or "")
    body = dict(identity)
    body.pop("profile_hash", None)
    return bool(re.fullmatch(r"[0-9a-f]{64}", claimed)) and sha256_obj(body) == claimed


def generate_diverse_paired_queries_file(
    *,
    paired_claims_path: str | Path,
    benchmark_path: str | Path,
    output_path: str | Path,
    chat_client: ChatClient,
    sibling_profile_identity: dict[str, Any],
    nli_predictor: NLIPredictor,
    nli_identity: dict[str, Any],
    embedder: Any,
    expected_provider_model_id: str,
    pairs_per_source: int = 3,
    candidates_per_pair: int = 3,
    correction_retries: int = 2,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    min_question_proposition_similarity: float = 0.80,
    max_five_gram_containment: float = 0.35,
    max_longest_common_token_run: int = 8,
    max_dataset_duplicate_template_rate: float = 0.01,
    max_dataset_opening_4gram_rate: float = 0.15,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """生成、断点保存并冻结多样化槽位问句。"""

    if pairs_per_source < 1 or candidates_per_pair != 3:
        raise ValueError("Protocol requires a positive source budget and exactly three candidates per pair")
    if correction_retries < 0:
        raise ValueError("correction_retries must be non-negative")
    if not _profile_identity_is_valid(sibling_profile_identity):
        raise ValueError("Sibling profile identity hash is missing or invalid")
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    error_path = output.with_suffix(".errors.jsonl")
    checkpoint_path = output.with_suffix(".generation_checkpoint.jsonl")
    checkpoint_manifest_path = output.with_suffix(".generation_checkpoint.manifest.json")
    claims_hash = sha256_file(paired_claims_path)
    benchmark_hash = sha256_file(benchmark_path)
    protocol_config = {
        "protocol_version": PROTOCOL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "query_type": QUERY_TYPE,
        "pairs_per_source": pairs_per_source,
        "candidates_per_pair": candidates_per_pair,
        "correction_retries": correction_retries,
        "temperature": float(temperature),
        "min_question_proposition_similarity": min_question_proposition_similarity,
        "max_five_gram_containment": max_five_gram_containment,
        "max_longest_common_token_run": max_longest_common_token_run,
        "max_dataset_duplicate_template_rate": max_dataset_duplicate_template_rate,
        "max_dataset_opening_4gram_rate": max_dataset_opening_4gram_rate,
    }
    identity = {
        "input_claims_hash": claims_hash,
        "input_benchmark_hash": benchmark_hash,
        "sibling_profile": sibling_profile_identity,
        "nli_identity": nli_identity,
        "protocol": protocol_config,
        "expected_provider_model_id": expected_provider_model_id,
    }
    identity_hash = sha256_obj(identity)
    if resume and not force and output.is_file() and manifest_path.is_file():
        existing = read_json(manifest_path)
        if str(existing.get("generation_identity_hash") or "") != identity_hash:
            raise RuntimeError("Existing diverse queries do not match the requested generation identity")
        return {**existing, "output_path": str(output), "skipped_existing": True}
    if not resume and not force and any(
        path.exists()
        for path in (output, manifest_path, checkpoint_path, checkpoint_manifest_path)
    ):
        raise RuntimeError(
            "Diverse query artifacts already exist while resume is disabled; "
            "use --force to start a clean generation."
        )
    if force:
        for path in (output, manifest_path, error_path, checkpoint_path, checkpoint_manifest_path):
            path.unlink(missing_ok=True)

    benchmark_lookup = {
        str(row.get("source_key") or row.get("source_id") or row.get("doc_id") or ""): str(row.get("text") or "")
        for row in read_jsonl(benchmark_path)
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in read_jsonl(paired_claims_path):
        source_key = str(pair.get("source_key") or pair.get("source_id") or pair.get("doc_id") or "")
        if not source_key:
            raise RuntimeError(f"Paired claim is missing source_key: {pair.get('pair_id')}")
        grouped[source_key].append(pair)
    for source_key, pairs in grouped.items():
        if len(pairs) != pairs_per_source:
            raise RuntimeError(
                f"Diverse query generation requires exactly {pairs_per_source} pairs per source: "
                f"{source_key} has {len(pairs)}"
            )
        if not benchmark_lookup.get(source_key):
            raise RuntimeError(f"Benchmark source text is missing: {source_key}")
        pairs.sort(key=lambda pair: str(pair["pair_id"]))

    checkpoint_rows: dict[str, dict[str, Any]] = {}
    if resume and checkpoint_path.is_file():
        if not checkpoint_manifest_path.is_file():
            raise RuntimeError("Generation checkpoint manifest is missing")
        checkpoint_manifest = read_json(checkpoint_manifest_path)
        if str(checkpoint_manifest.get("generation_identity_hash") or "") != identity_hash:
            raise RuntimeError("Generation checkpoint identity mismatch")
        for record in read_jsonl(checkpoint_path):
            source_key = str(record.get("source_key") or "")
            if not source_key or source_key in checkpoint_rows:
                raise RuntimeError("Generation checkpoint contains missing/duplicate source_key")
            checkpoint_rows[source_key] = record
    elif checkpoint_manifest_path.is_file():
        raise RuntimeError(
            "Generation checkpoint manifest exists without a resumable checkpoint; "
            "use --force to start clean."
        )
    else:
        write_json(
            {
                "generation_identity": identity,
                "generation_identity_hash": identity_hash,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            checkpoint_manifest_path,
        )

    errors: list[dict[str, Any]] = []
    sibling_calls = 0
    ordered_sources = sorted(grouped)
    for source_index, source_key in enumerate(ordered_sources, start=1):
        if source_key in checkpoint_rows:
            continue
        pairs = grouped[source_key]
        source_text = benchmark_lookup[source_key]
        failure_reasons: list[str] = []
        selected: list[ScoredCandidate] | None = None
        generation_metadata: dict[str, Any] | None = None
        for correction_attempt in range(correction_retries + 1):
            prompt = build_generation_prompt(
                pairs,
                correction_reasons=failure_reasons,
            )
            result = chat_client.chat_with_metadata(
                prompt,
                temperature=float(temperature),
                timeout=timeout,
                max_tokens=max_tokens,
            )
            sibling_calls += 1
            provider_model_id = str(getattr(result, "provider_model_id", None) or "")
            if provider_model_id != expected_provider_model_id:
                raise RuntimeError(
                    "Sibling provider model identity drift: "
                    f"expected={expected_provider_model_id!r}, actual={provider_model_id!r}"
                )
            configured_version = str(
                sibling_profile_identity.get("model_version") or ""
            )
            if configured_version:
                response_error = strict_response_metadata_error(
                    getattr(result, "content", None),
                    provider_model_id=provider_model_id,
                    provider_request_id=getattr(result, "provider_request_id", None),
                    called_at=getattr(result, "called_at", None),
                    expected_model_id=expected_provider_model_id,
                    configured_model_version=configured_version,
                )
            else:
                response_error = generator_response_error(
                    getattr(result, "content", None),
                    provider_model_id=provider_model_id,
                    expected_model_id=expected_provider_model_id,
                    require_provider_model_id=True,
                )
            if response_error:
                raise RuntimeError(
                    f"Sibling response rejected: {response_error}"
                )
            raw = str(getattr(result, "content", "") or "")
            try:
                candidates = parse_generation_response(
                    raw,
                    [str(pair["pair_id"]) for pair in pairs],
                )
                scored, scoring_failures = score_source_candidates(
                    pairs,
                    candidates,
                    source_text=source_text,
                    nli_predictor=nli_predictor,
                    embedder=embedder,
                    min_question_proposition_similarity=min_question_proposition_similarity,
                    max_five_gram_containment=max_five_gram_containment,
                    max_longest_common_token_run=max_longest_common_token_run,
                )
                selected, diversity_failures = select_diverse_source_candidates(pairs, scored)
                failure_reasons = [*scoring_failures, *diversity_failures]
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                selected = None
                failure_reasons = [f"{type(exc).__name__}:{exc}"]
            generation_metadata = {
                "response_hash": sha256_text(raw),
                "provider_model_id": provider_model_id,
                "provider_request_id": getattr(result, "provider_request_id", None),
                "system_fingerprint": getattr(result, "system_fingerprint", None),
                "called_at": getattr(result, "called_at", None),
                "input_tokens": getattr(result, "input_tokens", None),
                "output_tokens": getattr(result, "output_tokens", None),
                "finish_reason": getattr(result, "finish_reason", None),
                "latency_ms": getattr(result, "latency_ms", None),
                "transport_retry_count": int(getattr(result, "retry_count", 0) or 0),
                "correction_attempt": correction_attempt,
            }
            if selected is not None:
                break
            errors.append(
                {
                    "source_key": source_key,
                    "attempt": correction_attempt,
                    "response_hash": sha256_text(raw),
                    "failure_reasons": failure_reasons,
                }
            )
        if selected is None or generation_metadata is None:
            write_jsonl(errors, error_path)
            raise RuntimeError(
                f"Diverse query generation failed closed for source {source_key}: "
                f"{failure_reasons[:5]}"
            )
        rows = _query_rows_for_source(
            pairs,
            selected,
            source_text=source_text,
            generation_metadata=generation_metadata,
            sibling_identity_hash=str(sibling_profile_identity["profile_hash"]),
        )
        record = {
            "source_key": source_key,
            "source_input_hash": sha256_obj(
                [
                    {
                        "pair_id": pair["pair_id"],
                        "true_claim": pair["true_claim"],
                        "counterfactual_claim": pair["counterfactual_claim"],
                    }
                    for pair in pairs
                ]
            ),
            "generation": generation_metadata,
            "rows": rows,
        }
        write_jsonl([record], checkpoint_path, append=True)
        checkpoint_rows[source_key] = record
        LOGGER.info(
            "Generated diverse queries source=%s progress=%s/%s",
            source_key,
            source_index,
            len(ordered_sources),
        )

    output_rows = [
        row
        for source_key in ordered_sources
        for row in checkpoint_rows[source_key]["rows"]
    ]
    templates = [
        str(row["question_template"])
        for row in output_rows
        if str(row.get("claim_type")) == "true"
    ]
    diversity = diversity_statistics(templates)
    if diversity["duplicate_template_rate"] > max_dataset_duplicate_template_rate:
        raise RuntimeError(f"Dataset duplicate-template gate failed: {diversity}")
    if diversity["dominant_opening_4gram_rate"] > max_dataset_opening_4gram_rate:
        raise RuntimeError(f"Dataset opening-concentration gate failed: {diversity}")
    expected_queries = len(grouped) * pairs_per_source * 2
    if len(output_rows) != expected_queries:
        raise RuntimeError(
            f"Diverse query output budget mismatch: expected={expected_queries}, actual={len(output_rows)}"
        )
    query_ids = [str(row["query_id"]) for row in output_rows]
    if len(set(query_ids)) != len(query_ids):
        raise RuntimeError("Diverse query output contains duplicate query_id values")
    write_jsonl_atomic(output_rows, output)
    write_jsonl(errors, error_path)
    by_group = Counter(str(row["group"]) for row in output_rows)
    manifest = {
        "output_path": str(output),
        "error_path": str(error_path),
        "checkpoint_path": str(checkpoint_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query_generation_protocol": PROTOCOL_VERSION,
        "query_prompt_version": PROMPT_VERSION,
        "query_type": QUERY_TYPE,
        "queries": len(output_rows),
        "pairs": len(output_rows) // 2,
        "sources": len(grouped),
        "queries_by_group": dict(by_group),
        "pairs_per_source": pairs_per_source,
        "queries_per_source": pairs_per_source * 2,
        "sibling_calls": sibling_calls,
        "sibling_profile": sibling_profile_identity,
        "nli_identity": nli_identity,
        "diversity": diversity,
        "protocol_config": protocol_config,
        "generation_identity": identity,
        "generation_identity_hash": identity_hash,
        "input_claims_hash": claims_hash,
        "input_benchmark_hash": benchmark_hash,
        "output_hash": sha256_file(output),
        "errors": len(errors),
    }
    write_json(manifest, manifest_path)
    return manifest
