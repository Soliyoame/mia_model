# Task Plan: PCV-MIA v20 正式实验前整改

## Goal

在不调用 Generator API、不更换三个数据集现有 1,250-source universe 的前提下，完成并验证
Reserve 5/245 冻结、Oracle/Random、source-level baseline、离线 defense、统计口径、
响应元数据、交错调度和 canonical fail-closed 门禁。

## Phases

- [x] Phase 1: 审计现有实现、artifact schema 与未提交修改边界
- [x] Phase 2: 冻结配置、Reserve 角色、统计与论文口径
- [x] Phase 3: 修复 Oracle/Random、Pilot gate 和响应 metadata
- [x] Phase 4: 实现 representative-chunk baseline 和完整身份
- [x] Phase 5: 实现两项离线 defense 与 conformal/utility 报告
- [x] Phase 6: 完成近重复整改、交错 schedule、Retriever 门禁与 canonical 门禁
- [x] Phase 7: 生成 representative chunk，运行无 API 全量测试与 dry-run
- [x] Phase 8: 同步研究记录与交付总结

## Decisions Made

- 保持 `pcv-mia-v20` / `pcv-rag-only-source-v20` 和
  `meta/llama-3.1-70b-instruct`。
- Reserve 中 Pilot 5 source 永久排除，剩余 245 source 用于 secondary empirical conformal。
- 删除数值型 TPR@0.1%FPR；保留 AUC、TPR@1%/5%、attack advantage 和 conformal 1%/5%。
- Baseline 仅用 BGE，每个 source 使用五方法共享的一个 representative chunk。
- Defense 仅实现两项离线响应层策略，不声称通用 QA utility。
- 本轮不调用任何 Generator API。
- 跨组近重复簇以 seed 42 进行 cluster-level 确定性重分组，并保留原产物备份。
- Retriever 门禁候选级 checkpoint 必须绑定 index/query/benchmark/config hash。

## Errors Encountered

- 首次 release-controls 在 Edgar 检出 1 个跨组近重复对；已确定性重分组并备份。
- 第二次 release-controls 在 Enron 检出 7 个跨组近重复对；已按 cluster 重分组并备份。
- 重分组后三个数据集跨组近重复 overlap 均为 0。
- 第一次 Retriever 门禁因 20 分钟工具时限被终止，未写新报告。
- 已增加候选级 checkpoint；用户随后要求暂停，进程已安全终止，尚无新候选 checkpoint。
- 恢复后 9/9 Retriever 候选完成，BGE 门禁通过并选择 128/32。
- 首次全量测试暴露三个旧测试 fixture 与 v20 口径不一致；已改为 1%/5% FPR、
  schedule/reserve hash 和带文本 Reserve fixture。
- token-bucket timing 测试在 Windows 调度下偶发越界；增大 fake endpoint 的测试
  间隔后连续通过，不改变生产限速逻辑。
- canonical dry-run 首次发现 `victim_model_slug` 未定义；改为从冻结 concrete model
  生成 slug，并让 BM25/hybrid 默认跳过 BGE-only secondary steps。
- v20 总预检首次用完整 source_key 对照 index docstore 的 source_id 而失败；修正
  为按冻结 KB source_id 验证后通过。

## Status

**Complete** — 306/306 unittest、255 Python AST、17 YAML、canonical dry-run、
`git diff --check` 与 v20 zero-API preflight 均通过。正式/API calls=0；下一阶段是
需要用户真实 endpoint 的 2,700-call Llama Pilot。
