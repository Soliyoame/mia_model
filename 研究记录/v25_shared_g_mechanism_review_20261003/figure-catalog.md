# Figure catalog

| 文件 | 内容 | 统计单位 |
|---|---|---|
| figures/gate_and_conditional_recovery.png | initial gate 与条件 G recovery 的分组对比 | slot；条件部分只含 initial-correct slot |
| figures/paired_followup_outcomes.png | anchored/no-anchor 配对结果 2×2 表 | 同一 source-slot |
| figures/triggered_retrieval_hits.png | Member 触发槽位的 target-source 与 answer-surface hit@5 | 同一 source-slot |
| figures/false_positive_correction_tradeoff.png | 赋分制 cutoff=2 下的 FPR/TPR trade-off | source-level，development diagnostic |
| figures/point_score_distribution.png | anchored 与 remote-only 的 S1 分数分布及 cutoff=2 | source-level，Member/True Non-member |

图仅用于 development mechanism review，不是 formal paper figure。主分数是 `S_lambda`；旧 tau 阈值图不再作为当前主评分图。
