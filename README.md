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

PCV-MIA 的做法是：从候选文档里抽取可验证事实，构造真实 claim 和最小同类型反事实 claim，再生成 Q+ / Q- 查询；同一批查询分别运行 `RAG` 和 `LLM-only`。如果 RAG 比 LLM-only 更能支持真实事实、否定反事实并纠正原实体，则这个差异更可能来自 RAG 知识库中的成员文档。

一句话概括当前代码：

```text
KB isolation
+ attackable fact extraction
+ paired counterfactual verification
+ RAG vs LLM-only context gain
= document-level membership score
```

## 当前状态

当前仓库实现的是 PCV-MIA 主流程和实验评估框架。需要特别注意以下几点：

- RAG index 只能由 `KB_Member` 构建，代码中有硬检查。
- `True_Non_Member`、`Spoof_Seed`、`Reserve`、`Spoofed_Non_Member` 都不能进入 `indexes/`。
- hashing embedding fallback 已经移除，当前默认使用真实 `sentence-transformers/all-MiniLM-L6-v2`。
- 如果显式配置 `hashing` 或 `backend: hashing`，代码会直接报错。
- 没有安装或无法加载 `sentence-transformers` 模型时，流程会失败，而不是静默换成 fallback。
- `json_vector_fallback` 只是在没有 FAISS 时保存真实 embedding 向量的索引存储 fallback，不是 hashing embedding。
- `Spoofed_Non_Member` 是可选 hard negative 对照组，不是 PCV-MIA 主方法必需部分。
- 当前 NER 只是 `EntityExtractor` 的可注入候选源接口，默认没有自动加载 NER 模型。
- 部分 baseline 和 defense 是 reserved interface，不能当成已完成论文实验结果。

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
RAG / LLM-only dual inference
CG-CVG scoring
```

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
```

可选加速依赖：

```text
faiss-cpu
```

说明：

- `sentence-transformers` 是当前正式流程的核心依赖。
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
PCV_SIBLING_PROFILE=openai_api

# 可选，对照组开关；默认 false
PCV_ENABLE_SPOOFED_NONMEMBER=false
```

配置优先级：

```text
CLI profile > .env 中的 PCV_* 变量 > configs/llm_profiles.yaml 默认值
```

当前主要 profile：

```text
openai_api
```

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
    Spoof_Seed: 500
    Reserve: 200
  formal:
    KB_Member: 3000
    True_Non_Member: 3000
    Spoof_Seed: 3000
    Reserve: 1000
```

`source_exclusive: true` 表示同一原始文档的不同 chunk 不会跨 member 和 non-member 分组，避免成员推理实验中的数据污染。

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
  request_interval_seconds: 1
  max_workers: 1
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
  false_acceptance_penalty: 1.0
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
python scripts/run_pipeline.py --dataset enron --from-step 10 --to-step 15 --force
```

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

这一步会过滤太像 prompt injection、context probing、membership probing，或者相似度过低/过高的 query。

### 10. RAG 和 LLM-only 双路推理

```powershell
python scripts/10_run_rag_and_llm_only.py --dataset enron --config configs/rag_config.yaml --force
```

输出：

```text
outputs/rag_responses/enron_rag_responses.jsonl
outputs/rag_responses/enron_rag_responses.manifest.json
outputs/llm_only_responses/enron_llm_only_responses.jsonl
outputs/llm_only_responses/enron_llm_only_responses.manifest.json
```

这一步需要配置 `PCV_VICTIM_*`。

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
```

### 12. 运行 baselines

```powershell
python scripts/12_run_baselines.py --dataset enron --config configs/baseline_config.yaml --force
```

输出：

```text
outputs/baselines/enron_baseline_results.jsonl
outputs/baselines/enron_baseline_results.manifest.json
```

当前已实现的 baseline：

```text
PCV-MIA new version
Direct RAG-MIA
IA / Interrogation Attack
```

当前只是 reserved interface 的 baseline：

```text
S2MIA
MBA
RAG-leaks / difficulty-calibrated similarity baseline
E-MIA / exam-style QA baseline
```

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

可选渲染可读 HTML / Markdown 表格：

```powershell
python scripts/render_report_table.py --input outputs/reports/enron_final_report.json
```

输出：

```text
outputs/reports/enron_report_table.html
outputs/reports/enron_report_table.md
```

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
  index_builder.py  只用 KB_Member 构建 index
  retriever.py      top-k 检索，支持 FAISS 或 JSON vector store
  runner.py         RAG / LLM-only 双路推理

src/attack/
  entity_extractor.py        Attackable Fact Extractor
  perturbation_generator.py  同类型 counterfactual entity 生成

src/fact_extraction/
  fact_extractor.py  从实体候选转成 fact units

src/paired_claims/
  claim_generator.py  true/counterfactual claim 构造

src/query_generation/
  paired_query_builder.py  Q+ / Q- 查询构造
  stealth_filter.py        stealth query 过滤

src/parsing/
  stance_parser.py  回答立场解析

src/scoring/
  pcv_scorer.py  CVG、CG-CVG、PCV score

src/spoof/
  generator.py  可选 Spoofed_Non_Member 对照组生成

src/baselines/
  runner.py  baseline 统一输出接口

src/defenses/
  runner.py  defense policy report 骨架

src/evaluation/
  metrics.py              membership 指标
  mechanism_analysis.py   机制分析
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
CG-CVG = CVG_RAG - CVG_LLM
```

文档级分数：

```text
PCV_SCORE(x) = average(CG-CVG over all fact pairs from document x)
```

当前代码中：

```text
pcv_score = cg_cvg
```

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

检查：

```text
是否真的修改了 .env 中的 PCV_VICTIM_MODEL
是否运行时用了 --force
outputs/rag_responses/ 和 outputs/llm_only_responses/ 是否仍是旧文件
configs/rag_config.yaml 的 generation / retrieval 是否符合当前实验
```

### 6. 新增实体类型后 paired claims 质量不好

检查 `src/attack/perturbation_generator.py` 是否为该实体类型提供了同类型扰动规则。否则会落到通用 fallback。

### 7. NER 是否已经默认启用

没有。当前只是接口可用，默认流程没有加载 NER 模型。正式实验如果要启用 NER，需要明确接入模型、记录模型名、阈值和 ablation。

### 8. baseline 和 defense 是否都已经完整实现

没有。当前 baseline 只有部分可由现有中间结果计算；defense 目前是 policy report 骨架。正式论文结果需要区分 implemented 和 reserved interface。

## 安全与复现注意事项

- 不要提交 `.env`、API key、私有数据集或大型生成产物。
- `configs/llm_profiles.yaml` 只保存环境变量名和非敏感默认配置，不写真实密钥。
- RAG 知识库只能由 `KB_Member` 构建。
- `True_Non_Member`、`Spoof_Seed`、`Reserve`、`Spoofed_Non_Member` 不能进入 index。
- attack benchmark 会保存 `.sha256`，不要手动修改后继续复用旧 hash。
- 修改 fact extraction、query generation、retrieval、generation 或 scoring 后，应从受影响阶段重跑。
- 正式报告前检查各 manifest 的 `created_at`、`config_snapshot`、`config_hash`，避免新旧 artifacts 混用。

## 研究记录

仓库根目录下的 `思路v*.txt`、`baseline.txt`、`thesislogic.txt` 是研究记录，不是运行入口。

其中 [思路v7.txt](思路v7.txt) 是当前代码思路的详细说明，README 是面向运行和复现的操作文档。两者都应以后续代码变更同步更新。
