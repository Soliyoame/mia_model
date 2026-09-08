# Repository Guidelines

## Communication & Change Boundary

默认用中文和用户沟通，判断类问题先给结论、再给依据。用户说“先别改代码”时只做只读分析。修改前先说明将改哪些文件及原因，保持改动小而直接，不做无关重构。

本仓库经常存在未提交的实验代码、配置和研究记录。开始工作先检查 `git status --short --branch`；所有既有改动都视为用户资产，不覆盖、不回滚、不顺手清理。若任务与脏文件重叠，先理解现有改动并在其上兼容。模型下载、依赖安装、GPU 长任务、真实 API/victim 调用和会产生费用的实验，必须在执行前获得用户明确授权。

## Code Reuse & Cleanup Discipline

- 实现需求时第一优先在职责匹配的现有代码文件上修改和扩展；除非现有文件无法合理承载新职责、协议要求独立入口或产物，或拆分能显著避免耦合，否则不得无缘无故新建代码文件。确需新建时，修改前说明新文件的职责及现有文件不适合承载的原因。
- 对已经明确与当前实验主线无关的代码应及时清理。清理前必须确认其没有被主线代码、配置、测试或文档引用，也不属于历史复现、失败证据、审计链、冻结协议或用户尚未提交的资产；用途或归属不明确时不得擅自删除，应先向用户确认。
- 每次修改代码后都要复查 `git status --short` 及本次任务产生的文件，及时删除确认与实验主线无关的临时测试文件、一次性调试脚本、缓存和输出文件。正式回归测试、协议要求的脚本以及可复现、可审计的实验产物不属于临时文件，不得以“清理”为由删除。

## Research Goal & Scientific Standard

项目目标是把 PCV-MIA 做到可投稿安全、隐私或机器学习顶会的研究质量。工程决策优先保证：威胁模型清晰、数据无泄漏、对照公平、统计单位正确、协议可复现、失败证据可审计，而不是只追求跑通或提高单次 AUC。

- 论文主评估单位是 source document；chunk 只用于切分、检索和构造查询，不能把 chunk 当独立样本夸大样本量。
- 模型、Retriever、切块、实体策略、阈值、查询预算和审计规则必须在正式 test/victim 结果前冻结。禁止根据正式攻击 AUC、victim response 或 membership label 调参。
- 开发校准、pilot、fresh audit 与 formal test 必须身份隔离；报告结果时同时保留逐数据集结果、macro 汇总、置信区间/低 FPR 指标及失败模式。
- AI 预审、Assistant annotation、用户复核和独立人工盲审必须准确区分，不能把自动审核写成真人标注或 Cohen's kappa 证据。
- 失败、暂停、superseded 和 diagnostic-only artifact 都是研究证据；不得静默删除、改写为 passed，或混入 canonical release。

## Research Engineering Simplicity

### 1. 总原则：科研正确性优先，但不要过度工程化

本项目的目标是完成高质量、可复现的科研实验和论文，而不是构建企业级实验治理平台。

所有工程设计遵循：

Scientific validity > reproducibility > simplicity > governance complexity

在满足以下前提的情况下，优先采用最简单、最直接的实现：

- 无数据泄漏
- 无 test-set post-hoc tuning
- 实验配置可复现
- 数据划分固定
- 模型、Prompt、Retriever 与 scoring 可追踪
- 正式结果不可静默覆盖

不要因为“可能更严格”或“更加可审计”就自动增加复杂治理层。

### 2. 默认科研流程只需要

今后新实验或 successor protocol 默认使用：

Development
→ Freeze config + code commit
→ Fixed split
→ Formal run
→ Evaluation

通常只需要保留：

1. experiment/config YAML
2. fixed dataset split manifest
3. random seed
4. model ID/revision/decoding configuration
5. Prompt/query configuration
6. Retriever/index configuration
7. scoring configuration
8. evaluation metric configuration
9. Git commit SHA
10. 必要关键 artifact 的 hash

这已经足以满足论文实验的可复现性要求。

### 3. Freeze 的定义必须简单

“Freeze”默认指在正式 test/victim 结果可见之前固定：

- dataset split
- selector / fact construction
- counterfactual construction
- Query construction
- query budget
- model configuration
- Retriever configuration
- scoring formula
- thresholds/hyperparameters
- evaluation metrics
- random seed

并记录对应 config + Git commit。

不要默认把 Freeze 扩展成复杂的：

- runtime bundle closure
- 多级 protocol identity
- 多层 successor identity
- stage dependency fingerprint
- 每文件多层 hash hierarchy
- carry-forward attestation chain

除非当前任务明确存在实际科研风险，且简单的 config/version/hash 无法解决。

### 4. Authorization 不是论文实验的必要组件

Authorization 只作为工程安全保护使用，例如防止：

- 未经用户许可的付费 API 调用
- GPU 长任务
- victim 正式调用
- 大规模 Retriever/index 构建
- 删除或覆盖正式实验结果

不要把 authorization 当成科研方法的一部分。

以后不要默认创建：

- per-stage authorization
- run authorization hierarchy
- authorization budget
- reservation authorization
- authorization attestation
- authorization-specific protocol revision

除非用户明确要求，或者任务确实涉及外部费用、不可逆写操作或正式 test 数据暴露。

对于普通本地开发、单元测试、配置检查、统计分析，不应因为缺少 authorization artifact 而人为阻塞。

### 5. 默认禁止继续扩大以下治理系统

除非用户明确要求，否则不要新增或扩展：

- reservation system
- append-only execution ledger
- ledger anchor
- budget journal
- stage-scoped execution identity
- carry-forward attestation
- recovery attestation
- stage authorization chain
- attempt ordinal governance
- runtime bundle closure
- multi-level freeze identity
- protocol identity nesting
- execution identity nesting

如果现有历史版本已经包含这些机制：

- 不要为了“清理”而破坏正在运行的正式实验；
- 不要静默删除历史 artifact；
- 但也不要继续让新的科研功能依赖更多治理层。

把它们视为历史协议兼容基础设施，而不是未来新功能的默认架构。

### 6. 修改前必须进行 complexity check

每次 Codex 准备新增以下任意内容：

- 新 YAML governance config
- 新 manifest
- 新 freeze 文件
- 新 authorization 文件
- 新 ledger
- 新 identity/hash 层
- 新 recovery contract
- 新 stage wrapper
- 新 orchestration script

必须先问自己：

“这个文件是否直接解决论文实验中的真实科研问题？”

如果答案只是：

- 更严格
- 更完整
- 更可审计
- 以后可能有用
- 为了防止理论上的状态漂移

则默认不要创建。

必须优先检查能否通过以下更小的改动解决：

- 一个字段
- 一个 config
- 一个 manifest
- 一个 Git commit
- 一个普通校验函数
- 一个已有脚本的小修改

### 7. 优先修改现有文件，避免文件爆炸

实现新功能时遵循以下优先级：

existing implementation
→ small extension
→ existing config field
→ existing test
→ only then new file

不要为每个很小的协议变化创建：

config_x_r1.yaml
config_x_r1_fix1.yaml
config_x_r1_fix2.yaml
config_x_r2.yaml
config_x_r2.freeze.json
config_x_r2.policy.freeze.json

除非论文复现或已经产生正式实验结果确实要求保存这些版本。开发阶段允许正常使用 Git 版本历史追踪变化。

Git 本身就是版本控制系统，不需要在文件系统里重新实现一套 Git。

### 8. 区分“论文必要”和“工程可选”

以后判断一个机制是否要实现时，使用下面标准。

论文通常必须：

- fixed split
- fixed seed
- fixed model configuration
- fixed Prompt
- fixed query budget
- fixed Retriever
- fixed scoring
- fixed evaluation
- dev/test separation
- no leakage
- no post-hoc test tuning
- reproducible code/config

通常只是工程可选：

- authorization hierarchy
- ledger
- reservation
- stage identity
- carry-forward attestation
- recovery contract
- multi-layer freeze hash
- per-stage budget journal

不要把第二类自动升级成第一类。

### 9. 已冻结协议与历史产物的保护

对于已进入正式阶段或已经产生冻结产物的协议：

- 不要为了应用本条“简化原则”而修改其已冻结的主协议；
- 不要重新生成已有正式 split；
- 不要修改已经冻结的 selector/query/scoring；
- 不要删除已有 governance artifact；
- 不要让已有结果或正在运行的实验失效。

当前使用哪个协议、是否仍在运行及可恢复的阶段，以当前配置、机器可读产物和研究总表为准；历史 passed 状态不自动授权续跑下游。

本条规则主要约束：

- 后续 robustness 实验
- ablation
- 新 generator/retriever 扩展
- 后续实验版本或 successor protocol
- 开源代码整理
- 新的实验工具开发

对于这些新任务，默认采用简单科研流程，不再复制历史协议的全部治理复杂度。

### 10. 不要因为小修改自动创建 successor protocol

只有以下情况通常值得创建新的实验版本：

- 改变攻击核心方法
- 改变 selector
- 改变 counterfactual policy
- 改变正式 Query construction
- 改变 scoring
- 改变正式 split
- 改变正式评估定义
- 正式 test 结果已经可见后又修改超参数

普通的 bug fix（不改变实验语义）、logging、CLI usability、文档修改、测试补充，以及输出完全一致的性能优化，不要自动创建新的 protocol generation。

如果修复确实会改变已经产生的实验结果，则明确说明影响范围，再决定是否重跑。

### 11. Codex 的默认回答方式

当用户提出一个科研代码修改需求时，不要主动把简单问题升级成治理工程。

先给出：

1. 最小可行修改
2. 是否影响论文实验语义
3. 是否需要重跑
4. 是否需要新版本

默认答案应倾向：

“能在现有结构中简单完成，就简单完成。”

而不是：

“新增一个 protocol revision + authorization + manifest + freeze + ledger + attestation。”

### 12. 一个重要判断标准

以后任何工程设计都用这句话检查：

“如果删掉这个机制不会影响实验科学有效性、可复现性、数据泄漏控制或论文结论解释，那么它通常不应该成为强制基础设施。”

英文原意：

“If removing this mechanism would not change scientific validity, reproducibility, leakage control, or the interpretation of the paper results, then it should probably not be mandatory infrastructure.”

本条简化原则不追溯修改已冻结协议、冻结文件或历史 artifact；它只作为后续 Codex 会话设计新工作的默认项目规则。

## Experiment Context & Source of Truth

本文件只保存稳定的协作规则、环境约束和科研边界，不记录实验过程、当前进度、逐次结果或临时下一步。

开始修改代码或运行实验前，先读取目标配置与机器可读 manifest/status，再查阅 [研究总表](研究记录/顶会推进_notes.md) 和 [任务总表](研究记录/顶会推进_task_plan.md)，确认当前协议、阶段、产物身份及下一步。README 只承担入口与简要说明，详细历史见两份总表及其引用的专项记录。

若文字记录冲突，优先级为：当前配置与机器可读 manifest/status > 两份研究总表 > README 当前协议段 > 更早的 `思路v*.txt` 和历史记录。区分配置声明、已实现功能、实际运行结果和待办，不把设计、预检或 mock 通过写成正式实验完成。

历史失败、暂停或 superseded 协议不得自动续跑、覆盖或并入新论文主表。跨协议复用必须符合目标配置的显式绑定；不得沿用旧 membership、eligible 判定、labels、thresholds 或 response/score 作为新选择器的输入。

## Repository Map

- `src/data/`：数据读取、清洗、切块和 Enron sampling。
- `src/prepare/`：source/candidate pool、eligibility、split、benchmark、版本化 release controls、capacity 与 entity-policy 工作流。
- `src/attack/`：attackability selector、实体抽取/路由、扰动和语义解析。
- `src/fact_extraction/`、`src/paired_claims/`、`src/query_generation/`：事实、最小反事实 claim 和成对 query 构造。
- `src/rag/`、`src/llm/`：索引、Retriever、RAG/LLM-only runner 与 OpenAI-compatible 客户端。
- `src/parsing/`、`src/scoring/`、`src/evaluation/`：stance parsing、PCV/calibration、统计与论文报告。
- `src/baselines/`、`src/defenses/`、`src/spoof/`：对照方法、防御和可选 hard negative。
- `src/utils/`：I/O、hash、seed、日志和 run identity；这些通常处于实验完整性边界内。
- `scripts/01_*.py` 到 `15_*.py` 是经典主流水线；`scripts/run_pipeline.py` 只编排 01-15。后续编号与未编号脚本包含独立协议、源池构建、门禁和审计入口，不能因为不在 01-15 中就视为辅助废弃代码，也不能假定经典 runner 已支持当前协议。
- `configs/` 按协议世代并存；运行时必须显式选择正确配置，不能用无版本默认配置替换目标协议的冻结配置。
- `artifacts/`、`indexes/` 和 `legacy/` 保存带身份的生成物；`datasets/` 保存原始/处理数据。不要手工修改大型 artifact 来“修结果”。
- `tests/` 使用 `unittest`；`研究记录/` 保存研究依据、协议历史和接管摘要。

## Architecture & Leakage Invariants

以下边界默认 fail closed，任何放宽都必须有明确研究理由、配置版本、回归测试和总表记录。

- 正式主 RAG index 只能包含 `KB_Member`。`True_Non_Member`、`Spoof_Seed`、`Spoofed_Non_Member` 和 `Reserve` 不得进入主 index。仅冻结协议显式定义的 isolated shadow/dev index 可使用 `Reserve`，且必须通过 `allowed_group="Reserve"`、独立路径和 manifest 与主 index 区分。
- split 必须保持 source-exclusive，并验证 source/text hash 跨组零重叠。source 的定义以目标数据配置为准：BEIR corpus 的 document 与历史 PubMed 的完整 PMCID article 不得混为同一数据单位；不能退化为 chunk 或行号。
- Attack benchmark、query plan、index、模型 revision、配置、代码 commit 和关键 artifact 都必须保存 hash/identity。resume 前重算并校验，漂移则拒绝复用；需要重建时使用新身份或明确 `--force`，不能伪装成同一实验。
- 主攻击使用成对 true/counterfactual claim 与 Q+/Q-；除目标实体槽位外必须保持最小改动。每个协议的固定 pair/query 预算不可在看到响应后自适应增加。
- P0 主分是 source-level RAG-only Paired Verification Score。LLM-only/context gain、conformal、shadow、mechanism、baseline 和 defense 是归因、校准或对照，不能偷换主攻击定义。各 Retriever backend 分别报告逐数据集和 macro 结果，禁止跨 backend 聚合主分。
- 一次只运行一个 dataset x Generator x Retriever x run-role cell。provider 实际 model ID/version、Retriever backend/revision 和 response fingerprint 必须写入身份；具体模型变化后新建 suite，禁止跨模型合并或原地续跑。
- `Spoofed_Non_Member` 只是可选 hard-negative 对照，由显式开关控制，不是 PCV-MIA 主方法必需部分。

## Environment & Commands

唯一 Python 环境是 Conda `mia_model`，Windows 解释器为 `D:\python\anaconda\envs\mia_model\python.exe`。禁止使用 `D:\python\anaconda\python.exe`（base）或向 base 安装依赖。命令优先加 `-B`，避免写入无关 `.pyc`。

运行测试、流水线、模型下载或安装前先确认：

```powershell
& 'D:\python\anaconda\envs\mia_model\python.exe' -B -c "import sys; print(sys.executable)"
```

BGE、reranker、GLiNER 或其他 CUDA 门禁前还要确认 `torch.cuda.is_available()` 为 `True`；不得静默接受 CPU PyTorch/CPU fallback。当前锁定环境使用 `requirements.txt` 中的 CUDA PyTorch。

常用安全命令：

```powershell
# 全量单元测试
& 'D:\python\anaconda\envs\mia_model\python.exe' -X utf8 -B -m unittest discover -s tests

# 文档与空白检查
git diff --check
```

协议专属命令从 README 当前入口和任务总表选择，并先检查对应 CLI 参数；不要直接执行历史记录中的长任务示例。经典 01-15 流水线只有在目标协议适用时才使用，并先执行 dry-run。

若 Windows 缓存权限导致 `py_compile`/`compileall` 失败，改用内存 AST 编译，不删除或改权限绕过。长任务必须使用协议已有的 checkpoint/resume 和单 wave/单 cell 参数；不要把受工具超时影响的中断写成实验失败。

## Coding & Testing

使用 Python 3.10+、4 空格缩进和类型标注；函数、变量、模块及 JSON/YAML 字段使用 `snake_case`。新增行为优先暴露到 `configs/*.yaml`，不要把模型名、路径、阈值或数据集特例散落硬编码。编号脚本、CLI 参数和 artifact schema 是复现接口，非必要不改名。

测试放在 `tests/`，方法名为 `test_<expected_behavior>`。研究协议改动至少覆盖：数据隔离、source/hash identity、determinism、resume/force drift、claim/query 单槽约束、模型/检索身份、release fail-closed。涉及 LLM 的测试应 mock 或隔离客户端，不依赖真实网络。先跑受影响的定向测试，再按风险决定全量回归；文档-only 改动至少执行 `git diff --check` 和内容复读。

## Experiment & Artifact Discipline

- 修改 scoring、selection、query、Retriever、模型或生成配置后，从最早受影响阶段以新身份重跑，禁止混用新旧中间产物。
- 不直接编辑 immutable manifest、label、response、score 或 report。代码 bug 导致的 partial attempt 原样保留并标注 superseded，再创建新 revision。
- 正式结果必须能追溯到 config hash、runtime bundle/commit、输入 hash、模型 revision、随机种子和完整 gate 链。
- 不把 pilot、capacity stress test、development calibration 或 selective subset 结果表述成 untouched formal test。
- 大型生成物、私有数据和模型权重默认不纳入 Git；提交前只暂存本任务文件，并复核没有 `.env`、key、response payload 或无关脏改动。

## Research Progress Records

`研究记录/顶会推进_notes.md` 与 `研究记录/顶会推进_task_plan.md` 是项目级权威总表。任何重要协议、模型、Retriever、环境、实验身份、门禁、artifact 状态、错误处理、论文口径或下一步发生变化时，必须同步更新两者：notes 记录高层决策、依据和结果，task plan 记录阶段勾选、当前状态和唯一下一步。

详细指标、逐次日志和完整证据写入对应 `研究记录/思路v*.txt`、专项实施记录或机器可读 artifact。根目录 `notes.md`/`task_plan.md` 可作任务级工作日志，但不能替代上述两份项目总表。更新历史结论时追加带日期的 superseding 条目，不回写旧事实。

不要再将实验进展或阶段快照复制进 AGENTS.md；本文件只链接上述记录。只有稳定的协作规则、环境要求或科研约束变化时才更新本文件。

## Security, Commits & Handoff

不要提交或输出 `.env`、API key、私有数据集、模型权重或大型响应。LLM 凭据只来自 `PCV_VICTIM_*`、`PCV_SIBLING_*` 等环境变量；日志和错误信息不得回显 secret。不要为排错擅自切换 provider、模型或联网 fallback。

Git 提交沿用现有 Conventional Commits 风格，如 `feat(attack): ...`、`fix(evaluation): ...`、`docs(project): ...`。提交说明需写清协议世代、受影响阶段、配置/identity 是否改变、是否产生新 artifact、API/victim/Retriever 调用数和验证命令。除非用户明确要求，不提交、不推送，也不把无关工作树改动带入提交。
