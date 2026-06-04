"""Paired true/counterfactual claim generation for PCV-MIA.

中文说明：本文件是 src/paired_claims 包的入口说明(__init__.py)。
paired_claims 包对应流水线第 07 步：把每条事实改写成一对声明——真实声明(与原文一致)
和反事实声明(把关键实体换成假值)。这一对声明是 PCV 攻击的"探针"。核心实现见
claim_generator.py。
"""
