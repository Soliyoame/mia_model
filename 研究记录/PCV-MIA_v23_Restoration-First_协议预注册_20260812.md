# PCV-MIA v23 Restoration-First 协议预注册（design r6）

## 1. 状态、权限与规范优先级

- 协议版本：`pcv-mia-v23`。
- 方法版本：`pcv-restoration-first-v23`。
- 设计规范：`pcv-restoration-first-v23-design-r6`。
- 当前状态：`design_preregistered_runtime_not_implemented`。
- 独立输出根：`artifacts/v23/`；本轮不创建该目录或任何实验 artifact。

`configs/restoration_first_v23.yaml` 是 selector、证据分区、门禁、split 与权限边界的机器可读规范，本文给出研究解释。若二者出现歧义，runtime 实现必须停止并创建新 design revision，不能在实现阶段自行选择一种解释。design manifest 只绑定本设计；未来 executable protocol manifest 必须另行绑定实现代码、commit、runtime bundle 与 consumed-source ledger tip。

本轮授权仅覆盖协议制定，不覆盖 runtime 实现、pilot、GPU 长任务、模型下载、API、victim、Retriever、提交或推送。冻结配置中的 `false` 不得原地改成 `true`。实现授权使用不依赖 runtime hash 的 `implementation_authorization`；runtime bundle 冻结后的每次实际执行另用 `run_authorization`，未列明的 stage、dataset、cell、wave 或调用数默认拒绝。

## 2. 研究问题、威胁模型与估计量

v23 测试：攻击者给出一个只腐化实体槽的验证请求后，目标 RAG 是否会因目标 source 存在于知识库而检索到相关证据、判定腐化命题不一致并恢复原实体。目标不是让错误实体替换“尽量自然”，因此不计算 counterfactual naturalness，不使用自然性阈值、学习排序或加权 utility。

攻击者针对一个已知候选 source 判断其是否属于目标 RAG 知识库。攻击者持有该 source 的完整文本、由不含 membership/downstream 信号的冻结 selector 得到的原事实和原实体、公开协议以及目标 RAG 的黑盒文本查询接口；看不到 membership/split、index 内容、Retriever 文档/分数/排名、victim logits 或内部状态，也不能写 index。每个 source 对 dense、BM25、hybrid 三个 RAG backend 各固定发送 3 pair × Q+/Q-=6 个非自适应 query；matched LLM-only 对同一 source 只生成一组全局共享的6个 response，供三个 backend 的 context-gain 对照共同引用，不能重复生成三组。因此每个正式 source 的 victim generation 总数唯一为24：18个RAG加6个共享 LLM-only。攻击者只观察最终 victim response body 或 transport error，不能在观察响应后增加预算、改 query、换 pair 或删 source。

P0 估计量是：**在预注册 selector 判为 eligible 的 source 条件下，source-level RAG-only restoration score 对 `KB_Member` 与 `True_Non_Member` 的区分性能**。每个 source 是一个统计单位；chunk 只用于候选抽取、检索与 query 构造。每个 eligible source 恰好贡献 3 个不同 fact signature 的 pair，每 pair固定 Q+/Q-，共 6 个 query。论文必须同时报告各数据集 frozen-pool coverage、eligible-source rate、拒绝原因和被条件化的 source 范围，不能把 P0 外推为全部文档上的无条件攻击成功率。

matched LLM-only 仅在 selection 和 split 冻结后作机制对照。selection 禁止读取 membership、split/group、victim/LLM-only response、Retriever 输出/排名、attack score/AUC，以及 v22 r1-r3 calibration labels、thresholds 和 context-passed IDs。

## 3. 与 v22 的继承、重建和隔离

v23 只绑定并只读复用 v22 的三套 passed source pool、source order、processed 文件、source-pool SQLite、完整 source text/hash、固定最多 5 个 chunk、实体策略/抽取代码 hash，以及 `fastino/gliner2-base-v1@f5b2ec...` snapshot。design manifest 的冻结上游集合不再通过章节推断，而是 YAML 中显式排序的23个 `{path, sha256}` 对象；其 canonical list SHA-256 固定为 `59578397e9c998dc576d5d9fe4b692a9a3ba87d0d5a6f704afb7c5a4aa4ed03e`。v22 r1-r3 的标签、阈值、utility/naturalness/context-usability 分数、旧 eligible 判定和 15,092 条 r3 context-passed 集合均是 `superseded_goal_mismatch`，不能成为 v23 的候选全集或选择证据。

v23 不复用任何 pre-r3/r3 candidate artifact。它从绑定的 v22 source-pool database 在 v23 identity 下 fresh re-extract：遍历已经冻结的最多 5 个 chunk，保留绑定 pattern registry 在 v22 score/top-k 前发出的全部 P0 类型候选，并补充冻结 GLiNER2 在分数不低于 0.65 时发出的 P0 类型候选。GLiNER2 只负责候选 emission、粗类型 routing 和完整 source 的 filler inventory，不提供 recoverability、自然性、排序或 eligibility 分数。所有候选重新生成 `source_hash`、`normalized_text_hash`、`chunk_hash`、`sentence_hash`、span、relation/fact signature 与 v23 pair identity。

## 4. 证据分区与跨 revision 消耗

每数据集使用在 v23 设计前已冻结、且不读取 label/victim/Retriever/AUC 的 v22 SHA-256 source order：

1. 前 1,000 个 source 是 development cohort，永久排除 audit 与 formal。
2. 每个 design/runtime revision 从 development 后的冻结顺序中排除 prior-revision ledger snapshot，取接下来的 250 个未消耗 source 作为该 revision 的 fresh-audit reserve；初始 revision 恰为下标 1000-1249。不足 250 则该 revision 无法启动。在 development capacity 裁决之前原子登记全部 250 个，随后运行同一 selector 并按冻结顺序取前 100 个 eligible source；不足 100 则失败。无论 eligible 与否，250 个均永久排除 formal。
3. formal domain 是排除 formal-scan 启动时 prior-revision ledger snapshot 中所有 development、audit reserve、human/diagnostic viewed 与 earlier formal-scan viewed source 后的剩余冻结顺序。

跨全部 v23 revisions 共用 append-only hash-chain ledger：`artifacts/v23/governance/consumed_source_ledger.jsonl`。首个 runtime bundle 冻结时一次性建立具名 genesis与genesis anchor。development、audit reserve 与 formal scan 分别按配置中的 canonical reservation batch 登记；这里的“批次原子”专指**内容可见性原子**：独占锁下逐行 append/flush/fsync，整批行与 no-overwrite completion anchor 全部 durable 后才允许读取批内任何 source 内容。中途崩溃只能在相同 batch identity 下验证前缀并 append 缺失后缀，不能读取内容或回滚已写行；前缀不一致、重复 index 或 tip 漂移均 fail closed。checkpoint 记录 input/output tip；不修改 ledger 的 stage 复用 input tip/anchor，旧 checkpoint 的 output tip只须是当前有效 tip 的祖先，不要求等于后来增长的最新 tip。

每份 `run_authorization` 只能绑定一个 `authorized_stage`、一个 attempt 与一个 execution unit，并必须声明 `protocol_revision_id`、`attempt_id` 与 `expected_prior_ledger_tip_sha256`。预算种类只能是 `none|sources|waves|calls` 之一；各 stage 的唯一 charge 单位在 YAML 固定，每个 source/wave/call 执行前必须先在 append-only budget journal 原子扣1。达到上限后，在任何内容读取、reservation 或外部调用前 fail closed。三个数据集治理顺序固定为 EDGAR -> Enron -> PubMed；每个 revision 对同一个 prior ledger tip 同时冻结三套 audit reserve，依次登记三批250 source，只有 group completion anchor durable 后才允许读取 development 或 reserve 内容。formal scan 同样按该顺序串行运行，每个 reservation batch 恰好一个 source，收集到第2,250个 eligible source 后立即停止，不得再登记或读取后续 source。

该 ledger 的信任模型是防止正常协议执行、崩溃恢复和误操作造成的静默漂移；**不声称仅靠同一可写文件系统上的 hash chain 能抵抗攻击者把 ledger、anchor、checkpoint 和项目记录全部恶意重写**。在此信任模型下，ledger 缺失、截断、重排、partial trailing row、tip/anchor/checkpoint/authorization 不一致均 fail closed。每个 revision 在启动 formal scan 前冻结 prior-consumption snapshot；本轮随后扫描的 source 先登记再读取，但不会把已经进入本轮 selected set 的 source 动态踢出。若本轮失败，它们对未来 revision 永久排除。任何新增 consumed source 后，下一 revision 在进入 audit/formal 前必须重新计算容量门禁。

## 5. Selector 的唯一实现规则

### 5.1 规范化、坐标和身份

规范化固定为 Unicode NFKC -> Python `str.casefold()` -> 每段 Unicode whitespace 折叠为一个 ASCII 空格 -> strip。span 使用相对未修改 supporting sentence 的 Python Unicode codepoint 半开区间 `[start, end)`，并要求 `sentence[start:end] == original_entity`。canonical JSON 固定 UTF-8、`ensure_ascii=false`、key 排序、紧凑分隔符、禁止 NaN、无尾换行，再取小写 SHA-256。relation/fact/counterfactual/pair/split/reserve snapshot 的 hash payload 均在 YAML 中以具名 JSON object schema、字段类型与常量 `kind` 完整列出，并提供 normalization/span/canonical-JSON golden vectors，禁止使用位置数组或隐式字符串 join 替代。

完整 source、chunk 与 supporting sentence 另保留原字符串 UTF-8 hash；`normalized_text_hash` 对上述规范化文本取 hash。句子/命题按绑定 regex `[^.!?\n]+(?:[.!?]+|$)` 切分，换行始终形成边界，trim 后重算 span。relation cue、mail header、未解析指代、generic role、token regex 与 stopword 全部逐项写入 YAML；regex 使用 Python Unicode + IGNORECASE。

`fact_signature` 保守定义为 dataset、source key 与 sentence hash 的 canonical hash，因此同一句内最多选一个 P0 pair。`relation_signature` 把精确目标 span 替换为唯一 `[ENTITY_SLOT]` 后再规范化并绑定 dataset/source/effective type。counterfactual ID 与 pair ID 的精确具名字段见 YAML。

candidate emission 固定按 `chunk_rank`、proposition 原始起点、pattern registry index/regex match 顺序遍历；GLiNER span 与候选 span 使用同一 codepoint 坐标，其 overlap 是交集长度除以较短 span 长度。先按 score/type 过滤，再用冻结 tuple 选单模型 prediction。rule/model 冲突先解析 effective type，再调用一次绑定 semantic subtype；最终 dedup key 包含 subtype，survivor 的 source priority、registry index、model score、declared type 与 raw surface 顺序均在 YAML 固定。pre-gate 不设 cap。

### 5.2 Counterfactual 构造

替代池仅来自绑定 `entity_type_policy_v21_r1.yaml` 中与 deterministic semantic subtype 对应的冻结候选表；subtype 未映射即拒绝，不调用 perturbation fallback。规范化重复值保留 YAML subtype list 中最早出现的 surface（再以 raw UTF-8 破同位置），再剔除原值、完整 source 中有边界出现的值、空值、粗类型/表面格式不兼容值及破坏外部 `a/an` 框架的值，最后按 counterfactual ID 与规范化值升序取最多 3 个。

最低构造有效性只要求：精确单槽替换、prefix/suffix 逐字不变、替代值非空、完整 source absence、粗类型与表面格式兼容、括号配平不变及外部 `a/an` 首字母类别兼容。它不声称替换在语义或自然性上最优，也不调用 LLM 裁判。

### 5.3 Restoration hard gates

Grounded fact stability 使用保守可重算代理：原句必须在完整 source 中出现，包含冻结 relation cue，句末为 `.` 或 `;`，ASCII alphanumeric token 数为 8-80，且不是邮件头，不含冻结未解析指代词，原实体也不能是冻结 generic value/role。通过门禁只表示满足预注册构造条件，不等于人工确认语义正确。

Original-entity recoverability 在完整 source 的所有 proposition 上联合 pattern registry 与 GLiNER2 建立同类型 filler inventory。目标 relation signature 必须恰好出现一次、对应 filler 必须等于原实体、不得有其他同类型 filler 产生相同 signature。GLiNER 分数只作 0.65 emission threshold，不进入排序。

Non-entity retrieval anchor 从 masked true claim 删除目标/替代实体与 P0 router 识别的其他 P0 entity spans 后，按冻结 token/stopword 规则至少保留 4 个不同 content token、1 个 relation cue 与 1 个 source-specific token。structured diagnostic extractor 是完全独立机制：其 spans/literals 不参与 P0 removal、cue、DF/IDF、rank 或 eligibility。source-specific 定义为同数据集完整冻结 pool 的 source-document DF 满足 `100 * df <= N`；IDF 为 `ln((N+1)/(df+1))`。这是使用未标注完整 pool 的 transductive statistic，论文必须披露，不能称 formal 文本完全未触碰；这里不运行 Retriever。

完整池 DF 是 ledger 的唯一显式内容读取例外：runtime bundle 冻结后、任何 selector/source reservation 前，受控 `aggregate_df_precomputation` 读取每个绑定 pool 的完整 source，仅按同一 normalization/tokenization 累加 document-boolean token DF。它只能输出按 token 排序的 `{token, document_frequency}` 与绑定输入/代码的 manifest，禁止输出 source key/hash、逐 source token、文本或 membership 字段；因此不把全池登记 consumed。任何禁止字段、输入漂移或重算 hash 不一致均 fail closed。该 transductive aggregate 必须在论文中披露，不能描述为 formal pool 从未被机器读取。

Verification discriminativeness 要求 target signature 只有原实体这一个 correction candidate，且替代实体在完整 source 中无有边界出现。Query self-containment 要求 relation cue 前有非停用 content token、masked claim 恰有一个 slot、且冻结 unresolved-reference regex 零命中。正式响应 schema 全局固定为 `stance` 与 `correction_entity`；不得用逐 pair 输出可解析性返工样本。

### 5.4 排序与 source eligibility

所有 P0 hard-gate-passed pair 使用 YAML 中完全展开的 17 项升序 tuple。负号字段表示原计数降序，所有计数、DF/IDF 与 hash 均由独立 validator 从冻结输入重算。排序后执行一次 stable greedy：仅接受尚未使用的 fact signature，且同一规范化原实体累计少于 2；恰好取到 3 pair 时 source eligible，否则 source ineligible 且不输出 P0 pair。structured diagnostic 使用独立 extractor/manifest/denominator，不能提供 removal span、cue、P0 pair，也不能改变 development、audit、formal 容量或 early-stop。

selector 的序列化输入不再依赖 forbidden-field blacklist，而采用递归 exact allowlist：source/chunk/row 的必需字段、可选字段（空集）与类型逐项冻结，未知字段一律拒绝；GLiNER predictions 只能由绑定 runtime 内部产生，不能从输入 payload 注入。旧 blacklist 仅作 defense-in-depth 日志检查，不构成安全边界。

## 6. Development 容量门禁

development 固定扫描每数据集 1,000 source。必须满足重跑 hash 一致、所有跨分区 source/text hash overlap 为 0、独立重算 hard-gate violation 为 0，并且每个 eligible source 恰好 3 pair。

容量不再使用 Wilson 比例下界或统一 `eligible >= 500`。由于 development 是在结果未知前冻结的 SHA-256 无放回排列前缀，使用固定样本的超几何一侧 95% 总容量下界。对 `N=完整冻结 pool source 数`、`n=1000`、观察 eligible 数 `x`：

```text
K_L = min {K in [0,N] : Hypergeom.sf(x - 1; N, K, n) >= 0.05}
c   = ledger 中该数据集除 development 外已消耗的互异 source 数
formal_lower = max(0, K_L - x - c)
gate: formal_lower >= 2250
```

每个 revision 在 capacity gate 前已 write-ahead 登记其250-source audit reserve，因此首轮 `c=250`，不存在 `c=0` 的合规时序。最小观察值与边界校验为：EDGAR `x>=623`（`K_L=3125`, lower=2252）；Enron `x>=89`（`K_L=2618`, lower=2279）；PubMed `x>=66`（`K_L=2574`, lower=2258）。这是依赖冻结 hash permutation 的 design-based 容量下界；若 source order 生成身份、pool、reserve snapshot 或 ledger 漂移，推断无效并 fail closed。门禁失败必须创建新 design revision，不能查看 AUC 后改规则。

## 7. Fresh Human Blind Audit

development 全部 passed 后，才可对当前 revision 已预登记的 250-source reserve 执行相同 selector，并选前 100 个 eligible source，每 source 3 pair，共 900 pair。失败后的新 revision 从 prior ledger 排除后再取下一批250个，不能复用旧 reserve。初始 revision 唯一对应各数据集冻结 order 下标 1000-1249；后续 revision 统一引用排除 prior ledger 后的定义。两名真人 reviewer 分别对全部 900 pair 独立盲审；包内可见完整 source、true/counterfactual claim 与构造字段，但隐藏显式 dataset 名、source identity、split/membership、selector rank/features、v22 标签、另一 reviewer 标签及全部 downstream 输出。这里准确称“source identity 与协议特征盲审”，不声称完整文本模态一定隐藏 dataset。opaque ID 与 packet order 使用 revision audit secret 的 HMAC；secret 在 packet 前提交 hash、裁决完成后才揭示。两名 reviewer 与第三方 adjudicator 必须是三个不同 pseudonymous identity，分别绑定 packet/schema/label-file hash。任一 reviewer 缺失、重复或非法标签均使 audit incomplete 并 fail closed。

六个维度均为 `pass|fail|uncertain`。全维度 pass 才是 overall accept，任一 fail 为 reject，其余为 uncertain。两人 overall label 不同或任一 uncertain 的 pair 交第三方用同一 schema 裁决。pre-adjudication raw agreement 与三分类 unweighted Cohen's kappa 均以 900 为分母；kappa 分母为零时失败。裁决后整体 acceptance >=0.90、uncertain <=0.05、每数据集 300 pair acceptance >=0.85，且每数据集 100 source 中至少 80% 的 3 pair 全部 accepted；另要求 raw agreement >=0.90、kappa >=0.80。Assistant-only 标签不能写作真人审核或 kappa 证据。

## 8. Formal Scan、Split 与下游顺序

runtime/test -> commit/runtime bundle freeze -> aggregate DF precomputation -> revision reserve write-ahead -> development capacity -> fresh blind audit -> formal scan -> source-exclusive split -> Reserve-only shadow -> release finalize -> Luna query -> main index/Retriever -> matched RAG/LLM-only victim -> parsing/scoring/source-level evaluation，严格逐门禁串行。

formal scan 按启动时冻结的 prior-consumption exclusion snapshot 与 v22 source order 运行，在每数据集收集恰好 2,250 个 eligible source 后早停；所有扫描过的 source 立即写 ledger，但只影响未来 revision。先冻结完整 selected set，再计算与 membership 无关的 split key，按 key 升序将前 1,000 分配为 `KB_Member`、后 1,000 为 `True_Non_Member`、最后 250 为 `Reserve`。split manifest 必须绑定 selected-set、design/runtime、commit、ledger tip 与完整 key list hash；split 后禁止重跑 selector 改变集合。主 index 只能含 `KB_Member`，isolated shadow index 只能含 `Reserve`。

Luna 仅把已冻结 Q+ true claim / Q- counterfactual claim 各映射成一个自包含中性验证问题，不生成或选择 counterfactual。配置冻结精确 prompt、输入/输出 object schema、`temperature=0`、单次 transport attempt、零语义重试、query validator 与 query-plan 顺序；任一缺失/非法 query 原样记失败并阻断所有 Retriever/victim run cell，不得再生或返工。response parser 对完整 UTF-8 响应执行单一 RFC8259 JSON object 解析，只允许精确字段 `stance` 与 `correction_entity`：`supported|insufficient` 时 correction 必须为 null，`contradicted` 时必须为非空 string；额外字段、markdown fence、重复 key 或外围文本均 invalid。

main index 只含 `KB_Member`，按冻结 BGE tokenizer 以128 token/32 overlap分块；formal run cells 为 dense、BM25、hybrid，top-k=5，hybrid 参数、model revision 与 tie-break 全在配置固定。每个 index/Retriever contract 必须绑定 split、source/chunk list、模型/tokenizer snapshot、库版本、参数、代码与文件 hash。Gemma victim 的模型 snapshot、tokenizer、CUDA precision、依赖版本、精确 RAG/LLM-only prompt 与 greedy decoding manifest 必须在调用前冻结；一次 cell 只尝试一次，timeout/OOM/transport error 保留为 missing=`-0.5`。matched LLM-only 与 RAG 唯一变化是是否提供按 rank 排列的 context；其恢复成功或失败不得回头删样本。

P0 outcome 对每个 source、每个 RAG backend 的6个 response 独立固定计分。Q+：`supported=1`、`contradicted=-1`、`insufficient=-0.5`；Q-：`contradicted` 且 correction entity 经同一规范化后精确等于原实体为1，否定但 correction 非原实体为0.5，`supported=-1`，`insufficient=-0.5`。缺失、错误、不可解析或 schema-invalid cell 保留并计 `-0.5`，不得删 source 或用其他 cell 插补。pair PVS 为同一 backend 内 Q+ 与 Q- 之和，`source_pvs(dataset, backend, source)` 为同一 backend 内冻结3 pair的等权均值。

主指标按 dense、BM25、hybrid 三个 backend 分别计算：每个 backend 在每数据集冻结的1,000 member与1,000 true non-member source 上计算 source-level ROC AUC，tie 给半分；每个 backend 的 macro 是其三数据集 AUC 算术均值。禁止为主指标跨 backend 平均、拼接或池化 source score。95% CI 使用 NumPy `Generator(PCG64(42))`，source key 升序、固定六 membership cell顺序、每 repetition/cell 恰抽 1,000 个 `int64` index，重复10,000次；所有 backend 复用同一冻结 index tensor。分位数固定为排序后的 type-7 linear 2.5%/97.5%，RNG 与 quantile 均有 golden vector。逐 backend/逐数据集和逐 backend macro 报 AUC/CI；低 FPR 只逐 backend/逐数据集报告 TPR@1% 与 TPR@0.1%，禁止 pooled cross-dataset 或 cross-backend主指标。Reserve 不进入主指标，LLM-only/context gain 仅作诊断。

### 8.1 Design r5 canonical closure

为消除 r4 reader-test 发现的跨章节歧义，以下规则对本预注册前文的概括性措辞具有规范优先级，精确字段仍以 r5 YAML 为准：

1. design manifest 的冻结上游集合是 YAML 中显式排序的23个 `{path, sha256}` 对象，不再从章节位置推断；该列表 canonical SHA-256 为 `59578397e9c998dc576d5d9fe4b692a9a3ba87d0d5a6f704afb7c5a4aa4ed03e`。
2. 每份 run authorization 只绑定一个 stage、一个 attempt 与一个 execution unit。预算只允许 `none|sources|waves|calls`，每次操作前在 append-only budget journal 先扣1；达到上限后，在内容读取、reservation或外部调用前拒绝执行。genesis/no-ledger-mutation stage 均有合法 anchor/checkpoint 表示。
3. 数据集治理顺序固定为 EDGAR -> Enron -> PubMed。一个 revision 的三套 audit reserve 从同一 prior ledger tip冻结，按该顺序登记三批250 source，group completion durable后才可读内容。formal scan逐数据集串行，每次只登记一个 source，达到第2,250个 eligible后不得再登记、读取或评估后续 source。
4. DF rows、selected pair rows、audit packet/labels/result、formal selected rows、split rows、release rows、query rows及retrieval rows均有固定路径、exact schema、顺序、canonical JSONL编码和完整文件SHA-256。release固定为三数据集×2,250 source×3 pair=20,250行，是 Luna 的唯一上游；Luna只对member和true non-member生成36,000条query，Reserve不调用。
5. 最低构造gate绑定冻结的entity-policy parent type与已hash的 `machine_format_compatible` callable；`a/an` frame、重叠P0 span合并顺序均为确定算法。Luna relation cue取claim首个regex match，schema canonical JSON与prompt逐字替换顺序固定；新增P0 entity校验复用同一冻结rule+GLiNER pipeline。
6. 检索算法固定为BGE snapshot pooling/L2-normalized float32/FAISS `IndexFlatIP`、明确regex/k1/b/IDF的BM25，以及固定RRF和cross-encoder输入/截断/batch/precision的hybrid；Gemma固定为 `google/gemma-2-2b-it@9b78bb...`、BF16、batch=1、left padding和冻结chat-template编码。实际库版本、snapshot文件hash与golden vectors必须在首调前进入runtime bundle，不得看结果后调整。
7. 每个正式source固定三个RAG backend各6次，加一组全局共享的6次LLM-only，共24次victim generation；整套为144,000次。bootstrap只生成一次 `10000×6×1000` little-endian int64 PCG64 index tensor，dense/BM25/hybrid与共享LLM-only全部复用，不得重置或继续消费RNG。

### 8.2 Design r6 bounded closure

r5 独立 reader-test 给出 `REQUEST_CHANGES`。r6 只修复该轮确认的5个实质闭环问题；fact extraction、Restoration hard gates、3-pair selector、容量公式和人工审计门槛均不变：

1. `source_pvs(dataset, backend, source)` 只使用同一 backend 的6个RAG response。dense、BM25、hybrid分别报告逐数据集AUC/CI/低FPR与各自macro，禁止跨backend主指标聚合。
2. aggregate DF 对每个 runtime bundle/dataset 只允许一次有预算的完整池读取。development、audit、formal等后续selector stage只验证输入identity与已落盘DF rows/manifest的完整文件hash，不得重新读取全池；任何重算必须成为新的显式授权 aggregate-DF attempt。
3. 首个runtime bundle与ledger genesis使用不含`runtime_bundle_sha256`/`protocol_revision_id`的单次bootstrap authorization和独立bootstrap attempt/checkpoint；bundle产生后才创建普通protocol revision与run authorization。fresh audit按每个实际reserve source selector evaluation在读取前扣费，最多250 source/dataset，不只对最终100个packet source计费。
4. canonical链显式绑定：formal selected-pair files -> audit packet/reviewer/adjudicator/final-label manifests -> split -> shadow gate -> release -> query plan -> retrieval manifests -> 12个response manifests（144,000 rows）-> evaluation input -> parsed/source-score rows -> evaluation manifest。每个数据文件均由完整文件SHA-256绑定，未绑定或hash漂移fail closed。
5. BM25 query terms先去重，再按Python规范化token字典序排序，并严格按该顺序做浮点累加；禁止直接迭代Python `set`。

## 9. Runtime 必须通过的 fail-closed 测试

1. 递归 enforcing source/chunk/row exact allowlist，拒绝所有未知、嵌套注入或类型漂移；blacklist 只作附加检查。
2. 对三种 membership unit、source/normalized text/chunk/sentence hash、codepoint span 与 canonical JSON 做 golden tests。
3. 对 fresh extraction、GLiNER routing 职责、counterfactual pool/filter/order 与禁止 fallback 做 golden tests。
4. 对 aggregate DF 的禁止逐 source 输出、所有 hard gate、DF/IDF、17 项 rank tuple、stable greedy 3-pair 与 structured diagnostic 隔离逐项重算。
5. 对超几何公式、三个最小 `x` 边界和 ledger 消耗增加后的容量下降做精确整数测试。
6. 对 revision-specific reserve snapshot、capacity 前内容可见性原子 write-ahead、ledger genesis/hash chain/fsync/anchor/checkpoint/recovery、跨 revision exclusion 与信任模型内的丢失/截断/重写 fail closed 做测试。
7. 对 900-row blind schema、所有分母、kappa、裁决及 missing/duplicate labels 做测试。
8. 对 formal selected-set-before-split、2,250 分配、source/hash 零 overlap 与主/shadow index allowlist 做测试。
9. resume 前重算全部绑定 hash；漂移拒绝复用；partial/failed/superseded 保留，`--force` 产生新 attempt/revision identity。
10. 对 query/parser/index/Retriever/victim/evaluation manifest schema、逐backend P0六cell映射、缺失/不可解析保守计分、逐backend 3-pair source mean、tie-aware AUC、PCG64 draw/type-7 CI 与低 FPR threshold 做 golden tests；prior gate 或对应 authorization 未满足时，所有后续 stage 均拒绝，selection manifest 外部调用数恒为0。
11. 对 aggregate-DF 单次读取/后续仅hash验证、runtime bootstrap authorization/attempt/checkpoint、fresh-audit实际扫描扣费、BM25有序累加及完整artifact hash链做fail-closed回归测试。

## 10. 当前唯一下一步

design r6 限定范围无上下文 reader test 已于2026-08-13判定`PASS`：r5的5个阻断项全部闭合，且fact extraction与Restoration hard gates未受r6修改。design manifest生成后设计阶段结束。当前唯一下一步是等待用户单独授权实现v23 runtime与定向测试；该授权仍不包含development pilot、GPU、API、victim、Retriever、提交或推送。
