# S²MIA — Semantic Similarity MIA

- 论文:arXiv:2406.19234(ICASSP'25,Generating/Seeing Is Believing)
- 源码:无官方 → 抽取自 MIRABEL(https://github.com/nonalcohol-park/MIRABEL)
- 代码:`s2mia_reference.py`(自包含 S2 + S2Prompt;详见文件头 docstring)
- ⚠ 威胁模型:本实现是 (s&p),困惑度需本地 GPT-2 = 非纯黑盒。
  纯黑盒主表只用 **(s) 相似度版**,(s&p) 单列。
- 接入与注意事项见 `../BASELINES.md`。
