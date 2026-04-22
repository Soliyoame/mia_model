"""Write local default model settings for experiments.

Usage examples:
  python scripts/set_model_config.py --victim-model models/qwen --reference-model models/qwen
  python scripts/set_model_config.py --show
  python scripts/set_model_config.py --clear
"""

import argparse
import json
import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "model_config.json")
DEFAULTS = {
    "victim_model_name": "models/qwen",
    "reference_model_name": "models/qwen",
}


def load_config():
    if not os.path.isfile(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def show_config(config):
    effective = dict(DEFAULTS)
    effective.update(config)
    print(f"配置文件: {CONFIG_PATH}")
    print(f"victim_model_name:    {effective['victim_model_name']}")
    print(f"reference_model_name: {effective['reference_model_name']}")


def main():
    parser = argparse.ArgumentParser(description="设置项目默认 victim/reference 模型")
    parser.add_argument("--victim-model", type=str, help="Default victim model name or local path")
    parser.add_argument("--reference-model", type=str, help="Default reference model name or local path")
    parser.add_argument("--show", action="store_true", help="显示当前模型配置")
    parser.add_argument("--clear", action="store_true", help="清空本地模型配置文件")
    args = parser.parse_args()

    if args.clear:
        if os.path.isfile(CONFIG_PATH):
            os.remove(CONFIG_PATH)
            print(f"已删除配置文件: {CONFIG_PATH}")
        else:
            print(f"配置文件不存在: {CONFIG_PATH}")
        return

    current = load_config()
    if args.show and not any([args.victim_model, args.reference_model]):
        show_config(current)
        return

    if not any([args.victim_model, args.reference_model]):
        parser.error("请至少提供一个更新项，或使用 --show / --clear")

    updated = dict(current)
    if args.victim_model is not None:
        updated["victim_model_name"] = args.victim_model
    if args.reference_model is not None:
        updated["reference_model_name"] = args.reference_model

    save_config(updated)
    print("本地模型默认配置已更新。")
    show_config(updated)


if __name__ == "__main__":
    main()
