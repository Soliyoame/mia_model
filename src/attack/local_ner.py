"""本地命名实体模型加载与版本冻结。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LocalNerMetadata:
    enabled: bool
    backend: str | None
    model: str | None
    model_version: str | None
    runtime_version: str | None
    local_files_only: bool
    pipeline: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_local_ner_model(config: dict[str, Any] | None) -> tuple[Any | None, LocalNerMetadata]:
    """按正式配置加载本地 NER；启用时不允许静默降级。"""

    cfg = dict(config or {})
    enabled = bool(cfg.get("enabled", False))
    local_files_only = bool(cfg.get("local_files_only", True))
    if not enabled:
        return None, LocalNerMetadata(
            enabled=False,
            backend=None,
            model=None,
            model_version=None,
            runtime_version=None,
            local_files_only=local_files_only,
            pipeline=(),
        )
    if not local_files_only:
        raise ValueError("Canonical NER must set local_files_only=true")

    backend = str(cfg.get("backend") or "").strip().casefold()
    if backend != "spacy":
        raise ValueError(f"Unsupported local NER backend: {backend!r}")
    model_name = str(cfg.get("model") or "").strip()
    if not model_name:
        raise ValueError("Enabled local NER requires a model name")

    try:
        import spacy
    except ImportError as exc:  # pragma: no cover - dependency failure
        raise RuntimeError("spaCy is required by the canonical local NER protocol") from exc

    try:
        model = spacy.load(model_name)
    except Exception as exc:  # pragma: no cover - external package state
        raise RuntimeError(
            f"Failed to load required local NER model {model_name!r}; "
            "the canonical pipeline will not fall back to regex-only extraction"
        ) from exc

    model_version = str(model.meta.get("version") or "")
    expected_version = str(cfg.get("model_version") or "").strip()
    if expected_version and model_version != expected_version:
        raise RuntimeError(
            f"Local NER model version mismatch for {model_name!r}: "
            f"expected {expected_version!r}, got {model_version!r}"
        )
    runtime_version = str(spacy.__version__)
    expected_runtime = str(cfg.get("runtime_version") or "").strip()
    if expected_runtime and runtime_version != expected_runtime:
        raise RuntimeError(
            f"spaCy runtime version mismatch: expected {expected_runtime!r}, "
            f"got {runtime_version!r}"
        )

    metadata = LocalNerMetadata(
        enabled=True,
        backend="spacy",
        model=model_name,
        model_version=model_version,
        runtime_version=runtime_version,
        local_files_only=True,
        pipeline=tuple(model.pipe_names),
    )
    return model, metadata
