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

## Current Protocol Generations

先确认所处协议世代，再改代码或运行实验。若文字记录冲突，优先级为：当前配置与机器可读 manifest/status > `研究记录/顶会推进_notes.md` 和 `研究记录/顶会推进_task_plan.md` > README 当前协议段 > 更早的 `思路v*.txt` 和历史记录。

- **v23（当前活跃设计，runtime 未实现）**：`pcv-mia-v23` / `pcv-restoration-first-v23` / `pcv-restoration-first-v23-design-r6`，设计配置为 `configs/restoration_first_v23.yaml`，预注册为 `研究记录/PCV-MIA_v23_Restoration-First_协议预注册_20260812.md`，未来产物只能写入 `artifacts/v23/`。类型/句法只承担最低构造有效性，P0 选择目标是原事实稳定、原实体可恢复、非实体检索锚点、验证可辨别和 query 自包含/输出可解析；不优化反事实自然性，不允许读取 membership、victim/LLM-only response、Retriever 输出或 AUC。完整池只允许每个 runtime bundle/dataset 在受控 aggregate-DF stage 读取一次并输出不含 source 映射或逐 source 行的 token DF，后续 selector stage 只验 identity/hash；不得声称低频 token 不可反演。P0 按 dense/BM25/hybrid 分别计算 source PVS 与逐数据集/macro 指标，禁止跨 backend 聚合主分。当前只完成设计预注册，不得当作可执行协议。
- **2026-08-13 状态快照**：v22 三套 source pool 与 pilot 均 passed，但 calibration_r3 已以 `failed_final_calibration_revision` 正式失败；v22 formal scan、split、fresh audit、shadow、release、Luna query、Gemma victim 和 Retriever 均未启动且停止推进。v23 design-r5 reader-test 已 `REQUEST_CHANGES`；仅修复其5个实质阻断项的 design-r6 已通过限定范围reader-test，fact extraction与Restoration hard gates未变；design manifest已生成并核验。runtime、pilot和下游均未启动。当前唯一下一步是等待用户单独授权实现runtime与定向测试，且实现授权不自动包含pilot、GPU、API、victim或Retriever。
- **v22（冻结失败上游/受控复用）**：`pcv-mia-v22` / `pcv-attackability-first-v22` 的 source pool/order、完整 source 与绑定模型/代码 hash 仅可按 v23 design-r6 中显式23文件列表复用；r1-r3 labels、thresholds、utility/naturalness/context-usability 分数、旧 eligible 判定和 r3 context-passed 集合不得迁入 v23 selection。需要核验历史状态时使用 `scripts/39_run_v22_attackability_first.py status`，不得续跑 v22 下游。
- **v21/r4（受控历史/开发证据）**：只允许按 v22 配置显式绑定的 pool、source order 或 model snapshot 复用。`phase_2_review_r1/r2` 对 v22 为 `superseded_goal_mismatch`；不要原地续跑、覆盖或把其 labels/threshold 迁入 v22。
- **v20（下游 RAG 与评估基线）**：`pcv-mia-v20` / `pcv-rag-only-source-v20` 仍是成熟的 01-15 RAG、matched LLM-only、baseline、defense 和报告实现参考。v22 release 完成前，不得把 v22 上游候选与 v20 正式响应/分数拼成同一 suite。
- **v19、v6.x 与 `legacy/`**：仅作历史复现和证据追踪，除非用户明确要求，不得续跑、合并或进入新论文主表。

## Repository Map

- `src/data/`：数据读取、清洗、切块和 Enron sampling。
- `src/prepare/`：split、benchmark、v20/v21/v22 release controls、capacity 与 entity-policy 工作流。
- `src/attack/`：attackability selector、实体抽取/路由、扰动和语义解析。
- `src/fact_extraction/`、`src/paired_claims/`、`src/query_generation/`：事实、最小反事实 claim 和成对 query 构造。
- `src/rag/`、`src/llm/`：索引、Retriever、RAG/LLM-only runner 与 OpenAI-compatible 客户端。
- `src/parsing/`、`src/scoring/`、`src/evaluation/`：stance parsing、PCV/calibration、统计与论文报告。
- `src/baselines/`、`src/defenses/`、`src/spoof/`：对照方法、防御和可选 hard negative。
- `src/utils/`：I/O、hash、seed、日志和 run identity；这些通常处于实验完整性边界内。
- `scripts/01_*.py` 到 `15_*.py` 是经典主流水线；`scripts/run_pipeline.py` 只编排 01-15。`16_*.py` 到 `39_*.py` 以及未编号脚本是归档、门禁、版本化协议和审计入口，不能因为不在 01-15 中就视为辅助废弃代码。
- `configs/` 按协议世代并存；运行时必须显式选择正确配置，不能用无版本默认配置替换冻结的 v20/v21/v22 配置。
- `artifacts/`、`indexes/` 和 `legacy/` 保存带身份的生成物；`datasets/` 保存原始/处理数据。不要手工修改大型 artifact 来“修结果”。
- `tests/` 使用 `unittest`；`研究记录/` 保存研究依据、协议历史和接管摘要。

## Architecture & Leakage Invariants

以下边界默认 fail closed，任何放宽都必须有明确研究理由、配置版本、回归测试和总表记录。

- 正式主 RAG index 只能包含 `KB_Member`。`True_Non_Member`、`Spoof_Seed`、`Spoofed_Non_Member` 和 `Reserve` 不得进入主 index。仅冻结协议显式定义的 isolated shadow/dev index 可使用 `Reserve`，且必须通过 `allowed_group="Reserve"`、独立路径和 manifest 与主 index 区分。
- split 必须保持 source-exclusive，并验证 source/text hash 跨组零重叠。PubMed membership unit 是完整 PMCID article；不得退化为 chunk 或行号。
- Attack benchmark、query plan、index、模型 revision、配置、代码 commit 和关键 artifact 都必须保存 hash/identity。resume 前重算并校验，漂移则拒绝复用；需要重建时使用新身份或明确 `--force`，不能伪装成同一实验。
- 主攻击使用成对 true/counterfactual claim 与 Q+/Q-；除目标实体槽位外必须保持最小改动。每个协议的固定 pair/query 预算不可在看到响应后自适应增加。
- P0 主分是 source-level RAG-only Paired Verification Score。LLM-only/context gain、conformal、shadow、mechanism、baseline 和 defense 是归因、校准或对照，不能偷换主攻击定义。
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
# v22 只读状态
& 'D:\python\anaconda\envs\mia_model\python.exe' -B scripts\39_run_v22_attackability_first.py status

# 全量单元测试
& 'D:\python\anaconda\envs\mia_model\python.exe' -B -m unittest discover -s tests

# 经典 01-15 流水线先 dry-run
& 'D:\python\anaconda\envs\mia_model\python.exe' -B scripts\run_pipeline.py --dry-run
```

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

## Security, Commits & Handoff

不要提交或输出 `.env`、API key、私有数据集、模型权重或大型响应。LLM 凭据只来自 `PCV_VICTIM_*`、`PCV_SIBLING_*` 等环境变量；日志和错误信息不得回显 secret。不要为排错擅自切换 provider、模型或联网 fallback。

Git 提交沿用现有 Conventional Commits 风格，如 `feat(attack): ...`、`fix(evaluation): ...`、`docs(project): ...`。提交说明需写清协议世代、受影响阶段、配置/identity 是否改变、是否产生新 artifact、API/victim/Retriever 调用数和验证命令。除非用户明确要求，不提交、不推送，也不把无关工作树改动带入提交。
