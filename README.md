# PCV-MIA

PCV-MIA 是一个面向 RAG 知识库的成员推理攻击实验框架。方法全称是：

```text
Paired Counterfactual Verification Membership Inference Attack
```

中文可以理解为：

```text
基于成对反事实验证的 RAG 知识库成员推理攻击
```

核心问题是：当某篇文档进入 RAG 知识库后，模型在回答真假事实验证问题时，是否会因为检索到私有上下文而获得额外的验证、否定和纠错能力。

PCV-MIA 的做法是：从候选文档里抽取可验证事实，构造真实 claim 和最小同类型反事实 claim，再生成 Q+ / Q- 查询。P0 主攻击只使用 `RAG` 返回的支持、否定和纠错行为计算 Paired Verification Score；`LLM-only` 作为预训练记忆/上下文增益的归因对照，不参与主攻击判定。

一句话概括当前代码：

```text
KB isolation
+ attackable fact extraction
+ paired counterfactual verification
+ RAG-only paired verification score
= source-document membership score
```

## 当前状态

### 2026-07-20：投稿级 canonical 完善进度

- 已预注册 `configs/canonical_suite.yaml`：Edgar/Enron × main/matched-control，formal、seed 42、同一 Qwen victim，选择规则固定为首个通过全部门禁的 run。
- canonical 门禁现强制检查干净 commit、benchmark/config/artifact hash、source coverage、响应完整性、source whitelist、baseline/report 同源，以及完整 suite 四格；不完整 suite 不能驱动正式图表。
- 已接入 source-level 离线消融、2/4/6/8 调用预算曲线、三个在线 query control、文本/embedding/检索捷径诊断和跨 Edgar/Enron 的 stance 人工审计模板。预算曲线现在在共同 source 上报告 AUC bootstrap CI，以及相对 full PVS 的 paired delta。
- Edgar formal 主查询计划含 4,446 条 query、2,223 个完整 pair；当前 Qwen 模型目录中的 RAG 响应已达到 4,446/4,446 成功，无重复、空回答、失败或缺失。Step 10 的主攻击采集已经补完，但后续 source-level canonical 重建和门禁尚未执行。
- Edgar 独立 matched-control 的 LLM-only 响应当前保留为 incomplete attribution control（已知 3,877/4,446 成功，仍缺 569 条）；由于 victim API 暂不可用，暂不将其纳入 canonical 归因结论。Enron formal 的 01–09 已完成，主查询计划含 4,766 条 query、2,383 个完整 pair，但同一 Qwen victim 下的 RAG/LLM-only 响应尚未采集。因此两数据集当前都还不是 canonical run。
- canonical release 会从完整 matched-control 响应离线重建 `pvs_llm`，在与主运行完全相同的 source whitelist 上生成 `cg_cvg = pcv_score - pvs_llm` 归因诊断；`pcv_score` 始终保留为 RAG-only 主分，不被归因对照改写。

### 2026-07-11：P0/P1 工程状态

- P0 协议层已切换为 **RAG-only Paired Verification Score** 主分，LLM-only/context gain 仅作归因与阴性对照；论文评估单位为 source document，chunk 仅是检索与查询单位。
- 现有历史结果仍属于 `legacy_feasibility`，尚未重新生成可投稿的 canonical suite。
- P1 基础设施修复已落地：source coverage/完整 pair 门禁、空回答重试与成功优先响应压实、source-only report/figures/baseline、归档 SHA-256 inventory，以及共同 source 的 paired/budget-matched baseline 统计。旧产物仍须从第 10/11 步断点补齐后强制重建，不能直接视为已修复结果。
- 当前 Edgar/Qwen 模型分层响应中除 **356 个显式失败调用**外，还有 RAG 391、LLM-only 397 个空回答；新版 runner 会把空回答视为 `empty_response` 并重试，但旧文件必须断点补跑。
- 当前工作区已出现真实模型目录与 `unspecified/` 并存。正式重跑完成前，不要把不同目录下的 responses、scores、baseline、mechanism 或 report 拼成同一次实验。

P1 推荐恢复顺序：

```text
固定同一 PCV_RUN_ID 补跑失败与空回答调用
→ 强制重建 parsed stance / source scores / source coverage
→ 在共同 source whitelist 上重跑 baseline paired/budget-matched 统计
→ 重建 feasibility、mechanism、figures、final report 与 run manifest
```

当前仓库实现的是 PCV-MIA 主流程和实验评估框架。P0 冻结主分是 source-level RAG-only PVS；L1 conformal、LLM-only/context gain 和 L2 shadow 都是校准或归因分析，不替代主攻击定义。历史 Edgar 数字只用于可行性参考，必须等 source-level canonical run 完整后再更新论文主表。需要特别注意以下几点：

- RAG index 只能由 `KB_Member` 构建，代码中有硬检查。
- `True_Non_Member`、`Spoof_Seed`、`Reserve`、`Spoofed_Non_Member` 都不能进入 `indexes/`（`Reserve` 会从第 05 步起进入 benchmark 充当 L1 群体校准的零分布，但绝不进 RAG index）。
- hashing embedding fallback 已经移除，当前默认使用真实 `sentence-transformers/all-MiniLM-L6-v2`。
- 如果显式配置 `hashing` 或 `backend: hashing`，代码会直接报错。
- 没有安装或无法加载 `sentence-transformers` 模型时，流程会失败，而不是静默换成 fallback。
- `json_vector_fallback` 只是在没有 FAISS 时保存真实 embedding 向量的索引存储 fallback，不是 hashing embedding。
- `Spoofed_Non_Member` 是可选 hard negative 对照组，不是 PCV-MIA 主方法必需部分。
- `Reserve` 组从第 05 步起被纳入 benchmark，随主流水线跑出 `cvg_rag`，仅作为 L1 群体校准的"非成员零分布"；评估指标时必须排除（开关 `PCV_ENABLE_RESERVE_CALIBRATION`，默认 true）。
- 当前 NER 只是 `EntityExtractor` 的可注入候选源接口，默认没有自动加载 NER 模型。
- 5 个 baseline 已实现；defense 仍以 policy/report 骨架为主。P1 重跑完成前，现有 baseline 数值不得与新 source-level 主结果混用。

### 2026-07-13：Baseline 与 API 请求可靠性

- MBA 的 proxy-LM 选词阶段已串行化 Hugging Face tokenizer/model 访问，修复 `max_workers>1` 时的 `Already borrowed`。锁在 victim 请求前释放，不影响 RAG/API 并发。
- PCV-MIA 第 10 步与第 12 步全部 baseline 共享「短指数退避 + 长冷却无限重试」语义。超时、SSL EOF、空回答、429/5xx 和网关偶发 403 不再丢弃查询，而是冷却后重试同一请求直到成功。
- 每一次物理重试都重新经过令牌桶，不会绕过 `requests_per_minute`。缺依赖、解析错误等非 API 异常不会无限空等。
- 默认长冷却是 300 秒。若端点长期宕机或授权永久不可用，进程会持续运行并重试；需人工停止时使用 `Ctrl+C`。

## 方法概览

完整流水线如下：

```text
01 数据预处理
↓
02 数据切分
↓
03 只用 KB_Member 构建 RAG index
↓
04 可选生成 Spoofed_Non_Member
↓
05 构建并 hash 固化 attack benchmark
↓
06 抽取可验证 fact units
↓
07 生成 true/counterfactual paired claims
↓
08 生成 Q+ / Q- paired queries
↓
09 stealth filter 过滤不自然或像攻击的 queries
↓
10 同一批 queries 跑 RAG 和 LLM-only
↓
11 parse stance 并计算 PCV score
↓
12 运行 baselines
↓
13 机制分析
↓
14 防御实验报告骨架
↓
15 生成最终报告
```

主方法只依赖：

```text
fact extraction
paired claim/query construction
RAG inference
RAG-only PVS source scoring
```

LLM-only 仅在独立 matched-control run 中启用，用于判断预训练记忆/上下文增益，不参与主攻击分数。

`Spoofed_Non_Member`、baseline、mechanism analysis 和 defense 都属于实验评估层，不是攻击算法本体。

## 安装

建议环境：

```text
Python >= 3.10
```

安装依赖：

```powershell
pip install -r requirements.txt
```

当前核心依赖：

```text
PyYAML
tqdm
numpy
sentence-transformers
matplotlib
nltk
```

可选加速依赖：

```text
faiss-cpu
```

说明：

- `sentence-transformers` 是当前正式流程的核心依赖。
- `matplotlib` 用于评估结果可视化：`plots.py` 自查仪表盘（ROC / 分数分布 / 信号 AUC / 历次趋势图）与 `paper_figures.py` 论文级单图（导出 PDF 矢量 + 300dpi PNG）；缺失时只警告不出图，不让分析失败。
- `faiss-cpu` 只是检索索引加速依赖；没有 FAISS 时会使用 JSON 向量索引存储。
- 不再支持 hashing embedding 作为实验 fallback。

## LLM 配置

所有 LLM 调用都走 OpenAI-compatible Chat Completions 风格接口。真实密钥不要写入配置文件，使用 `.env` 提供。

`.env` 示例：

```dotenv
# Victim LLM：用于第 10 步 RAG / LLM-only 回答
PCV_VICTIM_API_KEY=your-victim-key
PCV_VICTIM_BASE_URL=https://your-provider/v1
PCV_VICTIM_MODEL=your-victim-model
PCV_VICTIM_PROFILE=openai_api

# Sibling LLM：只在启用 Spoofed_Non_Member 时用于 rewrite / judge
PCV_SIBLING_API_KEY=your-sibling-key
PCV_SIBLING_BASE_URL=https://your-provider/v1
PCV_SIBLING_MODEL=your-sibling-model
PCV_SIBLING_PROFILE=dashscope_qwen

# 可选，对照组开关；默认 false
PCV_ENABLE_SPOOFED_NONMEMBER=false
```

配置优先级（选择哪个 profile）：

```text
CLI --profile > .env 的 PCV_VICTIM_PROFILE / PCV_SIBLING_PROFILE > 脚本配置 > configs/llm_profiles.yaml 的 active
```

`configs/llm_profiles.yaml` 内置两个 profile：

```text
openai_api      OpenAI 官方接口，默认模型 gpt-4.1-mini
dashscope_qwen  阿里云 DashScope OpenAI 兼容接口，默认模型 qwen3-235b-a22b
```

仓库当前默认 victim active 是 `openai_api`，sibling active 是 `dashscope_qwen`。profile 只决定接口风格和 system prompt；真实的 `base_url`、`model`、`api_key` 仍由 `.env` 中的 `PCV_VICTIM_*` / `PCV_SIBLING_*` 覆盖。

第 10 步必须配置 `PCV_VICTIM_*`。第 04 步只有在 `PCV_ENABLE_SPOOFED_NONMEMBER=true` 时才需要 `PCV_SIBLING_*`。

## 数据准备

默认数据配置在：

```text
configs/data_config.yaml
```

当前支持的数据集键：

```text
enron
cuad
edgar
pubmed
```

默认输入路径：

```text
datasets/raw/extracted/enron
datasets/raw/extracted/cuad/CUAD_v1/CUAD_v1.json
datasets/raw/extracted/edgar/raw.jsonl
datasets/raw/extracted/pmc/raw.jsonl
```

预处理阶段会读取本地数据，清洗文本，切成片段，过滤模板文本和缺少可扰动实体的片段，最后写成 JSONL。

当前默认预处理约束：

```yaml
preprocess:
  min_chars: 300
  max_chars: 2000
  target_chars: 1000
  require_entity: true
  require_numeric: false
  min_entities: 2
```

这些约束是为了保证后续能构造 paired claims。如果文本没有具体实体或可验证事实，即使用 RAG 也很难形成稳定的成员推理攻击单元。

## 关键配置

### `configs/data_config.yaml`

控制数据预处理和 split。

关键字段：

```yaml
split:
  seed: 42
  source_exclusive: true
  scale: small
  small:
    KB_Member: 100
    True_Non_Member: 100
    Spoof_Seed: 100
    Reserve: 100
    per_source_cap: 3
  formal:
    KB_Member: 600
    True_Non_Member: 600
    Spoof_Seed: 0
    Reserve: 450
    per_source_cap: 3
```

`source_exclusive: true` 表示同一原始文档的不同 chunk 不会跨 member 和 non-member 分组，避免成员推理实验中的数据污染（近邻泄漏）。

`per_source_cap` 限制每篇**原始文档**对单个组最多贡献的 chunk 数（其余丢弃），用于按「独立文档数」而非 chunk 数控制规模：`source_exclusive` 下若不限制，少数几篇长文档的 chunk 就能填满一组，使"样本数"虚高而**有效独立样本数（= 原始文档数）**仍是个位数（旧 small 每组仅 2–3 篇文档，word_count 等表层特征会因此可分）。例：`formal` 的 `KB_Member: 600 / per_source_cap: 3 ≈ 200 篇独立文档`（edgar 一篇原始文档约切 62 个 chunk）。不写该字段即旧行为（单篇文档可填满整组，向后兼容）。`Spoof_Seed: 0` 表示不生成 Spoof 种子（当前未使用 Spoofed 对照组）。

### `configs/rag_config.yaml`

控制 RAG index、检索和生成。

当前默认：

```yaml
embedding:
  model: sentence-transformers/all-MiniLM-L6-v2
  backend: auto
  dim: 384

chunking:
  chunk_size: 500
  chunk_overlap: 50

retrieval:
  top_k: 5
  query_rewriting: false

generation:
  victim_profile: null
  temperature: 0.0
  max_tokens: 512
  timeout: 60
  retries: 2
  retry_backoff_base: 30
  retry_backoff_max: 300
  retry_until_success: true
  retry_cooldown_seconds: 300
  request_interval_seconds: 20
  # 抗卡顿限速（令牌桶 + 并发）：requests_per_minute > 0 时启用全局令牌桶，
  # 全局速率恒 ≤ 此 RPM，但 max_workers>1 时某条 call 卡住不阻塞其他线程。
  # =0 则回退到 request_interval_seconds 固定间隔（旧行为）。详见「10. 双路推理」提速小节。
  requests_per_minute: 4
  sibling_requests_per_minute: 4
  max_workers: 4
```

`embedding.dim` 保留是为了兼容旧调用；真实维度来自加载到的 sentence-transformers 模型。

### `configs/pcv_attack_config.yaml`

控制 fact extraction、paired claims、paired queries、stealth filter 和 scoring。

当前默认：

```yaml
fact_extraction:
  max_facts_per_doc: 2
  max_entities_per_doc: 8
  min_importance: 0.6
  min_replaceability: 0.6
  min_privacy_specificity: 0.5

paired_claims:
  perturbation_levels: [light]
  max_pairs_per_fact: 1

paired_queries:
  query_types: [compressed_verification]

stealth_filter:
  embedding_model: sentence-transformers/all-MiniLM-L6-v2
  min_naturalness: 0.55
  max_context_probe: 0.5
  max_prompt_injection: 0.5
  min_similarity: 0.03
  max_similarity: 0.97

scoring:
  unknown_lambda: 0.5
  refusal_penalty: 0.5
  false_acceptance_penalty: 0.0   # 2026-06-17：误受惩罚项默认关闭（消融：干净集单项 AUC≈0.525 死重）；设 >0 可恢复
  thresholds: [0.3, 0.5, 0.7, 1.0]
```

### `configs/spoof_config.yaml`

只用于可选的 `Spoofed_Non_Member` 对照组。主方法不依赖这一步。

当前默认：

```yaml
spoof:
  candidates_per_seed: 3
  max_per_seed: 1
  strategies: [formal_rewrite, syntax_restructure, compression, domain_style, neutral_paraphrase]
  thresholds:
    naturalness: 8
    fluency: 8
    semantic_preservation: 8
    entity_preservation: 8
    style_match: 8

statistics:
  embedding_model: sentence-transformers/all-MiniLM-L6-v2
```

启用方式：

```dotenv
PCV_ENABLE_SPOOFED_NONMEMBER=true
```

未启用时，第 04 步直接跳过。

### `configs/experiment_config.yaml`

控制 `scripts/run_pipeline.py` 的默认数据集和阶段开关。

```yaml
default_dataset: enron

pipeline:
  preprocess: true
  split: true
  build_rag_index: true
  generate_spoofed_nonmember: true
  build_attack_benchmark: true
  extract_facts: true
  generate_paired_claims: true
  generate_paired_queries: true
  filter_stealth_queries: true
  run_rag_and_llm_only: true
  parse_stance_and_score: true
  run_baselines: true
  mechanism_analysis: true
  run_defenses: true
  generate_report: true
```

## 快速运行

先看将要执行哪些命令：

```powershell
python scripts/run_pipeline.py --dataset enron --from-step 1 --to-step 15 --dry-run
```

只跑本地准备阶段，不调用 Victim LLM：

```powershell
python scripts/run_pipeline.py --dataset enron --from-step 1 --to-step 9 --force
```

配置好 `PCV_VICTIM_*` 后继续跑 LLM、评分和报告：

```powershell
python scripts/run_pipeline.py --dataset enron --from-step 10 --to-step 15 --force-from-step 11
```

`--force-from-step 11` 会让第 10 步保留成功响应、只补失败/缺失请求，再强制重建 11–15；不要用全局 `--force` 误重查已成功的正式请求。

正式 main run 还需显式运行全部投稿级分析：

```powershell
python scripts/run_pipeline.py --dataset edgar --scale formal --run-id edgar-qwen-formal-seed42 --force-from-step 11 --canonical-analyses
```

`--canonical-analyses` 会追加离线消融、预算/捷径诊断和三个在线 query control，并与主 run 一起归档。matched-control 使用独立 run id、`--run-role matched_control --llm-only`；编排器会只执行第 10 步的 LLM-only 采集，不加载检索器，也不会复制主运行的 RAG 分数、baseline 或报告。只有干净 commit 上生成且通过门禁的 candidate 才能由 `scripts/16_archive_run.py --status canonical --suite-id pcv-mia-paper-v1` 晋升。

只跑核心攻击，不跑 spoof、baseline、defense：

```powershell
python scripts/run_pipeline.py --dataset enron --only-steps 1-3,5-11,15 --force
```

选择 formal split 规模：

```powershell
python scripts/run_pipeline.py --dataset enron --from-step 1 --to-step 5 --scale formal --force
```

只重跑最近修改过 fact extraction / perturbation 后受影响的步骤：

```powershell
python scripts/run_pipeline.py --dataset enron --only-steps 6-13,15 --force
```

## 输出组织：run 归档 / 模型分层 / 论文图

从 `思路v15` 起，产物做了三项工程化改造。

### 每次运行按「开始时间」归档

`run_pipeline.py` 启动时盖一个 run_id（实验开始时间，形如 `20260708-153012`，可加 `--run-name` 标签），广播给所有子步骤共享；跑完把本次全部产物快照进一个自包含文件夹，附 `run_manifest.json`（数据集 / 规模 / 起止时间 / 耗时 / 步骤 / victim / git / 配置 / 命令 / 归档清单）：

```text
outputs/runs/{数据集}/{模型}/{run_id}/
  run_manifest.json
  scores/  rag_responses/  reports/ ...        # 本次各阶段产物拷贝
  figures/                                     # 论文图（见下）
  {数据集}_final_report_{run_id}.png            # 自查仪表盘快照
outputs/runs/{数据集}/{模型}/index.jsonl        # 历次运行速查表 + trend 趋势图
```

阶段目录（如 `outputs/scores/`）仍是「最新工作区」，`--resume` 与「只重跑第 N 步」照旧；run 文件夹是拷贝快照，不影响迭代。`--no-archive` 跳过归档。也可 `python scripts/16_archive_run.py --dataset edgar` 手动补一次快照。

### 模型相关产物按 {数据集}/{模型}/ 分层

**换受害者模型重跑不再互相覆盖。** 第 10–15 步（模型相关）的输出目录，在下文各自列出的 `outputs/<阶段>/` 后**自动插入 `<数据集>/<模型>/` 两级**，例：

```text
outputs/scores/edgar/qwen3.5-397b-a17b/edgar_pcv_scores.jsonl
outputs/reports/edgar/qwen3.5-397b-a17b/edgar_final_report.json
```

涉及 rag_responses / llm_only_responses / parsed_stance / scores / baselines / mechanisms / defenses / reports / runs。第 **01–09** 步（facts / claims / queries，与受害者模型无关）**保持扁平**，`datasets/`、`indexes/` 也不变。

> **模型名来自 `PCV_VICTIM_MODEL`**（如 `qwen/qwen3.5-397b-a17b` → 清洗为 `qwen3.5-397b-a17b`），可由进程环境或项目 `.env` 提供；进程环境优先。未设置时仍会落到 `unspecified/`，canonical 门禁会拒绝该 run。

### 论文级图表

第 15 步跑完会自动产 5 张**论文级单图**（各 `.pdf` 矢量 + `.png` 300dpi）到 run 文件夹的 `figures/`，附 `captions.md`（中英图注，可直接粘 LaTeX `\caption{}`）；也可随时手动刷：

```powershell
python scripts/17_paper_figures.py --dataset edgar --workspace                        # 显式工作区诊断
python scripts/17_paper_figures.py --dataset edgar --workspace --figures roc,signals  # 只出某几张
python scripts/17_paper_figures.py --dataset edgar --suite-id pcv-mia-paper-v1        # 正式 suite 图
python scripts/build_canonical_release.py --suite-id pcv-mia-paper-v1                 # 绑定两数据集全部产物 hash
```

5 张图：`roc`（PCV / cvg_rag / cvg_llm 阴性对照 多曲线 + 工作点）、`separation`（成员 vs 非成员分数小提琴）、`signals`（信号 AUC 柱 + 阴性对照标注）、`baselines`（PCV vs 基线）、`threshold`（TPR/FPR/Acc 随阈值）。未经概率校准的 PVS 不再绘制 reliability/calibration 图。色盲安全配色、每图右上角记录数据集 + 受害者模型。

## 分步命令

以下以 `enron` 为例，其他数据集把 `--dataset enron` 替换为 `cuad`、`edgar` 或 `pubmed`。

### 01. 数据预处理

```powershell
python scripts/01_preprocess_data.py --config configs/data_config.yaml --datasets enron --force
```

输出：

```text
datasets/processed/enron.jsonl
datasets/processed/enron.stats.json
datasets/processed/enron.manifest.json
datasets/processed/enron.errors.jsonl
```

### 02. 数据切分

```powershell
python scripts/02_split_dataset.py --dataset enron --config configs/data_config.yaml --force
```

输出：

```text
datasets/splits/enron/kb_member.jsonl
datasets/splits/enron/true_non_member.jsonl
datasets/splits/enron/spoof_seed.jsonl
datasets/splits/enron/reserve.jsonl
datasets/splits/enron/split_manifest.json
```

只有 `kb_member.jsonl` 允许进入 RAG index。

### 03. 构建 RAG index

```powershell
python scripts/03_build_rag_index.py --dataset enron --config configs/rag_config.yaml --force
```

输出：

```text
indexes/enron/faiss.index
indexes/enron/docstore.jsonl
indexes/enron/index_manifest.json
```

如果安装了 FAISS，`faiss.index` 是 FAISS index；如果没有安装 FAISS，文件中保存 JSON 向量索引。无论哪种方式，embedding 都来自真实 sentence-transformers 模型。

### 04. 可选生成 Spoofed_Non_Member

默认跳过。启用后运行：

```powershell
python scripts/04_generate_spoofed_nonmember.py --dataset enron --config configs/spoof_config.yaml --force
```

输出：

```text
datasets/spoofed/enron/spoofed_non_member.jsonl
datasets/spoofed/enron/spoofed_non_member_scored_candidates.jsonl
datasets/spoofed/enron/spoof_manifest.json
```

这一步需要 `PCV_ENABLE_SPOOFED_NONMEMBER=true` 和 `PCV_SIBLING_*`。

### 05. 构建 attack benchmark

```powershell
python scripts/05_build_attack_benchmark.py --dataset enron --data-config configs/data_config.yaml --force
```

输出：

```text
datasets/benchmarks/enron_attack_benchmark.jsonl
datasets/benchmarks/enron_attack_benchmark.sha256
datasets/benchmarks/enron_benchmark_manifest.json
```

如果 `PCV_ENABLE_SPOOFED_NONMEMBER=false`，benchmark 只包含 `KB_Member` 和 `True_Non_Member`。如果为 true，会额外包含 `Spoofed_Non_Member`。

默认还会纳入 `Reserve` 组作为 L1 群体校准的零分布来源（开关 `PCV_ENABLE_RESERVE_CALIBRATION`，默认 true）；其 `experimental_role` 标为 `calibration_group`，`in_knowledge_base=false`，评估时会被排除。`benchmark_manifest.json` 中以 `num_reserve` 记录其数量。

### 06. 抽取可验证事实

```powershell
python scripts/06_extract_facts.py --dataset enron --config configs/pcv_attack_config.yaml --force
```

输出：

```text
outputs/facts/enron_facts.jsonl
outputs/facts/enron_facts.manifest.json
outputs/facts/enron_facts.errors.jsonl
```

### 07. 生成 paired claims

```powershell
python scripts/07_generate_paired_claims.py --dataset enron --config configs/pcv_attack_config.yaml --force
```

输出：

```text
outputs/paired_claims/enron_paired_claims.jsonl
outputs/paired_claims/enron_paired_claims.manifest.json
outputs/paired_claims/enron_paired_claims.errors.jsonl
```

### 08. 生成 paired queries

```powershell
python scripts/08_generate_paired_queries.py --dataset enron --config configs/pcv_attack_config.yaml --force
```

输出：

```text
outputs/paired_queries/enron_paired_queries.jsonl
outputs/paired_queries/enron_paired_queries.manifest.json
```

### 09. Stealth filter

```powershell
python scripts/09_filter_stealth_queries.py --dataset enron --config configs/pcv_attack_config.yaml --force
```

输出：

```text
outputs/stealth_filtered_queries/enron_paired_queries.jsonl
outputs/stealth_filtered_queries/enron_paired_queries_rejected.jsonl
outputs/stealth_filtered_queries/enron_paired_queries.manifest.json
```

这一步会过滤太像 prompt injection、context probing、membership probing，或者相似度过低/过高的 query。**过滤以 pair 为单位**：Q+ 与 Q- 共进退，对内任一条被拒则整对剔除，保证进入第 10 步的永远是完整配对（否则下游 `score_pair` 会把缺失的一边按 0 计入、扭曲 CVG）。`manifest.json` 额外记录 `accepted_pairs` / `rejected_pairs` / `pair_rejection_rate`。

### 10. RAG 和 LLM-only 双路推理

```powershell
python scripts/10_run_rag_and_llm_only.py --dataset enron --config configs/rag_config.yaml --force
```

默认只运行 RAG，以节省 token。需要论文归因或阴性对照时，显式增加 `--llm-only`；也可以在
`configs/rag_config.yaml` 中将 `generation.run_llm_only` 设为 `true`。

```bash
python scripts/10_run_rag_and_llm_only.py --dataset enron --config configs/rag_config.yaml --llm-only --force
```

直接调用第 10 步时，`--llm-only` 表示在 RAG 路之外增加 matched 响应。内部 `--skip-rag` 只供
`run_pipeline.py --run-role matched_control --llm-only` 使用，用于确保独立对照不触碰 RAG 产物。

长时间调用建议显式缩短写盘间隔。下面的 matched-control 命令每完成一条响应就立即写盘；中断后
重复执行同一命令即可，runner 会压实已有文件、跳过成功项，只补失败、空回答和缺失项：

```powershell
$env:PCV_RUN_ID = "edgar-qwen-formal-seed42-matched"
python scripts/10_run_rag_and_llm_only.py --dataset edgar --config configs/rag_config.yaml --llm-only --skip-rag --checkpoint-every 1
```

`--checkpoint-every` 必须为正整数，默认值为 `200`。设为 `1` 会增加少量磁盘写入，但最适合昂贵、
易中断的 victim API；断点续跑时不要增加 `--force` 或 `--no-resume`。若 API 长期不可用，可以停止
并保留成功响应，但该产物必须标记为 incomplete matched-control，不能通过 canonical 完整性门禁。

输出：

```text
outputs/rag_responses/{dataset}/{model}/{dataset}_rag_responses.jsonl
outputs/rag_responses/{dataset}/{model}/{dataset}_rag_responses.manifest.json
outputs/llm_only_responses/{dataset}/{model}/{dataset}_llm_only_responses.jsonl
outputs/llm_only_responses/{dataset}/{model}/{dataset}_llm_only_responses.manifest.json
```

这一步需要配置 `PCV_VICTIM_*`。

#### 提速（RPM 受限端点）

第 10 步是全流水线唯一密集调用 victim API 的步骤，慢。若你的 key 有每分钟请求上限（如 4 RPM），有两条**不改变任何测量结果**的安全提速：

- **令牌桶 + 并发抗卡顿**（`configs/rag_config.yaml` 的 `requests_per_minute` + `max_workers`）：
  设 `requests_per_minute` = key 的真实 RPM 上限，`max_workers` = 3~4。全局令牌桶保证发送速率恒
  `≤ RPM`（绝不超端点限流），但并发让某条 call 卡住时其他线程仍能发满 RPM——把管道填满。
  并发**不是**为了超过 RPM，而是为了在端点间歇卡顿时**仍能达到** RPM。`requests_per_minute: 0`
  则回退到 `request_interval_seconds` 固定间隔的旧行为。每条查询仍逐条单发，输出与串行**逐字节一致**。
  可用 `scripts/_smoke_token_bucket.py` 在换 key/端点后验证实际吞吐。

- **API 失败不丢样本**（`retry_until_success` + `retry_cooldown_seconds`）：
  每个请求先按 `retries` / `retry_backoff_*` 做短指数退避；若仍是可恢复的 API/网络错误，
  则冷却 300 秒后继续请求同一 prompt，直到得到非空成功回答。该规则同时覆盖 RAG、可选
  LLM-only 与第 12 步 baseline 的 victim/attacker 调用。

- **`--primary-only`**（命令行开关）：只跑 `selection_tier=primary` 的高质量 fact 对应的 query，
  跳过仅作保底的 `fallback` fact，同时砍掉 RAG 与 LLM-only 两路调用数。每条 primary 仍单发、
  答案零改变，`pcv_score_primary` 口径与全量跑**是同一个数**；代价仅是「一条 primary 都抽不出」
  的少数文档退出评估集（对可行性结论无实质影响）。

```powershell
python scripts/10_run_rag_and_llm_only.py --dataset enron --config configs/rag_config.yaml --primary-only --force
```

> **不做 LLM-only 批处理**：曾实现「多条 statement 打包一次请求」以省调用，但真跑诊断证明它会
> 实质改变每条 LLM-only 答案（edgar/qwen3.5-flash 上 stance 一致率仅 55%），污染 `cvg_llm` 负对照，
> 已移除。RAG 路同理永不批（每条检索上下文不同，混批污染 `cvg_rag`）。原则：可行性阶段任何提速都
> 不能改变测量仪器，只能「少测低价值样本」和「在限额内不浪费」。

### 11. 解析 stance 并计算 PCV score

```powershell
python scripts/11_parse_stance_and_score.py --dataset enron --config configs/pcv_attack_config.yaml --force
```

输出：

```text
outputs/parsed_stance/enron_parsed_stance.jsonl
outputs/parsed_stance/enron_parsed_stance.manifest.json
outputs/scores/enron_pcv_scores.jsonl
outputs/scores/enron_pcv_scores_pair_scores.jsonl
outputs/scores/enron_pcv_scores.manifest.json
```

核心分数字段：

```text
cvg_rag
cvg_llm
cg_cvg
pcv_score
pcv_score_primary
```

其中 `pcv_score` 是当前主分：只使用 RAG 的 `Support(Q+) + Correction(Q-)`，先在 chunk 内平均 pair，再对 source 内 chunk 等权平均。`cg_cvg`、质量加权和 primary-only 都只保留为归因/消融口径。

### 12. 运行 baselines

```powershell
python scripts/12_run_baselines.py --dataset enron --config configs/baseline_config.yaml --force
```

输出：

```text
outputs/baselines/{dataset}/{model}/{dataset}_{method}_scores.jsonl
outputs/baselines/{dataset}/{model}/{dataset}_{method}_scores_source_scores.jsonl
outputs/baselines/{dataset}/{model}/{dataset}_baseline_comparison.jsonl
```

5 个 baseline 均已按「方案一」忠实复现（原样移植官方确定性逻辑 + 接缝注入统一 RAG + 差分测试）：

```text
PCV-MIA（本方法）
RAG-MIA      直接询问 yes/no（地板线，二值分→AUC 退化，主看 Accuracy）
S2MIA(s)     切半 + BLEU(原文, 回答)，移植 IA 官方 mia_utils/s2.py（纯黑盒；s&p 困惑度作附录）
MBA          proxy-LM 高难词遮蔽 + 填空填对率，移植 IA 官方 mia_utils/mba.py
IA           summary + 30问 + 同源检索器区分度筛选(代替 ElectraScorer) + 一致率
DCMI         反义词扰动差分（base=BLEU 重叠），对齐官方 perturb.py
```

忠实度审计与实验条件对齐见 `src/baselines/BASELINES.md`；确定性逻辑由 `tests/test_baseline_adapters.py`（差分测试 14/14）背书。IA/DCMI 需 attacker LLM，可加 `--attacker victim` 复用受害模型。

MBA 额外对共享 proxy-LM 的 tokenizer/model 选词阶段加了串行锁，解决真实 GPT-2 在多线程下的 `Already borrowed`；得到攻击 query 后立即释放锁，victim 请求仍可并发。所有 baseline 的可恢复 API 错误与第 10 步一样，会长冷却并持续重试到成功。

### 13. 机制分析

```powershell
python scripts/13_mechanism_analysis.py --dataset enron --force
```

输出：

```text
outputs/mechanisms/enron_mechanism_report.json
```

当前机制分析包括：

```text
Retrieval Exposure Rate
Entity Evidence Rate
True Claim Support Rate
Counterfactual Rejection Rate
Counterfactual Correction Rate
False Acceptance Rate
Entity Evidence Override Rate
Context Gain
Query-Document Similarity
Entity Type Sensitivity
Query Rewriting Robustness
Control Group False Positive Analysis
```

仍待补充的分析：

```text
Nearest-Neighbor Similarity
Top-k Sensitivity
```

### 14. Defense analysis

```powershell
python scripts/14_run_defenses.py --dataset enron --config configs/defense_config.yaml --force
```

输出：

```text
outputs/defenses/enron_defense_results.json
```

当前 defense 是 report 骨架，预留策略包括：

```text
Conflict-aware Non-disclosure
Entity Redaction
Query Similarity Filter
Answer-without-Correction
```

这些策略还没有真正接入第 10 步 RAG generator 前。正式论文实验要报告 defense 数字时，需要接入 policy 后重新跑相关步骤。

### 15. 生成最终报告

```powershell
python scripts/15_generate_report.py --dataset enron --force
```

输出：

```text
outputs/reports/enron_final_report.json
outputs/reports/enron_summary.md
```

主报告的攻击指标（`AUC` / `TPR@1%FPR` / `FPR` 等）只在**排除 `Reserve` 校准组**后的 `KB_Member` 与 `True_Non_Member` 上计算，与 `analyze_feasibility` 口径一致（`Reserve` 是 L1 校准的非成员零分布，不是测试样本）；`score_distributions` 仍保留各组均值（含 `Reserve`）作诊断展示。

可选渲染可读 HTML / Markdown 表格：

```powershell
python scripts/render_report_table.py --input outputs/reports/enron_final_report.json
```

输出：

```text
outputs/reports/enron_report_table.html
outputs/reports/enron_report_table.md
```

## 辅助脚本（不在 01-15 主流水线）

这些脚本读取主流水线产物做诊断/校准，不修改主流水线，也不重跑 LLM。

### 投稿级离线消融与预算曲线

```powershell
python scripts/analyze_p0_ablation.py --dataset edgar --model qwen3.5-397b-a17b --bootstrap 2000 --seed 42
```

输出使用 source-level 评估，在同一 source whitelist 上报告 full PVS、Q+ only、Q- only、
correction only、质量加权和 primary-only。2/4/6/8 次 RAG 调用预算曲线固定使用满足最大预算的
共同 source；每档均包含 AUC 95% bootstrap CI，以及 full PVS 相对其他变体的 source-paired delta。

### Stance parser 人工审计

两个数据集的当前 victim RAG 与 parsed stance 都完整后，生成至少 200 条分层盲标样本：

```powershell
python scripts/stance_audit.py --dataset both --model qwen3.5-397b-a17b --sample-size 200 --seed 42
```

模板按 dataset × group × claim type 分层，并故意隐藏 parser 的 `stance`；人工只填写
`human_stance`，不得修改其他字段。manifest 会冻结样本 whitelist 和 parser prediction hash。
标注完成后计算 accuracy、macro-F1 和混淆矩阵：

```powershell
python scripts/stance_audit.py --dataset both --model qwen3.5-397b-a17b --annotations outputs/diagnostics/stance_audit/qwen3.5-397b-a17b/both_stance_audit_annotations.jsonl --minimum-labeled 200
```

若 Enron 尚未完成，可以先对 Edgar 抽取 100 条；最终仍须补齐 Enron，并保证两个数据集合计至少
200 条后再形成论文审计结论。

### 可行性验证

```powershell
python scripts/analyze_feasibility.py --dataset enron
```

读取第 11 步分数、第 05 步 benchmark、第 02 步 splits，跑三块分析（信号拆解 / shortcut 排捷径 / 同源泄漏检查），在控制台打印方向性判据表，并接入 L1 校准对比（评估时排除 Reserve）。

方向性 go / no-go 五条判据：

```text
判据1：cvg_rag AUC > 0.6                    （检索带来判别力）
判据2：cvg_llm AUC ≤ 0.6                     （阴性对照成立；>0.6 视为 LLM 先验已可分=泄漏）
判据3：cvg_rag − cvg_llm > 0.05              （增益来自检索）
判据4：最强 shortcut 可分性 < cvg_rag − 0.02 （没走文本统计捷径）
判据5：KB 与 True_Non 的 source_key 交集 == 0（无同源泄漏）
```

每次运行会按时间戳归档、不覆盖历次，并出一张综合图：

```text
固定名 latest：     outputs/reports/{dataset}_feasibility.json
带时间戳快照：      outputs/runs/{dataset}/{run_id}/{dataset}_feasibility_{run_id}.json + .png
历次总表（追加）：  outputs/runs/{dataset}/index.jsonl
历次 AUC 趋势图：   outputs/runs/{dataset}/trend_feasibility.png
```

### L2 shadow 校准

见上文「L2 shadow 逐样本校准」章节：

```powershell
python scripts/run_l2_shadow.py --dataset enron --num-shadows 4
```

### 泄漏诊断（临时工具）

```powershell
python scripts/_diag_leakage.py --dataset enron
```

只读现有产物，做 bootstrap 置信区间 + KB/True_Non 两组的 LLM-only/RAG 行为分解 + entity_type/难度/文本统计对比，用于定位"信号是否来自成员性、还是预训练污染等混淆因素"。不调用 API。

## 核心模块

```text
src/data/
  reader.py        读取 Enron / CUAD / EDGAR / PubMed 本地数据
  cleaner.py       数据集特定清洗
  chunker.py       文本切片
  filter.py        实体密度、模板文本、可扰动实体过滤
  preprocess.py    预处理主流程

src/prepare/
  splitter.py          PCV-MIA 四组切分
  benchmark_builder.py 固定 attack benchmark 并保存 hash

src/rag/
  embeddings.py     真实 sentence-transformers embedding；禁用 hashing
  index_builder.py  只用 KB_Member 构建 index（显式 allowed_group="Reserve" 才能建 shadow 索引）
  retriever.py      top-k 检索，支持 FAISS 或 JSON vector store
  runner.py         RAG / LLM-only 双路推理（run_llm_only 开关，shadow 只跑 RAG）
  shadow_runner.py  建 K 个 Reserve-shadow + 跑 RAG，供 L2 per-example 校准

src/attack/
  entity_extractor.py        Attackable Fact Extractor
  perturbation_generator.py  同类型 counterfactual entity 生成

src/fact_extraction/
  fact_extractor.py  从实体候选转成 fact units

src/paired_claims/
  claim_generator.py  true/counterfactual claim 构造

src/query_generation/
  paired_query_builder.py  Q+ / Q- 查询构造（回答格式指令统一由第 10 步 runner 给出）
  stealth_filter.py        stealth query 过滤（按 pair 整体接受/拒绝，Q+/Q- 共进退）

src/parsing/
  stance_parser.py  回答立场解析

src/scoring/
  pcv_scorer.py  CVG、CG-CVG、PCV score
  calibration.py L1 群体校准（经验百分位 / z-score）+ L2 shadow per-example 校准（Φ(z)）

src/spoof/
  generator.py  可选 Spoofed_Non_Member 对照组生成

src/baselines/
  victim_harness.py  5 个 baseline 的统一 RAG/API 执行、重试、聚合与输出接口

src/defenses/
  runner.py  defense policy report 骨架

src/evaluation/
  metrics.py              membership 指标
  feasibility.py          可行性验证（信号拆解 / shortcut / 同源泄漏 + 五判据）
  mechanism_analysis.py   机制分析
  plots.py                评估结果可视化（ROC / 分数分布 / 信号 AUC / 趋势图）
  report_builder.py       最终报告

src/llm/
  openai_compatible.py  OpenAI-compatible client
  sibling_client.py     spoof 生成 / judge
  victim_client.py      RAG 和 LLM-only 被测模型
  factory.py            profile 解析和 client 构造
```

## Attackable Fact Extractor

第 06 步的实体抽取已经从旧的线性规则抽取升级成 `Attackable Fact Extractor`。

旧逻辑大致是：

```text
regex 抽实体 -> 固定分数 -> 阈值过滤 -> top-k
```

当前逻辑是：

```text
candidate generation
↓
candidate normalization / merge
↓
sentence-level context analysis
↓
attackability dynamic scoring
↓
hard gates
↓
diversity selection
```

### 实体 family

当前实体类型按 family 管理：

```text
identifier:
  URL, EMAIL, PHONE, SECTION_ID, IDENTIFIER

structured_numeric:
  MONEY, MEDICAL_VALUE, PERCENT, NUMERIC_VALUE

date_time:
  DATE, TIME, DURATION

domain_term:
  CONTRACT_TERM, PRODUCT, PROJECT_NAME

named_entity:
  ORG, LOCATION, PERSON
```

这种设计不是给 Enron 写特化规则，而是把不同数据集中的可验证事实锚点统一到几类跨数据集实体中。

### NER 接口

`EntityExtractor` 支持可选注入 NER 模型：

```python
EntityExtractor(ner_model=...)
```

支持 spaCy 风格对象和 HuggingFace pipeline 风格 dict。NER 输出只作为 candidate source，不直接决定最终 fact 是否入选。最终选择仍然由句子质量、attackability score 和 family diversity 决定。

当前默认流程没有自动加载 NER，也没有新增 NER 依赖。

### attackability score

当前动态分数考虑：

```text
base type score
context_quality
specificity
replaceability
retrieval_anchor_strength
parser_friendliness
source_agreement
NER confidence bonus
generic_penalty
```

输出仍保留旧字段：

```text
importance
replaceability
privacy_specificity
```

同时在 `entity_metadata` 中保留：

```text
entity_family
attackability_score
specificity
context_quality
retrieval_anchor_strength
parser_friendliness
generic_penalty
context_reasons
candidate_sources
selection_reason
extractor_version
```

### diversity selection

默认 family quota：

```text
structured_numeric: 2
date_time: 1
identifier: 1
named_entity: 1
domain_term: 1
```

这样可以避免某一类实体，例如 PERSON 或 ORG，占满每篇文档的所有 fact。

## Paired Claims 和扰动规则

第 07 步只替换 fact 中的 `object_entity` 一次，生成同类型 counterfactual。

当前支持的扰动类型包括：

```text
MONEY / MEDICAL_VALUE / NUMERIC_VALUE
PERCENT
DATE
TIME
DURATION
EMAIL
URL
PHONE
SECTION_ID
IDENTIFIER
CONTRACT_TERM
LOCATION
PERSON
ORG
PRODUCT
PROJECT_NAME
```

示例：

```text
48,720 USD -> 51,156 USD
March 12, 2022 -> March 15, 2022
3:30 PM -> 4:00 PM
30 days -> 38 days
support@example.com -> alternate.contact@example.com
https://example.com/report -> https://example.com/report/archive
Section 5.2 -> Section 5.3
Contract ABC-1234 -> Contract ABC-1241
212-555-0100 -> 212-555-0129
Project Atlas -> Project Beacon
Atlas Platform -> Beacon System
```

如果某个实体类型没有专门规则，最后才会走保底 fallback：

```text
value + " revised"
```

当前常见实体类型已经尽量避免落到这个 fallback。

## Scoring

PCV-MIA 的核心分数来自 `src/scoring/pcv_scorer.py`。

对 Q+：

```text
supports_true_claim -> +1
rejects_true_claim -> -1
says_unknown -> -unknown_lambda
refuses -> -refusal_penalty
unrelated -> 0
```

对 Q-：

```text
corrects_to_original_entity -> +1
rejects_counterfactual -> +0.5
accepts_counterfactual -> -1
says_unknown -> -unknown_lambda
refuses -> -refusal_penalty
unrelated -> 0
```

pair-level 公式：

```text
CVG = SupportScore(Q+) + CorrectionScore(Q-) - FalseAcceptancePenalty(Q-)
      # 2026-06-17：误受惩罚项默认关闭（false_acceptance_penalty=0），消融证其单项 AUC≈0.525 是死重；
      # 故当前默认 CVG = SupportScore(Q+) + CorrectionScore(Q-)；config 设 >0 可恢复（污染集或有用）。
CG-CVG = CVG_RAG - CVG_LLM
```

文档级分数：

```text
PVS_pair = Support_RAG(Q+) + Correction_RAG(Q-)
PVS_chunk = mean(PVS_pair within chunk)
pcv_score(source) = mean(PVS_chunk within source)
cg_cvg = PVS_RAG - PVS_LLM                 # 归因诊断
pcv_score_context_gain_weighted            # 质量加权诊断
```

当前代码中：

```text
pcv_score 始终是 RAG-only、pair→chunk→source 的不加权分层主分。
predicted_member_t* 这类阈值字段按 pcv_score 判定。
```

## L1 群体校准（Reserve 零分布）

`cg_cvg = cvg_rag - cvg_llm` 是一个朴素的 per-example 校准（用样本自己的 LLM-only 分减去先验），有三个统计缺陷：

- **零点估错**：即便 x 非成员，RAG 也可能检索到语义近邻的成员文档，把 `cvg_rag` 抬高，所以非成员的 `cg_cvg` 期望并非 0。
- **未校准方差**：不同文档的 `cg_cvg` 在非成员世界下波动幅度不同，全局阈值对高方差样本不公平。
- **只是点估计**：`A − B` 没有统计语义，不是假设检验。

L1 群体校准（`src/scoring/calibration.py`）用 `Reserve` 组当"非成员零分布"修正这三点：

- `Reserve` 同分布、非成员、与评估组（`KB_Member` / `True_Non_Member`）source 互斥；从第 05 步起纳入 benchmark，随主流水线 06→11 跑出 `cvg_rag`。
- 对每个待测样本，按它的 `cvg_rag` 在 Reserve 分布中的位置算两种校准分（都写回每行）：
  - `pcv_score_calibrated_z`：z-score = `(cvg_rag − μ_reserve) / σ_reserve`；**默认主校准分**（`PRIMARY_CALIBRATED_KEY`，2026-06-17 由经验百分位改来）。严格单调保序，AUC/TPR 恒等 `cvg_rag`、低 FPR 不坍缩，且无量纲可跨集比较。
  - `pcv_score_calibrated`：历史字段名，Reserve-calibrated `cvg_rag` 经验百分位（mid-rank 处理 ties），取值 [0,1]；降为**辅助分**——它是阶梯函数，超 Reserve 上界的样本并列封顶 1.0（顶端坍缩），会压低 AUC、且低 FPR 区常取不到阈值（TPR@1%FPR=n/a）。
- **评估指标必须排除 Reserve**：它是校准料不是测试样本。`analyze_feasibility` 与第 15 步主报告 `generate_final_report` 在算 AUC / TPR / FPR 前均已剔除 Reserve——校准用 Reserve、评估排除 Reserve，两者零重叠。

`scripts/analyze_feasibility.py` 的 `[1.5]` 段并排打印四档终分（`cvg_rag` / z-score / 经验百分位 / `cg_cvg`）的 `AUC / Accuracy / TPR@1%FPR / TPR@5%FPR`；`[1.6]` 段输出**阈值-指标关系表**（固定 `cvg_rag`，扫所有判定阈值给 FPR/TPR/Accuracy，标注 ≤1%/≤5%FPR 区，并给全局 AUC/Accuracy/TPR@1%·5%FPR；report json 亦存 `threshold_table`）。校准收益主要落在低 FPR 区，**重点看 TPR@1%FPR**。Reserve 经 06–09 筛选后有效样本可能偏少，零分布不稳时可调大 `configs/data_config.yaml` 的 `Reserve` 目标。

> LLM-only 可视为"空 KB shadow"的极端特例，因此 `cg_cvg` 是本校准框架在"参考只有一个、且为空索引"时的退化版本；`cg_cvg` 与 `pcv_score` 并存便于对比：前者是不加权诊断口径，后者是质量加权主分。

## L2 shadow 逐样本校准（per-example，offline LiRA）

L1 的 **z-score** 是对 `cvg_rag` 的**严格单调线性变换**：AUC/TPR@FPR 恒等于 `cvg_rag`（实测 small 0.936、edgar 0.954）。**注意经验百分位不是严格单调**——它是阶梯函数会"顶端坍缩"（超 Reserve 上界的样本并列封顶 1.0），实测 edgar AUC 0.954→0.919、TPR@1%FPR 由 0.815 变 n/a；这正是 2026-06-17 把 L1 主分由百分位改成 z-score 的原因。L1（无论哪种）能做标定、甩 `cvg_llm` 噪声、改善低 FPR 区，但**扣不掉 per-example 先验泄漏**——即"某个样本的事实本身先验可验证性就更高"这种逐样本偏差。

放大样本（small→formal）后诊断出：enron 上 `cvg_llm AUC=0.606 CI[0.542,0.672]`，下界 > 0.5，说明 victim 模型在无检索时也能部分区分两组（enron 是公开数据集，几乎肯定被预训练见过）。这种先验不在任何可观测表层特征里（类型/难度/文本统计两组均衡），难度回归式的捷径抓不到，只能用 shadow 直接估。

L2（`src/scoring/calibration.py` 的 `calibrate_l2_shadow`，入口 `src/rag/shadow_runner.py`）对每个评估目标 x 估计它**自己的**非成员零分布：

```text
1. 从 Reserve 采 K 个子集，各建一个 shadow RAG 索引（纯 embedding、不花 API）。
   Reserve 与所有评估目标 source 互斥，故 K 个 shadow 对全体目标天然都是 OUT 世界，
   全体目标共享（成本 = K 倍而非 N×K）。
2. 评估 query 在每个 shadow 上只跑 RAG（LLM-only 与索引无关、复用主 run，省 K 倍调用）。
3. 同一目标 x 在 K 个 shadow 上的 cvg_rag 即其 OUT 分布 (μ_out(x), σ_out(x))。
4. per-example 标准化：z(x) = (cvg_rag_victim(x) − μ_out(x)) / σ_out(x)
   L2 分 = Φ(z) ∈[0,1]（单边，越高越像成员）；σ_out 退化时用全体中位数兜底。
```

写回每行的字段：`pcv_score_l2`（= Φ(z)，主 L2 分）、`pcv_score_l2_z`、`l2_mu_out`、`l2_sigma_out`、`l2_n_shadows`。

PCV-MIA 做 L2 的天然优势（论文卖点）：传统 MIA 做 LiRA 要训几百个 shadow model，而这里"模型"是 RAG 索引，建 shadow 只是 re-embed + 重建索引（秒级、近免费），所以负担得起 per-example 校准。

运行（辅助脚本，不在 01-15 主流水线）：

```powershell
python scripts/run_l2_shadow.py --dataset enron --num-shadows 4
```

成本 = 对评估 query 跑 K 遍 RAG（LLM-only 复用主 run，不重跑），强烈建议 resume。脚本会打印 `cg_cvg` / L1 / L2 三方 AUC 对比与阴性对照。go/no-go：L2 分应使 True_Non 的 Φ(z)≈0.5（先验扣净）、KB→1，且 AUC 超过 `cg_cvg`。当前状态：代码完成、离线单元测试通过（扣先验机制已验证），真实 K-shadow 运行待跑。

## 指标

最终报告中的主指标包括：

```text
AUC
Accuracy
Precision
Recall
TPR@1%FPR
TPR@5%FPR
FPR-True_Non_Member
FPR-Spoofed_Non_Member
Detection Rate
threshold_curve
```

MIA 场景里建议重点看：

```text
TPR@1%FPR
TPR@5%FPR
FPR-True_Non_Member
FPR-Spoofed_Non_Member
```

accuracy 不是最关键指标，因为低误报场景更接近成员推理攻击论文的评估要求。

## 断点续跑与重跑建议

多数脚本支持：

```text
--force
--no-resume
```

默认行为是：如果输出文件和 manifest 已存在，脚本会跳过已有结果。正式实验中，修改了配置或代码后应使用 `--force` 重跑受影响阶段，避免新旧 artifacts 混用。

常见重跑范围：

### 修改 fact extraction 或 entity perturbation

至少重跑：

```text
06_extract_facts
07_generate_paired_claims
08_generate_paired_queries
09_filter_stealth_queries
10_run_rag_and_llm_only
11_parse_stance_and_score
12_run_baselines
13_mechanism_analysis
15_generate_report
```

命令：

```powershell
python scripts/run_pipeline.py --dataset enron --only-steps 6-13,15 --force
```

### 修改 embedding 或 retrieval

至少重跑：

```text
03_build_rag_index
09_filter_stealth_queries
10_run_rag_and_llm_only
11_parse_stance_and_score
12_run_baselines
13_mechanism_analysis
15_generate_report
```

命令：

```powershell
python scripts/run_pipeline.py --dataset enron --only-steps 3,9-13,15 --force
```

### 修改 split 或 benchmark

从对应更早阶段重跑。不要把新 split 和旧 benchmark 混用，也不要手动改 benchmark 后继续使用旧 `.sha256`。

## 验证

运行单元测试：

```powershell
python -B -m unittest discover -s tests
```

语法检查：

```powershell
python -m compileall src scripts tests
```

如果 Windows 上已有 `__pycache__` 权限异常，可以使用不写 `.pyc` 的内存编译：

```powershell
@'
from pathlib import Path
for root in ["src", "scripts", "tests"]:
    for path in Path(root).rglob("*.py"):
        source = path.read_text(encoding="utf-8-sig")
        compile(source, str(path), "exec")
print("syntax ok")
'@ | python -
```

## 常见问题

### 1. 第 03 或第 09 步加载 embedding 失败

当前代码不再 fallback 到 hashing。请确认：

```text
sentence-transformers 已安装
模型名可用
本地网络或模型缓存可用
configs/rag_config.yaml 和 configs/pcv_attack_config.yaml 没有写 hashing
```

可以先测试：

```powershell
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); print('ok')"
```

### 2. 显式配置 hashing 后报错

这是预期行为。`hashing` 已禁用，因为它会改变检索语义，污染 Retrieval Exposure 和 AUC 的解释。

### 3. 第 04 步没有生成 Spoofed_Non_Member

默认就是跳过。启用方式：

```dotenv
PCV_ENABLE_SPOOFED_NONMEMBER=true
```

同时需要配置：

```dotenv
PCV_SIBLING_API_KEY=...
PCV_SIBLING_BASE_URL=...
PCV_SIBLING_MODEL=...
```

### 4. 第 10 步提示 API key 未设置

第 10 步使用 Victim LLM，必须配置：

```dotenv
PCV_VICTIM_API_KEY=...
PCV_VICTIM_BASE_URL=...
PCV_VICTIM_MODEL=...
```

### 5. 换了模型但结果没有变化

自 `思路v15` 起模型相关产物按 `{数据集}/{模型}/` 分层，换模型**不会覆盖**旧模型结果——新模型写到新目录。检查：

```text
是否 export 了 PCV_VICTIM_MODEL（没设的话不同模型都落到 unspecified/，才会"看起来没变"）
是否在看新模型的目录：outputs/scores/{数据集}/{模型}/、outputs/reports/{数据集}/{模型}/
是否运行时用了 --force
configs/rag_config.yaml 的 generation / retrieval 是否符合当前实验
```

### 6. 新增实体类型后 paired claims 质量不好

检查 `src/attack/perturbation_generator.py` 是否为该实体类型提供了同类型扰动规则。否则会落到通用 fallback。

### 7. NER 是否已经默认启用

没有。当前只是接口可用，默认流程没有加载 NER 模型。正式实验如果要启用 NER，需要明确接入模型、记录模型名、阈值和 ablation。

### 8. baseline 和 defense 是否都已经完整实现

baseline：5 个（RAG-MIA / S2MIA / MBA / IA / DCMI）均已按「方案一」忠实复现——移植官方确定性逻辑 + 接缝注入统一 RAG，差分测试 14/14 背书，见 `src/baselines/BASELINES.md`。注：S2/MBA 移植自第三方复现（原论文无官方码）、DCMI 的 base 为 BLEU 重叠近似（官方 base 未完整开源），均已诚实标注。defense 目前仍是 policy report 骨架。

## 安全与复现注意事项

- 不要提交 `.env`、API key、私有数据集或大型生成产物。
- `configs/llm_profiles.yaml` 只保存环境变量名和非敏感默认配置，不写真实密钥。
- RAG 知识库只能由 `KB_Member` 构建。
- `True_Non_Member`、`Spoof_Seed`、`Reserve`、`Spoofed_Non_Member` 不能进入 index（`Reserve` 仅进 benchmark 当校准组，且评估时排除）。
- attack benchmark 会保存 `.sha256`，不要手动修改后继续复用旧 hash。
- 修改 fact extraction、query generation、retrieval、generation 或 scoring 后，应从受影响阶段重跑。
- 正式报告前检查各 manifest 的 `created_at`、`config_snapshot`、`config_hash`，避免新旧 artifacts 混用。

## 研究记录

仓库 `研究记录/` 目录下的 `思路v2.txt`~`思路v18.txt`、`baseline.txt`、`分类器.txt`、`实验v1.txt` 是研究记录，不是运行入口（该目录默认不入库）。当前思路文档以增量方式叠加，权威性以最新为准：

- `思路v18` 记录 2026-07-13 baseline 复现就绪审计、MBA 并发修复、IA/DCMI 失败放大原因，以及 PCV-MIA/全 baseline 的 API 长冷却无限重试决策。
- `思路v17` 固定 LLM-only 默认关闭与 P1 完整性基础设施修复。
- `思路v16` 是当前最新协议增量：P0 固定 RAG-only 主攻击、source-level 评估、conformal 校准与 canonical run/suite；P1 负责修通实验基础设施。若该文件未纳入仓库，请以当前 README 与代码中的 `P0_PROTOCOL` 为准。
- [思路v15.txt](研究记录/思路v15.txt) 是上一版工程化增量文档（run 归档、论文图、模型相关产物分层）。
- [思路v11.txt](研究记录/思路v11.txt) 是终分层精炼（L1 主分→z-score、去误受项、per-term 去偏对照、门控否决、阈值-指标关系表 + Accuracy 输出；全程离线消融裁决，含两个被数据否决的方向）。
- [思路v10.txt](思路v10.txt) 是 v9 的增量（方案 D 抽事实保底覆盖 + 质量加权三口径 + 句子定位 bug 修复；附录"同日第二批"：07/08/09 加固 + 第 15 步主报告排除 Reserve + 死兜底清理）。
- [思路v9.txt](思路v9.txt) 是 v8 的增量（L1 群体校准 + 预训练污染诊断 + L2 shadow 逐样本校准）。
- [思路v8.txt](思路v8.txt) 是 v7 的增量（prompt 对称化 + 可行性验证 + 输出归档/可视化）。
- [思路v7.txt](思路v7.txt) 是主流水线本体（01-15 顺序、数据隔离、事实抽取、打分公式）的详细说明。
- 新旧说法冲突时，以 `思路v16` + 当前 README + 当前代码为准；旧版中的 context-gain 主分、chunk-level 主评估与历史数值仅作研究过程记录。
- **当前阶段定位 = 可行性验证**（确认信号是否来自成员性，而非 prompt 不对称 / 文本捷径 / 同源泄漏 / 模型先验），非冲顶会的完整实验。
- v9 关键诊断：enron 在 formal 上 `cvg_llm AUC=0.606`（阴性对照失败），根因是 enron 公开数据集被 victim 预训练污染；扣先验后 `cg_cvg AUC=0.772 CI[0.716,0.828]` 仍显著，攻击未失效，但污染数据上应主报扣先验终分或用 L2。
- `实验v1.txt` 记录首次 Enron 端到端实验结果（AUC ≈ 0.77）。
- `分类器.txt` 是关于 MIA 元分类器方向的调研笔记；其中提到的 `GradientBoostingClassifier` 等分类器属于后续设想，当前代码尚未引入，主方法仍是 CG-CVG 阈值判定。

README 是面向运行和复现的操作文档，应与 `思路v9.txt` / `思路v10.txt` 和代码同步更新。
