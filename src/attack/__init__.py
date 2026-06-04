"""Entity extraction and perturbation helpers used by PCV-MIA.

中文说明：本文件是 src/attack 包的入口说明(__init__.py)。
attack 包提供两块攻击核心能力：
    - entity_extractor.py：从文本里抽取"关键实体"(金额、日期、人名、机构等)，并评估
      哪些实体最适合用来做攻击。
    - perturbation_generator.py：把一个真实实体替换成"同类型但不同"的假值，用于构造
      反事实声明(Q-)。
这两块是 PCV-MIA"成对声明"构造的基础。
"""
