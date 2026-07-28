"""LLM client factory for PCV-MIA.

Scripts read one logical profile from ``configs/llm_profiles.yaml`` and allow
the concrete API key, base URL, and model name to be switched from ``.env``.

中文说明
========
本文件是"LLM 客户端工厂"：根据配置和环境变量，创建出 victim/sibling 两类模型的
客户端对象。设计思路是把"逻辑配置"和"具体凭据"分开：
    - configs/llm_profiles.yaml 里写各种"profile(配置档)"——给模型起个名字、设好
      接口/系统提示词等。
    - .env 里放真正的 API key、base_url、model 名，可随时切换，不进代码仓库。
优先级(谁说了算)：命令行参数 > .env > 脚本配置 > yaml 里的 active 默认档。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .sibling_client import OpenAICompatibleSiblingClient, SiblingClient
from .victim_client import OpenAICompatibleVictimClient, VictimClient
from ..utils.env import env_str
from ..utils.io import load_yaml, resolve_path


# 默认的 profile 配置文件路径。
DEFAULT_PROFILE_PATH = "configs/llm_profiles.yaml"
# 每个角色对应的"选用哪个 profile"的环境变量名。
ENV_PROFILE_VARS = {
    "sibling": "PCV_SIBLING_PROFILE",
    "victim": "PCV_VICTIM_PROFILE",
}
# 每个角色的"具体凭据"可由哪些环境变量覆盖(密钥变量名/接口地址/模型名)。
ROLE_ENV_VARS = {
    "sibling": {
        "api_key": ("PCV_SIBLING_API_KEY",),
        "base_url": ("PCV_SIBLING_BASE_URL",),
        "model": ("PCV_SIBLING_MODEL",),
        "model_version": ("PCV_SIBLING_MODEL_VERSION",),
    },
    "victim": {
        "api_key": ("PCV_VICTIM_API_KEY",),
        "base_url": ("PCV_VICTIM_BASE_URL",),
        "model": ("PCV_VICTIM_MODEL",),
        "model_version": ("PCV_VICTIM_MODEL_VERSION",),
    },
}


def load_llm_profiles(pipeline_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read LLM profile config.

    中文说明：读取 LLM profile 配置文件。文件不存在时返回一个空结构(而不是报错)，
    便于在没有配置时也能优雅降级。

    参数:
        pipeline_config: 流水线配置，可在其中用 llm_profiles_path 指定配置文件位置。
    返回:
        解析后的 profile 配置字典。
    """
    config = pipeline_config or {}
    # 取配置里的路径(没有就用默认)，并解析成绝对路径。
    profile_path = resolve_path(config.get("llm_profiles_path", DEFAULT_PROFILE_PATH))
    # 文件不存在就返回空骨架结构。
    if not profile_path.exists():
        return {"active": {}, "sibling": {"profiles": {}}, "victim": {"profiles": {}}}
    return load_yaml(profile_path)


def resolve_llm_profile_name(
    role: str,
    *,
    cli_profile: str | None = None,
    config_profile: str | None = None,
    env_path: str | Path | None = None,
) -> str | None:
    """Resolve an LLM profile name with precedence: CLI > .env > script config > active YAML.

    中文说明：决定最终用哪个 profile 名字。按优先级依次看：命令行 > .env 环境变量 >
    脚本配置；都没有则返回 None(交由后续用 yaml 里的 active 默认值)。

    参数:
        role:           角色，"sibling" 或 "victim"。
        cli_profile:    命令行传入的 profile 名。
        config_profile: 脚本配置里的 profile 名。
        env_path:       .env 文件路径(可选)。
    返回:
        选定的 profile 名字；都没指定则为 None。
    异常:
        ValueError: role 不被支持时抛出。
    """
    if role not in ENV_PROFILE_VARS:
        raise ValueError(f"Unsupported LLM role: {role}")
    # 从环境变量读取该角色选定的 profile 名。
    env_profile = env_str(ENV_PROFILE_VARS[role], path=env_path)
    # 按优先级顺序取第一个非空的候选。
    for candidate in (cli_profile, env_profile, config_profile):
        if candidate is None:
            continue
        name = str(candidate).strip()
        if name:
            return name
    return None


def _get_profile(
    profiles_config: dict[str, Any],
    role: str,
    override_name: str | None,
    fallback: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """从配置里取出指定角色、指定名字的 profile(配置档)。

    参数:
        profiles_config: load_llm_profiles 读出的整体配置。
        role:            "sibling" 或 "victim"。
        override_name:   想用的 profile 名;为空则用 yaml 里 active 指定的。
        fallback:        当没有任何已命名 profile 可用时的兜底内联配置。
    返回:
        (profile 名字, profile 配置字典)。
    异常:
        KeyError: 指定了未知名字、或既无可选 profile 也无 fallback 时抛出。
    """
    active = profiles_config.get("active", {})
    role_block = profiles_config.get(role, {})
    # 取该角色下所有已定义的 profiles。
    profiles = role_block.get("profiles", {}) if isinstance(role_block, dict) else {}
    # 优先用调用方指定的名字，否则用 active 里该角色的默认名。
    name = override_name or active.get(role)
    if name:
        # 指定的名字必须真实存在，否则报错并列出可选项。
        if name not in profiles:
            available = ", ".join(sorted(profiles)) or "<none>"
            raise KeyError(f"Unknown {role} LLM profile '{name}'. Available: {available}")
        profile = dict(profiles[name])
        profile["profile_name"] = name
        return name, profile
    # 没有命名 profile 时，若给了 fallback 就用它(标记为 inline)。
    if fallback:
        profile = dict(fallback)
        profile["profile_name"] = "inline"
        return "inline", profile
    raise KeyError(f"No {role} LLM profile selected. Set PCV_{role.upper()}_PROFILE in .env or active.{role} in configs/llm_profiles.yaml.")


def _first_nonempty(*values: str | None) -> str:
    """返回参数里第一个"非空且去空格后不为空"的字符串;都为空则返回 ""。"""
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _first_env_value(names: list[str]) -> tuple[str | None, str | None]:
    """按顺序在环境变量里找第一个有值的变量。

    参数:
        names: 候选的环境变量名列表。
    返回:
        (命中的变量名, 它的值);都没值则返回 (None, None)。
    """
    for name in names:
        value = env_str(name)
        if value:
            return name, value
    return None, None


def _apply_role_env_overrides(role: str, profile: dict[str, Any]) -> dict[str, Any]:
    """Apply .env overrides for API key env var, base URL, and model name.

    中文说明：用 .env 里的环境变量覆盖 profile 中的 base_url / model / api_key_env。
    这样无需改 yaml，仅改 .env 就能切换实际使用的接口与模型。

    参数:
        role:    "sibling" 或 "victim"。
        profile: 待覆盖的 profile 配置。
    返回:
        覆盖后的新 profile(原 profile 不被修改)。
    异常:
        ValueError: role 不被支持时抛出。
    """
    if role not in ROLE_ENV_VARS:
        raise ValueError(f"Unsupported LLM role: {role}")
    # 复制一份再改，避免污染传入的原始配置。
    updated = dict(profile)
    role_env = ROLE_ENV_VARS[role]

    # base_url：先看 profile 里自定义的变量名,再看该角色的标准变量名,取第一个有值的。
    base_url_names = [_first_nonempty(updated.get("base_url_env")), *role_env["base_url"]]
    _, base_url = _first_env_value([name for name in base_url_names if name])
    if base_url:
        updated["base_url"] = base_url

    # model：同理。
    model_names = [_first_nonempty(updated.get("model_env")), *role_env["model"]]
    _, model = _first_env_value([name for name in model_names if name])
    if model:
        updated["model"] = model

    # Version is provenance-only: it identifies the concrete served snapshot
    # without changing the model argument sent to an OpenAI-compatible API.
    model_version_names = [
        _first_nonempty(updated.get("model_version_env")),
        *role_env["model_version"],
    ]
    _, model_version = _first_env_value([name for name in model_version_names if name])
    if model_version:
        updated["model_version"] = model_version

    # api_key：注意这里存的是"变量名"而不是 key 本身;选出实际有值的那个变量名。
    api_key_env_names = [_first_nonempty(updated.get("api_key_env")), *role_env["api_key"]]
    selected_api_key_env, _ = _first_env_value([name for name in api_key_env_names if name])
    # 没有任何变量有值时,退而记录第一个候选变量名(供底层报"未设置该变量")。
    updated["api_key_env"] = selected_api_key_env or _first_nonempty(*api_key_env_names)
    return updated


def resolve_effective_llm_profile(
    profiles_config: dict[str, Any],
    role: str,
    *,
    profile_name: str | None = None,
) -> dict[str, Any]:
    """Resolve one profile plus environment overrides without constructing an API client."""

    _, profile = _get_profile(profiles_config, role, profile_name, None)
    return _apply_role_env_overrides(role, profile)


def _profile_extra_body(profile: dict[str, Any]) -> dict[str, Any]:
    """取出 profile 里的 extra_body(额外请求参数);为空返回空字典,类型不对则报错。"""
    extra_body = profile.get("extra_body", {})
    if extra_body is None:
        return {}
    if not isinstance(extra_body, dict):
        raise ValueError("LLM profile extra_body must be a mapping.")
    return dict(extra_body)


def build_sibling_client(
    profiles_config: dict[str, Any],
    *,
    profile_name: str | None = None,
    fallback_seed: int = 42,
) -> tuple[SiblingClient, dict[str, Any]]:
    """Create the Sibling client and return the resolved profile.

    中文说明：根据配置创建兄弟模型客户端。流程：取 profile → 用 .env 覆盖 →
    按 provider 类型实例化对应客户端。

    参数:
        profiles_config: 整体 profile 配置。
        profile_name:    想用的 profile 名(可选)。
        fallback_seed:   兼容保留的参数(此处未直接使用)。
    返回:
        (sibling 客户端对象, 最终生效的 profile 字典)。
    异常:
        ValueError: provider 不被支持时抛出。
    """
    # 取 sibling 的 profile(无 fallback)，再叠加 .env 覆盖。
    _, profile = _get_profile(profiles_config, "sibling", profile_name, None)
    profile = _apply_role_env_overrides("sibling", profile)
    provider = str(profile.get("provider", "")).lower()
    # 目前只支持 openai_compatible 这一种 provider。
    if provider == "openai_compatible":
        return OpenAICompatibleSiblingClient(
            base_url=str(profile.get("base_url", "")),
            model=str(profile.get("model", "")),
            api_key_env=str(profile.get("api_key_env", "")),
            system_prompt=str(profile.get("system_prompt", "")),
            timeout=float(profile.get("timeout", 60.0)),
            max_tokens=int(profile.get("max_tokens", 1024)),
            stream=bool(profile.get("stream", False)),
            extra_body=_profile_extra_body(profile),
        ), profile
    raise ValueError(f"Unsupported sibling provider: {provider}")


def build_victim_client(
    profiles_config: dict[str, Any],
    *,
    profile_name: str | None = None,
    fallback_config: dict[str, Any] | None = None,
) -> tuple[VictimClient, dict[str, Any]]:
    """Create the Victim client and return the resolved profile.

    中文说明：根据配置创建受害者模型客户端，流程与 build_sibling_client 类似。

    参数:
        profiles_config: 整体 profile 配置。
        profile_name:    想用的 profile 名(可选)。
        fallback_config: 没有命名 profile 时的兜底内联配置。
    返回:
        (victim 客户端对象, 最终生效的 profile 字典)。
    异常:
        ValueError: provider 不被支持时抛出。
    """
    _, profile = _get_profile(profiles_config, "victim", profile_name, fallback_config)
    profile = _apply_role_env_overrides("victim", profile)
    provider = str(profile.get("provider", "")).lower()
    if provider == "openai_compatible":
        return OpenAICompatibleVictimClient(
            base_url=str(profile.get("base_url", "")),
            model=str(profile.get("model", "")),
            api_key_env=str(profile.get("api_key_env", "")),
            system_prompt=str(profile.get("system_prompt", "")),
            timeout=float(profile.get("timeout", 60.0)),
            stream=bool(profile.get("stream", False)),
            extra_body=_profile_extra_body(profile),
        ), profile
    raise ValueError(f"Unsupported victim provider: {provider}")


def profile_config_path(pipeline_config: dict[str, Any] | None = None) -> Path:
    """Return the configured LLM profile file path.

    参数:
        pipeline_config: 流水线配置(可含 llm_profiles_path)。
    返回:
        profile 配置文件的绝对路径。
    """
    config = pipeline_config or {}
    return resolve_path(config.get("llm_profiles_path", DEFAULT_PROFILE_PATH))
