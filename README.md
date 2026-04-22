# Robust MIA Auditor

当前仓库实现的是一套三阶段流程：

1. 从本地隐私数据集中划分真实成员、真实非成员、伪造源文本。
2. 用 LLM 将部分真实非成员改写为“逼近成员分布”的伪造非成员，并用受害模型成员概率进行阈值筛选与迭代重生成。
3. 提取基于 loss 的审计特征，训练 GBDT 元分类器，对文本执行成员推理。



## 当前方案

### 阶段一：数据准备与伪造非成员生成

对每个数据集执行以下构造：

- `true_members`：用于微调 victim 的真实成员样本
- `true_non_members`：真实非成员样本
- `spoof_source_pool`：从真实非成员中抽出的伪造源文本

伪造流程：

1. 使用 LLM 将源文本重写为低熵、高平滑度的同义文本。
2. 将候选文本送入受害模型，利用 loss 校准后的成员概率进行筛选。
3. 若成员概率未达到用户显式指定的 `spoof_threshold`，则结合：
   - 原始源文本
   - 上一轮失败伪造文本
   - 上一轮成员概率
   - “更接近成员分布”的指令
   继续重生成。
4. 若最终伪造样本数量不足，则同步裁剪真实成员与真实非成员，保证三类数据硬平衡。

### 阶段二：多维探测与特征提取

当前实现提取 3 维核心特征：

```text
[
  Loss_vic,
  Loss_vic / Loss_base,
  Loss_vic / Mean(Loss_vic(N(X)))
]
```

含义如下：

- `Loss_vic`：受害模型对样本的绝对记忆程度
- `Loss_vic / Loss_base`：相对记忆特征，近似 LiRA 思路
- `Loss_vic / Mean(Loss_vic(N(X)))`：受害模型局部邻域平滑度

其中邻域 `N(X)` 由 LLM 生成若干语义保持的同义改写。

## 默认实验参数

当前默认值已经调整为更适合论文实验的设置：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `neighbor_count` | `8` | 提高邻域平滑度估计稳定性 |
| `victim_ratio` | `0.3333` | 让成员、真实非成员、伪造源三方更接近平衡 |
| `spoof_ratio` | `0.5` | 将剩余非成员一半用于伪造源、一半保留为真实非成员 |
| `max_samples_per_dataset` | `300` | 比原先更适合论文实验统计 |
| `max_spoof_per_dataset` | `100` | 与 `victim_ratio=1/3` 配合形成更均衡构造 |
| `max_spoof_attempts` | `6` | 给高难伪造样本更多逼近空间 |
| `max_spoof_rounds` | `600` | 避免全局重生成预算过早耗尽 |
| `victim_epochs` | `2` | 比 1 轮更稳定，但仍保持可训练成本 |

推荐论文实验时使用：

- `spoof_threshold=0.80`
- `neighbor_count=8`
- `max_samples_per_dataset=300`
- `max_spoof_per_dataset=100`

### 阶段三：审计器训练与推断

- 使用严格平衡后的三类样本构建训练集
- 用 GBDT 训练成员推理审计器
- 输出指标：
  - `roc_auc`
  - `tpr_at_1pct_fpr`
  - `tpr_at_01pct_fpr`
  - `accuracy`
  - `precision`
  - `recall`
  - `f1`

## 目录结构

```text
mia_model/
├── main.py
├── requirements.txt
├── 思路改动v1.txt
├── dataset/
├── models/
├── output/
└── src/
    ├── __init__.py
    ├── attack_model.py
    ├── audit_data.py
    ├── data_prep.py
    ├── llm_client.py
    ├── neighborhood_probe.py
    ├── pipeline.py
    ├── reference_model.py
    ├── utils.py
    └── victim_model.py
```

## 核心文件

- `main.py`
  CLI 入口，提供 `train` 和 `infer` 两个命令。
- `src/pipeline.py`
  训练与推断主流程编排。
- `src/audit_data.py`
  三类样本构造、伪造非成员重生成、平衡约束与统计汇总。
- `src/attack_model.py`
  特征提取器与 GBDT 审计器。
- `src/victim_model.py`
  victim/reference 生成模型封装，以及基于 loss 的成员概率校准器。
- `src/neighborhood_probe.py`
  LLM 邻域探针。
- `src/data_prep.py`
  本地数据集加载与数据集元信息。

## 数据集

仓库当前默认使用以下本地数据集：

| 数据集 | Hugging Face 来源 | 领域 |
| --- | --- | --- |
| `pubmed_papers` | `ccdv/pubmed-summarization` | 医疗 |
| `us_congressional_bills` | `FiscalNote/billsum` | 法律 |
| `enron_emails` | `aeslc` | 企业邮件 |

当前代码只从本地读取数据集，不会自动联网下载。

也就是说，以下目录必须在运行前已经存在：

- `dataset/pubmed_papers`
- `dataset/us_congressional_bills`
- `dataset/enron_emails`

## 环境准备

### 1. Python

推荐 Python `3.10`。

### 2. 安装 PyTorch

`requirements.txt` 不直接安装 `torch`。请先按你的 CUDA 环境安装 PyTorch，例如：

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

CPU 环境可按 PyTorch 官方说明安装对应版本。

### 2.1 默认受害模型

当前默认受害模型与参考模型都已经切换为仓库内的本地模型目录：

- `models/qwen`

也就是说，不额外传参时：

- `victim` 从 `models/qwen` 初始化，然后在成员样本上微调
- `reference` 也从 `models/qwen` 初始化，但不做微调，作为基线模型

如果你想临时改回其他模型，也可以显式传：

```bash
python main.py train ^
  --victim-model-name some_other_model ^
  --reference-model-name some_other_reference ^
  --spoof-threshold 0.80
```

如果你后续要频繁切换实验模型，推荐使用本地模型配置脚本：

```bash
python scripts/set_model_config.py ^
  --victim-model models/qwen ^
  --reference-model models/qwen
```

查看当前默认模型：

```bash
python scripts/set_model_config.py --show
```

清空本地模型默认配置：

```bash
python scripts/set_model_config.py --clear
```

脚本会把配置写入：

```text
config/model_config.json
```

模型默认值读取优先级是：

```text
命令行参数 > config/model_config.json > 代码内置默认值
```

### 3. 安装项目依赖

```bash
pip install -r requirements.txt
```

## LLM API 配置

当前实现依赖 OpenAI 兼容接口，用于：

- 生成伪造非成员
- 生成邻域同义改写

推荐用本地配置脚本快速切换：

```bash
python scripts/set_llm_config.py ^
  --api-key your_key ^
  --base-url https://api.deepseek.com/v1 ^
  --model deepseek-chat
```

查看当前配置：

```bash
python scripts/set_llm_config.py --show
```

清空本地配置：

```bash
python scripts/set_llm_config.py --clear
```

脚本会把配置写入：

```text
config/llm_api.json
```

客户端读取优先级是：

```text
命令行构造参数 > 环境变量 > config/llm_api.json > 内置默认值
```

如果你不想写本地配置文件，也可以继续用环境变量：

```bash
set LLM_API_KEY=your_key
set LLM_BASE_URL=https://api.deepseek.com/v1
set LLM_MODEL=deepseek-chat
```

也可以通过命令行传入：

```bash
python main.py train --spoof-threshold 0.75 ^
  --llm-api-key your_key ^
  --llm-base-url https://api.deepseek.com/v1 ^
  --llm-model deepseek-chat
```

## 使用方式

### 训练

`spoof_threshold` 是强制参数，必须显式指定。

```bash
python main.py train --spoof-threshold 0.80 --verbose
```

指定数据集：

```bash
python run_exampl.py train --dataset pubmed_papers --spoof-threshold 0.80 --verbose
```

控制样本和重生成预算：

```bash
python main.py train ^
  --dataset enron_emails ^
  --spoof-threshold 0.80 ^
  --neighbor-count 8 ^
  --victim-ratio 0.3333 ^
  --spoof-ratio 0.5 ^
  --victim-epochs 2 ^
  --max-samples-per-dataset 300 ^
  --max-spoof-per-dataset 100 ^
  --max-spoof-attempts 6 ^
  --max-spoof-rounds 600
```

### 推断

```bash
python main.py infer --text "your text here" --verbose
```

## 训练输出

训练完成后会输出并保存：

- 每个数据集的原始成员数、原始非成员数
- 候选伪造样本数
- 达到阈值的伪造样本数
- 进入重生成的样本数
- 每个数据集使用的重生成轮次
- 最终每类平衡数量
- 当前使用的 `spoof_threshold`
- 审计器评估指标

相关文件默认写入：

- `models/auditor/auditor.pkl`
- `models/auditor/metadata.json`
- `models/auditor/spoof_audit_log.json`

## 说明

- 当前实现的主链路不再依赖旧版文本改写策略、Critic 分析或影子模型。
- `sentence-transformers` 相关嵌入工具已降为可选辅助函数，不是训练/推断主流程所需。
- 如果你继续演化方案，应优先以 `思路改动v1.txt` 为准，而不是旧版文档描述。
