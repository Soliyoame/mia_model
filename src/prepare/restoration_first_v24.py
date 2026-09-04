"""v24 query-local reconstruction and pre-split eligibility primitives.

The module is intentionally offline and membership blind.  It reuses only the
frozen v22 source-pool reader and low-level text helpers; v23 pair fields such
as ``effective_type`` and the old counterfactual claim never enter the v24
fact/pair contract.  A real Luna integration can provide a candidate provider
and the two proposition-local judges through the small callable interfaces
below.  Tests use deterministic mocks.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..attack.entity_extractor import EntityExtractor
from ..attack.restoration_first_v23 import (
    bounded_occurrence_count,
    content_tokens,
    segment_propositions,
)
from ..prepare.restoration_first_v23 import FrozenSourcePoolReader, _pool_contract
from ..utils.hash import canonical_json, sha256_file, sha256_obj, sha256_text
from ..utils.io import load_yaml, write_json


CONFIG_PATH = Path("configs/restoration_first_v24.yaml")
DATASET_ORDER = ("edgar", "enron", "pubmed")
GROUP_COUNTS = {"KB_Member": 1000, "True_Non_Member": 1000, "Reserve": 250}
PAIRS_PER_SOURCE = 3
DEFAULT_MAX_CANDIDATE_FACTS_PER_SOURCE = 8
QUERY_POLARITIES = ("Q_plus", "Q_minus")
FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "effective_type",
        "counterfactual_entity",
        "counterfactual_claim",
        "membership",
        "membership_label",
        "group",
        "split",
        "retriever_output",
        "retrieval_score",
        "victim_response",
        "attack_score",
        "attack_auc",
        "auc",
    }
)
UNRESOLVED_REFERENCE_RE = re.compile(
    r"\b(?:this|that|these|those|here|there|above|below|aforementioned|former|latter|"
    r"he|she|it|they|we|us|our|ours|ourselves|i|me|my|mine|myself|"
    r"theirs|themselves|herein|therein|thereof|thereafter)\b",
    re.IGNORECASE,
)
PROPOSITION_REFERENCE_RE = re.compile(
    r"\b(?:above|below|aforementioned|former|latter|we|us|our|ours|ourselves|i|"
    r"me|my|mine|myself|herein|therein|thereof|thereafter)\b",
    re.IGNORECASE,
)
GENERIC_DOCUMENT_REFERENCE_RE = re.compile(
    r"\b(?:[Tt]he\s+Company|[Tt]he\s+following)\b|^[Tt]he\s+period\b"
)
INCOMPLETE_TEMPORAL_REFERENCE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.\s*$",
    re.IGNORECASE,
)
HEADING_SENTENCE_GLUE_RE = re.compile(
    r"\b(?:Breed|Genes|Study|Methods|Results|Introduction|Discussion|Background)\s+"
    r"(?:Some|The|A|An|This|These)\b"
)
UNDEFINED_ACRONYM_CITATION_RE = re.compile(r"\b([A-Z]{2,})\b\s*\[\s*\d")
FIRST_PERSON_REFERENCE_RE = re.compile(
    r"\b(?:we|us|our|ours|ourselves|i|me|my|mine|myself)\b", re.IGNORECASE
)
BARE_COMPANY_REFERENCE_RE = re.compile(r"\bthe\s+company\b", re.IGNORECASE)
QUOTED_FIRST_PERSON_ALIAS_RE = re.compile(
    r"[\"'\u2018\u2019\u201c\u201d]\s*(?:we|us|our|ours|i|me|my|mine)\s*,?\s*"
    r"[\"'\u2018\u2019\u201c\u201d]",
    re.IGNORECASE,
)
INVALID_MODAL_COORDINATION_RE = re.compile(
    r"\b(?:will|would|shall|should|can|could|may|might|must)\s+[^?]*\band\s+"
    r"(?:will|would|shall|should|can|could|may|might|must)\s+"
    r"(?:be|have|has|do|does|receive|remain|continue|appear)\b",
    re.IGNORECASE,
)
INVALID_DO_COORDINATION_RE = re.compile(
    r"\bdo\s+[^?]*\bor\s+are\s+\w+", re.IGNORECASE
)
MALFORMED_REPORTATIVE_TAIL_RE = re.compile(
    r",\s*[A-Z][^,?]{0,80}\b(?:has|have|had)\s+(?:learned|reported|found)\s*$",
    re.IGNORECASE,
)
EMBEDDED_CLAUSE_CAPITALIZATION_RE = re.compile(
    r"^Is\s+it\s+correct\s+that\s+(?:In|On|At|During|Before|After)\b"
)
QUESTION_START_RE = re.compile(
    r"^(?:is|are|was|were|do|does|did|has|have|had|can|could|will|would|should|"
    r"may|might|must|shall|is it correct that)\b",
    re.IGNORECASE,
)
CAPITALIZED_PHRASE_RE = re.compile(
    r"(?<!\w)(?:[A-Z][A-Za-z0-9&.'/-]*)(?:\s+[A-Z][A-Za-z0-9&.'/-]*)*"
)
QUESTION_FRAME_WORDS = frozenset(
    {
        "a", "after", "an", "and", "are", "at", "before", "between", "can",
        "correct", "could", "did", "does", "do", "during", "from", "had", "has",
        "have", "in", "is", "it", "may", "might", "must", "on", "shall", "should",
        "since", "the", "until", "was", "were", "will", "would",
    }
)
ATTACK_EXPOSING_RE = re.compile(
    r"\b(?:membership|knowledge\s+base|hidden\s+context|retriever|system\s+prompt|"
    r"victim|attack\s+score|private\s+document)\b",
    re.IGNORECASE,
)
DETERMINATE_CONTEXT_RE = re.compile(
    r"\b(?:sole|唯一|designated|authorized|authorised|record(?:ed)?|lists?|"
    r"identif(?:y|ies|ied)|incorporated|jurisdiction|cfo|ceo|during|fiscal|"
    r"year|quarter|period|as the|appointed|assigned|registered)\b",
    re.IGNORECASE,
)
NEGATION_RE = re.compile(r"\b(?:no|not|never|neither|nor)\b|n't", re.IGNORECASE)
MODALITY_RE = re.compile(r"\b(?:can|could|may|might|must|shall|should|will|would)\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d+(?:[./-]\d+)*\b")
CITATION_RE = re.compile(r"\[\s*\d+(?:\s*[-,]\s*\d+)*\s*\]")
TEMPORAL_MARKER_RE = re.compile(
    r"\b(?:during|before|after|since|until|between|fiscal|quarter|year|month|week|day|january|"
    r"february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)
SCOPE_RE = re.compile(r"\b(?:only|all|each|any|every|exactly|at\s+least|at\s+most|sole)\b", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CandidateProvider(Protocol):
    def __call__(self, fact: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]: ...


class RoleJudge(Protocol):
    def __call__(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


class EligibilityJudge(Protocol):
    def __call__(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass
class SemanticSimilarityScorer:
    """Embedding-backed semantic scorer; lexical fallback is forbidden."""

    embedder: Any
    model_name: str
    revision: str | None
    backend: str
    local_files_only: bool
    threshold: float = 0.80
    _cache: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __call__(self, left: str, right: str) -> float:
        from ..rag.embeddings import cosine_similarity

        score = cosine_similarity(self._encode(left), self._encode(right))
        if not math.isfinite(score):
            raise RuntimeError("v24_semantic_scorer_non_finite_score")
        return score

    def _encode(self, text: str) -> Any:
        key = str(text)
        if key not in self._cache:
            vectors = self.embedder.encode([key])
            if getattr(vectors, "ndim", None) != 2 or tuple(getattr(vectors, "shape", ()))[:1] != (1,):
                raise RuntimeError("v24_semantic_scorer_invalid_embedding_shape")
            self._cache[key] = vectors[0]
        return self._cache[key]

    def identity(self) -> dict[str, Any]:
        return {
            "kind": "sentence_transformers_cosine",
            "backend": self.backend,
            "model": self.model_name,
            "revision": self.revision,
            "local_files_only": self.local_files_only,
            "threshold": self.threshold,
        }

    def close(self) -> None:
        closer = getattr(self.embedder, "close", None)
        if callable(closer):
            closer()
        self._cache.clear()


def build_v24_semantic_similarity(project_root: str | Path = ".") -> SemanticSimilarityScorer:
    """Build the configured real semantic scorer for v24 construction."""

    config = load_v24_config(project_root)
    semantic = config.get("semantic_similarity")
    if not isinstance(semantic, Mapping):
        raise RuntimeError("v24_semantic_similarity_config_missing")
    backend = str(semantic.get("backend") or "").casefold()
    model_name = str(semantic.get("model") or "").strip()
    allowed_backends = {"auto", "sentence_transformers", "sentence-transformers", "sentence-transformer"}
    if backend not in allowed_backends:
        raise RuntimeError("v24_semantic_similarity_requires_real_embedding_backend")
    if not model_name or model_name.casefold() in {"hash", "hashing"}:
        raise RuntimeError("v24_semantic_similarity_model_invalid")
    revision = str(semantic.get("revision")) if semantic.get("revision") else None
    local_files_only = bool(semantic.get("local_files_only", True))
    threshold = float(config.get("eligibility", {}).get("query_similarity_threshold", 0.80))
    from ..rag.embeddings import build_embedding_model

    embedder = build_embedding_model(
        model_name,
        backend=backend,
        local_files_only=local_files_only,
        revision=revision,
        query_instruction=str(semantic.get("query_instruction") or ""),
    )
    return SemanticSimilarityScorer(
        embedder=embedder,
        model_name=model_name,
        revision=revision,
        backend=backend,
        local_files_only=local_files_only,
        threshold=threshold,
    )


def build_candidate_prompt(fact: Mapping[str, Any]) -> str:
    """Build the membership-blind Luna reconstruction prompt."""

    _reject_forbidden(fact)
    fields = {
        "upstream_pair_id": str(fact.get("upstream_pair_id") or ""),
        "true_claim": str(fact.get("true_claim") or ""),
        "original_entity": str(fact.get("original_entity") or ""),
        "slotted_true_claim": str(fact.get("slotted_true_claim") or ""),
    }
    return (
        "You are a query-local counterfactual reconstruction model for a privacy "
        "benchmark. Use only the supplied source-grounded proposition and entity slot.\n"
        "Generate exactly three independent candidate packages. The replacement must "
        "be contextually plausible in exactly the same grammatical and semantic role; "
        "do not use entity type taxonomies and do not require classic NLI contradiction. "
        "Keep one canonical proposition frame and change only {ENTITY}. Q+ verifies the "
        "true proposition and Q- verifies the counterfactual proposition. Questions must "
        "be natural self-contained polar questions with exactly one question mark. "
        "The canonical template must contain exactly one literal {ENTITY} token; if the "
        "original is repeated, rewrite the proposition equivalently so it appears in only "
        "that slot. Preserve every factual number, date, temporal relation, negation, "
        "scope qualifier, and semantic modal (can/could/may/might/must/shall/should/will/"
        "would). Do not introduce or remove a modal merely to form a question. Start each "
        "question with a polar auxiliary, mention its target entity exactly once, and never "
        "use unresolved pronouns or deictic phrases such as this/that/these/those/he/she/"
        "it/they/I/we/my/our or document-bound wording such as herein, the Company, the "
        "following, or an antecedent-free the period; the fixed phrase 'Is it correct that' "
        "is the only permitted expletive. When the input uses first-person or document-bound "
        "references, replace them only with a source-grounded role description such as the "
        "reporting company or the sender; never substitute the bare phrase 'the company' and "
        "never invent an identity. Do not merge a heading with a sentence, emit a fragment, "
        "put a bibliography citation inside the target entity slot, coordinate incompatible "
        "question auxiliaries, or append a reportative tail such as 'VentureWire has learned'. "
        "When a proposition contains multiple modal clauses, prefer the fixed frame 'Is it "
        "correct that <proposition>?' and keep every source modal inside that proposition; "
        "never front one auxiliary and then coordinate a second auxiliary (for example, "
        "never write 'Will ... and should ...' or 'Do ... or are ...'). Do not drop or "
        "invent a modal while making the surface natural. "
        "After 'Is it correct that', lowercase an initial preposition such as in/on/during, "
        "or prefer a direct polar-auxiliary question. "
        "Do not add factual entities. Return one to three retrieval anchors only; anchors "
        "are diagnostics and must not be appended mechanically to a question. "
        "Return JSON only with this shape:\n"
        '{"candidates":[{"replacement_entity":"...",'
        '"canonical_proposition_template":"...{ENTITY}...",'
        '"q_plus_text":"...?","q_minus_text":"...?",'
        '"retrieval_anchors":["..."],'
        '"true_grounding":{"entailment_probability":0.95,"top_label":"entailment"},'
        '"contextual_role_compatibility":{"compatible":true,"plausibility":"strong"},'
        '"correction_eligibility":{"correction_eligible":true,'
        '"slot_determinacy":"strong","open_world_ambiguity":"low",'
        '"reason_code":"..."},"canonical_pair_nli_relation":"neutral"}]}\n\n'
        f"Input:\n{canonical_json(fields)}"
    )


def build_correction_prompt(
    fact: Mapping[str, Any],
    rejected_candidates: Sequence[Mapping[str, Any]],
) -> str:
    """Build the single preregistered semantic-correction retry prompt."""

    _reject_forbidden(fact)
    evidence: list[dict[str, Any]] = []
    allowed_fields = (
        "replacement_entity",
        "canonical_proposition_template",
        "q_plus_text",
        "q_minus_text",
    )
    for item in rejected_candidates:
        candidate = item.get("candidate")
        if not isinstance(candidate, Mapping):
            continue
        evidence.append(
            {
                "candidate": {
                    key: candidate.get(key)
                    for key in allowed_fields
                },
                "rejection_reasons": sorted(
                    str(reason) for reason in item.get("rejection_reasons", [])
                ),
            }
        )
    fields = {
        "upstream_pair_id": str(fact.get("upstream_pair_id") or ""),
        "true_claim": str(fact.get("true_claim") or ""),
        "original_entity": str(fact.get("original_entity") or ""),
        "slotted_true_claim": str(fact.get("slotted_true_claim") or ""),
        "rejected_candidates": evidence,
    }
    return (
        build_candidate_prompt(fact)
        + "\n\nThis is the one allowed semantic correction retry. Correct every listed "
        "validator failure without weakening or changing the source-grounded proposition. "
        "For modal-coordination or natural-question failures, rewrite the whole question "
        "with the fixed 'Is it correct that <proposition>?' frame while retaining every "
        "modal word inside the proposition; never repeat forms such as 'Will ... and should '"
        "or 'Do ... or are ...'. Return three revised candidate packages in the exact same "
        "JSON schema. Do not "
        "repeat a rejected surface form.\nCorrection input:\n"
        + canonical_json(fields)
    )


@dataclass
class LunaCandidateProvider:
    """Callable Luna adapter with secret-free transport accounting."""

    client: Any
    profile: Mapping[str, Any]
    max_candidates: int = 3
    logical_api_calls: int = 0
    physical_attempts: int = 0
    transport_retry_count: int = 0
    provider_model_ids: set[str] = field(default_factory=set)
    failures: list[str] = field(default_factory=list)

    def __call__(self, fact: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        return self._request_candidates(build_candidate_prompt(fact))

    def correct(
        self,
        fact: Mapping[str, Any],
        rejected_candidates: Sequence[Mapping[str, Any]],
    ) -> Sequence[Mapping[str, Any]]:
        return self._request_candidates(build_correction_prompt(fact, rejected_candidates))

    def _request_candidates(self, prompt: str) -> Sequence[Mapping[str, Any]]:
        self.logical_api_calls += 1
        try:
            result = self.client.chat_with_metadata(
                prompt,
                temperature=0.0,
                timeout=float(self.profile.get("timeout", 120.0)),
                max_tokens=int(self.profile.get("max_tokens", 2048)),
            )
            raw = str(getattr(result, "content", result) or "")
            retry_count = int(getattr(result, "retry_count", 0) or 0)
            provider_model_id = getattr(result, "provider_model_id", None)
            self.transport_retry_count += retry_count
            self.physical_attempts += retry_count + 1
            if provider_model_id:
                self.provider_model_ids.add(str(provider_model_id))
            from ..llm.openai_compatible import parse_json_object

            payload = parse_json_object(raw)
            candidates = payload.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                raise ValueError("v24_luna_candidates_missing")
            if len(candidates) > self.max_candidates:
                raise ValueError("v24_luna_candidate_count_exceeded")
            normalized: list[dict[str, Any]] = []
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    raise ValueError("v24_luna_candidate_schema")
                item = dict(candidate)
                _reject_forbidden(item, path="luna_candidate")
                item["provider_model_id"] = str(provider_model_id) if provider_model_id else None
                item["transport_retry_count"] = retry_count
                normalized.append(item)
            return normalized
        except Exception as exc:
            self.failures.append(f"{type(exc).__name__}:{exc}")
            raise

    def stats(self) -> dict[str, Any]:
        return {
            "logical_api_calls": self.logical_api_calls,
            "physical_attempts": self.physical_attempts,
            "transport_retry_count": self.transport_retry_count,
            "provider_model_ids": sorted(self.provider_model_ids),
            "profile_name": self.profile.get("profile_name"),
            "configured_model": self.profile.get("model"),
            "failures": list(self.failures),
        }


def build_luna_candidate_provider(
    project_root: str | Path = ".",
    *,
    profile_name: str | None = None,
    client: Any | None = None,
) -> LunaCandidateProvider:
    """Construct the configured Luna provider without exposing credentials."""

    config = load_v24_config(project_root)
    if client is None:
        from ..llm.factory import build_role_chat_client, load_llm_profiles

        profiles = load_llm_profiles(config)
        selected = profile_name or str(config.get("llm", {}).get("profile") or "luna_query_generator")
        client, profile = build_role_chat_client(profiles, "sibling", profile_name=selected)
    else:
        profile = {
            "profile_name": profile_name or "mock",
            "model": str(config.get("llm", {}).get("model") or "mock"),
            "timeout": config.get("llm", {}).get("timeout", 120),
            "max_tokens": config.get("llm", {}).get("max_tokens", 2048),
        }
    return LunaCandidateProvider(client=client, profile=profile)


def _norm(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _boundary_count(text: str, value: str) -> int:
    return bounded_occurrence_count(text, value)


def _mask_entity_mentions(claim: str, entity: str) -> str:
    if not claim or not entity:
        return claim
    pattern = re.compile(rf"(?<!\w){re.escape(entity)}(?!\w)")
    return pattern.sub("{ENTITY}", claim)


def _candidate_spans(sentence: str, extractor: EntityExtractor) -> list[dict[str, Any]]:
    """合并规则候选与通用专名 span；不写入任何实体类型标签。"""

    candidates = list(extractor._regex_candidates(sentence))  # type: ignore[attr-defined]
    seen = {(int(item.get("start", -1)), int(item.get("end", -1))) for item in candidates}
    for match in CAPITALIZED_PHRASE_RE.finditer(sentence):
        value = match.group(0).strip(" .?!,:;\t\r\n")
        start = match.start()
        end = start + len(value)
        if value and (start, end) not in seen:
            candidates.append({"text": value, "start": start, "end": end})
            seen.add((start, end))
    return candidates


def _candidate_fact_quality_reasons(fact: Mapping[str, Any]) -> list[str]:
    """检查 adapter 输入是否满足既有完整命题与合法实体槽要求。"""

    claim = str(fact.get("true_claim") or "").strip()
    original = str(fact.get("original_entity") or "").strip()
    reasons: list[str] = []
    if INCOMPLETE_TEMPORAL_REFERENCE_RE.search(claim):
        reasons.append("candidate_fact_incomplete_temporal_reference")
    if HEADING_SENTENCE_GLUE_RE.search(claim):
        reasons.append("candidate_fact_heading_sentence_glue")
    if CITATION_RE.search(original) or UNDEFINED_ACRONYM_CITATION_RE.search(original):
        reasons.append("candidate_fact_entity_contains_citation")
    return sorted(set(reasons))


def _canonical_proposition_quality_reasons(
    canonical: str,
    true_claim: str,
) -> list[str]:
    """检查 canonical proposition 是否完整、自包含且没有文档外指代。"""

    proposition = str(canonical or "").strip()
    reference_text = QUOTED_FIRST_PERSON_ALIAS_RE.sub("", proposition)
    reasons: list[str] = []
    if PROPOSITION_REFERENCE_RE.search(reference_text):
        reasons.append("canonical_unresolved_reference")
    if GENERIC_DOCUMENT_REFERENCE_RE.search(proposition):
        reasons.append("canonical_unresolved_reference")
    if (
        FIRST_PERSON_REFERENCE_RE.search(str(true_claim or ""))
        and BARE_COMPANY_REFERENCE_RE.search(proposition)
    ):
        reasons.append("canonical_unresolved_reference")
    if INCOMPLETE_TEMPORAL_REFERENCE_RE.search(proposition):
        reasons.append("canonical_incomplete_temporal_reference")
    if HEADING_SENTENCE_GLUE_RE.search(proposition):
        reasons.append("canonical_heading_sentence_glue")
    if not content_tokens(proposition):
        reasons.append("canonical_incomplete_proposition")
    return sorted(set(reasons))


def _reject_forbidden(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).casefold()
            if key_text in FORBIDDEN_INPUT_KEYS:
                raise ValueError(f"v24_forbidden_input_field:{path}.{key}")
            _reject_forbidden(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_forbidden(nested, path=f"{path}[{index}]")


def load_v24_config(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_yaml(root / CONFIG_PATH)
    if not isinstance(config, Mapping):
        raise RuntimeError("v24_config_invalid")
    if config.get("protocol_version") != "pcv-mia-v24":
        raise RuntimeError("v24_config_identity_invalid")
    if config.get("specification_version") != "pcv-restoration-first-v24-pre-split-eligibility-r1":
        raise RuntimeError("v24_config_specification_invalid")
    if config.get("eligibility", {}).get("nli_contradiction_required") is not False:
        raise RuntimeError("v24_nli_contradiction_gate_forbidden")
    if config.get("stealth_diagnostics", {}).get("hard_gate") is not False:
        raise RuntimeError("v24_stealth_diagnostics_must_not_be_hard_gate")
    semantic = config.get("semantic_similarity")
    allowed_backends = {"auto", "sentence_transformers", "sentence-transformers", "sentence-transformer"}
    if not isinstance(semantic, Mapping) or str(semantic.get("backend") or "").casefold() not in allowed_backends:
        raise RuntimeError("v24_semantic_similarity_config_invalid")
    model_name = str(semantic.get("model") or "").strip().casefold()
    if not model_name or model_name in {"hash", "hashing"}:
        raise RuntimeError("v24_semantic_similarity_model_invalid")
    if int(config.get("eligibility", {}).get("semantic_correction_retries", -1)) != 1:
        raise RuntimeError("v24_semantic_correction_retry_must_equal_one")
    if "max_candidate_facts_per_source" not in config.get("eligibility", {}):
        raise RuntimeError("v24_max_candidate_facts_per_source_missing")
    get_max_candidate_facts_per_source(config)
    return dict(config)


def get_max_candidate_facts_per_source(config: Mapping[str, Any]) -> int:
    """Return the single frozen source-local Luna processing budget."""

    value = config.get("eligibility", {}).get(
        "max_candidate_facts_per_source", DEFAULT_MAX_CANDIDATE_FACTS_PER_SOURCE
    )
    try:
        budget = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("v24_max_candidate_facts_per_source_invalid") from exc
    if budget < PAIRS_PER_SOURCE:
        raise RuntimeError("v24_max_candidate_facts_per_source_too_small")
    return budget


def _source_identity(source: Mapping[str, Any]) -> dict[str, str]:
    required = {"dataset", "source_key", "source_order_rank", "full_text"}
    if not required.issubset(source):
        raise ValueError("v24_source_fields_missing")
    _reject_forbidden(source)
    text = str(source["full_text"])
    return {
        "dataset": str(source["dataset"]),
        "source_key": str(source["source_key"]),
        "source_order_rank": str(source["source_order_rank"]),
        "source_hash": sha256_text(text),
        "normalized_text_hash": sha256_text(_norm(text)),
    }


def enumerate_candidate_facts(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Enumerate source-grounded proposition/entity slots without old type data."""

    identity = _source_identity(source)
    text = str(source["full_text"])
    extractor = EntityExtractor(enable_ner=False)
    facts: list[dict[str, Any]] = []
    for chunk_rank, proposition in _iter_source_propositions(source):
        sentence = proposition["text"]
        if _candidate_fact_quality_reasons({"true_claim": sentence}):
            continue
        source_start = int(proposition.get("source_offset", 0)) + int(proposition["start"])
        if source_start < 0 or text[source_start:source_start + len(sentence)] != sentence:
            source_start = text.find(sentence)
        if source_start < 0:
            # 命题必须能从完整 source 独立复核，不能只依赖 chunk 局部文本。
            continue
        for entity in _candidate_spans(sentence, extractor):
            original = str(entity.get("text") or "").strip()
            start = int(entity.get("start", -1))
            end = int(entity.get("end", -1))
            if not original or start < 0 or end <= start or sentence[start:end] != original:
                continue
            if _boundary_count(text, original) < 1:
                continue
            fact = {
                **identity,
                "upstream_pair_id": sha256_obj(
                    {
                        "kind": "v24_upstream_fact",
                        "dataset": identity["dataset"],
                        "source_key": identity["source_key"],
                        "chunk_rank": chunk_rank,
                        "proposition_start": source_start,
                        "proposition_text": sentence,
                        "original_span": [start, end],
                    }
                ),
                "true_claim": sentence,
                "slotted_true_claim": _mask_entity_mentions(sentence, original),
                "original_entity": original,
                "original_span": [source_start + start, source_start + end],
                "proposition_span": [source_start, source_start + len(sentence)],
                "chunk_rank": chunk_rank,
                "fact_order": len(facts),
            }
            if _candidate_fact_quality_reasons(fact):
                continue
            facts.append(fact)
    facts.sort(
        key=lambda row: (
            int(row["chunk_rank"]),
            int(row["proposition_span"][0]),
            int(row["original_span"][0]),
            _norm(str(row["original_entity"])),
            str(row["upstream_pair_id"]),
        )
    )
    for index, fact in enumerate(facts):
        fact["fact_order"] = index
    return facts


def _iter_source_propositions(source: Mapping[str, Any]) -> Iterable[tuple[int, dict[str, Any]]]:
    full_text = str(source.get("full_text") or "")
    chunks = source.get("chunks")
    if isinstance(chunks, list) and chunks:
        for chunk in sorted(chunks, key=lambda item: int(item.get("chunk_rank", 0))):
            row = chunk.get("row") if isinstance(chunk, Mapping) else None
            chunk_text = row.get("text") if isinstance(row, Mapping) else None
            if not isinstance(chunk_text, str):
                continue
            chunk_start = full_text.find(chunk_text)
            for proposition in segment_propositions(chunk_text):
                proposition["source_offset"] = chunk_start if chunk_start >= 0 else 0
                yield int(chunk.get("chunk_rank", 0)), proposition
        return
    for proposition in segment_propositions(str(source.get("full_text") or "")):
        yield 0, proposition


def _replace_exact(template: str, entity: str) -> str:
    return template.replace("{ENTITY}", entity)


def _canonical_pair(
    true_claim: str, original: str, replacement: str, template: str
) -> tuple[str, str]:
    if not original.strip() or not replacement.strip():
        raise ValueError("v24_entity_slot_empty")
    if template.count("{ENTITY}") != 1:
        raise ValueError("v24_canonical_template_slot_count")
    if not isinstance(template, str) or not template.strip():
        raise ValueError("v24_canonical_template_empty")
    canonical_true = _replace_exact(template, original).strip()
    canonical_counterfactual = _replace_exact(template, replacement).strip()
    if not canonical_true or not canonical_counterfactual:
        raise ValueError("v24_canonical_proposition_empty")
    if "{ENTITY}" in canonical_true or "{ENTITY}" in canonical_counterfactual:
        raise ValueError("v24_canonical_slot_leak")
    if _norm(original) == _norm(replacement):
        raise ValueError("v24_replacement_equals_original")
    if _boundary_count(template.replace("{ENTITY}", ""), original) > 0:
        raise ValueError("v24_original_outside_entity_slot")
    if _boundary_count(template.replace("{ENTITY}", ""), replacement) > 0:
        raise ValueError("v24_replacement_outside_entity_slot")
    return canonical_true, canonical_counterfactual


def deterministic_role_judge(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Conservative proposition-local proxy used only by offline tests.

    The formal protocol supplies a frozen proposition-local model judge.  This
    deterministic implementation is deliberately labelled as a proxy so the
    small lexical compatibility heuristic cannot be mistaken for an entity
    taxonomy or a production replacement policy.
    """

    proxy = {"judge_mode": "offline_proxy", "proxy_only": True}

    true_claim = str(payload.get("true_claim") or "")
    replacement = str(payload.get("replacement_entity") or "")
    canonical = str(payload.get("canonical_counterfactual") or "")
    if not true_claim or not replacement or not canonical:
        return {**proxy, "compatible": False, "plausibility": "reject", "reason_code": "missing_input"}
    if UNRESOLVED_REFERENCE_RE.search(true_claim) or not content_tokens(canonical):
        return {**proxy, "compatible": False, "plausibility": "reject", "reason_code": "unresolved_or_fragment"}
    if re.search(r"\b(?:Paris|London|California)\b", replacement, re.IGNORECASE) and re.search(
        r"\b(?:acquired|partnered|served as|designated|authorized)\b", true_claim, re.IGNORECASE
    ):
        return {**proxy, "compatible": False, "plausibility": "reject", "reason_code": "role_mismatch"}
    return {
        **proxy,
        "compatible": True,
        "plausibility": "strong" if DETERMINATE_CONTEXT_RE.search(true_claim) else "acceptable",
    }


def deterministic_correction_eligibility_judge(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Offline conservative proxy for the frozen proposition-local judge."""

    claim = str(payload.get("true_claim") or "")
    if not claim:
        return {
            "correction_eligible": False,
            "slot_determinacy": "weak",
            "open_world_ambiguity": "high",
            "reason_code": "missing_true_claim",
        }
    determinate = bool(DETERMINATE_CONTEXT_RE.search(claim))
    return {
        "correction_eligible": determinate,
        "slot_determinacy": "strong" if determinate else "weak",
        "open_world_ambiguity": "low" if determinate else "high",
        "reason_code": "record_specific_or_role_specific" if determinate else "underdetermined_open_world_slot",
    }


def _token_ngrams(tokens: Sequence[str], size: int) -> set[tuple[str, ...]]:
    if size <= 0 or len(tokens) < size:
        return set()
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def _ngram_containment(source: str, query: str, *, size: int = 5) -> float:
    source_ngrams = _token_ngrams(content_tokens(source), size)
    query_ngrams = _token_ngrams(content_tokens(query), size)
    if not query_ngrams:
        return 0.0
    return len(source_ngrams & query_ngrams) / len(query_ngrams)


def _longest_literal_copy_run(source: str, query: str) -> int:
    source_tokens = content_tokens(source)
    query_tokens = content_tokens(query)
    if not source_tokens or not query_tokens:
        return 0
    source_set = set(source_tokens)
    longest = current = 0
    for token in query_tokens:
        if token in source_set:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _distinct_ratio(tokens: Sequence[str], size: int) -> float:
    grams = _token_ngrams(tokens, size)
    return len(grams) / max(1, len(tokens) - size + 1)


def stealth_diagnostics(
    *,
    source_text: str,
    q_plus: str,
    q_minus: str,
    original_entity: str,
    replacement_entity: str,
    similarity_fn: Callable[[str, str], float] | None = None,
) -> dict[str, float]:
    """Compute non-blocking stealth/diversity diagnostics for one pair."""

    if similarity_fn is None:
        raise RuntimeError("v24_semantic_similarity_required")
    masked_plus = _mask_entity_mentions(q_plus, original_entity)
    masked_minus = _mask_entity_mentions(q_minus, replacement_entity)
    plus_tokens = content_tokens(q_plus)
    minus_tokens = content_tokens(q_minus)
    pair_tokens = plus_tokens + minus_tokens
    word_count_ratio = min(len(plus_tokens), len(minus_tokens)) / max(1, max(len(plus_tokens), len(minus_tokens)))
    masked_grams_plus = _token_ngrams(content_tokens(masked_plus), 5)
    masked_grams_minus = _token_ngrams(content_tokens(masked_minus), 5)
    masked_denominator = max(1, len(masked_grams_plus | masked_grams_minus))
    return {
        "entity_masked_similarity": float(similarity_fn(masked_plus, masked_minus)),
        "word_count_ratio": word_count_ratio,
        "entity_masked_5gram_containment": len(masked_grams_plus & masked_grams_minus) / masked_denominator,
        "query_source_5gram_containment": (
            _ngram_containment(source_text, q_plus) + _ngram_containment(source_text, q_minus)
        )
        / 2.0,
        "longest_literal_copy_length": float(
            max(_longest_literal_copy_run(source_text, q_plus), _longest_literal_copy_run(source_text, q_minus))
        ),
        "distinct_1": _distinct_ratio(pair_tokens, 1),
        "distinct_2": _distinct_ratio(pair_tokens, 2),
    }


def aggregate_stealth_diagnostics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Aggregate pair/query diagnostics without turning them into hard gates."""

    pairs = [
        pair
        for source in rows
        for pair in (source.get("selected_pairs", []) or [])
        if isinstance(pair, Mapping)
    ]
    diagnostics = [pair.get("stealth_diagnostics", {}) for pair in pairs]
    numeric_keys = (
        "entity_masked_similarity",
        "word_count_ratio",
        "entity_masked_5gram_containment",
        "query_source_5gram_containment",
        "longest_literal_copy_length",
        "distinct_1",
        "distinct_2",
    )
    result = {
        key: sum(float(item.get(key, 0.0)) for item in diagnostics if isinstance(item, Mapping))
        / max(1, len(diagnostics))
        for key in numeric_keys
    }
    queries = [
        str(pair.get(field) or "").strip()
        for pair in pairs
        for field in ("q_plus_text", "q_minus_text")
    ]
    openings = [" ".join(content_tokens(query)[:4]) for query in queries if query]
    result["duplicate_query_rate"] = 1.0 - len(set(queries)) / max(1, len(queries))
    result["dominant_opening_4gram_rate"] = (
        max(Counter(openings).values()) / len(openings) if openings else 0.0
    )
    result["fallback_pair_rate"] = sum(
        pair.get("generation_mode") == "deterministic_fallback" for pair in pairs
    ) / max(1, len(pairs))
    return result


def _question_entities(text: str) -> set[str]:
    entities: set[str] = set()
    for match in CAPITALIZED_PHRASE_RE.finditer(text):
        phrase = match.group(0).strip(" .?!,:;\t\r\n")
        words = phrase.split()
        while words and words[0].casefold() in QUESTION_FRAME_WORDS:
            words.pop(0)
        if words:
            entities.add(_norm(" ".join(words)))
    return entities


def _has_unresolved_reference(query: str) -> bool:
    # ``it`` in the frozen verification frame is an expletive, not an
    # unresolved source reference.  Other pronouns remain hard failures.
    normalized = query.strip()
    normalized = re.sub(r"^is\s+it\s+correct\s+that\b", "", normalized, flags=re.IGNORECASE)
    return UNRESOLVED_REFERENCE_RE.search(normalized) is not None


def _query_proposition_body(query: str) -> str:
    """Return the proposition-like body used for narrow reference checks."""

    stripped = str(query or "").strip().rstrip("?").strip()
    fixed_frame = re.sub(
        r"^is\s+it\s+correct\s+that\b", "", stripped, flags=re.IGNORECASE
    ).strip()
    if fixed_frame != stripped:
        return fixed_frame
    return re.sub(
        r"^(?:is|are|was|were|do|does|did|has|have|had|can|could|will|would|"
        r"should|may|might|must|shall)\b\s*",
        "",
        stripped,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _query_surface_reasons(query: str, true_claim: str) -> list[str]:
    """Map concrete surface defects to the existing query hard-gate categories."""

    stripped = str(query or "").strip()
    without_terminal_mark = stripped[:-1].rstrip() if stripped.endswith("?") else stripped
    proposition_body = _query_proposition_body(stripped)
    reasons: list[str] = []
    if _has_unresolved_reference(stripped):
        reasons.append("unresolved_reference")
    if (
        GENERIC_DOCUMENT_REFERENCE_RE.search(stripped)
        or GENERIC_DOCUMENT_REFERENCE_RE.search(proposition_body)
        or UNDEFINED_ACRONYM_CITATION_RE.search(stripped)
    ):
        reasons.append("unresolved_reference")
    if (
        FIRST_PERSON_REFERENCE_RE.search(str(true_claim or ""))
        and BARE_COMPANY_REFERENCE_RE.search(stripped)
    ):
        reasons.append("unresolved_reference")
    if (
        INCOMPLETE_TEMPORAL_REFERENCE_RE.search(without_terminal_mark)
        or HEADING_SENTENCE_GLUE_RE.search(stripped)
        or INVALID_MODAL_COORDINATION_RE.search(stripped)
        or INVALID_DO_COORDINATION_RE.search(stripped)
        or MALFORMED_REPORTATIVE_TAIL_RE.search(without_terminal_mark)
        or EMBEDDED_CLAUSE_CAPITALIZATION_RE.search(stripped)
    ):
        reasons.append("not_natural_question")
    if INCOMPLETE_TEMPORAL_REFERENCE_RE.search(without_terminal_mark):
        reasons.append("not_polar_question")
    return sorted(set(reasons))


def _reverse_substitute_entity(query: str, replacement: str, original: str) -> str:
    """Reverse exactly one entity-slot substitution using complete boundaries."""

    pattern = re.compile(rf"(?<!\w){re.escape(replacement)}(?!\w)")
    return pattern.sub(original, query, count=1)


def _semantic_features(text: str) -> dict[str, set[str]]:
    return {
        "negation": {value.casefold() for value in NEGATION_RE.findall(text)},
        "modality": {value.casefold() for value in MODALITY_RE.findall(text)},
        "numeric": _numeric_markers(text),
        "temporal": _temporal_markers(text),
        "scope": {value.casefold() for value in SCOPE_RE.findall(text)},
    }


def _numeric_markers(text: str) -> set[str]:
    """Return factual numbers while excluding bracketed bibliography citations."""

    without_citations = CITATION_RE.sub(" ", text)
    return set(NUMBER_RE.findall(without_citations))


def _temporal_markers(text: str) -> set[str]:
    """Return explicit temporal semantics without treating every preposition as time."""

    without_citations = CITATION_RE.sub(" ", text)
    markers = {value.casefold() for value in TEMPORAL_MARKER_RE.findall(without_citations)}
    # ``may`` is both a modal and a month.  Count it as temporal only when the
    # local context makes the month reading explicit (e.g. ``May 2024``).
    if "may" in markers and not re.search(
        r"\b(?:in|on|during)?\s*may\s+\d{2,4}\b|\b(?:in|on|during)\s+may\b",
        without_citations,
        flags=re.IGNORECASE,
    ):
        markers.remove("may")
    return markers


def _anchor_diagnostics(
    source_text: str,
    q_plus: str,
    q_minus: str,
    anchors: Any,
) -> dict[str, Any]:
    """记录 retrieval anchor 质量，但不把它升级为科学拒绝理由。"""

    if anchors is None:
        return {
            "provided": False,
            "schema_valid": True,
            "source_grounded": True,
            "present_in_query": True,
            "reasons": [],
        }
    reasons: list[str] = []
    if not isinstance(anchors, (list, tuple)) or len(anchors) > 3:
        reasons.append("retrieval_anchor_schema")
        return {
            "provided": True,
            "anchor_count": None,
            "schema_valid": False,
            "source_grounded": False,
            "present_in_query": False,
            "reasons": reasons,
        }
    source_grounded = True
    present_in_query = True
    for anchor in anchors:
        if not isinstance(anchor, str):
            reasons.append("retrieval_anchor_schema")
        value = anchor.strip() if isinstance(anchor, str) else str(anchor or "").strip()
        if not value or _boundary_count(source_text, value) < 1:
            reasons.append("retrieval_anchor_not_source_grounded")
            source_grounded = False
        if _boundary_count(q_plus, value) < 1 and _boundary_count(q_minus, value) < 1:
            reasons.append("retrieval_anchor_not_in_query")
            present_in_query = False
    return {
        "provided": True,
        "anchor_count": len(anchors),
        "schema_valid": "retrieval_anchor_schema" not in reasons,
        "source_grounded": source_grounded,
        "present_in_query": present_in_query,
        "reasons": sorted(set(reasons)),
    }


def validate_query_semantics(
    *,
    true_claim: str,
    original_entity: str,
    replacement_entity: str,
    canonical_true: str,
    canonical_counterfactual: str,
    q_plus: str,
    q_minus: str,
    similarity_fn: Callable[[str, str], float] | None = None,
) -> tuple[list[str], dict[str, float]]:
    if similarity_fn is None:
        raise RuntimeError("v24_semantic_similarity_required")
    reasons: list[str] = []
    metrics = {
        "q_plus_similarity": similarity_fn(q_plus, canonical_true),
        "q_minus_similarity": similarity_fn(q_minus, canonical_counterfactual),
        "reverse_similarity": similarity_fn(
            _reverse_substitute_entity(q_minus, replacement_entity, original_entity), canonical_true
        ),
    }
    for name, query in (("q_plus", q_plus), ("q_minus", q_minus)):
        stripped = str(query or "").strip()
        if not stripped or stripped.count("?") != 1 or not stripped.endswith("?"):
            reasons.append(f"{name}_question_mark")
        if not QUESTION_START_RE.search(stripped):
            reasons.append(f"{name}_not_polar_question")
        for surface_reason in _query_surface_reasons(stripped, true_claim):
            reasons.append(f"{name}_{surface_reason}")
        if ATTACK_EXPOSING_RE.search(stripped):
            reasons.append(f"{name}_attack_exposing_wording")
        if "ENTITY" in stripped or "{ENTITY}" in stripped:
            reasons.append(f"{name}_slot_leak")
    if _boundary_count(q_plus, original_entity) != 1 or _boundary_count(q_plus, replacement_entity) > 0:
        reasons.append("q_plus_entity_binding")
    if _boundary_count(q_minus, replacement_entity) != 1 or _boundary_count(q_minus, original_entity) > 0:
        reasons.append("q_minus_entity_binding")
    if metrics["q_plus_similarity"] < 0.80:
        reasons.append("q_plus_semantic_binding")
    if metrics["q_minus_similarity"] < 0.80:
        reasons.append("q_minus_semantic_binding")
    if metrics["reverse_similarity"] < 0.80:
        reasons.append("q_minus_reverse_binding")
    for feature_name in ("negation", "modality", "numeric", "temporal", "scope"):
        canonical_features = _semantic_features(canonical_true)[feature_name]
        query_features = _semantic_features(q_plus)[feature_name]
        if canonical_features != query_features:
            reasons.append(f"q_plus_{feature_name}_drift")
        canonical_minus = _semantic_features(canonical_counterfactual)[feature_name]
        query_minus = _semantic_features(q_minus)[feature_name]
        if canonical_minus != query_minus:
            reasons.append(f"q_minus_{feature_name}_drift")
    allowed = {_norm(original_entity), _norm(replacement_entity)} | _question_entities(canonical_true) | _question_entities(canonical_counterfactual)
    for name, query in (("q_plus", q_plus), ("q_minus", q_minus)):
        emitted = _question_entities(query)
        if emitted - allowed:
            reasons.append(f"{name}_new_factual_entity")
    return sorted(set(reasons)), metrics


def evaluate_candidate(
    fact: Mapping[str, Any],
    source_text: str,
    package: Mapping[str, Any],
    *,
    role_judge: RoleJudge | None = None,
    eligibility_judge: EligibilityJudge | None = None,
    grounding: Mapping[str, Any] | None = None,
    similarity_fn: Callable[[str, str], float] | None = None,
    allow_surface_fallback: bool = False,
    candidate_index: int = 0,
) -> dict[str, Any]:
    _reject_forbidden(fact, path="fact")
    _reject_forbidden(package, path="candidate")
    fact_quality_reasons = _candidate_fact_quality_reasons(fact)
    if fact_quality_reasons:
        return {
            "accepted": False,
            "rejection_reasons": fact_quality_reasons,
            "fact": dict(fact),
        }
    original = str(fact.get("original_entity") or "")
    replacement = str(package.get("replacement_entity") or "")
    template = package.get("canonical_proposition_template")
    reasons: list[str] = []
    try:
        canonical_true, canonical_counterfactual = _canonical_pair(
            str(fact.get("true_claim") or ""), original, replacement, str(template or "")
        )
    except ValueError as error:
        return {"accepted": False, "rejection_reasons": [str(error)], "fact": dict(fact)}
    canonical_quality_reasons = sorted(
        set(
            _canonical_proposition_quality_reasons(
                canonical_true, str(fact.get("true_claim") or "")
            )
            + _canonical_proposition_quality_reasons(
                canonical_counterfactual, str(fact.get("true_claim") or "")
            )
        )
    )
    if canonical_quality_reasons:
        return {
            "accepted": False,
            "rejection_reasons": canonical_quality_reasons,
            "fact": dict(fact),
        }
    if _boundary_count(source_text, replacement) > 0:
        reasons.append("source_absence")
    role_payload = {
        "true_claim": fact.get("true_claim"),
        "original_entity": original,
        "replacement_entity": replacement,
        "canonical_true": canonical_true,
        "canonical_counterfactual": canonical_counterfactual,
    }
    if role_judge is not None:
        role_result = role_judge(role_payload)
    else:
        package_role = package.get("contextual_role_compatibility")
        role_result = package_role if isinstance(package_role, Mapping) else deterministic_role_judge(role_payload)
    role = dict(role_result)
    if role.get("compatible") is not True or role.get("plausibility") not in {"strong", "acceptable"}:
        reasons.append("contextual_role_incompatible")
    grounding_value = dict(grounding or package.get("true_grounding") or {})
    entailment = float(grounding_value.get("entailment_probability", 0.0))
    if entailment < 0.80 or str(grounding_value.get("top_label", "")) != "entailment":
        reasons.append("true_grounding")
    eligibility_payload = {
        "true_claim": fact.get("true_claim"),
        "original_entity": original,
        "replacement_entity": replacement,
        "canonical_true": canonical_true,
        "canonical_counterfactual": canonical_counterfactual,
    }
    if eligibility_judge is not None:
        eligibility_result = eligibility_judge(eligibility_payload)
    else:
        package_eligibility = package.get("correction_eligibility")
        eligibility_result = (
            package_eligibility
            if isinstance(package_eligibility, Mapping)
            else deterministic_correction_eligibility_judge(eligibility_payload)
        )
    eligibility = dict(eligibility_result)
    slot_determinacy = str(eligibility.get("slot_determinacy") or "").casefold()
    open_world_ambiguity = str(eligibility.get("open_world_ambiguity") or "").casefold()
    if (
        eligibility.get("correction_eligible") is not True
        or slot_determinacy in {"weak", "reject", "high"}
        or open_world_ambiguity in {"high", "reject"}
    ):
        reasons.append("correction_eligibility")
    query_reasons, metrics = validate_query_semantics(
        true_claim=str(fact.get("true_claim") or ""),
        original_entity=original,
        replacement_entity=replacement,
        canonical_true=canonical_true,
        canonical_counterfactual=canonical_counterfactual,
        q_plus=str(package.get("q_plus_text") or ""),
        q_minus=str(package.get("q_minus_text") or ""),
        similarity_fn=similarity_fn,
    )
    reasons.extend(query_reasons)
    anchor_diagnostics = _anchor_diagnostics(
        source_text,
        str(package.get("q_plus_text") or ""),
        str(package.get("q_minus_text") or ""),
        package.get("retrieval_anchors"),
    )
    raw_anchors = package.get("retrieval_anchors")
    row = {
        "upstream_pair_id": str(fact.get("upstream_pair_id") or ""),
        "dataset": str(fact.get("dataset") or ""),
        "source_key": str(fact.get("source_key") or ""),
        "source_hash": str(fact.get("source_hash") or ""),
        "normalized_text_hash": str(fact.get("normalized_text_hash") or ""),
        "original_entity": original,
        "fact_order": int(fact.get("fact_order", 0)),
        "candidate_index": candidate_index,
        "replacement_entity": replacement,
        "true_claim": str(fact.get("true_claim") or ""),
        "canonical_proposition_template": str(template),
        "canonical_true": canonical_true,
        "canonical_counterfactual": canonical_counterfactual,
        "q_plus_text": str(package.get("q_plus_text") or ""),
        "q_minus_text": str(package.get("q_minus_text") or ""),
        "retrieval_anchors": raw_anchors if raw_anchors is not None else [],
        "retrieval_anchor_diagnostics": anchor_diagnostics,
        "contextual_role_compatibility": role,
        "correction_eligibility": eligibility,
        "canonical_pair_nli_relation": package.get("canonical_pair_nli_relation", "diagnostic_unprovided"),
        "true_grounding": grounding_value,
        "semantic_metrics": metrics,
        "stealth_diagnostics": stealth_diagnostics(
            source_text=source_text,
            q_plus=str(package.get("q_plus_text") or ""),
            q_minus=str(package.get("q_minus_text") or ""),
            original_entity=original,
            replacement_entity=replacement,
            similarity_fn=similarity_fn,
        ),
        "generation_mode": "luna_naturalized",
    }
    row["pair_id"] = sha256_obj({
        "kind": "v24_pair",
        "upstream_pair_id": row["upstream_pair_id"],
        "original_entity": _norm(original),
        "replacement_entity": _norm(replacement),
        "canonical_proposition_template": row["canonical_proposition_template"],
    })
    row["query_manifest_hash"] = sha256_obj(
        {
            "pair_id": row["pair_id"],
            "q_plus_text": row["q_plus_text"],
            "q_minus_text": row["q_minus_text"],
            "generation_mode": row["generation_mode"],
        }
    )
    if reasons and allow_surface_fallback:
        # 只有 surface naturalization 失败可使用固定 fallback；重建和 eligibility 失败仍 fail-closed。
        reconstruction_reasons = [
            reason for reason in reasons
            if not reason.startswith(("q_plus_", "q_minus_"))
        ]
        if not reconstruction_reasons:
            fallback_plus, fallback_minus = fallback_queries(canonical_true, canonical_counterfactual)
            fallback_reasons, fallback_metrics = validate_query_semantics(
                true_claim=str(fact.get("true_claim") or ""),
                original_entity=original,
                replacement_entity=replacement,
                canonical_true=canonical_true,
                canonical_counterfactual=canonical_counterfactual,
                q_plus=fallback_plus,
                q_minus=fallback_minus,
                similarity_fn=similarity_fn,
            )
            if not fallback_reasons:
                row["q_plus_text"] = fallback_plus
                row["q_minus_text"] = fallback_minus
                row["semantic_metrics"] = fallback_metrics
                row["stealth_diagnostics"] = stealth_diagnostics(
                    source_text=source_text,
                    q_plus=fallback_plus,
                    q_minus=fallback_minus,
                    original_entity=original,
                    replacement_entity=replacement,
                    similarity_fn=similarity_fn,
                )
                row["generation_mode"] = "deterministic_fallback"
                row["query_manifest_hash"] = _query_manifest_hash(row)
                row["naturalization_failure_reasons"] = sorted(set(reasons))
                return {"accepted": True, "rejection_reasons": [], "pair": row, "fact": dict(fact)}
    return {"accepted": not reasons, "rejection_reasons": sorted(set(reasons)), "pair": row, "fact": dict(fact)}


def rank_candidates(candidates: Sequence[Mapping[str, Any]], *, tie_tolerance: float = 0.01) -> list[dict[str, Any]]:
    accepted = [dict(item) for item in candidates if item.get("accepted") is True and isinstance(item.get("pair"), Mapping)]
    if not accepted:
        return []
    for item in accepted:
        pair = item["pair"]
        metrics = pair.get("semantic_metrics", {})
        pair["binding_score"] = min(
            float(metrics.get("q_plus_similarity", 0.0)),
            float(metrics.get("q_minus_similarity", 0.0)),
            float(pair.get("true_grounding", {}).get("entailment_probability", 0.0)),
        )
        pair["source_literal_copying"] = _literal_copying(pair)
        pair["lexical_duplication"] = _lexical_duplication(pair)
    best = max(float(item["pair"]["binding_score"]) for item in accepted)
    def key(item: Mapping[str, Any]) -> tuple[Any, ...]:
        pair = item["pair"]
        close = best - float(pair["binding_score"]) <= tie_tolerance
        plausibility = 0 if pair.get("contextual_role_compatibility", {}).get("plausibility") == "strong" else 1
        if close:
            # 在预注册容差内按语义质量相近的候选执行次级确定性排序。
            return (
                0,
                float(pair["source_literal_copying"]),
                float(pair["lexical_duplication"]),
                plausibility,
                -float(pair["binding_score"]),
                int(pair.get("candidate_index", 0)),
                canonical_json(pair),
            )
        return (
            1,
            -float(pair["binding_score"]),
            int(pair.get("candidate_index", 0)),
            canonical_json(pair),
        )
    return sorted(accepted, key=key)


def _literal_copying(pair: Mapping[str, Any]) -> float:
    source = set(content_tokens(str(pair.get("true_claim") or "")))
    queries = set(content_tokens(str(pair.get("q_plus_text") or ""))) | set(content_tokens(str(pair.get("q_minus_text") or "")))
    return len(source & queries) / max(1, len(queries))


def _lexical_duplication(pair: Mapping[str, Any]) -> float:
    plus = set(content_tokens(str(pair.get("q_plus_text") or "")))
    minus = set(content_tokens(str(pair.get("q_minus_text") or "")))
    return len(plus & minus) / max(1, len(plus | minus))


def select_fact_pair(
    fact: Mapping[str, Any],
    source_text: str,
    packages: Sequence[Mapping[str, Any]],
    *,
    allow_surface_fallback: bool = False,
    **kwargs: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    evaluated = [
        evaluate_candidate(
            fact,
            source_text,
            package,
            allow_surface_fallback=allow_surface_fallback,
            candidate_index=index,
            **kwargs,
        )
        for index, package in enumerate(packages)
    ]
    ranked = rank_candidates(evaluated)
    if not ranked:
        reasons = sorted({reason for item in evaluated for reason in item.get("rejection_reasons", [])})
        return None, reasons or ["no_scientifically_valid_candidate"]
    return dict(ranked[0]["pair"]), []


def screen_source(
    source: Mapping[str, Any],
    *,
    candidate_provider: CandidateProvider,
    facts: Sequence[Mapping[str, Any]] | None = None,
    minimum_pairs: int = PAIRS_PER_SOURCE,
    allow_surface_fallback: bool = True,
    similarity_fn: Callable[[str, str], float] | None = None,
    semantic_correction_retries: int = 1,
    include_candidate_evidence: bool = False,
    max_candidate_facts_per_source: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    if similarity_fn is None:
        raise RuntimeError("v24_semantic_similarity_required")
    if semantic_correction_retries not in {0, 1}:
        raise ValueError("v24_semantic_correction_retries_must_be_zero_or_one")
    if minimum_pairs <= 0:
        raise ValueError("v24_minimum_pairs_must_be_positive")
    distinct_target = min(minimum_pairs, PAIRS_PER_SOURCE)
    fact_budget = (
        DEFAULT_MAX_CANDIDATE_FACTS_PER_SOURCE
        if max_candidate_facts_per_source is None
        else int(max_candidate_facts_per_source)
    )
    if fact_budget <= 0:
        raise ValueError("v24_max_candidate_facts_per_source_invalid")
    identity = _source_identity(source)
    source_facts = list(facts if facts is not None else enumerate_candidate_facts(source))
    source_facts.sort(
        key=lambda row: (
            int(row.get("fact_order", 0)),
            int(row.get("chunk_rank", 0)),
            int((row.get("proposition_span") or [0])[0]),
            int((row.get("original_span") or [0])[0]),
            str(row.get("upstream_pair_id") or ""),
        )
    )
    candidate_fact_count = len(source_facts)
    preferred_distinct_pairs: list[dict[str, Any]] = []
    selected_original_entities: set[str] = set()
    duplicate_entity_fallbacks: list[dict[str, Any]] = []
    accepted_pair_ids: set[str] = set()
    rejection_counts: Counter[str] = Counter()
    candidate_package_count = 0
    contextual_role_pass_count = 0
    correction_eligibility_pass_count = 0
    query_feasible_pair_count = 0
    candidate_evidence: list[dict[str, Any]] = []
    processed_fact_count = 0
    third_eligible_pair_fact_position: int | None = None
    third_distinct_eligible_pair_fact_position: int | None = None
    early_stop_triggered = False
    for fact in source_facts[:fact_budget]:
        fact_quality_reasons = _candidate_fact_quality_reasons(fact)
        if fact_quality_reasons:
            rejection_counts.update(fact_quality_reasons)
            continue
        processed_fact_count += 1
        packages = list(candidate_provider(fact))
        initial_package_count = len(packages)
        candidate_package_count += len(packages)
        evaluated = [
            evaluate_candidate(
                fact,
                str(source["full_text"]),
                package,
                allow_surface_fallback=allow_surface_fallback,
                candidate_index=index,
                similarity_fn=similarity_fn,
                **kwargs,
            )
            for index, package in enumerate(packages)
        ]
        if semantic_correction_retries == 1 and not any(
            item.get("accepted") is True for item in evaluated
        ):
            corrector = getattr(candidate_provider, "correct", None)
            if callable(corrector):
                rejected = [
                    {
                        "candidate": dict(package),
                        "rejection_reasons": list(item.get("rejection_reasons", [])),
                    }
                    for package, item in zip(packages, evaluated, strict=True)
                ]
                corrected_packages = list(corrector(fact, rejected))
                correction_offset = len(packages)
                candidate_package_count += len(corrected_packages)
                corrected_evaluated = [
                    evaluate_candidate(
                        fact,
                        str(source["full_text"]),
                        package,
                        allow_surface_fallback=allow_surface_fallback,
                        candidate_index=correction_offset + index,
                        similarity_fn=similarity_fn,
                        **kwargs,
                    )
                    for index, package in enumerate(corrected_packages)
                ]
                packages.extend(corrected_packages)
                evaluated.extend(corrected_evaluated)
        if include_candidate_evidence:
            for index, (package, item) in enumerate(
                zip(packages, evaluated, strict=True)
            ):
                pair = item.get("pair")
                candidate_evidence.append(
                    {
                        "upstream_pair_id": str(fact.get("upstream_pair_id") or ""),
                        "candidate_index": index,
                        "generation_attempt": (
                            "initial"
                            if index < initial_package_count
                            else "semantic_correction"
                        ),
                        "candidate": {
                            key: package.get(key)
                            for key in (
                                "replacement_entity",
                                "canonical_proposition_template",
                                "q_plus_text",
                                "q_minus_text",
                            )
                        },
                        "accepted": item.get("accepted") is True,
                        "rejection_reasons": list(item.get("rejection_reasons", [])),
                        "semantic_metrics": (
                            dict(pair.get("semantic_metrics", {}))
                            if isinstance(pair, Mapping)
                            else {}
                        ),
                    }
                )
        for item in evaluated:
            rejection_counts.update(item.get("rejection_reasons", []))
            pair = item.get("pair")
            if not isinstance(pair, Mapping):
                continue
            naturalization_failures = pair.get("naturalization_failure_reasons", [])
            if isinstance(naturalization_failures, Sequence) and not isinstance(
                naturalization_failures, (str, bytes)
            ):
                rejection_counts.update(
                    f"naturalization_failure:{reason}" for reason in naturalization_failures
                )
            role = pair.get("contextual_role_compatibility", {})
            if isinstance(role, Mapping) and role.get("compatible") is True:
                contextual_role_pass_count += 1
            eligibility = pair.get("correction_eligibility", {})
            if (
                isinstance(role, Mapping)
                and role.get("compatible") is True
                and isinstance(eligibility, Mapping)
                and eligibility.get("correction_eligible") is True
            ):
                correction_eligibility_pass_count += 1
            if item.get("accepted") is True:
                query_feasible_pair_count += 1
        ranked = rank_candidates(evaluated)
        if not ranked:
            continue
        pair = dict(ranked[0]["pair"])
        pair_id = str(pair.get("pair_id") or "")
        if not pair_id or pair_id in accepted_pair_ids:
            continue
        accepted_pair_ids.add(pair_id)
        if len(accepted_pair_ids) == PAIRS_PER_SOURCE:
            third_eligible_pair_fact_position = processed_fact_count
        original_key = _norm(str(pair.get("original_entity") or ""))
        if original_key not in selected_original_entities:
            selected_original_entities.add(original_key)
            preferred_distinct_pairs.append(pair)
            if len(preferred_distinct_pairs) == distinct_target:
                if distinct_target == PAIRS_PER_SOURCE:
                    third_distinct_eligible_pair_fact_position = processed_fact_count
                early_stop_triggered = True
                break
        else:
            duplicate_entity_fallbacks.append(pair)
    ordered = preferred_distinct_pairs + duplicate_entity_fallbacks
    ordered = ordered[:minimum_pairs]
    eligible = len(ordered) >= minimum_pairs
    if not eligible:
        rejection_counts["fewer_than_three_eligible_pairs"] += 1
    entity_diversity = len(
        {_norm(str(pair.get("original_entity") or "")) for pair in ordered}
    )
    fallback_pair_count = sum(
        pair.get("generation_mode") == "deterministic_fallback" for pair in ordered
    )
    result = {
        **identity,
        "eligible": eligible,
        "selected_pairs": ordered,
        # candidate_pair_count 统计已处理 fact 生成包；fact 总数单独用于 coverage。
        "candidate_pair_count": candidate_package_count,
        "candidate_fact_count": candidate_fact_count,
        "processed_fact_count": processed_fact_count,
        "unprocessed_fact_count": candidate_fact_count - processed_fact_count,
        "candidate_package_count": candidate_package_count,
        "eligible_pair_count": len(accepted_pair_ids),
        "contextual_role_pass_count": contextual_role_pass_count,
        "correction_eligibility_pass_count": correction_eligibility_pass_count,
        "query_feasible_pair_count": query_feasible_pair_count,
        "fallback_pair_count": fallback_pair_count,
        "max_candidate_facts_per_source": fact_budget,
        "early_stop_triggered": early_stop_triggered,
        "third_eligible_pair_fact_position": third_eligible_pair_fact_position,
        "third_distinct_eligible_pair_fact_position": third_distinct_eligible_pair_fact_position,
        "original_entity_diversity": entity_diversity,
        "repeated_original_entity_pair_count": max(0, len(ordered) - entity_diversity),
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
    }
    if include_candidate_evidence:
        result["candidate_evidence"] = candidate_evidence
    return result


def scan_until_target(
    sources: Iterable[Mapping[str, Any]],
    *,
    candidate_provider: CandidateProvider,
    target_sources: int = 2250,
    minimum_pairs: int = PAIRS_PER_SOURCE,
    max_candidate_facts_per_source: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    fact_budget = (
        DEFAULT_MAX_CANDIDATE_FACTS_PER_SOURCE
        if max_candidate_facts_per_source is None
        else int(max_candidate_facts_per_source)
    )
    if fact_budget <= 0:
        raise ValueError("v24_max_candidate_facts_per_source_invalid")
    eligible: list[dict[str, Any]] = []
    screened = 0
    totals: Counter[str] = Counter()
    rejection_reasons: Counter[str] = Counter()
    diversity_counts: Counter[str] = Counter()
    for source in sources:
        screened += 1
        result = screen_source(
            source,
            candidate_provider=candidate_provider,
            minimum_pairs=minimum_pairs,
            max_candidate_facts_per_source=fact_budget,
            **kwargs,
        )
        totals.update(
            {
                "candidate_pair_count": int(result["candidate_pair_count"]),
                "candidate_fact_count": int(result.get("candidate_fact_count", 0)),
                "processed_fact_count": int(result.get("processed_fact_count", 0)),
                "unprocessed_fact_count": int(result.get("unprocessed_fact_count", 0)),
                "candidate_package_count": int(result.get("candidate_package_count", 0)),
                "eligible_pair_count": int(result["eligible_pair_count"]),
                "contextual_role_pass_count": int(result.get("contextual_role_pass_count", 0)),
                "correction_eligibility_pass_count": int(result.get("correction_eligibility_pass_count", 0)),
                "query_feasible_pair_count": int(result.get("query_feasible_pair_count", 0)),
                "fallback_pair_count": int(result.get("fallback_pair_count", 0)),
                "early_stop_source_count": int(bool(result.get("early_stop_triggered"))),
            }
        )
        rejection_reasons.update(result.get("rejection_reason_counts", {}))
        if result["eligible"]:
            result["selection_index"] = len(eligible)
            eligible.append(result)
            diversity_counts[str(int(result.get("original_entity_diversity", 0)))] += 1
            if len(eligible) == target_sources:
                break
    status = "passed" if len(eligible) == target_sources else "insufficient_eligible_capacity"
    return {
        "status": status,
        "screened_source_count": screened,
        "eligible_source_count": len(eligible),
        "eligible_source_rate": len(eligible) / max(1, screened),
        "target_source_count": target_sources,
        "eligible_sources": eligible,
        "candidate_pair_count": totals["candidate_pair_count"],
        "candidate_fact_count": totals["candidate_fact_count"],
        "processed_fact_count": totals["processed_fact_count"],
        "unprocessed_fact_count": totals["unprocessed_fact_count"],
        "eligible_pair_count": totals["eligible_pair_count"],
        "candidate_package_count": totals["candidate_package_count"],
        "contextual_role_pass_count": totals["contextual_role_pass_count"],
        "correction_eligibility_pass_count": totals["correction_eligibility_pass_count"],
        "query_feasible_pair_count": totals["query_feasible_pair_count"],
        "fallback_pair_count": totals["fallback_pair_count"],
        "max_candidate_facts_per_source": fact_budget,
        "early_stop_source_count": totals["early_stop_source_count"],
        "entity_diversity_1_source_count": diversity_counts["1"],
        "entity_diversity_2_source_count": diversity_counts["2"],
        "entity_diversity_3_source_count": diversity_counts["3"],
        "mean_original_entity_diversity": (
            sum(int(key) * value for key, value in diversity_counts.items())
            / max(1, len(eligible))
        ),
        "rejection_reason_distribution": dict(sorted(rejection_reasons.items())),
    }


def deterministic_split(eligible_sources: Sequence[Mapping[str, Any]], *, dataset: str, selection_seed: int = 42) -> list[dict[str, Any]]:
    if selection_seed != 42 or len(eligible_sources) != sum(GROUP_COUNTS.values()):
        raise ValueError("v24_split_requires_exactly_2250_sources")
    keyed: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for source in eligible_sources:
        _reject_forbidden(source, path="eligible_source")
        if not source.get("eligible") or len(source.get("selected_pairs", [])) != PAIRS_PER_SOURCE:
            raise ValueError("v24_split_source_not_frozen_eligible")
        declared_integrity = source.get("integrity_hash")
        if declared_integrity is not None and declared_integrity != _integrity_row_hash(source):
            raise ValueError("v24_split_source_integrity_drift")
        key = str(source.get("source_key"))
        if key in seen:
            raise ValueError("v24_split_duplicate_source")
        seen.add(key)
        split_key = sha256_obj({"kind": "v24_membership_split", "selection_seed": selection_seed, "dataset": dataset, "source_key": key, "source_hash": source.get("source_hash"), "normalized_text_hash": source.get("normalized_text_hash")})
        keyed.append((split_key, source))
    keyed.sort(key=lambda item: (item[0], str(item[1].get("source_key"))))
    rows: list[dict[str, Any]] = []
    for index, (split_key, source) in enumerate(keyed):
        group = "KB_Member" if index < 1000 else "True_Non_Member" if index < 2000 else "Reserve"
        pairs = list(source["selected_pairs"])
        rows.append(
            {
                "kind": "v24_source_split_row",
                "dataset": dataset,
                "split_index": index,
                "split_key": split_key,
                "group": group,
                "source_key": source["source_key"],
                "source_order_rank": source.get("source_order_rank"),
                "source_hash": source["source_hash"],
                "normalized_text_hash": source["normalized_text_hash"],
                "ordered_pair_ids": [row["pair_id"] for row in pairs],
                "ordered_query_manifest_hashes": [row.get("query_manifest_hash") for row in pairs],
                "source_integrity_hash": source.get("integrity_hash") or _integrity_row_hash(source),
            }
        )
    validate_split_rows(rows, dataset=dataset)
    return rows


def validate_split_rows(rows: Sequence[Mapping[str, Any]], *, dataset: str) -> dict[str, Any]:
    if len(rows) != 2250:
        raise ValueError("v24_split_row_count")
    counts = Counter(str(row.get("group")) for row in rows)
    if dict(counts) != GROUP_COUNTS:
        raise ValueError("v24_split_group_counts")
    seen_keys: set[str] = set()
    seen_hashes: set[str] = set()
    for index, row in enumerate(rows):
        if row.get("dataset") != dataset or row.get("split_index") != index or row.get("group") not in GROUP_COUNTS:
            raise ValueError("v24_split_row_invalid")
        source_key = str(row.get("source_key") or "")
        source_hash = str(row.get("source_hash") or "")
        if source_key in seen_keys or source_hash in seen_hashes:
            raise ValueError("v24_split_overlap")
        seen_keys.add(source_key)
        seen_hashes.add(source_hash)
        if len(row.get("ordered_pair_ids", [])) != PAIRS_PER_SOURCE:
            raise ValueError("v24_split_pairs_per_source")
        pair_ids = row.get("ordered_pair_ids", [])
        if len(set(str(pair_id) for pair_id in pair_ids)) != PAIRS_PER_SOURCE:
            raise ValueError("v24_split_pair_overlap")
        source_integrity_hash = str(row.get("source_integrity_hash") or "")
        if not SHA256_RE.fullmatch(source_integrity_hash):
            raise ValueError("v24_split_source_integrity_hash")
        query_hashes = row.get("ordered_query_manifest_hashes")
        if query_hashes is not None and len(query_hashes) != PAIRS_PER_SOURCE:
            raise ValueError("v24_split_query_hash_count")
        if query_hashes is not None:
            present = [value for value in query_hashes if value is not None]
            if present and (len(present) != PAIRS_PER_SOURCE or not all(SHA256_RE.fullmatch(str(value)) for value in present)):
                raise ValueError("v24_split_query_manifest_hash")
    return {"status": "passed", "dataset": dataset, "source_count": 2250, "group_counts": dict(GROUP_COUNTS)}


def fallback_queries(canonical_true: str, canonical_counterfactual: str) -> tuple[str, str]:
    return (
        f"Is it correct that {canonical_true.rstrip('.?! ')}?",
        f"Is it correct that {canonical_counterfactual.rstrip('.?! ')}?",
    )


def validate_formal_integrity(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_source_count: int = 2250,
    queries_per_source: int = 6,
    frozen_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if len(rows) != expected_source_count:
        raise ValueError("v24_formal_source_count")
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"v24_formal_row_invalid:{index}")
        if len(row.get("selected_pairs", [])) != PAIRS_PER_SOURCE:
            raise ValueError("v24_formal_pair_count")
        if int(row.get("max_candidate_facts_per_source", -1)) != DEFAULT_MAX_CANDIDATE_FACTS_PER_SOURCE:
            raise ValueError("v24_formal_fact_budget")
        if int(row.get("query_count", queries_per_source)) != queries_per_source:
            raise ValueError("v24_formal_query_budget")
        if not str(row.get("source_key") or "") or not str(row.get("source_order_rank") or ""):
            raise ValueError(f"v24_formal_source_identity:{index}")
        for field in ("source_hash", "normalized_text_hash"):
            if not SHA256_RE.fullmatch(str(row.get(field) or "")):
                raise ValueError(f"v24_formal_{field}:{index}")
        pair_ids: set[str] = set()
        for pair in row.get("selected_pairs", []) or []:
            if not isinstance(pair, Mapping):
                raise ValueError(f"v24_formal_pair_invalid:{index}")
            pair_id = str(pair.get("pair_id") or "")
            if not pair_id or pair_id in pair_ids:
                raise ValueError(f"v24_formal_pair_identity:{index}")
            pair_ids.add(pair_id)
            if not str(pair.get("q_plus_text") or "") or not str(pair.get("q_minus_text") or ""):
                raise ValueError(f"v24_formal_query_text:{index}")
            if pair.get("generation_mode") not in {"luna_naturalized", "deterministic_fallback"}:
                raise ValueError(f"v24_formal_generation_mode:{index}")
            if pair.get("query_manifest_hash") != _query_manifest_hash(pair):
                raise ValueError("v24_formal_query_manifest_drift")
    if frozen_rows is not None:
        if len(frozen_rows) != len(rows):
            raise ValueError("v24_formal_integrity_row_count")
        for index, (current, frozen) in enumerate(zip(rows, frozen_rows)):
            for candidate in (current, frozen):
                declared = candidate.get("integrity_hash")
                if not SHA256_RE.fullmatch(str(declared or "")):
                    raise ValueError(f"v24_formal_integrity_hash_missing:{index}")
                if declared != _integrity_row_hash(candidate):
                    raise ValueError(f"v24_formal_integrity_hash_invalid:{index}")
            if _integrity_row_hash(current) != _integrity_row_hash(frozen):
                raise ValueError(f"v24_formal_integrity_drift:{index}")
    return {
        "status": "passed",
        "source_count": expected_source_count,
        "queries_per_source": queries_per_source,
    }


def _integrity_row_hash(row: Mapping[str, Any]) -> str:
    """Hash only frozen source/pair/query content, never membership labels."""

    pairs = []
    for pair in row.get("selected_pairs", []) or []:
        if not isinstance(pair, Mapping):
            pairs.append(pair)
            continue
        pairs.append(
            {
                "pair_id": pair.get("pair_id"),
                "upstream_pair_id": pair.get("upstream_pair_id"),
                "original_entity": pair.get("original_entity"),
                "replacement_entity": pair.get("replacement_entity"),
                "canonical_proposition_template": pair.get("canonical_proposition_template"),
                "canonical_true": pair.get("canonical_true"),
                "canonical_counterfactual": pair.get("canonical_counterfactual"),
                "q_plus_text": pair.get("q_plus_text"),
                "q_minus_text": pair.get("q_minus_text"),
                "query_manifest_hash": pair.get("query_manifest_hash"),
                "generation_mode": pair.get("generation_mode"),
            }
        )
    return sha256_obj(
        {
            "dataset": row.get("dataset"),
            "source_key": row.get("source_key"),
            "source_order_rank": row.get("source_order_rank"),
            "source_hash": row.get("source_hash"),
            "normalized_text_hash": row.get("normalized_text_hash"),
            "max_candidate_facts_per_source": row.get(
                "max_candidate_facts_per_source", DEFAULT_MAX_CANDIDATE_FACTS_PER_SOURCE
            ),
            "selected_pairs": pairs,
            "query_count": row.get("query_count", 6),
        }
    )


def _query_manifest_hash(pair: Mapping[str, Any]) -> str:
    return sha256_obj(
        {
            "pair_id": pair.get("pair_id"),
            "q_plus_text": pair.get("q_plus_text"),
            "q_minus_text": pair.get("q_minus_text"),
            "generation_mode": pair.get("generation_mode"),
        }
    )


def validate_fallback_rate(
    rows: Sequence[Mapping[str, Any]], *, maximum: float = 0.01, denominator: int | None = None
) -> dict[str, Any]:
    pair_rows = [
        pair
        for source in rows
        for pair in (source.get("selected_pairs", []) or [])
        if isinstance(pair, Mapping)
    ]
    total = int(denominator if denominator is not None else len(pair_rows))
    if total <= 0:
        raise ValueError("v24_fallback_denominator_invalid")
    fallback_count = sum(pair.get("generation_mode") == "deterministic_fallback" for pair in pair_rows)
    if fallback_count > total:
        raise ValueError("v24_fallback_denominator_too_small")
    rate = fallback_count / max(1, total)
    if rate > maximum:
        raise ValueError("v24_fallback_pair_rate_exceeded")
    return {
        "status": "passed",
        "fallback_pair_count": fallback_count,
        "fallback_pair_rate": rate,
        "denominator": total,
        "maximum": maximum,
    }


def build_eligibility_manifest(
    scan_result: Mapping[str, Any],
    *,
    dataset: str,
    config: Mapping[str, Any],
    source_pool: Mapping[str, Any],
    v23_release_provenance_hash: str | None = None,
) -> dict[str, Any]:
    """Create an ordinary, content-addressed pre-split eligibility manifest."""

    if scan_result.get("status") != "passed":
        raise ValueError("v24_eligibility_scan_not_passed")
    sources = [dict(source) for source in scan_result.get("eligible_sources", [])]
    target = int(config.get("eligibility", {}).get("target_sources", 2250))
    if len(sources) != target:
        raise ValueError("v24_eligibility_manifest_source_count")
    fact_budget = get_max_candidate_facts_per_source(config)
    scan_budget = int(scan_result.get("max_candidate_facts_per_source", fact_budget))
    if scan_budget != fact_budget:
        raise ValueError("v24_eligibility_scan_fact_budget_mismatch")
    for source in sources:
        source_budget = int(source.get("max_candidate_facts_per_source", fact_budget))
        if source_budget != fact_budget:
            raise ValueError("v24_eligibility_source_fact_budget_mismatch")
        source["max_candidate_facts_per_source"] = fact_budget
        source["query_count"] = PAIRS_PER_SOURCE * 2
        source["integrity_hash"] = _integrity_row_hash(source)
    fallback = validate_fallback_rate(
        sources,
        maximum=float(config.get("formal", {}).get("fallback_pair_rate_maximum", 0.01)),
        denominator=target * PAIRS_PER_SOURCE,
    )
    contextual_denominator = int(scan_result.get("candidate_package_count", 0))
    role_pass = int(scan_result.get("contextual_role_pass_count", 0))
    correction_pass = int(scan_result.get("correction_eligibility_pass_count", 0))
    manifest = {
        "kind": "pcv_v24_eligible_source_manifest",
        "protocol_version": "pcv-mia-v24",
        "dataset": dataset,
        "config_sha256": sha256_obj(dict(config)),
        "source_pool": dict(source_pool),
        "v23_release_provenance_hash": v23_release_provenance_hash,
        "screened_source_count": int(scan_result.get("screened_source_count", 0)),
        "target_source_count": target,
        "eligible_source_count": len(sources),
        "eligible_source_rate": float(scan_result.get("eligible_source_rate", 0.0)),
        "max_candidate_facts_per_source": fact_budget,
        "candidate_pair_count": int(scan_result.get("candidate_pair_count", 0)),
        "candidate_package_count": contextual_denominator,
        "candidate_fact_count": int(scan_result.get("candidate_fact_count", 0)),
        "processed_fact_count": int(scan_result.get("processed_fact_count", 0)),
        "unprocessed_fact_count": int(scan_result.get("unprocessed_fact_count", 0)),
        "eligible_pair_count": int(scan_result.get("eligible_pair_count", 0)),
        "contextual_role_pass_count": role_pass,
        "contextual_role_pass_rate": role_pass / max(1, contextual_denominator),
        "correction_eligibility_pass_count": correction_pass,
        "correction_eligibility_pass_rate": correction_pass / max(1, role_pass),
        "final_selected_source_count": len(sources),
        "final_selected_pair_count": len(sources) * PAIRS_PER_SOURCE,
        "fallback_pair_count": fallback["fallback_pair_count"],
        "fallback_pair_rate": fallback["fallback_pair_rate"],
        "fallback_pair_rate_maximum": fallback["maximum"],
        "early_stop_source_count": int(scan_result.get("early_stop_source_count", 0)),
        "entity_diversity_1_source_count": int(scan_result.get("entity_diversity_1_source_count", 0)),
        "entity_diversity_2_source_count": int(scan_result.get("entity_diversity_2_source_count", 0)),
        "entity_diversity_3_source_count": int(scan_result.get("entity_diversity_3_source_count", 0)),
        "mean_original_entity_diversity": float(scan_result.get("mean_original_entity_diversity", 0.0)),
        "rejection_reason_distribution": dict(scan_result.get("rejection_reason_distribution", {})),
        "stealth_diagnostics": aggregate_stealth_diagnostics(sources),
        "sources": sources,
    }
    manifest["manifest_sha256"] = sha256_obj(manifest)
    return manifest


def write_eligibility_manifest(manifest: Mapping[str, Any], path: str | Path) -> str:
    payload = dict(manifest)
    expected = payload.pop("manifest_sha256", None)
    actual = sha256_obj(payload)
    if expected is not None and expected != actual:
        raise ValueError("v24_eligibility_manifest_hash_invalid")
    payload["manifest_sha256"] = actual
    write_json(payload, path)
    return actual


def validate_eligibility_manifest(
    manifest: Mapping[str, Any], *, expected_source_count: int | None = None
) -> dict[str, Any]:
    """Validate a previously frozen eligibility manifest without downstream data."""

    declared = manifest.get("manifest_sha256")
    if not isinstance(declared, str):
        raise ValueError("v24_eligibility_manifest_hash_missing")
    _reject_forbidden(manifest, path="eligibility_manifest")
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    if sha256_obj(payload) != declared:
        raise ValueError("v24_eligibility_manifest_hash_invalid")
    if payload.get("kind") != "pcv_v24_eligible_source_manifest":
        raise ValueError("v24_eligibility_manifest_kind_invalid")
    sources = payload.get("sources")
    target = int(
        expected_source_count
        if expected_source_count is not None
        else payload.get("target_source_count", 2250)
    )
    if target <= 0 or not isinstance(sources, list) or len(sources) != target:
        raise ValueError("v24_eligibility_manifest_sources_invalid")
    if int(payload.get("eligible_source_count", -1)) != target:
        raise ValueError("v24_eligibility_manifest_source_count")
    if int(payload.get("final_selected_source_count", -1)) != target:
        raise ValueError("v24_eligibility_manifest_final_source_count")
    if int(payload.get("final_selected_pair_count", -1)) != target * PAIRS_PER_SOURCE:
        raise ValueError("v24_eligibility_manifest_final_pair_count")
    fact_budget = int(payload.get("max_candidate_facts_per_source", 0))
    if fact_budget < PAIRS_PER_SOURCE:
        raise ValueError("v24_eligibility_manifest_fact_budget")
    if fact_budget != DEFAULT_MAX_CANDIDATE_FACTS_PER_SOURCE:
        raise ValueError("v24_eligibility_manifest_fact_budget_not_frozen")
    candidate_fact_count = int(payload.get("candidate_fact_count", 0))
    processed_fact_count = int(payload.get("processed_fact_count", candidate_fact_count))
    unprocessed_fact_count = int(
        payload.get("unprocessed_fact_count", candidate_fact_count - processed_fact_count)
    )
    if (
        candidate_fact_count < 0
        or processed_fact_count < 0
        or unprocessed_fact_count < 0
        or candidate_fact_count != processed_fact_count + unprocessed_fact_count
    ):
        raise ValueError("v24_eligibility_manifest_fact_coverage")
    dataset = str(payload.get("dataset") or "")
    seen_sources: set[str] = set()
    seen_source_hashes: set[str] = set()
    seen_pairs: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping) or not source.get("eligible"):
            raise ValueError("v24_eligibility_manifest_source_invalid")
        source_key = str(source.get("source_key") or "")
        source_hash = str(source.get("source_hash") or "")
        if not source_key or source_key in seen_sources or not SHA256_RE.fullmatch(source_hash):
            raise ValueError("v24_eligibility_manifest_source_identity")
        if source_hash in seen_source_hashes:
            raise ValueError("v24_eligibility_manifest_source_overlap")
        if dataset and source.get("dataset") != dataset:
            raise ValueError("v24_eligibility_manifest_dataset_mismatch")
        seen_sources.add(source_key)
        seen_source_hashes.add(source_hash)
        if len(source.get("selected_pairs", [])) != PAIRS_PER_SOURCE:
            raise ValueError("v24_eligibility_manifest_pair_count")
        if int(source.get("max_candidate_facts_per_source", -1)) != fact_budget:
            raise ValueError("v24_eligibility_manifest_source_fact_budget")
        source_candidate_count = int(source.get("candidate_fact_count", 0))
        source_processed_count = int(
            source.get("processed_fact_count", source_candidate_count)
        )
        source_unprocessed_count = int(
            source.get(
                "unprocessed_fact_count", source_candidate_count - source_processed_count
            )
        )
        if (
            source_candidate_count < 0
            or source_processed_count < 0
            or source_processed_count > fact_budget
            or source_unprocessed_count < 0
            or source_candidate_count != source_processed_count + source_unprocessed_count
        ):
            raise ValueError("v24_eligibility_manifest_source_fact_coverage")
        if int(source.get("query_count", -1)) != PAIRS_PER_SOURCE * 2:
            raise ValueError("v24_eligibility_manifest_query_budget")
        if source.get("integrity_hash") != _integrity_row_hash(source):
            raise ValueError("v24_eligibility_manifest_integrity_drift")
        for pair in source.get("selected_pairs", []) or []:
            if not isinstance(pair, Mapping) or not str(pair.get("pair_id") or ""):
                raise ValueError("v24_eligibility_manifest_pair_invalid")
            pair_id = str(pair["pair_id"])
            if pair_id in seen_pairs:
                raise ValueError("v24_eligibility_manifest_pair_overlap")
            seen_pairs.add(pair_id)
            if pair.get("query_manifest_hash") != _query_manifest_hash(pair):
                raise ValueError("v24_eligibility_manifest_query_manifest_hash")
    validate_fallback_rate(
        sources,
        maximum=float(payload.get("fallback_pair_rate_maximum", 0.01)),
        denominator=len(sources) * PAIRS_PER_SOURCE,
    )
    return {
        "status": "passed",
        "dataset": payload.get("dataset"),
        "eligible_source_count": target,
        "final_selected_pair_count": target * PAIRS_PER_SOURCE,
    }


def build_split_manifest(
    eligible_manifest: Mapping[str, Any], *, dataset: str, selection_seed: int = 42
) -> dict[str, Any]:
    sources = eligible_manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("v24_eligible_manifest_sources_missing")
    validate_eligibility_manifest(eligible_manifest)
    if eligible_manifest.get("dataset") != dataset:
        raise ValueError("v24_eligible_manifest_dataset_mismatch")
    rows = deterministic_split(sources, dataset=dataset, selection_seed=selection_seed)
    payload: dict[str, Any] = {
        "kind": "pcv_v24_split_manifest",
        "protocol_version": "pcv-mia-v24",
        "dataset": dataset,
        "selection_seed": selection_seed,
        "eligible_manifest_sha256": eligible_manifest.get("manifest_sha256"),
        "rows": rows,
    }
    payload["manifest_sha256"] = sha256_obj(payload)
    return payload


def write_split_manifest(manifest: Mapping[str, Any], path: str | Path) -> str:
    payload = dict(manifest)
    expected = payload.pop("manifest_sha256", None)
    actual = sha256_obj(payload)
    if expected is not None and expected != actual:
        raise ValueError("v24_split_manifest_hash_invalid")
    payload["manifest_sha256"] = actual
    write_json(payload, path)
    return actual


def validate_split_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    declared = manifest.get("manifest_sha256")
    if not isinstance(declared, str):
        raise ValueError("v24_split_manifest_hash_missing")
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    if sha256_obj(payload) != declared:
        raise ValueError("v24_split_manifest_hash_invalid")
    dataset = str(payload.get("dataset") or "")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("v24_split_manifest_rows_missing")
    return validate_split_rows(rows, dataset=dataset)


def build_query_manifest(eligible_manifest: Mapping[str, Any]) -> dict[str, Any]:
    """展平冻结 pair 为普通 Q+/Q- manifest，不改变 query budget。"""

    validate_eligibility_manifest(eligible_manifest)
    rows: list[dict[str, Any]] = []
    for source in eligible_manifest["sources"]:
        for pair in source["selected_pairs"]:
            for polarity, text, expected in (
                ("Q_plus", pair["q_plus_text"], "supported"),
                ("Q_minus", pair["q_minus_text"], "contradicted_exact_correction"),
            ):
                rows.append(
                    {
                        "dataset": source.get("dataset"),
                        "source_key": source.get("source_key"),
                        "source_hash": source.get("source_hash"),
                        "pair_id": pair.get("pair_id"),
                        "query_id": sha256_obj({"pair_id": pair.get("pair_id"), "polarity": polarity}),
                        "polarity": polarity,
                        "query_text": text,
                        "expected_success": expected,
                        "original_entity": pair.get("original_entity"),
                        "replacement_entity": pair.get("replacement_entity"),
                        "generation_mode": pair.get("generation_mode"),
                        "query_manifest_hash": pair.get("query_manifest_hash"),
                        "stealth_diagnostics": pair.get("stealth_diagnostics", {}),
                        "retrieval_anchor_diagnostics": pair.get("retrieval_anchor_diagnostics", {}),
                    }
                )
    manifest: dict[str, Any] = {
        "kind": "pcv_v24_query_manifest",
        "protocol_version": "pcv-mia-v24",
        "dataset": eligible_manifest.get("dataset"),
        "eligible_manifest_sha256": eligible_manifest.get("manifest_sha256"),
        "query_count": len(rows),
        "queries_per_source": PAIRS_PER_SOURCE * 2,
        "rows": rows,
    }
    manifest["manifest_sha256"] = sha256_obj(manifest)
    return manifest


def write_query_manifest(manifest: Mapping[str, Any], path: str | Path) -> str:
    payload = dict(manifest)
    expected = payload.pop("manifest_sha256", None)
    actual = sha256_obj(payload)
    if expected is not None and expected != actual:
        raise ValueError("v24_query_manifest_hash_invalid")
    payload["manifest_sha256"] = actual
    write_json(payload, path)
    return actual


def validate_query_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    declared = manifest.get("manifest_sha256")
    if not isinstance(declared, str):
        raise ValueError("v24_query_manifest_hash_missing")
    _reject_forbidden(manifest, path="query_manifest")
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    if sha256_obj(payload) != declared:
        raise ValueError("v24_query_manifest_hash_invalid")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != int(payload.get("query_count", -1)):
        raise ValueError("v24_query_manifest_rows_invalid")
    if payload.get("kind") != "pcv_v24_query_manifest":
        raise ValueError("v24_query_manifest_kind_invalid")
    if int(payload.get("queries_per_source", -1)) != PAIRS_PER_SOURCE * 2:
        raise ValueError("v24_query_manifest_queries_per_source")
    source_rows: dict[str, list[Mapping[str, Any]]] = {}
    pair_rows: dict[str, list[Mapping[str, Any]]] = {}
    seen_query_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("v24_query_manifest_row_invalid")
        source_key = str(row.get("source_key") or "")
        pair_id = str(row.get("pair_id") or "")
        polarity = str(row.get("polarity") or "")
        if not source_key or not pair_id or polarity not in QUERY_POLARITIES:
            raise ValueError("v24_query_manifest_row_invalid")
        if payload.get("dataset") is not None and row.get("dataset") != payload.get("dataset"):
            raise ValueError("v24_query_manifest_dataset_mismatch")
        expected_query_id = sha256_obj({"pair_id": pair_id, "polarity": polarity})
        if row.get("query_id") != expected_query_id or expected_query_id in seen_query_ids:
            raise ValueError("v24_query_manifest_query_id")
        seen_query_ids.add(expected_query_id)
        expected_success = "supported" if polarity == "Q_plus" else "contradicted_exact_correction"
        if row.get("expected_success") != expected_success or not str(row.get("query_text") or "").strip():
            raise ValueError("v24_query_manifest_semantics")
        source_rows.setdefault(source_key, []).append(row)
        pair_rows.setdefault(pair_id, []).append(row)
    if not source_rows or len(rows) != len(source_rows) * PAIRS_PER_SOURCE * 2:
        raise ValueError("v24_query_manifest_source_count")
    for source_key, source_items in source_rows.items():
        if len(source_items) != PAIRS_PER_SOURCE * 2:
            raise ValueError(f"v24_query_manifest_source_query_count:{source_key}")
        pair_ids = {str(row["pair_id"]) for row in source_items}
        if len(pair_ids) != PAIRS_PER_SOURCE:
            raise ValueError(f"v24_query_manifest_source_pair_count:{source_key}")
        source_hashes = {str(row.get("source_hash") or "") for row in source_items}
        if len(source_hashes) != 1 or not SHA256_RE.fullmatch(next(iter(source_hashes))):
            raise ValueError(f"v24_query_manifest_source_hash:{source_key}")
    for pair_id, pair_items in pair_rows.items():
        if len(pair_items) != 2 or {str(row["polarity"]) for row in pair_items} != set(QUERY_POLARITIES):
            raise ValueError(f"v24_query_manifest_pair_rows:{pair_id}")
        plus = next(row for row in pair_items if row["polarity"] == "Q_plus")
        minus = next(row for row in pair_items if row["polarity"] == "Q_minus")
        if (
            plus.get("source_key") != minus.get("source_key")
            or plus.get("source_hash") != minus.get("source_hash")
            or plus.get("original_entity") != minus.get("original_entity")
            or plus.get("replacement_entity") != minus.get("replacement_entity")
        ):
            raise ValueError(f"v24_query_manifest_pair_binding:{pair_id}")
        if plus.get("generation_mode") != minus.get("generation_mode"):
            raise ValueError(f"v24_query_manifest_generation_mode:{pair_id}")
        expected_hash = _query_manifest_hash(
            {
                "pair_id": pair_id,
                "q_plus_text": plus.get("query_text"),
                "q_minus_text": minus.get("query_text"),
                "generation_mode": plus.get("generation_mode"),
            }
        )
        if plus.get("query_manifest_hash") != expected_hash or minus.get("query_manifest_hash") != expected_hash:
            raise ValueError(f"v24_query_manifest_pair_hash:{pair_id}")
    counts = Counter(str(row.get("polarity")) for row in rows)
    if counts.get("Q_plus", 0) != counts.get("Q_minus", 0):
        raise ValueError("v24_query_manifest_polarity_balance")
    return {
        "status": "passed",
        "dataset": payload.get("dataset"),
        "query_count": len(rows),
        "source_count": len(source_rows),
    }


def iter_frozen_source_pool(project_root: str | Path, dataset: str) -> Iterator[dict[str, Any]]:
    """Yield sources strictly in v22's frozen order, without membership fields."""

    root = Path(project_root).resolve()
    from .restoration_first_v23 import load_design_config

    config = load_design_config(root)
    pool = _pool_contract(config, dataset)
    with FrozenSourcePoolReader(project_root=root, dataset=dataset, pool=pool) as reader:
        for source_key in reader.source_order:
            yield reader._read_source(source_key)


def scan_frozen_source_pool(
    project_root: str | Path,
    dataset: str,
    *,
    candidate_provider: CandidateProvider,
    target_sources: int = 2250,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run the pre-split scanner against the actual membership-blind v22 pool."""

    config = load_v24_config(project_root)
    fact_budget = get_max_candidate_facts_per_source(config)
    requested_budget = kwargs.pop("max_candidate_facts_per_source", fact_budget)
    if int(requested_budget) != fact_budget:
        raise ValueError("v24_frozen_scan_fact_budget_mismatch")
    return scan_until_target(
        iter_frozen_source_pool(project_root, dataset),
        candidate_provider=candidate_provider,
        target_sources=target_sources,
        max_candidate_facts_per_source=fact_budget,
        **kwargs,
    )


def source_pool_bindings(project_root: str | Path = ".") -> dict[str, dict[str, Any]]:
    """Return hashes/counts for the already-frozen v22 pools without membership labels."""

    root = Path(project_root).resolve()
    # 这里只解析既有 v22 pool 绑定，不选择或读取 v23 final source set。
    from .restoration_first_v23 import load_design_config

    v23 = load_design_config(root)
    output: dict[str, dict[str, Any]] = {}
    for dataset in DATASET_ORDER:
        pool = _pool_contract(v23, dataset)
        manifest_path = root / str(pool["manifest_path"])
        order_path = root / str(pool["source_order_path"])
        database_path = root / str(pool["database_path"])
        if not manifest_path.is_file() or sha256_file(manifest_path) != str(pool["manifest_sha256"]):
            raise RuntimeError(f"v24_source_pool_manifest_drift:{dataset}")
        if not order_path.is_file() or sha256_file(order_path) != str(pool["source_order_file_sha256"]):
            raise RuntimeError(f"v24_source_pool_order_drift:{dataset}")
        if not database_path.is_file():
            raise RuntimeError(f"v24_source_pool_database_missing:{dataset}")
        output[dataset] = {
            "manifest_path": str(manifest_path.relative_to(root)).replace("\\", "/"),
            "manifest_sha256": sha256_file(manifest_path),
            "source_order_path": str(order_path.relative_to(root)).replace("\\", "/"),
            "source_order_sha256": sha256_file(order_path),
            "source_order_content_sha256": str(pool.get("source_order_sha256") or ""),
            "database_path": str(database_path.relative_to(root)).replace("\\", "/"),
            "database_sha256": str(pool.get("database_sha256") or ""),
            "source_pool_identity_sha256": str(pool.get("source_pool_identity_sha256") or ""),
            "source_count": int(pool["source_count"]),
            "membership_labels_read": [],
        }
    return output
