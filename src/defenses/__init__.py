"""Defense experiment interfaces for PCV-MIA.

中文说明：本文件是 src/defenses 包的入口说明(__init__.py)。
defenses 包负责"防御实验"：评估在 RAG 系统里加入各种隐私保护策略后，本攻击的
效果会下降多少(以及对正常问答能力的影响)。当前提供可运行的评估骨架与预留的策略
接口，真实策略需接到生成阶段再重跑。核心实现见 runner.py。
"""
