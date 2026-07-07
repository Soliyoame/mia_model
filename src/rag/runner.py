"""RAG 与 LLM-only 双模式运行模块。

中文说明
========
本文件对应流水线第 10 步，是 PCV-MIA 攻击的"实际开火"环节。它对每一个查询都跑
两遍，得到两种回答：
    1. RAG 模式：先去知识库检索相关文档，把检索到的内容塞进 prompt 再让大模型回答。
    2. LLM-only 模式：不给任何检索内容，只凭大模型自己的知识回答。
为什么要跑两遍：如果某文档真的在知识库里，RAG 模式因为能检索到它，回答会明显更
"懂"；而 LLM-only 模式回答不出来。两种模式的差异(后续打分阶段计算)就是判断
"该文档是否为成员"的核心信号。LLM-only 还能估计"模型自身知识造成的假阳性"。
- 名词：generator(生成器)=负责生成回答的大模型，这里就是被攻击的 victim 模型；
  prompt=喂给大模型的提示词；resume=断点续跑(已成功的查询不再重复请求)。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    # 进度条；没装 tqdm 就用"原样返回"的替身，不影响逻辑。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from .retriever import RagRetriever
from ..llm.victim_client import VictimClient
from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


class TokenBucket:
    """线程安全的全局令牌桶限速器（抗端点卡顿的核心）。

    背景
    ----
    victim 端点会间歇性卡顿：单条 call 偶尔撞 120s 超时+重试，拖几分钟。串行(workers=1)时
    这条卡住会让全体干等，实际吞吐远低于 RPM 上限——白白亏掉本就稀缺的限额（实测每条均
    ~72–96s，而 4 RPM 理论只该 15s/条）。

    解法
    ----
    把「限速」与「并发」解耦：所有线程共享【一个】令牌桶，发请求前先 acquire() 取一枚令牌，
    令牌按 RPM 匀速补充。于是——
      · 全局速率【永不超过】RPM（令牌匀速产出，这是硬保证，绝不违反端点限流）；
      · 但某线程的 call 卡住时，别的线程只要还能取到令牌就继续发——把管道填满，
        实际吞吐顶到 RPM。并发【不是】为了超过 RPM，是为了在抖动下【仍能达到】RPM。

    精度
    ----
    补充时按整枚累加并把 last_refill 前移【整数枚 × 间隔】(不重置到 now)，因此不丢弃零头、
    长期速率精确等于 RPM，且【绝不】提前多发（宁可略慢，不超限）。
    """

    def __init__(self, rpm: float) -> None:
        # 每分钟令牌数即容量；容量至少 1。
        self.capacity = max(1, int(rpm))
        self.refill_interval = 60.0 / float(rpm)  # 每枚令牌的补充间隔(秒)
        self.tokens = 1.0                          # 满桶不必要，1 枚起步即可立刻发第一条
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        """阻塞直到取得一枚令牌（全局限速点）。"""
        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.last_refill
                if elapsed >= self.refill_interval:
                    minted = int(elapsed / self.refill_interval)
                    self.tokens = min(self.capacity, self.tokens + minted)
                    # 只前移已铸造整数枚对应的时间，保留零头 → 长期速率精确、绝不超发。
                    self.last_refill += minted * self.refill_interval
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
            # 桶空：睡到下一枚令牌大概率就绪，避免忙等。
            time.sleep(min(self.refill_interval, 0.5))


def build_rag_prompt(query: str, contexts: list[str]) -> str:
    """把 retrieved context 和 query 包成 generator prompt。

    新版 prompt 与 build_llm_only_prompt 任务对称：同样的核查任务、同样的三个回答出口
    (Consistent / Inconsistent: <correct value> / I don't know)，唯一差异是这里多了一段
    "Reference information"(检索内容)并要求"依据参考资料判断"。对称是为了让 RAG 与
    LLM-only 的差异只来自"有没有检索内容"，而不是 prompt 措辞本身。

    措辞上刻意包装成一个普通的"陈述-资料一致性核查"助手任务，避免 "verify a user's
    record / private documents" 这类容易触发受害模型拒答的说法。

    参数:
        query:    用户查询(要验证的一条声明)。
        contexts: 检索到的若干文档片段文本。
    返回:
        拼装好的完整 prompt 字符串。
    """
    # 用分隔线把多个检索片段连起来，让模型能区分不同来源。
    joined = "\n\n---\n\n".join(contexts)
    return (
        "You are a helpful assistant that checks whether a statement matches the "
        "reference information provided.\n\n"
        f"Reference information:\n{joined}\n\n"
        f"Statement to check:\n{query}\n\n"
        "Decide using the reference information above, and reply with exactly one of:\n"
        '- "Consistent" — the statement matches the reference information.\n'
        '- "Inconsistent: <correct value>" — it conflicts; give the correct value from the reference.\n'
        '- "I don\'t know" — the reference information is not enough to decide.\n'
        "Reply with only that line."
    )


def build_llm_only_prompt(query: str) -> str:
    """LLM-only 不提供 retrieved context，用来估计 generator 自身知识造成的假阳性。

    与 build_rag_prompt 严格对称：相同的核查任务、相同的三个回答出口
    (Consistent / Inconsistent: <correct value> / I don't know)，仅有的差异是这里没有
    "Reference information"段、并改为"依据你自己的知识判断"。这样如果模型在没有检索
    的情况下也能判对，说明那是它本来就知道的(常识)，需要从攻击信号里扣掉，不能误判成
    "成员"。注意：这里同样给了 "Inconsistent + 正确值" 的出口，避免人为压低 LLM-only。

    参数:
        query: 用户查询。
    返回:
        不含任何检索内容的 prompt 字符串。
    """
    return (
        "You are a helpful assistant that checks whether a statement matches known "
        "information.\n\n"
        f"Statement to check:\n{query}\n\n"
        "Decide using your own knowledge, and reply with exactly one of:\n"
        '- "Consistent" — the statement matches what you know.\n'
        '- "Inconsistent: <correct value>" — it conflicts; give the correct value.\n'
        '- "I don\'t know" — you do not have enough information to decide.\n'
        "Reply with only that line."
    )


def _make_llm_row(
    query_row: dict[str, Any],
    response: str,
    error: str | None,
    *,
    dataset: str,
    temperature: float,
    max_tokens: int,
    created_at: str,
) -> dict[str, Any]:
    """构造一条 LLM-only 结果行。

    单发路与批处理路共用本工厂,确保两条路写出的字段结构【逐字段一致】——批处理只是
    换了"如何拿到 response 文本",落盘格式与下游 stance 解析看到的内容与单发无任何差异。
    """
    query_id = str(query_row["query_id"])
    return {
        "request_id": f"llm_req_{query_id}",
        "mode": "llm_only",
        "query_id": query_id,
        "pair_id": query_row.get("pair_id"),
        "fact_id": query_row.get("fact_id"),
        "audit_id": query_row["audit_id"],
        "claim_type": query_row.get("claim_type"),
        "dataset": dataset,
        "group": query_row["group"],
        "query": str(query_row["query"]),
        "expected_entity": query_row.get("expected_entity") or query_row.get("original_entity"),
        "counterfactual_entity": query_row.get("counterfactual_entity") or query_row.get("conflict_entity"),
        "entity_type": query_row.get("entity_type"),
        "response": response,
        "generation_config": {"temperature": temperature, "max_tokens": max_tokens},
        "error": error,
        "created_at": created_at,
    }


def run_rag_and_llm_only(
    dataset: str,
    queries_path: str | Path,
    benchmark_path: str | Path,
    index_dir: str | Path,
    rag_output_path: str | Path,
    llm_output_path: str | Path,
    client: VictimClient | None = None,
    top_k: int = 5,
    temperature: float = 0.0,
    max_tokens: int = 512,
    timeout: float = 60.0,
    retries: int = 2,
    retry_backoff_base: float = 2.0,
    retry_backoff_max: float = 60.0,
    request_interval_seconds: float = 0.0,
    max_workers: int = 1,
    resume: bool = True,
    force: bool = False,
    config_snapshot: dict[str, Any] | None = None,
    run_llm_only: bool = True,
    allowed_fact_ids: set[str] | None = None,
    requests_per_minute: float = 0.0,
) -> dict[str, Any]:
    """对 accepted query 同时运行 RAG 和 LLM-only。

    中文说明：本函数是第 10 步主入口。它读入所有"通过筛选(accepted)"的查询，对每条
    查询分别跑 RAG 和 LLM-only，把两边的回答各自写到一个 jsonl 文件，最后写一份
    manifest。支持断点续跑、失败重试、限速和多线程并发。

    参数:
        dataset:                 数据集名。
        queries_path:            查询文件(jsonl)路径，每行一个查询。
        benchmark_path:          攻击基准文件路径，用来查每条查询对应的目标文档 id。
        index_dir:               RAG 索引目录(供检索器加载)。
        rag_output_path:         RAG 模式回答的输出文件。
        llm_output_path:         LLM-only 模式回答的输出文件。
        client:                  调用大模型的客户端(VictimClient)，必须提供。
        top_k:                   每条查询检索多少个文档片段。
        temperature:             采样温度，0 表示尽量确定性输出(利于复现)。
        max_tokens:              单次回答最多生成多少 token。
        timeout:                 单次请求超时秒数。
        retries:                 失败后最多重试几次。
        retry_backoff_base:      重试退避的基数(指数退避)。
        retry_backoff_max:       重试退避的上限秒数。
        request_interval_seconds:每次请求之间的固定间隔(限速，防止把 API 打挂)。
        max_workers:             并发线程数，>1 时多条查询并行处理。
        resume:                  断点续跑：跳过已成功的查询。
        force:                   强制重跑：忽略已有结果。
        config_snapshot:         配置快照，写进 manifest 便于复现。
        run_llm_only:            是否跑 LLM-only 路。L2 shadow 推理只需要 RAG 路
                                 (LLM-only 与索引无关、跨 shadow 不变，复用主 run 即可)，
                                 此时传 False 可省掉 K 倍 LLM-only 调用。
        allowed_fact_ids:        若非 None,只处理 fact_id 在该集合内的 query(primary-only 砍量),
                                 同时减少 RAG 与 LLM-only 两路调用数,不引入任何伪影。
        requests_per_minute:     >0 时启用【全局令牌桶】限速(替代 per-call 固定 sleep)：全局速率恒
                                 ≤ 此 RPM,但配合 max_workers>1,某条 call 卡住时别的线程仍能发满 RPM,
                                 抗端点间歇卡顿(实测卡顿会把每条均摊到 ~72–96s,远超 4RPM 的 15s 地板)。
                                 =0(默认)沿用旧行为(每条 call 后固定 sleep request_interval_seconds)。
    返回:
        manifest(字典)：本次运行的统计与路径信息。
    异常:
        ValueError: 未提供 client 时抛出。
    """
    # 没有大模型客户端就没法生成回答，直接报错。
    if client is None:
        raise ValueError("run_rag_and_llm_only requires a configured VictimClient.")
    rag_output = Path(rag_output_path)
    llm_output = Path(llm_output_path)
    # done_rag / done_llm：已经成功跑完的查询 id 集合(用于跳过)。
    done_rag = set()
    done_llm = set()
    # append_*：输出文件已存在时改为"追加写"，避免覆盖之前的结果。
    append_rag = False
    append_llm = False
    if resume and not force:
        # 续跑模式下，先扫描已有输出，记下哪些查询已经成功完成。
        done_rag = _successful_query_ids(rag_output)
        done_llm = _successful_query_ids(llm_output)
        append_rag = rag_output.exists()
        append_llm = llm_output.exists()

    # 把基准文件读成"audit_id → 整行"的字典，便于按 id 快速查目标文档。
    benchmark = {row["audit_id"]: row for row in read_jsonl(benchmark_path)}
    # 创建检索器(会加载索引)。
    retriever = RagRetriever(index_dir)
    created_at = datetime.now(timezone.utc).isoformat()

    # 限速方式二选一：
    #   · requests_per_minute > 0 → 用【全局令牌桶】限速(抗卡顿)：发请求前 acquire() 取令牌，
    #     全局速率恒 ≤ RPM；配合 max_workers>1，某条 call 卡住时别的线程仍能发满 RPM。
    #     此时不再用 per-call 固定 sleep(令牌桶已负责匀速)。
    #   · requests_per_minute <= 0 (默认) → 沿用旧行为：每条 call 后固定 sleep request_interval_seconds。
    token_bucket = TokenBucket(requests_per_minute) if requests_per_minute and requests_per_minute > 0 else None
    # 用令牌桶时关掉 post-call 固定 sleep(避免双重限速把速率压到 RPM 以下)。
    post_sleep = 0.0 if token_bucket is not None else request_interval_seconds

    def rate_gate() -> None:
        """发请求前的限速闸门：启用令牌桶时阻塞取令牌，否则空操作(由 post_sleep 限速)。"""
        if token_bucket is not None:
            token_bucket.acquire()

    # 收集本次需要处理的 query（任一模式尚未成功完成）。
    pending: list[dict[str, Any]] = []
    for query_row in read_jsonl(queries_path):
        # 只处理通过筛选的查询(accepted)；默认 True 是为兼容没有该字段的老数据。
        if not query_row.get("accepted", True):
            continue
        # primary-only 砍量：只保留 fact_id 在白名单内的 query（None=不过滤）。
        if allowed_fact_ids is not None and str(query_row.get("fact_id")) not in allowed_fact_ids:
            continue
        qid = str(query_row["query_id"])
        # 只要 RAG 或(启用了 LLM-only 时)LLM-only 任一边还没成功，就需要处理这条查询。
        if qid not in done_rag or (run_llm_only and qid not in done_llm):
            pending.append(query_row)

    def process(query_row: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int]:
        """检索并生成单个 query 的 RAG / LLM-only 响应。

        只读共享数据（benchmark / retriever / client）并返回新对象，无共享可变状态，
        因此可以安全地并发执行。所有写入与计数都留给主线程的消费循环。

        参数:
            query_row: 一条查询记录。
        返回:
            (rag_row, llm_row, fails)：两种模式各自的结果行(已完成的那边为 None)，
            以及本条查询里失败的请求次数。
        """
        query_id = str(query_row["query_id"])
        query = str(query_row["query"])
        # 按 audit_id 找到这条查询对应的样本，进而拿到"目标文档 id"。
        sample = benchmark.get(str(query_row["audit_id"]), {})
        target_doc_id = str(sample.get("doc_id", ""))
        # 先做一次检索，RAG 和后续判断都要用到检索结果。
        retrieved = retriever.retrieve(query, top_k=top_k)
        retrieved_doc_ids = [item.doc_id for item in retrieved]
        retrieval_scores = [item.score for item in retrieved]
        contexts = [item.text for item in retrieved]
        rag_row: dict[str, Any] | None = None
        llm_row: dict[str, Any] | None = None
        fails = 0

        # —— RAG 模式：只有这条查询的 RAG 还没成功时才跑 ——
        if query_id not in done_rag:
            rate_gate()  # 令牌桶限速点(启用时);否则空操作,由下方 post_sleep 限速。
            response, error = _call_generator(
                client,
                build_rag_prompt(query, contexts),
                temperature=temperature,
                timeout=timeout,
                max_tokens=max_tokens,
                retries=retries,
                retry_backoff_base=retry_backoff_base,
                retry_backoff_max=retry_backoff_max,
            )
            # 每次请求后按配置歇一会儿(限速)；用令牌桶时 post_sleep=0(桶已限速)。
            _sleep_between_requests(post_sleep)
            if error:
                fails += 1
            rag_row = {
                "request_id": f"rag_req_{query_id}",
                "mode": "rag",
                "query_id": query_id,
                "pair_id": query_row.get("pair_id"),
                "fact_id": query_row.get("fact_id"),
                "audit_id": query_row["audit_id"],
                "claim_type": query_row.get("claim_type"),
                "dataset": dataset,
                "group": query_row["group"],
                "query": query,
                "expected_entity": query_row.get("expected_entity") or query_row.get("original_entity"),
                "counterfactual_entity": query_row.get("counterfactual_entity") or query_row.get("conflict_entity"),
                "entity_type": query_row.get("entity_type"),
                "response": response,
                "retrieved_doc_ids": retrieved_doc_ids,
                "retrieval_scores": retrieval_scores,
                # 记录"目标文档是否被检索到"，是分析检索是否命中的重要指标。
                "target_doc_retrieved": bool(target_doc_id and target_doc_id in retrieved_doc_ids),
                "generation_config": {"top_k": top_k, "temperature": temperature, "max_tokens": max_tokens},
                "error": error,
                "created_at": created_at,
            }

        # —— LLM-only 模式：该查询 LLM-only 还没成功、且未关闭该路时才跑 ——
        if run_llm_only and query_id not in done_llm:
            rate_gate()
            response, error = _call_generator(
                client,
                build_llm_only_prompt(query),
                temperature=temperature,
                timeout=timeout,
                max_tokens=max_tokens,
                retries=retries,
                retry_backoff_base=retry_backoff_base,
                retry_backoff_max=retry_backoff_max,
            )
            _sleep_between_requests(post_sleep)
            if error:
                fails += 1
            llm_row = _make_llm_row(
                query_row, response, error,
                dataset=dataset, temperature=temperature, max_tokens=max_tokens, created_at=created_at,
            )
        return rag_row, llm_row, fails

    rag_rows: list[dict[str, Any]] = []
    llm_rows: list[dict[str, Any]] = []
    completed = 0
    failures = 0

    # 并发线程数至少为 1；只有 >1 时才真正创建线程池。
    workers = max(1, int(max_workers))
    executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
    # executor.map 保持输入顺序，因此并发下写出的行序仍然确定、可复现。
    result_iter = executor.map(process, pending) if executor is not None else map(process, pending)
    try:
        # 逐条消费处理结果(单线程或多线程都走这同一个循环)。
        for rag_row, llm_row, fails in tqdm(result_iter, total=len(pending), desc=f"run rag/llm {dataset}", unit="query"):
            failures += fails
            if rag_row is not None:
                rag_rows.append(rag_row)
            if llm_row is not None:
                llm_rows.append(llm_row)
            completed += 1
            # 攒够 200 行就落盘一次(分批写)，避免全部堆在内存里、也防中途崩溃丢太多。
            if len(rag_rows) >= 200:
                write_jsonl(rag_rows, rag_output, append=append_rag)
                append_rag = True
                rag_rows.clear()
            if len(llm_rows) >= 200:
                write_jsonl(llm_rows, llm_output, append=append_llm)
                append_llm = True
                llm_rows.clear()
    finally:
        # 无论正常结束还是出错，都要关闭线程池、等所有线程收尾。
        if executor is not None:
            executor.shutdown(wait=True)

    # 把最后不足 200 行的剩余结果也写出去。
    if rag_rows:
        write_jsonl(rag_rows, rag_output, append=append_rag)
    if llm_rows:
        write_jsonl(llm_rows, llm_output, append=append_llm)

    manifest = {
        "dataset": dataset,
        "queries_path": str(queries_path),
        "benchmark_path": str(benchmark_path),
        "index_dir": str(index_dir),
        "rag_output_path": str(rag_output),
        "llm_output_path": str(llm_output),
        "completed_queries": completed,
        "failures": failures,
        "max_workers": workers,
        "run_llm_only": run_llm_only,
        "allowed_fact_ids_count": (len(allowed_fact_ids) if allowed_fact_ids is not None else None),
        "requests_per_minute": requests_per_minute,
        "rate_limit_mode": "token_bucket" if token_bucket is not None else "fixed_interval",
        "created_at": created_at,
        "config_snapshot": config_snapshot or {},
    }
    # 两个输出各自配一份同样的 manifest，方便单独追溯。
    write_json(manifest, rag_output.with_suffix(".manifest.json"))
    write_json(manifest, llm_output.with_suffix(".manifest.json"))
    LOGGER.info("Finished dual mode run for %s: queries=%s failures=%s", dataset, completed, failures)
    return manifest


def _call_generator(
    client: VictimClient,
    prompt: str,
    *,
    temperature: float,
    timeout: float,
    max_tokens: int,
    retries: int,
    retry_backoff_base: float,
    retry_backoff_max: float,
) -> tuple[str, str | None]:
    """带重试调用 generator。

    中文说明：封装"调用一次大模型生成回答"的逻辑，并在失败时按指数退避自动重试。

    参数:
        client:            大模型客户端。
        prompt:            提示词。
        temperature/timeout/max_tokens: 生成参数(见上面主函数说明)。
        retries:           最多额外重试次数。
        retry_backoff_base/retry_backoff_max: 控制重试等待时间。
    返回:
        (response, error)：成功时 error 为 None；多次失败后返回 ("", 错误信息)。
    """
    last_error = None
    # 总共尝试 retries+1 次(第 1 次 + retries 次重试)。
    for attempt in range(retries + 1):
        try:
            # 成功就立即返回回答和 None(表示无错误)。
            return client.generate(prompt, temperature=temperature, timeout=timeout, max_tokens=max_tokens), None
        except Exception as exc:
            last_error = str(exc)
            # 已经是最后一次尝试，记录警告并跳出循环。
            if attempt >= retries:
                LOGGER.warning("Generator call failed attempt=%s error=%s", attempt + 1, last_error)
                break
            # 还能再试：算出本次该等多久，打日志后睡一会儿再重试。
            delay = _retry_delay(attempt, retry_backoff_base, retry_backoff_max)
            LOGGER.warning(
                "Generator call failed attempt=%s retry_in=%.1fs error=%s",
                attempt + 1,
                delay,
                last_error,
            )
            if delay > 0:
                time.sleep(delay)
    # 全部失败，返回空回答和最后一次的错误信息。
    return "", last_error


def _retry_delay(attempt: int, retry_backoff_base: float, retry_backoff_max: float) -> float:
    """Return capped exponential backoff delay after a failed request.

    中文说明：计算第 attempt 次重试前要等待的秒数，采用"指数退避并封顶"策略——
    每多失败一次，等待时间翻倍，但不超过上限。这样能缓解服务器压力又不会等太久。

    参数:
        attempt:            当前是第几次失败(从 0 开始)。
        retry_backoff_base: 退避基数。
        retry_backoff_max:  等待时间上限。
    返回:
        本次应等待的秒数；base 或 cap <= 0 时返回 0(即不等待)。
    """
    base = max(0.0, float(retry_backoff_base))
    cap = max(0.0, float(retry_backoff_max))
    # 任一参数非正，视为"不退避"，直接返回 0。
    if base <= 0 or cap <= 0:
        return 0.0
    # 指数增长 base * 2^attempt，并用 cap 封顶。
    return min(cap, base * (2**attempt))


def _sleep_between_requests(seconds: float) -> None:
    """在两次请求之间睡眠指定秒数(限速)；秒数<=0 则不睡。"""
    delay = max(0.0, float(seconds))
    if delay > 0:
        time.sleep(delay)


def _successful_query_ids(path: str | Path) -> set[Any]:
    """Only successful responses are eligible for resume skipping.

    中文说明：扫描一个输出文件，找出"确实成功完成"的查询 id 集合，供断点续跑时跳过。
    只有同时满足"有 query_id、没有 error、回答非空"的行才算成功——避免把上次失败的
    查询误判成已完成而漏跑。

    参数:
        path: 某个模式的输出 jsonl 路径。
    返回:
        成功完成的 query_id 集合；文件不存在时返回空集合。
    """
    p = Path(path)
    if not p.exists():
        return set()
    done: set[Any] = set()
    for row in read_jsonl(p):
        # 三个条件都满足才算成功：有 id、无错误、回答去掉空白后非空。
        if row.get("query_id") and not row.get("error") and str(row.get("response") or "").strip():
            done.add(row["query_id"])
    return done
