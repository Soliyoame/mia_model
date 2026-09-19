-- Active: 1778327661076@@127.0.0.1@5432
# Task Plan: PCV-MIA 安全顶会推进

> **当前有效覆盖（2026-08-10）**：EDGAR、Enron、PubMed 均进入论文主表；
> EDGAR/PubMed=`standard_primary`，Enron=`capacity_qualified_primary`。下文把
> Enron 写成 boundary-only、500-row audit 或禁止 formal promotion 的旧条目均为历史状态，
> 已被末尾“capacity-qualified primary 修订”取代；历史结果本身仍保留，不得改写。

## 当前执行点：v22 Attackability-First（2026-08-11）

- [x] 2026-08-12 更新根目录 `AGENTS.md` 项目总导航：明确顶会研究标准、v20/v21/v22
  世代边界、当前 v22 status、source-level/无泄漏/身份冻结要求、目录职责与安全验证命令；
  本次不改变协议或 artifact，下一实验门禁保持不变。
- [x] 新建 `pcv-mia-v22` / `pcv-attackability-first-v22` 独立配置、selector 与编号 runner；
  v21/r4 原产物保持只读，`phase_2_review_r1/r2` 记为 `superseded_goal_mismatch`。
- [x] 将正式 router 收敛为唯一模型
  `fastino/gliner2-base-v1@f5b2ecedebe4381b088c1cf276f5bf72a52cac54`；移除 v22
  runtime 中的 GLiNER2-large、spaCy transformer 与 PubMed biomedical voter。
- [x] 实现规则优先、单模型补充/重路由、模型漏检回退 declared type；semantic 输出不再
  单独否决高攻击效用实体；`PROJECT_NAME` 诊断预测不能降级主表候选或提升诊断候选。
- [x] 实现固定六分量 utility、三候选反事实、单槽/source-absence/格式门禁、确定性 top-3、
  structured extension 隔离、membership/victim/AUC 字段隔离。
- [x] 实现可续跑 source-pool、pilot/formal scan、300-row calibration、用户复核、150-row
  fresh audit、split、Reserve-only shadow gate 与 release finalize。
- [x] 收紧 fail-closed：SQLite/JSON 崩溃恢复、assistant-label hash、不可变 threshold/evaluation、
  calibration/fresh-audit source+fact 零重叠、formal scan 2250×3 固定预算、split/shadow/release
  上游 hash 与身份复核；shadow gate 生成和 release 消费时均重验实际 manifest/payload。
- [x] 定向单测 21/21、全量 unittest 425/425、AST/YAML、CLI status/help 与
  `git diff --check` 通过；外部/API/victim/Retriever 调用为 0。
- [x] 独立只读复审最终 `Go`，协议级阻断项已清零。
- [x] 用户已确认并提交 v22 冻结输入：commit=`baead70`；提交后 runtime 冻结文件相对
  `HEAD` 无漂移，无关脏改动未进入提交。
- [x] `freeze-protocol` 已通过：status=`frozen_zero_external_calls`，commit=`baead70`，
  protocol identity=`a488372a733977543f345fa46ed82b6dcc154c32f758595417d5d96c898f1044`，
  API/victim/Retriever=0。
- [x] 分数据集执行可续跑的 `prepare-source-pool`；按用户决定改为 Enron 优先，Enron pool
  通过后再决定其 pilot 与 EDGAR/PubMed pool 顺序。长任务命令交给用户逐次运行。
  - Enron 已 `passed`：source count=35,000，source-pool identity=
    `66d746a9db665c5d660db1235c6144cf8148afb86f10165068c8f267c59a258b`，外部调用=0。
  - EDGAR 已 `passed`：source count=5,210，source-pool identity=
    `44b6e2c89931601dec0378b75d654f26a59ec22433b461283277e80a51db20cf`，外部调用=0。
  - PubMed 已 `passed`：source count=47,950，source-pool identity=
    `f1f490435f3555e8908d688b3309d42c68400fd8e81e8a17bf8dce8607e9df5c`，外部调用=0。
- [x] source pool 完成后运行三数据集短 pilot并冻结 300-row calibration；plan identity=
  `3bbda077698505856f366e6cd22997a30500258503c323e514e8c302f05623bd`，API/victim/Retriever=0。
- [x] 三数据集 pilot 已全部通过：Enron=393/1,000、EDGAR=594/1,000、PubMed=664/1,000；
  每套 4 waves 的 artifact 哈希和模型身份均有效，API/victim/Retriever=0。
- [x] Assistant 仅依据 blinded calibration 完成 300/300 标签并通过校验；attack_usable=
  yes 52 / no 233 / uncertain 15。用户盲审已冻结为 90 行（基础 75 + uncertain 15），
  Assistant 标签和抽样原因均不可见；详细记录见
  `研究记录/PCV-MIA_v22_Calibration与盲审记录_20260812.md`。
- [x] 用户确认完成 90 行逐条独立判断并全部 pass；Assistant 仅机械代录为 90/90 yes，
  user labels SHA-256=`e8b8cdb86cb171c31c7e2075ab5371db0d66ee6e324fa541ad3e09f57464a705`，
  schema/review-ID/manifest identity 校验通过。
- [x] 正式 `evaluate-calibration` 已运行：status=`failed_new_protocol_identity_required`；结构负例
  rejection=0%、Assistant–user agreement=3.33%、user precision=100%、selected threshold=null，
  AUC/victim response/API/Retriever 均未访问或调用。
- [x] 原样保留 r1 failed evidence，并实现独立 `pcv_v22_attackability_calibration_r2`；不回改或复用
  r1 labels。r2 改为 Assistant-only surrogate calibration，显式禁止 human-validation/human-gold
  precision claim，输出隔离到 `artifacts/v22/calibration_r2/`。
- [x] r2 冻结规则实现：15 cells×(16 fresh real+4 structural controls)=300 rows；排除 r1 pair/source/
  fact overlap；匿名 review ID 和 blinded metadata；绑定基础 v22 protocol/runtime hash、r1 failed
  identity、r2 commit/runtime bundle；resume/hash drift 均 fail closed。
- [x] r2 容量检查通过：15 cells 均≥16 个 fresh unique facts，minimum=73；AUC/victim/API/Retriever=0。
- [x] 240/240 fresh real rows 的 true claim 均可在冻结 source-pool 原文定位；blinded evidence 使用
  原文上下文，禁止把 true claim 自身当作独立 groundedness 证据。
- [x] r2 定向与 v22 回归 27/27、内存语法编译、CLI help、`git diff --check` 通过。
- [x] 最终全量 unittest 431/431 通过。
- [ ] 单独提交 r2 runtime 文件；提交前禁止 freeze，因为正式 plan 必须绑定已提交代码身份。
- [ ] 提交后运行 `scripts/40_run_v22_attackability_calibration_r2.py freeze`，再由 Assistant 仅依据
  新 blinded rows 审核 300/300，运行 label validator 与 r2 evaluate。
- [ ] calibration 通过后冻结 150-row fresh audit；通过后才允许 formal scan、split 与 Reserve
  shadow。shadow 通过前禁止 Luna query、Gemma victim 和正式 Retriever 矩阵重绑定。

当前唯一下一步：审核并提交已实现的 calibration r2 runtime；随后才能冻结 r2 300-row plan。
r1 已正式失败且不可改写；r2 尚未冻结，threshold、fresh audit、formal scan、query、victim 与
Retriever 继续禁止。

## Goal

完成 `pcv-mia-v20`：在 Edgar/Enron/PubMed 上建立 BGE/BM25/strong-RAG、
动态四 Generator 家族且具体模型严格冻结的 source-level 固定预算实验框架，
先完成 Llama 主模型，再形成可投安全/隐私顶会的主结果、机制、baseline 与 defense。

## Phases

- [x] Phase 0: 创建冻结方案、任务计划与研究笔记
- [x] Phase 1: 实现无 API 的 claim/query validator 及单元测试
- [x] Phase 2: 实现 source-level quota 和每 source 固定 4 pair/8 调用
- [x] Phase 3: 实现 BM25 backend 与 generator/retriever 实验身份
- [x] Phase 4: 加强 matched-control 语义与 36-cell canonical 门禁
- [x] Phase 5: 完成 PubMed 当前协议的离线重建入口与 pilot 审计模板
- [x] Phase 6: 运行语法检查、全量 unittest、安全检查和 diff review
- [x] Phase 7: 完成 v6.3/RC2 本地阶段；旧 MiniLM/Qwen API 计划由 Phase 8 supersede
- [x] Phase 8A: 将旧 MiniLM/Gemini 主协议升级为 v20 BGE + Llama 主模型
- [x] Phase 8B: 完成 BGE snapshot、CUDA、三数据集离线门禁与正式索引
- [ ] Phase 8C0: 关闭正式 API 前审稿红队审计发现的 P0 协议与矩阵风险
- [ ] Phase 8C: 运行三数据集、六系统、2,700-call Llama compatibility pilot
- [ ] Phase 8D: pilot 通过后运行 Llama 正式 suite、机制、baseline 与 defense
- [ ] Phase 8E: 冻结 Qwen/GPT/Gemini 具体型号并运行跨模型 extension

## Key Questions

1. 如何建立未参与方法开发的 canonical test，并拆分 Retriever-dev、Pilot-dev
   与 conformal calibration？
2. 如何在现有调用预算内公平复现 MEntA/E-MIA 等 baseline，并使 defense 与
   benign QA utility 真正可执行？
3. Provider 首个真实响应能否返回与 registry 完全一致的
   `meta/llama-3.1-70b-instruct` model ID？
4. 修复后的三数据集六系统 pilot 能否同时通过完整率、stance、身份、hybrid 和
   Oracle/Random 机制门禁？
5. pilot 通过后，如何在不混合 Generator/Retriever/hash 身份的前提下安全推进
   90,000-call Llama 主 suite 与后续跨模型 extension？

## Decisions Made

- Claim validator 的硬门禁不调用任何 API；LLM 只允许作可选自然度评分。
- 主攻击每 source 固定 3 pair/6 victim calls，不允许响应后自适应追加；
  4 pair/8 calls 只作为高预算消融。
- PubMed 以 PMCID/完整论文为 source，不复用旧 True_Member 产物。
- MiniLM 决策已被 v20 supersede；正式 dense 改为
  `BAAI/bge-base-en-v1.5`，完整 repo ID、commit SHA 与 index hash 必须进入身份。
- 主 Generator 从不可用的 `gemini-2.0-flash` 在首次正式调用前合法切换并冻结为
  `meta/llama-3.1-70b-instruct`；具体模型变更必须新建 suite。
- Retriever 切块只依据 Reserve 离线 Recall/MRR/延迟门禁选择，禁止查看攻击 AUC；
  三数据集唯一共同通过的正式配置为 128 tokens / overlap 32。
- 六系统 compatibility pilot 对同一 150-query 集合全部运行，预算为
  `6 × 150 × 3 = 2,700`，不是旧估算 2,160。

## Errors Encountered

- 直接按 `tests.test_*` 模块名运行失败：`tests/` 不是 Python package；改用 `unittest discover -s tests -p ...`。
- 重写 query builder 的一次组合 patch 在删除后未完成新增；随即用 `apply_patch` 恢复完整文件并通过 `py_compile`。
- runner 测试使用 fake retriever 时没有磁盘 `index_manifest.json`，新增 hash 读取最初触发 3 个错误；改为真实文件优先、fake manifest hash 兜底后 9 tests 全通过。
- Windows 对 `scripts/__pycache__` 无写权限导致一次 `py_compile` 报 Permission denied；同一脚本已通过 dry-run 成功导入，Phase 6 改用内存编译/`-B` 验证。
- PubMed Step 01 首次强制重建在读取数据前失败：共享 `datasets/logs/preprocess.log` 被 Windows 拒绝写入。该文件非只读且 ACL 允许修改，判断为外部进程占用；增加 `--log-file` 覆盖参数，使用独立 v19 日志重跑，不改变数据协议。
- 2026-07-31 首次同步两份顶会总表时，组合补丁因旧条目空格不匹配被
  `apply_patch` 整体拒绝；确认未写入后拆分为小补丁完成，没有覆盖历史记录。
- 2026-07-31 最终总表校验的一行 Python 命令因 PowerShell 引号转义在解析阶段触发
  `SyntaxError`；该命令未读取或写入文件，改用简单单引号表达式重跑。

## Status

**Currently in Phase 8C0** - v20 代码、CUDA、BGE/BM25/hybrid 离线门禁、
三数据集正式索引和 150-query pilot 计划均已完成；正式 API 前红队审计发现
untouched test、Reserve 角色复用、Oracle/Random、低 FPR 样本量、baseline
预算公平性、defense placeholder 和 prompt 外部有效性等 P0 风险。先关闭这些风险，
再运行 2,700-call compatibility pilot。正式 API 主矩阵尚未启动，v20 Generator
API 调用数仍为 0。

### Phase 7A：新协议 benchmark、claims 与双盲样本

- [x] 审计 Edgar/Enron/PubMed 的 processed 与 formal split 协议版本。
- [x] 从不合格阶段强制重建并冻结三个 attack benchmark。
- [x] 生成新 facts 与通过本地 validator 的 claims。
- [x] 每数据集确定性抽取 200 个 claim pair，生成 A/B 双盲模板与 manifest/hash。
- [x] 完成自动完整性验证并交付给两位真实标注者独立填写。
- [ ] 回收两位真实标注者的独立标签，计算通过率与 Cohen's κ，并通过 ≥90%/≥0.80 门禁。

说明：AI 不代替人类填写 `human_pair_valid`；“完成双人盲标”在本阶段指完成样本冻结、双盲模板与验收工具准备，真实标签回收后再运行 κ/通过率门禁。

Phase 7A 当前状态（2026-07-21）：三数据集 benchmark、facts、claims、每数据集 200 条 A/B 双盲包及自动完整性验收均已完成；未调用 API。唯一剩余项是两位真实标注者独立填写与回收，未将空标签伪装为人工结论。

### Phase 7B：人工标注期间的离线 query/index 准备

- [x] 三数据集生成 Q+/Q− paired queries。
- [x] Step 09 为每个 source 固定选择 4 pair/8 query，并通过完整性门禁。
- [x] 三数据集在分组前冻结 `stealth-passed pairs >= 4` 且 8 条 query 文本唯一的 query-eligibility whitelist，并据此重建正式上游产物。
- [x] Enron 仅用 KB_Member 构建 `sentence-transformers/all-MiniLM-L6-v2` dense index。
- [x] 生成 Enron×Qwen3.5-397B×dense 单-cell pilot 调用量、成本参数与启动门禁。

实施前决策：人工标签仍由两位真实标注者独立完成；离线准备不宣称人工门禁通过，也不得启动 victim API。`rag_config.yaml` 的 split、benchmark、query、index、response 路径统一切换到隔离的 `artifacts/v19/`，避免读取旧协议产物。Step 09 允许将同一 embedding 模型的逐条编码改为批量编码以降低运行时间，但模型、阈值、pair 级共进退、排序与固定 4 pair/8 query 定义均不得改变。

Phase 7B 错误记录：Enron Step 08 首次启动在写入 `datasets/logs/pcv_attack.log` 时遇到 Windows `PermissionError`，发生在读取 claims/生成 query 之前。处理方式是将 PCV/RAG 日志一并隔离到 `artifacts/v19/logs/` 后强制重跑，不复用任何可能的旧输出。

Phase 7B 模型加载记录：Step 09 首次模型加载长时间无输出，已核实 `HF_HOME=D:\MIA\shiyan\dataset` 中存在完整 all-MiniLM-L6-v2 snapshot；精确终止本次未写出产物的 Python 进程。后续 embedding 配置强制 `local_files_only=true` 并写入 manifest，禁止联网检查或模型 fallback。

Phase 7B 批处理错误记录：启用本地模型后，Step 09 在首个 batch 前因 `read_jsonl` 返回 generator 而 `len(query_rows)` 抛出 `TypeError`；未写出 accepted/rejected 产物。修复为 `itertools.islice` 流式分批，不预加载全部 query，评分与选择协议不变。

Phase 7B 协议修订（Step 09 实测后、任何 victim API 前）：Enron 正式 1,250 source 中仅 1,203 个在 stealth 后保留至少 4 pair，47 个不足；因此旧的 `validator-passed claims >= 4` 资格门禁不足以兑现固定八次调用。不得删除 47 个 source、不得调阈值凑数。三数据集统一升级为在无组标签候选池上执行相同 query builder + stealth filter，冻结 `stealth-passed complete pairs >= 4` 的 source whitelist/hash，再按 seed=42 重建 500/500/250 split 及所有下游正式产物。资格计算仍不读取组标签、不调用 API；旧双盲模板尚未人工填写，重建后必须覆盖生成新模板。
Phase 7B query-eligibility 进度（2026-07-21）：Enron 候选池 9,770 source，经本地 validator、paired-query builder、all-MiniLM-L6-v2 stealth 门禁后有 1,891 source 满足完整 4 pair/8 query；白名单 hash=`9c7654118c7b0531211c50fc749037cdc8f3f9d0b8673845d610fc4e98ec4f52`，足够按 seed=42 重建正式 500/500/250 split。全过程未读取未来组标签、未调用 API。
Phase 7B query-eligibility 进度（2026-07-21）：PubMed 候选池 3,666 source，经同一门禁后有 3,543 source 满足完整 4 pair/8 query；白名单 hash=`d14290a196ad3756fd17d53598c2a4a22f7a55348bd6d3d89aa0fb37b09a5e29`，足够重建正式 split。全过程未调用 API。
Phase 7B query-eligibility 进度（2026-07-21）：Edgar 候选池 1,549 source，经同一门禁后有 1,525 source 满足完整 4 pair/8 query；白名单 hash=`3ab29e44c7d04114b0f899b13f83154902aeaec44f05c1b71339d2c0933a9478`。至此三数据集均有至少 1,250 个 query-eligible source，可进入正式重建；全过程未调用 API。
Phase 7B 正式重建进度（2026-07-21）：Enron 已按 query-level 白名单完成 500/500/250 split、benchmark、facts、claims、Q+/Q− 与最终 stealth 门禁。最终恰好 1,250 source、5,000 pair、10,000 条唯一预算查询，`insufficient_sources={}`；fixed-budget plan hash=`b67bea0774287f875c90b8c50e2dc925880bc5388000c81526249c6d82b4edd4`。新的 A/B 各 200 条双盲模板已覆盖生成。
Phase 7B Enron 索引进度（2026-07-21）：已仅用 500 个 KB_Member source 的 2,009 个文档构建 `sentence-transformers/all-MiniLM-L6-v2` dense index；索引 doc_id 与 KB split 完全一致，与 True_Non_Member/Reserve 交集均为 0。环境无 `faiss`，因此使用项目内置 `json_vector_fallback`，该后端差异已写入 index manifest，未伪装成 FAISS。
Phase 7B pilot 预算进度（2026-07-21）：已确定性选择 Enron 10 KB_Member、10 True_Non_Member、5 Reserve，共 25 source/200 条唯一 query；预算为 200 RAG + 200 matched LLM-only = 400 次调用，当前 API 调用数为 0。Qwen3.5-397B endpoint/provider 单价未冻结，因此金额明确为 `unavailable`，保留成本公式及 204,800 hard output-token cap，不生成伪精确费用。

Phase 7B 批处理错误记录：启用本地模型后，Step 09 在首个 batch 前因 `read_jsonl` 返回 generator 而 `len(query_rows)` 抛出 `TypeError`；未写出 accepted/rejected 产物。修复为 `itertools.islice` 流式分批，不预加载全部 query，评分与选择协议不变。
Phase 7B 验证环境记录：对新增 pilot 脚本直接运行 `py_compile` 时，Windows 拒绝写入 `scripts/__pycache__`；脚本本身随后以 `python -B` 成功运行并生成预算。最终验证改用内存 `compile()`，不把缓存目录权限误判为语法错误。
Phase 7B Edgar Step 09 错误记录（2026-07-21）：正式 379,752 条 query 在第 3,584 条、首轮写盘前因 RTX 4060 8 GiB 上的 CUDA OOM 退出；accepted/rejected 未写出。将仅影响吞吐/显存的 `embedding_batch_size` 从 256 降为 64 后 `--force` 重跑；embedding 模型、local-only、所有 stealth 阈值、pair 级共进退、排序和每 source 固定 4 pair 均保持不变。

#### Phase 7B 协议修订（2026-07-22，实施前记录）

- 新增离线完整性审计发现：三数据集虽然均有 10,000 个唯一 `query_id`，但当前固定选择器未禁止不同 pair 产生相同的实际 query 文本；Edgar/Enron/PubMed 分别有 481/46/35 个 source 出现至少一次文本重复。
- 决策：将“每 source 恰好 8 条唯一查询”明确为 query 文本与 `query_id` 都必须在 source 内唯一，而不是只检查 ID。该门禁必须在任何 victim API 前完成。
- 修复边界：只允许在已经通过原 claim/query validator 与原 stealth 阈值的完整 pair 中，按既有质量排序确定性选择文本互异的 4 pair；不得放宽阈值、不得依据组标签或响应选择、不得手工删除 source。
- 接受条件：重新执行 Step 09 后，三个正式数据集仍须各有 1,250 source、5,000 pair、10,000 query、`insufficient_sources={}`，且每 source 的 8 个 query 文本互异；否则回到 pre-split query eligibility 重建受影响 split。
- 验证器首轮曾对重复出现的反事实实体使用全局替换而误报一个 Edgar pair；已确认正式 validator 通过前后缀对齐定位唯一变化槽位。离线验收必须复用正式 `validate_query_pair`，不得另造弱化或过强的替代判定。
- Enron 首次按新门禁重选结果：1,226 source/4,904 pair/9,808 query，24 个正式 source 仅有 3 个文本互异 pair；门禁按设计失败。下一步必须从无组标签 candidate pool 重算 query-eligibility whitelist 并重建 Enron split/下游，禁止在当前组内手工换 source。

Phase 7B 错误记录：Enron Step 08 首次启动在写入 `datasets/logs/pcv_attack.log` 时遇到 Windows `PermissionError`，发生在读取 claims/生成 query 之前。处理方式是将 PCV/RAG 日志一并隔离到 `artifacts/v19/logs/` 后强制重跑，不复用任何可能的旧输出。

#### Phase 7A 协议修订（2026-07-21，实施前记录）

- 发现：旧的 `limit` 会在 membership unit 内按 chunk 截断；改为软 chunk 上限，并新增 `source_limit`。Edgar 扫描 1,600 个 filing，获得 1,549 个有效 source。
- 发现：旧随机 Enron split 的 1,250 个 source 中仅 185 个能通过现有流水线产出至少 4 个有效 claim，无法兑现固定四 pair。
- 决策：Enron formal split 在分组前执行确定性的 source 资格门禁，要求聚合 `metadata.entity_count >= 12`；门禁与组标签无关，排除数写入 manifest。
- 决策：仅 Enron 的事实抽取使用 `max_entities_per_doc=12`、`max_facts_per_doc=8`、`guarantee_min_facts=8`，给本地 claim validator 留失败缓冲；Edgar/PubMed 保持原配置。
- 接受条件：重建后 KB_Member、True_Non_Member、Reserve 仍为 500/500/250 source，且三组各 source 均至少有 4 个通过硬门禁的 claim；否则协议修订判定失败并继续记录，不得进入 victim 调用。
- 结果：实体数代理门禁失败，重建后仅 597/1,250 source 达到 4 个有效 claim；该门禁不得作为正式定义。
- 替代决策：分组前对全部 Enron source 运行同一套本地 fact/claim/validator，冻结 `validator-passed claims >= 4` 的 source whitelist 与 hash，再从 whitelist 中按 seed=42 随机切分 500/500/250。资格计算不读取未来组标签，不调用 API；manifest 必须报告候选数、合格数和 whitelist hash。
- 一致性扩展：Edgar 仍有 13 个、PubMed 仍有 33 个正式 source 不足 4 claims，因此同一 pre-split whitelist 门禁扩展到三数据集；三者统一满足后才能冻结最终 benchmark。

## Phase 6 Completion (2026-07-21)

- [x] v19 claims/query/stealth 旧产物 resume 均增加协议一致性检查，不兼容产物要求 `--force`。
- [x] dense/BM25 索引 resume 与加载均校验 index/docstore hash，篡改时 fail closed。
- [x] baseline 策略落实为 Qwen 六个 cell 跑五种方法，其余十八个 cell 只跑 IA/DCMI。
- [x] 三个防御代表 cell 固定为 Edgar/Enron/PubMed 的 Qwen+dense；其他主 cell 不误跑 Step 14。
- [x] `llm_profiles.yaml` 未扩成四模型批量配置；Generator、Retriever 均保持 one-cell-at-a-time。
- [x] 全量 `unittest`：124 tests passed；212 个 Python 文件内存编译通过；focused ruff、YAML、diff 与 secret scan 通过。

## Phase 7B Completion（2026-07-22）

- [x] v2 query eligibility 已在无组标签 candidate pool 上完成：Edgar 1,525、Enron 1,858、PubMed 3,543 个 source 合格，均不少于正式实验所需的 1,250。
- [x] 三数据集正式 split 均为 500 KB_Member / 500 True_Non_Member / 250 Reserve，source-exclusive；全部下游 benchmark、facts、claims、Q+/Q− 与 Step 09 已按新 hash 强制重建。
- [x] 三数据集最终均为 1,250 source、5,000 pair、10,000 条 query，`insufficient_sources={}`，每 source 恰好 4 pair/8 个唯一 ID/8 条唯一文本。
- [x] 六份 A/B 双盲模板已按最终 claims 覆盖刷新；每份 200 条，A/B 样本 ID 相同、顺序不同、人工标签为空。
- [x] Enron dense index 已按最终 split 刷新，仅含 500 个 KB source 的 2,187 chunks，与所有禁入组重叠为 0；模型为 `sentence-transformers/all-MiniLM-L6-v2`，当前载体为 `json_vector_fallback`（环境未安装 FAISS）。
- [x] Enron×Qwen3.5-397B×dense pilot 已刷新：25 source、200 条 ID/文本均唯一的 query；200 RAG + 200 matched LLM-only = 400 逻辑调用；实际 API 调用 0；价格因服务商费率未冻结而标记 `unavailable`。
- [x] 独立离线验收报告状态为 `passed`；全量 `unittest` 为 139/139；219 个 Python 文件内存编译、10 个 YAML 解析、`git diff --check` 和常见密钥扫描均通过。Ruff 当前环境不可用，已如实记录为未运行。
- [ ] 外部门禁仍待完成：两位真实标注者独立填写六份文件并回收；逐数据集计算双通过率 ≥90% 与 Cohen's κ≥0.80。该门禁通过前不启动 victim API。

**当前状态（2026-07-22）**：Phase 7B 的本地技术工作全部完成；唯一阻塞项是两位真实标注者的独立标签。正式 API 矩阵、baseline 和防御实验尚未启动。

## Phase 7J：v6.3 最终提速与 Enron 容量恢复（2026-07-27）

- [x] 冻结协议变更理由与实施边界。
- [x] 实现 Enron `v6_3_precision_cascade_ranked_expandable_pool_v4` 排序、按批验证和第 1,250 个合格 source 的精确 retained-prefix 截断。
- [x] 增加独立 `--scan-config`，保持 `data_v6_3.yaml` 与 PubMed checkpoint hash 不变。
- [x] 实现 GLiNER CUDA OOM 的 `8→4→2→1` fail-closed 重试和 wave-local SQLite 缓存。
- [x] 增加协议兼容、排序确定性、精确停止/恢复、retained 过滤、缓存与 OOM 回归测试。
- [x] 运行完整 unittest、内存编译、diff 与历史 206 条决策等价性门禁。
- [x] 从 checkpoint 9 续跑 PubMed，禁止重跑已完成的九个 wave。
- [x] 冻结 Enron v4 的完整无模型排序计划及历史回放门禁。
- [x] 在独立 v4 目录完成 Enron 排序扫描；正式 retained prefix 在第 1,250 个
  query-eligible source 处结束，finalization 与正式 loader 均通过。
- [ ] 容量、promotion、RC/release 审计全部通过后冻结 v6.3，更新 README 并清理旧大型产物。

### Phase 7J 决策

- 语义模型、schema、六类阈值和 claim/stealth 门禁全部保持不变；正式 bulk 不启用 GLiNER2-base 或 spaCy transformer。
- Edgar 保留现有 v3 产物；PubMed 继续 v3；v4 只允许 Enron 使用。
- Enron 初始候选池仍为 2,500，但先按无模型、本地规则质量排序；历史只读回放在旧随机样本中覆盖 254/263 个 query-eligible source（96.58%）。
- 2,500 只作为原始 2× 优先范围，不再是必须扫描完的固定池。正式 whitelist 恰好由排序扫描得到的前 1,250 个 query-eligible source 构成，不做二次抽样。
- 为避免给一次性 eligibility 扫描引入复杂的嵌套调度，GPU 可完成当前
  250-source terminal wave；边界后的结果只能留在临时 attempt/cache。checkpoint
  同时记录 `processed_source_end` 和 `retained_source_end`，正式
  benchmark/facts/claims/queries/stealth 与 whitelist 仍只保留到产生第 1,250 个
  合格 source 的精确 source 边界。
- terminal wave 必须同时记录 `processed_source_end` 与 `retained_source_end`；finalization 只合并 retained prefix，`eligible_source_count` 必须严格等于 1,250。
- 排序只能决定正式验证顺序，不能直接放行 claim，不能读取 group label、历史 eligibility 标签或响应。
- PubMed OOM 优化只改变批处理执行方式；206 条决策等价性未达到 100% 时不得续跑正式产物。
- 旧 Enron v3、PubMed failed attempt 和临时缓存只在新产物完整冻结后清理。

### Phase 7J 错误记录

- 首次聚焦测试误用 `python -m unittest tests.<module>`；本仓库 `tests/` 不是 package，出现 2 个 `ModuleNotFoundError`。改用 `unittest discover -s tests -p <file>` 后正常执行。
- 首轮 resolver 回归发现无缓存路径也对重复文本去重，使旧审计模式的 fake backend 调用数从 2 变成 1。修复为仅启用 SQLite 缓存时去重；无缓存决策/调用语义保持不变。
- 首轮 exact-stop 测试发现 terminal batch 的全量 eligible 返回值会与 retained eligible 保留字段冲突。调度器现先冻结 processed/retained 双边界，再用 retained eligible 覆盖 checkpoint 保留字段；聚焦测试通过。
- 首次 Enron v4 plan 冻结在写入前 fail closed：配置校验返回值漏掉独立 `output_dir` 与历史回放路径，程序退回旧 v3 目录并因目录非空拒绝。没有覆盖旧产物；修复为显式保留并 hash 绑定三个 v4 路径字段后重试。
- Enron v4 plan 首次只读 resume 校验把 plan 的绝对 `output_dir` 与 YAML 相对路径误判为 drift，原因是 `**scan_config` 覆盖了解析后的路径。调整校验字典顺序，使绝对运行路径拥有最终优先级；冻结 plan/hash 本身未修改。
- PubMed checkpoint 9 续跑在约 640 chunk 触发 CUDA OOM；递归重试尚未开始时，`torch.cuda.empty_cache()` 又因异步 OOM 状态抛出 `AcceleratorError`，遮蔽了原 OOM。成功 microbatch 已写 SQLite，旧 checkpoint 未变；修复为确认 OOM 后 best-effort 清理，清理异常不得阻止 `8→4→2→1` 重试。
- Enron v4 连续完成 5 个 wave 后，第 6 个 wave 在 fact extraction 416 doc 处经
  `8→4→2→1` 仍出现 batch=1 CUDA OOM。失败文本仅 630 字符，前五个 wave 的峰值
  显存约 4.4–5.5 GB，排除“单个超长输入必然无法推理”，根因定位为长进程中
  all-MiniLM stealth runtime 与 CUDA allocator 的跨 wave 释放不充分。
- 修复为每次 stealth 完成后显式将一次性 SentenceTransformer runtime 移回 CPU、
  断开引用并清空 CUDA cache；下一 wave 开始前再次执行 best-effort GC/cache 清理。
  模型、向量、阈值和决策面不变。新增 2 个资源释放回归测试，完整 unittest 更新为
  259/259。
- Enron 恢复证据：`checkpoint_0005.json` 及前驱链全部通过 hash 验证，累计
  scanned=1,250、query-eligible=1,064；失败 wave 5 的 SQLite `quick_check=ok`，
  保留 416 条预测和 1 个 identity。恢复不得删除该 cache 或重跑前五个 wave。

### Phase 7J 当前状态

**本地实现与门禁已完成**：

- 完整 unittest 为 259/259；`src/`、`scripts/`、`tests/` 共 243 个 Python 文件
  内存编译通过；三份 v6.3 YAML 解析通过；`git diff --check` 无空白错误，仅有
  工作树既有 LF/CRLF 提示。
- 206 条固定 calibration 与自适应 batch 的 span、类型、accepted/rejected 和失败
  原因 100% 一致；已知坏例误接受=0、总体及六类 precision=1.0。等价性 identity
  hash=`fef3562f12f3bb71ab200579786dcff51c66297aa842bd732164f8f1d6490220`。
- PubMed 已从 checkpoint 9 的 SQLite 缓存安全恢复并完成第 10 个 wave：
  scanned=2,500、claim-eligible=2,150、query-eligible=2,062；
  checkpoint hash=`2e236a6d5a089f7418767969f65c1392609ec000d6652736d377b4c23b6d531c`，
  whitelist hash=`e54adc8e626f11989259d6f0e7c45c2e1501c21173118f4ef9ad53afdcd1bfeb`。
  finalization 后 wave-local prediction cache 已删除，旧九个 checkpoint 未重跑。
- Enron v4 已对 14,523 个 source 完成无模型排序并冻结：
  plan hash=`f8ed17ef292a7316fc9ef1e9bb954f2f575b255c1dc2593834dce2701ab65cdf`，
  order hash=`ff2fdcfd8004e2ab65323e857d0cedda6bec0963ac9db35b269e02cb9479f6af`，
  ranking hash=`711d2cd136fc1d846ad6ee33941ce021a19d604ec580b56a2531cf864882b2c4`；
  历史回放覆盖 254/263（96.58%），门禁通过。

**剩余工作**：执行三数据集 promotion、Enron/PubMed 新 artifact 的 RC 100 与
Release 200 审计。此前不调用 API/Retriever，不删除旧 Enron v3 或失败 attempt。

## Phase 7K：v6.3 formal promotion 与新审计（2026-07-27）

- [x] 三数据集 eligibility/finalization 通过正式 loader：Edgar=1,295、
  Enron=1,250、PubMed=2,062；容量均 passed，临时 prediction cache 均已清理。
- [x] 按冻结 eligibility 生成三数据集 source-exclusive formal split：
  每数据集固定 500 KB_Member / 500 True_Non_Member / 250 Reserve，
  Spoof_Seed=0。
- [x] 构建三数据集 formal benchmark，并从冻结 eligibility pair plan promotion
  facts/claims/queries/stealth。
- [x] 验证每数据集 1,250 source、5,000 pair、10,000 条 source 内 ID/文本唯一查询，
  所有 split/benchmark/eligibility/artifact hash 一致。
- [x] 生成 RC 100/数据集审计包；排除 RC source 后生成 Release 200/数据集审计包，
  并检查六类语义实体覆盖。Release 仅冻结模板，RC 通过前不得裁决或晋升。
- [ ] 审计通过后冻结 v6.3、更新 canonical 配置/README，并按计划清理 superseded
  Enron v3、失败 attempt 和临时大型产物。

### Phase 7K 审计抽样决定

- RC 固定 `sample_size=100, seed=6301`；Release 固定
  `sample_size=200, seed=6302`，并按 source_key/audit_id 排除同数据集 RC 样本。
- 沿用 `claim_pair_audit.py` 的 group×entity_type 确定性分层和每 source 优先一条，
  因而定向覆盖正式 claims 中实际存在的语义实体，不修改或补造正式 claim。
- promotion 后六类语义实体计数显示：PERSON/ORG/LOCATION/PRODUCT 在三数据集均存在；
  PROJECT_NAME 仅 Enron=7；CONTRACT_TERM 三数据集均为 0。后两类不足属于正式产物的
  可用性事实，必须在审计 coverage manifest 中标为 unavailable/limited，不得用
  eligibility 外样本伪装成正式 release 覆盖。

**当前状态**：formal split、benchmark、promotion、独立完整性复核和 RC/Release
抽样均已完成。RC 第一遍预审发现多种重复的明显失败模式（残句/表格或邮件污染、
结构化实体上下文误型、语义实体误型），已触发“同一失败模式出现两次即不得冻结”
门禁；Release 模板保持未填写、未裁决。下一步先做可泛化 validator/extractor 修复，
再从受影响阶段重建并重新抽取独立 RC。API=0、Retriever=0。

### Phase 7K RC 修订协议（实施前冻结）

- 新开发协议版本：`local_claim_pair_v6_3_precision_cascade_rc1`；
  extractor 版本：`attackability_v6_3_precision_cascade_rc1`。旧 promotion 与
  eligibility 因版本变化自动失效，不允许原地改标签后继续使用。
- sentence gate 只增加通用结构规则：拒绝小写残片开头、截断的金额/URL/称谓或
  单字母结尾、邮件头/quoted-printable 软换行、常见论文标题前缀、图表/名单式短句；
  不使用 dataset、source_key 或 audit_id。
- structured entity gate 增加日历日期合法性、引用/复合名称/日期中的孤立数字、
  比例或时长误作 TIME、法律/通信上下文误作 MEDICAL_VALUE、动词 `contract`
  误作 IDENTIFIER，以及数词—单位一致性。
- semantic entity gate 仅增加 schema 已定义的竞争类型表面/上下文规则：
  generic organization、generic/event/biomedical/material surface 不得作为
  PRODUCT/ORG；GLiNER2-large、BioMed veto、阈值和 schema hash 不变。
- 先对当前 RC 做只读重放并计算剩余明显失败；若仍有重复模式继续修规则，不生成
  新正式产物。规则稳定后优先复用已冻结 GLiNER 原始语义结果做本地 revalidation；
  只有 Enron 容量不足时才继续扫描排序边界后的新 source。

## Phase 7C：双盲分发前 AI 预审（2026-07-22）

- [x] 在不修改六份 A/B 文件、不填写 `human_pair_valid` 的前提下，对 600 个唯一 pair 做独立 AI 预审。
- [x] 复跑正式硬门禁，并增加仅用于预审的语义/表面风险提示；生成独立重点清单，不向正式 A/B 标注者披露。
- [x] 确认正式 A/B 文件 hash 未变化，离线结构完整性仍为 `passed`，全量 `unittest` 为 145/145。
- [x] 触发分发停止门禁：高风险 207/600（Edgar 66、Enron 91、PubMed 50），当前模板不得直接发给两位标注者。
- [ ] 在实施前冻结 validator v2 修订：至少覆盖句中/句尾截断、邮件头/编码污染、PERSON/IDENTIFIER/PROJECT_NAME 误类型、URL 尾标点、年份 numeric 子类型、冠词和数词—单位语法一致性。
- [ ] 修复后从受影响的 fact/claim 阶段重新生成三数据集资格白名单、split 下游、queries、审计模板、Enron index 与 pilot；禁止手工删坏样本。
- [ ] 对新模板再次做 AI 预审；只有明显风险率降到可接受范围后，才启动真实双人盲标。

**更新状态（2026-07-22）**：真实双人盲标暂停分发。结构门禁通过不等于 claim 语义质量通过；当前首要任务已经从“找标注者”切换为“修复 validator/extractor 并重建”。本轮未修改正式 validator 或正式产物，等待用户复查预审证据后再实施协议修订。

## Phase 7D：validator v2 协议冻结（2026-07-22，实施前记录）

- [x] 冻结实施边界：全部硬门禁继续在本地确定性完成，不调用 victim/sibling API，不读取组标签，不用人工逐条删除坏样本；AI 预审只作风险筛查，不能写入 `human_pair_valid`。
- [x] 冻结完整性门禁：claim 必须是带句末标点的完整英文陈述；拒绝固定字符窗口造成的句中/词中截断、邮件 MIME/路由头、quoted-printable 残片、异常路径元数据和不平衡结构。
- [x] 冻结实体门禁：URL 不得吞入尾部标点；IDENTIFIER 必须有完整类别前缀、词边界和含数字的结构化 payload；PERSON 采用高精度本地形态规则并拒绝章节标题、财务/法律角色和普通文档短语；PROJECT_NAME 必须完整匹配项目类型表面规则。
- [x] 冻结反事实子类型/语法门禁：四位年份只能替换为合理四位年份；时长数值与单复数单位必须一致；带定冠词地点只能替换为同冠词类别地点；替换前后继续要求同类型、不同值、单槽变化。
- [x] 冻结 fallback 边界：`guarantee_min` 只能从通过上述语义安全门禁的低分候选中补齐；残句、污染句和类型错误候选不得因覆盖率目标重新进入 facts/claims。
- [x] 冻结版本与重建边界：升级 extractor/validator 版本并写入 manifest；先在旧 600 样本上离线重放，再从标签无关 candidate pool 重算三数据集 eligibility。只有 Edgar、Enron、PubMed 各仍不少于 1,250 个 source 时，才覆盖重建正式 split 及下游产物。
- [x] 实现 extractor/validator/perturbation v2 与针对性回归测试。
- [x] 旧 600 样本离线重放，报告逐失败原因和剩余风险，不修改正式 A/B 文件。
- [x] 重算三数据集无标签 eligibility；最终 query-eligible source 为 Edgar 1,518、Enron 2,504、PubMed 3,523，均不少于 1,250。
- [x] 达标后重建正式 benchmark 下游、A/B 模板、Enron dense index 与单-cell pilot，并复跑 AI 预审。
- [x] 全量 `unittest`、离线 artifact verifier、内存编译、YAML 与 diff 检查全部通过后，才恢复真实双人盲标分发。

**当前状态（2026-07-22）**：v2 已实现，154/154 tests 通过。旧 600 条只读重放中，原模板有 253 条被 v2 正式 validator 拒绝；AI 预审剩余 high-risk 中没有 validator 漏接项。正在独立 v2 目录重算标签无关 source eligibility，实际 API 调用数保持为 0。

### Phase 7D Enron 上游协议修订（2026-07-22，实施前记录）

- 首次 v2 claim eligibility 按设计失败：9,770 个候选 source 中仅 967 个达到至少 4 条有效 claim，低于正式实验所需 1,250；因此没有覆盖正式 split、A/B、index 或 pilot。
- 根因审计发现 `FORWARD_NOISE_RE` 使用 `DOTALL + .*$`，会从 `Forwarded by`/`Original Message` 分隔线起删除余下整封转发正文；同时 `EMAIL_HEADER_RE` 漏删 `Content-Transfer-Encoding` 和 `X-*` 邮箱元数据。这会同时造成真实正文召回损失和头部污染。
- 决策：不放宽完整句、类型或反事实门禁；修复 Enron cleaner 为“只删除转发分隔行、不删除后续正文”，并删除 MIME 与 `X-*` 元数据行。该变更要求 Enron 从 Step 01 重建，旧 processed/eligibility/formal 下游不得混用。
- 接受条件：新增清洗单元测试必须证明转发正文保留、技术头删除；重建后的无标签 v2 query eligibility 仍须不少于 1,250，且新审计预审无系统性污染。若仍不足则继续 fail closed，不得改小正式 split。
- 第二个上游阻断（实施前记录）：完整 1.4GB Enron CSV 在第 18,225 条遇到 Python 默认 131,072 字符字段上限后，reader 的文件级异常处理使余下记录全部未被扫描；`enron.errors.jsonl` 明确记录该错误。修订为给可信本地 CSV 设置有界 32 MiB 字段上限，并增加“超默认长度记录之后仍继续读取”的测试。该修复不改变 membership unit、质量门禁或正式样本数。
- [x] Enron 修复后 Step 01 隔离重建完成：扫描 52,086 条原始记录，生成 30,001 个 chunk、14,528 个 source；不再出现 CSV field-limit 截断。
- [x] Enron v2 claim eligibility 通过：2,564/14,528 个 source 至少有 4 个通过本地 validator 的 claim pair，高于正式协议所需 1,250；whitelist hash=`7dade12a2080a621149dfd377e9e08fe3085a34106cd85eb877ce91d2ca7e97c`，processed hash=`15fe1f8555006266371ef315385bc6297da78691eb120cee720798a6b7b849a1`。
- [x] Enron v2 query eligibility 通过：2,504 个 source 均保留恰好 4 个 stealth-passed pair/8 条文本与 ID 唯一的 query；whitelist hash=`07bcb75d4d4d7ecdf78340d530389b0f24e35402ab198c1a3d1a8e97fe2c4b82`，fixed-budget plan hash=`efbecbc3893ad25836a573e21010eafb20d56043cd6cc4e095ec7e6475148953`。
- [x] 按相同 v2 协议逐个重算 Edgar、PubMed claim/query eligibility；三者全部达标前不覆盖正式产物。
- [x] Edgar v2 claim eligibility 通过：1,530/1,549 个 filing 至少有 4 个有效 pair；whitelist hash=`19397629f423d2f0ed2c262810a0ec8b2bf6190e257655093c70959f694dc174`。
- [x] Edgar v2 query eligibility 通过：1,518 个 filing 均保留 4 pair/8 条唯一 query；whitelist hash=`a0a348701c3687fc3931951c088edb703175e7c12bb1ae3d1d7de59da6bf81d1`，fixed-budget plan hash=`d92ff5b61fd0c3c6786174321a63f95b85537cf31fbc5f68ea4bfa4acfeaab02`。
- [x] PubMed v2 claim/query eligibility；通过后完成“三数据集各不少于 1,250 source”的正式重建前置门禁。
- [x] PubMed v2 claim eligibility 通过：3,541/3,666 篇 PMCID 论文至少有 4 个有效 pair；whitelist hash=`8bb6932f06e59e1f56e8fcba8f72758c11bcbcdf4df38fcf414c7969fcae9344`。
- [x] PubMed v2 query eligibility 通过：3,523 个 PMCID source 均保留 4 pair/8 条唯一 query；whitelist hash=`7db0de2bd201531f052d4da0c08bb5ab6ea70664e77330c75c92b1010f248117`，fixed-budget plan hash=`b1227a0099f1d85eede593605f5708f68748a9ad89a2d2c9d2af3a4204013200`。

### Phase 7D 正式 v2 输入晋升决策（2026-07-22，覆盖正式产物前记录）

- 决策：正式 Step 02 不复制或覆盖旧 Enron processed 文件，而是通过 dataset-specific `processed_path` 显式绑定 `artifacts/v19/processed_validator_v2/enron.jsonl`；Edgar/PubMed 继续使用当前 Step 01 processed 产物。
- 决策：三数据集 `source_eligibility_path` 分别绑定本轮 validator v2 的隔离 query-eligibility manifest，不将旧 v1/v2 白名单复制到同名目录。
- 理由：这能防止新旧 Enron Step 01 产物混用，同时让 split manifest 保留真实输入路径、hash、validator 版本和 whitelist hash。该变化不改变样本定义、随机种子、阈值或数量。
- 接受条件：三数据集 formal split 必须各为 500/500/250 source，且 manifest 中的 eligibility whitelist hash 必须分别为 `a0a348…bf81d1`、`07bcb7…c4b82`、`7db0de…f248117`；任一不符即停止下游。
- [x] Edgar 正式 v2 下游重建完成：500/500/250 source；benchmark=78,792 rows；facts=196,097；validator-v2 claims=187,315；最终 1,250 source/5,000 pair/10,000 query，`insufficient_sources={}`。
- [x] Enron 正式 v2 下游重建完成：500/500/250 source；benchmark=7,009 rows；facts=14,455；validator-v2 claims=13,650；最终 1,250 source/5,000 pair/10,000 query，`insufficient_sources={}`。
- [x] PubMed 正式 v2 下游重建完成：500/500/250 source；benchmark=17,382 rows；facts=31,784；validator-v2 claims=27,356；最终 1,250 source/5,000 pair/10,000 query，`insufficient_sources={}`。
- [x] 三数据集正式 benchmark/facts/claims/Q+/Q−/stealth fixed-budget 已全部按 v2 协议覆盖重建；API 调用=0。
- [x] 六份新 A/B 双盲模板已从正式 v2 claims 覆盖生成；每份 200 条、200 个不同 source，A/B ID 集合一致但顺序不同，所有人工标签为空。
- [x] 刷新 Enron `all-MiniLM-L6-v2` dense index：2,745 chunks/500 KB source，只含 KB_Member，与 True_Non_Member/Reserve 交集均为 0。
- [x] 刷新 Enron×Qwen3.5-397B×dense 单 cell pilot：25 source/200 全局文本与 ID 唯一 query，200 RAG + 200 matched LLM-only，API=0，价格=`unavailable`。
- pilot 首次刷新发现：200 个 query ID 唯一，但跨 source 实际 query 文本仅 196 个唯一；脚本却写入了含混的 `query_text_uniqueness_enforced=true`。决策是不改正式每-source 协议，仅让 pilot source 选择器确定性跳过跨-source 文本冲突，并分别报告 per-source/global 门禁；修复后必须为 200/200 文本唯一。
- [x] 对新 A/B 模板复跑 AI 预审，不写入人工字段；结果为 8 high-risk / 23 needs-review / 569 low-risk。
- [x] 完成全量 unittest、离线 artifact verifier、内存编译、YAML、diff 和密钥扫描。

### Phase 7D 最终验收（2026-07-22）

- [x] `verify_v19_offline_artifacts.py`：`status=passed`，三数据集的 split/query/audit/index 边界均通过。
- [x] 全量 `unittest`：161/161 通过；224 个 Python 文件内存编译通过；10 个 YAML 解析通过。
- [x] 本轮相关文件 focused Ruff 通过；`git diff --check` 无空白错误（仅 CRLF 警告）；252 个代码/配置文件常见密钥扫描 0 命中。
- [ ] 外部人工门禁：两位真实标注者独立填写六份新 A/B 文件，回收后逐数据集计算双通过率与 Cohen's κ。

**当前状态（2026-07-22）**：新 validator v2 的所有本地技术工作已完成，可恢复真实双人盲标分发；人工门禁通过前仍不启动 victim API。

## Phase 7E：负责人复核后的明显问题修复（2026-07-22，实施前记录）

- [x] 负责人只读复核 AI 预审重点清单；该复核不是 A/B 双人盲标，不写入 `human_pair_valid`，负责人后续只作裁决者。
- [x] 冻结修复边界：拒绝明显的 PERSON/PROJECT_NAME 误类型、跨从句标点或连接词的命名实体边界、`order 6shots` 一类把上下文前缀与粘连词一起吞入的槽位，以及明显列表/标题残片。
- [x] 冻结保留边界：字母数字混合本身不构成失败；合法 PDB ID、案件号、产品号、文件号等只要前缀、payload、边界与类型正确，仍可通过。单纯 claim 较长也不构成失败，只有截断、结构异常或非完整声明才拒绝。
- [x] 为上述明确模式增加回归测试，并最小修改本地 extractor/validator；升级协议版本，所有失败继续保留稳定 `validation_failure_reason`。
- [x] 在旧 600 条模板上只读重放，确认明显问题被正式门禁拒绝，同时统计新增拒绝原因与可能误杀；不修改 A/B 标签。
- [x] 从受影响阶段重新计算三数据集 claim/query eligibility，并确认三者均不少于 1,250 source。
- [ ] 按 source-exclusive 500/500/250 重建正式 split、claims、queries、Step 09、A/B 模板、Enron dense index 与 pilot。
- [ ] 复跑 AI 预审、离线 artifact verifier、全量 unittest、内存编译、YAML、diff 与密钥检查；通过后才恢复真实双人盲标分发。

**当前状态（2026-07-22）**：针对性测试已通过；旧 600 条只读重放由 v3 拒绝 23 条（Edgar 10、Enron 4、PubMed 9）。三数据集 v3 claim/query eligibility 已在隔离目录重算并全部超过 1,250-source 门槛，正式配置已显式切换到 v3 whitelist；下一步从 Step 02 重建 source-exclusive 正式下游，实际 API 调用保持为 0。

### Phase 7E 正式 v3 输入晋升决策（2026-07-22，覆盖正式产物前记录）

- Edgar v3 claim/query eligibility 分别为 1,529/1,517 source；query whitelist hash=`77636212db5b9595b42314bd9d9ca27f13f20f29d55f18b2927797650c128cca`，fixed-budget plan hash=`3b6ea2648e9a92c727aef5b904ae8be46459dbb167fdc9936374744b6c84e323`。
- Enron v3 claim/query eligibility 分别为 2,520/2,465 source；query whitelist hash=`92a4afae18dfbb996ec07f2e5b57795b8e854a5ce32e32602d47e6b8a22ed17d`，fixed-budget plan hash=`98b7822f0d10209506c47f262a52f6da3e9c9c02fade50684a5649caa3436e1d`。
- PubMed v3 claim/query eligibility 分别为 3,538/3,521 source；query whitelist hash=`3f103261de8bcfe13918df8585659f4754849660748eac0e26040eedac6ee952`，fixed-budget plan hash=`3c63adda9de13932a1b5b64934dedcbb56e0e14d57c23359f030e7bd1700f446`。
- 决策：`configs/data_config.yaml` 的三个 `source_eligibility_path` 显式晋升到各自 v3 隔离目录；Enron processed 仍绑定已修复并冻结 hash 的 `processed_validator_v2/enron.jsonl`，因为本轮没有改 Step 01 cleaner 或 membership unit。
- 接受条件：Step 02 必须从上述 v3 whitelist 各确定性切分 500 KB_Member、500 True_Non_Member、250 Reserve，保持 source-exclusive；任一 manifest 的 whitelist hash、数量或版本不符即停止，不得继续下游。

### Phase 7E v4 补充修订（2026-07-22，实施前记录）

- v3 正式模板预审为 1 high-risk / 18 needs-review / 581 low-risk；唯一 high-risk 是 `Supplementary Figure` 被标为 PERSON，另有 `Program At` 被标为 PROJECT_NAME 并以介词结尾，二者均为确定性类型错误。
- [x] 将章节/图表词 `supplementary`、`figure` 纳入 PERSON 高精度拒绝词，将 `at` 纳入 PROJECT_NAME 通用连接词尾门禁，并升级 extractor/validator 与 eligibility 协议到 v4。
- [x] focused tests 22/22 通过；对当前 600 条模板只读重放仅新增拒绝上述两条 PubMed 样本，Edgar/Enron 新增拒绝为 0。
- [x] 在隔离目录重算三数据集 v4 claim/query eligibility；三者均不少于 1,250 source，正式配置已从 v3 晋升到 v4。
- [ ] 从 Step 02 覆盖重建最终正式下游、空白 A/B、Enron dense index 和 pilot；复跑预审与完整验收后恢复真实双盲分发。

**v4 当前状态（2026-07-22）**：标签无关 eligibility 与容量门禁已通过，正式配置已显式晋升 v4；下一步从 Step 02 强制重建最终正式下游，API 调用保持为 0。

### Phase 7E 正式 v4 输入晋升决策（2026-07-22，覆盖正式产物前记录）

- Edgar v4 claim/query eligibility 分别为 1,529/1,517 source；query whitelist hash=`77636212db5b9595b42314bd9d9ca27f13f20f29d55f18b2927797650c128cca`，fixed-budget plan hash=`6dea9a226014b1920077d47e4825bc5eac47526e771630a0b74d14ff1d4182f9`。
- Enron v4 claim/query eligibility 分别为 2,520/2,465 source；query whitelist hash=`92a4afae18dfbb996ec07f2e5b57795b8e854a5ce32e32602d47e6b8a22ed17d`，fixed-budget plan hash=`98b7822f0d10209506c47f262a52f6da3e9c9c02fade50684a5649caa3436e1d`。
- PubMed v4 claim/query eligibility 分别为 3,538/3,521 source；query whitelist hash=`3f103261de8bcfe13918df8585659f4754849660748eac0e26040eedac6ee952`，fixed-budget plan hash=`6e6df8cff8be99d7c62d9f02e2a446eea383958e120aa73309497bc585cff11b`。
- 三套 query whitelist 均超过正式 1,250-source 门槛；`configs/data_config.yaml` 只切换 eligibility manifest 路径，不改变数据集、membership unit、500/500/250 数量、随机种子、stealth 阈值或 Enron frozen processed 输入。
- 接受条件：Step 02 必须各生成 500 KB_Member、500 True_Non_Member、250 Reserve，source-exclusive，并在 manifest 中绑定 v4 protocol/version 与上述 whitelist hash；任一不符立即停止下游。

### Phase 7E v5 表格化残片补充修订（2026-07-23，实施前记录）

- v4 正式 A/B 预审为 0 high-risk / 15 needs-review / 585 low-risk；复核 needs-review 发现 2 条确定性失败，均来自 PubMed：一条把多个疫苗平台与机构列串接成声明，另一条包含 `Topic:`、大量百分比列并截断在 `Wednesday, Sept.`。
- [x] 冻结修复边界：新增窄范围、本地确定性的 `claim_tabular_fragment` 门禁；只拒绝带明确列头/密集统计列或多类别、多斜线串接的表格化文本，不以长度本身拒绝正常完整声明。
- [x] 升级 validator 与 eligibility 协议到 v5，增加“两条坏样本拒绝 + 合法长句/ID/机构声明保留”的回归测试；focused unittest 24/24 通过。
- [x] 对当前 600 条模板只读回放；新增拒绝严格为上述 2 条 PubMed 样本，Edgar/Enron 新增失败均为 0。
- [x] 在隔离目录重算三数据集 v5 claim/query eligibility；三者均不少于 1,250 source 后才晋升正式配置。
- [x] 从 Step 02 重建统一 v5 正式 benchmark/claims/queries，刷新空白 A/B 与 v5 AI 预审。
- [x] 用 v5 Enron split/queries 刷新 dense index 和 pilot，并复跑完整离线验收。

**v5 当前状态（2026-07-23）**：v5 协议、正式 benchmark/claims/queries、A/B 模板与 AI 预审已冻结；v5 Enron index/pilot 和本地技术验收已完成，v6 修复已取消且从未实现。下一步只剩真实双人盲标门禁，API 调用保持为 0。

### artifacts 旧版本清理（2026-07-23）

- [x] 只读盘点 `artifacts/v19` 及当前配置引用；确认当前 formal 输入只依赖三个 v5 eligibility 目录与 `processed_validator_v2/enron.jsonl`。
- [x] 删除已被 v5 取代的 legacy/v2/v3/v4 eligibility 候选池、v1–v4 AI 预审副本和重复的 v2 离线报告；18 个精确目标全部删除，释放约 17.27 GB。
- 保留：三个 v5 eligibility、当前正式 split/benchmark/facts/claims/queries/index/audit、当前 v5 预审、仍被 Enron 配置引用的 `processed_validator_v2`，以及体积极小但有审计价值的历史日志。
- [x] 删除后核验：`artifacts/v19` 从约 24.40 GB 降至约 7.13 GB；所有当前配置引用与正式 v5 核心产物存在，`data_config.yaml` 解析通过。

- 测试错误记录：首次 focused unittest 为 24 tests / 1 failure；统计表测试约 30 个词，被共享的 35 词前置阈值挡住。修正为列头+至少 6 个百分比单元分支独立要求至少 20 词，多类别/多斜线分支继续要求至少 35 词；失败发生在产物重建前。
- 配置错误记录：首次 v5 Edgar Step 02 在读取 YAML 时退出；晋升三条 `source_eligibility_path` 时误多缩进 2 个空格，未写出 split。已把三条路径恢复到 dataset 字段的同级 4 空格缩进，并在重跑前独立执行 YAML 解析。

### Phase 7E 正式 v5 输入晋升决策（2026-07-23，覆盖正式产物前记录）

- Edgar v5 claim/query eligibility 分别为 1,529/1,517 source；claim whitelist hash=`61008b0ce07a0f9209c5433b17915df7423be1e7621af8e299886c5667374014`，query whitelist hash=`77636212db5b9595b42314bd9d9ca27f13f20f29d55f18b2927797650c128cca`，fixed-budget plan hash=`72381e6faa9224fd9173acbbf1b76b7ec5df5d2832c31575408c4b6b6f88fca2`。
- Enron v5 claim/query eligibility 分别为 2,520/2,465 source；claim whitelist hash=`d9502bf0968abf89685dadd162635b86ac9bff2f99e9f138afff9c0bc174e835`，query whitelist hash=`92a4afae18dfbb996ec07f2e5b57795b8e854a5ce32e32602d47e6b8a22ed17d`，fixed-budget plan hash=`7744758ef6cae79dc05af03143544817cd54e6570fa4a3d3833074b42ffa68fb`。
- PubMed v5 claim/query eligibility 分别为 3,538/3,521 source；claim whitelist hash=`09bcfc3d8fb8cf81591f9e734571eafe2b845f597e8a6c5a517d1f5fd5187de0`，query whitelist hash=`3f103261de8bcfe13918df8585659f4754849660748eac0e26040eedac6ee952`，fixed-budget plan hash=`df824fdc683251e6b229212571ce80794e87ba4b9635b5f508a79802a7f762aa`。
- 三套 query eligibility 均记录 `sentence-transformers/all-MiniLM-L6-v2`、`local_files_only=true`、每 source 8 query 且文本唯一，容量均超过正式所需 1,250；全程未调用 API。
- 决策：仅将 `configs/data_config.yaml` 的三条 `source_eligibility_path` 从 v4 隔离目录切到对应 v5 隔离目录；不改变 processed 输入、membership unit、500/500/250 数量、随机种子、stealth 阈值或 Retriever。
- 接受条件：Step 02 必须各生成 500 KB_Member、500 True_Non_Member、250 Reserve，source-exclusive，并绑定 v5 protocol/version 与上述 query whitelist hash；任一不符即停止下游。
- [x] v5 Step 02 完成并独立核验：Edgar、Enron、PubMed 均为 500/500/250 source，三组实际 `source_key` 两两交集为 0；manifest 均绑定 v5 query protocol、`local_claim_pair_v5` 与预期 whitelist hash。
- 只读核验错误记录：首个脚本误以为 split manifest 有 `source_ids`，随后又误以为 JSONL 顶层有 `source_key`；两次均仅报 `KeyError`、未修改产物。最终从实际字段 `metadata.source_key` 完成三数据集交叉验证。
- [x] Edgar v5 Step 05–09 完成：benchmark=78,888 rows，facts=195,479（errors=0），claims=185,884（validator failures=9,595），queries=371,768（errors=0）；最终 1,250 source/5,000 pair/10,000 query，source 内文本与 ID 全部唯一，`insufficient_sources={}`，plan hash=`6eb671f8610b1b395ead834c4becca58adcf4cd7feefd6bcff929c944f81e730`。
- 运行记录：Edgar Step 07 的进度输出通道在脚本仍运行时关闭；未重启或并行写入，而是等待原进程结束，并通过新 manifest 时间、`claim_validator_version=local_claim_pair_v5` 与计数确认成功。
- [x] Enron v5 Step 05–09 完成：benchmark=6,777 rows，facts=13,980（error file=0），claims=12,955（validator failures=1,025），queries=25,910（errors=0）；最终 1,250 source/5,000 pair/10,000 query，source 内文本与 ID 全部唯一，`insufficient_sources={}`，plan hash=`fe44b2682ec6729335acbeec33af963a43e3ddc67ca1a213bbf14110461d6ead`。
- [x] PubMed v5 Step 05–09 完成：benchmark=17,213 rows，facts=31,037（errors=0），claims=26,746（validator failures=4,291，其中 8 个 pair 命中表格残片门禁），queries=53,492（errors=0）；最终 1,250 source/5,000 pair/10,000 query，source 内文本与 ID 全部唯一，`insufficient_sources={}`，plan hash=`c428c37acb7347e7f13b91caee948c2122946cc220df1c794896f1b316105d31`。
- [x] 三数据集统一 v5 benchmark/claims/Q+/Q−/固定预算 query 已全部强制重建；已确认旧预审中的两个 PubMed 坏 pair ID 均不在新正式 claims 中，API 调用=0。

### Phase 7E v5 正式冻结决议（2026-07-23）

- [x] 取消 v6 修复：截至本决议没有 v6 代码、配置或 artifact；后续不得把 v5 审计样本作为继续调规则的开发集。
- [x] 完成两条新 PubMed 表格残片的影响审计：二者均因 `low_naturalness` 未进入主 accepted queries，受影响 source 仍各有 4 pair/8 条唯一查询，主实验影响为 0。
- [x] 量化残余影响：无 stealth filter 控制为 2/26,746 pair（0.007478%）；人工审计为 PubMed 2/200（1%）、全体 2/600（0.33%）。该量级不足以单独触发新 validator 版本。
- [x] 创建 `研究记录/v5正式冻结清单.md`，登记协议、canonical 计数、核心 artifact/hash、已知残差、解冻条件和冻结后门禁。
- [x] 用 v5 split/queries 重建 Enron dense index 与 pilot，并完成离线 verifier、全量 unittest、内存编译、YAML、Ruff、diff/hash 与密钥验收。
- [ ] 回收两位真实标注者独立填写的六份 A/B 文件，逐数据集验证双通过率 >=90%、Cohen's kappa >=0.80。
- [ ] 仅在本地技术验收和真实双盲门禁均通过后，逐个 Generator、逐个 Retriever 启动正式 API 矩阵。

**冻结状态**：`local_claim_pair_v5` 是唯一正式协议；v6 已取消。两条 PubMed 残差原样保留为诚实审计结果，不手工删除、不修改 A/B，也不进入主 accepted query 集。

本地技术验收结果（2026-07-23）：

- Enron index：当前 v5 KB hash=`4361efa3fc74ba5b32326e7078f7fdd8ad0dd4f4e0b6b5fd67259ce5e5b42577`，2,842 个 KB_Member 文档，doc ID 精确匹配，禁止组交集=0；retriever=`sentence-transformers/all-MiniLM-L6-v2`，storage backend=`json_vector_fallback`，index hash=`b501b6f4bd56111ecef5f0cbf80665c66bf3c223880746fa4d150bcc87163472`。
- pilot：25 source/200 query，10/10/5 分组，每 source 4 pair/8 query，全局 ID/文本唯一；200 RAG + 200 matched LLM-only=400 调用预算，实际 API=0，queries hash=`7a090d809c641b3bd29a13416152827ec6e8ad904b47f59e3d4a90582f7125bb`。
- 离线报告 `status=passed`，hash=`e71ce95ba8d16fa33497244db95d8cf81bc6e8e2ac37877a52bd301316692dc3`；focused tests 5/5、全量 unittest 171/171、内存编译 224/224、YAML 10/10、相关 Ruff、diff/hash 与 223 文件密钥扫描均通过。
- 人工门禁仍为 pending：当前 Edgar A 有 5/200 条 `pass`，其余五份未填；不得据此提前计算双通过率或 κ。

本轮只读检查错误记录：

- 首次一致性检查中的 Python 正则引号被 PowerShell 提前解析，命令未执行、文件未修改；随后改用无正则的分步检查。
- 首次 manifest 汇总假定存在顶层 `protocol_version`/`validator_version` 字段，实际版本位于 `protocol`、`claim_validator_version` 和 `claim_eligibility`；只产生 `None` 输出，未修改文件。
- 第二次汇总误把 split manifest 的逐 source `hashes` 当成 benchmark SHA256 字段并触发 `KeyError`；随后直接对正式文件执行 SHA256，核验结果与既有 benchmark 记录一致。
- 查看 split `hashes` 时误输出了完整逐 source 哈希列表并被终端截断；这是只读输出噪声，不影响任何 artifact。
- 核验两个 PubMed source 的 accepted query 文本时首次误用不存在的 `query_text` 字段并触发 `KeyError`；改用真实字段 `query` 后确认二者均为 4 pair/8 条唯一查询。
- 第一次运行更新后的官方 verifier 在 `edgar annotator A hash drift` 停止；诊断确认 A 文件已有 5 条合法人工 `pass`，原逻辑错误地把任何人工字段填写都视为整文件篡改。已改为只在内存清空三个人工字段后核对原始模板哈希，A/B 和 manifest 均未修改。
- verifier 回归测试首次同时修改 A/B 的“第 1 行”，但盲化顺序不同，实际命中了两个不同 audit ID，因而提前触发正确的 A/B content drift。测试随后改为按相同 `audit_id` 定位，focused 5/5 与全量 171/171 均通过。

### Phase 7F AI 辅助逐条裁决（2026-07-23）

- [x] 保留六份 A/B 原始文件和 manifest，不覆盖、不把 AI 判断写入 `human_pair_valid`。
- [x] 对 Edgar、Enron、PubMed 各 200 条，共 600 个唯一 claim pair 逐条复核并给出 `pass/fail`。
- [x] 新增可重放脚本 `scripts/adjudicate_claim_pair_audit.py`，校验每数据集 200 条、A/B ID 集一致、机器字段一致、失败决策无重复且不存在未知 ID。
- [x] 生成 `artifacts/v19/audits/claim_pair_ai_adjudication/`：三份逐条 JSONL、`FAILURE_REVIEW.md`、`README.md` 和 `summary.json`。
- [x] 裁决结果：Edgar 100/200 pass，Enron 88/200 pass，PubMed 111/200 pass；总计 299 pass、301 fail，三个数据集均低于原定 90% claim-pair 通过率门槛。
- [x] 失败主因：实体语境类型或边界错误 165 条，claim 残片/截断 119 条，邮件/编码/异常结构污染 17 条。
- [x] 六份 A/B 原文件 SHA256 与裁决前快照一致；离线 verifier 继续通过，API 调用为 0。
- [ ] 不得把本轮结果表述为“两位真人独立盲标”或用它计算 Cohen’s κ；论文和 artifact 只能写作 `AI-assisted adjudication`。
- [ ] 暂停正式 victim API。301/600 的系统性失败要求先修复候选实体语义/边界和声明完整性门禁，再从受影响阶段重建并重新抽样审计。

**协议状态**：用户因标注资源限制授权 AI 完成最终裁决，但这不追溯改变原双人盲标定义。`local_claim_pair_v5` 的既有文件继续保留为冻结证据，不能再被视为已通过投稿质量门禁。

### Phase 7G v5 解冻与 v6 混合抽取协议（2026-07-23）

- [x] 记录解冻理由：AI 辅助逐条裁决发现 301/600 系统性失败，三个数据集均低于 90%。
- [x] 创建 `研究记录/v6协议修复计划.md`，冻结模型角色、数据使用边界、实施顺序和接受标准。
- [x] 将旧 600 条及其裁决降级为开发诊断集；禁止继续用作 v6 独立验收集。
- [x] 确认本机已有 spaCy 3.8.13 与本地 `en_core_web_sm` 3.8.0；无需 API 或下载。
- [x] 实现规则 + 本地 NER 混合实体抽取，并冻结模型元数据。
- [x] 实现结构化实体上下文、span 边界、合同术语子类型和声明完整性门禁。
- [x] 完成通用回归测试、旧样本诊断回放和误拒绝分析。
- [x] 在实施前冻结 v6.1 eligibility probe：每 source 按 seed=42 的内容哈希最多抽取
  4 个 chunk；该 cap 不改变正式 source membership unit 或下游全 chunk 保留规则。
- [x] 将本地 spaCy NER 接入批处理；逐条与预计算 NER 输出等价测试通过。
- [x] 重算 v6 eligibility，确认三数据集容量均超过正式切分所需 1,250 source。
  - [x] Edgar：1,516 claim-eligible、1,339 query-eligible source，容量门槛通过。
  - [x] Enron：5,901 claim-eligible、5,301 query-eligible source，容量门槛通过。
  - [x] PubMed：3,570 claim-eligible、3,472 query-eligible source，容量门槛通过。
- [x] 将三数据集 `source_eligibility_path` 从 v5 晋升到已验证的 v6.1 query whitelist。
- [x] 用 v6.1 whitelist 重建三数据集 Step 02；每个数据集均为 500/500/250 source，三组交集为 0。
- [ ] 按 v6.1 冻结计划重建三数据集正式 benchmark/claims/queries；不运行 Retriever 或 API。
  - [x] 冻结晋升规则：正式 source 只使用 eligibility 中已经选定的 4 pair/8 query，不再次扫描全 source 或二次重选。
  - [x] 实现并测试 eligibility plan → formal artifact 的确定性晋升脚本；focused 3/3、全量 202/202。
  - [x] Edgar、Enron、PubMed 依次晋升并通过哈希、分组、预算和完整性门禁。
- [ ] 生成来源不重叠的新 600 条审计集并完成 AI-assisted adjudication。
  - [x] v6.1 第二轮审计模板生成并确认与 v5 旧审计 source/audit ID 零重叠。
  - [x] 语义敏感类型复核发现系统性误型；v6.1 审计不得判为通过，降级为开发诊断集。
  - [x] 实现 v6.2 元数据语义门禁并通过 validator 定向测试。
  - [x] 按 probe cap=5 重建三数据集 v6.2 eligibility artifacts。
  - [x] 切换 v6.2 白名单并重建三数据集 formal artifacts。
  - [x] 排除前两轮 source，生成第三套独立 600 条审计；结构与互斥门禁通过。
  - [x] v6.2 第三轮审计发现语义误型及结构化边界错误，降级为开发诊断集。
  - [ ] 实现 v6.3 structured-precision canonical 门禁并重建正式产物。
  - [ ] 排除前三轮 source，生成第四套独立 600 条审计并完成 AI-assisted adjudication。

**当前状态**：v6.2 第三轮审计发现 `$63,000,` 尾逗号、quoted-printable 软换行 URL、
电话号码/关节角度误作日期、`contract COVID-19` 误作编号，以及通用 NER 的语义误型。
v6.2 不得冻结。容量评估确认仅使用结构化实体时三数据集仍有至少
1,415/2,258/3,128 个 source 可提供 4 条 claim，因此升级 v6.3 structured-precision
canonical。在第四轮新审计完成前，不运行 victim API。

### Phase 7H v6.3 开放语义共识协议（2026-07-24）

- [x] 冻结 `local_claim_pair_v6_3_open_semantic_consensus`：保留全部实体类型，
  撤销“六类语义实体退出 canonical”的旧草案。
- [x] 建立本地 `SemanticEntityResolver`，支持 GLiNER2、transformer NER、
  PubMed biomedical veto、竞争类型、边界校正、置信度 margin 与 fail-closed。
- [x] 构建历史语义开发集，自动比较 base/large 与共识方案；总体 exact precision
  >=97%、每类型 >=95%、已知坏例误接受=0。
- [x] 将语义解析结果接入 extractor、counterfactual 和 claim validator；替换后的
  反事实必须再次通过相同类型/子类型验证。
- [x] 增加全部 v6.2 明确坏例、模型冲突、span 修正、模型缺失、固定预算和 source
  隔离测试；通过完整 unittest 与离线完整性验证。
- [ ] 按 cap `[5, 8, 12]` 依次构建独立 v6.3 eligibility，选择满足 1,250 source
  的最小 cap，不降低 stealth 门槛。
- [ ] 重建三数据集 v6.3 formal split/benchmark/facts/claims/queries；Retriever/API
  保持未运行。
- [ ] 完成每数据集 100 条 RC 审计；问题修复后使用新 source 重建。
- [ ] 规则冻结后完成每数据集 200 条 release 审计和六类语义实体定向复核；每数据集
  通过率 >=95%、语义类型通过率 >=95%、双遍一致率 >=98%。
- [ ] 全部门禁通过后切换配置、标记 v6.2 superseded、更新 README、清理临时/RC
  大型产物并重建失效的 Enron dense index。

**当前状态**：v6.3 本地语义解析器、模型锁、counterfactual 复检与开发阈值选择已完成；
206 条开发样本误接受为 0，总体及每类 exact precision 均为 100%。正在运行完整测试并
准备 cap `[5, 8, 12]` eligibility probe。正式 API 调用仍为 0；在 release 审计通过前
不得冻结或切换 canonical 配置。

#### Phase 7H 实施进度（2026-07-24）

- [x] 实现 `SemanticEntityResolver`，保留 PERSON、ORG、LOCATION、PRODUCT、
  PROJECT_NAME、CONTRACT_TERM 全部正式实体类型。
- [x] 锁定 GLiNER2 base/large、`en_core_web_trf==3.8.0` 与 PubMed BioMed veto
  的 exact revision、运行时版本和逐文件 SHA-256；缺失或漂移时 fail closed。
- [x] 接入边界共识、目标/竞争类型、置信度 margin、稳定失败原因和 PubMed 生物实体否决。
- [x] counterfactual 保持 subtype/format，在替换后重新解析，并拒绝出现在原完整 source
  中的反事实实体。
- [x] 使用 206 条 AI-assisted 开发样本扫描 672 组阈值；36 组通过门禁，冻结最保守的
  最小阈值组合：0.55/0.05/2/2/BioMed 0.90。
- [x] 开发集总体 precision=1.0、六类 precision=1.0、已知坏例误接受=0、修复坏边界=6；
  未触发本地微调。
- [x] 完整 unittest、历史坏例回放和模型 hash/load smoke test 最终验收。
- [ ] 创建独立 v6.3 配置，依次执行 cap 5/8/12 probe 并选择满足三数据集各 1,250
  source 的最小 cap。

执行记录：2026-07-24 首次 Edgar v6.3 Step 01 在约 1,365/1,600 个 filing 时按用户
指令停止；进程已终止，未生成有效 preprocess manifest，残留 JSONL 仅为临时文件。
恢复时必须使用 `--force` 从头覆盖，不得 resume 或晋升该临时产物。

- [x] v6.3 Step 01 从原始输入完整重建三数据集 processed：
  Edgar=1,549 filing/97,051 chunks，Enron=14,523 complete email/30,000 chunks，
  PubMed=3,666 PMCID article/50,011 chunks；均有独立 manifest，旧成员产物未复用。
- [x] 冻结正式本地推理运行身份：GLiNER2 base/large 与 PubMed BioMed veto 使用
  CUDA FP16，`en_core_web_trf` 使用 CPU，batch=8；模型权重/revision/schema/阈值不变。
- [x] 在最终 CUDA FP16 运行身份下强制重跑 206 条历史开发集：36 组阈值通过，
  false accept=0、总体及六类 precision=1.0，选中阈值与 CPU FP32 完全一致。
- [x] fact 抽取与 counterfactual 二次语义复检均改为冻结等价的 batch 推理；
  `resolve_candidate` 复用预计算预测，不重复调用模型。针对性 resolver 14/14、
  claim validator 39/39 通过；一次测试命令因 `tests/` 非 package 未执行，改用
  `unittest discover -p` 后通过。
- [x] 将 v6.3 本地语义依赖合并到主 `requirements.txt`：固定
  `gliner2[local]==1.3.2`、`gliner==0.2.27` 和
  `en-core-web-trf==3.8.0` wheel；删除独立 `requirements-semantic-v6_3.txt`，
  11 条有效 requirement 均通过语法解析。
- [x] Edgar v6.3 cap=5 eligibility 完成：1,549 filing/7,588 probe chunks/
  17,835 facts；claim-eligible=1,391、query-eligible=1,294，均达到 1,250，
  故最小 cap 冻结为 5。query whitelist hash=
  `9afe365f6d5e334f9eab0f096690659d3247cc788e73db70e59322efb40a7e9c`，
  fixed-budget plan hash=
  `69d5d420fcb4ed3d68777f0e306f769eee88f8c97ff26b0eee782a99d9681b4e`。

## Phase 7I：账号切换与 precision cascade（2026-07-25）

协议修订理由已在实施前记录：旧
`local_claim_pair_v6_3_open_semantic_consensus` 对每个 chunk 运行 GLiNER2
base/large 和 CPU `en_core_web_trf`，PubMed 再加 BioMed，运行成本与“高精度抽取并
获得至少 1,250 个 source”的目标不匹配。用户同意改为
`local_claim_pair_v6_3_precision_cascade`；该 ID 目前是开发协议，门禁全部通过前
不得切换 canonical。

- [x] 创建 `研究记录/v6_3账号切换交接.md`，冻结可复用产物、失效产物、Git 状态、
  新协议和新账号首条指令。
- [x] 核验旧 Enron 三模型任务已停止：GPU=0、无 Python 进程，目录仅有
  `enron_candidate_benchmark.jsonl`，没有有效 facts/claims/eligibility manifest。
- [x] 将旧 Edgar cap=5 eligibility 标为 `development_only_superseded`；
  只保留三个独立 Step 01 processed 及其 manifest/hash 可复用。
- [x] 新账号完成阶段 A 只读接管：完整阅读交接材料，保留全部 staged/unstaged/untracked
  改动；GPU 复核为 0%/0 MiB，短暂观察到的 Python PID 46924 未经干预自行退出，最终
  复核无 Python 进程；三个 Step 01 processed 实际 SHA-256 与交接记录一致，旧 Enron
  目录仍只有 candidate benchmark。
- [x] 修改 v6.3 配置与 resolver：结构化规则不变；六类语义实体正式 bulk 只运行
  GLiNER2 large；PubMed BioMed 只检查候选句；base/spaCy 仅用于审计/消融。
- [x] 在 206 条开发/历史坏例上重新校准单模型阈值：总体 exact precision ≥97%、
  每类 ≥95%、已知坏例误接受=0；旧三模型阈值不得直接沿用。
  - [x] 完成 CUDA FP16、batch=8 的第一轮 large-only 推理及 540 组全局标量阈值扫描；
    206 条输入与三份 raw prediction/hash 已冻结，但没有全局阈值同时通过全部门禁。
  - [x] 将 decision surface 改为按六类实体冻结 target/margin 阈值并纳入 hash，
    复用第一轮 raw predictions 离线重算通过：overall/per-class precision=1.0、
    false accepts=0、true accepts=68，selected threshold hash=
    `d180bdb02d5bcb5748cfac64b955ecc307b37022671c0200a35a50d0394edfa8`。
- [x] 在隔离的 `configs/pcv_attack_v6_3.yaml` 写入完整六类阈值、通过摘要路径和
  threshold hash，并冻结 `thresholds_frozen=true`；真实 YAML 经 injected formal
  loader 核验，Enron 只选 large、PubMed 只选 large+BioMed。canonical 未切换。
- [x] 增加 cascade 路径、候选句 BioMed veto、显式三模型审计模式、阈值 hash 漂移
  fail-closed 单元测试；resolver、claim validator、local NER、eligibility、promotion
  与人工审计相邻聚焦测试共 93 个用例通过。
- [ ] 在阈值冻结与分波 orchestrator 完成后运行完整 unittest。
- [ ] 实现 seed=42 的无标签稳定 source 排序、分波 checkpoint 和预注册的
  1,300 query-eligible source 停止规则；manifest 绑定扫描前缀与全部 hash。
- [ ] 在新协议独立目录依次重建 Edgar、Enron、PubMed eligibility；不得复用旧
  Edgar 下游产物或续跑 Enron 部分文件。
- [ ] 通过 RC 100/数据集和 Release 200/数据集审计后，才切换 canonical、更新
  README、清理 superseded 大型产物，并开始 Retriever/单 cell API pilot。

当前停止点：precision cascade 代码、按类阈值校准和隔离配置冻结已通过，schema hash 保持
`1e50ffc451e01f85d64e5013bf4e76de5e462c5ca6ed0e445fccdb8bd9e1ffeb`，selected
threshold hash 为 `d180bdb02d5bcb5748cfac64b955ecc307b37022671c0200a35a50d0394edfa8`。
下一步实现 seed=42 的无标签稳定排序、完整分波 checkpoint 与 1,300 query-eligible
预注册停止规则，只运行 synthetic/focused tests，不启动全量扫描。没有 Retriever/API
或 canonical 切换，不得继续旧三模型命令。

## Phase 7J：precision-first wave scan v2（2026-07-26）

实施前协议修订：旧 v1 的 1,300-source 目标使用任意 50-source buffer，却没有保证这
50 个 source 能覆盖正式 splitter 的完整 source 去重。v2 改为在冻结 source 顺序前
直接复用正式 splitter 的完整 membership-unit 去重，目标因此设为正式需要的 1,250；
只在完整 wave 边界停止，实际合格数允许自然超过 1,250。该修订减少无意义扫描，同时
提高 eligibility 与正式 split 的一致性。

- [x] 新增 `v6_3_precision_cascade_wave_scan_v2` 配置：seed=42、wave=250、
  target=1,250、cap=5，预注册 fallback cap=[8,12]，每 source 4 pair/8 query。
- [x] 将 1,662 行半成品 CLI 拆为 `src/prepare/eligibility_scan.py` 与薄脚本入口，
  并复用正式 splitter 的完整 source 去重规则。
- [x] 一个执行进程只加载一次 GLiNER2 large/BioMed runtime，fact 与 counterfactual
  阶段共享；完整 source lookup 只保留当前 wave 的 source。
- [x] checkpoint 改为验证完整前驱 hash 链；finalization 使用 staging+原子晋升，
  中断后可验证并补齐，hash 漂移时 fail closed。
- [x] split 与 promotion 增加共同门禁：capacity passed、去重一致、至少 1,250
  source、4 pair/8 唯一 query、checkpoint/finalization hash 完整。
- [x] 新增 11 个 synthetic/integration 测试；首轮 2 个夹具因未按协议字典序构造
  whitelist/mock wave 而失败，保留稳定排序实现并修正夹具后 11/11 通过。
- [x] 运行完整 unittest、内存编译和 diff 检查：244/244 tests 通过，
  受影响的 9 个 Python 文件内存编译通过，v6.3 两份 YAML 解析通过；
  `git diff --check` 仅报告工作树既有 LF/CRLF 转换提示，无空白错误。
- [x] 只冻结三数据集 cap=5 scan plan，核验 source universe/hash，不加载模型：
  Edgar 1,549 source/7 waves、Enron 14,523/59、PubMed 3,666/15；
  三者 cap/order/candidate hash、完整去重和 API=0/Retriever=0 均通过。
- [x] 运行 Edgar 单个 250-source wave pilot：250 source 中 212 个通过，
  claim-eligible=228，最终固定 848 pair/1,696 唯一 query；完整 checkpoint/output
  hash 链和 API=0/Retriever=0 复核通过。下一步从 checkpoint 续跑，不重算 wave 0。
- [ ] 三数据集容量通过后重建 formal split/benchmark 并 promotion，随后进入
  RC/Release 审计；此前 Retriever/API/canonical 均保持不动。

当前状态：v2 代码和聚焦测试已完成，尚未创建正式 scan plan 或运行模型 wave。

### Phase 7J 协议修订：固定双倍候选池 v3（2026-07-26，实施前冻结）

用户决定不再按“累计得到 1,250 个合格 source 即自适应停止”，改为先冻结正式需求两倍
的候选 source 池，再从通过全部门禁的 source 中选择正式 1,250 个。该修订把扫描停止点
从 eligibility 结果中解耦，减少停止规则造成的选择偏差。

- 固定候选池目标为 `2 × 1,250 = 2,500` 个完整去重 source，按 seed=42 的既有
  label-independent 顺序取前缀；不按中途合格率提前停止。
- 数据集全集不足 2,500 时使用全部 source 并显式记录 shortfall，不复制 source：
  Edgar 固定使用全部 1,549；Enron/PubMed 各使用前 2,500。
- 扫描完整固定池后，只有 query-eligible source ≥1,250 才通过；正式 1,250 仍按
  冻结顺序选取。容量不足时按预注册 cap 5→8→12 重跑固定池，不放宽精度门禁。
- 新协议与目录必须独立于 v2；v2 已完成的三个 Edgar checkpoint 保留为
  `superseded_development_evidence`，不得直接晋升或混入 v3。
- [x] 实现固定池配置、调度停止语义、plan/manifest 身份字段与回归测试：
  聚焦 13/13、完整 246/246、内存编译与 `git diff --check` 通过。
- [x] 冻结三数据集 v3 plan 并核验有效候选池为 1,549/2,500/2,500；
  candidate/source-order hash、pool source 绑定、API=0/Retriever=0 全部通过。
- [ ] 逐数据集完成固定池扫描；容量通过后再进入 formal promotion 和 RC/Release 审计。

当前执行点：按用户要求暂停。Edgar v3 已完成 3/7 waves，累计扫描 750 source、
query-eligible=626；`checkpoint_0001`–`0003` 完整保留。wave 3 的未完成 attempt
没有 checkpoint，续跑时不得手工晋升。

## Phase 7L：RC1 明显错误门禁与容量复核（2026-07-28）

协议变化理由：v6.3 formal promotion 后的 RC100 逐条检查发现自动预审漏掉了重复的
截断、列表/标题/邮件污染和结构化实体误型。按照“重复失败模式出现两次即不得冻结”的
既定门禁，必须先修复可泛化规则，不能手工删除 audit 样本，也不能直接裁决 Release。

- [x] 冻结本地版本：
  `attackability_v6_3_precision_cascade_rc1` 与
  `local_claim_pair_v6_3_precision_cascade_rc1`。
- [x] 新增并测试句首/句尾截断、邮件元数据、quoted-printable、标题/名词片段、
  引用编号、日期/比例/医疗量误型、generic ORG/PRODUCT 与生物实体误型门禁。
- [x] 修正两处门禁误伤：完整大额句末金额（如 `$136,000.`）不再当作 `$14.`
  式小数截断；`350-kilometre` 的数值槽位不再当作 `COVID-19` 式标识符组件。
- [x] 新增 `scripts/revalidate_v6_3_candidate_claims.py`：复用冻结语义解析与既有
  stealth 分数，无 GLiNER/API/Retriever 地重验证 candidates，并重新固定选择
  4 pair/8 条 source 内唯一 query；所有失败保留稳定原因。
- [x] 三数据集本地容量复核：
  - Edgar：13,056 candidate claims 中 9,135 通过；952 source 合格，缺 298。
  - Enron：9,825 candidate claims 中 6,347 通过；正式 retained prefix 中
    685 source 合格；回收 terminal wave 的 9 个已计算 source 后种子为 694，
    仍缺 556。
  - PubMed：16,370 candidate claims 中 11,921 通过；1,479 source 合格，
    容量通过。
- [x] 旧 RC100 回放：Edgar/Enron/PubMed 分别有 28/43/30 条旧 pair 被 RC1
  拒绝；已知 `Company`、`$14.`、`lso operates`、`-based Enron`、
  `Project GEM ... for`、`DNaseI` 等明显坏例均被拦截。Release 继续保持未裁决。
- [x] 新增 Enron 可续跑入口
  `scripts/extend_enron_v6_3_rc1_capacity.py`：复用前 2,000 个已计算 source，
  对未处理后缀做新的无标签 RC1 本地质量排序，冻结 8 个 seed checkpoint；准备阶段
  GLiNER/API/Retriever 调用均为 0。
- [x] Enron RC1 extension plan 已冻结并通过 `--resume` 只读验证：
  plan hash=`bc3ec9779f7c48048d27c0a6ed74391130d098447ad55f14a148f9b7f753dd66`，
  seed=694，next source index=2,000，shortfall=556。
- [x] 完整 `python -B -m unittest discover -s tests`：271/271 通过；两个新增脚本
  内存 `compile()` 通过。直接 `py_compile` 仍因 Windows `scripts/__pycache__`
  ACL 报 Permission denied，未误判为语法失败。
- [ ] 用户先运行一个 250-source Enron extension wave，回传
  `eligible_source_count`；依据真实增量决定是否继续，禁止盲目连续烧 GPU。
- [ ] Edgar 容量仍不足；优先评估预注册 cap=8，不得用当前 952-source whitelist
  重建 500/500/250，也不得降低 RC1、stealth 或 4 pair/8 query 门槛。
- [ ] 只有三数据集重新达到 1,250、生成新 RC 并通过审计后，才重建 formal
  split/benchmark/claims/queries；现有 promoted v6.3 与旧 RC/Release 不得晋升。

Enron 单 wave 可续跑命令：

```powershell
D:\python\anaconda\python.exe -B scripts\extend_enron_v6_3_rc1_capacity.py `
  --resume --execute --max-new-waves 1
```

## Phase 7M：主实验统一 3 pair / 6 queries（2026-07-28）

协议变化理由：4-pair RC1 容量门禁对 Enron 完整邮件产生明显的事实丰富度选择偏差；
前 2,000 source 中 ≥4 pair 仅 694，而 ≥3 pair 为 1,077。两个新增 250-source
wave 分别贡献 111 和 120 个 ≥3-pair source，使累计容量达到 1,308。相比继续扫描
并偏向超长邮件，统一减少一个 pair 更节省调用预算，也更容易保持三数据集可比。

- [x] 主实验统一冻结为每 source 3 pair / 6 条文本唯一 query。
- [x] 4 pair / 8 queries 保留为高预算消融；2 pair / 4 queries 保留为低预算消融。
- [x] validator、semantic resolver、实体类型、stealth 与 source-level 评估门禁不变。
- [x] 更新 canonical suite、attack/RAG 配置、eligibility/promotion/offline verification
  门禁与回归测试。
- [x] PubMed 本地重选：1,820 source，容量通过。
- [x] Enron 合并十个已完成 wave：3-pair eligible=1,308；按冻结 source 顺序在
  index 2,361 精确保留第 1,250 个 source，得到 3,750 pair / 7,500 query。
- [x] Enron whitelist hash=
  `949a6fb41f9620f12dd40d701e5fe3ec53150eb8980762e677cd062c5f1e7e3c`；
  fixed-budget plan hash=
  `c8b7c4a4b5f1c692c608656c623480020d9c94a35754cc1f429b51df74baf138`。
- [x] 完整 unittest 274/274、受影响 Python 文件内存编译、配置 3/6 一致性、
  Enron 1,250-source/3,750-pair/7,500-query 完整性与 `git diff --check` 均通过。
- [x] Edgar 本地重选原有 1,173；定向 cap=8 计划只处理 147 个
  exact-2-pair source 的 438 个第 6–8 chunk，每 wave 50 source。plan hash=
  `8fc79a76cadac0e779d82b3e72a41bb5c057c5513421963ba34efc5ee8f9644d`；
  两个 wave 后新增并保留 77 个 source，最终达到 1,250 source、3,750 pair、
  7,500 query；whitelist hash=
  `9229525cfa9d57953b02fd1d17c363e44238428f27df61e46e81366e35bff99a`。
- [x] Edgar 达到 1,250 后，统一重建三数据集 formal split、promotion 和新
  RC100/Release200；旧 4-pair formal/审计不得晋升。

旧 Enron 4-pair extension plan 已 superseded，不得再使用原命令 resume。

Edgar 定向补跑命令（已完成，仅保留作复现记录）：

```powershell
D:\python\anaconda\python.exe -B scripts\extend_edgar_v6_3_budget6_capacity.py `
  --resume --execute --max-new-waves 1
```

## Phase 7N：3-pair formal 重建与新审计（进行中）

- [x] 将三数据集冻结的 budget-6 whitelist、selected facts/claims/queries 整理为统一、
  hash 绑定且可被 split/promotion 消费的 release input。
- [x] 使用新 whitelist 重建 source-exclusive formal split：
  500 KB_Member / 500 True_Non_Member / 250 Reserve。
- [x] 从新 split 重建 benchmark，并 promotion 为每 source 3 pair / 6 条唯一 query。
- [x] 运行 formal 完整性门禁：三数据集各 1,250 source、3,750 pair、7,500 query，
  无跨组 source、无空/重复 query、facts/claims/query/hash 一致。
- [x] 重新生成与旧 RC/Release source 和 audit ID 隔离的新 RC100 与 Release200。
- [x] 运行本地 AI 预审与审计统计：RC100 与 Release200 均为 0 high-risk；不把
  AI 预审写成真实双人盲标或 Cohen's κ。
- [x] 更新 README、notes 和 artifact 清单；完整 unittest 通过后结束本阶段。

当前状态：三数据集 source-exclusive formal split 已按 500/500/250 重建并绑定
release protocol/hash；开始重建 benchmark 与 promotion。API=0、Retriever=0。

错误记录：

- 首次聚焦测试误用 `python -B -m unittest tests.<module>`；仓库的 `tests/`
  不是 Python package，因而在收集阶段报 `ModuleNotFoundError`，没有执行代码。
  后续统一改用 `python -B -m unittest discover -s tests -p <pattern>`。
- 首次正式 split 在写文件前被旧的协议等值检查拒绝：配置同时保留上游
  `protocol=v3` 与新 `release_protocol`，脚本只读取前者。修复为优先校验
  `release_protocol`、缺省回退旧 `protocol`，并增加兼容测试。

## Phase 7O：attack-first RC2 明显伪影门禁（2026-07-28）

协议变化理由：本项目目标是成员推理攻击，而不是构造零瑕疵语言学 benchmark。
RC100 中需要处理的是会让 victim 不依赖文档记忆、直接凭语法或常识拒绝 Q− 的明显
shortcut。细粒度但仍自然的 PERSON/ORG/LOCATION/PRODUCT 差异不再作为硬失败。

- [x] 冻结版本目标 `local_claim_pair_v6_3_attack_first_rc2`，只处理四类明显伪影：
  大类子型冲突、冠词冲突、确定泛称实体、确定残句。
- [x] 将 LOCATION 候选分为国家、州省、城市、区域和带定冠词地点；只在类别可明确
  判断时强制兼容，未知类别保留。
- [x] 将 PRODUCT 候选分为药物/生物制品、实验试剂、设备、软件、服务/保险计划和
  消费/工业产品；只拒绝跨大类且会导致句义荒谬的替换。
- [x] 增加小型确定泛称门禁与无谓词/版权/标题残句门禁，不使用 API、Retriever 或
  新的 transformer。
- [x] 对历史明显坏例做回放，并保留自然但有细粒度歧义的正例。
- [x] 完整 unittest、内存编译与 diff review 通过后，本地重筛 3 pair/6 query。
- [x] 生成一次新的 RC100；自动高风险明显伪影为 0/300。若同一明显模式仍重复两次，
  停止 RC2，不再实施 RC3。
- [x] RC2 通过后准备单 cell Reserve pilot；不得根据正式 member/non-member
  测试 AUC 反向调 validator。

当前状态：协议范围已冻结，开始实现最小本地门禁；现有 RC1/formal artifacts 保留，
在 RC2 通过前不覆盖、不删除，也不启动 victim API。

错误记录：

- 首次 RC2 聚焦测试 13 项中 1 项失败：`Toolkit` 不满足 `\bkit\b`，导致历史坏例
  `Somatrogon → Lumen Toolkit` 未触发 PRODUCT 大类冲突。将 `toolkit` 作为同一
  实验试剂/工具中心词显式加入后重跑；没有扩大其他 PRODUCT 规则。
- 首次 RC100 只读回放命令两次被 PowerShell/Python `-c` 引号解析拒绝，均在导入
  和读取 artifact 前失败。改为新增可复现的只读脚本
  `scripts/replay_attack_first_rc2_audit.py`，不再使用脆弱的一行命令。

### Phase 7O 完成状态

- [x] 三数据集 RC2 whitelist 均恰好 1,250 source；每数据集 3,750 pair /
  7,500 条唯一 query。
- [x] 默认 `data_v6_3.yaml` 已切换到
  `v6_3_attack_first_rc2_budget6_release_v1` 和 RC2 release input，避免复现时
  静默回退 RC1。
- [x] formal source split 均为 500/500/250，promotion 与完整性报告通过。
- [x] 新 RC100 共 300 条、Release200 共 600 条，均为 0 high-risk；needs-review
  仅作细粒度语义人工抽查提示，不再触发新的规则迭代。
- [x] Enron 首个 Qwen3.5-397B + all-MiniLM-L6-v2 pilot 计划已生成：
  25 source、150 query、RAG 150 + matched LLM-only 150，实际 API 调用 0。
- [x] 最终验证：302/302 unittest、260 个 Python 文件内存编译、15 个 YAML
  解析、formal integrity 与 `git diff --check` 全部通过；diff check 仅有工作树
  既有 LF→CRLF 提示，无空白错误。

冻结结论：RC2 作为本轮最终 claim 协议；不实施 RC3。下一步是验证/重建仅含新
`KB_Member` 的 Enron dense index，然后逐个 Generator、逐个 Retriever 运行小规模
pilot。任何规则调整只能基于 Reserve pilot 的机制证据，不能读取正式测试 AUC 调参。

### Phase 7P：Enron dense index（2026-07-28）

- [x] 不新增 RAG 配置或执行脚本；直接把现有 `configs/rag_config.yaml` 的 artifact
  路径从 v19 统一切换到 v6_3。
- [x] 使用 `mia_model` 环境的 Python 和现有 Step 03 构建
  `sentence-transformers/all-MiniLM-L6-v2` dense index。
- [x] 索引严格来自当前 Enron `KB_Member`：500 source、2,611 行/块；与
  True_Non_Member/Reserve 的 doc ID 重叠为 0。
- [x] `kb_hash`、`docstore_hash`、`index_hash` 全部与文件实值一致；后端为
  `faiss.IndexFlatIP`、维度 384，top-5 冒烟检索全部来自 KB_Member。
- [x] 原 Qwen3.5-397B + MiniLM pilot 未启动且 API=0；该计划已由 Phase 8
  的 Llama+BGE pilot supersede，不再沿旧身份执行或 resume。

执行约定：激活 `(mia_model)` 后统一使用 `python`。不要使用
`D:\python\anaconda\python.exe`，该 base 解释器没有 FAISS。

## Phase 7Q：仓库瘦身（2026-07-28）

- [x] 盘点 `artifacts`、缓存、脚本引用和当前正式配置。
- [x] 冻结保留边界：RC2 正式产物、审计、索引、研究记录和复现入口不得删除。
- [x] 删除约 10.01 GiB 的 v19、RC1/旧 eligibility 中间产物和可再生缓存。
- [x] 移除不属于主流程的诊断、连通性测试和已完成的一次性恢复脚本。
- [x] 将冻结的 v6.3 配置接到标准配置文件名，更新 README 的唯一主流程。
- [x] 运行完整 unittest、正式完整性检查、索引隔离检查和配置 hash 检查。

## Phase 8：v20 BGE RAG + Llama 主结果（2026-07-30 起）

- [x] 停用 MiniLM 正式检索实验，保存停止状态并归档为 legacy/superseded。
- [x] 实现 Generator family registry、严格具体模型身份、provider 响应 metadata、
  suite 目录隔离和 resume identity 拒绝规则。
- [x] 在首次正式调用前将不可用的 Gemini 主模型合法切换为
  `meta/llama-3.1-70b-instruct`；Gemini/Qwen/GPT 改为 pending extension。
- [x] 冻结 BGE base、tokenizer、reranker 的完整 commit SHA，下载 local-only
  snapshot 并生成文件 hash manifest。
- [x] 将 `mia_model` 固定为唯一 Conda 环境，安装并验证 CUDA PyTorch
  2.11.0+cu130；更新 `requirements.txt` 与项目环境记忆。
- [x] 使用三个数据集 Reserve 构建独立 dev indexes；9/9 dense 候选均为
  FAISS，无 CPU/JSON fallback，禁入组重叠为 0。
- [x] 完成三数据集离线门禁并冻结 128 tokens / overlap 32；
  选择只依据 Recall@5、MRR、p95 latency，不使用攻击 AUC。
- [x] 构建三数据集正式 dense+BM25 索引并逐行审计：每数据集仅含
  500 个 KB_Member source，禁入组混入为 0。
- [x] 冻结三数据集 150-query pilot 计划及 hash；修正六系统总预算为 2,700，
  当前 `api_calls_made=0`。
- [x] 完成本地收口：297/297 unittest、AST/YAML、pip、CUDA/BGE 和 diff 门禁通过。
- [ ] 运行 Llama 三数据集六系统 compatibility pilot；按当前 4 RPM，
  2,700 次调用理论下限约 11.25 小时，命令默认断点续跑且不得跨身份 resume。
- [ ] 运行 `scripts/20_check_generator_pilot.py`，要求三数据集全部满足：
  响应完整率 100%、stance 可解析率 ≥99%、无重复/空响应/身份漂移、
  hybrid 不劣于 dense 超过 2 个百分点、Oracle 明显优于 Random、KB 隔离通过。
- [ ] 只有 pilot 全部通过后，才启动 Llama 约 90,000-call 正式 suite 和
  Oracle/Random 机制子集；失败时保留报告并停止，不得依据正式 AUC 调协议。
- [ ] 完成 Llama 的五个 baseline、代表性 defense、strong-RAG 机制分析和论文主表。
- [ ] 分别冻结 Qwen、GPT、Gemini 的一个具体型号，从独立 150-query pilot 开始
  运行 extension；不同具体型号、Retriever、hash 的产物禁止合并。
- [ ] 回收两位真实标注者标签并完成通过率/Cohen's κ 门禁，AI 预审不得替代人工结论。

当前执行点：Phase 8C0。离线工程门禁已经完成，但科学协议仍需按红队审计修正；
暂不启动 Llama compatibility pilot。详细证据见 `思路v20.txt` 与
`思路v21.txt`，本文件只维护阶段状态与下一步。

## Phase 8C0：正式 API 前审稿红队整改（2026-07-31）

- [ ] 把反复用于方法开发的现有集合降级为 dev，并冻结未触碰的 canonical test。
- [ ] 拆分互不重叠的 retriever-dev、pilot-dev 与 conformal calibration pool；
  Pilot source 不进入 canonical test/calibration。
- [ ] 决定低 FPR 方案：扩充独立负样本/calibration，或删除
  `TPR@0.1% FPR`；500 个负样本的 0.2% 经验分辨率不得伪装成 0.1%。
- [ ] 修复 Oracle 对非成员/Reserve 为空的问题；Random 做 token-budget matching
  与 target/近重复 source 排除，retrieval Recall 只对 member query 计算。
- [ ] 冻结 primary/secondary endpoint、功效或精度目标、多重比较、
  parse/timeout/missing-response 和停止规则。
- [ ] 将 baseline 改成 source-level、相同 6 victim calls/source、相同 whitelist
  和 v20 身份；纳入或正式回应 MEntA/E-MIA，adapted baseline 不冒充官方复现。
- [ ] 冻结现有五方法 DCMI/IA/MBA/RAG_MIA/S2MIA 的 source-level 分层预算：
  用户已决定 baseline 只运行 BGE，不运行 BM25/hybrid；BGE 使用完整
  1,000 source/dataset，按当前原生预算合计约 10 calls/source，总 victim calls
  约 30,000，不运行 chunk fan-out。MEntA/E-MIA 仅作为近期工作风险另行决策，
  不冒充当前 baseline。该限制不改变 PCV 主方法矩阵。
- [ ] 为每个 baseline evaluation source 冻结唯一 representative chunk：
  使用统一、标签无关、响应前确定的 evidence-relevance 规则；五方法共用
  `source_id → chunk_id/text_hash` manifest，禁止按攻击结果或方法分别挑 chunk。
- [ ] PCV 主方法保留每数据集、每实验 cell 7,500-call 固定预算；即三个数据集
  每 cell 22,500 calls，BGE/BM25/hybrid/matched LLM-only 主矩阵仍约 90,000。
- [ ] 实现至少一个真实文献 defense、项目 defense 与 benign QA utility；
  canonical gate 必须拒绝 `implemented=false`、空 privacy/utility 指标。
- [ ] 增加中性 RAG prompt robustness cell，结构化 correction prompt 仅作为
  controlled mechanism setting。
- [ ] 把正式条件改为确定性 block interleaving；响应 metadata 补齐 token usage、
  finish reason、latency、retry，并冻结可审计的 provider/endpoint identity。
- [ ] 完成 claim pair 双人盲标与 Llama Pilot stance parser 人工正确性门禁。
- [ ] 做跨组 semantic near-duplicate 审计，并报告 query-eligible source 覆盖率与
  selected-vs-excluded 分布。
- [ ] 关闭以上 P0 后清理工作树、填写 immutable `release_commit`，重跑所有离线
  门禁和 dry-run，再进入 Phase 8C。

审计中遇到的非破坏性命令问题：

- 首次读取 baseline 文档误查仓库根目录 `BASELINES.md`；实际文件位于
  `src/baselines/BASELINES.md`，纠正路径后完成，只读且未改文件。
- 首次协变量交叉验证使用 `cross_val_predict` 配合 repeated CV，因 repeated
  folds 不是 partition 而失败；改用 `cross_val_score` 后成功。
- 全量 unittest 首次只给 1 秒超时而被工具终止；改为 300 秒后 297/297 通过。
- 一次 PowerShell `Select-String` pattern 含方括号引号导致解析失败；改用简单
  pattern 数组后完成。
- 文档扫描首次按仓库根目录查找 `thesislogic.txt`/`baseline.txt`，其中实际
  baseline 位于 `研究记录/baseline.txt`；纠正后完成，无文件写入。

## Phase 8C1：v20 现有 Source 原地冻结整改（2026-07-31，完成）

本节 supersede 上方 Phase 8C0 的未完成清单。最终用户决定是不扩 source、不增加
中性 Prompt、不做真人双标/parser 审计；保留 conformal，但降格为 Retriever
冻结后的 secondary empirical calibration。

- [x] 三数据集现有 1,250 source 定义为 `pre_response_frozen_canonical`；
  保持 500 KB Member / 500 True Non-member / 250 Reserve。
- [x] Reserve 冻结为 5 个 `pilot_diagnostic` + 245 个
  `conformal_calibration`，两者 source ID/hash 互斥；Pilot Reserve 永久不进入
  conformal。
- [x] 删除数值型 TPR@0.1% FPR；保留 AUC、advantage、TPR@1%/5%、
  conformal TPR/FPR@1%/5% 及 retrieval 指标。
- [x] 冻结唯一 primary endpoint：Llama+BGE 三数据集等权 macro source AUC；
  数据集内 Member/Non-member 分层 bootstrap=2,000、seed=42。
- [x] 完成 exact hash + MinHash 近重复审计；Edgar/Enron 分别确定性重分组
  2/14 个 source，PubMed 不变，最终 cross-group overlap=0。
- [x] 重建受影响 split、benchmark、query、formal BGE/BM25 index 和全部
  Reserve dev indexes；复核所有文件/hash/snapshot。
- [x] 修复 Oracle/Random：三组目标上下文均可取，Random token 差≤5%，并排除
  target/exact/MinHash/BGE 近重复；Recall 只以 KB Member 为分母。
- [x] 完成 9 个 Retriever candidate 门禁并冻结 128/32；未读取攻击 AUC，
  BGE-large fallback 未触发。
- [x] 重新冻结三个 150-query Pilot manifest；每数据集 900 calls，总计
  2,700，实际 API=0。
- [x] 五 baseline 固定 DCMI/IA/MBA/RAG-MIA/S2MIA，只跑 BGE；每 source
  使用一个共享 representative chunk，总预算约 30,000 victim calls。
- [x] 实现 `answer_without_correction` 与 `target_entity_redaction` 两个真实
  零 API defense，并让 canonical gate 拒绝 placeholder/空指标。
- [x] 生成 90,000-request source-block interleaved schedule；resume 冻结
  schedule ordinal、query、benchmark、index、code、model identity。
- [x] 缺失响应策略冻结为 100% 完整才发布；允许按冻结规则 retry/resume，
  不插补、不删除 source；actual model/fingerprint 漂移立即停止。
- [x] 补齐 provider response metadata：actual model、request ID、fingerprint、
  timestamp、input/output tokens、finish reason、latency、retry count。
- [x] API 入口增加 clean release commit 硬门禁；正式首个成功响应记录
  `first_formal_call_at`。
- [x] 新增 `scripts/26_validate_v20_preflight.py`，总预检通过：
  22,500 条正式 query、90,000 个唯一主请求、2,700-call Pilot 计划、
  formal/API calls=0。
- [x] README、`顶会推进_notes`、`顶会推进_task_plan` 和 `思路v22` 同步。
- [x] 最终回归：306/306 unittest、255 Python AST、17 YAML、preflight passed。

### 下一执行点：Phase 8C2 Llama Pilot（需要真实 API）

- [x] 接入第六个 baseline MEntA：5 queries/source、local NLI entailment/refusal
  打分、source-level adapted disclosure、identity/resume hash 绑定和零 API tests；
  最终回归 320/320，MEntA 定向测试 14/14。
- [ ] 在 clean release commit 上运行 `scripts/download_frozen_menta_nli.py`，
  校验 `tasksource/deberta-base-long-nli@04dcf11f...99d5` 全部文件 hash。
- [ ] 用现有 sibling profile 分别生成 Edgar/Enron/PubMed 的 MEntA query
  manifest；每个 representative source 必须恰好 5 个唯一 query，生成阶段
  victim API calls=0。
- [x] MEntA 加入后 baseline victim 预算更新为 15,000 calls/dataset、
  45,000 calls/三数据集；正式 runner 必须逐 source 校验 MEntA 恰好 5 calls。

- [ ] 在 clean release commit、`mia_model` 环境和冻结
  `meta/llama-3.1-70b-instruct` endpoint 上运行三数据集六系统 2,700 calls。
- [ ] 三数据集分别运行 `scripts/20_check_generator_pilot.py`；必须达到 100%
  响应完整、stance parse≥99%、无重复/空响应/model drift、hybrid Recall@5
  不比 BGE 低超过 2pp、Oracle 明显优于 Random、KB 隔离通过。
- [ ] Pilot 任一数据集失败即停止并保留报告；不得依据 PCV AUC 或攻击中间结果
  修改模型、Retriever、claim 或 Prompt。
- [ ] 三数据集全部通过后运行 90,000-call interleaved 主矩阵，再运行约
  3,600-call Oracle/Random、约 30,000-call BGE-only baseline 和零 API defense。

### 本地 Qwen3-4B sibling 门禁（2026-07-31）

- [x] 新增 `qwen3:4b-q4_K_M` 的 8K Modelfile 和 `ollama_qwen3_4b` profile；
  保留仓库默认云端 active sibling，不修改 victim/Generator 身份。
- [x] 本地 sibling 显式关闭令牌桶与固定间隔；victim 保持独立 4 RPM 令牌桶。
- [x] profile/env 优先级、Ollama 请求参数、关闭 thinking、provider model ID、
  profile/model 摘要漂移和 partial/frozen resume 拒绝已纳入单元测试。
- [x] MEntA query/manifest 与 baseline identity 升级为 sibling profile hash 绑定；
  禁止云端/本地生成结果混合续跑。
- [x] 安装 Ollama，设置单并发/单模型/Flash Attention/q8_0 KV/10m keep-alive，
  拉取模型并创建 `pcv-qwen3-4b:q4km-8k`。
- [x] 从 `ollama list` 冻结实际模型 ID `39297c75a309` 到 `PCV_SIBLING_MODEL_VERSION`，再更新本机
  `.env`；不得使用占位摘要生成正式 artifact。
- [x] 运行三数据集各 10 条的小样本门禁：30/30 通过、每条 5 个唯一问题、
  无 thinking、model ID 一致；热启动 p95=2.462s/1.834s/2.403s。
- [x] 连续至少 50 次请求并让 BGE retriever 同驻：重跑 50/50 通过，p95=1.735s；
  `ollama ps` 为 100% GPU/8192 context，峰值 3983MiB/8188MiB，无 OOM/超时/CPU fallback。
- [x] 首轮稳定性第 50 个 source 的重复问题被拒绝；只为 JSON 结构/唯一性增加最多 2 次
  纠错重试，身份、thinking 和 provider 漂移继续立即 fail closed；MEntA 定向测试 18/18。
- [ ] 上述门禁全部通过后才生成三数据集正式 MEntA manifest；不得复用旧 sibling
  生成结果。当前门禁已通过，但正式 manifest 仍待 clean release commit；隔离诊断产物不得提升。

## Phase 8C3：多样化实体槽问句升级（2026-08-01）

- [x] 保持 Step 06 facts、Step 07 claims、split、benchmark 与正式 index 内容不变，解冻查询及其下游绑定。
- [x] 实现 source 级一次请求三个 pair、每 pair 三候选的 `diverse_slotted_verification` Step 08。
- [x] 实现唯一 `{ENTITY}` 槽、Q+/Q- 槽外一致、长度/极性/攻击术语/结构化事实/锚点硬门禁。
- [x] 接入冻结本地 NLI 与问句--命题 embedding 校验，实现联合多样性选择和最多两次纠错重试。
- [x] 实现 dataset 级模板重复率、opening 4-gram、distinct-2/3 与长度审计。
- [x] Step 09 改用 benchmark 原始 chunk 的实体遮蔽 5-gram/LCCS 门禁；embedding 降为 diagnostic-only。
- [x] 正式 Step 09 在任一 source 丢失三 pair/六 query 固定预算时 fail closed，不删 pair/source 凑数。
- [x] runner 改用 `Verification request`；保持 Consistent/Inconsistent/correction/unknown 输出协议。
- [x] 实现 shadow source 校验、source-bootstrap AUC 非劣、三 Retriever Recall@5 与字面下降晋升门禁。
- [x] 更新正式 suite/preflight：禁止旧查询进入正式矩阵，禁止中性 Prompt cell，拒绝旧 Pilot、
  Retriever query report、schedule 与未通过 shadow gate 的状态。
- [x] 新增定向单元测试和专门实施记录 `研究记录/多样化实体槽问句升级_实施记录.txt`。
- [x] 本地收口验证完成：`mia_model` 环境全量 unittest 340/340、相关 AST/YAML 与 diff 门禁通过；
  未调用 API、未生成正式查询或 shadow 指标。
- [ ] 在 clean release commit 中显式冻结强 `PCV_SIBLING_MODEL`/endpoint，并核验固定 NLI snapshot。
- [ ] 冻结每数据集 100 shadow member + 100 shadow non-member，完成 formal near-duplicate 排除。
- [ ] 运行旧/新 Llama+BGE shadow（7,200 victim calls）和 BGE/BM25/hybrid 离线检索对照。
- [ ] 运行 `scripts/28_validate_query_rewrite_shadow.py`；任一晋升门禁失败即停止，不读正式 AUC 调参。
- [ ] 晋升通过后强制重跑三数据集 Step 08/09，登记 sibling actual model ID 与全部新 hash。
- [ ] 重冻 Retriever query report、query controls、Pilot/Oracle/Random、baseline representative/MEntA
  绑定、90,000-call schedule 与总 preflight；内容不变的产物也必须重新绑定新 query hash。
- [ ] 总 preflight 再次 passed 后，才允许启动正式 victim API 矩阵。

当前执行点：实现与本地验证；正式查询、shadow 指标、新 hash 尚不存在。旧 Step 08/09 及全部
query-dependent 下游产物均不得继续 resume 或进入投稿结果。

## Phase v21：Luna Query + Qwen IA Shadow + Gemma 先行（2026-08-03）

- [x] 写入统一实施记录 `研究记录/思路v23.txt`，冻结三类模型角色、213,000 victim-call 总预算、
  `TPR@0.5% FPR` 与 IA attacker/victim 分账。
- [x] 新增 v21 generator registry 与版本化 data/rag/baseline/experiment 配置；Gemma concrete ID
  固定，Phi/Llama/Command-R 保持 pending。
- [x] 实现 Luna query 元数据、Qwen IA Shadow manifest、严格响应校验、本地 Gemma client、
  IA 五问冻结/运行身份与 0.5% FPR 经验阈值指标。
- [x] 建立并验证 v20 provenance，按用户批准白名单删除旧大型 payload；清理结果和不可恢复边界已记录。
- [x] 用旧清单 SHA + Phase 7I 证据段 + 阈值/模型锁建立 fail-closed v21 calibration provenance；
  不把恢复记录冒充重建校准，论文前有原标注行时重跑。
- [x] 完成 EDGAR 5,480、Enron 60,000、PubMed 50,000 raw-record v21 预处理；三者 source 容量均超过 2,250。
- [x] 冻结三套 4,500-source eligibility plan，shortfall=0、API=0、Retriever=0；plan hash 已写入 notes。
- [x] 修复 `mia_model` 运行环境并复核精确包版本、CUDA 和 GPU；全量 unittest 346/346、关键文件编译通过。
- [ ] 长跑三数据集 eligibility。EDGAR 首波在用户要求自行运行时终止，无 checkpoint；SQLite cache
  `quick_check=ok`，可直接 `--resume`。预计每个 250-source wave 约 15--30 分钟，完整三数据集需数小时。
- [x] Luna compatibility preflight 通过：实际模型 ID/request ID/timestamp/schema 全部合格；该请求不是正式 query。
- [x] Qwen IA Shadow compatibility preflight 通过：冻结别名摘要匹配，正式 parser 可解析，非正式诊断共 2 calls。
- [ ] 下载并核验 `google/gemma-2-2b-it@9b78bb...` 精确 snapshot；当前 local-only preflight 为
  `blocked_model_not_cached`，禁止 CPU fallback、量化或改 revision 绕过。
- [ ] eligibility 完成后冻结 1,000 member + 1,000 non-member + 250 Reserve/dataset，并验证只有 KB_Member 入 index。
- [ ] 完成 BGE/BM25/strong-RAG 离线门禁、MEntA controlled bridge 数据准备和 Luna Query pilot。
- [ ] 为每数据集人工审查至少 200 个 IA question-shadow-answer pair；通过后才冻结 IA manifest。
- [ ] Gemma 150-query compatibility pilot 与全部隔离/格式门禁通过后，才允许 213,000-call 正式 suite。

本机长跑命令（可中断后原样重跑，完成 wave 才写 checkpoint）：

```powershell
D:\python\anaconda\envs\mia_model\python.exe -B scripts\build_v6_3_precision_cascade_eligibility.py --dataset edgar --data-config configs\data_config_v21.yaml --attack-config configs\pcv_attack_v6_3.yaml --resume --execute
D:\python\anaconda\envs\mia_model\python.exe -B scripts\build_v6_3_precision_cascade_eligibility.py --dataset enron --data-config configs\data_config_v21.yaml --attack-config configs\pcv_attack_v6_3.yaml --resume --execute
D:\python\anaconda\envs\mia_model\python.exe -B scripts\build_v6_3_precision_cascade_eligibility.py --dataset pubmed --data-config configs\data_config_v21.yaml --attack-config configs\pcv_attack_v6_3.yaml --resume --execute
```

若希望每次只跑一个 250-source wave，在任一命令末尾加 `--max-new-waves 1`，完成后原样再次运行。

## Phase v21-E：Enron full-corpus sampling-frame 修订（2026-08-04）

- [x] 完成旧 4,500-source cap=5 scan：524 claim eligible、514 query eligible，容量门禁失败；
  保留全部 plan/checkpoint/finalization/hash 作为失败证据。
- [x] 核查本地 `emails.csv`：517,401 messages、150 users；旧 60,000-record prefix 仅覆盖 20 users。
- [x] 冻结决策：旧 Enron suite 标记为 `superseded_enron_prefix_sampling_and_capacity_failure`，
  不进入 canonical release。
- [x] 取消 Enron cap=8/12 路线；三个应用数据集继续使用统一 cap=5 eligibility 定义。
- [x] 冻结新设计：完整语料作为 sampling frame，固定 candidate pool=30,000、seed=42、hash selection，
  只对候选池执行昂贵 semantic eligibility。
- [ ] 新建独立 Enron full-v21 data/scan config 和输出目录；不得修改旧 plan 身份或原地追加 source。
- [ ] 对完整 517,401-message sampling frame 执行零 API census、清洗、source/exact/near-duplicate 和
  150-user coverage audit，冻结 raw/clean manifest 与 hash。
- [ ] 从 clean sampling frame 冻结 30,000-source pool；固定 cap=5、minimum claims=3、minimum pairs=3，
  scan_full_candidate_pool=true。
- [ ] 完成 30,000-source eligibility；必须得到至少 2,250 个 query-eligible source，否则停止并进行
  新协议决策，禁止放宽 claim/stealth/semantic 门槛。
- [ ] eligibility 通过后按 seed=42 冻结 1000/1000/250 split，验证 source exclusive、near-duplicate
  isolation 和只有 KB_Member 入 index。
- [ ] 在论文数据表报告全链路 coverage、排除原因和用户覆盖；所有攻击/baseline 使用同一正式 source。

当前状态：协议已确认、实施尚未开始。不要继续运行旧 Enron cap=8/12，也不要删除本地 raw CSV/ZIP。

实施更新（2026-08-04）：

- [x] 新建隔离的 `data_config_v21_enron_full.yaml`，不修改旧 v21 实验身份。
- [x] 实现完整 CSV 精确去重 + seed=42 内容哈希抽样，冻结 150,000 raw screening mail，并记录
  517,401-message/150-user/hash 审计。
- [x] 新增 Enron full eligibility protocol：固定 30,000 processed sources、仅 cap=5、无 fallback、全池扫描。
- [x] 将 sampling manifest/selected JSONL hash 绑定 eligibility plan 与 resume。
- [x] 补充抽样与新 scan config 单元测试。
- [ ] 用户运行完整 CSV 抽样命令，生成并冻结 sampling manifest。
- [ ] 用户运行 Step 01；确认 processed unique sources >=30,000，否则禁止创建 scan plan。
- [ ] 冻结零 API 的 30,000-source scan plan并检查 source/user/duplicate coverage。
- [ ] 按 250-source wave 续跑 eligibility；达到 2,250 仍须扫描完整 30,000-source pool。
- [ ] 通过后执行 split/near-duplicate isolation/index 边界门禁。

执行原则：预计超过数分钟的任务只提供命令，由用户自行运行；eligibility 用 `--max-new-waves 1`
可逐 wave 续跑。Step 01 只具备“完整产物存在则跳过”，不具备行级 checkpoint；若中途终止，应使用
`--force` 从该隔离目录重新开始。

### PCV_SIBLING 限速更新（2026-08-04）

- [x] 将 Luna/openai-compatible sibling profile 冻结为独立 4 RPM 令牌桶。
- [x] v21 generation 的 `sibling_requests_per_minute` 从 0 改为 4。
- [x] Step 08、MEntA、IA Luna 与 runtime sibling baseline 接入相同的 profile 限速语义。
- [x] 每次物理 HTTP retry 重新取令牌；victim 与 IA Shadow 限速身份保持隔离。
- [ ] 正式 query generation 前重新冻结 sibling profile hash，并拒绝旧 hash resume。

## Phase v21-F：18 类实体统一修复与一次正式全量门禁（2026-08-05）

- [x] 建立 18 类统一 policy registry，冻结 6 个 semantic 类型、subtype、replacement pool 和 policy hash。
- [x] 修复 semantic resolver 与 validator 重复判定冲突；保留边界、单槽、完整性、format 和 policy drift 硬门禁。
- [x] facts、claims、wave、scan plan 和 resume 身份绑定 policy/runtime hash；旧产物只能进入隔离 replay。
- [x] 实现 inventory、facts/source 双层 replay、A/B/C 三套 500-source pilot、formal scope 约束下的 blind audit 和 release gate。
- [x] 正式 scanner 接入 `v21_entity_policy_full_rescan_v1`；无 passed gate 或 evidence/runtime 漂移均拒绝。
- [x] 冻结旧 evidence inventory：EDGAR 14 waves、Enron 5 waves、PubMed 4 waves；未完成 attempt 不纳入。
- [x] 完成本地零 API 验证：最终全量 unittest 364/364；AST/YAML/diff 通过。
- [x] 运行 `freeze-pilots`，冻结三个 dataset 的 A/B/C cohort 和 candidate manifests；plan identity=`e43a1c4c4fa2d53db439993a5bd24d6878485078eea27805d0e337bd91c920c1`，每数据集 1,500 candidate sources。
- [ ] 续跑三数据集全部旧 wave replay；任一 source/type coverage gate 失败即停止。
  - [x] Enron 5/5 replay passed：131/1,250 eligible（10.48%，Wilson 95% 下界 8.90%），超过 125/10%/8% 三项门槛；旧策略为 85/1,250。report identity=`fbac0df34bc915d1e8c869d24cf84477da1d4cd02660f4cc1c2761545ae0bacc`。
  - [x] PubMed 4/4 replay passed：872/1,000 eligible（87.2%，Wilson 95% 下界 84.99%），超过 81.2% 非劣门槛；旧策略为 832/1,000。report identity=`1a3a9b1d1918dce9d4e650c04825eb5d76d44563ee876dfbcd82aba9a0eba723`。
  - [x] EDGAR 14/14 replay passed：3,230/3,500 eligible（92.2857%，Wilson 95% 下界 91.35%），超过 81.7429% 非劣门槛；旧策略为 2,931/3,500。report identity=`07a108f19a627bd013103e4587547408b6a5edeb2dfa7afac13bcb3a2f47a60c`。
- [x] 正式范围决策已冻结：保留 PROJECT_NAME 的代码/schema/提取/诊断统计，但设为 diagnostic-only；B/C 继续密封。
- [ ] cohort A pilot 继续暂停；本次范围修订与本地验证不构成启动授权。
- [ ] replay/pilot 通过后生成并完成五类共 500 条审计；用户复核预冻结 60 条和全部 uncertain。
- [ ] 运行 `finalize` 生成 passed release gate；failed gate 不得用于正式扫描。
- [ ] 使用新 data/scan config 冻结三数据集正式 plan，再按 250-source wave 续跑；禁止继续旧 v21/Enron-full checkpoint。

当前执行点：三数据集 replay 已全部通过；formal evidence scope 已冻结为 CONTRACT_TERM/LOCATION/ORG/PERSON/PRODUCT 五类，PROJECT_NAME 保留六类 schema 支持并设为 diagnostic-only。暂停仍位于 cohort A pilot 前；不得直接启动 pilot、audit、finalize、正式扫描、query、victim 或 Retriever。

API 登录切换交接（2026-08-06）：

- [x] 新建 `研究记录/API登录切换_工作交接_20260806.md`，冻结当前目标、三套 replay identity、PROJECT_NAME blocker、Git/测试状态、禁止事项与接管提示。
- [x] 核验本地 replay artifacts 与登录方式解耦；切换后无需重跑 Enron/PubMed/EDGAR replay。
- [x] 新登录接管后已确认 PROJECT_NAME formal scope：保留支持，设为 diagnostic-only；pilot/audit/finalize/formal scan/query/victim/Retriever 仍暂停。

PubMed resume 修复（2026-08-05）：

- [x] 修复 Step 07 manifest 中 tuple/list JSON round-trip 被误判为协议漂移的问题；采用 canonical JSON 逐字段比较，不放宽真实模型身份、版本、hash、阈值或 policy 漂移门禁。
- [x] 增加正向 resume 与反向模型 ID 漂移测试；定向测试 67/67、内存语法编译、全量 unittest 365/365 通过。
- [x] 审计第二次 stage plan drift：仅 runtime tree 与派生 plan hash 变化，checkpoint 不存在、完成 wave=0；保留旧 plan 和 rebind manifest 后绑定修复后的 runtime，exact expected-plan 校验通过。
- [x] PubMed replay 已原样 resume 并完成 4/4 waves，872/1,000 eligible，source/type gate 全部通过。

## PROJECT_NAME diagnostic-only protocol amendment（2026-08-06）

- [x] 正式范围已冻结：保留 PROJECT_NAME 的代码/schema/提取/诊断统计，但设为 diagnostic-only；formal evidence 仅覆盖 CONTRACT_TERM、LOCATION、ORG、PERSON、PRODUCT。
- [x] scope identity=`pcv_formal_evidence_scope_v21_r1`，SHA-256=`4fe92ea49f442aedf0c29bbf280fd31a98e97686a211ee01c824a116e67154be`；policy/schema hash 不变。
- [x] audit 修订为五类 ×（90 accepted + 10 hard negatives）=500 行；用户复核仍为 60 行；PROJECT_NAME=1 继续诊断报告但不参与 90-pair gate。
- [x] audit/report/plan identity 绑定 scope version/hash，scope 漂移 fail closed；旧 replay identity 不重写。
- [x] 使用 `D:\python\anaconda\envs\mia_model\python.exe` 完成定向 unittest 14/14、全量 unittest 367/367、284 文件内存编译。
- [x] 2026-08-07 已收到后续明确授权，仅启动 Enron cohort A；B/C、audit、finalize、formal scan、API/victim/Retriever 未启动。

修订性质：三套 replay 之后、victim/AUC 之前的 evidence-driven protocol amendment；不混入定向富集样本，不对 PROJECT_NAME 声称正式验证充分。本轮真实 API/victim/Retriever 调用新增 0。

## 2026-08-07：cohort A pilot gate 裁决

- [x] 按明确授权启动 Enron cohort A；wave 1/2 均完成并写入 scope-bound checkpoint。
- [x] 独立复核 Enron pilot report：identity=`dcb1322cbd0ee4726dc4ba5bed596e20aebfff195854b74d1a4227b1dea2607e`，checkpoint identity 有效，type gate 通过。
- [x] source gate 判定为 failed：49/500（9.8%），Wilson lower=7.492%，同时低于 50/500、10%、7.5% 预注册门槛。
- [x] 确认两个 wave 的 API calls=0、Retriever runs=0；首次超时的 `attempt_000` 保留，成功 `attempt_001` 作为 canonical evidence。
- [x] 已停止 PubMed/EDGAR cohort A pilot；不得启动 audit、finalize、formal scan，不得重试碰阈值或静默改门槛。

当前执行点：Enron cohort A source gate failed closed。下一步只能进行失败原因分析和新协议决策；当前 release gate 不存在，B/C 继续密封。

## Phase v21-G：Enron capacity / role decision（2026-08-07）

- [x] 冻结 Enron cohort A failed：49/500（9.8%），Wilson lower=7.492%，type gate passed；保留 partial attempt 和 canonical checkpoint/report。
- [x] 完成失败归因：主要为 source-level fact/claim 密度与三-pair 离散门槛；pilot 与 replay 的 eligible rate、claim conversion 和 wave 差异没有模型退化证据。
- [x] 明确扩大候选池不能自动修复原 10% eligible-rate gate；禁止重抽 cohort、降低三-pair门槛或以新样本追溯改写 v21_r1 结论。
- [x] 冻结 Enron 正式角色为 `boundary_stress_test`、`primary_canonical=false`；capacity 通过只允许边界评估，不能追溯改写 v21_r1 failed。
- [x] 冻结 `pcv_enron_capacity_role_v21_r2`：35,000-source fixed pool、cap=5、minimum claims/pairs=3/3、required=2,250；protocol SHA=`3c8b8fb45b6b31cb265dd70d69a55e176a0eba548d451a5fb060c9866fef6b10`。
- [x] 冻结执行边界：`execution.enabled=false`，长任务由用户运行，API/victim/Retriever 禁止；当前不提供未接入的伪命令。
- [x] 完成新协议 loader 与 5/5 定向测试；YAML、内存编译、diff check 通过。工具记录：`rg.exe` 在沙箱内被拒绝执行，改用 PowerShell 只读检索，无仓库影响。
- [x] 在不修改旧 30k 配置和 artifact 的前提下，新增隔离的 35k execution config/runner 绑定；只读上游 SHA、隔离输出、manual flag、boundary-only artifact identity 与禁止 formal promotion 均 fail closed。
- [x] 完成 35k runner 短验证：role+runner 13/13、原 eligibility 回归 22/22、相关 Python 内存编译、YAML 解析与 diff check 全部通过；未启动任何长任务或外部调用。
- [x] 首次 plan-only 尝试被 processed SHA 门禁在写入前拒绝；确认是新配置/runner 常量录入错误而非文件漂移，修正为实际 SHA `47ef7d2f...19a19e`，实际上游只读预检通过且输出目录仍不存在。
- [x] 用户运行一次不带 `--execute` 的命令冻结 35k capacity plan；状态=`preregistered_not_executed`，plan SHA=`c8fcd26c48b40d4c8bf7da31d8f7d48ec49fbd0bc33d54341688fb57b19ce983`，source_count=35,000、source universe=62,384、shortfall=0；独立 identity/source/candidate coverage 校验通过。
- [ ] 用户使用 `--resume --execute --max-new-waves 1` 逐 wave 运行；当前 1/140 waves，checkpoint 0001 identity=`32758bd7...8e05`，scanned=250、eligible=29。每次只接受完整 checkpoint，禁止 `--force`、路径 override、并行执行或把 partial attempt 当 canonical evidence。
- [ ] 35,000 source 全部扫描后独立复核 capacity report；通过仅允许 Enron boundary evaluation，失败则停止 Enron 下游，两种结果都不得改写 v21_r1 cohort A failed。
- [ ] Enron role/capacity 决策完成后，才考虑是否单独授权 PubMed cohort A，再按独立 gate 决定 EDGAR cohort A；B/C、audit、finalize、formal scan、API、victim、Retriever 继续禁止。

当前执行点：Enron v21_r1 pilot 保持 failed；v21_r2 capacity 已完成并复核 wave 1/140，checkpoint 0001 有效，scanned=250、eligible=29。下一步由用户运行 wave 2，完成后先复核再继续；PubMed/EDGAR pilot、B/C、audit、finalize、formal scan、API、victim、Retriever 继续禁止。

### 2026-08-08：Enron v21_r2 capacity wave 95

- [x] 用户完成第 95 个 250-source wave，写入并暂停于 `checkpoint_0095.json`；95 个 checkpoint 连续，前驱 hash 链以及最新 completed wave 的 manifest 与全部输出哈希独立复核通过。
- [x] checkpoint identity=`5a005c18d34e22c74ea03818fb5ba6e8e33caa1acfa7656bbc828c70d302713e`；scanned=`23,750`，eligible=`2,558`，累计 rate=`10.7705%`，Wilson 95% 下界=`10.3826%`；最新 zero-based `wave_index=94`，boundary=`23,500:23,750`，wave identity=`08b2794f...5177c`。
- [x] 确认 `boundary_stress_test`、`primary_canonical=false`、prior applicability=`failed` 未漂移；API calls=0、Retriever runs=0；无 finalization/report 产物。
- [ ] 继续完成剩余 45 waves（11,250 source）；即使已达到 2,250 target，也必须满足 `scan_full_candidate_pool=true` 后才可终止并复核 capacity report。
- [ ] 每次由用户运行一个 `--max-new-waves 1`，先复核新 checkpoint 再继续；禁止 `--force`、路径 override、并行执行或把 partial attempt 当 canonical evidence。

当前执行点：v21_r1 Enron cohort A 保持 failed；v21_r2 capacity 已完成 95/140 waves，scanned=23,750、eligible=2,558，仍处于 paused。下一步由用户运行 wave 96；PubMed/EDGAR pilot、B/C、audit、finalize、formal scan、API、victim、Retriever 继续禁止。

### 2026-08-09：Enron v21_r2 capacity 完成

- [x] 完成固定 35,000-source 全池扫描：140/140 waves，checkpoint 0140 identity=`60fb2fd2e8781e98e31ce5e35a057a783cf890e7b63b34a1b39ef890c20635af`，连续 checkpoint 链与完整 source prefix 独立复核通过。
- [x] capacity passed：query-eligible=`3,786/35,000`（10.8171%，Wilson 95% 下界 10.4960%），超过 target 2,250；claim-eligible=`3,819`，excluded=`31,214`。
- [x] finalization manifest identity=`ee11296e88656f2c1c39aa7919401151b1f46e9b9636396380daf16c897ea0dd`；九类聚合输出哈希、checkpoint hash、plan hash 与 role identity 全部通过，API=0、Retriever=0。
- [x] wave 120 首次 GLiNER2 CUDA OOM 的 `attempt_000` 保留；同一配置重启后 `attempt_001` 成功，没有 CPU fallback、降门槛、改 source 或覆盖失败证据。
- [x] 冻结裁决：capacity pass 只允许 Enron boundary evaluation；`primary_canonical=false`，不得改写 v21_r1 cohort A failed，不得进入 formal promotion。
- [ ] 单独决定是否授权 PubMed cohort A；未获得明确授权前不得启动。EDGAR cohort A 等待 PubMed 独立 gate。
- [ ] B/C、audit、release finalize、formal scan、API、victim、Retriever 继续禁止。

当前执行点：Enron capacity 已完成并通过，不再运行 Enron wave。Enron 保持 boundary stress test，v21_r1 pilot 保持 failed。下一步是是否单独授权 PubMed cohort A 的协议决策；当前不启动任何长任务或下游阶段。

### 2026-08-09：第二次 API 登录切换交接

- [x] 新建自包含交接文档 `研究记录/API登录切换_工作交接_20260809.md`，记录当前协议、artifact identity、禁止事项、Git/环境/测试状态和新账号第一条提示词。
- [x] 用户已还原 2026-08-06 历史交接；保留原文不覆盖，并在新交接中明确 2026-08-09 状态优先。
- [x] 冻结接管边界：Enron capacity 已结束，Enron 仍为 boundary stress test；v21_r1 pilot failed 与 PROJECT_NAME diagnostic-only 均保持。
- [x] 保留 96 条脏工作树状态、全部 partial attempt/artifact 和 `.pytest_tmp`；未 reset、checkout、stash、commit、push、清理或覆盖。
- [ ] 新账号接管后先只读核验交接文档与最终 artifact，再由用户决定是否单独授权 PubMed cohort A。
- [ ] 未授权前继续禁止 EDGAR cohort A、B/C、audit、release finalize、formal scan、API、victim、Retriever 和正式 query。

当前执行点：账号切换暂停。没有正在运行的长任务；Enron 不再续跑。新账号接管后先确认状态，下一步仍是 PubMed cohort A 的单独授权决策。

### 2026-08-09：PubMed cohort A 单独授权

- [x] 用户已明确授权仅启动 PubMed cohort A；Enron 不再续跑，EDGAR cohort A 仍未授权。
- [x] 完成启动前只读核验：PubMed cohort A 为 500 个互异 source，pilot/cohort/source-order/candidate benchmark 身份与哈希一致；当前 PubMed pilot 目录不存在，无 stage plan、checkpoint、attempt 或 report。
- [ ] 用户运行首个 250-source wave：`pilot --dataset pubmed --cohort A --resume --max-new-waves 1`；长任务不由代理执行。
- [ ] 首个 wave 完成后独立复核 stage plan、checkpoint identity、wave manifest、输出哈希、source/type gate、API calls=0 与 Retriever runs=0，再决定是否授权第二个 wave。
- [ ] EDGAR cohort A、B/C、audit、release finalize、formal scan、API、victim、Retriever 和正式 query 继续禁止；PubMed 完整 gate 裁决前不得越级。

当前执行点：PubMed cohort A 已单独获授权，等待用户运行第一个 250-source wave；其余数据集与下游阶段仍保持暂停。

### 2026-08-09：PubMed cohort A wave 1

- [x] 完成第一个 250-source wave并暂停于 1/2；checkpoint identity=`bef73311fdbef264b3e81ee50f824ca307389a021bfa641c44bf088c5c83285c`，wave identity=`bf6d14d1372f91428c7e1f0fa75a51fc9a7a2a6213b681e189b5e983977f1375`。
- [x] 独立验证 stage plan/runtime/pilot cohort、checkpoint、source boundary、wave manifest 与十类输出哈希；API calls=0、Retriever runs=0。
- [x] 首波描述性 source/type 结果通过继续门禁：query-eligible=218/250（87.2%，Wilson lower=82.4887%），五类 formal coverage 均通过；PROJECT_NAME 维持 diagnostic-only。
- [x] 用户使用同一 `--resume --max-new-waves 1` 命令运行第二波；2/2 checkpoint 与正式 `pilot_report.json` 已在下一节完成验证。
- [x] PubMed 完整 gate 裁决前保持 EDGAR cohort A、B/C、audit、release finalize、formal scan、API、victim、Retriever 和正式 query 禁止；期间没有越级运行。

当前执行点：PubMed cohort A wave 1 已验证通过，允许用户运行第二个也是最后一个 250-source wave；尚未形成完整 pilot 裁决。

### 2026-08-09：PubMed cohort A gate 完成

- [x] 完成第二个 250-source wave与 2/2 checkpoint；checkpoint identity=`ca8db06a6d3e6da4fd7d906fa666114b54650ce1566024b1bda6f10ee9c17cca`，第二波 identity=`4bee0cfeb20de6aaf2d7cd15796f06b5d9f842148014e48feb39776e07889731`。
- [x] 正式 `pilot_report.json` passed，report identity=`ff79c46e7dd89d81c288e9703132faacd1ac57e6cd6c50ea6742cbd4dae95021`；独立复核 report/checkpoint/两波 manifest、500-source 精确覆盖与全部输出哈希通过。
- [x] PubMed source gate passed：443/500（88.6%，Wilson lower=85.5150%），failure reasons 为空；五类 formal type gate 全通过，PROJECT_NAME 维持 diagnostic-only。
- [x] 两波 API calls=0、Retriever runs=0；没有 victim、正式 query 或攻击 AUC。
- [ ] 单独决定是否授权 EDGAR cohort A；未获明确授权前不得启动。
- [ ] EDGAR 独立 gate 完成前，B/C、audit、release finalize、formal scan、API、victim、Retriever 和正式 query 继续禁止。

当前执行点：PubMed cohort A 已正式 passed。下一步唯一待决策事项是是否单独授权 EDGAR cohort A；当前不运行任何新长任务或下游阶段。

### 2026-08-09：EDGAR cohort A 单独授权

- [x] 用户已明确授权仅启动 EDGAR cohort A；PubMed cohort A 维持 passed，Enron 维持 boundary stress test。
- [x] 完成启动前只读核验：EDGAR cohort A 为 500 个互异 source，pilot/cohort/source-order/candidate benchmark 身份与哈希一致；formal scope 未漂移，CUDA 可用。
- [x] 确认当前 EDGAR pilot 目录不存在，无 stage plan、checkpoint、attempt 或 report。
- [x] 用户使用可续跑命令完成两个 250-source waves；长任务未由代理执行。
- [x] 独立复核 stage plan、checkpoint identity、两波 manifest、输出哈希、source/type gate、API calls=0 与 Retriever runs=0。
- [x] EDGAR 完整 gate 裁决前保持 B/C、audit、release finalize、formal scan、API、victim、Retriever 和正式 query 禁止；期间没有越级运行。

当前执行点：EDGAR cohort A 已单独获授权，等待用户运行第一个 250-source wave；其余阶段仍保持暂停。

### 2026-08-10：EDGAR cohort A gate 完成

- [x] 完成固定 500 source 的 2/2 waves；checkpoint identity=`2b4c62e2d4b387a1d0b991eb32b3084d04430e43fc8e7fa2c330a92d15cdd99e`，仅有两个成功 attempt，无额外失败/重试目录。
- [x] 正式 `pilot_report.json` passed，report identity=`9a125e6a3a7da44ea9342e88dbfbc219357c40eaaa0b46211f14c6541ceba7c5`；独立复核 report/checkpoint/两波 manifest、500-source 精确覆盖和全部输出哈希通过。
- [x] EDGAR source gate passed：471/500（94.2%，Wilson lower=91.7943%），五类 formal type gate 全通过；PROJECT_NAME 维持 diagnostic-only。
- [x] 两波 API calls=0、Retriever runs=0；没有 victim、正式 query 或攻击 AUC。
- [x] 完成五类 blind audit/release 输入的只读预检；确认当前 release gate 尚未接入 Enron boundary-only 角色，现状下必然因 pilot coverage 或 Enron failed 而失败。
- [ ] 由用户单独授权实现版本化 formal dataset role scope：EDGAR/PubMed 为 primary canonical，Enron 绑定 immutable failed pilot 与 passed capacity，仅允许 boundary evaluation。
- [ ] 完成 role-aware release gate/formal scan fail-closed 接线和测试后，再单独决定是否生成五类 500-row blind audit。
- [ ] B/C、release finalize、formal scan、API、victim、Retriever 和正式 query 继续禁止。

当前执行点：EDGAR 与 PubMed cohort A 均已 passed；Enron cohort A 维持 failed/boundary-only。下一步是 audit/release 输入的只读预检与后续单独授权决策，不自动启动任何新阶段。

### 2026-08-10：audit/release 预检阻断

- [x] 只读确认 `freeze_release_gate` 仍要求三数据集 pilot 全覆盖且全部 passed；省略 Enron 会产生 `pilot_dataset_coverage_mismatch`，纳入 immutable failed report 会产生 `pilot_enron_failed`。
- [x] 确认仓库其他模块仅在 Enron capacity artifact 中记录 `primary_canonical=false`，尚无 release gate/formal scan 的 dataset-role 接线。
- [x] 保持 blind audit、audit report、release gate 与 formal scan 未生成/未启动；没有通过修改 report 或降低门槛绕过。
- [ ] 等待用户授权实现既有 Enron boundary-only 决策的版本化接线；完成前不准备 audit artifact。

当前执行点：三套 cohort A 裁决已冻结（EDGAR/PubMed passed，Enron failed/boundary-only），但 release gate 仍有角色语义实现缺口。下一步不是直接 audit，而是是否授权修复该 fail-closed 接线。

### 2026-08-10：release gate 数据集角色接线

- [x] 用户单独授权修复 release gate 数据集角色接线；未扩大为 audit、release finalize、formal scan 或模型调用授权。
- [x] 冻结 `pcv_formal_dataset_role_scope_v21_r1` / `90a6a96e2e85880568c887e92863bf63c4d24341ab5148aa3c7afd389e2e4fdf`：EDGAR/PubMed=`primary_canonical`，Enron=`boundary_evaluation`。
- [x] 将三套 replay、EDGAR/PubMed passed pilot、Enron immutable failed pilot 和 passed capacity exact identity 接入 role-aware release gate；缺失、重复、状态漂移或 hash 漂移均 fail closed。
- [x] 将 formal 五类 pair coverage 改为只统计 primary 数据集；Enron 证据单列为 `boundary_semantic_valid_pairs`，不得用于主 formal coverage 补数。
- [x] 升级并接线 audit gate：audit prepare/evaluate/release 三处仅允许 EDGAR/PubMed 行；Enron 行和未知 dataset 均拒绝。
- [x] 升级 formal scan identity，只允许 EDGAR/PubMed；scan plan 绑定 role scope version/hash，Enron formal YAML 改为 boundary-only tombstone。
- [x] 真实冻结证据只读核验通过：role failures=`[]`；Enron capacity=`passed`、35,000 scanned、3,786 eligible、`primary_canonical=false`，finalization/checkpoint/九类输出 hash 有效。
- [x] 完成短验证：相关 Python 内存编译通过；entity-policy 8/8、Enron capacity/v21 19/19，共 27/27 tests passed。未运行全量 suite，未执行 API、victim、Retriever 或长任务。
- [ ] 由用户单独决定是否授权准备五类 500-row blind audit；未授权前不生成 audit manifest/labels/report。
- [ ] audit 通过后再单独决定是否授权 release finalize；release gate 通过后再分别授权 EDGAR/PubMed formal scan。
- [ ] B/C、API、victim、Retriever 和正式 query 继续禁止，不能由本次接线授权自动启动。

当前执行点：角色接线缺口已闭环，现有 Enron failed/capacity 边界未被改写。下一步唯一新增动作是“是否授权准备五类 500-row blind audit”的决策；当前尚未生成任何下游 artifact。

## 2026-08-10：capacity-qualified primary 修订

- [x] 接受用户的新论文范围：EDGAR、Enron、PubMed 全部进入主表；EDGAR/PubMed=`standard_primary`，Enron=`capacity_qualified_primary`。
- [x] 保持 Enron cohort A `49/500 failed`、35,000-source capacity artifact 的 `boundary_stress_test`/`primary_canonical=false` 原文与哈希不变；通过新的 promotion 层解释主表资格，不追溯改写旧 artifact。
- [x] 冻结 dataset-role scope v2：`pcv_formal_dataset_role_scope_v21_r2_capacity_qualified_primary` / `65dff74de67495f6afc9aa2c5f9f4d1d41a84e8f2125e01e7ea00a04bdef0450`。
- [x] 冻结 dataset-stratified evidence scope v2：`pcv_formal_evidence_scope_v21_r2_dataset_stratified` / `6fdc6ef950b0d1abed43fd2395657fa9ec814fc0eebab181b489c159adce778e`；五类 formal、PROJECT_NAME diagnostic-only 不变。
- [x] 将 blind audit 改为 600 行：3 datasets × 5 types ×（36 accepted + 4 hard negatives）；用户冻结复核 4/cell，共 60 条。
- [x] release gate 接受三套 exact replay、EDGAR/PubMed passed pilot、Enron immutable failed pilot 与 passed capacity evidence；每个 dataset×formal-type 必须至少有 36 个 frozen valid pairs。
- [x] 实现 Enron promotion：passed release 后按 seed 42 从 3,786 个 frozen eligible source 确定性选 2,250；promotion identity、release hash、runtime tree、query hash、checkpoint 与选择哈希任一漂移均拒绝。
- [x] 将 split/formal eligibility 校验接入 promotion manifest；EDGAR/PubMed 仍走 fresh formal scan，Enron 不重跑 35,000-source capacity scan。
- [x] 更新 v2 data/scan configs 与 CLI：新增 `promote-enron-capacity`、`check-enron-promotion`；输出隔离到 `artifacts/v21/entity_policy_r2/`。
- [x] 只读验证六份 report roles=`[]`，Enron capacity=3,786/35,000 passed；预演 selected=2,250、`selected_source_keys_sha256=e6e0a75507db6c83b9ae1517a99a89eaa0de751b69390057da2e74937df6f4eb`、`whitelist_hash=3edb7e3d4fe54299e5386ed25f8c1d1ecfacce2e18fe96dbb7e057035e1b77da`。
- [x] 完成短验证：43/43 targeted unittest、9 个 Python 文件内存编译、7 个 YAML 解析、CLI help 与目标 diff check 通过；未运行全量 unittest。
- [ ] 由用户单独授权后，才运行 `prepare-audit` 生成 600-row blind audit。当前未生成。
- [ ] 用户与 assistant 完成 labels/review 后，单独授权 `finalize`；passed release gate 尚不存在。
- [ ] release 通过后，先生成并核验 Enron promotion manifest，再分别冻结 EDGAR/PubMed fresh formal scan plan 与 Enron promoted split plan。
- [ ] B/C、API、victim、Retriever、正式 query 与任何长任务仍未授权，不由本次修订自动启动。

论文报告约束：主文报告三数据集逐项与 all-three macro；补充 standard-primary sensitivity（仅 EDGAR/PubMed）。Enron 必须同时披露 cohort A failed、capacity yield、promotion selection 与“capacity-qualified”限定。

当前执行点：代码/配置/门禁/记录已完成，所有下游 artifact 均未生成。下一步唯一可新增动作是用户是否授权准备五类、三数据集分层的 600-row blind audit，不再是旧 500-row audit。

## 2026-08-10：600-row blind audit preparation

- [x] 用户单独授权准备 audit；该授权不包含 assistant labels、user review、audit evaluation、release finalize 或后续实验。
- [x] 执行前验证六份 frozen report 的 exact role/status/identity，role failures=`[]`；Enron pilot 保持 `failed`，未改写 report。
- [x] 生成 `artifacts/v21/entity_policy_r2/audit/` 下 blinded、key 和 manifest；protocol=`v21_entity_policy_audit_v4_dataset_stratified_r1`，status=`prepared`。
- [x] 冻结 manifest SHA-256=`d139849a27332edfbe2935a7b5705a59a2b746871f0faef9279b7ad24009a283`，audit identity=`aa15ca5b8d1ba8892711d059bced44b90e0785286afc42710462448fd567a698`。
- [x] 验证 600 unique rows：每数据集 200、每类型 120、每 dataset×type 40；冻结 user review 60 IDs、每 cell 4。
- [x] blind integrity 通过：PROJECT_NAME=0、forbidden/leakage fields=0、预填 judgments=0；key 仅验证 600 行和 SHA-256，未查看内容。
- [x] 本阶段 API/victim/Retriever/正式 query 调用新增 0；未生成 labels、review、audit report、release 或 promotion。
- [ ] 单独授权后，才对 blinded 文件生成完整 600-row assistant labels；不得读取 key。
- [ ] 用户按 manifest 冻结 IDs 完成至少 60-row review；每个 dataset×type 恰好覆盖 4 条。
- [ ] labels/review 完成并验证后，再单独授权 audit evaluation 与 `finalize`。

当前执行点：600-row blind audit 已准备并冻结。下一决策点是是否授权 assistant 对 blinded 文件完成 600 条盲标；release gate 仍不存在。

## 2026-08-10：blind subtype leakage blocker

- [x] 用户授权 assistant labeling；在写任何 label 前发现 blinded row 泄漏 `semantic_subtype=mismatched_donor_type`。
- [x] 只读确认 30 leaked rows，15 cells×2；定位为 hard-negative sentinel 经 blinded fallback 原样公开。
- [x] 保持 key 未读、assistant labels 不存在、evaluate/finalize 未运行；r2 artifact 原样保留为 compromised evidence。
- [ ] 等待用户单独授权新协议修复：所有 blinded rows 删除 machine subtype，增加泄漏回归门禁，升级 audit identity，并在隔离目录重新抽样 600 rows。
- [ ] 新 audit 通过 blind-integrity 检查后，必须从头重新授权/执行 assistant labels；不得续用本次已查看的旧 cell。

当前执行点：assistant labeling 已 fail closed 暂停。release、promotion、formal scan 继续 blocked。

## 2026-08-10：blind subtype redaction v5 / r3 audit

- [x] 用户单独授权修复 blind subtype 泄漏并重生 600-row audit；授权范围不包含 labels、review、evaluate/finalize 或后续实验。
- [x] 新增 blinded schema 字段白名单；从所有 blinded rows 移除 `semantic_subtype`，并禁止 semantic resolution、bucket/decision、hard-negative reason、source path、pair/fact ID 等机器侧字段。
- [x] 将 `mismatched_donor_type` 冻结为 forbidden sentinel；`prepare_blinded_audit`、`evaluate_audit`、release retained-evidence validation 均执行相同 schema identity 与 row-level fail-closed 校验。
- [x] audit protocol 升级为 `v21_entity_policy_audit_v5_blind_subtype_redaction_r1`；默认输出隔离到 `artifacts/v21/entity_policy_r3/`，未覆盖 r2 compromised evidence。
- [x] 回归测试覆盖“即使篡改 blinded 并重算 manifest hash，evaluate 仍拒绝 subtype sentinel”；31/31 相关测试、5/5 内存编译和 CLI help 通过。
- [x] 使用原六份 frozen replay/pilot report 重生 r3 audit；Enron cohort A 仍为 immutable failed，dataset-role identity 未变。
- [x] r3 结构核验通过：600 unique rows，3 datasets×200、5 types×120、15 cells×40；machine subtype/sentinel/prefill 均为 0；旧 30 条泄漏 hard negative 与新 audit overlap=0。
- [x] 冻结 r3 hashes：manifest=`0ea92ae2458f443386a0d2a80f1769c76c165e5be1edd4e1c7bccd09faa2cd60`；identity=`e7dc2324af3812bc4cf6d0fb2188303e503a234ee0d7e0327dcc1e28934b5d43`；blinded=`0be539eadfa57aeb2c3c6e58d6eba0c0a2d14d04a025c606c3211b76d0708a81`；key=`ca577b1d145bb22b93f3b07605a3fbeb5dc1210c805f51b9d143937d196b9952`；user-review IDs=`712d2b51d0a743dec4e1179cd9c3c121777bd7dfcfe4171353eac53b67cff868`。
- [x] key 仅做 600 行计数和 SHA-256 核验，未读取/解析/展示内容；本轮零 API、零 victim、零 Retriever、零正式 query。
- [ ] 用户重新单独授权后，才从头生成 r3 的 600-row assistant labels；禁止续用 r2 身份或旧授权。
- [ ] 用户按 r3 manifest 新冻结的 60 IDs 完成 review 后，再单独授权 evaluate/finalize。

当前执行点：r3 audit 已 prepared 且 blind-integrity gate 通过。唯一下一决策是是否重新授权 r3 assistant blind labeling；release、promotion、formal scan 继续 blocked。

## 2026-08-10：r3 assistant blind labeling

- [x] 用户重新单独授权 r3 600-row assistant blind labels；授权不包含 user review、key access、evaluate/finalize 或后续实验。
- [x] 冻结 annotation plan，绑定 v5 audit identity、blinded hash 与 schema hash；plan SHA-256=`1a5b20093ce6f682430639ec6ae34160d9ce34f4ca0d4e2d41d897b481290725`。
- [x] 只基于 blinded 的 entity/claim 与冻结语义范围逐 cell 审核；不读取 key，不使用 36 accepted/4 negative 配额倒推判断。
- [x] 生成 600/600 unique labels：pass=371、fail=225、uncertain=4；15 cells 均为 40，30 条 visible unchanged counterfactual 全部 fail。
- [x] 冻结 labels SHA-256=`0f4736b2e54e498092a77c4e7645d5266abb8c916fd8f95420b503f64b2813b5`，labels manifest SHA-256=`136531e52bf4fd433c790e9980f6715d3146fb1e06b3c9f319b4b1d754b65cf3`，labels identity=`db1bfe7eda7aa0979274dfee851270e7d9f760731d1734f06f75fb94fa7c9db3`。
- [x] 独立一致性验证 problems=`[]`：exact ID coverage、judgment/field schema、reason completeness、cell counts、input hashes 全部通过。
- [x] 识别 4 条 uncertain；其中 1 条已在 frozen 60 review IDs，另外 3 条必须追加人工复核，因此通过门禁所需 user review 为 63 个唯一 ID。
- [x] 本阶段 key content access=0、API/victim/Retriever/query calls=0，evaluate/finalize=0。
- [ ] 经用户单独授权后，生成仅含 blinded 内容的 63-row human-review template；不得附带 expected decision 或 hard-negative reason。
- [ ] 用户本人填写 63 条 `human_judgment` 后，先做 review schema/hash 检查；再单独决定是否授权 evaluate/finalize。

当前执行点：assistant labels 已完整冻结。下一步只能是用户是否授权准备 63-row blind human-review template；release、promotion、formal scan 继续 blocked。

## 2026-08-10：63-row blind human-review template

- [x] 用户单独授权准备模板；授权不包含代填 human judgment、key access、audit evaluation、release finalize 或后续实验。
- [x] 验证 r3 audit identity、blinded hash、assistant-labels identity 与冻结 60-ID hash 均未漂移。
- [x] 选择冻结 60 IDs 加 3 个不重复 uncertain 补审 ID，共 63 unique IDs；冻结 15 cells×4 覆盖保持不变，4 个 uncertain 全部覆盖。
- [x] 生成无 assistant judgment、无 expected decision、无 hard-negative/subtype/scope 标记的 JSONL 模板；所有人工判断字段为空。
- [x] 冻结 template hash=`bf71aaea68baf4eaa8e34ce6fdad99a85362b6399af7bacf053103b0ee3d4d3a`、manifest hash=`d1ab00e2f6467d017daa61f174a035916ff1dfc81f3f3b9c467eadbf59464fdb`、identity=`6d677f1d2319c65b8db42380d40dbcac3f29e855cb66e715c05081dfb4b90feb`。
- [x] 独立 blind/schema/coverage/hash 验证 passed；key content access=0、API/victim/Retriever/query=0、evaluate/finalize=0。
- [ ] 用户本人填写 63 行 `human_judgment=pass|fail`，不得由 assistant 根据自身 labels 代填。
- [ ] 填写完成后先单独执行不访问 key 的 review schema/hash 预检；再由用户另行决定是否授权 evaluate/finalize。

当前执行点：63-row blind template 已冻结，等待用户人工复核。release、promotion、formal scan 继续 blocked；在新授权前不得读取 key 或运行 evaluate/finalize。

## 2026-08-10：63-row human review blind-only precheck

- [x] 用户完成 63-row 工作模板；仅执行不访问 key、不中途比较 assistant labels 的 schema/identity 检查。
- [x] 验证 63/63 unique IDs、frozen 60 + extra uncertain 3 精确覆盖、所有 immutable blinded 字段未改、`human_judgment` 仅含 `pass|fail`。
- [x] 冻结 canonical review hash=`2b1480a6fa5e816743a609d9e68135083e39b571ec29c405943be3310b68a113`、manifest hash=`4760cc61204a8826035517f50167be56df44a448ab4da60be3699325a5cddc2b`、identity=`87d369c20d169dd8b5e9906dd8498d814d951686b87ded60ab6b2a6bc7459488`。
- [x] 记录 judgment distribution：pass=63、fail=0；可选判据/evidence 填写数均为 0；可见 unchanged-claim/same-entity 硬矛盾数为 0。
- [x] key content access=0、assistant-label content access=0、API/victim/Retriever/query=0、evaluate/finalize=0。
- [ ] 用户确认 63 个 pass 均为逐条独立判断，不是批量填充；不得为满足预期分布或 assistant agreement 反向修改。
- [ ] 获得该确认及新的 evaluate/finalize 单独授权后，才允许进入 audit evaluation；否则重新进行独立人工复核并产生新 review identity。

当前执行点：review schema 已通过并冻结，但全 pass 分布仍等待人工意图确认。release、promotion、formal scan 继续 blocked；尚无 audit pass/fail 结论。

## 2026-08-10：human-review independence attestation

- [x] 用户明确确认：`确认全部为逐条独立判断`；不根据配额或 assistant agreement 修改冻结 judgments。
- [x] attestation 精确绑定 63-row review hash/manifest/identity，artifact SHA-256=`5f1cfdc45b8ccd52bb770b50662d386cbc00912593233de611b66b4af7a8893d`，identity=`e4cab8d56d5d3338f382548757799dae3a61654477edf044599568a252d7f3dd`。
- [x] attestation status=`confirmed_pending_evaluation_authorization`；明确不授权 key、evaluate/finalize、promotion、formal scan 或模型调用。
- [x] 本阶段 key/assistant-label content access=0、evaluate/finalize=0、API/victim/Retriever/query=0。
- [ ] 等待用户新的单独授权后，才可运行 audit evaluate + release finalize；运行时必须原样使用冻结的全 pass human review。

当前执行点：人工独立性确认已冻结，但仍无 audit pass/fail 结论。下一步唯一决策是是否授权 evaluate/finalize。

## 2026-08-10：r3 audit evaluation / release finalize

- [x] 用户单独授权 evaluate + finalize；正式 evaluator 首次按授权读取 key，不修改冻结 labels/review。
- [x] finalize preflight 通过：六份 reports role/status/identity、r3 audit/labels/review/attestation hashes、runtime tree 与空输出目录均有效。
- [x] audit 正式结果=`failed`：accepted passes=369/540（68.33%），hard-negative correct rejections=58/60（96.67%）。
- [x] dataset×type cells passed=1/15（仅 PubMed/LOCATION）；entity types passed=1/5（仅 LOCATION）；audit failure reasons=22。
- [x] assistant-human compared=59，agreement=39/59（66.10%）<90%；4 个 assistant uncertain 不进入 agreement denominator。
- [x] release gate fail closed：status=`failed`、failure=`audit_failed`；audit report hash=`7a490ef065904407d8b3084969ef77c36883d4240cba4e68271473ce517f7558`。
- [x] release hash=`640e7851f30a23ed5df9ec23f0b94d77a0c8510b75af5c12949db584e668bb74`、identity=`4ca28106dc538f9680c0d6a8d735d70fad96cf4af7bb8362bcd918e3b93d391d`；independent identity/hash/runtime check 通过。
- [x] `check-release` 按设计拒绝 failed gate；未生成 Enron promotion，未启动 formal scan/API/victim/Retriever/query。
- [ ] 保留 r3 全部失败证据，不原地改标签、重评或降门槛；r3 不得进入 canonical release。
- [ ] 等待用户决定是否单独授权只读 failure diagnosis 与 r4 protocol design；任何 r4 必须是新 identity、新输出和预冻结规则。

当前执行点：r3 release 已正式 failed。所有正式下游阶段 blocked；下一步不是 promotion/formal scan，而是是否授权失败诊断与新协议决策。

## 2026-08-10：r3 failure diagnosis

- [x] 用户授权只读诊断；连接 r3 600 rows、63 human rows 与六份 report/29 claim files，540/540 accepted rows 上游 provenance 完整。
- [x] 生成严格分析包 r2：analysis report、stats appendix、figure catalog、3 PDF + 3 PNG、3 CSV、diagnosis/case JSON；manifest hash=`76dac1166cfecfbff5c01381a4273d3ae22637275f97c4aa0bcdc62f82bb89e8`，identity=`7a0fa97d994e3726e8b2e999e626b980be418d0674c0460cd02c18ab4b7f3aa9`。
- [x] 输入/输出 hash、manifest identity、15 cells、3 PDF/PNG header 与三张图 visual QA 全通过；partial/r1 attempts 保留并标记 superseded。
- [x] 证实 540/540 accepted 仅有一个 GLiNER supporting model、target/boundary votes 均为 1；145 accepted rows 被判 declared-type incorrect。
- [x] 证实 22 subtype rejects 中 22/22 符合 frozen machine subtype + format rule，属于 assistant rubric overreach；assistant 另漏过 2 个 wrong-type hard negatives。
- [x] 证实 human sample 含 3 hard negatives且全部误 pass，specificity=0/3；human template/rubric 不足以做 adjudication gold。
- [x] replay/pilot accepted pass 分别 68.36%/68.25%，问题跨 stage；confidence≥0.90 仍仅 262/311 pass。
- [x] 决策冻结：当前不全量重跑三数据集实体抽取；优先复用 Step 06 facts/source spans/candidate claims 做 r4 semantic revalidation。
- [ ] 用户单独授权后才制定 r4 protocol；必须预冻结 reviewer calibration、policy/subtype rubric、双人 adjudication、sampling 与新 identity/output。
- [ ] 只有 r4 revalidation 证明 span/entity candidate 系统性损坏且过滤/重分类不可修复时，才重跑受影响 dataset×type；不得默认三数据集全量重抽。

当前执行点：r3 failure mechanism 已定位，r3 仍 failed。下一步是是否授权制定 r4 方案，不是启动任何抽取、API、promotion 或 formal scan。

## 2026-08-10：r4 Phase 0/1 执行状态

- [x] 冻结 `configs/entity_policy_r4_protocol.yaml`，隔离 output、复用边界、r3 exposure 排除和 consensus 角色。
- [x] 实现 `scripts/35_prepare_v21_entity_policy_r4.py inventory/preflight`；exact resume 幂等、身份漂移 fail closed。
- [x] 修复 failed gate 的 resume 退出码；canonical Phase 1 输出迁入 `phase_1_r2/`，首版 attempt 保留为 superseded provenance。
- [x] 定向测试 3/3、内存语法/导入检查通过；未加载模型、未调用 API/victim/Retriever。
- [x] 生成 22,015-row inventory；13/15 dataset×type cell 达标。
- [x] Phase 1 preflight 正式 fail closed：PubMed/CONTRACT_TERM=15/36、PubMed/PERSON=22/36；其余 cell 无需 refill。
- [ ] 冻结 PubMed-only targeted refill cohort，排除 r3 暴露 source、当前 inventory source 和 canonical content duplicate。
- [ ] 用户运行可续跑的 refill 长命令；每 wave 后只检查 fresh candidate capacity，不查看 victim/AUC。
- [ ] 两个 PubMed cell 达到 minimum 36、目标 72 后重建 inventory/preflight，再进入 Phase 2 ensemble revalidation。
- [ ] Phase 3 前冻结双 reviewer calibration/rubric/adjudication；任何看过 r3 key 的 reviewer 不得作为唯一正式 blind reviewer。

## 2026-08-10：r4 Phase 1A PubMed targeted refill

- [x] 冻结 PubMed-only 配置：5,000 fresh sources、250/source wave、20-wave 上限、seed=42。
- [x] 固定四层 source exclusion 与 canonical content 去重，禁止旧 rc2 claims 接线。
- [x] 固定停止门槛：新增 CONTRACT_TERM≥57、PERSON≥50；只在完整 wave 后裁决。
- [x] 实现 `freeze-refill`、强制 `run-refill --resume`、`status`、immutable attempts/checkpoint/report。
- [x] 外部调用保持关闭；offline compressed query/stealth 仅作 source-capacity probe，不能进入正式 query manifest。
- [x] 定向测试 7/7、内存编译、CLI/status 与敏感信息扫描通过；当前无 plan/wave artifact。
- [ ] 用户运行 source-plan freeze；登记 plan/source-universe/exclusion/runtime identities。
- [ ] 用户每次续跑一个 wave，核验 fresh_counts 与 checkpoint；长任务不得由助手代跑。
- [ ] 达标后将 refill claims 作为新 claim input 重建 r4 inventory/preflight；原 phase_1_r2 保留为 superseded evidence。

当前执行点：runner 已完成，下一步只能冻结 PubMed refill source plan；Phase 2、fresh audit、release、formal scan、API/victim/Retriever 仍禁止。

### r4 refill r1→r2 修订

- [x] r1 首波在 0doc 因 candidate 缺失 `group` fail closed；无 checkpoint、无完整 wave。
- [x] 保留 r1 plan、66,736-row candidate 与两个 benchmark-only partial attempts；标记 superseded，禁止合并。
- [x] r2 使用 `freeze_source_plan` 统一 candidate schema并固定 5 chunks/source；输出目录与协议身份独立。
- [x] 新增针对原始无-group processed row 的回归；定向测试 8/8 通过。
- [ ] 重新冻结 r2 plan，然后每次仅运行一个 r2 wave 并复核 checkpoint。

当前执行点更新：r1 已停止；r2 尚未冻结。Phase 2 及所有正式下游继续 blocked。

### 2026-08-11：r2 targeted refill 运行进度

- [x] r2 source plan 冻结完成。
- [x] waves 0–1 完成并通过 manifest/checkpoint/hash 核验；无额外 incomplete attempt。
- [x] fresh counts=`CONTRACT_TERM 19 / PERSON 31`，duplicates=0，external calls=0。
- [ ] 剩余目标=`38 / 19`；继续 `--resume --max-new-waves 1`。
- [ ] 只有 checkpoint status=`passed` 后才允许生成 report 并重建 r4 inventory/preflight。

当前执行点：2/20 paused，继续 r2 wave 2；不得启动 Phase 2 或任何正式调用。

### 2026-08-11：r4 Phase 1A/Phase 1 完成

- [x] refill r2 7/20 waves 后 passed；fresh counts=68/94，report/hash/identity 验证通过。
- [x] 仅接入 7 个 complete wave claims；两个 benchmark-only partial attempts 保留但排除。
- [x] 新增 provenance manifest SHA/protocol/status/identity 四重绑定及回归测试；相关测试 9/9。
- [x] 生成 `phase_1_r3` inventory=24,190；15/15 cells 均达到 target，无 warning。
- [x] `phase_1_r3` preflight passed，inventory/preflight identities 分别为 `ac7d82c3...` / `a6ed18fc...`，resume 幂等。
- [ ] 冻结 Phase 2 calibration cohort、consensus thresholds、模型执行与 checkpoint schema。
- [ ] 长模型任务继续交由用户逐批运行；Phase 2 通过前不启动 reviewer audit/query/victim/Retriever。

当前执行点：Phase 1 capacity gate 已通过；Phase 2 尚未开始。

### 2026-08-11：r4 Phase 2A calibration freeze/runner

- [x] 只读核验 model lock、`audit_consensus` batch API、Phase 1 r3 provenance 与 r3 failure diagnosis。
- [x] 将 r3 暴露行限定为 development calibration，禁止进入 fresh r4 audit；固定 15 cells×(12 accepted candidates+4 hard negatives)=240 rows。
- [x] 分离 30 条结构负例与 30 条语义 donor-type 负例；结构负例保留并在 semantic threshold 前直接拒绝。
- [x] 冻结双 reviewer rubric/templates、阈值网格、零 false-accept/retention 约束、tie-break 与 victim/AUC 禁止查看项。
- [x] 实现 `scripts/37_run_v21_entity_policy_r4_phase2.py freeze-calibration|status|run-calibration --resume`；12 个 immutable batches，prediction cache 可补算中断项。
- [x] r2 plan identity=`22f7898b54b82fc24cf140c0b4e0c3411be12579bb6914b6a5ceff38ea11ac55`；freeze resume 幂等，当前 0/12 paused，full revalidation allowed=false。
- [x] 定向 unittest 6/6、内存编译与 reviewer-template 泄漏检查通过；API/victim/Retriever=0。
- [x] 最终关联回归 15/15、CUDA/解释器、YAML、plan identity、secret scan 与 diff check 通过；ruff 未安装，未改环境。
- [ ] 用户逐次运行 `run-calibration --resume --max-new-batches 1`，每批后执行 `status`；不得向 superseded r1 写 batch。
- [ ] 两名未接触 private key/model predictions 的 reviewer 独立完成 A/B 模板；disagreement/uncertain 由第三方 adjudicate。
- [ ] ensemble predictions 和 adjudicated labels 均冻结后，实现并运行 threshold evaluator/calibration gate。
- [ ] 只有 calibration gate passed 才冻结 full 24,190-row revalidation cohort/runner；否则 fail closed，不查看攻击 AUC 调参。

当前执行点：Phase 2A r2 已冻结但尚未加载模型。下一步只能运行第一个 calibration batch，或并行安排两名独立 reviewer；formal revalidation、fresh audit、query、victim、Retriever 仍 blocked。

### Phase 2A batch 0 启动前快照修复

- [x] 定位失败为 base snapshot 缺少 `image/GitHub.png`；不是 CUDA/OOM、模型推理或 checkpoint 错误。
- [x] 核验 large 同名文件 SHA 与 base lock 精确匹配；其余 57 个锁定文件全部存在且 hash 正确。
- [x] 确认当前只有 immutable batch plan，模型调用=0、completed batch=0，不需要清理或重冻 r2。
- [x] 将 large 的同 hash 图片复制到 base 对应路径并复核 SHA。
- [x] 使用原命令 `run-calibration --resume --max-new-batches 1` 续跑 batch 0。
- [x] batch 0 只读验证通过：EDGAR 20 rows/40 texts、3 voters、OOM=0、predictions/manifest/checkpoint hashes 有效。
- [ ] 继续 batch 1；仍每次最多 1 个 batch并在完成后核验 status/manifest。

当前执行点：1/12 paused；下一步是同一 r2 identity 的 batch 1，不重冻、不清理 batch 0。

### Phase 2A predictions complete

- [x] 同一 r2 identity 完成 12/12 batches；checkpoint status=`predictions_complete`、identity=`05c58b26d1089af28840ea2245d07ab6c15e3ff91e8ce4916b63d9259604cf8c`。
- [x] 240/240 rows 与 IDs 精确覆盖；三数据集各 80、15 cells 各 16，structural=30、semantic eligible=210。
- [x] 12 个 prediction/manifest hash、四模型 ID/revision/role、checkpoint entries 全通过；aggregate problems=[]。
- [x] OOM retries=0；cache misses/writes=`1600/1500` 的差值由 unchanged pairs 的后端级文本去重完全解释。
- [x] API/victim/Retriever=0；没有查看 threshold performance、victim response 或攻击 AUC。
- [ ] Reviewer A 与 B 分别由两个独立人员填写各自 240-row template；禁止互看、禁止访问 private key/model predictions。
- [ ] 对任一 disagreement/uncertain 进行第三方 adjudication，冻结 adjudicated-label manifest/hash。
- [ ] labels 冻结后才实现/运行 threshold evaluator；在此之前 full revalidation、fresh audit、query、victim、Retriever 继续 blocked。

当前执行点：模型 predictions 已完成；reviewer 角色按用户原方案另行更正，暂不运行 threshold evaluator。

### Phase 2A reviewer 接线更正

- [x] 用户确认方案是 Assistant 全量审核后由用户复核，不是两名独立人工 reviewer。
- [x] 冻结边界：更正前尚无 labels、human review、threshold metrics 或 AUC，raw predictions 无需重跑。
- [x] 旧 A/B 双人工模板保留为 superseded design evidence，不删除、不填写、不合并。
- [ ] 建立独立 `phase_2_review` manifest，绑定 r2 prediction checkpoint/cohort/rubric hashes；不得改 r2 model outputs。
- [ ] Assistant 只读取 blinded calibration rows/rubric，审核 240/240；不读取 private key 或 model predictions生成标签。
- [ ] 从 Assistant labels 生成用户复核模板：每 cell 预冻结 5 条共 75 条，加全部 uncertain（去重）。
- [ ] 用户逐条复核；冻结 agreement、corrections 与 adjudicated-label manifest 后才运行 threshold evaluator。
- [ ] 论文中将此阶段描述为 development assistant annotation + human validation；fresh formal audit 另用严格 blind protocol。

当前执行点：下一步是实现并冻结更正后的 review-only identity，然后由 Assistant 完成 240-row 初审；不再运行模型。

### 2026-08-12：v22 calibration_r2 执行结果

- [x] 提交 r2 runtime：commit=`2cfe3f668f4df3acda7b742884d5a67b84d87d45`。
- [x] 冻结独立 300-row calibration_r2；240 real + 60 controls，r1 pair/source/fact overlap=0。
- [x] Assistant 仅依据 blinded rows 完成 300/300 标签；yes=108、no=192、uncertain=0。
- [x] labels schema/ID/hash receipt 校验通过；解盲后 structural controls 拒绝率=100%、real uncertain rate=0%。
- [x] 运行预注册 threshold evaluation；0.50–0.85 无阈值达到 judged usability ≥90%。
- [x] r2 fail closed：status=`failed_new_protocol_identity_required`、selected threshold=null、threshold manifest 未生成。
- [x] 定位主因：0.50–0.75 容量投影通过，但 utility score 无法把自然、上下文兼容、自包含且可辨别的替换排到高分端。
- [ ] 保留 r1/r2 全部失败证据，禁止原地改标签、降门禁、覆盖 evaluation 或续跑为 passed。
- [ ] 若用户授权，设计独立 calibration_r3：预冻结新的 context-compatibility/queryability 硬门禁或评分，再抽取 fresh rows；不重新扫描 source pool。
- [ ] calibration_r3 通过前，fresh audit、formal scan、split、shadow、Luna query、Gemma victim、Retriever 继续 blocked。

当前执行点：calibration_r2 已正式失败并完成诊断。下一步只能是是否授权设计新的 calibration_r3 协议，不能进入 formal scan。

### 2026-08-12：v22 calibration_r3 实施状态

- [x] 冻结 r3 设计边界：独立 identity/output；不改 r2；不读取 membership/victim/AUC。
- [x] 实现 context overlay：确定性单槽/span/冠词/别名 hard gates，角色与 queryability soft score。
- [x] 固定单一 `fastino/gliner2-base-v1@f5b2ec...` 反事实上下文验证：same type + exact slot + score≥0.65。
- [x] 实现 numbered runner：context plan、可续跑 validation、capacity、fresh calibration、labels/evaluate。
- [x] r1/r2 pair/source/fact 三层排除；冻结前容量检查 15/15 cells 足够，最小=117。
- [x] 定向测试 33/33、全量 unittest 439/439、AST/diff/secret check 通过。
- [x] 用户确认并提交 r3 五个 runtime 文件；commit=`25ce2c4d1e9e2c2f3be01b3e4fd00d8c2d04d40c`，未夹带旧脏工作树。
- [x] 冻结 context plan：19,469 rows / 39 batches，identity=`5db279d9787065fb295ac0cbad498edb4922007ef1954597ed844312631560b1`。
- [x] 首个 context batch 完成并复核：512 rows，383 pass / 129 reject；模型 revision、exact span 输出、CUDA/fp16 和 checkpoint 均有效，当前 1/39 paused。
- [x] 用户续跑剩余 context batches；39/39 完成，19,469 rows 中 15,092 通过，合并 SHA-256=`02e71e70b36b591dd4c81f59ee18a4bc1787e3759da25f013536e0a118f60bae`。
- [x] 运行 15-cell capacity gate：全部通过；每 cell 要求16个唯一 fact，最小 PubMed/CONTRACT_TERM=34。
- [x] 冻结 fresh 300-row calibration：240 real+60 controls，r1/r2 pair/source/fact overlap=0，plan identity=`2912806746828fe3b211bba708e047196118f78feed73756e291993e301c3cb4`。
- [x] Assistant 仅依据冻结 blinded rows 完成300行标签；yes=122、no=178、uncertain=0，写入前未读取 private key。
- [x] labels validator 通过；receipt identity=`81e43c6c79c8376d6f8dac3d992f50a709493e0d85aa7068c3f9c5543fbb01dc`。
- [x] 运行预注册 `evaluate`：60/60 controls拒绝、real uncertain=0%，但无阈值达到90% usability，selected threshold=null。
- [x] r3 fail closed：status=`failed_final_calibration_revision`，evaluation identity=`333e920d01cfb77839526d988787ebb8b9c11ef42dc2d8308a45b2eae4aa5189`。
- [x] r3最高 usability=61.49%@0.70，较r2最高47.42%提高14.07个百分点，但仍不足；EDGAR最低阈值投影也仅1,760.98<2,500。
- [ ] 保留 r3 labels/evaluation，禁止原地修改、降低门禁或进入150-row fresh audit；按预注册要求停止复杂评分路线。
- [ ] 等待用户决定替代方向；未有新决策前 formal scan、split、shadow、Luna query、Gemma victim、Retriever 全部 blocked。

当前执行点：r3 已正式失败并完成诊断。结构控制有效且纯度较r2改善，但90% usability与EDGAR 2,500-source projection均未通过；下一步是用户重新决策，而不是自动开始r4或正式下游。

### 2026-08-12：Restoration-First 纠偏与 API 登录切换

- [x] 明确攻击恢复目标：corrupted entity 输入用于测试 RAG 是否依靠目标文档恢复原实体，而不是优化反事实自然性。
- [x] 取消尚未实施的 Luna `Generation-First`；Luna 暂仅保留下游 query-generator 角色。
- [x] 冻结概念边界：反事实只需通过原事实 grounding、精确单槽、source absence、粗类型/格式兼容和最低句法有效性；不得以自然性分数主导 pair/source 选择。
- [x] 将下一方向记为待授权 `Restoration-First`：核心信号为 original-entity recoverability、source-specific non-entity anchor、verification discriminativeness、自包含与可解析性。
- [x] 明确 matched LLM-only 只作机制对照，不得读取其响应挑选 pair、删除 source 或调整阈值。
- [x] 保留 v22/r1-r3 全部失败证据；其 labels、threshold 和旧 usability gate 视为 `superseded_goal_mismatch`，不得原地续跑或改写。
- [x] 新建 `研究记录/API登录切换_工作交接_20260812.md`，记录机器状态、hash、复用边界、禁止事项和新会话接管指令。
- [ ] 用户完成 API 登录切换后，先只读复核 git status、v22 status 和 r3 evaluation，并确认没有身份漂移或越级调用。
- [ ] 等待用户明确授权后，才制定/实现独立 `pcv-mia-v23` / `pcv-restoration-first-v23`；先冻结协议与测试，不直接启动 API 或长任务。
- [ ] 新协议优先复用冻结 source pool/order、原事实/span provenance；从 pre-r3 候选重新应用 Restoration 门禁，不把 r3 context-passed 集合当唯一候选全集。
- [ ] 新身份的小型离线 pilot/capacity gate 通过前，禁止 formal scan、split、fresh audit、shadow、Luna query、Gemma victim 和正式 Retriever。
- [ ] 任何真实 API、victim、Retriever 或 GPU 长任务必须再次获得用户明确授权；API 登录切换本身不构成调用授权。

当前执行点：研究目标已从“反事实自然性优化”纠偏为“原实体可恢复性优先”。v23 只是待授权方向，尚未冻结或实现；唯一下一步是在新 API 登录会话完成只读接管确认，并等待用户授权制定/实现 Restoration-First 新协议。
### 2026-08-12：v23 Restoration-First design r1 草案（已被 r2 supersede）

- [x] 完成新 API 登录会话的只读接管，核验 git status、v22 status 与 r3 evaluation；无身份漂移或越级调用。
- [x] 用户明确授权制定独立 v23 协议。
- [x] 冻结设计身份：`pcv-mia-v23` / `pcv-restoration-first-v23` / `pcv-restoration-first-v23-design-r1`，输出根=`artifacts/v23/`。
- [x] 冻结 v22 复用边界：只复用 source pool/order、完整 source hash、原事实/span provenance 与受限 GLiNER2 router；r1-r3 labels/thresholds/旧分数及 r3 context-passed 集合不用于 selection。
- [x] 冻结 Restoration hard gates：grounded fact、原实体近似唯一可恢复、非实体 source-specific anchor、明确一致/不一致、query 自包含；自然性不计分，parser friendliness 为全局 schema 门禁。
- [x] 冻结无加权的确定性词典序、每 source 3 pair/6 query、fact diversity、同原实体最多2 pair与固定 tie-break。
- [x] 冻结开发/audit/正式隔离：每数据集 v22 前1,000 source永久作 development，随后250 source永久作 fresh-audit reserve，formal均排除；development gate要求 eligible>=500、Wilson lower>=0.45、按扣除1,250 source后的 formal capacity下界>=2,250。
- [x] 冻结 fresh audit 设计：reserve至少100 eligible后取前100 source×3 pair/dataset=900 pair；两名独立真人盲审、第三方裁决、raw agreement>=90%、kappa>=0.80；Assistant-only不足以形成 human validation。
- [x] 冻结阶段链与下游边界：runtime/test -> commit/bundle freeze -> development pilot -> fresh audit -> formal scan -> split -> shadow -> release -> Luna -> Retriever/victim -> source-level evaluation。
- [x] 无上下文 reader test 判定 r1 `Request Changes`；保留本节为历史草案，并由 design r2 supersede。

### 2026-08-12：v23 Restoration-First design r2 reader-test revision（已被 r3 supersede）

- [x] 冻结 `pcv-restoration-first-v23-design-r2`，维持 `design_preregistered_runtime_not_implemented` 与独立 `artifacts/v23/`。
- [x] 冻结 selector primitives：NFKC/casefold/whitespace、codepoint 半开 span、canonical JSON/hash、proposition/token/regex、完整 provenance 与 relation/fact/counterfactual/pair identity。
- [x] 冻结 fresh re-extraction：从绑定 v22 source DB 重抽全部 pattern/GLiNER2 P0 候选，不复用 pre-r3/r3 candidate artifact；GLiNER2 只作 emission/routing/filler inventory，禁止评分与排序。
- [x] 冻结 counterfactual pool/filter/hash order、无 fallback、全部 hard gates、17项 rank tuple、stable greedy top-3；不足3 pair则 source ineligible。structured types 不补 P0 pair、不改变 capacity/audit/formal gate。
- [x] 用一侧95%超几何总容量下界替换 Wilson/500 门禁；首轮最小 eligible `x` 为 EDGAR=623、Enron=89、PubMed=66，且每次跨 revision ledger 增加后必须重算。
- [x] 冻结跨 revision append-only consumed-source hash-chain ledger、250 audit reserve 预登记、formal-scan prior-consumption snapshot、全部 viewed/scanned source 对未来 revision 永久排除与 ledger 漂移 fail closed。
- [x] 冻结900-pair双人独立真人盲审、第三方裁决、可见/隐藏字段、缺失/重复处理、三分类 kappa 和所有分母。
- [x] 冻结 formal selected-set-before-split：按独立 SHA-256 key 排序为1,000 member/1,000 non-member/250 reserve，并绑定 selected-set/config/runtime/commit/ledger/key-list hash。
- [x] 将 immutable design capability 与独立 run-scoped authorization manifest 分离；配置中的执行权限不得原地翻转，未列权限默认拒绝。
- [x] 最小同步 `AGENTS.md` 当前协议世代；v22 三套 source pool/pilot passed、r3 `failed_final_calibration_revision` 与全部下游 blocked 口径不变。
- [x] 第二轮无上下文 reader test 给出 `Request Changes`；未生成 r2 design manifest，保留本节并升级 design r3。

### 2026-08-12：v23 Restoration-First design r3

- [x] 升级设计身份为 `pcv-restoration-first-v23-design-r3`，保持 runtime 未实现、所有执行权限 false。
- [x] 将全部 identity payload 冻结为具名 canonical JSON object schema并加入golden vectors；冻结候选遍历、GLiNER overlap/filter、rule/model merge、含subtype dedup与surface survivor。
- [x] 将 structured diagnostic 与 P0 extractor完全隔离，禁止 structured span/literal影响anchor、cue、DF/IDF、rank、eligibility或任何gate。
- [x] 冻结 revision-specific 250-source audit reserve：排除 prior ledger取下一批，capacity前write-ahead登记；不足250 fail closed，失败revision不能复用旧reserve。
- [x] 冻结 ledger append-before-read、lock/flush/fsync、crash recovery、tip anchor/checkpoint及有限信任模型；formal scan维持start snapshot、当前选中source只对未来revision排除。
- [x] selector序列化输入改为递归exact allowlist，unknown/nested injection/type drift拒绝；forbidden blacklist只作附加检查。
- [x] 冻结P0六cell outcome、missing/unparseable计分、3-pair source mean、tie-aware AUC、macro、source-stratified bootstrap CI与低FPR经验规则。
- [x] 分拆implementation/run authorization并新增完整stage-status matrix，消除runtime bundle尚不存在时的授权循环。
- [x] 第三轮无上下文 reader test 对 design r3 给出 `REQUEST_CHANGES`；保留 r3 失败证据，未生成 design manifest，并升级 design r4。

### 2026-08-12：v23 Restoration-First design r4

- [x] 升级设计身份为 `pcv-restoration-first-v23-design-r4`，保持 runtime 未实现、所有执行权限 false。
- [x] 冻结攻击者知识/未知/黑盒接口/可见输出与每 source/cell 6-query 非自适应预算，明确 P0 条件估计量。
- [x] 新增 ledger 唯一例外 `aggregate_df_precomputation`：只输出不含 source 映射/逐 source 行的 dataset-level token DF，并绑定输入/tokenizer/runtime/output hash；不声称低频 token 不可反演。
- [x] 冻结 ledger genesis/source row/batch/anchor/checkpoint、内容可见性原子批次、崩溃前缀恢复，以及 authorization 的 revision/attempt/expected prior tip。
- [x] 合并 revision-specific reserve/formal scan 唯一定义，补 reserve/formal selected-set/split schema与 audit HMAC identity/order/role separation。
- [x] 冻结 Luna claim-to-query、strict response parser、dense/BM25/hybrid index/Retriever、Gemma victim、matched LLM-only 的精确 prompt/schema/参数/错误与 manifest contract。
- [x] bootstrap 冻结 PCG64、六 cell/source/draw 顺序、type-7 quantile 与 golden vectors；明确 per-dataset/macro/low-FPR 报告层级。
- [x] 第四轮无上下文 reader test 给出 `REQUEST_CHANGES`；保留r4失败证据，未生成design manifest，并升级design r5。
- [ ] 实现 v23 selector、prepare/runner、编号脚本与定向测试；在实现完成前 `runtime_implemented=false`、`runtime_frozen=false`。
- [ ] runtime 实现和验证完成后，由用户另行决定是否提交，并生成绑定 commit/config/runtime hashes 的 executable protocol manifest。
- [ ] 另获用户明确授权后，才运行首个本地 development wave；GPU 长任务、API、victim、Retriever 均需分别授权。
- [ ] development gate 与 fresh audit passed 前，formal scan、split、shadow、release、Luna query、Gemma victim 和正式 Retriever 全部 blocked。

### 2026-08-12：v23 Restoration-First design r5

- [x] 升级为 `pcv-restoration-first-v23-design-r5`，保持方法hard gates、容量门禁、audit与P0 outcome不变。
- [x] 显式冻结唯一23文件列表与canonical list hash；23个磁盘SHA-256全部匹配。
- [x] 授权收敛为单stage/attempt/execution unit，并冻结per-stage预算单位、append-only先扣后执行journal与genesis/no-op checkpoint anchor。
- [x] 冻结EDGAR->Enron->PubMed顺序、三套reserve共同prior snapshot/group completion，以及formal逐source reservation和第2,250个eligible后立即停止。
- [x] 补齐DF、selector pair、audit、selected set、split、release、query、retrieval的canonical rows/schema/path/order/file hash链。
- [x] 冻结Luna bytes/validator、BGE/BM25/hybrid、Gemma BF16/chat encoding和完整cell matrix；每source固定18 RAG+6共享LLM-only=24次victim generation。
- [x] 冻结跨backend共享的单一PCG64 bootstrap index tensor；runtime bundle必须绑定NumPy版本与state/tensor golden hash。
- [ ] 第五轮无上下文reader test只审科学协议、泄漏边界、identity/artifact链、预算与确定性是否闭合；纯实现偏好不构成升版阻断。
- [ ] reader test通过后生成design manifest；未通过则仅在存在实质性科学或identity矛盾时允许r6。
- [ ] design manifest完成后，等待用户另行授权实现runtime与定向测试；实现授权仍不包含pilot、GPU、API、victim、Retriever、提交或推送。

当前唯一下一步：执行design r5无上下文reader test；未通过不得生成design manifest或进入runtime。

### 2026-08-13：v23 Restoration-First design r6 bounded closure

- [x] 第五轮无上下文reader test判定design r5为`REQUEST_CHANGES`；保留r5失败证据，未生成design manifest。
- [x] 用户明确授权执行r6；身份升级为`pcv-restoration-first-v23-design-r6`，修订范围限定为r5的5个实质阻断项。
- [x] 将P0冻结为逐backend的`source_pvs(dataset, backend, source)`、逐backend逐数据集与macro AUC/CI、逐backend低FPR；禁止跨backend主指标聚合。
- [x] aggregate-DF冻结为每runtime bundle/dataset一次有预算全池读取，后续stage只验identity与文件hash；重算必须新授权attempt。
- [x] 新增首个bundle/genesis专用bootstrap authorization/attempt/checkpoint；fresh audit按实际扫描/评估的reserve source读取前扣费。
- [x] 补齐formal selected-pair -> audit -> split -> shadow -> release -> query -> retrieval -> response -> evaluation逐级文件hash链。
- [x] BM25 query token去重后按Python字典序累加，禁止直接迭代`set`。
- [x] 对design r6执行一次限定范围reader test，只核验上述5项；判定`PASS`，fact extraction与Restoration hard gates未变。
- [x] 已生成并核验design manifest，绑定最终config/prereg hash、reader-test PASS与23个冻结上游文件；manifest SHA-256=`6a7163830f36b65247b7d6222f5adecfb18c85695a885cc0384128c81ffbd6fe`。
- [ ] design manifest完成后，等待用户另行授权实现runtime与定向测试；实现授权不包含pilot、GPU、API、victim、Retriever、提交或推送。

当前唯一下一步：等待用户单独授权实现runtime与定向测试；实现授权不包含pilot、GPU、API、victim、Retriever、提交或推送。

### 2026-08-13：v23 前旧文件与可再生 payload 清理

- [x] 保留全部既有脏工作树，不执行reset、checkout、stash、无关清理、覆盖、提交或推送。
- [x] 删除20个明确superseded且不再使用的v21/r4配置、脚本、实现和测试，保留仍在现有验证/审计链中的5个关键文件。
- [x] 删除541个v21可再生candidate/query/cache/replay payload，释放`3,783,866,168` bytes；删除清单SHA-256=`4802fe9a4702d5a96102bd2ecfc41ecfc59384b311862443254d21d52a578c6d`。
- [x] 删除53个v22可再生展开payload，释放`247,429,177` bytes；删除清单SHA-256=`45ef2078d5dc9325cdb9d85eb5f62dc9ed900ae3f9800a4666571b4b8303b1db`。
- [x] 保留全部status/manifest/report/evaluation/audit/decision/failure/label证据，以及v22 pilot selected pairs、source results和r3正式失败evaluation；历史passed/failed口径不变。
- [x] 明确保留`gliner2-large-v1`、`gliner-biomed-large-v1.0`、spaCy `en_core_web_trf-3.8.0-data`与`gliner2-base-v1`；`models/`和`datasets/`零删除。
- [x] 清理后复核v23显式绑定的23个文件全部存在且SHA-256匹配，design manifest SHA-256仍为`6a7163830f36b65247b7d6222f5adecfb18c85695a885cc0384128c81ffbd6fe`。
- [x] 停止继续清理：v23绑定的大型完整source/source pool约`4.726 GiB`不能删除；剩余v22非source-pool内容主要是小型研究证据，继续删除得不偿失。
- [ ] 被删payload如需恢复，只能按保留的旧输入、代码身份、plan/manifest/hash与原流程重新计算，不得手工伪造或改写immutable artifact。

当前唯一下一步仍是：等待用户单独授权实现v23 runtime与定向测试；清理授权不包含pilot、GPU、API、victim、Retriever、提交或推送。

### 2026-08-13：v23 runtime 实现与离线测试

- [x] 记录并验证implementation authorization `5c191b1b...751d`；授权路径限定为v23实现/测试与两份项目总表，`external_calls_allowed=false`。
- [x] 实现v23 selector/fact adapter、Restoration hard gates、确定性rank/top-3、aggregate DF与递归exact allowlist；禁止membership、victim/LLM-only response、Retriever输出或AUC进入selection。
- [x] 实现runtime bundle identity、bootstrap/run authorization、attempt registry、append-only预算journal、consumption ledger/batch anchor/checkpoint、只读source-pool reader、容量/audit/split/release边界与artifact hash校验原语。
- [x] 实现strict query/response parsing、保守`-0.5`计分、逐backend 3-pair source PVS、tie-aware AUC、低FPR、PCG64/type-7 bootstrap与确定性BM25。
- [x] 收紧治理回归：registry row自身hash必验；reservation绑定stage/role/attempt/prior tip并在ledger写入前预检整批预算；reserved read绑定durable batch anchor，重复/漂移/未授权/预算不足均fail closed。
- [x] v23定向测试24/24通过；全量`unittest discover -s tests`为443/443通过；内存AST、`git diff --check`、design 23-file binding与implementation authorization验证通过。
- [x] 状态保持`runtime_implemented_unfrozen`、`runtime_bundle_frozen=false`、`pilot_started=false`、`external_calls_performed=0`；未创建bundle/genesis/DF/pilot或下游artifact，未运行GPU/API/victim/Retriever，未提交或推送。
- [ ] 用户另行授权后，才允许执行首个`runtime_bundle_and_commit_freeze` bootstrap并建立ledger genesis；本条不包含commit/push授权。
- [ ] bundle/genesis冻结后，aggregate-DF仍需按dataset签发独立run authorization；development pilot及所有下游继续分别blocked。

当前唯一下一步：等待用户单独授权runtime bundle/genesis bootstrap。未获得该授权前，不读取正式source pool，不创建aggregate-DF，不启动pilot、audit、formal、split或任何模型/检索调用。

### 2026-08-13：v23 bootstrap 事务实现与离线回归

- [x] 补齐 `runtime_bundle_and_commit_freeze` 的 bootstrap authorization、单次 attempt registry、runtime bundle、protocol revision 0、ledger genesis、genesis anchor、bootstrap checkpoint 与完整 post-validation；半产物/重复授权/身份漂移均 fail closed。
- [x] 增加 runtime closure 与提交后 HEAD 对照；GLiNER2 base 仅按 lock 和 tokenizer 小文件 hash 绑定，未加载模型权重；绑定 NumPy 版本与 PCG64(42) state golden hash，未生成完整 bootstrap tensor。
- [x] 增加 CLI `prepare-bootstrap-authorization`、`bootstrap`、`validate-bootstrap`；实现授权仍为 `external_calls_allowed=false`，不包含 source pool、pilot、GPU、API、victim、Retriever 或 commit/push。
- [x] 增加 7 个合成仓库 bootstrap 回归用例；v23 定向测试 `31/31`、全量 `450/450` 通过，`git diff --check` 通过。
- [x] 状态仍为 `runtime_implemented_unfrozen`、`runtime_bundle_frozen=false`、`pilot_started=false`、`external_calls_performed=0`；真实 bootstrap 未执行，正式 source pool 未读取。
- [ ] 提交前向用户展示精确 v23 提交清单与 `feat(v23): implement restoration-first runtime`，等待明确确认；确认后只提交 v23 协议/runtime/测试和两份项目总表，不推送、不带入其他脏改动。
- [ ] 用户确认清单并完成提交后，使用本轮“开始吧”的现有授权只运行一次 `runtime_bundle_and_commit_freeze` bootstrap并建立ledger genesis；之后每个aggregate-DF/dataset和所有下游阶段继续要求独立授权。

当前唯一下一步：向用户展示待提交文件清单和提交信息，等待确认；在确认前不执行 `git add`、`git commit`，也不执行 bootstrap。

### 2026-08-13：v23 runtime bootstrap 冻结

- [x] 用户确认后仅提交10个v23协议/runtime/测试及项目总表文件；commit=`c05a088f887471bc825aab6acdbeaf2e34fbe917`，提交信息=`feat(v23): implement restoration-first runtime`，未推送且未带入其他脏改动。
- [x] 消费一次性bootstrap authorization `d06e6cfd...64d3`，完成attempt `7823debf...cdcd`；runtime bundle SHA-256=`272bd6faa36f2923dceeefde000b46caba9efe852d44bc62065401bc8053a7c7`，protocol revision ID=`e5a870133c1548be34dcb2727f8324e0e413dfc48f7c66fe9aa8c6d6b9f2d655`。
- [x] 建立并验证ledger genesis row `41a77b70...f57e`、genesis anchor `c767aaa1...a791`和bootstrap checkpoint `artifacts/v23/checkpoints/bootstrap/7823debf3821ffbe2bb8a1a88e8e6cfd17bd32e50add571ed755a3f050a6cdcd.json`。
- [x] `validate-bootstrap`与`status`通过；当前状态=`runtime_frozen_downstream_blocked`，`source_pool_contents_read=false`、`pilot_started=false`、`external_calls_performed=0`。
- [ ] 按dataset分别获得独立run authorization后，依冻结顺序执行EDGAR、Enron、PubMed各一次`aggregate_df_precomputation`；不得复用一次授权跨dataset或重算已有DF。
- [ ] 三套aggregate-DF均完成并逐一验证前，不启动development pilot；pilot、fresh audit、formal、split、shadow、release、Luna、Gemma、Retriever与evaluation继续blocked。

当前唯一下一步：等待用户单独授权EDGAR的`aggregate_df_precomputation`。该授权不包含Enron/PubMed、pilot、GPU、API、victim、Retriever或任何下游阶段。

### 2026-08-13：EDGAR aggregate-DF 授权与runner阻断

- [x] 用户已单独授权EDGAR `aggregate_df_precomputation`，并指定长时间命令由用户本人执行；授权范围不含其他dataset或下游阶段。
- [x] 启动前确认runtime bundle `272bd6fa...a7c7`与protocol revision `e5a87013...d655`有效，当前仍为`runtime_frozen_downstream_blocked`。
- [x] 只读审计确认已有DF/reader/budget/authorization/attempt/writer/checkpoint原语，但真实stage的授权生成、输入identity、exactly-once、失败/完成checkpoint、resume与CLI执行/验证入口未实现。
- [x] 因执行事务未闭合而fail closed；未生成EDGAR run authorization或attempt，未读取source pool，未创建DF artifact，预算扣费、外部调用、GPU/API/victim/Retriever均为0。
- [ ] 获得单独实现授权后，仅补齐aggregate-DF runner及定向测试；不得使用未绑定的临时`python -c`编排产生canonical artifact。
- [ ] 实现完成后由用户确认提交，并冻结绑定新commit的新runtime bundle/protocol revision；随后使用现有EDGAR执行授权生成单次run authorization，把长命令交由用户执行。

当前唯一下一步：等待用户授权补齐`aggregate_df_precomputation`真实runner与定向测试；该实现授权不包含执行完整池读取、其他dataset、pilot、GPU、API、victim或Retriever。

### 2026-08-13：v23 aggregate-DF runner 与 successor freeze 实现

- [x] 实现 successor runtime freeze authorization/run/validation；保留 revision 0、首个 runtime bundle、ledger genesis 与 genesis anchor，不创建 r7，不修改 fact extraction 或 Restoration hard gates。
- [x] 实现 aggregate-DF prepare/run/validate 与 CLI；冻结 EDGAR -> Enron -> PubMed 顺序、dataset 独立 authorization/attempt、逐 source 先扣预算后读取、boolean token DF 和无 source mapping 输出。
- [x] 准备/执行前验证 active runtime 与 source-pool manifest/database/source-order hash，并要求 ledger 为 genesis-only；失败 checkpoint、已有输出、错误 dataset/order、身份或 artifact 漂移均 fail closed。
- [x] v23 governance 定向测试 `24/24`、全量 `456/456`、内存 AST、`git diff --check` 与敏感值扫描通过；测试仅使用合成临时仓库/SQLite fixture。
- [x] 真实 EDGAR source pool 未读取；未生成 EDGAR run authorization、attempt、DF 或 checkpoint，external calls/GPU/API/victim/Retriever/费用均为 0。
- [ ] 用户确认精确提交范围后，才提交本轮 runner/runtime/test；随后冻结绑定新 commit 的 successor runtime bundle/protocol revision。revision 0/genesis 历史必须原样保留。
- [ ] successor freeze 完成后，使用既有 EDGAR 执行授权生成一次性 run authorization，并将长时间 `aggregate-df --dataset edgar` 命令交由用户本人执行；Enron/PubMed、pilot 与所有下游继续 blocked。

当前唯一下一步：等待用户确认本轮精确提交范围。确认前不执行 `git add`、`git commit`、successor freeze、真实 source-pool 读取或任何下游阶段。

### 2026-08-13：v23 successor runtime revision 2 冻结

- [x] 用户确认后提交 3 个 runner/runtime/test 文件，commit=`7d82ea4f530ba4d0f80e0b69bf93a7f04e1c5587`；未推送、未带入其他脏改动。
- [x] 修复 `v23_status` 报告 bootstrap revision 0 的状态 bug，新增 successor identity 回归测试；commit=`f00205f1933863357458f5741ab8bf9115e56126`，governance `25/25`、全量 `457/457` 通过。
- [x] 冻结 successor revision 2：bundle=`c1e61ac5b9902b2b6a8e6922151e67ca03a9c13463ad195cb107f20d237285ea`，protocol revision=`286e1f0a1c0dff1db917ea00a387192b8cbded7b3577e57d3cc86b4847524621`；revision 0/1、genesis、ledger tip 保留且未发生 source ledger mutation。
- [x] `validate-successor-runtime` 与 `status` 通过；状态仍为 `runtime_frozen_downstream_blocked`，source pool、aggregate-DF、pilot、GPU、API、victim、Retriever 与费用均为 0。
- [ ] 在 revision 2 下生成 EDGAR 一次性 `aggregate_df_precomputation` run authorization，并把长命令交由用户本人执行；执行前仍须验证授权、runtime/pool bindings 和冻结顺序。
- [ ] EDGAR aggregate-DF 完成并验证前，Enron/PubMed、development pilot、fresh audit、formal、split、shadow、release、Luna、Gemma、Retriever 与 evaluation 继续 blocked。

当前唯一下一步：生成 revision 2 绑定的 EDGAR run authorization；不读取完整 source pool，不启动其他 dataset 或下游阶段。

### 2026-08-13：EDGAR aggregate-DF run authorization 已生成

- [x] 生成 revision 2 绑定的 EDGAR 独立 authorization=`0e63f9b0...045e` 与 attempt=`7f4be98e...84ad`；`datasets=[edgar]`、`execution_unit=one_dataset`、预算=`5210` sources、prior ledger tip=genesis。
- [x] 授权生成阶段未读取 source 内容，未执行 aggregate-DF，未产生 DF rows/manifest/checkpoint；external calls/GPU/API/victim/Retriever/费用仍为 0。
- [ ] 用户本人执行一次性长命令 `aggregate-df --dataset edgar --authorization ...0e63f9b0...045e.json`；不得跨 dataset 复用授权，不得同 attempt 重跑。
- [ ] EDGAR 完成后由用户要求再运行正式 `validate-aggregate-df --dataset edgar`；验证通过前 Enron/PubMed、pilot 与所有下游继续 blocked。

当前唯一下一步：等待用户本人执行 EDGAR aggregate-DF 长命令并回报退出结果；助手不代跑完整 source-pool 读取。

### 2026-08-13：EDGAR aggregate-DF 完成并通过验证

- [x] 用户本人按 revision 2 的一次性 EDGAR authorization 执行 `aggregate-df --dataset edgar`，attempt=`7f4be98e...84ad`，authorization=`0e63f9b0...045e`；返回 `status=passed`。
- [x] 正式 `validate-aggregate-df --dataset edgar` 返回 `status=passed`；`source_count=5210`、`token_count=116953`、预算扣费=`5210`、`external_calls_performed=0`、`ledger_mutation=false`。
- [x] 记录 artifact identity：DF manifest SHA-256=`aeb7af6c0b776566cfd782168e7e125ad92b0faaa76bdf75088aa471ec52fdf6`，token DF rows SHA-256=`add48dd0dc818b94e98735f48b45cc27059d4e8a5f918c6d1524fe0e2b58e27f`；输出不含 source 映射或逐 source 行。
- [x] EDGAR attempt 已完成，不得同 attempt 重跑；revision 0/1、genesis、历史 artifact 与脏工作树均保留。
- [ ] 获得用户单独授权后，按冻结顺序为 Enron 生成独立 authorization 并由用户执行一次 aggregate-DF；不得跨 dataset 复用 EDGAR authorization。
- [ ] Enron/PubMed aggregate-DF 全部完成并逐一验证前，development pilot、fresh audit、formal、split、shadow、release、Luna、Gemma、Retriever 与 evaluation 继续 blocked。

当前唯一下一步：等待用户单独授权 Enron `aggregate_df_precomputation`；授权前不生成 Enron authorization、不读取 source pool、不运行其他阶段。

### 2026-08-13：Enron aggregate-DF run authorization 已生成

- [x] 用户单独确认授权 Enron `aggregate_df_precomputation`；授权范围不含 PubMed、GPU、API、victim、Retriever 或任何下游阶段。
- [x] 生成 Enron 一次性 authorization=`c01e5d8d...7004` 与 attempt=`ddff63f6...168f`；`datasets=[enron]`、`execution_unit=one_dataset`、预算=`35000` sources、prior ledger tip=genesis。
- [x] 授权生成阶段未读取 Enron source 内容，`source_pool_contents_read=false`、external calls/GPU/API/victim/Retriever/费用均为 `0`。
- [ ] 用户本人执行一次性 Enron `aggregate-df --dataset enron`，不得跨 dataset 复用 authorization，不得同 attempt 重跑。
- [ ] Enron 完成并通过 `validate-aggregate-df --dataset enron` 前，不生成 PubMed authorization，不启动 development pilot、fresh audit、formal、split、shadow、release、Luna、Gemma、Retriever 或 evaluation。

当前唯一下一步：等待用户本人执行 Enron aggregate-DF 长命令并回报退出结果。

### 2026-08-14：Enron aggregate-DF 完成并通过验证

- [x] 用户本人完成 Enron `aggregate-df --dataset enron`，随后正式 `validate-aggregate-df --dataset enron` 返回 `status=passed`。
- [x] attempt=`ddff63f6...168f`、authorization=`c01e5d8d...7004`；`source_count=35000`、`token_count=181394`、预算扣费=`35000`、`external_calls_performed=0`、`ledger_mutation=false`。
- [x] 记录 artifact identity：DF manifest SHA-256=`703b1756137aa0bdb9ca06e0e1416a12f884e4f6a5591fe6a120bb136d5526b5`，token DF rows SHA-256=`18c6df70e5a6236eb96292061d1d1ee33caef6f721acbc628200b08aece43fdc`。
- [x] Enron attempt 已完成，不得同 attempt 重跑；EDGAR 与 Enron aggregate-DF 至此均已 passed。
- [ ] 获得用户单独授权后，按冻结顺序为 PubMed 生成独立 authorization 并由用户执行一次 aggregate-DF；不得复用 EDGAR 或 Enron authorization。
- [ ] PubMed 完成并通过验证前，development pilot、fresh audit、formal、split、shadow、release、Luna、Gemma、Retriever 与 evaluation 继续 blocked。

当前唯一下一步：等待用户单独授权 PubMed `aggregate_df_precomputation`；授权前不生成 PubMed authorization、不读取 source pool、不运行其他阶段。

### 2026-08-14：PubMed aggregate-DF run authorization 已生成

- [x] 用户单独确认授权 PubMed `aggregate_df_precomputation`，并指定长时间命令由用户本人执行；授权不包含 development pilot、GPU、API、victim、Retriever 或任何下游阶段。
- [x] 生成 PubMed 一次性 authorization=`52f4a84e...4fc7f` 与 attempt=`43ff2d69...bb53`；`datasets=[pubmed]`、`execution_unit=one_dataset`、预算=`47950` sources、prior ledger tip=genesis。
- [x] 授权生成阶段未读取 PubMed source 内容，`source_pool_contents_read=false`、`external_calls_performed=0`。
- [ ] 用户本人执行一次性 PubMed `aggregate-df --dataset pubmed`，不得复用 EDGAR/Enron authorization，不得同 attempt 重跑；依据已有实测和 PubMed 数据规模，暂估 5--8 小时，保守预留 8--12 小时。
- [ ] 完成后运行正式 `validate-aggregate-df --dataset pubmed`；验证通过前不启动 development pilot、fresh audit、formal、split、shadow、release、Luna、Gemma、Retriever 或 evaluation。

当前唯一下一步：等待用户本人执行 PubMed aggregate-DF 长命令并回报退出结果；助手不代跑完整 source-pool 读取。

### 2026-08-14：PubMed aggregate-DF 完成与冻结 runtime 验证入口

- [x] 用户本人完成PubMed一次性`aggregate_df_precomputation`；artifact记录`source_count=47950`、`token_count=1284757`、预算扣费47950、checkpoint=`passed`、external calls=0、ledger mutation=false。
- [x] 定位末尾`active_runtime_commit_drift`：任务运行期间新增两个closure外commit，当前`HEAD`从冻结`f00205f1...6126`前进到`5099fbf8...6b4`；19个runtime closure文件内容与bundle hash均未变化。
- [x] 保留原PubMed rows/manifest/checkpoint/authorization/budget，不覆盖、不重跑完整池；核验DF manifest SHA-256=`8418d737...b043`、token DF rows SHA-256=`75955e53...7f8e`。
- [x] 建立detached frozen worktree`D:\MIA\mia_model_v23_runtime_r2`并固定到`f00205f1...6126`；新增非closure入口`scripts/run_v23_frozen_runtime.ps1`，以冻结Git identity调用原`42` runtime，不创建新bundle或design revision。
- [x] 通过冻结入口完成PubMed正式validator，返回`status=passed`；EDGAR、Enron、PubMed三套aggregate-DF至此全部passed且均不得同attempt重跑。
- [ ] 用户单独授权后，才允许准备并执行revision audit reserve snapshot/write-ahead与`development_pilot_and_capacity_gate`；该授权不自动包含fresh audit、formal、split、shadow、release、API、victim或Retriever。

当前唯一下一步：等待用户明确授权development pilot前置reserve write-ahead与pilot执行范围。授权前不读取新的source、不运行首次真实fact extraction，不启动fresh audit、formal scan、split、shadow、release、Luna、四个Generator、Retriever、victim或evaluation。

### 2026-08-14：development pilot runner 缺口阻断

- [x] 将用户“进行下一步吧”限定为下一阶段准备授权；未推导为GPU长任务、API、victim或Retriever调用授权。
- [x] 通过冻结入口核验active bundle/revision与三套aggregate-DF状态；只读确认reservation、reserved read、fact extraction、Restoration selection和capacity原语存在。
- [x] 确认正式事务缺口：`42` CLI和prepare runtime均没有reserve group write-ahead或development pilot的prepare/run/validate入口，也没有对应canonical snapshot/group completion/selection/capacity checkpoint闭环。
- [x] 保持fail closed：未用临时`python -c`或非closure脚本编排；未创建authorization/attempt、未写ledger或budget、未读取新source、未启动GPU。
- [ ] 路径A：保持design-r6不变，补runner并冻结successor bundle，然后在新bundle下重新授权/执行三套aggregate-DF。
- [ ] 路径B：先制定stage-scoped compatibility/carry-forward execution erratum并改变协议身份，证明aggregate计算closure不变后复用现有三套DF，再补runner。

当前唯一下一步：等待用户明确选择路径A或路径B。选择前不修改runtime closure，不创建reserve/pilot authorization，不启动source读取、GPU、API、victim或Retriever。

### 2026-08-14：v23 Stage-Scoped Identity execution erratum e1 实现

- [x] 用户选择路径B并授权实施独立stage-scoped identity；保持design-r6方法定义，不创建r7，不修改fact extraction、Restoration hard gates、rank或统计。
- [x] 新增execution erratum e1与stage DAG/change-impact matrix；erratum SHA-256=`4245105e0058a3f8e326f7f1e57175665a2199a1e9ca82bc82402c477b08c279`。
- [x] 实现整文件/指定symbol规范化AST hash、指定YAML子树hash、精确data/model/upstream artifact SHA-256和stage execution identity；缺失/漂移/未知依赖/DAG环一律fail closed。
- [x] 将aggregate-DF fingerprint限定到tokenization、normalization、DF/serialization、只读pool reader、三套pool identity与Python环境；验证fact/pilot-only变化不失效DF，DF算法/tokenization/pool hash变化令三套DF及下游stale。
- [x] 实现`stage-status`、carry-forward authorization/run/validation及aggregate-DF native/carried-forward双模式；Luna变化传播到retrieval，Retriever变化保留query/LLM-only，parser/scoring变化保留原始response。
- [x] carry-forward attestation绑定旧/新bundle与revision、fingerprint、两端execution identity、三套DF rows/manifest、authorization、budget、checkpoint和ledger tip/anchor；自哈希、错误identity/hash、不完整三数据集组及缺失证据均fail closed。
- [x] 记录并验证implementation authorization=`5036ed6f...245c`，scope限定为本轮8个实现/文档路径，`external_calls_allowed=false`。
- [x] v23定向测试`45/45`、全量单元测试`464/464`通过；内存AST、erratum/authorization hash、`git diff --check`和敏感值扫描通过。
- [x] 同步README与两份项目总表；三套既有DF和历史artifact原样保留，真实stage compatibility目录仍为空，source读取/新增预算扣费/ledger mutation/GPU/API/victim/Retriever调用均为0。
- [ ] 等待用户确认后只提交e1计划范围文件，不推送、不带入其他脏工作树。
- [ ] 提交后另行获得明确授权，再冻结successor runtime；不得把提交确认解释为freeze授权。
- [ ] successor freeze后另行获得明确授权，仅当旧/新aggregate fingerprint完全相等时生成三数据集group carry-forward证明；不得重跑或改写原DF。
- [ ] carry-forward验证通过后，再单独授权实现reserve/pilot runner与执行development pilot；fresh audit及下游继续blocked。

当前唯一下一步：等待用户确认提交本轮e1实现。确认前不提交、不冻结successor、不生成真实carry-forward artifact、不读取source、不写ledger，也不启动pilot/GPU/API/victim/Retriever。

### 2026-08-14：v23 e1 本地提交完成

- [x] 仅提交8个e1代码/配置/测试/文档增量，commit=`3010c19aa81c59ee4b1ec081752702d9ff32dcd4`，提交信息=`feat(v23): add stage-scoped runtime identity`。
- [x] README与两份项目总表使用局部暂存；既有脏工作树、历史artifact和非e1文件均保留，未推送，暂存区为空。
- [x] 提交阶段未读取source、未写ledger、未生成successor bundle或carry-forward证明，GPU/API/victim/Retriever调用与费用均为0。
- [ ] 用户另行授权后冻结successor runtime；提交确认不能解释为freeze授权。
- [ ] freeze完成后再次取得独立授权，并仅在旧/新aggregate fingerprint完全一致时生成和验证三数据集group carry-forward证明。
- [ ] carry-forward通过后再推进reserve/pilot runner与development pilot；fresh audit及全部下游继续blocked。

当前唯一下一步：等待用户单独授权successor runtime freeze。未获授权前不创建新bundle/revision、不生成真实carry-forward artifact、不读取source、不写ledger，也不启动pilot/GPU/API/victim/Retriever。

### 2026-08-15：successor runtime freeze revision 3

- [x] 修复 runtime closure 的规范排序缺陷并增加回归断言；仅提交 `32f9ba88c833f9ca7dbf7dd37967306d70061b29`，其他脏工作树与历史 artifact 保留。
- [x] 生成 successor freeze authorization=`bb53ae708823d477fab8b4a7a0f0384a7903d9e54eb7f6d012645427fe79dc87`。
- [x] 冻结 successor bundle=`1c2c933d890f52e11ffa2e9d37ca2aede3a5037ff009656f9d8cf54763ea8cb8` 与 revision=`7add7622b9bf76e1547a6ce98fa5178e0a6e9a26eb147fb3553a7b9b0ab54bff`（ordinal 3）。
- [x] `freeze-successor-runtime` 与 `validate-successor-runtime` 均通过；ledger tip 未变，source读取、ledger mutation、外部调用均为 0。
- [ ] 用户另行授权后，才可为 aggregate-DF stage 生成并验证三数据集 carry-forward attestation；不能重跑或改写既有 DF。
- [ ] carry-forward 通过后，才可继续 reserve snapshot/write-ahead、development pilot 与首次真实 fact extraction/Restoration 质量门禁；fresh audit 及所有下游仍 blocked。

当前唯一下一步：等待用户明确授权 aggregate-DF stage carry-forward；授权前不写 compatibility artifact、不读取 source、不启动 pilot/GPU/API/victim/Retriever。

### 2026-08-15：aggregate-DF 三数据集 carry-forward

- [x] 生成 group authorization=`e7e64dde111300ea13928a2345018d8d17ceefa1657cfad1e6a31ca664660ff7`，scope 仅为 `aggregate_df_precomputation` carry-forward。
- [x] 验证旧/新 aggregate-DF fingerprint 完全相等：`9fc3c9d28016b5d3483ca414145c5a9a025d4ec4196ab9679525b8ae268c8011`。
- [x] 生成 attestation=`c3f1b179571383751d6231c1175094d8b6fa6801abf4940a57dbcaf3b0a95db3`，文件 SHA-256=`24d7fa0df7baf4c180e76ae3d6bdf8f9f49c672d0d9de4c38d7ea0db5c127aba`，完整绑定 EDGAR/Enron/PubMed 三套证据。
- [x] `validate-carry-forward` 通过；三套 `validate-aggregate-df` 均在 revision 3 下返回 `passed/carried_forward`。
- [x] 权威 `stage-status` 返回 aggregate-DF=`carried_forward`；旧总 `status.blocked_stages` 是不参与 gate 的静态摘要，记录为下一次 runner runtime 修改时一并修正的展示问题。
- [x] 原 DF、budget、checkpoint、ledger 与 producer identity 均未改写；source 重读、预算新增、ledger mutation、GPU/API/victim/Retriever 调用均为 0。
- [ ] 单独授权后实现 reserve snapshot/write-ahead 与 development-pilot runner，并完成离线定向测试；实现授权不等于真实执行授权。
- [ ] runner 提交并按 stage-scoped identity 冻结后，再单独授权真实 reserve/pilot；fresh audit 与下游保持 blocked。

当前唯一下一步：等待用户明确授权实现 reserve/pilot runner 与定向测试；未获授权前不修改 runtime closure、不读取 source、不写 ledger，也不启动 GPU/API/victim/Retriever。

### 2026-08-15：reserve/write-ahead 与 development-pilot runner 实现

- [x] 记录并验证 implementation authorization=`37dd6ce0...f0e3d5`；scope 仅含本轮 7 个 runtime/CLI/test/doc 路径，`external_calls_allowed=false`。
- [x] 实现三数据集 common-prior reserve snapshot、首次 development reuse/registration、固定 dataset/role batch 顺序、write-ahead budget/ledger/anchor、group completion、checkpoint 与崩溃恢复。
- [x] 实现零 source 读取的 reservation validator；snapshot/plan/batch/ledger/anchor/budget/checkpoint、development 前1000身份、reserve prior 排除与跨数据集 hash 排除任一漂移均 fail closed。
- [x] 实现逐 dataset development-pilot authorization/run/validate；逐 source 先扣 logical budget 再读、ledger hash 复核、durable source result、完整结果 resume、确定性双算、canonical selected-pairs、capacity decision 与 failed checkpoint 均闭环。
- [x] 实现三数据集 development gate manifest；只有三个 dataset pilot 均 passed 且 source/raw-normalized hash overlap 均为0时才通过。
- [x] 新增 7 个 CLI 子命令并扩展 `stage-status`；未实现 fresh audit、formal scan、split、shadow、release 或任何 query/victim/Retriever 入口。
- [x] 保持 design-r6、execution erratum e1、fact extraction、Restoration hard gates、17项 rank、capacity 公式与统计定义不变；aggregate-DF fingerprint 仍为 `9fc3c9d2...c8011`，既有 carry-forward 保持有效。
- [x] 新增离线合成回归：reservation partial-prefix/anchor 恢复、篡改拒绝、validator 不读 source；pilot 已扣预算无结果恢复、确定性、组 overlap、forbidden field、capacity pass/fail。
- [x] v23 定向回归 `49/49` passed；内存 AST 与 CLI help passed。`ruff` 不在锁定环境中，未联网安装。
- [x] 全量 `unittest discover -s tests` `468/468` passed；298-file 内存 AST、CLI help、`git diff --check`、implementation authorization scope/self-hash 与敏感字段扫描全部通过。既有 `src/utils/hash.py` BOM 通过 `utf-8-sig` 正确读取，未修改原文件。
- [ ] 等待用户确认后仅提交本轮授权范围文件，不推送、不纳入其他脏工作树。
- [ ] 提交后另行获得 successor runtime freeze 授权；freeze 之后再次单独授权真实 reservation/write-ahead 与 development pilot。
- [ ] fresh audit、formal、split、shadow、release、Luna、四个 Generator、Retriever、victim 与 evaluation 继续 blocked。

当前唯一下一步：等待用户确认提交本轮授权范围文件；不得把提交确认解释为 successor freeze、真实 source 读取、ledger mutation、GPU 或 development pilot 执行授权。

### 2026-08-16 至 2026-08-17：revision 4 freeze、reservation 与 EDGAR pilot 准备

- [x] 仅提交 reserve/pilot runner 授权范围 7 文件，commit=`4856e31da50e7316e0b5b298401739097df0d3e3`；未推送、未带入既有无关脏工作树。
- [x] 使用 authorization=`f07c7f35...5fc6` 冻结并验证 revision 4：bundle=`bc5a81de...9833`，protocol revision=`71e862b7...8043`，external calls=0。
- [x] 验证 aggregate-DF fingerprint 仍为 `9fc3c9d2...c8011`，使用 authorization=`b8cd218a...8199` 生成并验证三数据集 attestation=`7f37e1d3...b6c8`；三套 DF 均为 `carried_forward`，未重读 source、未新增预算、未写 ledger。
- [x] 生成 revision reservation authorization=`49ce6a80...6965`、attempt=`73c19117...1d5a`，预算恰为 3,750 sources。
- [x] 助手启动的 reservation 在 1,652 条 durable 前缀处按用户要求停止；核验 ledger/budget 一致并清除已终止 PID 的 stale lock 后，用户用同一 authorization/attempt 恢复完成，未新建 attempt、未将操作中断记作方法失败。
- [x] reservation 与 validator 均 `passed`：三数据集 development 各 1,000、reserve 各 250，checkpoint=`0c16fa63...75e2`、group completion=`54983e73...4b17`、final ledger tip=`3c912fd1...a8e1`，external calls=0。
- [x] CUDA 门禁通过：PyTorch `2.11.0+cu130`、RTX 4060 Laptop GPU、无 CPU fallback；冻结 `gliner2-base-v1@f5b2ec...` 本地 snapshot 保持有效。
- [x] 生成 EDGAR development pilot authorization=`a40eab77...a67d`、attempt=`385a242b...23ea`、budget=`1000`；准备阶段未加载模型、未读取正文、未扣 pilot 预算。
- [ ] 用户本人运行 EDGAR pilot 长命令并执行 `validate-development-pilot --dataset edgar`；每个 source 固定双算，按预注册 determinism、hard-gate 与 capacity 门槛一次性判定。
- [ ] EDGAR `passed` 后才依次生成并运行 Enron、PubMed pilot authorization；不得并发、跨 dataset 复用授权或在看到结果后改门槛。
- [ ] 三数据集全部 `passed` 后运行 `validate-development-pilot-group`，确认跨数据集 source/raw-normalized hash overlap 为 0，再进入 fresh audit 实现/授权。
- [ ] fresh audit、formal、split、shadow、release、Luna、四个 Generator、Retriever、victim 与 evaluation 继续 blocked；Gemma 2 2B 仍是上游 release 后首个 victim Generator。

当前唯一下一步：用户本人运行 EDGAR development pilot；完成前不签发 Enron/PubMed pilot authorization，也不启动任何下游阶段。

### 2026-08-17：EDGAR revision 4 pilot runtime bug 修复

- [x] 将首个 source 的异常判定为 operation/runtime failure，而非 `failed_development_gate`；未查看 membership、AUC、victim/LLM-only response 或 Retriever 输出。
- [x] 保留 revision 4 partial attempt：authorization=`a40eab77...a67d`、attempt=`385a242b...23ea`、budget charge=`1`、source results=`0`、checkpoint 不存在；进程已退出、lock 已移除，未删除或改写 artifact。
- [x] 定位 schema mismatch：v22 生产 `source_order_rank` 是 SHA-256 十六进制字符串，pair 构造却按十进制转换；旧测试的 `"000001"` 掩盖了生产错误。
- [x] 在不修改 design-r6/e1、hard gates、17 项 rank、capacity 或 pair schema 的前提下，将转换最小修复为 base 16，并添加包含 `a-f` 的 64 位生产格式回归。
- [x] 修复前新回归精确失败；修复后单测 `1/1`、selector `6/6`、完整 v23 测试 `50/50`、目标文件内存 AST 均通过。真实 source/GPU/API/victim/Retriever 调用和新增真实预算均为 0。
- [x] 用户确认后运行全仓回归；`unittest discover -s tests` 为 `469/469` passed（`605.003s`），308-file 内存 AST、敏感值扫描与 `git diff --check` 通过，无真实外部调用。锁定环境无 `ruff`/`mypy`，未使用 Conda base 或联网安装。
- [ ] 仅提交本次代码与回归测试；两份总表在本轮前已有 revision 4 未提交增量，因此继续整体保留在工作树，不随本次 commit 带入；不推送。
- [ ] 提交后另行授权 successor runtime freeze；旧 revision 4 authorization 不得配合工作树修复直接续跑。
- [ ] 新 revision 下的 aggregate-DF/reservation 复用或重建必须由 stage-scoped fingerprint、显式 authorization 与 validator 决定；不得手工迁移或覆盖 partial artifact。
- [ ] EDGAR 新授权并一次性 pass/fail 前，不签发或启动 Enron/PubMed；fresh audit 与全部下游继续 blocked。

当前唯一下一步：仅提交本次代码与回归测试；提交不等于 freeze、pilot resume、GPU/API/victim/Retriever 或下游授权。

### 2026-08-17：source-order-rank 修复提交后状态

- [x] 按用户确认的 subject 创建本地 commit=`e8f5a3f6cea68bfa87bbc37eb40c813f8ada254f`（`fix(attack): parse v23 source order rank as hex`）；仅含代码与回归测试 2 个文件，未推送、未纳入其他脏工作树。
- [ ] 等待用户单独授权 successor runtime freeze；提交本身不授权 freeze、新 authorization、pilot resume 或外部调用。
- [ ] freeze 与显式 validator/authorization 完成前，不复用旧 EDGAR authorization，不启动 Enron/PubMed，不修改或清理 revision 4 partial artifact。

当前唯一下一步：等待用户单独授权 successor runtime freeze；未获授权前保持所有 execution stage blocked。

### 2026-08-17：revision 5 freeze 与新 EDGAR authorization 门禁

- [x] 生成 successor freeze authorization=`71235950...7ac38`，冻结并独立验证 revision ordinal=`5`、bundle=`439c2c14...40991`、protocol revision=`26cf9140...76b2d`、code commit=`e8f5a3f6...254f`；ledger tip 未变化，external calls=`0`。
- [x] 对比 revision 4/5 的 aggregate-DF stage dependency fingerprint，均为 `9fc3c9d2...c8011`；使用 authorization=`0e948bef...85de5` 完成并独立验证 carry-forward，attestation=`ef1e7d33...03020`、文件 SHA-256=`c05bc3d3...c9394`，source reread/新增预算/ledger mutation/external calls 均为 `0/0/false/0`。
- [x] 通过官方入口尝试生成 revision 5 EDGAR authorization；因 revision 5 reservation 尚未建立，`revision_reservation_authorization_count_invalid` 在分配 attempt 前 fail closed，新 revision run authorization 数量保持 `0`。
- [x] 确认 e1 只定义 aggregate-DF fingerprint/carry-forward；reservation 与 development pilot 不可人工按“未受修复影响”直接迁移。
- [x] 确认下一道恢复阻断：revision 4 空 partial 目录仍存在，当前 authorization preparation 会以 `development_pilot_attempt_or_artifact_already_exists` 拒绝；禁止删除、移动、覆盖或绕过。
- [ ] 等待用户单独授权最小恢复 runtime/测试：保留旧 authorization、budget 与空 partial evidence，同时为 successor revision 提供有审计绑定的合法新 attempt 路径；不得放宽其他 gate。
- [ ] 恢复修复提交并再次 freeze 后，按新 revision 完成 aggregate-DF 身份验证、revision reservation 与 validator，再生成 EDGAR authorization；长 reservation/pilot 命令继续由用户本人运行。

当前唯一下一步：等待用户授权最小恢复语义的实现与测试；未获授权前不创建 revision 5 reservation attempt、不手工生成 EDGAR authorization、不启动任何 pilot。

### 2026-08-17：development recovery r1 实现与验证

- [x] 新增精确哈希绑定的 `restoration_first_v23.development_recovery_r1.yaml`（SHA-256=`8b57250c...56ef`）并纳入后继 runtime closure；不改写 design-r6/e1。
- [x] 仅允许在 active reservation 未开始、latest prior reservation 完整 passed、ledger tip 未前进、development batch identity 精确一致时，把 prior reservation 作为 development-only prerequisite；fresh-audit reserve reuse 明确为未授权。
- [x] 将新 development source results 改为 `<dataset>/attempts/<attempt_id>/source_results/`，保留 revision 4 旧 authorization、budget 与空 legacy 目录原样；任何旧 source result、checkpoint、canonical output 或意外目录条目均 fail closed。
- [x] 在新 source 可见前生成并验证 recovery attestation，绑定 recovery contract、prior reservation completion/checkpoint/final tip、旧 partial 文件 hashes，以及新 authorization/revision/attempt。
- [x] 合成端到端回归先红后绿：实现前精确阻断于 `revision_reservation_authorization_count_invalid`（115.712s），实现后恢复通过（205.121s），并验证旧证据与 ledger 不变、新结果按 attempt 隔离。
- [x] 非空旧 result 拒绝、既有 development group、capacity terminal、runtime closure 定向回归均通过；恢复后的秒级门禁 `2/2`（0.015s），目标 AST 与 recovery contract 精确身份加载通过。
- [ ] 完整 `tests.test_restoration_first_v23` 曾按用户要求中断，不能登记为 passed；由用户本人运行长回归并返回结果。
- [ ] 长回归通过后，等待用户单独确认仅提交 recovery contract、`src/prepare/restoration_first_v23.py` 与对应测试；不纳入其他脏工作树，不推送。
- [ ] 提交后另行授权 successor freeze；freeze/validator 通过后才可准备新 EDGAR authorization。不得生成 revision 5 reservation、删除旧 partial、启动 Enron/PubMed 或任何外部调用。

当前唯一下一步：用户本人运行完整 v23 离线回归；在其通过前，工作树实现不得进入真实 runtime，EDGAR/Enron/PubMed 与全部下游继续 blocked。

### 2026-08-17：development recovery r1 长回归完成

- [x] 用户本人完成 `tests.test_restoration_first_v23`：`52/52 passed`（789.765s，`OK`）；此前中断执行不再是当前验证阻断，但仍保留为操作历史。
- [x] recovery r1 定向与全模块离线验证闭环通过；未产生真实 source/GPU/API/victim/Retriever 调用、费用、ledger mutation、authorization 或 attempt。
- [ ] 等待用户明确确认仅提交 recovery contract、`src/prepare/restoration_first_v23.py` 与 `tests/test_restoration_first_v23.py`；不得带入两份总表或其他脏工作树，不推送。
- [ ] 提交后另行授权 successor freeze 与 validator；freeze 前不得生成新 EDGAR authorization 或运行 pilot。
- [ ] EDGAR 新 attempt 按预注册门槛一次性判定；passed 才继续 Enron，failed 则停止并记录。fresh audit 与全部下游继续 blocked。

当前唯一下一步：等待用户确认三文件 recovery commit；确认只授权本地提交，不自动授权 freeze、authorization、pilot、Enron/PubMed 或外部调用。

### 2026-08-17：development recovery r1 提交后状态

- [x] 创建限定范围本地 commit=`a964e63676b95d71f85975eaa3390c0bfb1bca03`（`fix(prepare): add audited v23 development recovery`）；仅含 3 个 recovery 文件，未推送、未带入两份总表或其他脏工作树。
- [x] 提交信息记录 runtime closure 变化、artifact/API 边界与 `52/52 passed`；分支当前 ahead 5。
- [ ] 等待用户单独授权 successor runtime freeze 与独立 validator；提交不等于 freeze。
- [ ] freeze 通过后再单独准备新 EDGAR authorization；不得复用 revision 4 authorization，不启动 Enron/PubMed。
- [ ] EDGAR 按预注册门槛一次性判定；passed 才继续 Enron，failed 则停止并记录。fresh audit 与全部下游继续 blocked。

当前唯一下一步：等待用户授权 successor freeze/validator；未获授权前不修改 active runtime identity、不生成 authorization、不运行真实 pilot。

### 2026-08-17：revision 6 freeze/validator

- [x] 仅按用户授权生成 freeze authorization=`d03228af...1c17`（文件 SHA-256=`a6f51323...347d`）；未扩展到 stage carry-forward、EDGAR authorization 或 pilot。
- [x] 冻结并激活 revision ordinal=`6`、bundle=`c946f350...2e1a`、protocol revision=`1275ff12...348f`、code commit=`a964e636...ca03`。
- [x] 独立 validator exit code 0、`status=passed`；checkpoint SHA-256=`4f117da2...98ac`，ledger tip 保持 `3c912fd1...aa8e1`，external calls=0，无 governance lock。
- [x] 非必要的补充全链 `status` 因超出短时预期主动中止，不作为实验/协议失败；freeze 与独立 validator 结论不受影响。
- [ ] 等待用户单独授权 aggregate-DF stage fingerprint 比对；只在 revision 5/6 fingerprint 精确相等时生成并验证 carry-forward attestation。
- [ ] carry-forward passed 后再单独准备 recovery-aware EDGAR authorization；不生成 revision 6 reservation，不复用 revision 4 authorization。
- [ ] EDGAR 按预注册门槛一次性判定；passed 才继续 Enron，failed 则停止并记录。fresh audit 与全部下游继续 blocked。

当前唯一下一步：等待 aggregate-DF fingerprint/carry-forward 的单独授权；未获授权前不生成任何 run authorization/attempt，不运行真实 source 或外部调用。

### 2026-08-17：revision 6 aggregate-DF carry-forward

- [x] 重算 revision 5/6 stage fingerprint，均为 `9fc3c9d2...c8011`；允许进入 carry-forward。
- [x] 生成 compatibility authorization=`3e1483b6...b83c`（文件 SHA-256=`2029c4fa...9668e`），provenance `from_*` 保持指向原始 producer revision 2，target 指向 revision 6。
- [x] carry runner exit code 0、内嵌 validator 返回 `passed/carried_forward`；attestation=`5a1428eb...04ed`，文件 SHA-256=`b7e29bb4...5ed0`，三数据集证据 hash 完整绑定。
- [x] ledger 文件 hash 前后均为 `0f05967a...d394`；revision 6 run authorization/attempt=`0/0`，source reread/ledger mutation/external calls=`false/false/0`，无 governance lock。
- [ ] 用户本人运行独立 `validate-carry-forward --stage aggregate_df_precomputation` 长命令并返回结果；该验证不生成新 artifact/authorization。
- [ ] 独立 validator passed 后，等待用户单独授权准备 recovery-aware EDGAR authorization；不创建 revision 6 reservation。
- [ ] EDGAR 按预注册门槛一次性判定；passed 才继续 Enron，failed 则停止并记录。fresh audit 与全部下游继续 blocked。

当前唯一下一步：用户运行独立 carry-forward validator；在其通过前不生成 EDGAR authorization，不运行真实 pilot。

### 2026-08-17：revision 6 aggregate-DF 独立验证完成

- [x] 用户本人运行独立 carry-forward validator，返回 `passed/carried_forward`；attestation、文件 hash、fingerprint、三数据集 producer 证据与 runner 输出完全一致。
- [x] revision 6 aggregate-DF authorization→carry→independent validation 闭环完成；source reread/ledger mutation/external calls=`false/false/0`。
- [ ] 等待用户单独授权准备 recovery-aware EDGAR authorization；仅生成新 authorization/attempt/recovery attestation，不运行 pilot。
- [ ] EDGAR 新 authorization 生成后由用户本人运行长命令，并按预注册门槛一次性判定；passed 才继续 Enron，failed 则停止并记录。
- [ ] fresh audit、formal、split、shadow、release、Generator、Retriever、victim 与 evaluation 继续 blocked。

当前唯一下一步：等待 recovery-aware EDGAR authorization preparation 的单独授权；未获授权前保持 revision 6 run authorization/attempt=`0/0`。

### 2026-08-17：EDGAR recovery-aware authorization preparation 长命令交接

- [x] 用户明确授权 preparation，不授权运行 pilot、Enron/PubMed 或外部调用。
- [x] 助手侧 preparation 因本地完整性验证超过 15 分钟按长命令边界中止；未出现治理失败。
- [x] 中止后核验 revision 6 run authorization/attempt=`0/0`、legacy result=`0`、ledger 与旧 authorization/budget hashes 不变。
- [x] 核验遗留 lock PID=`956776` 已退出，仅移除该精确 stale lock；无其他 artifact 清理或改写。
- [ ] 用户本人使用同一授权记录运行冻结 preparation 命令并返回 JSON；不得并行或重复启动。
- [ ] 成功后核验唯一新 authorization/attempt、recovery attestation、reservation validation mode 与旧 partial 字节不变；不运行 pilot。
- [ ] EDGAR 长 pilot 仍需沿用现有单独运行授权边界，并按预注册门槛一次性判定；passed 才继续 Enron，failed 则停止并记录。

当前唯一下一步：用户运行 EDGAR authorization preparation 长命令；完成前保持 pilot 与全部下游 blocked。

### 2026-08-17：revision 6 EDGAR recovery authorization 准备完成

- [x] 用户本人完成 preparation，生成唯一 authorization=`09f1466a...a93bd`、attempt=`093ed478...a3991`；authorization 文件 SHA-256=`e3479550...d4f5c`。
- [x] attempt registry 恰好 1 条匹配；recovery attestation ID=`1928af0b...c9286`、文件 SHA-256=`ad58e959...715ad`、canonical ID 校验通过。
- [x] mode=`prior_revision_development_recovery`，attestation 绑定 revision 4 reservation 与旧 partial authorization/budget/result=`a40eab77...a67d` / `1` / `0`。
- [x] 新 budget/source-result/checkpoint 均不存在；ledger 与旧 partial 文件 hashes 不变，legacy result=0，external calls=0，无 governance lock。
- [ ] 等待用户单独授权运行 revision 6 EDGAR pilot；preparation 不等于执行授权。
- [ ] 授权后由用户本人运行长 pilot 命令，再运行独立 validator；按预注册门槛一次性判定 passed/failed。
- [ ] EDGAR passed 才准备 Enron；failed 则停止并记录。fresh audit 与全部下游继续 blocked。

当前唯一下一步：等待 EDGAR pilot 的明确运行授权；未获授权前不得使用新 authorization 启动 source processing。

### 2026-08-17：revision 6 EDGAR pilot 运行授权与 resume 规则

- [x] 用户明确授权运行 revision 6 EDGAR pilot；不授权 Enron/PubMed 或外部调用。
- [x] CUDA preflight 通过：`mia_model`、PyTorch `2.11.0+cu130`、CUDA=true、RTX 4060 Laptop GPU；无 CPU fallback。
- [x] 启动前 authorization 未消费，budget/result/checkpoint 均不存在，无 governance lock。
- [x] 确认同一 authorization/attempt 支持 durable resume：已完成 result 验证后跳过，已扣费未落盘使用同一 operation charge，不重复扣预算；checkpoint 存在时幂等验证返回。
- [ ] 用户本人运行冻结 pilot 长命令；中断时不得重新 prepare，只能原样重跑同一命令。
- [ ] runner 完成后运行独立 validator，并按 determinism、hard-gate、capacity 预注册门槛一次性判定 passed/failed。
- [ ] EDGAR passed 才准备 Enron；failed 则停止并记录。fresh audit 与全部下游继续 blocked。

当前唯一下一步：用户运行 EDGAR pilot；长时间无控制台输出不等于停滞，可只读监控计数但不得读取 result 内容。

### 2026-08-17：v23 轻量 development execution

- [x] 用户批准以“开发阶段最低够用、formal 边界一次性冻结”取代逐阶段 strict governance；科学泄漏边界、固定 reservation、source-level 单位、checkpoint/resume 与 capacity gate 不变。
- [x] development CLI 收敛为六个命令；删除 bootstrap/successor/carry-forward/revision-reservation 与全部 `prepare-*-authorization` 的主流程入口，`run-development-pilot` 不再接受 `--authorization`。
- [x] development attempt 仅绑定逐数据集科学依赖；Git HEAD 仅记录为元数据，governance/日志/进度代码不改变 attempt ID，不再访问 runtime lineage、历史 `git show` 或全工作树 clean gate。
- [x] EDGAR 只读加载 revision 4 的 EDGAR development plan 和 EDGAR aggregate-DF；不读取 Enron/PubMed reservation、fresh reserve、membership、victim/LLM-only response、Retriever 输出或 AUC，也不修改 ledger。
- [x] 实现 attempt-scoped 原子 source result、稳定 resume、每 10 条进度/ETA、活跃 PID 排他与死亡 PID stale-lock 恢复；已完成 1000 条但未汇总时直接 finalize，不重新加载 GPU。
- [x] 取消 authorization budget journal 与 pilot ledger lock；只保留 dataset development run lock 和 dataset aggregate-DF build lock。
- [x] capacity/hard-gate failure 保持终态；所有 manifest、selected pairs、source results 与 checkpoint 均在 `<dataset>/attempts/<attempt_id>/` 内，不覆盖全局文件。
- [x] 旧 authorization=`09f1466a...a93bd` / attempt=`093ed478...a3991` 标记为历史未使用证据：result=`0/1000`、新 budget=`0`、checkpoint=`0`、external calls=`0`；全部历史 artifact 原样保留。
- [x] 现有 EDGAR aggregate-DF 只读 validator `passed`；新 CLI/identity/status 均秒级完成，未加载 GPU或启动真实 pilot。
- [x] 轻量回归 `7/7`、primitive/selector/evaluation `14/14` 通过；合并模块为 `60 tests / OK / skipped=39`（39 项为已 supersede 的 strict-governance 测试）。AST/import 与 `git diff --check` 通过，仅有 CRLF warning。
- [ ] 用户本人运行全仓库离线 `unittest discover -s tests`；助手不代跑长回归。
- [ ] 全量回归通过后，用户本人运行新的 EDGAR 长命令：`& 'D:\python\anaconda\envs\mia_model\python.exe' -B -X utf8 scripts\42_run_v23_restoration_first.py run-development-pilot --dataset edgar`。
- [ ] EDGAR 完成后运行 `validate-development-pilot --dataset edgar`，按预注册门槛一次性判定；`passed` 才继续 Enron，`failed_*` 则停止并记录。
- [ ] fresh audit、formal test、API/victim/Retriever、付费调用及未来 formal runtime freeze 均维持单独授权边界。

当前唯一下一步：用户运行全量离线测试；通过后直接执行不带 authorization 的 EDGAR development pilot。不得消费旧 authorization，不启动 Enron/PubMed 或任何外部调用。

### 2026-08-18：EDGAR pilot crash-only selector 修复

- [x] 记录 EDGAR pilot 在 `451/1000` 的真实边界异常：mask 后 relation cue 为空，`next(RELATION_CUE_RE.finditer(masked))` 未处理空迭代器。
- [x] 将该候选改为正常 `relation_cue_missing_after_masking` rejection，保持 Restoration hard-gate 语义，不把异常计为 eligible 或 capacity failure。
- [x] 通过精确 scientific hash compatibility 保持原 attempt=`2dedf433...f342`，已完成 451 条 result 原样复用；未创建新 authorization、新 attempt 或新 artifact。
- [x] 回归测试 `8/8 passed`；未启动真实续跑，external calls/API/victim/Retriever/membership/AUC 仍为 0。
- [ ] 用户本人原样重跑 EDGAR pilot，确认从 `451/1000` 继续。
- [ ] 完成后运行 `validate-development-pilot --dataset edgar`，按预注册门槛一次性判定；passed 才继续 Enron，failed 则停止并记录。

当前唯一下一步：用户续跑现有 EDGAR attempt；不得重新 preparation、生成新 authorization 或启动 Enron/PubMed。

### 2026-08-18：EDGAR capacity gate 失败终态

- [x] EDGAR attempt=`2dedf433...f342` 完成 `1000/1000` source，eligible=`138`，selected pairs=`414`，external calls=`0`。
- [x] capacity gate 返回 `K_L=636`、`formal_eligible_lower=248`、`required_formal=2250`、`status=failed_capacity_shortfall`；最低观察门槛 `623` 未达到。
- [x] 保留全部 attempt-scoped manifest、source result、selected pairs 与 checkpoint；不调门槛、不补样本、不重选 source、不改写失败为 passed。
- [x] 按协议停止 Enron/PubMed development、fresh audit、formal freeze、formal test、API/victim/Retriever 与全部下游。
- [ ] 追加失败模式分析，决定是否提出新的版本化科学设计；新设计未获单独批准前不得运行任何其他数据集。

当前唯一下一步：完成 EDGAR failure analysis；项目停在 `failed_capacity_shortfall`，不进入 formal 实验。

### 2026-08-18：EDGAR failure analysis 完成

- [x] 只读核验 attempt=`2dedf433...f342` 的 1000 条 source-level 安全元数据；未读取 membership、victim/LLM-only response、Retriever 输出、AUC 或 source 正文。
- [x] 确认容量失败：eligible=`138/1000`，selected pairs=`414`，最低观察门槛=`623`；`K_L=636`、`c=250`、formal lower=`248<2250`，终态保持 `failed_capacity_shortfall`。
- [x] 确认主要可观测瓶颈是 pair candidate gate：失败 862 条中 457 条 pair candidates 为 0；eligible 的 pair 数中位数 27，失败中位数 0。失败 reason union 高频项集中于 relation cue、source-specific anchor、unresolved reference 和 fact-token gate。
- [x] 记录归因边界：reason 列表非互斥且只有 source-level union；128 条存在 >10 pair candidates 但未选对的失败 source 只能提示 diversity gate，不能作候选级因果结论。
- [x] 确认运行完整性：deterministic rerun hash=`true`（1000/1000），hard-gate violation=`0`，external calls=`0`；该结果可复现且不是治理/泄漏故障。
- [x] 生成并保留诊断 bundle：`artifacts/v23/analysis/edgar_development_failure/analysis-report.md`、`stats-appendix.md`、`figure-catalog.md`、`summary.json` 与两张 PNG；历史 attempt/source results/checkpoint 原样保留。
- [x] 按预注册失败顺序停止 Enron/PubMed、fresh audit、formal freeze、formal test 及 API/victim/Retriever；不通过调门槛、补样本或续跑将其改写为 passed。
- [ ] 如需继续研究，另行提出并审批新的版本化 selector/gate 科学设计；在批准前不运行其他数据集、不修改旧 attempt、不进入 formal。

当前唯一下一步：等待新的科学设计决策；现行 v23 development 证据以 EDGAR `failed_capacity_shortfall` 终态封存。

### 2026-08-18：独立 v23 Fact Layer r1 实现

- [x] 新增 fact-layer config、纯 fact candidate/evaluation 模块、resumable runner、CLI 与测试；旧 r6 runtime/attempt/artifact 未修改。
- [x] 新 fact identity 绑定 dataset、固定 development reservation/source-order、entity policy、GLiNER lock、fact-layer config/implementation hash 与 design-r7 manifest identity；不绑定旧 r6 selected pairs、eligible count 或历史 facts。
- [x] `FactCandidate` 保存 exact proposition、target span、slot-aware fact signature、predicate kind、fact validity、retrieval diagnostics、replacement candidates 与 rejection codes；不生成启发式 subject/relation 文本。
- [x] P0 移除 source-specific anchor 与固定 relation-cue 硬门槛；保留完整 proposition、exact span、recoverability、single-slot replacement、source absence、content-token self-containment 与每 source 三个不同 fact signature。结构化类型仅 diagnostic。
- [x] 新 runner 支持每 dataset lock、source-level 原子 result、checkpoint/resume、deterministic rerun、死亡 PID stale-lock 恢复；不读取 r6 aggregate-DF/旧 selection artifact，不获取 ledger lock，DF/IDF 诊断保持非阻断未使用状态，external calls=`0`。
- [x] 新 CLI 已包含 `status`、`extract-facts`、`validate-facts`、`select-pairs`、`run-development-pilot`、`validate-development-pilot`；fact extraction 与 validation 可独立执行。
- [x] 定向测试 `5/5 passed`；新模块/CLI/test AST compile 通过；未启动 CUDA、未读取真实 source、未创建新 attempt、未调用 API/victim/Retriever。
- [ ] 用户本人运行 `scripts/42_run_v23_fact_layer.py extract-facts --dataset edgar`，返回 manifest 后运行 `validate-facts --dataset edgar`。
- [ ] fact layer 通过后再复核 `select-pairs` 与 P0 capacity gate；通过前不运行 Enron/PubMed、fresh audit 或 formal。

当前唯一下一步：用户运行 EDGAR fact extraction 长命令；助手不代跑 GPU 长任务。

### 2026-08-19：EDGAR Fact Layer r1 development 闭环

- [x] EDGAR `extract-facts` 完成 `1000/1000`：candidate=`661689`、structured diagnostic=`608652`、fact-valid=`27749`、P0-ready=`21021`，attempt=`eac91b4b...ffcd9`，external calls=`0`。
- [x] `validate-facts` 独立核验通过，fact manifest SHA-256=`731cc284...2e38`。
- [x] `select-pairs` 通过：candidate pairs=`141065`、eligible source=`970/1000`、selected pairs=`2910`，每个 eligible source 恰好三对；selection manifest SHA-256=`5897fe99...4488`。
- [x] development capacity gate 通过：`K_L=5005`、`c=250`、formal lower=`3785>=2250`。
- [x] `validate-development-pilot` 以 `recomputed_from_fact_and_selection_artifacts` 重算通过；facts、selection、capacity 与 manifest hashes 一致。
- [x] 保留旧 r6 EDGAR `failed_capacity_shortfall` 为历史失败证据；新结果不回写、不覆盖旧 attempt，也不表述为 formal MIA/AUC 结果。
- [ ] 等待用户单独授权后才运行 Enron Fact Layer r1；不得自动启动 PubMed、fresh audit、formal freeze、victim/API/Retriever 或付费调用。

当前唯一下一步：等待 Enron `extract-facts` 的明确运行授权；EDGAR development 已完整闭环，formal 与外部调用仍未授权。

### 2026-08-19：Enron Fact Layer r1 development 闭环

- [x] Enron `extract-facts` 完成 `1000/1000`：candidate=`24303`、structured diagnostic=`5948`、fact-valid=`2399`、P0-ready=`1175`，attempt=`1d90a395...9d343`，external calls=`0`。
- [x] `validate-facts` 独立核验通过，fact manifest SHA-256=`001e0bc5...d155`。
- [x] `select-pairs` 通过：candidate pairs=`9548`、eligible source=`149/1000`、selected pairs=`447`，每个 eligible source 恰好三对；selection manifest SHA-256=`41a17212...9dd5`。
- [x] development capacity gate 通过：`K_L=4586`、`c=250`、formal lower=`4187>=2250`。
- [x] `validate-development-pilot` 以 `recomputed_from_fact_and_selection_artifacts` 重算通过；facts、selection、capacity 与 manifest hashes 一致。
- [x] 保持外部调用、membership/victim/LLM-only response、Retriever、AUC、fresh audit 与 formal test 均未启动；结果不表述为 formal MIA 结果。
- [ ] 等待用户单独授权后才运行 PubMed Fact Layer r1；不得自动启动 fresh audit、formal freeze、victim/API/Retriever 或付费调用。

当前唯一下一步：等待 PubMed Fact Layer r1 的明确运行授权；EDGAR 与 Enron development 均已完整闭环。

### 2026-08-20：三数据集 Fact Layer r1 development 闭环完成

- [x] PubMed `extract-facts` 完成 `1000/1000`：candidate=`243433`、structured diagnostic=`194238`、fact-valid=`26800`、P0-ready=`18041`，attempt=`920b51fb...4d672`，external calls=`0`。
- [x] `validate-facts` 独立核验通过，fact manifest SHA-256=`d6beeab5...a478c`。
- [x] `select-pairs` 通过：candidate pairs=`146122`、eligible source=`948/1000`、selected pairs=`2844`，每个 eligible source 恰好三对；selection manifest SHA-256=`ef8aea8f...dc54a`。
- [x] development capacity gate 通过：`K_L=44837`、`c=250`、formal lower=`43639>=2250`。
- [x] `validate-development-pilot` 以 `recomputed_from_fact_and_selection_artifacts` 重算通过；facts、selection、capacity 与 manifest hashes 一致。
- [x] 三数据集 development 结果汇总：EDGAR `970/1000`、Enron `149/1000`、PubMed `948/1000` eligible，全部 `status=passed`，external calls=`0`。
- [x] 明确保留边界：development capacity 通过不等于 formal MIA/AUC 通过；旧 r6 EDGAR failure 不改写；fresh audit、formal freeze、formal test、victim/API/Retriever 仍未启动。
- [ ] 等待用户单独决定并授权 fresh audit；未授权前不得消费 fresh reserve 或进入 formal。

当前唯一下一步：准备 fresh-audit 决策与一次性授权；三数据集 Fact Layer development 已完整闭环。

### 2026-08-20：Fact Layer r1 AI 预审

- [x] 只读核验三数据集 facts/pairs/manifest：结构 hash、fact-to-pair、exact span、single-slot replacement、3 pair/source、fact signature distinctness、原实体上限均通过。
- [x] 发现 diagnostic-only 语义风险：EDGAR `The Company` 泛化实体约 144 条，并有 `$2`/`2015`/`2 acres` formal-type 数值误接受；Enron 有 `Start Date` 与 timestamp `To:` 邮件头样式及 `347356` 数值标识符；PubMed 有 Date/Subject 邮件头样式、`organization` 泛化实体和数值/度量误接受。
- [x] 记录代表样本供用户复核：`The Company -> Vanta Industries`、`2 acres -> Sydney`、`Start Date -> Jordan Ellis`、`PLOS ONE -> Alex Carter`、`14 -> Dublin`。
- [x] AI 预审仅为 diagnostic，不冒充两名真人 blind fresh audit，不消费 fresh reserve，不改变 r1 passed/capacity artifact，external calls=`0`。
- [ ] 用户复核疑点；若确认误接受，先创建新 Fact Layer revision/attempt 修复后再 fresh audit，禁止原地改写 r1 artifact。

当前唯一下一步：等待用户确认 AI 预审样本是否确属误接受，再决定是否实现 Fact Layer r2 修复；fresh audit 暂不消费 reserve。

### 2026-08-19：Enron Fact Layer r1 development 闭环

- [x] Enron `extract-facts` 完成 `1000/1000`：candidate=`24303`、structured diagnostic=`5948`、fact-valid=`2399`、P0-ready=`1175`，attempt=`1d90a395...d343`，external calls=`0`。
- [x] `validate-facts` 独立核验通过，fact manifest SHA-256=`001e0bc5...d155`。
- [x] `select-pairs` 通过：candidate pairs=`9548`、eligible source=`149/1000`、selected pairs=`447`，每个 eligible source 恰好三对；selection manifest SHA-256=`41a17212...9dd5`。
- [x] development capacity gate 通过：`K_L=4586`、`c=250`、formal lower=`4187>=2250`。
- [x] `validate-development-pilot` 以 `recomputed_from_fact_and_selection_artifacts` 重算通过；facts、selection、capacity 与 manifest hashes 一致。
- [x] Enron 结果不改写旧 r6 artifact，也不表述为 formal MIA/AUC 结果；外部调用、membership、victim/LLM-only response、Retriever、fresh audit 与 formal test 均保持未启动。
- [ ] 等待用户单独授权后才运行 PubMed Fact Layer r1；不得自动启动 fresh audit、formal freeze、victim/API/Retriever 或付费调用。

当前唯一下一步：等待 PubMed `extract-facts` 的明确运行授权；EDGAR 与 Enron development 均已完整闭环。

### 2026-08-20：Fact Layer selection r2 闭环完成

- [x] 新增 selection-only r2 config、质量过滤/选择模块、prepare runner 和回归测试；r1 fact extraction 的 config/attack/prepare 文件未修改，因此三套 r1 fact attempt identity 原样复用。
- [x] CLI 的 `select-pairs`、`run-development-pilot`、`validate-development-pilot` 支持显式 `--selection-revision r2`；r2 runner 不调用 `extract_facts`，不加载 GLiNER，只读取已验证的对应数据集 r1 facts。
- [x] r2 高置信过滤覆盖 mail/submission metadata、structured numeric/measurement formal-type 泄漏、通用占位实体、明确 PERSON surface mismatch 与 table/author-contribution metadata；生硬但类型兼容的 probe 不因自然性被拒绝。
- [x] EDGAR r2 attempt=`cc693e3a...9c917`：quality rejected=`1205` facts，eligible=`969/1000`、selected=`2907`、`K_L=4999`、formal lower=`3780>=2250`，selection manifest SHA-256=`6acb9f9a...eb3c`。
- [x] Enron r2 attempt=`f0e8b529...de668`：quality rejected=`33` facts，eligible=`148/1000`、selected=`444`、`K_L=4553`、formal lower=`4155>=2250`，selection manifest SHA-256=`9e07f489...228`。
- [x] PubMed r2 attempt=`65e8b9fa...a3620`：quality rejected=`323` facts，eligible=`946/1000`、selected=`2838`、`K_L=44732`、formal lower=`43536>=2250`，selection manifest SHA-256=`d90696d2...36dfc`。
- [x] 三套 `validate-development-pilot --selection-revision r2` 均以 `recomputed_from_r1_fact_and_r2_selection_artifacts` 独立重算通过；external calls=`0`。
- [x] r1 非回归 hashes 全部保持：fact manifests=`731cc284...2e38` / `001e0bc5...d155` / `d6beeab5...a478c`，selection manifests=`5897fe99...4488` / `41a17212...9dd5` / `ef8aea8f...dc54a`；旧 r6 failure 与 r1 AI 预审证据均未改写。
- [x] fresh reserve、membership、victim/LLM-only response、Retriever、AUC、GPU 与外部调用均未读取/启动；r2 development passed 不表述为 formal MIA/AUC 或真人事实质量结论。
- [x] 验证完成：r1+r2+lightweight 定向回归 `18 tests / OK`，r2 AST compile、新文件 whitespace check 与 `git diff --check` 通过；未安装缺失的 `ruff`，未改变环境依赖。
- [ ] 用户复核 r2 过滤范围与结果；确认后先做 r2 AI 语义复审，再决定是否执行尚未消费的真人 blind fresh audit。

当前唯一下一步：等待用户复核 r2 development 结果；fresh audit 尚未消费，formal runtime freeze、formal test、API/victim/Retriever 与付费调用继续 blocked。

### 2026-08-20：Fact Layer selection r2 AI 语义复审

- [x] 只读复核三套 r2 selected pairs 共 `6189` 条；未读取 membership、victim/LLM-only response、Retriever、AUC 或 fresh reserve，external calls=`0`。
- [x] 结构重算通过：三数据集 single-slot replacement mismatch=`0/6189`；r2 已知首批泛化实体、数值/度量和邮件/投稿头样例未重新进入 selected pairs。
- [x] 发现残留 list/clause-dump 诊断：逗号数 `>=10` 的 EDGAR=`33`、Enron=`3`、PubMed=`48`，另有 PubMed `1` 条多 email/header 形态；代表为 `Listed by:`、抗体/化合物/区域/引用枚举和多公司合同条款枚举。
- [x] 发现未解析指代表面：EDGAR=`6`、Enron=`2`；代表 Enron `them→Orion Services Inc`。这些与 P0 unresolved-reference 排除边界冲突。
- [x] 记录高置信类型错配：`Texas Exes→Tokyo`、`gas→Meridian Service`、`ER→Summit Data Corp`、`slaughter→Renewal Period`、`caudate→Dublin`、`Statgraphics Centurion→Casey Brooks`、`Educational Psychology→Morgan Lee`、`5 years old girl→Quinn Harper`、`college students→Alex Carter`。
- [x] PERSON 表面启发式疑点上界：EDGAR=`13`、Enron=`3`、PubMed=`123`；未将其冒充真人标注或最终错误率。
- [ ] r2 不作为 fresh audit 开封版本；需先决定是否提出 selection revision r3，专门处理列表/代词/实体角色错配。fresh reserve、formal、API/victim/Retriever 继续 blocked。

当前唯一下一步：用户确认是否实现 r3 选择层修复；在确认前不消费 fresh reserve，不修改 r2 artifact。

### 2026-08-20：r2 固定与 API 登录切换后的续接计划（superseding）

- [x] 接受 r2 的少量残余语义风险；不实现 r3，不重新抽取实体，不改写既有 r1/r2 artifact。
- [x] 将 r2 作为当前 development 与后续 fresh-audit 准备版本；三数据集 capacity gate、selection manifest 和独立 validator 结果保持冻结。
- [x] 完成 API 登录切换交接记录；登录方式/额度变化不改变 protocol、artifact identity 或数据隔离边界。
- [x] 明确外部调用边界：截至交接时 `external_calls_performed=0`，未消费 fresh reserve，未启动 membership、victim/LLM-only response、Retriever、AUC 或 formal test。
- [ ] 新登录环境只读核验 r2 manifest、两份项目总表和交接文档。
- [ ] 获得用户对 fresh audit 的明确授权后，按冻结 r2 版本执行；不因登录切换自动生成 authorization，也不自动启动 API/victim/Retriever/付费调用。

当前唯一下一步：完成新登录后的只读状态核验，然后等待/记录 fresh-audit 的一次性明确授权。

### 2026-08-20：frozen-r2 fresh audit 准备授权与只读核验

- [x] 用户确认 selection r2 固定；本轮仅授权 frozen-r2 fresh audit 准备与只读验证，不含 API、victim、Retriever、付费调用或正式实验。
- [x] 三数据集 r2 development validator 只读重算通过；eligible=`969/148/946`，formal lower=`3780/4155/43536`，selection/pilot hash 绑定有效，external calls=`0`。
- [x] 只读确认现有 reserve/group metadata 与 execution revision=`71e862b7591b2ac9bd1a1759b3784fc3b0e4b7286b96098d4997f0f173b78043` 一致；未读取 reserve source 内容、未写 ledger、未生成 authorization 或 audit packet。
- [x] 确认当前 CLI 尚无 `fresh-blind-audit` 或 packet-preparation 入口，`artifacts/v23/audit/` 不存在；不使用临时编排绕过治理门禁。
- [ ] 在不消费 fresh reserve 的前提下，另行授权实现/冻结 frozen-r2 fresh-audit preparation runner。

当前唯一下一步：等待 frozen-r2 fresh-audit preparation runner 的单独实现/冻结授权；API、victim、Retriever、付费调用和正式实验继续 blocked。

### 2026-08-20：frozen-r2 fresh-audit preparation runner

- [x] 固定 Fact Layer selection r2，不实现 r3、不重新抽取实体、不覆盖 r1/r2 artifact。
- [x] 实现 preparation config、freeze manifest、metadata-only freeze/validate/status、显式 authorization schema、dataset preparation 与 blind packet preparation CLI 入口。
- [x] 加入 r2 manifest/reserve/group/design/model identity hash binding、数据库 hash/schema 门禁、连续 prefix resume、完整 source-result aggregate hash、盲包 visible/hidden schema 与 deterministic HMAC order。
- [x] 定向测试 `8/8 OK`；内存 AST compile、CLI help、`git diff --check` 通过；freeze identity=`09b9a362ec56acddc3e348084521d3fee41171143c5b37589e782c8ac7acf803`，`validate-freeze=status passed`。
- [x] 本轮只完成 runner 实现与冻结；没有执行 `prepare-dataset`、`build-packets`、authorization 生成、fresh reserve source 内容读取、ledger 写入、API/victim/Retriever、付费调用或正式实验。
- [ ] 等待用户单独授权实际 frozen-r2 fresh-audit dataset preparation；随后才可在另一明确授权下构造 blind packet/human audit 输入。

当前唯一下一步：保持 runner frozen，等待实际 dataset preparation 的明确授权；不得自动生成 authorization、消费 fresh reserve 或启动外部/正式流程。

### 2026-08-20：dataset preparation 已获用户授权，交由用户运行

- [x] 用户授权 frozen-r2 dataset preparation；范围限于本地 fresh reserve source 读取、事实抽取、r2 selection 与 dataset-level preparation artifact。
- [x] API、victim、Retriever、付费调用、membership、AUC、blind packet 与 formal experiment 仍明确不授权。
- [ ] 本会话不启动 GPU 长任务；用户按 `edgar → enron → pubmed` 分数据集运行，使用同一数据集 authorization 可安全 resume 连续 source prefix。

当前唯一下一步：用户自行运行 CUDA 检查、dataset-specific authorization 和第一个 `prepare-dataset` 命令；执行前本 runner 仍未消费 fresh reserve。

### 2026-08-20：EDGAR 首次 preparation 失败，已建立 r1-fix1 freeze

- [x] 记录首次 EDGAR `prepare-dataset` 的 TypeError：reader 缺少 context-manager protocol；失败在 source loop 前，未生成 source-result/manifest/selected-pairs，未消费 reserve source 内容。
- [x] 增加 `_FreshAuditSourceReader.__enter__/__exit__` 与回归测试；旧 `r1` freeze/空 audit 目录保持不变。
- [x] 新 runner revision=`r1-fix1`，freeze identity=`bf3808063e71ff46f371bd8a27c3d3023b39dfe57f54b76bfeb0456db2b17f74`，manifest SHA-256=`9acd8c85ec08a924ae23b55026d62a25bb7ada9ce62c085367a115812e88dc79`；`validate-freeze/status` 和 `9/9` 定向测试通过。
- [ ] 旧 authorization=`d98e00ef...6d775d` 不能复用；用户需为新 freeze 重新生成 EDGAR authorization，再重试 dataset preparation。

当前唯一下一步：用户自行用 `r1-fix1` 新 authorization 重试 EDGAR；不运行 packet preparation 或任何外部/正式流程。

### 2026-08-20：EDGAR 第二次 preparation 失败，建立 r1-fix2

- [x] `r1-fix1` 重试已读取首个 source 内容后触发 `source_order_identity_drift`；根因是 DB `source_order_rank` 为 hash 字符串，不能与 reserve 的 numeric order index 比较；未写 canonical source-result。
- [x] 修复为绑定冻结 source-order 文件的 index-to-key 映射，新增回归测试；旧 `r1-fix1` freeze、authorization 与 audit 目录保留。
- [x] 新 runner revision=`r1-fix2`，freeze identity=`3bfad5b67a7f71f7d8278e6e18a5149d37e78464b64d750fc41a40129a8bc4ae`，manifest SHA-256=`99c12c2e74336b83503bfe3e33b95ce3df8cc9d8aa295e1028e949da81699c41`；`validate-freeze/status`、`10/10` 定向测试通过。
- [ ] `r1-fix1` authorization=`81172096...d296e` 不得复用；用户需为 `r1-fix2` 重新生成 EDGAR authorization。

当前唯一下一步：用户自行用 `r1-fix2` 新 authorization 重试 EDGAR；不运行 packet preparation 或任何外部/正式流程。

### 2026-08-20：EDGAR dataset preparation 完成

- [x] EDGAR 使用 r1-fix2 authorization=`6fa812ee...e6924f9` 运行成功。
- [x] `104` evaluated source → `100` selected eligible source → `300` selected pair；dataset manifest `status=passed`，source-results aggregate identity 已冻结，external calls=`0`。
- [x] EDGAR 结果绑定 freeze identity=`3bfad5b6...a8bc4ae`；未读取 membership、victim/LLM-only response、Retriever 或 AUC。
- [ ] Enron/PubMed dataset preparation 尚未执行；blind packet/human audit 与 formal/API/victim/Retriever 流程仍 blocked。

当前唯一下一步：用户分别决定并授权 Enron、PubMed preparation；不要运行 `build-packets`。

### 2026-08-20：Enron preparation 交由用户续跑

- [x] 确认 runner 已按 `eligible >= 100` 自动停止，无需修改配置。
- [x] 本会话进程按用户要求停止；保留 `157` 个连续 source-result，当前 `22` eligible，dataset manifest 尚未生成。
- [x] 原 Enron authorization=`dc54a681...d526446` 可继续用于同一 freeze 的 prefix resume；packet、API/victim/Retriever、付费调用和 formal 仍 blocked。

当前唯一下一步：用户自行续跑 Enron，达到 `100` eligible 后自动完成；不要生成新 authorization，不要运行 `build-packets`。

### 2026-08-20：Enron fresh-audit reserve shortfall（failed, evidence preserved）

- [x] Enron 连续完成 `250/250` reserve source，source-result index `0..249` 无缺口。
- [x] eligible=`29/250`，低于冻结 selected target=`100`；`prepare-dataset` fail-closed，未生成 dataset manifest/selected-pairs release。
- [x] 保留所有 source-result、旧 authorization 与 freeze；不修改目标数、不扩充 reserve、不覆盖历史 artifact，不运行 packet/API/victim/Retriever/formal。
- [ ] Enron fresh-audit preparation 不再对同一 reserve 重跑；该 shortfall 作为当前 revision 的失败证据。

当前唯一下一步：保留 Enron shortfall，等待用户决定是否运行 PubMed preparation；三数据集未全部通过前禁止 `build-packets`。

### 2026-08-20：版本化 Enron 1000-source reserve 扩展 policy 已冻结

- [x] 保留旧 frozen-r2 `250/250 -> 29 eligible` shortfall、authorization、source-results 与 freeze；不覆盖、不续跑同一 reserve、不降低 `100` selected-source 目标。
- [x] 新增 fresh-audit preparation r2 配置与独立 runner：新 reserve group 为 EDGAR=`250`、Enron=`1000`、PubMed=`250`，继续绑定 Fact Layer selection r2 与三套 passed development manifest。
- [x] 冻结 execution reservation revision=`f004bc75...f4934b`、policy identity=`20b09721...dcc72`、policy manifest SHA-256=`71927082...170a0`；旧 r1-fix2 freeze 只读验证仍 passed。
- [x] 新 runner 支持显式 reserve-registration authorization、identity-only registrar、append-only ledger/hash-chain、batch resume/fail-closed、reservation validator、preparation freeze、逐数据集 preparation 与 packet gate。
- [x] 新旧 preparation 定向测试合计 `14/14 passed`，包括隔离临时 ledger 的 batch hash-chain/预算/anchor/幂等恢复；AST 与 diff check 通过，未安装 `ruff` 或新依赖。
- [ ] 新 reserve-registration authorization 尚未生成；新 reserve group、preparation freeze、dataset preparation、blind packet 和 human audit 均未启动，ledger tip 未变化，external calls=`0`。

当前唯一下一步：用户明确授权后自行执行 r2 runner 的 `prepare-reservation-authorization` 与 `register-reserve-group` 长命令；成功后执行只读 `validate-reserve-group`，再单独决定是否 `freeze-preparation`。API/victim/Retriever、付费调用和 formal experiment 继续 blocked。

### 2026-08-20：expanded reserve registration passed

- [x] 用户授权并运行 `r2-enron-reserve-1000` reservation registration；authorization=`d4abd2b9...f3f2dc`，仅允许 identity-only hash registrar 与 append-only ledger registration。
- [x] 新 group 已注册并验证：EDGAR=`250`、Enron=`1000`、PubMed=`250`，ledger tip 从旧 `3c912fd1...aa8e1` 前进至 `3dce5019...0912`，reservation validation 通过。
- [x] 注册只持久化 source identity/hash-chain artifact，未持久化 source content 或 selector-derived feature；未启动 dataset preparation、blind packet、human audit、API/victim/Retriever 或 formal。
- [ ] preparation freeze 尚未生成；三数据集 dataset preparation 仍 blocked。

当前唯一下一步：用户自行运行 `scripts\44_prepare_v23_fresh_audit_expanded.py freeze-preparation`，随后运行 `validate-freeze`；通过后再分别授权 dataset preparation。

### 2026-08-20：expanded preparation freeze passed

- [x] `freeze-preparation` 幂等返回 freeze identity=`4b90c510...b5b19`；`validate-freeze` 通过，freeze manifest SHA-256=`f51640c9...14c6`。
- [x] `status` 确认 policy freeze、reservation group、preparation freeze 全部 `passed`，execution reservation revision=`f004bc75...f4934b`，当前状态=`policy_frozen_downstream_blocked`。
- [x] freeze 绑定固定 selection r2 与新原子 reserve group EDGAR=`250`、Enron=`1000`、PubMed=`250`；selected target 保持每数据集 `100` source / `300` pair。
- [x] 旧 EDGAR passed 与 Enron `29/250` shortfall 保持旧 revision 历史证据，不跨组复用、不覆盖；新 revision 需对三个 dataset 分别授权 preparation。
- [x] freeze 与只读验证未读取 source content，未启动 dataset preparation/packet/human audit/formal，external calls=`0`；API/victim/Retriever/付费调用仍未授权。
- [ ] expanded EDGAR/Enron/PubMed dataset preparation 尚未开始；三者全部通过前禁止 `build-packets`。

当前唯一下一步：等待用户单独授权 expanded revision 的 EDGAR dataset preparation；授权后才生成 EDGAR preparation authorization 并把长命令交由用户本人执行。其他 dataset、blind packet、human audit、API/victim/Retriever、付费调用和 formal experiment 继续 blocked。

### 2026-08-21：expanded EDGAR preparation authorization passed

- [x] 生成并验证 expanded revision EDGAR-only `dataset_preparation` authorization=`1d507ecf...327cb`。
- [x] 绑定 freeze identity=`4b90c510...b5b19`、execution reservation revision=`f004bc75...f4934b`，预算=`250` source reads；scope 不包含 API/victim/Retriever/付费调用、membership、AUC、packet、human audit 或 formal。
- [x] 授权阶段未读取 reserve source content，未执行 `prepare-dataset`，未复用旧 EDGAR dataset preparation，external calls=`0`。
- [ ] expanded EDGAR dataset preparation 尚未执行；Enron/PubMed 仍未授权，三数据集全部通过前禁止 `build-packets`。

当前唯一下一步：用户本人运行 authorization 绑定的 EDGAR `prepare-dataset` 长命令；完成并验证 dataset manifest 后，才决定是否分别授权 Enron/PubMed。

### 2026-08-21：expanded EDGAR dataset preparation passed

- [x] expanded EDGAR preparation 完成：`106` evaluated source，`100` eligible，`100` selected source，`300` selected pair。
- [x] dataset manifest SHA-256=`8106c421...e004`，dataset identity=`39beeeee...10aa`，source-results identity=`36e0b218...f829`，`status=passed`，external calls=`0`。
- [x] 结果绑定 preparation freeze=`4b90c510...b5b19` 与 expanded reserve snapshot/plan；不复用旧 EDGAR dataset artifact，旧 revision 继续保留。
- [x] 未启动 packet、human audit、formal、API/victim/Retriever 或付费调用；未读取 membership、victim/LLM-only response、Retriever 输出或 AUC。
- [ ] expanded Enron/PubMed dataset preparation 尚未执行；三数据集全部通过前禁止 `build-packets`。

当前唯一下一步：等待用户单独授权 expanded revision 的 Enron dataset preparation；完成并验证后再决定 PubMed。

### 2026-08-21：expanded Enron preparation authorization passed

- [x] 生成并验证 expanded revision Enron-only `dataset_preparation` authorization=`8280df6a...e0232`。
- [x] 绑定 freeze identity=`4b90c510...b5b19`、execution reservation revision=`f004bc75...f4934b`，预算=`1000` source reads；scope 不包含 API/victim/Retriever/付费调用、membership、AUC、packet、human audit 或 formal。
- [x] 授权阶段未读取 Enron reserve source content，不复用旧 `29/250` shortfall 或旧 preparation，external calls=`0`。
- [ ] expanded Enron dataset preparation 尚未执行；PubMed 尚未授权，三数据集全部通过前禁止 `build-packets`。

当前唯一下一步：用户本人运行 authorization 绑定的 Enron `prepare-dataset` 长命令；完成并验证 dataset manifest 后，才决定是否授权 PubMed。

### 2026-08-21：expanded Enron dataset preparation passed

- [x] expanded Enron preparation 完成：`665` evaluated source，`100` eligible，`100` selected source，`300` selected pair。
- [x] dataset manifest SHA-256=`597cb9f9...f920`，dataset identity=`cdd27cfb...dbb5`，source-results identity=`3b0b0337...d429`，`status=passed`，external calls=`0`。
- [x] 结果绑定 preparation freeze=`4b90c510...b5b19` 与 expanded Enron 1000-source reserve；旧 `29/250` shortfall 继续保留，不覆盖、不改写、不跨 revision 复用。
- [x] 未启动 packet、human audit、formal、API/victim/Retriever 或付费调用；未读取 membership、victim/LLM-only response、Retriever 输出或 AUC。
- [ ] expanded PubMed dataset preparation 尚未执行；三数据集全部通过前禁止 `build-packets`。

当前唯一下一步：等待用户单独授权 expanded revision 的 PubMed dataset preparation；完成并验证后再单独决定是否授权 blind packet preparation。

### 2026-08-21：expanded PubMed preparation authorization passed

- [x] 生成并验证 expanded revision PubMed-only `dataset_preparation` authorization=`52127310...b496c2`。
- [x] 绑定 freeze identity=`4b90c510...b5b19`、execution reservation revision=`f004bc75...f4934b`，预算=`250` source reads；scope 不包含 API/victim/Retriever/付费调用、membership、AUC、packet、human audit 或 formal。
- [x] 授权阶段未读取 PubMed reserve source content，不复用旧 PubMed preparation，external calls=`0`。
- [ ] expanded PubMed dataset preparation 尚未执行；三数据集全部通过前禁止 `build-packets`。

当前唯一下一步：用户本人运行 authorization 绑定的 PubMed `prepare-dataset` 长命令；完成并验证 dataset manifest 后，才可单独决定是否授权 blind packet preparation。

### 2026-08-21：expanded 三数据集 dataset preparation 全部 passed

- [x] expanded PubMed preparation 完成：`107` evaluated source，`100` eligible，`100` selected source，`300` selected pair。
- [x] PubMed manifest SHA-256=`b97a3063...65db`，dataset identity=`1fb181e1...dd35`，source-results identity=`49312448...6c24`，`status=passed`，external calls=`0`。
- [x] 三数据集在同一 expanded freeze=`4b90c510...b5b19` 下全部通过：EDGAR `106→100→300`、Enron `665→100→300`、PubMed `107→100→300`，合计 `900` pair。
- [x] 未复用或覆盖旧 preparation/shortfall artifact；未启动 packet、human audit、formal、API/victim/Retriever 或付费调用；未读取 membership、victim/LLM-only response、Retriever 输出或 AUC。
- [ ] `build-packets` 尚未执行；packet preparation 需要独立 authorization，授权前保持 blocked。

当前唯一下一步：等待用户单独授权 expanded frozen-r2 的 `packet_preparation`，随后才生成 packet authorization 并由用户本人执行长命令。

### 2026-08-24：expanded packet preparation authorization passed

- [x] 生成并验证 expanded frozen-r2 三数据集 `packet_preparation` authorization=`0f646578...d491`。
- [x] 绑定 freeze identity=`4b90c510...b5b19`、execution reservation revision=`f004bc75...f4934b`；`dataset=null` 表示三套 passed dataset manifest，`budget_maximum_source_reads=0`。
- [x] authorization 不包含 API/victim/Retriever/付费调用、membership、AUC、human audit 或 formal；授权阶段未执行 packet build，external calls=`0`。
- [ ] `build-packets` 尚未执行；packet manifest、blind packet 与 human audit 仍未生成/启动。

当前唯一下一步：用户本人运行 authorization 绑定的 `build-packets` 长命令；完成并验证 packet artifact 后，另行决定 human audit 授权。

### 2026-08-24：兼容 envelope 已冻结（不重新冻结科学 preparation）

- [x] 保留原 frozen-r2 policy/preparation identity；未创建 successor freeze，未重跑三套 dataset preparation，未修改或覆盖历史 artifact。
- [x] 新增 `configs/restoration_first_v23_fresh_audit_compatibility_r1.json`，将 packet adapter 的实现漂移从科学 freeze identity 中分离；兼容 identity=`e40222d9bf30631353677039ded6b5e425439eba3fd71a6df24651fdf3d18ac2`。
- [x] 兼容白名单限定为 packet builder 及其 r2 wrapper；selection/fact/model/reserve/source identity 仍由原 freeze 与受保护 surface fail-closed 校验。
- [x] 修复 legacy packet builder 对 freeze 摘要/完整 manifest 的接口兼容问题；仅完成 AST、freeze、policy 与 diff-check 验证，未执行 `build-packets`，`external_calls_performed=0`。
- [ ] `build-packets` 仍待用户使用既有 packet authorization 自行运行；human audit、API/victim/Retriever、付费调用与 formal experiment继续 blocked。

当前唯一下一步：用户本人重新执行既有 packet `build-packets` 长命令；通过后再单独决定 human audit 授权。

### 2026-08-24：blind packet preparation passed

- [x] `build-packets` 使用既有 packet authorization 通过，`packet_row_count=900`，authorization id=`0f646578e6d2089303288cd94afe892ddd917cb51b628dc118c076b92b4ad491`。
- [x] packet manifest SHA-256=`bbe1479a6e679e052a7e1b6312afdcca72ee803806d61a1d129ada68f363e587`；frozen-r2 scientific freeze identity 保持不变。
- [x] `external_calls_performed=0`；未启动 human audit、API/victim/Retriever、付费调用或 formal experiment。
- [x] 最终 compatibility envelope identity=`388a8a99b704422dceed3254aa672dda2a4d1fe8397ba76ee4c0bbbee64d68fc`，仅覆盖 packet adapter，未放宽 selection/fact/model/reserve/source identity 约束。
- [ ] human blind audit 尚未授权或启动。

当前唯一下一步：等待用户明确授权 human blind audit；授权前保持 packet 解盲、API/victim/Retriever 与 formal experiment blocked。

### 2026-08-24：AI-only blind-packet structural audit 完成（superseding）

- [x] AI-only audit authorization=`aed7737ca2c698f9c289b19d99f50ce0810cabe2ddf77e760d355d15340a6aab` 已验证；scope 明确 `human_audit_allowed=false`、private key/membership/victim/Retriever/API/formal 均为 false。
- [x] frozen-r2 blind packet `900` 行只读 structural audit 完成：`875 pass / 25 uncertain / 0 fail`；uncertain 原因均为 `not_exact_single_slot_replacement`。
- [x] 独立 diagnostic-only artifact 已写入 frozen-r2 audit root 的 `ai_audit/`；audit identity=`467c29448144182f3907462c5eeddeaeee87ce5eced8d98cb9f1497556338b67`，`external_calls_performed=0`，未冒充人工标注。
- [x] AI audit 实现修复并通过定向 unittest、AST 与 CLI 验证；修复仅涉及 legacy packet schema 常量兼容和移除硬编码 packet manifest hash，不改变科学 freeze 或历史 artifact。

当前唯一下一步：保持 AI audit 为 diagnostic-only；等待用户另行授权前，不执行 human audit、packet 解盲、API/victim/Retriever、付费调用或 formal experiment。

### 2026-08-24：AI 结果封存口径锁定

- [x] 将 AI-only audit 明确封存为 `diagnostic evidence`；不作为 canonical formal release、人工盲审替代或 formal gate 通过证据。
- [x] 保留 audit manifest、labels、`875 pass / 25 uncertain / 0 fail` 与全部 identity/hash；禁止重跑凑数、静默删除 uncertain、消费 fresh reserve 或据此调参。

当前唯一下一步：保持 diagnostic evidence 封存；等待新的明确授权前，不启动 human audit、packet 解盲、API/victim/Retriever、付费调用或 formal experiment。

### 2026-08-24：API 登录切换交接更新

- [x] 新建 `研究记录/API登录切换_工作交接_20260824.md`，记录 frozen-r2、packet、AI-only audit、脏工作树保护和新账号接管顺序。
- [x] AI audit 保持 `diagnostic evidence`，不进入 canonical formal release；preparation freeze、packet、labels 和历史 artifact 均不可覆盖。
- [ ] 下一阶段仅待用户明确授权实现并冻结 v23 formal runtime；允许本地离线实现/测试/identity freeze，不包含 formal test、GPU、API、victim、Retriever、付费调用或任何受限响应读取。

当前唯一下一步：新账号先只读核验交接文档、两份项目总表和当前 identities；formal runtime 实现/冻结授权前保持 downstream blocked。

### 2026-08-24：v23 formal runtime r1 implementation/freeze passed

- [x] 完整阅读新交接和两份项目总表，并只读核验 frozen-r2 preparation、三套 dataset manifests、packet、AI authorization/manifest/labels 的 identity/hash/count；private key、membership、victim/LLM-only response、Retriever output 与 AUC 均未读取。
- [x] 新增 `configs/restoration_first_v23_formal_runtime_r1.yaml`、`src/prepare/restoration_first_v23_formal_runtime.py`、`scripts/46_freeze_v23_formal_runtime.py` 与 `tests/test_restoration_first_v23_formal_runtime.py`；旧 lightweight/frozen-r2 代码和全部历史 artifact 保持原样。
- [x] runtime guards 覆盖：exact file/hash closure、AI diagnostic 非 formal gate、递归 forbidden input、`2250 -> 1000/1000/250` deterministic source-exclusive split、cross-dataset hash isolation、main-index member-only / shadow-index reserve-only、stage-scoped authorization 与 budget-before-operation exhaustion。
- [x] formal runtime identity=`e8cc004b...6a72c`，runtime bundle=`4434cf5c...e369`，freeze manifest SHA-256=`c3ef3159...fe14`，runtime file count=`30`；`validate-freeze`、`status` 和重复 `freeze` 幂等验证均通过。
- [x] 新增定向 unittest `11/11 OK`，AST 与 CLI help 通过；v23 扩大回归 `102` 项为 `62 passed / 39 skipped / 1 failed`，唯一失败是既有测试对当前已 passed reservation/preparation 的过期 `not_started` 断言，未修改历史测试。compileall 的既有 `__pycache__` 权限失败按规则改由内存 AST 覆盖。
- [x] 首次 `freeze` 的 manifest 构造成功但目标 `xb` 创建被 Windows 权限拒绝；确认无 partial 后，以同一 builder canonical JSON 通过 `apply_patch` 新增 freeze，再用独立 validator 与重复 `freeze` 验证，不改权限、不清理或覆盖。
- [x] 本阶段仅实现/冻结 runtime；`formal_test_started=false`，GPU/API/victim/Retriever/付费调用、membership、response、AUC、fresh reserve、packet rebuild、commit/push 均为 `0/false`。
- [ ] canonical independent human blind audit 尚未完成；AI-only `875 pass / 25 uncertain / 0 fail` 仍只作 diagnostic evidence，不能满足 formal gate。formal scan 及全部下游继续 blocked。

当前唯一下一步：停止并等待用户单独授权 canonical independent human blind audit 或其他下一项工作；human gate 与后续 formal test 未分别明确授权前，不运行任何 formal/GPU/API/victim/Retriever/付费或受限数据流程。

### 2026-08-24：runtime-r1 AI 审计 + 项目负责人人工核验门禁 passed（superseding）

- [x] 按用户明确指令取消 runtime-r1 的独立人工盲审硬门禁，不新建 design/runtime revision；为保持 frozen-r2 design hash、preparation、packet 与 AI artifact 可验证，没有修改 design-r6 或任何 frozen-r2 artifact。
- [x] runtime-r1 原位门禁改为：绑定 AI-only audit + 项目负责人人工核验。组合门禁 passed；AI artifact 仍是 diagnostic-only，AI 单独不作为 formal gate。
- [x] 人工核验口径冻结为非独立、非盲审、无单独标签文件；禁止声称 independent blind audit、双人一致性或 Cohen's kappa。
- [x] 同名 freeze 原位重算：runtime identity=`2f45761b...ad03d3`，bundle=`db051de1...3eef7`，freeze SHA-256=`b4545bc8...e0b`，30-file closure；原 identity=`e8cc004b...6a72c` 由本条 supersede。
- [x] 定向 unittest `11/11 OK`、AST、`validate-freeze`、`status`、重复 `freeze` 全部通过；组合门禁 satisfied，formal test 仍未授权/未启动。
- [x] 首次终端 JSON 传递因非 ASCII 路径编码导致 identity drift，validator 正确拒绝；使用 ASCII-escaped canonical JSON 重算后通过，未掩盖失败。
- [x] GPU/API/victim/Retriever/付费调用、membership、response、AUC、fresh reserve、packet rebuild、commit/push 均为 `0/false`。

当前唯一下一步：等待用户单独授权 formal test 的首个 stage/dataset/budget；授权前不启动 formal scan、GPU、API、victim、Retriever、membership/split、response 或 AUC。

### 2026-08-25：EDGAR formal source scan passed（正式实验首阶段）

- [x] 首阶段授权冻结为 `formal_source_scan / edgar`：authorization=`737629ea...dea8`，source-read budget=`3710`，target=`2250` eligible source；仅允许本地 CUDA selector，API/victim/Retriever/external/membership/split/response/AUC 均为 false。
- [x] 最终 formal runtime identity=`6c102137...372f8`，bundle=`7cd2bd45...69271`，freeze SHA-256=`3899e059...5e0b`，32-file closure；`validate-freeze` 与 authorization validator passed。
- [x] EDGAR 扫描结果：`2327 viewed -> 2250 selected source -> 6750 selected pair`，每 source 恰好 3 pair，达到目标即停；manifest SHA-256=`96d2bff9...62c28`，selected sources SHA-256=`fcce9e7e...495f`，selected pairs SHA-256=`0e1382c6...4633`。
- [x] budget charges=`2327`；ledger tip=`80d02112...9b56`，final anchor SHA-256=`05e882e4...96e4`，manifest/tip/anchor 精确一致；formal-source-scan validator passed，live status=`formal_source_scan_edgar_passed_awaiting_next_authorization`。
- [x] 两次异常终端退出均只产生 stale lock；核实锁 PID 不存在后移除精确临时锁并从 checkpoint 续跑，正式预算、ledger、anchor、source result 与历史 artifact 全部保留。
- [x] `formal_test_started=true`、`gpu_used=true`；API/victim/Retriever/external calls=`0`。Enron、PubMed、split、membership、response 与 AUC 均未启动。
- [ ] Enron formal source scan 未授权；PubMed、source-exclusive split 与全部下游继续 blocked。

当前唯一下一步：停止并等待用户单独授权 Enron `formal_source_scan` 的 dataset/budget/GPU 边界；授权前不启动任何下一正式执行单元。

### 2026-08-25：Enron/PubMed formal scan successor frozen，Enron authorization passed

- [x] 用户授权按 `Enron -> PubMed` 完成剩余 formal source scan；仅本地 CUDA selector，split/membership/API/victim/Retriever/response/AUC/external 均未授权。
- [x] 新建最小 r2 successor，hash-bind/carry forward r1 EDGAR passed artifact；r1 freeze/代码/正式 artifact 保持不变，Fact Layer r1、selection r2、模型锁、阈值、排序与目标数不变。
- [x] r2 identity=`5ce4e736...095bd`，bundle=`921beffe...dda4f`，freeze SHA-256=`a26f114a...01ae3`，41-file closure；r2 validator 与原 r1 validator 均 passed。
- [x] Enron authorization=`fb0f6f94...52a89` passed，budget=`32750`、target=`2250`、prior tip=`80d02112...9b56`；GPU=true，API/victim/Retriever/external=false。
- [x] PubMed budget 冻结为 `46450`；authorization 必须等 Enron passed/final tip 后由串行 runner 生成，禁止提前生成。
- [x] r2 unittest `8/8`、r1 unittest `14/14`、AST/CLI/freeze/auth/diff-check passed；扩大回归 `72 passed / 39 skipped / 1` 个既有过期状态断言失败；`ruff` 未安装且未安装新依赖。
- [x] 尚未读取 Enron/PubMed source、未启动 GPU、未修改 ledger；所有外部调用为 `0`。
- [ ] Enron/PubMed formal source scan 尚未执行；source-exclusive split 与全部下游继续 blocked。

当前唯一下一步：用户本人运行 `run-remaining-formal-source-scans` 长命令；Enron 与 PubMed 均 passed 后停止，等待 split 的独立授权。

### 2026-08-27：Luna query transport retry policy 更新（待 successor freeze）

- [x] 已按用户要求为 Luna query-generation 增加 `retry_until_success`：连接超时、网络抖动与既有可重试 HTTP 状态持续指数退避重连，直到拿到可用响应。
- [x] 仅 Luna profile 默认打开；victim/RAG 与普通 sibling 保持原有有限重试边界。语义/schema/NLI/多样性失败仍按原 correction retry 与 fail-closed 处理。
- [x] 离线重试测试、query/LLM 相关回归、内存 AST 和 `git diff --check` 已通过；本轮 API/external calls=`0`。
- [ ] v23 旧 runtime freeze 仍声明 query 每条一次 transport attempt；正式 Luna stage 前需用 successor identity/freeze 显式纳入持续 transport 重连规则，不能原位伪装为旧 freeze。

当前 formal source scan 的执行顺序和授权边界不变；Luna query stage 仍须 successor freeze 与单独授权。

### 2026-08-27：v23 Luna query-generation runner（代码已接入，未执行）

- [x] 已实现独立 v23 query runner 与 CLI：`src/prepare/restoration_first_v23_query_generation.py`、`scripts/48_run_v23_luna_query_generation.py`。
- [x] 已覆盖 release hash/status 校验、Reserve query 排除、frozen true/counterfactual claim 的 Q+/Q- 映射、严格 query validator、失败 cell/attempt 审计和 query plan manifest。
- [x] 已完成离线定向回归：query runner 4 项、既有 query/LLM/v20 相关回归合计 `57/57 OK`；未连接 API、未读取 victim/Retriever/response/AUC。
- [ ] r2 formal runtime freeze 不包含本次 query runner 与持续 transport retry 改动；正式 Luna 前仍需 successor query/runtime identity/freeze 及 `luna_query_generation` 每 dataset 单独授权。

当前唯一下一步：完成 Enron/PubMed formal source scan 并通过后，再进行 split → Reserve shadow gate → release finalize；只有 release passed 且 query successor freeze/auth passed，才可进入 Luna query-generation。runner 代码实现本身不启动任何外部调用。

### 2026-08-31：v23 r2 三数据集 formal source scan 齐备

- [x] r2 freeze 复验通过：identity=`5ce4e736...095bd`，bundle=`921beffe...dda4f`，freeze SHA-256=`a26f114a...01ae3`；r1 EDGAR passed artifact 保持绑定并 carry forward。
- [x] Enron authorization=`fb0f6f94...52a89` 完成：`15371 viewed -> 2250 selected source -> 6750 selected pair`；manifest=`cf41fa15...065`，selected sources=`05de81c7...bda4`，selected pairs=`7d7321e7...fb22`，final ledger tip=`02e9edd7...e17c`，anchor=`b8ce765c...f983`。
- [x] PubMed authorization=`64fe2dbc...2452` 完成：`2394 viewed -> 2250 selected source -> 6750 selected pair`；manifest=`9a490931...e9c3e`，selected sources=`bcacace0...7e09`，selected pairs=`b5940227...bbb9`，final ledger tip=`dfbb9254...4754`，anchor=`9f345df1...aff1`。
- [x] freeze、两份 authorization 与两套 formal-source-scan validator 全部 `passed`；live status=`formal_source_scans_all_datasets_passed_awaiting_split_authorization`。
- [x] EDGAR/Enron/PubMed 各选出 `2250` source、各生成 `6750` pair；本阶段 API/victim/Retriever/external calls=`0`，未读取 membership、response、Retriever output 或 AUC。
- [ ] source-exclusive split 尚未授权或启动；Reserve shadow、release finalize、正式 Luna query-generation 与后续 victim/Retriever 阶段继续 blocked。

当前唯一下一步：停止并等待用户单独授权 v23 source-exclusive split；在此之前不运行任何后续正式执行单元。

### 2026-08-31：v23 source-exclusive split 已冻结并通过

- [x] 已获用户单独授权，仅运行 source-exclusive split；保持 r2 三数据集 formal scan passed 输入及其 manifest/source/tip/anchor hash，不读取 source content、membership、response、Retriever 或 AUC。
- [x] 新增 successor split freeze（保留旧 r1 freeze，不覆盖）：`configs/restoration_first_v23_split_runtime_r1_patch1.freeze.json`；identity=`ac8ca724...a4ed`，bundle=`6b22303e...b984`，freeze SHA-256=`c79a38a8...c7bf`，28-file closure。首次实现缺口（freeze 摘要缺少 `code_commit`）已以新身份修复并重新验证。
- [x] 已生成并验证三份 dataset-scoped `source_exclusive_split` authorization：EDGAR=`68fd42d4...12472`、Enron=`303c390f...06855`、PubMed=`481590ab...7806d1`；预算均为 0，GPU/API/victim/Retriever/external 全部关闭。
- [x] 固定 seed=42、dataset order=`edgar -> enron -> pubmed` 的三套 split 均 passed：每 dataset `2250` source，`KB_Member=1000`、`True_Non_Member=1000`、`Reserve=250`；三套 manifest/rows hash 已写入 notes，跨 dataset source-exclusive 零重叠验证通过。
- [x] `5/5` 定向 unittest、`validate-freeze`、授权 validator、split runner/validator、status 与 `git diff --check` 通过；live status=`source_exclusive_split_all_datasets_passed_awaiting_shadow_authorization`，所有 API/victim/Retriever/external 计数为 0，未使用 GPU。
- [ ] Reserve shadow gate、release finalize、Luna query/API、victim、Retriever、response 与 AUC 尚未授权或启动。

当前唯一下一步：停止并等待用户单独授权 `Reserve-only shadow gate`；授权前不得创建 shadow index 或启动任何 downstream formal stage。

### 2026-08-31：Reserve-only shadow gate runtime implementation/freeze 完成

- [x] 已实现并测试 `src/prepare/restoration_first_v23_shadow_runtime.py` 与 `scripts/50_run_v23_reserve_shadow.py`；新增 `configs/restoration_first_v23_shadow_runtime_r1.yaml` 和 `tests/test_restoration_first_v23_shadow_runtime.py`。
- [x] 已生成/验证 `configs/restoration_first_v23_shadow_runtime_r1.freeze.json`：shadow identity=`959f3591...bebf82`，bundle=`df3bf7cc...faf4c5e8`，freeze SHA-256=`4157289491...74b82fb`，20-file closure；重复 freeze 幂等通过。
- [x] contract/gates：Reserve-only 250 source；每 source 3 pair、Q+/Q- 6 query；每 dataset/backend budget 1500、top-k 5；dense/BM25/hybrid 分离；shadow index 仅 `artifacts/v23/shadow_indexes/`；主 `indexes/`、membership、victim、API、external calls 全部 fail-closed。
- [x] 离线定向 unittest=`9/9 OK`，内存 AST、CLI help、freeze validator、status、Unicode path existence、`git diff --check` 均通过；runtime 不读取 source content 以外的受限输入，不产生 Retriever/API/victim 调用。
- [ ] 尚未运行 `prepare-shadow-authorizations`、`run-shadow-gate` 或 `validate-shadow-gate`；未构建 shadow index，未启动 GPU/Retriever 长任务。

当前唯一下一步：用户单独授权实际 Retriever 后，由用户逐 dataset/backend 执行 Reserve-only shadow gate，并在每个 cell 完成后独立验证；9 个 cell 全部 passed 前不得进入 release finalize 或下游 API/victim/formal 主 index。

### 2026-08-31：shadow runtime r1 -> r2 successor 修复授权准备错误

- [x] r1 `validate-freeze` passed，但 `prepare-shadow-authorizations` 暴露 split-manifest helper API 错误；失败发生在 authorization 落盘前，未产生 partial authorization、budget、shadow index 或 Retriever/GPU 调用。
- [x] 新增 `configs/restoration_first_v23_shadow_runtime_r2.yaml`、`configs/restoration_first_v23_shadow_runtime_r2.freeze.json` 与 `src/prepare/restoration_first_v23_shadow_runtime_r2.py`；`scripts/50_run_v23_reserve_shadow.py` 已切换到 r2 successor，旧 r1 freeze 保留且不覆盖。
- [x] r2 freeze validator passed：identity=`153515b4...953c9`，bundle=`ae9f781e...036acf`，freeze SHA-256=`8f67dada...c1fc8a`，22-file closure。
- [x] 修复版 `prepare-shadow-authorizations` passed，9 个 dataset/backend authorization 已生成并验证；每 cell `budget_limit=1500`，API/victim/external=false，shadow budget journal=`0`。
- [ ] 9 个 `validate-shadow-authorization`、9 个 `run-shadow-gate` 与 9 个 `validate-shadow-gate` 尚未执行；shadow index、retrieval rows 与 gate manifest 尚未生成。

当前唯一下一步：用户按 dataset/backend 顺序逐 cell 执行已生成 authorization 绑定的长时间 Retriever 命令；每个 cell 完成后立即验证，全部 passed 后才可进入 release finalize。

### 2026-08-31：authorization 批量验证的 PowerShell 编码问题已澄清

- [x] 默认 `Get-Content` 在 Windows PowerShell 中未按 UTF-8 解码授权 JSON，导致 `ConvertFrom-Json` 对包含中文授权记录的文件报告 syntax error；未修改或删除任何授权文件。
- [x] Python UTF-8 读取并公开 validator 复核 r2 的 9 个 authorization，`validated_count=9`，全部 `passed`。
- [ ] 实际 `run-shadow-gate` 仍未启动；shadow index、retrieval rows、budget journal 和 gate manifest 仍待用户逐 cell 长任务产生。

当前唯一下一步：PowerShell 批量验证使用 `Get-Content -Encoding UTF8 -Raw`，然后按 `edgar -> enron -> pubmed`、`dense -> bm25 -> hybrid` 顺序逐 cell 运行和验证。

### 2026-08-31：Reserve-only shadow gate r3 successor（当前）

- [x] r2 `edgar/dense` 运行在 split rows helper API 处 fail-closed；未到 shadow index、Reserve source、Retriever/GPU 或 budget journal。空 partial 目录和 r2 authorization/freeze 保留为 superseded/failed evidence。
- [x] r3 wrapper/config 已接入 CLI，修复 `_assert_exact_fields` 与 `validate_split_rows` 的实际模块路径；不改变 v23 shadow scientific contract 或历史 artifact。
- [x] r3 freeze validator passed：identity=`b74ae66698f99ad31daee59fed8b72f899e8be365760fc2d1def0f208ba92992`，bundle=`38604d9664ce8e6625a7967bd37f875b6c84073e6dc747fb32ac485ca072e98a`，freeze SHA-256=`50d103fa895f95860cec9ba84aaa1d5180a2a6bb4d52799f4b42b86f4eda3771`；定向 unittest=`9/9 OK`。
- [ ] r3 authorization 尚未生成；r2 的 9 个 authorization 不得继续使用。

当前唯一下一步：执行 `prepare-shadow-authorizations` 生成 r3 9 个授权，使用 UTF-8 读取并逐个 `validate-shadow-authorization`；授权全部通过后由用户按 `edgar -> enron -> pubmed`、`dense -> bm25 -> hybrid` 顺序逐 cell 运行并验证。期间 API/victim/external calls 保持禁止，未完成全部 9 cell 前不得 release finalize。

### 2026-08-31：r3 authorization 已生成并验证（当前）

- [x] r3 9 个 dataset/backend authorization 已生成，均绑定 identity=`b74ae66698f99ad31daee59fed8b72f899e8be365760fc2d1def0f208ba92992`、budget=`1500`、Retriever/GPU allowed、API/victim/external=false。
- [x] Python UTF-8 独立 validator `9/9 passed`，授权记录精确匹配用户文本；`status` 显示 9 个 cell authorized、未完成，所有调用计数为 0。
- [ ] 尚未执行任何 `run-shadow-gate` 或 `validate-shadow-gate`；shadow index、retrieval rows、budget journal、gate manifest 均未生成。

当前唯一下一步：主人运行首个 `edgar/dense` 长命令并在返回后立即验证；通过后按固定 dataset/backend 顺序逐 cell 串行执行。长任务中断或报错时先运行 `status`，保留 partial artifact，不使用 r2 authorization 或盲目重跑。

### 2026-08-31：r3 `edgar/dense` query-plan 前置失败（当前）

- [x] r3 freeze/auth 校验通过，但运行入口向 `_run_one_shadow_cell` 传入 freeze 摘要，导致 `_load_pairs` 缺少 `pair_bindings`；失败在 Retriever/GPU 前，未生成 shadow index、retrieval rows 或 budget journal。
- [x] r4 草稿已撤回；没有新 protocol、freeze 或 authorization。进程内兼容探针确认完整 freeze manifest 可读取，EDGAR pair count=`6750`。
- [ ] 尚未完成永久 CLI 修复；当前 r3 freeze 保持不变，不能直接修改 hashed runtime 文件。

当前唯一下一步：优先采用不新增文件的进程内兼容入口完成 diagnostic-only shadow gate；只有明确要求永久 CLI 修复时，才重新评估 pre-run re-freeze 与授权影响。

### 2026-08-31：EDGAR/dense 已通过（当前）

- [x] EDGAR/dense run 与独立 validate 均 `passed`；1500 logical calls、7500 retrieval rows，manifest/index/rows/query-plan hash 已记录。
- [x] status：EDGAR/dense `completed=true`；其余 8 个 cell `completed=false`；API/victim/external calls=`0`。
- [ ] 尚未运行 EDGAR/bm25、EDGAR/hybrid、Enron 三 backend、PubMed 三 backend。

当前唯一下一步：使用进程内完整-freeze 兼容入口运行 `edgar/bm25`，返回后立即验证；按 dataset/backend 固定顺序推进，失败先查 status，不盲目重跑。

### 2026-08-31：Reserve-only shadow gate 全部 9 个 cell passed

- [x] 完成并验证 `edgar/enron/pubmed × dense/bm25/hybrid` 全部 9 个 cell；每 cell `1500` logical Retriever calls、`7500` rows，合计 `13500` Retriever calls。
- [x] 全局 status=`reserve_shadow_gate_all_cells_passed`；r3 identity=`b74ae66698f99ad31daee59fed8b72f899e8be365760fc2d1def0f208ba92992`，bundle=`38604d9664ce8e6625a7967bd37f875b6c84073e6dc747fb32ac485ca072e98a`，freeze SHA-256=`50d103fa895f95860cec9ba84aaa1d5180a2a6bb4d52799f4b42b86f4eda3771`。
- [x] 9 个 gate manifest hash 已写入 notes；shadow index 仅位于 `artifacts/v23/shadow_indexes/`，主 index 未写入；API/victim/external=`0`，membership/source-content flags=`false`。
- [x] r1/r2 前置失败与 r3 兼容运行证据保留；未创建新的 successor、freeze 或 authorization，未改变 v23 scientific contract。
- [x] Reserve-only shadow gate 已完成；9 个 cell 均通过独立 validator。
- [ ] release finalize、Luna/API、victim、正式主 index、response、AUC 尚未授权或启动。

当前唯一下一步：停止并等待主人单独明确授权 release finalize。授权前不得执行任何 release 或下游外部/正式评估阶段；如需复核 shadow cell，继续使用已验证的进程内完整-freeze 兼容入口。

### 2026-08-31：v23 release finalize 已通过

- [x] 用户明确授权 v23 release finalize；只执行本地离线 artifact 聚合，不启动 Luna/API、victim、正式主 index、Retriever 或正式评估。
- [x] release protocol/runtime identity=`5ce4e736...095bd`，runtime bundle=`921beffe...dda4f`；release manifest=`artifacts/v23/release/5ce4e736aac3fd9127b33d89b9b3533d5155502d375ac44548f17142ad0095bd/release_manifest.json`。
- [x] release manifest SHA-256=`e998c602823a7e5bc2d695d04dc25f16da33fe603d38aa67ef436e720965333a`；rows SHA-256=`f370bf9bef5ab40591e3ac8828623eab64909378d560029c9a50cf1169c5ba77`；rows=`20250`，三 dataset、三组 source-exclusive split、每 source 三 pair。
- [x] `finalize-release`、`validate-release`、`status` 均 passed；release 新增 API/victim/Retriever/external calls=`0`，既有 shadow 累计 Retriever calls=`13500`，主 `indexes/` 未写入，membership/response/AUC 未读取。
- [ ] Luna query-generation、API/victim、正式主 index、response、AUC 与正式评估仍未启动。

当前唯一下一步：停止在 release finalize passed 边界，等待主人单独授权 query-generation successor freeze/auth；未获后续授权前不运行 Luna/API、victim、主 index、response 或 AUC。

### 2026-09-01：v23 query-generation successor freeze/auth 已完成

- [x] query successor freeze passed：identity=`691ce230...4753`，bundle=`86b19fa8...323fa`，freeze SHA-256=`3ada84d7...6684`，18-file closure；绑定 release manifest=`e998c602...333a`。
- [x] 冻结 Luna endpoint/model/version、Prompt 与 decoding/retry/rate-limit 参数；不包含 API key。每 dataset 固定 `6000` pair、`12000` Q+/Q- logical query cells，Reserve=`0`，transport retry 不改变科研 query budget。
- [x] 最终 authorization passed：EDGAR=`e863dc0f...4251`、Enron=`c211e654...f4f1`、PubMed=`13711364...4170`；每份 budget=`12000 logical_query_cells`，API/external=true，victim/Retriever/GPU=false。
- [x] preflight 发现并在首次 API 调用前修复 dataset 输出目录隔离；旧 identity=`430ac62a...3cbc9` 与旧授权保留为 superseded evidence，调用数为 0。最终输出路径为 `<query_contract_id>/<dataset>/`。
- [x] freeze/auth/input validators、定向 `9/9`、扩大回归 `23/23`、AST、diff-check 均通过；status=`query_runtime_frozen_all_datasets_authorized`，API/victim/Retriever/external calls=`0`。
- [ ] 三数据集正式 Luna query-generation 尚未运行；主 index、victim、Retriever、response、AUC 与评估未授权。

当前唯一下一步：主人串行运行 `edgar -> enron -> pubmed` 三个 query-generation 长任务，每个完成后检查产物再继续；本授权不包含 victim、主 index、Retriever 或评估。

### 2026-09-01：query-quality development canary 前置阻断（superseding）

- [x] 收到 development-only canary 明确授权：最多 `60` 次 Luna API 调用，只使用 development pilot pairs，不读 formal membership/victim/Retriever/response/AUC，不启动正式 query-generation。
- [x] 新增与正式 query freeze closure 隔离的 52 号 development canary；没有新增 config/freeze/authorization/ledger，没有修改当前 frozen Prompt、validator、48 号 runner 或正式 release。
- [x] 固定抽样为三数据集 × 五类实体 × 每类 2 pair × Q+/Q-=`60` cell；单次物理尝试、零 retry、checkpoint/resume 与 60-call 硬上限已由 mock 回归覆盖。
- [x] preview 在 API 前得到 `development_input_contract_failed`：样本 `12/60` cell 为 `relation_cue_missing`；全量 development 汇总为 `3774/12378` cell 不兼容，EDGAR=`1967/5814`、Enron=`372/888`、PubMed=`1435/5676`。
- [x] 根因确认是 Fact Layer r1 将 relation cue 改为 diagnostic-only，而 design-r6/query runtime 仍将其作为 query self-containment 硬门禁；selection r2 未补回。该冲突位于 Luna 调用之前，不能归因于模型输出质量。
- [x] 定向测试 `13/13 OK`；preview/API/victim/Retriever/external calls=`0`，未生成正式 query rows，现有 freeze/auth 未覆盖或删除。
- [ ] 禁止执行当前三条正式 48 号 `run` 命令；禁止重抽 canary 规避失败、跳过正式 pair、release 后删行或原地放宽 validator。

当前唯一下一步：等待主人单独授权 successor 科学协议修复。推荐从 development 恢复 selector 与 query self-containment 的一致门禁并重跑 canary；该变更影响 selector/source eligibility 或 Query construction，需从最早受影响阶段以新版本重跑，当前 v23 release/freeze/auth 保留为 blocked 历史证据。

### 2026-09-01：query-quality canary status 哈希稳定性修复

- [x] 修复 52 号 canary 的只读 `status` 路径：已有 summary 时不再调用会写盘的 preview 初始化，避免 `created_at` 导致 summary 哈希漂移。
- [x] 变更仅限 `src/prepare/restoration_first_v23_query_quality_canary.py` 与既有 query-generation 测试；不改变实验语义，不需要重跑 query canary、freeze/auth 或正式协议，也不创建 successor 版本。
- [x] 定向 unittest=`13/13 OK`、AST=`3/3 OK`、连续 status 哈希稳定；summary SHA-256=`14a0caf04655e5e5672c4ae246fa87519c774a21cb9be255077958f1c643a96e`。
- [ ] 当前唯一科研下一步不变：等待主人单独授权 successor 科学协议修复；在此之前禁止正式 48 号 Luna query-generation。

### 2026-09-01：query-quality canary successor probe 离线阶段完成

- [x] selection r3 恢复 frozen relation-cue gate；EDGAR/PubMed capacity passed，Enron 保留 `failed_capacity_shortfall`，未放宽门禁或修改旧 artifact。
- [x] development canary r3 + `subject_presence_r2` preview：`0/11352` input-contract failures，`30` pairs、`60` cells，`api_call_slots_consumed=0`；新增 probe 只处理自然问句倒装、冠词/尾标点 surface 变体，正式 validator 与正式 query runtime 未改。
- [x] 真实 canary 的首个失败 checkpoint 原样保留（`1` API call，`automatic_validation_failed`），不得重试；新的 r2 输出目录独立且尚未调用 API。
- [x] 定向 unittest=`23/23`（selection `7/7` + query-generation `16/16`），内存 AST 编译与 diff-check 通过。
- [x] 最新 r2 preview summary SHA-256=`f536d909...f55c6e`；只读 status 前后字节与 hash 稳定。
- [x] 新 r2 canary 第 1 次物理调用为 transport failure：`Remote end closed connection without response`，无 response/query 质量证据；旧 checkpoint=`automatic_validation_failed`、已消耗 `1/60`，禁止原地重试。
- [x] 独立 attempt2 的第 1 次物理调用收到 HTTP 404 `model_not_found`：远端账号组不支持冻结模型 `gpt-5.6-luna`；无 response/query 质量证据，attempt2=`automatic_validation_failed`、已消耗 `1/60`。不得继续用同一模型重试，也不得未经授权切换模型/endpoint。
- [x] 只读 `/v1/models` 诊断返回 HTTP 200 和 58 个模型 ID，其中包含 `gpt-5.6-luna`；故模型在服务目录存在，但当前 API key 所属账号组没有 completion entitlement。未产生 query response，不改变 canary 预算/身份。
- [x] 更换 key 后复核：新进程从 `.env` 加载的新 key 指纹与文件值一致，`/v1/models`=`200`，但 Luna 最小 completion 仍=`404 model_not_found`；key 有效但账号组仍未开通该模型 completion 权限。未切换模型/endpoint，未启动新 canary。
- [x] 主人用 OpenAI SDK 直接硬编码另一把 key 成功调用 `gpt-5.6-luna`，说明 endpoint/model 本身可用；此前 404 仅适用于项目进程实际加载的 `.env` key，不能外推为服务端无 Luna 权限。先对齐项目使用的 key，再做 smoke/canary；不记录或复用聊天中暴露的 secret。
- [x] 更新 `.env` 并清除 PowerShell 旧环境覆盖后，项目 client smoke=`passed`，provider model id=`gpt-5.6-luna`，内容=`OK`；该调用不属于 canary query，不写 query artifact。已提醒撤销聊天中暴露的旧 key。
- [x] 新授权 attempt3 已完成离线 preview：独立输出目录，`60` cells、`0/11352` 输入失败、API 调用=`0`，状态=`prepared_awaiting_execution`。
- [x] 新独立 attempt4 已完成离线 preview：目录=`artifacts/v23/development/query_quality_canary_r3_subject_presence_r2_attempt4/`，`60` cells、`0/11352` 输入失败、API 调用=`0`，状态=`prepared_awaiting_execution`；未复用 attempt1/2/3 checkpoint。
- [x] attempt3 第 1 个物理调用收到 provider HTTP 500 `get_channel_failed`（`auto` 分组无 gpt-5.6-luna 可用渠道），无 query response；状态=`automatic_validation_failed`、已消耗 `1/60`，禁止原地重试。该失败属于 provider 路由可用性，不是 validator 或 query 质量结论。
- [x] 环境/调用方式对照已通过：当前 `.env` 同 key/model 下，OpenAI SDK 与仓库 OpenAI-compatible client（使用 canary 的 `top_p/n/seed/max_tokens`）均返回 `gpt-5.6-luna`/`OK`。故 attempt3 500 是 provider 瞬时渠道故障，不是 env 或客户端封装错误；诊断调用不写 canary artifact。
- [ ] 尚未运行新的 API canary、正式 query-generation、victim、主 index、Retriever 或评估。

当前唯一下一步：等待主人明确授权一个使用全新输出目录的 development-only canary attempt；本次 authorization 已消耗 1 个 transport-failed call，不能默认再增加 60-call 配额。新 attempt 运行后先执行 `status`，再根据 `awaiting_quality_review` 或 `automatic_validation_failed` 决定是否继续。未通过 canary 前不得启动正式 48 号 query-generation。

### 2026-09-01：query-quality canary transport retry 修复（当前）

- [x] 修复 52 号 canary：同一 logical query cell 对可识别的 provider/network transport failure 最多额外重试 2 次；底层 client 仍保持 `max_retries=0`，避免隐藏重试和预算不透明。
- [x] 每次物理调用都写入 `canary_attempts.jsonl` 并带 `call_ordinal`、`retry_ordinal`；最终结果区分 logical cell 与 physical attempt，物理上限为 `180`，logical cell 仍固定 `60`。
- [x] 语义/schema/subject validator 失败、HTTP 404 和模型身份错误不重试；旧失败 attempt 不复用、不覆盖。
- [x] 定向 unittest=`17/17 OK`、AST 与 `git diff --check` 通过；未产生新的 API、victim、Retriever、response 或 AUC 调用。
- [ ] 尚未获得新 attempt 的 `180` 次物理 API 授权；当前仍禁止正式 48 号 query-generation。

当前唯一下一步：主人单独授权新的 development-only canary attempt（最多 `180` 次物理调用）后，使用全新输出目录运行；返回后先执行 `status`，再进行人工质量复核。

- [x] attempt5 preview/status passed；目录=`artifacts/v23/development/query_quality_canary_r3_subject_presence_r2_attempt5/`，API/victim/Retriever/external calls=`0`，正式 query-generation 仍未启动。

### 2026-09-01：query-quality canary transport retry policy superseded

- [x] transport/network failure 改为持续重试直到成功或用户手动终止；不再设置 `2` 次或 `180` 次的 canary transport/API 上限。60 个 logical query cells、Prompt、model、validator 与 development-only 边界不变。
- [x] attempt5 允许从已有纯 transport failure 结果追加恢复；旧 attempts/results 只追加不覆盖，语义失败不会被重试。
- [x] 定向 unittest=`18/18 OK`、AST 与 `git diff --check` 通过；attempt5 summary 已离线刷新为 `transport_failure_awaiting_resume`，未增加 API 调用。
- [ ] 尚未执行 attempt5 续跑；主人需确认持续重试的运行授权与手动停止边界。

当前唯一下一步：主人确认后，在 attempt5 同一输出目录运行续跑命令；网络故障将持续重试，成功后再进入人工 query 质量复核。

### 2026-09-01：attempt5 终态分类修复（当前）

- [x] attempt5 的第 3 个 cell 在 `16` 次 transport failure 后获得模型 response，但 `those awards` 触发 `query_unresolved_reference`；这是语义 validator 终态，不是网络失败。
- [x] 52 号 canary 的 resume 判定已改为检查最后一次 `failure_reason`；不再由历史 `transport_failure_reasons` 将语义失败误标为 `transport_failure_awaiting_resume`。仅改现有 canary 模块与既有测试，不影响论文实验语义、不需要新协议或重跑 formal 阶段。
- [x] 定向 unittest=`19/19 OK`、AST 和 `git diff --check` 通过；无新的 API 或其他外部调用。
- [ ] 当前唯一下一步：主人用同一 attempt5 `run` 命令刷新 summary；它会在建 client 前终止并写出 `automatic_validation_failed`，不调用 API、不改 attempts/results。随后人工决定是否调整 development-only 的 prompt/validator 后另开独立 attempt；正式 48 号 query-generation 继续禁止。

### 2026-09-02：v24 Pre-Split Eligibility 实现状态

- [x] v24 单一 config、离线 reconstruction/eligibility 实现、普通 CLI 与 unittest 已加入；核心边界为 v22 membership-blind source pool，未触碰 v23 frozen 文件或 artifact。
- [x] pre-formal 顺序已实现为 source-order 扫描、candidate-fact adapter、contextual role、correction eligibility、query feasibility、固定三 pair，再 split；scanner 达到 exactly 2250 即停止，容量不足 fail closed。
- [x] deterministic 1000/1000/250 split、eligible-source/split manifest hash、coverage/rejection reason/fallback 统计和 formal source/pair/query integrity re-check 已实现；fallback 仅修复 surface naturalization，不替换 source/pair/replacement。
- [x] 定向 v24 unittest=`29/29 OK`，AST/CLI/hash-order 检查通过；API、Retriever、victim、GPU、正式 index、response、AUC 调用=`0`。
- [ ] 下一步：先单独授权并运行 development/capacity canary；canary 通过前不得启动 v24 正式 query-generation 或下游评估。

### 2026-09-02：v24 离线完整性校验补强

- [x] split 构造先验证 eligible manifest；严格校验 3 pairs/source、6 queries/source、pair/query manifest hash、source integrity hash、dataset 和 manifest linkage。
- [x] 修正 surface fallback 后 query hash 重算，并将 fallback 统计限制为最终固定三对；offline role proxy 显式标记 `proxy_only`，不升级为正式 entity taxonomy。
- [x] 定向 v24 unittest=`29/29 OK`；ruff、AST parse、`git diff --check` 通过；无 API/Retriever/victim/GPU/正式 index/response/AUC 调用。
- [x] 全量 unittest 结果：`597` tests，`556 passed / 39 skipped / 1 failure / 1 error`；两项均为已有 v23 ledger/fresh-audit 测试失败，v24 未触碰相关代码、artifact 或状态。
- [ ] 当前唯一下一步仍是主人单独授权 development/capacity canary；不得在此之前执行真实 Luna、Retriever、victim 或正式评估。

### 2026-09-02：v24 retrieval anchor 门禁语义修正

- [x] 修复 `_anchor_reasons()` 直接进入 v24 `rejection_reasons` 的实现错误；anchor schema/source grounding/query presence 降为 `retrieval_anchor_diagnostics`，不影响科学 hard gates、candidate ranking、PVS 或 query budget。
- [x] 增加回归覆盖：无效 anchor 仍可接受但诊断被记录；anchor 不改变 ranking；query manifest 携带诊断且仍保持 6 queries/source。定向 v24 unittest=`39/39 OK`。
- [x] 三数据集 offline capacity estimate：EDGAR `30/30` source signal、Enron `28/30`、PubMed `30/30`；均未调用真实 API/Retriever/victim，membership=`false`。
- [x] 全量 unittest=`605`，`1 failure / 8 errors / 39 skipped`；失败仍为既有 v23 runtime/fresh-audit 工作区漂移，不能归因于 v24。
- [ ] 新的真实 Luna canary 尚未执行；上次 30-cell canary 的调用额度已用尽，必须获得新的明确 API 授权后才可重跑。

### 2026-09-02：v24 Luna development canary attempt r2

- [x] 新独立输出目录 `artifacts/v24/development/query_quality_canary_r2/` 已完成 30-cell 运行；`gpt-5.6-luna` 响应有效，`56` 次物理调用含 `26` 次 transport retry。
- [x] 失败证据已保留：`passed_pair_count=13/30`，失败集中于 semantic/reverse binding、unresolved reference、numeric/temporal/modality drift；anchor diagnostics 未作为拒绝理由。
- [x] API 之外的边界保持：membership、Retriever、victim、AUC、GPU、主 index 和正式 query-generation 调用均为 `0`。
- [ ] 当前状态：`v24_canary_hard_gate_failed`。在修复并提交新的 generator/config 前，禁止 capacity/formal 下游；不得删除失败 pair、换 source 或降低 eligibility/query hard gates。

### 2026-09-02：v24 semantic similarity 修复与新 canary

- [x] 将 Q+/Q-/reverse 的 `0.80` hard gate 从 lexical Jaccard 切换为冻结的 `BAAI/bge-base-en-v1.5` embedding cosine；未显式提供 scorer 时 fail closed，不允许 hashing/lexical fallback。
- [x] v24 config 固定 model revision=`a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`、`local_files_only=true`；canary summary 记录 semantic scorer identity。
- [x] 定向 unittest=`44/44 OK`、AST 与 diff check 通过；本地 BGE/CUDA smoke cosine=`0.8950162529945374`，hard gate 与 entity-masked semantic diagnostic 均无 lexical fallback。
- [x] 新独立 canary `query_quality_canary_r3_semantic_attempt2` 完成：`18/30`，30 logical / 50 physical API calls，20 transport retries，Retriever/victim/membership/AUC=`0/false`；失败 artifact 原样保留。
- [ ] 当前唯一下一步：先修复或重新界定 temporal/modality/unresolved-reference 等剩余结构 validator 与自然问句 realization 的契约，再开新的 development-only canary；在 30/30 前不运行 capacity/formal 下游。

### 2026-09-02：v24 query 结构门禁修复（当前）

- [x] 修复 temporal 误报：普通 `in/on/at` 不再构成 temporal marker；显式前后/期间关系、月份和 year/week/day 语义仍受 hard gate 保护。
- [x] 修复 citation 误报：`[5]`、`[16]` 等方括号文献编号不进入 factual numeric marker；真实数字省略仍 hard fail。
- [x] 补齐合法 polar auxiliary 和句首功能词识别，避免 `could/must/shall` 及 `In December` 被错误判作 non-polar/new factual entity。
- [x] 在现有生成路径加入一次固定 semantic correction retry，并保存 initial/correction candidate 级拒绝证据；禁止第三次生成、换 fact/source 或读取下游信号。
- [x] 定向 unittest=`54/54 OK`；config validation、AST、diff check 通过；API/Retriever/victim/GPU/formal calls=`0`。
- [x] 全量 unittest=`620`：`572 passed / 39 skipped / 1 failure / 8 errors`；失败均为既有 v23 query-runtime/fresh-audit/ledger 状态漂移，本次 v24 定向回归无失败。
- [ ] 当前唯一下一步：主人单独授权新的 v24 development-only canary attempt 后，使用新独立输出目录运行并检查 `30/30`；通过前不运行 capacity/formal 下游。

### 2026-09-03：v24 attempt4 transport 终态与重试修复（当前）

- [x] attempt4 独立目录完成 30 logical cells，`27/30` 通过；3 个 PubMed cell 均为错误响应体 `IncompleteRead`，不是 query semantic/structure rejection。
- [x] attempt4 provider model=`gpt-5.6-luna`，记录 physical attempts=`132`、transport retries=`102`；membership/Retriever/victim/AUC/GPU/formal=`0`，失败 artifact 保留。
- [x] 修复 `OpenAICompatibleChatClient` 的 HTTPError detail read：截断错误体现在 retryable status 下继续进入持续重连；非流式和流式路径均覆盖，避免网络问题错误落为 canary terminal failure。
- [x] 新增两条 `IncompleteRead` retry mock，定向 unittest=`56/56 OK`，AST 和 diff check 通过；未启动新的 API attempt。
- [ ] 当前唯一下一步：主人单独确认新的独立 v24 canary attempt 后再运行修复后的版本；通过 `30/30` 前不得进入 capacity/formal 下游。

### 2026-09-03：v24 development canary semantic attempt5（通过）

- [x] 新独立输出目录 `artifacts/v24/development/query_quality_canary_r3_semantic_attempt5/` 完成 30-cell 运行，`passed_pair_count=30/30`，`fallback_pair_count=0`，未覆盖既有失败 attempt。
- [x] provider model=`gpt-5.6-luna`；逻辑 API 调用=`32`，物理尝试=`71`，transport retry=`39`；持续重连修复在本 attempt 中生效。
- [x] semantic scorer identity=`BAAI/bge-base-en-v1.5@a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`，本地文件模式，threshold=`0.80`；summary/result hash 已记录。
- [x] membership、Retriever、victim、AUC、GPU、主 index 和正式 query-generation 均未读取或调用。
- [x] v24 query-quality canary 阶段完成，可进入离线 capacity sanity check；capacity 运行及所有 Retriever/victim/formal 下游必须等待单独授权。

### 2026-09-03：v24 source-level pair selection refinement

- [x] `eligibility.max_candidate_facts_per_source=8` 已加入现有 v24 config，定位为统一 frozen source-local Luna processing budget；raw fact 中出现 3 个不同实体的统计不再被表述为 3 个 eligible pair 的证明。
- [x] `screen_source()` 按 frozen fact order 最多处理 8 个 facts；3 个 distinct、完整 hard-gate accepted pairs 后 early stop；实体重复时保留 duplicate fallback，不升级为 eligibility gate。
- [x] coverage 字段口径固定为：`candidate_fact_count`=完整枚举总 facts，`processed_fact_count`=实际 provider/Luna processing，`candidate_package_count`=已处理 facts packages，`unprocessed_fact_count`=差值。
- [x] scan、capacity、manifest 记录统一 budget、processed/unprocessed、early-stop 与 diversity diagnostics；formal capacity/pre-split eligibility 不得越过 budget=8 处理后续 fact。
- [x] 新增 source-level selection mock tests；v24 定向 unittest=`53/53 OK`，无 v23 frozen 文件改动、无 API/Retriever/victim/GPU/formal 调用。
- [x] 追加验证：v24 + sibling retry 定向 unittest=`63/63 OK`；全量 unittest=`629`（`581 passed / 39 skipped / 1 failure / 8 errors`），失败属于既有 v23 query-runtime/fresh-audit/ledger 状态漂移。
- [ ] 下一步仍为单独授权后的 v24 capacity sanity check；capacity 必须使用同一 budget=8 和完整 frozen hard gates，未通过前不启动 Retriever/victim/formal。

### 2026-09-03：v24 source-level pair selection refinement 定义校正（superseding）

- [x] 将 `max_candidate_facts_per_source=8` 定义为 frozen source-local processing budget；“前 7 个 raw facts 出现 3 个不同实体”仅为保守的 development 经验依据，不再被当作 3 个 scientific-valid eligible pairs 的证明。
- [x] 固定 coverage 字段：`candidate_fact_count`=完整枚举总数，`processed_fact_count`=实际 provider/Luna processing，`candidate_package_count`=已处理 facts 返回 packages（含一次 retry），`unprocessed_fact_count`=两者差值。
- [x] capacity、pre-split eligibility 与 freeze 前 validation 共享 budget=8；禁止第 9 个 fact 隐式补救；manifest validator 拒绝非冻结预算；third-pair 位置只在完成全部 scientific hard gates 后记录，early-stop 定义仍以达到 distinct target 为准。
- [x] 保持 entity diversity 为 selection preference + diagnostic，未改变 hard gates、candidate ranking、PVS、split、query budget、governance 或 v23 frozen artifacts。
- [x] 定向 v24 unittest=`56/56 OK`；未执行 API、Retriever、victim、GPU 或 formal 运行。
- [x] 修正 offline `estimate_only` coverage 口径：无 provider/Luna 调用时 `processed_fact_count=0`，完整 candidate facts 计入 `unprocessed_fact_count`；预算内数量只用于 estimate-only eligibility signal。

### 2026-09-04：v24 capacity estimate 口径与断点续跑修复（当前）

- [x] 三数据集 30-source offline raw-fact estimate 已完成：EDGAR `30/30`、Enron `28/30`、PubMed `30/30` 满足“前 8 个 facts 至少有 3 个 raw candidate facts”；Luna/API、Retriever、victim、membership、AUC=`0`。
- [x] 将上述结果限定为必要条件 diagnostic。旧 r1 JSON 中的 `observed_eligible_source_rate` / `projected_eligible_source_count` 命名已 superseded，禁止作为 full-gate eligibility 或 2250 capacity 证据。
- [x] offline 新输出只填 raw-fact feasibility 字段，正式 eligibility 观察/投影字段为 `null`；Luna sample 才允许填 `observed_eligible_source_count/rate` 与 projection。
- [x] `run-capacity-check --output-dir <attempt>` 已接线；offline/Luna 文件分离，默认不覆盖已有 attempt。Luna 模式按 source 追加 checkpoint，`--resume` 只续跑同 config、同 source prefix、同 budget=8 的未完成 source，完成 summary 复用前复核 checkpoint hash。
- [x] 保持 transport failure 持续重连；终端显示逐 source progress。没有改变 hard gates、candidate ranking、PVS、split、query budget、membership-blind boundary 或 v23 frozen 文件。
- [x] v24 定向 unittest=`59/59 OK`，AST 和 diff check 通过；ruff 在当前 Conda 环境不可用，未安装新依赖。修复过程未执行真实 API、GPU、Retriever、victim 或 formal 实验。
- [ ] attempt5 仍只有自动门禁 `30/30` 证据；完成并记录 60/60 人工 query-quality review 后，才进入真实 capacity sample。
- [ ] 真实 Luna capacity sample 顺序：先 EDGAR 30 source（新独立 output dir、显式 API 授权），解释后再分别决定 Enron/PubMed。sample 不替代完整 deterministic scan。

当前唯一下一步：完成人工检查或由主人确认已有 60/60 review 记录；之后单独授权 EDGAR capacity sample。当前禁止完整 pre-split scan、membership split、Retriever、victim 和 formal evaluation。

### 2026-09-04：v24 attempt5 Assistant-only query-quality review（当前）

- [x] 主人将 pending 的人工 query review 改为 Assistant-only；审核口径固定为 `assistant_only_query_quality_review`，禁止称为人工审核、独立盲审、人类标注或一致性证据。
- [x] 已逐条审核 attempt5 的 60 条 query：通过 `27/60`、失败 `33/60`，完整通过 pair=`13/30`；EDGAR/Enron/PubMed 分别为 `4/20`、`8/20`、`15/20` query 通过。
- [x] 失败维度：semantic fidelity=`4`、naturalness=`12`、self-containedness=`29`、stealth=`0`、entity binding=`0`、polar question=`2`。逐条 reason 已写入 attempt5 普通诊断 artifact；未因复制率或 anchor warning 拒绝 query。
- [x] `assistant_query_quality_review.jsonl` SHA-256=`76b1a5d6538edf5e66e379073d4de313938d8faf65eac6fe4c04b452f2fcf54e`；review summary 状态=`failed_assistant_query_quality_review`、`human_review_performed=false`、`capacity_sample_allowed=false`。
- [x] 审核过程外部 API、Retriever、victim、GPU、membership、AUC 调用均为 `0`；没有修改 v23 frozen 文件，也没有新增 protocol、governance、ledger、authorization 或 identity 机制。
- [ ] 当前 attempt5 不满足 60/60 query-quality 条件，真实 Luna capacity sample 继续禁止。

当前唯一下一步：在现有 v24 内最小修复 proposition 完整性以及 query 的 unresolved-reference/naturalness 覆盖，另开 development-only canary attempt；只有自动 hard gates 与 Assistant-only `60/60` 同时通过后，才可单独授权 EDGAR 30-source Luna capacity sample。

### 2026-09-04：v24 attempt5 query 结构门禁覆盖修复（superseding）

- [x] 完成既有 self-contained/natural-polar gate 的最小实现补齐：Prompt 约束、fact quality、canonical proposition quality、query surface validation 均在现有 `src/prepare/restoration_first_v24.py` 内完成；未新增 scientific gate 或 successor protocol。
- [x] provider 前拒绝高置信残句/标题粘连/引文实体槽，避免无效 fact 消耗 Luna processing；query validator 覆盖 first-person/document-bound reference、局部未解析 `the Company/the following/the period`、`herein`、错误 modal/do coordination、reportative tail 与 `Is it correct that In/...`。
- [x] 局部定义的引号第一人称别名、普通小写 `the company`、已解析 `their` 保持兼容；first-person claim 机械改成裸 `the company` 仍拒绝，显式 `the reporting company` 可通过。
- [x] 定向 unittest=`67/67 OK`；attempt5 旧 Assistant-only 失败条目只读 replay 捕获=`33/33`，未改写 attempt5 artifact；1 个含 bibliography citation 的旧通过 query 仍按 fact-quality 规则拒绝。
- [x] AST parse 与 `git diff --check` 通过；本次没有 API、Retriever、victim、GPU、membership、AUC 或 formal 调用，v23 frozen 文件未触碰。
- [ ] 需要新的独立 development-only canary attempt，重新生成 30 pairs / 60 queries，并执行 Assistant-only query-quality review；通过前不得进入 capacity sample 或任何下游正式阶段。

当前唯一下一步：运行离线验证后，由主人单独授权新的 v24 development-only canary attempt；attempt5 失败 evidence 保持为历史证据，不原地重试或改标通过。

### 2026-09-04：v24 development canary attempt6 结构门禁失败（当前）

- [x] 新独立目录 `artifacts/v24/development/query_quality_canary_r3_structural_attempt6/` 完成 30 个 logical cells，自动 hard gates 通过 `26/30`，`fallback_pair_count=0`，终态=`failed_hard_gates`；失败 artifact 原样保留。
- [x] attempt6 使用 `gpt-5.6-luna`，logical API calls=`32`、physical attempts=`79`、transport retries=`47`；网络持续重连有效。未读取 membership，Retriever/victim/AUC/GPU/formal 调用均为 `0`。
- [x] 四个失败项已定位：Enron index `4` 的多 modal 协调不自然，Enron index `5` 的残缺时间事实，PubMed index `1` 的标题-句子粘连，PubMed index `9` 的 bibliography citation 实体槽。已在既有 v24 prompt 与 correction retry 中补充多 modal 固定 frame 约束；定向 unittest=`68/68 OK`，AST/diff check 通过。
- [x] attempt6 hashes：summary=`7b81d4b93f15657d9f87778ed4bab1e419b5465b6fbb7c512535f22603482192`，results=`29b3b610c49fd75a3cee1c50e9d7912174bc5e7506768978a683534020e02563`。NLI neutral/contradiction diagnostic 口径未变。
- [ ] 新 canary 尚未获授权；在新的独立 attempt 达到自动 `30/30` 且完成 Assistant-only `60/60` query-quality review 前，不得运行 EDGAR capacity sample、完整 eligibility scan、membership split、Retriever、victim 或 formal evaluation。

当前唯一下一步：先提交现有 prompt/test 修复并等待主人单独授权新的 development-only Luna canary；不得复用 attempt6 输出目录，也不得以失败样本替换或降低 hard gates。

### 2026-09-04：v24 development canary attempt7 失败与 validator 修复（当前）

- [x] 独立目录 `artifacts/v24/development/query_quality_canary_r3_structural_attempt7/` 完成 30 logical cells，自动 hard gates=`28/30`，fallback=`0`，终态=`failed_hard_gates`；summary/results 原始文件和 hash 已保留。
- [x] provider=`gpt-5.6-luna`，logical API calls=`32`、physical attempts=`72`、transport retries=`40`；Retriever/victim/membership/AUC/GPU/formal=`0`。
- [x] EDGAR index `2` 为 canonical first-person `we` 残留；Enron index `14` 为固定 `Is it correct that ...` 框架中的自然多 modal 被旧正则误报。两者都没有导致 hard gate 放宽或失败样本替换。
- [x] 现有 v24 validator 的 modal/do coordination 正则改为仅检测句首倒装协调；candidate/correction Prompt 增补逐字段清除 first-person/document-bound token 的明确要求。该修复不改变 canonical reference gate 或任何 scientific hard gate。
- [x] 定向 v24 unittest=`69/69 OK`；AST parse 与 `git diff --check` 通过；未运行新的 API、capacity、Retriever、victim 或 formal 任务。
- [ ] attempt7 仍不满足自动 `30/30`，Assistant-only `60/60` review 尚未开始；在新的独立 canary 达标前继续阻断 capacity sample 及所有下游。

当前唯一下一步：等待主人单独授权新的 v24 development-only Luna canary attempt，使用新输出目录；不得复用 attempt7、降低 hard gates 或把失败证据改标为通过。

### 2026-09-04：v24 query naturalization 直接问句优先（当前）

- [x] 只读统计 attempt7：56 条已选 query 中 42 条（75%）使用 `Is it correct that ...?`，而 fallback=`0`；问题定位为旧 Prompt 对固定安全模板的过强偏好。
- [x] candidate Prompt 与唯一 semantic correction retry 均改为优先生成语法成立的直接 polar question；固定 verification frame 仅保留给直接倒装会失真、歧义或无法自然承载复杂多 modal 命题的情况。
- [x] 保持 validator 对 `Is/Are/Was/Were/Do/Does/Did/Has/Have/Had/Can/Could/Will/Would/Should/May/Might/Must/Shall` 的合法接受；新增 `Does/Was/Can/Will` 回归，不把 opening diversity 变成 hard gate或 ranking signal。
- [x] 不改变 scientific hard gates、BGE、candidate ranking、fallback、PVS、split、query budget 或 v23 frozen 文件；本次 API/Retriever/victim/GPU/membership/AUC/formal 调用均为 `0`。
- [ ] 运行 v24 定向 unittest、AST parse 与 `git diff --check`；通过后方可请求新的独立 Luna canary 授权。

当前唯一下一步：完成离线验证；随后等待主人单独授权新的独立 v24 development-only Luna canary，不复用 attempt7，不启动 capacity 或下游。

### 2026-09-04：v24 development canary attempt10 direct-polar 终态是

- [x] 新独立输出目录 `artifacts/v24/development/query_quality_canary_r3_direct_polar_attempt10/` 完成 30 logical cells；自动 hard gates=`27/30`、`fallback_pair_count=0`、状态=`failed_hard_gates`，失败 evidence 原样保留。
- [x] provider=`gpt-5.6-luna`；logical API calls=`31`、physical attempts=`76`、transport retries=`45`；summary/results hashes 分别为 `98a1b9cf6247ad5bc1456cf54ce2c9b37f8ee2debe63f956f57566a7b5de3c7e` / `4a1bb9145651214565cbd98a0f78bd8499d24f749ece162003d0bfe348086ddd`。
- [x] 失败为既有 pre-Luna fact-quality gate：Enron index `5`=`candidate_fact_incomplete_temporal_reference`，PubMed index `1`=`candidate_fact_heading_sentence_glue`，PubMed index `9`=`candidate_fact_entity_contains_citation`；不属于 direct-polar naturalization 回归，也未替换样本或放宽 hard gates。
- [x] 54 条 query 的 direct-polar=`46/54`（85.19%），`Is it correct that`=`8/54`（14.81%），fallback=`0`；NLI neutral diagnostic 可通过，未读取 membership/Retriever/victim/AUC。
- [ ] attempt10 未达到 `30/30`，因此不启动 Assistant-only `60/60` review 或 capacity sample；完整 eligibility scan、membership split、Retriever、victim 和 formal evaluation 继续 blocked。

当前唯一下一步：在现有 v24 范围内处理这三类已知 fact-quality 输入问题后，使用新的独立 canary attempt；不得复用 attempt10、替换失败样本或降低 hard gates。

### 2026-09-05：v24 Qwen3.5-4B Candidate-Fact Pool（当前）

- [x] 实现本地 Ollama 原文 claim/entity 抽取、严格 JSON、唯一 spans、单槽检查、跨 chunk 去重与稳定 fact_order；配置固定 Qwen3.5-4B Q4_K_M、关闭 thinking、4096/1024、seed=42、temperature=0、单并发及一次传输重试。digest 暂未绑定，真实运行必须通过 digest/量化/GPU 检查。
- [x] 实现 source JSONL + 普通 pool manifest，保留提议/拒绝计数、完整响应和失败证据；零候选完成 source 不丢失分母，未完成 source 不伪装为零候选。checkpoint/resume 校验完整记录，损坏拒绝复用，完成池禁止覆盖。
- [x] 53 号 runner 接入 build/validate 命令与重复 `--candidate-pool`；capacity、fresh canary、frozen scanner 显式读取同一绑定池，并复核所选数据集的冻结源池数据库内容 hash。开发子集不能用于正式 scanner，pool hash 进入 capacity/resume 和 eligibility manifest，Luna 配置变化不自动要求重新抽取。
- [x] 复用现有开发记录的 source identities/text hashes，补齐冻结原文 hash 并写入池排除集合；恢复旧 capacity 确定性 source prefix，仅消费身份。禁止历史类型、反事实、membership、Retriever/victim 回答或 AUC/PVS 进入候选输入。
- [x] 离线验收通过：v24 `97/97`，加 PVS/source/budget 回归共 `102/102`；静态配置通过、`candidate_model_bound=false`，内存 AST 编译、diff check 通过。起始快照的 76 个 v23 文件 hash 保持一致；没有新增代码文件或真实实验 artifact，没有提交/推送。
- [x] 本阶段真实模型/API/GPU/检索/victim 调用为 0；模型部署、10-source 验证、Luna canary、capacity、完整构建均未启动。Qwen3-4B 保留 IA、Luna 保留重构/query、Gemma 保留 victim；不声称 Qwen 不同权重之间的模型家族独立性。
- [ ] 单独授权后，先部署并绑定本地完整 digest；固定每数据集 10 个 source，验证显存、速度、长度预检与事实质量，不因失败或候选不足替换/补抽 source。
- [ ] 抽取开发验证后再决定新 Luna canary；重新取得自动 `30/30` 和 Assistant-only `60/60` 证据后，才推进 capacity、完整候选池及下游。保留 attempt10 与旧 regex 失败证据，不将其混入新 adapter 结果。

当前唯一下一步：等待主人单独授权模型部署及每数据集 10-source 抽取验证。新候选输入会改变 eligibility，需重新取得相关实验依据；仍使用 v24，不改 hard gates、BGE/NLI diagnostic、前 8 预算/early stop、3 pairs/6 queries、split 配额与 victim budget，不增加 governance 层。

### 2026-09-05：Qwen3.5-4B 抽取部署验证完成

- [x] ModelScope 下载并导入 Ollama；GGUF hash=`00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4`，Ollama digest=`sha256:67dd8464f0fdef87b1c1984629e6ef728498332e5a7d72c709ba7dd1046baae7`。
- [x] Q4_K_M、RTX 4060 全 GPU 驻留、Ollama 0.32.5、`num_ctx=8192`、`num_predict=1024`、`think=false` 已通过实际 preflight；抽取后仍为全 GPU/8192。
- [x] 固定范围 EDGAR/Enron/PubMed 各 10 source，30 source/113 chunk；8192 超限 chunk=`0`。完成/失败=`15/15`，失败均为输出截断；Ollama chat=`74`，Luna/victim/Retriever=`0`。
- [x] 候选统计 EDGAR 162、Enron 38、PubMed 11，合计 211；Assistant-only quality review=`quality_followup_required`，结构残片不能通过正式事实质量门禁。
- [x] 诊断 artifact 已封存于 `artifacts/v24/development/qwen35_extraction_validation_20260905_8k/`，失败 source 和截断响应完整保留，不作为正式池。
- [x] 离线回归 `102/102 OK`，AST 与 `git diff --check` 通过；未运行 Luna canary、capacity、完整候选池、Retriever、victim 或 formal test。
- [ ] 新独立 development 目录处理输出截断与事实完整性修复；未通过前不得进入下游。

当前唯一下一步：保留本批失败证据，完成最小质量修复/复核，不补抽、不替换 source，不降低 hard gates。

### 2026-09-05：Qwen3.5-4B 3072 输出验证完成

- [x] `num_ctx=8192` 保持不变，`num_predict=3072` 已接入 YAML、adapter identity、请求参数和测试；新增明确结构残片拒绝规则。
- [x] 同一固定 30 source/113 chunk 重新验证，8192 超限为 `0/113`，最大边界 7088；完成/失败 `25/5`，失败全为 3072 输出截断。
- [x] 分数据集完成/失败：EDGAR `8/2`、Enron `10/0`、PubMed `7/3`；候选 183/19/306，合计 508；原始提议 877，拒绝 369；零候选完成 source=4。
- [x] Ollama chat=96，模型为 Q4_K_M、digest 已绑定、全 GPU/8192 驻留；Luna/victim/Retriever/membership/AUC=0。
- [x] 106 项 v24/PVS/source-budget 回归、AST、diff check 和产物 hash 复核通过；诊断 artifact 位于 `artifacts/v24/development/qwen35_extraction_validation_20260905_8k_3072/`，不作为正式池。
- [ ] 5 个 source 仍因输出截断失败，且尚未完成逐事实语义审查；正式候选池、Luna canary、capacity 和下游继续阻断。

当前唯一下一步：在独立 development 目录处理截断 source 并完成 Assistant-only 逐事实审查，保留本轮失败证据，不替换 source、不降低 hard gates。

### 2026-09-05：3072 抽取验证事实审查完成

- [x] 25 个完成 source 的前 8 个候选已逐条 Assistant-only 审查，覆盖 130/508 候选：明显无问题 95、需复核 6、拒绝 29。
- [x] 已记录邮件头/署名、键值字段、整段实体、并列槽、方程编号等失败模式；artifact=assistant_fact_review.json，不宣称人工盲审或统计质量指标。
- [ ] 5 个 source 仍因 done_reason=length 在 3072 截断；EDGAR 8/10、Enron 10/10、PubMed 7/10，正式池和下游继续阻断。

当前唯一下一步：基于审查证据决定最小结构规则，再在独立目录复核截断 source 和实体槽质量。
### 2026-09-05：Qwen3.5-4B 4096 验证状态（superseding）

- [x] `num_predict=4096` 已同步 v24 YAML、adapter identity、Ollama options 和 context unittest；`num_ctx=8192`、Q4_K_M、digest、think=false、seed=42、单并发保持冻结。
- [x] 同一固定 30 source/113 chunk 精确预检通过：EDGAR/Enron/PubMed 最大边界 `7998/7159/8112`，超限 `0/113`。
- [x] 实际完成/失败：EDGAR `8/2`、Enron `10/0`、PubMed `8/2`，合计 `26/30`；4 个失败全部为完整输出截断，Ollama chat=`103`，无 context overflow、传输失败、非法 JSON。
- [x] 候选=`547`、原始提议=`969`、代码拒绝=`422`；零候选完成 source=`4`，计入分母。Luna/victim/Retriever/membership/AUC=`0`。
- [x] 诊断输出目录：`artifacts/v24/development/qwen35_extraction_validation_20260905_8k_4096/`；3072 目录原样保留，不作为正式候选池。
- [x] v24 定向 unittest=`101/101 OK`，AST 与 `git diff --check` 通过。
- [ ] 仍未达到稳定完成和事实质量条件，正式 candidate pool、Luna canary、capacity、split、Retriever、victim 与 formal evaluation 继续阻断。

当前唯一下一步：完成 4096 诊断目录的 Assistant-only 前 8 facts 质量审查，并基于失败证据决定最小结构修复；不补抽、不替换 source、不降低 hard gates。
### 2026-09-05：v24 GLiNER2 entity/value span adapter（superseding）

- [x] candidate construction 改为原文 proposition + GLiNER2 entity/value span detection；Luna、Gemma、Qwen3-4B IA 和所有下游职责保持不变。
- [x] 增加少量 proposition structural rejection 与 rejection counters；不引入新的 LLM 或通用 NLP parser。
- [x] `preferred_max_words=6` 降级为诊断，`hard_max_words=12` 作为保护；保留长组织名、生物医学/药物/基因/通路、法规名和技术术语，记录 entity word count 与 label provenance。
- [x] 支持同一 claim 多 entity/value candidates，按 proposition span、entity span、entity text 确定性排序并按相同 `(claim span, entity span)` 去重。
- [x] 现有 pool JSONL/manifest/checkpoint/resume/hash、显式 `--candidate-pool`、zero-candidate 分母、前 8 facts、hard gates、PVS、split 和 query budget 未改变。
- [x] Qwen3.5 历史验证产物保留为 diagnostic-only，不复用到 GLiNER2 pool；v23 文件未修改。
- [x] mock/static 验收：v24 unittest=`106/106 OK`，AST 与 `git diff --check` 通过；真实模型/GPU/API/Luna/Retriever/victim/capacity/formal 均未运行。
- [ ] 需要新的 GLiNER2 development validation，确认本地模型绑定、GPU 驻留、proposition rejection 分布和 entity/value 质量后，才考虑正式 pool。

当前唯一下一步：固定 10-source development validation 使用 GLiNER2 adapter；完成前继续阻断正式 candidate pool、Luna canary、capacity 和下游正式阶段。

### 2026-09-05：v24 Qwen adapter removal（superseding）

- [x] 删除 v24 Qwen3.5/Ollama candidate adapter 代码、配置分支和 pool 消费兼容分支；GLiNER2 是唯一正式 candidate extractor。
- [x] 保留 Qwen 历史验证产物为 `diagnostic_only`，不删除、不覆盖、不复用。
- [x] 更新 `validate-config` 与 GLiNER2 mock 测试；旧 Qwen 专属测试仅作 skipped legacy regression，不参与 v24 adapter 验收。
- [x] 重新验证：v24 unittest `106` 项（`96` passed，`10` skipped legacy），AST OK，`git diff --check` 通过。

当前唯一下一步：固定三数据集各 10 source 的 GLiNER2 development validation；正式 pool、Luna canary、capacity 和下游实验继续阻断。

### 2026-09-05：GLiNER2 三数据集 10-source validation 完成

- [x] EDGAR/Enron/PubMed 各完成 10 个冻结 source（30/30），使用本地 CUDA GLiNER2，独立输出目录 `artifacts/v24/development/gliner2_entity_value_validation_20260905_r2/`。
- [x] 三池 `validate-candidate-pool` 全部通过；零候选 source=0；候选统计 EDGAR `1118`、Enron `112`、PubMed `2296`；pool hash 已写入 notes 和 manifest。
- [x] 记录 proposition/span rejection、模型 revision、设备和 source-pool identity；首轮失败目录保留，修复仅涉及 validator 对重复 mention 的重复拒绝。
- [x] 未调用 Luna、Retriever、victim、membership、AUC、capacity 或正式下游；Qwen 历史目录继续 diagnostic-only。
- [ ] 完成预先定义的逐事实质量复核；在复核完成前不构建 formal candidate pool、不启动 Luna canary 或下游实验。

当前唯一下一步：GLiNER2 30-source development pool 逐事实质量复核，并保留所有失败证据。

### 2026-09-05：30-source candidate structural review 完成

- [x] 全部 `3526` 个 GLiNER2 candidate 已生成 assistant-only structural review artifact；结果 pass=`3516`、reject=`9`、review=`1`。
- [x] review 明确标记 `diagnostic_only=true`、`human_review_performed=false`，不改变 candidate pool、前 8 规则或下游协议。
- [ ] 对 10 条非 pass candidate 做独立语义决定；在决定完成前继续阻断 Luna canary、capacity、formal pool 和下游实验。

当前唯一下一步：复核 9 条 reject 与 1 条 review 候选，并保留原始记录。

### 2026-09-06：v24 BEIR source-pool migration implementation

- [x] v24 数据集绑定改为 `nfcorpus`、`scidocs`、`trec-covid`；旧数据集生产入口 fail closed。
- [x] v24-local reader/contract 与 BEIR corpus builder 已实现；固定统一字段映射和 1 document=1 source=1 chunk。
- [x] duplicate ID/text、manifest/order/database hash、membership-blind flags、2250 minimum、development exclusion 已覆盖。
- [x] v24 unittest、AST 和 diff check 通过；v23 未作为新数据集兼容层修改。
- [ ] 真实 BEIR source pool 尚未构建；GLiNER2 10x3 validation、Luna canary、capacity 和 formal eligibility 继续阻断。

当前唯一下一步：获得本地固定 `corpus.jsonl` 后构建三套 v24 source pool，并固定 10x3 development identities。

### 2026-09-06：BEIR source pools 构建完成

- [x] 下载并解压三个 BEIR corpus，未读取 query/qrels。
- [x] v24-local pools 已冻结：NFCorpus `3593`、SCIDOCS `25656`、TREC-COVID `170367`；每个 source 只有一个 rank-0 chunk。
- [x] manifest/order/database hash、membership-blind flags 和每池 10 个 development identities 已生成并通过 reader 验证。
- [x] v24 unittest `110` 项通过（`100 passed`、`10 skipped legacy`），AST 和 `git diff --check` 通过。
- [ ] GLiNER2 10x3 development validation 尚未运行；Luna canary、capacity、formal eligibility 继续阻断。

当前唯一下一步：获得单独授权后，在三套新冻结 pool 上运行 GLiNER2 各 10 source 验证。

### 2026-09-06：新 BEIR GLiNER2 10x3 validation 完成

- [x] NFCorpus、SCIDOCS、TREC-COVID 各 10 source，30/30 完成；candidate=`291/212/312`，proposal=`380/260/381`。
- [x] 三个 candidate pool 离线 validation passed，pool hash 已绑定；零候选 source=0，fact slot 结构异常=0。
- [x] 未调用 Luna、Retriever、victim、capacity 或 formal eligibility；新池仍为 development-only。
- [ ] 完成新三数据集 candidate 的 assistant-only structural/semantic review。

当前唯一下一步：复核新三数据集 815 条候选，保留所有 reject/review 证据，再决定 Luna canary。

### 2026-09-06：815 candidate assistant-only review 完成

- [x] 新三数据集全部 `815` 条候选已完成结构复核：pass=`810`、review=`5`、reject=`0`。
- [x] 5 条 review 候选来自 NFCorpus 的 `and/or` 短语，未从 candidate pool 删除。
- [x] review artifact 标记为 diagnostic-only，未调用任何下游模型或服务。
- [ ] 对 5 条候选进行独立语义决定。

当前唯一下一步：完成 5 条 review 候选的语义复核，再决定是否授权 Luna canary。

### 2026-09-06：5 条 review 候选独立语义决定

- [x] 已写入 `artifacts/v24/development/gliner2_beir_validation_20260906/semantic_review_decisions.json`；保留 4 条、拒绝 1 条。
- [x] 拒绝 `nfcorpus::MED-1013` 的 `functioning and quality of life`（两个可独立替换概念）；保留其余四条固定术语/程度值/数值范围候选。
- [x] 原始 `assistant_fact_review.json`、source records、candidate pool hash 和下游协议未修改；该记录仍是 assistant-only diagnostic evidence。

当前唯一下一步：用户单独授权后才进行 Luna canary；在此之前不启动 Luna、capacity、formal eligibility 或正式评估。

### 2026-09-06：entity/value ranking 静态实现

- [x] 对现有 815 条候选做只读分布检查，确认 OTHER/generic span 与错误 label 会过早占据 first-8。
- [x] 保留同 claim 多槽；使用确定性三档 surface+label quality。0/1 档共同按 claim 轮转，每轮按 tier 与原文位置排序，低优先级 2 档最后轮转。疑似词性仅降级，避免宽泛词尾硬删；明显结构问题才拒绝。
- [x] candidate count 仍是完整 validated+deduped 集合，`fact_order` 和完整 `candidate_processing_order` 为冻结顺序；reader 重算 ranking/grounding 并拒绝漂移，adapter policy 变化使旧池不能继续消费。first-8 不补第 9、early stop、Luna/hard gates/PVS/split/query budget 均未变。
- [x] 修复问句、明确 heading/body glue 和过宽 signature 过滤；GLiNER2 schema/model/revision 与 Luna prompt projection 保持不变，排名 metadata 不进入 Luna。
- [x] 独立离线报告 `artifacts/v24/development/entity_ranking_offline_diagnosis_20260906.json` 保存每 source counts、每 claim histogram、label distribution/examples、旧与重放 first-8。原 815 条在新过滤重放后为 744；low-priority 诊断 `113/215 -> 16/211`，claim coverage `77 -> 165`。不得将按本次规则计算的诊断变化写成独立语义准确率或真实 validation passed。
- [x] 更正旧记录：原 TREC-COVID 有 2 个零候选 source，新问句过滤重放后为 3 个，全部计入分母；旧 `810 pass + 5 review` 不代表全池只有 1 条语义问题，5 条独立决定亦仅为 Assistant 复核。原 artifacts 未改写，未生成手工筛选的 814 条池。
- [x] v24 + BEIR reader 定向 mock unittest `126` 项（`116 passed`、`10 skipped legacy`）通过；未运行真实 GLiNER2、Luna、Retriever、victim 或 capacity。
- [x] Conda 解释器路径、AST、诊断 JSON/hash、`git diff --check` 通过；最终 `git status` 复查完成，76 个 v23 文件及原 validation 目录内 8 个产物 hash 不变。本次未提交、推送或产生临时脚本/缓存。
- [ ] 尚未完成新 ranking 的真实 development validation，不能表述为 ranking validation passed。

当前唯一下一步：使用独立 development 输出重跑已使用的同一批 30 个 source identities，复核 first-8 及全部失败/零候选；不得自动改选另一批 source，不修改 development exclusion，不用旧 validation 背书新排序。重跑前继续保持 Luna/capacity/formal 未启动。

### 2026-09-06：ranking rerun 完成

- [x] 新增 development-only `fixed_source_identities` 参数，按 source key 与 source/text hash 绑定旧 30-source 身份；resume 时 identity drift fail closed，正式池路径拒绝该参数。
- [x] 新 GLiNER2 rerun 目录：`artifacts/v24/development/gliner2_beir_ranked_validation_rerun_20260906/`；NFCorpus/SCIDOCS/TREC-COVID 各 `10/10` 完成，候选 `270/212/264`，原始提议 `354/264/326`，first-8 `75/80/56`。
- [x] 总 inference attempts=`224`；三池 reader/hash 校验通过，身份与旧记录一致。TREC-COVID 零候选 source=`3`，全部保留并计入分母。
- [x] mock/static 回归 `124` 项（`114 passed`、`10 skipped legacy`），未调用 Luna、Retriever、victim、capacity 或 formal evaluation。
- [ ] 仍需对新排序 first-8 做 assistant-only 质量复核；之后才讨论独立 Luna canary 授权。不得将本轮 development 结果写成正式质量或 eligibility 通过。

- [x] first-8 assistant-only review 已写入 `artifacts/v24/development/gliner2_beir_ranked_validation_rerun_20260906/first8_quality_review.json`：211 条中 pass=`209`、review=`2`、reject=`0`；review 仅为 `and/or` 协调短语。
- [ ] 仍需对 2 条 review 候选作独立语义决定；该 review 不等价于人工盲审或正式质量通过。

当前唯一下一步：独立决定 `first8_quality_review.json` 中 2 条 review 候选，之后再讨论是否授权 Luna canary。

### 2026-09-06：ranking v2 最小收紧完成（待真实复核）

- [x] 保留同 claim 多槽和完整 candidate pool；新增 source-level unique normalized entity preference，processing order 分为 unique pass 与 duplicate fallback，first-8 仍严格为 8。
- [x] bare scalar/cardinal number 降级但不删除；typed value、日期、金额、百分比、带单位数值保持较高优先级。
- [x] generic OTHER 使用小型 generic head/abstract suffix 诊断降级；明显 adjective/comparative slot、question proposition 和 publication fragment 增加确定性拒绝。
- [x] 新增测试，v24 unittest `129` 项通过（`119 passed`、`10 skipped legacy`）。
- [x] 生成 `entity_ranking_v2_offline_comparison.json` 作为旧 rerun 的 diagnostic-only 投影，未覆盖历史 artifact；尚无 v2 真实 GLiNER2 证据。

当前唯一下一步：用户授权后重跑同一批 30-source v2 GLiNER2 development validation，再决定是否进入 Luna canary。

### 2026-09-06：v2 GLiNER2 真实 10x3 validation 完成

- [x] 固定同一批 30 source identities，v2 输出目录为 `artifacts/v24/development/gliner2_beir_ranked_v2_validation_20260906/`；三数据集 `10/10`，source identity/hash `30/30` 一致。
- [x] proposals/candidates：NFCorpus `351/260`、SCIDOCS `264/205`、TREC-COVID `326/253`；合计 `941/718`，inference=`222`，first-8=`211`。
- [x] first-8 unique entity preference 后重复占用：NFCorpus=`8`、SCIDOCS=`0`、TREC-COVID=`0`；candidate pool 未删除重复 candidate。TREC-COVID 零候选=`3`，保留分母。
- [x] v2 first-8 assistant-only review=`209 pass / 2 review / 0 reject`，仅 diagnostic-only；reader/hash/manifest 校验通过。
- [ ] 尚需独立决定 2 条 review 候选；未启动 Luna、capacity、formal eligibility 或正式评估。

当前唯一下一步：独立复核 v2 first-8 的 2 条 review 候选，之后再讨论 Luna canary 授权。

### 2026-09-06：v2 review 语义决定完成

- [x] 复核 v2 first-8 的 2 条 `coordinated_entity_span`：`one or two` 和 `five or more times` 均保留为单一 value slot。
- [x] 新增 development-only `semantic_review_decisions.json`；两条均 `retain_for_candidate_pool`，`replacement_suitability=not_assessed`。
- [x] 未改写 candidate pool 或 first-8 顺序，未启动 Luna、capacity、formal eligibility、Retriever 或 victim。

当前唯一下一步：等待单独授权后进行 development-only Luna canary；正式 eligibility 和正式实验继续阻断。

### 2026-09-07：canary 零候选顺延补选已实现

- [x] 按用户新要求解除 canary 每个原固定 source 都必须有候选的限制；仅零候选可跳过，沿冻结顺序从绑定池中补足每数据集 10 个输入。
- [x] 复用 `--candidate-pool` 支持互不重叠的 development 补充池；原池不覆盖，同 dataset 多池只用于 canary，正式 pool 和 capacity 入口不变。
- [x] preflight evidence 保留零候选和补入 source 的身份/hash，现有开发排除逻辑同时覆盖两者；不足时保存缺口，未完成 fixture 不生成 canary 输入。
- [x] mock 覆盖连续零候选、冻结顺序和 pool hash 稳定、补充池读取、开发排除、缺口、错误记录 fail closed、first-8，以及 Luna 失败不补 source。136 项定向测试（126 passed、10 skipped legacy）和 AST 通过，旧 v2 三池离线校验通过。
- [ ] 尚未真实补抽 TREC-COVID source，也未准备真实补选 canary fixture 或调用 Luna。原 30-source validation 结果仍保留，不能把补选 canary 的通过率当作总体 source eligibility。

当前唯一下一步：为 TREC-COVID 的 3 个零候选缺口按冻结顺序补充 development 候选，之后准备新的 10x3 canary fixture；真实模型任务尚未执行。

### 2026-09-07：补充抽取与 10x3 canary 输入准备完成（superseding）

- [x] 使用冻结 GLiNER2/ranking v2，在独立 development 补充池完成 TREC-COVID rank `20/21/22` 三篇抽取；三篇均非空，候选=`61/23/10`，合计 `94`，原始提议=`109`，本地 CUDA inference=`24`，失败=`0`。
- [x] 补充池：`artifacts/v24/development/gliner2_beir_canary_supplement_20260907/batch_01/trec-covid/pool_manifest.json`；reader、source/chunk、排序和 hash 校验通过，原三套 v2 池及零候选证据保留。
- [x] 离线 fixture：`artifacts/v24/development/query_quality_canary_beir_ranked_v2_20260907/preflight/canary_inputs.jsonl`；preflight=`passed`，检查 `33` 篇、跳过 `3` 篇零候选、补入 `3` 篇，每数据集选中 `10` 篇，共 `30` 个不同 source。
- [x] 输入与 manifest 内容/文件 hash、first-8 绑定和全部 `33` 条 source decision 身份复核通过；已检查的入选/零候选 source 均受开发排除覆盖，三数据集当前开发 source key 数=`20/20/23`。
- [x] 本次真实 Luna/API、Retriever、victim、capacity、formal 与 membership/AUC 调用或读取为 `0`；输入准备完成不等于问句生成或质量审核通过。
- [ ] 使用固定输入运行新的 development-only Luna canary，并完成 Assistant-only 60-query review；真实 Luna API 需单独授权。
- [ ] 进入后续 capacity 前修复源池总量读取缺失导致的零投影问题；当前尚未开展 capacity 或正式下游。

当前唯一下一步：单独授权后运行已准备输入对应的 Luna canary，使用原三套 v2 池及 TREC-COVID 补充池，保留全部自动门禁失败并进行逐条问句质量复核。

### 2026-09-07：已授权并启动 BEIR Luna canary（进行中）

- [x] 主人授权运行固定 30-input Luna canary 并复核目标 60 条问句；已启动 `artifacts/v24/development/query_quality_canary_beir_ranked_v2_20260907/luna_attempt1/`，四套池及输入 hash 均已绑定。
- [x] 模型和限速/重试配置按现有配置运行；只读目录连通性检查 HTTP `200` 且列出 Luna，该检查 completion 次数为 `0`。
- [x] 长时间等待期间主人明确选择继续原配置等待；当前同一运行尚未返回整批 summary，实际完成数和 API 次数尚不可核验。
- [ ] 收到本轮 canary 终态及结果，核验模型身份、输入/结果 hash、自动门禁和调用计数。
- [ ] 逐条复核实际生成问句并记录未生成/失败项，明确 Assistant-only，不能将未完成的审核记作 60/60 passed。

当前唯一下一步：继续等待当前 `luna_attempt1`，返回后完成问句质量复核；不重复启动该批输入的另一运行。

### 2026-09-07：状态核验与文档职责调整（superseding）

- [x] 17:27（Asia/Shanghai）复核：未发现原 canary/Python 进程，`luna_attempt1` 无结果和 summary 文件；原任务有中断记录。此前“进行中、继续等待”的状态已过时，本批完成数和调用数仍未知，不能判为科学门禁失败。
- [x] README 更新为 v24 当前入口并保留历史说明；AGENTS.md 只保存稳定规则及研究总表链接，不再重复实验过程、进度或阶段快照。
- [x] 记录上一步离线定向回归：146 项，136 passed、10 skipped legacy；本次没有修改代码、配置或实验产物，也没有新增模型/API/Retriever/victim 调用。
- [ ] 最小修复 canary 的逐 source 保存、进度与恢复；修复 capacity 源池总量取数，并补充对应离线回归。
- [ ] 固定输入 canary 完成后核验真实结果，执行自动 30/30 pair 门禁与 Assistant-only 60-query 复核，保留所有缺失及失败证据。
- [ ] canary 通过后，先验证 NFCorpus 的真实 source 级容量；全部样本（含零候选与失败）计入分母，不以补选 canary 的通过率代替每篇 3-pair eligibility。
- [ ] 在正式运行前补齐 v24 query/split 到 RAG/PVS 的接口和开发集端到端验证，再冻结配置与代码并按单 cell 推进正式实验。

当前唯一下一步（待开发）：修复现有 53 号 runner 的 canary 持久化/恢复与 capacity 总量取数并完成离线回归；本次文档修改不构成实现或真实实验已完成的证据。

### 2026-09-07：canary 保存与恢复修复完成（superseding）

- [x] 53 号 `run-canary` 在初始化前建立结果/汇总文件，每条 source/input 完成后原子保存成功或失败证据，并显示、保存进度。
- [x] CLI 支持 `run-canary --resume`；校验固定输入、候选池、source/fact、配置、有效模型与相关代码，跳过已保存条目。已保存失败不得重试，完成的失败运行仍保持 hard-gate 失败。
- [x] 覆盖结果先于汇总落盘、原子替换后尚未更新内存、临时文件写入中断和最终汇总缺失；已完成结果可离线复用，损坏或身份漂移在模型调用前拒绝。
- [x] 明确未落盘条目需要重新执行；在途实际调用/重试次数可能未知，使用 `external_call_counts_complete=false`，不伪造精确调用数或将进程中断记作科学失败。
- [x] 新增 14 项 canary 离线回归；v24、BEIR 与 sibling retry 定向测试合计 160 项（150 passed、10 skipped legacy）。本轮未运行真实模型/API/GPU/Retriever/victim，未修改配置或真实实验产物。
- [x] README 已同步恢复方法和限制；AGENTS.md 继续只维护稳定规则。旧 `luna_attempt1` 及未完成证据保留，不声称修复找回了未落盘的结果。
- [ ] 用已固定输入在新输出目录完成真实 Luna canary，再核验自动门禁与 Assistant-only 问句质量；恢复实现通过不等于真实 30-pair/60-query 验收通过。
- [ ] 在进入 capacity 前修复源池总量取数，之后优先验证 NFCorpus 的真实 source 级容量。
- [ ] 正式实验前补齐 v24 query/split 到 RAG/PVS 接口与开发集端到端验证。

当前唯一下一步：在新输出目录运行固定输入的 BEIR Luna canary 并完成问句复核；中断后沿用同一输入、候选池和输出目录加 `--resume`。本轮已完成代码修复与离线验证，尚未启动该真实运行。

### 2026-09-07：已授权重新运行固定 canary（luna_attempt2）

- [x] 用户要求重新开始后，确认没有重复 Python 进程，并核验固定 `30` 条输入、`10/10/10` 数据集分布与四套候选池。
- [x] 使用修复后的 53 号 runner 启动 `artifacts/v24/development/query_quality_canary_beir_ranked_v2_20260907/luna_attempt2/`；输入 hash 不变，未重新生成输入或候选池。
- [x] 有效模型为 `gpt-5.6-luna`，沿用当前本机 HTTP 转发入口（端口 `8317`）和已配置的采样、预算及重试参数；CUDA 可用，BGE 本地 snapshot 已绑定。
- [x] 18:56（Asia/Shanghai）确认首条结果已经逐条保存；本轮 run fingerprint=`d773e25f097add1523ade620928bea0d96756a885b36c97a468cf66f5af21c54`。保存/进度修复已在真实调用中开始生效。
- [ ] 等待本批全部 30 条输入完成，校验结果 hash、实际模型、自动门禁与终态调用计数；保留所有成功、失败和缺失项。
- [ ] 对实际输出的问句完成 Assistant-only 质量复核；没有 gate-accepted pair 的输入须明确记作问句未提供，不冒充已审核的通过问句。

当前唯一下一步：完成当前 `luna_attempt2` 及其问句复核。本批不启动 capacity、Retriever、victim 或正式实验。

### 2026-09-07：luna_attempt2 完成，质量门禁未通过（superseding）

- [x] 固定 `30` 条输入全部执行并逐条保存，终态时间为 `19:12:28`（Asia/Shanghai）；自动门禁 `28/30`，NFCorpus/SCIDOCS/TREC-COVID 分别为 `8/10`、`10/10`、`10/10`。`failed_hard_gates` 与退出码 `1` 表示完成后的门禁失败，不再等待该进程或重新启动同批运行。
- [x] 实际模型=`gpt-5.6-luna`；逻辑调用 `36`、实际请求 `44`、传输重试 `8`，调用计数完整。真实运行验证逐条保存，未发生中断或使用 `--resume`；旧运行没有保存的完成数和调用数仍未知。
- [x] 校验四套候选池、输入/source/fact、配置、有效模型、代码及 run identity；30 条结果顺序、逐行内容 hash、最终文件 hash 和累计调用量均一致，未出现执行错误条目。
- [x] 保留 `nfcorpus::MED-1011`、`nfcorpus::MED-1015` 的自动失败及空 `selected_pair`；没有补选或重试为通过，其 `4` 个目标问句槽位记为 `not_generated`。
- [x] Assistant-only 复核完成全部 `60` 个槽位：实际问句 `56` 条，`20` passed、`36` failed，未生成 `4`，待复核 `0`；完整通过 pair=`9/30`。逐数据集问句通过数为 `6/8/6`，失败数为 `10/12/14`，未生成数为 `4/0/0`；主要失败项为自包含性 `34` 条。
- [x] 两份复核文件已完成并核验来源/问句 hash、唯一槽位及汇总；状态=`failed_assistant_query_quality_review`、`capacity_sample_allowed=false`。人类复核、独立盲审、agreement 和 Cohen's kappa 均未发生或不可用。
- [x] README 与研究总表同步本轮终态，保留启动、中断和失败历史；AGENTS.md 不添加实验进度。本轮没有改变源代码、构造配置、门禁、预算、科学协议或旧 artifact，也未启动 capacity、Retriever、victim、membership/AUC 或正式实验。
- [ ] 先针对原文指代、未定义统计范围、缩写、版权/OCR 残片及无依据主体补写完成最小开发修复与离线回归，同时排查两条 NFCorpus 的实体校验拒绝；再评估下一轮开发 canary。
- [ ] canary 验收通过后，进入 capacity 前修复源池总量取数；正式实验前补齐 v24 query/split 到 RAG/PVS 接口及开发集端到端验证。

当前唯一下一步（待开发）：以本轮失败问句为依据修复自包含性、源句质量和无依据的主体补写，并完成离线回归；当前 canary 已结束且未通过，不再等待或重试同批失败 source，不进入 capacity。

### 2026-09-07：问句质量开发修复与离线回归完成（superseding）

- [x] 修正把未解析主体改写成 `the reporting company` 等泛称的 prompt；首次与唯一一次语义纠正均可读取同篇 `source_context`，仅用于有原文依据的主体、研究范围与缩写消解，禁入字段仍在模型调用前拒绝。
- [x] 补齐 canonical/query 的泛称、统计总体与缩写检查；明确名称、限定语和同句已给出的研究范围保留。原文没有出现的新主体不能仅凭生成器自评通过。
- [x] query 构造与 fresh-canary 预检共用版权/OCR 单位噪声检查；保留候选池原文、排序、失败和固定 first-8，不读取第 9 个 fact 补足。
- [x] 修复 Q+ 原始 fact 别名误报；两条 NFCorpus 的 `12` 个旧候选不再误报 IBS-GIS 为新实体，但仍因未明确研究指代而被拒绝。Q− 不自动放行只属于原始 fact 的别名，旧结果不改判。
- [x] 新增 `17` 项回归；v24、BEIR 与 sibling retry 定向测试共 `177` 项（`167` passed、`10` skipped legacy），三个修改文件内存 AST 通过。恢复、数据隔离、固定预算、fallback 和候选池校验继续通过。
- [x] 只读结构回放使用 mock 相似度 `0.95`：旧已生成 `28` 对中，拦截先前复核失败的 `19` 对，保留复核通过的 `9` 对；明确是已见开发样本回归，不是新 canary 或独立质量验收。
- [x] 四套候选池、原 30 条 fact、配置、输入及旧运行/复核文件 hash 校验一致；本轮不改写实验 artifact。README 与两份研究总表更新，AGENTS.md 保持稳定规则职责；未提交、未推送、未新建协议或治理文件。
- [ ] 使用修复后的预检准备下一批开发 canary 输入，真实 Luna 生成与逐条质量验收仍待执行；新运行使用新输出目录，不能用新代码原地 resume 旧 attempt。
- [ ] canary 验收通过后再进入 capacity；源池总量取数与 v24 query/split → RAG/PVS 接口仍未修复。本轮 GPU/API/Retriever/victim、membership/AUC 与正式实验调用或读取为 `0`。

当前唯一下一步：准备下一批开发 canary 输入，再按授权范围完成真实生成与逐条复核；当前完成的是代码修复和离线回归，不把旧结构回放当作质量验收通过。

### 2026-09-07：已授权新开发样本 canary 验收（superseding）

- [x] 确认没有遗留 Python 进程，当前配置、修复后代码、有效 Luna profile 与 CUDA 环境已核验；使用本地锁定模型，不安装或下载依赖。
- [x] 在 `artifacts/v24/development/query_quality_canary_beir_contextfix_fresh_20260907/candidate_pools/` 完成 `32` 篇新开发 source 的 GLiNER2 抽取，保留 TREC-COVID `2` 篇零候选并按冻结顺序补取 `2` 篇；`271` 次本地推理、`965` 个候选，旧候选池与失败产物不覆盖。
- [x] `preflight/` 固定 `30` 条输入，三数据集各 `10` 篇，first-8 与 source/text hash 校验通过，历史开发身份无重叠。本批输入 SHA-256=`2a662debf0defa405cfe3ca1136b5ebac68c8fcb47ef8345de7d667d53363770`。
- [x] 运行前明确沿用原六项 Assistant-only 复核口径与 `30/30` 自动 pair、`60/60` query 验收要求；自评、结构门禁和 Assistant 标注不冒充独立人工证据。
- [ ] 在新 `luna_attempt1/` 完成真实 Luna 生成，确认逐条保存、实际模型、结果 hash 和逻辑/实际请求/重试终态计数，所有失败与未生成槽位保留。
- [ ] 完成全部 `60` 个目标槽位的 Assistant-only 质量复核，按数据集报告并记录通过/失败/未生成；本批不中途修改门禁或重试已保存失败。
- [ ] 根据完整验收决定下一步；capacity 总量取数和 v24 → RAG/PVS 接口修复仍未完成，本批不启动正式下游。

当前唯一下一步：执行并完成新开发 canary 的真实生成和问句复核，保留全部结果；通过前不进入 capacity。

- [x] `21:24:49`（Asia/Shanghai）已启动新批次 `luna_attempt1/`，PID=`184324`；初始运行汇总/结果文件建立，run fingerprint=`959a591443853babb80f25620b140612cdfd7b87adc7f2054d181896d399351a`。完整生成和质量复核仍在进行，不能把启动成功记作验收通过。

### 2026-09-07：新开发 canary 完成，质量验收未通过（superseding）

- [x] `query_quality_canary_beir_contextfix_fresh_20260907/luna_attempt1/` 于 `21:56:39`（Asia/Shanghai）完成全部 `30` 篇，终态=`failed_hard_gates`，进程已结束；NFCorpus/SCIDOCS/TREC-COVID 自动通过分别为 `7/10`、`8/10`、`7/10`，合计 `22/30`。
- [x] 首条、中途与终态结果均已真实落盘；没有中断或使用 `--resume`，不声称已完成真实恢复演练。全部失败保留，没有替换 source 或重试已保存失败。
- [x] 实际模型仅 `gpt-5.6-luna`，逻辑调用 `41`、实际请求 `73`、传输重试 `32`，计数完整；`90` 个初始 package、`33` 个纠正 package，符合最多一次纠正，没有 fallback、provider failure 或 execution error。
- [x] 完成全部 `60` 个目标槽位的 Assistant-only 复核：最终问句 `44` 条，`30` passed、`14` failed；`16` 个槽位没有 gate-accepted pair，待复核=`0`。三数据集各 `5/10` 对两问均通过，合计 `15/30`，`capacity_sample_allowed=false`。
- [x] 记录两类待修复问题：标题/数学乱码与缺失前提、文献/实验指代仍会漏检；`titled ...`、存在句 `there`、补语 `that`、`Jacobi-polynomial-based` 的原文派生形式存在规则误报。原文已存在的替换词也造成实际构造失败，不能把所有拒绝都归于误报。
- [x] 四套候选池、source/fact、first-8、输入/配置/代码/profile/run identity 与结果、复核 hash 全部校验一致，逐条调用量和汇总一致。保持 Assistant-only 标注口径，没有独立人工盲审、agreement 或 Cohen's kappa。
- [x] README 与两份总表同步终态，保留既有启动/失败历史；本轮仅生成授权的开发实验及复核产物，没有修改代码、配置或旧结果，没有提交/推送，没有进入 capacity、Retriever、victim、membership/AUC 或正式实验。
- [ ] 先在现有实现中修复指代/派生词校验误报，并补齐标题非命题、数学文本损坏和上下文缺失的检查及反事实原文排除提示，完成定向离线回归。
- [ ] 修复后使用新开发输入与新输出目录验收，不用本批已见样本原地重试为 passed，也不把新旧开发通过率差异当受控提升证据。
- [ ] canary 验收通过后再修复并进入 capacity；v24 → RAG/PVS 接口与开发端到端验证仍待后续完成。

当前唯一下一步（待开发）：依据本批草稿、失败与逐问复核证据完成上述最小代码修复和离线回归；当前真实 canary 已结束且未通过，不再等待进程或进入下游。

### 2026-09-07：指代、派生词与构造完整性修复完成（superseding，离线）

- [x] 在现有 v24 实现中区分存在句/补语/有先行词的定语从句与外指代，支持有原文题名依据的 `titled/entitled`；未放行虚构题名、泛称或任意截断前缀。
- [x] 对有原文依据的空格/连字符、普通名词规则复数和 `-based` 派生作有限兼容；名称、数字和 `source_absence` 保持约束，prompt 明确替换须在整篇原文中缺席。
- [x] query 预检与构造检查覆盖非命题标题、公式转码残片、标题主题被改为报告者、缺失实验/文献/描述对象及数学变量定义；保留完整声明式标题、明确局部范围和 DC/FIO2 等正常表达。
- [x] 新增 `10` 项回归；三个相关测试模块共 `187` 项，`177` passed、`10` skipped legacy，包含既有保存/恢复与 first-8 约束。两个修改的 Python 文件 AST 检查通过。
- [x] 只读结构回放保留原 Assistant-only 复核通过的 `15` 对，拦截原漏过的 `7` 对；具名论文/存在句/派生词草稿的相关误报消除，原文已存在替换、单槽和补造关系等真实失败保留。语义分数与语义判断使用 mock，不能当作新真实质量验收。
- [x] 核验四套候选池 `32` 条 source、固定 `30` 条 fact 的 source/span/first-8/binding；配置、53 号脚本、输入与四份运行/复核结果 hash 不变。旧失败产物、AGENTS 稳定规则与已有脏改动保留，没有新建治理文件、提交或推送。
- [x] README 与两份总表同步当前状态；本轮真实模型/API/GPU、Retriever/victim、membership/AUC 与正式实验调用或读取为 `0`。候选排序、固定预算、scoring、split 和科学协议版本不变，但构造代码身份及可能通过的集合改变，旧 canary 不能用新代码原地续跑。
- [ ] 使用新开发 source、新输出目录完成下一轮真实 canary 生成及逐问复核；当前仍没有修复后的独立验收结果。
- [ ] canary 验收通过后再修复并进入 capacity；v24 → RAG/PVS 接口与开发端到端验证仍待后续完成。

当前唯一下一步：用修复后的代码和新开发样本重新进行 canary 验收，保留既有失败证据；不将离线结构回放记作 canary 通过。

### 2026-09-08：修复后新开发 canary 执行中（superseding）

- [x] 按用户“开始下一步”在新目录 `query_quality_canary_beir_referencefix_fresh_20260908/` 完成新开发抽取；CUDA、本地锁定模型、代码/配置和有效 Luna profile 已核验，没有修改运行代码或配置。
- [x] GLiNER2 共抽取 `31` 篇、`845` 个候选、`250` 次本地推理；保留 `trec-covid::00ajdmac` 的零候选及首轮 `preflight/` 的 `29/30` 不足额证据，按冻结顺序补取 `1` 篇。
- [x] `preflight_attempt2/` 固定三数据集各 `10` 篇，共 `30` 条输入；四套候选池、source/text 身份隔离、原文/span 与 first-8 校验通过。输入 SHA-256=`4dd3bd14fcaa45141f853ff9d1fd56dd8b5e91b0673d109a9f66bd1fc859be2e`，新旧样本身份无重叠。
- [x] `07:31:06`（Asia/Shanghai）启动 `luna_attempt1/`，PID=`202256`；初始和中途结果已保存。run fingerprint=`6e1dcc15dbb945f6aaae7b7c51422e92fde511c7fe0ecb3b6af8ae0bc732d9eb`，实际模型为 `gpt-5.6-luna`；`07:42` 快照已保存 `16/30`、自动通过 `14`，尚未结束。
- [x] 固定使用既定六项 Assistant-only 复核标准；验收期间不调整代码、模型、门禁和预算，不补选或重试已保存失败。
- [ ] 完成全部 `30` 条真实生成，核验终态、逐行/文件 hash、输入/代码/config/profile 一致性和累计实际请求/重试计数。
- [ ] 完成全部 `60` 个槽位的 Assistant-only 复核，保存通过、失败及未选出问句记录；准确区分自动门禁、Assistant 标注与独立人工盲审。
- [ ] 将终态和失败模式同步 README 与两份总表；质量验收通过前不进入 capacity，capacity 总量取数和 v24 → RAG/PVS 接口仍待后续修复。

当前唯一下一步：完成正在运行的新开发 canary 与逐问质量复核；不重复启动本批，不将运行中快照写作最终验收结果。

### 2026-09-08：修复后新开发 canary 已完成且未通过（superseding）

- [x] `query_quality_canary_beir_referencefix_fresh_20260908/luna_attempt1/` 于 `07:51:43`（Asia/Shanghai）完成全部 `30` 篇，进程已结束，终态=`failed_hard_gates`；自动通过 NFCorpus `9/10`、SCIDOCS `8/10`、TREC-COVID `8/10`，合计 `25/30`。
- [x] 首条、中途与最终结果均已保存，没有中断、真实 resume、替换 source 或重试已保存失败；本轮验证逐条持久化，不声称真实恢复演练。
- [x] 实际模型仅 `gpt-5.6-luna`，逻辑调用 `38`、实际请求 `50`、传输重试 `12`，终态计数完整；`90` 个初始 package、`24` 个纠正 package，无 fallback、provider failure 或 execution error。
- [x] 全部 `60` 个目标槽位完成 Assistant-only 复核：`50` 条实际问句中 `26` passed、`24` failed；`10` 个槽位未选出问句，待复核=`0`。两问均通过 NFCorpus/SCIDOCS/TREC-COVID 分别为 `4/5/4` 对，合计 `13/30`，`capacity_sample_allowed=false`。
- [x] 记录 `20` 条 self-containedness 失败，以及无冒号名词性标题、比喻题名被补造谓语和原句病句；题名补充成功案例与仍然缺失的人群、比较基准、治疗/分组范围分别记录。
- [x] 只读定位新误报：`US` 被当作 `us`；题名冒号空格与未识别的 `considers` 导致完整命题被拒；倒装问句中完整题名后的 `to investigate` 未被边界规则接受。保留所有拒绝，不把消除这些误报写成草稿整体质量已通过；目标在补充题名中重复等真实单槽失败继续保留。
- [x] 输入、四套候选池、原文 fact/span/first-8、配置、有效 profile、代码及 run identity 与启动前一致；逐行/文件 hash、候选预算、累计调用数和复核汇总全部核验通过。Assistant-only 不冒充人类盲审；不同开发样本的通过率不解释为受控提升或正式三对/source 容量。
- [x] README 与两份总表同步终态，AGENTS.md 不增加实验进度；本轮没有修改运行代码、配置或旧 artifact，没有提交/推送，没有进入 capacity、Retriever、victim、membership/AUC 或正式实验。
- [ ] 在现有代码中修复上述误报、非命题标题及上下文缺失，补充本批失败的定向离线回归；不要为小修复新增协议/治理层。
- [ ] 修复后使用新开发输入、新输出目录重新验收，保留本批失败；canary 通过后再修复并进入 capacity，v24 → RAG/PVS 接口仍待后续完成。

当前唯一下一步（待开发）：修复 `US/us`、题名边界及非命题/上下文检查并完成定向回归；本批真实 canary 和逐问复核已全部结束且未通过，不再等待进程或进入 capacity。

### 2026-09-08：US、题名边界及观察范围修复已完成（superseding，离线）

- [x] 在现有 v24 实现中修正 `US/us`、有局部先行词的反身结构、题名标点空白及完整题名后的倒装不定式边界；未放行虚构/任意截断题名、实体槽外重复或真实第一人称。
- [x] 补齐无冒号名词性标题及比喻题名被改成行动主体的检查；使用已识别题名的检查副本，保留完整谓语和有正文支持的关系。
- [x] 补齐数字词计数、临床观察范围、参与单位、零事件、比较对象、治疗分组、day 0 和相对时间检查；百分比统计保留相邻原文明确给出的分析子集限定，研究名称不能替代这些细节。
- [x] 初始/纠正 prompt 与 Q+/Q− 独立校验同步；覆盖原句保护方向含混的病句，未增加调用预算、模型或新语义 API。
- [x] 新增 `12` 项回归并扩充正反例，最终三个相关测试模块 `199` 项：`189` passed、`10` skipped legacy；两个修改 Python 文件 AST 通过，既有预算、隔离和保存/恢复测试继续通过。
- [x] 只读结构回放保留本批原通过 `13` 对、拦截漏过 `12` 对；index `18/28/29` 的 `18` 个草稿相关引用/表面误报消除。语义分数和判定使用 mock，旧真实运行和 Assistant-only 结论不改判，不计作新 canary 通过。
- [x] 本批 `21` 个实验文件及 runner、配置、AGENTS.md hash 不变；代码身份已改变，不能用新代码按旧运行身份 resume。README 与两份总表同步，未新增协议/治理文件，未提交或推送。
- [ ] 使用新开发 source、新输出目录进行修复后的真实 canary 生成和逐问复核；本轮真实模型/API/GPU、Retriever/victim、membership/AUC 调用或读取为 `0`。
- [ ] canary 通过后再修复并进入 capacity；v24 → RAG/PVS 接口和开发端到端验证仍待后续完成。

当前唯一下一步：以新开发输入和新输出目录验收本轮修复；当前完成的是代码与离线回归，既有失败证据保留，尚未进入 capacity。

### 2026-09-08：记录 chunk 原则并准备新开发 canary（superseding）

- [x] 记录后续原则：短文整篇单块、长文根据实际 tokenizer 长度评估固定多块；在 source 内选择互补事实，同源 chunk 同组，候选与查询总预算按 source 固定，统计单位仍为 source。
- [x] 三套源池的词数分布已只读检查，详见研究总表；词数不是模型 token 数，不能据此直接判定模型截断或效果优劣。本批保持现有一个 BEIR document 对应一个冻结 chunk。
- [x] 用户已授权使用新开发样本、新输出目录完成真实 canary；Conda `mia_model` 与 CUDA 可用。新根目录为 `artifacts/v24/development/query_quality_canary_beir_scopefix_fresh_20260908/`，不改写旧失败运行。
- [x] 完成 `32` 篇新开发 source 抽取，`800` 个候选、`228` 次本地推理；与历史 source key/source hash/normalized text hash 无重叠。TREC-COVID 两篇零候选和首轮 `28/30` 不足额预检保留，按冻结顺序补选两篇。
- [x] `preflight_attempt2/` 固定 `30` 条输入，三数据集各 `10` 篇；原文/span/first-8 与四套候选池校验通过。输入 SHA-256=`3d98e354867bbe2b8e190b544f6bbb0c369cca50bb91105ccb8f122c50d413be`。
- [x] `09:49:32`（Asia/Shanghai）启动新 `luna_attempt1/`，PID=`258660`，实际模型=`gpt-5.6-luna`；run fingerprint=`93523d2f7d525ab3917ef3e52b12156bee09beeee2a4d36f88a15655e71fbfa4`。会话中断后后台仍运行，`09:56:33` 已保存 `9/30`、自动通过 `8`；未重复启动或使用 `--resume`。
- [ ] 完成全部真实生成，核验逐条保存、模型与输入/代码/config/profile 身份及最终调用计数；当前快照不作最终验收结果。
- [ ] 按既定六项标准复核全部 60 个目标槽位，分别记录通过、失败和未选出问句；验收要求仍为自动 30/30 pair、Assistant-only 60/60 query。
- [ ] 将完整结果同步 README 和两份总表；canary 通过前不进入 capacity，后续另行落实长文策略及尚未完成的 capacity 取数、v24 → RAG/PVS 接口。

当前唯一下一步：完成本批新开发 canary 及逐问验收；本轮不调整 chunk、固定预算或质量标准，不把启动和中途结果写作验收通过。

### 2026-09-08：scopefix 新开发 canary 及逐问验收完成（superseding，未通过）

- [x] 新 `luna_attempt1/` 于 `10:19:22`（Asia/Shanghai）完成全部 `30` 篇，终态=`failed_hard_gates`；NFCorpus/SCIDOCS/TREC-COVID 自动通过分别为 `8/5/5`，合计 `18/30`。会话中断期间后台运行和逐条保存继续，未重复启动或使用 `--resume`。
- [x] 实际模型仅 `gpt-5.6-luna`；逻辑调用 `43`、实际请求 `52`、传输重试 `9`，计数完整。`90` 个初始 package 与 `39` 个纠正 package 符合预算；无 fallback、provider failure 或 execution error。
- [x] 全部 `60` 个目标槽位完成 Assistant-only 复核：实际 `36` 条问句中 `16` passed、`20` failed；`24` 个槽位未选出问句，待复核=`0`。两问均通过 NFCorpus/SCIDOCS/TREC-COVID 分别为 `4/3/1` 对，合计 `8/30`；`capacity_sample_allowed=false`，没有独立人工盲审或 Cohen's kappa。
- [x] 记录时间、比较人群、视频/文献/政策简报及回归研究范围缺失；粘连词与患者/病因表达仍影响自然性。完整题名的新增实体/指代拒绝列为疑似误报，缩写展开、recently 和标题片段等真实失败分别保留。
- [x] 荷兰语输出、canonical 为疑问句、全称保留但只改括号缩写和数值关联问题均保留诊断；不在本批临时新增语言、反事实真值或一致性否决。
- [x] 输入、候选池、模型、代码/config/profile/run 身份、逐行/文件 hash、候选预算及调用总量核验通过；运行前 `39` 个受保护文件 hash 未变。复核文件已保存，README 与两份总表同步；chunk 原则仅记录，运行代码/配置/切分未改，未提交或推送。
- [ ] 先定位题名/缩写检查误报并完善时间、比较对象、研究范围及原文表达的开发回归；标题、语言、缩写变换策略如需改变，先明确其开发设计，再验证。
- [ ] 修复后使用新开发样本和新输出目录验收；不原地重试本批失败。canary 通过后再修复并进入 capacity，v24 → RAG/PVS 接口和长文策略仍待后续处理。

当前唯一下一步（待开发）：依据本批完整证据进行最小修复与离线回归。真实 canary 和逐问复核均已结束且未通过，不再等待进程，不进入 capacity。


### 2026-09-08：原始 fact / 完整 fact 的 18 篇对照准备完成（superseding）

- [x] 将下一步从不断叠加文本规则改为固定旧开发样本的受控归因；A/B 仅改变 fact 输入，原模型、prompt、目标实体、校验器、候选/纠正预算保持一致。
- [x] 18 篇按数据集各 4 个上下文失败与 2 个历史合格对照固定；普通输入位于 `artifacts/v24/development/fact_context_ablation_20260908/reference_facts.jsonl`，保留原文 span、池身份、Assistant 参考命题和逐段证据。
- [x] 11 条完成补全，6 条对照保持原句；S7/MED-1051 因摘要没有明确比较人群而不可可靠补全，保留其 A，B 明确拒绝且零生成调用。仍报告 18 篇/36 条件，可完整配对上限 17 篇，不换 source 补齐结果。
- [x] 4 个已见坏输入完成离线检查：C27、C12、R4 被现有预检拒绝；S23/Wake Forest 标题仍漏过。记录问题，不在同一 A/B 中调整门禁。
- [x] 53 号脚本支持 `preview-fact-ablation`、`run-fact-ablation` 与 `summarize-fact-ablation`；复用现有保存/恢复，保存所有草稿，恢复不重新抽取已尝试轮次；诊断完成不标为正常 canary passed。
- [x] 分层报告覆盖 canonical 来源支持/完整性、问句六项标准、自动误报/漏报、首次生成可用性与最终选择质量，并按 source 配对、逐数据集及 macro 报告；Assistant 标注不冒充独立人工审核。
- [x] 定向 unittest `210` 项：200 passed、10 skipped legacy；AST、CLI 与 diff check 通过，8 个关键 prompt/gate/抽取函数与 HEAD 一致。
- [ ] 执行真实固定 A/B：设计最多 72 次逻辑生成，本套输入因不可补全 B 条件最多 70 次；传输重试另计。API/GPU/正式调用当前均为 0，`luna_attempt1/` 尚未启动。
- [ ] 对所有初始和纠正候选做 Assistant-only 分层复核，区分合理拒绝、语义问题和校验误报；按对照证据决定后续事实补全或共享模板改造。

当前唯一下一步：取得本批真实 API 执行的明确许可后，检查 CUDA 并运行已固定对照和分层复核。自动两阶段构造、共享模板、别名策略及新样本验收等待对照结果；不改变正式三对六问、chunk、scoring 或科学协议版本。

### 2026-09-08：按用户要求补齐真正两阶段开发路径（superseding）

- [x] 核查实际代码：此前的 A/B 诊断入口不等于自动两阶段流水线；将这一区别明确记录，不回写历史完成状态。
- [x] 在现有 v24 模块接通原始 source/span 校验、完整事实构造与逐字证据、单独原文支持/完整性核验，再固定 canonical 和目标槽。
- [x] 问句阶段只选择替换实体和一个共享模板，由代码填出 Q+/Q−；逐问单独核验，最多一次纠正，纠正不得重构事实。自报 grounding 不能替代两层核验。
- [x] 明确别名单槽拒绝；补齐外层题名引号与固定命题中已有 `that` 从句误报修正，新路径开启、旧 A/B 行为保持。
- [x] 53 号脚本新增 `preview-two-stage-canary` / `run-two-stage-canary`，限定开发池、新输出目录、每篇一个指定 fact；当前 30 篇最多 180 次逻辑请求，传输重试另计。终态与自动质量、执行不完整分别报告，capacity 始终不放行。
- [x] 复用现有保存/恢复机制保存构造、两层核验及全部问句草稿；初始/纠正候选保存展开后的两问。已存响应恢复复用，已开始但无持久响应的阶段不重抽，执行问题不伪装成科学质量拒绝。
- [x] 新增 15 项两阶段离线测试；完整 v24/BEIR/rate-limit 定向回归 `225` 项，`215 passed / 10 skipped legacy`。AST、CLI 与 diff check 通过；原 18 篇 A/B 输入只读核查通过，原 prompt 和默认校验路径保留。
- [x] 同步 README 和两份总表，不新增协议/治理文件，不修改正式配置、chunk、scoring、历史产物、AGENTS.md 或既有 v23 用户资产；未提交/推送。
- [ ] 执行原方案第一轮固定 18 篇/36 条件 A/B，并复核全部初始/纠正草稿，分别报告首次质量、最终选择、合理拒绝、校验误报及逐数据集/source 配对归因。该轮尚未调用真实模型，当前输入最多 70 次逻辑生成。
- [ ] 根据受控对照审视新两阶段实现，再用新开发样本、新输出目录运行其真实 canary 与 Assistant-only 逐问验收；当前代码测试不作效果改善结论，也没有独立人工盲审。

当前唯一下一步：在对应真实 API/GPU 运行获得明确授权后，先执行固定 18 篇 A/B 和分层复核；随后才进入新样本两阶段验收。本轮真实 API、GPU 推理、Retriever、victim、membership/AUC 和正式实验调用均为 0，不进入 capacity/formal。

### 2026-09-08：固定 18 篇 A/B 已启动（superseding，运行中）

- [x] 用户明确要求开始已说明的下一步；执行范围为固定 A/B 生成及全部候选复核。
- [x] 输入预检通过：18 篇、36 条件、10 套开发候选池，原始身份与参考证据一致；1 个 B 不可补全，完整配对上限 17 篇，最多 70 次逻辑生成，传输重试另计。
- [x] 确认 Conda `mia_model`、CUDA PyTorch `2.11.0+cu130` 与 RTX 4060 Laptop GPU；启动前无其他 Python 实验进程，有效 Luna 模型为 `gpt-5.6-luna`。
- [x] `20:36:58` 启动 PID=`42604`，输出为 `fact_context_ablation_20260908/luna_attempt1/`，未使用 `--resume`；首条结果已保存。代码、配置、固定输入和历史产物不修改。
- [ ] 完成全部 36 条件，核验模型 ID、原始与逐条 hash、候选预算、完整请求/重试统计及终态。
- [ ] 复核全部初始/纠正候选并保存 Assistant-only 分层标注；按 source 配对、逐数据集与 macro 区分首次候选可用性、最终选择质量和校验器误差。
- [ ] 依据对照证据决定后续开发方向；本批不自动进入两阶段 fresh canary、capacity 或正式实验。

当前唯一下一步：完成本批真实 A/B 与全部候选复核，再保存归因报告及最终状态；不根据运行中结果调整任何实验因素。

### 2026-09-09：固定 A/B 离线复核与归因已完成（superseding，原执行缺失保留）

- [x] 核验本批已结束：36 条件结果行、29 个自动 selected、34 次成功初始生成和11次纠正，保存135候选/270问句。原运行终态 `completed_diagnostic`，无在途输入，未补跑/重试。
- [x] 核验 S7/B 参考不可补全、R21/A 初始 `JSONDecodeError` 无可解析草稿；保留18篇完整清单，主配对仅16篇（5/6/5）。R21/A 不记质量失败，S7/B 不猜测比较人群。
- [x] 复检全部135条既有 Assistant-only 标注，待评已保存候选=0，原标签未改写。source/span/first-8、10套开发池、输入/配置/代码/profile/fingerprint、阶段与结果hash通过；现有汇总函数重算与原报告完全一致，原文件前后hash不变。
- [x] 分开保存离线完成与原执行缺失：原 `incomplete_execution`、`generation_complete=false`、整批 macro=null 和 `external_call_counts_complete=false` 保留。记录逻辑/物理/重试=`46/46/0`，增量自洽但不宣称独立审计确认完整。
- [x] 保存逐数据集与source配对分析：首次可用性 `8/16→16/16`，最终质量 `9/16→14/16`；完整配对macro分别 `50.00%→100.00%`、`55.56%→88.89%`。首次精确p=`0.0078125`（两指标Holm=`0.015625`），最终p=`0.125`；有区间、缺失敏感性与小样本限制。
- [x] 区分补全与生成波动：上下文失败层n=10，首次 `3→10`、最终 `4→8`；输入不变控制n=6，首次/最终 `5→6`，C16差异不算补全收益。不宣称自动两阶段、容量、泛化或AUC已获验证。
- [x] 完成归因：39个质量失败候选按互斥层次为原文不支持3、支持但不完整27、canonical好但query失败9；30个质量通过却自动拒绝分为纯文本误报20、混合1、其他构造约束9，不一律放行。另15个候选自动接受却质量失败，对应5个坏selected；4个条件有好候选却被门禁完全拦截。
- [x] 保存[分析报告](../artifacts/v24/development/fact_context_ablation_20260908/offline_review_20260909/analysis-report.md)、统计附录、两张真实图、图目录、机器统计和可复算离线配方；同步README与两份总表。未修改实验源码/配置/历史产物，未新建协议，未提交/推送，本轮新增真实调用=0。
- [ ] 依据明确归因最小修复：R16题名末句点，C8/S12合法that从句，C10因果since，R0/C16/R24助动词和并列问句，以及JSON解析失败原响应安全持久化；先复用现有两阶段能力，完成定向离线回归。
- [ ] 开发回归完成后，用新开发source和新输出目录真实验收两阶段全链路与Assistant-only问句质量；本轮没有授权或启动该真实执行，不把同模型核验称为独立人工盲审。

当前唯一下一步：在现有实现内完成上述最小开发修复及离线回归。本批A/B离线工作已结束，不再等待、不原地重试为通过，不进入capacity/formal；后续新样本真实模型/API/GPU执行须对应明确授权，容量取数和v24→RAG/PVS接口仍为后续待办。

### 2026-09-09：A/B 归因修复完成，等待新样本质量验收（superseding）

- [x] 在现有校验器修复 R16 题名末标点、C8/S12 合法 that 从句、C10 因果 since；保留改词/任意截短题名、外指代、日期/事件时间起点等拒绝边界。
- [x] 在现有生成/纠正/核验 prompt 与表面门禁修复 R0/C16/R24 助动词及并列语法；保留完整事实、单槽约束和固定预算，兼容合法嵌套从句与省略并列。
- [x] 在既有 summary 中先保存允许的响应正文/元数据再解析；凭据脱敏、异常只记类型，解析前中断可离线恢复，已保存失败不重发，磁盘错误中止运行。原 R21/A 缺失响应不补填。
- [x] 新增 9 个正式回归方法；最终 234 项定向测试完成（224 通过、10 项既有跳过），CLI help、配置校验、内存 AST 与空白检查通过。mock 调用不计真实运行。
- [x] 135 个旧候选只读文本回放：消除 21 个候选的文本误报，新增拦截 12 个语法缺陷候选，对原合格 96 个候选无新增文本误拒；不放宽其他角色/构造约束，不重算 selected 或修改旧标签。
- [x] 保存可匹配旧 A/B hash 的两份源码 ZIP；原有 14 个实验/分析文件 hash 不变。修复后 runner/screening hash=`389526a5b98844ac4547c01b2f398cc064901b167c1a61f7337d2f218b043e7a`，配置未变；源码快照与详细验证见研究总表本日条目。
- [x] 同步 README 与两份总表；无新协议、freeze、manifest 或治理层，无 API/GPU/Retriever/victim 真实调用，无提交/推送。
- [ ] 获得对应真实模型/API/GPU 授权后，以新开发 source、新输出目录运行两阶段完整链路及 Assistant-only 逐问复核。当前代码回归不表示自动事实补全或最终 query 质量已经通过真实验收。

当前唯一下一步：新开发样本的两阶段真实质量验收（尚未启动）；本轮本地修复和离线回归已完成。旧 A/B 不原地重试，不进入 capacity/formal；capacity 总量取数和 v24→RAG/PVS 接口仍待后续开发。


### 2026-09-09：新开发两阶段真实 canary 已获授权并开始准备（superseding）

- [x] 用户明确授权本批新样本两阶段真实验收，并要求继续；本次无需再次请求同一 API/GPU 授权。
- [x] 确认固定配置/代码、Luna 模型身份与 CUDA 环境，使用新目录 `query_quality_canary_two_stage_fresh_20260909/`；保留既有未提交资产。
- [x] 建立新开发候选池：NFCorpus 20 篇池只取前 10，SCIDOCS 10；TREC-COVID 10+2+1，3 篇零候选按原规则顺序补选，第一次不足的预检保留。
- [ ] 固定三数据集各 10 篇输入并通过两阶段 preview，核验 source/text 排除、候选池及模型/代码身份。
- [ ] 执行一次两阶段真实 canary，保存完整阶段响应、失败/缺失及请求统计；不因质量失败增加轮次或换样本。
- [ ] 完成 60 个目标问句槽位的 Assistant-only 复核，区分事实支持/完整性、问句忠实性和构造约束，汇总逐数据集及 macro。

当前唯一下一步：完成预检并执行本批两阶段真实 canary 与逐问复核；不进入 capacity/formal，不将自动或 Assistant 标注称为独立人工盲审。


2026-09-09 启动补记：第二次预检与两阶段 preview 已通过，固定输入 30 篇（每数据集 10），SHA-256=`2bdcf77720525f1aca5d06f11829f2630d999f66be05df972ba73476f27b40d2`。本批检查了 TREC-COVID 13 篇，其中 3 篇零候选；按顺序得到 10 篇非空输入。5 个候选池共构建 43 篇、GLiNER2 推理尝试 342 次；NFCorpus 额外 10 篇不进入本批 Luna。真实运行于 10:27:34（Asia/Shanghai）以隐藏后台 PID=102136 启动，输出 `luna_attempt1/`，日志位于本批根目录。首条结果和阶段响应已逐条保存，实际返回模型为 `gpt-5.6-luna`。当前唯一下一步：完成这一个运行并逐问复核；中途不改代码/配置、不重抽失败输入。


### 2026-09-09：新开发两阶段真实 canary 与复核完成（superseding，验收未通过）

- [x] 完成30篇固定输入、5个候选池与预检；保留TREC-COVID三篇零候选及首次不足的预检，未替换生成/质量失败。
- [x] 完成一次真实两阶段运行，10:49:14终态completed_two_stage_diagnostic；30/30输入完成、12/30自动通过、执行缺失0、计数完整、后台进程结束。
- [x] 核验84逻辑/85物理请求/1传输重试；30构造+18事实核验+15初始生成+15问句核验+3纠正+3纠正核验。模型唯一gpt-5.6-luna，全部阶段/结果hash正确，84响应离线重解析一致。
- [x] 完成30 source复核及60目标槽位登记：交付24问句，16通过/8失败；36槽位未交付，其中6有草稿、30未进入生成，待复核0。完整pair质量8/30（NFCorpus3/10、SCIDOCS4/10、TREC-COVID1/10），自动分别5/10、5/10、2/10。
- [x] 区分9篇别名/缩写结构阻断、3篇不可用事实、3篇事实核验拒绝、3篇query阶段拒绝；自动选中后4篇失败来自实验上下文遗漏或删掉固定事实属性。德语门禁与目标别名分歧单独记录，不无条件放松构造约束。
- [x] 保存[验收归因报告](../artifacts/v24/development/query_quality_canary_two_stage_fresh_20260909/luna_attempt1/canary_acceptance_report.md)、逐source/逐query表及汇总；记录source层面区间与非随机开发样本限制，不与旧批次作因果比较。
- [x] 原生完成态resume只读身份校验通过，代码/配置快照未变，旧A/B保持原样；同步README及两份总表。无源码修改、提交/推送、Retriever/victim或正式调用。
- [ ] 依据本批证据修复目标别名/指代约定、事实范围核验、canonical属性保留和语言支持，先做离线回归。

当前唯一下一步：上述开发修复及离线回归（尚未开始）；本批真实canary和Assistant-only复核已全部完成且未通过。不原地重试，不进入capacity/formal；后续新样本真实验收另行明确，不把本次授权扩大为无界重跑。
### 2026-09-09：Luna-only fresh A/B 开发实现

- [x] 接通 Luna-only Stage A：全文 source 输入、最多 8 个 slot、不补满、exact-span deterministic grounding、严格单槽与 supporting-evidence 边界。
- [x] 接通现有 fixed-fact/shared-question Stage B；保留 GLiNER2 comparator 和默认 v24 adapter，不创建 v25。
- [x] 增加 fresh 30 source-first A/B 的准备、preview、运行、恢复与汇总入口；输入按三数据集各 10 篇固定，两臂共享 source order，历史 source key/hash 排除，零候选保留。
- [x] 增加 source-level usability repeatability 汇总；candidate overlap 仅 diagnostic；promotion threshold 暂为空。
- [x] 定向回归 `tests.test_restoration_first_v24`：226 passed、10 skipped legacy；无真实 Luna/Retriever/victim/formal 调用。
- [ ] 待单独授权后运行 fresh 30 A/B；运行前先完成三套 fixed-source GLiNER2 pool 构建，再执行 preview 和真实 Luna。结果不得据此自动 promotion 或进入 formal。

### 2026-09-09：Luna-only 实现回归计数更正（superseding）

- [x] 修复 53 号 runner 的 `_luna_ab_settings` 缩进导入错误；`tests.test_restoration_first_v24` 最终为 224 passed、10 skipped legacy（共 234 项），v23 fact-layer 定向测试 7 passed。
- [x] AST、CLI `--help`、`validate-config`、`git diff --check` 通过；本轮只做代码/文档回归，没有真实 Luna、GPU、Retriever、victim 或 formal 调用。
- [ ] 待单独授权后运行 fresh 30 A/B；先完成三套 fixed-source GLiNER2 pool 构建，再执行 preview 和真实 Luna。结果不得据此自动 promotion 或进入 formal。

### 2026-09-09：fresh 30-source Luna-only A/B 已启动

- [x] 固定 source-first 输入 30 篇（三数据集各 10），输入 hash=`97bac55a4e8adb7d1f57f8823777f2ff16e5aa1588e3ef7d9f357ab2bbec46e9`；repeatability runs=2，共 120 个条件。
- [x] 完成三套 fixed-source GLiNER2 pool 与离线校验；pool hash 分别为 NFCorpus=`8398d2d1f199fe25d2569a74d0ecc3fd3ca6a55ab271b5b6c6f269812a4bdbb1`、SCIDOCS=`b5eea20e97d577b3c3bb9016a88b3366b9cc746ec54531e44c4bc601957390f2`、TREC-COVID=`92070f5b9d3a32135fe4f107e93d2121fe55e72c28caac515a9e84ee10e53299`。
- [x] Preview 通过，run fingerprint=`8015ee85b2ec48cd480d88538a76f8b66304ed48cb96f1f103311df1c740cc65`；后台输出为 `artifacts/v24/development/luna_only_ab_fresh30/attempt1/`，支持 checkpoint/resume。
- [ ] 等待 A/B 运行终态与 source-level usability stability 汇总；candidate overlap 只作 diagnostic，promotion threshold 仍为空，不进入 capacity/formal。

### 2026-09-09：fresh 30-source A/B 交接到用户续跑

- [x] 后台已保存 77/120 条结果后停止，保留原 attempt1 checkpoint、结果和阶段草稿；无新 attempt、无换样本、无配置/代码变更。
- [x] 确认第 78 条在途 `verify_fact` 没有持久化响应；resume 不重发该请求，保守记录为 `execution_incomplete` 后继续后续条件。
- [ ] 用户使用同一 input、三套 candidate pool、同一 output-dir 加 `--resume` 完成剩余条件；终态需报告 execution-incomplete count，不得把缺失条件当作完整 A/B。

### 2026-09-10：Luna-only PCV 简化方案 B 本轮完成（superseding）

- [x] 依据用户冻结的方案，在现有 v24 模块/config/53 号脚本中实现独立 direct 路径；本条替代历史事实补全、多阶段核验和旧 A/B 续跑待办，历史代码与结果保留。
- [x] 每 source 一个 frozen chunk、一次 Luna 调用、0–8 个四字段候选；prompt 不读取 membership/检索/victim/PVS/AUC/formal，明确要求 chunk 足以确定反事实为假，不能以 counter 未出现代替真值判断。
- [x] 实现 exact claim/original、明确单槽、counter 不同、唯一模板占位符、代码实例化和 schema/预算/source identity gates；按规范化 claim/slot 去重，允许同 claim 多 slot，按返回顺序前三对停止。不足三对记录不足，不补抽、不 repair。
- [x] 新路径绕过 canonical/evidence 扩展、完整事实修复、独立 fact/query verifier、semantic correction retry、correction_eligible 和 unique restoration gate；GLiNER2/ranking v2 与旧入口保留。
- [x] 新增 18 项测试通过；定向回归 266 项（256 passed、10 项既有 legacy skipped），AST、validate-config、preview 和 diff 空白检查通过。
- [x] 完成一次真实 8-chunk fixture smoke：6 候选/6 pair，按 source 为 1/1/1/2/0/0/0/1；eligible=0/8，全部保留三对不足。代词、列表、真假无法确定三个负例返回空列表，无额外生成；不是 BEIR 通过率或容量估计。
- [x] 完成 8-source、6-candidate Assistant-only 诊断，保存[报告](../artifacts/v24/development/luna_only_direct_smoke_20260910/attempt1/implementation_smoke_report.md)与[逐条诊断](../artifacts/v24/development/luna_only_direct_smoke_20260910/attempt1/assistant_diagnostic_review.json)，展示实体/数值/日期/同 claim 多 slot/三类 skip/无 restoration 构造门槛。原 summary 未回写质量通过。
- [x] 核验 8 个原始响应的解析、构造回放、prompt/source/模型/代码配置身份和结果 hash；完成态 resume 在 API client 禁用条件下通过。逻辑/物理/重试=8/8/0；token=6,052 input、1,627 output；累计请求耗时126.973秒；执行缺失与无效输出均0。
- [x] 明确现有 PVS 的 exact correction/非空 correction parser/字符串布尔评分局限；本轮只移出 construction 职责，主公式不改，连续语义恢复留作后续独立评分事项。
- [x] 同步 README 和两份总表，保留全部旧资产；PVS 三份源码与旧 fresh30 两份结果的保护 hash 未变。未新增 v25、修改正式约束、提交或推送；收尾新增 API=0，GPU/Retriever/victim/formal 调用=0。

当前唯一下一步：本轮完成并停止，等待新的任务指令。不自动继续 fresh30、capacity 或 formal；正式 2250 target、3 对/6 问、数据集、split 与 AUC/TPR@1%FPR 保持。

### 2026-09-10：六篇真实 BEIR 验证与上下文依赖修复完成（superseding）

- [x] 按用户授权固定三个数据集各两篇未使用source；保留原chunk、冻结顺序及零候选，不根据质量补选。输入source_records.jsonl已纳入现有开发身份发现规则，未修改源池或formal split。
- [x] 完成一次真实Luna运行：6/6 source、16候选、9个自动pair、2/6自动达到三对；6/6/0次逻辑/物理/重试，5,871 input及10,200 output tokens，累计197.766秒。无执行缺失、无效JSON或额外生成。
- [x] 完成全部16候选的Assistant-only复核，包括6个早停后未处理草稿。已选9对中6个明确上下文失败、3个反事实/时间语义unconfirmed；确认满足三对的source为0/6。原自动状态保留，不将unconfirmed当作独立人工真值。
- [x] 保存[验证与修复报告](../artifacts/v24/development/luna_only_direct_beir6_20260910/offline_review_20260910/beir6_validation_and_context_fix_report.md)、[逐条诊断](../artifacts/v24/development/luna_only_direct_beir6_20260910/offline_review_20260910/assistant_diagnostic_review.json)与修复前代码快照。旧响应/summary、选择顺序、失败与不确定性均保留。
- [x] 仅收紧现有build_luna_direct_prompt的自包含要求：隐藏标题/前后文仍须明确主体，our→the不能当消解指代，不完整claim全部slot跳过，禁止借标题或拼句修复；保留同claim局部先行词及模板中的明确主体。
- [x] 新增两项定向测试，direct路径20/20通过；定向回归268项（258 passed、10项既有legacy skipped），40.096秒，AST/配置/空白检查通过。确定性gates、schema、返回顺序、预算、PVS和历史路径未改，无新版本或verifier。
- [x] 同步README和两份总表。本轮修复新增真实API=0，没有提交、推送、fresh30或formal。新prompt尚未有真实效果证据；prompt/code身份已变，旧attempt不使用新代码原地resume。
- [ ] 另行明确新prompt小规模真实验收的范围后执行；保持三对预算和反事实有效性要求，不将mock或旧输出当作修复后生成结果。

当前唯一下一步：修复后prompt的小规模真实验收（尚未启动）；本轮代码修复、本地测试及六篇旧批复核已经完成。

### 2026-09-10：同批六篇修复后真实复测完成（superseding，质量未通过）

- [x] 按用户授权复用同一六篇frozen chunk和顺序；预检确认input/config/profile一致、使用修复后Prompt，输出到新的context_fix_attempt1，保留旧attempt。
- [x] 六次Luna请求全部完成；候选0/1/2/3/0/4，共10个，自动pair0/1/2/3/0/3，共9对；自动eligible=2/6。9个候选处理、拒绝0、早停草稿1，无执行缺失或无效JSON。
- [x] 核验logical/physical/retry=6/6/0，实际gpt-5.6-luna，tokens=7,275 input/9,229 output，累计181.685秒。用户中断后的续作只有离线复核，没有重复调用。
- [x] 复核全部10候选及两个空输出；已选9对6 failed、3 unconfirmed，全部候选7 failed、3 unconfirmed，确认三对source=0/6，待复核0。unconfirmed明确为证据不足，不当作独立人工标签。
- [x] 对比旧症状：our proposed framework数值候选及MED-1114 OR候选未重现；隐式方法范围、相对时间、开放集合/替换错误性和一个量词范围歧义仍在。保留同claim多slot和句内有先行词的代词；未增加语义gate或restoration要求。
- [x] 完成source/prompt/model/结果身份、六响应重解析与选择回放、九对shared-template及禁用client完成态resume检查，新旧原始结果hash不变；代码与配置快照保存。
- [x] 保存[完整复测报告](../artifacts/v24/development/luna_only_direct_beir6_20260910/context_fix_attempt1/context_fix_retest_report.md)和[逐条Assistant诊断](../artifacts/v24/development/luna_only_direct_beir6_20260910/context_fix_attempt1/assistant_diagnostic_review.json)，同步README与研究总表。原summary和旧证据未回写语义通过。

当前唯一下一步：交付本批未通过结论与失败证据，本批到此停止。后续是否继续修复现有Prompt由新的任务指令确定；本轮没有修改代码/Prompt/PVS、增加generation、运行fresh30/capacity/formal或创建v25。

### 2026-09-10：简化自然语义与句内自包含判据（superseding，仅设计）

- [x] 按用户要求只整理方案和Prompt文本：自包含回归“句内能理解谁/什么做了什么”，不因缺少论文/方法/模型/研究专名拒绝。
- [x] 更正上一轮过严口径：句内完整的graph-cut或parent-child关系可作为claim；many applications→no applications按正常语义是明确对立，不再寻找极端scope解释。旧复核标签、原始响应和报告保留，不重写历史通过数。
- [x] 保留明显未解析话语指代和无绝对时间锚点的相对时间skip；不repair、不补标题、不拼句。主要检查同角色slot替换是否在该claim自然语义下明确为假；非穷尽uses/including/association/extracts关系不能仅凭A成立判B为假。
- [x] 在研究总表追加完整固定Prompt设计、最小语义/结构责任和数据流；仍为一次Luna、0–8候选、返回顺序、claim/slot去重、前三对停止，不足不补抽。
- [x] 明确construction与PVS职责：不预测victim恢复、不加入unique restoration或第二个verifier；PVS与正式评估保持。README区分新设计、现有运行时及旧复测结果。
- [ ] 后续实现时替换现有build_luna_direct_prompt的相关文字并更新对应测试；本轮按用户范围不执行。

当前状态：方案与Prompt设计完成，运行时尚未更新。旧批0/6只属于旧口径，不代表新设计已验证；本轮新增API=0，不启动新实验、不修改PVS、不创建v25。当前工作到此停止。

### 2026-09-10：自然语义 Prompt 接入与本地验证完成（superseding）

- [x] 完成上一条待办：在现有 `build_luna_direct_prompt` 接入定稿 Prompt。只改 Prompt 文字，不新增架构、配置、语义 gate、verifier、repair 或 restoration requirement。
- [x] 在既有测试文件更新三个 Prompt 测试并新增两个 mock 测试，覆盖描述性主体、正常程度/方向/数量对立，以及无锚点时间和非排他关系要求；明确 mock 不代表实际语义筛选效果。
- [x] direct/smoke 22/22通过；定向回归270项中260 passed、10项既有 legacy skipped。22项是270项的子集，不累加计数。
- [x] `validate-config` 通过；六个旧响应可解析，九对旧选择结构回放一致。新 Prompt hash 均改变；新代码在 API 客户端初始化前拒绝 resume 旧 attempt，旧产物不变。preview 仅为 prepared_diagnostic，没有新生成。
- [x] 另存十个旧候选的新口径 Assistant-only 复核：全部4有效/4不合格/2未确认，原选中九对4/3/2，1/6 source具备三对确认有效 pair；保留原自动九对/2 source eligible及旧复核，不以重评变化声称新 Prompt 改善。
- [x] 保存[本地验证报告与实际问句](../artifacts/v24/development/luna_only_direct_beir6_20260910/natural_semantics_local_review/local_validation_report.md)、[逐候选诊断](../artifacts/v24/development/luna_only_direct_beir6_20260910/natural_semantics_local_review/assistant_diagnostic_review.json)，同步 README 和研究总表。
- [x] 本轮新增 API/tokens/latency 均为0，不修改PVS、正式划分、2250目标、三对/六问或AUC/TPR@1%FPR；无v25、fresh30/formal、GPU/Retriever/victim调用、提交/推送。
- [ ] 后续真实验证：用已接入的新 Prompt 对同六篇 frozen source 在新输出目录重新生成一次并诊断；本轮仅授权本地验证，不执行此项。

当前状态：接入和本地验证全部完成，本轮停止。唯一后续验证点是新 Prompt 在同六篇真实文档上的生成效果；旧输出的新口径复核不能替代重新生成，也不作为总体容量或正式实验结论。

### 2026-09-10：同六篇新 Prompt 真实复测全部完成（superseding）

- [x] 用户授权同六篇真实复测；核对原source/chunk、模型/profile和新Prompt，沿用既有smoke入口，输出到新目录`natural_semantics_attempt1`。
- [x] 每篇一次Luna、共6次，无重试；16:55:52完成6/6篇，返回14候选、自动选中12对，3/6 source自动达到三对；未补抽或追加generation。
- [x] 全部14候选完成Assistant-only诊断：2有效/8不合格/4未确认；原选中12对为2/7/3，0/6 source具备三对确认有效pair。两个早停后草稿仅离线检查，不替补。
- [x] 保持自然语义口径，记录模板丢失固定内容、未解析指代、their重复、全称/缩写冲突、recent无锚点及反事实错误性不足；未恢复缺论文名或unique restoration门槛。
- [x] 与旧输出同口径的4有效pair、1/6有效source比较；本批只有2有效pair、0/6有效source。仅描述已知六篇开发样本，不做显著性或总体容量结论。
- [x] 六条真实响应身份、重解析、选择回放和禁用客户端的完成态resume通过，原response/summary不变；保存代码快照。未重复上一轮单元测试。
- [x] 保存[完整复测报告与实际问句](../artifacts/v24/development/luna_only_direct_beir6_20260910/natural_semantics_attempt1/natural_semantics_retest_report.md)和[逐候选诊断](../artifacts/v24/development/luna_only_direct_beir6_20260910/natural_semantics_attempt1/assistant_diagnostic_review.json)，同步README与研究总表。
- [x] API logical/physical/retry=6/6/0，tokens=6,585/9,275，累计latency=196.735秒；复核追加API=0。未改代码/Prompt/PVS/正式约束，未创建v25，无fresh30/formal、GPU/Retriever/victim或提交/推送。

当前状态：本批执行、全部复核与报告完成并停止。新Prompt仍有明确漏检，后续先讨论已有要求的遵循问题；本轮不继续改Prompt或运行下一批。

### 2026-09-10：atomic Q+ 与单次替换设计完成（superseding，仅文档）

- [x] 按用户最新要求，在[研究总表](顶会推进_notes.md#v24-luna-atomic-qplus-design)定稿四字段 `true_claim / original_entity / counter_entity / q_plus` 与完整 Prompt；Luna 直接生成 Q+，未来由代码单次 exact replacement 得到 Q−，不再让 Luna 生成模板或 Q−。
- [x] 以 atomic factual relation 为忠实性单位；允许长句只问一项 OR、counter 已在 chunk、同 claim 不同 slot。original 的唯一一次约束在 Q+ 中，不在整个长引文中。
- [x] 保留正常语义下的反事实错误性、最小上下文过滤和无锚点相对时间 skip；不增加论文/模型命名要求、repair、alias/canonicalization、多阶段 verifier 或 restoration gate。
- [x] 写明六类定向测试规格及边界对照，区分确定性/mock 断言与 Luna 语义验收。重复 their 与目标全称/缩写冲突不能靠 exact replacement 自动保证消失；以 Prompt 约束和开发诊断检查。
- [x] 撤回“省略无关并列事实即失败”的旧审核理由；原六篇响应、14候选旧诊断和原自动计数保留，本轮未重标或重算，不把旧0/6写成新方案结果。
- [x] 明确运行代码仍为 shared-template：后续在现有 direct adapter 与测试文件迁移 schema、Prompt 和 Q+ 唯一槽位，不新增架构文件。现行 direct 已允许 counter 在 chunk 中，无需删除一个不存在的硬 gate。
- [x] 本轮仅更新 README 和两份总表；API/tokens/latency=0，不改变 PVS、正式 split、BEIR datasets、2250目标、三对/六问和指标，不创建 v25。
- [x] 文档差异与示例核对通过：`git diff --check`、JSON/schema、真实引文 exact match、单次替换与链接检查；9个代码/配置/测试及实验文件 hash 未变。未将这些文档检查记作运行时单元测试通过。
- [ ] 后续唯一开发步骤：按此设计在现有代码接入 `q_plus` 与单次替换，并将已写明的定向测试规格落实为本地测试。本轮范围只含方案和 Prompt 设计，未执行此项。

当前状态：设计、完整 Prompt 和定向测试规格已完成；运行时接入、可执行测试和新真实生成均未进行。本轮到文档交付停止，不自动继续实现、同六篇重跑、fresh30/formal 或提交/推送。

### 2026-09-10：atomic Q+ 已接入并完成本地验证（superseding）

- [x] 按用户“开始改代码”完成上条待办：修改现有 direct Prompt、四字段 schema 和单次 exact replacement；不新增架构、verifier、repair 或配置文件。
- [x] original 唯一出现约束移到 Q+；长 claim 可以重复 original，direct pair 不再伪造 `original_span`。counter 在 chunk、同 claim 不同 slot 允许，来源/预算/去重/前三对早停保持。
- [x] 定向测试规格接入既有测试文件：direct/smoke 29/29；扩展回归277项中267 passed、10项既有 legacy skipped。mock 只验证结构、发出的 Prompt 和调用契约，不代表真实语义质量通过。
- [x] `validate-config`、6/6 Prompt 与定稿一致、同六篇只读 preview 通过；新代码在 API 客户端初始化前拒绝 resume 旧 attempt，旧输入/结果/summary/诊断/报告不变。
- [x] 同步 README 与[研究总表实施记录](顶会推进_notes.md#v24-luna-atomic-qplus-implementation)，保留历史整句忠实性诊断及计数。
- [x] 真实 API/tokens/latency=0；PVS、BEIR、formal split、2250目标、三对/六问及指标不变，无v25、fresh30/formal、提交或推送。
- [ ] 唯一后续验证：用当前 atomic Q+ Prompt 对相同六篇 frozen BEIR source 在新输出目录做一次真实生成与 Assistant diagnostic。此次授权为代码接入和本地验证，本轮未执行真实调用。

当前状态：代码接入与本地验证完成并停止；新构造的真实效果尚未复测，不以 mock、preview 或旧结果替代。

### 2026-09-10：同六篇 atomic Q+ 真实复测完成（superseding）

- [x] 用户授权本轮真实生成；核对六篇输入、顺序、chunk、当前atomic Prompt与模型，使用 `atomic_qplus_attempt1` 新目录，未改代码/配置或旧产物。
- [x] 20:21:20完成6/6请求，候选18个、自动选中7对、2/6 source自动达到三对；实际确定性拒绝 `q_plus_slot_count=3`、`claim_not_exact_chunk_span=1`，7个草稿早停后未处理，不补选。
- [x] 全部18候选完成Assistant-only诊断：8有效/10失败；原已选7对为4有效/3失败，1/6 source有三对确认有效pair。明确区分自动选择、语义诊断与未选草稿，不声称独立人工审核。
- [x] 归因：MED-1114前三个We人数句污染选择，后四个有效OR草稿未选；多条Q+提前含e−；一个claim改了大小写。major/minor与单原子OR允许，不恢复整句忠实性或restoration gate。
- [x] 六条身份、解析和选择回放，七对单次替换及禁用API client的完成态resume通过；原response/summary未变，保存代码快照与[完整报告](../artifacts/v24/development/luna_only_direct_beir6_20260910/atomic_qplus_attempt1/atomic_qplus_retest_report.md)、[全部诊断](../artifacts/v24/development/luna_only_direct_beir6_20260910/atomic_qplus_attempt1/assistant_diagnostic_review.json)。
- [x] API logical/physical/retry=6/6/0，tokens=8,205/8,590，累计latency=172.324秒，复核追加API=0；无GPU/Retriever/victim/fresh30/formal调用。
- [x] README与研究总表同步完成态。PVS、BEIR、正式split、2250目标、三对/六问和指标不变，无v25、提交或推送；未重算旧口径标签或重复上一轮本地测试。
- [ ] 唯一后续事项：围绕本次已观察到的三类遵循错误讨论最小修复，保持atomic Q+架构。本轮到复测与报告结束，不自动修改或追加实验。

当前状态：本批生成、全部复核和记录已完成并停止。1/6是该已知开发样本的Assistant诊断结果，不代表总体容量或正式质量门槛通过。

### 2026-09-11：最小筛选修复与同六篇保存响应回归完成（superseding）

- [x] 在现有direct selector取消三对后的early-stop；最多8个候选全部检查、去重，再按原顺序取前三对。新增本地valid计数和逐候选selected，不增加ranking或generation。
- [x] 增加仅匹配已观察短语的unresolved_discourse_reference规则；We conducted和we captured直接拒绝，描述性graph-cut主体和句内代词不因缺专名被拒。
- [x] 保留exact span、Q+内原实体唯一、单次替换、去重和预算；The/the大小写漂移继续fail closed。原Prompt、同角色/反事实语义要求和PVS不变，无repair/verifier/restoration gate。
- [x] 新增9项测试并更新原early-stop测试。旧实现先复现2条预期失败，修复后direct/mock 38/38通过；扩展回归286项中276通过、10项既有legacy skipped，38项为子集。
- [x] 原样复用atomic_qplus_attempt1的六条真实响应，重新执行本地筛选；候选8/3/5/1/0/1全部检查，本地valid=5/0/3/0/0/1，selected=3/0/3/0/0/1。MED-1114从C0/C1/C2改选C3/C4/C5。
- [x] 9个候选被拒：指代5次、q_plus_slot_count 4次、exact span 1次，其中一条同时命中两项。旧响应/summary/诊断/报告保留，没有将旧选择或诊断标签作为新selector输入。
- [x] Assistant-only复核已选7对全部有效，2/6 source三对均有效；全部18候选仍为8有效/10失败。MED-1114 C7仍非atomic，本地通过但未选，未继续为本批加规则；4篇不足三对仍保留insufficient。
- [x] 六篇身份、响应重解析、完整筛选确定性回放、七对单次替换、原产物/配置hash及diff检查通过。新增API/tokens/API latency=0，无GPU/Retriever/victim调用。
- [x] 保存[完整回归报告](../artifacts/v24/development/luna_only_direct_beir6_20260910/atomic_qplus_local_regression_20260911/local_regression_report.md)、[机器可读结果](../artifacts/v24/development/luna_only_direct_beir6_20260910/atomic_qplus_local_regression_20260911/local_regression.json)和代码/config快照，同步README与[研究总表](顶会推进_notes.md#v24-luna-local-selection-fix)。
- [ ] 唯一下一步：固定当前实现后做fresh30开发验证；本轮到同六篇回归结束，停止调整这批，不自动启动fresh30或formal。

当前状态：本次最小修复已完成并符合指定回归预期。PVS、BEIR、formal split、2250目标、三对/六问及指标不变，无v25、提交或推送。

### 2026-09-11：Prompt输出措辞修正与本地验证完成（superseding）

- [x] 按用户“先修复问题”，仅修改现有Prompt三处措辞：Q+指定槽位保留e+、true_claim逐字保持大小写、同次调用检查完整chunk并最多返回8个合格候选。允许不足或为空，不凑数、不top-up。
- [x] 正确的数值Q+保持合法；没有基于该正确示例增加规则。selector、确定性gates、四字段schema、单次替换、原序前三对与PVS保持。
- [x] 扩展现有mock/回归测试：错误Q+和大小写漂移仍拒绝，小写原文引文配自然问句通过，纯标题空输出和单候选继续insufficient。direct/mock **39/39通过，0.693秒**；未重跑上轮286项扩展回归。
- [x] 源码AST仅Prompt函数改变；六篇Prompt输入封装6/6通过，hash变化但仍只含原frozen chunk。旧响应、诊断及筛选产物不改，diff检查通过。
- [x] 同步README和[研究总表](顶会推进_notes.md#v24-luna-prompt-output-fix)。新增真实API/tokens/API latency=0，无GPU/Retriever/victim或新生成。
- [ ] 唯一下一步：固定当前实现后做fresh30开发验证，检查真实输出的实体保留、逐字引用和有效候选数量。本轮未启动，旧2/6不代表新Prompt效果。

当前状态：本轮修正与本地验证完成并停止。未继续调同六篇，未改正式预算、PVS、split、datasets或指标，无v25、提交或推送。

### 2026-09-11：fresh30开发验证与全部诊断完成（superseding）

- [x] 用户授权fresh30；三数据集各固定10个未见source，排除历史source/text身份，重叠为0。继续完整source单chunk输入，不为凑三对再切块，无失败换样。
- [x] 固定现有atomic Q+代码/Prompt/config并保存运行快照；沿用53号脚本，六批各五篇，每source一次Luna、最多8候选，全量本地筛选、原序前三对，不top-up或repair。
- [x] 30/30真实生成完成，115候选、本地valid=110、实际selected=66；本地凑齐三对17/30，逐数据集6/4/7。
- [x] Assistant-only完成全部115候选复核：79有效/34失败/2未确认；已选66对为41/23/2。实际选中三对均有效 **7/30**，nfcorpus **3/10**、scidocs **0/10**、trec-covid **4/10**。
- [x] 失败分为13篇数量不足（含5篇零输出）、10篇已选语义未通过。归因包括指代漏检、非atomic、反事实错误性不足、条件丢失及角色错配；不把少量生成等同于原文已穷尽。
- [x] 本地拒绝duplicate=1、q_plus_slot_count=4；后者只有1个真偷换、3个大小写契约失配。大小写与事实/语法错误分开记录，未改gate。
- [x] 5篇原返回候选足够但坏候选原序入选；12/30仅为事后候选可用性，未重选或替换，实际7/30不变。不称为独立人工盲审或正式效果。
- [x] API logical/physical/retry=30/30/0，tokens=43,980 input/64,251 output，累计latency=1265.146秒。无Retriever/victim/GPU、补生成或正式调用。
- [x] 30/30重解析、30/30选择回放、66/66单次替换和6/6禁用client完成态resume通过。10个保护文件及六批18个原artifact hash不变；本轮未改代码或重跑上轮39/39单测。
- [x] 完成[完整报告与全部实际Q+/Q−](../artifacts/v24/development/luna_only_direct_fresh30_20260911/fresh30_report.md)、[机器可读汇总](../artifacts/v24/development/luna_only_direct_fresh30_20260911/fresh30_summary.json)、[115候选Assistant诊断](../artifacts/v24/development/luna_only_direct_fresh30_20260911/assistant_diagnostic_review.json)，同步README与[研究总表](顶会推进_notes.md#v24-luna-fresh30-development)。
- [ ] 唯一下一步：审阅本轮失败归因后再决定最小修正；到本批报告交付停止，不自动修改Prompt/代码或启动新的实验。

当前状态：fresh30开发验证完成并停止，当前构造仍有明确语义遵循缺口。PVS、正式split、BEIR datasets、2250目标、三对/六问及指标不变；无v25、capacity/formal、提交或推送。

### 2026-09-11：同槽不同反实体补足规则实现与本地回放完成（superseding）

- [x] 按用户“行，改吧”实施：同一次Luna最多8候选，先选不同claim/slot，不足三对时按原序用同槽不同counter补足；不新增调用或改变source/chunk边界。
- [x] 仅修改原Prompt和selector；去重改为规范化claim/e+/e−三元组，完全重复拒绝。同槽备用保持首个通过候选的Q+逐字一致，不一致直接拒绝，不repair。
- [x] 保留exact chunk span、original子串、Q+唯一slot、Q−单次替换、有限指代和原语义要求。每个counter仍须明确为假，无额外verifier/restoration gate。
- [x] 三个定向测试先在旧实现复现失败；新增九项测试并更新旧去重测试。direct/mock 48/48通过；扩展回归296项中286通过、10项既有legacy skipped，48项为子集。
- [x] 原fresh30保存响应全部30条/115候选本地回放；只在选择后关联既有Assistant标签。MED-1118由两对变三对，其他29篇的选择及已选pair文本/ID不变。
- [x] 回放本地valid=111、selected=67、本地三对18/30、已选三对语义有效8/30（nfcorpus 4/10、scidocs 0/10、trec-covid 4/10）；已选42有效/23失败/2未确认。保留原真实fresh30的7/30，不将回放冒充新Prompt生成效果。
- [x] 30/30重解析与确定性回放、67/67单次替换、30/30新Prompt封装通过。新代码在client初始化前拒绝resume六个旧attempt；8个保护文件及24个原fresh30文件hash不变。
- [x] 本轮新增API/tokens/API latency=0，无GPU/Retriever/victim；完整source单chunk、三对/六问和PVS主公式不变，共享事实不视为独立事实证据。
- [x] 保存[本地回放报告](../artifacts/v24/development/luna_only_direct_fresh30_20260911/same_slot_counter_local_regression_20260911/local_regression_report.md)、[机器可读结果](../artifacts/v24/development/luna_only_direct_fresh30_20260911/same_slot_counter_local_regression_20260911/local_regression.json)和代码快照，同步README及[研究总表](顶会推进_notes.md#v24-luna-same-slot-counter)。
- [ ] 唯一下一步：对新Prompt做真实开发验证，检查少槽source能否主动给出合格备用反实体；本轮尚未启动，不自动追加生成。

当前状态：实现、定向/扩展测试和保存响应回放完成并停止。未改formal split、BEIR datasets、2250目标、PVS或指标；无v25、提交或推送。

### 2026-09-11：新Prompt同30篇真实复测与全量诊断完成（superseding）

- [x] 按用户授权复用原30篇、原顺序和完整chunk，保持代码/Prompt/config固定；六批各五篇顺序运行，每source一次Luna、最多8候选，无top-up、repair或失败换样。
- [x] 30/30真实响应完成，116候选全部本地筛选，valid=110、selected=61，本地三对source=15/30。
- [x] Assistant-only复核全部116候选为80有效/28失败/8未确认；已选61对为39/15/7。实际三对均有效**5/30**：nfcorpus 2/10、scidocs 0/10、trec-covid 3/10。
- [x] 分开保留原真实生成7/30、旧响应当前selector回放8/30、新Prompt真实生成5/30；新批是已知30篇开发回归，不称未见fresh30或显著总体效果。
- [x] 15篇数量不足全部原始输出仅0–2候选，gate导致从至少3个变不足的source为0；另10篇选满但语义未通过。12篇有至少3个本地接受且Assistant有效候选，仅作事后可用性诊断，不重选。
- [x] 6个本地接受同槽备用候选来自4篇scidocs，4失败/2未确认；选用2个，1篇因此本地补满三对，但没有新增三对语义有效source。近义counter不写成独立事实。
- [x] 本地拒绝duplicate=2、q_plus_slot_count=3、original_not_exact_claim_substring=1；大小写与copula倒装的字符串契约问题分别记录，未调整gates。
- [x] API logical/physical/retry=30/30/0，tokens=48,060/62,912，累计latency=1280.893秒；复核追加API=0，无victim/Retriever/GPU或formal调用。
- [x] 30/30重解析/选择回放、116/116候选处理、61/61单次替换、六批禁用client完成态resume通过；10个保护文件、27个旧产物和12个本次原始result/summary hash不变。代码未改，沿用已完成48/48 direct/mock及296项扩展回归结果。
- [x] 保存[本轮报告与全部实际问句](../artifacts/v24/development/luna_only_direct_fresh30_20260911/same_slot_counter_attempt1/regeneration_report.md)、[机器可读汇总](../artifacts/v24/development/luna_only_direct_fresh30_20260911/same_slot_counter_attempt1/regeneration_summary.json)、[全部Assistant诊断](../artifacts/v24/development/luna_only_direct_fresh30_20260911/same_slot_counter_attempt1/assistant_diagnostic_review.json)，同步README及[研究总表](顶会推进_notes.md#v24-luna-same30-regeneration)。

当前状态：本次同30篇真实复测、全量诊断和报告完成并停止。唯一下一步是审阅失败归因后决定是否继续最小修正；没有自动启动后续生成、fresh30或formal。PVS、split、datasets、2250目标、三对/六问及指标不变，无v25、提交或推送。

### 2026-09-11：Luna-only最终收缩式修复与本地验证完成（superseding）

- [x] 按用户本轮要求在现有direct路径修改Prompt、少量确定性gates及原测试文件，不增加源码入口、配置、manifest、版本或verifier。
- [x] 明确Q+使用e+，完整e+须唯一连续匹配且Q+不得出现完整e−；失败直接reject，Q−只由代码替换实际匹配span生成，不输出模板或独立Q−。
- [x] 实体槽位在claim和Q+中允许纯大小写差异，保留原始字段与槽外文本；引文仍逐字来自chunk，不fuzzy、不重排倒装、不repair。完整词边界避免18/181、common/uncommon子串误判。
- [x] 轻量指代规则覆盖we、our既有短语、this method/review及former/latter；不要求专名，不建立context parser，atomic子事实仍允许。
- [x] 保留全量最多8候选检查、三元组去重、共享Q+、原序优先不同slot、不足三对才用同槽counter的选择代码。无candidate 9、top-up、quality ranking或victim/PVS依赖。
- [x] Prompt明确仅少于三个不同有效slot时提供同次备用；每个counter独立同角色、明确为假且不能近义重复。近义限制测试属于Prompt契约测试，不称本地字符串代码已完成语义审核。
- [x] direct/mock共55项，包含于扩展303项中：293通过、10项既有legacy skipped。覆盖坏候选不占位、大小写、counter混入、fallback顺序/上限、代码替换及保存/resume；无真实网络调用。
- [x] 只读回放最近30条保存响应的116候选，全部处理并确定性复现；本地valid=100、selected=57、本地三对=13/30（nfcorpus 6/10、scidocs 1/10、trec-covid 6/10）。57对替换与Q+禁counter检查通过；不把13/30写成语义通过或新生成结果。
- [x] 3个纯大小写候选恢复；指代与Q+ counter禁入导致部分原候选退出，原5/30语义结果和原始产物保留。没有重新计算语义通过率或根据旧Assistant标签重选。
- [x] 66个保护文件/旧产物hash保持；源码与测试内存编译、14个当前入口/新增链接及diff空白检查通过。没有新增实验文件或清理既有资产。
- [x] 同步README与[最终设计、实现及验证记录](顶会推进_notes.md#v24-luna-final-contraction)。API/tokens/API latency均为0，无PVS、formal split、BEIR datasets、2250目标、三对/六问或指标变动。
- [ ] 唯一下一步：在独立输出目录验证本轮Prompt的真实开发输出；本轮未启动，不自动追加Luna生成或formal。

当前状态：本轮修复和本地验证完成并停止。仍为V24开发路径，无新复杂规则系统、v25、提交或推送。

### 2026-09-12：开发复核收窄为构造正确性抽查（superseding）

- [x] 按用户“那改吧”更新后续复核安排，只检查Q+的atomic事实依据、同角色e−使关系明确为假、Q+/Q−只改变指定槽位。
- [x] 正常语法变化、长句只问一个子事实、无论文/方法专名或victim未恢复e+均不单独判失败；明确错误性仍是构造要求，不能只凭counter缺席推断。
- [x] 下一轮原30篇仍全部生成与本地筛选；抽查范围固定为原输入顺序中每数据集前2篇，共6篇、最多18个已选pair。零pair/不足三对不换样、不补生成，不默认全量Assistant复核。
- [x] 报告分开记录全量本地数量与抽查的具体构造问题；未抽查不记通过，不外推整体语义通过率，不增加综合分数、阈值或复核eligibility gate。
- [x] 确认现有代码没有通用语义审核准入条件；只改README和两份研究总表，Prompt、selector、测试、PVS与旧schema保持，历史5/30和13/30不重标。
- [x] 完成文档/链接和diff检查，核对代码、配置及旧结果未改变；本轮真实API调用为0，未重跑测试或开展实际抽查。详见[三项抽查规则](顶会推进_notes.md#v24-luna-construction-correctness-review)。
- [ ] 唯一下一步：在独立输出目录完成当前Prompt的同30篇真实复测，再按6篇范围做构造正确性抽查；本轮未启动。

当前状态：复核口径修改完成并停止。没有新增verifier、修复链、版本或正式实验；固定预算、数据集、split和评估指标保持。

### 2026-09-12：最终收缩版同30篇真实复测与固定抽查完成（superseding）

- [x] 接到用户“开始进行下一步”授权；核对原30篇与六批输入、当前代码/config hash和唯一Python环境，六批preview通过。
- [x] 生成前固定每数据集前两篇作为6篇抽查对象，创建独立`final_contraction_attempt1/`输出及当前六文件代码/config/tests快照。
- [x] 六批顺序完成30份新Luna响应，每篇最多8候选，成功批次零传输重试；运行期间代码、Prompt与配置保持。首批沙箱内另5次无响应，经确认后在独立目录重执行，失败原件保留，计费未知。
- [x] 全量130候选、121本地valid、67对selected；22/30篇本地满三对（nfcorpus 8/10、scidocs 6/10、trec-covid 8/10）。8篇不足为7篇原始输出不足、1篇指代检查拒绝，未补生成或换样。
- [x] 同槽fallback在scidocs一篇填入2对，使其本地满三对；未把备用pair算独立事实，也未对固定范围外候选追加语义审核。
- [x] 固定6篇中2篇零pair，实际抽查4篇的10对；8对事实/反事实得到支持，2对分别缺少测量对象和疗程阶段，10对单槽保持。只作Assistant诊断，未按诊断改选或推算全30篇整体语义通过率。
- [x] 完成30条重解析/选择回放、130候选完整处理、67对单槽替换及六批禁止client的完成态resume；7个保护文件、原输入、前次结果和首批失败原件hash保持。
- [x] 30次成功生成input/output tokens=51,570/63,475、累计API latency=1229.418秒；含初始无响应记录共35次逻辑尝试，另2次只读models探测。没有victim、Retriever、GPU或formal调用。
- [x] 保存[完整报告](../artifacts/v24/development/luna_only_direct_fresh30_20260911/final_contraction_attempt1/retest_report.md)及固定抽查/汇总，同步README和[完成记录](顶会推进_notes.md#v24-luna-final-contraction-retest-result)。本轮源码/测试未变，沿用既有303项测试证据，没有提交或推送。
- [ ] 唯一下一步：审阅本次结果后确认下一批未使用开发文档的验证范围；当前未启动。

当前状态：本轮真实复测、固定抽查、离线核对和报告完成并停止。22/30是本地满三对数量，不是全量语义通过率；不自动追加source、candidate或新Prompt修改。PVS、split、BEIR datasets、2250目标、三对/六问与AUC/TPR@1%FPR均保持。

### 2026-09-12：一次 chunk 调用分组生成多个 counter，实现与本地验证完成（superseding）

- [x] 按用户最新要求修改现有 direct 路径：Luna 一次返回最多8个 slot 组，每组共享 true_claim/e+/Q+，同时生成1–3个 counter_entities；不发起后续 counter-only/top-up 调用。
- [x] Prompt 明确每个有效 slot 都在首次响应中尝试给出三个不同 counter，而非仅不足三槽时才生成备用；counter 须各自同角色、明确错误且非同义词/别名/近义改写，不足则照实返回。
- [x] 全部 slot/counter 本地检查后按原序优先不同slot；两槽 A1/B1/A2、一槽 A1/A2/A3，最终最多三对，每槽累计最多贡献三对，无质量ranking或victim/PVS输入。
- [x] 保留 atomic 子事实、claim exact span、有限指代拒绝、case-insensitive contiguous slot、Q+唯一e+及单次代码替换；Q+含组内任一不同counter即拒绝共享问句，不修复。
- [x] 三元组字面去重、重复slot共享Q+、counter数组1–3项及第九组拒绝均有测试；近义不同由同次Luna的Prompt约束，未新增语义verifier或把mock视为真实质量证明。
- [x] 在原config仅增加max_counters_per_slot=3；原smoke分别记录slot/counter/valid pair/selected数。每个下游pair仍为单值counter_entity，3 pairs/source、6 queries/source和PVS保持。
- [x] direct/mock **63/63通过**，包含于完整V24回归**297项：287通过、10项既有legacy skipped**；覆盖单/双/多槽选择、8组24counter全处理、坏counter不占位、单次mock请求、pair身份及离线resume。
- [x] 六个旧扁平checkpoint均在client初始化或写入前拒绝漂移，原响应、汇总、诊断、报告与快照hash保持；旧22/30单独保留，不称为分组版实测结果。
- [x] 同步README与[当前方案、实现和验证记录](顶会推进_notes.md#v24-luna-grouped-counters)。没有新增代码文件、manifest、freeze、repair或版本，没有提交/推送。
- [ ] 唯一下一步：在独立开发输出目录验证分组Prompt的真实输出，并按既定三项构造正确性规则抽查；本轮未运行，不自动追加API或formal。

当前状态：本轮实现、测试及文档同步完成并停止。真实API/tokens/API latency均为0，victim/Retriever/GPU调用为0；BEIR datasets、formal split、2250目标、source统计单位、3对/6问、PVS与AUC/TPR@1%FPR不变，无v25。

### 2026-09-12：分组 counter 版本对原30篇真实复测（running，superseding）

- [x] 收到本轮30篇真实API调用的明确授权；保持原source/chunk/顺序，六批preview通过，确认唯一Conda环境与当前分组配置。
- [x] 新建独立 `grouped_counters_attempt1/` 输出，保存当前代码/config/tests快照与保护hash；生成前固定每数据集前两篇共6篇抽查。
- [ ] 六批顺序完成30篇，每篇一次Luna、最多8组×3counter、零传输重试；本地优先不同slot、不足才同槽补足，不补生成。
- [ ] 汇总每source的组数、counter数、有效slot/pair、selected和拒绝原因，单独报告同槽补足作用；旧扁平候选数不与新组数混比。
- [ ] 完成固定6篇实际selected pair的三项构造正确性抽查、离线重解析/选择回放与产物保护检查，保存报告并同步总表。

当前状态：真实复测运行中，唯一下一步是完成本批生成、固定抽查和报告后停止。详见[本轮执行记录](顶会推进_notes.md#v24-luna-grouped-counters-retest)；不修改Prompt、PVS、split、datasets、2250目标或固定三对/六问预算。

### 2026-09-12：分组 counter 版同30篇真实复测完成（superseding）

- [x] 原样复用三数据集各10篇及完整chunk/顺序，当前分组代码和Prompt保持不变，六批首轮全部执行。
- [x] 取得30份响应；00s2pabm首轮RuntimeError且无响应，仅按原输入在独立目录恢复一次。失败原件及hash保留，没有重生成已完成source或counter-only补齐。
- [x] 新生成97个slot组、210个counter，本地有效95组/208对，最终selected 66对；20/30篇本地满三对：nfcorpus 8/10、scidocs 4/10、trec-covid 8/10，旧版22/30单独保留。
- [x] 同槽fallback在3篇选入4对并补满三对，包含真实一槽三counter及两槽补足；不把同槽多个counter计成独立事实。
- [x] 10篇不足为5篇零slot、5篇原始counter仅1–2个；本地两个拒绝均未造成source不足。scidocs两篇由旧三对降为一对，原输出数量下降，不是selector漏选。
- [x] 固定6篇中4篇有pair，实际11对完成三项抽查：8对得到支持，2对缺WhatsApp互动范围、1对previously时点不明；11对单槽保持。另记录一组hinder/prevent近义counter与一处the an措辞偏差，没有重选或新增gate。
- [x] 30条重解析/选择回放、97组/210counter完整处理、66对替换、31条尝试记录与七目录禁止client完成态resume通过；7个保护文件、18个旧产物和全部原输入hash保持。
- [x] API共31次逻辑尝试、30份响应、SDK重试0；有响应请求input/output tokens=55,950/71,510、累计latency=1387.325秒，无响应尝试费用未知。victim/Retriever/GPU与额外LLM复核调用均为0。
- [x] 保存[完整报告](../artifacts/v24/development/luna_only_direct_fresh30_20260911/grouped_counters_attempt1/retest_report.md)、汇总、固定抽查与当前快照，同步README和[完成记录](顶会推进_notes.md#v24-luna-grouped-counters-retest-result)。代码未改，沿用已有63项direct/mock及297项V24测试证据。
- [ ] 唯一下一步：审阅本次生成数量与counter差异问题后决定后续开发范围；本轮不自动修改Prompt或继续生成。

当前状态：复测、抽查、离线核对和报告全部完成并停止。20/30是本地数量，不是全30篇语义通过率；PVS、formal split、BEIR datasets、2250目标、source统计单位、三对/六问与AUC/TPR@1%FPR不变，无v25、formal、提交或推送。

### 2026-09-12：有效 slot 主动尝试三个 counter 的最小 Prompt 修订完成（superseding）

- [x] 仅将Prompt第4条改为主动尝试三个不同counter、不得找到第一个就停止；确实无法构造更多合法counter时允许少于三个，原有禁止近义凑数要求保留。
- [x] 只调整两个直接相关测试；63项LunaDirect本地测试全部通过，覆盖一槽三对、两槽补足及不同slot优先，`git diff --check`通过。
- [x] 对照本轮修改前内容确认selector、gates、Q+/Q−构造、配置、PVS与formal protocol未变；保留全部旧结果，同步[修订记录](顶会推进_notes.md#v24-luna-three-counters-prompt)。

当前状态：本轮修改和本地验证完成并停止。没有真实API或任何实验重跑，不将旧20/30视为新Prompt效果。后续唯一待定事项为是否验证新Prompt的真实生成效果，本轮不自动执行。

### 2026-09-12：新 Prompt 对原30篇真实复测（running，superseding）

- [x] 收到用户本轮真实生成指令；核对原30篇完整chunk、六批顺序、Luna模型及零重试设置，六批preview通过。
- [x] 独立 `three_counters_prompt_attempt1/` 保存新结果和当前快照，保护上一轮产物；沿用固定6篇Assistant抽查。
- [ ] 用既有53号入口顺序完成六批生成，统计每source的slot/counter、selected pair、拒绝原因及同槽补足。
- [ ] 与上一轮20/30逐数据集和逐source比较，完成固定抽查与离线核对，保存报告并停止。

当前状态：准备完成，唯一下一步是连续完成本轮真实复测和报告。详见[执行记录](顶会推进_notes.md#v24-luna-three-counters-prompt-retest)；不改代码或实验协议，不运行victim、Retriever、PVS或formal。

### 2026-09-12：连接恢复后重新运行原30篇（attempt2，superseding）

- [x] 保留attempt1的5次无响应及10061连接诊断；后25篇当时未执行，用户中断记录单列。
- [x] 按用户重跑指令，确认旧进程退出、同服务HTTP 200且Luna模型可用；六批preview与原输入/代码/profile核对通过。
- [ ] 在独立 `three_counters_prompt_attempt2/` 顺序重跑全部30篇，完成逐source比较、固定6篇抽查及报告；不改Prompt或协议。

当前状态：连接恢复，开始新一轮30篇生成；唯一下一步为完成本批并停止。旧失败原件不覆盖，不运行victim、Retriever、PVS、GPU或formal。

### 2026-09-12：新 Prompt 同30篇复测完成（attempt2，superseding）

- [x] 保持原30篇/完整chunk/顺序及代码配置，六批顺序执行；MED-1127一次无响应后同输入恢复，取得全部30份响应，失败原件保留。
- [x] 111个slot组、289个counter，本地有效109组/283对，selected 69对；22/30篇本地选满：nfcorpus 8/10、scidocs 6/10、trec-covid 8/10，旧20/30单列。
- [x] 3篇使用3个同槽fallback pair补满；8篇不足为6篇零slot、2篇原始counter仅1–2个。两组本地拒绝均未造成source不足。
- [x] 固定6篇实际12对Assistant抽查完成：6对三项支持、3对角色错配、1对测量对象不明、2对依赖聚类范围；12对单槽保持，没有重选或新增gate。
- [x] 30份重解析/选择回放、111组/289counter、69对替换、31条尝试记录及七目录禁止client完成态resume通过；原输入、7个保护文件、18个旧产物和4个中断attempt文件保持。
- [x] 本轮31次逻辑尝试/30份响应，SDK重试0；有响应input/output tokens=57,450/76,049，累计latency=1484.917秒，失败尝试用量未知；上次5次无响应另存。
- [x] 保存[报告](../artifacts/v24/development/luna_only_direct_fresh30_20260911/three_counters_prompt_attempt2/retest_report.md)、汇总和抽查，同步[完成记录](顶会推进_notes.md#v24-luna-three-counters-prompt-retest-result)。

当前状态：本轮全部完成并停止。唯一下一步是审阅数量改善与剩余构造问题；没有自动追加生成或运行victim/PVS/formal，没有v25、提交或推送。22/30是本地数量达标，不能当全30篇语义合格率。

### 2026-09-12：同30篇数量与构造离线审阅完成（superseding，仅文档）

- [x] 按用户续接要求保持代码、Prompt与配置不变，读取原30篇/69个selected pair，并核对五篇数量变化source的旧输出。
- [x] 确认本地三对source 20→22、selected 66→69、counter 210→289；八篇不足来自原始生成数量，本地拒绝未导致source不足，selector没有漏选。
- [x] 保存13对明确问题（7篇）、5对边界备注与其他51对逐对说明；不转为新评分/准入门槛，不据此重选pair或改写eligibility。
- [x] 三个新增选满source均仍有明确问题：WhatsApp角色错配、SVI比较基准缺失、D2D条件前件被当成事实。区分有效年龄slot备用与坏slot补数。
- [x] 记录未选counter中的近义情况；正常数字、大小写、倒装、描述性主体及atomic子事实没有被扩大拒绝。原固定12对抽查与所有生成结果保持。
- [x] 保存[完整审阅](../artifacts/v24/development/luna_only_direct_fresh30_20260911/three_counters_prompt_attempt2/quantity_construction_review.md)和逐对JSON，同步README及[审阅完成记录](顶会推进_notes.md#v24-luna-three-counters-offline-review)。输入/源码/config/原始输出与旧产物hash保持；无API或实验运行。
- [ ] 后续建议：仅针对现有构造要求补通用Prompt反例/定向用例，再验证未见开发样本；本轮未实施修改或启动下一阶段。

当前状态：审阅已完成，条件性推进暂不执行。原始22/30与69对统计保留，不把诊断改成总体语义合格率；PVS、formal split、BEIR、2250目标、三对/六问及AUC/TPR@1%FPR不变，无v25、提交或推送。

### 2026-09-12：保持当前代码/Prompt的未见开发30篇验证（running，superseding）

- [x] 按用户决定继续未见开发验证，不实施上一轮建议的Prompt修改，不将离线13对诊断作为新门槛。
- [x] 排除267个历史开发source/534个文本hash，三数据集各选10篇，source/text重叠0；按冻结顺序取样，零候选不换样。
- [x] 保存新30篇完整chunk与六个五篇批次；输入SHA-256为8c5a3c77168766226afd32f7b1a5975bea6e9fc29468a541024e5d23a3b0402f，六批预检通过。
- [x] 当前七文件与已有代码快照一致，有效Luna profile不变；同服务models GET为200，无新版本或formal freeze。
- [ ] 顺序运行六批一次性grouped-counter构造，记录完整响应、数量、拒绝原因及调用用量，不依据结果调整或换样。
- [ ] 完成全部selected pair的Assistant离线诊断及原始记录核对，保存本批报告并停止。

当前状态：准备完成，进入真实生成。详见[执行记录](顶会推进_notes.md#v24-luna-grouped-unseen30-20260912)及[本批汇总](../artifacts/v24/development/luna_only_direct_fresh30_20260912/run_summary.json)。唯一下一步是完成本批；PVS、formal split、BEIR、2250目标、三对/六问及AUC/TPR@1%FPR不变，不启动formal。

### 2026-09-12：保持当前代码/Prompt的未见开发30篇验证完成（superseding）

- [x] 原定三数据集各10篇全部取得响应；历史开发source/text重叠0，固定未见prefix与完整chunk复核一致，零候选不换样。
- [x] 完整处理106个slot组/279个counter，本地有效95组/254对，最终71对；23/30篇选满（nfcorpus 10、scidocs 8、trec-covid 5）。
- [x] 9篇使用14个同槽备用pair，8篇补满；其中5篇一槽三counter、3篇两槽补满。七篇不足为六篇零slot、一篇只有两个counter，没有selector漏选。
- [x] 全部71对Assistant离线审阅：8对明确问题（6篇）、13对边界备注、50对未见明确问题；没有新准入阈值、重选或语义评分，也不是独立人工盲审。
- [x] 首轮30次加2次无响应恢复，共32次逻辑尝试/30份响应；有响应input/output tokens=57,453/76,415，累计latency=1499.926秒，失败用量未知，原件保留。
- [x] 30份严格重解析/选择回放、106组/279counter全量检查、71对单槽替换、32条尝试记录、七目录禁用client完成态resume均通过；输入、7个代码/config文件、14个原始文件、旧对照汇总及快照hash保持。
- [x] 保存[本批报告](../artifacts/v24/development/luna_only_direct_fresh30_20260912/validation_report.md)、[汇总](../artifacts/v24/development/luna_only_direct_fresh30_20260912/run_summary.json)和全部逐对诊断，同步README及[完成记录](顶会推进_notes.md#v24-luna-grouped-unseen30-20260912-result)。

当前状态：本批完成并停止，保持当前代码与Prompt，不继续围绕本批修规则。下一步可按既定方案准备代码/config冻结与后续评估；本轮未启动下游。PVS、formal split、BEIR、2250目标、三对/六问及AUC/TPR@1%FPR保持，无victim、Retriever、GPU、PVS、formal、v25、提交或推送。

### 2026-09-13：V24 混合 PVS 开发实现与本地验证完成（superseding）

- [x] 按批准计划替代QA-NLI提案，仅新增结构化stance输入适配、实体语义恢复和pair/source评分函数，历史parser/scorer及经典CLI保持。
- [x] S+/A−按supported=1、contradicted/insufficient=0映射；纯No/空correction为合法零恢复，不把未知或运行错误混为同一类。
- [x] R−优先规范化完整相等，否则只对correction/e+的固定值表达取双向NLI最小蕴含概率；复用现有DeBERTa predictor，不读QA/chunk，不加verifier或alias表。
- [x] 保存全部中间分数、`pair_pvs=S+*max(0,R−−A−)`、source三对mean主分和median诊断；不足/不完整不填零，不按剩余pair平均。
- [x] 新增18项定向测试通过；扩展回归418项中369通过、49项既有skip，零失败/错误；18项包含其中。
- [x] 保存[七个合成样例、source聚合及验证证据](../artifacts/v24/development/pvs_hybrid_20260913/local_validation.json)，同步README与[实现记录](顶会推进_notes.md#v24-hybrid-pvs-20260913)。NLI概率为mock，不是模型准确率证据。
- [x] 核对10个保护文件、11个既有函数不变，V24配置只增加scoring段；旧构造产物不覆盖、不重新生成。Query Construction、victim prompt、预算、数据和评估边界保持。
- [ ] 唯一下一步：准备固定revision本地NLI权重并进行小规模真实语义匹配离线验证；当前权重目录缺失，模型未加载。

当前状态：独立开发评分接口与本地/mock测试完成并停止，正式runner尚未接通；不宣称真实语义效果已验收。本轮API/victim/Retriever/GPU/模型下载均为0，不自动运行fresh30或formal，无v25、提交或推送。

### 2026-09-13：V24 PVS 离线入口衔接与冻结准备完成（superseding）

- [x] 补齐五个RA固定case：exact=1且无NLI调用，另外四例用mock验证双向取min；不声称真实分数或模型语义排序已确认。
- [x] 11号脚本增加显式V24离线模式与dry-run；直接读取已有selected pairs/smoke结果，绑定原始RAG回答，调用现有PVS并保存pair/source/summary。
- [x] 同槽备用的重复Q+保留各自pair/query身份；不足三对、缺失或错误回答不补零/不按剩余pair平均；拒绝跨source、问句或cell漂移以及结果覆盖。
- [x] 新入口11项和既有PVS20项通过；扩展431项中382通过、49项既有skip，零失败/错误；CLI帮助及diff检查通过。
- [x] 仅用已有5篇开发产物执行无模型CLI预检，识别15对/30问；0 victim response、0新构造、0PVS分数。8个保护文件与9个旧评分函数保持，V24配置不改。
- [x] 保存[入口与冻结准备验证](../artifacts/v24/development/pvs_hybrid_20260913/entry_validation.json)，同步README和[决策记录](顶会推进_notes.md#v24-pvs-entry-freeze-preparation-20260913)。不新增协议或治理层。
- [ ] 唯一下一步：准备固定revision的本地NLI权重，完成五个RA case的真实双向entailment/R−离线验证；当前权重缺失，本轮没有下载或加载。
- [ ] 后续冻结待办：正式eligibility/split/query/index/cell绑定、runner字段及重复Q+预算兼容、config+代码提交。当前只接通PVS离线入口，不宣称完整正式runner就绪或正式冻结完成。

当前状态：本轮入口实现、回归与冻结准备已完成并停止；formal split、数据集、2250目标、三对/六问及评分/评估定义保持。API/victim/Retriever/GPU/下载均0，无fresh30/formal、v25、提交或推送。

### 2026-09-13：V24 正式 runner 代码衔接与 mock 端到端验证完成（superseding）

- [x] 10号脚本显式`--v24`连接既有selected pairs → 固定split/主index → 现有RAG/victim → 新PVS → source mean/median；历史V20入口保持。
- [x] 在现有V24 prepare模块导出运行字段，校验原pair/hash/单次替换；不重选、不生成、不repair。主计划保持2000 source/6000 pair/12000 query，Reserve无请求。
- [x] 补固定2250与1000/1000/250 split、主index只含KB_Member、模型/后端/profile/commit绑定；显式V24预算允许共享Q+，六个query ID逐条执行，旧预算默认不变。
- [x] 复用既有checkpoint/resume及response identity；中断只补剩余，失败问句只重试失败问句，回答不齐全不评分，完成态0调用，结果或输入漂移拒绝续跑。
- [x] 固定本地NLI在victim调用前初始化并由scorer复用；缺权重/CUDA先停止，dry-run不加载模型或写文件；没有修改PVS定义或victim prompt。
- [x] 新增11项定向测试；相关476项中427通过、49项既有skip，零失败。完整合成mock：2250 split source、12000唯一query、6000 pair/2000 source score；6+11994恢复，mean=0.6/median=0.8仅为mock结果。
- [x] 核对10个受保护函数和parser不变，配置仅新增`formal.runtime: null`；保存[验证证据](../artifacts/v24/development/pvs_hybrid_20260913/formal_runner_mock_validation.json)，同步README及[研究记录](顶会推进_notes.md#v24-formal-runner-mock-20260913)。
- [ ] 唯一下一步：准备固定revision本地NLI权重，完成五个RA case真实双向entailment/R−离线验证；目前权重缺失，本轮未下载或加载。
- [ ] 之后准备真实formal selected pairs/split/index及单cell runtime绑定，再提交config+代码冻结；当前正式产物尚未生成，runtime保持null，工作树未提交。

当前状态：正式runner的代码链和mock验证已完成并停止；真实API/victim/Retriever/NLI/GPU调用为0，没有formal/fresh30、v25、提交或推送。此前“正式runner未接通”的状态由本条更新；真实权重/输入/冻结未就绪的状态保留。

### 2026-09-13：V24 代码版本交付（superseding）

本条随用户授权的当前V24提交保存，目标为`codex/v24-pre-split-eligibility`及其`origin`同名分支；提交SHA和远端结果以Git记录为准。交付包含grouped-counter构造、混合PVS、正式runner、测试及文档，独立V23改动和本地开发artifacts保持原位。沿用476项回归结果，不重跑模型或实验。

唯一下一步保持：准备固定revision本地NLI权重，完成五个RA case真实离线验证。随后补真实formal输入和cell绑定，再做正式冻结；当前`formal.runtime`仍为空，此次代码交付不代表formal已冻结或已运行。

### 2026-09-17：v24 single-query black-box runtime 完成（superseding）

- [x] 将固定短wrapper生成的同一个`attack_query`同时送入Retriever和RAG Generator；matched LLM-only的`User request`逐字节相同。
- [x] 保留raw `query`并在response新增`attack_query`；query plan及Q+/Q-字节不改，三对/六问、top-k与context不变。
- [x] generic shell不包含回答格式；回答契约只在attacker request出现一次。
- [x] runtime版本更新为`pcv-single-query-blackbox-v1`；resume/formal identity新增完整prompt contract hash，旧版本/旧hash/缺失hash拒绝续跑。
- [x] runner 22项、PCV parser/scoring 47项、V24套件运行312项（302通过、10项既有skip），合计运行381项（371通过、10 skip）；完整12000-query mock通过，`git diff --check`通过。
- [x] parser、NLI、PVS `S+ * R- - A-`、Luna、selector、eligibility、split与baseline零修改；真实API/Retriever/GPU/formal调用为0，无artifact生成。
- [ ] 下一步：正式victim运行前冻结包含新runtime identity的config+代码；不得复用`pcv-attacker-request-v1`响应。已有构造、Q+/Q-、eligibility与split无需重跑。

### 2026-09-19：V24 主线合并交付

- [x] 用户授权本地提交并将V24合并main；正式长任务由用户启动。
- [x] 确认main是V24祖先，当前原目录有旧V23/论文未提交资产，采用独立主线工作树保留。
- [x] 交付范围为V24构造/补充入口、Gemma服务器兼容、首cell配置及测试；数据/索引及历史失败证据不改。
- [ ] 完成本地合并后在主线验证干净状态、正式输入绑定与可用运行命令；正式cell尚未启动，不推送远端。

冻结参数仍为nfcorpus × Gemma完整BF16 × dense BGE，2000主source、12000问，Reserve=0，top-k5、三对六问、PVS独立负惩罚；服务器版本按用户确认的部署别名记录。唯一下一步为完成主线合并验证并交付用户执行命令。
