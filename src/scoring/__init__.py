"""PCV-MIA scoring.

中文说明：本文件是 src/scoring 包的入口说明(__init__.py)。
scoring 包负责把"立场标记"换算成"成员可能性分数"：先算每对声明的 CVG(反事实
验证差距)，再算 CG-CVG = CVG_RAG - CVG_LLM 作为最终成员分。核心实现见 pcv_scorer.py。
"""
