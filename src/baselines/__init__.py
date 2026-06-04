"""Baseline interfaces for PCV-MIA.

中文说明：本文件是 src/baselines 包的入口说明(__init__.py)。
baselines 包负责"对照实验"：把本项目方法(PCV-MIA)和其它已有攻击方法放在同样的
数据与指标下比较。能直接由现有中间结果算出的就实现，需要额外 LLM 调用的先预留
接口(占位)。核心实现见 runner.py。
"""
