# Notes: PCV-MIA v20 正式实验前整改

## Current Facts

- Llama 正式 API 调用数为 0，本轮也禁止 API 调用。
- 每数据集为 500 KB Member、500 True Non-member、250 Reserve、7,500 queries。
- 每数据集 Reserve 已冻结为 5 个 `pilot_diagnostic` 和 245 个
  `conformal_calibration`。
- 三数据集 release-controls 已生成：
  - 近重复跨组 overlap=0；
  - ground-truth source store 覆盖三个 group；
  - execution schedule 精确覆盖 90,000 个主请求。
- Edgar 重分组改变 2 个 source；Enron 改变 14 个 source；PubMed 未改组。
- 原产物备份位于 `legacy/pre_response_regroup_20260731/`。
- Edgar、Enron 的 formal dense/BM25 index 已根据新 KB split 重建。
- Edgar、Enron 三种 Reserve dev chunk 配置的 dense/BM25 index 已重建。
- `mia_model` 环境为 PyTorch `2.11.0+cu130`，CUDA 可用，设备为 RTX 4060 Laptop。
- 三数据集 Retriever 门禁 9/9 候选完成，`tokens-128-overlap-32` 通过并被选中：
  - macro Recall@5 = 0.8487；
  - Edgar Recall@5/10 = 0.7733/0.8393，zero-hit source rate = 0.004；
  - Enron Recall@5/10 = 0.8653/0.8947，zero-hit source rate = 0；
  - PubMed Recall@5/10 = 0.9073/0.9253，zero-hit source rate = 0。
- 三数据集各 1,000 个 Member/Non-member representative chunks 已生成并冻结 manifest。

## Implemented Controls

- 统计：
  - source-level conformal，最小 p-value 为 1/246；
  - alpha 仅 1%/5%，bootstrap 2,000、seed 42；
  - 唯一 primary endpoint 为三数据集等权 macro source AUC。
- Oracle/Random：
  - Oracle 使用只读 ground-truth store；
  - Random 约束 chunk 数与 token 差，排除 target、exact、MinHash 和 BGE 近重复。
- Baseline：
  - DCMI/IA/MBA/RAG_MIA/S2MIA；
  - BGE-only；
  - 共享 representative chunk 和固定 victim-call budget。
- Defense：
  - `answer_without_correction`；
  - `target_entity_redaction`；
  - 输出 raw/conformal privacy 与限定 utility。
- Execution：
  - source-block interleaved；
  - 绑定 schedule ordinal/query identity；
  - response/model/fingerprint drift fail closed。

## Final Validation

- `python -B -m unittest discover -s tests`: 306/306 passed。
- Python AST: 255 files passed；YAML: 17 files parsed。
- dense/BM25/hybrid canonical dry-run passed；非 dense 默认不误跑 BGE-only
  baseline/mechanism/defense steps。
- `scripts/26_validate_v20_preflight.py`: passed；22,500 formal queries、
  90,000 scheduled requests、2,700 planned Pilot calls、formal/API calls=0。
- `git diff --check`: passed（仅 Windows LF→CRLF warning）。
- 研究总表已更新，详细记录写入 `研究记录/思路v22.txt`。

## Next External Step

- 在 clean release commit 与冻结 Llama endpoint 上运行 2,700-call Pilot。
- 三数据集 Pilot gate 全部通过前不得启动 90,000-call formal matrix。
