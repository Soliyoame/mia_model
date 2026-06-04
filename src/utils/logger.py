"""共享日志工具。

中文说明
========
本文件统一配置全项目的日志:所有日志器都挂在 ``pcv_mia`` 命名空间下,既输出到控制台,
也可选地写入日志文件。各脚本和模块通过 get_logger 取得带统一前缀的日志器,
主入口处调用 setup_logging 完成一次性初始化(避免重复添加 handler)。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOGGER_NAMESPACE = "pcv_mia"


def setup_logging(name: str = LOGGER_NAMESPACE, log_file: str | Path | None = None, level: str = "INFO") -> logging.Logger:
    """初始化控制台日志,并可选地附加文件日志。

    参数:
        name:     日志器名(默认用 PCV-MIA 命名空间)。
        log_file: 日志文件路径;为空则只输出到控制台。
        level:    日志级别字符串(如 "INFO"、"DEBUG")。
    返回:
        配置好的 logging.Logger。
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    # 关闭向上传播,避免日志被根日志器重复打印。
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    # 仅在还没有 handler 时添加控制台输出,防止重复初始化造成重复行。
    if not logger.handlers:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        abs_path = str(path.resolve())
        # 检查是否已挂了写同一文件的 FileHandler,避免重复添加。
        has_same_file = any(
            isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == abs_path
            for handler in logger.handlers
        )
        if not has_same_file:
            file_handler = logging.FileHandler(path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """返回 PCV-MIA 命名空间下的日志器。

    参数:
        name: 子模块名;若本身已在 pcv_mia 命名空间内则原样返回,否则自动加前缀。
    返回:
        对应的 logging.Logger。
    """
    # 已经是命名空间本身或其子级则直接用,否则补上统一前缀。
    if name == LOGGER_NAMESPACE or name.startswith(f"{LOGGER_NAMESPACE}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{name}")
