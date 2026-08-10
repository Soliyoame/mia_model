"""Source-level adapted MEntA baseline for the shared PCV-MIA harness."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from statistics import mean
from typing import Any, Protocol, Sequence

from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import read_json, read_jsonl, resolve_path


MENTA_PROTOCOL_VERSION = "menta-source-adapted-v2"
MENTA_QUERY_PROMPT_VERSION = "menta-query-generation-v1"
MENTA_RAG_PROMPT_VERSION = "menta-rag-answer-v1"
MENTA_QUERY_COUNT = 5
MENTA_NLI_MODEL_ID = "tasksource/deberta-base-long-nli"
MENTA_NLI_REVISION = "04dcf11f844b07bc57015169fca2b7d6df8299d5"

# The seven semantic refusal templates are evaluated with NLI rather than
# matched as literal strings, following the MEntA refusal-detection protocol.
MENTA_REFUSAL_HYPOTHESES: tuple[str, ...] = (
    "The answer says that it does not know the requested information.",
    "The answer says that the requested information is unavailable.",
    "The answer says that there is not enough information to respond.",
    "The answer says that it cannot answer the question.",
    "The answer refuses to provide the requested information.",
    "The answer asks the user to provide more information before responding.",
    "The answer says that the question cannot be answered from the available context.",
)

_WHITESPACE_RE = re.compile(r"\s+")
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


class NLIPredictor(Protocol):
    """Minimal NLI interface used by MEntA and its network-free tests."""

    def probabilities(
        self,
        pairs: Sequence[tuple[str, str]],
    ) -> list[dict[str, float]]:
        ...


def build_menta_query(summary: str, question: str) -> str:
    """Build the frozen broad-query form used for both retrieval and answering."""

    normalized_summary = _WHITESPACE_RE.sub(" ", str(summary)).strip()
    normalized_question = _WHITESPACE_RE.sub(" ", str(question)).strip()
    if not normalized_summary or not normalized_question:
        raise ValueError("MEntA summary and question must both be non-empty")
    return f"Topic summary: {normalized_summary}\nQuestion: {normalized_question}"


def build_menta_rag_prompt(query: str, contexts: list[str]) -> str:
    """Build MEntA's natural information-seeking RAG prompt."""

    joined = "\n\n---\n\n".join(contexts)
    return (
        "Use the retrieved information to answer the user's information-seeking "
        "question directly and concisely. If the retrieved information is insufficient, "
        "say so instead of inventing facts.\n"
        "Retrieved information:\n"
        "---------------------\n"
        f"{joined}\n"
        "---------------------\n"
        f"{query}\n"
        "Answer:"
    )


def split_atomic_claims(response: str) -> list[str]:
    """Split an English response into deterministic sentence-like atomic claims."""

    normalized = str(response or "").replace("\r\n", "\n").replace("\r", "\n")
    claims: list[str] = []
    for block in re.split(r"\n+", normalized):
        block = _BULLET_PREFIX_RE.sub("", block).strip()
        if not block:
            continue
        for sentence in _SENTENCE_BOUNDARY_RE.split(block):
            claim = _WHITESPACE_RE.sub(" ", sentence).strip(" \t-*")
            if claim:
                claims.append(claim)
    return claims


def _validate_probability_row(row: dict[str, float]) -> dict[str, float]:
    required = {"entailment", "neutral", "contradiction"}
    if set(row) != required:
        raise RuntimeError(
            f"NLI output labels must be exactly {sorted(required)}; got {sorted(row)}"
        )
    result = {key: float(row[key]) for key in required}
    if any(value < 0.0 or value > 1.0 for value in result.values()):
        raise RuntimeError(f"NLI probabilities are outside [0, 1]: {result}")
    return result


def is_entailment(row: dict[str, float]) -> bool:
    """Apply MEntA's strict argmax entailment rule."""

    probabilities = _validate_probability_row(row)
    return probabilities["entailment"] > max(
        probabilities["neutral"],
        probabilities["contradiction"],
    )


def validate_nli_snapshot(
    snapshot_dir: str | Path,
    *,
    expected_model_id: str = MENTA_NLI_MODEL_ID,
    expected_revision: str = MENTA_NLI_REVISION,
) -> dict[str, Any]:
    """Verify the frozen model identity and every file hash before loading."""

    root = Path(snapshot_dir)
    manifest_path = root / "pcv_snapshot_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"MEntA NLI snapshot manifest not found: {manifest_path}")
    manifest = read_json(manifest_path)
    if str(manifest.get("repo_id") or "") != expected_model_id:
        raise RuntimeError("MEntA NLI snapshot model id mismatch")
    if str(manifest.get("revision") or "") != expected_revision:
        raise RuntimeError("MEntA NLI snapshot revision mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("MEntA NLI snapshot contains no file hashes")
    required_files = {
        "config.json",
        "model.safetensors",
        "spm.model",
        "tokenizer.json",
        "tokenizer_config.json",
    }
    if not required_files.issubset(files):
        missing = sorted(required_files - set(files))
        raise RuntimeError(f"MEntA NLI snapshot missing required files: {missing}")
    for relative in files:
        relative_path = PurePosixPath(str(relative))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError(f"Unsafe MEntA NLI snapshot path: {relative}")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual_files != set(files):
        raise RuntimeError(
            "MEntA NLI snapshot file list mismatch: "
            f"missing={sorted(set(files) - actual_files)}, "
            f"extra={sorted(actual_files - set(files))}"
        )
    for relative, metadata in files.items():
        relative_path = PurePosixPath(str(relative))
        path = root.joinpath(*relative_path.parts)
        if not path.is_file():
            raise FileNotFoundError(f"MEntA NLI snapshot file not found: {path}")
        expected_size = int((metadata or {}).get("size") or -1)
        expected_hash = str((metadata or {}).get("sha256") or "")
        if path.stat().st_size != expected_size or sha256_file(path) != expected_hash:
            raise RuntimeError(f"MEntA NLI snapshot file verification failed: {relative}")
    return {
        "model_id": expected_model_id,
        "revision": expected_revision,
        "snapshot_dir": str(root.resolve()),
        "snapshot_manifest_path": str(manifest_path.resolve()),
        "snapshot_manifest_sha256": sha256_file(manifest_path),
    }


@dataclass
class TransformersNLIPredictor:
    """Hash-verified, local-only DeBERTa NLI runtime."""

    snapshot_dir: str | Path
    model_id: str = MENTA_NLI_MODEL_ID
    revision: str = MENTA_NLI_REVISION
    device: str = "cuda"
    require_cuda: bool = True
    batch_size: int = 16
    max_length: int = 1280

    def __post_init__(self) -> None:
        self.identity = validate_nli_snapshot(
            self.snapshot_dir,
            expected_model_id=self.model_id,
            expected_revision=self.revision,
        )
        if self.batch_size <= 0 or self.max_length <= 0:
            raise ValueError("MEntA NLI batch_size and max_length must be positive")

        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if self.require_cuda and not torch.cuda.is_available():
            raise RuntimeError("MEntA formal NLI runtime requires CUDA")
        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(f"MEntA NLI device is unavailable: {self.device}")

        source = str(Path(self.snapshot_dir).resolve())
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(
            source,
            local_files_only=True,
        )
        self._model = AutoModelForSequenceClassification.from_pretrained(
            source,
            local_files_only=True,
        )
        labels = {
            int(index): str(label).casefold()
            for index, label in dict(self._model.config.id2label).items()
        }
        required_labels = {"entailment", "neutral", "contradiction"}
        if set(labels.values()) != required_labels:
            raise RuntimeError(f"Unexpected MEntA NLI labels: {labels}")
        self._label_indices = {label: index for index, label in labels.items()}
        self._model.to(self.device)
        self._model.eval()
        self._lock = threading.Lock()

    def probabilities(
        self,
        pairs: Sequence[tuple[str, str]],
    ) -> list[dict[str, float]]:
        if not pairs:
            return []
        rows: list[dict[str, float]] = []
        with self._lock:
            for start in range(0, len(pairs), self.batch_size):
                batch = list(pairs[start : start + self.batch_size])
                encoded = self._tokenizer(
                    [premise for premise, _ in batch],
                    [hypothesis for _, hypothesis in batch],
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                with self._torch.inference_mode():
                    logits = self._model(**encoded).logits
                    probabilities = self._torch.softmax(logits, dim=-1).cpu().tolist()
                for values in probabilities:
                    rows.append(
                        {
                            label: float(values[index])
                            for label, index in self._label_indices.items()
                        }
                    )
        return rows


@dataclass(frozen=True)
class MEntAQueryBundle:
    """Validated query rows and immutable provenance for one dataset."""

    dataset: str
    query_path: Path
    manifest_path: Path
    rows_by_doc_id: dict[str, dict[str, Any]]
    manifest: dict[str, Any]
    identity: dict[str, Any]


def validate_menta_query_row(row: dict[str, Any], dataset: str) -> dict[str, Any]:
    if str(row.get("protocol_version") or "") != MENTA_PROTOCOL_VERSION:
        raise RuntimeError("MEntA query row protocol version mismatch")
    if str(row.get("query_prompt_version") or "") != MENTA_QUERY_PROMPT_VERSION:
        raise RuntimeError("MEntA query row prompt version mismatch")
    if str(row.get("dataset") or "") != dataset:
        raise RuntimeError("MEntA query row dataset mismatch")
    doc_id = str(row.get("doc_id") or "").strip()
    source_key = str(row.get("source_key") or "").strip()
    group = str(row.get("group") or "").strip()
    text_hash = str(row.get("representative_text_hash") or "").strip()
    summary = _WHITESPACE_RE.sub(" ", str(row.get("summary") or "")).strip()
    questions = row.get("questions")
    queries = row.get("queries")
    if not doc_id or not source_key or group not in {"KB_Member", "True_Non_Member"}:
        raise RuntimeError("MEntA query row identity is incomplete")
    if not re.fullmatch(r"[0-9a-f]{64}", text_hash):
        raise RuntimeError(f"MEntA query row has invalid representative hash: {doc_id}")
    if not summary or "\n" in summary:
        raise RuntimeError(f"MEntA summary must be one non-empty line: {doc_id}")
    if not isinstance(questions, list) or len(questions) != MENTA_QUERY_COUNT:
        raise RuntimeError(f"MEntA requires exactly five questions: {doc_id}")
    normalized_questions = [
        _WHITESPACE_RE.sub(" ", str(question)).strip()
        for question in questions
    ]
    if any(not question for question in normalized_questions):
        raise RuntimeError(f"MEntA questions must be non-empty: {doc_id}")
    if len({question.casefold() for question in normalized_questions}) != MENTA_QUERY_COUNT:
        raise RuntimeError(f"MEntA questions must be unique: {doc_id}")
    expected_queries = [
        build_menta_query(summary, question)
        for question in normalized_questions
    ]
    if not isinstance(queries, list) or [str(query) for query in queries] != expected_queries:
        raise RuntimeError(f"MEntA combined queries are not frozen correctly: {doc_id}")
    return {
        **row,
        "doc_id": doc_id,
        "source_key": source_key,
        "group": group,
        "representative_text_hash": text_hash,
        "summary": summary,
        "questions": normalized_questions,
        "queries": expected_queries,
    }


def load_menta_query_bundle(
    query_path: str | Path,
    *,
    dataset: str,
    representative_manifest_hash: str,
) -> MEntAQueryBundle:
    """Load and fail-closed validate the frozen offline query artifact."""

    path = Path(query_path)
    manifest_path = path.with_suffix(".manifest.json")
    if not path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"MEntA query artifact is incomplete: {path}")
    manifest = read_json(manifest_path)
    expected = {
        "protocol_version": MENTA_PROTOCOL_VERSION,
        "query_prompt_version": MENTA_QUERY_PROMPT_VERSION,
        "dataset": dataset,
        "queries_per_source": MENTA_QUERY_COUNT,
        "representative_chunk_manifest_hash": representative_manifest_hash,
    }
    mismatches = {
        key: {"expected": value, "actual": manifest.get(key)}
        for key, value in expected.items()
        if manifest.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"MEntA query manifest mismatch: {mismatches}")
    sibling_profile = manifest.get("sibling_profile")
    if not isinstance(sibling_profile, dict):
        raise RuntimeError("MEntA query manifest is missing sibling profile identity")
    sibling_identity = dict(sibling_profile)
    sibling_identity_hash = str(sibling_identity.pop("profile_hash", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", sibling_identity_hash):
        raise RuntimeError("MEntA query manifest has invalid sibling identity hash")
    if sha256_obj(sibling_identity) != sibling_identity_hash:
        raise RuntimeError("MEntA query manifest sibling identity hash mismatch")
    if str(manifest.get("sibling_identity_hash") or "") != sibling_identity_hash:
        raise RuntimeError("MEntA query manifest sibling identity binding mismatch")
    query_hash = sha256_file(path)
    if query_hash != str(manifest.get("output_sha256") or ""):
        raise RuntimeError("MEntA query artifact hash mismatch")
    raw_rows = list(read_jsonl(path))
    rows = [validate_menta_query_row(row, dataset) for row in raw_rows]
    for raw, row in zip(raw_rows, rows):
        if str(row.get("sibling_identity_hash") or "") != sibling_identity_hash:
            raise RuntimeError(
                f"MEntA query row sibling identity mismatch: {row['doc_id']}"
            )
        if str(raw.get("row_hash") or "") != query_row_hash(row):
            raise RuntimeError(f"MEntA query row hash mismatch: {row['doc_id']}")
    if len(rows) != int(manifest.get("source_count") or -1):
        raise RuntimeError("MEntA query source count mismatch")
    rows_by_doc_id = {row["doc_id"]: row for row in rows}
    if len(rows_by_doc_id) != len(rows):
        raise RuntimeError("MEntA query artifact contains duplicate doc_id values")
    if len({str(row["source_key"]) for row in rows}) != len(rows):
        raise RuntimeError("MEntA query artifact contains duplicate source_key values")
    row_binding_hash = sha256_obj(
        [
            {
                "doc_id": row["doc_id"],
                "source_key": row["source_key"],
                "row_hash": row["row_hash"],
            }
            for row in rows
        ]
    )
    if row_binding_hash != str(manifest.get("row_binding_hash") or ""):
        raise RuntimeError("MEntA query row binding hash mismatch")
    identity = {
        "protocol_version": MENTA_PROTOCOL_VERSION,
        "protocol_hash": sha256_obj(
            {
                "protocol_version": MENTA_PROTOCOL_VERSION,
                "query_prompt_version": MENTA_QUERY_PROMPT_VERSION,
                "rag_prompt_version": MENTA_RAG_PROMPT_VERSION,
                "query_count": MENTA_QUERY_COUNT,
                "refusal_hypotheses": MENTA_REFUSAL_HYPOTHESES,
            }
        ),
        "query_path": str(path.resolve()),
        "query_sha256": query_hash,
        "query_manifest_path": str(manifest_path.resolve()),
        "query_manifest_sha256": sha256_file(manifest_path),
        "representative_chunk_manifest_hash": representative_manifest_hash,
        "sibling_profile": sibling_profile,
        "sibling_identity_hash": sibling_identity_hash,
    }
    return MEntAQueryBundle(
        dataset=dataset,
        query_path=path,
        manifest_path=manifest_path,
        rows_by_doc_id=rows_by_doc_id,
        manifest=manifest,
        identity=identity,
    )


@dataclass
class MEntARuntime:
    """Execute five frozen MEntA queries for the current harness target."""

    bundle: MEntAQueryBundle
    predictor: NLIPredictor
    nli_identity: dict[str, Any]

    @classmethod
    def from_config(
        cls,
        *,
        dataset: str,
        config: dict[str, Any],
        representative_manifest_hash: str,
    ) -> "MEntARuntime":
        query_path = (
            resolve_path(config["query_manifest_dir"])
            / f"{dataset}_menta_queries.jsonl"
        )
        bundle = load_menta_query_bundle(
            query_path,
            dataset=dataset,
            representative_manifest_hash=representative_manifest_hash,
        )
        nli_cfg = dict(config.get("nli") or {})
        model_id = str(nli_cfg.get("model_id") or "")
        revision = str(nli_cfg.get("revision") or "")
        if model_id != MENTA_NLI_MODEL_ID:
            raise RuntimeError(f"MEntA requires NLI model {MENTA_NLI_MODEL_ID}")
        if revision != MENTA_NLI_REVISION:
            raise RuntimeError(f"MEntA requires NLI revision {MENTA_NLI_REVISION}")
        if nli_cfg.get("local_files_only") is not True:
            raise RuntimeError("MEntA formal NLI runtime must be local_files_only")
        device = str(nli_cfg.get("device") or "")
        if nli_cfg.get("require_cuda") is not True or not device.startswith("cuda"):
            raise RuntimeError("MEntA formal NLI runtime must require a CUDA device")
        if int(config.get("queries_per_source") or 0) != MENTA_QUERY_COUNT:
            raise RuntimeError("MEntA configuration must freeze five queries per source")
        predictor = TransformersNLIPredictor(
            snapshot_dir=resolve_path(nli_cfg["snapshot_dir"]),
            model_id=model_id,
            revision=revision,
            device=device,
            require_cuda=True,
            batch_size=int(nli_cfg.get("batch_size") or 16),
            max_length=int(nli_cfg.get("max_length") or 1280),
        )
        return cls(
            bundle=bundle,
            predictor=predictor,
            nli_identity=dict(predictor.identity),
        )

    @property
    def identity(self) -> dict[str, Any]:
        return {
            **self.bundle.identity,
            "nli": self.nli_identity,
        }

    def validate_targets(self, targets: Sequence[dict[str, Any]]) -> None:
        """Bind selected harness targets to the frozen query rows."""

        for target in targets:
            doc_id = str(target.get("doc_id") or "")
            row = self.bundle.rows_by_doc_id.get(doc_id)
            if row is None:
                raise RuntimeError(f"MEntA query row missing for target: {doc_id}")
            source_key = str(
                target.get("source_key")
                or target.get("source_id")
                or target.get("doc_id")
                or ""
            )
            if str(row["source_key"]) != source_key:
                raise RuntimeError(f"MEntA source binding mismatch: {doc_id}")
            if str(row["group"]) != str(target.get("group") or ""):
                raise RuntimeError(f"MEntA membership-group binding mismatch: {doc_id}")
            if str(row["representative_text_hash"]) != sha256_text(
                str(target.get("text") or "")
            ):
                raise RuntimeError(f"MEntA representative text hash mismatch: {doc_id}")

    def score_target(self, text: str, services: Any) -> float:
        target = services.scope_target()
        doc_id = str(target.get("doc_id") or "")
        row = self.bundle.rows_by_doc_id.get(doc_id)
        if row is None:
            raise RuntimeError(f"MEntA query row missing for target: {doc_id}")
        if str(row["representative_text_hash"]) != sha256_text(text):
            raise RuntimeError(f"MEntA representative text changed: {doc_id}")

        query_details: list[dict[str, Any]] = []
        for index, query in enumerate(row["queries"]):
            answer = services.rag_answer(
                str(query),
                prompt_builder=build_menta_rag_prompt,
            )
            claims = split_atomic_claims(answer)
            claim_probabilities = self.predictor.probabilities(
                [(text, claim) for claim in claims]
            )
            if len(claim_probabilities) != len(claims):
                raise RuntimeError("MEntA NLI claim output count mismatch")
            entailed_claims = [
                claim
                for claim, probabilities in zip(claims, claim_probabilities)
                if is_entailment(probabilities)
            ]
            refusal_probabilities = self.predictor.probabilities(
                [(answer, hypothesis) for hypothesis in MENTA_REFUSAL_HYPOTHESES]
            )
            if len(refusal_probabilities) != len(MENTA_REFUSAL_HYPOTHESES):
                raise RuntimeError("MEntA NLI refusal output count mismatch")
            refusal_hits = [
                hypothesis
                for hypothesis, probabilities in zip(
                    MENTA_REFUSAL_HYPOTHESES,
                    refusal_probabilities,
                )
                if is_entailment(probabilities)
            ]
            entailment_hit = int(bool(entailed_claims))
            refusal_hit = int(bool(refusal_hits))
            query_details.append(
                {
                    "query_index": index,
                    "question": row["questions"][index],
                    "query": query,
                    "answer": answer,
                    "atomic_claim_count": len(claims),
                    "entailed_claim_count": len(entailed_claims),
                    "entailment_hit": entailment_hit,
                    "refusal_hit": refusal_hit,
                    "query_score": entailment_hit - refusal_hit,
                }
            )

        score = mean(float(detail["query_score"]) for detail in query_details)
        services.set_scope_diagnostics(
            {
                "menta": {
                    "protocol_version": MENTA_PROTOCOL_VERSION,
                    "queries": MENTA_QUERY_COUNT,
                    "entailment_hits": sum(
                        int(detail["entailment_hit"]) for detail in query_details
                    ),
                    "refusal_hits": sum(
                        int(detail["refusal_hit"]) for detail in query_details
                    ),
                    "atomic_claims": sum(
                        int(detail["atomic_claim_count"]) for detail in query_details
                    ),
                    "query_scores": [
                        int(detail["query_score"]) for detail in query_details
                    ],
                    "query_details": query_details,
                }
            }
        )
        return float(score)


def query_row_hash(row: dict[str, Any]) -> str:
    """Stable helper used by the offline preparation script and tests."""

    return sha256_obj(
        {
            "doc_id": row.get("doc_id"),
            "source_key": row.get("source_key"),
            "representative_text_hash": row.get("representative_text_hash"),
            "summary": row.get("summary"),
            "questions": row.get("questions"),
            "queries": row.get("queries"),
            "sibling_identity_hash": row.get("sibling_identity_hash"),
        }
    )


def parse_query_generation_response(raw: str) -> tuple[str, list[str]]:
    """Parse the sibling model's strict JSON response."""

    from ..llm.openai_compatible import parse_json_object

    obj = parse_json_object(raw)
    summary = _WHITESPACE_RE.sub(" ", str(obj.get("summary") or "")).strip()
    questions = obj.get("questions")
    if not isinstance(questions, list):
        raise ValueError("MEntA query-generation response must contain questions")
    row = validate_menta_query_row(
        {
            "protocol_version": MENTA_PROTOCOL_VERSION,
            "query_prompt_version": MENTA_QUERY_PROMPT_VERSION,
            "dataset": "_validation",
            "doc_id": "_validation",
            "source_key": "_validation",
            "group": "KB_Member",
            "representative_text_hash": "0" * 64,
            "summary": summary,
            "questions": questions,
            "queries": [
                build_menta_query(summary, str(question))
                for question in questions
            ],
        },
        "_validation",
    )
    return str(row["summary"]), list(row["questions"])
