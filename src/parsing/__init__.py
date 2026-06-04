"""Response stance parsing for PCV-MIA.

中文说明：本文件是 src/parsing 包的入口说明(__init__.py)。
parsing 包负责把大模型"自由文字回答"解析成结构化的"立场(stance)"标记
(支持/反对/接受伪造/纠正/不知道/拒绝等)，是打分前的必要预处理。
核心实现见 stance_parser.py。
"""
