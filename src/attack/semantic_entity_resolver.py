"""Local semantic precision cascade and audit consensus for v6.3 validation.

The resolver is deliberately independent from any hosted API.  Formal runs
load only locally pinned model artifacts, verify their file hashes, and stop
when a required model, schema, package version, or model hash drifts.
"""

from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import io
import json
import math
import re
import sqlite3
import warnings
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .entity_type_policy import (
    ENTITY_TYPE_POLICY_SHA256,
    ENTITY_TYPE_POLICY_VERSION,
    SEMANTIC_TARGET_TYPES,
    TARGET_SUBTYPE_SCHEMA,
    TARGET_TYPE_SCHEMA,
)


# v6.3 的正式 bulk 协议只使用 large；旧三模型共识仍保留为显式审计模式。
PRECISION_CASCADE_PROTOCOL = "local_claim_pair_v6_3_precision_cascade"
LEGACY_CONSENSUS_PROTOCOL = "local_claim_pair_v6_3_open_semantic_consensus"
SEMANTIC_RESOLVER_PROTOCOL = PRECISION_CASCADE_PROTOCOL
SUPPORTED_SEMANTIC_PROTOCOLS = frozenset(
    {PRECISION_CASCADE_PROTOCOL, LEGACY_CONSENSUS_PROTOCOL}
)
PRECISION_CASCADE_MODE = "precision_cascade"
AUDIT_CONSENSUS_MODE = "audit_consensus"

COMPETING_TYPE_SCHEMA: dict[str, str] = {
    "FINANCIAL_METRIC": (
        "An accounting, finance, tax, liability, expense, revenue, valuation, "
        "interest-rate, or performance metric rather than a named entity."
    ),
    "LEGAL_DOCUMENT_OR_PLAN": (
        "A legal document, compensation plan, policy, filing, or legal category "
        "that is not itself a contextual contractual term."
    ),
    "METHOD_OR_ALGORITHM": (
        "A scientific, statistical, computational, laboratory, or analytical "
        "method, model, algorithm, assay, or technique."
    ),
    "BIOMEDICAL_ENTITY": (
        "A disease, drug, chemical, organism, tissue, anatomical structure, "
        "clinical condition, or other biomedical entity."
    ),
    "CELL_LINE_OR_PROTEIN": (
        "A cell line, gene, protein, receptor, antibody, biomarker, or molecular "
        "construct."
    ),
    "DOCUMENT_HEADING": (
        "A paper section, table, figure, appendix, supplement, document heading, "
        "citation label, or bibliography fragment."
    ),
    "JOB_TITLE_OR_ROLE": (
        "A job title, office, professional role, participant role, or generic "
        "description of a person rather than a person's name."
    ),
    "COMMON_NOUN": (
        "An ordinary common noun, generic concept, generic department, or "
        "descriptive phrase that is not a proper named entity."
    ),
    "NONE": "No entity from the target or competing schemas.",
}

ALL_SEMANTIC_SCHEMA: dict[str, str] = {
    **TARGET_TYPE_SCHEMA,
    **TARGET_SUBTYPE_SCHEMA,
    **COMPETING_TYPE_SCHEMA,
}

BIOMEDICAL_VETO_SCHEMA: dict[str, str] = {
    "BIOMEDICAL_ENTITY": COMPETING_TYPE_SCHEMA["BIOMEDICAL_ENTITY"],
    "CELL_LINE_OR_PROTEIN": COMPETING_TYPE_SCHEMA["CELL_LINE_OR_PROTEIN"],
    "METHOD_OR_ALGORITHM": COMPETING_TYPE_SCHEMA["METHOD_OR_ALGORITHM"],
}

_LABEL_ALIASES = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "PEOPLE": "PERSON",
    "ORG": "ORG",
    "ORGANIZATION": "ORG",
    "ORGANISATION": "ORG",
    "COMPANY": "ORG",
    "INSTITUTION": "ORG",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "LOCATION": "LOCATION",
    "FAC": "LOCATION",
    "FACILITY": "LOCATION",
    "PRODUCT": "PRODUCT",
    "COMMERCIAL_PRODUCT": "PRODUCT",
    "SOFTWARE_OR_OPERATIONAL_SYSTEM": "PRODUCT",
    "NAMED_SERVICE": "PRODUCT",
    "NAMED_DEVICE_OR_TOOL": "PRODUCT",
    "EVENT": "PROJECT_NAME",
    "PROJECT": "PROJECT_NAME",
    "PROJECT_NAME": "PROJECT_NAME",
    "LAW": "CONTRACT_TERM",
    "CONTRACT": "CONTRACT_TERM",
    "CONTRACT_TERM": "CONTRACT_TERM",
    "WORK_OF_ART": "DOCUMENT_HEADING",
}


class SemanticResolverProtocolError(RuntimeError):
    """Non-recoverable formal-protocol failure with a stable reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _is_cuda_out_of_memory(exc: BaseException) -> bool:
    """只识别 CUDA 显存不足，避免把普通推理错误误当作可恢复错误。"""

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = type(current).__name__.casefold()
        message = str(current).casefold()
        if (
            "cuda out of memory" in message
            or "cuda error: out of memory" in message
            or (
                name in {"outofmemoryerror", "acceleratorerror"}
                and "memory" in message
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _release_cuda_cache() -> None:
    """释放失败批次的临时显存；没有 CUDA 时保持无副作用。"""

    gc.collect()
    try:
        import torch
    except ImportError:  # pragma: no cover - 纯 CPU 环境
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        # 异步 CUDA OOM 可能在 empty_cache 才上报；清理是 best-effort，
        # 不能遮蔽原 OOM 并阻止 8→4→2→1 的 fail-closed 重试。
        return


def _mapping_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _schema_sha256() -> str:
    payload = json.dumps(
        {
            # schema hash 绑定实体定义，不随执行协议 ID 改变；沿用 v6.3
            # 初始 schema domain，避免模型锁因运行模式切换而漂移。
            "protocol": LEGACY_CONSENSUS_PROTOCOL,
            "targets": dict(TARGET_TYPE_SCHEMA),
            "target_subtypes": dict(TARGET_SUBTYPE_SCHEMA),
            "competitors": COMPETING_TYPE_SCHEMA,
            "biomedical_veto": BIOMEDICAL_VETO_SCHEMA,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


SEMANTIC_SCHEMA_SHA256 = _schema_sha256()


def _canonical_thresholds_by_entity_type(
    raw_thresholds: Mapping[str, Mapping[str, Any]] | None,
    *,
    require_complete: bool = False,
) -> dict[str, dict[str, float]]:
    """Validate and canonically order per-entity precision thresholds."""

    if raw_thresholds is None:
        raw_thresholds = {}
    if not isinstance(raw_thresholds, Mapping):
        raise ValueError("thresholds_by_entity_type must be a mapping")
    normalized: dict[str, dict[str, float]] = {}
    required_keys = {"min_target_confidence", "min_confidence_margin"}
    for raw_entity_type, raw_values in raw_thresholds.items():
        entity_type = str(raw_entity_type or "").strip().upper()
        if entity_type not in SEMANTIC_TARGET_TYPES:
            raise ValueError(
                f"Unsupported threshold entity type: {raw_entity_type!r}"
            )
        if entity_type in normalized:
            raise ValueError(f"Duplicate threshold entity type: {entity_type}")
        if not isinstance(raw_values, Mapping):
            raise ValueError(
                f"Thresholds for {entity_type} must be a mapping"
            )
        missing = required_keys - set(raw_values)
        unexpected = set(raw_values) - required_keys
        if missing or unexpected:
            raise ValueError(
                f"Invalid threshold keys for {entity_type}: "
                f"missing={sorted(missing)!r} unexpected={sorted(unexpected)!r}"
            )
        target = float(raw_values["min_target_confidence"])
        margin = float(raw_values["min_confidence_margin"])
        if not 0.0 <= target <= 1.0:
            raise ValueError(
                f"{entity_type} min_target_confidence must be in [0, 1]"
            )
        if not 0.0 <= margin <= 1.0:
            raise ValueError(
                f"{entity_type} min_confidence_margin must be in [0, 1]"
            )
        normalized[entity_type] = {
            "min_target_confidence": target,
            "min_confidence_margin": margin,
        }
    if require_complete and set(normalized) != set(SEMANTIC_TARGET_TYPES):
        missing_types = sorted(set(SEMANTIC_TARGET_TYPES) - set(normalized))
        extra_types = sorted(set(normalized) - set(SEMANTIC_TARGET_TYPES))
        raise ValueError(
            "thresholds_by_entity_type must cover all semantic target types: "
            f"missing={missing_types!r} extra={extra_types!r}"
        )
    return {
        entity_type: normalized[entity_type]
        for entity_type in sorted(normalized)
    }


def semantic_thresholds_sha256(
    *,
    min_target_confidence: float,
    min_confidence_margin: float,
    min_consensus_votes: int,
    min_boundary_votes: int,
    biomedical_veto_threshold: float,
    overlap_threshold: float,
    thresholds_by_entity_type: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """Hash the complete precision-cascade decision surface."""

    payload = {
        "protocol": PRECISION_CASCADE_PROTOCOL,
        "execution_mode": PRECISION_CASCADE_MODE,
        "min_target_confidence": float(min_target_confidence),
        "min_confidence_margin": float(min_confidence_margin),
        "min_consensus_votes": int(min_consensus_votes),
        "min_boundary_votes": int(min_boundary_votes),
        "biomedical_veto_threshold": float(biomedical_veto_threshold),
        "overlap_threshold": float(overlap_threshold),
    }
    canonical_by_type = _canonical_thresholds_by_entity_type(
        thresholds_by_entity_type
    )
    if canonical_by_type:
        payload["thresholds_by_entity_type"] = canonical_by_type
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalise_label(label: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]+", "_", str(label or "").strip()).strip("_").upper()
    return _LABEL_ALIASES.get(compact, compact)


def _normalise_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _span_overlap_ratio(
    left: tuple[int, int],
    right: tuple[int, int],
) -> float:
    overlap = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    denominator = max(1, min(left[1] - left[0], right[1] - right[0]))
    return overlap / denominator


def _case_style(value: str) -> str:
    letters = "".join(character for character in value if character.isalpha())
    if not letters:
        return "no_letters"
    if letters.isupper():
        return "upper"
    if letters.islower():
        return "lower"
    words = re.findall(r"[A-Za-z]+", value)
    if words and all(word[:1].isupper() for word in words):
        return "title"
    return "mixed"


def semantic_subtype(value: str, entity_type: str) -> str:
    """Return a deterministic subtype used to constrain counterfactuals."""

    compact = " ".join(str(value or "").split())
    kind = _normalise_label(entity_type)
    if kind == "PERSON":
        if re.search(r"\b[A-Z]\.(?:\s+[A-Z]\.)*", compact):
            return "initialed_person_name"
        if re.match(r"(?i)^(?:dr|mr|mrs|ms|prof)\.?\s+", compact):
            return "titled_person_name"
        return "single_person_name" if len(compact.split()) == 1 else "multi_token_person_name"
    if kind == "ORG":
        if re.search(r"(?i)\b(?:inc|corp|corporation|llc|ltd|limited|plc|co)\.?\b", compact):
            return "corporate_organization"
        if re.search(r"(?i)\b(?:university|college|institute|laborator(?:y|ies)|hospital)\b", compact):
            return "academic_or_medical_organization"
        if re.search(r"(?i)\b(?:ministry|department|commission|agency|authority|council)\b", compact):
            return "government_organization"
        return "named_organization"
    if kind == "LOCATION":
        if "," in compact:
            return "compound_geographic_location"
        if re.match(r"(?i)^the\s+", compact):
            return "definite_article_location"
        return "named_geographic_location"
    if kind == "PRODUCT":
        if re.search(r"\d", compact):
            return "versioned_or_numbered_product"
        if re.search(r"(?i)\b(?:software|platform|service|suite|system)\b", compact):
            return "software_or_service_product"
        return "named_product"
    if kind == "PROJECT_NAME":
        if _case_style(compact) == "upper" and len(compact) <= 16:
            return "acronym_project_name"
        return "titled_project_name"
    if kind == "CONTRACT_TERM":
        if re.search(r"(?i)\b(?:agreement|contract|lease|license|licence)\b", compact):
            return "named_agreement"
        if re.search(r"(?i)\b(?:plan|policy)\b", compact):
            return "contractual_plan_or_policy"
        return "defined_contract_term"
    return kind.casefold() or "unknown"


def semantic_format_signature(value: str, entity_type: str) -> dict[str, Any]:
    """Record surface constraints that a counterfactual must preserve."""

    compact = " ".join(str(value or "").split())
    return {
        "entity_type": _normalise_label(entity_type),
        "case_style": _case_style(compact),
        "token_count": len(compact.split()),
        "contains_digit": bool(re.search(r"\d", compact)),
        "contains_period": "." in compact,
        "contains_comma": "," in compact,
        "contains_hyphen": "-" in compact,
        "has_definite_article": bool(re.match(r"(?i)^the\s+", compact)),
    }


def semantic_format_compatible(
    original: Mapping[str, Any],
    counterfactual: Mapping[str, Any],
    entity_type: str,
) -> bool:
    """Check only format features that carry semantic subtype information."""

    kind = _normalise_label(entity_type)
    if str(original.get("entity_type") or kind) != str(
        counterfactual.get("entity_type") or kind
    ):
        return False
    required_keys = {"contains_digit", "has_definite_article"}
    if kind == "PERSON":
        required_keys.update({"contains_period"})
    if kind in {"LOCATION", "ORG"}:
        required_keys.add("contains_comma")
    if kind in {"PRODUCT", "PROJECT_NAME"}:
        required_keys.add("case_style")
    return all(original.get(key) == counterfactual.get(key) for key in required_keys)


@dataclass(frozen=True)
class SemanticPrediction:
    model_id: str
    role: str
    label: str
    text: str
    start: int
    end: int
    score: float

    @property
    def span(self) -> tuple[int, int]:
        return self.start, self.end


class SemanticPredictionCache:
    """Hash-bound SQLite cache for immutable local model predictions."""

    def __init__(
        self,
        path: str | Path,
        identity: Mapping[str, Any],
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = {
            str(key): value for key, value in sorted(identity.items())
        }
        self.identity_sha256 = _mapping_sha256(self.identity)
        try:
            self.connection = sqlite3.connect(str(self.path))
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            quick_check = self.connection.execute(
                "PRAGMA quick_check"
            ).fetchone()
            if quick_check is None or str(quick_check[0]).casefold() != "ok":
                raise SemanticResolverProtocolError(
                    "semantic_prediction_cache_corrupt",
                    f"quick_check failed: {self.path}: {quick_check!r}",
                )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_identity (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    identity_sha256 TEXT NOT NULL,
                    identity_json TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    cache_key TEXT PRIMARY KEY,
                    backend_id TEXT NOT NULL,
                    backend_role TEXT NOT NULL,
                    schema_sha256 TEXT NOT NULL,
                    text_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            row = self.connection.execute(
                """
                SELECT identity_sha256, identity_json
                FROM cache_identity
                WHERE singleton = 1
                """
            ).fetchone()
            identity_json = json.dumps(
                self.identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if row is None:
                existing_predictions = self.connection.execute(
                    "SELECT COUNT(*) FROM predictions"
                ).fetchone()
                if existing_predictions and int(existing_predictions[0]) != 0:
                    raise SemanticResolverProtocolError(
                        "semantic_prediction_cache_corrupt",
                        f"missing identity: {self.path}",
                    )
                self.connection.execute(
                    """
                    INSERT INTO cache_identity(
                        singleton, identity_sha256, identity_json
                    ) VALUES (1, ?, ?)
                    """,
                    (self.identity_sha256, identity_json),
                )
                self.connection.commit()
            elif (
                str(row[0]) != self.identity_sha256
                or str(row[1]) != identity_json
            ):
                raise SemanticResolverProtocolError(
                    "semantic_prediction_cache_identity_mismatch",
                    (
                        f"path={self.path} expected={self.identity_sha256} "
                        f"actual={row[0]}"
                    ),
                )
        except SemanticResolverProtocolError:
            if hasattr(self, "connection"):
                self.connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if hasattr(self, "connection"):
                self.connection.close()
            raise SemanticResolverProtocolError(
                "semantic_prediction_cache_corrupt",
                f"{self.path}: {type(exc).__name__}: {exc}",
            ) from exc
        self.hits = 0
        self.misses = 0
        self.writes = 0

    def _key(
        self,
        backend: SemanticPredictionBackend,
        text: str,
        schema: Mapping[str, str],
    ) -> tuple[str, str, str]:
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        schema_sha256 = _mapping_sha256(schema)
        cache_key = hashlib.sha256(
            "\0".join(
                (
                    self.identity_sha256,
                    str(backend.model_id),
                    str(backend.role),
                    schema_sha256,
                    text_sha256,
                )
            ).encode("utf-8")
        ).hexdigest()
        return cache_key, text_sha256, schema_sha256

    def get(
        self,
        backend: SemanticPredictionBackend,
        text: str,
        schema: Mapping[str, str],
    ) -> list[SemanticPrediction] | None:
        cache_key, text_sha256, schema_sha256 = self._key(
            backend,
            text,
            schema,
        )
        try:
            row = self.connection.execute(
                """
                SELECT backend_id, backend_role, schema_sha256,
                       text_sha256, payload_json
                FROM predictions
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise SemanticResolverProtocolError(
                "semantic_prediction_cache_corrupt",
                f"{self.path}: {type(exc).__name__}: {exc}",
            ) from exc
        if row is None:
            self.misses += 1
            return None
        if (
            str(row[0]) != str(backend.model_id)
            or str(row[1]) != str(backend.role)
            or str(row[2]) != schema_sha256
            or str(row[3]) != text_sha256
        ):
            raise SemanticResolverProtocolError(
                "semantic_prediction_cache_identity_mismatch",
                f"row identity drift: {cache_key}",
            )
        try:
            payload = json.loads(str(row[4]))
            if not isinstance(payload, list):
                raise TypeError("prediction payload must be a list")
            predictions = [
                SemanticPrediction(
                    model_id=str(item["model_id"]),
                    role=str(item["role"]),
                    label=str(item["label"]),
                    text=str(item["text"]),
                    start=int(item["start"]),
                    end=int(item["end"]),
                    score=float(item["score"]),
                )
                for item in payload
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SemanticResolverProtocolError(
                "semantic_prediction_cache_corrupt",
                f"{cache_key}: {type(exc).__name__}: {exc}",
            ) from exc
        for prediction in predictions:
            if (
                prediction.model_id != str(backend.model_id)
                or prediction.role != str(backend.role)
                or not (0 <= prediction.start < prediction.end <= len(text))
                or text[prediction.start : prediction.end]
                != prediction.text
                or not math.isfinite(prediction.score)
            ):
                raise SemanticResolverProtocolError(
                    "semantic_prediction_cache_corrupt",
                    f"invalid cached prediction: {cache_key}",
                )
        self.hits += 1
        return predictions

    def put(
        self,
        backend: SemanticPredictionBackend,
        text: str,
        schema: Mapping[str, str],
        predictions: Sequence[SemanticPrediction],
    ) -> None:
        cache_key, text_sha256, schema_sha256 = self._key(
            backend,
            text,
            schema,
        )
        payload_json = json.dumps(
            [asdict(prediction) for prediction in predictions],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            self.connection.execute(
                """
                INSERT INTO predictions(
                    cache_key, backend_id, backend_role, schema_sha256,
                    text_sha256, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    str(backend.model_id),
                    str(backend.role),
                    schema_sha256,
                    text_sha256,
                    payload_json,
                ),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise SemanticResolverProtocolError(
                "semantic_prediction_cache_identity_mismatch",
                f"duplicate immutable cache key: {cache_key}",
            ) from exc
        except sqlite3.DatabaseError as exc:
            raise SemanticResolverProtocolError(
                "semantic_prediction_cache_write_failed",
                f"{self.path}: {type(exc).__name__}: {exc}",
            ) from exc
        self.writes += 1

    def stats(self) -> dict[str, Any]:
        return {
            "path": str(self.path.resolve()),
            "identity_sha256": self.identity_sha256,
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
        }

    def close(self, *, remove: bool = False) -> None:
        self.connection.close()
        if remove:
            for suffix in ("", "-wal", "-shm"):
                Path(f"{self.path}{suffix}").unlink(missing_ok=True)


@dataclass(frozen=True)
class SemanticResolution:
    accepted: bool
    entity_type: str
    text: str
    start: int
    end: int
    subtype: str
    format_signature: dict[str, Any]
    failure_reasons: tuple[str, ...]
    target_votes: int
    boundary_votes: int
    mean_target_confidence: float
    competing_confidence: float
    confidence_margin: float
    supporting_models: tuple[str, ...]
    competing_labels: tuple[str, ...]
    protocol: str = SEMANTIC_RESOLVER_PROTOCOL
    schema_sha256: str = SEMANTIC_SCHEMA_SHA256
    entity_policy_version: str = ENTITY_TYPE_POLICY_VERSION
    entity_policy_sha256: str = ENTITY_TYPE_POLICY_SHA256

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticPredictionBackend(Protocol):
    """Small adapter interface, allowing deterministic fake models in tests."""

    model_id: str
    role: str

    def predict(
        self,
        text: str,
        schema: Mapping[str, str],
    ) -> Sequence[SemanticPrediction]:
        ...


@dataclass(frozen=True)
class SemanticResolverMetadata:
    enabled: bool
    protocol: str
    schema_sha256: str
    models: tuple[dict[str, Any], ...]
    min_target_confidence: float
    min_confidence_margin: float
    min_consensus_votes: int
    min_boundary_votes: int
    biomedical_veto_threshold: float
    runtime_device: str = "cpu"
    spacy_device: str = "cpu"
    biomedical_device: str = "cpu"
    use_fp16: bool = False
    batch_size: int = 1
    execution_mode: str = PRECISION_CASCADE_MODE
    primary_model_role: str = "gliner2_large"
    biomedical_candidate_only: bool = True
    skipped_model_roles: tuple[str, ...] = ()
    thresholds_sha256: str = ""
    thresholds_by_entity_type: dict[str, dict[str, float]] = field(
        default_factory=dict
    )
    entity_policy_version: str = ENTITY_TYPE_POLICY_VERSION
    entity_policy_sha256: str = ENTITY_TYPE_POLICY_SHA256

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GLiNER2Backend:
    """Normalize the official GLiNER2 local inference interface."""

    def __init__(self, model: Any, model_id: str, role: str) -> None:
        self.model = model
        self.model_id = model_id
        self.role = role

    def predict(
        self,
        text: str,
        schema: Mapping[str, str],
    ) -> Sequence[SemanticPrediction]:
        try:
            raw = self.model.extract_entities(
                text,
                dict(schema),
                include_confidence=True,
                include_spans=True,
            )
        except Exception as exc:  # pragma: no cover - external model runtime
            raise SemanticResolverProtocolError(
                "semantic_model_inference_failed",
                f"{self.model_id}: {type(exc).__name__}: {exc}",
            ) from exc
        return _normalise_mapping_predictions(text, raw, self.model_id, self.role)

    def predict_batch(
        self,
        texts: Sequence[str],
        schema: Mapping[str, str],
        *,
        batch_size: int,
    ) -> list[list[SemanticPrediction]]:
        try:
            raw_batch = self.model.batch_extract_entities(
                list(texts),
                dict(schema),
                batch_size=batch_size,
                include_confidence=True,
                include_spans=True,
            )
        except Exception as exc:  # pragma: no cover - external model runtime
            raise SemanticResolverProtocolError(
                "semantic_model_inference_failed",
                f"{self.model_id}: {type(exc).__name__}: {exc}",
            ) from exc
        if len(raw_batch) != len(texts):
            raise SemanticResolverProtocolError(
                "semantic_model_batch_size_mismatch",
                f"{self.model_id}: expected={len(texts)} actual={len(raw_batch)}",
            )
        return [
            list(_normalise_mapping_predictions(text, raw, self.model_id, self.role))
            for text, raw in zip(texts, raw_batch, strict=True)
        ]


class SpacySemanticBackend:
    """Normalize a pinned spaCy transformer pipeline as an independent vote."""

    def __init__(self, model: Any, model_id: str, role: str) -> None:
        self.model = model
        self.model_id = model_id
        self.role = role

    def predict(
        self,
        text: str,
        schema: Mapping[str, str],
    ) -> Sequence[SemanticPrediction]:
        try:
            document = self.model(text)
        except Exception as exc:  # pragma: no cover - external model runtime
            raise SemanticResolverProtocolError(
                "semantic_model_inference_failed",
                f"{self.model_id}: {type(exc).__name__}: {exc}",
            ) from exc
        predictions: list[SemanticPrediction] = []
        for entity in getattr(document, "ents", ()):
            label = _normalise_label(getattr(entity, "label_", ""))
            if label not in schema:
                continue
            predictions.append(
                SemanticPrediction(
                    model_id=self.model_id,
                    role=self.role,
                    label=label,
                    text=str(entity.text),
                    start=int(entity.start_char),
                    end=int(entity.end_char),
                    score=float(getattr(entity, "score", 1.0)),
                )
            )
        return predictions

    def predict_batch(
        self,
        texts: Sequence[str],
        schema: Mapping[str, str],
        *,
        batch_size: int,
    ) -> list[list[SemanticPrediction]]:
        try:
            documents = self.model.pipe(list(texts), batch_size=batch_size)
        except Exception as exc:  # pragma: no cover - external model runtime
            raise SemanticResolverProtocolError(
                "semantic_model_inference_failed",
                f"{self.model_id}: {type(exc).__name__}: {exc}",
            ) from exc
        outputs: list[list[SemanticPrediction]] = []
        for document in documents:
            predictions: list[SemanticPrediction] = []
            for entity in getattr(document, "ents", ()):
                label = _normalise_label(getattr(entity, "label_", ""))
                if label not in schema:
                    continue
                predictions.append(
                    SemanticPrediction(
                        model_id=self.model_id,
                        role=self.role,
                        label=label,
                        text=str(entity.text),
                        start=int(entity.start_char),
                        end=int(entity.end_char),
                        score=float(getattr(entity, "score", 1.0)),
                    )
                )
            outputs.append(predictions)
        return outputs


class GLiNERBiomedicalBackend:
    """Normalize the local GLiNER-BioMed veto model."""

    def __init__(self, model: Any, model_id: str, role: str) -> None:
        self.model = model
        self.model_id = model_id
        self.role = role

    def predict(
        self,
        text: str,
        schema: Mapping[str, str],
    ) -> Sequence[SemanticPrediction]:
        try:
            raw = self.model.predict_entities(
                text,
                list(schema),
                threshold=0.0,
            )
        except Exception as exc:  # pragma: no cover - external model runtime
            raise SemanticResolverProtocolError(
                "semantic_model_inference_failed",
                f"{self.model_id}: {type(exc).__name__}: {exc}",
            ) from exc
        predictions: list[SemanticPrediction] = []
        for item in raw if isinstance(raw, list) else ():
            if not isinstance(item, Mapping):
                continue
            start = int(item.get("start", -1))
            end = int(item.get("end", -1))
            if not (0 <= start < end <= len(text)):
                continue
            label = _normalise_label(str(item.get("label") or item.get("entity") or ""))
            if label not in schema:
                continue
            predictions.append(
                SemanticPrediction(
                    model_id=self.model_id,
                    role=self.role,
                    label=label,
                    text=text[start:end],
                    start=start,
                    end=end,
                    score=float(item.get("score") or item.get("confidence") or 0.0),
                )
            )
        return predictions

    def predict_batch(
        self,
        texts: Sequence[str],
        schema: Mapping[str, str],
        *,
        batch_size: int,
    ) -> list[list[SemanticPrediction]]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                raw_batch = self.model.batch_predict_entities(
                    list(texts),
                    list(schema),
                    threshold=0.0,
                    batch_size=batch_size,
                )
        except Exception as exc:  # pragma: no cover - external model runtime
            raise SemanticResolverProtocolError(
                "semantic_model_inference_failed",
                f"{self.model_id}: {type(exc).__name__}: {exc}",
            ) from exc
        outputs: list[list[SemanticPrediction]] = []
        for raw in raw_batch:
            predictions: list[SemanticPrediction] = []
            for item in raw if isinstance(raw, list) else ():
                if not isinstance(item, Mapping):
                    continue
                start = int(item.get("start", -1))
                end = int(item.get("end", -1))
                label = _normalise_label(str(item.get("label") or ""))
                if label not in schema or not (0 <= start < end):
                    continue
                predictions.append(
                    SemanticPrediction(
                        model_id=self.model_id,
                        role=self.role,
                        label=label,
                        text=str(item.get("text") or ""),
                        start=start,
                        end=end,
                        score=float(item.get("score", 0.0)),
                    )
                )
            outputs.append(predictions)
        if len(outputs) != len(texts):
            raise SemanticResolverProtocolError(
                "semantic_model_batch_size_mismatch",
                f"{self.model_id}: expected={len(texts)} actual={len(outputs)}",
            )
        return outputs


def _normalise_mapping_predictions(
    text: str,
    raw: Any,
    model_id: str,
    role: str,
) -> list[SemanticPrediction]:
    entities = raw.get("entities", raw) if isinstance(raw, Mapping) else {}
    if not isinstance(entities, Mapping):
        return []
    predictions: list[SemanticPrediction] = []
    for raw_label, raw_items in entities.items():
        label = _normalise_label(str(raw_label))
        items: Sequence[Any]
        if isinstance(raw_items, (str, Mapping)):
            items = [raw_items]
        elif isinstance(raw_items, Sequence):
            items = raw_items
        else:
            continue
        for item in items:
            if isinstance(item, str):
                start = text.find(item)
                end = start + len(item)
                score = 0.0
            elif isinstance(item, Mapping):
                value = str(item.get("text") or item.get("value") or "")
                start = int(item.get("start", text.find(value)))
                end = int(item.get("end", start + len(value)))
                score = float(item.get("confidence") or item.get("score") or 0.0)
            else:
                continue
            if not (0 <= start < end <= len(text)):
                continue
            predictions.append(
                SemanticPrediction(
                    model_id=model_id,
                    role=role,
                    label=label,
                    text=text[start:end],
                    start=start,
                    end=end,
                    score=score,
                )
            )
    return predictions


class SemanticEntityResolver:
    """Resolve semantic candidates with either cascade or audit semantics."""

    def __init__(
        self,
        voters: Sequence[SemanticPredictionBackend],
        *,
        biomedical_veto: SemanticPredictionBackend | None = None,
        min_target_confidence: float = 0.70,
        min_confidence_margin: float = 0.15,
        thresholds_by_entity_type: Mapping[str, Mapping[str, Any]] | None = None,
        min_consensus_votes: int = 1,
        min_boundary_votes: int = 1,
        biomedical_veto_threshold: float = 0.70,
        overlap_threshold: float = 0.80,
        execution_mode: str = PRECISION_CASCADE_MODE,
        protocol: str = SEMANTIC_RESOLVER_PROTOCOL,
        primary_model_role: str = "gliner2_large",
        biomedical_window_chars: int = 512,
        batch_size: int = 1,
    ) -> None:
        if len({backend.model_id for backend in voters}) != len(voters):
            raise ValueError("Semantic voter model_id values must be unique")
        if not voters:
            raise ValueError("Semantic resolver requires at least one voter")
        if execution_mode not in {PRECISION_CASCADE_MODE, AUDIT_CONSENSUS_MODE}:
            raise ValueError(f"Unsupported semantic execution mode: {execution_mode}")
        if protocol not in SUPPORTED_SEMANTIC_PROTOCOLS:
            raise ValueError(f"Unsupported semantic protocol: {protocol}")
        if execution_mode == PRECISION_CASCADE_MODE:
            if min_consensus_votes < 1 or min_boundary_votes < 1:
                raise ValueError("Precision cascade vote thresholds must be positive")
            primary = [
                backend for backend in voters
                if str(getattr(backend, "role", "")) == primary_model_role
            ]
            if len(voters) == 1 and not primary:
                primary = list(voters)
            if len(primary) != 1:
                raise ValueError(
                    "Precision cascade requires exactly one primary semantic backend"
                )
            self._primary_voters = tuple(primary)
        else:
            if min_consensus_votes < 2 or min_boundary_votes < 2:
                raise ValueError("Audit consensus requires at least two votes")
            self._primary_voters = tuple(voters)
        if biomedical_window_chars < 64:
            raise ValueError("biomedical_window_chars must be at least 64")
        if batch_size < 1:
            raise ValueError("semantic batch_size must be positive")
        self.voters = tuple(voters)
        self.biomedical_veto = biomedical_veto
        self.min_target_confidence = float(min_target_confidence)
        self.min_confidence_margin = float(min_confidence_margin)
        self.thresholds_by_entity_type = _canonical_thresholds_by_entity_type(
            thresholds_by_entity_type
        )
        self.min_consensus_votes = int(min_consensus_votes)
        self.min_boundary_votes = int(min_boundary_votes)
        self.biomedical_veto_threshold = float(biomedical_veto_threshold)
        self.overlap_threshold = float(overlap_threshold)
        self.execution_mode = execution_mode
        self.protocol = protocol
        self.primary_model_role = primary_model_role
        self.biomedical_window_chars = int(biomedical_window_chars)
        self.batch_size = int(batch_size)
        self._prediction_cache: SemanticPredictionCache | None = None
        self._prediction_cache_identity: dict[str, Any] = {}
        self._prediction_trace_contexts: dict[str, dict[str, Any]] = {}
        self._oom_retry_count = 0
        self._successful_batch_sizes: dict[int, int] = {}

    def configure_prediction_cache(
        self,
        path: str | Path,
        *,
        identity: Mapping[str, Any],
    ) -> None:
        """为当前 wave 绑定缓存；跨 wave 或 identity 漂移一律拒绝复用。"""

        if self._prediction_cache is not None:
            self._prediction_cache.close()
        self._prediction_cache = None
        prediction_cache = SemanticPredictionCache(path, identity)
        self._prediction_cache = prediction_cache
        self._prediction_cache_identity = dict(identity)
        self._oom_retry_count = 0
        self._successful_batch_sizes = {}

    def prediction_runtime_stats(self) -> dict[str, Any]:
        cache_stats = (
            self._prediction_cache.stats()
            if self._prediction_cache is not None
            else {
                "path": None,
                "identity_sha256": None,
                "hits": 0,
                "misses": 0,
                "writes": 0,
            }
        )
        return {
            "requested_batch_size": self.batch_size,
            "oom_retry_count": self._oom_retry_count,
            "successful_batch_sizes": {
                str(size): count
                for size, count in sorted(
                    self._successful_batch_sizes.items(),
                    reverse=True,
                )
            },
            "prediction_cache": cache_stats,
        }

    def close_prediction_cache(self, *, remove: bool = False) -> None:
        if self._prediction_cache is None:
            return
        cache = self._prediction_cache
        self._prediction_cache = None
        cache.close(remove=remove)
        self._prediction_cache_identity = {}

    def _oom_failure_detail(
        self,
        backend: SemanticPredictionBackend,
        text: str,
    ) -> str:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        context = self._prediction_trace_contexts.get(text_hash, {})
        fields = {
            "dataset": (
                context.get("dataset")
                or self._prediction_cache_identity.get("dataset")
                or ""
            ),
            "wave": self._prediction_cache_identity.get("wave_index", ""),
            "source": context.get("source_key") or "",
            "model": backend.model_id,
            "role": backend.role,
            "text_sha256": text_hash,
        }
        return " ".join(f"{key}={value}" for key, value in fields.items())

    def _predict_backend(
        self,
        backend: SemanticPredictionBackend,
        text: str,
        schema: Mapping[str, str],
    ) -> list[SemanticPrediction]:
        cached = (
            self._prediction_cache.get(backend, text, schema)
            if self._prediction_cache is not None
            else None
        )
        if cached is not None:
            return cached
        try:
            predictions = list(backend.predict(text, schema))
        except Exception as exc:
            if _is_cuda_out_of_memory(exc):
                _release_cuda_cache()
                raise SemanticResolverProtocolError(
                    "semantic_cuda_oom_batch_one",
                    self._oom_failure_detail(backend, text),
                ) from exc
            raise
        self._successful_batch_sizes[1] = (
            self._successful_batch_sizes.get(1, 0) + 1
        )
        if self._prediction_cache is not None:
            self._prediction_cache.put(
                backend,
                text,
                schema,
                predictions,
            )
        return predictions

    def _predict_backend_microbatch(
        self,
        backend: SemanticPredictionBackend,
        texts: Sequence[str],
        schema: Mapping[str, str],
    ) -> list[list[SemanticPrediction]]:
        if not texts:
            return []
        effective_batch_size = len(texts)
        batch_predict = getattr(backend, "predict_batch", None)
        if not callable(batch_predict):
            return [
                self._predict_backend(backend, text, schema)
                for text in texts
            ]
        try:
            outputs = [
                list(predictions)
                for predictions in batch_predict(
                    list(texts),
                    schema,
                    batch_size=effective_batch_size,
                )
            ]
        except Exception as exc:
            if not _is_cuda_out_of_memory(exc):
                raise
            self._oom_retry_count += 1
            _release_cuda_cache()
            if len(texts) == 1:
                raise SemanticResolverProtocolError(
                    "semantic_cuda_oom_batch_one",
                    self._oom_failure_detail(backend, texts[0]),
                ) from exc
            midpoint = len(texts) // 2
            return [
                *self._predict_backend_microbatch(
                    backend,
                    texts[:midpoint],
                    schema,
                ),
                *self._predict_backend_microbatch(
                    backend,
                    texts[midpoint:],
                    schema,
                ),
            ]
        if len(outputs) != len(texts):
            raise SemanticResolverProtocolError(
                "semantic_model_batch_size_mismatch",
                (
                    f"{backend.model_id}: expected={len(texts)} "
                    f"actual={len(outputs)}"
                ),
            )
        self._successful_batch_sizes[effective_batch_size] = (
            self._successful_batch_sizes.get(effective_batch_size, 0) + 1
        )
        if self._prediction_cache is not None:
            for text, predictions in zip(texts, outputs, strict=True):
                self._prediction_cache.put(
                    backend,
                    text,
                    schema,
                    predictions,
                )
        return outputs

    def _predict_backend_uncached_batch(
        self,
        backend: SemanticPredictionBackend,
        texts: Sequence[str],
        schema: Mapping[str, str],
        *,
        batch_size: int,
    ) -> list[list[SemanticPrediction]]:
        """逐 microbatch 提交成功结果，使 OOM 后只补算缺失文本。"""

        if batch_size < 1:
            raise ValueError("semantic batch_size must be positive")
        outputs: list[list[SemanticPrediction]] = []
        text_list = list(texts)
        for start in range(0, len(text_list), batch_size):
            outputs.extend(
                self._predict_backend_microbatch(
                    backend,
                    text_list[start : start + batch_size],
                    schema,
                )
            )
        return outputs

    def _predict_backend_batch(
        self,
        backend: SemanticPredictionBackend,
        texts: Sequence[str],
        schema: Mapping[str, str],
        *,
        batch_size: int,
    ) -> list[list[SemanticPrediction]]:
        text_list = list(texts)
        if self._prediction_cache is None:
            return self._predict_backend_uncached_batch(
                backend,
                text_list,
                schema,
                batch_size=batch_size,
            )
        results: list[list[SemanticPrediction] | None] = [
            None for _ in text_list
        ]
        missing_texts: list[str] = []
        missing_positions: dict[str, list[int]] = {}
        for index, text in enumerate(text_list):
            cached = (
                self._prediction_cache.get(backend, text, schema)
                if self._prediction_cache is not None
                else None
            )
            if cached is not None:
                results[index] = cached
                continue
            if text not in missing_positions:
                missing_positions[text] = []
                missing_texts.append(text)
            missing_positions[text].append(index)
        if missing_texts:
            fresh = self._predict_backend_uncached_batch(
                backend,
                missing_texts,
                schema,
                batch_size=batch_size,
            )
            for text, predictions in zip(
                missing_texts,
                fresh,
                strict=True,
            ):
                for index in missing_positions[text]:
                    results[index] = list(predictions)
        if any(result is None for result in results):
            raise SemanticResolverProtocolError(
                "semantic_model_batch_size_mismatch",
                "prediction reconstruction left an empty slot",
            )
        return [
            list(result)
            for result in results
            if result is not None
        ]

    def _decision_thresholds(self, entity_type: str) -> tuple[float, float]:
        override = self.thresholds_by_entity_type.get(
            _normalise_label(entity_type)
        )
        if override is None:
            return self.min_target_confidence, self.min_confidence_margin
        return (
            float(override["min_target_confidence"]),
            float(override["min_confidence_margin"]),
        )

    def resolve_candidates(
        self,
        text: str,
        candidates: Sequence[Mapping[str, Any]],
        *,
        dataset: str,
    ) -> list[SemanticResolution | None]:
        """Run each local model once and resolve every semantic candidate."""

        voter_predictions, biomedical_predictions = self._predict_all(
            text,
            dataset=dataset,
            candidates=candidates,
        )

        resolutions: list[SemanticResolution | None] = []
        for candidate in candidates:
            entity_type = _normalise_label(str(candidate.get("type") or ""))
            if entity_type not in SEMANTIC_TARGET_TYPES:
                resolutions.append(None)
                continue
            resolutions.append(
                self._resolve_one(
                    text,
                    candidate,
                    voter_predictions,
                    biomedical_predictions,
                )
            )
        return resolutions

    def resolve_and_propose(
        self,
        text: str,
        candidates: Sequence[Mapping[str, Any]],
        *,
        dataset: str,
        precomputed_predictions: tuple[
            Mapping[str, Sequence[SemanticPrediction]],
            Sequence[SemanticPrediction],
        ]
        | None = None,
    ) -> tuple[list[dict[str, Any]], list[SemanticResolution | None]]:
        """Add resolver target spans and resolve all candidates in one pass."""

        if precomputed_predictions is None:
            voter_predictions, biomedical_predictions = self._predict_all(
                text,
                dataset=dataset,
            )
        else:
            voter_predictions, biomedical_predictions = precomputed_predictions
        combined = [dict(candidate) for candidate in candidates]
        existing = {
            (
                _normalise_label(str(candidate.get("type") or "")),
                int(candidate.get("start", -1)),
                int(candidate.get("end", -1)),
            )
            for candidate in combined
        }
        grouped: dict[
            tuple[str, int, int],
            list[SemanticPrediction],
        ] = {}
        for predictions in voter_predictions.values():
            for prediction in predictions:
                if prediction.label not in SEMANTIC_TARGET_TYPES:
                    continue
                target_threshold, _ = self._decision_thresholds(
                    prediction.label
                )
                if prediction.score < target_threshold:
                    continue
                grouped.setdefault(
                    (prediction.label, prediction.start, prediction.end),
                    [],
                ).append(prediction)
        for (label, start, end), predictions in sorted(grouped.items()):
            supporting_models = {
                prediction.model_id for prediction in predictions
            }
            if len(supporting_models) < self.min_consensus_votes:
                continue
            if (label, start, end) in existing:
                continue
            combined.append(
                {
                    "text": text[start:end],
                    "type": label,
                    "start": start,
                    "end": end,
                    "span": [start, end],
                    "semantic_proposal": True,
                    "semantic_proposal_models": sorted(supporting_models),
                    "semantic_proposal_confidence": round(
                        sum(
                            prediction.score
                            for prediction in predictions
                        )
                        / len(predictions),
                        6,
                    ),
                }
            )
            existing.add((label, start, end))

        if (
            self.execution_mode == PRECISION_CASCADE_MODE
            and dataset.casefold() == "pubmed"
        ):
            biomedical_predictions = self._predict_biomedical_for_candidates(
                text,
                combined,
            )

        resolutions: list[SemanticResolution | None] = []
        for candidate in combined:
            entity_type = _normalise_label(str(candidate.get("type") or ""))
            if entity_type not in SEMANTIC_TARGET_TYPES:
                resolutions.append(None)
                continue
            resolutions.append(
                self._resolve_one(
                    text,
                    candidate,
                    voter_predictions,
                    biomedical_predictions,
                )
            )
        return combined, resolutions

    def _predict_all(
        self,
        text: str,
        *,
        dataset: str,
        candidates: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[
        dict[str, list[SemanticPrediction]],
        list[SemanticPrediction],
    ]:
        voter_predictions = {
            backend.model_id: self._predict_backend(
                backend,
                text,
                ALL_SEMANTIC_SCHEMA,
            )
            for backend in (
                self.voters
                if self.execution_mode == AUDIT_CONSENSUS_MODE
                else self._primary_voters
            )
        }
        biomedical_predictions: list[SemanticPrediction] = []
        if dataset.casefold() == "pubmed":
            if self.biomedical_veto is None:
                raise SemanticResolverProtocolError(
                    "semantic_biomedical_veto_missing",
                    "PubMed requires Ihor/gliner-biomed-large-v1.0",
                )
            if self.execution_mode == AUDIT_CONSENSUS_MODE:
                biomedical_predictions = self._predict_backend(
                    self.biomedical_veto,
                    text,
                    BIOMEDICAL_VETO_SCHEMA,
                )
            elif candidates:
                biomedical_predictions = self._predict_biomedical_for_candidates(
                    text,
                    candidates,
                )
        return voter_predictions, biomedical_predictions

    def _supporting_window(
        self,
        text: str,
        start: int,
        end: int,
    ) -> tuple[int, int] | None:
        """定位候选所在的短句窗口，避免 BioMed 扫描完整 chunk。"""

        if not (0 <= start < end <= len(text)):
            return None
        left_markers = [
            text.rfind(marker, 0, start)
            for marker in (".", "!", "?", "\n")
        ]
        left = max(left_markers, default=-1) + 1
        right_candidates = [
            position
            for marker in (".", "!", "?", "\n")
            for position in [text.find(marker, end)]
            if position >= 0
        ]
        right = min(right_candidates, default=len(text) - 1) + 1
        if right - left > self.biomedical_window_chars:
            half = max(1, self.biomedical_window_chars // 2)
            left = max(0, start - half)
            right = min(len(text), max(end, start + half))
            if right - left > self.biomedical_window_chars:
                right = min(len(text), left + self.biomedical_window_chars)
                left = max(0, right - self.biomedical_window_chars)
        return left, right

    def _predict_biomedical_for_candidates(
        self,
        text: str,
        candidates: Sequence[Mapping[str, Any]],
    ) -> list[SemanticPrediction]:
        """仅在候选句窗口内运行 PubMed BioMed 竞争类型否决。"""

        if self.biomedical_veto is None:
            raise SemanticResolverProtocolError(
                "semantic_biomedical_veto_missing",
                "PubMed requires Ihor/gliner-biomed-large-v1.0",
            )
        windows: dict[tuple[int, int], str] = {}
        for candidate in candidates:
            entity_type = _normalise_label(str(candidate.get("type") or ""))
            if entity_type not in SEMANTIC_TARGET_TYPES:
                continue
            span = self._supporting_window(
                text,
                int(candidate.get("start", -1)),
                int(candidate.get("end", -1)),
            )
            if span is not None:
                windows[span] = text[span[0] : span[1]]
        if not windows:
            return []
        ordered_windows = sorted(windows.items())
        window_texts = [item[1] for item in ordered_windows]
        raw_outputs = self._predict_backend_batch(
            self.biomedical_veto,
            window_texts,
            BIOMEDICAL_VETO_SCHEMA,
            batch_size=self.batch_size,
        )
        if len(raw_outputs) != len(ordered_windows):
            raise SemanticResolverProtocolError(
                "semantic_model_batch_size_mismatch",
                (
                    f"{self.biomedical_veto.model_id}: expected={len(ordered_windows)} "
                    f"actual={len(raw_outputs)}"
                ),
            )
        mapped: list[SemanticPrediction] = []
        for (span, _window_text), predictions in zip(
            ordered_windows,
            raw_outputs,
            strict=True,
        ):
            offset = span[0]
            for prediction in predictions:
                start = int(prediction.start) + offset
                end = int(prediction.end) + offset
                if not (0 <= start < end <= len(text)):
                    continue
                mapped.append(
                    SemanticPrediction(
                        model_id=prediction.model_id,
                        role=prediction.role,
                        label=prediction.label,
                        text=text[start:end],
                        start=start,
                        end=end,
                        score=prediction.score,
                    )
                )
        return mapped

    def predict_batch(
        self,
        texts: Sequence[str],
        *,
        dataset: str,
        batch_size: int,
        candidate_spans: Sequence[Mapping[str, Any] | None] | None = None,
        trace_contexts: Sequence[Mapping[str, Any] | None] | None = None,
    ) -> list[
        tuple[
            dict[str, list[SemanticPrediction]],
            list[SemanticPrediction],
        ]
    ]:
        """Run each frozen backend once per text batch without changing decisions."""

        if batch_size < 1:
            raise ValueError("semantic batch_size must be positive")
        text_list = list(texts)
        if candidate_spans is not None and len(candidate_spans) != len(text_list):
            raise SemanticResolverProtocolError(
                "semantic_candidate_batch_size_mismatch",
                f"expected={len(text_list)} actual={len(candidate_spans)}",
            )
        if trace_contexts is not None and len(trace_contexts) != len(text_list):
            raise SemanticResolverProtocolError(
                "semantic_trace_context_batch_size_mismatch",
                f"expected={len(text_list)} actual={len(trace_contexts)}",
            )
        self._prediction_trace_contexts = {}
        if trace_contexts is not None:
            for text, context in zip(
                text_list,
                trace_contexts,
                strict=True,
            ):
                if context is None:
                    continue
                self._prediction_trace_contexts[
                    hashlib.sha256(text.encode("utf-8")).hexdigest()
                ] = dict(context)
        voter_outputs: dict[str, list[list[SemanticPrediction]]] = {}
        active_voters = (
            self.voters
            if self.execution_mode == AUDIT_CONSENSUS_MODE
            else self._primary_voters
        )
        for backend in active_voters:
            outputs = self._predict_backend_batch(
                backend,
                text_list,
                ALL_SEMANTIC_SCHEMA,
                batch_size=batch_size,
            )
            if len(outputs) != len(text_list):
                raise SemanticResolverProtocolError(
                    "semantic_model_batch_size_mismatch",
                    (
                        f"{backend.model_id}: expected={len(text_list)} "
                        f"actual={len(outputs)}"
                    ),
                )
            voter_outputs[backend.model_id] = [
                list(predictions) for predictions in outputs
            ]

        biomedical_outputs: list[list[SemanticPrediction]] = [
            [] for _ in text_list
        ]
        if dataset.casefold() == "pubmed":
            if self.biomedical_veto is None:
                raise SemanticResolverProtocolError(
                    "semantic_biomedical_veto_missing",
                    "PubMed requires Ihor/gliner-biomed-large-v1.0",
                )
            if self.execution_mode == AUDIT_CONSENSUS_MODE:
                biomedical_outputs = self._predict_backend_batch(
                    self.biomedical_veto,
                    text_list,
                    BIOMEDICAL_VETO_SCHEMA,
                    batch_size=batch_size,
                )
            elif candidate_spans is not None:
                biomedical_outputs = [
                    self._predict_biomedical_for_candidates(
                        text,
                        [candidate] if candidate is not None else [],
                    )
                    for text, candidate in zip(
                        text_list,
                        candidate_spans,
                        strict=True,
                    )
                ]
            if len(biomedical_outputs) != len(text_list):
                raise SemanticResolverProtocolError(
                    "semantic_model_batch_size_mismatch",
                    (
                        f"{self.biomedical_veto.model_id}: "
                        f"expected={len(text_list)} "
                        f"actual={len(biomedical_outputs)}"
                    ),
                )

        return [
            (
                {
                    model_id: predictions[index]
                    for model_id, predictions in voter_outputs.items()
                },
                biomedical_outputs[index],
            )
            for index in range(len(text_list))
        ]

    def resolve_candidate(
        self,
        text: str,
        candidate: Mapping[str, Any],
        *,
        dataset: str,
        precomputed_predictions: tuple[
            Mapping[str, Sequence[SemanticPrediction]],
            Sequence[SemanticPrediction],
        ]
        | None = None,
    ) -> SemanticResolution:
        """Resolve one candidate; primarily used for counterfactual replay."""

        if precomputed_predictions is None:
            voter_predictions, biomedical_predictions = self._predict_all(
                text,
                dataset=dataset,
                candidates=[candidate],
            )
        else:
            voter_predictions, biomedical_predictions = precomputed_predictions
            if (
                self.execution_mode == PRECISION_CASCADE_MODE
                and dataset.casefold() == "pubmed"
                and not biomedical_predictions
            ):
                biomedical_predictions = self._predict_biomedical_for_candidates(
                    text,
                    [candidate],
                )
        entity_type = _normalise_label(str(candidate.get("type") or ""))
        if entity_type not in SEMANTIC_TARGET_TYPES:
            raise ValueError("resolve_candidate requires a v6.3 semantic target type")
        result = self._resolve_one(
            text,
            candidate,
            voter_predictions,
            biomedical_predictions,
        )
        if result is None:
            raise ValueError("resolve_candidate requires a v6.3 semantic target type")
        return result

    def _resolve_one(
        self,
        text: str,
        candidate: Mapping[str, Any],
        voter_predictions: Mapping[str, Sequence[SemanticPrediction]],
        biomedical_predictions: Sequence[SemanticPrediction],
    ) -> SemanticResolution:
        requested_type = _normalise_label(str(candidate.get("type") or ""))
        min_target_confidence, min_confidence_margin = (
            self._decision_thresholds(requested_type)
        )
        original_start = int(candidate.get("start", -1))
        original_end = int(candidate.get("end", -1))
        original_span = (original_start, original_end)
        original_text = (
            text[original_start:original_end]
            if 0 <= original_start < original_end <= len(text)
            else str(candidate.get("text") or "")
        )
        reasons: list[str] = []
        if not (0 <= original_start < original_end <= len(text)):
            reasons.append("semantic_candidate_boundary_invalid")

        relevant_by_model: dict[str, list[SemanticPrediction]] = {}
        target_predictions: list[SemanticPrediction] = []
        competing_predictions: list[SemanticPrediction] = []
        for model_id, predictions in voter_predictions.items():
            deduplicated: dict[
                tuple[str, int, int],
                SemanticPrediction,
            ] = {}
            for prediction in predictions:
                key = (prediction.label, prediction.start, prediction.end)
                current = deduplicated.get(key)
                if current is None or prediction.score > current.score:
                    deduplicated[key] = prediction
            relevant = [
                prediction
                for prediction in deduplicated.values()
                if _span_overlap_ratio(original_span, prediction.span)
                >= self.overlap_threshold
            ]
            relevant_by_model[model_id] = relevant
            target_predictions.extend(
                prediction
                for prediction in relevant
                if prediction.label == requested_type
                and prediction.score >= min_target_confidence
            )
            competing_predictions.extend(
                prediction
                for prediction in relevant
                if prediction.label in COMPETING_TYPE_SCHEMA
            )
            competing_predictions.extend(
                prediction
                for prediction in relevant
                if prediction.label in SEMANTIC_TARGET_TYPES
                and prediction.label != requested_type
            )

        span_groups: dict[tuple[int, int], list[SemanticPrediction]] = {}
        for prediction in target_predictions:
            span_groups.setdefault(prediction.span, []).append(prediction)
        ranked_spans = sorted(
            span_groups.items(),
            key=lambda item: (
                -len({prediction.model_id for prediction in item[1]}),
                -sum(prediction.score for prediction in item[1]) / len(item[1]),
                abs(item[0][0] - original_start) + abs(item[0][1] - original_end),
                item[0],
            ),
        )
        if ranked_spans:
            corrected_span, boundary_support = ranked_spans[0]
        else:
            corrected_span, boundary_support = original_span, []
        boundary_models = {prediction.model_id for prediction in boundary_support}
        supporting_models = tuple(sorted(boundary_models))
        target_votes = len(
            {
                prediction.model_id
                for prediction in target_predictions
                if prediction.span == corrected_span
            }
        )
        boundary_votes = len(boundary_models)
        target_scores = [
            prediction.score
            for prediction in target_predictions
            if prediction.span == corrected_span
        ]
        mean_target = (
            sum(target_scores) / len(target_scores)
            if target_scores
            else 0.0
        )
        relevant_competitors = [
            prediction
            for prediction in competing_predictions
            if _span_overlap_ratio(corrected_span, prediction.span)
            >= self.overlap_threshold
        ]
        competitor_score = max(
            (prediction.score for prediction in relevant_competitors),
            default=0.0,
        )
        margin = mean_target - competitor_score

        if target_votes < self.min_consensus_votes:
            reasons.append("semantic_target_consensus_missing")
        if boundary_votes < self.min_boundary_votes:
            reasons.append("semantic_boundary_consensus_missing")
        if mean_target < min_target_confidence:
            reasons.append("semantic_target_confidence_below_threshold")
        if margin < min_confidence_margin:
            reasons.append("semantic_confidence_margin_below_threshold")

        strong_competing_labels = {
            prediction.label
            for prediction in relevant_competitors
            if prediction.score >= min_target_confidence
        }
        if strong_competing_labels:
            reasons.append("semantic_competing_type_detected")

        if biomedical_predictions:
            biomedical_hits = [
                prediction
                for prediction in biomedical_predictions
                if prediction.score >= self.biomedical_veto_threshold
                and _span_overlap_ratio(corrected_span, prediction.span)
                >= self.overlap_threshold
            ]
            if biomedical_hits:
                reasons.append("semantic_pubmed_biomedical_veto")
                strong_competing_labels.update(
                    prediction.label for prediction in biomedical_hits
                )

        corrected_start, corrected_end = corrected_span
        if not (0 <= corrected_start < corrected_end <= len(text)):
            corrected_start, corrected_end = original_span
            corrected_text = original_text
            reasons.append("semantic_corrected_boundary_invalid")
        else:
            corrected_text = text[corrected_start:corrected_end]
        if not corrected_text.strip():
            reasons.append("semantic_corrected_surface_empty")

        unique_reasons = tuple(dict.fromkeys(reasons))
        return SemanticResolution(
            accepted=not unique_reasons,
            entity_type=requested_type,
            text=corrected_text,
            start=corrected_start,
            end=corrected_end,
            subtype=semantic_subtype(corrected_text, requested_type),
            format_signature=semantic_format_signature(
                corrected_text,
                requested_type,
            ),
            failure_reasons=unique_reasons,
            target_votes=target_votes,
            boundary_votes=boundary_votes,
            mean_target_confidence=round(mean_target, 6),
            competing_confidence=round(competitor_score, 6),
            confidence_margin=round(margin, 6),
            supporting_models=supporting_models,
            competing_labels=tuple(sorted(strong_competing_labels)),
            protocol=self.protocol,
        )


def _verify_model_lock(
    model_config: Mapping[str, Any],
    *,
    workspace_root: Path,
) -> tuple[Path, dict[str, Any]]:
    model_id = str(model_config.get("model_id") or "").strip()
    local_path_value = str(model_config.get("local_path") or "").strip()
    if not model_id or not local_path_value:
        raise SemanticResolverProtocolError(
            "semantic_model_lock_incomplete",
            "Every model requires model_id and local_path",
        )
    local_path = Path(local_path_value)
    if not local_path.is_absolute():
        local_path = workspace_root / local_path
    if not local_path.exists():
        raise SemanticResolverProtocolError(
            "semantic_model_missing",
            f"{model_id}: {local_path}",
        )
    expected_hashes = model_config.get("files_sha256")
    if not isinstance(expected_hashes, Mapping) or not expected_hashes:
        raise SemanticResolverProtocolError(
            "semantic_model_hash_lock_missing",
            model_id,
        )
    verified_hashes: dict[str, str] = {}
    for relative_name, expected_hash in sorted(expected_hashes.items()):
        artifact = local_path / str(relative_name)
        if not artifact.is_file():
            raise SemanticResolverProtocolError(
                "semantic_model_file_missing",
                f"{model_id}: {artifact}",
            )
        actual_hash = _sha256_file(artifact)
        if actual_hash.casefold() != str(expected_hash).casefold():
            raise SemanticResolverProtocolError(
                "semantic_model_hash_mismatch",
                f"{model_id}:{relative_name} expected={expected_hash} actual={actual_hash}",
            )
        verified_hashes[str(relative_name)] = actual_hash

    package_name = str(model_config.get("package") or "").strip()
    expected_package_version = str(model_config.get("package_version") or "").strip()
    actual_package_version = ""
    if package_name:
        try:
            actual_package_version = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise SemanticResolverProtocolError(
                "semantic_model_runtime_missing",
                package_name,
            ) from exc
        if expected_package_version and actual_package_version != expected_package_version:
            raise SemanticResolverProtocolError(
                "semantic_model_runtime_version_mismatch",
                (
                    f"{package_name} expected={expected_package_version} "
                    f"actual={actual_package_version}"
                ),
            )
    return local_path, {
        "model_id": model_id,
        "backend": str(model_config.get("backend") or ""),
        "role": str(model_config.get("role") or ""),
        "local_path": str(local_path),
        "revision": str(model_config.get("revision") or ""),
        "package": package_name,
        "package_version": actual_package_version,
        "files_sha256": verified_hashes,
    }


def _load_backend(
    model_config: Mapping[str, Any],
    local_path: Path,
    *,
    runtime_device: str,
    use_fp16: bool,
) -> SemanticPredictionBackend:
    backend = str(model_config.get("backend") or "").strip().casefold()
    model_id = str(model_config["model_id"])
    role = str(model_config.get("role") or "voter")
    if backend == "gliner2":
        try:
            from gliner2 import GLiNER2
        except ImportError as exc:  # pragma: no cover - dependency state
            raise SemanticResolverProtocolError(
                "semantic_model_runtime_missing",
                "gliner2[local]",
            ) from exc
        try:
            # GLiNER2 prints an emoji banner during construction.  Redirect
            # only that banner so Windows GBK consoles do not fail before the
            # model is loaded; exceptions still propagate unchanged.
            with redirect_stdout(io.StringIO()):
                model = GLiNER2.from_pretrained(
                    str(local_path),
                    map_location=runtime_device,
                    quantize=bool(use_fp16),
                )
        except Exception as exc:  # pragma: no cover - external model state
            raise SemanticResolverProtocolError(
                "semantic_model_load_failed",
                f"{model_id}: {type(exc).__name__}: {exc}",
            ) from exc
        return GLiNER2Backend(model, model_id, role)
    if backend == "spacy":
        try:
            import spacy
        except ImportError as exc:  # pragma: no cover - dependency state
            raise SemanticResolverProtocolError(
                "semantic_model_runtime_missing",
                "spacy",
            ) from exc
        try:
            if runtime_device.startswith("cuda"):
                spacy.require_gpu()
            model = spacy.load(local_path)
        except Exception as exc:  # pragma: no cover - external model state
            raise SemanticResolverProtocolError(
                "semantic_model_load_failed",
                f"{model_id}: {type(exc).__name__}: {exc}",
            ) from exc
        return SpacySemanticBackend(model, model_id, role)
    if backend == "gliner_biomed":
        try:
            from gliner import GLiNER
        except ImportError as exc:  # pragma: no cover - dependency state
            raise SemanticResolverProtocolError(
                "semantic_model_runtime_missing",
                "gliner",
            ) from exc
        try:
            model = GLiNER.from_pretrained(
                str(local_path),
                local_files_only=True,
                map_location=runtime_device,
                dtype=("float16" if use_fp16 else None),
            )
        except Exception as exc:  # pragma: no cover - external model state
            raise SemanticResolverProtocolError(
                "semantic_model_load_failed",
                f"{model_id}: {type(exc).__name__}: {exc}",
            ) from exc
        return GLiNERBiomedicalBackend(model, model_id, role)
    raise SemanticResolverProtocolError(
        "semantic_model_backend_unsupported",
        f"{model_id}: {backend}",
    )


def load_semantic_entity_resolver(
    config: Mapping[str, Any] | None,
    *,
    dataset: str,
    workspace_root: str | Path | None = None,
    injected_backends: Mapping[str, SemanticPredictionBackend] | None = None,
) -> tuple[SemanticEntityResolver | None, SemanticResolverMetadata]:
    """Load a local-only resolver and make the bulk/audit role split explicit."""

    cfg = dict(config or {})
    root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    model_lock_path = str(cfg.get("model_lock_path") or "").strip()
    if model_lock_path:
        from ..utils.io import load_yaml

        lock_path = Path(model_lock_path)
        if not lock_path.is_absolute():
            lock_path = root / lock_path
        if not lock_path.is_file():
            raise SemanticResolverProtocolError(
                "semantic_model_lock_missing",
                str(lock_path),
            )
        locked = load_yaml(lock_path)
        cfg = {
            **locked,
            **{
                key: value
                for key, value in cfg.items()
                if key != "model_lock_path"
            },
        }

    enabled = bool(cfg.get("enabled", False))
    protocol = str(cfg.get("protocol") or SEMANTIC_RESOLVER_PROTOCOL)
    if protocol not in SUPPORTED_SEMANTIC_PROTOCOLS:
        raise SemanticResolverProtocolError(
            "semantic_protocol_mismatch",
            f"supported={sorted(SUPPORTED_SEMANTIC_PROTOCOLS)!r} actual={protocol!r}",
        )
    expected_mode = (
        PRECISION_CASCADE_MODE
        if protocol == PRECISION_CASCADE_PROTOCOL
        else AUDIT_CONSENSUS_MODE
    )
    execution_mode = str(cfg.get("execution_mode") or expected_mode)
    if execution_mode != expected_mode:
        raise SemanticResolverProtocolError(
            "semantic_execution_mode_mismatch",
            f"protocol={protocol!r} expected={expected_mode!r} actual={execution_mode!r}",
        )
    primary_model_role = str(
        cfg.get("primary_model_role") or "gliner2_large"
    )
    if (
        execution_mode == PRECISION_CASCADE_MODE
        and primary_model_role != "gliner2_large"
    ):
        raise SemanticResolverProtocolError(
            "semantic_primary_model_role_invalid",
            primary_model_role,
        )
    biomedical_candidate_only = bool(
        cfg.get(
            "biomedical_candidate_only",
            execution_mode == PRECISION_CASCADE_MODE,
        )
    )
    if execution_mode == PRECISION_CASCADE_MODE and not biomedical_candidate_only:
        raise SemanticResolverProtocolError(
            "semantic_biomedical_candidate_only_required",
            "precision cascade requires candidate-only PubMed BioMed veto",
        )

    runtime_device = str(cfg.get("device") or "cpu").strip().casefold()
    spacy_device = str(cfg.get("spacy_device") or "cpu").strip().casefold()
    biomedical_device = str(
        cfg.get("biomedical_device") or runtime_device
    ).strip().casefold()
    use_fp16 = bool(cfg.get("use_fp16", False))
    batch_size = int(cfg.get("batch_size", 1))
    valid_devices = {"cpu", "cuda"}
    for name, value in (
        ("device", runtime_device),
        ("spacy_device", spacy_device),
        ("biomedical_device", biomedical_device),
    ):
        if value not in valid_devices:
            raise SemanticResolverProtocolError(
                "semantic_runtime_device_invalid",
                f"{name}={value!r}",
            )
    if batch_size < 1:
        raise SemanticResolverProtocolError(
            "semantic_batch_size_invalid",
            str(batch_size),
        )
    default_votes = 1 if execution_mode == PRECISION_CASCADE_MODE else 2
    min_consensus_votes = int(
        cfg.get("min_consensus_votes", default_votes)
    )
    min_boundary_votes = int(cfg.get("min_boundary_votes", default_votes))
    min_target_confidence = float(cfg.get("min_target_confidence", 0.70))
    min_confidence_margin = float(cfg.get("min_confidence_margin", 0.15))
    biomedical_veto_threshold = float(
        cfg.get("biomedical_veto_threshold", 0.70)
    )
    overlap_threshold = float(cfg.get("overlap_threshold", 0.80))
    try:
        thresholds_by_entity_type = _canonical_thresholds_by_entity_type(
            cfg.get("thresholds_by_entity_type")
        )
    except (TypeError, ValueError) as exc:
        raise SemanticResolverProtocolError(
            "semantic_entity_type_thresholds_invalid",
            str(exc),
        ) from exc
    thresholds_hash = (
        semantic_thresholds_sha256(
            min_target_confidence=min_target_confidence,
            min_confidence_margin=min_confidence_margin,
            min_consensus_votes=min_consensus_votes,
            min_boundary_votes=min_boundary_votes,
            biomedical_veto_threshold=biomedical_veto_threshold,
            overlap_threshold=overlap_threshold,
            thresholds_by_entity_type=thresholds_by_entity_type,
        )
        if execution_mode == PRECISION_CASCADE_MODE
        else ""
    )

    if not enabled:
        return None, SemanticResolverMetadata(
            enabled=False,
            protocol=protocol,
            schema_sha256=SEMANTIC_SCHEMA_SHA256,
            models=(),
            min_target_confidence=min_target_confidence,
            min_confidence_margin=min_confidence_margin,
            min_consensus_votes=min_consensus_votes,
            min_boundary_votes=min_boundary_votes,
            biomedical_veto_threshold=biomedical_veto_threshold,
            runtime_device=runtime_device,
            spacy_device=spacy_device,
            biomedical_device=biomedical_device,
            use_fp16=use_fp16,
            batch_size=batch_size,
            execution_mode=execution_mode,
            primary_model_role=primary_model_role,
            biomedical_candidate_only=biomedical_candidate_only,
            thresholds_sha256=thresholds_hash,
            thresholds_by_entity_type=thresholds_by_entity_type,
        )

    if not bool(cfg.get("local_files_only", True)):
        raise SemanticResolverProtocolError(
            "semantic_local_only_required",
            "local_files_only must be true",
        )
    expected_schema_hash = str(cfg.get("schema_sha256") or "")
    if expected_schema_hash != SEMANTIC_SCHEMA_SHA256:
        raise SemanticResolverProtocolError(
            "semantic_schema_hash_mismatch",
            f"expected={SEMANTIC_SCHEMA_SHA256} actual={expected_schema_hash}",
        )
    if (
        execution_mode == PRECISION_CASCADE_MODE
        and not bool(cfg.get("calibration_mode", False))
    ):
        if not bool(cfg.get("thresholds_frozen", False)):
            raise SemanticResolverProtocolError(
                "semantic_thresholds_not_frozen",
                "precision cascade requires a passed 206-row calibration",
            )
        try:
            _canonical_thresholds_by_entity_type(
                thresholds_by_entity_type,
                require_complete=True,
            )
        except ValueError as exc:
            raise SemanticResolverProtocolError(
                "semantic_entity_type_thresholds_incomplete",
                str(exc),
            ) from exc
        expected_thresholds_hash = str(cfg.get("thresholds_sha256") or "")
        if expected_thresholds_hash != thresholds_hash:
            raise SemanticResolverProtocolError(
                "semantic_thresholds_hash_mismatch",
                f"expected={expected_thresholds_hash} actual={thresholds_hash}",
            )

    required_roles = (
        {"gliner2_large"}
        if execution_mode == PRECISION_CASCADE_MODE
        else {"gliner2_base", "gliner2_large", "spacy_transformer"}
    )
    if dataset.casefold() == "pubmed":
        required_roles.add("biomedical_veto")
    requested_devices = {runtime_device}
    if execution_mode == AUDIT_CONSENSUS_MODE:
        requested_devices.add(spacy_device)
    if dataset.casefold() == "pubmed":
        requested_devices.add(biomedical_device)
    if "cuda" in requested_devices:
        try:
            import torch
        except ImportError as exc:
            raise SemanticResolverProtocolError(
                "semantic_runtime_device_unavailable",
                "torch is required for CUDA semantic inference",
            ) from exc
        if not torch.cuda.is_available():
            raise SemanticResolverProtocolError(
                "semantic_runtime_device_unavailable",
                "CUDA was requested but torch.cuda.is_available() is false",
            )

    model_configs = cfg.get("models")
    if not isinstance(model_configs, list) or not model_configs:
        raise SemanticResolverProtocolError(
            "semantic_model_lock_incomplete",
            "models must be a non-empty list",
        )
    configured_roles = {
        str(item.get("role") or "")
        for item in model_configs
        if isinstance(item, Mapping)
    }
    missing_locked_roles = required_roles - configured_roles
    if missing_locked_roles:
        if missing_locked_roles == {"biomedical_veto"}:
            raise SemanticResolverProtocolError(
                "semantic_biomedical_veto_missing",
                "PubMed requires role=biomedical_veto",
            )
        raise SemanticResolverProtocolError(
            "semantic_required_model_role_missing",
            ",".join(sorted(missing_locked_roles)),
        )
    skipped_roles = tuple(sorted(configured_roles - required_roles - {""}))

    injected = dict(injected_backends or {})
    voters: list[SemanticPredictionBackend] = []
    biomedical_veto: SemanticPredictionBackend | None = None
    model_metadata: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for raw_model_config in model_configs:
        if not isinstance(raw_model_config, Mapping):
            raise SemanticResolverProtocolError(
                "semantic_model_lock_incomplete",
                "model entry is not a mapping",
            )
        model_config = dict(raw_model_config)
        model_id = str(model_config.get("model_id") or "")
        role = str(model_config.get("role") or "")
        if role not in required_roles:
            continue
        model_device = (
            biomedical_device
            if role == "biomedical_veto"
            else spacy_device
            if role == "spacy_transformer"
            else runtime_device
        )
        if model_id in injected:
            backend = injected[model_id]
            metadata = {
                "model_id": model_id,
                "backend": str(model_config.get("backend") or "injected"),
                "role": role,
                "local_path": "injected-test-backend",
                "revision": str(model_config.get("revision") or "test"),
                "package": "",
                "package_version": "",
                "files_sha256": {"injected": "test-only"},
                "runtime_device": model_device,
                "runtime_precision": "fp16" if use_fp16 else "fp32",
            }
        else:
            local_path, metadata = _verify_model_lock(
                model_config,
                workspace_root=root,
            )
            backend = _load_backend(
                model_config,
                local_path,
                runtime_device=model_device,
                use_fp16=use_fp16,
            )
            metadata = {
                **metadata,
                "runtime_device": model_device,
                "runtime_precision": "fp16" if use_fp16 else "fp32",
            }
        seen_roles.add(role)
        model_metadata.append(metadata)
        if role == "biomedical_veto":
            biomedical_veto = backend
        else:
            voters.append(backend)

    missing_roles = required_roles - seen_roles
    if missing_roles:
        if missing_roles == {"biomedical_veto"}:
            raise SemanticResolverProtocolError(
                "semantic_biomedical_veto_missing",
                "PubMed requires role=biomedical_veto",
            )
        raise SemanticResolverProtocolError(
            "semantic_required_model_role_missing",
            ",".join(sorted(missing_roles)),
        )

    resolver = SemanticEntityResolver(
        voters,
        biomedical_veto=biomedical_veto,
        min_target_confidence=min_target_confidence,
        min_confidence_margin=min_confidence_margin,
        thresholds_by_entity_type=thresholds_by_entity_type,
        min_consensus_votes=min_consensus_votes,
        min_boundary_votes=min_boundary_votes,
        biomedical_veto_threshold=biomedical_veto_threshold,
        overlap_threshold=overlap_threshold,
        execution_mode=execution_mode,
        protocol=protocol,
        primary_model_role=primary_model_role,
        biomedical_window_chars=int(cfg.get("biomedical_window_chars", 512)),
        batch_size=batch_size,
    )
    return resolver, SemanticResolverMetadata(
        enabled=True,
        protocol=protocol,
        schema_sha256=SEMANTIC_SCHEMA_SHA256,
        models=tuple(model_metadata),
        min_target_confidence=resolver.min_target_confidence,
        min_confidence_margin=resolver.min_confidence_margin,
        min_consensus_votes=resolver.min_consensus_votes,
        min_boundary_votes=resolver.min_boundary_votes,
        biomedical_veto_threshold=resolver.biomedical_veto_threshold,
        runtime_device=runtime_device,
        spacy_device=spacy_device,
        biomedical_device=biomedical_device,
        use_fp16=use_fp16,
        batch_size=batch_size,
        execution_mode=execution_mode,
        primary_model_role=primary_model_role,
        biomedical_candidate_only=biomedical_candidate_only,
        skipped_model_roles=skipped_roles,
        thresholds_sha256=thresholds_hash,
        thresholds_by_entity_type=resolver.thresholds_by_entity_type,
    )


SemanticResolverRuntime = tuple[
    SemanticEntityResolver | None,
    SemanticResolverMetadata,
]


def resolve_semantic_runtime(
    config: Mapping[str, Any] | None,
    *,
    dataset: str,
    runtime: SemanticResolverRuntime | None = None,
) -> SemanticResolverRuntime:
    """加载或校验可复用的 resolver runtime，禁止跨协议静默复用。"""

    cfg = dict(config or {})
    if runtime is None:
        return load_semantic_entity_resolver(cfg, dataset=dataset)

    resolver, metadata = runtime
    enabled = bool(cfg.get("enabled", False))
    if metadata.enabled != enabled:
        raise SemanticResolverProtocolError(
            "semantic_runtime_enabled_mismatch",
            f"config={enabled} runtime={metadata.enabled}",
        )
    if not enabled:
        if resolver is not None:
            raise SemanticResolverProtocolError(
                "semantic_runtime_unexpected_resolver",
                "disabled semantic configuration received a live resolver",
            )
        return runtime
    if resolver is None:
        raise SemanticResolverProtocolError(
            "semantic_runtime_resolver_missing",
            "enabled semantic configuration requires a live resolver",
        )

    expected = {
        "protocol": str(cfg.get("protocol") or ""),
        "execution_mode": str(
            cfg.get("execution_mode") or PRECISION_CASCADE_MODE
        ),
        "primary_model_role": str(
            cfg.get("primary_model_role") or "gliner2_large"
        ),
        "thresholds_sha256": str(cfg.get("thresholds_sha256") or ""),
        "batch_size": max(1, int(cfg.get("batch_size", 8))),
    }
    actual = {
        "protocol": metadata.protocol,
        "execution_mode": metadata.execution_mode,
        "primary_model_role": metadata.primary_model_role,
        "thresholds_sha256": metadata.thresholds_sha256,
        "batch_size": metadata.batch_size,
    }
    if actual != expected or metadata.schema_sha256 != SEMANTIC_SCHEMA_SHA256:
        raise SemanticResolverProtocolError(
            "semantic_runtime_identity_mismatch",
            f"expected={expected!r} actual={actual!r}",
        )

    roles = {
        str(model.get("role") or "")
        for model in metadata.models
        if isinstance(model, Mapping)
    }
    expected_roles = {"gliner2_large"}
    if dataset.casefold() == "pubmed":
        expected_roles.add("biomedical_veto")
    if roles != expected_roles:
        raise SemanticResolverProtocolError(
            "semantic_runtime_model_roles_mismatch",
            f"dataset={dataset} expected={sorted(expected_roles)!r} "
            f"actual={sorted(roles)!r}",
        )
    return runtime
