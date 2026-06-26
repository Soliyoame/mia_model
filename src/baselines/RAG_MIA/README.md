# RAG-MIA — Direct Query(地板线)

- 论文:arXiv:2405.20446(IBM,Is My Data in Your Retrieval Database?)
- 源码:无官方,攻击=一句「直接询问」prompt,据论文重写。
- 代码:`rag_mia_reference.py`(RAGMIA + RAGMIAPrompt;详见文件头 docstring)
- 纯黑盒 ✓。应替换 runner.py 里用 cvg_rag 当代理的「Direct RAG-MIA」占位。
- 接入与注意事项见 `../BASELINES.md`。
