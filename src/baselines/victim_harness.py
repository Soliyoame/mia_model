"""Baseline 受害查询 harness —— 把 6 个 RAG-MIA baseline 接到本项目同一套基础设施。

中文说明
========
对应"baseline 对照"的真实执行层。核心思想:**共享流水线、只换攻击层**——所有 baseline
都用同一个 KB 索引(RagRetriever)、同一个受害模型(VictimClient)、同一批目标 chunk
(kb_member=成员 / true_non_member=非成员)、同一套指标(summarize_membership_scores),
唯一差异是每个 baseline 自己的「①发什么 query ②怎么打分」。

6 个 baseline(参考实现/出处见 src/baselines/BASELINES.md):
  - RAG-MIA   : 直接问"在不在上下文" yes/no(二值分,AUC 会退化,见 BASELINES.md)。1 次 victim/目标。
  - S2MIA(s)  : 按字符切半→前半段当 query 让 RAG 复述→BLEU(完整原文, 回答)。纯黑盒。1 次/目标。
  - MBA       : proxy LM 按预测难度挑高难词遮蔽→让 RAG 填空→填对率。proxy LM 仅离线选词。1 次/目标。
  - IA        : attacker 生成 summary+N 问→同源检索器筛 top_k 高区分度问题→生成标准答案→
                逐个问 victim→一致率(λ_unk 罚)。~top_k victim + (2+top_k) attacker/目标(贵)。
  - DCMI      : 差分校准——base(原文) − base(扰动文),base=S2(s) 同口径 BLEU 重叠,扰动=反义词
                替换;成员在扰动下掉得更多。2 次 victim + 1 次 attacker/目标。
  - MEntA     : 离线冻结 summary+5 个自然问题→逐个问 victim→本地 DeBERTa NLI 蕴含/拒答分。5 次/目标。

IA / DCMI 需要一个独立于 victim 的 runtime attacker LLM(用 sibling profile);
MEntA 的 sibling 仅在离线 query 准备阶段使用。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
from statistics import mean
from typing import Any, Callable

import numpy as np

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..evaluation.metrics import summarize_membership_scores
from ..llm.victim_client import VictimClient
from ..rag.retriever import RagRetriever
from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger

from .MBA.mba_highdiff import MBAHighDiff
from .RAG_MIA.rag_mia_reference import RAGMIA
from .S2MIA.s2mia_reference import S2
from .ia_shadow import load_source_bundle

LOGGER = get_logger(__name__)


def is_retryable_api_error(exc: Exception) -> bool:
    """仅识别值得等待后重试的 API/网络错误,避免对缺依赖或代码异常空等。"""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    message = str(exc).lower()
    markers = (
        "empty_response",
        "timed out",
        "timeout",
        "urlopen error",
        "connection reset",
        "connection aborted",
        "connection refused",
        "remote end closed",
        "unexpected_eof",
        "eof occurred",
        "temporarily unavailable",
        "http 403",
        "authorization failed",
        "http 408",
        "http 425",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "http 520",
        "http 522",
        "http 524",
    )
    return any(marker in message for marker in markers)


# ============================================================
# 通用 RAG 作答(还原"RAG 系统拿用户 query 检索后作答"的真实行为)
# ============================================================
def build_generic_rag_prompt(query: str, contexts: list[str]) -> str:
    """标准 RAG prompt:把检索到的上下文 + 用户 query 拼起来让模型作答。

    注意:这里**不**用 PCV-MIA 的"一致性核查"包装——各 baseline 有自己的 query 格式
    (填空/续写/yes-no),只需通用 RAG 外壳即可。
    """
    joined = "\n\n---\n\n".join(contexts)
    return (
        "Context information is below.\n"
        "---------------------\n"
        f"{joined}\n"
        "---------------------\n"
        "Given the context information, answer the query.\n"
        f"Query: {query}\nAnswer:"
    )


def resolve_attacker_rate_limits(
    generation_config: dict[str, Any],
    attacker_profile: dict[str, Any] | None,
    *,
    attacker_role: str,
    victim_requests_per_minute: float,
    victim_request_interval_seconds: float,
) -> tuple[float, float]:
    """解析 attacker 限速；profile 中显式的 0 表示禁用本地限速。"""

    if attacker_role == "victim":
        return victim_requests_per_minute, victim_request_interval_seconds
    if attacker_role != "sibling":
        raise ValueError(f"Unsupported attacker role: {attacker_role}")

    profile_rpm = (
        attacker_profile.get("requests_per_minute")
        if attacker_profile is not None
        else None
    )
    requests_per_minute = float(
        generation_config.get(
            "sibling_requests_per_minute",
            victim_requests_per_minute,
        )
        if profile_rpm is None
        else profile_rpm
    )
    profile_interval = (
        attacker_profile.get("request_interval_seconds")
        if attacker_profile is not None
        else None
    )
    request_interval_seconds = float(
        victim_request_interval_seconds
        if profile_interval is None
        else profile_interval
    )
    if requests_per_minute < 0 or request_interval_seconds < 0:
        raise ValueError("Attacker rate limits must be non-negative")
    return requests_per_minute, request_interval_seconds


@dataclass
class Services:
    """提供给各 baseline 适配器的"服务":检索作答、attacker 调用、向量相似度。"""

    retriever: RagRetriever
    victim: VictimClient
    attacker_chat: Callable[[str], str] | None = None  # IA/DCMI 用;None=没配 attacker
    top_k: int = 5
    temperature: float = 0.0
    max_tokens: int = 512
    timeout: float = 60.0
    request_interval_seconds: float = 0.0  # 每次 victim 调用后限速睡眠
    attacker_request_interval_seconds: float | None = None
    # 重试退避:吸收瞬时 HTTP 524/5xx/网络抖动(对齐第 10 步 runner 的做法)。
    retries: int = 3
    retry_backoff_base: float = 2.0
    retry_backoff_max: float = 30.0
    # 短重试耗尽后,API/网络错误进入长冷却并重试同一请求,直到成功。
    retry_until_success: bool = True
    retry_cooldown_seconds: float = 300.0
    victim_calls: int = 0
    attacker_calls: int = 0
    _embedder: Any = field(default=None, repr=False)
    # 令牌桶(抗端点卡顿,复用 src/rag/runner.py 的 TokenBucket):发 victim/attacker 请求前
    # acquire() 取一枚令牌,全局速率恒 ≤ RPM。None=不启用,回退到 request_interval_seconds
    # 固定 sleep。victim/attacker 各一只桶;若 attacker 复用 victim 端点(同一个 key),二者
    # 传入【同一只】桶,把两路调用合并计入该 key 的 RPM 限额。
    victim_bucket: Any = None
    attacker_bucket: Any = None
    menta_runtime: Any = None
    dataset: str | None = None
    ia_shadow_manifest_dir: str | Path | None = None
    # 并发下保护调用计数自增(victim_calls/attacker_calls)的锁。
    _count_lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)
    _scope_local: Any = field(default_factory=threading.local, repr=False, compare=False)

    def begin_scope(self, target: dict[str, Any] | None = None) -> None:
        """开始一个目标的调用计数作用域；线程池下各目标互不串扰。"""
        self._scope_local.victim_calls = 0
        self._scope_local.attacker_calls = 0
        self._scope_local.target = dict(target or {})
        self._scope_local.diagnostics = {}

    def scope_counts(self) -> tuple[int, int]:
        return (
            int(getattr(self._scope_local, "victim_calls", 0)),
            int(getattr(self._scope_local, "attacker_calls", 0)),
        )

    def scope_target(self) -> dict[str, Any]:
        return dict(getattr(self._scope_local, "target", {}) or {})

    def set_scope_diagnostics(self, diagnostics: dict[str, Any]) -> None:
        self._scope_local.diagnostics = dict(diagnostics)

    def scope_diagnostics(self) -> dict[str, Any]:
        return dict(getattr(self._scope_local, "diagnostics", {}) or {})

    def _with_retries(
        self,
        fn: Callable[[], str],
        what: str,
        before_attempt: Callable[[], None] | None = None,
    ) -> str:
        """短指数退避耗尽后,对 API/网络错误长冷却并无限重试同一请求。"""
        retry_cycle = 0
        while True:
            last_error: Exception | None = None
            for attempt in range(self.retries + 1):
                try:
                    if before_attempt is not None:
                        before_attempt()
                    response = fn()
                    if not str(response or "").strip():
                        raise ValueError("empty_response")
                    return str(response)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt >= self.retries:
                        break
                    delay = min(self.retry_backoff_max, self.retry_backoff_base * (2 ** attempt))
                    LOGGER.warning("%s 第%s次失败,%.1fs 后重试:%s", what, attempt + 1, delay, str(exc)[:120])
                    if delay > 0:
                        time.sleep(delay)
            assert last_error is not None
            if not self.retry_until_success or not is_retryable_api_error(last_error):
                raise last_error
            retry_cycle += 1
            delay = max(0.0, float(self.retry_cooldown_seconds))
            LOGGER.warning(
                "%s 短重试耗尽;长冷却轮次=%s,%.1fs 后重试同一请求:%s",
                what, retry_cycle, delay, str(last_error)[:160],
            )
            if delay > 0:
                time.sleep(delay)

    def rag_answer(
        self,
        query: str,
        *,
        prompt_builder: Callable[[str, list[str]], str] | None = None,
    ) -> str:
        """检索 top_k → 通用 RAG prompt → victim 作答(带重试)。计 1 次 victim 调用。

        限速:启用令牌桶时【发请求前】acquire() 取令牌(全局 ≤ RPM,抗端点卡顿),对齐第 10 步
        runner 的做法(每【逻辑】调用取一枚;_with_retries 内部重试不再额外取,重试自带长退避、
        天然拉开间隔)。未启用令牌桶时回退到调用后固定 sleep(旧行为)。
        """
        retrieved = self.retriever.retrieve(query, top_k=self.top_k)
        contexts = [r.text for r in retrieved]
        prompt = (prompt_builder or build_generic_rag_prompt)(query, contexts)
        out = self._with_retries(
            lambda: self.victim.generate(
                prompt, temperature=self.temperature, timeout=self.timeout, max_tokens=self.max_tokens
            ),
            what="victim.generate",
            before_attempt=(self.victim_bucket.acquire if self.victim_bucket is not None else None),
        )
        with self._count_lock:
            self.victim_calls += 1
        self._scope_local.victim_calls = int(getattr(self._scope_local, "victim_calls", 0)) + 1
        # 令牌桶模式下桶已限速,不再固定 sleep;否则沿用旧的 per-call 间隔。
        if self.victim_bucket is None and self.request_interval_seconds > 0:
            time.sleep(self.request_interval_seconds)
        return out

    def attacker(self, prompt: str) -> str:
        """调用 attacker LLM(sibling)(带重试)。IA 生成问题/答案、DCMI 扰动文本用。

        限速同 rag_answer:优先 attacker 专用令牌桶(若与 victim 同 key 则为同一只桶,共享限额)。
        """
        if self.attacker_chat is None:
            raise RuntimeError("该 baseline 需要 attacker LLM,请配置 sibling profile。")
        out = self._with_retries(
            lambda: self.attacker_chat(prompt),
            what="attacker.chat",
            before_attempt=(self.attacker_bucket.acquire if self.attacker_bucket is not None else None),
        )
        with self._count_lock:
            self.attacker_calls += 1
        self._scope_local.attacker_calls = int(getattr(self._scope_local, "attacker_calls", 0)) + 1
        attacker_interval = (
            self.request_interval_seconds
            if self.attacker_request_interval_seconds is None
            else self.attacker_request_interval_seconds
        )
        if self.attacker_bucket is None and attacker_interval > 0:
            time.sleep(attacker_interval)
        return out

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._embedder is None:
            # 复用检索器已加载的同一个向量模型,避免重复加载。
            self._embedder = self.retriever.embedder
        return np.asarray(self._embedder.encode(list(texts)), dtype="float32")

    def cosine(self, a_text: str, b_text: str) -> float:
        v = self.embed([a_text, b_text])
        x, y = v[0], v[1]
        denom = float(np.linalg.norm(x) * np.linalg.norm(y)) or 1.0
        return float(np.dot(x, y) / denom)


# ============================================================
# 6 个 baseline 适配器:score_target(text, svc) -> float(越大越像成员)
# ============================================================
def lexical_overlap(reference: str, candidate: str) -> float:
    """统一的「生成 vs 原文」词法重叠度量(BLEU,method4 平滑)。

    S2MIA(s) 与 DCMI base 共用这同一把「记忆复现」尺子:RAG 回答越逐字贴近原文,
    越可能命中库内原文 → 越像成员。与官方 IA(mia_utils/s2.py)、MIRABEL 的
    sentence_bleu + SmoothingFunction.method4 同口径,便于差分测试逐值对齐。
    """
    from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu

    ref_tokens = reference.strip().split()
    cand_tokens = candidate.strip().split()
    if not ref_tokens or not cand_tokens:
        return 0.0
    smoothie = SmoothingFunction().method4
    return float(sentence_bleu([ref_tokens], cand_tokens, smoothing_function=smoothie))


def score_rag_mia(text: str, svc: Services) -> float:
    """RAG-MIA:直接问"这段在不在上下文",yes→1 / no/idk→0。"""
    atk = RAGMIA()
    resp = svc.rag_answer(atk.get_attack_query(text))
    s = atk.get_mia_score(resp)  # 1=yes / 0=no / -1=无法判定
    return 1.0 if s == 1 else 0.0


def score_s2mia(text: str, svc: Services) -> float:
    """S2MIA(s):切半→前半段当 query 让 RAG 复述→BLEU(完整原文, 回答)。

    对齐 IA 官方 mia_utils/s2.py 的确定性逻辑:
      - 按「字符」切半(split_idx = len//2),只把前半段当 query;
      - reference 用「完整原文」、candidate 用 victim 回答,算 BLEU(method4)。
    纯黑盒(仅相似度 s,不取困惑度 p;困惑度需本地 GPT-2 的 logprob,破纯黑盒,
    作附录变体单列)。
    """
    if not text.strip():
        return 0.0
    split_idx = len(text) // 2
    query_text = text[:split_idx].strip()
    if not query_text:
        return 0.0
    atk = S2()
    resp = svc.rag_answer(atk.get_attack_query(query_text))
    return lexical_overlap(text, resp)


_MBA_SINGLETON: "MBAHighDiff | None" = None
_MBA_LOCK = threading.Lock()
_MBA_INFERENCE_LOCK = threading.Lock()


def _get_mba_singleton() -> "MBAHighDiff":
    """线程安全地惰性加载 MBA proxy LM 单例(只加载一次;并发下用双检锁防重复加载 gpt2)。"""
    global _MBA_SINGLETON
    if _MBA_SINGLETON is None:
        with _MBA_LOCK:
            if _MBA_SINGLETON is None:
                _MBA_SINGLETON = MBAHighDiff()  # 加载 proxy LM(gpt2),只加载一次
    return _MBA_SINGLETON


def score_mba(text: str, svc: Services) -> float:
    """MBA(高难词遮蔽):proxy LM 按预测难度选词→victim RAG 填空→填对率(0~1)。

    单例加载 proxy LM(默认 gpt2,离线只选词);victim 仍纯黑盒,只看填空 prompt。选词与打分
    逻辑见 MBA/mba_highdiff.py。【并发安全】:用 build_query/score_response 走【局部】
    mask_answers(线程独立),不碰单例实例状态。Hugging Face tokenizer/model 的内部
    借用状态不保证多线程并发安全,因此只对本地选词阶段串行化;锁在 victim 调用前释放,
    不影响后续 RAG/API 并发。
    """
    atk = _get_mba_singleton()
    with _MBA_INFERENCE_LOCK:
        query, mask_answers = atk.build_query(text)  # 局部 mask_answers,线程独立
    resp = svc.rag_answer(query)
    return float(MBAHighDiff.score_response(resp, mask_answers))


# ---- IA:prompts 内联自 MIRABEL(prompt/mia_prompt.py),逻辑同 MIRABEL IA 类 ----
def _ia_summary_prompt(text: str) -> str:
    return (
        "Provide only a one-sentence, topic-focused noun-phrase description of the "
        "following text. Avoid phrases like 'The document discusses'. Include key "
        f"keywords.\n\nText:\n{text}\n\nDescription:"
    )


def _ia_question_prompt(text: str, n: int) -> str:
    """对齐官方 IA(MIRABEL prompt/mia_prompt.py IAPrompt.question_prompt):生成 N 个
    具体、多样、含文中关键词的 yes/no 问题作检索 query;**保留文中缩写/acronym**;带一个
    few-shot 示例教问题形式。官方是 system+user 双消息,这里合并为单串(attacker 走单串)。
    """
    return (
        f"Based on the following text corpus, generate a list of {n} specific, diverse "
        "yes/no questions as queries that could be used to retrieve information from this "
        "corpus. Note: If the text uses any abbreviations or acronyms, such as 'AhR' or "
        "'IC(50)', use the same forms in your questions. Do not use the expanded version "
        "unless it is explicitly mentioned in the text. Here are a few examples of the type "
        "of questions we are looking for:\n\n"
        "Example Text:\n"
        "Dioxins invade the body mainly through the diet, and produce toxicity through the "
        "transformation of aryl hydrocarbon receptor (AhR). Flavones and flavonols "
        "suppressed antagonistically the transformation of AhR induced by TCDD, with "
        "antagonistic IC(50) values ranging from 0.14 to 10 microM.\n\n"
        "Example Questions:\n"
        "1. Are flavones and flavonols shown to antagonistically suppress the transformation of AhR induced by dioxins?\n"
        "2. Do flavones and flavonols exhibit agonistic effects that transform the aryl hydrocarbon receptor?\n"
        "3. Are the antagonistic IC(50) values for flavones and flavonols between 0.14 and 10 microM?\n\n"
        "Now, based on the corpus below, create questions that are specific, contain keywords "
        "from the text, and are diverse enough to cover different aspects. Avoid mentioning "
        "'the study' or any references to the passage itself, and ensure questions do not "
        "contain general phrases that could apply to any text. Number each question "
        f"(1., 2., ...).\n\nCorpus:\n{text}\n\nGenerate {n} yes/no questions:"
    )


def _ia_answer_prompt(question: str, text: str) -> str:
    return (
        "Based solely on the provided context, answer the question with only 'Yes', "
        "'No', or 'I don't know'.\n\n"
        f"Context:\n{text}\n\nQuestion: {question}\nAnswer:"
    )


def _ia_attack_query(summary: str, question: str) -> str:
    # 对齐官方 IAPrompt.attack_prompt:"I am inquiring about a {summary} {question} ..."
    return f"I am inquiring about a {summary} {question} Please answer with 'Yes', 'No', or 'I don't know'."


def _ia_yn(s: str) -> int:
    import re

    s = re.sub(r"[^a-z0-9]", "", s.lower())
    if s[:3] == "yes":
        return 1
    if s[:2] == "no":
        return 0
    if s.startswith("idontknow"):  # 官方 mia.py 此处误写 s[:8](右边 9 字符,是死代码);修正为
        return -1                  # startswith。因 -1/-999 在打分中等价(均罚 λ_unk),不改变任何分数。
    return -999


def _ia_parse_questions(raw_q: str) -> list[str]:
    """从 attacker 返回里解析编号问句,去掉 "1." / "1)" 这类序号前缀。抽成独立函数便于差分测试。"""
    questions: list[str] = []
    for line in raw_q.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 去掉 "1." 这类前缀(仅当点号前是纯数字)。
        parts = line.split(".", 1)
        q = parts[1].strip() if len(parts) > 1 and parts[0].strip().isdigit() else line
        if q:
            questions.append(q)
    return questions


def score_ia_legacy(text: str, svc: Services, n_questions: int = 30, top_k_questions: int = 5, lambda_unk: float = 0.1) -> float:
    """IA(审问攻击,对齐官方 ali7naseh/RAG_MIA 流程):

      1) attacker 生成 summary;
      2) attacker 生成 N 个 yes/no 问题(官方 prompt:含 few-shot、保留文中缩写);
      3) **区分度筛选**:用与 RAG 同源的检索器算 cosine(问题, 目标文本),选 top_k 个最能
         检索回原文的高区分度问题——代替官方 ElectraScorer 的 query-doc 相关性打分,既抓住
         IA「选高区分度问题」的灵魂,又与目标系统同源(更公平、免 pyterrier 重依赖);
      4) 只对筛后问题用 attacker 基于原文生成 yes/no 标准答案(先筛后答,省调用,对齐官方
         main_mia.py 里 filter_questions_topk → generate_ground_truth_answers 的顺序);
      5) 逐个把「summary+问题」发给 victim RAG,按 yes/no 一致率打分(idk/无效罚 λ_unk)。

    开销:1+1+top_k attacker 调用 + top_k victim 调用 / 目标。
    """
    summary = svc.attacker(_ia_summary_prompt(text)).strip()
    questions = _ia_parse_questions(svc.attacker(_ia_question_prompt(text, n_questions)))
    if not questions:
        return 0.0

    # 区分度筛选:问题与目标文本的检索相关性(同源 embedder 的余弦),取 top_k。
    if len(questions) > top_k_questions:
        questions = sorted(questions, key=lambda q: svc.cosine(q, text), reverse=True)[:top_k_questions]

    ground_truths = [_ia_yn(svc.attacker(_ia_answer_prompt(q, text))) for q in questions]
    scores: list[float] = []
    for q, gt in zip(questions, ground_truths):
        pred = _ia_yn(svc.rag_answer(_ia_attack_query(summary, q)))
        if pred == gt:
            scores.append(1.0)
        elif pred in (-1, -999):  # victim 答 idk/无效 → 轻惩罚
            scores.append(-lambda_unk)
        else:
            scores.append(0.0)
    return sum(scores) / len(scores)


# ---- DCMI:差分校准。base 用 S2(s) 同口径 BLEU 重叠,扰动用反义词替换(对齐官方 perturb.py) ----
def score_ia(
    text: str,
    svc: Services,
    n_questions: int | None = None,
    top_k_questions: int | None = None,
    lambda_unk: float = 0.1,
) -> float:
    """Score IA from frozen attacker-side artifacts, then make five victim calls."""

    if n_questions is not None or top_k_questions is not None:
        return score_ia_legacy(
            text,
            svc,
            n_questions=30 if n_questions is None else n_questions,
            top_k_questions=5 if top_k_questions is None else top_k_questions,
            lambda_unk=lambda_unk,
        )

    if not svc.dataset or not svc.ia_shadow_manifest_dir:
        raise RuntimeError("IA requires a frozen v21 shadow manifest directory")
    target = svc.scope_target()
    bundle = load_source_bundle(
        svc.ia_shadow_manifest_dir,
        svc.dataset,
        {**target, "text": text},
    )
    summary = str(bundle["summary"])
    pairs = list(bundle["selected_pairs"])
    scores: list[float] = []
    victim_answers: list[dict[str, Any]] = []
    for pair in pairs:
        question = str(pair["question"])
        ground_truth = _ia_yn(str(pair["shadow_answer"]))
        prediction = _ia_yn(svc.rag_answer(_ia_attack_query(summary, question)))
        victim_answers.append(
            {
                "question_id": pair["question_id"],
                "candidate_rank": pair["candidate_rank"],
                "shadow_answer": pair["shadow_answer"],
                "victim_answer_class": prediction,
            }
        )
        if prediction == ground_truth:
            scores.append(1.0)
        elif prediction in (-1, -999):
            scores.append(-lambda_unk)
        else:
            scores.append(0.0)
    svc.set_scope_diagnostics(
        {
            "ia": {
                "query_hash": bundle["query_hash"],
                "bundle_hash": bundle["bundle_hash"],
                "shadow_model": pairs[0]["shadow_model"],
                "shadow_model_version": pairs[0]["shadow_model_version"],
                "victim_answers": victim_answers,
            }
        }
    )
    return sum(scores) / len(scores)


def _dcmi_perturb_prompt(text: str) -> str:
    word_count = len(text.split())
    replace_count = int(0.03 * word_count) or 1
    return (
        f"Replace {replace_count} key adjectives or adverbs in noticeable positions with "
        "their antonyms in the following text, ensuring the modified text remains logically "
        f"correct:\n{text}\nReturn only the modified text."
    )


def _dcmi_base_signal(text: str, svc: Services) -> float:
    """base 信号 = S2MIA(s) 同口径的「记忆复现」分:切半→前半段当 query 让 RAG
    复述→BLEU(完整原文, 回答)。DCMI 即此 base 的「原文 − 扰动文」差分版,与 S2 共用
    同一把尺子(全套 baseline 的记忆信号统一成词法重叠,审稿口径一致)。
    """
    return score_s2mia(text, svc)


def score_dcmi(text: str, svc: Services) -> float:
    """DCMI:差分校准 = base(原文) − base(扰动文)。成员在扰动下掉得更多 → diff 更大。

    注:官方 base 分藏在其 flashrag 管线内(MIA.py 仅是占位脚本,base 未完整开源),
    此处 base 用 S2(s) 同口径 BLEU 重叠近似;DCMI 的忠实保证在「反义词扰动 + 差分 +
    阈值优化」这条主链(扰动逻辑对齐官方 perturb.py)。见 BASELINES.md。
    """
    base = _dcmi_base_signal(text, svc)
    perturbed = svc.attacker(_dcmi_perturb_prompt(text)).strip()
    if not perturbed:
        return 0.0
    perturbed_base = _dcmi_base_signal(perturbed, svc)
    return base - perturbed_base


def score_menta(text: str, svc: Services) -> float:
    """MEntA: five frozen broad queries scored by local NLI entailment."""

    if svc.menta_runtime is None:
        raise RuntimeError("MEntA runtime is not configured")
    return float(svc.menta_runtime.score_target(text, svc))


@dataclass
class BaselineSpec:
    """一个 baseline 的注册项。"""

    fn: Callable[..., float]
    needs_attacker: bool
    victim_calls_hint: str  # 每个目标大致 victim 调用数,仅用于成本提示


BASELINES: dict[str, BaselineSpec] = {
    "RAG-MIA": BaselineSpec(score_rag_mia, needs_attacker=False, victim_calls_hint="1"),
    "S2MIA": BaselineSpec(score_s2mia, needs_attacker=False, victim_calls_hint="1"),
    "MBA": BaselineSpec(score_mba, needs_attacker=False, victim_calls_hint="1"),
    "IA": BaselineSpec(score_ia, needs_attacker=False, victim_calls_hint="5"),
    "DCMI": BaselineSpec(score_dcmi, needs_attacker=True, victim_calls_hint="2"),
    "MEntA": BaselineSpec(score_menta, needs_attacker=False, victim_calls_hint="5"),
}


# ============================================================
# 目标枚举 + 跑批 + 指标
# ============================================================
def load_targets(splits_dir: str | Path) -> list[dict[str, Any]]:
    """从 split 读目标 chunk:kb_member(成员) + true_non_member(非成员)。

    Reserve / Spoof 不纳入评估(与 PCV-MIA 评估口径一致)。
    """
    splits = Path(splits_dir)
    targets: list[dict[str, Any]] = []
    for fname in ("kb_member.jsonl", "true_non_member.jsonl"):
        path = splits / fname
        if not path.exists():
            LOGGER.warning("Split file missing: %s", path)
            continue
        for row in read_jsonl(path):
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            targets.append(
                {
                    "doc_id": str(row.get("doc_id")),
                    "group": str(row.get("group")),
                    "text": str(row.get("text") or ""),
                    "source_id": row.get("source_id"),
                    "source_key": row.get("source_key") or metadata.get("source_key"),
                }
            )
    return targets


def aggregate_baseline_source_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把成功的 chunk-level baseline 分数等权聚合为 source-level 分数。"""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_groups: dict[str, str] = {}
    for row in rows:
        if row.get("score") is None or row.get("error"):
            continue
        source_key = str(row.get("source_key") or row.get("source_id") or row.get("doc_id"))
        group = str(row.get("group"))
        previous = source_groups.setdefault(source_key, group)
        if previous != group:
            raise RuntimeError(f"Baseline source crosses membership groups: {source_key}: {previous} vs {group}")
        buckets[source_key].append(row)

    source_rows: list[dict[str, Any]] = []
    for source_key, source_chunks in sorted(buckets.items()):
        first = source_chunks[0]
        source_row = {
                "baseline": first.get("baseline"),
                "source_key": source_key,
                "source_id": first.get("source_id"),
                "group": first.get("group"),
                "score": mean(float(row["score"]) for row in source_chunks),
                "num_chunks": len(source_chunks),
                "victim_calls": sum(int(row.get("victim_calls", 0)) for row in source_chunks),
                "attacker_calls": sum(int(row.get("attacker_calls", 0)) for row in source_chunks),
            }
        diagnostics = [row.get("diagnostics") for row in source_chunks if row.get("diagnostics")]
        if diagnostics:
            source_row["diagnostics"] = diagnostics[0] if len(diagnostics) == 1 else diagnostics
        source_rows.append(source_row)
    return source_rows


def run_one_baseline(
    name: str,
    targets: list[dict[str, Any]],
    services: Services,
    output_path: str | Path,
    threshold: float = 0.3,
    resume: bool = True,
    force: bool = False,
    max_workers: int = 1,
) -> dict[str, Any]:
    """跑单个 baseline:对每个目标打分,写 per-target 分数,算指标。

    并发:max_workers>1 时用线程池【跨目标】并行——单个目标内部(尤其 IA/DCMI 的
    summary→问题→答案→victim 链)仍是串行数据依赖,不拆。所有 victim/attacker 调用经
    services 的令牌桶统一限速:某目标卡在慢调用时别的目标继续发,把 RPM 管道填满、抗端点
    间歇卡顿(与第 10 步 runner 同一机制)。scores 与 doc_id 一一对应,输出行序不影响指标。
    """
    if name not in BASELINES:
        raise ValueError(f"Unknown baseline: {name}. 可选:{list(BASELINES)}")
    spec = BASELINES[name]
    if spec.needs_attacker and services.attacker_chat is None:
        raise ValueError(f"{name} 需要 attacker LLM,请提供 sibling profile。")

    output = Path(output_path)
    # 断点续跑:已打分的 doc_id 跳过。
    done: dict[str, dict[str, Any]] = {}
    target_ids = {str(target["doc_id"]) for target in targets}
    if resume and not force and output.exists():
        for r in read_jsonl(output):
            if str(r.get("doc_id")) in target_ids and r.get("score") is not None and not r.get("error"):
                done[str(r.get("doc_id"))] = r

    rows: list[dict[str, Any]] = list(done.values())
    pending = [t for t in targets if t["doc_id"] not in done]

    def _score_one(t: dict[str, Any]) -> dict[str, Any]:
        """给单个目标打分(工作线程执行:只读共享 services,不碰 rows/磁盘)。返回一行结果。"""
        score: float | None = None
        error: str | None = None
        services.begin_scope(t)
        try:
            score = float(spec.fn(t["text"], services))
        except Exception as exc:  # 非 API 异常仍记录失败,避免缺依赖/代码错误无限空等
            error = str(exc)
            LOGGER.warning("%s failed on doc_id=%s: %s", name, t["doc_id"], error)
        victim_calls, attacker_calls = services.scope_counts()
        diagnostics = services.scope_diagnostics()
        return {
            "baseline": name,
            "doc_id": t["doc_id"],
            "group": t["group"],
            "source_id": t.get("source_id"),
            "source_key": t.get("source_key"),
            "score": score,
            "error": error,
            "victim_calls": victim_calls,
            "attacker_calls": attacker_calls,
            "diagnostics": diagnostics or None,
        }

    def _consume(row: dict[str, Any]) -> None:
        """收一条结果并增量落盘(仅主线程调用,串行消费,防中途崩溃丢进度)。"""
        rows.append(row)
        write_jsonl(rows, output)

    workers = max(1, int(max_workers))
    if workers > 1 and pending:
        # 跨目标并发:提交所有目标,按完成顺序消费(令牌桶保证全局速率 ≤ RPM)。
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_score_one, t) for t in pending]
            for fut in tqdm(as_completed(futures), total=len(pending), desc=f"baseline {name}", unit="target"):
                _consume(fut.result())
    else:
        for t in tqdm(pending, desc=f"baseline {name}", unit="target"):
            _consume(_score_one(t))

    # 只用成功打分的行算指标。
    scored = [r for r in rows if r.get("score") is not None]
    source_rows = aggregate_baseline_source_scores(scored)
    source_output = output.with_name(f"{output.stem}_source_scores.jsonl")
    write_jsonl(source_rows, source_output)
    metrics = summarize_membership_scores(source_rows, score_key="score", threshold=threshold) if source_rows else {}
    return {
        "baseline": name,
        "output_path": str(output),
        "scored": len(source_rows),
        "scored_chunks": len(scored),
        "failed": len(rows) - len(scored),
        "source_output_path": str(source_output),
        "evaluation_unit": "source",
        "victim_calls": services.victim_calls,
        "attacker_calls": services.attacker_calls,
        "metrics": metrics,
    }


def _chat_fn_from_profile(
    profile: dict[str, Any],
    *,
    temperature: float = 0.2,
    timeout: float = 60.0,
    max_tokens: int = 512,
) -> Callable[[str], str]:
    """由一个已解析的 profile 字典造通用对话函数。"""
    from ..llm.openai_compatible import OpenAICompatibleChatClient

    effective_temperature = float(profile.get("temperature", temperature))
    effective_timeout = float(profile.get("timeout", timeout))
    effective_max_tokens = int(profile.get("max_tokens", max_tokens))
    chat = OpenAICompatibleChatClient(
        base_url=str(profile.get("base_url", "")),
        model=str(profile.get("model", "")),
        api_key_env=str(profile.get("api_key_env", "")),
        system_prompt="",  # attacker 用通用对话,不挂专用 system prompt
        timeout=effective_timeout,
        max_retries=int(profile.get("max_retries", 0)),
        retry_backoff_base=float(profile.get("retry_backoff_base", 2.0)),
        retry_backoff_max=float(profile.get("retry_backoff_max", 30.0)),
        stream=bool(profile.get("stream", False)),  # 继承 profile 的流式开关(绕 524),与 victim 一致
        extra_body=dict(profile.get("extra_body", {}) or {}),
    )

    def _chat(prompt: str) -> str:
        return chat.chat(
            prompt,
            temperature=effective_temperature,
            timeout=effective_timeout,
            max_tokens=effective_max_tokens,
        )

    return _chat


def build_attacker_chat(
    profiles_config: dict[str, Any],
    profile_name: str | None = None,
    *,
    temperature: float = 0.2,
    timeout: float = 60.0,
    max_tokens: int = 512,
) -> Callable[[str], str]:
    """从 sibling profile 造一个通用对话函数,供 IA/DCMI 的 attacker 使用。

    sibling_client 只暴露 rewrite/judge_spoof 专用接口,这里直接用其底层 profile 构造
    一个通用 OpenAICompatibleChatClient.chat。attacker 与 victim 是不同模型(纯黑盒前提)。
    若 sibling key 未配,可改用 victim profile 当 attacker(见 _chat_fn_from_profile)。
    """
    from ..llm.factory import build_sibling_client

    # 复用 factory 的 profile 解析(含 .env 覆盖);构造出的 sibling 客户端弃用,只取 profile。
    _, profile = build_sibling_client(profiles_config, profile_name=profile_name)
    return _chat_fn_from_profile(profile, temperature=temperature, timeout=timeout, max_tokens=max_tokens)


def balanced_sample(targets: list[dict[str, Any]], max_targets: int) -> list[dict[str, Any]]:
    """从两类各取一半,凑成最多 max_targets 个目标(便于小规模/试跑,保证两类都有)。"""
    if max_targets is None or len(targets) <= max_targets:
        return targets
    kb = [t for t in targets if t["group"] == "KB_Member"]
    tn = [t for t in targets if t["group"] == "True_Non_Member"]
    half = max_targets // 2
    return kb[:half] + tn[: max_targets - len(kb[:half])]
