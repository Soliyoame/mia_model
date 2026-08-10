# Baselines 源码索引（PCV-MIA 对照实验）

本目录收集 RAG 成员推断攻击的 baseline **源码**，供"共享流水线、只换攻击层"的公平对照使用。
所有 baseline 最终都应在**同一个 edgar KB、同一个 victim API、同一套指标**（AUC / TPR@FPR / Accuracy）
下评估，由 `victim_harness.py`（第 12 步 `scripts/12_run_baselines.py` 调用）统一汇总。

> ⚠ 切忌直接跑各仓库自带的 pipeline/数据/受害模型去比数字——那样不可比。
> 源码的用途是**当"精确实现的标准答案"**：抠出每个攻击的「①发什么 query ②怎么打分」，
> 在本项目流水线里重写成"攻击打分器"。

## 六个 baseline 一览

| 名称 | 论文 | 源码来源 | 纯黑盒? | 本目录形态 |
|---|---|---|---|---|
| **IA**（Interrogation Attack，最近竞品） | [2502.00306](https://arxiv.org/abs/2502.00306) | ✅ 官方 [ali7naseh/RAG_MIA](https://github.com/ali7naseh/RAG_MIA) | ✓ | `IA/`（整仓） |
| **DCMI**（当前 SOTA） | [2509.06026](https://arxiv.org/abs/2509.06026) | ✅ 官方 [Xinyu140203/RAG_MIA](https://github.com/Xinyu140203/RAG_MIA) | ✓ | `DCMI/`（整仓） |
| **MBA** | [2410.20142](https://arxiv.org/abs/2410.20142) | ❌ 无官方 → 第三方 [MIRABEL](https://github.com/nonalcohol-park/MIRABEL) | ✓ | `MBA/`（抽取）+ `MIRABEL/`（整仓） |
| **S²MIA** | [2406.19234](https://arxiv.org/abs/2406.19234) | ❌ 无官方 → 第三方 [MIRABEL](https://github.com/nonalcohol-park/MIRABEL) | (s)✓ / (s&p)✗ | `S2MIA/`（抽取）+ `MIRABEL/` |
| **RAG-MIA**（地板线） | [2405.20446](https://arxiv.org/abs/2405.20446) | ❌ 无官方（一句 prompt） | ✓ | `RAG_MIA/`（据论文重写） |
| **MEntA**（Membership Entailment Attack） | [2605.24312](https://arxiv.org/abs/2605.24312) | 论文流程适配 | ✓ | `menta.py`（source-level adapted） |

附：`MIRABEL/` = EMNLP'25 防御研究仓（[2505.22061](https://arxiv.org/abs/2505.22061)），一处含 MBA+S2+IA+防御+一站式脚本，是 MBA/S²MIA 的源。

## 目录结构

- `IA/` — IA 官方整仓（ali7naseh）。注：自带 `datasets/`（~14M）我们用不上，可删。
- `DCMI/` — DCMI 官方整仓（Xinyu140203）。核心 `MIA.py` / `perturb.py`。
- `MIRABEL/` — MBA+S2+IA 统一复现整仓。核心 `mia.py` / `prompt/mia_prompt.py`。
- `MBA/mba_highdiff.py` — **投稿级高难词 MBA**（移植 IA 官方 `mba.py`：proxy LM 按 rank 挑最难词遮蔽）。harness 默认用它。
- `MBA/mba_reference.py` — MIRABEL 随机 mask 版（简化，保留备查/消融）。
- `S2MIA/s2mia_reference.py` — 从 MIRABEL 抽取的自包含 S²MIA（含 S2Prompt）。
- `RAG_MIA/rag_mia_reference.py` — 据论文重写的直接询问攻击。
- `menta.py` — MEntA 冻结 query 校验、专用 RAG prompt、atomic claim、DeBERTa NLI 和拒答扣分。
- `victim_harness.py` — **真实受害查询 harness**：目标枚举 + RAG 作答 + 6 个适配器（RAG-MIA/S2MIA/MBA/IA/DCMI/MEntA）+ attacker 构造 + per-target 打分 + 指标。第 12 步实际调用它。

## 怎么跑

```bash
# 试跑（省 API）：每类各取少量目标，限速 15s
python scripts/12_run_baselines.py --dataset edgar --max-targets 20 --request-interval 15
# 只跑便宜三件套（不需 attacker）
python scripts/12_run_baselines.py --dataset edgar --methods RAG-MIA,S2MIA,MBA
# 下载并校验 MEntA 的冻结 NLI snapshot（不调用 Generator API）
python scripts/download_frozen_menta_nli.py
# 用 sibling 离线生成并冻结 summary+5 queries（不调用 victim）
python scripts/27_prepare_menta_inputs.py --dataset edgar
# 全量六个（IA/DCMI 需 runtime attacker；MEntA query 已离线冻结）
python scripts/12_run_baselines.py --dataset edgar
```
输出：`outputs/baselines/edgar/edgar_<method>_scores.jsonl`（每目标分数）+ `edgar_baseline_comparison.jsonl`（含 PCV-MIA 的对照表）。支持断点续跑。

## 威胁模型对齐（关键）

- PCV-MIA = **纯黑盒 + chunk 级**；所有 baseline 同此口径。
- **S²MIA(s&p) 困惑度变体需 logprob/本地 GPT-2 → 非纯黑盒**：主表只用 **S²MIA(s) 相似度版**，(s&p) 附录单列并标注。
- 其余（IA / DCMI / MBA / RAG-MIA / MEntA）均纯黑盒。MBA 的 proxy LM 只在 attacker 侧**离线选词**；MEntA 的 sibling 只离线生成查询，本地 NLI 只对黑盒回答打分。

## 忠实度现状（方案一落地后）

走「方案一」：**原样移植官方确定性逻辑 + 接缝注入统一 RAG + 差分测试**。

| Baseline | 实现 | 忠实度 |
|---|---|---|
| RAG-MIA | 据论文一句 prompt + yes/no 二值分 | 高（二值→AUC 退化，主看 Accuracy/balanced-acc） |
| S²MIA(s) | 按字符切半→前半段当 query→**BLEU(完整原文, 回答)**，移植 IA 官方 `s2.py` | 高（纯黑盒；(s&p) 困惑度作附录） |
| MBA | **proxy LM 按 rank 挑高难词遮蔽**→填空→填对率，移植 IA 官方 `mba.py` | 高（跳过拼写纠正并标注；弃 MIRABEL 随机版） |
| IA | summary+30 问（官方 prompt，保留缩写）→**同源检索器筛 top_k 区分度**→一致率 | 高（用同源检索分代替 ElectraScorer，免 pyterrier 重依赖） |
| DCMI | base=S²(s) 同口径 BLEU 重叠；扰动=**反义词替换 3%**（对齐官方 `perturb.py`）；差分+阈值 | 中-高（扰动/差分/阈值忠实；base 为重叠近似，官方 base 藏 flashrag 未完整开源） |
| MEntA | summary+5 个自然问题→5 次 RAG→回答 atomic claims→DeBERTa entailment/refusal→均值 | source-level adapted（共享代表 chunk 与统一 harness，不冒充官方数据集复现） |

统一「记忆复现」尺子 = `lexical_overlap`（BLEU method4），S²MIA 与 DCMI base 共用，审稿口径一致。

> 差分测试见 `tests/test_baseline_adapters.py`：对确定性逻辑（切半/选词解析/yes-no/区分度筛选/差分公式/填对率）喂罐头断言，回避 LLM 随机。移植中发现并修正官方 `_ia_yn` 的 `s[:8]=="idontknow"` 死代码 bug（-1/-999 在打分中等价，不改变任何分数）。

## 实验条件对齐（审稿命门）

- **同一** KB 索引 / victim / 检索器+top_k / temperature / RAG prompt 外壳 / 指标（harness 强制共享）。
- **逐行同源**：PCV-MIA 只在 baseline 实际跑的同一批 `doc_id` 上算指标（`scripts/12` 已按 target_ids 过滤），`--max-targets` 子集时尤其关键。
- **attacker 统一**：IA/DCMI 的 attacker 固定同一模型；`--attacker victim` 让 attacker 复用 victim（免配 sibling key），纯黑盒前提不破（attacker 仅离线造问题/扰动）。
- **粒度=chunk**：baseline 原论文多 document 级，我们统一到 chunk（更严格），论文需声明。
- **指标口径**：主指标 AUC + TPR@1%/5%FPR（阈值无关）；Accuracy@best 是 oracle 阈值，辅助参考；RAG-MIA 二值→AUC 退化，单独标注。

## 状态

- ✅ 六个适配器已接入；MEntA 的 query/NLI/harness mock 测试零 API 全绿。
- ⚠ MEntA 正式运行前必须先生成三数据集 query manifest，并下载 revision `04dcf11f...99d5` 的本地 NLI snapshot；任一 hash 漂移都会拒绝 resume。
- ⚠ MBA 首次跑会下载 proxy LM（默认 gpt2，~0.5G）；CPU 可跑，但选词慢（每候选词一次前向）。
- ⏳ 待真跑：先 `--max-targets` 小规模验证，再 small 全量 → formal。IA/DCMI 贵，按需限速。
