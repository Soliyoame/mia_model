"""PCV-MIA scoring.

中文说明：本文件是 src/scoring 包的入口说明(__init__.py)。
scoring 包负责把"立场标记"换算成成员推理分数：先算每对声明的 CVG(反事实
验证差距)，再算 CG-CVG = CVG_RAG - CVG_LLM，最后聚合成文档级的 cg_cvg、
pcv_score 和 pcv_score_primary。其中 pcv_score 是当前主分，按 fact quality_weight
对 pair-level CG-CVG 加权。核心实现见 pcv_scorer.py。
"""
