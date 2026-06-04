"""评估、机制分析和报告生成模块。

中文说明：本文件是 src/evaluation 包的入口说明(__init__.py)。
evaluation 包对应流水线尾段(11/13/15 步用到)：
    - metrics：计算攻击效果指标(AUC、TPR@FPR、准确率、各分组 FPR 等)。
    - mechanism_analysis(第13步)：机制分析，拆解"攻击为什么有效/失效"。
    - report_builder(第15步)：汇总各阶段产物，生成 JSON + Markdown 最终报告。
"""
