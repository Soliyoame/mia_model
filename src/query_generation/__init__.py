"""PCV-MIA paired-query generation and filtering.

中文说明：本文件是 src/query_generation 包的入口说明(__init__.py)。
query_generation 包负责流水线第 08、09 两步：
    - paired_query_builder(第08步)：把"成对声明"包装成自然的"验证查询"(真正去问模型的话)。
    - stealth_filter(第09步)：过滤掉那些"太露骨、一看就像攻击/在套取知识库内容"的查询，
      保证攻击足够隐蔽(stealth)。
"""
