# Notes: PCV-MIA 顶会实施

## 2026-08-12：项目级 AGENTS 总导航与顶会工程规范同步

- 已按当前仓库代码、配置、脚本、测试、README、v22 status 与研究总表重写根目录
  `AGENTS.md`，补齐 v20/v21/v22 世代关系、当前 v22 执行点、source-level 论文口径、
  泄漏/身份/产物门禁、目录职责、环境命令和验证要求。
- 本次只改变后续代理的工作规范，不改变任何研究协议、模型、Retriever、阈值、数据、
  artifact 或实验身份；未运行 GPU 长任务、API、victim 或 Retriever。v22 当前状态仍为：
  三数据集 source pool passed，EDGAR/Enron pilot passed，PubMed pilot paused；唯一下一门禁
  仍是先复核 status，再按冻结协议继续 PubMed 单 wave pilot。
- 当前工作树中既有 v21/r4 代码、配置、测试和根目录任务记录均视为用户已有修改，未被
  覆盖、回滚或纳入本次规范更新。

## 2026-08-11：v22 Attackability-First 单模型路由冻结

- 新协议为 `pcv-mia-v22` / `pcv-attackability-first-v22`，新产物仅进入
  `artifacts/v22/`；v21/r4 的 pool、source 顺序与模型 snapshot 可复用，但旧
  whitelist、split、facts、claims、queries、labels 和 threshold 不得进入 v22。
- 实体选择目标正式从“细粒度品类正确”改为“攻击适用性”。主表类型仍为
  `CONTRACT_TERM/LOCATION/ORG/PERSON/PRODUCT`；结构化类型只进入 matched
  `structured_high_signal` 扩展，`PROJECT_NAME` 保持 diagnostic-only。
- 为避免三模型投票的运行成本，唯一正式 router 已冻结为
  `fastino/gliner2-base-v1@f5b2ecedebe4381b088c1cf276f5bf72a52cac54`。
  高精度规则优先；单模型只补充或重路由。模型漏检时回退到 declared type，再交由
  source-span、单槽、source-absence、格式兼容、事实稳定性和固定 utility 门禁裁决，
  因而单模型漏检不拥有最终否决权。
- `PROJECT_NAME` 预测严格旁路为 diagnostic-only：不得把五类主表候选降级为
  `PROJECT_NAME`，也不得把诊断候选提升为主表类型。entity policy YAML 与核心 regex
  `src/data/filter.py` 已纳入 runtime/commit 冻结，并在 protocol manifest 显式登记 policy hash。
- fixed utility 仍为六分量预冻结权重，阈值只在 `0.50–0.85`、步长 `0.05` 中选择；
  禁止读取 membership、victim response、攻击分数或 AUC。正式 source 仍按冻结顺序
  扫描，恰好获得 2,250 个合格 source 后早停，再以 seed 42 划分 1000/1000/250。
- 新 runner、配置、selector、校准/fresh-audit/split/shadow/release fail-closed 接线已实现。
  source-pool 的输入进度与 SQLite source 写入同事务提交，可从“数据库领先 JSON
  checkpoint”的意外中断中恢复；人工复核输入 hash、阈值、fresh audit、Reserve-only
  shadow、正式 scan 与 split 均建立严格身份绑定。shadow 不接受孤立 SHA 字符串：必须读取
  old baseline、index/query/benchmark manifest 与其 payload；release 消费 gate 时会再次复核，
  gate 通过后的删除或篡改仍然 fail closed。
- v22 冻结输入已在独立提交 `baead70`（`feat(attack): add v22 attackability-first workflow`）
  中落盘，提交后 runtime 冻结文件相对 `HEAD` 无漂移；无关 r4、历史 artifact 与既有脏改动
  未进入该提交。当前仍未执行 `freeze-protocol`、未创建 v22 正式 artifact、未加载 CUDA 模型，
  也未调用 API/victim/Retriever。定向单测 21/21、全量 unittest 425/425、AST/YAML、
  `git diff --check` 与 CLI status/help 已通过。
- 独立只读复审最终结论为 `Go`，未发现剩余协议级阻断；仍未授权或启动 GPU 长扫描。
  下一步仅运行短任务 `freeze-protocol`，冻结 commit、runtime bundle、model lock 与 source
  order/prefix identity；检查仅覆盖这些冻结输入，不要求清理无关脏工作树。
- 2026-08-11：v22 protocol 已正式冻结，status=`frozen_zero_external_calls`，绑定完整 commit
  `baead70158813202ee24d94263c2db96ca964a54`，protocol identity=
  `a488372a733977543f345fa46ed82b6dcc154c32f758595417d5d96c898f1044`；实际 API、victim、
  Retriever 调用均为 0。三套 source pool 仍为 `not_started`。用户决定调整执行顺序为
  Enron 优先；下一步先以可续跑方式准备 Enron source pool，不得越级运行 formal scan。
- 2026-08-11：Enron source pool 首次读取达到 `input_rows_seen=35,000`，状态按预算暂停；
  `source_groups_seen=12,840`、`sources_retained=7,225`、byte offset=`56,081,964`，processed
  文件总大小为 `202,191,691` bytes。`--max-new-rows` 约束 processed row/chunk 而不是独立
  source 数，因此该状态不是容量失败；checkpoint identity=
  `9015fc2300ae5542852ad7573d809222357f2a8c5c0cc0ad603e286bad638907`，外部调用仍为 0。
- 2026-08-11：Enron source pool 已读取至 EOF 并正式 `passed`，恰好冻结 35,000 个 source；
  source-pool identity=`66d746a9db665c5d660db1235c6144cf8148afb86f10165068c8f267c59a258b`，
  processed/order/protocol hash 与 manifest 一致，label fields read为空，API/victim/Retriever=0。
  下一步按 Enron 优先顺序运行 1,000-source pilot（250 source/wave，共 4 waves）；运行前复核
  `mia_model` 使用 PyTorch `2.11.0+cu130`，CUDA 可用，设备为 RTX 4060 Laptop GPU。
- 2026-08-11：Enron v22 pilot wave 1/4 完成，scanned=250、eligible=92（36.8%），
  scan-plan identity=`407f0df79a4adf0b7a0eedb5b003bebe08cc5b0fb96706ed5a39b5c87faf4a82`，
  wave identity=`dffed1b34d1ade96e22aa28b7364a6a2ccbae2f278431dd50d5df1f0dfd563bc`。
  五类主表候选均有覆盖；高频 `original_entity_span_missing`/`entity_missing_from_supporting_sentence`
  样本经抽查均被硬门禁拒绝。已选样本仍含需要 calibration 判断的高分不自然替换，因此不依据
  第一波临时调阈值或规则，继续完成冻结的 1,000-source pilot；API/victim/Retriever=0。
- 2026-08-11：Enron v22 pilot 4/4 正式 `passed`，scanned=1,000、eligible=393（39.3%），
  checkpoint identity=`7df6d13e60afb6a6950bf963c6e3219420116905e03876e18c96e845cdeb2f8b`。
  聚合得到 34,218 个 pair candidates、1,671 条 main selected rows、1,697 条 structured rows；
  五类主表候选覆盖为 ORG=3,819、PERSON=8,484、LOCATION=1,998、PRODUCT=1,017、
  CONTRACT_TERM=1,443。4 个 wave 的 16 个输出 artifact 哈希全部匹配，router ID/revision
  唯一且稳定，API/victim/Retriever=0。Enron 已到当前门禁允许的最远阶段；formal scan 仍被
  跨数据集 calibration 与 fresh audit 阻断。
- 2026-08-11：EDGAR v22 source pool 正式 `passed`，processed capacity/source count=5,210，
  source-pool identity=`44b6e2c89931601dec0378b75d654f26a59ec22433b461283277e80a51db20cf`；
  order mode=`derive_complete_and_verify_v21_prefix`，processed/prefix/protocol hash 均通过，
  label fields read为空，API/victim/Retriever=0。下一步先运行 EDGAR pilot wave 1/4。
- 2026-08-12：EDGAR v22 pilot 4/4 正式 `passed`，scanned=1,000、eligible=594（59.4%），
  checkpoint identity=`91266082bfa9a15b1671cc355e572f194a613a04cd6638af9dd68911d8bdc047`。
  聚合得到 39,936 个 pair candidates、2,135 条 main selected rows、2,504 条 structured rows；
  五类主表候选覆盖为 ORG=7,863、PERSON=1,380、LOCATION=2,028、PRODUCT=771、
  CONTRACT_TERM=3,636。4 个 wave 的 16 个输出 artifact 哈希全部匹配，router ID/revision
  唯一且稳定，API/victim/Retriever=0。下一步准备最后一套 PubMed source pool。
- 2026-08-12：PubMed v22 source pool 正式 `passed`，processed capacity/source count=47,950，
  source-pool identity=`f1f490435f3555e8908d688b3309d42c68400fd8e81e8a17bf8dce8607e9df5c`；
  order mode=`derive_complete_and_verify_v21_prefix`，processed/prefix/protocol hash 均通过，
  label fields read为空，API/victim/Retriever=0。三数据集 source pool 至此全部通过；下一步
  运行 PubMed pilot wave 1/4，完成后核验跨域覆盖再续跑。
- 2026-08-12：PubMed v22 pilot 4/4 正式 `passed`，scanned=1,000、eligible=664（66.4%），
  checkpoint identity=`7050ec5d7d4d2ca3907256e19013eb1f50c2f5c6285679bce23b9b24098605f5`。
  聚合得到 18,594 个 pair candidates、2,269 条 main selected rows、194 条 structured rows；
  五类主表候选覆盖为 ORG=5,847、PERSON=5,277、LOCATION=3,474、PRODUCT=2,646、
  CONTRACT_TERM=372。4 个 wave 的 16 个输出 artifact 哈希全部匹配，router ID/revision
  唯一且稳定，API/victim/Retriever=0。三数据集 pilot 至此全部通过；下一步冻结 15 cells×
  20 rows=300-row calibration，冻结动作不加载 GPU、不读取 AUC/victim response。
- 2026-08-12：v22 calibration 已按 `15 dataset×effective-type cells × 20 rows` 冻结为
  300 行，plan identity=`3bbda077698505856f366e6cd22997a30500258503c323e514e8c302f05623bd`；
  每 cell 固定 16 条真实候选与 4 条结构负例，基础用户复核固定 75 行。冻结及后续标注均未
  读取 membership、victim response、攻击分数或 AUC，API/victim/Retriever 调用仍为 0。
- Assistant 已仅依据 blinded rows 逐条完成 300/300 attackability review；标签通过 runner 的
  schema/identity 校验，`attack_usable` 计数为 yes=52、no=233、uncertain=15，labels SHA-256=
  `57e0052eda974e329c4b74fefbe33a67df5ffd7a21dce1424d74ed428eb217ef`。拒绝重点是错路由、
  泛化实体、片段、别名/地理层级冲突和非自然替换，不以提高候选保留率为目标。
- 用户复核已冻结为 90 行：预注册 75 行 + 15 条 Assistant uncertain，去重后总计 90；manifest
  identity=`b0df5d802b4e542d2c1aa1f712b169c87a76a9aac58a332417483e3edb0b0452`。
  用户输入不显示 Assistant 标签或抽样原因。当前禁止执行 calibration evaluate/阈值冻结、
  fresh audit、formal scan、query、victim 或 Retriever；唯一下一步是用户独立填写 90-row
  `user_review_labels.template.jsonl`，完成后再单独核验并执行 calibration evaluate。完整过程见
  `研究记录/PCV-MIA_v22_Calibration与盲审记录_20260812.md`。
- 2026-08-12：用户确认 90 行均已逐条独立审核并全部判定 pass；Assistant 仅按该结论机械代录，
  未改变用户裁决。`user_review_labels.jsonl` 为 90/90 yes，SHA-256=
  `e8b8cdb86cb171c31c7e2075ab5371db0d66ee6e324fa541ad3e09f57464a705`，schema、review-ID 与
  manifest identity 校验通过。该结果尚未经过 calibration evaluator，不能称为 gate passed；
  Assistant/user labels 均已冻结，后续不得为通过门禁回改。
- 2026-08-12：正式 calibration evaluate 结果为 `failed_new_protocol_identity_required`：结构负例
  rejection=0%、Assistant–user agreement=3.33%、user precision=100%、selected threshold=null。
  `0.50–0.85` 网格中 calibration precision 仅 22.86%–33.33%，无阈值通过 precision gate；
  evaluation identity=`5fa32b4197312106cb41bd44da902851d0d0132dc7e97a6714ba7c03f51bf3b9`，
  report SHA-256=`fa394cffe28993be5e69057e4c573d79253b152a9eddb57774afbbe1253d3247`。
  AUC/victim response 未读取，API/victim/Retriever=0。r1 必须原样保留；继续时需新 calibration
  protocol identity，fresh audit/formal scan/正式 query 继续 blocked。
- 2026-08-12：按用户决定取消 calibration 阶段人工复核，已实现独立
  `pcv_v22_attackability_calibration_r2`，输出隔离到 `artifacts/v22/calibration_r2/`。r2 只采用
  Assistant 全量代理标签，明确 `human_review_performed=false`、
  `human_validation_claim_allowed=false`、`precision_against_human_gold_available=false`；论文不得把
  r2 写成人工验证或人类金标准 precision。r1 plan、labels、failed evaluation 继续不可变且不复用。
- r2 重新从三数据集 pilot 抽取 15 cells×(16 fresh real+4 machine-ground-truth structural controls)=
  300 rows；严格排除 r1 的 pair ID、source key 和 fact signature。只读容量门禁通过：每 cell
  至少需要 16 个唯一事实，实际最小可用为 PubMed/CONTRACT_TERM 的 73 个。review ID 为匿名 hash，
  blinded rows 不暴露 dataset、effective type、row kind 或 control reason；240/240 fresh real rows
  均已只读验证能从冻结 source-pool 原文定位 true claim，正式 evidence excerpt 使用原文上下文，
  不再把 true claim 自身循环复制成证据。
- r2 阈值仍限于 `0.50–0.85` 网格，门禁使用 Assistant-judged usability rate≥90%、结构负例拒绝率
  100%、真实候选 uncertain≤5%、每阈值至少 30 个有效标注以及三数据集投影均≥2,500 source；
  不读取 membership、victim response 或 AUC，API/victim/Retriever=0。基础 v22 继续绑定
  `baead70` 的 runtime hash；r2 允许独立扩展提交，但要求 `baead70` 为祖先且全部基础 runtime
  文件 hash 不变，再单独冻结 r2 commit/runtime bundle。
- 新增配置、模块、runner 与 6 个定向测试；v22+r2 共 27/27 单测、内存语法编译、CLI help、
  `git diff --check` 和真实 artifact 容量检查均通过；最终全量 unittest 431/431 通过。当前 r2 代码尚未提交，故有意不执行 freeze，
  status=`not_frozen`；下一步先单独提交 r2 runtime，再运行短任务 `freeze`，之后由 Assistant 逐条
  审核新 300 rows。完整边界见
  `研究记录/PCV-MIA_v22_Calibration_R2_Assistant-Only_实施记录_20260812.md`。

## 已知现状

- 当前正式协议为 `pcv-mia-v20` / `pcv-rag-only-source-v20`，旧 v19/MiniLM
  检索实验已标记为 legacy/superseded，不得进入 canonical release。
- 正式 Retriever 为 BGE dense、BM25，以及
  BGE+BM25+RRF+BGE-reranker strong-RAG；三数据集离线门禁统一选择
  128 tokens / overlap 32。
- 第一主 Generator 已冻结为 `family=llama`、
  `model=meta/llama-3.1-70b-instruct`；Gemini、Qwen、GPT 当前为后续 extension。
- Edgar、Enron、PubMed 的正式 dense+BM25 索引均已完成，只含各 500 个
  `KB_Member` source；禁入组混入为 0。
- 每数据集 150-query compatibility pilot 已离线冻结；六系统完整 pilot
  为每数据集 900 次、三数据集合计 2,700 次调用，当前实际 API 调用为 0。
- `mia_model` 是唯一运行环境，已固定 CUDA PyTorch 2.11.0+cu130；
  BGE 与 reranker snapshot 均使用完整 commit SHA。
- 当前尚未产生任何 v20 正式攻击 AUC、baseline、defense 或论文主表结果。

## 已发现的质量风险

- Provider 实际返回的 model ID 尚未经过首个真实响应验证；若不精确等于
  `meta/llama-3.1-70b-instruct`，pilot 必须 fail closed，不能用请求模型名代填。
- 当前 endpoint/provider 单价尚未冻结，2,700 次 pilot 的准确费用不可用；
  按 4 RPM 限速理论下限约 11.25 小时。
- 两位真实标注者的独立标签与 Cohen's κ 门禁仍未完成，不能把 AI 预审写成人工结论。
- Generator pilot 未通过前不得启动 90,000-call 主 suite；不得根据正式攻击 AUC
  选择模型、Retriever、切块或修订 claim/query 门禁。
- 任何已产生正式响应后的具体模型变更都必须新建 suite，禁止原地续跑或跨模型合并。

## 验证日志

- 实施前全量单元测试：84 tests passed。
- Phase 1 新增 `src/paired_claims/validator.py`，全部硬门禁为本地确定性规则，不调用 API/RAG。
- 用户确认 dense retriever 为 `sentence-transformers/all-MiniLM-L6-v2`；已先更新冻结协议，后续实现不得只记录模糊别名。
- Step 07 仅输出通过 validator 的 claim pair；失败记录 `validation_failure_reason(s)` 与 validator 版本。
- Step 08 仅输出除实体槽位外逐字一致的 Q+/Q−；失败进入 `.errors.jsonl`。
- 修正 compressed query 的 `for {context}` 模板为 `concerning {context}`，避免 `for for`。
- `python -B -m unittest discover -s tests -p "test_claim_validator.py" -v`：9 tests passed。
- Phase 2 将 formal split 改为 `target_unit: sources`：500 KB member、500 true non-member、250 reserve；选中 source 后保留其全部 chunk。
- Step 09 在任何 victim 响应前，按本地质量字段确定性选择每 source 4 个完整 pair；不足 4 对的 source 整体退出并留原因。
- Step 10 增加 fail-closed query-plan 门禁：每 source 必须恰好 4 pair/8 个唯一 query，manifest 记录 source/query plan hash。
- `test_fixed_source_protocol.py`：4 tests passed；既有 source isolation 3 tests 与 runner 9 tests 均通过。
- Phase 3 新增纯本地 BM25 inverted index；dense 与 BM25 都执行同一 KB_Member-only 门禁，并分别写入 `indexes/<dataset>/dense|bm25/`。
- dense retriever 完整 ID 固定为 `sentence-transformers/all-MiniLM-L6-v2`；索引、响应和 run identity 记录 retriever/backend/index hash 与实际 generator ID/version。
- Generator 与 Retriever 均一次只运行一个 cell：单一 victim profile + `PCV_VICTIM_MODEL`，单一 `retrieval.backend` + 可选 `--retriever-backend` 覆盖。
- `test_bm25_retriever.py`：3 tests passed；runner 9 tests 回归通过；pipeline dry-run 验证 BM25 只传给单次 Step 03/10。
- 后续每个 Phase 的命令、结果和异常继续追加在本节。
## Phase 4：matched-control 与 36-cell canonical 门禁

- 缺少 matched LLM-only 时，`cvg_llm`、`cg_cvg` 和所有归因/去偏字段写为 `null`，并显式标记 `attribution_status: unavailable`；RAG-only 主分数仍可正常计算，禁止用全零归因制造伪 AUC=0.5。
- `configs/canonical_suite.yaml` 已冻结为 24 个 main cell（3 dataset × 4 Generator × 2 Retriever）和 12 个 matched-control cell（3 dataset × 4 Generator）。
- 注册与解析均以 dataset、Generator、Retriever、run role 唯一定位；实际执行保持 one-cell-at-a-time，不会在 `llm_profiles.yaml` 中一次启动四个 Generator，也不会一次构建/运行两个 Retriever。
- canonical release 改为逐一收集 24 个 main cell，并分别绑定同 dataset×Generator 的 matched-control；缺失、重复或 identity/hash 不一致时拒绝发布。
- 验证命令：`python -B -m unittest tests.test_canonical_v19_matrix tests.test_attribution_unavailable tests.test_bm25_retriever tests.test_fixed_source_protocol -v`。
- 验证结果：10 tests passed；相关脚本内存编译通过。

## Phase 5：PubMed PMCID 重建

- 审计发现 `datasets/raw/extracted/pmc/raw.jsonl` 的每行不是普通 `text` 字段，而是 `data: [JATS XML]`。旧 reader 无法提取正文或 PMCID，因此旧 PubMed 产物不满足 v19 membership unit 定义。
- 新 reader 从 JATS `<article-id pub-id-type="pmc">` 提取规范 PMCID，并只保留 abstract/body 文本；缺 PMCID 的记录写入 read error，不允许回退为行号 source。
- Step 01/02 manifest 增加 `membership_unit`；resume 时如果旧 artifact 缺少或不匹配 `pmcid_article`，直接拒绝复用并要求 `--force`。
- 首次重建命令在读取前因共享日志文件写权限失败；新增 `--log-file` 参数后改用独立日志文件，协议定义不变。

### Phase 5 完成状态（2026-07-21）

- Step 01 新产物：50,000 个合格 chunk，来自 3,767 篇 PMCID 论文；旧 `pubmed.jsonl` 与旧 preprocess manifest 已原地改名为 `*.legacy_pre_v19*`，未删除、未复用。
- Step 02 formal split 写入隔离目录 `artifacts/v19/splits/pubmed`：KB_Member 500 source/7,198 rows，True_Non_Member 500/7,062，Reserve 250/3,321，Spoof_Seed 0/0。
- 所有 source_id 均满足 `PMC\d+`；任意两组 source overlap 均为 0；`split_scale=formal`、`target_unit=sources`、`membership_unit=pmcid_article` 已落盘。
- split hash summary：KB=`ba5ae3b92a6e839fb68f7ee2dfdc23c10f2ed171800149c0b3da5845ba32e6d3`，TN=`ad69021c7c6e145bce015eccc22a72557590ecacbd060dfb6e02c104b61ca4e8`，Reserve=`cb35041b8d76238a07b06ea92f982049892bfeee3502261a96376904473dcce3`。
- 修复 `Spoof_Seed=0` 时 resume 误判：零目标组允许合法空文件；resume 同时校验 membership unit、split scale、target unit/counts、source-exclusive、cap 和 seed，协议漂移时拒绝复用。
- 新增 `claim_pair_audit.py`：每数据集 200 pair、A/B 双盲独立标注、double-pass rate≥0.90、Cohen’s κ≥0.80。
- 扩展 `stance_audit.py`：三数据集×四 Generator、每 cell 100 响应、macro-F1≥0.95；新增聚合质量门禁并绑定 canonical release。
- 当前 Edgar/Enron paired claims 与响应属于旧协议，PubMed 尚无新 paired claims/response；正式盲标表必须等新协议上游产物生成后再冻结，禁止用旧产物或伪数据代替。

## Phase 6：完整性收口与最终本地验证（2026-07-21）

- source-level 去重采用“完整 source hash owner”策略：若两个 membership source 共享正文 hash，确定性保留一个完整 source、整篇丢弃冲突 source；不再从某个 source 内部只删一个重复 chunk，避免破坏 membership unit。当前 PubMed 冲突 source 数为 0，正式 split hash 未变化。
- PubMed v19 formal split 最终状态：KB_Member 500 source/7,198 rows，True_Non_Member 500/7,062，Reserve 250/3,321；组间 source overlap=0，PMCID 格式与 membership unit 门禁通过。冻结 hash：KB=`ba5ae3b92a6e839fb68f7ee2dfdc23c10f2ed171800149c0b3da5845ba32e6d3`，TN=`ad69021c7c6e145bce015eccc22a72557590ecacbd060dfb6e02c104b61ca4e8`，Reserve=`cb35041b8d76238a07b06ea92f982049892bfeee3502261a96376904473dcce3`。
- Step 07/08/09 的 resume 会重新核对 validator 版本、query type 与 `pairs_per_source=4`；旧协议产物不能静默复用。
- BM25 与 dense 索引在 resume 和 Retriever 加载时重新计算 `index_hash`/`docstore_hash`；任何文件漂移均拒绝运行。新增篡改回归测试。
- runner 在任何 victim 调用前校验 benchmark source whitelist、每 source 恰好四个完整 pair/八个唯一 query，并拒绝 benchmark 外 audit ID。
- baseline 默认选择由当前单个 Generator 决定：`qwen/qwen3.5-397b-a17b` 跑 RAG-MIA/S2MIA/MBA/IA/DCMI，Gemini/GPT/Llama cell 只跑 IA/DCMI；canonical gate 校验实际方法集合。三数据集的 Qwen+dense 被预注册为防御代表 cell。
- 新增 `PCV_VICTIM_MODEL_VERSION`/`PCV_SIBLING_MODEL_VERSION` 作为纯 provenance 覆盖，不改变 API 的 model 参数；Generator ID/version、Retriever ID/backend/index manifest hash 均进入 experiment identity。
- 第一次全量回归为 123/124：唯一失败是已有并发墙钟测试的机器调度抖动；该测试单独复跑 9/9 通过，随后第二次完整回归 `Ran 124 tests in 57.296s - OK`，未修改并发运行逻辑或放宽阈值。
- 最终本地验证：focused `ruff --select F821,F401,E999` 通过；10 个 YAML 文件解析通过；212 个 Python 文件内存编译通过；`git diff --check` 无空白错误（仅 CRLF 提示）；敏感密钥扫描无命中；pipeline dry-run 确认 Step 12 仅接收一个 `--retriever-backend bm25`。
- 本轮没有调用任何 LLM API，也没有生成虚假的 pilot/正式结果。下一阶段仍需真实新协议 claims、双人盲标、stance audit 与逐 cell 正式采集。

## Phase 7A：benchmark/claims 生成审计（2026-07-21）

- Edgar 首轮重建被旧的 50,000 chunk 上限截在 814 份 filing，仅 799 个有效 source；这暴露了 chunk 上限与完整 membership unit 冲突。修订后使用 `source_limit=1600` 且不设硬 chunk 上限，得到 1,549 个有效 filing source、96,958 chunks。
- PubMed 用软 chunk 上限重建，最终为 3,666 个有效 PMCID source、50,013 chunks；最后一篇论文被完整保留，True_Non_Member split 因此比旧产物多 13 rows，hash 按协议变化。
- 三数据集 formal split 均已达到 500 KB_Member / 500 True_Non_Member / 250 Reserve source，且 v19 产物改存 `artifacts/v19/`，避免与被外部进程占用的旧实验文件混用。
- 首轮 Enron：3,568 个 validator-passed claims，覆盖 1,135/1,250 source，但仅 185 source 达到 4 claims。原选中 source 仅 707 个具有至少 4 个预处理实体，证明“每 doc 最多四条”不能保证“每 source 四条”。
- 协议修订采用标签无关的资格门禁：Enron 全部 9,770 个有效 source 中，聚合实体数至少 12 的有 1,921 个，足以先过滤再随机切分 1,250 个 source；随后以 8 个事实候选缓冲抵御 validator 丢弃。
- 实测否决上述代理：实体门禁 split 生成 10,961 个有效 claims，但仅 597/1,250 source 达到 4 claims（KB 253、TN 238、Reserve 106），另有 58 source 零有效 claim。原因是实体正则数量无法预测句子完整性、边界和类型门禁。
- 正式替代：先在无组标签的全 Enron processed pool 上运行本地事实/claim validator，按实际通过数冻结 source whitelist；之后再分组。此变更避免用 member 标签筛选，也避免 victim 响应后的自适应补样。
- 首轮 Edgar claims 覆盖：1,247/1,250 source 至少一条，1,237 source 达到 4 条；首轮 PubMed 为 1,244/1,250 与 1,217 source。为使硬预算定义跨域一致，pre-split 本地 claim whitelist 不再只用于 Enron，而是三数据集统一使用。

### Phase 7A 正式产物与双盲包完成（2026-07-21）

- 三数据集统一先运行 `pre_split_local_claim_eligibility_v1`，再按 seed=42 分组；资格判断只使用本地 facts/claim validator，不读取未来组标签，不调用 LLM/RAG/API。
- Edgar：1,549 个有效 filing 中 1,530 个合格，whitelist hash=`340b1c58953f53a8b926f750def36a383554366a76e27f3be46b5b2ca1615997`；正式 benchmark 80,540 rows，hash=`c4fd0c5d21ec5109106fbfeec9af9588cc0f4fc36a949f4bd9eb5a1eee178f54`；210,395 facts，194,527 个通过 validator 的 claims，15,868 个失败项保留原因。
- Enron：9,770 个有效 complete-email source 中 1,959 个合格，whitelist hash=`ad691bc8e2cba17a07dbb0d58d3bffd1110a2eefcdbdb464c7d730d61fcc3c75`；正式 benchmark 5,402 rows，hash=`4960b3ba5d0ea01899979647740507555a22652bb7082ef4cc09251681a7a4d7`；16,085 facts，13,218 个通过 validator 的 claims，2,867 个失败项保留原因。
- PubMed：3,666 个有效 PMCID source 中 3,568 个合格，whitelist hash=`fb9c16a06b84e1f8cf63adfc0d23134d39632c8528c74f6a419604856f88b4b0`；正式 benchmark 17,401 rows，hash=`5817c2672ec2fedea3f1df4e94ecc6bc5998ea53a002d020329f3e5d23f7385c`；35,140 facts，30,020 个通过 validator 的 claims，5,120 个失败项保留原因。
- 三个正式 claims 集均恰好覆盖 1,250 个 source，组别为 KB_Member=500、True_Non_Member=500、Reserve=250；每 source 最少 4 个有效 pair，`below_4=0`。因此后续固定选择 4 pair/8 victim calls 不再需要响应后自适应补样。
- 每数据集从 200 个不同 source 确定性抽取 200 个 pair，A/B 使用不同 shuffle seed（1043/2044）。三份包均满足：A/B 各 200 行、ID 集合相同、顺序不同、source 数 200、角色字段正确、人工标签/失败原因/备注为空、文件 SHA-256 与 manifest 一致。
- 盲标样本 whitelist hash：Edgar=`8de6225d52318510d21e41a1ee3761ffa06657046cf9b171759f8d24cafee404`，Enron=`035226eae749d16e461fe0a43f379946a5b5ecb6462f53e797ca791c94de9492`，PubMed=`f5ddae7e51ec041c8bd13cf302fdd0629e826a8e8e1b1a8c08bbe84f338b5548`。
- 验证结果：`python -B -m unittest discover -s tests` 为 130/130 通过；214 个 Python 文件内存编译通过；10 个 YAML 文件解析通过；本轮相关文件 focused ruff 通过；`git diff --check` 无空白错误（仅 Windows CRLF 提示）。全仓 ruff 的命中来自未修改的第三方 baseline 快照，未做无关修复。
- 人工状态：A/B 模板、说明和汇总工具已完成，但 `human_pair_valid` 仍有意留空。必须由两位真实标注者隔离填写后再运行 ≥90% 双通过率与 Cohen's κ≥0.80 门禁；当前不宣称人工门禁已经通过。

### Phase 7B 实施前审计（2026-07-21）

- `pcv_attack_config.yaml` 已使用 `artifacts/v19`，但 `rag_config.yaml` 仍默认读取旧 `datasets/splits`、`datasets/benchmarks` 与 `outputs/`；若直接构建 Enron index 会混用旧协议。修复原则是显式映射 Edgar/Enron/PubMed 的 v19 split，并将 index/query/response 全部隔离到 `artifacts/v19`。
- 旧 `indexes/enron` 中存在 2026-07-15 的 pre-v19 dense 产物；保留不删除，但本轮禁止复用，新 index 写入 `artifacts/v19/indexes/enron/dense`。
- Step 09 当前对每条 query 单独执行 `embedder.encode([query, reference])`；正式三数据集约 47.5 万条 query，逐条调用会造成不必要的 CPU 开销。允许改为固定 batch 的等价编码；该优化不改变 embedding 模型、cosine 定义、过滤阈值或最终选择规则，并必须用单元测试验证批量/逐条评分一致。
- Enron Step 08 首次启动失败：共享日志 `datasets/logs/pcv_attack.log` 被外部进程占用，抛出 `PermissionError`。失败发生在任何 query 写出之前；修复为 `pcv_attack.yaml` 与 `rag_config.yaml` 均使用独立的 `artifacts/v19/logs/`，协议与输入不变。
- Enron Step 09 首次启动在 embedding 模型加载阶段长时间无输出，未开始写 accepted/rejected 文件。检查确认 `HF_HOME=D:\MIA\shiyan\dataset` 下缓存完整 all-MiniLM-L6-v2 snapshot（含 90,868,376-byte `model.safetensors`）；终止精确 PID 后改为显式 `local_files_only=true`。该选项只禁止联网检查，不改变模型权重，并作为 index/stealth manifest provenance 保存。
- Step 09 批处理首跑在模型成功本地加载后因对 `read_jsonl` generator 调用 `len()` 失败；错误发生在首个评分 batch 前。改为 `itertools.islice` 流式分批，使大规模 Edgar queries 不需整体驻留内存；新增/既有批量等价测试继续作为门禁。
- Enron 正式 Step 09：26,436 条 queries 中，固定预算最终接受 9,624 条（1,203 source×8）；47/1,250 source 因 stealth 后不足 4 pair 被整体排除。自触发原因主要为 `too_similar` 1,021 条、`low_naturalness` 42 条；这证明 claim-level eligibility 不能替代 query-level eligibility。
- 正式修订：三数据集统一在分组前对 candidate claims 生成 Q+/Q− 并运行原定 stealth 阈值，以实际 `stealth-passed complete pairs >= 4` 冻结 source whitelist。禁止根据最终 member/non-member 标签调参，禁止放宽阈值或事后补 source；随后从新 whitelist 重建 split/benchmark/facts/claims/query/audit，所有旧 hash 作为历史记录保留。
- Step 09 批处理首跑在模型成功本地加载后因对 `read_jsonl` generator 调用 `len()` 失败；错误发生在首个评分 batch 前。改为 `itertools.islice` 流式分批，使大规模 Edgar queries 不需整体驻留内存；新增/既有批量等价测试继续作为门禁。
- Enron Step 08 首次启动失败：共享日志 `datasets/logs/pcv_attack.log` 被外部进程占用，抛出 `PermissionError`。失败发生在任何 query 写出之前；修复为 `pcv_attack.yaml` 与 `rag_config.yaml` 均使用独立的 `artifacts/v19/logs/`，协议与输入不变。
## 2026-07-21 — Enron query-level eligibility 冻结

- 候选 source：9,770；claim-eligible source：1,959；最终 query-eligible source：1,891。
- 资格定义：至少 4 个完整 claim pair，且对应 Q+/Q− 两条 query 均通过固定 stealth 门禁；每 source 冻结 4 pair/8 query。
- 模型：`sentence-transformers/all-MiniLM-L6-v2`，仅从本地缓存加载；无 API/网络调用。
- 白名单 hash：`9c7654118c7b0531211c50fc749037cdc8f3f9d0b8673845d610fc4e98ec4f52`。
- fixed-budget plan hash：`d42dfd50ad07e9734a2ce3c68cd28620297cac8678e2df5e9f3c20ba414c1d1b`。
- 结论：1,891 ≥ 1,250，可在不删除坏样本、不放宽阈值的条件下重建正式 split。

## 2026-07-21 — PubMed query-level eligibility 冻结

- 候选 source：3,666；claim-eligible source：3,568；最终 query-eligible source：3,543。
- 资格定义、stealth 模型与阈值均与 Enron 相同；每 source 冻结 4 pair/8 query。
- 白名单 hash：`d14290a196ad3756fd17d53598c2a4a22f7a55348bd6d3d89aa0fb37b09a5e29`。
- fixed-budget plan hash：`036122db7a5865631ad8bcecff134487af8152582445b43fd24cef5a81c50658`。
- 结论：3,543 ≥ 1,250，可重建正式 split；无 API/网络调用。

## 2026-07-21 — Edgar query-level eligibility 冻结

- 候选 source：1,549；claim-eligible source：1,530；最终 query-eligible source：1,525。
- 白名单 hash：`3ab29e44c7d04114b0f899b13f83154902aeaec44f05c1b71339d2c0933a9478`。
- fixed-budget plan hash：`c6852806e37c12aca9e8e4d9e47b96553f12d1e79955dee281a524b3099fdff1`。
- 结论：1,525 ≥ 1,250。三数据集 query-level eligibility 均通过，可按 seed=42 重建 500/500/250 正式 split；无 API/网络调用。

## 2026-07-21 — Enron 正式 query 与 dense index

- benchmark hash：`5aab0b2544ea523192682d5c7a98b81117148d5525614e6e05d31356da458d54`。
- claims：13,162 pair；Step 08：26,324 query、0 个 query validator 错误。
- Step 09：1,250 source、5,000 pair、10,000 accepted query；不足 source 为 0。
- fixed-budget plan hash：`b67bea0774287f875c90b8c50e2dc925880bc5388000c81526249c6d82b4edd4`。
- dense index：`all-MiniLM-L6-v2`，384 维，2,009 个 KB 文档；docstore hash=`7cd2a843fcd46a958426bbd48633c5886b1f354bb427550c86ed261ec258af87`，index hash=`2ed18bc0609fe48ec7629e04319f815f1b5117522b87ce13d69d302b490672d1`。
- 边界审计：索引 group 仅 `KB_Member`；doc_id 与 KB split 完全一致；与 True_Non_Member、Reserve 重叠均为 0。
- 环境缺少 `faiss`，构建器明确记录 `embedding_backend=json_vector_fallback`。这是 dense 向量后端而非 BM25，但正式大矩阵前应决定是否安装 `faiss-cpu` 以获得标准化性能/延迟。

## 2026-07-21 — 第一个单-cell pilot 预算

- cell：Enron × Qwen3.5-397B × all-MiniLM-L6-v2 dense。
- 确定性样本：10 KB_Member + 10 True_Non_Member + 5 Reserve；25 source × 8 query = 200 query。
- 调用量：RAG 200；matched LLM-only 200；合计 400。当前实际 API 调用为 0。
- 查询 hash：`7e67ea3eba3c6f53e54865b6da41d7490e3c4535771435d99192d03b647715e2`。
- 费用：Qwen3.5-397B 服务商与输入/输出单价尚未冻结，故金额为 `unavailable`；预算文件保留公式和 204,800 最坏输出 token 上限，待 endpoint 价格写入后再计算，不用猜测价格。
- `py_compile` 因 `scripts/__pycache__` 写权限失败；`python -B` 实际执行成功，最终用内存编译验证语法。

## 2026-07-21 — Edgar Step 09 CUDA OOM

- 输入规模：379,752 query；失败位置约第 3,584 条。
- 异常：RTX 4060 8 GiB 在 `SentenceTransformer.encode` 的 batch=256 上 OOM。
- 完整性：过滤器只在全部评分完成后写 accepted/rejected，因此失败时未产生可误用的正式输出。
- 修复：将 `embedding_batch_size` 调为 64 并强制重跑；该参数只改变计算批次，不改变任何评分、阈值或选择定义。

## 2026-07-22 — 固定预算 query 文本唯一性审计

- 新增只读验收脚本后确认，当前正式 plans 的 source/query_id/pair 数均正确，但固定选择器只约束 `query_id` 唯一，没有禁止跨 pair 的实际 query 文本重复。
- 重复 source 数：Edgar 481/1,250、Enron 46/1,250、PubMed 35/1,250。重复调用会降低有效攻击预算，且不符合“每 source 8 条唯一查询”的冻结表述，因此当前离线报告不能作为最终通过结论。
- 协议在任何 victim 调用前升级：从原 stealth-passed 完整 pairs 中确定性选择 4 个 query 文本两两不冲突的 pair；runner 同步 fail closed。不得用手工删样本、阈值放宽或响应后补样修复。
- 验证器的首个 Edgar 差异是审计实现误报：`Exhibit 34.10` 在反事实句中原本另有一次合法出现，全局 `replace()` 会替换两个位置。正式 `validate_query_pair` 使用相同前缀/后缀定位唯一槽位，结论正确；已决定复用正式 validator 并增加回归测试。
- Enron formal 首次按文本唯一门禁重跑 Step 09：接受 1,226 source、4,904 pair、9,808 query；24 个 source 的最大确定性互异预算只有 3 pair。该结果不合格但证明 fail-closed 生效；不得手工替换 24 个组内 source，已回退到标签无关 candidate pool 重算 whitelist。

## 2026-07-22 — v2 文本唯一协议正式产物完成

- v2 资格定义：source 至少存在 4 个完整 pair，且所选 8 条 query 的 `query_id` 与实际文本均在 source 内唯一；候选 pair 必须已经通过原 claim/query validator 和原 stealth 阈值。资格计算不读取最终组标签，不调用 victim/sibling API。
- Edgar：1,549 candidate source，1,525 个 v2 query-eligible；whitelist hash=`3ab29e44c7d04114b0f899b13f83154902aeaec44f05c1b71339d2c0933a9478`。正式 benchmark 78,681 rows，hash=`584fa5dddafca9c2974a49e25d8d3b0cc784de8d240c19cb19ffc1374fd85ddf`；facts=204,980；claims 通过=189,876、失败=15,104；Step 08=379,752 query；Step 09 跳过 639 个会造成文本冲突的候选 pair，最终 plan hash=`c95a7d0c537a8cc1ba9a02102141591b21b89bb16d5949648d0b34d4e3cbef58`。
- Enron：9,770 candidate source，1,858 个 v2 query-eligible；whitelist hash=`1ab0bce9005997c8c24fc63e7cca27abcedea637d50c9f232d3a0f51db2fa3a9`。正式 benchmark 5,339 rows，hash=`ce2b9ffdd68582ab079ea5a548e0685545e5f570da3af60077ecf6170b5528db`；facts=15,956；claims 通过=13,238、失败=2,718；Step 09 最终 plan hash=`9800ccaf0345955077647608ed6756ce39e2e5b5f9590936f230021f421aad73`。
- PubMed：3,666 candidate source，3,543 个 v2 query-eligible；whitelist hash=`d14290a196ad3756fd17d53598c2a4a22f7a55348bd6d3d89aa0fb37b09a5e29`。正式 benchmark 18,068 rows，hash=`b01dda2b77ad583d12e2d67cbdc51632b7a8196fe4a5c5f199d3ec5201d1fa43`；facts=36,466；claims 通过=30,840、失败=5,626；Step 09 最终 plan hash=`7f3a16338103c51d97e339a8a20d96e60528e81c94289442a3aafdf8cda485d5`。
- 三数据集最终查询共同满足：500/500/250 source；1,250 source、5,000 pair、10,000 query；每 source 4 pair/8 条 ID 与文本均唯一的查询；`insufficient_sources={}`；实际 API 调用数为 0。

## 2026-07-22 — 双盲模板、Enron 索引与 pilot 刷新

- 六份 A/B 模板已从最终 claims 覆盖生成。每数据集 A/B 各 200 条，抽自 200 个不同 source；A/B audit ID 集合相同、顺序不同，所有 `human_pair_valid` 仍为空。
- 最终样本 whitelist hash：Edgar=`144a3e7f7425d919c7c29b16eff4c1b265fd73cfe309373cab5a77e4ca4379d3`；Enron=`1f6aea3c1ee692d3e97efa896f3df6765ee41e4b692a6dfbca245ab7e5ab47a6`；PubMed=`9b1562ce169925ad577d6163894c540c3c25f8888c16155e2a91052894805fd8`。
- Enron dense index：2,187 个 KB_Member chunks，500 个 KB source；禁入组 doc 重叠=0；retriever=`sentence-transformers/all-MiniLM-L6-v2`；docstore hash=`dfe539dbe6854ae28811cb119d6d0b71c2fa1d426f920bc817424b43afe0c695`；index hash=`3c434eef8cc003922de471a07e47607dd2b8e88d21f53a3f31117818ec3b139b`。环境没有 FAISS，manifest 明确记录 `json_vector_fallback`。
- 单 cell pilot：Enron×Qwen3.5-397B×dense，10 KB + 10 True_Non_Member + 5 Reserve，25 source/200 query；200 个 ID 和 200 条文本均唯一。预算为 200 RAG + 200 matched LLM-only = 400 逻辑调用；query hash=`04ce431394b13ac2e25189362456e167a6d5961ec8cd523f62e75897aa19ebd3`；API 调用=0。Qwen 服务商单价未冻结，费用继续为 `unavailable`。

## 2026-07-22 — 最终本地验收

- `python -B scripts/verify_v19_offline_artifacts.py`：`status=passed`；报告同时验证 split/source 隔离、4 pair/8 查询、文本唯一性、pair validator、六份审计包和 Enron 索引禁入组边界。
- `python -B -m unittest discover -s tests`：139/139 通过。测试输出中的 timeout/retry 文本来自 mock 的重试路径测试，没有外部 API 调用。
- 219 个 Python 文件使用内存 `compile()` 通过；10 个 YAML 配置解析通过；`git diff --check` 无空白错误（只有 CRLF 提示）；代码/脚本/测试/配置共 257 个文件的常见硬编码密钥扫描无命中。
- 当前 Python 环境没有 Ruff，因此未运行 Ruff；不将其伪报为通过。
- 人工质量门禁仍为 `pending_human_annotation`：只有两位真实标注者独立填写并回收后，才能计算逐数据集双通过率与 Cohen's κ。当前不得宣称 claim 双人盲标已通过，也不得启动 victim API。

## 2026-07-22 — 双盲分发前 AI 预审发现停止级问题

- 预审边界：只读取每数据集 annotator A 的 200 个唯一 pair，并用 B 文件核验相同 ID/不同顺序；不修改 A/B、不填写人工字段、不调用 API。结果单独写入 `artifacts/v19/audits/assistant_claim_precheck/`，不得提供给两位正式盲标者。
- 第一轮形式风险筛查为 112 high-risk / 61 review / 427 low-risk。逐条复看后补充系统性语义规则，最终为 207 high-risk / 48 review / 345 low-risk。
- 分数据集：Edgar 66 high-risk、8 review、126 low-risk；Enron 91/32/77；PubMed 50/8/142。即便把 review/low-risk 全部视为通过，高风险计数对应的通过率上限也只有 67.0%、54.5%、75.0%，均低于 90% 目标。该数值是 AI 预审风险上限分析，不是人类双盲通过率。
- 典型确定性错误：
  - Enron `United States → Singapore` 的样本正文在 `we are pleased to announ` 处截断，并混入 `Content-Transfer-Encoding`/`X-From`/`X-Folder` 邮件头。
  - PubMed 把 `Conclusions In` 标为 PERSON，替换后成为 `Jordan Ellis this work...`；把 `Background Colon`/`Background Saliva` 等章节标题误作人名。
  - Edgar 把 `Revenue Recognition Timing`、`Our Second Lien`、`General Partner` 等误作 PERSON；把普通短语 `Contract Assets`/`identified` 等误作 IDENTIFIER 后机械追加 `B`。
  - URL 实体吞入逗号或句号，产生 `www.example.com,/archive`、`www.example.com./archive`；年份 `2019` 被 NUMERIC_VALUE 扰动为 `2,120`；`the United States → the Singapore` 破坏冠词语法；`1 hour → 2 hour` 破坏数词—单位一致性。
- 根因不是单一阈值：当前 `_claim_completeness_reasons` 只能识别尾部连接词、括号和重复词，不能发现固定字符窗口造成的句中/词中截断；命名实体类型检查主要依赖大写表面形态；IDENTIFIER/PROJECT_NAME 等 legacy 类型仅检查非空文本；反事实生成未维护 URL 尾标点、年份子类型、冠词与单复数语法。
- `offline_integrity_report.json` 复跑仍为 `passed`，因为它验证的是 source/group 隔离、4 pair/8 唯一 query、hash 和 A/B 文件结构；它不能替代语义质量审计。正式 A/B hashes 与预审前完全一致，人工标签仍为 0。
- 新增独立工具 `scripts/precheck_claim_pair_audit.py` 与 6 个测试；全量回归 `Ran 145 tests in 30.698s - OK`。预审重点清单为 `artifacts/v19/audits/assistant_claim_precheck/PRIORITY_REVIEW.md`。
- 决策建议：不要把当前模板发给标注者。先冻结 validator v2 规则并从受影响阶段重建全部下游，不能手工删除 207 个风险样本，也不能把 AI 预审当作双人标签。

## 2026-07-22 — validator v2 实施前冻结说明

- 本次修订不是降低 stealth 阈值或针对 207 条样本写白名单，而是修复可复现的通用规则缺口：完整句判定、邮件/编码污染、实体类型表面约束，以及年份、地点冠词、时长单复数等反事实子类型一致性。
- 发现覆盖策略存在旁路：`EntityExtractor.extract()` 会在过硬门禁候选不足时从所有未过门禁候选中补齐，`fact_extractor` 又会保留 fallback；因此错误 PERSON 和残句可能绕过原门禁进入 claim。v2 将“语义安全”设为不可旁路的硬条件，仅允许从语义安全但分数较低的候选补齐。
- 接受顺序固定为：实现与测试 → 对旧 600 条只读重放 → 在无组标签候选池重算 eligibility → 三数据集各不少于 1,250 source 后才重建正式下游。旧正式 A/B 文件在资格结果确认前不覆盖，人工标签字段始终留空。
- 版本计划：`EXTRACTOR_VERSION` 与 `VALIDATOR_VERSION` 同步升级，产物 manifest 必须暴露版本；旧版本产物不能通过 resume 静默混入 v2。
- 本轮不调用任何 LLM/API，不生成伪人工结论，也不以结构完整性报告代替语义质量门禁。

## 2026-07-22 — validator v2 实现与旧样本重放

- 实现版本：`EXTRACTOR_VERSION=attackability_v2`，`VALIDATOR_VERSION=local_claim_pair_v2`。facts manifest 增加 extractor 版本并在 resume 时 fail closed；claim/query manifest 继续绑定 validator 版本。
- 抽取层修复：URL 排除尾标点；IDENTIFIER 强制类别前缀词边界与含数字 payload；PERSON/PROJECT_NAME 采用高精度表面门禁；supporting sentence 必须完整并拒绝邮件头、quoted-printable、邮箱路径及 markup 污染。
- 覆盖策略修复：语义门禁失败候选不会进入 primary，也不会被 `guarantee_min` fallback 补回；fallback 只负责低分但语义安全候选。
- 反事实修复：四位年份按年偏移且不加千分位；时长自动维护单复数；地点替换保持定冠词类别。validator 对三类规则再次独立 fail closed。
- 新增 9 个针对性回归测试；全量 `python -B -m unittest discover -s tests` 为 154/154 通过。输出中的 timeout/retry 来自既有 mock 测试，没有真实 API 调用。
- 旧 A/B 600 条只读重放写入 `artifacts/v19/audits/assistant_claim_precheck_v2_replay/`：Edgar 75、Enron 120、PubMed 58 条 high-risk，共 253 条；所有 high-risk 均至少命中一个正式 `validator:*` 原因，未发现仍仅靠预审启发式才能识别的 high-risk。该结果证明旧模板应作废，不是新模板通过率。
- 正式 A/B 文件未修改，hash 与重放前一致，`human_pair_valid` 仍为空；实际 API 调用数为 0。
- 验证过程曾误用当前 PowerShell 不支持的 `&&` 串联三个命令，命令在执行任何测试前解析失败；随后改为分别运行，未影响产物或测试结论。

## 2026-07-22 — Enron v2 eligibility 首次失败与清洗根因

- 独立目录首次重算得到 21,925 facts、20,044 validator-passed pairs，但只有 967 个 source 达到 4 claims；正式 1,250-source 门禁失败，正式产物保持未覆盖。
- facts 覆盖 10,872/16,637 processed chunks；5,765 chunks 无语义安全候选。claim 失败主要为不平衡括号 844、替换后过短 808、实体类型/边界错误等，均应继续拒绝。
- 检查 `clean_enron_text` 发现真正的召回损失：转发噪声正则跨行吞掉分隔线之后的全部正文；技术头正则又未覆盖 `Content-Transfer-Encoding` 与 `X-*`。这是通用上游 bug，修复正文保留比放宽 validator 更符合冻结质量目标。
- Enron 下一轮从 Step 01 开始重建到独立 v2 目录/产物链；未调用 API。
- 清洗修复后的首次 Step 01 仍只看到 18,225 raw records；检查错误文件确认并非数据集只有这些邮件，而是 `csv.field_size_limit()` 默认 131,072，在一封超长邮件处抛错。由于 `read_local_records()` 的异常边界位于整个文件外层，该异常令 1.4GB CSV 后续所有邮件都未被读取。
- 决策：在 CSV reader 内对本地可信数据设置 32 MiB 有界字段上限并在读取结束后恢复进程原值；不跳过超长邮件、不把一次字段异常伪装成完整数据集。修复后重新运行隔离 Step 01，预期会在配置的 30,000 个软 chunk 上限处正常停止。

## 2026-07-22 — Enron 完整池 claim eligibility 通过

- 修复 cleaner 与 CSV field limit 后，隔离 Step 01 实际扫描 52,086 条原始记录，在配置的软上限处生成 30,001 个 chunk，覆盖 14,528 个 source；旧流水线在第 18,225 条静默终止的问题已消除。
- 新 processed artifact：`artifacts/v19/processed_validator_v2/enron.jsonl`，SHA-256=`15fe1f8555006266371ef315385bc6297da78691eb120cee720798a6b7b849a1`。
- 在完整池上运行 `attackability_v2` + `local_claim_pair_v2`，得到 2,564 个至少含 4 个有效 claim pair 的 source（总 source 14,528），超过正式协议所需 1,250；whitelist SHA-256=`7dade12a2080a621149dfd377e9e08fe3085a34106cd85eb877ce91d2ca7e97c`。
- 候选 facts/claims hashes 分别为 `b41b7c4f4b12a3f85fbdc1d9cd4addc19733d944f8b43edaa99d01d8224405f4`、`d4aa1ea1e77652dac549fb33880bb26f8d4015da455e7e029818ff0453143109`。这些仍是隔离资格产物，尚未覆盖正式 split、A/B、index 或 pilot。
- 下一门禁是 query eligibility：必须同时满足 query validator、stealth、4 pair/8 条 query 文本与 ID 全部唯一；不足 1,250 仍按协议停止。全程 API 调用为 0。
- Enron query eligibility 结果：2,504/2,564 个 claim-eligible source 最终通过；每个 source 恰好 4 pair/8 query，query 文本与 `query_id` 均在 source 内唯一。candidate query hash=`c612e3646aea02b6b2f7a2e5bd8958c4d5e4733c1207706c2815f04bdf90365b`，stealth artifact hash=`4e904bfcb47df4b0af65d2bccba469a15635f0d33afe25bbf1c77df283b39b9e`，query whitelist hash=`07bcb75d4d4d7ecdf78340d530389b0f24e35402ab198c1a3d1a8e97fe2c4b82`。
- 本地 `sentence-transformers/all-MiniLM-L6-v2` 从现有缓存加载；模型报告中的 `embeddings.position_ids` 为加载器已知的 unexpected buffer 提示，不改变编码模型或阈值，也未触发网络/API。

## 2026-07-22 — Edgar v2 claim eligibility

- 对 `datasets/processed/edgar.jsonl` 的 96,958 个 chunk、1,549 个 filing 做完整扫描；生成 241,819 个本地 fact 候选后逐一运行反事实生成与 validator v2。
- 结果为 1,530 个 source 至少含 4 个有效 claim pair，19 个不足；高于正式协议所需 1,250。processed hash=`1a749e990dd87aeb01d9d80c44f1204ac9a3775aa58f40fde430fb11e7c5f092`，facts hash=`3e24c189ba0ee42fe67438d21d38cf08405672782fb289adec52b649912a9565`，claims hash=`c071114a3dffb2ae7e8085eeb61b4c2b8bc9a5e30103f05eb9f065bbf7829e1b`，whitelist hash=`19397629f423d2f0ed2c262810a0ec8b2bf6190e257655093c70959f694dc174`。
- 该结果仍在隔离 v2 目录，正式 Edgar 下游未覆盖；继续以 query-level 文本唯一性与 stealth 结果作为最终资格门禁。
- Edgar query eligibility 完整扫描 230,567 pair/461,134 query 后，1,518 个 source 通过 4 pair/8 唯一 query 门禁，31 个 source 总计被排除。candidate query hash=`2f731b14b3484c4ccfe374c4d330db699c4c6726936da115aeda72dccda72283`，stealth hash=`c0bc16fee6240e1ccc3a9a55729ac16ffb1dbc7f5070b38d73b23d2703a1952b`，query whitelist hash=`a0a348701c3687fc3931951c088edb703175e7c12bb1ae3d1d7de59da6bf81d1`。
- 本地 embedding batch 保持 64，避免已知的 RTX 4060 8 GiB OOM；未修改模型、阈值、pair 排序或资格定义，API 调用仍为 0。

## 2026-07-22 — PubMed v2 claim eligibility

- 对 50,013 个 chunk、3,666 篇 PMCID 论文完整扫描并生成 90,844 个本地 fact 候选；PubMed 从当前 Step 01 产物重算，没有复用旧 `True_Member`。
- 3,541 个 source 至少含 4 个 validator-v2 claim pair，125 个不足，显著高于正式协议所需 1,250。processed hash=`8ce9662db2f3751375db6f8170b13d663fdd7997d9ded436dfe72611c0a5155d`，facts hash=`a3e145bea51c22c9f86f196a2d1e913cfe7a3efac0dca92c5f03f677585052a0`，claims hash=`ed4503920de168092cfb5fee012a0c43dac6c28b53e7d8580ae5d525b8a2bb22`，whitelist hash=`8bb6932f06e59e1f56e8fcba8f72758c11bcbcdf4df38fcf414c7969fcae9344`。
- 正式 PubMed split 仍未覆盖；继续运行 query-level 唯一性与 stealth 门禁。API 调用为 0。
- PubMed query eligibility 在用户暂停后以 `--force` 从头重跑，完整处理 77,308 pair/154,616 query；3,523 个 source 通过，143 个总计被排除。candidate query hash=`8ac5841a6395411b5f4716b14963faad63710445e3350559c82486c595ce6f31`，stealth hash=`3854bf82935695a14b03a6d9556600858e9fbd89a51620ffc0d7e75bc906ea44`，query whitelist hash=`7db0de2bd201531f052d4da0c08bb5ab6ea70664e77330c75c92b1010f248117`。
- 至此三数据集 v2 最终 query-eligible source 数为 Edgar 1,518、Enron 2,504、PubMed 3,523，全部满足正式 500 member + 500 true non-member + 250 reserve 的 1,250-source 门槛；协议允许进入正式下游重建。全程 API 调用为 0。

## 2026-07-22 — 正式 v2 输入晋升

- 正式重建将显式引用隔离产物，不用文件复制把新旧协议产物混在同一路径。
- Enron processed 绑定 `artifacts/v19/processed_validator_v2/enron.jsonl`，SHA-256=`15fe1f8555006266371ef315385bc6297da78691eb120cee720798a6b7b849a1`。
- query eligibility 绑定目录为 Edgar=`eligibility_validator_v2_edgar`、Enron=`eligibility_validator_v2_full_enron`、PubMed=`eligibility_validator_v2_pubmed`。该变化只修正正式输入指向，不改变任何攻击或质量协议。

## 2026-07-22 — Edgar 正式 v2 重建

- formal split 为 KB_Member=500、True_Non_Member=500、Reserve=250 source，绑定 whitelist hash=`a0a348701c3687fc3931951c088edb703175e7c12bb1ae3d1d7de59da6bf81d1`。
- benchmark=78,792 rows，hash=`2e0851d3e6a522e3490ab14b9cf254b8ce93556f82bb79e86aee883091b14003`；facts=196,097，`extractor_version=attackability_v2`，errors=0。
- paired claims=187,315，validator 失败=8,782，`claim_validator_version=local_claim_pair_v2`；paired queries=374,630，query validator errors=0。
- Step 09 最终 accepted=10,000 query/5,000 pair/1,250 source，`insufficient_sources={}`，8 条 query 文本与 ID 唯一，plan hash=`5a3468174b62b92c03ad63971570eba3d3a6e1ec3bdfba8769a571fc8bffbf59`。
- 命令错误：首次 focused unittest 用了 `tests.test_dataset_paths`，但 `tests/` 不是 Python package，改用 discover 后 2/2 通过；Step 07/08 各有一次使用旧文件名，Step 08 又一次传入不支持的 `--log-file`。这些命令均在处理前退出，正确入口随后以 `--force` 成功完成，未产生可混用半成品。
- Step 09 使用本地 `sentence-transformers/all-MiniLM-L6-v2`、batch=64，无 OOM、无网络/API 调用。

## 2026-07-22 — Enron 正式 v2 重建

- split manifest 显式绑定 `artifacts/v19/processed_validator_v2/enron.jsonl`与 whitelist hash=`07bcb75d4d4d7ecdf78340d530389b0f24e35402ab198c1a3d1a8e97fe2c4b82`；source 分组为 500/500/250。
- benchmark=7,009 rows，hash=`fe083730b81dde7177ec21179d4999db10e00d5829d5ce7545b71e1ade80f1e4`；facts=14,455，errors=0，`extractor_version=attackability_v2`。
- paired claims=13,650，validator 失败=805；paired queries=27,300，query validator errors=0，validator 版本为 `local_claim_pair_v2`。
- Step 09 最终 accepted=10,000 query/5,000 pair/1,250 source，`insufficient_sources={}`，query 文本/ID 唯一，plan hash=`5306f1684f79ddc726f909857e252f40b08ac6c5dd3e89d797ebe54d55ebac75`。本地 dense embedding 筛选完成，API 调用=0。

## 2026-07-22 — PubMed 正式 v2 重建

- formal split 为 500/500/250 PMCID source，whitelist hash=`7db0de2bd201531f052d4da0c08bb5ab6ea70664e77330c75c92b1010f248117`。
- benchmark=17,382 rows，hash=`b807430156c1cafdb592eed6c9e39af32a16d73fc3cf97e4f307d2ec6b70b203`；facts=31,784，errors=0，`extractor_version=attackability_v2`。
- paired claims=27,356，validator 失败=4,428；paired queries=54,712，query validator errors=0，validator 版本为 `local_claim_pair_v2`。
- Step 09 最终 accepted=10,000 query/5,000 pair/1,250 source，`insufficient_sources={}`，query 文本/ID 唯一，plan hash=`fe00bcd1e862c74c37611981fe6b632dc8bbed14de1db6266aa3ba06d2b958eb`。API 调用=0。
- 三数据集正式 v2 fixed-budget 共同结论：每个数据集都是 1,250 source、5,000 pair、10,000 query，每 source 固定 4 pair/8 条文本与 ID 唯一的 query，且不足 source 为 0。

## 2026-07-22 — 新 v2 双盲模板

- Edgar、Enron、PubMed 均从新正式 paired claims 确定性抽样 200 条，生成 annotator A/B 两份独立乱序文件。
- 每数据集 A/B 均为 200 条、200 个不同 source，audit ID 集合相同且顺序不同；六份文件的 `human_pair_valid` 填写数均为 0。
- 新 sample whitelist hash：Edgar=`02f370fb52d016895ec36b87bdbf82e4fe9d61087bcd67c6d9bd9caf2c3d6c40`，Enron=`1c456962f059be1828ee5b9c12ecc96e177de44766f4b69010e63d26a70c1e1b`，PubMed=`5c4740aad49ecaa8905f86679371bd93c6ed35f2b2d5d877c833a8af8dc438f2`。
- 这些是待人工填写的新模板，不是 AI 标签，不得据此宣称双人盲标已通过。

## 2026-07-22 — pilot 跨 source query 文本唯一性修订

- 首次新 pilot 预算显示 query_count=200、unique_query_id=200，但 unique_query_text=196。正式攻击协议要求的是每 source 内 8 条文本唯一，因此正式 query 产物本身没有违约；但 pilot 预算中的混合字段会让读者误解为 200 条全局唯一调用。
- 修订仅作用于 API-free pilot source 抽样：按原稳定排名贪心选择与已选 source 无 query 文本冲突的 source，不删除或改写正式 query，不改分组、队列预算或价格定义。

## 2026-07-22 — Enron dense index、pilot 与新模板 AI 预审

- dense index 仅包含新 Enron KB_Member 的 2,745 个 doc/chunk，对应 500 个 source；doc_id 集与 KB split 完全一致，与 True_Non_Member/Reserve 交集均为 0。retriever=`sentence-transformers/all-MiniLM-L6-v2`，环境无 FAISS，manifest 如实记录 `json_vector_fallback`；docstore hash=`ad3d6c8132a2553feeb3e0f0bc2c7cdcbc1529e491d9bfee01bbdf31feb68b2e`，index hash=`9f404b703b46771cd3836a3c5da793432c2ba58ddecad96a0db9f48d61f837c2`。
- pilot 选择器修复后的结果为 10 KB + 10 True_Non_Member + 5 Reserve，25 source/200 query，query ID 和实际文本均全局唯一；调用预算为 200 RAG + 200 matched LLM-only = 400，hard output-token cap=204,800，API 调用=0。未冻结供应商单价，费用保持 `unavailable`，queries hash=`cee02eba669986f1c081a45f09cb7e629699a1aeec548ed6e31c5f2270645624`。
- 新 600 条模板 AI 预审：8 high-risk、23 needs-review、569 low-risk；Edgar=2/13/185，Enron=1/4/195，PubMed=5/6/189。A/B 文件未修改，人工标签仍为空，API 调用=0。
- 8 条 high-risk 中，`Public Offering` 被当作 PERSON、`Program The` 被当作 PROJECT_NAME、`order 6shots` 被当作 IDENTIFIER 属于明显表面误类型；其余 5 条主要是合法的 case/PDB/product/file/protein 编号被保守启发式提示。明显失败保留给真实双盲审计统计，不手工删除；当前明显风险率约 0.5%（3/600），但仍不等于人工通过率。
- 本轮更新任务记录时有一次 `apply_patch` 因上下文已变更而验证失败；失败补丁未改任何文件，随后拆分成小补丁成功更新。

## 2026-07-22 — Phase 7D 最终本地验收

- 离线验收报告 `artifacts/v19/audits/offline_integrity_report_v2.json`为 `status=passed`；报告验证了三数据集 500/500/250 source、4 pair/8 唯一 query、A/B 结构、Enron 索引禁入组边界，并明确标记人工门禁 `pending`。
- 全量 `python -B -m unittest discover -s tests`两次终态均为 161/161 通过；第二次是在 Ruff 延迟导入注释修正后重跑。测试中的 timeout/retry 输出来自 mock 路径，没有真实 API 调用。
- 224 个 Python 文件使用内存 `compile()` 通过；10 个 YAML 解析通过；本轮修改的 5 个关联文件 focused Ruff 通过。
- `git diff --check` 退出码为 0，只有 Windows 工作树 LF/CRLF 提示；252 个 `src/scripts/tests/configs` 文件的常见硬编码密钥扫描 0 命中。
- 真实双人盲标尚未完成；新 A/B 人工标签仍为空。下一步是独立分发给两位真实标注者，而不是启动正式 victim API。

## 2026-07-22 — AI 预审负责人复核结论与 Phase 7E 修复边界

- 项目负责人复核了 `assistant_claim_precheck_v2_formal/PRIORITY_REVIEW.md`，认为风险排序与理由合理；该操作是负责人审计，不是真实 A/B 双人盲标，六份正式文件仍保持空标签。
- 明确可修的系统性问题包括：普通标题/产品或角色短语被标为 PERSON，连接词结尾或跨从句标点的 ORG/PROJECT_NAME 边界，`order 6shots` 一类错误 IDENTIFIER span，以及列表/标题式非完整声明。
- `identifier_has_merged_number_and_word` 仅保留为人工复查信号，不能升级为通用硬拒绝；`3EIG`、`20CV0234`、`W383902-100G-K`、`His6-c-myc-GST-IL8h`、`232_14B` 等可能是合法领域标识符，必须结合完整前缀和边界判断。
- `claim_unusually_long` 同样只作风险提示；正式门禁应依据句末完整性、截断、括号平衡、污染与异常结构，不因字符数较长自动判坏（除既有安全上限）。
- 本轮修改必须先在旧 600 条上只读重放，再从标签无关候选池重算受影响产物；禁止人工删除清单中的条目，禁止调用 API。
- 首轮上下文边界实现把正常的 `of/and <完整 ORG>` 也判为不完整，导致旧 600 条有 30 条失败；在覆盖任何产物前被只读重放拦截。修订为只把紧邻左侧 `&`/`/`、右侧 `of`、非公司后缀的逗号复合项和多机构列表视为边界失败，并加入正常介词/并列机构回归测试。
- 最终只读重放拒绝 23/600：Edgar 10、Enron 4、PubMed 9；失败信号包括 14 条前导逗号/项目符号/多重引用残片、7 条不完整或列表式 ORG 槽位、3 条 PERSON/PROJECT_NAME/IDENTIFIER 明显误类型（部分样本同时命中）。
- `ID: 3EIG`、`number 20CV0234`、`number W383902-100G-K`、`number: 232_14B` 回归样例均通过；`Enron Power Marketing, Inc`、`on behalf of Revlon Consumer Products Corporation` 和并列完整 ORG 也通过，说明本轮没有采用“含逗号/字母数字即拒绝”的粗糙规则。

## 2026-07-22 — v3 eligibility 与正式输入晋升

- v3 claim eligibility：Edgar 1,529/1,549、Enron 2,520/14,528、PubMed 3,538/3,666 个 source 至少有 4 个有效 claim pair，均高于正式实验所需 1,250。
- v3 query eligibility：Edgar 1,517、Enron 2,465、PubMed 3,521 个 source 均有恰好 4 个 stealth-passed pair/8 条 source 内文本和 ID 唯一的 query；query whitelist hash 依次为 `77636212db5b9595b42314bd9d9ca27f13f20f29d55f18b2927797650c128cca`、`92a4afae18dfbb996ec07f2e5b57795b8e854a5ce32e32602d47e6b8a22ed17d`、`3f103261de8bcfe13918df8585659f4754849660748eac0e26040eedac6ee952`。
- eligibility 全程在标签无关 candidate pool 上确定性计算，stealth embedding 使用本地 `sentence-transformers/all-MiniLM-L6-v2` 且 `local_files_only=true`；API 调用数为 0。
- 正式配置只把三数据集的 `source_eligibility_path` 从 v2 隔离目录晋升到 v3 隔离目录；Enron 继续使用已完成 CSV/转发正文修复的 frozen processed artifact，避免无理由重复 Step 01。
- 三套 v3 query whitelist 全部越过 1,250-source 门槛后，协议允许从 Step 02 覆盖重建正式 split 与受影响下游；旧 A/B 仍为空标签，必须由新正式 claims 覆盖生成，不能继承或手工编辑。

## 2026-07-22 — v3 模板复查触发的 v4 补充修订

- v3 正式模板及 precheck 已成功重建：600 条中从 v2 的 8 high-risk 降到 1 high-risk；该唯一 high 是 PubMed 的 `Supplementary Figure` 被错误标为 PERSON。needs-review 中的 `Program At` 也是明显以介词结尾的截断 PROJECT_NAME。
- 决策：在任何人工分发前补充两个类别级本地门禁：PERSON 拒绝 `supplementary/figure` 章节图表短语，PROJECT_NAME 拒绝 `at` 连接词尾。合法公司后缀 ORG、PDB/gene/case ID 和完整长声明不受影响。
- v4 focused tests 22/22 通过；对当前 600 条只读重放仅拒绝 `Supplementary Figure` 与 `Program At` 两条 PubMed 样本，未新增其他失败，说明修订边界精确。
- A/B 模板核验的首个只读命令误用了不存在的 `source_doc_id` 字段并报 `KeyError`；文件未被修改。改用真实字段 `source_key` 后，六份文件均为 200 条、每份 200 个不同 source、A/B ID 集相同顺序不同、人工标签 0。
- 本轮文本搜索尝试调用 `rg` 时遇到 Windows `Access is denied`，改用 `Get-ChildItem | Select-String` 完成同范围只读搜索；不影响代码或产物。
- v4 必须重新经过标签无关 claim/query eligibility 容量门禁；三数据集全部过 1,250 之前，正式 `data_config.yaml` 继续指向 v3，防止未验收协议提前晋升。

## 2026-07-23 — v4 终态预审暴露的表格化残片

- v4 正式重建后预审结果为 0 high-risk、15 needs-review、585 low-risk；`Supplementary Figure` 与 `Program At` 已消失，说明 v4 两项类型修复生效。
- needs-review 中仍有 2 条明显失败：`PMC7431966` 的疫苗候选/机构表被串成一个 ORG claim，以及 `PMC7433905` 的统计表列被串成 DATE claim并截断在 `Wednesday, Sept.`。二者都不是正常长句，不能留给人工门禁兜底。
- 决策：v5 增加通用但窄范围的表格化残片硬门禁，稳定失败原因为 `claim_tabular_fragment`。保留完整长句、合法公司后缀、结构化案件号/PDB/产品号；不根据数据集 ID、audit ID 或人工样本白名单写特例。
- validator 版本是 canonical manifest 的全局协议字段，因此先对三数据集做只读回放与标签无关 eligibility 重算，再决定正式晋升；不得只手工删除两条审计样本或混用 v4/v5 claims。实际 API 调用数保持为 0。
- v5 首次 focused unittest 暴露测试语料约 30 词、未达到共享 35 词阈值；疫苗表拒绝与合法长句保留均已通过。修订仅把“明确列头且至少 6 个百分比单元”分支的最低词数设为 20，多类别/多斜线分支仍为 35，避免为了测试而整体放宽规则。
- 修订后 focused unittest 为 24/24。对当前 600 个唯一 A 样本只读回放，v5 恰好拒绝 2 条：`pair_pubmed_audit_007404_011625` 与 `pair_pubmed_audit_011304_017792`，失败原因均为 true/counterfactual `claim_tabular_fragment`；Edgar、Enron 新增拒绝为 0，A/B 文件未修改。

## 2026-07-22 — v4 eligibility 通过与正式输入晋升

- v4 claim eligibility：Edgar 1,529/1,549、Enron 2,520/14,528、PubMed 3,538/3,666；claim whitelist hash 均与 v3 相同。两条新增拒绝所在 PubMed source 仍有至少 4 个其他合格 claim，因此无需错误地整篇剔除。
- v4 query eligibility：Edgar 1,517、Enron 2,465、PubMed 3,521 个 source；query whitelist hash 依次为 `77636212db5b9595b42314bd9d9ca27f13f20f29d55f18b2927797650c128cca`、`92a4afae18dfbb996ec07f2e5b57795b8e854a5ce32e32602d47e6b8a22ed17d`、`3f103261de8bcfe13918df8585659f4754849660748eac0e26040eedac6ee952`。
- fixed-budget plan hash 依次为 Edgar=`6dea9a226014b1920077d47e4825bc5eac47526e771630a0b74d14ff1d4182f9`、Enron=`98b7822f0d10209506c47f262a52f6da3e9c9c02fade50684a5649caa3436e1d`、PubMed=`6e6df8cff8be99d7c62d9f02e2a446eea383958e120aa73309497bc585cff11b`。
- eligibility 全程本地确定性运行；stealth embedding 为缓存中的 `sentence-transformers/all-MiniLM-L6-v2`，`local_files_only=true`。模型加载时的 `embeddings.position_ids` 提示不改变权重、阈值或 backend；API 调用数为 0。
- 容量门禁全部通过后才将正式 `source_eligibility_path` 从 v3 隔离目录切换到 v4；Enron processed 仍绑定已冻结的 `processed_validator_v2/enron.jsonl`。下一步必须从 Step 02 强制重建，旧 v3 下游不得通过 resume 混入。

## 2026-07-23 — v5 eligibility 通过与正式输入晋升

- v5 claim eligibility：Edgar 1,529/1,549、Enron 2,520/14,528、PubMed 3,538/3,666 个 source 至少有 4 个有效 claim pair；claim whitelist hash 依次为 `61008b0ce07a0f9209c5433b17915df7423be1e7621af8e299886c5667374014`、`d9502bf0968abf89685dadd162635b86ac9bff2f99e9f138afff9c0bc174e835`、`09bcfc3d8fb8cf81591f9e734571eafe2b845f597e8a6c5a517d1f5fd5187de0`。
- v5 query eligibility：Edgar 1,517、Enron 2,465、PubMed 3,521 个 source 均有恰好 4 个 stealth-passed pair/8 条 source 内文本与 ID 唯一 query；query whitelist hash 依次为 `77636212db5b9595b42314bd9d9ca27f13f20f29d55f18b2927797650c128cca`、`92a4afae18dfbb996ec07f2e5b57795b8e854a5ce32e32602d47e6b8a22ed17d`、`3f103261de8bcfe13918df8585659f4754849660748eac0e26040eedac6ee952`。
- v5 fixed-budget plan hash 依次为 Edgar=`72381e6faa9224fd9173acbbf1b76b7ec5df5d2832c31575408c4b6b6f88fca2`、Enron=`7744758ef6cae79dc05af03143544817cd54e6570fa4a3d3833074b42ffa68fb`、PubMed=`df824fdc683251e6b229212571ce80794e87ba4b9635b5f508a79802a7f762aa`。
- eligibility 全程在标签无关 candidate pool 上本地确定性运行；embedding 使用缓存中的 `sentence-transformers/all-MiniLM-L6-v2` 且 `local_files_only=true`。`embeddings.position_ids` 加载提示不改变权重、阈值或 backend；API 调用数为 0。
- 三数据集容量门禁全部通过后，正式配置才从 v4 晋升到 v5 eligibility 路径。Enron processed 继续绑定已冻结的 `processed_validator_v2/enron.jsonl`；下一步从 Step 02 强制重建，禁止通过 resume 混入 v4 下游。

## 2026-07-23 — artifacts 旧版本清理边界

- 清理前 `artifacts/v19` 约 24.40 GB；legacy/v2/v3/v4 eligibility 与旧 AI 预审副本合计约 17.27 GB。
- 删除目标已逐项解析为 `D:\MIA\mia_model\artifacts` 内的绝对路径并确认不是 reparse point；不使用通配符，不删除当前正式未分版本产物。
- `processed_validator_v2` 名称虽旧，但 `configs/data_config.yaml` 的当前 Enron `processed_path` 仍引用它，因此必须保留。三个 v5 eligibility 目录及 `assistant_claim_precheck_v5_formal` 同样保留。
- 历史日志总计仅约 0.3 MB，继续保留作为协议变化、失败与重跑的研究审计轨迹。
- 实际删除 18 个目标、残留目标 0；`artifacts/v19` 从约 24.40 GB 降至约 7.13 GB，释放约 17.27 GB。该删除为永久删除，未进入回收站。
- 删除后确认三个 v5 query eligibility manifest、`processed_validator_v2/enron.jsonl`、三数据集正式 claims/stealth queries、A/B 审计目录与 `assistant_claim_precheck_v5_formal` 全部存在；`configs/data_config.yaml` 成功解析且仍指向这些保留输入。

- 首次 Edgar Step 02 在读取 `configs/data_config.yaml` 时因三条晋升路径误多缩进 2 个空格而报 YAML `ScannerError`；错误发生在 split 写入前。已最小修正为 dataset 字段同级缩进，并先独立解析 YAML 后再重跑。
- v5 Step 02 已完成：Edgar、Enron、PubMed 均为 500 KB_Member / 500 True_Non_Member / 250 Reserve source；从实际 split JSONL 的 `metadata.source_key` 计算，三组两两交集均为 0。三个 manifest 分别绑定预期 query whitelist `776362…8cca`、`92a4af…d17d`、`3f1032…e952`，且 protocol/version 为 v5。
- 附加只读交叉检查先后误用了不存在的 manifest `source_ids` 和 JSONL 顶层 `source_key`，均只产生 `KeyError`、不写产物；改用真实字段 `metadata.source_key` 后三数据集全部通过。
- Edgar v5 正式下游：benchmark 78,888 rows，hash=`15384b0e95b87e136045d882cd2bb9ec1f009a6965790939adcd051382f5f831`；facts 195,479、errors=0；paired claims 185,884、validator failures=9,595、版本 `local_claim_pair_v5`；paired queries 371,768、errors=0。
- Edgar Step 09 最终 accepted=10,000 query/5,000 pair/1,250 source，`insufficient_sources={}`，plan hash=`6eb671f8610b1b395ead834c4becca58adcf4cd7feefd6bcff929c944f81e730`。独立读取最终 JSONL 验证每 source 恰好 8 query/4 pair，query ID 与文本在 source 内均唯一。
- Edgar Step 07 的长进度输出通道提前关闭，但原 Python 进程仍在运行；未启动第二个写进程，等待其自然结束后以新 manifest 时间、v5 版本与计数确认完成。
- Enron v5 正式下游：benchmark 6,777 rows，hash=`2d699bd0e670848bcb197d852c00cded9749dc5a04967acd7bf87400da0c92d1`；facts 13,980、error file=0；paired claims 12,955、validator failures=1,025、版本 `local_claim_pair_v5`；paired queries 25,910、errors=0。
- Enron Step 09 最终 accepted=10,000 query/5,000 pair/1,250 source，`insufficient_sources={}`，plan hash=`fe44b2682ec6729335acbeec33af963a43e3ddc67ca1a213bbf14110461d6ead`。独立读取最终 JSONL 验证每 source 恰好 8 query/4 pair，query ID 与文本在 source 内均唯一。
- PubMed v5 正式下游：benchmark 17,213 rows，hash=`24e0686573fcec54790ae647b0a2a2343cef93bd588b0ed7a40f567ba64fabad`；facts 31,037、errors=0；paired claims 26,746、validator failures=4,291、版本 `local_claim_pair_v5`；其中 8 个 pair 的 true/counterfactual claim 命中 `claim_tabular_fragment` 并被保留在错误产物中。paired queries 53,492、errors=0。
- PubMed Step 09 最终 accepted=10,000 query/5,000 pair/1,250 source，`insufficient_sources={}`，plan hash=`c428c37acb7347e7f13b91caee948c2122946cc220df1c794896f1b316105d31`。独立读取最终 JSONL 验证每 source 恰好 8 query/4 pair，query ID 与文本在 source 内均唯一。
- 旧 v4 预审确认的两个坏 pair ID `pair_pubmed_audit_007404_011625`、`pair_pubmed_audit_011304_017792` 均不在新 v5 正式 claims 中；这是 validator/正式重建的结果，不是手工删除审计行。

## 2026-07-23 — 取消 v6 并正式冻结 v5

- 项目负责人决定取消 v6 修复，`local_claim_pair_v5` 正式冻结。仓库中没有实现或生成过 v6；本次只新增/更新研究记录，没有修改代码、配置、数据和实验 artifact，也没有调用 API。
- 冻结前交叉核验三个数据集的 eligibility、split 和 claims manifest：均绑定 `local_claim_pair_v5` 与 `pre_split_local_query_eligibility_v5_unique_query_text`。Edgar/Enron/PubMed 最终均为 1,250 source、5,000 pair、10,000 accepted query，`insufficient_sources={}`。
- 两条新发现的 PubMed 表格残片分别是 `pair_pubmed_audit_011293_017759`（PMC7433905）和 `pair_pubmed_audit_012330_019389`（PMC7433221），均为 True_Non_Member。它们的 Q+/Q− 共 4 条查询全部因 `low_naturalness` 被拒绝，分数分别为 0.18、0.288，未进入主 accepted queries。
- 两个受影响 source 均由其他候选补足 4 pair/8 条 source 内文本唯一查询，入选自然度均为 0.9，所以主实验影响为 0。二者仅占无 stealth filter 控制的 2/26,746 pair（0.007478%），占 PubMed 人工审计 2/200（1%）、总审计 2/600（0.33%）。
- 决策：原样保留两条审计残差，不手工删除、不修改 A/B、不创建 v6。仅当真实双盲出现系统性失败并跌破 90%/0.80 门槛、相同缺陷进入主 accepted queries，或发现协议级隔离/预算错误时，才允许先记录理由再解冻。
- 当前 2026-07-22 Enron dense index 是旧 split 构建结果，不能冒充 v5 canonical index；当前 artifact 中也未找到 v5 pilot。二者与完整离线验收仍是冻结后的本地待办，不影响 v5 协议冻结。
- 已创建 `研究记录/v5正式冻结清单.md`，登记 frozen protocol、代码/配置/正式产物 SHA256、A/B manifest hash、残差和解冻条件。
- 只读检查错误：一次 PowerShell 引号解析失败；一次按错误顶层键读取 manifest 得到 `None`；一次误取不存在的 benchmark hash 键触发 `KeyError`；一次误输出超大的 split 逐 source 哈希列表；一次误用 accepted query 的 `query_text` 字段触发 `KeyError`。这些检查均未写文件，随后按真实 schema/字段完成核验。

## 2026-07-23 — v5 Enron index、pilot 与本地技术门禁完成

- 重建前核验发现旧 index 的 KB hash=`3c13854a676427fe94a5f027ef7130be58e8b5ee1ed5cf0090a5869d7f7af2bc`，与当前 v5 Enron KB hash=`4361efa3fc74ba5b32326e7078f7fdd8ad0dd4f4e0b6b5fd67259ce5e5b42577` 不一致，因此使用 Step 03 `--force --no-resume` 精确重建，未复用旧索引。
- 新 dense index 共 2,842 个 KB_Member 文档/向量，doc ID 与 v5 KB split 精确一致，True_Non_Member/Reserve 交集为 0；模型为 `sentence-transformers/all-MiniLM-L6-v2`。环境无 FAISS，按项目既有实现使用 `json_vector_fallback` 并写入 manifest；docstore hash=`256841a5e8aeaf59732a559d61ca948cb95d90af7853ffedcd4adc3aee465b75`，index hash=`b501b6f4bd56111ecef5f0cbf80665c66bf3c223880746fa4d150bcc87163472`。
- v5 pilot 已覆盖旧版本：10 KB_Member、10 True_Non_Member、5 Reserve，共 25 source/200 query；每 source 4 pair/8 query，ID 与文本全局唯一。预算为 200 RAG + 200 matched LLM-only=400，hard output-token cap=204,800，实际 API 调用=0；input hash=`edef550adeaedc4cfdcb9f1109ac830cc4ef046c09a1369cc5d491dda1d797b7`，output hash=`7a090d809c641b3bd29a13416152827ec6e8ad904b47f59e3d4a90582f7125bb`。
- 官方 verifier 首次运行因 Edgar annotator A 文件 hash drift 停止。只读诊断发现该文件在 2026-07-23 10:27 已有 5 条 `pass`，其他五份仍为空；把人工字段清空后，六份文件均与冻结 manifest 原始哈希一致，说明没有样本或机器字段篡改。
- 验收工具的旧逻辑要求填写后的整文件哈希仍等于空白模板哈希，真实标注必然误报。最小修复为只在内存清空 `human_pair_valid`、`human_failure_reason`、`audit_notes` 后验证冻结模板哈希，同时校验标签只能为 manifest 声明的 `pass/fail`；不修改 A/B、manifest 或 v5 实验协议。
- verifier 回归测试首次误按 A/B 的第 1 行同时构造篡改，但盲化顺序不同导致两个不同 audit ID 被改，正确触发了更早的 A/B content drift；随后按相同 audit ID 构造测试。focused tests 5/5 通过。
- 最终 `artifacts/v19/audits/offline_integrity_report.json` 为 `status=passed`、API calls=0、human gate=`pending`，hash=`e71ce95ba8d16fa33497244db95d8cf81bc6e8e2ac37877a52bd301316692dc3`。三数据集 split/query 固定预算、六份模板归一化哈希和 Enron index 隔离全部通过。
- 修改后全量 unittest 171/171、224 个 Python 文件内存编译、10 个 YAML 解析、两文件 Ruff、`git diff --check`（仅既有 LF/CRLF 提示）及 223 个代码/配置文件凭据模式扫描全部通过。
- 人工质量门禁尚未完成：当前只有 Edgar A 5/200 条有标签，不能计算双通过率或 Cohen's kappa。下一步继续两位标注者的独立填写与回收，不启动 victim API。

## 2026-07-23 — 六百条 claim pair 的 AI 辅助逐条裁决

- 用户说明没有足够精力继续真人标注，并授权 Codex 完成逐条裁决。为避免把 AI 冒充成人类标注者，六份正式 A/B 文件保持原样，结果另存于 `artifacts/v19/audits/claim_pair_ai_adjudication/`；协议名称明确为 `v19_ai_adjudication_2026-07-23`。
- 裁决覆盖 600/600 个唯一 pair：Edgar 100 pass / 100 fail（50.0%），Enron 88 / 112（44.0%），PubMed 111 / 89（55.5%）；合计 299 pass / 301 fail。
- 按首要失败原因统计：`entity_type_or_boundary_error` 165 条，`claim_fragment_or_truncation` 119 条，`abnormal_structure_or_artifact` 17 条。典型问题包括把章节标题/地名/机构片段标成 PERSON，把会计或生物学 `liability/termination` 当合同条款，把比例当 TIME、人口数当 MONEY，以及 Enron 邮件地址列表和截断正文。
- 该结果推翻了“残余问题仅有两条 PubMed 表格片段”的判断；早先 AI 预审的规则召回不足，真人文件中的全 pass 分布也没有识别这些系统性错误。当前三个数据集均远低于 90% 门槛，因此不得启动正式 victim API。
- 新增 `scripts/adjudicate_claim_pair_audit.py` 与 `tests/test_adjudicate_claim_pair_audit.py`。脚本只读 A/B，验证每数据集恰好 200 条、A/B 样本与机器字段一致、裁决 ID 全部属于冻结样本且无重复，并输出逐条标签、失败原因、人工标签快照、来源哈希和汇总。
- focused unittest 为 3/3；官方离线 verifier 为 `status=passed`，六份 A/B 归一化模板哈希和当前文件 SHA256 均未漂移，API 调用为 0。
- 验证错误记录：首次使用模块路径运行新测试时因 `tests` 不是 Python package 而报 `ModuleNotFoundError`，随后改用仓库约定的 `unittest discover` 并通过；一次 `py_compile` 因 `scripts/__pycache__` 权限拒绝失败，代码随后改用内存编译验证，不涉及 artifact 写入或逻辑失败。
- 方法学边界：本轮可以作为 AI 辅助质量裁决和 validator 修复依据，但不能计算或报告两位真人 Cohen’s κ，也不能声称原“双人盲标门禁”通过。若论文采用该结果，必须如实披露 `AI-assisted adjudication` 和缺少双人真人一致性统计。

## 2026-07-23 — v5 解冻与本地 NER 决策

- 301/600 的失败规模满足 `v5正式冻结清单.md` 中系统性质量失败的解冻条件。v5 artifact
  不删除、不覆盖，但正式 API 矩阵暂停，后续协议版本定为 v6。
- 旧 600 条已用于定位错误，不能继续冒充独立验收集；v6 必须重新抽取 source/audit ID
  均不重叠的 600 条。
- 仓库原有 `EntityExtractor(ner_model=...)` 注入接口，但 Step 06 一直固定实例化
  regex-only `EntityExtractor()`，所以正式流水线从未使用 NER。
- 本机只读依赖检查：spaCy=True、transformers=True、torch=True、GLiNER=False；
  spaCy=3.8.13，本地 pipeline 为 `en_core_web_sm` 3.8.0。决定使用已存在的 spaCy 模型，
  不新增 API、在线下载或 victim/sibling 调用。
- 小规模只读探针显示：模型可把 `New Jersey`/`Rollo Bay` 判为地点，把 `Forest Service`、
  `Internal Revenue Service`、`Texas Instruments` 和完整 `Internal Control -
  Integrated Framework` 判为机构，把 `Gary Spraggins` 判为 PERSON；这正好能为当前
  regex 的 PERSON/PRODUCT/LOCATION 子 span 误判提供冲突信号。
- 模型只用于 PERSON/ORG/LOCATION 的候选佐证和冲突检测；金额、时间、编号、合同术语、
  PRODUCT/PROJECT_NAME 仍由确定性规则和上下文硬门禁负责。缺失或版本漂移时正式 v6
  流程必须失败，不允许静默退回。

## 2026-07-23 — v6 本地混合门禁实现与开发集回归

- 新增 `src/attack/local_ner.py`，正式配置冻结 spaCy 3.8.13 与本地
  `en_core_web_sm` 3.8.0；`local_files_only=true`，模型缺失或版本漂移时失败，不静默
  退回 regex-only。Step 06 与 pre-split claim eligibility 使用同一配置并把模型元数据写入
  manifest。
- extractor 升级为 `attackability_v5_local_ner_context`：PERSON 需要同 span 的本地 NER
  佐证；PERSON/ORG/LOCATION/PRODUCT 使用 exact/covering/conflict 证据；更长完整 NER
  span 可替换较短正则 span；spaCy 句界优先于会截断小数、`Inc.`、`p.m.` 的旧正则句界。
- validator 升级为 `local_claim_pair_v6_local_ner_context`：增加千分位/编号/范围边界、
  非金融数量、非时钟比例、非合同语境、项目/产品/地点子 span、邮件列表、异常引号和
  明显截断门禁；CONTRACT_TERM 改为语义子类型替换，例如 `liability→indemnity`、
  `confidentiality→non-disclosure`，不再统一改成 `renewal`。
- 真实本地模型冒烟测试：`Gary Spraggins` 保留为 PERSON；`Internal Control` 不再作为
  PERSON；`Texas` 不从 `Texas Instruments` 中截成 LOCATION；`1:10 v/v` 不作为 TIME。
- 新增通用合成测试和可复用开发诊断脚本。全量
  `python -B -m unittest discover -s tests` 为 183/183 通过；8 个相关 Python 文件内存
  编译通过。首次 `py_compile` 因 Windows `__pycache__` 权限拒绝失败，随后改用内存
  `compile()`，不是语法失败。
- 旧 600 条只作开发回归。当前 v6 组合门禁对旧 301 个 AI fail 拒绝 172（57.14%），对
  旧 299 个 AI pass 保留 283（94.65%）。低召回主要来自旧生成器留下的标题/句中残片，
  这部分将在重建时由 spaCy 句界从源头消除；不会以激进的通用拒绝牺牲正常长句。
- 回归还发现旧 AI 标签存在同型边界不一致：例如 `$1 million` 的 `$1` 被判 fail，而
  `$69 million`、`$220 billion`、`$8 billion` 的等价 span 被判 pass。为避免过拟合噪声，
  在生成 v6 eligibility/独立审计前将“旧失败拒绝召回≥95%”由硬门槛改为描述性指标；
  正式接受条件仍是新来源不重叠审计逐数据集 pass rate≥90%。

## 2026-07-23 — v6 eligibility 性能诊断与协议内采样

- 首次 Edgar v6 claim eligibility 使用逐文档 spaCy 路径；候选 benchmark 已写完，但
  facts 尚在内存中。处理约 3,198 行后确认速度不足以支撑约 9.7 万 chunk，精确终止唯一
  Python 写进程；隔离的 v6 输出目录没有可复用的部分 facts，后续统一 `--force` 重建。
- 为不改变实体、claim 或 validator 判定，先把 spaCy 改为 `Language.pipe` 批处理；
  新增“预计算 NER 输出与逐条调用结果完全一致”回归测试并通过。
- 一次 focused unittest 误用 `tests.test_*` 模块路径，因 `tests/` 不是 package 而产生
  `ModuleNotFoundError`；改用 `unittest discover -s tests -p ...` 后 6/6 通过，属于命令
  错误而非代码失败。
- 1000 条 smoke 请求实际只读到现有 Edgar pilot benchmark 的 400 条并成功完成；manifest
  记录 `processing_mode=batch_pipe` 与 batch size。实测说明单纯 batching 仍不足以消除
  长 filing 的 eligibility 成本。
- 在继续改动前冻结 v6.1：claim eligibility 对每个 source 仅取 seed=42 内容哈希排序的
  最多 4 个 chunk。该标签无关 probe 只判断“能否提供至少 4 claim”，避免长 source 因
  chunk 多而占优；正式 split 仍以完整 source 为 membership unit，入选后保留全部 chunk。
- Edgar v6.1 claim eligibility：输入 96,958 行/1,549 source，经固定 probe 后为 6,095
  行；生成 15,178 facts，1,516 source 至少有 4 个有效 claim。query/stealth 完成后
  1,339 source 恰有 4 个文本互异 pair/8 条唯一 query，超过正式所需 1,250。claim
  whitelist hash=`daccdc4e05d55c34adc71aa8595aa083e011b84aec331e37b7cbb0108fbd4b33`，
  query whitelist hash=`9fd02b7311e06416dff06a17eb0d5c0e79f7870f664d50a32629733a68c0b4fc`。
- query eligibility 增加上游完整性门禁：必须匹配 v6.1 claim protocol、当前 validator
  version 与 candidate claims SHA256，否则失败关闭。新增 3 个回归测试通过；重跑 Edgar
  后 eligible 数、whitelist hash、query hash 和 fixed-budget plan hash 均保持不变。
- Enron v6.1：30,001 个 processed chunk/14,528 source 经 seed=42、每 source 最多 4
  chunk 的 probe 后保留 23,073 行；生成 60,218 facts。首次 claim 生成因两条模板 URL
  `http://www.[company` 与 `www.your-name-goes-here.com[IMAGE` 触发 `Invalid IPv6 URL`
  而停止，facts 已完整落盘、claims 未落盘。
- 修复采用失败关闭而非手工删样本：validator 版本升级为
  `local_claim_pair_v6_local_ner_context_url_gate`，不可解析 host 判为类型不匹配；
  perturbation 异常写入稳定 `counterfactual_generation_error`。新增测试后全量
  unittest 199/199 通过。
- 为安全复用已完成 facts，增加 audit ID、source key、支撑句与行数完整性核验；仅空白
  归一化差异允许通过，真实内容漂移失败关闭。Enron 23,073 candidate 行/60,218 facts
  全部核验通过，最终 5,901 claim-eligible、5,301 query-eligible source；query whitelist
  hash=`d7a927c96922a5f99b8ed37489d7f54de1cb2baed6320008477eff09888a03e1`，
  fixed-budget plan hash=`f68c708692b30bf07427c5cb1771454a483f2274e560a60ca6418010bafe359b`。
- PATH 一度切换到 `D:\python\python.exe`（Python 3.12、无 spaCy），PubMed 在 facts 写入
  前按协议失败关闭；未静默退回 regex-only。后续显式使用冻结的
  `D:\python\anaconda\python.exe`（spaCy 3.8.13）继续，未安装或下载依赖。

## 2026-07-23 — v6.1 PubMed eligibility 完成与正式配置晋升

- PubMed 输入为 50,013 个 processed chunk/3,666 个 PMCID source；seed=42、每 source
  最多 4 chunk 的固定 probe 得到 14,280 行。使用冻结的本地 spaCy 3.8.13 /
  `en_core_web_sm` 3.8.0 批处理生成 32,316 条 facts，candidate benchmark/facts 完整性
  门禁通过。
- PubMed 最终 3,570 个 claim-eligible、3,472 个 query-eligible source，均远高于正式
  切分所需 1,250。claim whitelist hash=
  `de5d037d1a63388e62e8c7a9ac1b7f4b0e208f902ce1d900baeedfeedf582981`；
  query whitelist hash=
  `4bb39e392480c16f7b9f105025c60122c7e24bed0cddd855183902de8756b2c1`；
  fixed-budget plan hash=
  `bea2d1a5b71cba14c4b0970d0ab4e80346387c5cf71f226b06ed21323fb19e6e`。
- query eligibility 共生成 31,778 个候选 pair/63,556 条查询；本地
  `sentence-transformers/all-MiniLM-L6-v2` 完成 stealth 门禁，最终每个合格 source
  恰有 4 pair/8 条文本唯一查询。全程 API 调用为 0。
- Edgar、Enron、PubMed 的 v6.1 query-eligible 容量分别为 1,339、5,301、3,472；
  三者均通过后，才把 `configs/data_config.yaml` 的三条 `source_eligibility_path`
  从 v5 晋升到对应 v6 目录。除 eligibility 路径外，不改变 membership unit、
  500/500/250 source 数、seed、Retriever、Generator 或 stealth 阈值。
- 下一接受条件：三数据集 Step 02 都必须得到 500 KB_Member、500 True_Non_Member、
  250 Reserve source，三组 source 两两不交叠，且 split manifest 绑定当前 v6.1 protocol、
  validator version 与 query whitelist hash；不满足即停止 Step 05–09。
- Step 02 已按 Edgar → Enron → PubMed 顺序强制重建并独立读取 JSONL 核验。三者均为
  500 KB_Member、500 True_Non_Member、250 Reserve，三组 source 两两交集为 0；
  split manifest 分别绑定 query whitelist `9fd02b…4fc`、`d7a927…03e1`、
  `4bb39e…b2c1`，protocol 均为
  `pre_split_local_query_eligibility_v6_1_local_ner_context_source_probe4_unique_query_text`，
  validator 均为 `local_claim_pair_v6_local_ner_context_url_gate`。
- Edgar 首次 Step 02 在写 split 前因旧 `datasets/logs/preprocess.log` 的文件权限失败；
  改用各数据集独立的 `artifacts/v19/logs/split_v6_<dataset>.log` 后成功。该问题只影响
  日志初始化，没有产生半成品 split，也没有改变配置或协议。

## 2026-07-23 — v6.1 fixed pair plan 正式晋升规则（实施前冻结）

- v6.1 query eligibility 已在分组前、标签无关地为每个合格 source 冻结 4 pair/8 条
  文本唯一查询及 `fixed_budget_plan_hash`。正式 split 又只从该 whitelist 选择 source；
  因此正式攻击查询应晋升这组已冻结 pair，而不应在完整 filing/email/article 上重新抽取
  后二次选择另一组 pair。
- 该决策不截断 membership unit：Step 02 和 Step 05 仍保留入选 source 的全部 chunk，
  RAG index 仍只索引完整 KB_Member。probe cap 只决定攻击查询，不能决定索引内容。
- 晋升必须以 `source_key + doc_id` 将 eligibility candidate 映射到正式 benchmark，
  用正式 `group/audit_id` 替换 `Eligibility_Candidate` 标签，同时保留原始
  `fact_id/pair_id/query_id`，使 frozen plan 可追溯。
- 正式每数据集必须恰好 1,250 source/5,000 pair/10,000 query；每 source 恰好
  4 pair/8 query，Q+/Q− 成对、query ID 与文本唯一。任一 benchmark source 缺少冻结计划、
  candidate hash/validator/protocol 漂移、doc ID 非唯一或分组映射失败，都必须失败关闭。
- Edgar 映射前只读探针：正式 benchmark 1,250 source 对应 eligibility accepted
  10,000 query/5,000 pair；probe doc ID 缺失=0、正式 benchmark doc ID 重复=0。
- 实现采用单独的确定性晋升脚本，写入标准 facts/paired_claims/paired_queries/
  stealth_filtered_queries 路径和 provenance manifest。它取代本轮 Step 06–09 的重复 NER
  计算，但不改变 Step 06–09 的通用入口；API 调用仍为 0。
- 新增 `scripts/promote_eligibility_plan.py` 与
  `tests/test_promote_eligibility_plan.py`。focused unittest 3/3、全量 unittest
  202/202 通过后才覆盖正式中间产物。首次 focused test 因测试夹具只有 KB_Member、
  期望统计却保留两个零计数组而失败；改为只比较非零组后通过，失败发生在正式晋升前。
- Edgar v6.1 formal：benchmark=82,393 rows，hash=
  `4062626a31b951e5d3120416dfd32eb98209390f9858f8bac72292700cdcd5ae`；
  claims=5,000，hash=`ffdb2d5114a46e673d19013189d26728dbd133518c4358531750698a6135068b`；
  accepted queries=10,000，hash=
  `a9811b6b754000dad8607dcfa6fcdfc3823bd75ae1119b1b90014d571351b72a`；
  formal plan hash=`538a4cc266b51f0369ee3937872cb7920fda270198704d66744833f8771ec8d1`。
- Enron v6.1 formal：benchmark=4,086 rows，hash=
  `6f72bb956d291fff0d0a3f2931f07a406e67d5984a5c2f3ddef4f14372eb877f`；
  claims=5,000，hash=`aa86d91e965c6b6cf9e9e31db2c2701b47ac0eaad31faa240da9f0a542c28736`；
  accepted queries=10,000，hash=
  `5040bd250435c153e192c5fcea013e4cee91d913e52b36236e5e4a30791f2ac0`；
  formal plan hash=`861ed1265ec536c93919400a5e4759a7d4f039f78c7d85338430d0b675028065`。
- PubMed v6.1 formal：benchmark=17,337 rows，hash=
  `188f4e03590f1e089b1d87cc49fa6bfb032a67ced19b9758fe05ba47e2da3273`；
  claims=5,000，hash=`44be8573bd01855d81ba3fdf515ebd96bf7a9d6de7a7cf6e7a0a0ae27f68821f`；
  accepted queries=10,000，hash=
  `48db254af7e25c5b82c01ca1b19f0b0d937ff1ba40afc4018716cfbe3e7ceaae`；
  formal plan hash=`4c266322d390aab5aa13ed679f235e2daea4cae6f17aab86041b06c28c4f9ea9`。
- 三数据集独立预算核验均为 1,250 source/5,000 pair/10,000 query，
  KB_Member/True_Non_Member/Reserve 查询数均为 4,000/4,000/2,000；
  每 source 恰好 4 pair/8 条文本唯一 query，`bad_budget=0`。

## 2026-07-23 — v6.1 独立审计失败与 v6.2 解冻理由

- 新审计目录为 `artifacts/v19/audits/claim_pair_audit_v6_formal`。Edgar、Enron、
  PubMed 各生成 200 个独立 source 的 A/B 模板；A/B 样本集合相同、顺序不同，
  与 v5 旧审计的 source_key 和 audit_id 重叠均为 0，人工字段全部为空。
- 为防止随机种子碰巧复用旧样本，`claim_pair_audit.py` 新增
  `--exclude-audit-dir`，同时排除旧 source_key 和 audit_id，并把旧 A/B 路径与实际
  SHA256 写入新 manifest。focused unittest 7/7 通过。
- 规则预审只报告 10 needs-review / 590 low-risk，但回连 formal facts 的本地 NER/context
  元数据并复核语义敏感类型后，发现大量预审漏报：Edgar 有
  `Black Scholes→LOCATION`、`Related Transactions/Delaware Law→PERSON`；
  Enron 有 `Dynegy/Cause→LOCATION`、编码残片 `01=07??MasterCard→ORG`；
  PubMed 有 `HMGB1/NEAT1/T0→LOCATION`、`w/w/IGF-1/PDMS→ORG` 和多个章节标题被当
  PERSON。另有 `New Castle,`、`North Thailand /` 的实体尾部边界错误及长邮件列表。
- 这些是类型/边界/声明结构的系统性失败，不允许靠手工删除或把 590 条 low-risk 自动
  记为 pass。v6.1 第二轮 600 条自此只作开发诊断集，不计算 Cohen's kappa、不宣称通过。
- 协议升级为 v6.2：claim 生成必须读取 fact 的 `entity_metadata` 和原始支持句上下文；
  PERSON 需要人名语境而非只信通用 NER，ORG/LOCATION 增加领域冲突与边界门禁，
  CONTRACT_TERM 对所有术语要求严格合同语境，邮件多段/编码/列表结构失败关闭。
  所有失败继续写稳定 `validation_failure_reason`，仍为纯本地、API=0。
- v6.2 允许复用已经完整性校验通过的 candidate facts，但必须重新生成 claims、queries、
  stealth whitelist 和 formal fixed plan；新独立审计必须同时排除 v5 与 v6.1 两轮 source。

## 2026-07-23 — v6.2 probe cap=5 协议修订（实施前冻结）

- v6.2 元数据语义门禁细化后，Edgar 在原 cap=4 候选探测中得到 1,468 个
  claim-eligible source；query builder 和 all-MiniLM-L6-v2 stealth 门禁完成 pair 级
  共进退后，仅 1,247 个 source 保留完整 4 pair，距正式 1,250 source 门槛差 3。
- 不降低正式数据规模、不放宽 stealth 阈值、不手工替换 source。候选资格探测统一改为
  seed=42 内容哈希排序后每 source 最多 5 个 chunk，并将协议名中的 `source_probe4`
  升级为 `source_probe5`。Edgar、Enron、PubMed 均按相同 cap 重算，避免数据集特例。
- probe cap 只扩大无标签候选搜索空间；正式 membership unit 仍是完整 filing、完整邮件和
  PMCID 论文，入选 source 的完整 chunk 仍进入 benchmark，RAG index 仍只允许 KB_Member。
  攻击预算不变：每个正式 source 固定选择 4 pair/8 条文本唯一查询。
- 命令错误记录：首次启动 Edgar query eligibility 时误传脚本不支持的
  `--selection-seed 42`，参数解析阶段即退出且未改写产物；移除该参数后重跑。
- 性能诊断：曾只读比较完整 spaCy pipeline 与仅启用 `tok2vec+ner` 的输出。20 条 smoke
  样本一致，但扩大到 200 条 Enron 文本后有 5 条实体结果不同，因此否决该加速方案；
  正式 v6.2 继续使用冻结的完整 pipeline，不以速度换取实体边界/类型漂移。
- Edgar probe5 已完成：7,588 个候选 chunk、18,828 条 fact，得到 1,506 个
  claim-eligible 和 1,390 个 query-eligible source；query whitelist hash=
  `4616ae500e197dc95a0179cecbc4009845c92bb855967c32d86cf72521df34f9`，
  fixed-budget plan hash=
  `a398b1741224f12761b436c13988f59c7c57583afda2d880290bf816b1c718e0`。
- Enron probe5 已完成：30,001 个 processed chunk/14,528 个完整邮件 source 经候选
  探测保留 24,050 个 chunk，生成 56,672 条 fact；4,786 个 claim-eligible、4,427 个
  query-eligible source。query whitelist hash=
  `ed69d30d118da2bf2697ced957de0d6b8529d0c6467a79ac6d77fb156c83d9af`，
  fixed-budget plan hash=
  `32356386ae69aacc12713e46fb462112f4903c5ad948f3b6fa5ec3de8deecd4f`。
- PubMed probe5 已完成：50,013 个 processed chunk/3,666 个 PMCID source 经候选
  探测保留 17,627 个 chunk，生成 39,875 条 fact；3,473 个 claim-eligible、3,394 个
  query-eligible source。query whitelist hash=
  `43e9910fa6826284905c918d5fe07ff1682fcc033a0390d329025e72d02f1723`，
  fixed-budget plan hash=
  `a3e222ca0d9418e23899d508f421d06a4f1fc9a5842571c0798826497837b106`。
- 三数据集 v6.2 eligibility 均超过 1,250 source 正式门槛后，才允许把配置中的
  `source_eligibility_path` 从 v6.1 切换到 v6.2；membership unit、500/500/250、
  seed=42、Retriever、Generator 和 stealth 阈值均不变。
- 审计预检新增 `semantic_entity_type_requires_manual_review`：PERSON、ORG、
  LOCATION、CONTRACT_TERM、PRODUCT、PROJECT_NAME 不再进入自动低风险队列。
  该改动只影响审计排序，不参与 validator 硬门禁，也不改变正式样本。
- 验证记录：审计预检定向测试 9/9 通过；完整
  `D:\python\anaconda\python.exe -B -m unittest discover -s tests`
  为 208/208 通过。一次误用 `tests.test_precheck_claim_pair_audit` 模块路径因
  `tests/` 不是 package 而失败，改用 `unittest discover -p` 后通过，不是代码回归。

## 2026-07-23 — v6.2 正式晋升与索引失效检查

- Edgar formal：benchmark=81,854 rows，benchmark hash=
  `5f0a4dff3c106b8a59082f663bba62fa3891d4b66ae7105e24e7b4b7b03fc9f8`；
  claims=5,000、queries=10,000，formal fixed-budget plan hash=
  `da7be58501d8489fa73a1ab32f3cf0c888a5327c6e6a37027281946539ed04d1`。
- Enron formal：benchmark=4,204 rows，benchmark hash=
  `5c3e0db64b643eb810b4460f31320c4c48fbd7c5dfca4597a578a73d5a4a5f4c`；
  claims=5,000、queries=10,000，formal fixed-budget plan hash=
  `def1188c7e181cce7084d5f30ec9504e281f97d1b3c66c4d797ad0a9bce5a608`。
- PubMed formal：benchmark=17,163 rows，benchmark hash=
  `67f70109107b66c709dca8d86e7bad6e1f5cd1a85aac9e8fa6b115467daf0647`；
  claims=5,000、queries=10,000，formal fixed-budget plan hash=
  `4249e6e6a04a7273373f112f65d03504a2a15c756d3a856369f52a60feaf7707`。
- 三个晋升器均报告 1,250 source/5,000 pair/10,000 query，固定预算、Q+/Q− 成对、
  query ID/文本唯一性与分组映射门禁全部通过。
- 首次运行 `verify_v19_offline_artifacts.py` 在 Enron dense index 检查处失败：
  `enron dense docstore does not exactly match the KB split`。原因是 v6.2 正式 split
  已变化而旧 v6.1 index 尚未重建；这是预期的 stale artifact 检出，不是 claims/query
  回归。按逐 Retriever 原则只允许重建 Enron dense，不启动其他 Retriever 或 API。

## 2026-07-23 — v6.2 第三轮审计失败与 v6.3 冻结理由

- 第三轮审计目录为 `claim_pair_audit_v6_2_formal`，Edgar/Enron/PubMed 各 200 个
  独立 source；每个 manifest 同时排除 v5 与 v6.1 两轮各 200 个 source。A/B 各
  200 行、ID 集相同、顺序不同、标签为空，结构门禁通过。
- 加强后的预检得到 196 条语义敏感重点项和 404 条结构化低风险项。逐条查看重点项并
  批量检查全部结构化实体后，确认 v6.2 仍有系统性失败，不能把 0 个规则 high-risk
  误解为审计通过。
- 明确失败包括：金额 span 吞入尾逗号（`$63,000,`、`$2,000,`、`$200,`）；
  quoted-printable 软换行把 `http://www.otcjournal.=\ncom` 截成伪 URL；
  `+44-20-7783-7520` 的中段被当作日期；关节活动度 `90/0/90` 被当作日期；
  动词短语 `contract COVID-19` 被当作编号；以及通用 spaCy NER 对公司、标题、
  生物分子、算法、地名和人物的多类语义误型。
- 容量只读评估：排除 PERSON、ORG、LOCATION、PRODUCT、PROJECT_NAME、
  CONTRACT_TERM 后，probe cap=5 的现有 candidate claims 中仍分别有 Edgar 1,415、
  Enron 2,258、PubMed 3,128 个 source 至少含 4 条结构化 claim。该容量足以维持
  500/500/250 source 与固定 4 pair/8 query，不需要降低规模或 stealth 阈值。
- 因此在实施前冻结 v6.3：canonical allowlist 仅包含 MONEY、DATE、PERCENT、EMAIL、
  MEDICAL_VALUE、TIME、DURATION、URL、PHONE、SECTION_ID、IDENTIFIER、
  NUMERIC_VALUE。语义实体继续保留在 facts/错误诊断中，但不进入 canonical 主实验；
  后续可在具备更强、冻结的本地语义模型时作为扩展重新评估。
- v6.3 同时新增确定性硬门禁：结构化实体不得吞入尾标点；日期必须通过月/日范围与
  文本年份形状检查；URL hostname 必须合法；claim 不得含 quoted-printable 软换行；
  疾病名不得由 `contract` 动词误作编号；从单数 1 改成复数数值时必须保持单位一致；
  有界百分比不得从不超过 100% 扰动到超过 100%。所有拒绝继续写入
  `validation_failure_reason`。
- v6.2 第三轮 600 条只作为开发诊断，不计算/宣称 Cohen’s κ。v6.3 必须排除前三轮
  source 后重新生成独立审计集。

## 2026-07-24 — v6.3 改为保留全类型的开放语义共识

- 用户明确要求 PERSON、ORG、LOCATION、PRODUCT、PROJECT_NAME、CONTRACT_TERM
  继续保留，因此取消仅允许结构化实体进入 canonical 的 v6.3 草案。
- 本机只读环境核验：Python 3.12.9、PyTorch 2.11.0+cu128、CUDA 可用，GPU 为
  NVIDIA GeForce RTX 4060 Laptop GPU（8,188 MiB）；spaCy 3.8.13，仅安装
  `en_core_web_sm` 3.8.0；尚未安装 GLiNER2、`en_core_web_trf` 或 GLiNER-BioMed。
- 新协议使用 GLiNER2 开放类型抽取与标记 span 二次分类，transformer NER 提供常规
  命名实体第二票，PubMed biomedical 模型提供蛋白/细胞系/方法等竞争类型否决。
- 目标不是最大召回，而是 precision-first：历史开发集总体 exact span/type precision
  至少 97%、每个语义类型至少 95%、全部已知系统性坏例误接受数为 0；阈值冻结后才可
  生成 v6.3 release 审计。
- 模型权重允许一次性下载，但正式产物必须绑定 exact revision、文件 SHA-256、schema
  hash 和阈值 hash，并在 local-only 模式运行。模型或 hash 不可用时停止，不允许用
  旧 `en_core_web_sm` 兜底生成 canonical。
- 审计仍只写作 AI-assisted review；A/B 人工字段保持空白，不能冒充两位真人盲标或
  报告真人 Cohen’s κ。victim/sibling API 调用保持 0。

## v6.3 本地模型与校准实测（2026-07-24）

- 已安装并验证 `gliner2==1.3.2`、`gliner==0.2.27`、
  `en_core_web_trf==3.8.0`；模型权重保存在忽略提交的 `models/v6_3/`，正式锁文件
  保存 exact revision、包版本和逐文件 SHA-256。
- GLiNER2 base revision=`f5b2ecedebe4381b088c1cf276f5bf72a52cac54`，large
  revision=`b122b11eeaee4dabd32bed80412f3234c0d0e943`，BioMed revision=
  `f79771210ab2111a2081ef31620fdb7342f602e9`。
- hash/load smoke test 已验证普通 ORG 能被三票接受，PubMed 中 HEK 被
  CELL_LINE/BIOMEDICAL 竞争类型和 BioMed veto 拒绝；没有网络 fallback。
- 校准读取 193 条历史语义开发样本与 13 条 PRODUCT 补充开发样本；claim 截断等非语义
  失败不计入语义 precision。历史坏边界若被 v6.3 精确扩展为完整实体，计作 repaired，
  仍保留原始坏例标签和可追溯记录。
- 冻结开发阈值后统计：rows=206、positives=90、negatives=116、true_accepts=53、
  false_accepts=0、repaired_bad_boundaries=6、precision=1.0、recall=0.5889。
  各类型 precision 均为 1.0；PRODUCT recall=1/17，是否足够只由后续 cap probe 决定，
  不以放宽 precision 门槛解决。
- 校准产物位于 `artifacts/v6_3/semantic_calibration/`，属于开发证据，不得混入新的
  RC/release source 或被描述为独立人工盲标。
- 2026-07-24 Edgar Step 01 首次运行被用户主动暂停，终止时约处理 1,365/1,600 个
  filing；无有效 manifest，因此不是实验产物。后续以 `--force` 完整覆盖重建。
- Step 01 最终 hash：Edgar processed=`ef87d9e7794a8932628d1d8704979d178fedf41777054ba0ec9b64b6bfd4e09c`；
  Enron=`1a856f278525b514cd314bc554c761e5e543288fd7ca26a8d1e475f5edcaa91b`；
  PubMed=`fd229f632fc0a0d7e63d830c896541d00a2f566dbe73ee94e3275782ee09e23b`。
  PubMed 从 raw PMCID 重建并在 50,000 软 chunk 上限后写完当前论文，共 50,011 chunks，
  membership unit=`pmcid_article`。
- 逐条 CPU smoke test 为 16.826 秒/4 chunks；批处理与设备评估显示 CUDA FP16
  batch=8 为 3.459 秒/8 chunks、峰值约 2.9 GiB。FP32 batch=16 用时 119.137 秒且
  峰值约 10.9 GiB，明确淘汰；FP16 batch=16 也慢于 batch=8。
- PubMed BioMed veto 放在 CUDA FP16 时 8 chunks 总用时 9.538 秒、峰值约 4.5 GiB，
  在 8 GiB 显存内稳定；最终运行身份已写入 resolver metadata 和 config hash。
- 最终运行身份下历史校准结果仍为 rows=206、true_accepts=53、false_accepts=0、
  repaired_bad_boundaries=6、总体/每类 precision=1.0，故运行优化没有改变冻结判定。
- eligibility 前性能复核发现：fact 阶段已经批处理，但 claim 阶段对每个反事实仍会
  逐条重复运行三模型（PubMed 为四模型），会造成不必要的长时间运行。已在不改阈值、
  schema、模型或判定逻辑的前提下，将反事实文本按 batch=8 推理并复用预测完成逐条
  `resolve_candidate`；spaCy `pipe` 同时改为流式消费，避免保留整批 transformer Doc。
- 针对性回归结果：semantic resolver 14/14、claim validator 39/39 通过；新增测试确认
  预计算反事实预测不会触发第二次模型调用，完整 source 中出现的反事实仍在模型推理前
  被拒绝。首次用 `tests.test_*` 运行失败是因为 `tests/` 不是 Python package，未执行
  任何测试也未改写 artifact；随后按仓库约定改用 `unittest discover -p`。
- 依赖清单合并：用户要求将 `requirements-semantic-v6_3.txt` 并入主清单后删除。
  主 `requirements.txt` 现可一次安装 v6.3 的两个本地语义运行库与精确
  `en_core_web_trf` 3.8.0 wheel。第一次补丁因 PowerShell 显示的中文注释乱码而
  上下文不匹配，未产生任何修改；改用 ASCII 锚点后成功，随后用
  `packaging.Requirement` 验证 11 条依赖，旧文件确认不存在。
- Edgar cap=5 实测：完整 fact 阶段处理 7,588 个候选 chunk，产生 17,835 facts；
  反事实语义复检共 53 个窗口，随后生成 12,664 个候选 pair/25,328 条查询。
  claim eligibility 为 1,391/1,549，query/stealth eligibility 为 1,294/1,549，
  每个合格 source 均为 4 pair/8 条文本唯一 query，最小 cap=5 通过。全过程
  victim/sibling API=0、Retriever 未运行；stealth 仅使用本地
  `sentence-transformers/all-MiniLM-L6-v2`。

## 2026-07-25 — 账号切换与 v6.3 性能方向修订

- 用户质疑每个 chunk 依次运行 GLiNER2 base、GLiNER2 large 和 CPU
  `en_core_web_trf` 的必要性，并明确目标是可靠抽取实体和获得 1,250 个正式 source，
  不是为三票共识承担全语料重复推理成本。该质疑成立：三模型共识适合校准/审计，
  不适合无条件放在正式 bulk path。
- 决定在任何新正式产物生成前，把开发协议修订为
  `local_claim_pair_v6_3_precision_cascade`：结构化实体继续用确定性规则；六类语义
  实体的 bulk extraction 只运行锁定的 GLiNER2 large；GLiNER2 base 和
  `en_core_web_trf` 只作开发审计/消融；PubMed BioMed 只检查已经产生的候选句。
- counterfactual 仍必须通过单槽、类型、格式、原 source 不出现和本地 claim/query
  完整性门禁；语义二次复检只运行 supporting sentence/window，不扫描整篇 source。
- 旧共识阈值 0.55/0.05/2 votes/2 boundary votes 不能直接迁移。新账号必须先在相同
  206 条开发/历史坏例上重新校准 GLiNER2 large，继续执行总体 precision ≥97%、
  每类 ≥95%、已知坏例误接受=0 的 fail-closed 门禁。
- eligibility 改为 label-independent 的确定性分波扫描：在任何组标签、审计结论或
  victim 输出前，以 seed=42 和 source identity 冻结顺序；每个 wave 完整运行到
  query/stealth；预注册在 1,300 个 query-eligible source 后停止，并把扫描前缀、
  顺序 hash、停止原因和全部运行身份写入 manifest。
- 旧 Edgar cap=5 三模型运行虽然得到 1,294 个 query-eligible source，但从本次修订起
  只标记为 `development_only_superseded`，不能晋升或与新协议混用；三个 Step 01
  processed 因不依赖 semantic resolver，仍可复用。
- Enron 旧命令在约 6,922 docs/2:09:44 后被停止。账号切换前再次核验：GPU 0%/0 MiB、
  没有 Python 进程，`artifacts/v6_3/eligibility/cap_5/enron/` 仅有约 38.8 MB、
  24,051 行的 candidate benchmark，没有 facts、claims 或完成 manifest。它不是可恢复
  的正式结果，不得续跑或晋升。PubMed 旧三模型 eligibility 未启动。
- 新建 `研究记录/v6_3账号切换交接.md` 作为新账号的单一事实来源，内含可直接复制的
  首条接管指令、协议边界、有效/失效产物、执行顺序、Git 安全要求和只读核验命令。
- 当前分支 `codex/pcv-v19-protocol`；工作树同时包含 staged、unstaged 和 untracked
  修改，stash 为空。账号切换不得 reset/checkout/clean，也不得未经审阅混合提交。
  victim/sibling API=0，Retriever 未运行，v6.3 尚未 canonical freeze。

## 2026-07-26 — precision-first wave scan v2 实施记录

- 接管核验发现另一个账号留下的
  `scripts/build_v6_3_precision_cascade_eligibility.py` 已有 1,662 行调度代码，但
  `configs/data_v6_3.yaml` 缺少其强制要求的 `eligibility_scan` 段，也没有任何对应
  单元测试，因此当时无法安全启动。
- v2 在 source 排序前复用正式 splitter 的完整 source 去重，目标从旧 v1 的
  1,300 改为 1,250，并保持完整 wave 后才停止。理由是旧 50-source buffer 只是启发式，
  不能替代同一套去重规则；提前去重后 1,250 个 eligible source 可直接保证正式容量。
- 正式 cap 策略预注册为 5→8→12。每个 cap 使用独立目录；容量不足时不得放宽按类
  precision 阈值、删除实体类型或手工换 source。
- 调度逻辑已移入可测试模块；CLI 默认只冻结计划，执行仍必须显式
  `--resume --execute`，并可用 `--max-new-waves` 在完整 wave 后暂停。
- semantic runtime 改为进程内复用并校验 protocol/schema/threshold/model-role；
  PubMed runtime 必须恰好包含 large+BioMed，其他数据集必须恰好只含 large。
- claim source lookup 新增 wave allowlist：仍扫描完整 processed 以检查反事实是否在
  原 source 任一 chunk 出现，但内存只聚合当前 wave source，缺失 source 时 fail closed。
- checkpoint 现验证从第一个到最新的完整 hash 链；finalization 先写独立 staging，
  再逐文件原子晋升，已有同 hash 文件可恢复复用、不同 hash 立即拒绝。
- 新测试首轮出现 2 个错误：测试构造的 whitelist hash 和 mock wave 使用自然数字顺序，
  而正式协议使用字典序。实现没有修改，测试夹具按冻结排序修正后 11/11 通过。
- 受影响的既有回归：semantic resolver 23/23、claim validator 39/39、promotion
  3/3 均通过。当前仍未创建 scan plan、运行 Retriever 或调用 API。

## 2026-07-26 — precision-first wave scan v2 完整回归

- 完整 `unittest discover -s tests -v` 共 244 个用例，32.675 秒全部通过。
  其中新增的 11 个 source-plan、wave、checkpoint、runtime 复用、staging 和正式容量
  门禁用例均已纳入完整套件。
- 受影响的 9 个 Python 文件使用内存 `compile()` 全部通过；`data_v6_3.yaml` 与
  `pcv_attack_v6_3.yaml` 使用 `yaml.safe_load` 解析通过。
- `git diff --check` 退出码为 0；输出仅为工作树既有文件的 LF/CRLF 转换提示，
  没有 trailing whitespace 或 patch 格式错误。
- 本阶段没有加载 GLiNER/BioMed/MiniLM，没有运行 Retriever，也没有调用
  victim/sibling API。下一步只冻结三数据集 cap=5 scan plan，先核验冻结后的 source
  universe、顺序和输入 hash，再允许 Edgar 单 wave pilot。

## 2026-07-26 — 三数据集 cap=5 scan plan 冻结

- 三份计划均由相同的 `v6_3_precision_cascade_wave_scan_v2`、seed=42、wave=250、
  cap=5、fallback=[8,12] 和 threshold hash
  `d180bdb02d5bcb5748cfac64b955ecc307b37022671c0200a35a50d0394edfa8`
  生成，状态均为 `preregistered_not_executed`。
- Edgar：raw/deduplicated rows=97,051/97,051，source=1,549，probe rows=7,588，
  共 7 waves；plan hash=
  `c27f1e5f96b361f7eb29d3ed4b61d63a2da3e789ac8f30e1327b439eeee85779`。
- Enron：raw/deduplicated rows=30,000/30,000，source=14,523，probe rows=24,051，
  共 59 waves；plan hash=
  `d63fbc0e96f88d8efed9b9bbab4409f855884180ee79e0926ee1b1c13d102349`。
- PubMed：raw/deduplicated rows=50,011/50,011，source=3,666，probe rows=17,627，
  共 15 waves；plan hash=
  `b8b3d1cdb776ff867e721801c026feda7e79a8cd814c5527733b36b031e9c681`。
- 三个计划均无跨 source 或 source 内重复行被删除；重新计算的 source-order file
  与 candidate benchmark SHA-256 和 manifest 完全一致，`api_calls_performed=0`、
  `retriever_runs=0`。
- 只读核验的前两条临时命令分别误用了不存在的 `{dataset}_scan_plan.json` 文件名和
  不存在的 `sources` 键，均只触发 `FileNotFoundError`/`KeyError`，没有修改产物。
  随后按实际 `scan_plan.json` 与 `source_order` 键完成全部断言。

## 2026-07-26 — Edgar wave 0 precision-first pilot

- 只执行一个完整 250-source wave 后按 `--max-new-waves 1` 正常暂停，没有重复启动
  进程。候选 benchmark=1,226 rows，facts=3,370，claim-eligible source=228，
  最终 query-eligible source=212，pilot 通过率=84.8%。
- 最终固定预算为 848 pair/1,696 query；每个通过 source 恰好 4 pair/8 条文本唯一
  Q+/Q− query。checkpoint SHA-256=
  `2cc26fa2e4994742fc8a72b39b7db010f1b6caa6cf5cd134bec617130a03cb96`。
- `load_latest_checkpoint` 验证完整 checkpoint 链，`validate_completed_wave` 重新
  校验 wave manifest 及所有输出 hash；随后从正式 stealth 输出重新计算 fixed-budget
  统计并与 manifest 的关键字段一致。API=0，Retriever=0。
- fact 阶段只加载/运行 GLiNER2 large；counterfactual 语义复检共 12 个 large-only
  batch，base 与 CPU spaCy 未进入 bulk path。stealth 阶段仅加载本地
  `sentence-transformers/all-MiniLM-L6-v2`。
- pilot 后只读核验最初误把 pre-stealth `queries` 当作最终固定预算文件，正确触发
  “15 pairs 而非 4 pairs”拒绝；随后改读 `outputs.stealth`。另一次严格 Python
  dict 相等断言因 JSON 往返把分布键 `8` 从整数转成字符串而失败，关键字段与 hash
  实际一致；两次均未修改产物。后续核验改为显式字段比较并通过。

## 2026-07-26 — 用户决策：改为固定双倍候选池

- 用户指示“直接定为两倍，然后从中选”。解释并冻结为：候选池目标固定为正式
  1,250 source 的两倍，即 2,500；扫描完成后再从 query-eligible source 中按冻结
  source 顺序选择 1,250，而不是达到 1,250 时自适应停止。
- Edgar 经完整 source 去重后全集仅 1,549，无法人为补成 2,500，因此按
  `min(source_universe, 2500)` 使用全集；Enron/PubMed 各冻结前 2,500。该差异必须
  进入 plan/manifest 和论文限制说明。
- 决策到达时 v2 续跑已完成 checkpoint 0001–0003：累计扫描 750、合格 626；
  正在执行的下一 wave 已完成 fact/claim 并进行到 counterfactual replay 5/12。
  非交互式进程无法接收 Ctrl+C，先只读确认系统仅有一个
  `D:\python\anaconda\python.exe`（PID 246788），随后只停止该精确 PID。
- 停止后无 Python/PythonW 进程；v2 仍只有三个完整 checkpoint，未完成 wave 没有
  checkpoint。前三个 checkpoint 与其 wave outputs 保留为 superseded 开发证据，
  新 v3 不复用、不晋升。
- 只读定位命令 `Get-CimInstance Win32_Process` 因 WMI 权限不足失败，未改变系统或
  artifact；随后使用 `Get-Process` 确认唯一 Python PID 后完成精确停止。

## 2026-07-26 — 固定双倍候选池 v3 实现与回归

- 新协议为 `v6_3_precision_cascade_fixed_double_pool_v3`；配置冻结
  `candidate_pool_multiplier=2`、`candidate_pool_target_sources=2500`、
  `candidate_pool_shortfall_policy=use_complete_source_universe` 和
  `scan_full_candidate_pool=true`。输出目录独立为
  `artifacts/v6_3/eligibility/precision_cascade_fixed_double_pool/`。
- source universe 仍先复用正式 splitter 完整去重，再按 seed=42 冻结顺序取
  `min(universe,2500)` 前缀。plan 新增 universe/pool/shortfall 计数和完整池策略；
  候选 benchmark 只包含固定池 source。
- 调度器在 fixed-pool 模式下即使中途 eligible≥1,250 也继续，直到完整固定池耗尽；
  此后 eligible≥1,250 才写 `target_reached`，否则写 `insufficient`。每个完整 wave
  的 operational pause 与 checkpoint 恢复仍保留。
- checkpoint、claim/query eligibility 和 downstream formal gate 均绑定固定池目标、
  有效池大小与 `scan_full_candidate_pool=true`；formal gate 额外要求
  `scanned_source_count == effective_candidate_pool_source_count`。
- 新增 fixed-pool prefix/short-universe 与“不提前停止”测试。聚焦测试 13/13，
  完整 `unittest` 246/246（21.739 秒）通过；受影响文件内存编译通过，
  `git diff --check` 仅有既有 LF/CRLF 提示。没有运行模型、Retriever 或 API。

## 2026-07-26 — 固定双倍候选池 v3 plan 冻结

- Edgar：固定池/全集=1,549/1,549，shortfall=951，probe rows=7,588，7 waves；
  plan hash=`26d2cc2644a54019ff603ae883ca1fd4c6a90a174bc00ae8be33529e5e953f22`。
- Enron：固定池/全集=2,500/14,523，shortfall=0，probe rows=4,147，10 waves；
  plan hash=`fa2fdcfd2162aa8755a0b39a7b46105cabf0a795623aa9a03842c91a2466058e`。
- PubMed：固定池/全集=2,500/3,666，shortfall=0，probe rows=12,012，10 waves；
  plan hash=`3cb04c3fc91b752c6b82fb9aa73f6a02b1e7408bd8181739698a02faddbae82c`。
- 三份 candidate benchmark 的 source 集恰好等于各自固定 source-order 集；
  重新计算的 source-order/candidate SHA-256 与 plan 一致，所有计划均记录
  `scan_full_candidate_pool=true`、API=0、Retriever=0。

## 2026-07-26 — Edgar v3 执行移交

- 用户要求停止后台执行并由本人运行。停止前 Edgar v3 已完成三个完整 wave：
  checkpoint 0001=250/212、0002=500/410、0003=750/626；累计合格率 83.47%，
  三个 checkpoint 状态均为 `in_progress`，符合固定池不得提前停止的协议。
- 停止时正在 wave 3 的 fact 阶段约 345 chunks；系统仅有一个
  `D:\python\anaconda\python.exe`（PID 264044），已精确停止该 PID。复核无
  Python/PythonW 进程，checkpoint 目录仍恰好只有 0001–0003。
- 未完成 wave 目录不是 checkpoint，不得手工拼接或晋升；同一 `--resume --execute`
  命令会从完整 checkpoint 前缀恢复并为当前 wave 创建新的 attempt。
- 截至移交，Enron/PubMed v3 只冻结 plan，尚未加载模型；所有数据集 API=0、
  Retriever=0，canonical 未切换。

### Phase 7I 阶段 A 只读接管核验（2026-07-25）

- 已完整阅读 `AGENTS.md`、账号切换交接、Phase 7H/7I 与 notes 最近两个 v6.3 小节；
  未运行旧 eligibility 命令，未执行 reset、checkout、clean、删除或覆盖。
- 分支仍为 `codex/pcv-v19-protocol`，staged、unstaged 与 untracked 改动均原样保留，
  stash 仍为空；接管阶段没有创建提交。
- GPU 复核为 utilization=0%、memory=0 MiB。首次进程快照短暂观察到 Python
  PID 46924，随后在未干预、未终止的情况下自行退出；最终复核无 Python/PythonW
  进程，因此没有接续或启动任何长任务。
- `artifacts/v6_3/processed/` 三个 JSONL 的实际 SHA-256 分别为 Edgar
  `ef87d9e7794a8932628d1d8704979d178fedf41777054ba0ec9b64b6bfd4e09c`、
  Enron `1a856f278525b514cd314bc554c761e5e543288fd7ca26a8d1e475f5edcaa91b`、
  PubMed `fd229f632fc0a0d7e63d830c896541d00a2f566dbe73ee94e3275782ee09e23b`，
  与交接记录一致，可复用 Step 01。
- 旧 `artifacts/v6_3/eligibility/cap_5/enron/` 仍仅有
  `enron_candidate_benchmark.jsonl`（38,847,290 bytes），没有 facts、claims 或
  eligibility manifest；未尝试 resume。Retriever 与 victim/sibling API 仍未运行，
  canonical 配置未切换。

### Phase 7I 阶段 B precision cascade 实现与短验证（2026-07-25）

- 新开发协议已实现为 `local_claim_pair_v6_3_precision_cascade`。结构化实体仍由原有
  确定性规则处理；六类语义实体在正式 `precision_cascade` 模式只加载和运行锁定的
  GLiNER2 large。GLiNER2 base 与 `en_core_web_trf` 仅在显式 `audit_consensus`
  模式加载，旧 `local_claim_pair_v6_3_open_semantic_consensus` 仅保留为开发审计身份。
- PubMed BioMed veto 已改为延迟执行：仅当存在语义候选时，定位候选所在句/最长 512
  字符短窗口，在窗口内执行竞争类型否决并把局部 span 映射回原文；没有语义候选时不调用
  BioMed。修正了首次聚焦测试发现的窗口 offset 解包错误。
- 正式运行身份同步改为 `attackability_v6_3_precision_cascade`、
  `local_claim_pair_v6_3_precision_cascade` 和
  `pre_split_local_{claim,query}_eligibility_v6_3_precision_cascade...`，避免旧三模型
  facts/claims/query manifest 被误续跑或晋升。promotion 的输入协议检查也已同步。
- resolver metadata 记录 execution mode、primary model role、跳过的 audit-only roles、
  candidate-only BioMed 和阈值 hash；正式 loader 在阈值未冻结或 hash 漂移时 fail closed。
  semantic schema hash 有意保持
  `1e50ffc451e01f85d64e5013bf4e76de5e462c5ca6ed0e445fccdb8bd9e1ffeb`，
  以表明实体标签 schema 未改变。
- 短验证通过：内存语法编译与 `git diff --check` 通过；semantic resolver 20/20、
  claim validator 39/39、local NER 6/6、claim eligibility 6/6、query eligibility
  3/3、promotion 3/3、claim audit 7/7、precheck audit 9/9，共 93 个相邻聚焦用例通过。
  正式模式测试确认 base/spaCy 调用次数为 0，审计模式测试确认三 voter 仍可显式加载。
- 当前 `configs/pcv_attack_v6_3.yaml` 仍为 `thresholds_frozen=false` 且
  `thresholds_sha256=null`；占位阈值没有被宣称为冻结阈值。尚未运行 206 条校准、完整
  unittest 或 1,300-source 扫描，也未运行 Retriever、调用 victim/sibling API 或切换
  canonical 配置。

### Phase 7I 阶段 C 第一轮 206 条校准与全局阈值门禁（2026-07-25）

- 校准输入只读核验为 206 条：Edgar 77、Enron 51、PubMed 78；运行身份为 CUDA FP16、
  batch=8。实际 metadata 只包含 GLiNER2 large，PubMed 额外包含 candidate-window
  BioMed veto；`skipped_model_roles=(gliner2_base, spacy_transformer)`。全程
  `local_files_only=true`、API calls=0、Retriever 未运行。
- 新 raw predictions 已写入独立目录
  `artifacts/v6_3/semantic_calibration_precision_cascade/`：Edgar hash=
  `997c426b27293049e5a323165de4b8db4d1e02ba656af384d6e1a845f8cf3dc5`、
  Enron=`aafc73203e559c2f669d5e0477edb1143e90a40f6a7d1ff90fc2271df0e6bf00`、
  PubMed=`c70c0dc91ad46395ca53b8709ded8cd770baa1a184c19d07c34947b2ed567b25`。
  旧 `artifacts/v6_3/semantic_calibration/` 未被覆盖。
- 540 组单一全局 target/margin/BioMed 阈值没有通过全部门禁。最佳零坏例组合达到
  overall precision=1.0、true accepts=50、false accepts=0、recall=0.5556，但
  PRODUCT 零接受；放宽全局阈值后虽能接受 PRODUCT，却引入 PRODUCT 或 PROJECT_NAME
  坏例，故 `status=stopped_threshold_gate_failed`，没有选中阈值或 threshold hash。
- 离线按类检查确认不是模型路径失效：六类分别都存在 false accepts=0 且至少一条
  true accept 的阈值，单类 precision 均可为 1.0；冲突来自 PRODUCT 需要较低阈值而
  PROJECT_NAME 需要较高阈值。下一步把已哈希的 decision surface 扩展为按实体类型冻结
  target/margin，并只复用上述 raw predictions 重算，不重新调用模型。
- Windows PowerShell 因当前环境同时含 `Path/PATH`，两次 `Start-Process` 在创建进程前
  失败并留下四个零字节 operational log；均未删除或复用。实际 attempt3 完整处理
  206/206 后正常停止。结束复核 GPU=0%/0 MiB、无 Python 进程。配置继续保持
  `thresholds_frozen=false`，未切换 canonical。

### Phase 7I 阶段 D 按实体类型阈值校准通过（2026-07-25）

- resolver decision surface 已扩展为六类完整 `thresholds_by_entity_type`，每类分别冻结
  `min_target_confidence/min_confidence_margin`；映射被 canonicalize 后进入
  `thresholds_sha256`、resolver metadata 和 formal loader 完整性门禁。映射缺类或 hash
  漂移均 fail closed。
- 校准器新增只读 `--prediction-cache-dir`，第二轮从阶段 C 的三份已哈希 raw
  predictions 离线重算，没有加载模型、调用 API 或改写第一轮目录。新证据单独写在
  `artifacts/v6_3/semantic_calibration_precision_cascade_per_type/`，summary hash=
  `9a32fd54252c104a6277b1aa90863a572caff63a0527a0335ea1788de15a432d`，
  grid hash=`e333c2c51aabf1288423335fff6883708f09332bdc43a5d7a96df96a5eb59864`。
- 六个候选 BioMed veto 阈值的按类组合策略全部通过；在 true accepts 同为最大值时选择
  更保守的 BioMed threshold=0.90。最终全局 fallback 为 target=0.95、margin=0.40，
  六类覆盖映射为：CONTRACT_TERM=0.50/0.40、LOCATION=0.95/0.05、
  ORG=0.60/0.40、PERSON=0.55/0.40、PRODUCT=0.60/0.40、
  PROJECT_NAME=0.95/0.40；votes/boundary votes=1/1、overlap=0.80。
- 最终门禁：rows=206、positives=93、negatives=113、true accepts=68、
  false accepts=0、repaired bad boundaries=9、overall precision=1.0、
  recall=0.7312；六类 precision 均为 1.0，已知坏例误接受为 0。selected threshold
  hash=`d180bdb02d5bcb5748cfac64b955ecc307b37022671c0200a35a50d0394edfa8`。
- 新增/更新的聚焦测试确认按类阈值解决 PRODUCT/PROJECT_NAME 全局冲突、六类映射缺失
  fail closed、映射参与 hash，以及 PubMed 在预计算 large batch 后仍只对候选句运行
  BioMed；semantic resolver 23/23、校准器 synthetic 1/1 通过。此记录写入时配置仍为
  `thresholds_frozen=false`，尚未切换 canonical。

### Phase 7I 阶段 E 隔离配置冻结与 formal loader 核验（2026-07-25）

- 只修改隔离的 `configs/pcv_attack_v6_3.yaml`：写入阶段 D 六类阈值、BioMed=0.90、
  calibration summary 路径、`thresholds_frozen=true` 和
  `thresholds_sha256=d180bdb02d5bcb5748cfac64b955ecc307b37022671c0200a35a50d0394edfa8`。
  未修改 `configs/pcv_attack_config.yaml`、`configs/canonical_suite.yaml` 或模型锁。
- 直接从真实 YAML 重新计算 decision-surface hash，并与配置值及 calibration summary
  的 selected hash 三方比对一致。使用 injected backend 走完整 formal loader：
  Enron 加载角色仅 `gliner2_large`，跳过 BioMed/base/spaCy；PubMed 加载角色仅
  `gliner2_large + biomedical_veto`，跳过 base/spaCy；两者 metadata 都含完整六类映射
  和相同 threshold hash。
- 冻结后回归：semantic resolver 23/23、claim validator 39/39 通过，
  `git diff --check` 无空白错误（仅报告工作树原有 LF/CRLF 提示）。没有启动模型推理、
  Retriever、victim/sibling API 或 canonical 切换。
## 2026-07-27：v6.3 最终提速与容量恢复实施依据

- v3 Edgar cap=5：扫描完整 1,549 source，1,295 个 query-eligible，容量通过。
- v3 Enron cap=5：扫描完整 2,500 source，claim-eligible=280，query-eligible=263；stealth 只额外损失 17，瓶颈不在 stealth。
- 按 Enron 当前 10.52% 产率，随机顺序预计需约 11,882 source 才能达到 1,250，固定随机 2× 池已被数据证伪。
- 无模型只读回放使用现有 `EntityExtractor` 规则候选、cap=5 和 Enron 12/8 设置，对 14,523 source 排序；全局前 2,500 与旧随机样本相交 459 个，其中 254/263 个旧 query-eligible source 被覆盖，交集内产率 55.34%，线性估计约 1,383 个合格 source。
- v3 PubMed 已完成 9 个 checkpoint：扫描 2,250 source、query-eligible=1,856；最后 250-source wave 在 GLiNER2-large fact extraction 约 632 doc 后 CUDA OOM。旧九个 checkpoint 必须保留。
- 当前 formal loader：Enron 只加载 GLiNER2-large；PubMed 同时加载 GLiNER2-large 与 BioMed veto 到 CUDA。GLiNER 请求 batch=8，失败会令整个 wave attempt 作废；没有 microbatch OOM fallback 或原始预测缓存。
- 最终方案：Enron 使用独立 v4 排序扩展协议；PubMed/Edgar 保持 v3。GLiNER 增加只针对 CUDA OOM 的递归拆分和 hash-bound SQLite 缓存，任何 batch=1 OOM、模型错误或 identity 漂移均 fail closed。
- 本阶段不修改模型锁、阈值、`configs/data_v6_3.yaml`、Retriever 或 victim API 配置。

### 2026-07-27：Phase 7J 精确停止语义修订

- 用户将 Enron v4 的容量目标明确修订为“达到 1,250 个合格 source 即停止”，不再完整处理初始 2,500 source，也不从大于 1,250 的合格集合二次抽样。
- 2,500 仅保留为排序后的原始 2× 优先范围；若在其内达到目标，则在产生第 1,250 个 query-eligible source 的准确 source 边界结束；若不足，再沿冻结排序继续扩展。
- 为保持 GPU batching，terminal microbatch 可以计算边界后的预测，但这些预测属于临时运行数据。正式 checkpoint 与所有下游产物必须按 `retained_source_end` 截断，边界后的 source 不得作为正式处理证据。
- Enron 最终 eligibility whitelist 必须严格等于排序扫描得到的前 1,250 个 query-eligible source；任何不足、超额、边界后 source 泄漏或恢复时重新纳入被截断 source 都 fail closed。

#### 2026-07-27：terminal 计算边界的工程放宽

- 最终 diff 审查确认，现有实现会完成当前 250-source wave 后再定位第 1,250 个合格
  source，而不是只允许同一 GLiNER microbatch 的少量预取。用户明确表示该计算边界
  不必过严，因此不再增加 8-source 嵌套调度。
- 科学协议不变：正式 retained prefix、whitelist 和所有下游产物仍精确截止到第
  1,250 个合格 source；只有本地计算可能最多多处理一个 terminal wave 的尾部。
  manifest 必须同时记录 `processed_source_end` 与 `retained_source_end`，恢复和
  finalization 不得把尾部 source 重新纳入正式证据。
- 该放宽只影响少量一次性本地计算成本，不改变实体模型、阈值、source 顺序、资格
  决策或正式样本集合；因此不需要更改或重新冻结当前 Enron v4 plan hash。

### 2026-07-27：自适应批处理 206 条决策等价性门禁

- 新增并运行 `scripts/verify_v6_3_adaptive_batch_equivalence.py`，将当前自适应批处理实现与冻结的 fixed-batch=8 原始预测逐条比较。
- 总计 206 条：Edgar 77、Enron 51、PubMed 78；raw span/type/score 不一致=0，accepted/rejected、resolved span/type、failure reasons 不一致=0。
- 合并门禁保持 overall precision=1.0、true accepts=68、false accepts=0、repaired bad boundaries=9；六类 precision 均为 1.0。
- 等价性 summary 写入 `artifacts/v6_3/adaptive_batch_equivalence/equivalence_summary.json`，identity hash=`fef3562f12f3bb71ab200579786dcff51c66297aa842bd732164f8f1d6490220`；API=0、Retriever=0。
- 首次运行曾错误地对每个 dataset 单独要求六类正例齐全，Edgar 因缺 PERSON 正例而停止；raw/decision 当时已经均为 0 mismatch。修正为三数据集合并执行冻结的 206 条门禁后重新运行并通过。

### 2026-07-27：Enron v4 排序计划冻结

- 使用独立 `configs/eligibility_scan_v6_3_enron_v4.yaml` 对 Enron 全部 14,523 个
  source 完成无模型质量排序；probe rows=24,051，未读取 group label、历史 eligibility
  标签或模型响应。
- scan plan hash=`f8ed17ef292a7316fc9ef1e9bb954f2f575b255c1dc2593834dce2701ab65cdf`，
  source order hash=`ff2fdcfd8004e2ab65323e857d0cedda6bec0963ac9db35b269e02cb9479f6af`，
  quality ranking hash=`711d2cd136fc1d846ad6ee33941ce021a19d604ec580b56a2531cf864882b2c4`。
- 历史只读回放中，旧 v3 的 263 个 query-eligible source 有 254 个进入排序前
  2,500，recall=0.96577947，达到预注册的 254/96.5% 门槛。
- 本步骤 API=0、Retriever=0、GLiNER 调用=0；只冻结排序与执行身份。正式 v4 GPU
  扫描尚未启动，旧 v3 的 263-source 产物继续保留作为回放证据。

### 2026-07-27：PubMed checkpoint 9 恢复与 v3 finalization

- 第一次恢复在约 640 doc 后遇到真实 CUDA OOM；成功 microbatch 已逐批提交到
  `wave_0009.sqlite3`。清理 CUDA cache 时又出现异步 `AcceleratorError`，已修复为
  best-effort 清理，不能遮蔽原 OOM 或阻止递归拆批。
- 第二次使用同一 `--resume --execute --max-new-waves 1` 命令，从 SQLite 命中恢复
  已完成预测并完成最后一个 wave，没有重跑 checkpoint 0–8。
- PubMed 最终 scanned=2,500、claim-eligible=2,150、query-eligible=2,062；
  checkpoint count=10，checkpoint hash=
  `2e236a6d5a089f7418767969f65c1392609ec000d6652736d377b4c23b6d531c`，
  whitelist hash=`e54adc8e626f11989259d6f0e7c45c2e1501c21173118f4ef9ad53afdcd1bfeb`，
  fixed-budget hash=`b3be3c903b7486fa611046e82fd403dc9363c05adb63ce12de74fab5f38e9fc8`。
- finalization 成功后删除 wave-local prediction cache；失败 attempt 暂时保留，等
  Enron v4、promotion 和审计全部通过并冻结 v6.3 后统一清理。API=0、Retriever=0。

### 2026-07-27：最终本地代码门禁

- `python -B -m unittest discover -s tests`：257/257 通过。
- `src/`、`scripts/`、`tests/` 共 243 个 Python 文件使用内存 `compile()` 通过；
  `data_v6_3.yaml`、`pcv_attack_v6_3.yaml` 和 Enron v4 scan YAML 均成功解析。
- data config hash=
  `c69096019e7d609dab92f6b8d3af063cfc9acfec2d9f16e82968c2a3f12dca55`，
  attack config hash=
  `b2bcfdbe40869e8e8e9bafb99c8d794fd7fe0eb784260986c1805fd2fb2a8426`；
  Enron 独立 scan config 未改变两份共享配置。
- `git diff --check` 通过，仅报告工作树既有 LF/CRLF 转换提示。Edgar/PubMed v3
  正式 eligibility loader 复核通过，分别包含 1,295/2,062 个 source。

### 2026-07-27：Enron wave 5 batch=1 OOM 与恢复

- Enron v4 首次连续执行成功写出 5 个 checkpoint：scanned=1,250、
  query-eligible=1,064。第 6 个 wave 已完成 416 个 fact 输入后，GLiNER2-large
  依次尝试 8→4→2→1，最终在 batch=1 报 CUDA OOM 并按协议停止。
- 失败 source 为 `emails_00039583`，text hash=
  `e78e6833d1f0449119914e5e1f491ceef82e73f9b78ce77da83cc81d46b73385`；
  对应文本仅 630 字符/120 words，不是异常长输入。前五个 wave 的 peak CUDA
  allocated 分别约 4.36/5.39/5.26/5.50/4.86 GB，因此 batch=1 失败来自长进程的
  CUDA 资源残留/碎片，而非该文本本身超过 8 GB。
- `filter_stealth_queries` 原来每个 wave 都重新加载 all-MiniLM，但函数返回前没有
  显式关闭 SentenceTransformer runtime。现新增 `close()`：完成向量和正式输出后
  将 runtime 移回 CPU、断开引用、GC 并清空 CUDA cache；下一 wave 开始前再清理一次。
  该修改发生在向量已经生成之后，不改变 embedding、相似度、门槛或 source 决策。
- 完整 unittest 259/259 通过；资源释放聚焦测试、semantic resolver 28/28 通过。
  checkpoint chain 与 5 个 completed wave output hash 全部通过；失败 wave 的
  `wave_0005.sqlite3` 为 `quick_check=ok`，含 416 条 predictions/1 个 identity。
  同一 `--resume --execute` 命令会复用这些预测，不重算前五个 wave。

### 2026-07-27：v6.3 formal promotion、审计抽样与 RC 第一遍结论

- 三数据集 formal split 均为 500 KB_Member / 500 True_Non_Member /
  250 Reserve，组间 source 交集为 0；benchmark 分别为 Edgar 84,261、
  Enron 7,664、PubMed 17,344 rows。
- promotion 后每数据集均为 1,250 source、5,000 pair、10,000 query；逐 source
  复核恰好 4 pair/8 条 query，query ID 与文本均唯一，benchmark/facts/claims/
  stealth 文件 hash 与 manifest 一致。
- fixed-budget hash：Edgar
  `4de9665105c85d8e9d1cebc9e7c6127a50e54026390cfc653f044757406fb6ec`；
  Enron `5840430b7de1e2718ff8b45b795159016645041f06febad921af3f15eebcd283`；
  PubMed `9ed9a9c59636f015eb599b82561e548c9c89857cf18d81169a6e9208f266922b`。
- RC 使用 `sample_size=100, seed=6301`；Release 使用
  `sample_size=200, seed=6302`，并按 source_key/audit_id 排除同数据集 RC。
  六套 A/B 文件均保持标签为空，RC/Release source 与 audit ID 零重叠。
- RC/Release 实际覆盖 PERSON、ORG、LOCATION、PRODUCT；PROJECT_NAME 仅 Enron
  有限覆盖（RC=5、Release=2），CONTRACT_TERM 在正式 claims 中为 0，记录为
  unavailable，不补造样本。
- RC 本地硬门禁预审为 0 high-risk / 97 needs-review / 203 low-risk；随后逐条语义
  复核确认自动预审存在漏报。重复明显失败包括：句首/句尾截断、表格/标题/邮件元数据
  与 quoted-printable 污染、引用编号或复合名称中的数字被当作 NUMERIC_VALUE、
  比例被当 TIME、非日期等级被当 DATE、非医疗量被当 MEDICAL_VALUE，以及
  generic/biomedical/organization surface 被误作 PRODUCT/PERSON/ORG。
- 上述模式均出现至少两次，已触发“不冻结 v6.3、不裁决 Release”门禁。下一步仅修复
  可泛化的 sentence/entity context gate，不按 audit ID 打补丁；修复后从受影响阶段
  重建 eligibility/formal artifacts，并重新抽取与当前 RC/Release source 不重叠的
  新 RC。全过程 API=0、Retriever=0。

### 2026-07-28：RC1 本地回放、误伤修正与容量结论

- RC1 没有重新运行语义模型：facts 中的 original semantic resolution 和 claims 中的
  counterfactual semantic resolution 均按原 hash 复用；只重放本地 validator，
  并仅回收原来因 `fixed_budget_*` 或
  `insufficient_unique_source_pairs:*` 淘汰、且 `self_reject_reason` 为空的旧
  stealth-passed query。GLiNER/API/Retriever 调用均为 0。
- 第一版回放曾把所有句末金额和所有连字符数值都拒绝。样例复核确认
  `$136,000.` 与 `350-kilometre` 是合法完整槽位，因此收窄规则；`$14.` 式疑似
  小数截断、`COVID-19` 式标识符组件仍拒绝。修正后聚焦 validator 44/44、
  revalidation 3/3、extension 2/2 通过。
- 最终本地回放结果：
  - Edgar：accepted claims=9,135/13,056，eligible sources=952，
    whitelist hash=`0bb7a0498e17380441fe7994b541888badd881983f5f40fc6ee137d4b427a0c0`。
  - Enron retained：accepted claims=6,347/9,825，eligible sources=685，
    whitelist hash=`cfe878cc627450bb8326dd46110250061eb953da9510e6e431e227e45cb7673d`。
  - PubMed：accepted claims=11,921/16,370，eligible sources=1,479，
    whitelist hash=`512b8ae484f31fe68539809cc8de038728f999009a6bfc14dec52d8b12a36eee`。
- Enron 原 wave 7 完整处理了 source 1,751–2,000，而旧 exact-stop finalization
  只 retained 到 1,837。RC1 对完整 wave 7 得到 20 个合格 source，其中 9 个在旧
  retained boundary 之后；因此可审计种子容量为 694，缺口为 556。
- 为避免重算前 2,000 个 source，创建 seeded extension。它保留旧前缀，对剩余
  12,523 个 source 用当前本地规则重新排序，并将八个旧 wave 转成 RC1 绑定的
  checkpoint chain。extension plan hash=
  `bc3ec9779f7c48048d27c0a6ed74391130d098447ad55f14a148f9b7f753dd66`；
  `--resume` 校验显示 scanned=2,000、eligible=694。
- 未处理后缀的无模型预筛显示新排序前 250 个 source 中 43 个具有至少 4 个本地规则
  potential facts；GLiNER 仍可能补充命名实体，因此不能据此直接宣称该 wave 最终
  eligibility，但该数字提示收益不确定。停止规则固定为先跑一 wave，再按真实新增
  eligible 数决定是否继续。
- Edgar 全 universe 仅 1,549 source，RC1 cap=5 只剩 952；这不是简单换一批 source
  可以解决。下一合法动作是预注册 cap=8 probe，不能手工回收 `Company`、截断金额或
  其他已知坏例，也不能把 PubMed 的充足容量替代 Edgar 数据集门禁。
- 完整 unittest 271/271 通过。正式 API、Retriever、dense index 重建、新 RC 与
  Release 裁决均未启动。

### 2026-07-28：统一切换 3 pair / 6 queries

- 第二个 Enron extension wave 完整写入 checkpoint 0010：processed/retained
  source end=2,500，4-pair eligible 仅从 711 增至 713；但该 wave 有 118 个
  exact-3-pair source，加上 2 个 ≥4-pair source，共新增 120 个 ≥3-pair source。
- 十个已完成 wave 合并后的 ≥3-pair 容量为 1,308。新入口
  `scripts/reselect_enron_v6_3_budget6.py` 只读取 RC1 claims、stealth decisions、
  source order 和 checkpoint，不运行任何模型；在第 1,250 个合格 source 处得到
  retained source index=2,361。
- Enron 最终 budget-6 结果：source=1,250、pair=3,750、query=7,500；
  whitelist hash=
  `949a6fb41f9620f12dd40d701e5fe3ec53150eb8980762e677cd062c5f1e7e3c`，
  fixed-budget plan hash=
  `c8b7c4a4b5f1c692c608656c623480020d9c94a35754cc1f429b51df74baf138`。
- 同一 RC1 本地重选下，Edgar=1,173、PubMed=1,820。PubMed 通过，Edgar 缺 77；
  该缺口来自 cap=5 的 source 事实数量，不允许通过恢复已知坏 claim 填充。
- 主设置统一改为 3 pair/6 queries，而不是仅对 Enron 特判。理想独立近似下相对
  4 pair 的聚合标准误增加约 15.5%，但 source 数从不足提升到 1,250，且 API 成本
  下降 25%；最终影响必须在 2/4/6/8 调用预算消融中如实报告。
- 当前配置变化会使旧 4-pair Enron plan 的 identity 与新配置不一致；这是预期的
  superseded 状态，不得继续 resume。正式 victim API 仍未启动。
- 验证结果：274/274 unittest 通过；受影响 Python 文件内存编译通过；canonical、
  attack、RAG、data eligibility 与 `P0_PROTOCOL` 的 3/6 配置一致；Enron 最终
  1,250 source 均严格含 3 pair、6 条非空且文本唯一 query。
- Edgar 定向 cap=8 入口已实现并冻结。它从 cap=5 的 exact-2-pair source 中筛出
  147 个确实存在第 6–8 chunk 的 source，共 438 个新增 chunk；按新增 chunk 数和
  稳定 hash 排序，每 wave 50 source，只需新增 77 个 upgrade 即停止。plan hash=
  `8fc79a76cadac0e779d82b3e72a41bb5c057c5513421963ba34efc5ee8f9644d`。
  准备与只读 resume 均通过，加入新入口后完整 unittest 为 276/276。
- 用户完成两个定向 wave 后，Edgar 新增合格 source 已覆盖所需 77 个，最终
  capacity status=`sufficient`，source=1,250、pair=3,750、query=7,500。
  whitelist hash=
  `9229525cfa9d57953b02fd1d17c363e44238428f27df61e46e81366e35bff99a`。
  独立完整性复核确认每 source 恰好 3 个完整 pair、6 个 query_id 和 6 条非空且
  文本唯一 query，manifest 中三个输出 hash 均匹配；API/Retriever 调用为 0。

### 2026-07-28：budget-6 release input 兼容层

- 三数据集的最终选择产物来自不同恢复路径，不能直接伪装成旧 v3/v4 扫描结果。
  新增独立 `v6_3_rc1_budget6_release_v1` 协议，只做已冻结 facts/claims/queries
  的确定性封装与 hash 绑定，不重跑模型、embedding、Retriever 或 API。
- release input 必须逐 source 验证 3 pair/6 条非空且文本唯一 query、Q+/Q−
  配对、validator identity、source/whitelist 集合一致，并从原始 wave facts
  精确回收每个 selected fact；缺失或冲突 fact 一律 fail closed。
- 首次聚焦测试命令因 `tests/` 非 package 而收集失败，改用 unittest discover；
  该错误发生在导入前，不涉及 artifact 或模型计算。
- release input 结果：
  - Edgar：1,250 source / 3,750 pair / 7,500 query，whitelist hash=
    `9229525cfa9d57953b02fd1d17c363e44238428f27df61e46e81366e35bff99a`。
  - Enron：1,250 source / 3,750 pair / 7,500 query，whitelist hash=
    `949a6fb41f9620f12dd40d701e5fe3ec53150eb8980762e677cd062c5f1e7e3c`。
  - PubMed：1,820 source / 5,460 pair / 10,920 query，whitelist hash=
    `11c9f271b8d58f145af22867f1e9966cb32b2f54389f91b6b6cada09be0cd4af`；
    formal split 仍只确定性选择 1,250 source。
- 正式 eligibility loader 对三份 release manifest 分别返回 1,250/1,250/1,820，
  checkpoint、whitelist 和 3/6 budget 门禁通过。`data_v6_3.yaml` 仅将三条
  `source_eligibility_path` 切到新 release 目录，并保留上游 v3 scan 配置。
- formal split 已重建：Edgar、Enron、PubMed 均为 500 KB_Member /
  500 True_Non_Member / 250 Reserve / 0 Spoof_Seed，`target_unit=sources`、
  `source_exclusive=true`；split manifest 均绑定
  `v6_3_rc1_budget6_release_v1` 及各自 whitelist hash。

### 2026-07-28：attack-first RC2 止损决策

- RC100 的后续复核确认四类重复问题会形成攻击 shortcut：`in the Dublin` 这类冠词
  错误、国家→城市或药物→工具包这类跨大类替换、`commercial partners` 等确定泛称、
  以及 `Song Bo, to earn ...` 等没有完整断言的残句。
- 这些问题会使 Q− 在 member 与 non-member 上都因表面荒谬而被拒绝，污染配对差值；
  因此需要修复。银行→公司、全名→姓氏、国家→区域等仍自然的细粒度差异不再追求
  完全一致。
- RC2 采用确定性 attack-first profile：可明确判断时才强制 LOCATION/PRODUCT
  大类兼容；无法明确判断的实例保持可用，不增加第三个 NER 模型。
- 子型/冠词问题通过重新生成反事实解决；原实体为确定泛称或句子为确定残句时拒绝并
  从同 source 的其他候选补位。所有失败继续保留稳定 reason code。
- 本轮不调用 API、Retriever，不重新抽取全部 chunk。只允许一次 RC2 和一次审计；
  若仍未达到明显伪影率 <5%，记录限制并停止继续修改。

### 2026-07-28：attack-first RC2 正式产物与审计结果

- 历史审计只读回放发现 Edgar/Enron/PubMed 分别有 17/10/9 条明显 RC2 问题；逐条
  复核后均属于会造成攻击 shortcut 的大类冲突、冠词、泛称或残句，不是细粒度挑刺。
- 第一版本地重筛保留旧 claim-stage 语义元数据复查时，Edgar 只能得到 1,211 个
  source，且 10,360 个失败中有 4,404 个来自重复的
  `original_entity_metadata_semantic_mismatch`。原 facts 已经通过冻结的
  GLiNER2-large 门禁，因此 RC2 去掉该重复复查，但保留 span、单槽、粗类、
  source-absence、完整性、pair/query 唯一性和 stealth 门禁。
- 最终 RC2 本地重建结果（GLiNER/API/Retriever 调用均为 0）：
  - Edgar：1,250 source / 3,750 pair / 7,500 query，whitelist hash
    `bd859976d9bce18c2d4ca287fccae135691ea180ce84d7d65d46c053ca8836dc`。
  - Enron：1,250 / 3,750 / 7,500，whitelist hash
    `7705cd27f16d33a33442c8bf82ee6db6fcc65b863ae8b380631ed214d69fa327`。
  - PubMed：1,250 / 3,750 / 7,500，whitelist hash
    `6a145697be6e50f68755cd38a5a25820b5dbf759a5fafce4fa1acd709de36968`。
- `data_v6_3.yaml` 默认 release 已切到
  `v6_3_attack_first_rc2_budget6_release_v1`。按该配置重新生成的 benchmark hash：
  Edgar `0c47a6e07cd42293476a1880d9bbfd9d737efbc0f22ec9a1bef59a76faa1d380`；
  Enron `b65cbb6bed9651c821ab0a9b85b75d449ed4f3297a558041f23a481de5286b19`；
  PubMed `2dfe77d70175049e6fc2c1d3dd8ddc3151eb230ebe9bcb99a539916ade5d29bb`。
- promotion 后 claims/query hash 未因配置入口切换而变化；完整性报告
  `artifacts/v6_3/audits/budget6_formal_integrity_report_attack_first_rc2.json`
  验证三数据集均为 1,250/3,750/7,500。
- 新 formal RC100 预审为 0 high-risk / 101 needs-review / 199 low-risk；
  Release200 为 0 / 219 / 381。needs-review 是开放语义实体、专名逗号和少量
  PubMed ID 的人工抽查提示，不是自动失败；按 attack-first 目标停止继续调规则。
  这些数字不能表述为真实双人盲标、双通过率或 Cohen's κ。
- Enron 单 cell pilot 输入已冻结到
  `artifacts/v6_3/pilots/enron_qwen3_5_397b_minilm_rc2/`：10 member、
  10 true non-member、5 reserve，150 条 query；预算为 RAG 150 +
  matched LLM-only 150，共 300 次潜在调用。生成预算时 API 调用为 0，价格在
  endpoint/provider 未冻结前保持 `unavailable`。
- 最终回归为 302/302 tests；260 个 Python 文件内存 `compile()`、15 个 YAML
  解析、formal integrity 和 `git diff --check` 均通过。直接 `py_compile`
  仍会因 Windows `scripts/__pycache__` ACL 报权限错误，因此按项目既定方式使用
  不写 `.pyc` 的内存编译；这不是语法失败。

决策：RC2 已满足“去除明显攻击 shortcut、不过度追求语义完美”的工程门禁，本轮
停止 validator 迭代，不实施 RC3。论文若声称真实双人盲标，仍必须另行获得真实标签；
当前可先进行小规模机制 pilot，不能把 AI 预审冒充人类一致性。

### 2026-07-28：Enron v6.3 dense index

- 为避免继续增加入口，只修改现有 `configs/rag_config.yaml`，将 logging、split、
  index、benchmark、queries、responses 和 facts 路径统一从 v19 切换到 v6_3。
- 首次误用 `D:\python\anaconda\python.exe`；该 base 解释器没有 `faiss`，因而写出
  21.0 MiB 的 `json_vector_fallback`。随后确认
  `D:\python\anaconda\envs\mia_model\python.exe` 中 `faiss=True`，使用正确解释器
  原目录 `--force` 重建，旧 fallback 被覆盖。
- 最终 index 位于 `artifacts/v6_3/indexes/enron/dense/`：
  `retriever_id=sentence-transformers/all-MiniLM-L6-v2`、
  `embedding_backend=faiss.IndexFlatIP`、`embedding_dim=384`，
  index 大小约 3.82 MiB。
- 输入为 2,611 条 `KB_Member` 记录、恰好 500 个 source；docstore group 仅有
  `KB_Member`，doc ID 与输入逐项一致，与 True_Non_Member/Reserve 重叠为 0。
  `kb_hash`、`docstore_hash`、`index_hash` 全部复核通过，top-5 冒烟检索的五个
  doc ID 均属于当前 KB。
- MiniLM 加载时的 `position_ids UNEXPECTED` 或
  `get_sentence_embedding_dimension` FutureWarning 不改变向量或索引身份。
- 当前仍未调用 victim API。下一步必须先确认 Qwen3.5-397B 的实际 profile、
  model version、endpoint 和价格，避免默认 `openai_api` profile 中的
  GPT-4.1-mini 被误当作 Qwen。

### 2026-07-28：仓库瘦身边界

- 保留当前 RC2 正式产物：`artifacts/v6_3/attack_first_rc2`、
  `budget6_release_inputs_attack_first_rc2`、`processed`、`splits`、
  `benchmarks`、`facts`、`paired_claims`、`paired_queries`、
  `stealth_filtered_queries`、`audits`、`indexes`、`pilots`、`logs`
  以及小型语义校准证据。
- 删除旧版本和已被 RC2 取代的中间产物：`artifacts/v19`、
  `artifacts/v6_3/eligibility`、`rc1_revalidation`、
  `rc1_budget6_revalidation`、`budget6_release_inputs`。
- 删除 `.pytest_tmp` 和 `.ruff_cache`。`__pycache__` 清理因仓库既有 Windows
  ACL 拒绝访问而停止，残留约 2.26 MiB；不为这点空间修改目录权限。
- 删除前核验的预计释放空间约为 10.03 GiB。旧 eligibility 原始扫描若要完整
  重建，需要重新运行本地语义模型；当前正式 RC2 release input 与最终产物不受影响。
- 代码仅移除诊断、连通性测试和已完成的一次性 v6.3 容量恢复脚本；编号主流水线、
  RC2 重建、正式完整性验证、审计、模型锁和校准代码保留。
- 实际清理后 `artifacts/` 为 1.682 GiB / 313 files，相比清理前约
  11.69 GiB 释放约 10.01 GiB。
- 删除 17 个历史/诊断脚本、7 个对应专用测试、1 个失效扫描配置，并额外移除
  旧 validator development diagnostic；运行代码和 README 中
  `artifacts/v19` 及已删除脚本的有效引用均为 0。
- 标准 `data_config.yaml` 与 `data_v6_3.yaml` 文件 hash 完全相同；
  标准 `pcv_attack_config.yaml` 与 `pcv_attack_v6_3.yaml` 解析结果完全相同。
  两份 v6.3 命名配置继续作为小型备份保留，没有删除配置文件。
- 清理后验证：283/283 unittest、235 个 Python 文件内存编译、14 份 YAML
  解析、`run_pipeline.py --dry-run` 和 `git diff --check` 均通过。
- formal 完整性仍为每数据集 1,250 source / 3,750 pair / 7,500 query。
  Enron FAISS index 仍为 2,611 KB rows / 500 source，禁入组重叠 0，
  KB/docstore/index hash 全部匹配。

## 2026-07-30—31：v20 BGE RAG + Llama 主模型升级

- 正式协议升级为 `pcv-mia-v20` / `pcv-rag-only-source-v20`。旧 MiniLM
  索引与失败响应归档到 `legacy/abandoned_retriever_20260730/`，旧 suite
  标记为 superseded，不得进入 canonical release。
- 新增 Generator family registry。由于 `gemini-2.0-flash` 在首次正式调用前
  已不可用，按 `api_availability` 规则合法解冻；主模型改为并冻结
  `family=llama`、`model=meta/llama-3.1-70b-instruct`。Gemini、Qwen、GPT
  保留为后续 extension，任何已调用后的具体型号变化必须新建 suite。
- BGE dense 固定为 `BAAI/bge-base-en-v1.5` commit
  `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`；reranker 固定为
  `BAAI/bge-reranker-base` commit
  `2cfc18c9415c912f9d8155881c133215df768a70`。模型 snapshot 已下载并生成
  文件 SHA 清单，运行时强制 local-only。
- 项目唯一环境固定为 `D:\python\anaconda\envs\mia_model\python.exe`。
  PyTorch 已从 CPU build 换为 `2.11.0+cu130`，CUDA 13.0 和 RTX 4060
  Laptop GPU 实测可用；`requirements.txt` 与 `AGENTS.md` 已同步。
- Reserve-only 离线门禁比较 128/32、256/32、384/64 三种切块，以及
  dense、BM25、hybrid+reranker。只有 128/32 在三数据集同时通过 dense 硬门禁：
  Edgar R@5/R@10=0.7753/0.8400，Enron=0.8633/0.8933，
  PubMed=0.9073/0.9253；forbidden overlap 全为 0。
- 128/32 上的 hybrid R@5 分别为 0.9187、0.9887、0.9960，均高于 dense。
  配置选择明确记录 `selection_uses_attack_metrics=false`，未查看攻击 AUC，
  不触发 BGE-large fallback。
- 三数据集正式 dense+BM25 索引已完成并逐行审计：Edgar/Enron/PubMed
  分别为 65,933/6,596/31,164 chunks，每个数据集恰好 500 个 KB_Member
  source，其他组混入为 0。
- Llama compatibility pilot 查询计划已冻结：每数据集 10 member、
  10 true non-member、5 reserve，共 150 条唯一 query。六系统为 dense、BM25、
  hybrid、matched LLM-only、Oracle、Random，正确总预算为 2,700 次 API 调用；
  原 2,160 是算术不一致，已在调用前修正。
- 最终本地验证：297/297 unittest、245 个 Python 文件 AST、17 个 YAML、
  `pip check`、CUDA/BGE 冒烟与 `git diff --check` 均通过。`.env` 的 endpoint、
  key 与请求 model 已配置且请求 model 匹配 registry；Provider 实际返回 model ID
  仍须由首个真实响应验证。
- 本阶段 Generator API 调用数为 0。下一步是运行 2,700-call Llama pilot，
  三数据集全部通过后才能启动约 90,000-call 主 suite。
- 详细设计、指标、hash、环境与验证证据见 `研究记录/思路v20.txt` 和
  `artifacts/v20/retrieval_gate/retrieval_gate_report.json`。

## 2026-07-31：正式 API 前审稿红队审计

- 结论从“下一步直接运行 2,700-call Pilot”调整为“先完成 Phase 8C0
  preflight remediation”；当前 Generator API 调用仍为 0。
- P0 数据/统计问题：现有 benchmark 曾参与方法开发，缺少 untouched canonical
  test；同一批 Reserve 同时用于 Retriever 选择、Pilot 和 conformal calibration；
  500 个负样本的经验 FPR 步长为 0.2%，不能支撑 TPR@0.1% FPR。
- P0 Pilot 问题：Oracle 从只含 KB Member 的正式 docstore 取 target context，
  因而每数据集 60 条 True Non-member 与 30 条 Reserve query 的 Oracle context
  全为空；Random 也未与 Oracle 严格匹配 context budget。当前 Oracle/Random
  门禁不能直接使用。
- P0 实验矩阵问题：baseline 仍按 chunk 调用，静态估算三个 Retriever 可能达到
  约 249.6 万次 victim calls，既不与 PCV 的 6 calls/source 公平，也无法在
  4 RPM 下执行；正式 baseline 还需要处理 MEntA/E-MIA 及 adapted implementation
  的标注。defense runner 仍是 placeholder，canonical gate 不得接受空 defense。
- P0 外部有效性问题：目标 system prompt 强制输出结构化 correction signal，
  需要增加中性 RAG prompt robustness cell；长周期主矩阵必须按 block 交错条件，
  避免 Retriever 与 provider 时间漂移混杂。
- 开跑前仍需完成真实双人 claim 审计、Llama stance parser 人工正确性审计，
  并冻结 primary endpoint、功效/精度、多重比较和 missing-response 规则。
- 正面证据保持不变：三数据集正式索引禁入组重叠为 0；简单 source/query
  协变量交叉验证 AUC 约 0.502/0.466/0.500，未见明显标签捷径；`mia_model`
  中 297/297 unittest 通过。
- 详细风险、证据和 Gate A—D 开跑顺序见 `研究记录/思路v21.txt`。
- baseline 的 433 天是错误的 chunk-level fan-out 规模，不是论文必需预算。
  当前正式五方法明确保持为 DCMI、IA、MBA、RAG_MIA、S2MIA；MEntA/E-MIA
  只是近期工作风险，不是已经采用的 baseline。按当前方法原生预算合计约
  10 calls/source。用户已决定五个 baseline 只跑 BGE，不跑 BM25/hybrid；
  BGE 完整 1,000 source/dataset 约 30,000 calls，即 4 RPM 下约 5.2 天。
  该限制只针对 baseline，PCV 主方法的 BGE/BM25/hybrid 矩阵暂不改变；预算仍待
  Phase 8C0 用 source-level dry-run 复核。
- 用户进一步冻结预算方向：PCV 主方法继续保持每数据集、每 cell 7,500 calls；
  baseline 每个 evaluation source 只使用一个 representative chunk，不遍历全部
  chunks。代表 chunk 必须在响应前按统一、标签无关规则冻结，五方法共用同一
  source→chunk manifest；推荐选择与冻结 claim/query evidence 最相关的 chunk，
  并在论文中标为 source-level adapted baseline。

## 2026-07-31：v20 现有 Source 原地冻结整改完成

- 用户最终否决了红队审计中的两项扩展：不增加中性 Prompt robustness cell，不做
  真人 claim 双标或 Llama parser 人工审计。论文适用范围限定为“结构化声明核验型
  RAG”；人工质量模板只保留历史审计证据，不伪造 κ/F1。
- 不下载、不扩充 source。当前三数据集各 1,250 source 在首次 Llama 响应前定义为
  `pre_response_frozen_canonical`。Reserve 保留双重角色，但口径改为 Retriever
  冻结后的经验非成员校准：5 个 `pilot_diagnostic` 永久排除，245 个
  `conformal_calibration`；不再称为完全独立校准集。
- 近重复审计在 API=0 时完成。Edgar 按 cluster/seed 42 原地重分组 2 个 source，
  Enron 重分组 14 个，PubMed 无需调整；三个数据集最终仍严格为 500/500/250，
  cross-group overlap=0。旧 split/benchmark/query/index 备份位于
  `legacy/pre_response_regroup_20260731/`。
- 重分组后重新冻结 query 与 benchmark：query hash 分别为
  `250a392f...ff0d`、`627405f6...798f`、`cb47ed25...993`；benchmark hash
  分别为 `1279aa0e...00e6`、`a25e237f...e13b`、`2dfe77d...29bb`。
- Retriever 离线门禁完成 3 数据集 × 3 切块配置共 9 个候选，未使用攻击分数。
  唯一全数据集通过的 dense 配置为 128/32：Edgar/Enron/PubMed Recall@5
  分别为 0.7733/0.8653/0.9073，Recall@10 为 0.8393/0.8947/0.9253，
  source 零命中率为 0.4%/0%/0%；macro Recall@5=0.8487、
  macro MRR=0.7635。报告位于
  `artifacts/v20/retrieval_gate/retrieval_gate_report.json`。
- Oracle 改为从三组均完整的只读 `ground_truth_source_store` 取目标 source，
  按当前 query 选最多 5 个 128/32 chunks。Random 与 Oracle 匹配 chunk 数并把
  token 差限制为 5%，同时排除 target、exact duplicate、MinHash≥0.85 和
  BGE cosine≥0.85 的 source；Recall 分母只包含 KB Member。
- 五个 baseline 最终固定 DCMI/IA/MBA/RAG-MIA/S2MIA 且只跑 BGE。每个
  Member/Non-member source 只冻结一个代表 chunk，选择规则为六条冻结 query
  与 source 全部 128/32 chunks 的最大 BGE cosine，平局按 chunk_id。三个
  manifest 均为 1,000 source；hash 分别为
  `35f60e4e...2821`、`adab44ee...6c94`、`20572fa4...c22d`。
- 两个零 API response-layer defense 已真实实现：
  `answer_without_correction` 与 `target_entity_redaction`。防御后重新 parse、
  score、经验 conformal；只报告 privacy 和 stance/answer/correction/refusal
  utility，不声称通用 QA utility。placeholder/空指标会被 canonical gate 拒绝。
- 统计口径冻结为 source-level AUC/95% CI、attack advantage、TPR@1%/5% FPR、
  conformal TPR/FPR@1%/5%、Recall@5/10、MRR 与零命中率。删除数值型
  TPR@0.1% FPR。唯一 primary endpoint 是 Llama+BGE 三数据集等权 macro AUC，
  使用数据集内 Member/Non-member 分层的 2,000 次 seed-42 bootstrap。
- 90,000-request 主矩阵 schedule 已按 source block、数据集轮换与 Latin-square
  条件顺序冻结；每 source 的 24 个请求时间邻近，schedule hash 为
  `38dd6a54...9312`。resume 会绑定 schedule/query/benchmark/index/code/model
  身份；缺失响应不插补、不删 source，provider model/fingerprint 漂移即停止。
- 新增零 API 总预检 `scripts/26_validate_v20_preflight.py`，逐文件复核 split、
  query、benchmark、Reserve、Pilot、index、代表 chunk、schedule、Retriever gate、
  CUDA 环境和未产生正式响应。最终 preflight hash 为
  `34e2ffa3...b619`，状态 passed；Pilot 计划仍为 2,700 calls，正式调用为 0。
- API 启动入口新增 clean-worktree 硬门禁；Pilot、90,000-call interleaved 主矩阵
  和 baseline 都必须运行在冻结 commit 上。主矩阵首次成功响应会写入 Generator
  freeze state 的 `first_formal_call_at`，具体 model/version 变化禁止原地续跑。
- 最终本地回归：306/306 unittest；255 个 Python 文件 AST 编译通过；17 个 YAML
  解析通过；v20 总预检通过。下一步只剩配置真实 endpoint 后执行 2,700-call
  Llama Pilot；Pilot 三数据集全部通过前不得启动正式 90,000-call suite。
- 详细决策、实现映射和论文边界见 `研究记录/思路v22.txt`。

## 2026-07-31：MEntA source-level adapted baseline 接入

- Llama `full_methods` 从五方法扩展为六方法，新增 MEntA
  （Membership Entailment Attack，arXiv:2605.24312v3），仍只在 BGE baseline
  cell 运行并作为 secondary baseline；PCV primary endpoint 不变。
- MEntA 每个冻结 representative source 使用一个 summary 和 5 个自然信息寻求型
  query，固定 5 次 victim RAG 调用。query 由现有 `PCV_SIBLING_*` profile 在
  `scripts/27_prepare_menta_inputs.py` 中离线生成，baseline runner 只读加载，
  禁止运行中重新生成。
- 回答按确定性 sentence-like atomic claims 拆分，以 representative chunk 为
  premise、回答 claim 为 hypothesis；本地 NLI 固定为
  `tasksource/deberta-base-long-nli` commit
  `04dcf11f844b07bc57015169fca2b7d6df8299d5`。entailment 使用严格 argmax，
  另以 7 个 refusal hypotheses 检测拒答。source 分数为 5 个
  `entailment_hit - refusal_hit` 的均值。
- NLI 正式运行强制 hash-verified local-only snapshot、CUDA、`max_length=1280`，
  不允许 CPU fallback。权重目录保持 git ignore；query manifest、NLI snapshot
  manifest、协议 hash 均进入 baseline identity，漂移时拒绝 resume。
- 原五方法约 10 victim calls/source；加入 MEntA 后为 15 calls/source，
  每数据集 1,000 source 约 15,000 calls，三数据集约 45,000 calls。
- 代码、配置与零 API mock tests 已接入；最终回归为 320/320 unittest，
  其中 MEntA 定向测试 14/14，`compileall src scripts tests`、30 个 YAML 解析、
  `pip check` 与 `git diff --check` 均通过。`mia_model` 环境未安装 ruff，因此
  未执行 ruff lint；没有为此向环境新增依赖。
- 正式 NLI 权重尚未下载，三数据集 MEntA query manifest 尚未生成，正式 victim
  调用数仍为 0。下载脚本会先枚举固定 revision 的完整仓库文件列表，再逐文件记录
  size/SHA-256；本地加载同时拒绝缺失文件、额外文件、路径越界和哈希漂移。

## 2026-07-31：本地 Qwen3-4B sibling 接入

- 攻击侧 sibling 冻结为 Ollama `qwen3:4b-q4_K_M`，项目别名
  `pcv-qwen3-4b:q4km-8k`；Modelfile 固定 8K context、temperature 0、seed 42。
  该模型只用于 MEntA 输入生成、IA/DCMI attacker 和可选 Spoof，不作为 victim
  Generator，也不修改 `generator_families.yaml`。
- `configs/llm_profiles.yaml` 新增 `ollama_qwen3_4b`，默认云端 active sibling
  保持不变，本机通过 `PCV_SIBLING_PROFILE` 选择。OpenAI-compatible 请求固定
  `reasoning_effort=none`、seed 42、stream false、timeout 180 秒。
- 限速边界按用户确认冻结：本地 sibling 的 RPM 与固定间隔均显式为 0，不创建
  sibling 令牌桶；单并发由 `OLLAMA_NUM_PARALLEL=1` 保证。victim 继续独立使用
  `generation.requests_per_minute=4` 的令牌桶，不能被 sibling 的 0 覆盖。
- MEntA protocol 升为 `menta-source-adapted-v2`。query 行、query manifest 和
  baseline identity 绑定无密钥 sibling profile hash；模型摘要、endpoint、请求参数、
  provider model ID 或 partial/frozen resume 身份漂移时 fail closed。响应同时拒绝
  `<think>` 泄漏。
- Ollama 0.32.5 已安装到 `D:\Ollama`，模型目录固定为 `D:\Ollama\models`；
  `qwen3:4b-q4_K_M` 上游 ID=`2bfd38a7daaf`，8K 项目别名 ID=`39297c75a309`，
  本机 `.env` 已冻结 `PCV_SIBLING_MODEL_VERSION=ollama:39297c75a309`。
- OpenAI-compatible 冒烟返回精确别名和合法 JSON，reasoning/thinking 为空；冷启动
  53.167s。三数据集 30/30 功能样本全部通过，Edgar/Enron/PubMed 热启动 p95 分别为
  2.462s、1.834s、2.403s，profile hash 均为
  `0a96bc1d4dc73b8f6f64cc9227d6a67de1d93b39ecb988449262b2b2f0912849`。
- 首轮 50 条稳定性门禁在第 50 个 source 因重复问题被协议正确拒绝；准备脚本随后只对
  JSON 结构/问题唯一性增加最多 2 次纠错重试，身份、thinking 和 provider 漂移仍立即
  fail closed。MEntA 定向测试 18/18 通过，重跑 50/50 通过，p95=1.735s、最大
  1.910s；BGE 同驻时 `ollama ps` 为 100% GPU/8192 context，GPU 峰值
  3983MiB/8188MiB、峰值利用率 97%，无 OOM、超时或 CPU fallback。
- 当前只生成隔离诊断产物 `artifacts/v20/local_sibling_gate/`。三数据集正式 1,000-source
  MEntA manifest 仍待 clean release commit 后生成，禁止把诊断或旧云端产物提升为正式产物。

## 2026-08-01：多样化实体槽问句协议升级（代码完成，产物待重冻）

- 根因确认：旧 Step 08 把原始 `true_claim` 直接套入统一查询前缀，导致长句、逐字复制与句式单一；
  旧 Step 09 又以 query--claim embedding 余弦拒绝 `too_similar`，实际惩罚了检索有效性。
- 决策：`true_claim` 继续原样保留；正式 query 改为
  `diverse_slotted_verification`。Sibling 按 source 一次处理三个 pair、每 pair 返回三个候选，
  只生成一次含 `{ENTITY}` 的自然极性问句/本地 proposition。Q+/Q- 由本地填槽，槽外字节级一致。
- 本地硬门禁已实现：唯一槽、8--45 token、极性问句、攻击/注入术语、结构化字面量幻觉、原文锚点、
  true/counterfactual 双向 NLI entailment、问句--命题 cosine>=0.80、source 级联合多样性、
  最多两次纠错；仍失败时整数据集 fail closed，不删除 pair/source。
- Step 09 改为按 `source_key` 绑定 attack benchmark 原始 chunk；实体遮蔽后要求 5-gram containment
  <=0.35、最长连续公共 token 串<=8。embedding 仅记录 query--claim 与 query--chunk 语义诊断，
  不再产生 `too_similar/too_dissimilar` 拒绝。正式 fixed budget 丢失任一 source 时整数据集失败。
- RAG/LLM-only 标签改为 `Verification request`，三种 stance 出口不变；不增加中性 Prompt cell。
  论文边界继续限定为结构化声明核验型 RAG，不声称适用于任意 free-form QA/RAG。
- 新增 shadow 晋升门禁：每数据集 100+100 source、旧/新同一 Llama+BGE 共 7,200 victim calls，
  BGE/BM25/hybrid 离线对照；macro AUC delta bootstrap 95% 下界>=-0.01、单数据集下降<=0.03、
  Recall@5 下降<=0.02、5-gram 中位数至少下降 50%，且全部结构/自然度/语义/多样性门禁通过。
- 模型身份：正式 Step 08 必须显式冻结 `PCV_SIBLING_MODEL`；effective profile、endpoint、实际返回
  model ID、NLI snapshot、claims/benchmark/protocol hash 全部进入 resume identity，禁止跨 5.6/5.5/5.4
  或跨 endpoint 混合产物。
- 冻结状态：Step 06/07、split、benchmark 与 index 内容保持冻结；旧 Step 08/09、Retriever query
  report、Pilot/Oracle/Random、query controls、baseline/MEntA 绑定、schedule 和总 preflight 均标为 stale，
  必须在 shadow 晋升后按新 query hash 重冻。preflight 已增加对应拒绝条件。
- 本次没有调用 sibling/victim API，没有生成新正式 query hash，也没有伪造 shadow 结果。详细接管见
  `研究记录/多样化实体槽问句升级_实施记录.txt`。
- 本地收口验证：使用 `mia_model` 解释器全量 unittest 340/340 通过；相关 Python AST、5 份 YAML
  与 `git diff --check` 通过。shadow 审计另外硬绑定固定 Llama victim、BGE RAG、旧/新变体身份、
  7,200-call 预算和禁止中性 Prompt cell。

## 2026-08-03：PCV-MIA v21 实施与当前接管点

- 模型角色已重构为三个彼此隔离的身份：Luna `gpt-5.6-luna` 只负责 PCV/MEntA/IA/DCMI
  文本生成；Ollama `pcv-qwen3-4b:q4km-8k@39297c75a309...` 只负责 IA Shadow answer；
  `google/gemma-2-2b-it` 作为本地 BF16/CUDA/no-quantization/batch=1 victim。Gemma 以外的
  Phi/Llama/Command-R 家族仍为 pending，不得产生正式响应。
- 新增 v21 registry、RAG/data/baseline/experiment 配置，新增本地 Hugging Face victim client、
  Luna/IA Shadow 角色 client、严格响应成功判定、IA Shadow 冻结流水线、IA victim 五问运行器、
  `TPR@0.5% FPR` 经验阈值统计与独立调用账本。成功响应必须同时通过 HTTP/transport、正文错误文本、
  actual model ID、冻结 version、request ID 与 called_at 门禁。
- IA 正式边界已实现为 summary -> 30 candidate questions -> 冻结 BGE 排名 -> Qwen 依次作答 ->
  前 5 个可解析非 IDK pair -> manifest 冻结 -> Gemma 相同五问；不足五问会阻断整个 source，不能根据
  victim 回答/AUC 补位或删 source。IA run identity 绑定 query hash、shadow manifest hash 和版本。
- v20 清理采用“留证据、删大文件”：`legacy/provenance_v20_superseded_20260803/` 保存 818 个文件、
  4,136,580,751 bytes 的路径/大小/SHA-256 清单，inventory hash=
  `377c25fc541fdb34a6124e0f24ae81e6bd1e7249278992854cbebdd784ceda221c`，另复制 278 份关键证据。
  校验通过后已删除批准的 `artifacts/v6_3`、`artifacts/v20`、`indexes`、`outputs` 和两个旧 legacy
  payload；原始数据、模型、代码、配置、测试、研究记录未删除。
- 清理脚本未把旧 per-type calibration summary 正文复制进 evidence（文件名不命中当时的复制 token）；
  不能伪造旧 summary。已新增 fail-closed 恢复记录
  `artifacts/v21/release_controls/semantic_calibration_provenance.json`，其 SHA-256=
  `342bb8774df212ca41d406c18c160fa5b58fd130ceeccdda1b8e5a6f359d8dcb`，同时绑定旧 summary 清单
  SHA-256=`9a32fd54252c104a6277b1aa90863a572caff63a0527a0335ea1788de15a432d`、Phase 7I 研究证据段、
  206-row/0 false accept/六类 precision=1.0 门禁、阈值 hash 和模型锁。论文前若找回原始标注行，
  应重跑校准；当前记录只恢复身份，不宣称重建结果。
- v21 Step 01 完成。EDGAR 扫描 5,480 raw records，得到 5,210 unique sources/325,539 kept chunks；
  Enron 扫描 60,000 raw records，得到 18,893 unique sources/48,178 kept chunks；PubMed 扫描完整
  50,000 raw records，得到 47,950 unique sources/645,161 kept chunks。这里只证明 source 容量，
  尚不等价于 query eligible。
- 三数据集 eligibility 均冻结 4,500-source、seed=42、wave=250 的零 API plan：EDGAR plan=
  `50179b6c0c0e3396dc2f71ba9df8062d51eecfaf370973eb72f665148430c9bf`，Enron=
  `3a272a71d730ea6bc1888013a3ed77eedf958d444409ec0733ffcd31df6d4b63`，PubMed=
  `5bb3e47a73c6d577859f8cd6bd7f071b89df6ba9f852409be690a0c54a0f0f89`；三者 shortfall=0，
  API calls=0、Retriever runs=0。
- 首次 EDGAR wave 被环境门禁拦截，因为唯一 `mia_model` 环境缺少 GLiNER/spaCy 且 Transformers=5.7.0
  超出 `<5.0`。随后按 `requirements.txt` 修复为 torch=2.11.0+cu130、transformers=4.57.6、
  spacy=3.8.14、gliner2=1.3.2、gliner=0.2.27、en-core-web-trf=3.8.0；CUDA=True，设备为 RTX 4060
  Laptop。恢复 wave 后因用户要求改为自行长跑而安全终止，未生成 checkpoint；保留
  `wave_0000_attempt_000` 和可复用 SQLite prediction cache，`PRAGMA quick_check=ok`，正式 eligibility
  仍未完成。
- 模型短预检：Luna 唯一成功请求返回 actual model ID=`gpt-5.6-luna`、合法 request ID，严格门禁通过，
  latency=39.57s；Qwen Shadow 返回实际别名、request ID、fingerprint，按正式解析规则把 `Yes.` 规范化
  为 `Yes` 后通过，热调用 latency=0.447s。第一次 Qwen 诊断因预检脚本错误地要求逐字 `Yes` 被标失败，
  已修正为复用正式 parser；两次均不是正式 IA answer。Gemma 精确 revision
  `9b78bb926a2a249dd297e27b043019eb0666ce82` 未在本地 HF cache，故 victim preflight 阻断且
  Gemma formal calls=0。所有 query/shadow/victim 正式调用仍为 0。
- 收口验证：`D:\python\anaconda\envs\mia_model\python.exe -B -m unittest discover -s tests`
  为 346/346 通过；关键 v21 文件内存编译通过。详细协议和逐步状态见 `研究记录/思路v23.txt`。

## 2026-08-04：Enron 完整抽样框与固定 30,000-source 候选池修订

- Enron v21 cap=5 已完整扫描冻结的 4,500-source pool，最终 claim eligible=524、query eligible=514，
  低于 required=2,250；状态为 `fixed_candidate_pool_exhausted_below_required_capacity`。该结果保留为
  容量失败证据，不得删除、覆盖或进入 canonical release。
- 新的只读语料核查发现：本地 `emails.csv` 实际包含 517,401 封邮件、150 个用户；此前
  `source_limit=60000` 只覆盖文件顺序靠前的 20 个用户，属于明显的 prefix-sampling coverage
  问题。当前 Enron 派生 suite 因此统一标记为
  `superseded_enron_prefix_sampling_and_capacity_failure`。
- 决定不再运行 Enron cap=8/12。原因是 cap=5 pool 的 7,916 probe chunks/4,500 sources，平均仅
  1.76 chunks/source，增大 cap 只影响少量长邮件，同时会破坏三个应用数据集统一的 cap=5
  eligibility 定义。
- v21 Enron 改为：完整 517,401-message 语料只作为 sampling frame；先执行零 API 的解析、清洗、
  source/exact/near-duplicate 与用户覆盖审计，再按 seed=42/hash 冻结 30,000 个 candidate sources；
  只有这 30,000 个进入 cap=5 GLiNER/claim/query eligibility。不得对全部 517,401 封邮件运行昂贵
  semantic eligibility。
- membership split 必须发生在 eligibility 之后；从通过门禁的 source 中冻结 1,000 KB_Member、
  1,000 True_Non_Member、250 Reserve。筛选阶段不得读取组标签、victim response 或攻击 AUC；
  PCV 与所有 baseline 使用相同正式 source。
- 论文必须同时报告 raw/clean/candidate/query-eligible/formal source count、eligibility coverage、
  excluded-reason distribution、用户覆盖和 near-duplicate 排除量，避免把 fact-rich 子集描述成
  无条件代表完整 Enron。
- 本次仅确认协议并更新研究记录；未删除/下载数据，未修改运行配置，未启动 full-corpus preprocessing
  或新的 eligibility，正式 API/Retriever 调用新增 0。

### 2026-08-04 实施细化：两级固定抽样，长任务由用户运行

- 新增独立配置 `configs/data_config_v21_enron_full.yaml`，旧 `data_config_v21.yaml`、旧 4,500-source
  plan/checkpoint 和失败产物保持不变。
- 完整 517,401-message CSV 只作 sampling frame。第一级按完整邮件正文 SHA-256 精确去重，再以
  `sha256(seed,dataset,message_sha256)`、seed=42 冻结 150,000 封 raw screening mail；禁止 prefix sampling。
- 第二级只对 150,000 封 screening mail 做现有 Step 01 本地清洗/切块/实体基础门禁，再从合格
  processed source universe 以冻结哈希顺序取 30,000 source。150,000 是容量缓冲，不是正式 eligibility pool。
- 新 eligibility protocol 为 `v21_enron_full_corpus_fixed_pool_v1`：candidate pool=30,000、cap=5、
  无 cap=8/12 fallback、scan_full=true、minimum claims/pairs=3/3、required=2,250。
- sampling manifest 的 raw CSV hash、选择索引 hash、150-user coverage、selected JSONL hash 会进入
  eligibility plan/resume identity；任何漂移均 fail closed。
- 本轮不启动完整 CSV 抽样、Step 01 或 30,000-source eligibility 长任务；仅完成代码、配置、短测试，
  长任务命令交给用户运行。

### 2026-08-04：PCV_SIBLING 独立令牌桶开启

- 远端 `PCV_SIBLING` 调用统一冻结为 4 RPM，`request_interval_seconds=0`；令牌桶在每次物理 HTTP
  尝试（包括底层 retry）前取令牌，避免重试绕过端点限流。
- Step 08 PCV 问句生成、MEntA Luna query generation、IA Luna summary/question generation 和 runtime
  sibling baseline 均使用独立 sibling 桶，不与本地 Gemma victim 共用。
- local Ollama `pcv-qwen3-4b:q4km-8k` 与 IA Shadow 继续保持 RPM=0，不增加无意义的本地限速。
- RPM 属于 sibling profile identity；从 0/缺省改为 4 会改变 profile hash，旧 sibling query/shadow
  产物不得原地续跑或与新产物合并。

## 2026-08-05：18 类实体统一策略与正式全量 release gate

- 保留全部 18 类，新增唯一 policy registry；修复 semantic 已接受的 `CONTRACT_TERM` 和真实 ORG 缩写仍被 validator 重复 heuristic 否决的问题。semantic schema hash 保持不变，不按 Enron 合格率改类型定义。
- 新 facts/claims/manifests 绑定 `pcv_entity_policy_v21_r1`，policy SHA-256=`e867112519b5ee952b740ba58f3ffec046c5a0a710297dc06d8c677cc670b00e`。旧 checkpoint 只读回放，禁止与新正式身份 resume/合并。
- 实现 facts 级 + source 级旧产物回放、三个互斥 500-source pilot cohort、六类共 600 条盲审和 `v21_entity_policy_release_gate_v1`。所有 stage 绑定 commit/runtime tree/model/schema/policy/config hash，不读 victim response、Retriever 分数或 AUC。
- 旧 inventory 已实际冻结：EDGAR 3,500/2,931，Enron 1,250/85，PubMed 1,000/832，identity=`8f051d015607dd59ac2a6b7dbd40c5b634ea8f128cf02038f72b0dfd9aac564e`。
- 新正式协议 `v21_entity_policy_full_rescan_v1` 只有在 release gate 为 passed 且全部 evidence/current runtime hash 匹配时才能冻结计划或续跑。正式输出隔离在 `artifacts/v21/formal_entity_policy_r1/`；EDGAR/PubMed pool=4,500，Enron pool=30,000，cap=5，达到恰好 2,250 eligible 后停止。
- 本地最终全量 unittest 364/364 通过，AST/YAML/diff 门禁通过。API/victim/Retriever 新增调用均为 0。长 replay/pilot 和 600 条审计未执行，正式扫描仍被阻断。
- `freeze-pilots` 已于 2026-08-05 完成并经独立 validator 复核：pilot plan identity=`e43a1c4c4fa2d53db439993a5bd24d6878485078eea27805d0e337bd91c920c1`；A/B/C hash 分别为 `a14611d0...91e43`、`c1e9e9c9...045e2`、`f921e7a1...d50a`。每数据集冻结 1,500 candidate sources，三个 cohort 各 500，互斥且 evidence hash 完整。该状态仅表示样本冻结，不表示 pilot gate 已通过；B/C 继续密封。
- Enron historical replay wave 1/5 已完成并写入 stage checkpoint：旧同 wave query eligible=22/250；新 policy facts/source 双路回放结果完全一致，均生成 360 facts、233 valid pairs、29 claim/query-eligible sources。新合格率=11.6%，Wilson 95% 下界=8.20%，单波描述性结果越过 10%/8%阈值，但最终门禁必须等 1,250 source 全部完成。类型恢复证据：`CONTRACT_TERM` 37 facts→18 pairs，ORG 92→30，PERSON 25→22，LOCATION 15→8，PRODUCT 33→3；本波没有 PROJECT_NAME opportunity，不能判断其覆盖。
- Enron historical replay 已完成 5/5 并正式 passed：131/1,250 eligible，rate=10.48%，Wilson 95% lower=8.901%，分别越过预注册的 125、10%、8%门槛；相比旧策略 85/1,250（6.8%）增加 46 source、+3.68 个百分点。report identity=`fbac0df34bc915d1e8c869d24cf84477da1d4cd02660f4cc1c2761545ae0bacc`，failure reasons 为空。
- 五个 Enron wave 的 old-facts 与 source 全链路回放 pair 数均逐波一致 `[233,279,209,249,204]`，且类型计数一致，总计 1,174 pairs。全量 semantic 类型：CONTRACT_TERM 155→68、ORG 454→156、PERSON 134→123、LOCATION 90→72、PRODUCT 141→23；PROJECT_NAME opportunities=0，因此本数据集不能提供该类型证据，后续全局 semantic ≥90-pair release gate 仍会 fail closed。

### 2026-08-05：PubMed replay resume JSON 语义比较修复

- PubMed replay 在进入新 wave 前被 Step 07 manifest resume 校验阻断；不是数据合格率失败，也没有覆盖旧产物。根因是运行时 `semantic_entity_resolver.models` 为 tuple，写入 JSON 后按标准变为 list，旧代码使用 Python 对象直接比较，因表示类型不同而误报协议漂移。
- `src/paired_claims/claim_generator.py` 已改为逐字段比较 canonical JSON 内容：仅消除 tuple/list 的 JSON round-trip 假差；模型 ID、版本、文件 SHA-256、阈值、policy/hash 或其他实际内容变化仍会 fail closed。
- 新增双向回归测试：tuple→list 后允许 resume；模型 ID 改变仍拒绝 resume。定向测试 67/67、内存语法编译及最终全量 unittest 365/365 全部通过。未启动 PubMed 长任务，下一步原命令直接 `--resume`，禁止 `--force`。

### 2026-08-05：PubMed 零 checkpoint stage plan 审计重绑

- Step 07 修复改变了 formal runtime tree，原 PubMed `stage_plan.json` 已在第一次失败前写入旧 runtime hash，因此第二次 resume 被正确的 stage identity 门禁阻断。差异审计确认仅有 `runtime_tree_sha256` 与派生 `scan_plan_sha256` 两项变化；commit、source 顺序、inventory、attack config、policy、semantic schema/threshold 等全部不变。
- 当前没有 `stage_checkpoint.json`，完成 wave=0；旧 plan 创建后运行树中唯一被修改的文件是 `src/paired_claims/claim_generator.py`。未完成的 `wave_0000_attempt_000` 保留为非 canonical 证据，后续 source replay 会创建新的 immutable attempt。
- 旧 plan 已留存为 `stage_plan.superseded_20260805_resume_hotfix.json`，并新增 `stage_plan_rebind_manifest.json`；新 plan 绑定 runtime tree=`3aa227d7...a1a551`、scan plan=`683f378f...3b8589`。使用当前 inventory/config/runtime 重建 expected plan 后达到 exact match，plan validation passed。没有删除产物、伪造 checkpoint 或放宽已有 wave 的身份门禁。

### 2026-08-05：PubMed historical replay 最终通过

- `replay_report.json` 已由正式 `validate_dataset_report` 复核：4/4 waves 完成，872/1,000 source 合格，rate=87.2%，Wilson 95% lower=84.986%，failure reasons 为空，report identity=`1a3a9b1d1918dce9d4e650c04825eb5d76d44563ee876dfbcd82aba9a0eba723`。
- 预注册 replay 非劣门槛为 max(75%, 旧率 83.2%-2pp)=81.2%；新策略比旧策略 832/1,000 增加 40 source、+4.0 个百分点，因此 source gate 正式 passed。该结果是确定性 eligibility/policy 门禁，不是攻击 AUC 结果，不做显著性检验或论文图。
- 四个 wave 的 facts replay 与 source 全链路 valid pair 数逐波一致 `[1463,1561,1553,1503]`，合计 6,080；每波 eligible=`[212,222,224,214]`，合计 872。类型 gate 全部通过：CONTRACT_TERM 144→34、LOCATION 439→403、ORG 1,104→698、PERSON 49→46、PRODUCT 1,480→104；PROJECT_NAME opportunity=0。
- 合并已通过的 Enron+PubMed replay 后，CONTRACT_TERM/LOCATION/ORG/PERSON/PRODUCT 的 valid pair 均已超过全局 90-pair 门槛；PROJECT_NAME 仍为 0，是当前唯一未覆盖 semantic 类型，必须由 EDGAR replay/pilot 补证，否则最终 release gate fail closed。

## 2026-08-06：EDGAR replay 通过，但 PROJECT_NAME 阻断 release

- `replay_report.json` 已由正式 validator 复核：14/14 waves 完成，3,230/3,500 eligible，rate=92.2857%，Wilson 95% lower=91.3547%，source/type failure reasons 为空，report identity=`07a108f19a627bd013103e4587547408b6a5edeb2dfa7afac13bcb3a2f47a60c`。
- 旧策略为 2,931/3,500（83.7429%），预注册 replay 非劣门槛为 81.7429%；新策略增加 299 source、+8.5429 个百分点。14 个 wave 的 facts replay 与 source 全链路 valid-pair 数逐波完全一致，总计 29,122；eligible 分波合计恰为 3,230。
- EDGAR semantic 证据：CONTRACT_TERM 6,662→3,086、LOCATION 919→814、ORG 7,847→4,565、PERSON 140→122、PRODUCT 1,768→141，均通过；PROJECT_NAME 仅 1 opportunity→1 valid pair。该结果是确定性 eligibility/policy 门禁，不是攻击 AUC，不做显著性检验或论文图。
- 至此 Enron/PubMed/EDGAR 三套 replay 全部 passed；全局 replay valid-pair 总数为 CONTRACT_TERM=3,188、LOCATION=1,289、ORG=5,419、PERSON=291、PRODUCT=268、PROJECT_NAME=1。当前 `prepare-audit` 要求每类 90 accepted，`finalize` 要求每类全局至少 90 pairs，因此 PROJECT_NAME 仍差 89，release 必然 fail closed。
- cohort A 仅含三个数据集各 500 个普通 hash 冻结 source，未针对 PROJECT_NAME 富集。若靠 pilot 补齐，需在 1,500 source 中产生至少 89 个 valid pairs（≥5.93% 密度），而 replay 实测为 1/5,750（0.017% opportunity 密度）；直接运行 pilot 极不合理。当前暂停在 pilot 前，等待正式范围决策，禁止静默放宽门槛或查看 victim/AUC 后选规则。

### 2026-08-06：API 登录切换交接

- 因当前登录余额不足，项目暂停并准备切换 API 登录；本地 artifact/checkpoint 不受影响，无需重跑三套 replay。
- 独立交接文档已写入 `研究记录/API登录切换_工作交接_20260806.md`，记录三套 report identity、PROJECT_NAME 1/90 blocker、禁止事项、推荐范围修订、Git 脏工作树、测试状态与下一会话接管提示。
- 当前未提交 88 条工作树状态（43 modified、1 deleted、44 untracked），无 stash；未执行 commit、push、清理或长任务。`.pytest_tmp` 约 524 个目录/6.6 MB，保留待用户确认后处理。

## 2026-08-06：PROJECT_NAME diagnostic-only 正式范围修订

- 用户已确认采用 evidence-driven protocol amendment：这是三套 replay 完成后、任何 victim/AUC 运行前的正式范围修订，不是根据攻击效果调参。实体 policy/schema、提取和诊断统计仍完整支持六类 semantic 类型，既有 entity policy SHA-256=`e867112519b5ee952b740ba58f3ffec046c5a0a710297dc06d8c677cc670b00e` 与 semantic schema SHA-256=`1e50ffc451e01f85d64e5013bf4e76de5e462c5ca6ed0e445fccdb8bd9e1ffeb` 均不变。
- 新 formal scope identity=`pcv_formal_evidence_scope_v21_r1`，SHA-256=`4fe92ea49f442aedf0c29bbf280fd31a98e97686a211ee01c824a116e67154be`。正式证据仅覆盖 `CONTRACT_TERM/LOCATION/ORG/PERSON/PRODUCT`；`PROJECT_NAME` 标为 `diagnostic_only`，继续如实报告全局 1 valid pair，但不进入 90-pair coverage gate、正式审计或 release 结论。
- blind audit 由六类 600 行修订为五类 500 行：每个 formal 类型仍为 90 accepted + 10 hard negatives，用户预冻结复核仍为 60 行。release gate 只对五个 formal 类型执行全局至少 90 valid pairs；不得混入 PROJECT_NAME 定向富集样本，也不得把 diagnostic 结果表述为正式验证充分。
- 代码、scope YAML、stage/release identity 与 fail-closed 校验已实现；旧 replay report 缺少 scope 字段时仍可按原 identity 只读验证，不重写三套 replay artifact。定向 unittest 14/14、全量 unittest 367/367、284 个 Python 文件内存编译全部通过。
- cohort A pilot 仍暂停，B/C 继续密封；audit、finalize、正式扫描均未启动，release gate 尚不存在。本轮真实 API、victim、Retriever 调用新增 0。下一步须先审阅本地修订，再单独决定是否解除 cohort A pilot 暂停。

## 2026-08-07：Enron cohort A pilot source gate 失败

- 用户已明确授权启动 cohort A pilot；先执行 Enron，B/C 保持密封，PubMed/EDGAR 未启动。
- Enron cohort A 两个 250-source wave 均完成，checkpoint identity=`de9d11e97cca569b4e00786de15760eba9a86054a91ecc15bb2de43c7940c1f9`，pilot report identity=`dcb1322cbd0ee4726dc4ba5bed596e20aebfff195854b74d1a4227b1dea2607e`。scope version/hash 与当前 formal scope 一致。
- source gate 失败：49/500 eligible（9.8%），Wilson 95% 下界=7.492%，低于 Enron pilot 预注册的 50/500、10% 和 7.5% 三项门槛。type gate 通过；formal pair counts 为 CONTRACT_TERM=22、LOCATION=34、ORG=72、PERSON=51、PRODUCT=15，`PROJECT_NAME`=0 仅作 diagnostic-only。
- 两个 wave 的 `api_calls_performed=0`、`retriever_runs=0`；没有 victim、Retriever 或正式 query 调用。首次 120 秒超时的 `wave_0000_attempt_000` 保留为 partial evidence，成功重试的 `attempt_001` 与 checkpoint 为 canonical，不删除或覆盖任何 artifact。
- 按 fail-closed 协议，Enron pilot 判定为 failed 后立即停止 PubMed/EDGAR pilot、audit、finalize 和 formal scan；不得重试以碰过门槛、静默放宽阈值或修改 cohort。下一步是分析该失败是否需要新的正式协议决策。

## 2026-08-07：Enron capacity / role decision（pilot 后）

- Enron cohort A 的失败应作为 `v21_entity_policy_pilot_v1` 的冻结结果保留，不通过扩大候选池、重抽 cohort 或修改门槛追溯修复。
- 失败主要是 source-level density，而不是全局实体类型完全缺失：500 个 source 中 310 个至少有一个 fact、240 个至少有一个 valid claim，但只有 49 个达到至少三个 valid claims；其中 124 个只有一个 claim、67 个只有两个 claims。type gate 通过，formal 五类 pair 统计为 CONTRACT_TERM=22、LOCATION=34、ORG=72、PERSON=51、PRODUCT=15，PROJECT_NAME=0 仅作 diagnostic-only。
- pilot=49/500（9.8%，Wilson lower=7.492%）与 Enron replay=131/1,250（10.48%，Wilson lower=8.901%）方向一致；已有归因分析未发现 stealth、claim conversion、类型 gate 或模型退化证据。该限制应表述为 Enron 的适用覆盖率/样本效率边界。
- 扩大候选池只能改善绝对 eligible 数量和 Wilson 容量，不能保证达到原预注册的 10% eligible-rate gate。若继续 Enron，必须建立新的 protocol identity，并把 capacity study 与 v21_r1 的 applicability gate 分开报告，不能把新协议结果写成 v21_r1 通过。
- 当前推荐角色：PubMed/EDGAR 作为高密度 canonical 候选，Enron 暂作低密度压力测试/边界证据；是否保留 Enron 为正式主数据集，待新的 capacity/role protocol 冻结后再决定。
- 后续长任务执行约束：预计超过数分钟的抽样、eligibility 或 pilot 命令只提供给用户，由用户自行运行；本地代理不代跑，不启动 API、victim、Retriever、B/C、audit、finalize 或 formal scan。

### 2026-08-07：Enron v21_r2 capacity/role 协议冻结

- 新协议版本=`pcv_enron_capacity_role_v21_r2`，SHA-256=`3c8b8fb45b6b31cb265dd70d69a55e176a0eba548d451a5fb060c9866fef6b10`；机器可读配置位于 `configs/enron_capacity_role_v21_r2.yaml`。
- Enron 正式角色冻结为 `boundary_stress_test`，`primary_canonical=false`。capacity study 即使通过，也只允许边界评估，不得把 Enron 提升为主 canonical 数据集或改写 v21_r1 cohort A 的 failed 结论；capacity 失败则停止 Enron 下游工作。
- 独立 capacity study protocol=`v21_enron_capacity_study_fixed_pool_r2`：固定 35,000 candidate sources、seed=42、完整扫描、cap=5、minimum valid claims/stealth pairs=3/3、required eligible=2,250、无 fallback。按 pilot Wilson lower=7.4923547% 保守估计为 floor(35,000×lower)=2,622，较目标留 372-source 余量；旧 30,000 对应约 2,247，不再作为新 capacity study 的候选池规模。
- 新协议绑定 entity policy v21_r1、formal scope v21_r1 与 Enron pilot report identity=`dcb1322...2607e`。执行开关冻结为 `enabled=false`，长任务 owner 为用户，API/victim/Retriever 全部禁止；当前没有可运行的新 capacity-study 入口或命令。
- 新增 fail-closed loader 和 5 个定向测试，验证角色边界、旧失败不可改写、30k 决策漂移、metadata 漂移和 pilot report 零调用证据。`mia_model` 解释器确认正确，5/5 tests、YAML、内存编译与 `git diff --check` 通过。

### 2026-08-07：Enron v21_r2 35k 隔离 runner 接入

- 新增 `configs/data_config_v21_enron_capacity_r2.yaml` 与 `configs/eligibility_scan_v21_enron_capacity_r2.yaml`，复用只读的 62,384-source processed universe，不重跑 sampling/Step 01。processed JSONL SHA-256=`47ef7d2fee45d519618dddc9a1be4be6aafcf69d862cd64f35a109081419a19e`，manifest SHA-256=`d4dbecb2c7c842485b230c9ecb50a8f297413292d48e00754080ee0854079aa6`；新输出仅允许写入 `artifacts/v21/enron_capacity_r2/eligibility/cap_5/enron`。
- `src/prepare/eligibility_scan.py` 已接入 `v21_enron_capacity_study_fixed_pool_r2`：严格要求 dataset=enron、35,000-source fixed pool、cap=5、完整扫描、minimum claims/pairs=3/3、required=2,250；30k、字段漂移、processed/output CLI override、上游 SHA/manifest/path 漂移均 fail closed。
- 创建或恢复 plan 必须显式提供 `--manual-user-owned-capacity-run`；该标志对其他协议无效。plan、checkpoint、query/claim/stealth manifest 与 finalization 均绑定 `boundary_stress_test`、`primary_canonical=false` 和 v21_r1 prior failure；capacity manifest 被 `validate_formal_eligibility_manifest` 显式拒绝，不能进入 formal promotion。
- 新增 8 个 runner 测试；与 5 个 role 测试合计 13/13 通过，原 eligibility runner 22/22 回归通过。4 个相关 Python 文件内存编译、3 份 YAML 解析与 `git diff --check` 均通过。解释器为 `D:\python\anaconda\envs\mia_model\python.exe`。
- 用户首次运行 plan-only 命令时，上游 SHA 门禁在创建输出目录前正确拒绝：capacity YAML 与 runner preregistration 常量误录了 processed JSONL SHA；实际文件 SHA 为 `47ef7d2fee45d519618dddc9a1be4be6aafcf69d862cd64f35a109081419a19e`，manifest SHA 仍为 `d4dbecb2...079aa6`，文件时间与内容没有漂移。两处误值已修正并增加精确常量回归测试；实际文件只读 upstream preflight 通过，capacity 输出目录仍不存在。
- 本轮没有启动 35k plan/scan、API、victim、Retriever、PubMed/EDGAR pilot、B/C、audit、finalize 或 formal scan，旧 30k 配置/artifact 未修改。下一步由用户先冻结 capacity plan，再使用 `--resume --execute --max-new-waves 1` 逐 wave 运行；任何失败或漂移均停止并保留现场。

### 2026-08-07：Enron v21_r2 capacity plan 冻结

- 用户运行 plan-only 命令成功，状态=`preregistered_not_executed`，scan plan SHA-256=`c8fcd26c48b40d4c8bf7da31d8f7d48ec49fbd0bc33d54341688fb57b19ce983`。source universe=62,384，固定 candidate sources=35,000，shortfall=0，wave size=250，target eligible=2,250。
- 独立流式复核重新计算 plan identity 并与冻结 SHA 完全一致；source order 恰有 35,000 个唯一 source，candidate benchmark 含 56,834 probe rows、覆盖恰好同一组 35,000 source，source-order/candidate 文件哈希均与 plan 绑定值一致。
- plan 继续绑定 `boundary_stress_test`、`primary_canonical=false`、prior applicability=`failed` 与 manual user-owned execution acknowledgement。当前 checkpoints/waves/finalization/prediction cache 均不存在，API calls=0、Retriever runs=0；这只是 capacity plan 冻结，不改变 v21_r1 failed，也不构成 formal promotion。
- 下一步仅由用户运行一个 250-source wave：使用相同配置加 `--resume --execute --max-new-waves 1`。完成后先独立复核 checkpoint 与 wave manifest，再决定是否继续下一 wave；禁止并行、`--force`、路径 override 或启动其他数据集/下游阶段。

### 2026-08-07：Enron v21_r2 capacity wave 1

- 用户完成第一个 250-source wave，写入 `checkpoint_0001.json`；checkpoint identity=`32758bd731834a69d377cc458f3d0a3e2c2ff1410a54b94f25cb8fac89b38e05`，wave identity=`aad61d97f041faf18b9fc35577fc4b81e40a9a7751bb8082978b286a0ea313d8`，唯一 attempt=`wave_0000_attempt_000`。
- 本波处理 250 source / 417 probe docs，得到 360 facts、233 paired claims、466 queries、29 query-eligible source；描述性 eligible rate=11.6%，Wilson 95% lower=8.1992%。35k target 对应累计最低比例 6.4286%，但协议要求扫描完整 35,000 source，本波不能提前判定 capacity passed。
- 独立复核通过 checkpoint identity、前驱链、wave manifest 与全部十类输出哈希；source boundary=0:250，`boundary_stress_test`、`primary_canonical=false`、prior failed 均保持。API calls=0、Retriever runs=0，尚无 finalization 或 query eligibility canonical artifact；一个完成 wave 的本地 prediction cache 按 runner 设计保留到最终清理。
- 当前进度=1/140 waves，scanned=250/35,000，eligible=29/2,250。下一步仍只允许用户运行一个 wave，完成后逐 checkpoint 复核；不得依据早期合格率提前停止或启动下游阶段。

### 2026-08-08：Enron v21_r2 capacity wave 95 复核

- 用户已完成并暂停于 `checkpoint_0095.json`；独立 `load_latest_checkpoint` 复核通过 95 个连续 checkpoint 与前驱 hash 链，并复核最新 completed wave 的 manifest 与全部输出哈希。checkpoint identity=`5a005c18d34e22c74ea03818fb5ba6e8e33caa1acfa7656bbc828c70d302713e`，文件 SHA-256=`33ebbb4294ad18e815e244089c117f560e3cc3438f234d2d2a7c38c65f011c53`。
- 当前累计扫描 `23,750/35,000` source，累计 eligible=`2,558`，描述性 rate=`10.7705%`，Wilson 95% 下界=`10.3826%`；已超过 `2,250` target，但 `scan_full_candidate_pool=true`，因此不能提前 finalize 或停止，仍须完成全池扫描。
- 最新完成 wave 的 zero-based `wave_index=94`（对应第 95 个 wave），source boundary=`23,500:23,750`，eligible=`37`；输出为 benchmark 428 行、facts 394 行、claims 287 行、queries 574 行、stealth accepted 222 行、stealth rejected 352 行。wave identity=`08b2794f98206f0456f65111b7d797d3584d07a0fae5bb92f736eaa3eed5177c`，wave manifest SHA-256=`7ce6e52d876bd8d5b6dbb690c08b4f5ece11eac425fea6704b5b77e590349251`。
- 角色与边界未漂移：`boundary_stress_test`、`primary_canonical=false`、prior applicability=`failed`；checkpoint 与 wave 的 API calls、Retriever runs 均为 0。输出目录目前只有 checkpoints、waves、prediction_cache 与 scan plan/order/benchmark，没有 finalization/report 产物。
- 剩余 `45` 个 wave、`11,250` 个 source。下一步仍只允许用户以 `--resume --execute --max-new-waves 1` 逐 wave 续跑；每个 wave 先由本地独立复核，再决定下一次运行。PubMed/EDGAR pilot、B/C、audit、finalize、formal scan、API、victim、Retriever 继续禁止。

### 2026-08-09：Enron v21_r2 capacity 全池完成并通过

- 用户已完成固定池全部 `140/140` waves；最终 checkpoint=`checkpoint_0140.json`，checkpoint identity=`60fb2fd2e8781e98e31ce5e35a057a783cf890e7b63b34a1b39ef890c20635af`，文件 SHA-256=`82a2f7d3962185aef21eb9abb1611fbbf63dd18de2eabbd28beb5666bd25fbe1`。独立 `load_latest_checkpoint` 复核通过 140 个连续 checkpoint、前驱 hash 链、完整 35,000-source prefix 与终止原因 `fixed_candidate_pool_exhausted_with_required_capacity`。
- 最终 query-eligible=`3,786/35,000`，rate=`10.8171%`，Wilson 95% 下界=`10.4960%`；超过 required target 2,250 共 1,536 source，也超过预注册保守期望 2,622 共 1,164 source。claim-eligible=`3,819`，从 claim 到 query eligibility 仅损失 33 source（占 claim-eligible 0.8641%）。
- `enron_finalization_manifest.json` 身份与九类聚合输出文件哈希全部独立复核通过；finalization identity=`ee11296e88656f2c1c39aa7919401151b1f46e9b9636396380daf16c897ea0dd`，query eligibility hash=`7f3be4e292967c13630cd27816b8cb9d92a8443323789b9b29301dfbac3cdd9a`。`capacity_status=passed`，API calls=0、Retriever runs=0。
- 第 120 个 wave（zero-based `wave_index=119`）首次 `attempt_000` 因 GLiNER2 CUDA OOM 在 batch 拆分到 1 后 fail closed；失败 attempt 保留，partial prediction cache 用于同一身份续跑后已按终态清理协议删除。进程重启、显存释放后以同一 checkpoint/config 创建 `attempt_001` 成功续跑，没有降低 batch/config、修改 source、使用 CPU fallback、覆盖失败证据或改写身份。
- 结论边界保持不变：Enron 仍为 `boundary_stress_test`、`primary_canonical=false`，capacity pass 的唯一效果是 `permits_boundary_evaluation_only`。v21_r1 cohort A 的 49/500 failed 不被改写，Enron 不提升为 primary canonical，也不能把本产物送入 formal promotion。
- Enron capacity 阶段已结束，不再运行 Enron wave。下一步仅进入协议决策：是否单独授权 PubMed cohort A；EDGAR cohort A 必须等待 PubMed 独立 gate，B/C、audit、release finalize、formal scan、API、victim、Retriever 继续禁止。

### 2026-08-09：第二次 API 登录切换交接

- 用户准备切换登录账号；新建自包含交接文档 `研究记录/API登录切换_工作交接_20260809.md`，冻结三套 replay、PROJECT_NAME diagnostic-only、Enron pilot failed、Enron capacity passed、OOM 续跑证据、当前禁止事项和下一步授权边界。
- 用户已还原 `研究记录/API登录切换_工作交接_20260806.md`；该文件继续作为 2026-08-06 历史快照保留，不覆盖。当前状态与接管优先以 2026-08-09 交接、两份总表和机器可读 artifact 为准。
- 接管后的唯一待决策事项是是否单独授权 PubMed cohort A；账号切换不构成启动授权。EDGAR cohort A、B/C、audit、release finalize、formal scan、API、victim、Retriever 和正式 query 均继续禁止。
- Git 脏工作树当前为 96 条（43 modified、1 deleted、52 untracked），branch=`codex/feat-pipeline-complete-v20-preflight-remediation`，stash 为空、upstream unpushed commits=0；未 reset、checkout、stash、commit、push、清理或覆盖。
- `.pytest_tmp` 当前约 550 个顶层条目、6,990,945 bytes，继续保留。最近一次完整代码回归仍是 2026-08-06 的 367/367 unittest 与 284 文件内存编译；本次只新增交接文档并执行只读状态核验，没有重新声称全量测试已运行。

### 2026-08-09：单独授权 PubMed cohort A

- 用户已明确授权仅启动 PubMed cohort A；该授权不覆盖 EDGAR cohort A、B/C、audit、release finalize、formal scan、API、victim、Retriever 或正式 query。
- 启动前只读预检通过：冻结 pilot plan identity=`e43a1c4c4fa2d53db439993a5bd24d6878485078eea27805d0e337bd91c920c1`，cohort A hash=`a14611d0f84d6852e88a4aea37f82a7668d6889d1d58d73384601fcbde691e43`；PubMed cohort A 含 500 个互异 source，source-order hash=`abdfb5a3ce2584420516ac8cb83bb35f05ea7061a2088d8b3e98f491e7c36b81`，candidate benchmark SHA-256=`f666132b9842c2758cbc3d1134f8e3f17c65591c916d4f7e50b5689fa240e0eb` 且实际文件匹配。
- `artifacts/v21/entity_policy_r1/pilots/cohort_A/pubmed/` 当前不存在，因此没有 PubMed stage plan、checkpoint、attempt 或 report；首个命令将从冻结 cohort 的第一个 250-source wave 开始，并在创建 stage plan 时绑定当前五类 formal scope、entity policy、semantic identity、runtime tree 与代码身份。
- 长任务继续由用户运行，只允许 `--cohort A --resume --max-new-waves 1`；首个 wave 完成后必须先独立复核 checkpoint、wave manifest、source/type gate 和零 API/Retriever 计数，再决定是否运行第二个 wave。禁止 `--force`、路径 override、并行运行或越级启动下游阶段。

### 2026-08-09：PubMed cohort A wave 1 复核

- 用户完成首个 250-source wave，状态按预期暂停于 1/2；stage plan identity=`632dd3aa9f07ae6ca6820c67715e173c3e568c0da666ae07e9d7b6999bfdc8de`，checkpoint identity=`bef73311fdbef264b3e81ee50f824ca307389a021bfa641c44bf088c5c83285c`，wave identity=`bf6d14d1372f91428c7e1f0fa75a51fc9a7a2a6213b681e189b5e983977f1375`，wave manifest SHA-256=`3fd76e5d7017193befc6fe93324db054280206ffc61583870b34d2951d9f056d`。
- 独立只读验证通过 stage plan、当前 runtime tree、冻结 pilot plan/cohort、checkpoint identity、source boundary=`0:250`、wave manifest 与十类输出文件哈希；唯一 attempt 为 `wave_0000_attempt_000`，没有 identity drift 或缺失产物。
- 本波 1,184 candidate rows，claim-eligible=224，query-eligible=218/250（87.2%，Wilson 95% lower=82.4887%）。五类 formal coverage 均通过：CONTRACT_TERM 26→7（minimum 3）、LOCATION 101→91（3）、ORG 262→166（6）、PERSON 14→13（0）、PRODUCT 322→13（7）；PROJECT_NAME 0→0 仅作 diagnostic-only。
- API calls=0、Retriever runs=0。第一波只提供描述性证据，最终 PubMed pilot gate 仍须完成固定 500 source 后统一裁决；当前结果足以允许使用同一 `--resume --max-new-waves 1` 命令运行第二波，完成前仍不得启动 EDGAR 或任何下游阶段。

### 2026-08-09：PubMed cohort A 正式通过

- 用户完成第二个也是最后一个 250-source wave；2/2 checkpoint identity=`ca8db06a6d3e6da4fd7d906fa666114b54650ce1566024b1bda6f10ee9c17cca`，第二波 identity=`4bee0cfeb20de6aaf2d7cd15796f06b5d9f842148014e48feb39776e07889731`，wave manifest SHA-256=`f979b2b297c3706031c7a449cef0d0b02d8de25add06eb8715990c322c1efbc5`。
- `pilot_report.json` 已由正式 validator 和独立内存重算共同验证，report identity=`ff79c46e7dd89d81c288e9703132faacd1ac57e6cd6c50ea6742cbd4dae95021`；两波 source boundary 恰为 `0:250`、`250:500`，按冻结顺序覆盖 cohort A 全部 500 个 source，stage plan/runtime、checkpoint、两波 manifest 与全部输出哈希均有效。
- PubMed source gate passed：query-eligible=443/500（88.6%），Wilson 95% lower=85.5150%，failure reasons 为空。五类 formal coverage 全部通过：CONTRACT_TERM 73→24（minimum 3）、LOCATION 203→190（5）、ORG 538→339（11）、PERSON 26→25（3）、PRODUCT 704→37（15）；PROJECT_NAME 0→0 继续只作 diagnostic-only。
- API calls=0、Retriever runs=0。该结果冻结为 PubMed cohort A eligibility/policy pilot passed，不是 victim AUC，也不构成 EDGAR、B/C、audit、release finalize、formal scan、API、victim、Retriever 或正式 query 的自动启动授权。
- 下一步唯一协议决策是是否单独授权 EDGAR cohort A；只有 EDGAR 完成独立 gate 后，才可考虑 audit/release 流程。

### 2026-08-09：单独授权 EDGAR cohort A

- 用户已明确授权仅启动 EDGAR cohort A；Enron 维持 boundary stress test、PubMed cohort A 维持 passed，该授权不覆盖 B/C、audit、release finalize、formal scan、API、victim、Retriever 或正式 query。
- 启动前只读预检通过：pilot plan identity=`e43a1c4c4fa2d53db439993a5bd24d6878485078eea27805d0e337bd91c920c1`，cohort A hash=`a14611d0f84d6852e88a4aea37f82a7668d6889d1d58d73384601fcbde691e43`；EDGAR cohort A 含 500 个互异 source，source-order hash=`4a840897ed7f6f484fac11d60f943cfbd024d042e1d6fc3e8c92a38c06cee9e8`，candidate benchmark SHA-256=`835de4503c38d7e0586c8933da38b3a0e590d21371faa10a39478dcde832ad89` 且实际文件匹配。
- formal scope 仍为 `pcv_formal_evidence_scope_v21_r1` / `4fe92ea49f442aedf0c29bbf280fd31a98e97686a211ee01c824a116e67154be`，正式五类不变，PROJECT_NAME 继续 diagnostic-only；唯一 Python 环境与 CUDA 预检通过。
- `artifacts/v21/entity_policy_r1/pilots/cohort_A/edgar/` 当前不存在，无 stage plan、checkpoint、attempt 或 report。长任务由用户运行，只允许首个 `--cohort A --resume --max-new-waves 1` 的 250-source wave；完成后先独立核验，再决定第二波。禁止 `--force`、路径 override、并行执行或越级启动下游阶段。

### 2026-08-10：EDGAR cohort A 正式通过

- 用户已完成 EDGAR cohort A 固定 500 source 的 2/2 waves；checkpoint identity=`2b4c62e2d4b387a1d0b991eb32b3084d04430e43fc8e7fa2c330a92d15cdd99e`。两波 identity 分别为 `085eb52e03b7495825bc5d76b71348e5efac5c25723da73701bef334a219a63f`、`05c423e5f5bbb688a0557ffadbee5157c1482d109abf7532472f3148a5f0c9ed`；仅存在 `wave_0000_attempt_000` 与 `wave_0001_attempt_000`，无额外失败或重试 attempt。
- `pilot_report.json` 已由正式 validator 和独立内存重算共同验证，report identity=`9a125e6a3a7da44ea9342e88dbfbc219357c40eaaa0b46211f14c6541ceba7c5`；两波 source boundary 恰为 `0:250`、`250:500`，按冻结顺序精确覆盖全部 cohort A，stage plan/runtime、checkpoint、两波 manifest 与全部输出哈希均有效。
- EDGAR source gate passed：query-eligible=471/500（94.2%），Wilson 95% lower=91.7943%，failure reasons 为空。五类 formal coverage 全通过：CONTRACT_TERM 946→461（minimum 19）、LOCATION 122→110（3）、ORG 1,128→653（20）、PERSON 19→18（0）、PRODUCT 246→22（5）；PROJECT_NAME 0→0 继续只作 diagnostic-only。
- API calls=0、Retriever runs=0。EDGAR cohort A 现冻结为 passed；PubMed cohort A 同为 passed，Enron v21_r1 cohort A 仍为 49/500 failed 且仅允许 boundary evaluation。本轮授权不包含 B/C、audit、release finalize、formal scan、API、victim、Retriever 或正式 query。
- 下一步应先进行 audit/release 输入与数据集角色的只读预检，再由用户单独决定是否授权准备五类 500-row blind audit；不得因 EDGAR passed 自动越级。

### 2026-08-10：release gate 数据集角色接线阻断

- EDGAR/PubMed cohort A 通过后的只读预检发现：当前 `freeze_release_gate` 仍硬编码要求 `edgar/enron/pubmed` 三份 pilot report 数据集覆盖完全一致且全部 `status=passed`；仓库中没有把已冻结的 Enron `boundary_stress_test`、`primary_canonical=false`、`permits_boundary_evaluation_only` 角色接入该 gate。
- 因此现状下省略 Enron pilot 会固定触发 `pilot_dataset_coverage_mismatch`，传入不可改写的 Enron 49/500 failed report 会固定触发 `pilot_enron_failed`。当前 release gate 结构上不可能 passed；不得通过删除 Enron 失败证据、伪造 passed、降低 gate 或手工改 report 绕过。
- 本轮没有生成 blind audit、audit labels/report 或 release artifact。直接准备 500-row audit 会产生尚不能进入 finalize 的孤立产物，因此继续停止在 audit 前。
- 下一步必须先由用户授权实现既有角色决策的版本化接线：正式主数据集为 EDGAR/PubMed，Enron 以绑定的 failed pilot + passed capacity finalization 作为 boundary evidence；release gate 需显式验证两类角色和 exact identity，formal scan 只允许主数据集，Enron 仅进入独立 boundary evaluation。该接线是对 2026-08-07 已冻结角色语义的实现闭环，不得依据 victim/AUC 调整。

### 2026-08-10：release gate 数据集角色接线完成

- 用户已明确授权修复角色接线。新增冻结配置 `configs/formal_dataset_role_scope_v21_r1.yaml`，协议=`pcv_formal_dataset_role_scope_v21_r1`，scope SHA-256=`90a6a96e2e85880568c887e92863bf63c4d24341ab5148aa3c7afd389e2e4fdf`。EDGAR/PubMed 固定为 `primary_canonical`，Enron 固定为 `boundary_evaluation`；该修订只实现 2026-08-07 已冻结的角色裁决，不依据 victim 响应、Retriever 指标或攻击 AUC。
- release gate 升级为 `v21_entity_policy_release_gate_v3_dataset_roles_r1`：仍要求三套 replay 和三套 cohort A pilot 完整存在且 exact report identity 匹配，但按角色解释状态。EDGAR/PubMed pilot 必须 passed；Enron pilot 必须保持 immutable failed，且同时逐哈希验证 35,000-source capacity finalization、checkpoint、九类输出和 `3,786/35,000` query eligibility。Enron capacity pass 仍只允许 boundary evaluation，不能改写 49/500 failed。
- 正式证据计数已分区：`formal_semantic_valid_pairs` 只汇总 EDGAR/PubMed primary 证据；Enron 单独进入 `boundary_semantic_valid_pairs`。blind audit 协议升级为 `v21_entity_policy_audit_v3_dataset_roles_r1`，准备、评估及 release 复核均拒绝 Enron 行；`PROJECT_NAME` 继续保留 schema/诊断统计但不进入五类 formal audit。
- formal scan 协议升级为 `v21_entity_policy_full_rescan_v2_dataset_roles_r1`，只允许 EDGAR/PubMed，并在 scan plan identity 中绑定 dataset-role scope version/hash/`primary_canonical`。旧 Enron formal-scan YAML 改为不可执行的 boundary-only tombstone；任何试图以正式协议运行 Enron 都会 fail closed。
- 真实冻结证据只读核验通过：六份 replay/pilot role/status/identity 无失败；Enron finalization/checkpoint/九类输出逐哈希通过，仍为 `primary_canonical=false`。相关内存语法检查通过；定向测试 8/8，Enron capacity 与 v21 回归 19/19，总计 27/27。未运行全量 unittest，未生成 audit、release gate 或 formal scan artifact，API/victim/Retriever/正式 query 新增调用均为 0。
- 下一步只能由用户单独决定是否授权准备五类 500-row blind audit。此次接线授权不自动授权 audit、release finalize、formal scan、B/C、API、victim、Retriever 或正式 query。

### 2026-08-10：capacity-qualified primary 主表修订（覆盖上一节角色结论）

- 用户明确要求 EDGAR、Enron、PubMed 全部进入论文主表。本节取代上一节“Enron 仅 boundary evaluation、不得进入主表”的后续适用结论，但不删除或改写历史证据：Enron cohort A 仍固定为 `49/500`、`status=failed`，旧 35,000-source capacity artifact 仍保持 `boundary_stress_test`、`primary_canonical=false`。
- 新 dataset-role scope=`pcv_formal_dataset_role_scope_v21_r2_capacity_qualified_primary`，SHA-256=`65dff74de67495f6afc9aa2c5f9f4d1d41a84e8f2125e01e7ea00a04bdef0450`。EDGAR/PubMed 为 `standard_primary`，Enron 为 `capacity_qualified_primary`；`main_table_datasets` 与 audit 范围均为三者。
- Enron 进入主表的依据不是把 pilot 改成 passed，而是独立 capacity qualification：固定池 35,000 source、3,786 query-eligible、capacity=`passed`。正式 promotion 只在 release gate 通过后，按 `selection_seed=42` 与 `sha256(scope_version,selection_seed,dataset,source_key)` 从 3,786 个冻结合格源确定性选择 2,250 个；protocol=`v21_enron_capacity_qualified_primary_promotion_v1`。
- 只读预演得到 `selected_source_keys_sha256=e6e0a75507db6c83b9ae1517a99a89eaa0de751b69390057da2e74937df6f4eb`、`whitelist_hash=3edb7e3d4fe54299e5386ed25f8c1d1ecfacce2e18fe96dbb7e057035e1b77da`。尚未写 promotion artifact；生成时仍须绑定实际 passed release gate 与当时 runtime tree。
- formal evidence scope 升级为 `pcv_formal_evidence_scope_v21_r2_dataset_stratified`，SHA-256=`6fdc6ef950b0d1abed43fd2395657fa9ec814fc0eebab181b489c159adce778e`。正式类型仍为 CONTRACT_TERM、LOCATION、ORG、PERSON、PRODUCT；PROJECT_NAME 继续 diagnostic-only。
- blind audit 从旧 500 行升级为 600 行：三数据集 × 五类型 ×（36 accepted + 4 hard negatives）=600；每个 dataset×type 用户复核 4 条，共 60 条。每个 cell 至少 35/36 accepted passes、rate≥0.96、Wilson 95% lower≥0.85；每类跨数据集至少 104/108、rate≥0.96、Wilson lower≥0.90。
- 六份冻结 report 的 exact role/status/identity 只读复核为零失败。三数据集五类 replay+pilot pair 总数为：EDGAR `{CONTRACT_TERM:3547, LOCATION:924, ORG:5218, PERSON:140, PRODUCT:163}`；Enron `{CONTRACT_TERM:90, LOCATION:106, ORG:228, PERSON:174, PRODUCT:38}`；PubMed `{CONTRACT_TERM:58, LOCATION:593, ORG:1037, PERSON:71, PRODUCT:141}`，所有 dataset×type 均不少于 36。
- release/audit/formal-scan protocol 分别升级为 `v21_entity_policy_release_gate_v4_capacity_qualified_primary_r1`、`v21_entity_policy_audit_v4_dataset_stratified_r1`、`v21_entity_policy_full_rescan_v3_capacity_qualified_primary_r1`。EDGAR/PubMed 走 fresh formal scan；Enron 不重跑 35,000-source scan，而在 release 通过后生成独立 promotion manifest，再由 split 阶段完整验证。
- 论文必须报告三数据集逐项结果、三数据集 macro，以及仅 EDGAR/PubMed 的 standard-primary sensitivity；必须披露 Enron cohort A failed、capacity yield 3,786/35,000、selection protocol 与 `capacity_qualified_primary` 限定，不能把 Enron 表述为通过原 applicability pilot。
- 本轮未生成 600-row audit、release gate、Enron promotion 或 formal scan artifact，API/victim/Retriever/正式 query 调用均为 0。定向回归 43/43；9 个 Python 文件内存编译、7 个 YAML 解析与 CLI help 通过；未运行全量 unittest。

### 2026-08-10：600-row dataset-stratified blind audit 已准备

- 用户已单独授权 `prepare-audit`。在分支 `codex/feat-pcv-mia-v21-capacity-primary`、commit=`2f3b541` 上，输入三套 exact replay 与三套 cohort A pilot（包括 Enron immutable `failed` report），role failures=`[]`；输出目录在执行前不存在。
- audit status=`prepared`，protocol=`v21_entity_policy_audit_v4_dataset_stratified_r1`，manifest SHA-256=`d139849a27332edfbe2935a7b5705a59a2b746871f0faef9279b7ad24009a283`，audit identity=`aa15ca5b8d1ba8892711d059bced44b90e0785286afc42710462448fd567a698`。
- blinded SHA-256=`d8d89f5fc2ac6d48a3d5d0ae0d99f03bc3c7e607ee804ea153b82a72b931d77d`；key SHA-256=`78f18c0b9dbafec86161206dfa3fe03465c30d1b8e8d27a16cca28d332354177`；required user-review IDs SHA-256=`b2275b3c29288d1b3e6dd359c17e1ce5fb1d08bc56fb2ec6d9dbc1aaf0a3d1a3`。
- 独立结构验证：600 rows/600 unique IDs，EDGAR/Enron/PubMed 各 200；五个 formal 类型各 120；15 个 dataset×type cell 均为 40；60 个冻结 user-review IDs 在每个 cell 恰好 4。PROJECT_NAME rows=0，blinded 中 forbidden key/leakage rows=0，预填 model judgment rows=0。
- 为维持 blindness，本轮没有打开、展示或解析 key 内容；只验证 key 文件行数=600 与 SHA-256。尚未生成 assistant labels、user review、audit report 或 release gate；未运行 finalize、promotion、formal scan、API、victim、Retriever 或正式 query。
- 下一步是单独决定是否授权生成 600 条 assistant blind labels；用户的 60 条冻结复核需使用 manifest 中预注册 IDs。两者完成前不得运行 `finalize`。

### 2026-08-10：assistant blind labeling 因 subtype sentinel 泄漏暂停

- 用户授权生成 600-row assistant labels 后，在读取 key 前对 blinded 第一 cell 开始人工审核，发现 wrong-type hard negative 的内部构造标记 `semantic_subtype=mismatched_donor_type` 被直接写入 blinded row。该字段等价于暴露负例身份，现有 audit 不能作为有效盲审证据。
- 只读全量确认泄漏 30/600 行，15 个 dataset×type cell 各 2 行；另有 30 行 true/counterfactual claim 相同，这是可由标注内容本身判断的 specificity case，不属于隐藏元数据泄漏。根因位于 `entity_policy_validation.py`：hard-negative builder 写 sentinel，blinded builder 又回退公开 `semantic_subtype`。
- 已立即 fail closed：未读取或解析 key，未生成 assistant labels，未运行 evaluate/finalize。现有 r2 audit 三文件和原 hash 全部保留，不覆盖、不删除；其状态在研究解释上为 `compromised_blind_subtype_leak`，不得进入 release。
- 推荐修复必须使用新 audit protocol/identity 和隔离输出：从所有 blinded rows 删除 machine-generated `semantic_subtype`，增加禁止 sentinel/negative metadata 的回归测试；协议字符串变化后重新确定性抽样 600 rows，使已查看的旧 cell 不进入新盲审身份。需用户单独授权后实施。

### 2026-08-10：blind subtype 泄漏已修复并重生 r3 audit

- 用户已单独授权修复并重生 audit。本轮没有延续旧 labels 授权，也没有读取/解析 key 内容；未生成 assistant labels、user review、audit report 或 release gate。
- 根因按 schema 级修复：所有 blinded rows 一律删除 machine-generated `semantic_subtype`；新增字段白名单、内部字段/`mismatched_donor_type` 禁止值、空标签门禁。`prepare`、`evaluate`、release retained-evidence validation 三处均 fail closed，不能靠重算 manifest hash 绕过泄漏检查。
- 新 audit protocol=`v21_entity_policy_audit_v5_blind_subtype_redaction_r1`；blinded schema=`v21_entity_policy_audit_blinded_v2_no_machine_subtype`，schema SHA-256=`7cf97e74f99e93d241ca5fcc7b3788a67c3c94860d6f77b9ba14ceeb6bc4f0a4`。默认 release workspace 隔离到 `artifacts/v21/entity_policy_r3/`；r2 compromised artifact 不覆盖、不删除。
- 新 r3 audit status=`prepared`，manifest SHA-256=`0ea92ae2458f443386a0d2a80f1769c76c165e5be1edd4e1c7bccd09faa2cd60`，audit identity=`e7dc2324af3812bc4cf6d0fb2188303e503a234ee0d7e0327dcc1e28934b5d43`；blinded/key SHA-256 分别为 `0be539eadfa57aeb2c3c6e58d6eba0c0a2d14d04a025c606c3211b76d0708a81`、`ca577b1d145bb22b93f3b07605a3fbeb5dc1210c805f51b9d143937d196b9952`；新 user-review ID-list hash=`712d2b51d0a743dec4e1179cd9c3c121777bd7dfcfe4171353eac53b67cff868`。
- 独立 blinded-only 验证：600/600 unique IDs，EDGAR/Enron/PubMed 各 200，五类各 120，15 cells 均 40；字段 schema 100% 一致，sentinel rows=0、prefilled rows=0。新旧内容有 149 条重叠，这是 Enron 等有限冻结 accepted pool 下的正常重采样；关键的旧 30 条已泄漏 hard negative 与新 audit 重叠为 0，且新旧 audit IDs 因协议变化全部重新绑定。
- r2 三文件复核仍为原哈希：blinded=`d8d89f5fc2ac6d48a3d5d0ae0d99f03bc3c7e607ee804ea153b82a72b931d77d`、key=`78f18c0b9dbafec86161206dfa3fe03465c30d1b8e8d27a16cca28d332354177`、manifest=`d139849a27332edfbe2935a7b5705a59a2b746871f0faef9279b7ad24009a283`。
- 验证完成：31/31 相关 unittest、5/5 Python 内存编译、CLI help 通过；普通 `py_compile` 仅因既有 `__pycache__` Windows 权限被拒，已按仓库约定用不写缓存的验证替代。本轮 API/victim/Retriever/正式 query 调用均为 0。
- 下一步必须由用户重新单独授权 r3 的 600-row assistant blind labeling；旧 r2 labels 授权不跨 audit identity 继承。label/review 完成前继续禁止 evaluate/finalize、promotion 和 formal scan。

### 2026-08-10：r3 600-row assistant blind labels 已完成

- 用户重新单独授权 r3 assistant blind labeling。本轮严格只读取 r3 manifest 与 blinded rows；key 内容未读取、解析或展示，未运行 evaluate/finalize，也未调用 API、victim、Retriever 或正式 query。
- 在写 labels 前冻结逐 ID annotation plan：protocol=`v21_entity_policy_assistant_blind_label_plan_v1`，plan SHA-256=`1a5b20093ce6f682430639ec6ae34160d9ce34f4ca0d4e2d41d897b481290725`，绑定 audit identity=`e7dc2324af3812bc4cf6d0fb2188303e503a234ee0d7e0327dcc1e28934b5d43`、blinded SHA-256=`0be539eadfa57aeb2c3c6e58d6eba0c0a2d14d04a025c606c3211b76d0708a81` 与 schema SHA-256=`7cf97e74f99e93d241ca5fcc7b3788a67c3c94860d6f77b9ba14ceeb6bc4f0a4`；没有按每 cell 预期正负数量倒推标签。
- 600/600 labels 完整，unique IDs=600，15 个 dataset×type cell 均 40；assistant judgments 为 pass=371、fail=225、uncertain=4。可见文本中的 30 条 true/counterfactual 完全相同行全部独立标为 fail；reason 计数为 declared-type=176、subtype=22、unchanged=30、insufficient-evidence=4（原因可重叠）。这些是 blinded-side judgment 分布，不是与 key 对照后的 audit 结果。
- labels SHA-256=`0f4736b2e54e498092a77c4e7645d5266abb8c916fd8f95420b503f64b2813b5`；labels manifest SHA-256=`136531e52bf4fd433c790e9980f6715d3146fb1e06b3c9f319b4b1d754b65cf3`；labels identity=`db1bfe7eda7aa0979274dfee851270e7d9f760731d1734f06f75fb94fa7c9db3`。
- 四条 uncertain IDs 为 `3c6f8c0e77917ca6a930bae1`、`82f638d50af04ba93b7de628`、`ae3fa1ad93ec673401c94f83`、`d737034c1b6977fdfcb05a60`。其中仅 `d737034c1b6977fdfcb05a60` 已包含在冻结 60-ID user-review sample；要满足 `uncertain_rows_not_fully_reviewed` 门禁，用户复核必须覆盖冻结 60 条再加另外 3 条，共 63 个唯一 ID。
- 独立 labels-only 核验 problems=`[]`：ID 集与 blinded 完全一致、judgment schema 合法、pass/fail reason 约束通过、unchanged 规则 30/30、cell size=40；audit manifest/blinded 原哈希保持不变。
- 下一步是准备不含 key/expected decision 的 63-row user-review 模板并由用户本人填写 `human_judgment`。用户 review 完成前不得读取 key 或运行 evaluate/finalize；本次 labels 授权不自动授权后续阶段。

### 2026-08-10：63-row blind human-review template 已准备

- 用户已单独授权准备模板。本轮以 r3 audit manifest、blinded JSONL 和 assistant-labels manifest 为唯一选择输入；没有读取 key 内容，也没有把 assistant judgment、expected decision、hard-negative reason、semantic subtype 或 uncertain scope 标记写入模板行。
- 模板由冻结 60 个 user-review IDs 加 3 个不重复的 assistant-uncertain 补审 ID 构成，共 63/63 unique rows；冻结 60 行仍覆盖 15 个 dataset×type cell、每 cell 恰好 4 行，全部 4 个 uncertain ID 均已纳入。模板行采用与判断无关的确定性哈希顺序，不标识哪 3 行属于补审。
- 输出 `artifacts/v21/entity_policy_r3/audit/entity_policy_audit_human_review_template.jsonl`，SHA-256=`bf71aaea68baf4eaa8e34ce6fdad99a85362b6399af7bacf053103b0ee3d4d3a`；template manifest SHA-256=`d1ab00e2f6467d017daa61f174a035916ff1dfc81f3f3b9c467eadbf59464fdb`，template identity=`6d677f1d2319c65b8db42380d40dbcac3f29e855cb66e715c05081dfb4b90feb`。
- 独立验证 passed：63 rows、63 unique IDs、0 个预填 human judgment、forbidden/assistant scope fields=0，模板 observable 字段逐项等于原 blinded rows；audit manifest、blinded 与 assistant-labels manifest 原哈希均未漂移。本轮 API/victim/Retriever/正式 query 调用为 0，evaluate/finalize 未运行。
- 下一步只能由用户本人逐行填写 `human_judgment=pass|fail`；`type_correct`、`original_supported`、`single_slot_counterfactual`、`subtype_preserved`、`reason_codes` 与 `evidence` 可作为人工判据记录。填写完成后先做不访问 key 的 schema/hash 检查，再由用户另行授权 evaluate/finalize。

### 2026-08-10：63-row human review blind-only 预检完成，等待全 pass 意图确认

- 用户已填写原 63-row 工作模板。blind-only validator 只读取 audit manifest、blinded rows、assistant-labels manifest 的 identity/uncertain IDs 和填写文件；没有读取 assistant labels 内容或 key，也没有运行 evaluate/finalize。
- JSONL/schema/identity 检查通过：63 rows、63 unique IDs，冻结 60 IDs 与额外 3 uncertain IDs 精确覆盖；`audit_id`、dataset、source、entity、claim 等 immutable blinded 字段逐项未变，所有 `human_judgment` 都是合法的 `pass|fail`。
- 已另存 canonical review `entity_policy_audit_human_review.jsonl`，SHA-256=`2b1480a6fa5e816743a609d9e68135083e39b571ec29c405943be3310b68a113`；review manifest SHA-256=`4760cc61204a8826035517f50167be56df44a448ab4da60be3699325a5cddc2b`，review identity=`87d369c20d169dd8b5e9906dd8498d814d951686b87ded60ab6b2a6bc7459488`。原填写工作副本未覆盖。
- 人工标签分布为 pass=63、fail=0；四个判据字段、reason codes 与 evidence 的填写数均为 0。可见内容硬检查没有发现 true/counterfactual claim 完全相同或 original/counterfactual entity 相同却标 pass 的行，因此 schema 层不擅自改判。
- 63/63 全 pass 属于需人工确认的退化分布，当前只能记为 `frozen_blind_only_pending_evaluation`，不能写成 audit passed。下一步由用户确认这是逐条独立判断而非批量填充；不得为了匹配预期配额或 assistant 判断修改标签。确认后仍需单独授权才可读取 evaluation 所需 key 并运行 evaluate/finalize。

### 2026-08-10：63-row 独立人工判断已确认

- 用户明确确认原话：`确认全部为逐条独立判断`。该确认仅证明 63 个 judgments 的人工过程，不改变 pass=63/fail=0 的冻结内容，也不构成 audit 结果或下游执行授权。
- 已生成独立 attestation：`entity_policy_audit_human_review.attestation.json`，SHA-256=`5f1cfdc45b8ccd52bb770b50662d386cbc00912593233de611b66b4af7a8893d`，identity=`e4cab8d56d5d3338f382548757799dae3a61654477edf044599568a252d7f3dd`；精确绑定 review SHA-256=`2b1480a6fa5e816743a609d9e68135083e39b571ec29c405943be3310b68a113`、review manifest 与 identity。
- attestation 明确列出不授权 key access、audit evaluate、release finalize、Enron promotion、formal scan 或 API/model calls。本轮仍未读取 key/assistant-label content，未运行 evaluate/finalize。
- 下一步唯一决策是是否单独授权 audit evaluate + release finalize；未授权前保持 release、promotion、formal scan 全部停止。

### 2026-08-10：r3 audit evaluate + release finalize 已执行并 fail closed

- 用户单独授权后，正式 evaluator 首次读取 r3 key，并原样使用冻结 assistant labels、63-row human review 与 independence attestation。执行前六份 replay/pilot exact role/status/identity、所有 r3 输入哈希、runtime tree 与空 release 输出目录预检通过。
- audit status=`failed`，release status=`failed`，release failure=`audit_failed`。`audit_report.json` SHA-256=`7a490ef065904407d8b3084969ef77c36883d4240cba4e68271473ce517f7558`；release gate SHA-256=`640e7851f30a23ed5df9ec23f0b94d77a0c8510b75af5c12949db584e668bb74`，identity=`4ca28106dc538f9680c0d6a8d735d70fad96cf4af7bb8362bcd918e3b93d391d`。
- 主要门禁结果：accepted passes=369/540（68.33%），hard-negative correct rejections=58/60（96.67%）；15 个 dataset×type cells 仅 PubMed/LOCATION 通过，五个跨数据集类型仅 LOCATION 通过。失败重点是 accepted precision，而非总体 hard-negative specificity。
- human review 为 63 个 pass；assistant 有 4 个 uncertain 不计 agreement，剩余 59 行中 agreement=39/59=66.10%，低于 90% gate。audit failure reasons 共 22 条，包含 dataset/type 与 type-level precision/specificity failure 以及 `assistant_human_agreement_below_gate`。
- `check-release` 因 status 非 passed 按设计拒绝；独立复算确认 embedded audit report、release identity、key hash、输入 hashes 与 runtime tree 全部匹配，因此这是有效实验失败，不是命令或文件漂移错误。release 绑定 code commit=`2f3b541e189c37879e1bd092e250dccb8a015087`、runtime tree=`89b88264f5fdb78ae144c9535544c70b09b0b78b695cde1bc115ac310a439a34`。
- r3 失败产物必须原样保留，禁止修改 labels/review、降低 gate 或原地重跑以求通过；Enron promotion、formal scan、API/victim/Retriever/正式 query 继续禁止。下一步只能先由用户决定是否授权只读失败诊断与 r4 协议设计，不能把 r3 纳入 canonical release。

### 2026-08-10：r3 failure diagnosis 完成——当前不需全量重跑实体抽取

- 用户授权只读诊断 r3。已将 600-row key/blinded/assistant labels、63-row human review 与六份 replay/pilot report 的 29 个 claim files 全部回连；540/540 key-accepted rows 均找到上游 semantic-resolution metadata。未修改标签、policy、threshold、facts/claims 或旧 artifact，新增 API/model calls=0。
- 最终分析包位于 `artifacts/v21/entity_policy_r3/diagnosis/r3_failure_analysis_r2/`；manifest SHA-256=`76dac1166cfecfbff5c01381a4273d3ae22637275f97c4aa0bcdc62f82bb89e8`，analysis identity=`7a0fa97d994e3726e8b2e999e626b980be418d0674c0460cd02c18ab4b7f3aa9`。包含 analysis report、stats appendix、figure catalog、3 组 PDF/600-DPI PNG、cell/subtype/review CSV 与代表性 case JSON，独立 hash/schema/visual QA 通过。
- 根因一：semantic accepted pool 的 precision gate 实际退化为单模型确认。540/540 accepted rows 均只由 `fastino/gliner2-large-v1` 支持，target vote=1、boundary vote=1；assistant 在 accepted 中标记 145 条 declared-type incorrect。`manufacturer’s protocol→CONTRACT_TERM`、`Fannie Mae→PERSON`、`CG-R→ORG` 等案例与冻结 policy 明确冲突，证明上游 accepted pool 存在真实类型误收。即便 confidence≥0.90 的 311 行，仍有 47 fail、2 uncertain，pass=262/311（84.24%），单纯调 confidence threshold 不足以达到 96%。
- 根因二：assistant rubric 与冻结机器 subtype 不一致。22 条 accepted 因 subtype 被 assistant 拒绝，但 22/22 的 frozen machine subtype 相同、22/22 通过代码 format-compatible；例如代码允许 `President Trump→Dakota Reyes`，assistant 却额外要求 title preservation。这部分不能算 extractor 错误。Assistant 还漏过 2 个显式 wrong-type hard negatives，说明静态 invalid-ID list + remainder default-pass 不能作为 formal reviewer。
- 根因三：human template 没有嵌入冻结 policy 定义/正反例，四个判据字段与 evidence 全空。63-row sample 中实际有 3 个 hard negatives（WSSs→PERSON、Sweden→CONTRACT_TERM、James Sapirstein→ORG），human 全部 pass，specificity=0/3；独立判断 attestation 仍成立，但该 review 不能充当可靠 adjudication gold。
- 问题跨 stage：replay accepted pass=283/414（68.36%），pilot=86/126（68.25%），差仅 0.10 个百分点；不是某一数据集 wave 或 cohort 单点故障。
- 决策：当前不重跑 EDGAR、Enron、PubMed 的完整实体抽取。r4 应先复用 Step 06 facts、source spans 与 candidate-claim pool，增加预冻结的强 semantic revalidation、两名独立 human reviewer/calibration/adjudication，只对通过 rows 重建 counterfactual/query 下游。只有 revalidation 证明原 facts 的 span/entity candidates 系统性错误且无法重新分类过滤时，才重跑对应 dataset×type，而不是默认三数据集全跑。
- 诊断生成过程中保留两个 superseded attempts：初始 partial 因 Matplotlib 参数兼容失败，r1 因 Figure 1 图例遮挡被视觉 QA 淘汰；最终 r2 数值不变、布局通过。下一步若继续，应先单独授权制定 r4 protocol，不得直接执行重抽取或重审。

## 2026-08-10：r4 Phase 0/1 启动与 fresh capacity 门禁

- 用户已授权开始 r4；冻结外层协议 `v21_entity_policy_r4_semantic_revalidation_r1`，输出隔离在 `artifacts/v21/entity_policy_r4/`。r3 继续保持 failed/diagnostic-only，不改写旧 labels、review、audit 或 release。
- r4 不默认重跑实体抽取：复用 Step 06 facts/source spans/Step 07 candidates；语义重验证改用现有 `audit_consensus` 三角色（GLiNER base/large + spaCy transformer，PubMed 加 biomedical veto），formal threshold 仍标记 `calibration_pending`。
- 零模型 inventory 保留 22,015 条 fresh candidates，canonical r2 identity=`f7364dc638dbc73d995d102ce67b45f0b1aeb88ecc06ae02e92a73b642d6bf96`；preflight identity=`26b26cd9933d7f2c24850e0b5264e350e497a71ec8be4b0073744bd7cf1e9868`。CUDA=True，API/model/victim/Retriever 调用均为 0。首版 attempt 原样保留；r2 修复 failed gate 在 `--resume` 时仍返回非零退出码。
- 13/15 cells 通过 36-row minimum；仅 PubMed/CONTRACT_TERM=15、PubMed/PERSON=22 失败。EDGAR 与 Enron 全部达到 target 72，因此不得全量重跑三个数据集。
- 旧 PubMed eligibility claims 缺少 v21 entity-policy identity，禁止补入 formal pool。下一步只能先建立排除 r3/current source 的 PubMed targeted refill cohort；达到 minimum 36、目标 72 后，才能启动 Phase 2 ensemble revalidation。

### 2026-08-10：r4 PubMed targeted refill runner 已就绪

- 已新增 `configs/entity_policy_r4_pubmed_refill.yaml`、`src/prepare/entity_policy_r4_refill.py` 与 `scripts/36_run_v21_entity_policy_r4_pubmed_refill.py`。协议仅覆盖 PubMed，固定 5,000 fresh sources、250/source wave、最多 20 waves；EDGAR/Enron 不重跑。
- source 排除覆盖 r1 replay、冻结 pilot A/B/C、r3 audit 与当前 r4 inventory；选择只按协议/seed/source identity 哈希，不读取标签、victim 或 AUC。新增目标固定为 CONTRACT_TERM≥57、PERSON≥50，对应把当前 15/22 补到 target 72。
- 每波复用本地完整 capacity runner：facts、candidate claims、compressed offline query、stealth capacity probe。这里的 query 不是 Luna/正式 query，API/victim/Retriever 均为 0；波内产物 immutable，checkpoint/resume 与所有身份漂移均 fail closed。
- 定向 unittest 7/7、内存编译、CLI help、status 与敏感信息扫描通过。当前 `status=not_frozen`，尚未扫描 1.6 GB processed PubMed、未生成 plan、未加载模型；下一步由用户先运行 `freeze-refill`，再逐个 wave 续跑。

### 2026-08-10：r4 refill r1 在 0doc fail closed，升级 r2

- r1 plan 已成功冻结，但 candidate benchmark 直接复制 processed PubMed schema，缺少事实抽取要求的 `group`，也未应用每 source 5-chunk probe；首波在 0doc 抛出 `KeyError: group`。没有 checkpoint 或完整 wave，fresh counts 未变化。
- r1 plan identity=`4f4dde9b43a5f7e981cde2e22eb9408d3a4bbe26b9fe53165454fbc05c080897`，66,736-row candidate hash=`fba6e2ef375504aa94d06bef770c28a24c408485572fee0153b55e195b346c30`；两个失败 attempt 都只含 benchmark。以上原样保留为 superseded，不得原地续跑、删除或并入 r4 inventory。
- r2 新身份改用历史 eligibility/pilot 共用的 `freeze_source_plan`，强制 `Eligibility_Candidate` group、source key、audit ID 与最多 5 chunks/source；其余 source exclusion、5,000-source pool、57/50 目标和零 API/victim/Retriever边界不变。
- r2 回归测试 8/8 通过，当前默认脚本指向 `configs/entity_policy_r4_pubmed_refill_r2.yaml`，状态为 `not_frozen`。下一步必须重新 freeze r2，不能对 r1 使用 `run-refill`。

### 2026-08-11：r4 PubMed refill r2 已完成前两波

- r2 checkpoint 已完成 2/20 waves，identity=`a97079366ecc7d6230ea800bbe17daa2bace1730fabfe61a25f4e03aad769078`，所有 completed-wave manifest/output hash 通过正式 status validator。
- 两波累计 500 sources，claim-eligible=436、query-eligible=421；fresh CONTRACT_TERM=19、PERSON=31，target 分别为 57/50，重复 target content=0。
- 当前状态 `paused`、report=null 正常。两波新增分别为 10/12 与 9/19；CONTRACT_TERM 是剩余瓶颈，按观察速率描述性预计还需 4–5 waves，但不得据此提前停止或调整样本。
- API/victim/Retriever=0。继续每次一个完整 wave，达标前 Phase 2、audit、release 与正式下游仍 blocked。

### 2026-08-11：r4 targeted refill 与 Phase 1 capacity 正式通过

- PubMed refill r2 在 7/20 waves 后按冻结 early-stop 通过：fresh CONTRACT_TERM=68≥57、PERSON=94≥50；report identity=`43c7ecd102a7db044c6f045e91c0cbfb2be9ebc49bb5fc572f63f7b2473c8bf1`。7 个正式 claims hash 全有效，4 个 target duplicates 被去重。
- wave 2/6 各有一个 benchmark-only partial attempt，均无 manifest/checkpoint 身份，不进入 report 或新 inventory；全部原样保留。
- 新 `phase_1_r3` 配置绑定 refill report SHA/protocol/passed status/identity 与逐 wave claim hash，避免仅凭 identity 字段接线。
- canonical r3 inventory=24,190 records，identity=`ac7d82c35ff818b9fc370e46077c1cefb7b32418cb7190e5e61c86b9decf058d`；15/15 cells 全部达到 target 72。PubMed CONTRACT_TERM=80、PERSON=116。
- preflight status=passed，identity=`a6ed18fcd78269b09ab5bf411b159f879bc4984c95bb7ad8feae70f07de76e84`；resume 幂等，model/API/victim/Retriever=0。旧 phase_1_r2 保留为 capacity-failed evidence，不覆盖。
- 下一步是冻结 Phase 2 calibration/ensemble semantic revalidation，不是直接生成 query、运行 victim 或进入 fresh audit。

### 2026-08-11：r4 Phase 2A ensemble 开发校准已冻结

- 正式 Phase 2A 身份升级为 `v21_entity_policy_r4_phase2_calibration_r2`；配置 SHA-256=`3cf208785237b4428aa2c66879bfdce412e39bc079cb33710b46bfc4d18017ec`，plan identity=`22f7898b54b82fc24cf140c0b4e0c3411be12579bb6914b6a5ceff38ea11ac55`，runtime bundle=`a7c4c7abaeb54a772e971e9acb2284da905579347df3745cb9020964c4e1823a`。
- r3 600-row 暴露集只作为 development calibration，不作为 fresh r4 audit。每个 dataset×type 固定 12 条旧 accepted 候选和 4 条 constructed hard negative，共 15 cells×16=240 rows；r3 expected decision 只控制分层抽样，不作为 human gold。
- 60 条 hard negative 中，30 条是 donor-type semantic negative，30 条是 `counterfactual_equals_true_claim` structural negative。后者保留并由结构门禁直接拒绝，不因无法形成替换 span 而删除；用于 semantic threshold 的 rows 共 210。
- 冻结阈值网格：target confidence 0.50–0.95（步长 0.05）、margin 0.05–0.40（步长 0.05），固定 target/boundary votes=2/2、biomedical veto=0.90、overlap=0.80。选择时禁止查看 victim/AUC；按每类型 adjudicated negatives 零 false accept、正例保留率至少 0.50，再按预冻结 tie-break 裁决。
- 两名 reviewer 必须独立填写各自 240-row 模板，不得查看 private selection key、模型预测或对方标签；任一 disagreement/uncertain 必须第三方 adjudication。Assistant 已读取 r3 key 进行抽样实现，不能充当这两名独立 reviewer。
- 本地 ensemble 固定 GLiNER2 base+large+spaCy transformer，PubMed 另加 biomedical veto；12 个 dataset-homogeneous batches，每批 20 pairs/40 texts。runner 支持 immutable batch、SQLite prediction cache、`--resume` 和身份漂移 fail closed。
- 首个 r1 plan identity=`1ece17826c0d4d54804710b8796e8b092848bfbb1786cdc2b077ce8d0e133989` 在零 batch 状态因后续加强相对路径/hash 校验而 superseded；原 artifact 保留，不得续跑或合并。r2 freeze/resume/status 已通过，当前 0/12 batches，API/victim/Retriever=0。
- 定向 unittest 6/6、内存编译、240-row cell/泄漏审计通过；review templates forbidden-field overlap=0。下一步由用户逐批运行 r2 calibration；预测和双人 adjudicated labels 均完成前，不实现/启动 full 24,190-row revalidation，也不进入 fresh audit/query/victim/Retriever。
- 最终关联回归覆盖 Phase 2A、r4 inventory 与 refill，共 15/15 tests passed；`mia_model` 解释器与 CUDA=True 已复核，YAML/内存编译、plan status、secret scan 与 `git diff --check` 通过。环境未安装 `ruff`，因此 lint 记为 unavailable，未为此修改环境。

### 2026-08-11：Phase 2A batch 0 首次启动前模型快照缺文件

- batch 0 在任何模型加载/推理前由严格 model-lock 校验 fail closed：`fastino/gliner2-base-v1` 缺少文档资产 `image/GitHub.png`。该 attempt 只产生冻结的 `batch_plan.json`，没有 prediction cache、predictions、batch manifest 或 checkpoint；completed batches 仍为 0/12。
- 全模型锁逐文件只读核验结果：base 其余 10 个文件匹配；large 11/11、spaCy 24/24、biomedical 12/12 全匹配，无 hash mismatch。large snapshot 内同名图片 SHA-256=`c945cbd7b6178aa0e80ed2f10382d6edf59799e3e0dd9b24e3e8c5fe58c02deb`，与 base lock 要求完全一致。
- 修复边界：仅把该已锁定的同 hash 文档资产补入 base snapshot，不改 model lock、配置、代码、plan 或 threshold。补齐后沿用同一 r2 `--resume`；不得删除 batch plan 或重冻实验身份。

### 2026-08-11：Phase 2A calibration batch 0 完成

- 用户补齐 base 的锁定文档图片，复核 SHA-256=`c945cbd7b6178aa0e80ed2f10382d6edf59799e3e0dd9b24e3e8c5fe58c02deb` 后以原 r2 identity 成功续跑；无需重冻 plan。
- batch 0 dataset=`edgar`，20 rows/40 logical texts，包含 2 条 structural negatives、18 条 semantic-threshold-eligible rows；prediction rows=20、unique calibration IDs=20，三 voter 输出覆盖检查 problems=`[]`。
- 实际模型身份：GLiNER2 base revision=`f5b2ecedebe4381b088c1cf276f5bf72a52cac54`、large revision=`b122b11eeaee4dabd32bed80412f3234c0d0e943`、spaCy=`3.8.0`，角色与冻结 lock 完全一致。
- OOM retry=0；cache identity=`d040b48ea36b5b053f5969b5514a0c31eba95d313e251f2414f1d8b9658c9385`。misses=120/writes=114 来自两组 identical structural texts 在三个 voter 上的批内去重，共减少 6 次 backend-text 写入，不是缺失输出。
- predictions SHA-256=`5192dbb556e57807167e53a63c069e231f7c944b214e1207b1259ba6d6eb7081`，batch manifest identity=`5bde60f80fd3b2c2bd88d7826bd1c7fbd8a8a051511c18a263880da64a6afc14`，checkpoint identity=`a94b780f003e4270e1674af1543c577c54d62283c1c9550ee47550f54c9a0bea`。
- 当前 status=`paused`、completed=1/12；API/victim/Retriever=0，threshold 仍 calibration_pending，full revalidation 仍禁止。

### 2026-08-11：Phase 2A ensemble predictions 12/12 完成

- 用户在同一 r2 identity 下完成剩余 11 batches；canonical status=`predictions_complete`，checkpoint identity=`05c58b26d1089af28840ea2245d07ab6c15e3ff91e8ce4916b63d9259604cf8c`，checkpoint 文件 SHA-256=`52a55ef98706a9d3fb7209c38186de3394aec1b72316b736585ed3d1575a138f`。
- 12/12 immutable batch manifests 与 prediction hashes 全部通过正式 status validator 和独立复算；240 rows、240 unique calibration IDs，与冻结 plan 精确相等。EDGAR/Enron/PubMed 各 80 rows，15 个 dataset×type cells 各 16 rows。
- 结构分层保持 30 条 `counterfactual_equals_true_claim`、210 条 semantic-threshold-eligible；没有重复 ID、缺失 row、voter coverage 缺口或非 PubMed biomedical 泄漏，aggregate problems=`[]`。
- 模型身份保持冻结 revision：GLiNER2 base=`f5b2ec...`、large=`b122b1...`、spaCy=`3.8.0`、PubMed biomedical veto=`f79771...`。12 batches 总 OOM retry=0。
- aggregate cache misses=1600、writes=1500、hits=0；100 的差值恰由 30 个 unchanged structural pairs 的正反文本按每 dataset active backend 数去重得到：EDGAR 10×3、Enron 10×3、PubMed 10×4，共 100，不是漏算。
- API/victim/Retriever 总调用均为 0。当前仅完成 raw ensemble predictions；threshold status 仍=`calibration_pending`，full revalidation allowed=false。下一门禁是两名未见 private key/model predictions 的 reviewer 独立完成 A/B 240-row templates，并对 disagreement/uncertain adjudicate。

### 2026-08-11：Phase 2A reviewer 角色接线更正

- 用户明确更正既定意图是“Assistant 先审核全部 rows，用户再做人类复核”，不是“两名独立人工 reviewer”。此前写入 r2 plan 的双人工 reviewer 角色属于实施时的协议接线错误。
- 更正发生在 raw predictions 12/12 完成后、任何 assistant label/user review/threshold evaluation/AUC 查看之前；没有观察 label quality 或 threshold performance，因此不得按结果调参。现有 r2 raw predictions 与模型身份保持有效，不重跑、不覆盖。
- r2 内原 A/B 双人工模板原样保留为 superseded review-design evidence，不再要求用户另找第二名人工 reviewer，也不得把未填写模板伪装成完成结果。
- 新建独立 review identity 时必须绑定 r2 plan identity、completed checkpoint SHA/identity、240-row cohort hash、rubric hash，采用：Assistant 审核 240/240；用户复核预冻结的每 cell 5 条（15×5=75）并追加全部 assistant uncertain（去重）；用户在复核范围内的更正作为 adjudicated label。
- Assistant 已在 r3 诊断/分层实现中接触旧 key，因此本轮只能称为 `development assistant annotation + human validation`，不能声称是严格 blind independent human audit。该限制可接受用于 Phase 2A 开发校准，但不能替代后续 fresh r4 formal blind audit。

### 2026-08-12：v22 calibration_r2 Assistant-only 正式失败

- 独立 r2 runtime 已提交为 `2cfe3f668f4df3acda7b742884d5a67b84d87d45`；plan identity=`432305b2797d31818fdb00f12b6c163f63c5883377a10be991b713eebbed63fe`，样本与 r1 在 pair/source/fact 三层重叠均为 0。
- Assistant 只读 blind rows 完成 300 行标签：yes=108、no=192、uncertain=0；labels SHA-256=`6e320b7df2811d0433084698a3d2b427c9a39fcd4a4a3c2014a68bd900f7f8ac`。解盲前未读取 private key。
- 结构负例拒绝 60/60=100%，uncertain=0%；但 threshold 0.50–0.85 的 judged usability 仅 29.73%–47.42%，全部低于预注册 90%，故 status=`failed_new_protocol_identity_required`、selected threshold=null。
- 0.50–0.75 的 EDGAR/Enron/PubMed source projection 均≥2,500，排除“样本容量不足”为主因。证据指向当前 utility score/硬门禁不能有效排序替换后的上下文兼容性、自然度与可查询性；提高阈值没有改善纯度。
- r2 失败产物与 labels 必须保留且不可原地修改；evaluation identity=`bfc7ba2c392fe7d994f39e290f436f44fd3c3fa51d31e066a9890006ad439bf7`。本轮 API/victim/Retriever/AUC access=0。
- 当前所有 fresh audit、formal scan、split、shadow、Luna query、Gemma victim 与正式 Retriever 继续 blocked。继续需另建 calibration_r3 身份，先修正评分/硬门禁与攻击适用性判断的错位，不重新扩大 source pool。

### 2026-08-12：v22 calibration_r3 单路由上下文验证实现

- r3 采用独立协议/输出，不修改基础 v22 selector 或 r2 runtime；旧失败 labels/evaluation 不复用、不覆盖。r3 同时排除 r1/r2 的 pair、source 和 fact signature。
- r2 失败根因确认是表面长度/token 相似度无法表达实体在句中的上下文槽角色。r3 增加确定性单槽/span/冠词/别名结构 gate，以及 context-slot/queryability soft score；类型/角色不确定不作为单独 hard veto。
- 反事实上下文验证只使用已冻结的 `fastino/gliner2-base-v1@f5b2ec...`：同一 `effective_type`、精确 counterfactual span、score≥0.65；无三模型投票，无 API。
- runner 支持 context plan freeze、按 batch 可续跑的本地 CUDA validation、capacity check、fresh 300-row calibration freeze、Assistant labels 与 evaluate。
- 冻结前容量审计：排除 r1/r2 后保留 19,469 fresh pilot pairs，15 cells 最小容量=117；当前尚未加载模型/生成 r3 artifact。
- 验证：定向 33/33、全量 unittest 439/439、AST/diff/secret check 通过。r3 runtime 提交前不允许 freeze；建议 commit=`feat(calibration): add final v22 context calibration r3`。
- formal scan、fresh audit、split、shadow、Luna query、Gemma victim 与 Retriever 继续 blocked；r3 context validation 是当前唯一可执行下游。

### 2026-08-12：v22 calibration_r3 已提交、冻结并完成首批上下文验证

- r3 五个 runtime 文件已独立提交：commit=`25ce2c4d1e9e2c2f3be01b3e4fd00d8c2d04d40c`，subject=`feat(calibration): add final v22 context calibration r3`；既有脏工作树未被纳入、清理或覆盖。
- `mia_model` 环境复核通过：Python=`D:\python\anaconda\envs\mia_model\python.exe`、PyTorch=`2.11.0+cu130`、CUDA=True、device=`NVIDIA GeForce RTX 4060 Laptop GPU`。
- context plan 已冻结为 19,469 rows / 39 batches；plan identity=`5db279d9787065fb295ac0cbad498edb4922007ef1954597ed844312631560b1`，candidate rows SHA-256=`60c2c2681ff18e91b859ab067de640ae552711012f8c6115568272c6a982dbde`，绑定 commit 与全部 runtime hashes。
- 首批 512 rows 已完整运行：383 通过、129 因 same-type/exact-counterfactual-span/score≥0.65 门禁拒绝；模型实际身份=`fastino/gliner2-base-v1@f5b2ecedebe4381b088c1cf276f5bf72a52cac54`，运行记录为 CUDA/fp16，未发生身份漂移或 CPU fallback。
- 当前 checkpoint status=`paused`、completed batches=`[0]`，identity=`cdf3a08737e2e8be47e1c4a1ecedce12cde713b63e60868e317de48e3423b67c`；batch manifest identity=`4f5e754721f58f96acf13da91c9ccb963a45b070506a1eea6f02f4b055a5f744`，prediction SHA-256=`a7d7b409cac2becab94f7d1d45d9f2675a1b46c3054b4a5f4fb8a61c36f6fd68`。
- API/victim/Retriever 调用与 AUC access 均为 0。下一步只能用同一 `--resume` identity 续跑剩余 38 batches；完成前不得执行 capacity、freeze-calibration、fresh audit 或正式实验下游。

### 2026-08-12：v22 calibration_r3 context 39/39 完成并冻结 fresh calibration

- 用户按原 identity 完成剩余38批；39/39 manifests、19,469 prediction rows及逐文件 SHA-256 全部通过复核，checkpoint status=`passed`、identity=`a53bed152f0d9a15115a68118d6e23d86f893b36cf941034d8fac88cbff0d411`。
- 19,469 候选中15,092通过上下文门禁（77.52%），4,377拒绝。EDGAR=5,077/6,678（76.03%），Enron=3,363/4,272（78.72%），PubMed=6,652/8,519（78.08%）。合并 SHA-256=`02e71e70b36b591dd4c81f59ee18a4bc1787e3759da25f013536e0a118f60bae`。
- 全部 batch 的实际模型 revision 均为冻结的 `fastino/gliner2-base-v1@f5b2ecedebe4381b088c1cf276f5bf72a52cac54`，runtime device 均为 CUDA；无身份漂移、无 prediction hash 问题。
- `check-capacity` 通过：15/15 cells 均满足每 cell 16个 fresh real rows；唯一 fact 最小值为 PubMed/CONTRACT_TERM=34，因此无需重新扫描 source pool。
- 已冻结独立300-row calibration_r3：240 fresh real+60 structural controls，r1/r2 pair/source/fact overlap=0；plan identity=`2912806746828fe3b211bba708e047196118f78feed73756e291993e301c3cb4`，blinded SHA-256=`ad4c1ab0e59dd33031671dafcfec8ba43f026b2b3330f5ad250d8238acfc15d0`。
- 当前 status=`frozen_waiting_for_assistant_labels`。尚未生成标签、未读取 private key、未运行 evaluation；API/victim/Retriever/AUC access=0。下一步是 Assistant-only 300-row blinded annotation，而不是 formal scan 或 victim 实验。

### 2026-08-12：v22 calibration_r3 Assistant-only 正式失败

- Assistant 仅读取冻结的300-row blinded calibration并逐条审核；labels=yes 122、no 178、uncertain 0，SHA-256=`6bf9ebff2b2e8e9c63fb1007cd5ec1c487358d69702bfcce83cebbf74814968f`。labels validator通过，receipt identity=`81e43c6c79c8376d6f8dac3d992f50a709493e0d85aa7068c3f9c5543fbb01dc`；标签冻结前未读取private key。
- 正式evaluate首次解盲后，60/60 structural controls正确拒绝，real uncertain rate=0%；但threshold 0.50–0.85的judged usability仅51.97%–61.49%，全部低于90%，故status=`failed_final_calibration_revision`、selected threshold=null。
- r3最高61.49%@0.70，较r2最高47.42%提高约14.07个百分点，说明单路由上下文验证有实质改善，但不足以支撑formal promotion。evaluation identity=`333e920d01cfb77839526d988787ebb8b9c11ef42dc2d8308a45b2eae4aa5189`，report SHA-256=`6e83b278c5e9ab8570ab1d6eebd20e1f67cdb1af0345a7604f92542d9cdd1aaf`。
- 容量门禁也未通过：EDGAR在threshold=0.50仅投影1,760.98个eligible sources，低于2,500；Enron/PubMed低阈值足够。real-cell质量高度不均：EDGAR/CONTRACT_TERM与PubMed/PERSON各18.75%，EDGAR/PERSON与PubMed/CONTRACT_TERM各25%，Enron/ORG最高87.5%。
- 结论：失败不是模型运行、hash、结构负例或语料总容量问题，而是“单模型同类型精确span”仍不能保证语义角色自然、事实适合验证，且EDGAR source coverage不足。r3失败证据必须保留，不得原地改标签、降门禁或进入fresh audit。
- API/victim/Retriever/AUC access均为0。按预注册规则，r3失败后停止复杂utility/calibration修订路线；formal scan、split、shadow、Luna query、Gemma victim与正式Retriever继续blocked，等待用户重新决定替代方案。

### 2026-08-12：攻击目标纠偏与 API 登录切换交接

- 用户重新明确 PCV-MIA 的核心攻击目标：对只替换一个实体槽的 corrupted/counterfactual verification input，测试 RAG 是否因检索到目标文档而恢复原实体；目标不是把反事实优化为“明显自然”。
- 因此，`counterfactual_naturalness` 不再作为独立效用目标或“越自然越高分”的晋升指标。仍保留最低构造有效性：原实体精确绑定、原事实有文档依据、反事实实体 source-absent、单槽替换、粗类型/格式兼容、替换后句法成立，避免模型仅靠乱码或表面类型错位判错。
- 新方向暂命名为 `Restoration-First`：优先考虑原事实稳定性、原实体从 source 的稳定/尽量唯一恢复性、非实体检索锚点、验证辨别力、query 自包含和 parser friendliness。matched LLM-only 只用于冻结后的机制归因，不得参与 pair/source 选择。
- 之前口头提出但从未实施的 Luna `Generation-First` 方案正式取消。Luna 继续仅保留为下游正式 query generator；不得把它用作反事实自然性裁判或依据 victim/AUC 返工 query。
- v22 r1/r2/r3 的 labels、utility thresholds 与 naturalness/context-usability evaluation 保留为 `superseded_goal_mismatch` 开发证据，不得改写为 passed。r3 的 15,092 条 context-passed 候选只能用于 diagnostic 回放，不能成为下一协议的唯一候选全集。
- 三个冻结 source pool/order、原文、source hash、原事实/span provenance 和 GLiNER2 snapshot原则上可在新 identity 下复用；无需因本次目标纠偏直接重建数据集。v23 尚未获授权、未冻结、未实现。
- 用户因额度不足准备切换为 API 登录。已新建 `研究记录/API登录切换_工作交接_20260812.md`；本次未修改代码、未调用 API/victim/Retriever、未运行 GPU 长任务、未提交 Git。登录切换不等于授权付费调用。
- 当前 formal scan、split、fresh audit、shadow、Luna query、Gemma victim 与 Retriever 全部继续 blocked。唯一下一步是用户在新会话确认交接后，明确授权是否制定并实现独立 `pcv-mia-v23` / `pcv-restoration-first-v23`。
### 2026-08-12：v23 Restoration-First 独立协议 design r1 草案

- 用户已授权“制定独立 v23 协议”；本轮将协议冻结为 `pcv-mia-v23` / `pcv-restoration-first-v23`，设计规范=`pcv-restoration-first-v23-design-r1`，独立输出根为 `artifacts/v23/`。新增 `configs/restoration_first_v23.yaml` 与 `研究记录/PCV-MIA_v23_Restoration-First_协议预注册_20260812.md`。当前仅为 `design_preregistered_runtime_not_implemented`，尚无 executable runtime/commit bundle/protocol manifest，不得表述为已实现或已通过。
- v23 复用 v22 三套 passed source pool/order、完整 source hash、原事实/span provenance 与 GLiNER2 snapshot，但全部在新 identity 下重绑。r1/r2/r3 labels、阈值、旧 naturalness/context-usability 分数、r3 15,092 条 context-passed 集合和 v22 旧 eligible 判定均不得进入 v23 selection。
- v23 取消加权 utility 和自然性阈值，采用 hard gates 后的确定性词典序：grounded fact stability、source 内原实体近似唯一可恢复、去实体后的 source-specific anchor、verification discriminativeness、query self-containment；parser friendliness 改为全局响应 schema 门禁，不读取逐 pair victim/LLM-only 输出。
- selection 只能读取完整 source document 的文档内生信息。source absence/recoverability 均以完整 membership unit 判定；PubMed 保持完整 PMCID article。禁止 membership/split/group、victim response、LLM-only response、Retriever 输出/排名、attack score/AUC 和 v22 calibration labels/thresholds。
- 三数据集 v22 冻结顺序前1,000 source固定为 v23 development cohort，紧接的250 source固定为 fresh-audit reserve；reserve至少100个 eligible后取前100个盲审，全部250个同样永久排除 formal。formal scan只在两门禁 passed后从剩余顺序中恰好收集2,250 source。development gate预注册每数据集 eligible>=500、Wilson lower>=0.45且扣除1,250 source后的容量下界>=2,250；EDGAR formal domain=3,960使其派生 lower-bound要求实际为0.568182，失败需新协议 revision。
- 每 eligible source恰好3 pair、fact signature互异、同一原实体最多2 pair；每 pair固定 Q+/Q-，即每 source 6 query。fresh audit为每数据集100 source×3 pair，共900 pair，由两名独立真人盲审并经第三方裁决，预注册 raw agreement>=90%与 kappa>=0.80；Assistant-only不能写成人工验证。
- 本轮未实现 selector/runner/测试，未写 `artifacts/v23/`，未运行 pilot/GPU/API/victim/Retriever，未下载模型、安装依赖或提交 Git。v22 formal scan、split、fresh audit、shadow、Luna query、Gemma victim 和 Retriever 仍保持 blocked。该版本随后经无上下文 reader test 判定需要修订，并由下述 design r2 supersede；本条作为设计演化证据保留。

### 2026-08-12：v23 Restoration-First design r2 reader-test revision

- 首轮无上下文 reader test 对 design r1 给出 `Request Changes`：selector 仍不能唯一实现，fresh-audit reserve/跨 revision 消耗、provenance、固定前缀容量推断、formal split、structured diagnostic 与执行世代存在缺口。历史 r1 不回写为 passed；本条以 `pcv-restoration-first-v23-design-r2` supersede。
- selector 已冻结到唯一实现所需的 primitives：Unicode NFKC/casefold/空白规范化、Python codepoint 半开 span、canonical JSON/SHA-256、sentence/proposition/token regex、relation/fact/counterfactual/pair identity、fresh re-extraction、GLiNER2 的 emission/routing/filler-inventory 限定职责、冻结 subtype replacement pool/filter/order、17 项显式 rank tuple与 stable greedy top-3。不复用 pre-r3/r3 candidate artifact；structured types 仅进入独立 diagnostic namespace，不能改变 P0 eligibility 或任何门禁。
- development 容量门禁取消 Wilson 与统一 `eligible>=500`，改为冻结 SHA-256 无放回排列下的一侧 95% 超几何总容量下界：`K_L=min{K:Hypergeom.sf(x-1;N,K,1000)>=0.05}`，再扣除 development 中观察到的 `x` 与 ledger 中其他已消耗 source，要求 formal lower>=2,250。首轮 audit reserve 已消耗250时，EDGAR/Enron/PubMed 最小 `x` 分别为623/89/66；边界 formal lower 为2252/2279/2258。
- 新增跨全部 v23 revisions 的 append-only consumed-source hash-chain ledger 设计；development、全部250-source audit reserve、human/diagnostic viewed 与 formal-scan viewed source 均登记并永久排除后续 fresh 角色。formal scan 启动时冻结 prior-consumption snapshot，本轮新扫描 source 不会动态失去本轮 selected-set 资格，但对未来 revision 永久排除。ledger genesis、行 schema、前驱 hash、reserve 预登记和缺失/截断/重写 fail-closed 已冻结。
- fresh audit 冻结为每数据集 reserve 前100个 eligible source、共900 pair；两名真人对全部行独立盲审、第三方按同 schema 裁决。可见/隐藏字段、六维 `pass|fail|uncertain`、缺失/重复处理、raw agreement、三分类 unweighted kappa 与所有 final 分母均已明确。
- formal scan 在 ledger 排除后的冻结顺序中恰收集2,250 eligible source；先冻结 selected set，再按独立 SHA-256 split key 排序，前1,000=`KB_Member`、后1,000=`True_Non_Member`、最后250=`Reserve`。split manifest 绑定 selected set、design/runtime、commit、ledger tip 和 key-list hash，split 后不得重跑 selector 改集合。
- design capability 与 run authorization 已分离：冻结设计配置的 `runtime/api/victim/retriever/gpu=false` 永不原地翻转；未来授权写独立、限定 stage/dataset/cell/wave/call 的 manifest，未列权限默认拒绝。同步修订 `AGENTS.md` 当前世代：v23 design-r2 为活跃设计但 runtime 未实现，v22 三套 pool/pilot passed、r3 正式失败且下游停止。
- 本轮只制定协议和做本地静态验证，未创建 `artifacts/v23/`，未运行 runtime/pilot/GPU/API/victim/Retriever，未下载模型、安装依赖、提交或推送。三套 v22 source pool/pilot 与 r3 failure artifact 原样保留。第二轮无上下文 reader test 仍给出 `Request Changes`，因此未生成 r2 design manifest；本节由下述 design r3 supersede，但作为修订证据保留。

### 2026-08-12：v23 Restoration-First design r3 修订

- 第二轮 reader test 确认超几何三个最小边界、formal split 主体、条件 P0 人群、DF 披露和授权大方向正确，同时指出会改变 candidate/rank 或治理状态的7项阻断歧义：hash payload、GLiNER overlap/merge/dedup、structured diagnostic 对 P0 anchor 的反向影响、跨 revision audit reserve、capacity/ledger 时序、ledger 事务与 tip、selector blacklist、P0 outcome functional，以及 implementation authorization 的 runtime-hash 循环。
- design identity 升级为 `pcv-restoration-first-v23-design-r3`。所有 relation/fact/counterfactual/pair/split/reserve-snapshot hash 改为具名 canonical JSON object schema，固定字段类型与 `kind`，新增 normalization/span/canonical-JSON golden vectors；候选遍历、GLiNER overlap/filter、rule/model type resolution、subtype derivation、dedup key/survivor 与 replacement surface survivor 均完全展开。
- P0 extractor 与 structured diagnostic 完全分离：structured span/literal 不参与 P0 anchor removal、cue、DF/IDF、rank、3-pair eligibility 或门禁，只能写独立 namespace/manifest/denominator。
- fresh-audit reserve 改为 revision-specific：在 development 后冻结顺序中排除 prior ledger，取下一批250个；初次仍是下标1000-1249。不足250则 revision不能启动。development cohort在 ledger genesis登记；当前 revision 的250 reserve必须在 development capacity裁决前原子 write-ahead登记，因此首轮容量公式唯一使用 `c=250`，失败后下一 revision 自动使用全新未查看 reserve并扣除全部历史消耗。
- ledger 补充 append-before-read、独占锁、完整JSONL行、flush/fsync、crash recovery、no-overwrite tip anchor和stage checkpoint绑定；同时明确其信任模型只覆盖正常协议执行/崩溃/误操作，不宣称抵抗同一可写文件系统上 ledger+anchor+checkpoint+记录的整体恶意重写。
- selector输入安全边界改为递归 exact allowlist：source/chunk/row required/optional/type 全冻结，unknown field拒绝，model predictions只允许 runtime内部产生；旧 forbidden-field列表降为 defense-in-depth。
- P0 outcome 已冻结：Q+ stance映射、Q-精确原实体恢复映射、missing/unparseable=`-0.5`、pair sum、3-pair source mean、member vs true-non-member tie-aware ROC AUC、三数据集macro、seed42的10,000次source-stratified bootstrap percentile CI，以及经验 TPR@1%/0.1% FPR。Reserve和matched LLM-only/context gain不进入主指标。
- implementation authorization 与 run authorization 分拆：前者只绑定 design manifest与允许改动路径、强制external calls=false，不要求尚不存在的runtime bundle；后者只在bundle冻结后授权具体stage/dataset/cell/wave/call。完整stage-status matrix默认fail closed。
- r3仍是 `design_preregistered_runtime_not_implemented`。本轮未实现或运行任何runtime/pilot/GPU/API/victim/Retriever，未创建`artifacts/v23/`，未提交或推送；r3须再次通过无上下文reader test后才生成最终design manifest。

### 2026-08-12：v23 Restoration-First design r4 reader-test revision

- 第三轮无上下文 reader test 对 design r3 给出 `REQUEST_CHANGES`；r3 未生成 design manifest，也不得回写为 passed。阻断项为：完整池 DF 与 append-before-read ledger 冲突；威胁模型及 query/parser/downstream freeze contract 不足；ledger batch/checkpoint/authorization 身份状态机不完整；后续 revision reserve 定义冲突；bootstrap RNG/draw/quantile 未完全确定。另有 candidate cap scope、audit identity/blinding 与指标报告层级歧义。
- design identity 升级为 `pcv-restoration-first-v23-design-r4`。新增完整攻击者能力表：攻击者持有候选 source/原事实/原实体与黑盒 RAG 接口，只观察最终 response/error，看不到 membership、index 或 Retriever 输出，每 source/cell 固定6个非自适应 query。
- 新增受控 `aggregate_df_precomputation`：runtime bundle 冻结后、任何 selector/source reservation 前读取完整未标注 pool，只输出按 token 排序的 dataset-level document frequency 与绑定 manifest；禁止 source key/hash、逐 source token/文本或 source 映射。该阶段是 ledger 内容读取的唯一显式例外，并须在论文中披露 transductive full-pool read；不声称低频 token 不可反演。
- ledger 将“批次原子”精确定义为内容可见性原子：一把独占锁下逐行 append/flush/fsync，整批与 no-overwrite completion anchor durable 后才可读取批内内容；补齐 interrupted-prefix resume、batch/row/genesis/anchor/checkpoint schema。旧 checkpoint output tip 只需是当前 tip 祖先；run authorization 增加 protocol revision、attempt 与 expected prior tip。
- fresh-audit reserve 与 formal scan 各自合并为唯一 revision-specific 定义；初始 reserve 单列下标1000-1249 golden vector。补齐 reserve/formal exclusion/selected set/split canonical schema，以及 HMAC opaque audit ID/order、secret commitment、三名真人角色 identity 绑定；准确称 source identity/协议特征盲审，不声称 dataset modality 一定不可推断。
- Luna query、strict JSON parser、main index、dense/BM25/hybrid Retriever、Gemma victim 与 matched LLM-only 的输入/输出、精确 prompt、参数、单次尝试、错误保留、manifest 路径/schema/hash 和阶段阻断均已冻结；实际 model snapshot/library/runtime hash 仍须在未来 bundle 与 run authorization 前绑定，不构成本轮调用授权。
- bootstrap 冻结为 NumPy `Generator(PCG64(42))`、source/cell/draw顺序、10,000次、type-7 linear quantile，并加入 RNG/quantile golden vectors；逐数据集与 macro 报 AUC/CI，低 FPR 逐数据集报告，禁止 pooled cross-dataset metric。
- r4 仍为 `design_preregistered_runtime_not_implemented`。本轮未实现/运行 runtime、pilot、GPU、API、victim 或 Retriever，未创建 `artifacts/v23/`，未提交或推送；只有 r4 无上下文 reader test 通过后才允许生成 design manifest。

### 2026-08-12：v23 Restoration-First design r5 canonical closure

- 第四轮无上下文 reader test 对 design r4 给出 `REQUEST_CHANGES`；r4 未生成 design manifest，也不得回写为 passed。阻断项不是 Restoration-First 方法目标漂移，而是 canonical identity/执行闭环仍有多义：23个冻结文件可被解释为20或23个；attempt单stage但authorization可多stage且预算无持久扣减；跨dataset reserve/formal reservation顺序与early-stop粒度未冻结；DF/selector/audit/split/release/query artifact链不完整；LLM-only可解释为每source 6或18次；Luna request bytes、Retriever/Gemma算法与跨backend bootstrap RNG仍可产生不同结果；少数最低构造gate仍只是名称。
- design identity 升级为 `pcv-restoration-first-v23-design-r5`。方法学主体保持不变：Restoration-First hard gates、每source 3 pair/每backend 6 query、超几何容量门禁、fresh human audit、source-level PVS/AUC、禁止membership/victim/LLM-only/Retriever/AUC选样本等均未调整。
- design manifest 现只允许绑定YAML中显式排序的23个 `{path, sha256}`；全部磁盘hash复核一致，canonical list SHA-256=`59578397e9c998dc576d5d9fe4b692a9a3ba87d0d5a6f704afb7c5a4aa4ed03e`。不再从配置章节位置推断冻结集合。
- ledger/authorization改为单stage、单attempt、单execution-unit授权；预算类型与每stage charge单位唯一，append-only budget journal先扣后执行。补genesis/no-op anchor、EDGAR->Enron->PubMed全局顺序、三套reserve共同prior snapshot/group completion，以及formal逐source reservation并在第2,250个eligible后立即停止。
- canonical artifact链补齐DF rows、selected pair rows、audit packet/labels/result、formal selected rows、split rows、release rows、query rows与retrieval rows的路径/schema/order/JSONL/file hash。release固定20,250 pair rows；Luna只对member/non-member生成36,000 query，Reserve不调用。
- 下游调用矩阵固定为dense/BM25/hybrid各6个RAG victim cell，加全局共享的6个LLM-only cell，即每source 24次、正式三数据集共144,000次victim generation。BGE/BM25/hybrid与Gemma算法契约、Luna prompt bytes、最低构造gate callable/span order均显式冻结；实际依赖版本和snapshot文件hash仍须在未来runtime bundle、任何调用前绑定。
- bootstrap改为一次性生成并冻结`10000x6x1000` little-endian int64 PCG64 index tensor，所有backend和共享LLM-only复用，禁止各cell重置或继续消费RNG。r5仍为`design_preregistered_runtime_not_implemented`；未创建`artifacts/v23/`或design manifest，未实现runtime，未运行pilot/GPU/API/victim/Retriever，未提交或推送。

当前唯一下一步：对 design r5 执行新的无上下文 reader test。只有在科学协议、泄漏边界和identity链闭合后才生成design manifest并结束设计阶段；纯实现偏好不再推动升版。通过后才等待用户单独授权runtime与定向测试。

### 2026-08-13：v23 Restoration-First design r6 bounded closure

- 第五轮无上下文reader test对design r5给出`REQUEST_CHANGES`；r5未生成design manifest，不得回写为passed。5个实质阻断项是：P0缺少backend维度；aggregate-DF“唯一全池读取”与每个selector stage重算冲突；首个runtime bundle授权存在identity循环且fresh audit未按实际扫描source计费；audit->release->retrieval->response->evaluation的canonical文件hash链仍有断点；BM25直接迭代`set`会使浮点累加顺序不确定。
- 用户明确授权执行r6。设计身份升级为`pcv-restoration-first-v23-design-r6`，仅修复上述5项；fact extraction、Restoration hard gates、3-pair selector、超几何容量门禁和fresh human audit门槛均未改变。v23 fact提取仍只属于设计冻结，runtime/定向测试/pilot尚未执行，不得写成实际质量passed。
- P0现唯一规定`source_pvs(dataset, backend, source)`：dense、BM25、hybrid分别计算逐数据集AUC/CI/低FPR和各自macro，禁止跨backend平均、池化或拼接主分。共享LLM-only仍仅作机制对照。
- aggregate DF改为每个runtime bundle/dataset恰好一次有预算全池读取；后续selector stage只验证输入identity及DF rows/manifest完整文件hash。首个bundle/genesis改用独立单次bootstrap authorization/attempt/checkpoint，普通protocol revision与run authorization只能在bundle产生后创建；fresh audit按每个实际reserve selector evaluation读取前扣费，最多250 source/dataset。
- canonical链现绑定formal selected-pair、audit packet/reviewer/adjudicator/final labels、split、shadow、release、query、retrieval、12个response manifest共144,000 rows、evaluation input、parsed/source scores及evaluation manifest。BM25 query tokens去重后按Python字典序累加，禁止`set`迭代。
- r6仍为`design_preregistered_runtime_not_implemented`。未创建`artifacts/v23/`或design manifest，未实现runtime，未运行pilot/GPU/API/victim/Retriever，未提交或推送。

当前唯一下一步：对design r6执行一次仅覆盖上述5项的独立reader test；通过后生成design manifest并结束设计阶段。若未通过，停在r6记录残余风险并由用户决定，不自动创建r7。

### 2026-08-13：v23 design r6 reader-test PASS

- 限定范围无上下文reader test判定`PASS`，确认r5的5个阻断项均已闭合；fact extraction与Restoration hard gates未受r6修改。
- design r6已生成只绑定设计配置、预注册、reader-test结论与23个冻结上游文件的`configs/restoration_first_v23.design_manifest.json`，manifest SHA-256=`6a7163830f36b65247b7d6222f5adecfb18c85695a885cc0384128c81ffbd6fe`；config SHA-256=`5c3c74c9af80c0c095c92c9e9f20fc618e80195c8c4e0c74f80162501dac0cc0`，预注册SHA-256=`aea0b5eb858b58a079491e37a6f58d806a35a54b146d33d6aa79e75749139cd1`。这只表示设计阶段完成，不表示runtime、fact实际质量、pilot或任何下游passed。
- 本轮外部调用、API、victim、Retriever和GPU任务均为0；未创建`artifacts/v23/`，未提交或推送。

当前唯一下一步：等待用户单独授权实现v23 runtime与定向测试；实现授权不包含pilot、GPU、API、victim、Retriever、提交或推送。

### 2026-08-13：v23 前旧实现与可再生 payload 清理

- 用户授权清理 v23 之前的旧产物、未使用旧配置和旧代码，并明确要求保留 `gliner2-large-v1`、`gliner-biomed-large-v1.0` 与 spaCy `en_core_web_trf-3.8.0-data`；本次也保留当前 `gliner2-base-v1`。`models/` 与 `datasets/` 均未删除任何文件。
- 删除20个已被后续协议取代、未提交且不再被当前入口使用的v21/r4配置、脚本、实现和测试，约229 KiB；保留仍被现有v21验证/审计链使用的 `entity_policy_audit_schema.py`、`entity_policy_release.py`、`entity_policy_validation.py`、`34_validate_v21_entity_policy.py` 与对应测试。未覆盖、回滚、stash或提交既有脏工作树。
- 删除541个v21可再生大型candidate/query/cache/replay payload，共`3,783,866,168` bytes（`3.524 GiB`）；删除清单SHA-256=`4802fe9a4702d5a96102bd2ecfc41ecfc59384b311862443254d21d52a578c6d`。失败、暂停、superseded、status、manifest、report、evaluation、audit、decision和label等研究证据全部保留。
- 进一步删除53个v22可再生展开payload：12个pilot `pair_candidates.jsonl`、r3的2个合并context candidate文件及39个batch JSONL，共`247,429,177` bytes（`235.967 MiB`）；删除清单SHA-256=`45ef2078d5dc9325cdb9d85eb5f62dc9ed900ae3f9800a4666571b4b8303b1db`。对应scan plan/checkpoint、wave manifest、source results、selected pairs、calibration plan、labels和`failed_final_calibration_revision` evaluation均保留。
- 两轮artifact清理合计删除594个可再生payload、释放`4,031,295,345` bytes（约`3.754 GiB`）。这些payload不可直接恢复，只能使用保留的旧输入、代码身份、plan/manifest/hash和原流程重算；这不改变任何历史passed/failed结论，也不把旧artifact迁入v23 selection。
- 清理后`artifacts/v21`=`3,077,624,155` bytes（`2.866 GiB`），`artifacts/v22`=`2,755,839,771` bytes（`2.567 GiB`）。其中v23显式绑定的三套完整source与三套source-pool SQLite约`4.726 GiB`，不能继续删除；剩余v22非source-pool文件最大不足1 MiB，主要为selected pairs、labels和审计证据，继续清理收益小且会损害复现。
- 清理后重新核验v23 design manifest SHA-256仍为`6a7163830f36b65247b7d6222f5adecfb18c85695a885cc0384128c81ffbd6fe`，23个冻结上游文件全部存在且SHA-256匹配。四套本地实体模型共`5,234,799,614` bytes（`4.875 GiB`），均完整保留；未创建`artifacts/v23/`，未调用API、GPU、victim或Retriever，未提交或推送。

当前唯一下一步仍是：等待用户单独授权实现v23 runtime与定向测试；清理授权不构成pilot、GPU、API、victim、Retriever、提交或推送授权。

### 2026-08-13：v23 runtime 实现与离线定向测试完成

- 用户已明确授权“实现v23 runtime与定向测试”。已生成只覆盖5个实现/测试文件与两份项目总表、且`external_calls_allowed=false`的implementation authorization：`artifacts/v23/governance/implementation_authorizations/5c191b1b132a7376c152014c896bf8c4b0295ab46dadd39dce58ff0dff19751d.json`。该授权不构成runtime bundle、正式source读取、pilot、GPU、API、victim、Retriever、提交或推送授权。
- 已实现`src/attack/restoration_first_v23.py`、`src/prepare/restoration_first_v23.py`、`src/evaluation/restoration_first_v23.py`与`scripts/42_run_v23_restoration_first.py`。覆盖递归exact selector schema、禁止downstream信号、fresh entity/fact extraction adapter、Restoration hard gates、17项确定性rank与stable top-3、aggregate DF、容量门禁、blind audit、source-exclusive split、strict query/response parser、逐backend source PVS/AUC/低FPR/bootstrap/BM25，以及runtime bundle/authorization/ledger/checkpoint/hash-chain治理原语。
- 最终静态复核额外闭合3个治理缺口：attempt registry row必须通过自身hash；reservation必须严格绑定stage/role/attempt/prior-tip并在任何ledger写入前整体预检预算；reserved source读取必须绑定完整durable batch anchor，formal registration不重复扣费，development/fresh-audit selector读取在内容可见前扣费。崩溃恢复只接受同一batch identity的完整durable prefix；预算已扣但无durable row、prefix漂移或anchor漂移均fail closed。fact extraction、Restoration hard gates、配置和design manifest均未改动，未创建r7。
- 使用唯一Conda解释器`D:\python\anaconda\envs\mia_model\python.exe -B`完成24/24项v23定向测试与443/443项全量`unittest`回归；5个实现/测试文件内存AST编译、`git diff --check`、CLI `validate-design`和`validate-implementation-authorization`均通过。`ruff`当前环境未安装，本轮未联网安装依赖。
- 最终CLI状态为`runtime_implemented_unfrozen`：design manifest SHA-256仍为`6a7163830f36b65247b7d6222f5adecfb18c85695a885cc0384128c81ffbd6fe`，23个冻结上游文件全部存在且hash匹配；`runtime_bundle_frozen=false`、`pilot_started=false`、`external_calls_performed=0`。没有创建runtime bundle、consumption-ledger genesis、aggregate-DF、pilot、audit、formal、split、release、query、response或evaluation artifact，未提交或推送。

当前唯一下一步：等待用户另行授权`runtime_bundle_and_commit_freeze`的bootstrap。只有bundle/genesis冻结后，才能再按dataset/stage签发独立run authorization；aggregate-DF、development pilot、GPU、API、victim与Retriever仍分别blocked，不能由本次实现授权推导。

### 2026-08-13：v23 bootstrap 事务实现与离线回归完成

- 在不读取正式 source pool、aggregate-DF、模型权重/GPU、API、victim 或 Retriever 的前提下，补齐首个 `runtime_bundle_and_commit_freeze` bootstrap 事务：独立 bootstrap authorization、单次 attempt registry、runtime bundle manifest、protocol revision ordinal 0、唯一 ledger genesis、genesis anchor 与 bootstrap checkpoint；写入顺序和 post-validation 均 fail closed，半产物不可覆盖或自动清理。
- bootstrap preflight 只核验 design r6 identity、冻结 v22/source-order 哈希常量、runtime closure 与提交后 HEAD 对照，以及 GLiNER2 base lock/tokenizer 小文件 hash、NumPy PCG64(42) state golden hash；不加载模型、不扫描 833MB 权重、不生成完整 bootstrap tensor。
- 新增 CLI：`prepare-bootstrap-authorization`、`bootstrap`、`validate-bootstrap`。授权原话可记录为用户本轮的“开始吧”，但必须由 bootstrap 命令显式消费；`external_calls_allowed=false`，不推导任何 pilot/GPU/API/victim/Retriever 权限。
- 新增合成 Git 仓库闭环测试 7 项，覆盖成功闭环、无授权、重复/已有产物、code commit drift、model lock/hash drift、partial artifact 与 post-validation 篡改；v23 定向测试 `31/31` 通过，全量 `unittest discover -s tests` `450/450` 通过，`git diff --check` 通过。
- 当前 CLI 状态仍为 `runtime_implemented_unfrozen`：`runtime_bundle_frozen=false`、`pilot_started=false`、`external_calls_performed=0`，未创建真实 `artifacts/v23` bundle/genesis，未读取正式 source pool，未提交或推送。

当前唯一下一步：按用户已给出的边界，先列出待提交 v23 文件清单和提交信息，等待用户明确确认后才提交；确认并提交完成后，使用用户本轮“开始吧”的现有授权只执行一次 bootstrap。bootstrap 之后 aggregate-DF 仍需独立 run authorization，其余 pilot、audit、formal、split、shadow、release、Luna、Gemma、Retriever 继续 blocked。

### 2026-08-13：v23 runtime bootstrap 已冻结并验证

- 用户确认后已将10个v23协议/runtime/测试及项目总表文件提交为`c05a088f887471bc825aab6acdbeaf2e34fbe917`（`feat(v23): implement restoration-first runtime`），未推送，其他既有脏工作树未纳入提交。
- 使用一次性bootstrap authorization `d06e6cfda9062c0423bb80d490130ca53e0e49c253330d7a8744ecddeab964d3`执行唯一一次`runtime_bundle_and_commit_freeze`；attempt ID=`7823debf3821ffbe2bb8a1a88e8e6cfd17bd32e50add571ed755a3f050a6cdcd`，状态`passed`，授权已消费。
- runtime bundle已冻结：bundle SHA-256=`272bd6faa36f2923dceeefde000b46caba9efe852d44bc62065401bc8053a7c7`，bundle manifest文件SHA-256=`aa1e6609c2291b021f1464f5695a0b444421b1371715da74279a770f7a4073ce`，protocol revision ID=`e5a870133c1548be34dcb2727f8324e0e413dfc48f7c66fe9aa8c6d6b9f2d655`。
- ledger genesis row SHA-256=`41a77b70c2609b369e4b91eec89267cd541b7c72b508dac05f23155f8966f57e`，genesis anchor SHA-256=`c767aaa17d22dda0ce39494cde1784ed87a8ea9e056ce2b8040aa0514fe7a791`；bootstrap checkpoint=`artifacts/v23/checkpoints/bootstrap/7823debf3821ffbe2bb8a1a88e8e6cfd17bd32e50add571ed755a3f050a6cdcd.json`，checkpoint状态`passed`。
- `validate-bootstrap`与`status`均通过，当前状态为`runtime_frozen_downstream_blocked`。本次`source_pool_contents_read=false`、`pilot_started=false`、`external_calls_performed=0`；未加载模型，未运行GPU、API、victim或Retriever。
- bootstrap只解除了runtime bundle/genesis冻结本身的阻断。aggregate-DF尚未创建，三套dataset必须各自获得独立run authorization后，才允许各进行一次有预算的完整池读取；development pilot及audit、formal、split、shadow、release、Luna、Gemma、Retriever和evaluation继续blocked。

当前唯一下一步：等待用户选择并单独授权首个dataset的`aggregate_df_precomputation`。建议按冻结顺序从EDGAR开始；该授权仅允许EDGAR在当前runtime bundle下进行一次aggregate-DF读取与产物写入，不包含Enron/PubMed、pilot、GPU、API、victim或Retriever。

### 2026-08-13：EDGAR aggregate-DF 授权后的执行入口阻断

- 用户已明确授权执行EDGAR的`aggregate_df_precomputation`，并要求由用户本人运行长时间命令；该授权不扩展到Enron/PubMed、pilot、GPU、API、victim、Retriever或其他下游阶段。
- 启动前只读核验发现当前已提交并冻结的CLI仅包含bootstrap/status/design/implementation验证入口。runtime内已有aggregate DF计算、只读source-pool reader、逐source预算扣费、run-authorization验证、attempt registry、artifact writer与checkpoint原语，但没有把它们闭合为真实EDGAR stage事务的授权生成、输入identity、exactly-once检查、失败/完成checkpoint、resume规则及CLI执行/验证入口。
- 因此EDGAR完整池尚未读取，run authorization/attempt尚未生成，aggregate-DF artifact尚不存在，预算扣费为0。禁止用临时`python -c`拼接这些原语：该编排不在冻结runtime bundle内，无法形成可审计的代码身份，并可能破坏exactly-once与崩溃恢复边界。
- 补齐runner会修改当前runtime bundle已绑定的`scripts/42_run_v23_restoration_first.py`与`src/prepare/restoration_first_v23.py`，不能继续冒充bundle `272bd6fa...a7c7`或revision `e5a87013...d655`。必须先获得单独实现授权，完成定向回归，并按新代码commit冻结新的runtime bundle/protocol revision；原bootstrap与本次阻断证据保留。

当前唯一下一步：等待用户授权最小补齐`aggregate_df_precomputation`真实runner与定向测试；实现完成后仍需用户确认提交/新bundle冻结，再使用本次EDGAR执行授权生成单次run authorization，并把最终长命令交给用户执行。

### 2026-08-13：v23 aggregate-DF runner 与 successor freeze 离线闭环

- 已按用户授权最小补齐 `aggregate_df_precomputation` 的正式授权准备、执行、验证与 CLI 入口，并实现 successor runtime freeze。该变更不创建 r7、不修改 design-r6、fact extraction、Restoration hard gates、selector 目标或 P0 统计定义。
- successor freeze 保留 revision 0、首个 runtime bundle、ledger genesis 与 genesis anchor，使用新 commit 生成后继 runtime bundle/protocol revision；旧 bootstrap 历史不覆盖、不重建。aggregate-DF 继续固定 EDGAR -> Enron -> PubMed 顺序，并要求每个 dataset 独立 authorization/attempt。
- aggregate-DF 在准备和执行前核验 active runtime、design identity，以及 source-pool manifest、SQLite database、source order 三个绑定文件的 SHA-256；执行前要求 ledger 仍为 genesis-only。逐 source 先扣预算再读取，只读 SQLite、流式计算 boolean token DF，输出不含 source mapping 或逐 source 行；失败 checkpoint 与已有输出均阻止同 attempt 重跑。
- 新增定向回归覆盖成功、exactly-once、dataset/order、预算、ledger 不变、Ctrl+C、失败不可复用、artifact/budget 篡改以及 runtime/pool hash 漂移。v23 governance `24/24`、全量 `unittest discover -s tests` `456/456`、内存 AST 与 `git diff --check` 均通过；敏感值扫描无命中。
- 本轮只使用合成临时仓库/SQLite fixture。真实 EDGAR source pool 未读取，未生成 EDGAR authorization/attempt/DF/checkpoint，外部调用、GPU、API、victim、Retriever 与费用均为 0；Enron/PubMed、pilot 及全部下游仍 blocked。

当前唯一下一步：向用户展示本轮精确代码提交范围并等待确认。确认后才允许提交并冻结 successor runtime；随后才能使用既有 EDGAR 执行授权生成单次 run authorization，把长时间 `aggregate-df --dataset edgar` 命令交由用户本人执行。提交确认不扩展到真实完整池读取或其他阶段。

### 2026-08-13：v23 successor runtime revision 2 冻结

- 用户确认后提交本轮 3 个 runner/runtime/test 文件，commit=`7d82ea4f530ba4d0f80e0b69bf93a7f04e1c5587`，未推送且未带入其他脏改动。
- 提交后发现 `status` 仍报告 bootstrap revision 0；这是状态读取 bug，不是协议或实验结果问题。仅补充 `v23_status` 的 active-lineage 读取和一个回归测试，commit=`f00205f1933863357458f5741ab8bf9115e56126`；v23 governance `25/25`、全量 `457/457` 通过。
- 使用 successor freeze authorization `427e7a66...e756` 冻结 revision 2：runtime bundle=`c1e61ac5b9902b2b6a8e6922151e67ca03a9c13463ad195cb107f20d237285ea`，protocol revision=`286e1f0a1c0dff1db917ea00a387192b8cbded7b3577e57d3cc86b4847524621`。revision 0=`e5a870...d655`、revision 1=`be18b6...5f2f`、bootstrap genesis 与 ledger tip=`41a77b...f57e` 均原样保留。
- `status` 与 successor validator 均通过；当前仍为 `runtime_frozen_downstream_blocked`，`external_calls_performed=0`、`source_pool_contents_read=false`、`pilot_started=false`。本轮未读取 EDGAR、未创建 aggregate-DF artifact，未运行 GPU/API/victim/Retriever。

当前唯一下一步：使用既有 EDGAR 执行授权，在 revision 2 下生成一次性 `aggregate_df_precomputation` run authorization，并把最终长命令交由用户本人执行；该动作不授权 Enron/PubMed、pilot 或任何下游阶段。

### 2026-08-13：EDGAR aggregate-DF 一次性 run authorization 已生成

- 已在 active revision 2 / runtime bundle `c1e61ac5...85ea` 下生成 EDGAR 独立 run authorization：authorization=`0e63f9b0...045e`，attempt=`7f4be98e...84ad`，protocol revision=`286e1f0a...4621`。
- 授权范围仅为 `aggregate_df_precomputation`、`execution_unit=one_dataset`、`datasets=[edgar]`，预算上限=`5210` sources；expected prior ledger tip 仍为 genesis `41a77b70...f57e`。授权生成只验证 runtime/pool binding/hash，`source_pool_contents_read=false`、external calls=0。
- 最终长命令必须由用户本人执行；助手不代跑、不改成临时编排。执行中每个 source 先扣预算再读，Ctrl+C/异常会写 failed checkpoint，同一 attempt 不可重跑；完成后只能运行正式 `validate-aggregate-df --dataset edgar` 验证。

当前唯一下一步：用户执行一次性 EDGAR aggregate-DF 命令。Enron/PubMed、pilot、fresh audit、formal、split、shadow、release、Luna、Gemma、Retriever 与 evaluation 继续 blocked。

### 2026-08-13：EDGAR aggregate-DF 完成并通过验证

- 用户本人按 revision 2 授权完成一次 `aggregate_df_precomputation`，随后运行正式 `validate-aggregate-df --dataset edgar`；两步均返回 `status=passed`。
- attempt=`7f4be98e2bdab16f4dccdbac6b55140f7e5867b351b92033a457f10cfa384ad6`，authorization=`0e63f9b0454555ec4acb72824199c124e930b14b34306e9a031e61b76244045e`，runtime bundle=`c1e61ac5b9902b2b6a8e6922151e67ca03a9c13463ad195cb107f20d237285ea`，protocol revision=`286e1f0a1c0dff1db917ea00a387192b8cbded7b3577e57d3cc86b4847524621`。
- 完整读取 `source_count=5210`，`token_count=116953`，预算扣费=`5210`；`external_calls_performed=0`、`ledger_mutation=false`。DF manifest SHA-256=`aeb7af6c0b776566cfd782168e7e125ad92b0faaa76bdf75088aa471ec52fdf6`，token DF rows SHA-256=`add48dd0dc818b94e98735f48b45cc27059d4e8a5f918c6d1524fe0e2b58e27f`。
- 该 artifact 仅为 dataset-level aggregate token DF，不含 source 映射或逐 source 行；不得据此声称低频 token 不可反演。EDGAR aggregate-DF 已完成且不得同 attempt 重跑；Enron/PubMed 仍需各自独立授权。development pilot、fresh audit、formal scan、split、shadow、release、Luna、Gemma、Retriever 与 evaluation 继续 blocked。

当前唯一下一步：等待用户单独授权 Enron `aggregate_df_precomputation`；未获授权前不生成 Enron authorization、不读取 Enron source pool，也不启动任何下游阶段。

### 2026-08-13：Enron aggregate-DF 一次性 run authorization 已生成

- 用户已单独授权 Enron `aggregate_df_precomputation`，授权不包含 PubMed、GPU、API、victim、Retriever 或任何下游阶段。
- 已在 active revision 2 / runtime bundle `c1e61ac5b9902b2b6a8e6922151e67ca03a9c13463ad195cb107f20d237285ea` 下生成独立 authorization=`c01e5d8d558e9896e164d659fca7ea59601af228d812646b24fa951e27f07004` 与 attempt=`ddff63f66a249a9b281dffcbbee18091981d0e421ffc8710a0629a5b728168f5`；protocol revision=`286e1f0a1c0dff1db917ea00a387192b8cbded7b3577e57d3cc86b4847524621`。
- 授权范围为 `datasets=[enron]`、`execution_unit=one_dataset`、预算上限=`35000` sources；expected prior ledger tip 仍为 genesis `41a77b70...f57e`。授权生成未读取 source 内容，`source_pool_contents_read=false`、external calls=0。

当前唯一下一步：用户本人执行一次性 Enron aggregate-DF 长命令并回报结果；完成并验证前不得生成 PubMed authorization，也不得启动 pilot 或任何下游阶段。

### 2026-08-14：Enron aggregate-DF 完成并通过验证

- 用户本人已完成一次 Enron `aggregate_df_precomputation`，随后运行正式 `validate-aggregate-df --dataset enron`；验证返回 `status=passed`。
- attempt=`ddff63f66a249a9b281dffcbbee18091981d0e421ffc8710a0629a5b728168f5`，authorization=`c01e5d8d558e9896e164d659fca7ea59601af228d812646b24fa951e27f07004`，runtime bundle=`c1e61ac5b9902b2b6a8e6922151e67ca03a9c13463ad195cb107f20d237285ea`，protocol revision=`286e1f0a1c0dff1db917ea00a387192b8cbded7b3577e57d3cc86b4847524621`。
- 完整读取 `source_count=35000`，`token_count=181394`，预算扣费=`35000`；`external_calls_performed=0`、`ledger_mutation=false`。DF manifest SHA-256=`703b1756137aa0bdb9ca06e0e1416a12f884e4f6a5591fe6a120bb136d5526b5`，token DF rows SHA-256=`18c6df70e5a6236eb96292061d1d1ee33caef6f721acbc628200b08aece43fdc`。
- Enron aggregate-DF 已完成且不得同 attempt 重跑。当前 EDGAR 与 Enron 均已 passed；PubMed 仍需独立授权。development pilot、fresh audit、formal scan、split、shadow、release、Luna、Gemma、Retriever 与 evaluation 继续 blocked。

当前唯一下一步：等待用户单独授权 PubMed `aggregate_df_precomputation`；未获授权前不生成 PubMed authorization、不读取 PubMed source pool，也不启动任何下游阶段。

### 2026-08-14：PubMed aggregate-DF 一次性 run authorization 已生成

- 用户已单独授权 PubMed `aggregate_df_precomputation`，并指定长时间命令由用户本人执行；授权不包含 development pilot、GPU、API、victim、Retriever 或任何下游阶段。
- 已在 active revision 2 / runtime bundle `c1e61ac5b9902b2b6a8e6922151e67ca03a9c13463ad195cb107f20d237285ea` 下生成独立 authorization=`52f4a84e672139793aa712f7a81b6b2901a737f667273ab2745637bef744fc7f` 与 attempt=`43ff2d69b284014d3702e9fdb5de9237ca5b5ad6ee78a242e605c98127a7bb53`；protocol revision=`286e1f0a1c0dff1db917ea00a387192b8cbded7b3577e57d3cc86b4847524621`。
- 授权范围为 `datasets=[pubmed]`、`execution_unit=one_dataset`、预算上限=`47950` sources；expected prior ledger tip 仍为 genesis `41a77b70...f57e`。授权生成未读取 PubMed source 内容，`source_pool_contents_read=false`、`external_calls_performed=0`。
- 依据预算日志，EDGAR 5210 sources 实测约 5 分钟，Enron 35000 sources 实测约 2 小时 6 分钟。PubMed 有 47950 sources，且数据库约 2.16 GB、明显大于另两套；当前逐 source 哈希链验证会随进度增长，因此不能按 source 数线性外推。执行时间暂估 5--8 小时，保守应预留 8--12 小时；该区间不是完成时间承诺。

当前唯一下一步：用户本人执行一次性 PubMed aggregate-DF 长命令，完成后运行正式 validator。运行期间不要主动中断；失败 checkpoint 会使同一 attempt 不可重用。PubMed 验证通过前，development pilot、fresh audit、formal scan、split、shadow、release、Luna、Gemma、Retriever 与 evaluation 继续 blocked。

### 2026-08-14：PubMed aggregate-DF 完成并在冻结 runtime 身份下通过验证

- 用户本人完成 PubMed `aggregate_df_precomputation`。任务在写出 manifest 与 `passed` checkpoint 后进入末尾自校验，但运行期间仓库新增了 `109352e0...a00` 与 `5099fbf8...6b4` 两个 closure 外提交，当前 `HEAD` 不再等于冻结 commit `f00205f1...6126`，因此主工作区末尾报 `active_runtime_commit_drift`。这不是 source 处理、token-DF 或预算链失败。
- PubMed artifact 与治理链完整：attempt=`43ff2d69...bb53`、authorization=`52f4a84e...4fc7f`、`source_count=47950`、`token_count=1284757`、预算日志恰为47950行且末行序号47949、checkpoint=`status=passed`、`external_calls_performed=0`、`ledger_mutation=false`。DF manifest SHA-256=`8418d7372590966dcdc4f7e9e23b1b3b7ac7fadce589ca5b492a58393658b043`，token DF rows SHA-256=`75955e537cfb9619bb302eea8668f16afc85f5d784b4b607eb7abe796f2e7f8e`。
- 只读核验确认 active bundle 的19个 runtime closure 文件在主工作区均未修改且文件SHA-256仍与bundle manifest一致；新增提交仅涉及closure外的实体审计实现/测试与README。为避免修改冻结runtime、创建新bundle或重读三套完整池，建立独立detached worktree `D:\MIA\mia_model_v23_runtime_r2` 固定到`f00205f1...6126`，并通过Git identity overlay让原runtime在主项目路径验证原artifact。
- 新增非runtime-closure操作入口`scripts/run_v23_frozen_runtime.ps1`；它先核验detached worktree commit，再临时绑定`GIT_DIR/GIT_WORK_TREE`并调用原冻结`scripts/42_run_v23_restoration_first.py`，调用结束后恢复环境变量。该入口不修改bundle、protocol revision、design-r6或immutable artifact。
- 使用冻结入口重新执行PubMed正式validator，返回`status=passed`，runtime bundle仍为`c1e61ac5...85ea`，protocol revision仍为`286e1f0a...4621`。至此EDGAR、Enron、PubMed三套aggregate-DF均完成并通过验证；所有三个attempt均不得重跑。本次恢复验证未读取source pool、未调用GPU/API/victim/Retriever，也未产生费用。

当前唯一下一步：等待用户单独授权`revision_audit_reserve_snapshot_and_write_ahead_registration`与`development_pilot_and_capacity_gate`的明确执行范围。首次真实fact extraction与Restoration质量门禁将在development pilot发生；获得该授权前，pilot、fresh audit、formal scan、split、shadow、release、Luna、四个Generator、Retriever、victim与evaluation继续blocked。

### 2026-08-14：development pilot 启动前发现正式 runner 缺口

- 用户回复“进行下一步吧”，授权推进当前唯一下一步的准备；该表述未扩大为GPU长任务、API、victim或Retriever调用授权。本轮仅执行冻结入口`status`与代码/配置只读核验，未写consumption ledger、attempt、authorization、budget、reserve snapshot或stage checkpoint，未读取新的source内容，GPU/API/victim/Retriever调用均为0。
- 冻结runtime已实现`append_reservation_batch`、`FrozenSourcePoolReader.read_reserved_source`、fresh fact/entity extraction、Restoration hard gates、top-3 selection与capacity decision等原语，但`scripts/42_run_v23_restoration_first.py`没有`revision_audit_reserve_snapshot_and_write_ahead_registration`或`development_pilot_and_capacity_gate`的prepare/run/validate CLI，`src/prepare/restoration_first_v23.py`也没有对应完整事务runner。
- 因而不能直接启动reserve write-ahead或pilot。用临时`python -c`、非runtime-closure脚本或手工拼接通用原语会重复EDGAR aggregate-DF启动前已经拒绝的未绑定编排问题：无法把执行顺序、group completion、失败checkpoint、exactly-once与恢复语义绑定到冻结runtime身份。
- 直接补runner会修改active runtime closure，必须冻结successor bundle；当前design-r6又要求aggregate-DF按runtime bundle绑定，所以严格沿用现有设计将要求在新bundle下重新授权并重跑EDGAR、Enron、PubMed aggregate-DF。若要复用现有三套DF，则必须先制定机器可读的stage-scoped compatibility/carry-forward erratum并改变协议身份，不能静默放宽runtime binding。

当前唯一下一步：由用户在两条路径中明确选择。路径A保持现有design-r6不变：实现reserve/pilot runner、提交并冻结successor runtime，再按新bundle重新执行三套aggregate-DF；路径B先制定并审计一个显式execution erratum，允许在计算相关closure完全相同的证明下carry forward现有DF，再实现runner。选择前不写ledger、不创建reserve/pilot authorization、不启动GPU或source读取。

### 2026-08-14：v23 Stage-Scoped Identity execution erratum e1 已实现，待提交与冻结

- 用户明确选择路径B并授权实施 `v23 Stage-Scoped Identity 修复计划`。本轮身份为 `pcv-restoration-first-v23-design-r6-execution-e1`，不是方法 r7；没有修改 fact extraction、Restoration hard gates、rank、query 或统计定义。
- 新增机器可读 erratum `configs/restoration_first_v23.execution_erratum_e1.yaml`，SHA-256=`4245105e0058a3f8e326f7f1e57175665a2199a1e9ca82bc82402c477b08c279`。其中冻结完整 stage DAG 与变更传播矩阵：Luna query 变化传播到 retrieval/RAG/LLM-only/evaluation；Retriever/index 变化不失效 query 或 LLM-only；parser/scoring 只失效 evaluation。
- 新增 `src/utils/stage_identity.py`：Python 依赖可按整文件或指定 symbol 计算规范化 AST hash并忽略注释、格式、模块/类/函数 docstring；配置只哈希指定 YAML 子树；data/model/upstream artifact 可绑定精确文件 SHA-256。缺失 symbol、未知依赖、非法路径、未知 change class、DAG 环、缺失 runtime field或文件 loader均fail closed。
- aggregate-DF fingerprint只绑定分词/归一化/DF与序列化逻辑、只读pool reader相关symbol、三套`frozen_v22_bindings.source_pools` identity和Python版本；fact extraction、Restoration、rank、reserve/pilot runner、CLI、README与研究记录不进入该fingerprint。合成测试确认fact extraction或pilot-only symbol变化不改变aggregate fingerprint，而分词/DF算法、YAML tokenization或任一pool hash变化会改变fingerprint并传播到全部下游。
- runtime新增`stage-status`、`prepare-carry-forward-authorization`、`carry-forward`和`validate-carry-forward`；`validate-aggregate-df`支持producer bundle下`native`验证，以及successor bundle下经显式attestation的`carried_forward`验证。证明自哈希并绑定旧/新bundle、旧/新revision、两端stage execution identity、共同fingerprint、三套DF rows/manifest、各自run authorization/budget/checkpoint、ledger tip及anchor；任何不完整dataset group、错误bundle/fingerprint、artifact篡改或缺失budget/checkpoint均拒绝。
- 本轮implementation authorization=`5036ed6f6df487454cee07bd56ace243d3199b6462ba90585bff34d1ed82245c`，只覆盖README、erratum、stage identity、runtime/CLI/test与两份项目总表，`external_calls_allowed=false`。该授权不包含successor freeze、真实carry-forward、reserve/pilot、GPU、API、victim、Retriever、提交或推送。
- 现有EDGAR、Enron、PubMed DF rows/manifest/authorization/budget/checkpoint与ledger均未修改；没有创建 `artifacts/v23/protocol/stage_compatibility/<new_revision>/aggregate_df_precomputation.json`，没有读取88,160个source，也没有新增预算扣费或ledger mutation。真实carry-forward只有在提交并冻结successor后，旧/新aggregate fingerprint完全相等且用户再次明确授权时才允许生成。
- 最终验证：v23定向测试`45/45`通过；全量`unittest discover -s tests`为`464/464`通过；内存AST、erratum固定hash、implementation authorization自哈希与scope、`git diff --check`均通过。测试仅使用mock或临时合成仓库/SQLite fixture，没有真实GPU/API/victim/Retriever调用。

当前唯一下一步：等待用户确认提交本轮e1实现。确认前不执行`git add`/`git commit`；提交后successor runtime freeze仍需单独授权，freeze完成后的真实三数据集DF carry-forward还需再次单独授权。carry-forward验证通过前不实现或启动reserve/pilot，也不读取新的source。

### 2026-08-14：v23 Stage-Scoped Identity execution erratum e1 已本地提交

- 用户确认后仅提交本轮8个e1文件；commit=`3010c19aa81c59ee4b1ec081752702d9ff32dcd4`，提交信息=`feat(v23): add stage-scoped runtime identity`。README与两份项目总表采用局部暂存，更早的未提交记录及`AGENTS.md`、root notes/task plan、legacy变更和冻结入口均未纳入。
- 提交未推送；暂存区为空。现有三套aggregate-DF、ledger、authorization、budget、checkpoint与历史artifact未改写，真实stage compatibility目录仍为空，source读取、ledger mutation、GPU/API/victim/Retriever调用和费用均为0。
- 本次提交确认不构成successor runtime freeze或真实carry-forward授权。只有另行授权并冻结successor后，才允许再次授权生成三数据集group carry-forward证明；fingerprint不相等时必须fail closed。

当前唯一下一步：等待用户单独授权successor runtime freeze。未获授权前不创建新bundle/revision、不生成真实carry-forward artifact，也不实现或启动reserve/pilot。

### 2026-08-15：successor runtime freeze revision 3 已通过

- 用户明确授权 successor runtime freeze。执行前发现 e1 的 `RUNTIME_BUNDLE_FILES` 顺序缺少规范字典序；仅修复该 closure 顺序并增加回归断言，commit=`32f9ba88c833f9ca7dbf7dd37967306d70061b29`，未纳入其他脏工作树文件。
- 新 authorization=`bb53ae708823d477fab8b4a7a0f0384a7903d9e54eb7f6d012645427fe79dc87`，目标 revision ordinal=`3`；freeze checkpoint=`artifacts/v23/checkpoints/runtime_freeze/bb53ae708823d477fab8b4a7a0f0384a7903d9e54eb7f6d012645427fe79dc87.json`。
- successor runtime bundle=`1c2c933d890f52e11ffa2e9d37ca2aede3a5037ff009656f9d8cf54763ea8cb8`，protocol revision=`7add7622b9bf76e1547a6ce98fa5178e0a6e9a26eb147fb3553a7b9b0ab54bff`；freeze 与独立 validate 均返回 `status=passed`。
- ledger tip 保持=`41a77b70c2609b369e4b91eec89267cd541b7c72b508dac05f23155f8966f57e`；`source_pool_contents_read=false`、`ledger_mutation=false`、`external_calls_performed=0`，没有读取 source、没有重跑 aggregate-DF、没有生成 carry-forward 证明。
- 三套 aggregate-DF 仍是旧 bundle/revision 下的既有 passed artifact；只有在用户另行授权且旧/新 fingerprint 完全相等时，才可生成显式三数据集 carry-forward attestation。reserve、pilot、fresh audit、formal、split、shadow、release、Luna、四个 Generator、Retriever、victim 与 evaluation 继续 blocked。

当前唯一下一步：等待用户单独授权 aggregate-DF stage carry-forward；授权前不写 compatibility artifact、不读取 source、不启动 reserve/pilot 或任何 GPU/API/victim/Retriever 阶段。

### 2026-08-15：三数据集 aggregate-DF carry-forward 已通过

- 用户明确授权 aggregate-DF 三数据集 group carry-forward。authorization=`e7e64dde111300ea13928a2345018d8d17ceefa1657cfad1e6a31ca664660ff7`，execution unit=`all_datasets_group`，禁止 source pool 内容读取、ledger mutation 与外部调用。
- 旧 revision 2 / bundle `286e1f0a...4621` / `c1e61ac5...85ea` 与新 revision 3 / bundle `7add7622...4bff` / `1c2c933d...8cb8` 的 aggregate-DF stage dependency fingerprint 完全一致：`9fc3c9d28016b5d3483ca414145c5a9a025d4ec4196ab9679525b8ae268c8011`。
- 已生成三数据集一体化 attestation=`c3f1b179571383751d6231c1175094d8b6fa6801abf4940a57dbcaf3b0a95db3`，文件 SHA-256=`24d7fa0df7baf4c180e76ae3d6bdf8f9f49c672d0d9de4c38d7ea0db5c127aba`；证明绑定三套既有 rows/manifest、run authorization、budget journal、checkpoint、ledger tip 及两端 stage execution identity。
- `validate-carry-forward` 与 EDGAR、Enron、PubMed 三次独立 `validate-aggregate-df` 均返回 `status=passed`、`validation_mode=carried_forward`。原 DF artifact 未改写，88,160 个 source 未重读，预算未新增，ledger tip 未变化，GPU/API/victim/Retriever 调用为 0。
- e1 的权威阶段状态 `stage-status --stage aggregate_df_precomputation` 返回 `status=passed`、stage=`carried_forward`、reason=`null`。旧 `status` 命令的 `blocked_stages` 仍是静态摘要并继续列出 aggregate-DF；该字段不参与 stage gate，不表示 carry-forward 失败，待下一次已授权的 runner runtime 修改时同步修正，避免仅为展示字段再次冻结 bundle。
- aggregate-DF 已在 active revision 3 下合法可复用；这不是重新计算，也不改变旧 artifact 的 producer identity。reserve/pilot runner 仍未实现，revision audit、development pilot、fresh audit、formal、split、shadow、release、Luna、四个 Generator、Retriever、victim 与 evaluation 继续 blocked。

当前唯一下一步：等待用户单独授权实现 revision-audit reserve snapshot/write-ahead 与 development-pilot runner 的 runtime/定向测试；实现授权不自动包含真实 reserve/pilot source 读取、GPU/API/victim/Retriever 或长任务执行。

### 2026-08-15：v23 reserve/write-ahead 与 development-pilot runner 离线实现

- 用户明确授权实现 `revision_audit_reserve_snapshot_and_write_ahead_registration` 与 `development_pilot_and_capacity_gate` runner；implementation authorization=`37dd6ce01efcda21bdfcfa48e9c8ab6f9444bd89a4f67930f6b8e5ff01f0e3d5`，仅覆盖 runtime、CLI、测试、README 与两份项目总表，`external_calls_allowed=false`。该授权不包含真实 reservation/pilot、source 读取、GPU、successor freeze、提交或推送。
- reservation runner 先验证三套 carried-forward aggregate-DF，从同一 prior ledger tip 推导并冻结三套 250-source reserve snapshot；首次 revision 按 EDGAR、Enron、PubMed 顺序登记三套既有 1000-source development batch，再按相同顺序登记 reserve batch。plan、batch、anchor、budget、group completion 与 checkpoint 全绑定；中断只接受同一 identity 的 durable prefix，完整 ledger rows 缺 anchor、completion 后缺 checkpoint 等崩溃窗口可恢复。
- reservation validator 不读取 source 内容，只核验 source order、snapshot、plan、ledger chain、batch anchor、budget operation、common prior、group completion 与 checkpoint；development 仍严格等于冻结 source order 的前 1000，reserve 必须与所有 prior/development raw hash、normalized hash 零重叠。
- development pilot 按 dataset 独立授权，固定读取已登记 development batch。每个 source 在内容可见前扣一次 logical source-evaluation budget，读取后再次核对 ledger raw/normalized hash；每条 source result 独立 fsync，预算已扣但结果未落盘时只恢复同一 operation，完整结果才允许跳过。生产 CLI 只加载冻结 `gliner2-base-v1` CUDA runtime；离线测试通过注入 selector，不加载模型或 GPU。
- 每个 source 使用同一 selector 输入重算两次并比较 canonical hash；正式链仍调用 `fresh_extract_candidates -> build_pair_candidates -> select_top_three`，fact extraction、Restoration hard gates、17项 rank 与 capacity 公式均未修改。token DF 完整验证一次后只跳过逐 candidate 的重复全表扫描；禁止 membership、split/group、victim/LLM-only response、Retriever 输出或 AUC 字段。
- 数据集 manifest 绑定 reservation completion、development anchor、aggregate-DF rows/manifest、模型 runtime identity、source-result group、selected-pairs 文件、budget/checkpoint 与 capacity decision。三数据集全部 passed 后才生成 group gate，并要求跨数据集 source hash 与 normalized text hash overlap 均为 0；capacity shortfall 写入 `failed_development_gate` 与 failed checkpoint，不能进入 fresh audit。
- 新增 CLI：`prepare/run/validate-revision-reservation`、`prepare/run/validate-development-pilot` 与 `validate-development-pilot-group`；`stage-status` 已能报告 reservation/pilot 的 `native/stale/not_started`。aggregate-DF stage fingerprint 仍精确为 `9fc3c9d28016b5d3483ca414145c5a9a025d4ec4196ab9679525b8ae268c8011`，现有三数据集 DF carry-forward 不失效。
- 离线合成测试覆盖 reservation partial-prefix 与缺 anchor 恢复、顺序/exactly-once、validator 零 source 读取、plan 篡改拒绝、pilot 预算已扣但无结果恢复、确定性复算、三数据集 group 零重叠、禁止字段篡改、capacity pass/fail 与 failed checkpoint。v23 定向回归 `49/49`、全量 `unittest discover -s tests` `468/468` 均通过；298 个 Python 文件内存 AST、CLI help、implementation authorization scope/self-hash、`git diff --check` 与敏感值扫描均通过。首次 AST 以 `utf-8` 读取未修改的 `src/utils/hash.py` 时遇到既有 BOM，按实际编码改用 `utf-8-sig` 后全量通过，未修改该文件。`ruff` 未安装且未联网安装。
- 本轮未执行真实 reservation 或 pilot，未读取新的正式 source，未修改真实 ledger/budget/checkpoint/selection artifact，未加载 GPU 模型，API/victim/Retriever/费用均为 0。当前代码尚未提交，active revision 3 对工作树新代码应继续 fail closed；不得直接运行真实新入口。

当前唯一下一步：等待用户确认提交本轮 runner。提交不等于 freeze；提交后仍需单独授权 successor runtime freeze，冻结完成后再单独授权真实 reservation/write-ahead 与逐数据集 development pilot。fresh audit、formal、split、shadow、release、Luna、四个 Generator、Retriever、victim 与 evaluation 继续 blocked。

### 2026-08-16 至 2026-08-17：v23 revision 4、reservation 与 EDGAR development pilot 授权

- 用户确认按收敛路线推进：提交并 freeze 当前实现，运行三数据集 reserve 与 development pilot，并严格按预注册门槛一次性判定 pass/fail；禁止查看 AUC 调参或无限版本迭代。长时间命令改由用户本人运行。
- reserve/pilot runner 已提交为 `4856e31da50e7316e0b5b298401739097df0d3e3`（`feat(v23): add reserve and development pilot runtime`），仅含 7 个授权范围文件，未推送且未纳入既有无关脏工作树。
- successor freeze authorization=`f07c7f3510be5a739793f01e7ac9b7c7efa71a701d510144a94c55f97e225fc6`；revision 4 runtime bundle=`bc5a81dead12db4c2ac3a333f926a6ea66bd65b0530035547c24b2ce2e298833`，protocol revision=`71e862b7591b2ac9bd1a1759b3784fc3b0e4b7286b96098d4997f0f173b78043`，freeze 与 validator 均 `passed`，外部调用为 0。
- aggregate-DF fingerprint 保持 `9fc3c9d28016b5d3483ca414145c5a9a025d4ec4196ab9679525b8ae268c8011`；authorization=`b8cd218a924107f744d1735f6614ec98c89a5c5811830cf1e06182b96d028199`、attestation=`7f37e1d3afd8b67667623cd886c40270641033fa5bc97406cd644b5dea98b6c8`、文件 SHA-256=`985b6ebd67dd590207518e2732efe07aa43d1fde9ed804236952a20af0e43912`。三套 DF 在 revision 4 下 `carried_forward`；未重读 source、未新增预算、未写 ledger。
- revision reservation authorization=`49ce6a80ed424e267a80c456c0acfecc414feffee99da6a35e6327de692c6965`、attempt=`73c1911799852a3f0ee8e67b2ae022ddb623de2ad65e84ecbd06a51b04931d5a`。首次由助手启动后，应用户要求在 ledger 已写入 1,652 条 source 前缀时停止；确认 ledger/budget 前缀一致并删除已终止 PID 遗留的三个 stale lock 后，由用户使用同一 authorization/attempt 恢复，没有生成新 attempt，也未把操作中断记作方法失败。
- reservation 执行与独立 validator 均 `passed`：EDGAR/Enron/PubMed development 各 1,000，fresh-audit reserve 各 250，budget charge=`3750`；common prior tip=`41a77b70...f57e`，final ledger tip=`3c912fd1...a8e1`，checkpoint SHA-256=`0c16fa63...75e2`，group completion SHA-256=`54983e73...4b17`，ledger mutation 已验证，外部调用为 0。
- CUDA preflight 通过：`mia_model` 环境为 PyTorch `2.11.0+cu130`，`torch.cuda.is_available()=True`，设备为 RTX 4060 Laptop GPU。冻结模型仍为本地 `fastino/gliner2-base-v1@f5b2ec...`，CUDA/fp16；这不是 Generator/victim，不调用 API。
- 已生成 EDGAR development pilot authorization=`a40eab77e95df4a9625e39921aaf641425f1715c5cc734f9ac61acc353a9a67d`、attempt=`385a242b02ff9fac40d90f444257fb669be27c42ba709f11c2c44b42043423ea`，预算为 1,000 sources。授权准备阶段未加载 GLiNER、未读取 development 正文、未扣 pilot 预算；正式命令由用户本人执行。

当前唯一下一步：用户本人运行 EDGAR `run-development-pilot` 并在完成后执行正式 validator。EDGAR 未通过前不签发 Enron/PubMed pilot authorization；fresh audit、formal、split、shadow、release、Luna、四个 Generator、Retriever、victim 与 evaluation 继续 blocked。

### 2026-08-17：EDGAR pilot revision 4 运行时类型错误与最小修复

- 用户首次启动 EDGAR development pilot 后，runner 在第一个 development source 的 pair candidate 构造阶段抛出 `ValueError: invalid literal for int() with base 10`。这是 operation/runtime failure，不是 `failed_development_gate`，没有 capacity、AUC、victim、LLM-only 或 Retriever 结果可供判定。
- 失败现场原样保留：authorization=`a40eab77e95df4a9625e39921aaf641425f1715c5cc734f9ac61acc353a9a67d`、attempt=`385a242b02ff9fac40d90f444257fb669be27c42ba709f11c2c44b42043423ea`；budget journal 已有 1 条 exact operation charge，source results=`0`，无 checkpoint，进程已退出且 lock 已由 context manager 移除。未删除、改写或伪造任何 partial artifact。
- 根因是冻结 v22 source pool 将 `source_order_rank` 存为 SHA-256 十六进制字符串，v23 selector source contract 同样声明为 `str`，但 pair artifact 构造错误使用十进制 `int(value)`；合成测试只使用可按十进制转换的 `"000001"`，未覆盖包含 `a-f` 的真实生产格式。
- 用户以“开始吧”明确授权最小 runtime 修复与离线验证，不包含提交、successor freeze、新 authorization、pilot resume、Enron/PubMed、API/victim/Retriever 或付费调用。工作树仅将转换改为 `int(value, 16)`，保持 design-r6、execution erratum e1、fact extraction、Restoration hard gates、17 项 rank、capacity 门槛与 canonical pair 的整数 schema 不变；非法非十六进制输入继续 fail closed。
- 新增真实 64 位十六进制 rank 回归；修复前该测试精确复现同一异常，修复后单测 `1/1`、selector tests `6/6`、完整 `tests.test_restoration_first_v23` `50/50` 与两个目标文件内存 AST 均通过。测试只使用离线/临时 fixture，未重读真实 EDGAR source、未加载 GPU 模型、未产生外部调用或新增真实预算。
- 用户确认继续验证与本地提交；全仓 `unittest discover -s tests` 为 `469/469` passed（`605.003s`），`src/`、`scripts/`、`tests/` 共 308 个 Python 文件内存 AST、敏感值扫描与 `git diff --check` 均通过。日志中的 timeout/API-key 文本均来自 mock 的预期失败路径，没有真实网络或 provider 调用。锁定 `mia_model` 环境未安装 `ruff`/`mypy`，未调用 PATH 上属于 Conda base 的同名可执行文件，也未联网安装依赖。
- active revision 4 / bundle `bc5a81de...9833` 仍是当前冻结身份；工作树修复不得配合旧 authorization 直接续跑。后续必须保留本次 partial evidence，并在提交与 successor freeze 后按新 bundle/revision 重新取得受控执行授权；是否可复用既有 reservation/aggregate-DF 只能由 stage-scoped identity 与显式 validator/authorization 决定，不能人工假定。

当前唯一下一步：仅提交本次代码与回归测试，不纳入其他脏工作树；提交不等于 successor freeze。提交后等待用户单独授权新 revision freeze，不重跑 EDGAR、不生成新 authorization、不启动 Enron/PubMed，也不修改或清理 revision 4 partial artifact。

### 2026-08-17：v23 source-order-rank 最小修复已本地提交

- 用户确认以 `fix(attack): parse v23 source order rank as hex` 提交；本地 commit=`e8f5a3f6cea68bfa87bbc37eb40c813f8ada254f`，仅包含 `src/attack/restoration_first_v23.py` 与 `tests/test_restoration_first_v23.py`，未推送，未纳入两份项目总表或其他既有脏工作树。
- 提交不改变 revision 4 partial evidence 的保留结论，也不构成 successor freeze、新 EDGAR authorization、pilot resume、Enron/PubMed、GPU/API/victim/Retriever 或付费调用授权；active revision 4 的旧 authorization 仍不得用于修复后的工作树。

当前唯一下一步：等待用户单独授权 successor runtime freeze；授权前不修改 runtime 身份、不生成新 EDGAR authorization、不运行任何 development pilot，并继续保留 revision 4 partial artifact。

### 2026-08-17：revision 5 freeze、aggregate-DF carry-forward 与 EDGAR authorization 阻断

- 用户明确授权 successor runtime freeze、stage fingerprint 验证与新 EDGAR authorization 准备；授权不包含运行 pilot、Enron/PubMed、API/victim/Retriever 或付费调用。successor freeze authorization=`71235950d7daea6133e316d5455344a6b4b5051e0470d94eb2176f339977ac38`（文件 SHA-256=`0e41de29d29792bc4e82b117e11e5a4af02c28cd354cc9dc6f452a67b7f63549`）。
- revision 5 freeze 与独立 validator 均 `passed`：HEAD/code commit=`e8f5a3f6cea68bfa87bbc37eb40c813f8ada254f`，runtime bundle=`439c2c14cfcfe9dac612794a7a734fdaa963bcdff222e2465b6ac2bd8eb40991`，protocol revision=`26cf914046ec36e7dc8714c302c5ef7f8e55dca988eeb8b8d8278df6a3876b2d`，revision ordinal=`5`，ledger tip 保持 `3c912fd1...a8e1`，external calls=`0`。freeze checkpoint SHA-256=`15a103b49067639e179ff56e89317f9ef5e163de52e5228b37338574369ba852`。
- execution erratum e1 只为可 carry-forward 的 `aggregate_df_precomputation` 定义 stage dependency fingerprint；revision 4 与 revision 5 均为 `9fc3c9d28016b5d3483ca414145c5a9a025d4ec4196ab9679525b8ae268c8011`。据此生成 authorization=`0e948bef13d7a910b351c8895375073233a71f9db530524e1629bead12b85de5` 并执行三数据集 carry-forward；独立 validator 返回 `passed/carried_forward`，attestation=`ef1e7d33d66f522fa57a7234922c998691d7393704027b043f2ee80689a03020`，文件 SHA-256=`c05bc3d3f04618d6f8b407878db18f0218a3f39cfe43e869b07ba738e9fc9394`。source reread=`0`、新增预算=`0`、ledger mutation=`false`、external calls=`0`。
- revision 5 的 reservation 是 revision-specific，当前 `stage-status` 为 `not_started/revision_reservation_group_missing`；e1 没有为 reservation 或 development pilot 定义可 carry-forward fingerprint。尝试通过官方入口生成新 EDGAR authorization 时，在任何 attempt/authorization 写入前由 `revision_reservation_authorization_count_invalid` fail closed；revision 5 run authorization 数量保持 `0`。
- 只读预检发现第二个后续阻断：revision 4 partial attempt 留下设计规定的非 revision-scoped 目录 `artifacts/v23/selection/development/edgar/source_results/`（0 个 result），而当前 `prepare_development_pilot_authorization` 对 `artifacts/v23/selection/development/edgar` 的任何存在都拒绝并返回 `development_pilot_attempt_or_artifact_already_exists`。不得删除/移动该 partial 目录、手工造 authorization 或绕过门禁；否则破坏失败证据与预注册路径语义。
- 当前无 Python 进程、无 governance lock；revision 4 reservation checkpoint/group completion 文件 SHA-256 仍为 `0c16fa63...75e2` / `54983e73...4b17`，旧 partial budget=`1`、source results=`0` 保持不变。未生成新的 EDGAR authorization，也未启动 reservation/pilot/Enron/PubMed。

当前唯一下一步：等待用户单独授权设计并实现“保留旧 partial evidence、允许新 revision development attempt”的最小恢复语义及回归测试；完成提交与再次 successor freeze 后，先按新 revision 生成/运行 reservation，再生成 EDGAR authorization。未获授权前不生成无用的 revision 5 reservation attempt，不清理旧目录，不运行任何 pilot。

### 2026-08-17：development recovery r1 最小恢复语义已实现、等待长回归

- 用户以“行”授权并在中断后要求继续完成最小 recovery runtime 与离线测试；授权仍不包含提交、successor freeze、新 authorization、真实 pilot、Enron/PubMed、API/victim/Retriever 或付费调用。实现新增机器可读契约 `configs/restoration_first_v23.development_recovery_r1.yaml`，SHA-256=`8b57250c66413352afc9707dfa0b582dbc6be2fa3e3816927994f4e2d22056ef`，revision=`pcv-restoration-first-v23-design-r6-execution-e1-development-recovery-r1`，并将其纳入后继 runtime closure；design-r6 与 execution erratum e1 本身未改写。
- 恢复窗口严格限定为：active revision 尚未开始 reservation、最近一个 prior revision reservation 已完整 `passed`、当前 ledger tip 与该 reservation final tip 完全相等、development batch identity 仍逐项一致；该复用仅是 development prerequisite，不授权复用或读取 fresh-audit reserve。若 active reservation 已出现、ledger 已前进、历史 reservation/aggregate 身份漂移，仍 fail closed。
- revision 4 EDGAR partial 只有在旧 authorization/budget 均可验证、budget charge 至少为 1 且未耗尽、source result=`0`、无 checkpoint、无 canonical selected-pairs/manifest、旧目录无其他条目时才可恢复。旧 authorization、budget 与空 `source_results/` 目录保持原字节；新 source results 写入 attempt-scoped 路径 `artifacts/v23/selection/development/<dataset>/attempts/<attempt_id>/source_results/`，并在任何新 source 可见前生成绑定 prior reservation、partial hashes、新 authorization/attempt 与 ledger tip 的 recovery attestation。任何历史 source result 非空都明确拒绝自动恢复。
- 合成端到端回归先在实现前稳定复现 `revision_reservation_authorization_count_invalid`（`1/1` failed as expected，115.712s），实现后同一场景通过（`1/1`，205.121s），验证 prior ledger 不变、旧 authorization/budget 字节不变、旧空目录不变且新结果进入 attempt 路径。历史非空 result 拒绝与既有 development group 回归为 `2/2`（289.220s）；capacity terminal、runtime bundle closure 也已分别通过。恢复后秒级复核为 `2/2`（0.015s），两个目标文件内存 AST 与 recovery contract 哈希/精确身份加载均通过。
- 完整 `tests.test_restoration_first_v23` 在运行中按用户“停一下”被主动中断；中断前未显示失败，但测试未完成，不能记为全量 passed。恢复后遵守“长命令由用户本人运行”，未重启该长回归。`git diff --check` 未发现 whitespace error，仅报告既有 CRLF conversion warning。
- 本轮只使用临时合成 fixture 和只读治理身份，未读取真实 development 正文或任何 membership、victim/LLM-only response、Retriever 输出、AUC；未加载 GPU 模型，真实 source/API/victim/Retriever/付费调用、ledger mutation、新 run authorization 与新 attempt 均为 0。active revision 仍为 5 / bundle `439c2c14...40991` / protocol revision `26cf9140...76b2d`；工作树 recovery 代码未提交，因此不得用于任何真实 runtime 命令。

当前唯一下一步：由用户本人运行完整 v23 离线回归；返回结果通过后，再由用户单独确认是否仅提交 recovery contract、runtime 与对应测试。提交不等于 successor freeze；freeze、新 EDGAR authorization 与真实 pilot 仍需后续分别授权，且 EDGAR passed 前不得启动 Enron/PubMed。

### 2026-08-17：development recovery r1 完整 v23 离线回归通过

- 用户本人使用锁定 `mia_model` 解释器完成 `tests.test_restoration_first_v23` 全模块回归，结果为 `Ran 52 tests in 789.765s`、`OK`，即 `52/52 passed`。这 supersede 前条目中的“长回归待运行”状态；此前被中断的那一次执行仍只作为操作中断记录，不改写成 passed。
- 结合已通过的恢复端到端、非空旧 result 拒绝、既有 development group、capacity terminal、runtime closure、AST 与契约身份检查，recovery r1 的当前离线验证闭环已通过。测试使用合成/临时 fixture；没有由本次回归产生真实 source 读取、GPU/API/victim/Retriever 调用、费用、ledger mutation、run authorization 或 attempt。
- recovery 文件仍未提交，active runtime 仍为 revision 5 / bundle `439c2c14...40991` / protocol revision `26cf9140...76b2d`；未冻结的工作树实现不得用于真实 EDGAR 命令。两份项目总表及其他既有脏工作树继续独立保留，不得顺带纳入 recovery commit。

当前唯一下一步：等待用户明确确认仅提交 `configs/restoration_first_v23.development_recovery_r1.yaml`、`src/prepare/restoration_first_v23.py` 与 `tests/test_restoration_first_v23.py`。该提交不等于 successor freeze、新 EDGAR authorization 或 pilot 执行授权；提交后仍需分别授权 freeze/validator 与 authorization 准备。

### 2026-08-17：development recovery r1 已限定范围本地提交

- 用户两次明确确认提交与提交信息；已创建本地 commit=`a964e63676b95d71f85975eaa3390c0bfb1bca03`（`fix(prepare): add audited v23 development recovery`），仅包含 recovery contract、`src/prepare/restoration_first_v23.py` 与对应测试，共 3 个文件；未纳入两份项目总表或其他既有脏工作树，未推送。
- commit message 明确记录 protocol scope、runtime bundle closure 将变化、只新增机器可读 recovery contract、真实 run artifact/API/victim/Retriever 调用均为 0，以及完整 v23 `52/52 passed` 验证。提交后分支相对远端为 ahead 5。
- 该提交尚未写入 active runtime lineage；active revision 仍为 5 / bundle `439c2c14...40991` / protocol revision `26cf9140...76b2d`。因此当前真实 runtime 继续 fail closed，不得直接生成或使用 EDGAR authorization。

当前唯一下一步：等待用户单独授权 successor runtime freeze 与 validator。freeze 完成前不生成新 EDGAR authorization、不运行 pilot；freeze 本身也不授权 Enron/PubMed、API/victim/Retriever 或付费调用。

### 2026-08-17：revision 6 successor freeze 与独立 validator 通过

- 用户明确授权范围仅为 successor runtime freeze 与 validator；不包含 stage fingerprint/carry-forward、新 EDGAR authorization、reservation、pilot、Enron/PubMed 或任何外部调用。预检确认 HEAD=`a964e63676b95d71f85975eaa3390c0bfb1bca03`，runtime closure 相对 HEAD 无脏改动，无 governance lock；freeze 前 `status` 以预期的 `active_runtime_commit_drift` fail closed。
- 生成一次性 freeze authorization=`d03228af1f17815ed823183610bba507106072c4137269d990173ba51ea61c17`，文件 SHA-256=`a6f513238c0c4c2f84926a66c8c21af877259a5f8a5e4c6c2524e9c0afbe347d`；绑定 prior revision 5 / bundle `439c2c14...40991` / protocol revision `26cf9140...76b2d`、prior ledger tip=`3c912fd1...aa8e1`，以及 target code commit=`a964e636...ca03`。
- successor freeze 已写入并激活 revision ordinal=`6`：runtime bundle=`c946f3503d269ecafa262abc2be158439ecd22a2cca86adb244340c150f22e1a`，protocol revision=`1275ff12203350073b7bbe2fd3188974dc88b648445e033dc2c4ce1d65ae348f`。bundle manifest SHA-256=`ac374c22d3c69b4017c5d561ed27e33d088762cec1bb1b648685b318af6a2b9b`，revision file SHA-256=`a630899c6aea1918c31e58d7339e9d53dced652b51faf6e0a873fe0f28e7a4d6`。
- 独立 `validate-successor-runtime` 重新运行并以 exit code 0 返回 `status=passed`；checkpoint SHA-256=`4f117da20e268ba90ace8d895b05fe550cad0f0d537472aa99a6ebe1c46698ac`，code commit、bundle、protocol revision、ordinal、authorization 与 ledger tip 全部一致。ledger tip 保持 `3c912fd1...aa8e1`，external calls=`0`，无遗留 lock。
- validator 通过后补充运行的全链只读 `status` 超出短时预期，按“长命令由用户本人运行”主动中止；它不是 freeze/validator 必需门禁，不改变上述 passed 判定，也不记录为协议失败。本轮未执行 aggregate-DF carry-forward、未创建 run authorization/attempt、未读取真实 source、未调用 GPU/API/victim/Retriever，费用为 0。

当前唯一下一步：等待用户单独授权 revision 5→6 的 `aggregate_df_precomputation` stage fingerprint 比对，以及仅在 fingerprint 精确相等时的 carry-forward；该授权不自动包含 EDGAR authorization 或 pilot。carry-forward 独立验证通过后，才能再单独准备 recovery-aware EDGAR authorization。

### 2026-08-17：revision 6 aggregate-DF fingerprint 相等并完成 carry-forward

- 用户明确授权 revision 5→6 的 `aggregate_df_precomputation` stage fingerprint 比对及 carry-forward；不包含 EDGAR authorization、reservation、pilot 或外部调用。只读重算显示 revision 5 bundle `439c2c14...40991` 与 revision 6 bundle `c946f350...2e1a` 的 fingerprint 完全相同，均为 `9fc3c9d28016b5d3483ca414145c5a9a025d4ec4196ab9679525b8ae268c8011`；不同 bundle/revision 的 stage execution identity 不同是预期，未被误当作 dependency drift。
- 生成 stage compatibility authorization=`3e1483b6f3ef4d4a8fca2237c10e7278a042e6b828f4041a7d4e17179b77b83c`，文件 SHA-256=`2029c4fa4cb102fc3dee1e26d144a7cb6c95e52ec26dae445eefc33d34d9668e`。authorization 的 `from_*` 按 provenance 绑定三套 DF 的原始生产者 revision 2 / bundle `c1e61ac5...285ea`，而非把 revision 5 carrier 改写成生产者；target 绑定 active revision 6。
- carry-forward 进程自然完成并以 exit code 0 返回 `status=passed`、`validation_mode=carried_forward`。attestation=`5a1428ebd4aaafbfb9c90f646fc596b763b021b4d2407acdbb915ab6e30904ed`，文件 SHA-256=`b7e29bb49d326ad2380622d5d43e2da2b395419d584be48734c0f502dca65ed0`；EDGAR/Enron/PubMed 三套 producer authorization、budget、checkpoint、DF manifest 与 rows hashes 均已绑定。
- carry runner 的末尾内嵌 validator 已通过；为遵守“长命令由用户本人运行”，没有再由助手启动耗时的独立 CLI 复跑。carry 前后 ledger 文件 SHA-256 均为 `0f05967af6bf97ff9dff2fd34970500cef7365ba8374f18af520f69dfb3dd394`，ledger mutation=`false`；revision 6 run authorization/attempt 数量仍为 `0/0`，source pool contents read=`false`，external calls=`0`，无 governance lock。
- 未生成 recovery-aware EDGAR authorization，未创建 revision 6 reservation，未启动任何 development pilot、Enron/PubMed 或下游阶段。旧 revision 4 partial evidence 与全部既有脏工作树保持不变。

当前唯一下一步：用户本人运行独立 `validate-carry-forward --stage aggregate_df_precomputation` 长命令；返回 `passed/carried_forward` 后，再等待单独授权准备 recovery-aware EDGAR authorization。独立验证本身不授权 pilot。

### 2026-08-17：revision 6 aggregate-DF 独立 carry-forward validator 通过

- 用户本人使用锁定 `mia_model` 解释器运行独立 `validate-carry-forward --stage aggregate_df_precomputation`，返回 `status=passed`、`validation_mode=carried_forward`、external calls=`0`、ledger mutation=`false`、source pool contents read=`false`。
- 独立结果与 runner 内嵌 validator 完全一致：attestation=`5a1428ebd4aaafbfb9c90f646fc596b763b021b4d2407acdbb915ab6e30904ed`，文件 SHA-256=`b7e29bb49d326ad2380622d5d43e2da2b395419d584be48734c0f502dca65ed0`，stage fingerprint=`9fc3c9d28016b5d3483ca414145c5a9a025d4ec4196ab9679525b8ae268c8011`，target revision 6 / bundle `c946f350...2e1a`；三数据集 artifact/budget/checkpoint hashes 全部一致。
- 至此 revision 6 aggregate-DF carry-forward 的授权、执行与独立验证闭环完成。未生成 EDGAR authorization/attempt，未创建 revision 6 reservation，未启动 pilot 或任何外部调用。

当前唯一下一步：等待用户单独授权准备 recovery-aware EDGAR development pilot authorization。该准备操作只允许生成 revision 6 的新 authorization/attempt 与 recovery attestation，不授权运行 pilot；旧 revision 4 authorization 继续不可复用。

### 2026-08-17：recovery-aware EDGAR authorization preparation 转交用户长命令

- 用户明确授权仅准备 revision 6 recovery-aware EDGAR authorization，不授权运行 pilot。助手启动冻结 `prepare-development-pilot-authorization --dataset edgar` 入口后，命令持续进行本地 aggregate/reservation/source-order identity 完整性验证超过 15 分钟，未出现方法失败或治理错误；按“长命令由用户本人运行”主动中止。
- 中止后只读核验 revision 6 run authorization/attempt 仍为 `0/0`，说明尚未分配新身份；ledger 文件 SHA-256 仍为 `0f05967af6bf97ff9dff2fd34970500cef7365ba8374f18af520f69dfb3dd394`，旧 revision 4 authorization/budget SHA-256 仍为 `8be11eee...b2358` / `43bcf7a8...4ce51`，legacy source results=`0`，均未变化。
- 中断进程遗留 `development_pilot_preparation.lock`，其内容 PID=`956776`；确认该 PID 已不存在后，仅删除这一精确 stale lock。没有删除、移动或改写任何 authorization、budget、selection 或历史 artifact；该操作中断不记为实验/协议失败，也不生成第二个 attempt。
- 用户已给出的 preparation 授权继续有效；下一次必须使用同一冻结 CLI 和同一 user authorization record。完成前不得手工生成 authorization、跳过 recovery attestation 或运行 pilot。

当前唯一下一步：用户本人运行 recovery-aware EDGAR authorization preparation 长命令并返回完整 JSON。预期只生成一个 revision 6 authorization/attempt 与 recovery attestation，预算 charge、source result、ledger mutation 和 external calls 均应为 0。

### 2026-08-17：revision 6 recovery-aware EDGAR authorization 已生成并核验

- 用户本人完成冻结 preparation 命令，生成唯一 EDGAR development authorization=`09f1466ae6d03b5914afa3ea6de5b085e2c3da7d378f1d4c3ff3af01cfca93bd`（文件 SHA-256=`e34795500642a58d446fe6431e27c5ff0be662313871b4f939ca8585bb0d4f5c`）、attempt=`093ed478887dff5734d8a4ba1868beaf3254b45d8bc2939e175bf8b5221a3991`。attempt registry 恰有 1 条匹配，row SHA-256=`836f7c40a240e821e86f9f7e2279e7bc48fd65212ef382908ee8de97a54ff42b`；protocol revision 6 / bundle `c946f350...2e1a`、budget limit=`1000 sources`、expected ledger tip=`3c912fd1...aa8e1`。
- reservation validation mode=`prior_revision_development_recovery`。recovery attestation ID=`1928af0b7d35c49500aa7248f9f9f0b8e484b9bce769448b887ba020f98c9286`，文件 SHA-256=`ad58e959b4d728d696fe0736e0bdd13f7a0301cf7849737b04837a7a747715ad`，canonical ID 校验通过；绑定 prior reservation protocol revision 4=`71e862b7...8043`、旧 partial authorization=`a40eab77...a67d`、旧 budget charge=`1`、旧 source result=`0`。
- preparation 后新 budget journal 不存在、新 attempt source-result 目录不存在、新 checkpoint 不存在，说明 budget charge/source result 均为 0；ledger 文件 SHA-256 保持 `0f05967a...d394`，旧 authorization/budget SHA-256 保持 `8be11eee...b2358` / `43bcf7a8...4ce51`，legacy result 仍为 0，无 governance lock，external calls=`0`。
- preparation 阶段没有读取 development 正文、没有运行 GLiNER/GPU、没有启动 pilot/Enron/PubMed，也没有修改 revision 4 partial evidence。旧 revision 4 authorization 继续不可用于运行；revision 6 新 authorization 在用户单独授权 pilot 前保持未执行。

当前唯一下一步：等待用户明确授权使用 revision 6 authorization=`09f1466a...a93bd` 运行 EDGAR development pilot。长命令必须由用户本人运行；完成后先独立 validator，再按预注册 determinism、hard-gate 与 capacity 门槛一次性判定 passed/failed。EDGAR 未 passed 前不启动 Enron/PubMed。

### 2026-08-17：revision 6 EDGAR pilot 已获运行授权、等待用户长命令

- 用户明确授权使用 revision 6 authorization=`09f1466a...a93bd` 运行 EDGAR development pilot；授权不扩展到 Enron/PubMed、API/victim/Retriever 或其他下游。运行前 CUDA preflight 通过：锁定解释器 `D:\python\anaconda\envs\mia_model\python.exe`、PyTorch `2.11.0+cu130`、`torch.cuda.is_available()=true`、设备 RTX 4060 Laptop GPU。
- 授权仍未消费：new budget/source-result directory/checkpoint 均不存在，无 governance lock。runner 使用 dataset exclusive lock；已有 checkpoint 时只做完整 validator 并幂等返回，已有 source result 时校验其 source/order/operation charge 后跳过；若 budget 已扣但 result 尚未落盘，则同一 operation identity 走 `resume_existing_charge`，不会重复扣费。
- 因此命令可续跑，但只能原样复用同一 authorization/attempt；不得重新 preparation 或创建新 attempt。若正常 Ctrl+C，context manager 应移除 lock；若强制终止留下 lock，必须先确认锁内 PID 已退出，再只移除该精确 stale lock。方法级 `failed_development_gate` checkpoint 是终态，不能当作中断继续补样本或调门槛。
- runner 默认没有逐 source 控制台进度，通常只在最终完成或异常时输出 JSON/traceback；长时间无输出不等于未运行。进度只能通过不读取 result 内容的 budget/source-result 文件计数做治理监控，禁止查看选择内容、membership、AUC、victim/LLM-only response 或 Retriever 输出。

当前唯一下一步：用户本人运行冻结 EDGAR pilot 命令；若中断，原样重复同一命令即可 resume。完成后先返回 runner JSON，再运行独立 validator，一次性判定 passed/failed；EDGAR 未 passed 前 Enron/PubMed 继续 blocked。

### 2026-08-17：strict governance 被轻量 development execution 取代

- 用户明确批准 `v23 轻量开发运行重构`。本次只改变 development 执行治理，不改变 Restoration hard gates、source-level 统计单位、每数据集 `1000 development + 250 fresh-audit reserve`、aggregate-DF 内容、capacity 判定、membership/response/Retriever/AUC 隔离或正式测试冻结边界。
- development 主 CLI 已收敛为六个入口：`status [--dataset]`、`aggregate-df --dataset`、`validate-aggregate-df --dataset`、`run-development-pilot --dataset`、`validate-development-pilot --dataset`、`validate-development-pilot-group`。bootstrap、successor freeze、carry-forward、revision reservation 运行入口和所有 `prepare-*-authorization` 入口均已退出 development 主流程；用户手动运行本地命令即视为该次 development 执行授权，API/victim/Retriever、fresh audit 与 formal test 仍需另行明确授权。
- 新 execution revision=`pcv-restoration-first-v23-lightweight-dev-r1`。attempt identity 只绑定协议设计、逐数据集固定 development reservation 及 1000-source identity hash、该数据集 aggregate-DF manifest/rows hash、selection/实体策略配置及科学实现文件 hash、GLiNER 单个 lock entry 与实际包版本；Git HEAD 仅作非阻断元数据。prepare/governance、日志和进度代码不进入 attempt identity；启动时不再扫描 runtime lineage、不运行历史 `git show`、不做三数据集 group validator，也不重哈希 833 MB 模型权重。
- development reservation 直接只读复用 revision 4 的逐数据集 plan；EDGAR 运行不会解析 Enron/PubMed plan 或 fresh-audit reserve 内容，也不扫描或修改 reservation ledger。容量公式中的既定 `consumed_non_development_c=250` 从冻结设计读取。现有 aggregate-DF 原样复用，缺失或 hash 漂移时 fail closed，不自动重建或覆盖。
- 新 runner 按科学依赖生成稳定 attempt ID，并写入 `artifacts/v23/selection/development/<dataset>/attempts/<attempt_id>/`。每个 source result 原子写入；同一身份重跑校验并跳过已完成 result，死亡 PID lock 自动恢复，活跃 PID 拒绝第二实例；每完成 10 条只打印 `Completed/1000`、耗时和 ETA，eligible count 只在全部完成后一次性计算。pilot 不获取 ledger lock，也没有 authorization budget journal。
- 只保留每数据集 development run lock 与 aggregate-DF build lock。capacity failure/hard-gate failure 写入 attempt-scoped manifest/checkpoint 后即为终态，续跑只验证返回，不能补样本或改门槛。正式实验尚未启动；未来 formal test 前只做一次 formal runtime freeze，绑定正式科学代码、配置、模型、Retriever 与 split。
- 历史 runtime bundles、lineage、carry-forward、reservation、authorization、budget、partial evidence 与全部既有脏工作树均原样保留，不迁移、不覆盖、不删除。revision 6 EDGAR authorization=`09f1466a...a93bd` / attempt=`093ed478...a3991` 现标记为历史未使用证据：development source result=`0/1000`、新 budget journal=`0`、checkpoint=`0`、external calls=`0`；重构后不再消费或重新生成该 authorization。
- 只读验证：新 CLI help 仅含六个命令；现有 EDGAR aggregate-DF 继续 `passed`，manifest SHA-256=`aeb7af6c...fdf6`、rows SHA-256=`add48dd0...e27f`；轻量 EDGAR attempt identity 可在不加载 GPU、不触及历史 Git 对象的情况下稳定生成。新增轻量回归 `7/7 passed`，selector/primitive/evaluation 定向回归 `14/14 passed`，合并模块运行 `60 tests / OK / 39 superseded strict-governance tests skipped`；AST import 与 `git diff --check` 通过，仅有既有 CRLF warning。未运行真实 pilot、未读取 membership/victim/LLM-only/Retriever/AUC、未加载 GPU，外部调用与费用为 0。

当前唯一下一步：由用户本人运行仓库全量离线 `unittest discover`；通过后，用户可直接运行不带 authorization 参数的 `run-development-pilot --dataset edgar` 长命令。EDGAR 终态 `passed` 才继续 Enron；`failed_*` 则停止并记录。fresh audit、formal test、API/victim/Retriever 与付费调用继续保持未授权。

### 2026-08-18：EDGAR development 在 451/1000 处暴露 selector 边界异常并完成续跑兼容修复

- 用户本人运行轻量 EDGAR pilot 后在 `Completed 451/1000` 处收到 `StopIteration`：候选的唯一 relation cue 位于原实体 span 内，mask 为 `ENTITY_SLOT` 后 cue 集合为空，而 pair builder 仍无条件调用 `next(...)`。这不是 capacity failure、数据泄漏或 GPU 故障。
- 已按用户确认做最小 crash-only 修复：无 masked relation cue 的候选现在返回 `relation_cue_missing_after_masking`，作为正常 hard-gate rejection；既有 451 个 source result、attempt 目录、aggregate-DF、reservation 与历史 artifact 均未修改或删除。
- 为保留已完成结果，增加仅针对这一精确“异常转拒绝”变更的 scientific hash compatibility：当前 attempt ID 仍为 `2dedf433989be511c459e3004425ba5df1ff84bee1085fc67c17fe776c60f342`，旧的 451 条可以继续跳过，后续 source 继续写入同一 attempt。该兼容不适用于其他科学代码、配置、模型、reservation 或 DF 变化。
- 定向验证：新增 relation-cue 回归与轻量 development tests 共 `8/8 passed`；未运行真实续跑、未读取 source result 内容、未调用 API/victim/Retriever、未读取 membership/AUC，外部调用与费用仍为 `0`。

当前唯一下一步：用户本人原样重跑同一 EDGAR 命令；预期从 `451/1000` 继续，不应重新生成 authorization 或新 attempt。完成后再运行 `validate-development-pilot --dataset edgar`，按 eligible、determinism、hard-gate 与 capacity 门槛一次性判定。

### 2026-08-18：EDGAR development capacity gate 终态失败

- 用户本人完成 EDGAR development attempt=`2dedf433...f342` 的全部 `1000/1000` source；eligible=`138`、selected pairs=`414`、external calls=`0`。
- 预注册 capacity 计算为 `K_L=636`、`consumed_non_development_c=250`、`formal_eligible_lower=248`，低于 required formal=`2250`；终态为 `failed_capacity_shortfall`。EDGAR 远低于最低观察门槛 `623/1000`，不能进入 fresh audit 或 formal test。
- 该失败是正式研究证据，不通过续跑增加样本、降低门槛、调 selector 或迁移结果来修复。attempt manifest、source results、selected pairs 与 checkpoint 均保留；未读取 membership/victim/LLM-only/Retriever/AUC，未执行外部调用。
- 按预注册顺序，Enron/PubMed development、fresh audit、formal runtime freeze、formal test 与全部下游均停止；不得将 EDGAR failure 表述为方法通过或正式攻击结果。

当前唯一下一步：记录 EDGAR failure 的失败模式并评估是否提出新的、明确版本化的科学设计；在新设计获单独批准前不启动 Enron/PubMed、不修改旧 attempt、不进入 formal。

### 2026-08-18：EDGAR capacity failure 的安全失败模式分析

- 仅读取 attempt-scoped 的 source-level 安全元数据（计数、gate reason union、candidate/pair 数、determinism/hard-gate 状态），未读取 source 正文、membership、victim/LLM-only response、Retriever 输出或 AUC。分析 bundle=`artifacts/v23/analysis/edgar_development_failure/`，包含报告、统计附录、图目录、两张诊断图和机器可读 summary。
- 主要瓶颈位于 candidate→pair hard gate：862 条失败 source 中，`pair_candidate_count=0` 有 457 条；失败 source 的 candidate 数均值/中位数为 51.97/49，但 pair 数均值/中位数仅 4.51/0。138 条 eligible source 的 pair 数均值/中位数为 29.31/27，且全部通过 3-pair 门槛并选择 3 对。
- 失败 source 的 reason union 高频项为 `relation_cue_missing`（855/862）、`source_specific_anchor_missing`（848/862）、`unresolved_reference`（809/862）和 `fact_token_count`（773/862）；这些列表是非互斥的 source-level 汇总，不能据此宣称单个 gate 的因果贡献。另有 128 条失败 source 虽有超过 10 个 pair candidates 仍未选出 pair，提示 distinct fact signature / original-entity diversity 约束是第二个待诊断瓶颈，但现有 artifact 不含候选级计数，不能进一步归因。
- 完整性方面：1000/1000 source 的 deterministic rerun hash 均匹配，hard-gate violation count 全为 0；因此本次是可复现的科学容量短缺，不是运行器完整性或数据泄漏事故。eligible=`138/1000=13.8%`，距离最低观察门槛 `623` 尚差 485 条；`K_L=636` 在扣除 `c=250` 后仅余 formal lower=`248`，距离 required formal=`2250` 尚差 2002。
- 该分析不改变失败终态，不调整阈值、不续跑补样本、不迁移结果；不启动 Enron/PubMed、fresh audit 或 formal。若要改变 selector/gate，必须提出新的预注册、版本化科学设计并从新 attempt 开始；当前 EDGAR attempt 及诊断 artifact 原样保留。

当前唯一下一步：在新设计获得单独批准前，项目停在 `failed_capacity_shortfall`，不运行其他数据集或正式实验。

### 2026-08-18：v23 独立 Fact Layer r1 实现完成

- 用户明确批准新增独立、可续跑的 fact extraction workflow；本实现不修改或消费 r6 EDGAR failed attempt、旧 selected pairs、旧 checkpoint、v19/v22 facts/claims/whitelist。
- 新增 `configs/restoration_first_v23_fact_layer_r1.yaml`、`src/attack/restoration_first_v23_fact_layer.py`、`src/prepare/restoration_first_v23_fact_layer.py`、`scripts/42_run_v23_fact_layer.py` 与对应回归测试。新的 artifact namespace 为 `artifacts/v23/selection/development_fact_layer/<dataset>/attempts/<attempt_id>/`。
- fact signature 改为绑定 `dataset/source_key/sentence_hash/original_span/effective_type`，允许同一句中不同非重叠槽位形成不同事实；不生成启发式 subject/relation 文本，true claim 直接保留 supporting sentence。
- P0 fact validity 与 retrieval diagnostics 分离：source-specific anchor 与旧固定 relation-cue 不再是 P0 硬门槛；完整 proposition、精确 span、source 内 recoverability、单槽 replacement、source absence、content-token 自包含仍保留。DATE/MONEY/PERCENT/IDENTIFIER/SECTION_ID 仅进入 structured diagnostic。
- runner 只读复用 v22 source pool/reservation 与模型缓存，不读取 r6 aggregate-DF 或其他旧 selection artifact；DF/IDF 诊断字段保持非阻断的未使用状态。新 runner 使用新的 fact identity、source-level 原子 result、checkpoint/resume、PID stale-lock recovery；不获取 ledger lock、不读取 membership/victim/LLM-only response/Retriever/AUC，external calls=`0`。
- 已完成静态验收：新 fact-layer 回归 `5/5 passed`，新模块与 CLI AST compile 通过，CLI help/status 可用；尚未加载 GPU、尚未读取真实 development source、尚未生成新 attempt artifact。

当前唯一下一步：用户本人先运行新 CLI 的 `extract-facts --dataset edgar` 长命令；返回 fact manifest 后再运行 `validate-facts`，不得直接启动 formal 或外部调用。

### 2026-08-19：EDGAR Fact Layer r1 development 全链通过

- 用户本人依次完成 `extract-facts`、`validate-facts`、`select-pairs`、`run-development-pilot` 与 `validate-development-pilot`；全链绑定同一 attempt=`eac91b4b35113019c3d32ea3b86451136e9d2f77d7d2567de3774664742ffcd9`，validator mode=`recomputed_from_fact_and_selection_artifacts`。
- 事实层完成 `1000/1000` development source：candidate=`661689`、structured diagnostic=`608652`、fact-valid=`27749`、P0-ready=`21021`；fact manifest SHA-256=`731cc2848f040348c4061705c968a47a5f0741b1af6831ecc1485cb042fd2e38`。
- pair selection 得到 candidate pairs=`141065`、eligible source=`970/1000`、selected pairs=`2910=970×3`；selection manifest SHA-256=`5897fe990c44c0666d73aabb7c7c401b67b01128b63f3b23515e19694ebe4488`。
- 预注册容量门槛通过：`N=5210`、`n=1000`、`x=970`、`K_L=5005`、`c=250`、formal eligible lower=`3785`，高于 required formal=`2250`；pilot 与独立 validator 均返回 `status=passed`。
- 该结果 supersede 的仅是新 Fact Layer r1 的 EDGAR development 推进状态；旧 r6 attempt=`2dedf433...f342` 的 `failed_capacity_shortfall` 证据继续原样保留，不改写为 passed。当前仍未执行 membership、victim/LLM-only response、Retriever、AUC、fresh audit 或 formal test，external calls=`0`。
- 解释边界：这是 source-level development capacity 与 artifact integrity 通过，不是正式 MIA 攻击效果、AUC 或人工事实质量结论；不能据此直接写成论文主结果。

当前唯一下一步：等待用户单独授权是否按同一 Fact Layer r1 运行 Enron `extract-facts`；未获授权前不启动 Enron/PubMed、fresh audit、formal runtime freeze、API/victim/Retriever 或付费调用。

### 2026-08-19：Enron Fact Layer r1 development 全链通过

- 用户本人完成 Enron `extract-facts`、`validate-facts`、`select-pairs`、`run-development-pilot` 与独立 `validate-development-pilot`；同一 attempt=`1d90a39588905229a8bffc4bb74e7299764580783032ffe1ac64f318b6c9d343`，validator mode=`recomputed_from_fact_and_selection_artifacts`。
- 事实层完成 `1000/1000` development source：candidate=`24303`、structured diagnostic=`5948`、fact-valid=`2399`、P0-ready=`1175`；fact manifest SHA-256=`001e0bc5de8ec644392195d333c33965e9b7a5c7db59748f546bc5e298f7d155`。
- pair selection 得到 candidate pairs=`9548`、eligible source=`149/1000`、selected pairs=`447=149×3`；selection manifest SHA-256=`41a17212f756652cd432311fb67501624425a134d8bdb8385fc1218b63419dd5`。
- 预注册容量门槛通过：`N=35000`、`n=1000`、`x=149`、`K_L=4586`、`c=250`、formal eligible lower=`4187`，高于 required formal=`2250`；pilot 与独立 validator 均返回 `status=passed`。
- 该结果是 Enron Fact Layer r1 的 source-level development capacity 与 artifact integrity 证据，不是 formal MIA/AUC、victim response、Retriever 或人工事实质量结论；external calls=`0`，未读取 membership/victim/LLM-only response/Retriever/AUC。

当前唯一下一步：等待用户单独授权是否运行 PubMed Fact Layer r1；在授权前不启动 PubMed、fresh audit、formal runtime freeze、API/victim/Retriever 或付费调用。

### 2026-08-20：三数据集 Fact Layer r1 development 全部闭环

- 用户本人完成 PubMed `extract-facts`、`validate-facts`、`select-pairs`、`run-development-pilot` 与独立 `validate-development-pilot`；同一 attempt=`920b51fbfd2ca9a668ffe307cb11d2216ea382141b3b3d74494d66899bb4d672`，validator mode=`recomputed_from_fact_and_selection_artifacts`。
- PubMed 事实层完成 `1000/1000` source：candidate=`243433`、structured diagnostic=`194238`、fact-valid=`26800`、P0-ready=`18041`；fact manifest SHA-256=`d6beeab538b7e36786b5f34e425ab97471459d420104dc1318a472c52c7a478c`。
- PubMed pair selection 得到 candidate pairs=`146122`、eligible source=`948/1000`、selected pairs=`2844=948×3`；selection manifest SHA-256=`ef8aea8f22852be487cac2d1c5a8eb9795d73974b111f137b3cbc09e963dc54a`。
- PubMed 预注册容量门槛通过：`N=47950`、`n=1000`、`x=948`、`K_L=44837`、`c=250`、formal eligible lower=`43639`，高于 required formal=`2250`；pilot 与独立 validator 均返回 `status=passed`。
- 至此 EDGAR=`970/1000`、Enron=`149/1000`、PubMed=`948/1000` 三个 Fact Layer r1 development 均完成 facts、pair selection、capacity gate 与独立 validator 闭环，三者 external calls 均为 `0`。
- 解释边界保持不变：这是 development source-level capacity 与 artifact integrity 通过，不是 formal MIA 攻击效果、AUC、victim response、Retriever 结果或人工事实质量结论；旧 r6 EDGAR `failed_capacity_shortfall` 证据继续原样保留。

当前唯一下一步：等待用户单独决定并授权 fresh audit；在授权前不启动 fresh reserve 消费、formal runtime freeze、formal test、API/victim/Retriever 或付费调用。

### 2026-08-20：Fact Layer r1 AI 预审（diagnostic-only）

- 对 EDGAR/Enron/PubMed 三套已通过 artifact 只读核验 `facts.jsonl`、`selected_pairs.jsonl` 与 manifest；未读取 membership、victim/LLM-only response、Retriever、AUC 或 fresh reserve。三套文件 hash、fact-to-pair 绑定、original span、single-slot counterfactual、每 source 三 pair、fact signature 去重和同一原实体最多两 pair 均无结构违规。
- 高置信度语义风险标记：EDGAR 选中 pair 中约 `144` 条 original entity 为 `The Company` 一类泛化实体，另有 `2 acres`、`2015`、`$2` 等数值/度量被 formal type 接受；Enron 有 `4` 条 `Start Date:` 邮件头样式、`3` 条带时间戳 `To:` 头样式，以及数值标识符 `347356` 被 formal type 接受；PubMed 有 `2` 条 Date/Subject 邮件头样式、`organization` 泛化实体和 `14`、`39`、`25 days` 等数值/度量被 formal type 接受。
- 代表样本包括：`The Company -> Vanta Industries`、`2 acres -> Sydney`、`Start Date -> Jordan Ellis`、`PLOS ONE -> Alex Carter`、`14 -> Dublin`。这些是 AI 预审的高置信度疑点，不把启发式计数直接当成人工标签或 fresh-audit 结论。
- 该预审不回写、不删除、不改写任何 r1 artifact，不调整阈值，不消费 fresh reserve，external calls=`0`。当前 development capacity `passed` 与语义质量疑点并存；不能把 capacity 通过直接解释为事实质量或 formal 攻击通过。

当前唯一下一步：用户先复核上述样本；若确认属于误接受，则实现新的 Fact Layer revision/attempt 修复泛化实体、邮件头和 structured-type 泄漏后再考虑 fresh audit，旧 r1 通过 artifact 原样保留。

### 2026-08-19：Enron Fact Layer r1 development 全链通过

- 用户本人完成 Enron `extract-facts`、`validate-facts`、`select-pairs`、`run-development-pilot` 与独立 `validate-development-pilot`；同一 attempt=`1d90a39588905229a8bffc4bb74e7299764580783032ffe1ac64f318b6c9d343`，validator mode=`recomputed_from_fact_and_selection_artifacts`。
- 事实层完成 `1000/1000` source：candidate=`24303`、structured diagnostic=`5948`、fact-valid=`2399`、P0-ready=`1175`；fact manifest SHA-256=`001e0bc5de8ec644392195d333c33965e9b7a5c7db59748f546bc5e298f7d155`。
- pair selection 得到 candidate pairs=`9548`、eligible source=`149/1000`、selected pairs=`447=149×3`；selection manifest SHA-256=`41a17212f756652cd432311fb67501624425a134d8bdb8385fc1218b63419dd5`。
- 预注册容量门槛通过：`N=35000`、`n=1000`、`x=149`、`K_L=4586`、`c=250`、formal eligible lower=`4187`，高于 required formal=`2250`；pilot 与独立 validator 均返回 `status=passed`。
- 该结果是 Enron development capacity 与 artifact integrity 证据，不是 formal MIA/AUC 或 victim/Retriever 结果；membership、victim/LLM-only response、Retriever、AUC、fresh audit、formal test 均未启动，external calls=`0`。

当前唯一下一步：等待用户单独授权是否运行 PubMed Fact Layer r1；未获授权前不启动 PubMed、fresh audit、formal runtime freeze、API/victim/Retriever 或付费调用。

### 2026-08-20：Fact Layer selection r2 实现并完成三数据集 development 闭环

- 用户确认基于 r1 AI 预审实现 r2。r2 被限定为 selection-only revision=`pcv-restoration-first-v23-fact-layer-selection-r2`：直接复用三套已验证 r1 `facts.jsonl`，不重新运行 GLiNER、不重新读取 source pool、不修改 r1 fact/pair/pilot artifact。新增 r2 config、attack/prepare selection 模块与测试；CLI 对 selection/pilot/validator 增加显式 `--selection-revision r2`，r1 默认入口仍可复现。
- r2 只过滤开发审计确认的高置信问题：邮件/投稿元数据、结构化数值或度量被映射到 formal type、`The Company`/`organization` 等通用占位实体、明确 PERSON 表面错型以及 table/author-contribution 元数据；略显生硬但类型兼容的 probe 保留。每个 source 继续要求三个不同 fact signature、同一 original entity 最多两对；被过滤后优先从同一 r1 P0 候选池确定性补位。
- r2 artifact 独立写入每个 r1 attempt 下的 `selection_r2/attempts/<selection_attempt_id>/`，包含完整 scientific identity、selected pairs、quality-filter diagnostics、selection manifest 与 pilot manifest。identity 绑定 r1 fact attempt/manifest hash、r2 config 和 r2 scientific implementation hash；不绑定 Git HEAD、治理 lineage 或 CLI 日志。
- EDGAR r2 selection attempt=`cc693e3a73ee534d8f1f68c77578e8b87d4295eb0ef18e950c18f12a5d39c917`：raw/candidate pairs=`141065/131014`，quality-rejected facts=`1205`（generic=`908`、PERSON surface=`257`、structured numeric=`40`），eligible=`969/1000`、selected=`2907`；selection manifest SHA-256=`6acb9f9a900feb08045fa1f42b0bafd47ec3ecc117bc5793bdebec04bee0eb3c`。
- Enron r2 selection attempt=`f0e8b529ae8c3c5ae1b2ab1428e3e4e31262ceb62bed445b021b07c5471de668`：raw/candidate pairs=`9548/9229`，quality-rejected facts=`33`（mail metadata=`29`、PERSON surface=`3`、structured numeric=`1`），eligible=`148/1000`、selected=`444`；selection manifest SHA-256=`9e07f489ed2d4361bfedfdfe866d39160428376658fda92cd25fb4650fb08228`。
- PubMed r2 selection attempt=`65e8b9fa7173b3f7f95e93a281323cc974be85a755d0bca657e64dbab75a3620`：raw/candidate pairs=`146122/143123`，quality-rejected facts=`323`（document metadata/table=`141`、generic=`5`、mail metadata=`7`、PERSON surface=`144`、structured numeric=`32`），eligible=`946/1000`、selected=`2838`；selection manifest SHA-256=`d90696d2f962da0e9519eb94609b1a554a0c6b69a67583ebb73d0fd533336dfc`。
- 三套 development capacity 继续通过：EDGAR `K_L=4999` / formal lower=`3780`，Enron `K_L=4553` / formal lower=`4155`，PubMed `K_L=44732` / formal lower=`43536`，均高于 required formal=`2250`。三套独立 validator 均以 `recomputed_from_r1_fact_and_r2_selection_artifacts` 通过。
- r1 非回归确认：三套 fact manifest hashes 仍为 `731cc284...2e38` / `001e0bc5...d155` / `d6beeab5...a478c`，r1 selection manifest hashes 仍为 `5897fe99...4488` / `41a17212...9dd5` / `ef8aea8f...dc54a`。已知样例 `The Company`、`2 acres`、`$2`、`2015`、`Start Date`、`347356`、timestamp `To:`、`organization`、`14`、`39`、`25 days` 与投稿头误接受均未进入对应 r2 selected pairs。
- 全过程只读取 development r1 fact artifact；未读取或消费 fresh reserve、membership、victim/LLM-only response、Retriever 或 AUC，未加载 GPU，external calls=`0`。r1 AI 预审和 r1 passed artifact 均保留为历史证据；r2 capacity passed 仍不等于 formal MIA/AUC 或真人事实质量通过。
- 最终验收：Fact Layer r1+r2+lightweight 定向回归共 `18 tests / OK`，四个 r2 Python/CLI 文件 AST compile 通过，新增文件尾随空白检查与 `git diff --check` 通过；仅出现工作树既有 LF→CRLF warning。环境未安装 `ruff`，本次未为此改变依赖。

当前唯一下一步：用户复核 r2 过滤范围与 development 结果；确认后再对 r2 做 AI 语义复审，并据此决定是否启动尚未消费的真人 blind fresh audit。formal runtime freeze、formal test、API/victim/Retriever 与付费调用继续保持未启动。

### 2026-08-20：Fact Layer selection r2 AI 语义复审（diagnostic-only）

- 只读复核三套 r2 `selected_pairs.jsonl` 共 `6189` 条；未读取 membership、victim/LLM-only response、Retriever、AUC 或 fresh reserve，未改写 r2 artifact，external calls=`0`。
- 结构层继续通过：EDGAR `2907`、Enron `444`、PubMed `2838` 条的 `original_span`/single-slot replacement 重算均为 `0` mismatch。r2 已知的泛化实体、结构化数值、邮件/投稿头样例未重新进入 selected pairs。
- 仍发现列表/元数据残留：以 `>=10` 个逗号作为保守 list/clause-dump 诊断，EDGAR=`33`、Enron=`3`、PubMed=`48`，另有 PubMed `1` 条多 email/header 形态。代表样本包括 Enron `Listed by: ... Federal ...`、PubMed `Antibodies against ... UK`、EDGAR 多公司/合同条款枚举句；这些与 P0 的“列表/元数据不进入主选择”边界冲突或高度接近。
- 仍发现未解析指代表面：EDGAR=`6`、Enron=`2` 条 original entity 是 `our/them` 等代词；代表样本为 Enron `possibly buying gas from them` 被替换为 `Orion Services Inc`，不应作为已恢复事实进入 P0。
- AI 人工复核的高置信类型错配残留包括：Enron `Texas Exes→Tokyo`（组织/地点且冠词异常）、`gas→Meridian Service`（普通物质/产品）；PubMed `ER→Summit Data Corp`（生物学缩写/组织）、`slaughter→Renewal Period`（事件/合同项）、`caudate→Dublin`（解剖区域/地点）、`Statgraphics Centurion→Casey Brooks`（软件/人物）、`Educational Psychology→Morgan Lee`（学科/人物）、`5 years old girl→Quinn Harper`（描述短语/人物）；EDGAR `college students→Alex Carter`（群体名词/人物）。
- PERSON 表面形态启发式还标出 EDGAR=`13`、Enron=`3`、PubMed=`123` 条疑点；这只是 AI diagnostic 上界，不把启发式计数直接当真人标签。残留说明 r2 解决了首批高置信问题，但尚未证明整体事实质量足以开 fresh audit。

复审结论：r2 development capacity 仍然 passed，但语义质量不 clean。fresh reserve 继续未消费；在再次收紧列表/代词/实体角色规则并建立新 selection revision 前，不启动真人 blind fresh audit 或 formal。

### 2026-08-20：固定 Fact Layer selection r2 与 API 登录切换交接

- 用户决定接受 r2 的少量残余语义风险，不再实现 r3 或重新抽取实体；r2 作为当前 development/fresh-audit 准备版本固定。该决定不改写、不删除 r1/r2 facts、pairs、pilot 或 AI diagnostic artifact。
- r2 三数据集 development capacity 与独立 validator 均已通过：EDGAR eligible=`969/1000`、Enron=`148/1000`、PubMed=`946/1000`；formal lower 分别为 `3780`、`4155`、`43536`，均高于 required=`2250`。
- 当前 r2 selection manifest：EDGAR=`6acb9f9a900feb08045fa1f42b0bafd47ec3ecc117bc5793bdebec04bee0eb3c`，Enron=`9e07f489ed2d4361bfedfdfe866d39160428376658fda92cd25fb4650fb08228`，PubMed=`d90696d2f962da0e9519eb94609b1a554a0c6b69a67583ebb73d0fd533336dfc`。
- API 登录/账号切换仅改变后续命令使用的本地凭据与额度，不改变协议、r2 identity、selection、reservation、fresh reserve 或正式测试边界；不得把登录成功解释为 API/victim/Retriever/付费调用授权。
- 截至本条目，membership、victim/LLM-only response、Retriever、AUC、fresh reserve 与 formal test 均未读取/消费，`external_calls_performed=0`。不得在交接时自动启动长任务或外部调用。

当前唯一下一步：新登录环境先只读核验本交接文档、两份项目总表和 r2 manifest；用户明确授权后再按冻结的 r2 版本进入 fresh audit。任何 API/victim/Retriever 或付费调用仍需单独、明确授权。

### 2026-08-20：frozen-r2 fresh audit 准备授权与只读核验

- 用户确认 Fact Layer selection r2 固定，授权范围仅为 frozen-r2 fresh audit 的准备与只读验证；不授权 API、victim、Retriever、付费调用或正式实验。
- 三套 `validate-development-pilot --selection-revision r2` 只读重算均通过：EDGAR `969/1000`、Enron `148/1000`、PubMed `946/1000`；三套 selection manifest hash 与 pilot manifest 绑定一致，`external_calls_performed=0`。
- 只读核验确认现有共同 prior snapshot、三套 250-source reserve plan 与 group completion 属于 execution revision `71e862b7591b2ac9bd1a1759b3784fc3b0e4b7286b96098d4997f0f173b78043`；未读取 reserve source 内容，未生成 fresh-audit packet、authorization 或 ledger 新行。
- 当前 `scripts/42_run_v23_restoration_first.py` 没有 `fresh-blind-audit`/packet-preparation 入口，`artifacts/v23/audit/` 尚不存在；不得用临时脚本或通用原语绕过冻结 runtime 与 reserve 可见性门禁。

当前唯一下一步：在不消费 fresh reserve 的前提下，等待用户另行授权实现/冻结 frozen-r2 fresh-audit preparation runner；API、victim、Retriever、付费调用和正式实验继续 blocked。

### 2026-08-20：frozen-r2 fresh-audit preparation runner 已实现并冻结

- [x] 新增 preparation config、runner 与 CLI，入口包含 `freeze`、`validate-freeze`、`status`、authorization 校验、`prepare-dataset` 和 `build-packets`。
- [x] freeze identity=`09b9a362ec56acddc3e348084521d3fee41171143c5b37589e782c8ac7acf803`，freeze manifest SHA-256=`93629f040910d5f48ce4e3346364a9a24ee7bd40dbdbfafba5434ff5c37ced0f`；绑定三数据集 r2 manifest、reserve/group metadata、design/selection/model lock 与 implementation hash。
- [x] runner fail-closed 校验连续 reserve prefix、完整 source-result aggregate hash、数据库 hash/schema、盲包 visible/hidden schema、deterministic HMAC order；authorization 明确禁止 API、victim、Retriever、外部调用和 formal experiment。
- [x] 定向 unittest `8/8 OK`，内存 AST compile、CLI help、`git diff --check` 通过；`validate-freeze` 与 `status` 通过，`source_content_read=false`、`external_calls_performed=0`，audit directory 尚不存在。
- [x] 本轮未执行 `prepare-dataset`、`build-packets`、authorization 生成、fresh reserve source 内容读取、ledger 写入、membership、victim/LLM-only response、Retriever 或 AUC。
- [ ] 实际 dataset preparation、blind packet 构造与 human audit 仍需用户另行明确授权，不得表述为 fresh audit 已执行或 formal 结果。

当前唯一下一步：等待实际 `prepare-dataset` 的单独明确授权；保持 frozen-r2、reserve 未消费、外部调用为 `0`。

### 2026-08-20：用户授权由本人启动 dataset preparation

- [x] 用户明确授权 frozen-r2 `dataset preparation`；授权仅覆盖本地 reserve source 读取、事实抽取、r2 pair selection 与 dataset manifest 生成。
- [x] 授权不包含 API、victim、Retriever、付费调用、membership、AUC、blind packet 构造或 formal experiment。
- [ ] 本会话不启动长任务；由用户按数据集分别运行命令。执行前仍需确认 `mia_model` Python 与 CUDA；中断后只允许使用同一 authorization 和连续 prefix resume。

当前唯一下一步：用户自行运行第一个数据集的 `prepare-authorization` 与 `prepare-dataset` 命令；本轮截至交接仍未读取 fresh reserve source，`external_calls_performed=0`。

### 2026-08-20：EDGAR preparation 首次启动失败与 r1-fix1 修复

- [x] 用户生成的 EDGAR authorization=`d98e00efaa41cce983d3624af975b4e344edd47e0e3286106363fff5346d775d.json` 保留为历史授权记录；首次 `prepare-dataset` 在 `_FreshAuditSourceReader` 进入 `with` 时因缺少上下文管理协议而失败。
- [x] 失败发生在 source 读取循环前；仅创建了旧 freeze identity 下的空 audit 目录并完成 reader metadata/schema 初始化，没有写 source-result、dataset manifest、selected pairs 或 ledger，没有读取 fresh reserve source 内容，外部调用仍为 `0`。
- [x] 修复为 reader 增加 `__enter__`/`__exit__` 并新增回归测试；由于 freeze 绑定 implementation hash，未覆盖旧 `r1.freeze.json`，新建 runner revision=`r1-fix1`。
- [x] 新 freeze identity=`bf3808063e71ff46f371bd8a27c3d3023b39dfe57f54b76bfeb0456db2b17f74`，manifest SHA-256=`9acd8c85ec08a924ae23b55026d62a25bb7ada9ce62c085367a115812e88dc79`；`validate-freeze`、`status` 通过，`9/9` preparation tests 通过。
- [ ] 旧 authorization 不得复用；需按新 freeze 重新生成 dataset-specific authorization 后再重试 EDGAR。旧失败目录和旧 freeze 保留，不做清理或覆盖。

当前唯一下一步：用户使用新 `r1-fix1` freeze 生成新的 EDGAR authorization，并重新运行 `prepare-dataset`；仍不启动 packet、API、victim、Retriever 或 formal experiment。

### 2026-08-20：EDGAR preparation 第二次失败与 r1-fix2 顺序身份修复

- [x] 用户使用 `r1-fix1` authorization=`811720960ee96d3406c6500c9c0322c1440d10c1b31074f9e9610321984d296e` 重试；首个 reserve source 已进入 reader，但因错误比较 DB `source_order_rank` 与 reserve numeric index，触发 `fresh_audit_source_order_identity_drift`。
- [x] 只读核验确认冻结 source-order 文件中该 source 的 index=`1000`，SQLite `source_order_rank` 为 hash 字符串；本次已读取首个 reserve source 内容但没有写 source-result、dataset manifest、selected pairs 或 ledger，继续保留旧 audit 目录与 authorization。
- [x] 修复为读取并校验冻结 `source_order[index] == source_key`，不再误比较 DB rank 字段；新增顺序身份回归测试，runner revision=`r1-fix2`。
- [x] 新 freeze identity=`3bfad5b67a7f71f7d8278e6e18a5149d37e78464b64d750fc41a40129a8bc4ae`，manifest SHA-256=`99c12c2e74336b83503bfe3e33b95ce3df8cc9d8aa295e1028e949da81699c41`；`validate-freeze/status` 通过，preparation tests=`10/10`。
- [ ] `r1-fix1` authorization 不得复用；需按 `r1-fix2` freeze 重新生成 EDGAR authorization 后再重试。

当前唯一下一步：用户为 `r1-fix2` 生成新的 EDGAR authorization 并重试；仍不启动 packet、API、victim、Retriever 或 formal experiment。

### 2026-08-20：EDGAR frozen-r2 dataset preparation 通过

- [x] 用户使用 r1-fix2 authorization=`6fa812eeef25ae6f687ab54999e97e2b013192145ca3263e77e97facae6924f9` 完成 EDGAR dataset preparation。
- [x] 按冻结 reserve 顺序评估 `104` 个 source，选出前 `100` 个 eligible source，生成 `300=100×3` 个 selected pair；dataset identity=`aff3fe282ce788e439ad3de696da99c6bf4507239eddb2ace9bc55ca848a553e`。
- [x] EDGAR dataset manifest `status=passed`，source-results aggregate identity=`cc8e607ce28cb1edf652a2a8dc8090cdb462eff02dc73cfdf6bb5f6d930b84cc`，`external_calls_performed=0`；未读取 membership、victim/LLM-only response、Retriever 或 AUC。
- [x] 本阶段仅消费 EDGAR fresh-audit reserve 内容；Enron/PubMed 尚未运行，blind packet、human audit、API/victim/Retriever、付费调用和 formal experiment 仍未授权/未启动。

当前唯一下一步：等待用户决定是否分别授权并运行 Enron、PubMed dataset preparation；三数据集完成前不得构造 blind packet。

### 2026-08-20：Enron preparation 改由用户续跑

- [x] 用户要求 Enron 达到 `100` eligible 即停止；runner 原有停止条件已满足该要求，无需改代码或改配置。
- [x] 本会话启动的 Enron 进程已由用户要求停止；已保留连续 `157/250` 个 source-result，其中 `22` 个 eligible；尚未写 dataset manifest、selected pairs manifest 或 packet。
- [x] 现有 Enron authorization=`dc54a681eea863dc15cebc35b712a80f516eb91cddd8330e953d67b27d526446` 仍绑定当前 freeze，可用于连续 prefix resume；未发生 API/victim/Retriever/付费调用，external calls=`0`。

当前唯一下一步：用户自行使用原 authorization 续跑 Enron；达到 `100` eligible 后 runner 自动停止并生成 dataset manifest。随后再决定是否运行 PubMed。

### 2026-08-20：Enron fresh-audit reserve eligible shortfall

- [x] Enron 使用当前 freeze=`3bfad5b67a7f71f7d8278e6e18a5149d37e78464b64d750fc41a40129a8bc4ae` 与 authorization=`dc54a681eea863dc15cebc35b712a80f516eb91cddd8330e953d67b27d526446` 完整评估 `250/250` 个 reserve source，source-result index 连续 `0..249`。
- [x] 最终仅 `29` 个 source eligible，低于冻结目标 `100`；runner 按 fail-closed 规则抛出 `fresh_audit_reserve_eligible_shortfall`，未生成 Enron dataset manifest 或 selected-pairs release artifact。
- [x] 保留全部 250 个 source-result 与授权记录；不把 shortfall 改写为 passed，不增加 reserve、不放宽 selected count、不重新抽取实体、不修改 r1/r2 历史 artifact。
- [x] 本次无 API、victim、Retriever、付费调用、membership、AUC 或 formal experiment，`external_calls_performed=0`。

当前唯一下一步：Enron 本轮 fresh-audit preparation 以 shortfall 失败证据封存；不得继续重跑同一 reserve 以凑数。PubMed 是否运行仍需单独决定，blind packet 不能构造。

### 2026-08-20：Enron 1000-source reserve 扩展 revision 已实现并冻结 policy

- [x] 用户决定在保留 Fact Layer selection r2 的前提下，为 shortfall 后的 fresh audit 建立版本化 reserve 扩展；不实现 r3、不重新抽取实体、不修改或覆盖旧 r1/r2 artifact，也不把旧 Enron `29/250` shortfall 改写为 passed。
- [x] 新增 `pcv-restoration-first-v23-fresh-audit-preparation-r2` / runner revision=`r2-enron-reserve-1000`。新的原子 reservation group 使用未消费 source，容量冻结为 EDGAR=`250`、Enron=`1000`、PubMed=`250`；每数据集 selected target 仍为 `100` source×`3` pair，blind packet 总量仍为 `900` pair。
- [x] 新 execution reservation revision=`f004bc7511305c17066c0e869c708b828aa58d13f3a7ccc0d94a59f034f4934b`；policy freeze identity=`20b0972141748e0b8f7b6ed1565df3294a3215dc1b49f5ffaccc4b41975dcc72`，policy manifest SHA-256=`71927082970303e974b85069f07bad72030470b67335fb9540d942e4539170a0`。
- [x] 新 runner 增加 policy freeze/validator、显式 reserve-registration authorization、append-only ledger/hash-chain 注册与恢复、逐数据集 preparation authorization、dataset preparation、packet gate；旧 `scripts/43_prepare_v23_fresh_audit.py` 与 freeze=`3bfad5b6...a8bc4ae` 只读回归仍为 `passed`。
- [x] 定向测试为 `14/14 passed`（含隔离临时 ledger 的 batch hash-chain、预算 journal、anchor 与幂等恢复），AST 编译与 `git diff --check` 通过；环境未安装 `ruff`，未安装新依赖。当前只完成 policy freeze，reservation group=`not_started`，preparation freeze=`not_started`。
- [x] 本轮没有生成 reserve-registration authorization，没有读取/登记新 reserve，没有修改 ledger；ledger tip 仍为 `3c912fd1...6aa8e1`。未运行 CUDA selector、blind packet、human audit、API/victim/Retriever、付费调用或 formal experiment，`external_calls_performed=0`。

当前唯一下一步：等待用户明确授权并自行运行新 revision 的 reserve-registration authorization 与 `register-reserve-group` 长命令；注册和 validator 通过后才允许 `freeze-preparation`。在此之前不得运行 dataset preparation 或 `build-packets`。

### 2026-08-20：expanded reserve group 注册通过

- [x] 用户运行 reservation authorization=`d4abd2b93dbf80ebb7fd9ea7085e8ab6c8247d4f6cb64044a835db3b64f3f2dc`，明确授权 identity-only registrar 与 append-only ledger mutation；API、victim、Retriever、付费调用、membership、AUC、blind packet、human audit 和 formal experiment 均未授权。
- [x] 新 reservation group 注册通过：EDGAR=`250`、Enron=`1000`、PubMed=`250`，合计 `1500` 条新 source identity；新 execution revision=`f004bc7511305c17066c0e869c708b828aa58d13f3a7ccc0d94a59f034f4934b`，最终 ledger tip=`3dce5019c9272c7f0abb0c182bed077d9f57f58e6ab8234eb9b7e11014c40912`。
- [x] reservation validator 通过，reservation validation identity=`1b4e230aaf0989e0dd13d82538032780561db08df423f09ce21987d1311d869d`；source content 仅由 identity registrar 瞬时读取以重算 hash，未持久化 source 内容、facts、claims 或 derived feature。
- [x] 旧 r1-fix2 freeze 仍通过；本阶段没有运行 fact selector、dataset preparation、blind packet、human audit、API/victim/Retriever 或 formal experiment，`external_calls_performed=0`。

当前唯一下一步：用户自行运行 `freeze-preparation` 并只读 `validate-freeze`；在 preparation freeze 通过前不得运行 dataset preparation 或 `build-packets`。

### 2026-08-20：expanded frozen-r2 preparation freeze 通过

- [x] 用户连续运行 `freeze-preparation` 与 `validate-freeze`，两次回传的冻结身份一致；preparation freeze identity=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19`，freeze manifest SHA-256=`f51640c9385a4cebc94b1ffe4a59c8e377c6ad4ef5f427ef1d40dd2e1a8614c6`。
- [x] 只读复验确认 policy freeze、expanded reservation group 与 preparation freeze 均为 `passed`；runner status=`policy_frozen_downstream_blocked`，execution reservation revision=`f004bc7511305c17066c0e869c708b828aa58d13f3a7ccc0d94a59f034f4934b`。
- [x] 新 freeze 继续绑定固定 Fact Layer selection r2 的三套 passed selection/pilot identity，并绑定新原子 reserve group：EDGAR=`250`、Enron=`1000`、PubMed=`250`，每数据集目标仍为前 `100` eligible source × `3` pair。
- [x] 旧 r1-fix2 EDGAR passed 与 Enron `29/250` shortfall artifact 继续按旧 freeze/execution revision 保留，不覆盖、不改写，也不跨 reservation group 计入新 revision；新 revision 的三数据集 preparation 必须分别授权并重新产生自身身份。
- [x] 本次 freeze/status/validator 未读取 reserve source 内容，未启动 dataset preparation、blind packet、human audit 或 formal experiment；API/victim/Retriever/付费调用继续禁止，`external_calls_performed=0`。

当前唯一下一步：等待用户明确授权 expanded revision 下按冻结 dataset order 开始 EDGAR dataset preparation；授权前不生成 preparation authorization、不读取新 reserve 内容、不运行 `build-packets`，API/victim/Retriever、付费调用与 formal experiment 继续 blocked。

### 2026-08-21：expanded revision EDGAR preparation authorization 已生成

- [x] 用户明确授权 expanded frozen-r2 revision 的 EDGAR `dataset_preparation`；生成 authorization=`1d507ecf2fc29e2f90cf0bf031336ed209b3bbc9b6b2bf2239b84eb21fd327cb`，绑定 preparation freeze=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19` 与 execution reservation revision=`f004bc7511305c17066c0e869c708b828aa58d13f3a7ccc0d94a59f034f4934b`。
- [x] authorization scope 仅为 `dataset_preparation` / `edgar`，预算上限为 `250` source reads；`validate-authorization` 通过，API/victim/Retriever/付费调用、membership、AUC、blind packet、human audit 与 formal experiment 均明确禁止。
- [x] 授权生成与验证未读取 reserve source 内容，未复用旧 EDGAR dataset preparation，未运行 dataset preparation，`external_calls_performed=0`。

当前唯一下一步：用户本人执行该 authorization 绑定的 expanded EDGAR `prepare-dataset` 长命令；运行前后不得执行 `build-packets`，Enron/PubMed preparation 仍需分别授权，API/victim/Retriever、付费调用与 formal experiment 继续 blocked。

### 2026-08-21：expanded frozen-r2 EDGAR dataset preparation 通过

- [x] 用户执行 expanded EDGAR `prepare-dataset` 成功；按新 reservation 顺序评估 `106` 个 source，`eligible=100`，选出 `100` 个 source，生成 `300=100×3` 个 selected pair。
- [x] dataset manifest `status=passed`，manifest SHA-256=`8106c4218d12e8b976968ea7e3db1d9e0b3b873eef8cdd1a84975c687e80e004`；dataset identity=`39beeeee95dc464050c7068c15744de48f9e8e03ad438b95a53cbd23f06110aa`，source-results identity=`36e0b21812867fa44138b7639895032e6086da8ed07d4b77021ce57c8a1cf829`。
- [x] EDGAR manifest 绑定 expanded preparation freeze=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19` 与新 reserve snapshot/plan；未复用旧 EDGAR dataset manifest，旧结果继续保留为历史证据。
- [x] 本次仅消费 expanded EDGAR reserve；`external_calls_performed=0`，未读取 membership、victim/LLM-only response、Retriever 或 AUC，未构造 blind packet、未启动 human audit 或 formal experiment。

当前唯一下一步：等待用户单独授权 expanded revision 的 Enron dataset preparation；在 Enron 与 PubMed preparation 均通过前不得构造 blind packet，API/victim/Retriever、付费调用与 formal experiment 继续 blocked。

### 2026-08-21：expanded revision Enron preparation authorization 已生成

- [x] 用户明确授权 expanded frozen-r2 revision 的 Enron `dataset_preparation`；生成 authorization=`8280df6a9c0c0446dec09e5e324efc4df0a4ba5141550900bb76ba0e646e0232`，绑定 preparation freeze=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19` 与 execution reservation revision=`f004bc7511305c17066c0e869c708b828aa58d13f3a7ccc0d94a59f034f4934b`。
- [x] authorization scope 仅为 `dataset_preparation` / `enron`，预算上限为 `1000` source reads；`validate-authorization` 通过，API/victim/Retriever/付费调用、membership、AUC、blind packet、human audit 与 formal experiment 均明确禁止。
- [x] 授权生成与验证未读取 Enron reserve source 内容；不复用旧 `29/250` shortfall 或旧 preparation，`external_calls_performed=0`。

当前唯一下一步：用户本人执行该 authorization 绑定的 expanded Enron `prepare-dataset` 长命令；运行前后不得执行 `build-packets`，PubMed preparation 仍需单独授权，API/victim/Retriever、付费调用与 formal experiment 继续 blocked。

### 2026-08-21：expanded frozen-r2 Enron dataset preparation 通过

- [x] 用户执行 expanded Enron `prepare-dataset` 成功；按新 reservation 顺序评估 `665` 个 source，`eligible=100`，选出 `100` 个 source，生成 `300=100×3` 个 selected pair。
- [x] dataset manifest `status=passed`，manifest SHA-256=`597cb9f9a66777eb747591fcd9015b6907b43ee36f376b0e8ab7bcaaf781f920`；dataset identity=`cdd27cfb745ef58876db26c70b837cc9689e9e4cba0ae9fccb536619f2b2dbb5`，source-results identity=`3b0b0337250051cca36a6358a6ea2c26b1d7f26274143b1c32e24f0b7f35d429`。
- [x] Enron manifest 绑定 expanded preparation freeze=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19` 与 1000-source reserve snapshot/plan；旧 `29/250` shortfall 继续作为旧 revision 失败证据保留，未覆盖、未改写、未跨 revision 复用。
- [x] 本次仅消费 expanded Enron reserve；`external_calls_performed=0`，未读取 membership、victim/LLM-only response、Retriever 或 AUC，未构造 blind packet、未启动 human audit 或 formal experiment。

当前唯一下一步：等待用户单独授权 expanded revision 的 PubMed dataset preparation；PubMed 通过后三数据集 preparation 才算齐备，届时仍需单独授权才能构造 blind packet。API/victim/Retriever、付费调用与 formal experiment 继续 blocked。

### 2026-08-21：expanded revision PubMed preparation authorization 已生成

- [x] 用户明确授权 expanded frozen-r2 revision 的 PubMed `dataset_preparation`；生成 authorization=`52127310a0595205a672e2e598bf314d3c551efc653eadd78fbac75c44b496c2`，绑定 preparation freeze=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19` 与 execution reservation revision=`f004bc7511305c17066c0e869c708b828aa58d13f3a7ccc0d94a59f034f4934b`。
- [x] authorization scope 仅为 `dataset_preparation` / `pubmed`，预算上限为 `250` source reads；`validate-authorization` 通过，API/victim/Retriever/付费调用、membership、AUC、blind packet、human audit 与 formal experiment 均明确禁止。
- [x] 授权生成与验证未读取 PubMed reserve source 内容；不复用旧 PubMed preparation，`external_calls_performed=0`。

当前唯一下一步：用户本人执行该 authorization 绑定的 expanded PubMed `prepare-dataset` 长命令；三数据集 preparation 全部通过后，仍需单独授权才能构造 blind packet，API/victim/Retriever、付费调用与 formal experiment 继续 blocked。

### 2026-08-21：expanded frozen-r2 三数据集 preparation 全部通过

- [x] 用户完成 expanded PubMed `prepare-dataset`；按新 reservation 顺序评估 `107` 个 source，`eligible=100`，选出 `100` 个 source，生成 `300=100×3` 个 selected pair。
- [x] PubMed dataset manifest `status=passed`，manifest SHA-256=`b97a306335532c8d98a3341205b6189836f32685ec81f8bd4cd36389aab065db`；dataset identity=`1fb181e18968106bd9cd05593e57f8526ba5b46c714687a9640bd0c985f7dd35`，source-results identity=`4931244841ae2cc18af9214e31ba6fea487122b489e5c6334e99ee0780f96c24`。
- [x] expanded freeze 下三数据集 preparation 均通过且身份一致：EDGAR `106` evaluated / `100` selected，Enron `665` / `100`，PubMed `107` / `100`；总计 `900` selected pair。各 dataset manifest 均绑定 freeze=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19`，各自 `external_calls_performed=0`。
- [x] 旧 r1/r2 preparation、EDGAR 旧 passed、Enron 旧 `29/250` shortfall 与旧 freeze/ledger 继续保留；expanded 结果未跨 revision 复用旧 dataset artifact，也未覆盖历史证据。
- [x] 本阶段未构造 blind packet、未进行 human audit，未读取 membership、victim/LLM-only response、Retriever 或 AUC；API/victim/Retriever、付费调用和 formal experiment 仍未授权。

当前唯一下一步：等待用户单独授权 expanded frozen-r2 的 `packet_preparation` / `build-packets`；授权前不得构造 blind packet，API/victim/Retriever、付费调用与 formal experiment 继续 blocked。

### 2026-08-24：expanded frozen-r2 packet preparation authorization 已生成

- [x] 用户明确授权 expanded frozen-r2 三数据集 `packet_preparation` / `build-packets`；生成 authorization=`0f646578e6d2089303288cd94afe892ddd917cb51b628dc118c076b92b4ad491`，绑定 freeze=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19` 与 execution reservation revision=`f004bc7511305c17066c0e869c708b828aa58d13f3a7ccc0d94a59f034f4934b`。
- [x] authorization scope 仅为 `packet_preparation`，dataset=`null` 表示消费三套已通过 dataset manifest；`validate-authorization` 通过，`budget_maximum_source_reads=0`，只允许 packet artifact 写入。
- [x] API/victim/Retriever/付费调用、membership、AUC、human audit 与 formal experiment 均明确禁止；授权生成与验证未执行 `build-packets`，`external_calls_performed=0`。

当前唯一下一步：用户本人执行该 authorization 绑定的 `build-packets` 长命令；完成并验证 packet manifest 后，human audit 仍需单独授权，API/victim/Retriever、付费调用与 formal experiment继续 blocked。

### 2026-08-24：兼容层协议放宽但科学 freeze 保持不变

- [x] 针对 packet builder 将 freeze 摘要误当完整 manifest 的兼容缺陷，采用“科学层 freeze + 兼容层 envelope”分层规则；不生成 successor freeze，不改变三数据集 selection、reserve 顺序、预算、pair 数量或任何历史 artifact。
- [x] 原 policy identity=`20b0972141748e0b8f7b6ed1565df3294a3215dc1b49f5ffaccc4b41975dcc72` 与 preparation identity=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19` 继续通过；兼容 envelope=`configs/restoration_first_v23_fresh_audit_compatibility_r1.json`，identity=`e40222d9bf30631353677039ded6b5e425439eba3fd71a6df24651fdf3d18ac2`。
- [x] 兼容白名单仅覆盖 packet adapter：legacy `build_packets`、r2 wrapper 的 `_legacy_packet_freeze_manifest` / `_legacy_profile` / `build_packets`；fact extraction、selection、source identity、reserve ledger、模型锁与 CLI 科学参数仍 fail-closed。
- [x] legacy packet builder 现在从同一路径读取并校验完整 freeze manifest，再计算 reserve snapshot binding；未运行 `build-packets`，未读取 membership、victim/LLM-only response、Retriever 输出或 AUC，`external_calls_performed=0`。

当前唯一下一步：用户本人重新执行既有 packet `build-packets` 长命令；兼容验证通过后仍需单独授权 human audit，API/victim/Retriever、付费调用与 formal experiment继续 blocked。

### 2026-08-24：expanded frozen-r2 blind packet preparation passed

- [x] 用户使用既有 `packet_preparation` authorization=`0f646578e6d2089303288cd94afe892ddd917cb51b628dc118c076b92b4ad491` 执行 `build-packets`，结果为 `status=passed`。
- [x] 生成 `900` 行 blind packet；packet manifest SHA-256=`bbe1479a6e679e052a7e1b6312afdcca72ee803806d61a1d129ada68f363e587`；artifact 位于 frozen-r2 audit root 下。
- [x] `external_calls_performed=0`；本阶段未授权或启动 human audit、API、victim、Retriever、付费调用或 formal experiment，未读取 membership、victim/LLM-only response、Retriever 输出或 AUC。
- [x] 对前一条兼容层记录作 superseding：最终 compatibility envelope identity=`388a8a99b704422dceed3254aa672dda2a4d1fe8397ba76ee4c0bbbee64d68fc`；原 frozen-r2 scientific identities 未变化。

当前唯一下一步：等待用户单独明确授权 human blind audit；在此之前不得打开/解盲 packet、运行 API/victim/Retriever 或启动正式实验。

### 2026-08-24：AI-only blind-packet structural audit 完成（superseding）

- [x] 用户明确授权只做 AI 审计、不做人工审计；生成并验证 assistant-only authorization=`aed7737ca2c698f9c289b19d99f50ce0810cabe2ddf77e760d355d15340a6aab`，绑定 frozen-r2 preparation freeze=`4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19` 与 packet manifest SHA-256=`bbe1479a6e679e052a7e1b6312afdcca72ee803806d61a1d129ada68f363e587`。
- [x] `scripts/45_run_v23_ai_audit.py run` 完成：packet `900` 行，`875 pass / 25 uncertain / 0 fail`；25 条不确定均为 `not_exact_single_slot_replacement`，不等同于人工语义标注或 formal gate。
- [x] 产物为独立 `ai_audit/` diagnostic-only artifact：audit identity=`467c29448144182f3907462c5eeddeaeee87ce5eced8d98cb9f1497556338b67`，manifest SHA-256=`1fa1a3547c0a20da9b6b34e1f591f8cbd9d5c7b8c360f87f2d8eea4708960d27`；`reviewer_role=assistant`、`review_mode=assistant_only_structural_review`、`human_validation_performed=false`，不产生人工一致性或 Cohen's kappa 证据。
- [x] 审计只读取公开 blind packet；manifest 记录 private key、membership、victim response、Retriever output、AUC 均未读取，`external_calls_performed=0`，未启动 formal experiment。

当前唯一下一步：AI 审计结果仅作为 diagnostic-only 结构审查证据；除非用户另行明确授权，不得进行人工审计、解盲、API/victim/Retriever 调用、付费调用或 formal experiment。

### 2026-08-24：AI 结果封存口径锁定

- [x] 明确将 frozen-r2 AI audit 结果封存为 `diagnostic evidence`；不纳入 canonical formal release，不改写为 passed，不替代独立人工盲审或 formal gate。
- [x] 原始 AI audit manifest、labels、`25` 条 uncertain 及 audit identity 原样保留；不再基于该结果重跑、调参、补样或消费 fresh reserve。

当前唯一下一步：保持该 diagnostic evidence 封存；除非用户另行明确授权，不进行人工审计、解盲、API/victim/Retriever 调用、付费调用或 formal experiment。

### 2026-08-24：API 登录切换交接更新

- [x] 新建 `研究记录/API登录切换_工作交接_20260824.md`，绑定当前 frozen-r2 preparation、expanded reserve、900-row packet 与 AI-only diagnostic evidence 的完整 identity/hash。
- [x] 交接文件明确：AI 结果仅为 `diagnostic evidence`；旧交接和全部历史 artifact 原样保留；账号切换不改变协议或授权。
- [x] 当前下一步改为等待用户明确授权实现并冻结 v23 formal runtime；该授权仅包含 runtime 代码/配置/测试、离线验证和新的 runtime freeze，不包含 formal test、GPU、API、victim、Retriever、付费调用、membership、response、AUC 或 fresh reserve。

当前唯一下一步：新账号接管后先只读核验交接文件和两份项目总表；获得 formal runtime 实现/冻结授权前，不修改实验 artifact、不运行正式实验、不发起外部调用。

### 2026-08-24：v23 formal runtime r1 已实现并冻结（superseding）

- [x] 新账号按交接顺序完成只读核验：expanded frozen-r2 policy/preparation、三套 dataset manifest、900-row blind packet 与 AI-only diagnostic evidence 的逻辑 identity 和实际文件 SHA-256 均与交接表一致；只核验公开 manifest/hash，未打开 private audit key，未读取 membership、victim/LLM-only response、Retriever output 或 AUC。
- [x] 新增独立 `pcv-restoration-first-v23-formal-runtime-r1` 配置、runtime guard、freeze/validator/status CLI 与定向测试；没有改写旧 `scripts/42_run_v23_restoration_first.py` lightweight 状态入口，也没有修改 frozen-r2 preparation、packet、AI labels、ledger、旧 runtime bundle 或历史失败 artifact。
- [x] formal runtime 实现冻结了 source-level evaluation、Fact Layer r1 / selection r2、每数据集 `2250` eligible source、`3` pair / `6` query / backend、dense/BM25/hybrid 分离、`1000/1000/250` source-exclusive split、主 index `KB_Member` only、shadow index `Reserve` only、递归 forbidden-input、stage authorization 与预算操作前 fail-closed 守卫。
- [x] 新 formal runtime identity=`e8cc004b05a317b7b74b559757f46bd62e2c7ab28b961bd885e0fa9e1636a72c`；runtime bundle SHA-256=`4434cf5c43a6a676d1d1cbd66cf7c4f1b7df33712cd751438c20b19876ece369`；freeze manifest SHA-256=`c3ef3159ea8b6372e0a59ae6f2899578614962ba6426de2b11b4da6630d8fe14`，精确绑定 `30` 个 runtime 文件。因本轮明确禁止提交，`code_commit=a964e636...bca03` 仅作 freeze-time provenance，执行身份由 exact worktree file SHA-256 closure 冻结。
- [x] 独立 `validate-freeze`、`status` 与第二次 `freeze` 幂等复验均通过；formal runtime 定向 unittest=`11/11 OK`，3 个新增 Python 文件内存 AST 与 CLI help 通过。扩大到全部 `test_restoration_first_v23*.py` 的离线回归共 `102` 项，其中 `62 passed / 39 skipped / 1 failed`；唯一失败是既有 frozen-r2 测试仍断言 reservation/preparation=`not_started`，与当前已冻结的 `passed` artifact 状态冲突，未为凑通过改写该历史测试。`compileall` 因既有 Windows `__pycache__` 权限失败，按仓库规则未删除缓存或修改权限。
- [x] 首次 `freeze` 已在内存完成 manifest/identity 构造，但 Windows 在目标文件 `xb` 创建时返回 `PermissionError`；只读确认目标文件不存在、没有 partial artifact 后，使用同一 builder 的完整 canonical JSON 经 `apply_patch` 新增 freeze 文件，再由独立 validator 重算对象 identity、30-file closure 与完整文件 SHA-256。未改目录权限、未清理缓存、未覆盖任何既有文件。
- [x] freeze/status 均记录 `formal_test_started=false`、`source_content_interpreted=false`、`membership_read=false`、`victim_or_llm_only_response_read=false`、`retriever_output_read=false`、`auc_read=false`、`fresh_reserve_consumed=false`、`packet_rebuilt=false`、`external_calls_performed=0`；未运行 GPU、API、victim、Retriever、付费调用、formal test，也未提交或推送。
- [x] AI-only audit 继续以 `diagnostic_only=true`、`accepted_as_formal_gate=false` 绑定。design-r6 要求的 canonical independent human blind audit result 仍不存在，runtime status 因此为 `formal_runtime_frozen_downstream_blocked`；runtime freeze 不等于 formal test 授权。

当前唯一下一步：停止在已冻结 runtime 边界，等待用户对 canonical independent human blind audit 或其他下一项工作的单独明确授权；在 human gate 通过且 formal test 另行授权前，不启动 formal scan、GPU、API、victim、Retriever、付费调用、membership/split、response、AUC、fresh reserve 或 packet 重建。

### 2026-08-24：runtime-r1 门禁按项目负责人指令原位改为 AI 审计 + 人工核验（superseding）

- [x] 用户明确取消 canonical independent human blind audit 硬门禁，要求不新建 design/runtime revision，改由已绑定的 AI-only audit 与项目负责人人工核验共同满足 formal-scan 前置门禁。为避免改变 `configs/restoration_first_v23.yaml` 的 hash 并连锁失效 frozen-r2 preparation/packet，本次没有修改 design-r6、design manifest、frozen-r2 artifact、AI labels 或 packet，只原位修改现有 runtime-r1 执行门禁、守卫、测试和同名 freeze。
- [x] 新门禁准确记录：AI artifact 继续为 `diagnostic_only=true`，AI 单独不能满足门禁；项目负责人声明人工核验结果与绑定 AI audit 一致，组合门禁 `status=passed`。该人工核验明确为非独立、非盲审、无单独 human-label artifact，不得声称独立人工盲审、reviewer agreement 或 Cohen's kappa。
- [x] 原 runtime-r1 identity=`e8cc004b05a317b7b74b559757f46bd62e2c7ab28b961bd885e0fa9e1636a72c` / bundle=`4434cf5c43a6a676d1d1cbd66cf7c4f1b7df33712cd751438c20b19876ece369` 由本条 supersede；同名 runtime-r1 原位重算后 identity=`2f45761bd0f5c9656378d1295eec26e2b91760bbd1f32173eedc918624ad03d3`，runtime bundle SHA-256=`db051de1c31f00dec6898c03ad9b06aa0086a4ea0ed859151cd3427251a3eef7`，freeze manifest SHA-256=`b4545bc82bea38494ab2f7702770f4502591e1eae19ccbc768ce0a4814fe5e0b`，仍绑定 `30` 个 runtime 文件。
- [x] 定向 unittest `11/11 OK`、内存 AST、`validate-freeze`、`status` 与重复 `freeze` 幂等复验通过；status=`formal_runtime_frozen_gate_passed_awaiting_formal_test_authorization`，`human_blind_audit_gate_required=false`，`ai_plus_project_owner_verification_gate_passed=true`，`formal_test_started=false`。
- [x] 第一次经终端传递新 canonical JSON 时，非 ASCII 路径被控制台编码替换为 U+FFFD，独立 validator 以 `formal_runtime_freeze_identity_drift` 拒绝；随后改用 ASCII-escaped JSON 原位重算并通过。未将失败状态写成 passed，也未读取 source content、private key、membership、victim/LLM-only response、Retriever output 或 AUC。
- [x] 本次没有启动 formal scan/test、GPU 长任务、API、victim、Retriever 或付费调用，没有消费 fresh reserve、重建 packet、提交或推送；所有相关计数保持 `0/false`。runtime 门禁通过不等于正式实验已获授权或已经执行。

当前唯一下一步：等待用户单独明确授权 formal test 的具体首阶段、dataset、预算及 GPU/外部调用边界；在该授权前保持 formal scan/test、GPU、API、victim、Retriever、membership/split、response 与 AUC 未启动。

### 2026-08-25：v23 formal test 首阶段 EDGAR formal source scan passed（superseding）

- [x] 用户明确授权正式实验首阶段；执行范围冻结为仅 `formal_source_scan / edgar`，使用 authorization=`737629ea3fd9dc44f0a4e53627cccfe7b2edda48f56d5e4dc2fe3452fd02dea8`，source-read budget=`3710`，目标为按冻结顺序取得恰好 `2250` 个 eligible source。GPU selector 允许；API、victim、Retriever、外部/付费调用、membership/split、response、AUC、Enron、PubMed 与下游均未授权。
- [x] 为承载正式执行入口，在同名 runtime-r1 内补齐 formal-scan authorization、预算 journal、逐 source write-ahead ledger/anchor、checkpoint/resume、selector 执行、正式 selected source/pair 输出与 validator；最终冻结 identity=`6c1021373bf58afa252083a58dc8be315828bf17c99ca55766f2656b8e5372f8`，runtime bundle SHA-256=`7cd2bd45471c3a81c20b1b3eb68dc14feb811d74f02a834d9ce445301df69271`，freeze manifest SHA-256=`3899e05921ef4b61a02bc6d406bad454ef12336cd56bb6e4ef395547d6daa4f5`，精确绑定 `32` 个 runtime 文件；本条 supersede 前一条的 `2f45761...ad03d3` runtime identity。
- [x] EDGAR formal source scan 完成并由独立 validator 复验为 `status=passed`：实际读取/预算 charge=`2327`，取得 `2250` 个 selected source，每 source 恰好 `3` pair，共 `6750` pair；达到目标后立即停止。selected source set manifest SHA-256=`96d2bff9abd20f59f95b3e957d5485bd89941925fe12bd1476524c6d0fb62c28`，selected sources SHA-256=`fcce9e7e8923858812a32ad449c5ac6ced909414a16a3f71e855fc0ee4fc495f`，selected pairs SHA-256=`0e1382c695ec00507acedaf75276b4083228d66e8bc655d77cf21f9451b14633`。
- [x] budget journal 共 `2327` 行、尾序号=`2326`；最终 consumption-ledger tip=`80d02112839672a6af158575ea926ca1aea0b1d6bdcd4681a1e2a665b3889b56`，唯一 final anchor SHA-256=`05e882e428c2ad0118d434f0fc7bfb491ab88478f65cadd25e22e57a727396e4`，均与 selected-source-set manifest 精确一致。`validate-freeze`、authorization validator、formal-source-scan validator 与 live `status` 全部通过；live status=`formal_source_scan_edgar_passed_awaiting_next_authorization`。
- [x] 运行期间两次直接关闭终端留下 stale `.formal-source-scan.lock`；每次均先读取锁内 PID、确认对应进程不存在，再只删除该精确临时锁并用同一 authorization 断点续跑。第一次从 `viewed=2` 恢复，第二次从 `viewed=2222 / eligible=2148` 恢复；未删除、回滚、覆盖或重写任何预算、ledger、anchor、source result 或历史 artifact，不能把中断表述为实验失败。
- [x] 本阶段 `gpu_used=true`、`formal_test_started=true`；`api_calls_performed=0`、`victim_calls_performed=0`、`retriever_calls_performed=0`、`external_calls_performed=0`。未读取 membership、victim/LLM-only response、Retriever output 或 AUC，未运行 split、Enron、PubMed 或任何下游正式阶段。

当前唯一下一步：停止在 EDGAR formal source scan passed 边界，等待用户对下一执行单元的单独明确授权；若继续正式扫描，按冻结顺序下一单元只能是 Enron `formal_source_scan`，并须另行冻结 dataset/budget/GPU 边界。授权前不得启动 Enron、PubMed、source-exclusive split、API、victim、Retriever、response、AUC 或其他下游。

### 2026-08-25：Enron/PubMed formal source scan successor 已冻结，Enron authorization passed

- [x] 用户明确授权继续完成同一 `formal_source_scan` 的 Enron 与 PubMed，并保持固定顺序 `Enron -> PubMed`；授权只包含本地 CUDA selector 与逐 dataset formal source scan，不包含 source-exclusive split、membership、API、victim、Retriever、response、AUC、外部或付费调用。
- [x] r1 执行入口被有意收窄为 EDGAR-only，直接复用会被 `first_dataset=edgar`、`first_dataset_maximum_source_reads=3710` 与 prior-attempt guard 拒绝。为保留已通过 EDGAR 的 32-file freeze 与正式 artifact，新建最小 `pcv-restoration-first-v23-formal-runtime-r2` successor overlay/薄封装；不修改 r1 配置、代码、freeze、authorization、selected source/pair、ledger 或 anchor。
- [x] r2 只改变 formal-scan 编排：hash-bind 并 carry forward EDGAR passed artifact，允许在同一 successor identity 下按 `Enron -> PubMed` 分别授权、逐 source checkpoint/resume；Fact Layer r1、selection r2、GLiNER2/model lock、实体策略、阈值、排序、`2250 source × 3 pair` 目标、budget-before-read、write-ahead ledger/anchor 与 forbidden-input 均不变。
- [x] r2 freeze identity=`5ce4e736aac3fd9127b33d89b9b3533d5155502d375ac44548f17142ad0095bd`，runtime bundle SHA-256=`921beffe6b5cd62184a4e35e0ad0904b89a41c993f8e982b8e8747f8a25dda4f`，freeze manifest SHA-256=`a26f114a1d45a5a49c93221b8b632df230deea249e9f0753c1bdfb8073901ae3`，41-file closure；独立 validator 同时确认 carried EDGAR=`2327 viewed / 2250 selected / 6750 pair` 与 r1 freeze identity=`6c102137...372f8` 仍为 passed。
- [x] Enron authorization=`fb0f6f94c812003155c49c27555179c9c7707bd28860e71c128155eab2152a89` 已生成并独立验证，绑定 r2 identity、EDGAR final ledger tip=`80d02112839672a6af158575ea926ca1aea0b1d6bdcd4681a1e2a665b3889b56`/anchor、dataset=`enron`、source-read budget=`32750`、target=`2250`；GPU=true，API/victim/Retriever/external=false。PubMed budget 冻结为当前剩余 pool 上限 `46450`，但其 authorization 只能在 Enron manifest passed 并产生最终 ledger tip 后生成。
- [x] 新编排命令会优先复用既有 Enron authorization；Enron validator passed 后才自动生成/验证 PubMed authorization，然后继续 PubMed。中断后重复同一命令按 dataset/source checkpoint 续跑，不重复覆盖已完成结果；异常直接关闭终端可能遗留 stale lock，仍须先核 PID 再处理。
- [x] r2 定向 unittest=`8/8 OK`、r1 定向 unittest=`14/14 OK`、AST/CLI/freeze/auth validator 与 `git diff --check` 通过。v23 扩大回归共 `112` 项：`72 passed / 39 skipped / 1 failed`；唯一失败是既有 frozen-r2 测试仍期待旧 reservation 状态，而 append-only ledger 已推进后实际返回 `stale:fresh_audit_r2_reservation_group_tip_drift`，未为凑通过改写历史测试。环境未安装 `ruff`，未安装依赖。
- [x] Python `xb` 新建 r2 freeze 再次遭 Windows `PermissionError`；确认目标不存在且无 partial 后，使用同一 builder 的完整 ASCII-escaped JSON 经 `apply_patch` 新增，再由 validator 重算对象 identity 与 41-file closure。授权准备阶段没有读取 Enron/PubMed source，没有修改 ledger，所有调用计数仍为 `0`。聚合 status 在“authorization 已存在但尚未启动”的短暂状态仍显示 awaiting authorization；执行门禁以已通过的独立 authorization validator 为准，此文案不影响运行身份或授权。

当前唯一下一步：用户本人运行 r2 的 `run-remaining-formal-source-scans` 长命令；它必须先完成并验证 Enron，之后才生成 PubMed authorization 并继续 PubMed。两者全部 passed 后立即停止，不启动 split 或任何下游。

### 2026-08-27：Luna query transport 持续重连策略（代码更新，待 successor freeze）

- [x] 用户明确要求：Luna 生成 query 时若遇到连接超时或其他可重试 transport 错误，必须指数退避并持续重连，直到取得可用响应；本次仅修改 opt-in 客户端行为与 `luna_query_generator` profile，不执行真实 API 调用。
- [x] `OpenAICompatibleChatClient` 新增 `retry_until_success`；该开关覆盖网络层 `URLError`/`TimeoutError`/`ConnectionError` 与既有瞬时 HTTP 状态码，保留请求限流、退避上限与每次物理尝试的 retry count。普通 sibling、victim/RAG 默认仍为有限重试或不重试。
- [x] Luna query 的 JSON/schema、实体槽位、NLI、复制率和多样性失败不被误判为网络错误，仍走原有 correction retry / fail-closed 逻辑；新增离线 timeout→URLError→success 测试，相关 query/LLM 回归与内存 AST 均通过，`git diff --check` 通过。
- [ ] 当前已冻结的 v23 formal runtime/query contract 仍绑定 `transport_attempts_per_query=1`；本次代码更新不得 retroactively 写入旧 freeze。正式进入 v23 Luna stage 前，必须创建并验证包含持续 transport 重连语义的新 successor query/runtime identity。

当前正式 source scan 的执行边界不变；Luna/API/victim/Retriever 与下游仍需独立授权，且本次未产生外部调用或新实验 artifact。

### 2026-08-27：v23 Luna query-generation runner 接入（离线实现，待 query successor freeze）

- [x] 新增 `src/prepare/restoration_first_v23_query_generation.py` 与 `scripts/48_run_v23_luna_query_generation.py`：按 release frozen pair 逐一构造 Q+ / Q-，Q+ 只使用 exact frozen `true_claim`，Q- 只使用 exact frozen `counterfactual_claim`；不做 pair/source 选择、不生成 counterfactual、不读取 membership、victim、Retriever 或 score。
- [x] runner 先校验 release manifest/status、文件 hash、pair identity、三 pair/source、dataset/group scope；Reserve 行只允许作为 release 输入存在，不生成 Reserve query。query plan 按 dataset → split/source order → pair order → Q+ → Q- 排序。
- [x] 接入 v23 strict query validator：unknown field、question mark、relation cue、claim subject、unresolved reference、new heuristic entity surface 与 pair/polarity mismatch 均 fail closed。每个 cell 只调用一次逻辑生成；schema/semantic/transport 异常保留 failed cell，不在 runner 层重复调用。
- [x] 产物协议已接上：`luna_prompt.txt`、query contract manifest、`query_rows.jsonl`、durable `query_attempts.jsonl`、failed-cell sidecar 与 `query_plan_manifest.json`；query contract 在首个 API call 前绑定 model/version/endpoint、prompt/schema/validator hash、generation parameters，要求显式 frozen Luna model version。
- [x] 新增 4 个离线单测，覆盖 prompt substitution、Reserve 排除、Q+/Q- 顺序、坏响应保留与无 semantic retry；本轮定向 query/LLM/v20 回归 `57/57 OK`，内存 AST、CLI help、`git diff --check` 通过，API/external calls=`0`。
- [ ] 新 runner 文件尚未写入已冻结的 r2 runtime bundle；不能把 r2 source-scan identity 当作 query runtime identity。正式 Luna stage 前需创建并验证包含 runner、持续 transport 重连语义及 query contract binding 的 successor identity/freeze，再生成每 dataset 的独立 API authorization。

当前唯一下一步：先按既定顺序完成 Enron/PubMed source scan、source-exclusive split、Reserve shadow gate 与 release finalize；release passed 后再在 successor query/runtime freeze 边界内授权并执行 Luna query-generation。未获该授权前不发起 API 或付费调用。

### 2026-08-31：v23 r2 Enron/PubMed formal source scan 全部 passed

- [x] 用户完成 `run-remaining-formal-source-scans` 串行执行；r2 formal runtime identity=`5ce4e736aac3fd9127b33d89b9b3533d5155502d375ac44548f17142ad0095bd`、bundle=`921beffe6b5cd62184a4e35e0ad0904b89a41c993f8e982b8e8747f8a25dda4f`、freeze SHA-256=`a26f114a1d45a5a49c93221b8b632df230deea249e9f0753c1bdfb8073901ae3` 复验通过，r1 EDGAR passed artifact 继续按冻结绑定 carry forward。
- [x] Enron authorization=`fb0f6f94c812003155c49c27555179c9c7707bd28860e71c128155eab2152a89`：`15371 viewed -> 2250 selected source -> 6750 selected pair`；manifest SHA-256=`cf41fa159f07fbcd3df4e79a74bb2c30dcc3807ffbb7ecc67ed67778ef305065`，selected sources SHA-256=`05de81c7d5dba3ae132d375112d398221e3f61f7fada81dc14c6445eb9b9bda4`，selected pairs SHA-256=`7d7321e73994f29a44b0f4c6509deb7127b86f157434be5eacfb0981ad0efb22`；final ledger tip=`02e9edd777d84ee36e36c5ae8bacc3e2cdec9f7cfa4d03a4b501a5cccd73e17c`，anchor=`b8ce765cb874f5c05912728647ed0132c03e6a6b1fefc1dc61d83dfba813f983`。
- [x] PubMed authorization=`64fe2dbcaa077fec85f196f7ab5f322f9d8b3a519493c8457def2e5c38762452`：`2394 viewed -> 2250 selected source -> 6750 selected pair`；manifest SHA-256=`9a49093137c91cda39ccfabf7f359d3264e954d84f18706f75078a4eac6e9c3e`，selected sources SHA-256=`bcacace08908a9df312ab73bb4f1d7436599413fc0af299f37249c2d68267e09`，selected pairs SHA-256=`b5940227b739b941e44d60be9486b744e3a759dad2e7ecde2c46c5019f96bbb9`；final ledger tip=`dfbb9254950323506d278caa8fecff56a5e616914190b6b81f1fa9cb2d3f4754`，anchor=`9f345df1334ecdb7536eda5e249d54291a302c8277e1542b14535ad07c80aff1`。
- [x] `validate-freeze`、两份 authorization validator 与两套 formal-source-scan validator 均为 `passed`；全局 status=`formal_source_scans_all_datasets_passed_awaiting_split_authorization`。三数据集 source scan 至此齐备：EDGAR/Enron/PubMed 各 `2250` selected source、各 `6750` selected pair。
- [x] Enron/PubMed 本阶段 `formal_test_started=true`、使用已授权本地 GPU；API/victim/Retriever/external calls 均为 `0`。source-exclusive split、membership、response、AUC、Reserve shadow、release finalize 与 Luna query-generation 均未启动。

当前唯一下一步：停止并等待用户单独授权 v23 source-exclusive split；授权前不得运行 split、membership、Reserve shadow、API/victim/Retriever、response、AUC、release finalize 或正式 Luna query-generation。

### 2026-08-31：v23 source-exclusive split runtime 冻结并通过（superseding）

- [x] 用户明确授权 v23 source-exclusive split；本阶段仅执行三数据集 source-level、离线、确定性划分，未读取 source content、membership、victim/LLM-only response、Retriever output 或 AUC，不启动 Reserve shadow、release、Luna/API、victim 或 Retriever。
- [x] 为修复首次运行暴露的 freeze 摘要缺少 `code_commit` 缺口，保留旧 `restoration_first_v23_split_runtime_r1.freeze.json` 及其历史 artifact，不覆盖；创建 successor freeze `restoration_first_v23_split_runtime_r1_patch1.freeze.json`。新 runtime identity=`ac8ca724bb30d4858d4a074328b5549ff194bc1f31fddf4731139f506963a4ed`，runtime bundle=`6b22303ee82fdb9b7cfcadd73e79976d59c34220277cbf2426f71a0c59beb984`，freeze manifest SHA-256=`c79a38a83053ea82794a500cf6da84b2c960a5b2d3bdb8e4440923f7316cf7bf`，精确绑定 `28` 个文件；split config SHA-256=`a4926927c03c3c6b516fd534d50b92621280e1ed9c443400292c20e613dd7d8f`。
- [x] 三份 `source_exclusive_split` authorization 均生成并独立验证 passed，均 `budget_limit=0`、`formal_test_allowed=true`、GPU/API/victim/Retriever/external=false：EDGAR authorization=`68fd42d4cd56ad62e37709b53be76d33ef06031cf37626b642a47e5d6b312472`（文件 SHA-256=`3dcaa067cf18d2b88cc52cf5aa48f3dfadedb213027cb271ec51c3e5b3117528`）；Enron=`303c390f7a8eb124b02cf6d841c0da8e2190141012924d26a1a8377037806855`（`5d45854b0642e468ad15854604153cb164100c9b78ade0fc96aaa935bdb7c177`）；PubMed=`481590ab49171cc2c3cbefcc57315612d97272743d2c53ddc9e83c66397806d1`（`393b3ea60db9a441c942fec6c7b27ca4c267561b1bd882335951beaa9fdf2a77`）。
- [x] `run-source-exclusive-splits` 与独立 `validate-source-exclusive-split` 均 passed；固定 seed=`42`、顺序=`edgar -> enron -> pubmed`。EDGAR manifest/rows SHA-256=`e8f627d02015c4820bce5d7a718f76df0d799a1996ef3b82af25e6606d69739a` / `7e30f821951f959f9d3237e62e43a7c476b6fb50f264e0a3e241fafbbe661f0d`；Enron=`bb27b1f922c6300fc4be15088841955470484f698d919dc761523cefaaf56334` / `1e6e89ec681de5fca28b0df709cc30962757bcf3fe202450e1dfa66c7afedf6c`；PubMed=`975dca0f010b986d68e14f98f90314974067e8e707fbb2a7990a52b11a3bd04d` / `721e73a74147b4263b2808a2fffb07885a0c3afbb2df311dee0e577c3881e3a4`。每个 dataset 均 `2250` rows、组计数 `1000/1000/250`，`required_zero_overlap_passed=true`，跨三数据集 source hash 零重叠。
- [x] split live status=`source_exclusive_split_all_datasets_passed_awaiting_shadow_authorization`；API/victim/Retriever/external calls=`0`，GPU 未使用，membership/source-content flags=`false`。离线定向 unittest=`5/5 OK`，`validate-freeze`、授权验证、split validator 与 `git diff --check` 通过；首次旧 identity 的部分 EDGAR rows 原样保留，新 successor identity 下三套 rows 重新生成并通过内容一致性校验，没有覆盖或删除历史 artifact。

当前唯一下一步：停止在 source-exclusive split passed 边界，等待用户对 `Reserve-only shadow gate` 的单独明确授权；未获授权前不构建 shadow index、不读取 membership、不运行 release、API/victim/Retriever、response、AUC 或 Luna query-generation。

### 2026-08-31：v23 Reserve-only shadow gate runtime 已实现并冻结（等待 Retriever 授权）

- [x] 用户明确授权仅补齐并测试 `Reserve-only shadow gate` runtime；新增 `configs/restoration_first_v23_shadow_runtime_r1.yaml`、`src/prepare/restoration_first_v23_shadow_runtime.py`、`scripts/50_run_v23_reserve_shadow.py` 与离线定向测试 `tests/test_restoration_first_v23_shadow_runtime.py`。实现绑定已通过的 v23 source-exclusive split successor：identity=`ac8ca724...a4ed`、bundle=`6b22303e...b984`、split freeze SHA-256=`c79a38a8...c7bf`。
- [x] shadow runtime freeze 已由同一 builder 构造并经 `apply_patch` 写入（Windows Python `xb` 创建临时文件权限限制未被绕过）；shadow runtime identity=`959f3591fc5d59cf8c4b02769ce01e6b2947f37ecc508f8c928be3d406bebf82`，runtime bundle=`df3bf7cc3eca82757930ed77fdff56ee484fd4b903bcd67e57df5c65faf4c5e8`，freeze manifest SHA-256=`4157289491c815c5a611578b0047fc714fadd09abffd429d802edb89074b82fb`，exact implementation closure=`20` files。
- [x] runtime contract 固定 `Reserve=250` source、每 source `3` pair、Q+/Q- 共 `6` query、每 dataset/backend `1500` logical retrieval calls、top-k=`5`，backend 顺序 `dense -> bm25 -> hybrid`；shadow index 独立写入 `artifacts/v23/shadow_indexes/`，主 `indexes/` 禁止写入。dense/hybrid 强制 CUDA/FAISS，BM25 使用排序 token adapter；每 cell retriever 在首笔预算 charge 前加载并复用，预算 journal 与 retrieval rows 均 append-only/fsync/hash-chain。
- [x] 离线定向 unittest=`9/9 OK`；覆盖 config boundary、freeze identity/timestamp independence、Reserve/main overlap、BM25 determinism、row schema/finite score、partial row fail-closed、result isolation、budget duplicate/exhaustion 与 dataset/backend authorization scope。内存 AST、CLI help、freeze validator、status、重复 freeze 幂等和 `git diff --check` 均通过。
- [x] 当前 `status=reserve_shadow_runtime_frozen_awaiting_retriever_authorization`；9 个 dataset/backend cell 均 `awaiting_authorization`，`retriever_calls_performed=0`、`api_calls_performed=0`、`victim_calls_performed=0`、`external_calls_performed=0`，`membership_read=false`、`source_content_interpreted=false`。本阶段没有准备 authorization、没有读取 Retriever output、没有构建 shadow index，也没有启动 GPU/API/victim/付费长任务。
- [ ] `prepare-shadow-authorizations`、每 cell `run-shadow-gate` 和 `validate-shadow-gate` 尚未执行；implementation/test authorization 不等同于 Retriever execution authorization。

当前唯一下一步：等待用户单独明确授权实际 Reserve-only shadow retrieval；授权后由用户按 `validate-freeze -> prepare-shadow-authorizations -> validate-shadow-authorization -> run-shadow-gate -> validate-shadow-gate` 顺序逐 cell 执行。全部 9 个 cell passed 前不得进入 release finalize、Luna/API、victim 或正式主 index。

### 2026-08-31：shadow runtime r1 授权准备失败，r2 successor 修复并授权成功

- [x] 用户先执行 r1 `validate-freeze`，结果 passed；随后执行 `prepare-shadow-authorizations` 时在 split-manifest schema 校验触发 `AttributeError: restoration_first_v23_split_runtime has no attribute _assert_exact_fields`。该失败发生在首个 authorization 写入前，未启动 Retriever/GPU、未读取 source content，r1 freeze 与历史证据保持不变。
- [x] 根因是 r1 shadow runtime 错误地直接访问 split runtime 的私有 helper；新增最小 r2 successor wrapper，通过 shadow runtime 自有 `_assert_exact_fields` 调用 split 模块公开可用的字段常量，并将 CLI 绑定到 r2 config/freeze。旧 r1 freeze 不覆盖，作为 superseded implementation evidence 保留。
- [x] r2 freeze 已通过独立 validator：shadow runtime identity=`153515b446ac78670d498bc464bb6556a519bee76505f29cdf5efd60414953c9`，runtime bundle=`ae9f781eddef8409011af3524f7928e04885fcd0eae03ac07ffa2ef571036acf`，freeze manifest SHA-256=`8f67dadae735eb64df00f4422847f31811ad46c4a84a3aa16da65a1d8bc1fc8a`，exact closure=`22` files。
- [x] 修复版 `prepare-shadow-authorizations` 成功生成并内部验证 9 个 dataset/backend authorization：每 cell budget=`1500`，GPU/Retriever allowed，API/victim/external calls=false；授权仅记录运行许可，不代表 gate 已执行。当前 status=`reserve_shadow_gate_authorized_or_running`，9 个 cell 均未完成，shadow budget journal=`0`。
- [x] 本次修复/授权阶段 API/victim/Retriever/external calls=`0`，membership/source-content interpreted=`false`，shadow index 尚未创建。r1 失败原因、r2 identity、授权 JSON 与后续 cell 状态均保留为可审计证据。

当前唯一下一步：用户逐 cell 先执行 `validate-shadow-authorization`，再运行长时间 `run-shadow-gate`；每个 cell 完成后执行 `validate-shadow-gate`。9 个 cell 全部 passed 前不得进入 release finalize 或下游 API/victim/formal 主 index。

### 2026-08-31：r2 authorization UTF-8 复核通过

- [x] 用户使用 PowerShell `Get-Content | ConvertFrom-Json` 批量读取授权时出现多个 JSON syntax error；根因是 Windows PowerShell 默认代码页未按 UTF-8 解码包含中文 `user_authorization_record` 的 JSON，不能据此判定 artifact 损坏。
- [x] 使用 Python `Path.read_text(encoding='utf-8')` 筛出 r2 identity=`153515b4...953c9` 且 `authorized_stage=reserve_only_shadow_gate` 的 9 个文件，并通过公开 `validate_shadow_authorization` 全部复核：`validated_count=9`，每个 budget=`1500`，API/victim/external=false。
- [x] 编码复核阶段未读取 source content、未构建 shadow index、未写 budget journal、未启动 Retriever/GPU/API/victim；当前状态仍为 `reserve_shadow_gate_authorized_or_running`，9 个 cell 均未完成。

当前唯一下一步：若在 PowerShell 中批量验证，必须使用 `Get-Content -Encoding UTF8 -Raw`；也可直接按 9 个 authorization path 调用 CLI。随后由用户逐 cell 运行 `run-shadow-gate` 长命令并验证。

### 2026-08-31：shadow runtime r2 运行前置失败，r3 successor 修复 split helper API

- [x] r2 的 9 个 authorization 虽已生成并验证，但用户执行 `run-shadow-gate --dataset edgar --backend dense` 时在 `_read_split_rows` 触发 `AttributeError: restoration_first_v23_split_runtime has no attribute validate_split_rows`；失败发生在读取/校验 split rows 阶段，尚未构建 shadow index、读取 Reserve source、调用 Retriever/GPU 或写入 budget journal。
- [x] r2 失败留下的目录 `artifacts/v23/shadow/153515b446ac78670d498bc464bb6556a519bee76505f29cdf5efd60414953c9/edgar/dense` 为空；未发现 query plan、Reserve input、shadow index、retrieval rows 或 budget journal。该 partial attempt 与 r2 authorization/freeze 均保留为 superseded/failed evidence，不覆盖、不删除、不重跑伪装为同一身份。
- [x] 新增最小 r3 successor wrapper/config，覆盖 split manifest 与 split rows 两个 helper 引用：分别使用 `split_runtime.base._assert_exact_fields` 与 `split_runtime.formal_runtime.validate_split_rows`；科学 contract、source order、Reserve-only 隔离、预算、backend/top-k 与 forbidden-input 边界均不变，旧 r1/r2 freeze 保持原样。
- [x] r3 `validate-freeze` 通过：shadow runtime identity=`b74ae66698f99ad31daee59fed8b72f899e8be365760fc2d1def0f208ba92992`，runtime bundle=`38604d9664ce8e6625a7967bd37f875b6c84073e6dc747fb32ac485ca072e98a`，freeze manifest SHA-256=`50d103fa895f95860cec9ba84aaa1d5180a2a6bb4d52799f4b42b86f4eda3771`，runtime file count=`22`；CLI 已切换到 r3，定向 unittest=`9/9 OK`。
- [x] r3 freeze/测试阶段 API/victim/Retriever/external calls=`0`，GPU 未使用，membership/source-content interpreted=`false`；r2 的 9 个 authorization 不再适用于 r3，r3 authorization 尚未生成。

当前唯一下一步：使用同一用户授权记录生成并验证 r3 的 9 个 dataset/backend authorization；之后由用户按既定顺序逐 cell 运行长时间 `run-shadow-gate`，每个 cell 完成后立即执行 `validate-shadow-gate`。未生成并验证 r3 authorization 前不得运行任何 shadow cell；9 个 cell 全部 passed 前不得进入 release finalize 或下游 API/victim/formal 主 index。

### 2026-08-31：v23 shadow runtime r3 authorization 已生成并验证

- [x] 使用用户明确授权记录“用户明确授权执行 v23 Reserve-only shadow gate Retriever 长任务”生成 r3 的 9 个 dataset/backend authorization；每 cell `budget_limit=1500`，`gpu_allowed=true`、`retriever_allowed=true`，`api_allowed=false`、`victim_allowed=false`、`external_calls_allowed=false`。
- [x] 9 个 authorization ID 按固定顺序为：EDGAR `dense=32e292670e1371cd1ea538038bd14ebf258d0cb7b09491b267e36b4730141e41`、`bm25=df18d335508770a26d14d180fa5094119e98ca702a0f988caecc9d3c6b8cd8cd`、`hybrid=65f1986c23ccc81a04c65a3460d8a2446061830c9136be7c3ce59b98f06f38cc`；Enron `dense=c8852cdcdd7041ff3716271ff916f0b692dc8284cc738bf3b8642abaf1c7cfb2`、`bm25=157a52d3c3d8d64c10fc0b90ec6fd4c9dc9ddfd68918f29e6563a73304f6ec4b`、`hybrid=d6331e6622c0322dcaaf83621afdf23e7d21582f20ac657dceb77ad875da2f26`；PubMed `dense=720177ad4ce651174dd16511fc189d9a4c6d21363c5bb0bb6b39e275cc9b353e`、`bm25=26e09ab1434cfd549fef26d06862e7978d60bd07515dfa66b24af066ed6a300d`、`hybrid=537d3974f97513c8c920d9758291aca2d6bb1631b82c247c527cc346227b664b`。
- [x] 使用 Python UTF-8 读取逐个公开 validator 复核，`validated_count=9`、全部 `passed`；进一步核对 9 个文件的授权文本 `record_exact=true`，均绑定 r3 identity=`b74ae66698f99ad31daee59fed8b72f899e8be365760fc2d1def0f208ba92992`。
- [x] 授权阶段仍未读取 Reserve source content、未构建 shadow index、未写 budget journal、未启动 Retriever/GPU/API/victim，计数均为 `0`；全局 status=`reserve_shadow_gate_authorized_or_running`，9 个 cell 均 `completed=false`。

当前唯一下一步：主人先运行 `edgar/dense` 的 `run-shadow-gate` 长命令；命令返回后立即运行同 cell 的 `validate-shadow-gate`。仅在该 cell validator passed 后继续 `edgar/bm25`，严格按 `edgar -> enron -> pubmed`、每个 dataset 内 `dense -> bm25 -> hybrid` 串行推进；任何错误先执行 `status`，不要盲目重跑。

### 2026-08-31：r3 shadow gate 首次运行在 query-plan 前置处失败（未产生 Retriever 结果）

- [x] 用户执行 r3 `validate-freeze` 与 EDGAR/dense authorization validator 均 passed；随后 `run-shadow-gate --dataset edgar --backend dense` 在 `_query_plan -> _load_pairs` 触发 `KeyError: pair_bindings`。
- [x] 根因是既有 `validate_shadow_runtime_freeze()` 返回校验摘要，而 `_run_one_shadow_cell()` 继续把该摘要当作完整 freeze manifest 使用；这是一处实现传递错误，不改变 Reserve-only、pair/query 预算、backend、split 或检索科学语义。失败发生在 query plan 生成前，r3 EDGAR/dense 目录保持空目录，未读取 Reserve source content、未构建 shadow index、未启动 Retriever/GPU、未写 budget journal。
- [x] 已完成不改仓库的进程内兼容探针：先用现有 validator 校验 r3，再将完整 freeze manifest 仅注入当前进程；EDGAR pair bindings 成功读取 `6750` 行，探针未写 artifact、未启动 Retriever/GPU。r4 草稿已撤回，未创建新 protocol/freeze/authorization。

当前唯一下一步：不再为该语义不变 bug 自动创建 successor。若主人继续当前 diagnostic-only shadow gate，应使用一次性兼容入口在同一进程加载完整 freeze manifest 后运行首个 cell；该入口不是新的 canonical runtime。若要求永久修复 CLI，则需主人明确接受一次 pre-run runtime re-freeze 与重新授权，因为现有 r3 exact file-hash freeze 会拒绝任何代码修改。

### 2026-08-31：EDGAR/dense Reserve-only shadow gate passed

- [x] 主人通过进程内兼容入口完成 r3 EDGAR/dense shadow gate；独立 validator 同样 `passed`。authorization=`32e292670e1371cd1ea538038bd14ebf258d0cb7b09491b267e36b4730141e41`，logical retriever calls=`1500`，retrieval rows=`7500`，external calls=`0`。
- [x] gate manifest SHA-256=`e8f674eb885871c042ee0d3781a05e355fe9db670e72771c95be75679170793b`；shadow index manifest SHA-256=`a87dfa277961d5450206d7e810fb102bb65f8df5646cc6127eff616d63f9a2c3`；retrieval rows SHA-256=`cc54b50a8cc6d2316f365c7f3f0e64dee50936232c795754fa88646718b1dbd2`；query plan SHA-256=`df7d2f8b382f28d371cfed8fdc4d7acd9bb850ad3b108a1a1a2ddaa3bc36ec82`。
- [x] `artifacts/v23/shadow/b74ae66698f99ad31daee59fed8b72f899e8be365760fc2d1def0f208ba92992/edgar/dense/` 已生成 query plan、Reserve input、retrieval rows、contract/gate manifest；对应 shadow index manifest 已生成于独立 shadow index root。status 显示 EDGAR/dense completed，其他 8 个 cell 未完成。

当前唯一下一步：主人使用同一兼容入口串行运行并验证 `edgar/bm25`；通过后再运行 `edgar/hybrid`。不要使用普通 CLI 直接运行，以免重复触发 r3 freeze 摘要的 `pair_bindings` 缺口。

### 2026-08-31：v23 Reserve-only shadow gate 9 个 cell 全部 passed（superseding）

- [x] 主人已按固定顺序完成并验证全部 9 个 dataset/backend cell：`edgar/{dense,bm25,hybrid}`、`enron/{dense,bm25,hybrid}`、`pubmed/{dense,bm25,hybrid}`；每个 cell `1500` logical Retriever calls、`7500` retrieval rows，合计 `13500` calls，status=`reserve_shadow_gate_all_cells_passed`。
- [x] 当前 r3 shadow runtime identity=`b74ae66698f99ad31daee59fed8b72f899e8be365760fc2d1def0f208ba92992`，runtime bundle=`38604d9664ce8e6625a7967bd37f875b6c84073e6dc747fb32ac485ca072e98a`，freeze manifest SHA-256=`50d103fa895f95860cec9ba84aaa1d5180a2a6bb4d52799f4b42b86f4eda3771`；`validate-freeze` 通过，未修改 r3 frozen 文件。
- [x] 9 个 shadow gate manifest SHA-256：EDGAR/dense=`e8f674eb885871c042ee0d3781a05e355fe9db670e72771c95be75679170793`、EDGAR/bm25=`86622441ec5f8a00016a9955490d10e36a6c07ee21565458ad503e9dbb56a5d4`、EDGAR/hybrid=`b74f22ea92f11d70054105a378ae2bf1f8846e7561d67befd2a1c34bfe8645cd`；Enron/dense=`f2a40265795c66a768f5d44f09f47d8f2211a9d4e02821cedc7c076bfa428074`、Enron/bm25=`60fa08479e57010e8f52661ca705beb8df004f22850b04033325bcb4a0ee2625`、Enron/hybrid=`072699c7f86656769a96185958f5bdd474ea9908508994fbecc7498015448825`；PubMed/dense=`4e6fea4d9ff72c7b9d16ad8e71f106a92af25596afe262571b0a393cfc7aa57e`、PubMed/bm25=`0a34f67ba136d91339f55ae46a322fd05361ede1545f3330a22651f676e5d3c5`、PubMed/hybrid=`2c91e2d227b605257b327c1aae036e7ff283c4cb2b0a7e4e48d5bb7f3125cb40`。
- [x] 本阶段只使用 Reserve-only isolated shadow index；主 `indexes/` 未写入。`api_calls_performed=0`、`victim_calls_performed=0`、`external_calls_performed=0`，`membership_read=false`、`source_content_interpreted=false`；未产生 API/victim response、AUC 或正式主 index 结果。
- [x] shadow gate 完成边界已验证：9 个 authorization 均存在且 completed，global `retriever_calls_performed=13500`；r1/r2 失败证据、r3 兼容入口及所有 manifest/artifact 保持可审计，不覆盖、不删除。

当前唯一下一步：停止在 Reserve-only shadow gate 全部 passed 边界，等待主人对 release finalize 的单独明确授权；授权前不得启动 release、Luna/API、victim、正式主 index、response 或 AUC。普通 `run-shadow-gate` 仍可能触发 r3 freeze 摘要的 `pair_bindings` 缺口，后续若需复核应沿用已验证的进程内完整-freeze 兼容入口，不能因此新建 successor。

### 2026-08-31：v23 release finalize 已通过

- [x] 用户明确授权执行 v23 release finalize；本阶段仅在本地离线聚合已通过的 formal selected pairs、source-exclusive split 与 9 个 Reserve-only shadow gate manifest，不启动 Luna/API、victim、正式主 index、Retriever 或正式评估。
- [x] release 使用 formal runtime identity=`5ce4e736...095bd`、runtime bundle=`921beffe...dda4f`；生成并验证 `artifacts/v23/release/5ce4e736aac3fd9127b33d89b9b3533d5155502d375ac44548f17142ad0095bd/release_manifest.json` 与同目录 `release_rows.jsonl`。
- [x] release manifest SHA-256=`e998c602823a7e5bc2d695d04dc25f16da33fe603d38aa67ef436e720965333a`；release rows SHA-256=`f370bf9bef5ab40591e3ac8828623eab64909378d560029c9a50cf1169c5ba77`；`release_row_count=20250`，按 dataset/group/split/pair 固定排序，未把 chunk 当独立评估样本。
- [x] manifest 继续绑定三数据集 selected-pair、split 与 9 个 shadow gate hashes，并绑定 AI diagnostic manifest=`1fa1a354...8960d27`；AI 证据仍为 diagnostic-only，项目负责人人工核验为组合门禁，不声称独立盲审或 Cohen's kappa。
- [x] `finalize-release`、`validate-release`、`status` 均通过；release 阶段 `external_calls_performed=0`、新增 API/victim/Retriever 调用为 `0`，未读取 membership、victim response 或 AUC。既有 Reserve shadow gate 的累计 Retriever calls=`13500` 保持不变。
- [ ] Luna query-generation、API/victim、正式主 index、response、AUC 与正式评估尚未授权或启动。

当前唯一下一步：停止在 v23 release passed 边界，等待主人单独授权并完成 query-generation successor freeze/auth；在此之前不启动 Luna/API、victim、主 index、response 或 AUC。

### 2026-09-01：v23 query-generation successor freeze/auth 已完成

- [x] 用户明确授权完成 query-generation successor freeze/auth；本阶段只进行本地离线 freeze、输入验证和授权准备，不执行 Luna/API、victim、Retriever、主 index 或正式评估。
- [x] 最终 query runtime identity=`691ce230d5c70d8dd7f8219d620363b348b2e30ef93284960c655313d4934753`，runtime bundle=`86b19fa8e69c3857df11cbc7f81dc4d5585a7f3c77b1f3369f2593fce8e323fa`，freeze SHA-256=`3ada84d7a762e14e527a3eaedd633af5f9888ce136d997288ce5fafdeaee6684`，18-file closure；release manifest 继续绑定 `e998c602...333a`。
- [x] Luna 身份在首次调用前冻结为 endpoint=`https://api.42w.shop/v1/chat/completions`、model/model_version=`gpt-5.6-luna`；Prompt SHA-256=`d2eb0138...f0b67`，temperature=`0`、top_p=`1`、n=`1`、max output tokens=`256`、seed=`42`、RPM=`4`、`retry_until_success=true`。freeze 只记录 API key 环境变量名，不包含 secret。
- [x] 三数据集离线输入均为 `6000` included pair rows、`12000` Q+/Q- logical query cells，Reserve query=`0`。logical query budget 固定为每 dataset `12000`；transport retry 只增加实际外部尝试记录，不改变科研 query budget，semantic retry 禁止。
- [x] 最终 authorization：EDGAR=`e863dc0f236a3a524c26287266261f59eb41154ed1b33e615c75d32a53484251`（文件 SHA-256=`c4fe678fababc67c5d554ca489d43032b0041b90dc1a23df598cdcc472bfc4b9`）；Enron=`c211e6549a5c36d3cdd1d8122684187a74b07bddb00d469b3487e66a4a1df4f1`（`3fcd3ffdb7324d59be4835d0d6dbd9c102ed1febdcf42ea5911841ee881deefa`）；PubMed=`137113641e50a0a1a67c88130b14423d42146921ac8144b14e14dda8ef7d4170`（`7e248f149b3ecf3dcb6f6c1fdf416a49bf1bf37fca9b56d98aac0f0163b54463`）。三份均 `api/external=true`、victim/Retriever/GPU=false，预算单位为 logical query cells。
- [x] preflight 首版暴露 dataset 输出目录未隔离；在 API 调用前修复为 `<query_contract_id>/<dataset>/` 并重新 freeze/auth。旧 identity=`430ac62a...3cbc9` 及其三份 authorization 保留为 superseded preflight evidence，不得用于正式运行；其 API/external calls=`0`。
- [x] 最终 `validate-freeze`、三份 authorization validator、三数据集 `validate-input`、定向 unittest=`9/9 OK`、query/retry/release/query-controls 扩大回归=`23/23 OK`、AST 与 `git diff --check` 通过；live status=`query_runtime_frozen_all_datasets_authorized`，API/victim/Retriever/external calls=`0`。
- [ ] 正式 Luna query-generation 尚未启动；没有 query response、主 index、victim response、Retriever output 或 AUC。

当前唯一下一步：由主人按 `edgar -> enron -> pubmed` 串行运行 48 号脚本的 `run` 长命令；每个 dataset 完成后先检查 query plan/status，再进入下一个。授权仅覆盖 Luna query-generation，不覆盖 victim、主 index、Retriever 或正式评估。

### 2026-09-01：v23 Luna query-quality development canary 在 API 前发现输入契约冲突

- [x] 主人明确授权最多 `60` 次 Luna API 调用的 development-only query-quality canary；输入只允许三套 development pilot pairs，不读取 formal membership、victim、Retriever、response 或 AUC，不启动正式 query-generation。
- [x] 为避免触碰当前 query freeze 的 18-file closure，新增独立 development-only canary 模块与 52 号薄 CLI；没有新增 YAML、freeze、authorization、ledger 或正式 identity，也没有修改当前 selector、Prompt、validator 或 48 号正式 runner。canary 固定 seed=`42`，每数据集按 `PERSON/ORG/LOCATION/PRODUCT/CONTRACT_TERM` 各抽 2 pair，共 `30` pair / `60` Q+/Q- cell；transport/semantic retry 均关闭，物理调用硬上限为 `60`。
- [x] 本地 preview 在任何 API 调用前返回 `status=development_input_contract_failed`：固定样本中 `12/60` cell 因 `ValueError:relation_cue_missing` 无法构造 query input，分布为 Enron=`6`、PubMed=`6`、EDGAR=`0`。输入 SHA-256=`f9fa929d335e400fb129e0f1d8fae6f482273004d5fddef4208593c7ec819d86`，失败清单 SHA-256=`c860f88322b4fd4d538400f4d1998f61be0d10448bbe3b6fa706463613d86e3a`。
- [x] 同一入口对三套 development selected pairs 做只汇总的兼容性扫描：共 `12378` 个 Q+/Q- cell，`3774` 个不满足当前 frozen `build_query_input`；EDGAR=`1967/5814`、Enron=`372/888`、PubMed=`1435/5676`。该扫描不读取 formal release/group/membership，不能据此声称已量化正式 release 的实际失败数。
- [x] 根因不是 Luna 输出，而是跨阶段科学契约不一致：`configs/restoration_first_v23_fact_layer_r1.yaml` 将 `relation_cue_role` 设为 `diagnostic_only`，Fact Layer r1 的 `p0_ready` 不要求 `relation_cue_present`，selection r2 也未恢复该门禁；但 design-r6 的 query self-containment 与当前 query runtime 仍要求 claim 命中同一冻结 relation-cue regex。样本中的路径片段、名词性 payment 片段和 PubMed `Aim To analyze...` 等因此在 Luna 前失败。
- [x] canary 定向测试 `13/13 OK`，覆盖真实 development 阻断、确定性分层、60-call 上限、单次物理尝试、断点不重复调用和首个自动失败即停止。preview 后 `api_call_slots_consumed=0`，API/victim/Retriever/external calls 均为 `0`；正式 `artifacts/v23/queries/` 仍不存在，当前 query freeze/auth 文件未变。
- [ ] 当前 query runtime 虽仍可通过其既有 freeze validator，但科学上不得继续执行三条正式 48 号 `run` 命令。不能通过跳过 cue-missing pair、从 development 中重抽“好样本”或在 release 后删行来掩盖冲突。

当前唯一下一步：停止正式 Luna query-generation。等待主人决定并单独授权一个科学协议修复：推荐恢复 selector/query self-containment 的一致硬条件，在 development 上重新选择并先通过 query-quality canary；因为这会改变 selector/source eligibility 或正式 Query construction，必须保留当前 v23 release 为 blocked 历史证据，并以明确 successor 版本从最早受影响阶段重跑，而不是原地放宽 validator 或继续使用现有正式授权。

### 2026-09-01：query-quality canary status 哈希稳定性修复

- [x] 发现 52 号 canary 的 `status` 复用 `prepare_canary` 会在只读查询时刷新 `created_at` 并改写 summary；该问题只影响工具产物稳定性，不影响 query contract、selector、freeze/auth 或 canary 阻断结论。
- [x] 最小修复：已有 `canary_summary.json` 时 `canary_status` 只读取并校验后返回；仅在 summary 不存在时执行 preview 初始化。没有新增协议、配置、freeze、authorization 或 artifact 层。
- [x] 定向 unittest=`13/13 OK`、AST=`3/3 OK`；连续 status 调用保持 summary 字节和 SHA-256 不变，当前 summary SHA-256=`14a0caf04655e5e5672c4ae246fa87519c774a21cb9be255077958f1c643a96e`。
- [x] API/victim/Retriever/external calls 仍为 `0`，formal query-generation 仍未启动；`artifacts/v23/queries/` 仍不存在。

### 2026-09-01：v23 query-quality canary successor probe 已完成离线修复，等待主人运行 API canary

- [x] 按用户授权完成最小 successor 科学修复：新增 selection r3，在复用不可变 Fact Layer r1 facts 的基础上恢复 query relation-cue 硬门禁；true claim 与每个 counterfactual claim 均必须命中冻结 `RELATION_CUE_RE`。未修改旧 r1/r2 artifact，未放宽正式 validator。
- [x] selection r3 结果：EDGAR=`915` eligible / `2745` pairs、PubMed=`895` / `2685`，capacity passed；Enron=`82` / `246`，`failed_capacity_shortfall`（`formal_eligible_lower=2061 < 2250`），该失败证据保留，不降低门禁。
- [x] development canary 固定输入已从 `3774/12378` 不兼容收敛为 `0/11352`；固定 `30` pairs / `60` Q+/Q- cells，r3 + `subject_presence_r2` preview=`prepared_awaiting_execution`，API calls=`0`。新增 probe 仅处理自然疑问句倒装、句首冠词和尾部标点造成的同实体 surface 变体；正式 frozen validator、正式 query runner、release 与 query freeze/auth 均未改变。
- [x] 早先真实 canary 失败 artifact 原样保留：`1` 次 API 调用因 frozen subject-presence 规则拒绝自然疑问句，状态为 `automatic_validation_failed`；不得在该失败 checkpoint 上重试。最新 r2 probe 输出目录独立且无结果文件，尚未消耗新 API 配额。
- [x] 定向回归：selection=`7/7`、query-generation/canary=`16/16`，内存 AST 编译与 `git diff --check` 通过；未读取 formal membership、victim、Retriever、response 或 AUC。
- [x] 本次离线 preview 后 r2 canary summary SHA-256=`f536d909dcc644dff5a6de33422f2f5f694179ed1da5a26775ce239bc7f55c6e`；随后只读 `status` 未改写 summary，前后 hash 相同。
- [x] 主人运行新的 r2 canary 后，第 1 个物理调用因 `RuntimeError:OpenAI-compatible request failed: Remote end closed connection without response` 失败；无 provider model、request id 或 query response，因此不能评价 query 质量。旧输出目录状态=`automatic_validation_failed`、`api_call_slots_consumed=1`，按 checkpoint 规则不得原地重试。
- [x] 主人明确授权独立 attempt2（最多 60 次）后，第 1 个物理调用收到远端 HTTP 404 `model_not_found`：当前 endpoint 的账号组不支持冻结模型 `gpt-5.6-luna`。attempt2 无 provider model/request id/query response，状态=`automatic_validation_failed`、调用=`1/60`；这是 provider/model availability 阻塞，不是 Prompt、selector 或 validator 失败，也不能作为 query 质量证据。
- [x] 对同一 `PCV_SIBLING_API_KEY` 做一次只读 `/v1/models` 诊断：HTTP 200、返回 `58` 个模型 ID，列表确实包含 `gpt-5.6-luna`。因此 404 不是模型 ID 不存在或本地拼写错误，而是该 endpoint 的模型总目录可见、当前账号组 completion entitlement 不可用；诊断未产生 query response，不改变 canary checkpoint 或 logical query budget。
- [x] 主人更换 key 后复核：新 Python 进程未继承旧 `PCV_SIBLING_API_KEY`，从当前 `.env` 加载的 key 指纹与文件值一致；同 key `/v1/models` 仍为 HTTP 200，但最小 `/v1/chat/completions`（model=`gpt-5.6-luna`）仍为 HTTP 404 `model_not_found`。结论是 key 已生效且可认证，但该 key/账号组仍无 Luna completion entitlement；未改 endpoint/model、未写 canary artifact 以外的实验产物。
- [x] 主人提供的独立 OpenAI SDK REPL 使用另一把硬编码 key 成功调用 `gpt-5.6-luna`；这证明 endpoint/model 路由可用，也修正了“服务端没有 Luna entitlement”的过强结论。此前项目 smoke 读取的是 `.env`/`PCV_SIBLING_API_KEY`，两把 key 是否相同尚未直接比较；不得把用户贴出的 secret 写入命令、日志或 artifact。需要先让项目进程加载同一有效 key，再重新做单次 smoke/canary。
- [x] 主人更新 `.env` 并清除 PowerShell 中旧的 `PCV_SIBLING_*` 覆盖后，项目 client smoke 已通过：`model=gpt-5.6-luna`、`provider_model_id=gpt-5.6-luna`、内容=`OK`。该调用仅为诊断 smoke，不是 canary query；未写入 query artifact。聊天中暴露的旧 key 不得继续使用，建议撤销并轮换。
- [x] 主人重新授权独立 canary attempt3；离线 preview 已通过，输出隔离于 `artifacts/v23/development/query_quality_canary_r3_subject_presence_r2_attempt3/`，固定 `60` cells、`0/11352` input-contract failures、`api_call_slots_consumed=0`，仍绑定 `gpt-5.6-luna` 与 `subject_presence_r2`。preview 未调用 API。
- [x] 主人要求新的独立 attempt4；离线 preview 已通过，输出隔离于 `artifacts/v23/development/query_quality_canary_r3_subject_presence_r2_attempt4/`，固定 `60` cells、`0/11352` input-contract failures、`api_call_slots_consumed=0`，绑定当前有效的 `gpt-5.6-luna`/`PCV_SIBLING_API_KEY` 与 `subject_presence_r2`。preview 未调用 API。
- [x] attempt3 第 1 个 canary 调用收到 provider HTTP 500：`get_channel_failed`，消息为“分组 auto 下模型 gpt-5.6-luna 的可用渠道不存在（retry）”；无 provider model/request id/query response，状态=`automatic_validation_failed`、调用=`1/60`。这与此前 smoke 成功并不矛盾，属于 provider 的瞬时/路由渠道选择失败，不是 query 质量证据；旧 checkpoint 不得原地重试。
- [x] 针对“是否为 env 调用方式”做最小对照诊断：当前 `.env` 的 `PCV_SIBLING_API_KEY` + `gpt-5.6-luna`，OpenAI SDK smoke=`passed`；仓库 `OpenAICompatibleChatClient` 使用 canary 同参数（`top_p=1,n=1,seed=42,max_tokens=256`）也=`passed`，两次均返回 provider model id=`gpt-5.6-luna`。因此 env/请求封装不是根因，attempt3 500 判定为 provider 瞬时渠道故障；两次诊断不写 canary artifact、不启动正式流程。
- [ ] 当前唯一下一步：等待主人明确授权一个全新、独立输出目录的 development-only canary attempt；本次授权的第 1 个调用已被 transport failure 消耗，不能自动把新 attempt 扩成另一组 `60` 次。重新授权并通过 canary 后，再评估是否需要新的 query runtime successor freeze/auth。正式 48 号 query-generation 继续禁止。

### 2026-09-01：query-quality canary transport retry 修复（等待新授权）

- [x] 根因确认：canary 入口此前把底层 `max_retries=0` 与“整个逻辑 cell 不重试”混为一谈；provider 的 HTTP 500、超时或断连会在首个物理调用后立即落为 `automatic_validation_failed`，因此用户看到“一下就断了”。这不是 `.env`、模型 ID 或 OpenAI-compatible client 的调用方式问题。
- [x] 在既有 `src/prepare/restoration_first_v23_query_quality_canary.py` 内做最小修复：每个固定 logical query cell 允许最多 `2` 次额外 transport retry；每次物理调用先写入 durable `canary_attempts.jsonl`，记录 `retry_ordinal`，最终 result 记录 `transport_retry_count`、`physical_attempt_count` 与 transport failure reasons。
- [x] retry 仅覆盖 HTTP `408/409/425/429/500/502/503/504/524` 和明确网络超时/断连；HTTP 404、模型身份漂移、JSON/schema/subject validator 失败仍立即失败且不重试。逻辑 query budget 仍为 `60` cells，物理 API 上限变为 `180`（60×3）。
- [x] 定向 unittest=`17/17 OK`，内存 AST 编译与 `git diff --check` 通过；mock 验证前两次 HTTP 500 后第三次成功时共 `62` 次物理调用、首个 result 的 `physical_attempt_count=3`，语义失败仍仅调用一次。
- [ ] 旧 attempt1-4 失败 checkpoint 原样保留，不原地重试；新逻辑尚未发起 API 调用，也未修改 formal query-generation、victim、Retriever、主 index 或 AUC。

当前唯一下一步：等待主人明确授权一个全新独立输出目录、最多 `180` 次物理 API 调用的 development-only canary attempt；授权前只可执行离线 preview。新 attempt 通过后再做人工 query 质量复核，未通过前禁止正式 48 号 query-generation。

### 2026-09-01：query-quality canary transport retry policy superseded

- [x] 按主人最新标准修正策略：可识别的网络/transport failure 不再有 canary 层的重试次数上限，持续重试直到该 logical cell 成功或用户手动终止；原有 `max_retries=0` 仅表示底层 client 不隐藏重试，所有物理调用仍逐次写入 checkpoint。
- [x] attempt5 的旧 transport-failed result 可追加恢复：保留原有 attempts/results，下一次运行从已有 `retry_ordinal` 继续，不覆盖失败证据；语义/schema/validator、鉴权、模型不存在和普通 4xx 仍立即终止。
- [x] 定向 unittest=`18/18 OK`、AST 与 `git diff --check` 通过；刷新 attempt5 summary 后状态=`transport_failure_awaiting_resume`、待恢复 cell=`1`，API 调用未增加。

当前唯一下一步：主人确认持续重试的费用与手动停止边界后，运行 attempt5 同一目录的续跑命令；出现网络错误时命令会持续等待/重试，按 `Ctrl+C` 才会手动停止。正式 query-generation 仍 blocked。

- [x] attempt5 离线 preview 已完成：输出目录=`artifacts/v23/development/query_quality_canary_r3_subject_presence_r2_attempt5/`，固定 `60` logical cells、`0/11352` input-contract failures，`transport_retries_enabled=true`、每 cell 最多 `2` 次额外 transport retry、物理上限=`180`，`api_call_slots_consumed=0`；只读 `status` 未改写 summary。

### 2026-09-01：attempt5 终态分类修复（当前）

- [x] attempt5 第 3 个 logical cell 前 `16` 次为可识别的 provider/network transport failure（`get_channel_failed`、断连或读超时）；第 `17` 次重试已收到 `gpt-5.6-luna` 的结构化 response，但 query 中的 `those awards` 被 `subject_presence_r2` 的字面 unresolved-reference 检查拒绝。该 cell 是语义校验失败，不再允许 transport retry。
- [x] 修复 52 号 canary 恢复分类：仅最后一次 `failure_reason` 为 transport failure 时才可恢复；历史 `transport_failure_reasons` 仅作审计，不能掩盖后续 validator/schema 失败。未改 Prompt、正式 validator、selection、freeze 或任何 attempt5 attempts/results。
- [x] 新增“network 失败后发生语义失败不可续跑”的回归；定向 unittest=`19/19 OK`、AST 与 `git diff --check` 通过，无 API/victim/Retriever/正式 query-generation 调用。
- [ ] attempt5 已有 summary 仍是修复前的错误分类；主人需运行同一 `run` 入口刷新 summary。修复后会在创建 API client 前以 `automatic_validation_failed` 返回，只改写 summary，不调用 API，也不覆盖失败证据。

### 2026-09-02：v24 Pre-Split Eligibility 离线实现完成

- [x] 按 v24 修订方案新增单一配置 `configs/restoration_first_v24.yaml`、实现 `src/prepare/restoration_first_v24.py` 和普通离线 CLI `scripts/53_run_v24_pre_split_eligibility.py`；未修改 v23 frozen 文件、release、split 或历史 artifact。
- [x] v24 仅复用 v22 membership-blind source pool；候选 fact adapter 从 source text/chunks 枚举 `true_claim + original_entity`，拒绝 `effective_type`、旧 counterfactual 字段和 membership/downstream 信号。
- [x] 实现 canonical single-slot reconstruction、source absence、proposition-local contextual role proxy、correction eligibility、neutral/contradiction NLI diagnostic、max-min semantic ranking、Q+/Q- hard validation、固定 surface fallback 与 fallback 1% 检查；stealth 指标不作为 pair-level hard gate。
- [x] 实现按冻结 v22 `source_order.json` 的 pre-split scanner：先筛 eligibility，达到 exactly 2250 eligible sources 后停止；容量不足返回 `insufficient_eligible_capacity`，不降低门禁、不替换 source/pair。
- [x] 实现普通 eligible-source/query/split manifest 生成与 hash 校验、coverage/rejection reason/fallback 统计、1000/1000/250 deterministic split，以及 formal source/pair/query integrity drift 的 fail-closed 校验；无 authorization hierarchy、ledger、attestation 或多层 identity。
- [x] 定向 unittest=`29/29 OK`；内存 AST 编译、CLI `validate-config`、v22 source-pool hash/order 只读检查通过；本任务 API/Retriever/victim/GPU/external calls=`0`。
- [ ] 尚未执行 v24 capacity scan、真实 Luna、Retriever、victim、主 index 或正式评估；下一步必须先单独授权 development/capacity canary。

### 2026-09-02：v24 离线完整性校验补强

- [x] split manifest 构造现在先重新验证 eligible-source manifest；eligible source、pair 数量、每 source 6 条 query、pair/query hash、source integrity hash 和 dataset 绑定均 fail closed。
- [x] fallback 统计仅计最终固定三对，surface fallback 后重新计算 query manifest hash；offline role judge 明确标注 `judge_mode=offline_proxy`/`proxy_only=true`，不作为实体类型 taxonomy。
- [x] 定向 unittest=`29/29 OK`；ruff、AST parse、`git diff --check` 通过。未执行 capacity scan、真实 Luna/API、Retriever、victim、GPU、主 index 或正式评估，external calls=`0`。
- [x] 仓库全量 unittest 只读回归：`Ran 597 tests`，`556 passed / 39 skipped / 1 failure / 1 error`；失败为既有 v23 `formal_runtime_r2` ledger-tail error 与 `fresh_audit_preparation_r2` reservation-tip failure，未修改其文件或历史证据，不能归因于 v24。
- [ ] v24 仍停留在 offline implementation；下一步必须由主人单独授权 development/capacity canary，不能从本记录推断 API 或下游授权。

### 2026-09-02：v24 retrieval anchor 门禁语义修正

- [x] 发现并修复 v24 实现中 retrieval anchor 校验被错误并入 candidate hard-gate rejection 的问题。anchor schema、source grounding 和 query presence 现在仅写入 `retrieval_anchor_diagnostics`，不再阻断 pair、candidate ranking、PVS 或 query budget；原始 anchor 值不被自动追加到 query。
- [x] query manifest 继续携带 anchor diagnostics，便于 canary/retrieval 解释性分析；该修正不读取 Retriever、victim、membership 或 AUC，也不修改 v23 frozen 文件。
- [x] v24 定向 unittest=`39/39 OK`；三数据集离线 capacity estimate 均完成，`external_calls_performed=0`、membership/Retriever/victim/AUC 均未读取。
- [x] 全量 unittest=`605`，其中 `1 failure / 8 errors / 39 skipped`；失败属于既有 v23 query-runtime/fresh-audit 漂移，不涉及本次 v24 文件，保留为既有工作区证据。
- [ ] v24 仍未运行新的真实 Luna canary；上一次 30-cell canary 已消耗其 API 配额并留下失败证据。新的真实 canary attempt 需主人重新明确授权。

### 2026-09-02：v24 Luna development canary attempt r2

- [x] 主人明确确认启动新的独立 v24 development/capacity canary；输出隔离于 `artifacts/v24/development/query_quality_canary_r2/`，未覆盖 r1 失败证据。
- [x] 30 个 logical cells 均完成响应；provider model id 全部为 `gpt-5.6-luna`，`external_calls_performed=56`，其中 `transport_retry_count=26`，证明网络/5xx 重连链路生效。
- [x] canary 仍未通过 hard gates：`13/30` eligible。主要失败为 `q_plus/q_minus semantic/reverse binding`、unresolved reference、时间/数字/模态漂移；不是 transport 中断。
- [x] 未读取 membership、Retriever、victim 或 AUC；Retriever/victim/GPU/主 index/正式 query-generation 均未启动。
- [ ] v24 query-quality canary 未通过前不得进入 capacity/formal 下游；需先修复候选生成质量并以新的 config/commit 开启新 attempt，不得放宽 hard gate 或替换失败 pair。

### 2026-09-02：v24 Query semantic binding 改用真实 embedding cosine

- [x] 确认原 v24 `query_similarity_threshold=0.80` 实际由 token Jaccard `_lexical_similarity` 提供，会错误惩罚自然 paraphrase；该实现不得继续作为 Q+/Q-/reverse semantic binding hard gate。
- [x] 在现有 v24 实现内最小替换为本地 `BAAI/bge-base-en-v1.5` sentence-transformers cosine，冻结 revision=`a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`、`local_files_only=true`、对称 semantic encoding；未注入真实 scorer 时 hard validation fail closed，禁止 hashing/lexical fallback。
- [x] 本地 CUDA smoke 成功，`Is the company incorporated in Delaware?` 与对应 canonical proposition cosine=`0.8950162529945374`；scorer identity 写入 canary summary。定向回归=`44/44 OK`，内存 AST 与 `git diff --check` 通过；hard gate 与 entity-masked semantic diagnostic 均无 lexical fallback。
- [x] 新独立 development attempt 输出=`artifacts/v24/development/query_quality_canary_r3_semantic_attempt2/`：`18/30` pair 通过，logical API calls=`30`、physical attempts=`50`、transport retries=`20`，provider model=`gpt-5.6-luna`。membership/ Retriever/victim/AUC 均未读取或调用。
- [x] 新 attempt 仍为 `failed_hard_gates`，但 12 条失败中只有 1 个 candidate 命中 `q_minus_semantic_binding`；主要阻断来自 temporal drift=`30` 个 candidate-side flags、modality drift=`24`、unresolved reference=`12`、numeric drift=`12` 等既有结构检查。结论是 lexical hard gate 已修复，但 query-quality canary 尚未通过。
- [ ] 在结构 validator 与 Luna query realization 的剩余问题厘清并通过新的 development canary 前，继续禁止 capacity/formal、Retriever、victim、主 index 和正式评估。

### 2026-09-02：v24 query 结构门禁修复（等待新 canary 授权）

- [x] 根据 semantic attempt2 的失败证据收敛结构问题：普通介词 `in/on/at` 不再被当作 temporal semantics；方括号文献引用（如 `[5]`、`[16]`）不再被当作 factual numeric semantics；`May` 仅在明确月份上下文中计入 temporal marker。
- [x] 保留科学 hard gates：显式 `before/after/during/since/until/between` 关系、事实数字以及 `can/could/may/might/must/shall/should/will/would` modality 发生漂移时仍拒绝；没有放宽 unresolved reference、entity binding、source absence 或 correction eligibility。
- [x] 补齐 `could/must/shall` 等合法 polar auxiliary 与句首功能词处理，避免将 `Shall Enron...`、`In December...` 中的助动词/介词误报为新增 factual entity。
- [x] 强化现有 Luna Prompt，并在同一 fact slot 的三个初始候选全部失败时允许一次固定 semantic correction retry；首轮已有合格候选时不重试，retry 再失败时不进行第三次生成，不换 pair/source，不读取 membership、Retriever、victim 或 AUC。
- [x] canary 输出可选保存每个候选的 query/template、拒绝理由、semantic metrics、candidate index 及 `initial|semantic_correction` 阶段，避免聚合计数掩盖具体结构失败；没有新增 governance artifact。
- [x] v24 + sibling retry 定向 unittest=`54/54 OK`；CLI config validation、3 文件内存 AST 与 `git diff --check` 通过。本阶段 API/Retriever/victim/GPU/formal calls=`0`。
- [x] 仓库全量 unittest=`620`，结果为 `572 passed / 39 skipped / 1 failure / 8 errors`；9 项均来自既有 v23 `query_runtime_current_binding_drift`、formal ledger tail 和 fresh-audit reservation tip 状态漂移，未涉及本次 v24 文件或结构门禁。
- [ ] 当前唯一下一步：取得新的明确 API 授权后，以新独立输出目录运行一次 v24 development-only canary，检查 correction 后是否达到 `30/30`；未通过前继续禁止 capacity/formal、Retriever、victim、主 index和正式评估。

### 2026-09-03：v24 development canary attempt4 与 transport retry 修复

- [x] 主人明确允许将固定 30 个 membership-blind development pair 发送到当前 `gpt-5.6-luna` endpoint；attempt4 使用独立目录 `artifacts/v24/development/query_quality_canary_r3_semantic_attempt4/`，未覆盖 attempt1、attempt2 或 semantic attempt2 失败证据。
- [x] attempt4 完成 `30/30` logical cells，provider model id 全部为 `gpt-5.6-luna`；summary 记录 `27/30` 通过、`external_calls_performed=132`、`transport_retry_count=102`，未读取 membership，Retriever/victim/AUC/GPU/formal calls=`0`。
- [x] 27 个 cell 的 query reconstruction/semantic hard gates 通过；3 个 PubMed cell（indices `0/3/6`）因 `IncompleteRead(0 bytes read, 210 more expected)` 终止，属于错误响应体读取阶段的 transport failure，不是 query 结构质量失败，因此 canary 按预注册规则为 `failed_hard_gates`。
- [x] 定位并修复现有 `OpenAICompatibleChatClient`：retryable HTTP status 的错误响应体若被截断，`IncompleteRead` 不再绕过 retry；非流式与流式路径均采用 best-effort error-body read，保留原 HTTP 状态的持续重连语义。
- [x] 新增非流式/流式 `IncompleteRead` mock 回归；v24 + sibling retry 定向 unittest=`56/56 OK`，5 文件 AST、`git diff --check` 通过。未启动新的 API attempt，attempt4 artifact 保持原样。
- [ ] 当前唯一下一步：修复已验证后，需主人单独确认新的独立 v24 canary attempt（建议新目录）再运行；通过 `30/30` 前继续禁止 capacity/formal、Retriever、victim、主 index 和正式评估。

### 2026-09-03：v24 development canary semantic attempt5（通过）

- [x] 主人已授权新的独立 v24 development-only Luna canary；输入仍为 30 个 membership-blind r3 development pair，输出隔离于 `artifacts/v24/development/query_quality_canary_r3_semantic_attempt5/`，未覆盖既有 attempt 证据。
- [x] 30/30 logical pair 通过 reconstruction、contextual-role、correction-eligibility 与 query semantic hard gates；`fallback_pair_count=0`，canary 未使用 deterministic fallback。
- [x] provider model id 全部为 `gpt-5.6-luna`；`logical_api_calls=32`、`physical_attempts=71`、`transport_retry_count=39`，网络/transport 重连链路生效且没有终态失败。
- [x] semantic scorer 为本地 `BAAI/bge-base-en-v1.5` sentence-transformers cosine，revision=`a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`，`local_files_only=true`，threshold=`0.80`；result hash=`c291e4d243845a48f991a5443d290c36d8e839faf20dd45429f0fdd5da83d1f0`。
- [x] membership 未读取；Retriever、victim、AUC、GPU、主 index、正式 query-generation 均未启动，`retriever_calls_performed=0`、`victim_calls_performed=0`。
- [x] attempt5 `canary_summary.json` 与 `canary_results.jsonl` 已落盘；既有 attempt1/2/4 失败证据保持不变。
- [ ] query-quality canary 已通过，可进入下一阶段 capacity sanity check；capacity、Retriever canary、victim 和正式评估仍需分别取得主人明确授权，不能由本次 canary 授权推断。

### 2026-09-03：v24 source-level pair selection refinement

- [x] 按最新方案在现有 v24 实现中加入 source-local processing budget：`eligibility.max_candidate_facts_per_source=8`。该值是 development 阶段基于 raw candidate-fact 分布预注册的 Luna processing 上限；30-source 统计中前三个不同 `original_entity` 出现在前 7 个 raw facts 内，但这不能证明前 8 个 facts 能产生 3 个 scientific-valid eligible pairs。
- [x] `screen_source()` 现在按 frozen `fact_order` 处理最多 8 个 facts；3 个 distinct、完整通过 hard gates 的 accepted pairs 达成后立即停止；distinct 不足时按 deterministic order 使用 duplicate eligible pair fallback，不改变 pair/source eligibility。
- [x] 恢复 coverage 定义：`candidate_fact_count` 为 source 完整枚举的 facts 总数；新增 `processed_fact_count`（实际送入 Luna/provider）、`unprocessed_fact_count`（两者差值）；`candidate_package_count` 只统计实际处理 facts 的 packages。
- [x] source/scan/manifest 增加 early-stop、third accepted/distinct pair position、entity diversity、重复实体 pair、processed/unprocessed coverage 诊断；diversity 只作 selection preference + diagnostic，不进入 hard gate、ranking、split 或 PVS。
- [x] capacity runner 与 frozen source-pool scanner 均从同一 `max_candidate_facts_per_source=8` 配置读取；前 8 个不足 3 个 eligible pair 时不得隐式处理第 9 个 fact。offline raw-fact capacity 仍标记为 `estimate_only`。
- [x] 新增 source-selection mock 回归，v24 定向测试=`53/53 OK`；未修改 v23 frozen 文件，未执行新的 API、Retriever、victim、GPU 或正式评估。
- [x] 追加验证：v24 + sibling retry 定向测试=`63/63 OK`；仓库全量 unittest=`629`，`581 passed / 39 skipped / 1 failure / 8 errors`，失败均为既有 v23 query-runtime/fresh-audit/ledger 状态漂移，未涉及本次 v24 source-selection 改动。

### 2026-09-03：v24 source-level pair selection refinement 定义校正（superseding）

- [x] 明确 `eligibility.max_candidate_facts_per_source=8` 的定位：这是 development 阶段依据当前 raw candidate-fact 分布预注册的 frozen source-local processing budget，用于限制每个 source 实际送入 Luna/provider 的 fact 上界。30-source 统计中前三个不同 `original_entity` 出现在前 7 个 raw facts 内，仅是预算选择的经验依据，不能证明前 8 个 facts 经全部 scientific hard gates 后一定产生 3 个 eligible pairs。
- [x] 明确 `candidate_fact_count` 始终是 source 完整枚举出的 candidate facts 总数；`processed_fact_count` 是实际进入 candidate provider/Luna 的 facts；`candidate_package_count` 只统计已处理 facts（含允许的一次 semantic correction retry）返回的 packages；`unprocessed_fact_count = candidate_fact_count - processed_fact_count`。early stop 不得从总候选数中删除未处理 facts。
- [x] capacity、pre-split eligibility 以及 freeze 前 validation 统一共享同一个 frozen budget=8；前 8 个不足 3 个 pair 时不得隐式处理第 9 个 fact。新增 manifest validator 的精确预算一致性检查；third-pair 位置只在完成全部 scientific hard gates 后记录，early-stop 定义仍以达到 distinct target 为准。
- [x] entity diversity 仍然只是 source-level selection preference 与 diagnostic；不改变 pair validity、source eligibility threshold、membership split、PVS 或 query budget。未新增 scientific hard gate、successor protocol、governance、ledger、authorization 或 identity 机制。
- [x] v24 定向 unittest=`56/56 OK`，包含 source-level budget、manifest/formal budget drift 拒绝和 source selection 回归；v23 frozen 文件与 artifact 未修改，API/Retriever/victim/GPU/formal 调用仍为 `0`。
- [x] 修正 offline `estimate_only` coverage 口径：该分支不调用 candidate provider/Luna，因此 `processed_fact_count=0`、`unprocessed_fact_count=candidate_fact_count`；预算内可处理数量仅用于 raw-fact eligibility 估计，不冒充实际 Luna processing。
