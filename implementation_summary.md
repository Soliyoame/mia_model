# PCV-MIA v20 Remediation Summary

## Outcome

现有三个 1,250-source 数据集已在 Llama 正式响应为 0 的前提下原地冻结为
`pre_response_frozen_canonical`。v20 离线整改与总预检全部完成，下一步可以进入
2,700-call Llama compatibility Pilot；正式 90,000-call suite 仍被 Pilot gate
阻断。

## Implemented

- Reserve 5 Pilot / 245 empirical conformal 分区与 source-level 统计；
- 128/32 BGE Retriever gate、正式 BGE/BM25 index 与 90,000-request schedule；
- 三组 Oracle、预算匹配 Random 与近重复排除；
- BGE-only 五 baseline 的共享 representative chunk；
- 两个真实零 API response defense；
- concrete model/response metadata/resume/model-drift/clean-commit fail closed；
- 唯一 primary macro AUC endpoint、1%/5% FPR 与 2,000×bootstrap；
- zero-API 总预检脚本和完整研究记录。

## Evidence

- 306/306 unittest passed；
- 255 Python AST / 17 YAML passed；
- Retriever 9/9 candidates complete，selected 128/32；
- preflight checks hash:
  `34e2ffa355d46d942aa9b27b339a4d0c02dbf589a1aa99747e3a73a2f65fb619`；
- formal/API calls made: 0。
