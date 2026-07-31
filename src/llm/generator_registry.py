"""Generator 家族冻结与正式实验身份校验。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..utils.hash import sha256_obj
from ..utils.io import ensure_dir, load_yaml, read_json, resolve_path, write_json


GENERATOR_FAMILIES = ("gemini", "qwen", "gpt", "llama")
FROZEN_REQUIRED_FIELDS = (
    "provider",
    "endpoint_id",
    "concrete_model",
    "model_version",
    "model_snapshot",
    "context_length",
    "temperature_supported",
    "selection_reason",
)


@dataclass(frozen=True)
class GeneratorIdentity:
    """一次 suite 不可变的 Generator 身份。"""

    generator_family: str
    concrete_model: str
    generator_version: str
    model_snapshot: str
    provider: str
    endpoint_id: str
    context_length: int
    temperature_supported: bool
    role: str
    registry_version: str
    registry_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_generator_registry(
    path: str | Path = "configs/generator_families.yaml",
) -> dict[str, Any]:
    """读取并验证 Generator 家族注册表的基本结构。"""

    registry_path = resolve_path(path)
    if not registry_path.is_file():
        raise FileNotFoundError(f"Generator registry not found: {registry_path}")
    registry = load_yaml(registry_path)
    families = registry.get("generator_families")
    if not isinstance(families, dict):
        raise ValueError("generator_families must be a mapping")
    unknown = sorted(set(families) - set(GENERATOR_FAMILIES))
    missing = sorted(set(GENERATOR_FAMILIES) - set(families))
    if unknown or missing:
        raise ValueError(
            f"Generator registry families mismatch: missing={missing}, unknown={unknown}"
        )
    return registry


def infer_generator_family(concrete_model: str) -> str | None:
    """仅根据模型命名推断家族；正式运行仍以冻结 registry 为准。"""

    normalized = str(concrete_model or "").casefold()
    aliases = {
        "gemini": ("gemini",),
        "qwen": ("qwen",),
        "gpt": ("gpt", "o1", "o3", "o4"),
        "llama": ("llama",),
    }
    matches = [
        family
        for family, tokens in aliases.items()
        if any(token in normalized for token in tokens)
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_frozen_generator(
    registry: dict[str, Any],
    *,
    family: str,
    concrete_model: str,
    provider: str,
    generator_version: str | None = None,
    allow_pilot_candidate: bool = False,
) -> GeneratorIdentity:
    """校验正式调用使用的模型与冻结家族完全一致。

    pending 家族、模糊版本、跨家族模型或环境变量偷换型号都会在 API 调用前失败。
    """

    family_name = str(family or "").strip().casefold()
    if family_name not in GENERATOR_FAMILIES:
        raise ValueError(f"Unknown generator family: {family!r}")
    entry = (registry.get("generator_families") or {}).get(family_name) or {}
    status = str(entry.get("status") or "").casefold()
    allowed_statuses = (
        {"frozen", "pilot_candidate"}
        if allow_pilot_candidate
        else {"frozen"}
    )
    if status not in allowed_statuses:
        raise RuntimeError(
            f"Generator family '{family_name}' has status {status or 'missing'}; "
            "register a pilot_candidate for an isolated pilot or freeze it before formal calls."
        )
    missing = [
        field
        for field in FROZEN_REQUIRED_FIELDS
        if entry.get(field) is None or str(entry.get(field)).strip() == ""
    ]
    if missing:
        raise RuntimeError(
            f"Frozen generator family '{family_name}' is missing fields: {missing}"
        )
    requested_model = str(concrete_model or "").strip()
    frozen_model = str(entry["concrete_model"]).strip()
    if requested_model != frozen_model:
        raise RuntimeError(
            f"Generator drift for {family_name}: registry={frozen_model!r}, "
            f"effective_profile={requested_model!r}. Create a new suite after updating the registry."
        )
    inferred = infer_generator_family(requested_model)
    if inferred != family_name:
        raise RuntimeError(
            f"Concrete model {requested_model!r} does not belong to family {family_name!r}."
        )
    frozen_provider = str(entry["provider"]).strip().casefold()
    if str(provider or "").strip().casefold() != frozen_provider:
        raise RuntimeError(
            f"Provider drift for {family_name}: registry={frozen_provider!r}, "
            f"effective_profile={provider!r}."
        )
    explicit_version = str(generator_version or entry["model_version"]).strip()
    if explicit_version != str(entry["model_version"]).strip():
        raise RuntimeError(
            f"Generator version drift for {family_name}: registry={entry['model_version']!r}, "
            f"effective_profile={explicit_version!r}."
        )
    return GeneratorIdentity(
        generator_family=family_name,
        concrete_model=frozen_model,
        generator_version=explicit_version,
        model_snapshot=str(entry["model_snapshot"]).strip(),
        provider=frozen_provider,
        endpoint_id=str(entry["endpoint_id"]).strip(),
        context_length=int(entry["context_length"]),
        temperature_supported=bool(entry["temperature_supported"]),
        role=str(entry.get("role") or "extension"),
        registry_version=str(registry.get("registry_version") or ""),
        registry_hash=sha256_obj(registry),
    )


def load_and_resolve_frozen_generator(
    *,
    family: str,
    concrete_model: str,
    provider: str,
    generator_version: str | None = None,
    path: str | Path = "configs/generator_families.yaml",
    allow_pilot_candidate: bool = False,
) -> GeneratorIdentity:
    """便捷入口：加载 registry 后解析一个冻结身份。"""

    return resolve_frozen_generator(
        load_generator_registry(path),
        family=family,
        concrete_model=concrete_model,
        provider=provider,
        generator_version=generator_version,
        allow_pilot_candidate=allow_pilot_candidate,
    )


def resolve_generator_from_pipeline_config(
    config: dict[str, Any],
    *,
    family: str | None = None,
    profile_name: str | None = None,
) -> tuple[GeneratorIdentity, dict[str, Any]]:
    """不创建 API client，解析当前 pipeline 配置对应的冻结 Generator。"""

    from .factory import (
        load_llm_profiles,
        resolve_effective_llm_profile,
        resolve_llm_profile_name,
    )

    profiles = load_llm_profiles(config)
    generation = config.get("generation") or {}
    selected_profile = resolve_llm_profile_name(
        "victim",
        cli_profile=profile_name,
        config_profile=generation.get("victim_profile"),
    )
    effective = resolve_effective_llm_profile(
        profiles,
        "victim",
        profile_name=selected_profile,
    )
    identity = load_and_resolve_frozen_generator(
        family=family or str(config.get("generator_family") or ""),
        concrete_model=str(effective.get("model") or ""),
        provider=str(effective.get("provider") or ""),
        generator_version=effective.get("model_version"),
        path=str(
            config.get(
                "generator_registry_path",
                "configs/generator_families.yaml",
            )
        ),
    )
    return identity, effective


def record_first_formal_call(
    identity: GeneratorIdentity,
    *,
    called_at: str,
    state_root: str | Path,
) -> Path:
    """在 artifact registry state 中一次性记录家族首次正式成功调用时间。"""

    if not str(called_at or "").strip():
        raise ValueError("called_at is required")
    state_path = (
        ensure_dir(
            resolve_path(state_root)
            / identity.generator_family
            / identity.concrete_model.replace("/", "--")
        )
        / "freeze_state.json"
    )
    frozen = identity.to_dict()
    if state_path.is_file():
        existing = read_json(state_path)
        existing_identity = existing.get("generator_identity") or {}
        if existing_identity != frozen:
            raise RuntimeError(
                f"Generator freeze state drift: {state_path}. "
                "Create a new concrete-model suite instead of overwriting it."
            )
        return state_path
    write_json(
        {
            "status": "frozen",
            "generator_identity": frozen,
            "first_formal_call_at": str(called_at),
        },
        state_path,
    )
    return state_path
