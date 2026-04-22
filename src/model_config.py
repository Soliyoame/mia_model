"""Local model configuration helpers for experiment switching."""

import json
import os


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "model_config.json")

_DEFAULT_MODEL_CONFIG = {
    "victim_model_name": "models/qwen",
    "reference_model_name": "models/qwen",
}


def load_local_model_config():
    if not os.path.isfile(_MODEL_CONFIG_PATH):
        return {}
    try:
        with open(_MODEL_CONFIG_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"[ModelConfig] 读取本地配置失败，忽略 {_MODEL_CONFIG_PATH}: {exc}")
        return {}
    if not isinstance(payload, dict):
        print(f"[ModelConfig] 本地配置格式无效，忽略 {_MODEL_CONFIG_PATH}")
        return {}
    return payload


def get_model_config_defaults():
    config = dict(_DEFAULT_MODEL_CONFIG)
    config.update(load_local_model_config())
    return config

