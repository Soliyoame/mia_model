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

---

# Notes: v21 实体类型统一修复

## 已确认根因

- `CONTRACT_TERM` 同时受 semantic resolver 的宽类型定义和 validator 的窄正则约束，导致 semantic 接受后仍被 `original_entity_type_mismatch`/`counterfactual_entity_type_mismatch` 拒绝。
- ORG 的 `_ORG_TECHNICAL_TOKEN_RE` 把任意全大写缩写视为技术 token，导致 BGE、ENA、NNG 等真实机构缩写被二次否决。
- extractor、resolver、perturber、validator 分别维护类型集合、子类型、表面规则和替换池，现有单点测试不能保证端到端类型覆盖。
- 当前 Enron full 前 1,250 source 只有 85 个合格；主要瓶颈在 facts/claims，不是 stealth filter。
- EDGAR/PubMed 总合格率较高，但同样存在 CONTRACT_TERM=0、ORG/PRODUCT 低转换率，因此必须共同回放。

## 当前旧产物下界

- EDGAR：3,500 scanned，2,931 eligible。
- Enron full：1,250 scanned，85 eligible。
- PubMed：1,000 scanned，832 eligible。
- 旧 calibration 正文已删除，只剩 hash/provenance；新审计只能作为独立验证证据，不能伪称恢复了原 calibration。

## 实施边界

- 不删除旧产物，不运行正式 API，不改变 cap=5 和每 source 三 pair 固定预算。
- 不使用数据集专属实体白名单，不根据正式 AUC 调整类型规则。
- 新策略失败时 fail closed；不得通过删类型或静默丢 source 凑数。

## 2026-08-05 实施结果

- 新增唯一策略 `configs/entity_type_policy_v21_r1.yaml`，18 类、6 个 semantic 类型、全部 subtype 替换池统一由 `src/attack/entity_type_policy.py` 加载；policy SHA-256=`e867112519b5ee952b740ba58f3ffec046c5a0a710297dc06d8c677cc670b00e`。
- semantic resolution 通过后，validator 不再重复使用 CONTRACT_TERM 窄正则和 ORG 技术缩写 heuristic；单槽替换、边界、完整性、semantic protocol/schema/type/subtype/format 与策略 hash 仍 fail closed。
- 新 facts/claims/manifests 绑定 policy 版本/hash；旧 facts 只允许在独立 replay suite 中重放，不能 resume 成新正式产物。
- 新增 `scripts/34_validate_v21_entity_policy.py`：inventory、facts/source 双层 replay、三个互斥 500-source pilot cohort、600 条盲审、release gate 和 gate 检查均有机器可读身份。
- 正式 scanner 新协议 `v21_entity_policy_full_rescan_v1` 必须提供通过的 release gate；gate 会复核 inventory、所有 wave 输出、replay/pilot report、审计 key/labels/review 和当前 runtime tree，任一漂移拒绝启动/续跑。
- 已冻结旧 inventory：EDGAR 3,500/2,931（14 waves），Enron 1,250/85（5 waves），PubMed 1,000/832（4 waves）；inventory identity=`8f051d015607dd59ac2a6b7dbd40c5b634ea8f128cf02038f72b0dfd9aac564e`。
- 最终全量 unittest 364/364 通过。AST 13 个关键文件、5 个 entity-policy YAML 与 `git diff --check` 通过；API/victim/Retriever 调用新增 0。
- pilot cohort 冻结已完成；尚未运行 23-wave replay、A cohort 6-wave pilot 和 600 条审计，这些门禁完成前正式扫描保持 blocked。
- 2026-08-05 已完成约 2.3GB processed universe 的单遍 cohort 冻结：plan identity=`e43a1c4c4fa2d53db439993a5bd24d6878485078eea27805d0e337bd91c920c1`，A/B/C 每数据集各 500 source，candidate coverage 验证为每数据集 1,500。剩余未运行任务为 23-wave replay、cohort A 的 6-wave pilot 和 600 条审计。
- Enron replay wave 1/5 已完成：29/250 query eligible（11.6%，Wilson lower 8.20%），旧同 wave 为 22/250。facts replay 与 source replay 都是 233 pairs；CONTRACT_TERM 恢复为 18 pairs、ORG 30 pairs。该结果只作为中间 checkpoint，不触发调参或通过判定。
- Enron replay 最终 5/5 passed：131/1,250（10.48%，Wilson lower 8.901%），旧策略 85/1,250。五波 facts/source pair count 与类型分布逐波一致，总计 1,174 pairs；report identity=`fbac0df34bc915d1e8c869d24cf84477da1d4cd02660f4cc1c2761545ae0bacc`。下一步 PubMed replay。
