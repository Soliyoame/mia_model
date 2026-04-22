"""Write local LLM API configuration for this project.

Usage examples:
  python scripts/set_llm_config.py --api-key sk-xxx --base-url https://api.deepseek.com/v1 --model deepseek-chat
  python scripts/set_llm_config.py --show
  python scripts/set_llm_config.py --clear
"""

import argparse
import json
import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "llm_api.json")


def mask_secret(value):
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


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


def print_config(config):
    print(f"配置文件: {CONFIG_PATH}")
    print(f"api_key:  {mask_secret(config.get('api_key', ''))}")
    print(f"base_url: {config.get('base_url', '')}")
    print(f"model:    {config.get('model', '')}")


def main():
    parser = argparse.ArgumentParser(description="设置项目本地 LLM API 配置")
    parser.add_argument("--api-key", type=str, help="LLM API key")
    parser.add_argument("--base-url", type=str, help="LLM API base URL")
    parser.add_argument("--model", type=str, help="LLM model name")
    parser.add_argument("--show", action="store_true", help="显示当前配置")
    parser.add_argument("--clear", action="store_true", help="清空本地配置文件")
    args = parser.parse_args()

    if args.clear:
        if os.path.isfile(CONFIG_PATH):
            os.remove(CONFIG_PATH)
            print(f"已删除配置文件: {CONFIG_PATH}")
        else:
            print(f"配置文件不存在: {CONFIG_PATH}")
        return

    current = load_config()
    if args.show and not any([args.api_key, args.base_url, args.model]):
        print_config(current)
        return

    if not any([args.api_key, args.base_url, args.model]):
        parser.error("请至少提供一个更新项，或使用 --show / --clear")

    updated = dict(current)
    if args.api_key is not None:
        updated["api_key"] = args.api_key
    if args.base_url is not None:
        updated["base_url"] = args.base_url
    if args.model is not None:
        updated["model"] = args.model

    save_config(updated)
    print("本地 LLM 配置已更新。")
    print_config(updated)


if __name__ == "__main__":
    main()
