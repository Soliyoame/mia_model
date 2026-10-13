# V25 shared-G 统计附录

## 数据与配对

- 输入 artifact：artifacts\v25\development\shared_g_anchor_cohort_query_usable_100sample_50plus50_member_index_fixed_20261002
- source：100（Member 50，True Non-member 50）
- query：900；initial response：300；follow-up response：178
- 条件比较只保留 initial_label=correct 的 slot，因此 n=89；同一 source 的 slot 不是独立 source 样本，source-cluster bootstrap 以 source 重采样。
- answer label 使用冻结 surface matcher；ambiguous 和 invalid 均不计为 correct。

## 条件恢复率

| subset | n trigger | anchored correct | no-anchor correct | delta |
|---|---:|---:|---:|---:|
| ALL | 89 | 58 | 56 | +2.25 pp |
| Member | 87 | 58 | 56 | +2.30 pp |
| True Non-member | 2 | 0 | 0 | +0.00 pp |

## McNemar

全部触发槽位：A=N=1: 50，A=N=0: 25，A=1,N=0: 8，A=0,N=1: 6。精确双侧 McNemar p=0.79052734375。

## Source-cluster bootstrap

对每个有触发的 source 计算 Δ_s=(Σ_i A_si−Σ_i N_si)/(Σ_i I_si)。点估计采用所有 triggered slot 的加权差异；bootstrap 每次有放回重采样 source，再按触发槽位聚合。种子=20261003，重复=20000。

| subset | source | trigger | weighted delta | 95% CI | mean source delta | sign test |
|---|---:|---:|---:|---|---:|---:|
| ALL | 45 | 89 | 0.0225 | [-0.0753, 0.1236] | 0.0296 | p=1 |
| Member | 43 | 87 | 0.0230 | [-0.0769, 0.1266] | 0.0310 | p=1 |

## Retrieval paired diagnostics

Member triggered slots：target-source hit paired counts={"true,true":83,"true,false":2,"false,true":0,"false,false":2}；answer-surface hit paired counts={"true,true":51,"true,false":2,"false,true":0,"false,false":34}。这些结果只能说明检索上下文变化，不能直接等同于 victim 的推理或记忆机制。

## Query length

- initial：mean 73.51 chars
- anchored：mean 130.65 chars
- no-anchor：mean 71.28 chars
- canonical anchor：mean 26.83 chars

## 解释限制

本附录只使用已有 development response、query plan 和 retrieval artifact；没有重新调用外部模型，也没有根据结果改选 source、G、anchor、query 或 scoring。当前统计不能估计充分的 Non-member interaction，也不能解决 surface matcher 的语义等价问题。

## 误报纠正终点

在当前 report 的 development diagnostic threshold `tau=0.3` 下，initial positive source 为 `45/100`，其中 Member `43`、True Non-member `2`。因此 initial FPR=`2/50=4%`。

- anchored-chain 后两个 initial True Non-member false positives 都降到阈值以下：FPC=`2/2=100%`，FPR=`0/50=0%`；Member TPR=`32/50=64%`。
- no-anchor-chain 后同样是 FPC=`2/2=100%`，FPR=`0/50=0%`；Member TPR=`27/50=54%`。

这两个 `2/2` 结果只能作为 feasibility evidence。阈值必须在 successor 的 victim response 可见前冻结，并且需要预注册足够的 initial false-positive source 容量，才能报告稳定的 correction rate。所有 correction 结果都必须同时报告 Member retention/TPR cost。

## 赋分制重算

旧 `tau=0.3` 只作为历史审计诊断保留。当前 source-level 主分数为：

\[
S_\lambda=\sum_i I_i+\lambda\sum_i I_iF_i,
\qquad \lambda=1.
\]

初始 gate 为 `sum(I_i)>=1`，操作性 cutoff 为 `S_1>=2`。因此一个 local 命中得到 1 分；一个 local 与其 gated `G` 都答对得到 2 分；两个 local 命中即使 follow-up 没有命中也得到 2 分。主统计是 score distribution 和 AUC，cutoff 只用于纠正诊断。

| arm | AUC of S1 | positive at cutoff | Member TPR | True Non-member FPR | corrected initial FP | retention among initial Member positives |
|---|---:|---:|---:|---:|---:|---:|
| initial gate | 0.9228（历史初始分） | 45/100 | 43/50 (86%) | 2/50 (4%) | - | - |
| anchored | 0.9260 | 40/100 | 40/50 (80%) | 0/50 (0%) | 2/2 | 40/43 (93.0%) |
| remote-only | 0.9256 | 39/100 | 39/50 (78%) | 0/50 (0%) | 2/2 | 39/43 (90.7%) |

参数网格为 `lambda={0.5,1,1.5,2}`、cutoff=`{1,2,3,4}`。`cutoff=1` 不纠正当前误报；cutoff=`2` 是拒绝单个 local 点的最小值。`lambda=0.5` 使完整 local→G 链只有 1.5 分；`lambda=1` 是满足“两个等权证据点”解释的最小值。该网格只是 development calibration，不能替代 successor victim 前冻结，也不能被 formal response 重新调节。

source-level 统计单位仍是 source document；三个 `F_i` 共享一个 `G`，不能将 3 个 probe 当成 3 个独立样本。当前 True Non-member 初始误报只有 2 个 source，`2/2` 仍只能报告 feasibility evidence。
