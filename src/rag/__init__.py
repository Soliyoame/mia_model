"""RAG indexing, retrieval, and dual-mode generation for PCV-MIA.

中文说明：这是 src/rag 包的入口说明文件(__init__.py)。
rag 包负责 PCV-MIA 攻击里与"检索增强生成(RAG)"相关的三件事：
    1. 建索引(index_builder)：只把"成员文档 KB_Member"切块、编码成向量、存成索引库。
    2. 检索(retriever)：给一个查询，找出索引库里最相似的若干文本块。
    3. 双模式生成(runner)：对同一批查询，分别跑"带检索的 RAG"和"不检索的纯 LLM"，
       两者的差异正是判断文档是否在知识库里的关键信号。
embeddings 则提供底层的"文本→向量"能力，被上面几个模块共用。
"""
