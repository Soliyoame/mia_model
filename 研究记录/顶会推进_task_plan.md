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
