# PCV-MIA

**2026-09-19 当前状态：V24 已合入本地 main，nfcorpus × Gemma BF16 × dense 首 cell 代码/config 随本提交冻结。** 输入为 `reconciled_20260919`，2000主source、12000问；真实输入dry-run通过，正式运行尚未启动。使用独立干净工作树 `D:/MIA/mia_model/artifacts/v24/worktrees/main`，不要从仍保留其他未提交工作的原目录启动。底部“V24 主线合并与 nfcorpus 首 cell”给出交付范围；本次未推送远端。

PCV-MIA（Paired Counterfactual Verification Membership Inference Attack）研究如何通过成对事实验证问题，判断一篇 source document 是否属于 RAG 知识库。主攻击分数是 source-level、RAG-only Paired Verification Score（PVS）；LLM-only 用于归因对照。

## 当前入口：v24 Pre-Split Eligibility

当前主线为 `pcv-mia-v24 / pcv-query-local-counterfactual-reconstruction`，仍处于开发验证阶段。详细实验过程、结果和下一步统一维护在[研究总表](研究记录/顶会推进_notes.md)与[任务总表](研究记录/顶会推进_task_plan.md)，本页只提供入口和简要状态。

**2026-09-13：V24 正式 runner 的代码链已接通，本地 mock 端到端验证通过。** 10号脚本的显式 `--v24` 串起冻结 selected pairs、固定split、主库index、现有RAG/victim执行循环和新PVS。新增11项测试；相关回归476项中427通过、49项既有跳过，零失败。合成2250-source split中，1000 Member/1000 Non-Member执行12000条mock查询，250 Reserve不发查询，得到6000个pair及2000个source分数；共享Q+保留独立query ID，中断/失败恢复和完成态不重跑均通过。真实API/GPU调用为0，没有运行正式实验。当前 `formal.runtime: null`，真实输入、模型/index绑定与代码冻结仍未完成，固定NLI权重仍缺失。见[正式入口说明](#v24-formal-runner)、[验证记录](artifacts/v24/development/pvs_hybrid_20260913/formal_runner_mock_validation.json)和[最新研究记录](研究记录/顶会推进_notes.md#v24-formal-runner-mock-20260913)；下方此前“正式runner未接通”的记录保留为历史状态。

**2026-09-13：V24 混合 PVS 离线入口已接通，正式冻结尚未完成。** 11号脚本增加显式 `--v24-hybrid` 和无模型 `--dry-run`，直接读取已有 selected pairs 或 smoke 结果，绑定单个 RAG cell 的原始回答，调用既有 pair/source 评分。新入口11项集成测试及已有20项PVS测试通过；扩展431项中382通过、49项既有跳过。已有5篇开发产物的预检识别15对/30问，未生成新查询或调用模型。固定NLI权重仍缺失，真实语义验证、正式split/index/cell绑定与代码提交尚待完成；不把预检当作formal freeze。见下方入口说明及[本轮记录](研究记录/顶会推进_notes.md#v24-pvs-entry-freeze-preparation-20260913)。

**2026-09-13：结构化 stance + semantic restoration 的独立 PVS 开发接口完成。** `S+`、`A−` 使用明确 stance（supported=1，contradicted/insufficient=0）；`R−` 在否定且有 correction 时先做完整规范化相等判断，否则仅比较 correction/e+ 的双向 NLI 蕴含概率并取较小值。主公式为 `S+ * max(0, R− − A−)`，source 三对 mean 为主分、median 仅诊断。新增18项测试通过；扩展回归418项中369通过、49项既有跳过，18项包含其中。Query Construction、victim prompt、历史评分与经典入口保持；新接口未接入正式 runner。NLI 复用现有 DeBERTa predictor，但本轮只有 mock 验证，没有模型加载或真实语义效果验证。见[定义、接口与验证记录](研究记录/顶会推进_notes.md#v24-hybrid-pvs-20260913)及[七个合成样例和全部中间分数](artifacts/v24/development/pvs_hybrid_20260913/local_validation.json)。

**2026-09-12：保持当前代码/Prompt的未见开发30篇验证完成。** 三数据集各10篇，与历史开发source/text重叠为0；106个slot组、279个counter，最终71对，**23/30篇本地选满三对**（nfcorpus 10/10、scidocs 8/10、trec-covid 5/10）。七篇不足为六篇零slot（其中五篇trec-covid仅标题）和一篇只有两个counter，没有selector漏选；8篇通过同槽备用补满。全部71对Assistant审阅记录8对明确问题与13对边界备注，未新增准入门槛或重选。32次逻辑尝试取得30份响应，两次无响应恢复原件保留；代码/Prompt/config及PVS不变。详见[本批报告和全部问句](artifacts/v24/development/luna_only_direct_fresh30_20260912/validation_report.md)、[机器可读汇总](artifacts/v24/development/luna_only_direct_fresh30_20260912/run_summary.json)及[完成记录](研究记录/顶会推进_notes.md#v24-luna-grouped-unseen30-20260912-result)。本批为固定未见prefix开发验证，已完成并停止，无victim/PVS/formal。

**2026-09-12：同30篇离线审阅完成，暂不进入下一阶段。** 已逐对查看全部69个selected pair，记录13对明确构造问题（7篇）与5对边界备注；三个新选满三对的source均仍有明确问题。20/30→22/30和66→69的原始数量改善保留，未按诊断重选或建立新门槛。本轮仅保存审阅与文档，代码、Prompt、配置和PVS未改，API调用为0。详见[完整离线审阅](artifacts/v24/development/luna_only_direct_fresh30_20260911/three_counters_prompt_attempt2/quantity_construction_review.md)与[审阅完成记录](研究记录/顶会推进_notes.md#v24-luna-three-counters-offline-review)。

**2026-09-12：新 Prompt 同30篇复测完成并停止。** 仅将每slot的“up to three”改为主动尝试三个不同counter，其余代码/配置保持。本次生成111组/289个counter、selected 69对，**22/30篇本地选满三对**（nfcorpus 8/10、scidocs 6/10、trec-covid 8/10），旧Prompt为20/30。固定6篇的12对Assistant抽查仍发现角色错配与事实范围问题，数量达标不代表语义合格。31次调用尝试取得30份响应，一次无响应同输入恢复，失败原件保留；未运行victim/PVS/formal。详见[完整报告](artifacts/v24/development/luna_only_direct_fresh30_20260911/three_counters_prompt_attempt2/retest_report.md)与[完成记录](研究记录/顶会推进_notes.md#v24-luna-three-counters-prompt-retest-result)。

| 文件 | 职责 |
|---|---|
| [configs/restoration_first_v24.yaml](configs/restoration_first_v24.yaml) | 数据集、模型、Luna-only 开发配置、固定预算与历史构造配置 |
| [src/prepare/restoration_first_v24.py](src/prepare/restoration_first_v24.py) | Luna-only 按 slot 分组的 Q+/counter 列表、单次替换、最小 gates 和 source eligibility；保留历史构造路径 |
| [scripts/53_run_v24_pre_split_eligibility.py](scripts/53_run_v24_pre_split_eligibility.py) | Luna-only preview/smoke，以及历史候选池、canary 和容量入口 |
| [scripts/54_build_v24_beir_source_pools.py](scripts/54_build_v24_beir_source_pools.py) | 从本地 BEIR corpus.jsonl 构建独立 source pool |
| [scripts/10_run_rag_and_llm_only.py](scripts/10_run_rag_and_llm_only.py) | 显式 `--v24` 单cell正式运行入口，已有pairs → RAG/victim → hybrid PVS；`--dry-run` 仅预检 |
| [scripts/11_parse_stance_and_score.py](scripts/11_parse_stance_and_score.py) | 显式 `--v24-hybrid` 离线PVS预检/评分；省略该开关仍走经典入口 |

当前数据集为 `nfcorpus`、`scidocs`、`trec-covid`。每个 BEIR document 对应一个 source 和一个冻结 chunk；只读取 corpus 的 `_id/title/text`，不读取 queries、qrels 或 relevance labels。当前输入和产物位于 `artifacts/v24/`，旧 EDGAR/Enron/PubMed 产物保留为历史证据。

当前单个 chunk 保存该记录完整的 `title + text`。按用户最新决定继续以完整 source 输入，取消为了凑三对而再切块的提案。Luna 读取整块，从中选取完整的 atomic factual relation；每个 pair 只询问其中一个关系，候选和查询预算仍按 source 计算。

当前开发主线已接入 **Luna-only PCV 简化方案 B：atomic Q+ + 同次分组 counter**：`frozen chunk → 一次 GPT-5.6 Luna → 0–8 个 (true_claim, original_entity, q_plus, counter_entities[1..3]) → 全部 slot/counter 最小检查/去重及 Q−=Q+[e+→e−] → 优先不同slot，不足时用同槽额外counter补至三对`。每个有效 slot 的多个 counter 都在首次响应中生成，无第二次 counter-only 调用。Q+ 只验证引文中的一个原子事实，不必复述其他并列事实；counter 可以出现在 chunk 中，错误性须由该原子关系及 chunk 的正常语义支持。最新 schema、选择规则及验证见[分组 counter 实现记录](研究记录/顶会推进_notes.md#v24-luna-grouped-counters)；此前[最终收缩式修复](研究记录/顶会推进_notes.md#v24-luna-final-contraction)和[同槽备用规则](研究记录/顶会推进_notes.md#v24-luna-same-slot-counter)保留为历史依据。

**atomic Q+ 的既有最小检查继续保留。** [build_luna_direct_prompt](src/prepare/restoration_first_v24.py) 明确Q+使用真实e+且不得包含本组列表中任何完整counter；代码验证后只替换Q+中唯一、连续的e+。实体槽位在claim和Q+中的匹配容忍大小写差异，保留模型原始文本及槽外所有字符；不做fuzzy matching或倒装重组，`true_claim`自身仍须逐字出现在chunk中。本地指代检查限于完整词`we`、`our [proposed] framework/method/model/approach`、`this approach/framework/method/review`及`the latter/former`，不要求论文或方法专名。其他上下文、同槽语义角色、反事实错误性及自然性仍由同次Luna构造约束；无绝对锚点的相对时间或无法确定为假的非排他替换直接skip，不repair。本地检查记录结构有效性，事实依据与反事实错误性通过开发抽查检查。

**开发复核统一收窄为“构造正确性抽查”**：只检查Q+对应原文支持的atomic fact、同角色e−使该关系明确为假，以及Q+/Q−只改变指定槽位。正常英语语法变化、只问长句中的一个子事实、不写论文/方法专名、victim未恢复e+都不单独构成拒绝理由；指代或表达问题只有在妨碍理解和判断该事实时才需要记录。现有代码没有综合语义评分或人工复核eligibility gate，也不新增此类gate。此前扁平版同30篇复测的抽查范围在生成前固定为原顺序每数据集前2篇的已选pair，共6篇、最多18对；缺少pair照实记录，不换样或补生成。只报告实际抽查结果，不推算30篇的“整体语义通过率”。详见[三项抽查规则](研究记录/顶会推进_notes.md#v24-luna-construction-correctness-review)。

direct 路径不使用事实补全、canonical repair、证据扩展、全文重建、独立 fact/query verifier、semantic correction retry 或 restoration eligibility，也不加载 GLiNER2/BGE。历史 GLiNER2、ranking v2、旧两阶段及旧 Luna-only A/B 保留为 comparator/复现路径。配置中的默认 `candidate_fact_adapter` 仍是历史 GLiNER2；现行 atomic Q+ 实现通过 `development.luna_only_direct` 和下述独立入口调用，旧 `run-canary` 保持历史路径。

固定的主要约束：

- 每个 frozen source/chunk 一次 Luna 调用，最多返回 8 个 slot 组；每组共享一个 claim/e+/Q+，在同次响应中提供 1–3 个 counter，最多展开 24 个备选 pair。每个有效 slot 都尝试提供三个 counter，无法给出足够明确错误的不同替换时允许少于三个；不追加 generation、counter-only 请求或 candidate 9。counter 须同角色、明确错误且不是彼此的同义词、别名或近义改写；语义要求由同次 Luna 承担，本地只做规范化字面去重，不增加在线语义 verifier。
- 按 `(normalized_true_claim, normalized_original_entity, normalized_counter_entity)` 去重，允许同 claim 不同 slot，也允许同槽不同 counter。全部检查后，先按原序选不同 slot 的首个有效 counter；不足三对再按 slot 顺序、counter 顺序补足：三槽 A1/B1/C1，两槽 A1/B1/A2，一槽 A1/A2/A3。每槽累计最多贡献三对，没有质量 ranking；若重复输出同槽，Q+ 必须逐字一致，否则 `same_slot_q_plus_mismatch` 拒绝。
- `candidate_count` / `valid_candidate_count` 现在记录 slot 组数，`valid_slot_count` 记录不同有效槽数；counter 数、有效 pair 数和最终 selected 数分别记录，不能把新组数与旧扁平候选数直接比较。不足三对仍记录 `source_eligibility_insufficient`；最终最多每 source 3 对、6 条 query，允许 Q+ 文本重复。共享事实的多个反事实探测不等于多个独立事实，统计单位仍是 source；交给后续的每个 pair 仍保存单值 `counter_entity`，支持与恢复行为由独立 PVS 评分处理。
- 先在 membership、Retriever、victim 与 AUC 不可见的条件下取得 2,250 篇 eligible source，再固定划分为 1,000 `KB_Member`、1,000 `True_Non_Member`、250 `Reserve`。
- 主 RAG index 只含 `KB_Member`；每个 dataset × Generator × Retriever 的主评估 cell 为 12,000 条 query，Reserve 不计入这一主 victim 预算。
- PVS 按 source 汇总，分别报告各 Retriever 的逐数据集与 macro 结果。模型、构造、split、检索、scoring 和评估配置必须在正式结果可见前冻结。

<a id="v24-formal-runner"></a>

### V24 正式 runner 与本地 mock 验证

正式代码路径为 `已有 selected pairs → 固定 split 绑定 → 六问计划 → 现有 RAG/victim → 原始回答 → hybrid PVS → source mean/median`。这是运行导出适配，不重新执行Luna、selector或构造gate，也不改变PVS公式和victim prompt。旧10号入口保留V20行为；V24必须显式使用 `--v24`，不会默认读取历史Gemma配置、V20 schedule或旧scoring。

复现本轮11项本地定向测试（外部client、Retriever、NLI均为mock，无网络/GPU）：

```powershell
& 'D:\python\anaconda\envs\mia_model\python.exe' -X utf8 -B -m unittest tests.test_token_bucket_runner.V24FormalRunnerTests
```

真实运行前，在现有 `configs/restoration_first_v24.yaml` 的 `formal.runtime` 填入单个dataset × Generator × Retriever cell的固定绑定。当前值为null，尚未选择真实运行参数。必填项如下：

| 字段 | 内容 |
|---|---|
| `selected_pairs_path` / `split_manifest_path` | 已有2250-source selected pairs JSONL与V24固定split manifest；不得用开发子集代替 |
| `output_dir` | 本cell独立输出目录；首次必须全新，后续默认校验后resume |
| `llm_profiles_path` / `victim_profile` | 已有victim profile文件和选中的profile；凭据仍只来自环境变量 |
| `generator_family` / `concrete_model` / `generator_version` | 明确的模型身份；实际profile和provider model ID必须匹配 |
| `retrieval` | `backend`、`retriever_id`、`index_dir`、`index_manifest_sha256`、`top_k`；支持dense/bm25/hybrid |
| `generation` | 显式保存 `temperature`、`max_tokens`、`timeout`、`retries`、`retry_backoff_base`、`retry_backoff_max`、`retry_until_success`、`retry_cooldown_seconds`、`request_interval_seconds`、`max_workers`、`requests_per_minute`、`checkpoint_every` |

hybrid的 `index_dir` 指向dense索引，另填 `bm25_index_dir`、`bm25_index_manifest_sha256` 与 `retrieval.hybrid` 的现有HybridRagRetriever参数；`reranker_revision`须固定、`reranker_local_files_only=true`，`final_top_k`与`top_k`一致。两个索引必须共享docstore。dense索引须声明固定embedding revision和本地加载。

绑定完成后可只读预检；当前null绑定会被明确拒绝，不会自动选用历史输入：

```powershell
& 'D:\python\anaconda\envs\mia_model\python.exe' -X utf8 -B scripts\10_run_rag_and_llm_only.py --v24 --dataset nfcorpus --config configs\restoration_first_v24.yaml --dry-run
```

预检验证2250总量、1000/1000/250固定split、source/hash/pair顺序、原问句及单次替换、主index只含完整的KB_Member集合，以及模型/后端绑定；不加载模型、不写文件。主计划只有2000 source、6000 pair、12000 query，Reserve无victim请求。相同Q+按不同pair保留三个query ID并逐条调用，Q−仍须互异。这里的检查是冻结产物完整性检查，不新增construction语义筛选。

实际执行去掉 `--dry-run`，并要求已获真实运行授权、config与代码已提交冻结。入口先加载既定本地NLI，再初始化Retriever/victim；缺权重或CUDA时不会先消费victim查询预算。原始回答不齐全时保留恢复状态、暂不评分；解析失败仍由既有PVS记录为不完整，不填零。默认resume只补未成功query；已完成cell仅校验产物，不再加载模型或调用API。输入、配置、profile、Git commit或结果hash漂移则拒绝续跑，不支持 `--force` 覆盖正式结果。

输出复用普通JSONL/JSON：`selected_main_pairs.jsonl`、`query_plan.jsonl`、`benchmark.jsonl`、`rag_responses.jsonl`及其既有identity/manifest、`scores/pair_scores.jsonl`、`scores/source_scores.jsonl`、`scores/scoring_summary.json`、`run_summary.json`。source主分是mean，median只诊断；membership分组在benchmark/split中，不能作为scoring或重选输入。每后端单独运行、单独报告，本入口不执行AUC/TPR评估。没有新增协议、authorization、ledger或freeze层。

当前只完成代码和mock验证；真实固定NLI五例sanity、正式输入与cell绑定、config+代码commit冻结尚待完成。mock的 `[1,0.8,0] → mean=0.6 / median=0.8` 仅验证接口与聚合，不代表真实NLI语义表现或攻击结果。

### V24 PVS 离线入口与此前冻结准备

只检查已有构造产物，不调用Luna、victim、Retriever或NLI，也不写分数：

```powershell
& 'D:\python\anaconda\envs\mia_model\python.exe' -X utf8 -B scripts\11_parse_stance_and_score.py --v24-hybrid --dataset nfcorpus --pairs artifacts\v24\development\luna_only_direct_fresh30_20260912\luna_attempt1\nfcorpus_batch1\smoke_results.jsonl --dry-run
```

`--config` 在该模式默认使用 `configs/restoration_first_v24.yaml`。`--pairs` 接受已有 `smoke_results.jsonl` 的 `construction.selected_pairs`、source级 `selected_pairs`，或逐pair JSONL；只展平已选结果，保持顺序、e+/e−及Q+/Q−原文，不读取Luna生成回答作为victim回答，不重新筛选或top-up。零对/不足三对的source保留为不足状态；同槽多个counter的重复Q+保留不同pair/query身份，不按文本去重。

有原始RAG回答后，用 `--responses <单cell回答JSONL> --output-dir <全新目录>` 替代 `--dry-run` 即可离线评分。回答沿用现有RAG行字段：`query_id/dataset/source_key/pair_id/claim_type/query/response/error`；`claim_type` 为 `true/counterfactual`，问句必须与已选pair逐字一致。query_id沿用V24已有规则：`sha256_obj({pair_id, polarity})`，polarity为`Q_plus/Q_minus`。每行保留 `mode=rag`、模型实际ID、Retriever、variant与context身份；入口拒绝跨cell、重复回答或问句/来源漂移。纯No、未知、解析失败与NLI失败仍按既有评分定义处理，不把失败填零或对剩余pair平均。

产出为 `pair_scores.jsonl`、`source_scores.jsonl` 和 `scoring_summary.json`；主分仍是三对mean，median仅诊断。summary保存输入/config/scorer hash、Git状态和cell信息；已有目录拒绝覆盖，不自动resume或回退到旧评分。模型仅在非exact恢复需要时加载；缺少固定本地权重则停止该次实际评分，不下载、不改模型。返回 `prepared_inputs_only` 仅表示输入预检完成，不表示模型可用、语义质量通过或正式冻结。

以下保留此前只接通离线入口时的冻结准备记录；正式runner衔接状态已由上节更新：

- Query Construction、Luna Prompt、selector、三对/六问及scoring公式保持；本轮只补评分入口。
- 固定NLI revision已声明，但本地权重与五个RA sanity case的真实双向entailment仍待验证；mock不能替代该结论。
- V24目录目前只有开发产物和source pools，正式eligibility/split/query/index/cell尚未产出或绑定。PVS离线入口不等于53号开发smoke已接通完整正式RAG运行；正式query导出和runner预算兼容仍待衔接，尤其不能沿用经典runner对source内重复Q+的拒绝规则。
- 工作树仍有未提交修改，当前HEAD不是本轮冻结提交。下一步先完成固定NLI的五例真实离线验证，再安排正式入口/固定split绑定与config+代码提交；本轮不启动这些运行。

证据：[入口与冻结准备验证](artifacts/v24/development/pvs_hybrid_20260913/entry_validation.json)。此前[独立函数验证](artifacts/v24/development/pvs_hybrid_20260913/local_validation.json)保持原样。

### 当前简况（2026-09-12）

**分组 counter 版本的同30篇真实复测已完成并停止。** 原完整chunk与顺序保持，30份响应共97个slot组、210个counter，本地有效208对、实际selected 66对；**20/30篇本地满三对：nfcorpus 8/10、scidocs 4/10、trec-covid 8/10**，旧扁平版为22/30。同槽fallback选入4对，让3篇补满三对；另10篇不足全部来自原始生成数量：5篇零slot、5篇只给出1–2个counter。本地仅拒绝2个counter，没有使原本够三对的source变成不足。见[完整报告与全部实际Q+/Q−](artifacts/v24/development/luna_only_direct_fresh30_20260911/grouped_counters_attempt1/retest_report.md)、[汇总](artifacts/v24/development/luna_only_direct_fresh30_20260911/grouped_counters_attempt1/retest_summary.json)及[完成记录](研究记录/顶会推进_notes.md#v24-luna-grouped-counters-retest-result)。

固定6篇中4篇有pair，实际抽查11对：8对的三项构造检查得到支持，2对丢失WhatsApp互动范围、1对的previously缺少参照时点；另记录一组hinder/prevent近义备用及一处the an措辞偏差。没有按抽查重选或推算全30篇语义通过率。共31次调用尝试、30份响应：00s2pabm首轮RuntimeError且无响应，仅在独立目录原样恢复一次，失败原件保留，其用量/计费未知。已收到响应的input/output tokens=55,950/71,510，累计请求latency=1387.325秒。30条离线回放和七个输出目录禁止client的resume通过；本次运行未改代码、Prompt、配置或PVS。

**分组 counter 版本的本地验证证据。** direct/mock **63项全部通过**，包含于完整 V24 回归 **297项：287通过、10项既有legacy skipped**。覆盖一槽三对、两槽补足、不同槽优先、8组/24counter全部检查但只选三对、Q+禁counter、去重与无top-up。六个旧扁平checkpoint在创建client或写入前均被既有漂移检查拒绝，历史产物保持。该实现阶段真实API/victim/Retriever/GPU调用为0；其后真实复测结果见上方，本次代码未变，没有重复运行这些测试。详见[实现与验证记录](研究记录/顶会推进_notes.md#v24-luna-grouped-counters)。

**此前扁平最终收缩版Prompt的同30篇真实复测与固定6篇抽查已完成并停止。** 当时生成130候选，本地valid=121、selected=67对，**22/30篇本地选满三对：nfcorpus 8/10、scidocs 6/10、trec-covid 8/10**。8篇不足中，7篇原始输出少于三候选（6篇为零），另1篇3个候选均被既有指代检查拒绝。同槽备用在1篇中填入2对，使其本地选满三对。该结果属于旧扁平schema的开发回归，不是分组版本的真实结果，也不是全30篇构造正确性通过率。

固定6篇中两篇零pair，实际抽查其余4篇的10对：8对的事实依据与反事实错误性得到支持，2对分别缺少抗体测量对象、初始/后续疗程范围；10对单槽替换均保持。未抽查部分不记通过，未按抽查重选。30条重解析/选择回放、130候选全量处理、67对替换和六批离线resume通过，代码、Prompt、配置与PVS不变。见[本轮报告与实际Q+/Q−](artifacts/v24/development/luna_only_direct_fresh30_20260911/final_contraction_attempt1/retest_report.md)及[完成记录](研究记录/顶会推进_notes.md#v24-luna-final-contraction-retest-result)。

30次成功生成的input/output tokens为51,570/63,475，累计请求latency为1229.418秒。首批另有5次沙箱内无响应尝试，经确认后在独立目录重新执行；失败原件保留，原请求计费未知，因此不能把整体调用写成只有30次。未运行victim、Retriever、GPU或formal，没有新版本、提交或推送。

**2026-09-12完成复核口径收缩。** 本次只修改README和两份研究总表，生成Prompt、选择器、测试与PVS均未改动；没有新增审核器、分数或准入阈值。后续报告分开记录本地数量是否满三对与抽查发现的具体构造问题。旧5/30等审核结论按原口径保留，未重新标注；本轮未做真实生成或抽查，API调用为0。

**2026-09-11最终收缩式修复及本地验证完成。** direct/mock共55项；扩展回归303项中293通过、10项既有legacy skipped，55项包含其中。最近30篇的116个保存候选只做离线回放：3个纯大小写拒绝恢复，新增指代/Q+ counter检查生效，本地valid由110变100、selected由61变57、本地三对source由15变13。没有重新生成或重新计算语义通过率，原始实验产物保持；API/victim/Retriever/GPU调用为0。设计、代码边界及回放明细见[最终修复记录](研究记录/顶会推进_notes.md#v24-luna-final-contraction)。新Prompt的真实输出尚未验证。

**上一版Prompt对同30篇的真实复测及全部候选诊断已完成。** 原样复用三数据集各10篇的完整chunk与顺序，30次Luna返回116候选，本地valid=110，实际selected=61；15/30篇本地选满三对，Assistant-only确认三对均有效为 **5/30：nfcorpus 2/10、scidocs 0/10、trec-covid 3/10**。对比旧响应按当时selector回放的8/30，这批复测未见提升；它是同批开发回归，不是新的未见fresh30或正式结果。见[该次报告与全部实际Q+/Q−](artifacts/v24/development/luna_only_direct_fresh30_20260911/same_slot_counter_attempt1/regeneration_report.md)及[研究总表](研究记录/顶会推进_notes.md#v24-luna-same30-regeneration)。

15篇数量不足全部在Luna原始响应中就只有0–2个候选，并非本地gate把至少3个筛成不足；另10篇虽选满三对，但语义未通过。新响应中本地接受6个同槽备用候选，全部来自4篇scidocs，诊断为4失败/2未确认；实际选入2个，没有增加三对语义有效source。已选61对为39有效/15失败/7未确认，没有按Assistant标签重选。

实际API logical/physical/retry=30/30/0，input/output tokens=48,060/62,912，累计请求latency=1280.893秒。30条重解析/回放、116候选全量处理、61对单次替换和六批禁用client的完成态resume通过；本轮未改代码、Prompt或配置，10个保护文件和27个旧产物hash不变。当前结果已保存并停止，没有追加生成、victim/Retriever/GPU或formal调用。

**同槽备用反实体规则已实现并完成本地验证。** direct/mock 48/48通过；扩展回归296项中286通过、10项既有legacy skipped。回放原fresh30的30条保存响应、115候选，仅MED-1118由C0/C1改为C0/C1/C2，新增一对沿用此前Assistant有效标签；其余29篇选择及已选问句不变。本地valid=111、selected=67、本地三对source=18/30、三对均语义有效=8/30（nfcorpus 4/10、scidocs 0/10、trec-covid 4/10）。见[实现与本地回放报告](artifacts/v24/development/luna_only_direct_fresh30_20260911/same_slot_counter_local_regression_20260911/local_regression_report.md)。

这是此前新selector对旧响应的回放；当时尚未真实验证新Prompt的生成效果。该次新增API/tokens/API latency均为0，未改PVS、配置或旧产物。30条重解析/回放、67对单次替换通过，新代码在client初始化前拒绝resume六个旧attempt；该次8/30与上面的新真实生成5/30分别保留。

**此前 atomic Q+ Prompt 的 fresh30 开发验证已完成。** 三数据集各10篇，30次Luna返回115候选，本地valid=110、实际selected=66；17/30篇本地凑齐三对，Assistant-only复核后实际选中三对均有效为 **7/30：nfcorpus 3/10、scidocs 0/10、trec-covid 4/10**。已选66对为41有效、23失败、2未确认。另23篇中13篇数量不足、10篇虽然凑齐却含语义问题。见[完整报告与全部实际Q+/Q−](artifacts/v24/development/luna_only_direct_fresh30_20260911/fresh30_report.md)及[研究总表](研究记录/顶会推进_notes.md#v24-luna-fresh30-development)。

主要失败包括未解析指代、非原子问句、反事实错误性未确定、条件或语义角色改变。本地只拒绝5个候选（duplicate=1、q_plus_slot_count=4）；其中3次slot失配是大小写契约问题，不等同于事实或英语语法错误。5篇原返回候选中仍有足够有效候选，但原序选中坏候选；诊断没有重选，不能把事后候选可用性12/30写成实际通过率。

该次API logical/physical/retry=30/30/0，tokens=43,980 input/64,251 output，累计请求latency=1265.146秒；无Retriever/victim/GPU调用。30条重解析、选择回放、66对单次替换及六批禁用客户端的完成态resume通过，当时原产物与10个源码/config/PVS保护hash不变。真实生成与复核阶段未改代码或Prompt，未重跑此前39/39 direct/mock测试。固定未见prefix每数据集10篇，只作开发诊断；该批结果原样保留，后续修改与本地回放另存。

此前Prompt输出修正仅改三处要求并通过39/39 direct/mock测试：Q+保持原实体、引文逐字复制、同次调用检查完整chunk。正常数值问句与小写引文配自然问句合法；无补生成或repair。上述fresh30才是该Prompt的新真实生成结果，历史mock与同六篇计数不替代本次语义复核。

**此前最小筛选修复与同六篇保存响应的本地回归已完成。** 原18个候选全部检查，本地valid=9，最终selected=7；Assistant-only复核已选7对均有效，2/6 source有三对有效pair。MED-1114的C0/C1/C2由指代规则拒绝，C3/C4/C5三个OR候选按原顺序入选。没有重新生成Luna候选。见[完整回归报告](artifacts/v24/development/luna_only_direct_beir6_20260910/atomic_qplus_local_regression_20260911/local_regression_report.md)。

该次9个候选被拒，原因命中为 `unresolved_discourse_reference=5`、`q_plus_slot_count=4`、`claim_not_exact_chunk_span=1`；一条候选同时命中两项。MED-1114的C7仍是非atomic问题，本地通过但未选，不把全部valid写成语义通过，也未为它加规则。该次是同一响应上的筛选回归，不能推断新样本或总体质量，也不代表最新Prompt的生成效果。

当次direct/mock测试38/38通过；扩展回归286项中276通过、10项既有legacy skipped，38项包含在286项内。六篇身份、原响应重解析、完整筛选和七对单次替换均通过，原产物及配置hash不变。该次新增API/tokens/API latency均为0，Prompt和PVS未改，完成后停止调整同六篇。

**此前2026-09-10的同六篇 atomic Q+ 真实复测与全部诊断已完成。** 20:21:20完成6次Luna请求，返回18候选，自动选中7对、2/6 source自动达到三对。Assistant-only复核全部18候选为8有效/10失败；已选7对为4有效/3失败，1/6 source具有三对确认有效pair。MED-1114前三个上下文依赖人数句占满选择名额，后四个有效OR草稿早停未选；另有Q+提前填入e−和claim大小写漂移被确定性gate拒绝。见[原始报告与全部问句](artifacts/v24/development/luna_only_direct_beir6_20260910/atomic_qplus_attempt1/atomic_qplus_retest_report.md)。

该次logical/physical/retry=6/6/0，tokens=8,205 input/8,590 output，累计请求latency=172.324秒。六条身份、重解析、选择回放、七对单次替换及禁用客户端的完成态resume均通过；原response/summary不变。当次运行与复核未改代码/Prompt/config，没有追加API、补选或进入fresh30/formal。

此前本地验证direct/smoke 29/29通过；v24、BEIR source pool与sibling rate-limit回归277项中267 passed、10项既有legacy skipped。29项是277项的子集。该次真实复测期间代码未变，没有重跑这些测试；它们不替代真实语义复核。

此前设计阶段撤回了“Q+ 没有复述其他并列事实”这一拒绝理由；OR 句只验证 beef 对应的 1.22 可以成立。旧响应、诊断标签与计数原样保留，本轮未重新标注或生成，下面的历史 0/6 不代表 atomic Q+ 的效果。

**上一版自然语义 Prompt 的同批六篇真实复测与全部诊断已完成。** 16:55:52 完成六次 Luna 请求，返回14个候选，自动选中12对、3/6 source自动达到三对。按当时整句忠实性口径，Assistant-only复核全部候选为 **2 confirmed_valid / 8 failed / 4 unconfirmed**；已选12对为 **2/7/3**，确认三对有效的source为 **0/6**。当时记录了模板省略并列内容、未解析话语指代、局部slot拼接/名称冲突、无锚点相对时间及反事实错误性不足。见[历史真实复测报告与全部实际 Q+/Q−](artifacts/v24/development/luna_only_direct_beir6_20260910/natural_semantics_attempt1/natural_semantics_retest_report.md)。

该次真实调用logical/physical/retry=6/6/0，tokens=6,585 input/9,275 output，累计请求latency=196.735秒。六个真实响应的身份、离线解析及选择回放通过；禁用API客户端的完成态resume保持原response/summary不变。真实复测期间未改代码、Prompt、配置、PVS或正式约束；复核追加API=0，完成后停止，未进入fresh30/formal。单次同六篇开发回归不能推断总体容量或显著改善/退化。

此前接入后的direct/smoke测试22/22通过，定向回归270项中260 passed、10项既有legacy skipped；该阶段API=0。本次代码未变，未重复这些测试。同六篇旧输出按新口径的Assistant-only诊断为4有效/4不合格/2未确认，原选中九对为4/3/2，1/6 source具备三对确认有效pair；它是本次同口径比较的旧输出基准。见[当时本地验证与重评报告](artifacts/v24/development/luna_only_direct_beir6_20260910/natural_semantics_local_review/local_validation_report.md)。

以下为此前运行时 Prompt 与当时审核口径下的历史复测记录。“仅缺专名”及“极端量词 scope 解释”已不再作为当前口径的拒绝依据；旧标签、响应与报告原样保留。

**此前上下文修复后的同批六篇真实复测已完成，当时质量验收未通过。** 13:23 完成六次 Luna 请求，返回10个候选、自动选中9对、2/6篇自动达到三对。全部候选已完成 Assistant-only 复核：7个 failed、3个 unconfirmed；已选9对为6个 failed、3个 unconfirmed，确认三对有效的 source 为0/6。旧的 `our proposed framework` 数值候选没有重现，当时记录了方法范围、相对时间和反事实错误性问题。见[同批六篇复测报告与实际 Q+/Q−](artifacts/v24/development/luna_only_direct_beir6_20260910/context_fix_attempt1/context_fix_retest_report.md)。

该次历史复测 logical/physical/retry=6/6/0，tokens=7,275 input/9,229 output，累计请求耗时181.685秒。source/prompt/模型/结果身份、离线解析、选择回放和禁用client的完成态resume通过；后续复核新增API=0。代码、Prompt与配置在该次复测过程中未改动，原批和新批原始结果均保留；这只是已知问题的开发回归，不是总体容量或正式评估。以上 API 使用量不计入本轮本地验证。

此前 **6 篇真实 BEIR 开发 source** 的修复前运行已完成全部16个候选的 Assistant-only 复核：自动选中9对、2/6篇达到三对；其中6对明确依赖上下文，另3对的反事实真假或时间语义未能确认，因此确认具备三对有效 pair 的 source 为0/6。见[六篇验证与上下文修复报告](artifacts/v24/development/luna_only_direct_beir6_20260910/offline_review_20260910/beir6_validation_and_context_fix_report.md)。原响应与自动计数保留。

此前上下文修复阶段曾在 Luna 构造 prompt 中明确：claim 脱离标题/前后文仍须明确主体和必要研究条件；`our proposed framework → the proposed framework` 不算消解指代；不得借标题加名称或拼句修复；不完整 claim 下的所有数值/日期 slot 都应跳过。claim 内已有明确先行词的代词仍允许，模板也须保留明确主体。确定性 gates 与其他构造行为不变。该阶段20项 direct 测试通过，完整定向回归268项（258 passed、10项既有 legacy skipped）；当时新增 API=0。其后真实效果见上方历史复测记录；当前 Prompt 已按最新自然语义口径更新。

以下是此前8个定向夹具的实现验收记录：

简化方案 B 的实现、定向测试与一次真实 smoke 已完成。8 个预先固定的开发 chunk 返回 6 个候选，代码保留 6 对，Assistant-only 逐条诊断均有效；未解析代词、成员列表、反事实真假不确定三个负例均返回空列表。没有 source 达到三对，eligible 为 **0/8**，未补抽；这些定向夹具不能估计 BEIR 通过率或 source 容量。完整八类样例、Q+/Q− 与归因见[本轮报告](artifacts/v24/development/luna_only_direct_smoke_20260910/attempt1/implementation_smoke_report.md)。

新增 18 项 direct 测试通过；定向回归共 266 项，256 passed、10 项既有 legacy skipped。真实调用为 8 次 logical / 8 次 physical / 0 次 retry，模型 `gpt-5.6-luna`；input/output tokens 为 6,052/1,627，累计请求耗时 126.973 秒。8 个保存响应离线重解析、构造回放和完成态 resume 校验通过，收尾未追加 API 请求。原始运行 summary 保持原样，语义诊断另存为 Assistant-only 记录。

Query Construction 在两问实例化后结束；支持、否定与恢复留给 PVS。现有 v23 PVS 对 correction_entity 使用规范化 exact equality，经典 parser/scorer 也依赖关键词/实体字符串，尚不完整表达连续语义 restoration；这些评分位置已记录为后续独立事项，本轮 PVS 主公式未改。

| 53 号脚本的当前运行入口（atomic Q+ + 单次替换） | 用途 |
|---|---|
| `preview-luna-only-smoke --input <frozen chunk JSONL>` | 本地校验，最多 8 source，无 API/GPU 调用 |
| `run-luna-only-smoke --input <同一输入> --output-dir <新开发目录>` | 每 source 一次 Luna，保存完整响应、候选、pair 与统计；同目录恢复使用 `--resume` |

输入和输出均限定在 `artifacts/v24/development/`。本轮分组 counter 的同30篇真实复测、固定抽查和报告完成并停止；未创建 v25，未改变 BEIR datasets、formal split、2250 target、3 对/6 问、PVS 主公式或 AUC/TPR@1%FPR，未启动 capacity/formal。

<details>
<summary>2026-09-09 及此前开发记录（历史路径与当时待办）</summary>

### 历史简况（2026-09-09）

以下保留当时的结果、入口与待办；当前构造方案和停止边界以上方 2026-09-12 分组 counter 条目为准。历史两阶段、事实补全和 A/B 待办不自动延续到简化方案 B。

新开发样本两阶段真实 canary 已于 10:49 完成，**质量验收未通过**：30篇输入完成，自动通过12/30对，Assistant-only两问均通过8/30对（NFCorpus 3/10、SCIDOCS 4/10、TREC-COVID 1/10）。已交付24问句中16通过、8失败；其余36目标槽位未选出问句，全部60槽位已记录。执行缺失0，Luna逻辑/物理/重试=84/85/1，阶段响应已保存且核验一致。见[本批验收与归因报告](artifacts/v24/development/query_quality_canary_two_stage_fresh_20260909/luna_attempt1/canary_acceptance_report.md)。TREC-COVID三篇零候选及首次不足的预检保留，本批不进入capacity/formal。

18 篇固定旧开发样本的 A/B 已结束，本轮离线复核与归因完成：135 个保存候选、270 条问句的既有 Assistant-only 标注已复检，原报告重算一致。S7/B 无法可靠补全、R21/A 发生 JSON 解析错误，完整可比 source 为 16 篇；首次合格候选可用性 A/B=`8/16→16/16`，最终选中 pair 合格数=`9/16→14/16`，最终指标精确配对 p=`0.125`。这是定向开发样本结果，不是容量、泛化或攻击 AUC 结论。见[离线归因报告](artifacts/v24/development/fact_context_ablation_20260908/offline_review_20260909/analysis-report.md)与[统计附录](artifacts/v24/development/fact_context_ablation_20260908/offline_review_20260909/stats-appendix.md)。

原运行保持 `completed_diagnostic`，原汇总报告保持 `incomplete_execution`，整批 macro 保持 null；本次补充统计仅针对 16 个完整配对。累计记录 46 次逻辑/物理请求、0 次传输重试，原 `external_call_counts_complete=false` 保留。未补跑、覆盖原标注或将缺失记成质量失败，本轮新增真实调用为 0。

代码已补齐“完整事实构造 → 原文支持/完整性核验 → 固定 canonical → 共享问句模板 → 问句忠实性核验”，两阶段模式现已完成首轮真实验收，结果见上文；此前题名标点、合法 `that` 从句、因果 `since`、助动词/并列问句和失败响应保存已修复；234 项定向测试通过（224 通过、10 项既有跳过）。旧 135 个草稿的文本规则回放消除了 21 个候选的文本误报、新增拦截 12 个语法缺陷候选，对原复核合格的 96 个候选没有新增文本误拒；其中 21 个包含原纯文本误报 20 个及叠加角色约束 1 个，其他构造约束不因此放行。这是开发回归，不是新样本质量验收。两阶段核验仍是同一模型的单独请求，不能称为独立人工审查。

此前批次 `query_quality_canary_beir_scopefix_fresh_20260908` 于 9 月 8 日 10:19（Asia/Shanghai）完成全部 30 篇，验收未通过：自动门禁通过 18/30（NFCorpus 8/10、SCIDOCS 5/10、TREC-COVID 5/10），Assistant-only 两问均通过 8/30 对。实际复核 36 条问句，16 条通过、20 条失败，另 24 个槽位未选出问句；全部 60 个槽位已记录，`capacity_sample_allowed=false`。见[该批运行汇总](artifacts/v24/development/query_quality_canary_beir_scopefix_fresh_20260908/luna_attempt1/canary_summary.json)与[该批逐问复核汇总](artifacts/v24/development/query_quality_canary_beir_scopefix_fresh_20260908/luna_attempt1/assistant_query_quality_review_summary.json)。

本批沿用修复后的代码、配置与切分，使用无历史 source/text 身份重叠的新开发样本及新输出目录；32 篇抽取记录包含两篇按既定规则补选的零候选，原记录和首轮 28/30 不足额预检保留。实际模型为 `gpt-5.6-luna`，逻辑调用 43、实际请求 52、传输重试 9，终态计数完整。会话中断期间后台持续运行，全部结果逐条保存，未使用 `--resume`。

剩余问题包括未限定的时间、比较人群、文献/研究范围，以及原文粘连词和病句；完整题名曾有疑似误报。另记录荷兰语输出、疑问句被当作 canonical、标题片段进入候选，以及仅替换缩写的语义区分度问题，未在本批临时增加语言或反事实真值门禁。后续两阶段开发不改判这些历史结果，当前不进入 capacity。不同开发样本的通过率不能当作受控修复效果。

此前 `query_quality_canary_beir_referencefix_fresh_20260908` 于 07:51（Asia/Shanghai）完整结束，自动门禁通过 25/30、Assistant-only 两问均通过 13/30 对；实际复核 50 条问句，26 条通过、24 条失败，另 10 个槽位未选出问句。见[该批运行汇总](artifacts/v24/development/query_quality_canary_beir_referencefix_fresh_20260908/luna_attempt1/canary_summary.json)与[该批逐问复核汇总](artifacts/v24/development/query_quality_canary_beir_referencefix_fresh_20260908/luna_attempt1/assistant_query_quality_review_summary.json)。随后完成 `US/us`、题名边界、标题与观察范围检查修复，199 项定向回归中 189 passed、10 skipped legacy；只读 mock 回放保留 13 对、拦截 12 对。本次真实验收使用这些修复，未重新运行上述单元测试或改判历史结果。

三套 BEIR source pool、GLiNER2 排序 v2 的开发验证和 30-input canary 离线预检已完成。修复保存机制后的 `luna_attempt2` 于 19:12（Asia/Shanghai）完成全部 30 条输入并保存结果；自动门禁通过 28/30 对（NFCorpus 8/10、SCIDOCS 10/10、TREC-COVID 10/10），终态为 `failed_hard_gates`。这是完整运行后的门禁失败，不是中断丢失结果。

Assistant-only 复核已覆盖全部 60 个目标槽位：实际生成并复核 56 条问句，20 条通过、36 条未通过，另有 4 个槽位没有通过自动门禁的问句。主要问题是原文指代或统计范围不明确，以及缩写、版权残片和 OCR 噪声。见[运行汇总](artifacts/v24/development/query_quality_canary_beir_ranked_v2_20260907/luna_attempt2/canary_summary.json)与[问句复核汇总](artifacts/v24/development/query_quality_canary_beir_ranked_v2_20260907/luna_attempt2/assistant_query_quality_review_summary.json)。当前不进入 capacity。

此后已完成构造修复与离线回归：Luna 使用同篇原文消解主体、研究范围和缩写；预检与运行时共同拦截版权残片和明显损坏的单位；校验拒绝未解析泛称、缺少范围的统计句和原文未出现的新主体，并修正原始 fact 别名被误报为新增实体的问题。旧样本的结构回放（相似度使用 mock）拦截了先前漏过的 19 对问题问句，保留原先复核通过的 9 对；这不是新的真实 canary 结果，也不代表完整语义质量已自动保证。

新开发批次 `query_quality_canary_beir_contextfix_fresh_20260907` 于 21:56（Asia/Shanghai）完成全部 30 篇并逐条保存，与历史开发 source/text 身份无重叠。自动门禁通过 22/30（NFCorpus 7/10、SCIDOCS 8/10、TREC-COVID 7/10）；最终选出并复核 44 条问句，30 条通过、14 条未通过，另 16 个目标槽位未选出合格问句。三数据集各有 5/10 对两问均通过，整批验收未通过。见[本批运行汇总](artifacts/v24/development/query_quality_canary_beir_contextfix_fresh_20260907/luna_attempt1/canary_summary.json)与[问句复核汇总](artifacts/v24/development/query_quality_canary_beir_contextfix_fresh_20260907/luna_attempt1/assistant_query_quality_review_summary.json)。TREC-COVID 的 2 篇零候选按冻结顺序补选，原记录保留；实际模型仍为 `gpt-5.6-luna`，逻辑调用 41、实际请求 73、传输重试 32。

本批同时发现漏检和误报：标题片段被当作命题、数学公式乱码及前提缺失、实验/论文/数学描述指代不完整仍会漏过；`titled ...` 的题名限定、存在句中的 `there`、补语从句中的 `that` 以及有原文依据的 `Jacobi-polynomial-based` 派生词又会被规则误拒。已有失败产物不改判，也不把新旧不同开发样本的通过数直接解释为修复效果。

本轮修复区分存在句、补语/有先行词的定语从句与真正外指代；题名限定须匹配原文首行完整题名或有明确边界的题名前缀，派生形式只容许保留名称/数字的有限变化。query 预检和构造检查补齐非命题标题、公式转码残片、缺失实验/描述对象及未定义数学变量，并禁止把标题主题擅自改成报告者；声明式标题仍可使用。已保存的 22 对问句在只读结构回放中，先前复核通过的 15 对均保留、漏过的 7 对均被拦截；相似度和语义判断使用 mock，这只是开发回归，不是新真实 canary 验收。旧输入/结果和候选池未改写；新代码不能按旧运行身份原地 resume。

当前 canary 每篇只测试 1 对问句，并按冻结顺序补选零候选 source；它的通过率不能估计正式所需的每篇 3 对问句覆盖率。结构检查、Luna 自评和 Assistant-only 复核也不能表述为独立人工盲审。

待完成的开发工作：

1. 首轮新样本两阶段验收已完成且未通过。优先修复目标别名与原文指代的处理约定、事实构造/核验的实验范围遗漏、固定命题属性保留及语言支持；先用本批证据做离线回归，再决定下一轮新样本验收。保留固定单槽、查询预算和历史失败，不原地重试为通过。
2. 修复 capacity 对缺失 `source_pool.expected_source_counts` 的读取，改用已核验的源池总量及开发排除集合；随后优先验证 NFCorpus 的真实 source 级容量。
3. 补齐 v24 query manifest 到 RAG/PVS 的接口：当前输出 `query_text/polarity`，经典 runner 要求 `query/claim_type`；正式扫描和导出也尚未由 53 号 CLI 串接。完成独立开发集端到端验证后，再冻结并运行正式实验。

capacity 总量取数与 v24 → RAG/PVS 接口仍待修复；新 BEIR 的正式 eligibility、split、victim 与评分产物均未生成。canary 逐条保存已通过真实运行验证，断点恢复已通过离线回归；本批会话中断未停止后台运行，也未实际使用 `--resume`，不声称完成真实恢复演练。旧运行未落盘的完成数及调用数仍未知，已有开发产物和历史失败证据保持各自身份。

### 开发对照与两阶段入口

均使用现有 53 号脚本，`preview-*` 只核对本地输入与身份，不加载模型。

| 命令 | 输入与用途 |
|---|---|
| `preview-fact-ablation` / `run-fact-ablation` | `--input artifacts/v24/development/fact_context_ablation_20260908/reference_facts.jsonl`；18 篇、36 个 A/B 条件；原批次已结束，复现其 prompt/校验器须使用当时源码，当前修复不能原地续跑该批次 |
| `summarize-fact-ablation` | `--input <canary_results.jsonl> --review <候选级 Assistant 复核.jsonl>`；分别报告首次生成、最终选择及校验误报，逐数据集和 source 配对汇总 |
| `preview-two-stage-canary` / `run-two-stage-canary` | `--input <开发 canary_inputs.jsonl> --candidate-pool <pool_manifest.json>`；池参数可重复，只接受开发候选池，按配置固定 30 篇、每篇一个指定 fact |

两种 `run-*` 都必须显式给出新的 `--output-dir`，恢复才加 `--resume`。A/B 设计最多 72 次逻辑生成，当前一个 B 条件不可补全，实际最多 70 次；两阶段每 fact 最多 6 次逻辑请求（构造、事实核验、三候选生成、问句核验，以及最多一次纠正和再次核验），30 篇上限 180 次。传输重试另计。拒绝一个 fact 不表示整个 source 无可用事实，正常 source 筛选会继续固定前 8 个候选；canary 不替换已经指定的 fact。

两阶段保留原句/span、重构命题、原文证据、目标别名、全部模板与展开后的两问，以及两层核验结果。完整命题只保留一个目标槽，需展开才能自包含的缩写目标或槽外残留目标别名会明确拒绝。原样保留的 `that` 局部从句只能凭已核验固定命题获得豁免；本轮明确的题名标点、语法与因果词修复作用于公共校验器。原 A/B 运行对应的两份源码另存为[修复前代码快照](artifacts/v24/development/fact_context_ablation_20260908/offline_review_20260909/pre_repair_code.zip)，原报告与标签不改写。`completed_two_stage_diagnostic` 表示执行结束；`automatic_quality_pass` 单独报告自动门禁，`assistant_review_completed=false`，不准许 capacity 或声称人工质量通过。

### Canary 保存与恢复

`run-canary` 在模型初始化前创建 `canary_results.jsonl` 和 `canary_summary.json`，每完成一条输入便原子保存结果，再更新汇总；成功、门禁失败和执行失败都会保留。终端显示当前 source 与完成数，汇总提供 `completed_pair_count`、`passed_pair_count`、`active_input_index`（从 0 开始）和 UTC `updated_at`。`running` 是最后保存的状态，不单独证明进程仍在运行。

恢复时在原 `run-canary` 命令末尾加 `--resume`，保持 `--input`、全部 `--candidate-pool` 和 `--output-dir` 不变。程序先核验输入、候选池、原文 fact、配置、有效模型 profile、相关代码和已保存结果，再跳过全部已完成条目；失败条目同样不会重试。结果已经落盘而汇总尚未更新时，可从结果补齐汇总。已完成的运行可离线读取；原本 `failed_hard_gates` 的运行仍返回失败，不会因 resume 转为 passed。

恢复粒度是一篇 source 的一条 canary 输入。中断时尚未落盘的条目会重新执行，在途 API 请求可能已经到达服务端；`external_call_counts_complete=false` 表示保存的调用/重试计数并不完整，不能将其当作精确总量。文件损坏或运行身份漂移会在模型调用前报错，不静默丢弃已有结果。旧版运行若没有可核验的 checkpoint，不能补造结果或直接 resume；保留旧目录，在新输出目录运行固定输入即可，无需创建新的科学协议版本。

新增 A/B 和两阶段入口在既有 summary 内先保存响应正文、模型 ID、结束原因、token 数与重试数，再解析 JSON。只保存允许的响应字段，脱敏已知凭据，异常仅记类型；不保存客户端或请求头。恢复时 `response_received` 可从保存正文离线解析，`response_invalid` / `request_failed` 保留失败且不重发；落盘错误中止运行，不转成科学质量拒绝。完整收到但 JSON 无效的响应可保留已知调用计数；传输失败或中断后的计数仍保守标为不完整。

两阶段恢复复用已保存的构造、核验与问句结果；已开始却没有持久响应的阶段标为 `response_unavailable_after_interruption`，该输入记执行不完整并停止下游请求，不重新抽取或计作科学质量拒绝。原 R21/A 未保存的响应无法追溯恢复，本次修复不补填旧证据。

</details>

### 环境与离线检查

本机唯一 Python 环境为 Conda `mia_model`，解释器固定为 `D:\python\anaconda\envs\mia_model\python.exe`。模型下载、依赖安装、GPU 长任务、真实 API/victim 和大型索引构建须有对应用户授权；普通本地开发与 mock 测试不需要额外 authorization 文件。

```powershell
& 'D:\python\anaconda\envs\mia_model\python.exe' -X utf8 -B -c "import sys; print(sys.executable)"
& 'D:\python\anaconda\envs\mia_model\python.exe' -X utf8 -B scripts\53_run_v24_pre_split_eligibility.py --help
& 'D:\python\anaconda\envs\mia_model\python.exe' -X utf8 -B scripts\53_run_v24_pre_split_eligibility.py validate-config
& 'D:\python\anaconda\envs\mia_model\python.exe' -X utf8 -B scripts\53_run_v24_pre_split_eligibility.py source-pools
& 'D:\python\anaconda\envs\mia_model\python.exe' -X utf8 -B -m unittest tests.test_restoration_first_v24 tests.test_v24_beir_source_pool tests.test_sibling_rate_limit
```

`source-pools` 会读取并校验本地数据库 hash，不执行模型推理或 API 调用。上述定向测试覆盖候选池、问句质量、原 canary 保存/恢复、A/B 归因及两阶段执行；最新测试结果见两份研究总表。这不是全仓库回归或真实模型质量验收。

## 历史说明

下方保留旧版本说明与当时的操作示例，供复现和查证。它们不是当前 v24 的执行入口，也不代表相应历史阶段仍待运行；最新状态以研究总表和绑定的机器可读产物为准。

<details>
<summary>v23 Restoration-First：2026-08-15 历史快照</summary>

### v23 历史协议

该快照中的研究协议是 `pcv-mia-v23 / pcv-restoration-first-v23`，设计配置入口为
`configs/restoration_first_v23.yaml`，零外部调用 runtime 入口为
`scripts/42_run_v23_restoration_first.py`。v22 的三套 source pool 与 pilot 可按
v23 冻结绑定受控复用，但 v22 `calibration_r3` 已以
`failed_final_calibration_revision` 正式失败；不得续跑 v22 formal scan、split、
fresh audit、shadow、query、victim 或 Retriever 阶段。

v23 取消反事实自然性优化和未实施的 Luna Generation-First。类型与句法只承担最低
构造有效性约束，P0 selector 的选择目标是：

- 原事实稳定、原实体可恢复；
- 非实体检索锚点充分；
- 验证结果可辨别；
- query 自包含且输出可解析。

P0 正式类型固定为 `CONTRACT_TERM`、`LOCATION`、`ORG`、`PERSON`、`PRODUCT`。
`DATE`、`MONEY`、`EMAIL`、`PHONE`、`IDENTIFIER` 只作为诊断与次要扩展，不能填充
P0 所需 pair。类型多样性本身不是优化目标。

v23 当前 Generator 实验矩阵为 `Phi-4-14B`、`Llama-3.1-8B`、`Command-R-7B`
和 `Gemma 2 2B`，首个实验 Generator 为 `Gemma 2 2B`。Luna 仅承担后续 query
generation，不属于这四个被测 Generator；各 Generator 的具体 model ID、revision、
snapshot、precision 与 decoding contract 必须在各自首次调用前冻结。

selector 禁止读取或利用 membership、split/group、victim/RAG response、
LLM-only response、Retriever 输出、attack score/AUC 或 v22 calibration
label/threshold。完整 source pool 只允许在受控 aggregate-DF stage 按 producer
execution identity/dataset 读取一次；跨 runtime bundle 复用必须有显式 carry-forward
证明。其输出只包含 aggregate token DF，不包含 source 映射或逐 source 行，也不得
据此声称低频 token 不可反演。

### v23 历史状态（2026-08-15）

| 阶段 | 状态 | 可核验证据 |
|---|---|---|
| Runtime 实现、bootstrap 与 revision 3 freeze | 已完成 | active bundle `1c2c933d...a8cb8` / revision `7add7622...54bff` |
| Edgar aggregate-DF | `passed` | 5,210 sources / 116,953 token rows / 0 external calls |
| Enron aggregate-DF | `passed` | 35,000 sources / 181,394 token rows / 0 external calls |
| PubMed aggregate-DF | `passed` | 47,950 sources / 1,284,757 token rows / 0 external calls |
| Stage-Scoped Identity execution erratum e1 | `passed` | aggregate-DF fingerprint `9fc3c9d...c8011`；三数据集 carry-forward 已验证 |
| reserve snapshot/write-ahead 与 development-pilot runner | 已实现、未冻结 | 仅完成离线合成测试；真实 reservation/pilot 均未启动 |
| v23 fact extraction、selector pilot 与 capacity gate | 未启动且 blocked | 等待 runner 提交、successor freeze 与独立真实运行授权 |
| fresh audit、formal scan、split、shadow、Luna query generation、四个 Generator victim、Retriever 与 evaluation | 未启动且 blocked | 必须依次通过上游 gate，并分别取得长任务/GPU/API/victim/Retriever 授权 |

三套 aggregate-DF 的 producer revision 为
`286e1f0a1c0dff1db917ea00a387192b8cbded7b3577e57d3cc86b4847524621`，并已通过
attestation `c3f1b179...a95db3` carry-forward 到 active revision
`7add7622b9bf76e1547a6ce98fa5178e0a6e9a26eb147fb3553a7b9b0ab54bff`。
三套 manifest 均记录 `external_calls_performed: 0`；当前没有 v23 victim、
LLM-only 或 Retriever 响应可用于选样或报告结果。

`pcv-restoration-first-v23-design-r6 execution erratum e1` 将完整 `runtime_bundle`
保留为 provenance，同时用 `stage_dependency_fingerprint` 决定阶段产物兼容性，并用
`stage_execution_identity` 绑定 protocol revision 与 fingerprint。README、研究记录和
非计算 launcher 不传播实验失效；aggregate-DF 分词、归一化、DF 算法或任一 source
pool identity 变化会令三套 DF 及全部下游 stale。任何跨 bundle 复用都必须单独授权并
生成 `artifacts/v23/protocol/stage_compatibility/<new_revision>/aggregate_df_precomputation.json`，
不会改写原 DF、读取 88,160 个 source、增加预算扣费或修改 ledger。revision 3 的
carry-forward artifact 已生成并通过验证，原 DF、budget、checkpoint 与 ledger 未改写。

本轮新增的 reservation/pilot runner 将一次 revision 的三套 fresh-audit reserve 从同一
prior ledger snapshot 推导，先冻结 snapshot，再按 EDGAR、Enron、PubMed 顺序完成
development 与 reserve write-ahead batch。development pilot 按 dataset 独立授权，逐
source 先扣预算再读，逐条持久化 source result，并复算两次选择结果；最终同时检查
exact-three、hard-gate、capacity 下界和三数据集 source/text hash 零重叠。validator
只读取登记 identity、hash、budget、checkpoint 和输出 artifact，不重新读取 source。
当前实现尚未提交或冻结，因此这些新入口不能用于真实实验。
离线验证为 v23 定向测试 `49/49`、全量 `unittest` `468/468`、298 个 Python
文件内存 AST、implementation authorization scope/self-hash、`git diff --check` 与
敏感值扫描全部通过；锁定环境未安装 `ruff`，本轮未联网安装。

只读校验命令：

```powershell
python -X utf8 -B scripts/42_run_v23_restoration_first.py validate-design
python -X utf8 -B scripts/42_run_v23_restoration_first.py validate-aggregate-df --dataset edgar
python -X utf8 -B scripts/42_run_v23_restoration_first.py validate-aggregate-df --dataset enron
python -X utf8 -B scripts/42_run_v23_restoration_first.py validate-aggregate-df --dataset pubmed
python -X utf8 -B scripts/42_run_v23_restoration_first.py validate-revision-reservation
python -X utf8 -B scripts/42_run_v23_restoration_first.py validate-development-pilot --dataset edgar
python -X utf8 -B scripts/42_run_v23_restoration_first.py validate-development-pilot-group
```

可用 `stage-status` 查看每阶段的 `native`、`carried_forward`、`stale` 或
`not_started`。本轮 runner 提交后的 successor freeze，以及真实 reservation/pilot
执行，都仍需分别取得明确授权；实现授权不允许读取新的 source 或启动 GPU。

`status` 会重算冻结输入与 runtime 身份哈希，在大型 source pool 上可能耗时较长：

```powershell
python -X utf8 -B scripts/42_run_v23_restoration_first.py status
```

执行新的 aggregate-DF 必须使用为单一 dataset/attempt 单独签发的 authorization；
不得复用示例 ID，也不得把一次登录切换或实现授权解释为实验运行授权：

```powershell
python -X utf8 -B scripts/42_run_v23_restoration_first.py aggregate-df `
  --dataset <edgar|enron|pubmed> `
  --authorization <authorized-manifest.json>
```

</details>

<details>
<summary>v20 及更早协议：经典流水线、历史配置与实验记录</summary>

## v20 兼容实现参考（已冻结，非当前执行入口）

v20 曾是成熟的 RAG、matched LLM-only、baseline、defense 与报告实现。以下命令和
配置仅用于理解或复现历史实现，不能作为当前 v24 的下一步，也不能跨协议与上游候选或
结果拼接。旧 MiniLM RAG 已标记为 `superseded` 并封存在
`legacy/abandoned_retriever_20260730/`，禁止续跑、合并、评分或进入论文。

v20 的正式系统为：

- dense：`BAAI/bge-base-en-v1.5`
- sparse：BM25
- strong-RAG：BGE Top-20 + BM25 Top-20 + RRF(`k=60`) + `BAAI/bge-reranker-base` + final Top-5
- Generator 家族：Gemini、Qwen、GPT、Llama
- 第一套冻结主模型：Llama 3.1 70B Instruct；服务商 concrete model ID 为 `meta/llama-3.1-70b-instruct`
- `gemini-2.0-flash` 已在首次正式调用前因 API 不可用解冻，未产生可合并的 v20 正式响应

激活 `(mia_model)` 环境后统一使用 `python`。标准配置入口只有：

- `configs/data_config.yaml`
- `configs/pcv_attack_config.yaml`
- `configs/rag_config.yaml`
- `configs/llm_profiles.yaml`
- `configs/generator_families.yaml`
- `configs/experiment_plan_v20.yaml`
- `configs/canonical_suite_v20_llama.yaml`

先验证既有三数据集 benchmark/query 产物：

```powershell
python -B scripts/verify_v6_3_budget6_formal_artifacts.py `
  --output artifacts/v6_3/audits/budget6_formal_integrity_report_attack_first_rc2.json
```

然后用 Reserve 构建 pseudo-member dev indexes，并执行 API=0 的检索门禁。Reserve
同时承担 Retriever dev 与后续经验 conformal calibration，因此不得描述为“完全独立校准集”：

```powershell
python -B scripts/18_build_retrieval_dev_indexes.py --dataset edgar
python -B scripts/18_build_retrieval_dev_indexes.py --dataset enron
python -B scripts/18_build_retrieval_dev_indexes.py --dataset pubmed
python -B scripts/19_evaluate_retrieval_gate.py
```

`configs/rag_config.yaml` 已冻结 BGE 与 reranker 的 Hugging Face commit SHA；
revision 为空的 dense/hybrid run 会被 canonical 门禁拒绝。只有三个数据集全部通过
Recall、零命中率和隔离门禁后，才构建正式 KB index。当前冻结结果选中
`128 tokens / overlap 32`：

```powershell
python -B scripts/03_build_rag_index.py --dataset enron --retriever-backend hybrid
```

首次 API 前必须运行总预检；它会复核三数据集 split/query/benchmark、Reserve 5/245
角色、正式 index、representative chunks、90,000-request schedule、Generator 身份和
“正式响应仍为 0”，不会调用任何模型 API：

```powershell
python -B scripts/26_validate_v20_preflight.py
```

Llama pilot 必须加独立 `--suite-id llama-3.1-70b-instruct-pilot`，依次采集
dense、BM25、hybrid、matched LLM-only、Oracle 和 Random；不得直接写入正式目录。
在干净 release commit 上配置好 `PCV_VICTIM_*` 后，以下一条 PowerShell 块会按
三数据集完成全部 2,700 次 Pilot 调用：

```powershell
foreach ($dataset in @("edgar", "enron", "pubmed")) {
  $queries = "artifacts/v6_3/query_controls/$dataset/llama-3.1-70b-instruct-pilot/queries.jsonl"
  python -B scripts/10_run_rag_and_llm_only.py --dataset $dataset --victim-profile llama_primary --generator-family llama --retriever-backend dense --queries-path $queries --suite-id llama-3.1-70b-instruct-pilot
  python -B scripts/10_run_rag_and_llm_only.py --dataset $dataset --victim-profile llama_primary --generator-family llama --retriever-backend bm25 --queries-path $queries --suite-id llama-3.1-70b-instruct-pilot
  python -B scripts/10_run_rag_and_llm_only.py --dataset $dataset --victim-profile llama_primary --generator-family llama --retriever-backend hybrid --queries-path $queries --suite-id llama-3.1-70b-instruct-pilot
  python -B scripts/10_run_rag_and_llm_only.py --dataset $dataset --victim-profile llama_primary --generator-family llama --retriever-backend dense --queries-path $queries --suite-id llama-3.1-70b-instruct-pilot --llm-only --skip-rag
  python -B scripts/10_run_rag_and_llm_only.py --dataset $dataset --victim-profile llama_primary --generator-family llama --retriever-backend dense --context-control oracle --queries-path $queries --suite-id llama-3.1-70b-instruct-pilot
  python -B scripts/10_run_rag_and_llm_only.py --dataset $dataset --victim-profile llama_primary --generator-family llama --retriever-backend dense --context-control random --queries-path $queries --suite-id llama-3.1-70b-instruct-pilot
}
```

完成后逐数据集运行：

```powershell
python -B scripts/20_check_generator_pilot.py `
  --dataset enron `
  --suite-id llama-3.1-70b-instruct-pilot `
  --queries-path <该数据集冻结的150-query计划>
```

Retriever 和 Generator 都必须一次只跑一个 cell。RAG index 只能包含
`KB_Member`；`True_Non_Member`、`Reserve`、`Spoof_Seed` 和
`Spoofed_Non_Member` 一律不能进入索引。

所有 v20 主产物按
`{dataset}/{generator_family}/{model_slug}/{retriever_id}/` 隔离；matched
LLM-only 的 Retriever 固定为 `none`。已有响应的 query、benchmark、index、
具体模型版本或 code commit 任一变化，resume 都会在 API 调用前失败。

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

## v20 历史状态（已 superseded）

### 2026-07-31：v20 首次 API 前离线门禁完成

| 维度 | v20 冻结定义 |
|---|---|
| 数据集 | Edgar、Enron、PubMed，各 500 `KB_Member` + 500 `True_Non_Member` + 250 `Reserve` |
| 主 Generator | `meta/llama-3.1-70b-instruct` |
| Retriever | BGE、BM25、`BGE+BM25+RRF+BGE-reranker`；baseline 只跑 BGE |
| 查询预算 | 每 source 固定 3 pair / 6 queries；每正式 cell 7,500 calls |
| Reserve | 5 source 用于 Pilot diagnosis，245 source 用于 Retriever 冻结后的经验 conformal calibration |
| 主矩阵 | 三数据集 × BGE/BM25/hybrid/matched LLM-only = 90,000 calls |
| 机制与 baseline | Oracle/Random 约 3,600 calls；五个 BGE-only baseline 约 30,000 calls |

API=0 的本地验收已经通过：三数据集 BGE Recall 门禁全部通过，选中
`128/32`；macro Recall@5=`0.8487`、macro MRR=`0.7635`。冻结 schedule 含
90,000 个不重复请求；三个 Pilot 计划合计 2,700 calls；正式 Llama 响应仍为 0。
最终代码测试为 306/306 通过，255 个 Python 文件通过 AST 编译，17 个 YAML
文件解析成功。

Conformal 只表述为“Retriever 冻结后的经验非成员校准”，不声称 Reserve 是完全
独立的校准集，也不声称 exchangeability 自动给出严格有限样本保证。主报告保留
source-level AUC、attack advantage、TPR@1%/5% FPR 与 conformal
TPR/FPR@1%/5%；不生成数值型 TPR@0.1% FPR。

> 下方 2026-07-22 及更早内容仅保留为历史进度；与 v20 冲突时，以本节、当前配置和
> `artifacts/v20/release_controls/preflight_report.json` 为准。

### 2026-07-22：v19 顶会协议本地阶段完成（历史）

v19 曾冻结为三数据集、四 Generator、两 Retriever 的 source-level 正式协议；该版本
现已被 v20 supersede，不得用于新实验或与 v20 合并。

早期 Step 01–09 的 4 pair/8 query 产物现仅作为历史证据保留。RC1 后的主协议已统一改为每 source 3 pair/6 条文本唯一 query；正式产物必须按当前配置重新生成。3-pair 主协议仍使用相同的本地 claim validator 硬门禁：

- 原实体 span/边界正确，true/counterfactual claim 只改一个槽位。
- 替换前后实体类型一致且值不同，并维持年份、时长单复数、地点冠词等子类语法。
- claim 是完整英文陈述句，无明显截断、MIME/邮件头污染、异常括号或重复词。
- Q+/Q− 把对应实体替换为 `{ENTITY}` 后完全一致；所有失败都保留 `validation_failure_reason`。

上述门禁、source eligibility、stealth filter、正式 promotion、审计模板和 pilot
预算均可本地完成。当前 attack-first RC2 正式产物的实际 API 调用为 0；最新验收为
302/302 tests、260 个 Python 文件内存编译、15 个 YAML 解析和
`git diff --check` 通过。三数据集完整性报告为
`artifacts/v6_3/audits/budget6_formal_integrity_report_attack_first_rc2.json`。

新 formal RC100/Release200 的本地 AI 预审均为 0 high-risk。该结果允许进入小规模
Reserve/机制 pilot，但不能表述为两位真人盲标或 Cohen’s κ；若论文要主张真人一致性，
仍需另行收集真实标签。正式矩阵只在单 cell pilot 验证检索隔离、输出完整性和成本后
逐个 Generator、逐个 Retriever 扩展。

> 下方 2026-07-20 及更早内容保留为历史进度；与 v19 冲突时以本节、当前配置和 artifact manifest 为准。

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
- 6 个 baseline 已接入统一 harness；其中 MEntA 明确属于 source-level adapted baseline。P1 重跑完成前，现有 baseline 数值不得与新 source-level 主结果混用。

### 2026-07-13：Baseline 与 API 请求可靠性

- MBA 的 proxy-LM 选词阶段已串行化 Hugging Face tokenizer/model 访问，修复 `max_workers>1` 时的 `Already borrowed`。锁在 victim 请求前释放，不影响 RAG/API 并发。
- PCV-MIA 第 10 步与第 12 步全部 baseline 共享「短指数退避 + 长冷却无限重试」语义。超时、SSL EOF、空回答、429/5xx 和网关偶发 403 不再丢弃查询，而是冷却后重试同一请求直到成功。
- 每一次物理重试都重新经过令牌桶，不会绕过 `requests_per_minute`。缺依赖、解析错误等非 API 异常不会无限空等。
- 默认长冷却是 300 秒。若端点长期宕机或授权永久不可用，进程会持续运行并重试；需人工停止时使用 `Ctrl+C`。

## v20 经典流水线（历史实现参考）

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

# Sibling LLM：用于 MEntA/IA/DCMI attacker，以及可选 Spoof
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

`configs/llm_profiles.yaml` 内置以下常用 profile：

```text
openai_api      OpenAI 官方接口，默认模型 gpt-4.1-mini
dashscope_qwen  阿里云 DashScope OpenAI 兼容接口，默认模型 qwen3-235b-a22b
ollama_qwen3_4b 本地 Ollama，固定别名 pcv-qwen3-4b:q4km-8k
```

仓库当前默认 victim active 是 `openai_api`，sibling active 是 `dashscope_qwen`。profile 只决定接口风格和 system prompt；真实的 `base_url`、`model`、`api_key` 仍由 `.env` 中的 `PCV_VICTIM_*` / `PCV_SIBLING_*` 覆盖。

第 10 步必须配置 `PCV_VICTIM_*`。第 04 步只有在 `PCV_ENABLE_SPOOFED_NONMEMBER=true` 时才需要 `PCV_SIBLING_*`。

### 本地 Qwen3-4B sibling（RTX 4060 8GB）

完整操作与门禁命令见
[`docs/ollama_qwen3_4b_sibling_使用说明.md`](docs/ollama_qwen3_4b_sibling_使用说明.md)。

本地攻击侧统一使用 Ollama 的 `qwen3:4b-q4_K_M`。仓库保留云端默认 sibling，
本机只通过 `.env` 选择 `ollama_qwen3_4b`，不会改变 victim Generator 或
`configs/generator_families.yaml`。当前本机安装在 `D:\Ollama`，模型目录为
`D:\Ollama\models`，项目别名实际 ID 冻结为 `39297c75a309`。

安装 Ollama 后执行：

```powershell
ollama pull qwen3:4b-q4_K_M
ollama create pcv-qwen3-4b:q4km-8k -f configs\qwen3_4b_q4km_8k.Modelfile
ollama list
```

Modelfile 固定 `num_ctx=8192`、`temperature=0`、`seed=42`。至少预留 5GB
磁盘；拉取完成后可离线运行。将以下变量设为 Windows 用户环境变量后重启 Ollama：

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "127.0.0.1:11434", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "q8_0", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "10m", "User")
```

本机 `.env` 使用：

```dotenv
PCV_SIBLING_PROFILE=ollama_qwen3_4b
PCV_SIBLING_API_KEY=ollama
PCV_SIBLING_BASE_URL=http://127.0.0.1:11434/v1
PCV_SIBLING_MODEL=pcv-qwen3-4b:q4km-8k
PCV_SIBLING_MODEL_VERSION=ollama:39297c75a309
```

`ollama_qwen3_4b` 显式设置 `requests_per_minute: 0` 和
`request_interval_seconds: 0`：这表示 sibling 不创建令牌桶，也不继承云端的
20 秒间隔；单并发只由 `OLLAMA_NUM_PARALLEL=1` 保证。victim 仍独立使用
`generation.requests_per_minute: 4` 的令牌桶，两者互不影响。

正式生成 MEntA manifest 前先做 30 条功能门禁（每数据集 10 条）和至少 50 次
稳定性门禁。要求 HTTP/JSON 成功率 100%、每条恰好 5 个唯一问题、无 `<think>`
泄漏、provider model ID 精确等于本地别名、热启动 p95≤30 秒；BGE 同驻时还需
`ollama ps` 显示 100% GPU、无 OOM/超时且独显峰值约不超过 7.2GiB。若显存失败，
只允许创建新的 4K 上下文别名并重跑全部门禁，不接受 CPU fallback，也不复用旧
sibling 生成结果。

本机 2026-07-31 实测已通过：三数据集 30/30 功能样本的热启动 p95 分别为
2.462s、1.834s、2.403s；BGE 同驻下 50/50 稳定性样本 p95 为 1.735s，GPU 峰值
3983MiB/8188MiB，`ollama ps` 为 100% GPU、8192 context，无 OOM、超时或 CPU fallback。

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
  scale: formal
  small:
    target_unit: records
    KB_Member: 100
    True_Non_Member: 100
    Spoof_Seed: 100
    Reserve: 100
    per_source_cap: 3
  formal:
    target_unit: sources
    KB_Member: 500
    True_Non_Member: 500
    Spoof_Seed: 0
    Reserve: 250
    per_source_cap: null
```

`source_exclusive: true` 表示同一原始文档的不同 chunk 不会跨 member 和 non-member 分组，避免成员推理实验中的数据污染（近邻泄漏）。

formal 协议的数量单位是 membership source，不是 chunk。source 被选中后保留它的全部 chunk，因此 `per_source_cap: null`；正式 split 只从标签无关的 query-eligible whitelist 中按 seed 42 抽样。`Spoof_Seed: 0` 表示主协议不生成 Spoof 种子。

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
  # 云端 sibling 的 generation fallback；profile 内显式值优先。
  # ollama_qwen3_4b 显式为 0，因此不创建 sibling 令牌桶。
  sibling_requests_per_minute: 4
  max_workers: 4
```

`embedding.dim` 保留是为了兼容旧调用；真实维度来自加载到的 sentence-transformers 模型。

### `configs/pcv_attack_config.yaml`

控制 fact extraction、paired claims、paired queries、stealth filter 和 scoring。

当前默认：

```yaml
fact_extraction:
  max_facts_per_doc: 4
  max_entities_per_doc: 8
  guarantee_min_facts: 1
  min_importance: 0.6
  min_replaceability: 0.6
  min_privacy_specificity: 0.5
  dataset_overrides:
    enron:
      max_facts_per_doc: 8
      max_entities_per_doc: 12
      guarantee_min_facts: 8

paired_claims:
  perturbation_levels: [light]
  max_pairs_per_fact: 1

paired_queries:
  query_types: [diverse_slotted_verification]

stealth_filter:
  embedding_model: sentence-transformers/all-MiniLM-L6-v2
  embedding_local_files_only: true
  embedding_batch_size: 64
  pairs_per_source: 3
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

### v6.3 precision cascade：精确 1,250 停止

v6.3 的正式本地语义门禁只运行 GLiNER2-large；PubMed 额外使用 BioMed
candidate-only veto。bulk 阶段不运行 GLiNER2-base、CPU spaCy、API 或 Retriever。

上游 v3/v4 与 RC1 扫描只作为已冻结的 GLiNER-passed facts 和历史容量证据保留。
当前正式 release 统一使用
`v6_3_attack_first_rc2_budget6_release_v1` 和 3 pair/6 query：

- Edgar、Enron、PubMed 的 whitelist 均恰好包含 1,250 个 source。
- 每数据集均为 3,750 个完整 pair、7,500 条非空且文本唯一 query。
- RC2 只重做确定性反事实、claim validator、source-absence、stealth 和固定预算选择；
  不重新运行 GLiNER、API 或 Retriever。
- 默认 [data_config.yaml](configs/data_config.yaml) 已指向 RC2 release input，避免复现
  时静默回退到旧 RC1。

Enron v4 排序计划和 GPU 扫描已经完成；旧 eligibility checkpoint 与一次性恢复入口
已在仓库瘦身时清理。冻结的 calibration 证据继续保存在
`artifacts/v6_3/semantic_calibration*`，正式 RC2 产物不依赖旧扫描目录。
三数据集 budget-6 formal split 均为 500 KB_Member / 500 True_Non_Member /
250 Reserve；每个数据集均已 promotion 为 1,250 source、3,750 pair、7,500 条
source 内唯一 query。RC2 完整性报告位于
`artifacts/v6_3/audits/budget6_formal_integrity_report_attack_first_rc2.json`。

RC 100 与 Release 200 审计模板位于：

- `artifacts/v6_3/audits/claim_pair_rc_100_attack_first_rc2_formal/`
- `artifacts/v6_3/audits/claim_pair_release_200_attack_first_rc2_formal/`

两轮均按 source/audit ID 排除旧 RC/Release，且新 Release 额外排除新 RC。
本地预审分别为 RC 0 high-risk / 101 needs-review / 199 low-risk，Release
0 high-risk / 219 needs-review / 381 low-risk；needs-review 主要来自开放语义实体、
专名标点和 PubMed 标识符的人工抽查提示，不等于失败。A/B 文件仍为空白，未伪造
人工标签；AI 预审只支持进入小规模机制 pilot，不能据此宣称真人 Cohen’s κ。

budget-6 formal 的本地复现顺序如下：

```powershell
python -B scripts/build_v6_3_budget6_release_inputs.py --input-mode attack_first_rc2 --force
foreach ($dataset in @("edgar", "enron", "pubmed")) {
  python -B scripts/02_split_dataset.py --dataset $dataset --config configs/data_config.yaml --scale formal --force --no-resume
  python -B scripts/05_build_attack_benchmark.py --dataset $dataset --data-config configs/data_config.yaml --force --no-resume
  python -B scripts/promote_eligibility_plan.py --dataset $dataset --data-config configs/data_config.yaml --attack-config configs/pcv_attack_config.yaml --force
}
python -B scripts/verify_v6_3_budget6_formal_artifacts.py `
  --output artifacts/v6_3/audits/budget6_formal_integrity_report_attack_first_rc2.json
```

当前只允许先运行 Enron 的单 cell pilot；不要一次启动四个 Generator 或两个
Retriever，也不要根据正式 member/non-member 测试 AUC 反向调 claim validator。

当前 v6.3 只使用现有编号流水线和现有配置，不再新增入口。激活 `mia_model`
环境后，Enron dense index 的唯一命令是：

```powershell
python -B scripts/03_build_rag_index.py `
  --dataset enron `
  --config configs/rag_config.yaml `
  --retriever-backend dense `
  --force
```

`configs/rag_config.yaml` 已统一指向 `artifacts/v6_3`。不要再使用
`D:\python\anaconda\python.exe`，它是没有 FAISS 的 base 解释器；在
`(mia_model)` 提示符下直接使用 `python`。

### 当前无 API 正式准备

如需有意重建 Step 01–09，三数据集必须逐个运行。以 Enron 为例：

```powershell
python -B scripts/02_split_dataset.py --dataset enron --config configs/data_config.yaml --scale formal --force
python -B scripts/05_build_attack_benchmark.py --dataset enron --data-config configs/data_config.yaml --force
python -B scripts/06_extract_facts.py --dataset enron --config configs/pcv_attack_config.yaml --force
python -B scripts/07_generate_paired_claims.py --dataset enron --config configs/pcv_attack_config.yaml --force
python -B scripts/08_generate_paired_queries.py --dataset enron --config configs/pcv_attack_config.yaml --force
python -B scripts/09_filter_stealth_queries.py --dataset enron --config configs/pcv_attack_config.yaml --force
```

生成双人盲标模板、Enron dense index 和 API-free pilot 预算：

```powershell
python -B scripts/claim_pair_audit.py --dataset enron --claims artifacts/v6_3/paired_claims/enron_paired_claims.jsonl --sample-size 200 --seed 42 --output-dir artifacts/v6_3/audits/claim_pair_release_200_attack_first_rc2_formal
python -B scripts/03_build_rag_index.py --dataset enron --config configs/rag_config.yaml --retriever-backend dense --force
python -B scripts/prepare_single_cell_pilot.py --dataset enron --config configs/rag_config.yaml --generator-id Qwen3.5-397B --retriever-id sentence-transformers/all-MiniLM-L6-v2
```

Edgar/PubMed 将 `--dataset` 和 eligibility 输出目录替换为对应配置路径。上述命令不调用 victim/sibling API；Step 10 及之后必须等真实双人盲标通过。

离线完整性验收：

```powershell
python -B scripts/verify_v6_3_budget6_formal_artifacts.py --artifacts-dir artifacts/v6_3 --output artifacts/v6_3/audits/budget6_formal_integrity_report_attack_first_rc2.json
```

### 通用流水线

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

正式 Step 08 使用 `diverse_slotted_verification`：`true_claim` 保留原文，Sibling
对同一 source 的三个 pair 一次生成三个候选问句，并在 `{ENTITY}` 槽位只生成一次。
Q+/Q− 由本地填入真/假实体，因此槽外必须字节级一致。运行前必须显式冻结
`PCV_SIBLING_MODEL`；manifest 同时绑定 effective profile、实际返回模型、NLI snapshot、
benchmark 与生成协议，身份变化会拒绝 resume。旧逐字查询仅允许用于 shadow 非劣对照。

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

Step 09 从 attack benchmark 按 `source_key` 重新加载原始 chunk。查询与 chunk 统一遮蔽
目标实体后，执行 5-gram containment 与最长连续公共 token 串门禁；embedding 余弦只记录
问句—claim 语义保真度和问句—chunk 检索相关度，不再以“过于相似”为由拒绝查询。
所有拒绝仍按 Q+/Q− 整对共进退。

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
  首次只使用已经冻结的 150-query pilot 验证端点和吞吐，不要直接启动正式矩阵。

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

6 个 baseline 已接入统一 source-level representative-chunk harness：

```text
PCV-MIA（本方法）
RAG-MIA      直接询问 yes/no（地板线，二值分→AUC 退化，主看 Accuracy）
S2MIA(s)     切半 + BLEU(原文, 回答)，移植 IA 官方 mia_utils/s2.py（纯黑盒；s&p 困惑度作附录）
MBA          proxy-LM 高难词遮蔽 + 填空填对率，移植 IA 官方 mia_utils/mba.py
IA           summary + 30问 + 同源检索器区分度筛选(代替 ElectraScorer) + 一致率
DCMI         反义词扰动差分（base=BLEU 重叠），对齐官方 perturb.py
MEntA        冻结 summary+5 个自然问题 + 本地 DeBERTa entailment/refusal 均值（source-level adapted）
```

忠实度审计与实验条件对齐见 `src/baselines/BASELINES.md`；确定性逻辑由 `tests/test_baseline_adapters.py` 与 `tests/test_menta.py` 背书。IA/DCMI 需 runtime attacker LLM；MEntA 必须先运行 `scripts/download_frozen_menta_nli.py` 和 `scripts/27_prepare_menta_inputs.py --dataset <dataset>`，正式 runner 不会联网生成 query 或补模型。

MEntA query manifest 和 baseline experiment identity 都绑定无密钥的 sibling profile
快照及 hash（含本地模型摘要、endpoint、请求参数和限速配置）。partial/frozen
resume 遇到 profile/model digest、provider model ID 或逐行 identity 漂移会直接拒绝，
避免云端与本地 sibling 产物混用。

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

### 捷径与泄漏诊断

正式诊断统一由 `scripts/analyze_shortcut_controls.py`、机制分析和 matched
LLM-only 对照完成，不再保留临时 `_diag_*` 脚本。

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
  victim_harness.py  6 个 baseline 的统一 RAG/API 执行、重试、聚合与输出接口
  menta.py           MEntA query/NLI/refusal runtime 与冻结产物校验

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

当前分支最新验收结果为 8/8 个 entity-policy 定向测试与 457/457 个全量单元测试
通过。测试过程没有 GPU、真实 API、victim 或 Retriever 调用；测试输出中的
timeout/retry 文本来自 mock 路径，不是真实外部调用。

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

baseline：6 个（RAG-MIA / S2MIA / MBA / IA / DCMI / MEntA）统一接入第 12 步 harness，见 `src/baselines/BASELINES.md`。MEntA 固定每 source 5 次 victim 调用，query 由 sibling 离线生成并冻结，回答由 `tasksource/deberta-base-long-nli@04dcf11f...99d5` 本地打分；它使用共享 representative chunk，必须标注为 source-level adapted baseline，不冒充官方数据集复现。注：S2/MBA 移植自第三方复现、DCMI 的 base 为 BLEU 重叠近似，均已诚实标注。

## 安全与复现注意事项

- 不要提交 `.env`、API key、私有数据集或大型生成产物。
- `configs/llm_profiles.yaml` 只保存环境变量名和非敏感默认配置，不写真实密钥。
- RAG 知识库只能由 `KB_Member` 构建。
- `True_Non_Member`、`Spoof_Seed`、`Reserve`、`Spoofed_Non_Member` 不能进入 index（`Reserve` 仅进 benchmark 当校准组，且评估时排除）。
- attack benchmark 会保存 `.sha256`，不要手动修改后继续复用旧 hash。
- 修改 fact extraction、query generation、retrieval、generation 或 scoring 后，应从受影响阶段重跑。
- 正式报告前检查各 manifest 的 `created_at`、`config_snapshot`、`config_hash`，避免新旧 artifacts 混用。

## 研究记录

`研究记录/`、根目录 `notes.md` 和 `task_plan.md` 是本地研究管理材料，不是公开运行
接口，也不应仅因 README 更新而提交到远端。公开 README 只保留能够由当前代码、
配置和机器可读 manifest 复核的协议状态，不复制 authorization ID、私有 artifact、
内部审计内容或历史逐次日志。

当前阶段定位是：v23 runtime 已实现，Edgar/Enron aggregate-DF 已通过，PubMed
aggregate-DF 与后续 selector/pilot 尚待独立授权；formal、victim、Retriever 和
evaluation 均未启动。v20 及更早研究结果只作历史证据，不能写入 v23 主结果。

## v6.3 RC1 四-pair容量诊断（历史，已 superseded）

旧 RC100 发现重复的截断、邮件/表格污染和实体误型后，RC1 本地回放曾以
4 pair/8 query 评估容量：

| Dataset | RC1 eligible sources | 目标 | 状态 |
|---|---:|---:|---|
| Edgar | 952 | 1,250 | 不足 |
| Enron | 694（含旧 terminal wave 可回收 9 个） | 1,250 | 不足 |
| PubMed | 1,479 | 1,250 | 容量通过 |

该诊断证明 4-pair 门槛会使 Enron 明显偏向事实丰富的超长邮件。旧 extension
checkpoint 只保留作历史证据，不得再 resume；当前主协议以下一节的 3/6 为准。

## v6.3 RC1 主预算调整：3 pair / 6 queries（2026-07-28）

RC1 容量实验表明，Enron 大量完整邮件天然只有 2–3 个可通过硬门禁的独立事实。
继续强制 4 pair 会明显偏向超长邮件，并增加 source selection bias。主实验因此统一
改为每 source 3 个完整 Q+/Q− pair，即 6 条文本唯一 query；validator、实体类型、
semantic resolver 和 stealth 阈值均不降低。4 pair/8 queries 保留为高预算消融，
2 pair/4 queries 保留为低预算消融。

当前纯本地重选结果如下；整个重选过程 GLiNER/API/Retriever 调用均为 0：

| Dataset | 3-pair eligible | 目标 | 状态 |
|---|---:|---:|---|
| Edgar | 1,250 | 1,250 | cap=5 + 定向 cap=8 完成 |
| Enron | 1,308 | 1,250 | 按 source 顺序精确保留 1,250 |
| PubMed | 1,820 | 1,250 | 容量通过 |

Enron budget-6 plan 的 retained boundary 为 source index 2,361，最终产物严格包含
1,250 source、3,750 pair、7,500 query。whitelist hash 为
`949a6fb41f9620f12dd40d701e5fe3ec53150eb8980762e677cd062c5f1e7e3c`。

旧 Enron 4-pair extension checkpoint 已完成其容量诊断使命；由于当前配置已切换为
3 pair，其旧产物和一次性入口已经清理，不得再 resume。

Edgar 的定向 cap=8 计划已经完成；旧 checkpoint 和一次性恢复入口已经清理。

计划 hash 为
`8fc79a76cadac0e779d82b3e72a41bb5c057c5513421963ba34efc5ee8f9644d`；
该入口 API/Retriever 调用固定为 0。加入此入口后的完整验证为 276/276 tests 通过。

Edgar 定向补跑已完成：2 个 wave 后新增并保留 77 个 upgrade source，最终严格包含
1,250 source、3,750 pair、7,500 条 source 内文本唯一 query；容量状态为
`sufficient`。最终 whitelist hash 为
`9229525cfa9d57953b02fd1d17c363e44238428f27df61e46e81366e35bff99a`，
输出文件 hash、source/pair/query 数量、Q+/Q− 完整性和查询文本唯一性均已复核。
Edgar 不再需要补跑。

### attack-first RC2 budget-6 formal 重建结果

- release protocol：`v6_3_attack_first_rc2_budget6_release_v1`。
- release whitelist hash：
  - Edgar：
    `bd859976d9bce18c2d4ca287fccae135691ea180ce84d7d65d46c053ca8836dc`
  - Enron：
    `7705cd27f16d33a33442c8bf82ee6db6fcc65b863ae8b380631ed214d69fa327`
  - PubMed：
    `6a145697be6e50f68755cd38a5a25820b5dbf759a5fafce4fa1acd709de36968`
- formal benchmark rows：Edgar 80,181；Enron 6,434；PubMed 17,028。
- promotion：每数据集 1,250 source / 3,750 facts / 3,750 claims /
  7,500 queries；source-exclusive、Q+/Q− 完整、query ID/文本 source 内唯一、
  引用与所有 output hash 均通过。
- 新 RC100/Release200 已与旧轮次及彼此隔离；本地预审分别为
  0/101/199 与 0/219/381（high-risk/needs-review/low-risk）。
- 最新本地验收为 302/302 tests、260 个 Python 文件内存编译、15 个 YAML 解析、
  formal integrity 和 `git diff --check` 全部通过。

Enron all-MiniLM-L6-v2 dense index 已使用 `mia_model` 环境中的 FAISS 构建完成：
500 个 `KB_Member` source、2,611 个文档块，禁止组重叠为 0；输入、docstore 和
index hash 均匹配，存储后端为 `faiss.IndexFlatIP`。首个单 cell pilot 计划已经生成
但尚未调用 API：

```powershell
python -B scripts\prepare_single_cell_pilot.py `
  --dataset enron `
  --config configs\rag_config.yaml `
  --queries-path artifacts\v6_3\stealth_filtered_queries\enron_paired_queries.jsonl `
  --output-dir artifacts\v6_3\pilots\enron_qwen3_5_397b_minilm_rc2 `
  --pilot-id enron_qwen3_5_397b_minilm_rc2 `
  --generator-id Qwen3.5-397B `
  --retriever-id sentence-transformers/all-MiniLM-L6-v2
```

该计划含 10 member、10 true non-member、5 reserve，150 条查询；RAG 150 次、
matched LLM-only 150 次，共 300 次潜在调用。价格在具体 endpoint/provider 未冻结
前保持 `unavailable`，不能用猜测价格生成费用数字。

</details>

### v24 Luna-only development alternative (2026-09-09)

The v24 development path now includes an optional GPT-5.6 Luna-only Stage A. Luna returns only `evidence_text`, `true_claim`, `original_entity`, `canonical_fact`, and supporting context; it must not return offsets. Code recovers all offsets by unique exact matching in the frozen source, and rejects any model-supplied location field. `original_entity` must be an exact span inside `true_claim`; supporting evidence can provide canonical-fact context only and cannot define another attack slot. Stage B remains the existing independent replacement plus shared question skeleton path, with Q+/Q- instantiated by code.

The historical 18-source comparison remains a fact-completeness diagnostic. The new development-only A/B starts from a fresh 30-source source-first manifest, uses identical source order for `GLiNER2+Luna` and `Luna-only`, and keeps zero-candidate sources. Candidate exact overlap is diagnostic only. Repeatability is summarized primarily by source-level `>=3 usable facts` and `>=3 eligible pairs` stability. No promotion thresholds are frozen, and no formal split, PVS, three-pairs/source, or six-queries/source contract changes.

### 2026-09-19：V24 主线合并与 nfcorpus 首 cell

本次合并纳入 V24 Luna-only 构造/补充入口、Gemma 服务器兼容和首 cell 配置。正式输入采用 `reconciled_20260919`；nfcorpus 主评估为 2000 source、6000 pair、12000 query，Reserve 不发主查询，BGE dense index 仅含 1000 Member。服务器 profile 为 `gemma2_2b_server`，使用 `PCV_VICTIM_*`，完整 BF16 部署由用户确认；版本别名不是独立核验的 HF commit。`system_prompt_as_user` 沿用本地 Gemma 的指令前缀格式，PVS 为 `S+ * R- - A-`。

主线独立工作树位于 `artifacts/v24/worktrees/main`，用于保留原目录未提交的旧协议及论文工作。正式运行前须在该干净工作树完成只读 dry-run；原目录的脏工作树不能直接运行正式 cell。长任务由用户启动，默认恢复断点，每 200 条保存；当前配置串行、请求间隔 20 秒。数据/权重不纳入 Git，不能仅凭代码 checkout 推断这些本地产物已存在。
