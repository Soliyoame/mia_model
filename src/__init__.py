"""PCV-MIA 实现包(顶层包)。

中文说明
========
本包是整个 PCV-MIA(成员推理攻击)项目的代码根目录,按职责拆成若干子包:
data(数据预处理)、prepare(切分与基准构建)、rag(检索增强生成)、llm(大模型客户端)、
attack/spoof/paired_claims/query_generation(攻击样本与查询构造)、parsing/scoring(响应解析与打分)、
evaluation/baselines/defenses(评测、对照方法与防御)、utils(通用工具)。
scripts/ 下的编号脚本按 01~15 顺序调用这些子包,串成完整流水线。
"""
