# V25 shared-G 独立机制审阅与赋分重算

日期：2026-10-03
状态：development_only；不构成 formal release 或方法有效性结论。
统计单位：source document；条件机制比较的配对单位是同一 source 的同一 slot。

## 审阅问题

本审阅先保留同一 initial correctness gate 的条件机制比较，再重算 source-level 累计证据分。主分析问题是：local 命中与 gated shared-G 命中组成的累计分数，是否比旧二元 chain threshold 更能保留 Member 证据并提供误报纠正诊断？chain AUC 只作为历史 secondary diagnostic，不能直接当作纯 anchor effect。

## 已核验事实

- 固定 cohort：100 个 source，50 KB_Member + 50 True_Non_Member；900 条冻结 query；300 条 initial response；178 条 follow-up response。
- initial correctness gate 触发 89 个 slot，其中 Member 87 个、True Non-member 2 个。
- follow-up gate 完整性为 178/178；没有多发或漏发。
- stored diagnostic：initial AUC=0.9228；anchored-chain AUC=0.82；no-anchor-chain AUC=0.77。两个 chain 分数都包含 initial gate。

## 主要结果

| 条件 | 触发槽位 | anchored correct | no-anchor correct | 条件差异 |
|---|---:|---:|---:|---:|
| 全部触发槽位 | 89 | 58/89 (65.2%) | 56/89 (62.9%) | +2.25 pp |
| Member | 87 | 58/87 (66.7%) | 56/87 (64.4%) | +2.30 pp |
| True Non-member | 2 | 0/2 (0.0%) | 0/2 (0.0%) | +0.00 pp |

配对结果：两臂都正确 50、两臂都不正确 25、anchored-only 8、no-anchor-only 6。精确双侧 McNemar 检验 p=0.79052734375，当前数据没有证明 anchored 相对 remote-only 存在稳定条件增益。

source-cluster bootstrap 按 source 重采样 20,000 次：

- 全部有触发 source：weighted delta=0.0225，95% CI=[-0.0753, 0.1236]。
- Member 有触发 source：weighted delta=0.0230，95% CI=[-0.0769, 0.1266]；source-level mean delta=0.0310；非零 source delta 的 sign test p=1（正 6、负 5）。

最稳妥的判断是：观察到很小的正向点估计，但区间跨过 0，不能把它写成机制已经成立。

## 混杂与机制审计

1. Initial gate 已经承担了大部分 membership 分离。Member 初问正确率为 87/150 = 58.0%，True Non-member 为 2/150 = 1.33%。因此 chain AUC 的差异不能单独归因于 anchor。
2. Anchored query 更长。在触发槽位上，anchored 平均 130.65 字符，no-anchor 平均 71.28 字符；canonical anchor 平均 26.83 字符。若没有长度和模板对照，差异可能来自 query specificity 或长度。
3. 检索层只显示轻微变化。Member 触发槽位 target-source hit@5：anchored 85/87，no-anchor 83/87；answer-surface hit@5：anchored 53/87，no-anchor 51/87。target-source paired hit 为 both=83、anchored-only=2、no-anchor-only=0、both-miss=2；answer-surface paired hit 为 both=51、anchored-only=2、no-anchor-only=0、both-miss=34。
4. Answer matcher 仍是诊断限制。触发槽位中两臂标签不同的有 18 个，Member 为 17 个。已见 r = 0.885 与 0.885、100.57% and 108.46% 与 100.57% to 108.46%、连字符/空格等格式差异。当前不事后改写标签；下一轮必须在 victim 调用前冻结 answer alias 和 semantic adjudication 规则。
5. G 的 region 约束是偏好而非硬门禁。当前 100 个 source 全部记录为 different_preferred；其中 96/100 个 source 的 different_region_count=3，4 个 source 的远端 region 与至少一个 local region 相同。因此下一轮应按 region relation 分层报告，不能把“尽量另一区域”写成已满足的硬条件。
6. Non-member interaction 当前不可估计。只有 2 个 True Non-member triggered slot，不能支持 Member/Non-member anchor interaction 结论。

## 机制结论

当前证据支持“设计可运行、可以在严格 gate 下配对比较”，不支持“正确 local anchor 已经产生稳定的 Member 特异远端恢复增益”。在新的误报纠正口径下，这批数据可报告两个初始非成员误报均被 follow-up 拒绝，但分母只有 2 个 source，且 Member TPR 有明显代价。因此这批结果仍保持 development_only，不能晋升 formal，也不能把 anchored-chain AUC=0.82 相对 no-anchor-chain AUC=0.77 写成已证实的 anchor navigation。

## 下一轮最小对照矩阵

推荐建立新的 development identity，保留同一 initial gate，并冻结以下 follow-up arms：

| arm | 查询内容 | 主要排除的解释 |
|---|---|---|
| correct_anchor | 对应 slot 的 canonical e_i + 同一个 G | 目标方法 |
| remote_only | 同一个 G，不放 local fact | 远端问题本身或目标可回答性 |
| same_source_permuted_anchor | 同一 source 的另一个 local fact e_j，建议固定循环置换 e1→e2→e3→e1 + 同一个 G | 正确对应关系之外的任意 source-local cue、长度和模板具体性 |
| cross_source_matched_anchor（matched subset） | 同数据集、同事实类型、相近长度的其他 source anchor + G | source specificity；只做次要诊断 |
| neutral_length_matched（可选） | 只能在自然且提前冻结时使用的长度匹配模板 | query 长度效应；不能事后填充无意义字符串 |

在原先的 anchor-gain 目标下，前三个 arm 是最小集合。按照当前“误报纠正”目标，core 只需 `correct_anchor` 与 `remote_only`；`same_source_permuted_anchor` 改为可选 attribution control。core 最大调用数为 `3 + 2×3 = 9`，加入置换臂时才是 `3 + 3×3 = 12`，两种情况都需要新的 successor identity。

## 预先注册的判定与停止规则

- 原机制指标 P(F=1 | I=1, arm) 降为 secondary diagnostic；新的主指标是冻结 `S_lambda` 的 source-level 分布与 AUC，固定 cutoff 下的 false-positive correction、FPR/TPR、Member retention 和 TPR cost 作为操作性诊断。
- 预先冻结 canonical answer alias、数字/连字符/单位归一化和 ambiguous 处理；人工复核如存在，单独标为 annotation，不与自动 matcher 混写。
- 若初始 True Non-member false-positive 集合太小，只能报告 feasibility，不能声称稳定 correction rate。
- correct_anchor 与 remote_only 的差异用于判断纠正是否依赖 anchor；它不再是必须证明的稳定 G-recovery gain。
- same_source_permuted_anchor 只用于可选 attribution；若加入，需预注册并做多重比较校正。
- 必须同时报告 Member retention/TPR cost，不能只报告 FPR 降为 0。
- 所有 query、G、anchor mapping、region relation、answer rules 必须在第一条 victim response 前冻结；运行时只能条件发送，不能条件构造。

## 当前决定

继续做 successor development 对照，不进入 formal。分析包、图表和统计附录保存在 研究记录/v25_shared_g_mechanism_review_20261003/；输入 response、retrieval、query plan 和 report 保持只读。

## 历史阈值诊断（保留作审计）

这一节保留旧 report 中的 `tau=0.3` 二元诊断，数值不再作为当前主评分规则。后续不把“正确 local anchor 是否带来稳定的 G 恢复增益”作为必要主张。

对 source-level 阈值 tau 定义：

\[
FP_0 = \{s: y_s=\mathrm{True\_Non\_Member},\ S_{initial}(s)\ge\tau\}
\]

若某个 source 满足 `S_initial >= tau` 且 `S_followup < tau`，则记为一次 false-positive correction。主要指标为：

- `FPC = corrected initial false positives / initial false positives`；
- 同一 tau 下的 FPR before/after；
- Member retention：follow-up 后仍为正的 Member source / initial 为正的 Member source；
- TPR cost：follow-up 后 Member TPR 相对 initial TPR 的下降。

在当前 development report 的诊断阈值 `tau=0.3` 下：

- initial：45 个 source 为正，其中 43 Member、2 True Non-member，FPR=`2/50=4%`；
- anchored-chain：32 个 source 为正，2 个初始非成员误报均被纠正，FPR=`0/50=0%`，FPC=`2/2=100%`；Member TPR 从 `43/50=86%` 降为 `32/50=64%`；
- no-anchor-chain：27 个 source 为正，同样纠正 `2/2` 个初始非成员误报，FPR=`0/50=0%`，但 Member TPR 降为 `27/50=54%`。

这说明当前数据已经提供了“可以纠正误报”的可行性证据，但不能把 `2/2` 当作稳定总体纠正率：误报分母只有 2 个 source，且 tau 在该 report 中是 development diagnostic threshold。successor 必须在 victim response 可见前冻结 tau，并预先规定最小初始误报容量；容量不足时只能报告 feasibility，不得报告稳定率或泛化结论。

因此 successor 的 core arms 可以简化为 `correct_anchor` 与 `remote_only`：前者测试目标流程能否纠正误报，后者测试纠正是否只是任意 follow-up 拒答效应。`same_source_permuted_anchor` 保留为可选的 attribution control，不再是“证明稳定 G 增益”的必要条件。无论哪一臂，都必须同时报告 Member retention 和 TPR cost，不能只报告 FPR 降为 0。

## 赋分制重算

当前 successor 的主分数为：

\[
S_\lambda(s)=\sum_{i=1}^{3}I_i(s)+\lambda\sum_{i=1}^{3}I_i(s)F_i(s).
\]

离线 development calibration 选择 `lambda=1`：local 命中和对应 gated `G` 命中各占一个证据点，source 满分为 6。它不把三个共享 `G` probe 当成三个独立事实。为便于操作性报告，另行使用 `initial gate=sum(I_i)>=1` 与 `score cutoff=2`；主结果仍是 source-level 分布和 AUC，cutoff 只用于 FPR/TPR 与误报纠正诊断。

| arm | S1 AUC | cutoff 以上 source | Member TPR | True Non-member FPR | 初始误报纠正 | Member retention |
|---|---:|---:|---:|---:|---:|---:|
| initial gate | 0.9228（历史初始分） | 45/100 | 43/50 (86%) | 2/50 (4%) | - | - |
| anchored | 0.9260 | 40/100 | 40/50 (80%) | 0/50 (0%) | 2/2 | 40/43 (93.0%) |
| remote-only | 0.9256 | 39/100 | 39/50 (78%) | 0/50 (0%) | 2/2 | 39/43 (90.7%) |

参数敏感性检查覆盖 `lambda={0.5,1,1.5,2}` 与 cutoff=`{1,2,3,4}`。`cutoff=1` 保留初始误报；`cutoff=2` 是拒绝单个 local 点的最小值。`lambda=0.5` 会使完整 local→G 链只有 1.5 分，而 `lambda=1` 让这条链恰好获得两个等权证据点；更高 cutoff 会显著牺牲 Member TPR。因此 `lambda=1、cutoff=2` 是可解释的 development 候选，不是看过 formal response 后调出的最优参数。

这个结果改善了旧 chain-threshold 的 Member retention（anchored `80%` 对旧 `64%`，remote-only `78%` 对旧 `54%`），但两个初始 True Non-member 误报的分母仍只有 2 个 source。结论仍限定为 development feasibility；successor 必须在 victim response 可见前冻结公式、参数、answer rules 和最小误报容量。
