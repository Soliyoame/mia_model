# V25 shared-G 跨批次零调用汇总与案例审计

日期：2026-10-03<br>
状态：development_only；不构成 formal test 或正式方法结论。<br>
统计单位：source document。<br>
本次审计：只读取已有 artifact，外部调用、Luna、Retriever、victim、GPU 均为 0。

## 结论先行

两批有自然 gated 初始误报的 development identity 都出现了相同的操作性结果：fixed-index 批次的 2 个 True Non-member 初始误报，以及 fresh successor 的 1 个初始误报，在 lambda=1、cutoff=2 的 source-level 赋分下都被 correct_anchor 和 remote_only 两个追问臂降到 cutoff 以下。跨批次只是一个描述性计数：3 个自然初始误报、3 个被筛除；不能把它写成合并后的总体纠正率或置信区间。

这个结果支持的命题是：

> correctness-gated second-stage source-evidence confirmation can correct a small number of local-stage false positives.

它不支持两个更强的命题：correct_anchor 已经带来稳定的 anchor-specific 增益，或局部事实已经被证明能因果地导航到远端 G。fixed-index 和 fresh 中，correct_anchor 与 remote_only 的误报纠正结果完全相同；当前纠正主要表现为“一个 local 点不足以达到最终 cutoff，而追问没有产生第二个证据点”。

r3 没有自然 gated 初始误报，因此不能贡献 correction event。r3 的 9 条 forced non-member follow-up 全部得到 ambiguous 拒答，目标 source/G 的 top-5 命中均为 0；它是单独的拒答/上下文缺失诊断，不能并入 gated correction。

## 批次汇总

| 批次 | source（Member / Non-member） | 冻结 query | initial 正确槽位（M / N） | 初始误报 source | 触发槽位 | gated follow-up | 备注 |
|---|---:|---:|---:|---:|---:|---:|---|
| r3 pilot | 3 / 3 | 54 | 5 / 0 | 0 | 5 | 10 | 只有 Member 触发；另有 9 条 bypass diagnostic |
| fixed-index | 50 / 50 | 900 | 87 / 2 | 2 | 89 | 178 | 完整 50+50，Member-only index |
| fresh successor | 29 / 30（原始 frame 50 / 50） | 531 | 44 / 1 | 1 | 45 | 90 | 97 个结构通过，59 个盲审 accepted/evaluated |

### 追问标签与检索

| 批次 / arm | G 正确 | G 错误 | ambiguous | target-source hit | G answer-surface hit |
|---|---:|---:|---:|---:|---:|
| r3 anchored（5 个触发槽） | 5 | 0 | 0 | 见整批 26/54 | 见整批 10/54 |
| r3 remote-only（5 个触发槽） | 2 | 3 | 0 | 见整批 26/54 | 见整批 10/54 |
| fixed anchored（89 个触发槽） | 58 | 24 | 7 | Member 144/150；Non-member 0/150 | Member 85/150；Non-member 0/150 |
| fixed remote-only（89 个触发槽） | 56 | 29 | 4 | Member 138/150；Non-member 0/150 | Member 78/150；Non-member 0/150 |
| fresh correct-anchor（45 个触发槽） | 24 | 20 | 1 | Member 87/87；Non-member 0/90 | Member 46/87；Non-member 0/90 |
| fresh remote-only（45 个触发槽） | 29 | 15 | 1 | Member 81/87；Non-member 0/90 | Member 48/87；Non-member 0/90 |

r3 的整批检索检查为 target-source 26/54、G surface 10/54。fixed-index 的 900 条 query 中，主 index 没有出现 Non-member chunk。fresh 中 Non-member initial 只有 2/90 的 answer-surface 命中，两个 follow-up arm 均为 0/90。

## 赋分制下的误报纠正

统一读取已有的 development 赋分规则：

S_1 = sum(I_i) + sum(I_i * F_i)，初始 gate 为 sum(I_i) >= 1，操作性 cutoff 为 2。

| 批次 / arm | AUC | Member TPR | True Non-member FPR | 初始误报纠正 | Member retention（相对 initial positive） |
|---|---:|---:|---:|---:|---:|
| fixed local-only，cutoff 2 | 未在原 report 单列 | 32/50 = 64.0% | 0/50 = 0% | 2/2 | 作为同 cutoff baseline |
| fixed correct-anchor | 0.9260 | 40/50 = 80.0% | 0/50 = 0% | 2/2 | 40/43 = 93.0% |
| fixed remote-only | 0.9256 | 39/50 = 78.0% | 0/50 = 0% | 2/2 | 39/43 = 90.7% |
| fresh local-only，cutoff 2 | 0.9397 | 14/29 = 48.3% | 0/30 = 0% | 1/1 | 作为同 cutoff baseline |
| fresh correct-anchor | 0.9448 | 23/29 = 79.3% | 0/30 = 0% | 1/1 | 23/26 = 88.5% |
| fresh remote-only | 0.9448 | 23/29 = 79.3% | 0/30 = 0% | 1/1 | 23/26 = 88.5% |

同 cutoff local-only baseline 已经会拒绝这些 one-local-hit 非成员；因此不能把 3/3 写成只有 G 才能完成的纠正。二阶段臂的实际附加作用，在这些批次中更明显地表现为保留一部分 Member source 的额外分数。fresh 中两个 arm 的每个 source-level 结果都相同；fixed 中两臂也纠正同一组 2 个 source，不能从这些结果识别 anchor-specific effect。

旧的 fixed chain threshold 结果仍保留为历史诊断：initial AUC 0.9228，anchored-chain AUC 0.82，remote-only-chain AUC 0.77。这些数字与新的 S_1/cutoff=2 诊断不可混合，也不能用来声称 anchor mechanism 已成立。

## 自然误报案例

### Case 1：SciDocs，单个 local hit

- source：scidocs::015d1aabae32efe2c30dfa32d8ce71d01bcac9c5
- group：True_Non_Member
- initial bits：[0, 1, 0]；触发 slot：1
- local question：What complexity are computational problems underlying solutions to these issues often found to have?
- local canonical answer：NP-hard
- initial response：These problems are often combinatorial (NP-hard).
- initial label：correct
- G answer：cost function
- anchored question：In the discussion of problems that are NP-hard, what is the function C known as?
- anchored response：The provided text does not contain the answer to your question.
- anchored label：ambiguous
- remote-only question：What is the function C known as?
- remote-only response：c / sub m /
- remote-only label：incorrect
- retrieval：三个 arm 的 target-source 和 G surface 命中均为 0
- 分数：initial 1，correct-anchor 1，remote-only 1；cutoff 2
- 结果：两臂都把这个 one-local-hit source 留在 cutoff 以下

这是一条明确的“局部事实可以答对，但同一 source 的远端事实没有形成第二个证据点”的案例。它不能区分 anchored 和 remote-only，因为两者都失败。

### Case 2：TREC-COVID，局部回答包含目标词但远端回答跑题

- source：trec-covid::00qoe8ir
- group：True_Non_Member
- initial bits：[1, 0, 0]；触发 slot：0
- local question：What is identified as having effects on the national health system response?
- local canonical answer：COVID-19
- initial response：The text states that the variability of health care scenarios, institutional capacity, heterogeneity and burden of urologic disease, impact of surgical indications and decision making when prioritizing and scheduling surgeries in times of covid - 19 pandemic are factors that can impact the national health system response.
- initial label：correct
- G answer：national health system
- anchored question：In the study involving COVID-19, what system's response is discussed?
- anchored response：The response to COVID-19 in assisted living facilities (ALFs) is discussed in the study.
- anchored label：incorrect
- remote-only question：What system's response is discussed?
- remote-only response：The acute phase response of haptoglobin and serum amyloid A (SAA) in cattle is discussed.
- remote-only label：incorrect
- retrieval：三个 arm 的 target-source 和 G surface 命中均为 0
- 分数：initial 1，correct-anchor 1，remote-only 1；cutoff 2
- 结果：两臂都把这个 one-local-hit source 留在 cutoff 以下

该案例中 anchored response 仍复用了 local anchor 词 COVID-19，但没有回答冻结的 G。它说明“回答中出现 anchor”不能替代 G 正确性判定。

### Case 3：fresh nfcorpus，自然 successor 复现

- source：nfcorpus::MED-3483
- group：True_Non_Member
- initial bits：[0, 0, 1]；触发 slot：2
- local question：What barrier can the main citrus flavonoids traverse?
- local canonical answer：the blood-brain barrier
- initial response：The blood-brain barrier.
- initial label：correct
- G answer：hesperetin
- correct-anchor question：In the discussion involving the blood-brain barrier, which citrus flavonoid is discussed as inducing cellular defense proteins against oxidative stress and neurotoxicity?
- correct-anchor response：The reference information does not discuss which citrus flavonoid is discussed as inducing cellular defense proteins against oxidative stress and neurotoxicity.
- correct-anchor label：ambiguous
- remote-only question：Which citrus flavonoid is discussed as inducing cellular defense proteins against oxidative stress and neurotoxicity?
- remote-only response：Naringenin
- remote-only label：incorrect
- retrieval：三个 arm 的 target-source 和 G surface 命中均为 0
- 分数：initial 1，correct-anchor 1，remote-only 1；cutoff 2
- 结果：两臂都把唯一的 one-local-hit 初始误报留在 cutoff 以下

这是 fresh identity 中唯一的自然初始误报，复现了 fixed-index 的操作性模式；同时，correct-anchor 与 remote-only 的 source-level 结果完全一致。

## r3 forced non-member 诊断

r3 的 3 个 True Non-member source（nfcorpus::MED-1134、scidocs::00ef4151ae7dfd201b326afbe9c112fac91f9872、trec-covid::00l2apsc）在 initial gate 下均没有触发，因此没有自然 correction case。按独立 diagnostic 规则绕过 initial gate 后发送 9 条 anchored follow-up，结果为：

- correct=0、incorrect=0、ambiguous=9、invalid=0
- target-source hit 0/9
- G answer-surface hit 0/9
- 9 条回答都是当前参考上下文无法提供答案的拒答形式

这说明在 Member-only index 中缺少目标 Non-member source/G 时，victim 对强制追问倾向拒答；它解释了为何非成员追问通常答不上来，但没有通过 gated protocol 纠正一个初始误报，所以必须保持 diagnostic_only。

## 证据边界与下一步

当前跨批次证据足以把方法定位为一个可运行的二阶段误报纠正机制，并且在 fixed-index 与 fresh successor 中各出现了自然案例。不能将三批合并为 formal AUC、稳定 FPC 或 anchor-specific gain。总自然初始误报容量只有 3 个 source，fresh 批次只有 1 个，统计不确定性仍由容量主导。

如需继续，下一次应使用新的 membership-blind 自然 cohort，在第一条 victim response 前冻结 S_1、cutoff、answer policy 和 gate，并增加自然 initial false-positive 容量。没有必要把 hard-negative 搜索设成继续实验的硬门槛，也不应根据本次 response、误报名单或结果回改 query/G/index。当前 formal release 仍关闭。

## 机器可读证据

完整统计、案例字段与 artifact hash 见同目录的 cross_batch_audit.json。关键输入 report hash：

- r3 report：207f520e34c9498605d580eea5cc9b2392a582c3920be2e115ef6cfd1229d580
- fixed-index report：c63c51a75a479cd1e277ea3145ac9bf337ad811f5f1dbed550f4b3305c6ae9f3
- fresh report：6bffed9ea977182767e7bee77108a620e507592a5efe825d70f3dc203dac1c66
