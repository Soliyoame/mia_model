"""随机种子工具。

中文说明
========
本文件集中管理随机性,保证实验可复现。数据集切分、spoof(非成员伪造)生成等步骤
都依赖随机数,这里统一设置 Python ``random``、``PYTHONHASHSEED`` 与 NumPy 的种子,
并支持直接从实验配置里解析种子值(兼容顶层 ``seed`` 和 ``split.seed`` 两种写法)。
"""

from __future__ import annotations

import os
import random


def set_seed(seed: int) -> None:
    """设置可复现实验所需的随机种子。

    参数:
        seed: 随机种子整数;会同时作用于 random、PYTHONHASHSEED 与 NumPy。
    """
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        # 环境未装 NumPy 时跳过,不影响纯 Python 随机性的设置。
        pass


def seed_from_config(config: dict, default: int = 42) -> int:
    """从实验配置解析随机种子，兼容顶层 ``seed`` 与 ``split.seed`` 两种写法。

    参数:
        config:  实验配置字典。
        default: 配置中找不到种子时返回的默认值。
    返回:
        解析得到的种子整数。
    """
    if isinstance(config, dict):
        # 优先取顶层 seed;否则退而取 split 子配置里的 seed。
        if "seed" in config:
            return int(config["seed"])
        split = config.get("split")
        if isinstance(split, dict) and "seed" in split:
            return int(split["seed"])
    return default


def set_seed_from_config(config: dict, default: int = 42) -> int:
    """根据配置统一设定随机种子，返回实际使用的种子值。

    参数:
        config:  实验配置字典。
        default: 配置中无种子时使用的默认值。
    返回:
        本次实际设定的种子值。
    """
    seed = seed_from_config(config, default)
    set_seed(seed)
    return seed
