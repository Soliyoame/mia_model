"""MBA(Mask-Based Attack)忠实复现 —— 高难词遮蔽版(移植自 IA 官方 mia_utils/mba.py)。

来源
====
- 论文:Mask-based Membership Inference Attacks for Retrieval-Augmented Generation
        (WWW'25)arXiv:2410.20142
- 代码:原作者未放官方仓库;本文件移植 ali7naseh/RAG_MIA(IA 官方仓库)对 MBA 的复现
        mia_utils/mba.py 的**确定性选词逻辑**(compute_rank + mba_pipeline + 解析打分),
        只把"代理 LM 前向"这个接缝换成本项目可控的本地小模型。

为什么不用 MIRABEL 随机版
========================
MBA 的灵魂是"用代理语言模型挑**最难预测**的词来遮蔽"——rank(P(token|prefix)) 越大=越难
预测=越可能是文档独有的高信息词。MIRABEL 的 mask_text_easy 简化成了分段随机,丢了这个核心。
投稿级对照用本高难词版。

威胁模型:纯黑盒 ✓
==================
proxy LM 只在 attacker 侧**离线选词**(不碰 victim);victim 仍只看最终填空 prompt 的黑盒
输出。proxy LM 用小模型(默认 gpt2,CPU 可跑)即可——选词排难度不需要强模型。

与官方的差异(诚实标注)
======================
- 跳过官方的拼写纠正模型(spell-correction):它只为兜底被 BPE 切碎的 OCR/拼写错词;edgar
  财报文本干净,fragmented 词直接用其多子词的 max-rank 近似(官方 FRAGMENT 分支逻辑,但不做
  拼写纠正、候选只保留原词)。差分测试据此断言。
- fragmented 判定与首子词取用统一走 add_special_tokens=False,适配 gpt2(无 BOS),
  对齐官方"词被切成多于一个子词"的本意。
"""

from __future__ import annotations

import re
import string

import numpy as np

# 内置英文停用词(避免 nltk.download 联网);常见集,够 MBA 选词时"跳过停用词"用。
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "while", "is", "are", "was", "were", "be",
    "been", "being", "to", "of", "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "into", "through", "during", "before", "after", "above", "below", "from", "up",
    "down", "out", "off", "over", "under", "again", "further", "then", "once", "here", "there",
    "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just", "should",
    "now", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "them",
    "his", "her", "its", "our", "their", "as", "what", "which", "who", "whom", "when", "where",
    "why", "how", "s", "t", "etc", "eg", "ie",
}
_PUNCT = set(string.punctuation)


def normalize(word: str) -> str:
    """去标点、转小写、去首尾空白(对齐官方 mba.py 的 normalize)。"""
    return word.strip().lower().translate(str.maketrans("", "", string.punctuation))


def extract_mask_answers(text: str) -> dict[str, str]:
    """从填空回答里解析 "[Mask_i]: answer" → {i: answer}(对齐官方 calculate_score 正则)。"""
    pattern = r"\[?MASK?_?(\d+)\]?:?\s*\**\s*([\w\-' ]+)"
    matches = re.findall(pattern, text, re.IGNORECASE)
    return {mid: ans.strip() for mid, ans in matches}


# 填空指令模板(对齐官方 mba.py generate_questions 的 template)。
_MBA_TEMPLATE = (
    "Predict the answers of the masks in the given texts:\n\n{masked_document}\n\n"
    "You should strictly follow the contexts below to answer, and provide your answers "
    'in the specified format:\n"[Mask_i]: answer_i\\n" for each mask:'
)


class MBAHighDiff:
    """高难词遮蔽 MBA:proxy LM 选词(mba_pipeline)+ 填空打分(get_mia_score)。

    用法(每个目标 chunk):
        atk = MBAHighDiff()                 # 单例,只加载一次 proxy LM
        query = atk.get_attack_query(text)  # 选词 + 拼填空 prompt,并把 self.mask_answers 设好
        resp  = victim_rag(query)
        score = atk.get_mia_score(resp)     # 填对率 0~1
    """

    def __init__(
        self,
        proxy_lm: str = "gpt2",
        num_masks: int = 10,
        document_slice_size: int = 2048,
        device: str | None = None,
    ) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.num_masks = num_masks
        self.document_slice_size = document_slice_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tok = AutoTokenizer.from_pretrained(proxy_lm)
        # 保留最近上下文:prefix 过长时从左截断(预测下一词靠的是右端最近文本)。
        self.tok.truncation_side = "left"
        self.model = AutoModelForCausalLM.from_pretrained(proxy_lm).eval().to(self.device)
        self.stop_words = set(_STOPWORDS)
        self.mask_answers: dict[int, list[str]] = {}

    def _ids(self, text: str) -> list[int]:
        """统一不加 special token 的子词 id(适配 gpt2 无 BOS)。"""
        return self.tok(text, add_special_tokens=False)["input_ids"]

    def _fragmented_indices(self, words: list[str]) -> set[int]:
        """proxy tokenizer 把哪些词切成了多于一个子词(对齐官方 _fragmented_word_extraction)。"""
        return {i for i, w in enumerate(words) if len(self._ids(w)) > 1}

    def _compute_rank(self, prefix: str, token_id: int) -> int:
        """rank(P(token|prefix)):token 在"下一个词"概率排序里的名次(0=最可能)。

        rank 越大=该词越难预测=越可能是文档独有高信息词(对齐官方 compute_rank)。
        """
        import torch

        enc = self.tok(prefix, return_tensors="pt", truncation=True, max_length=1024)
        enc = {k: v.to(self.device) for k, v in enc.items()}
        with torch.no_grad():
            logits = self.model(**enc).logits
        order = torch.argsort(logits[0, -1], descending=True).cpu().numpy()
        pos = np.where(order == token_id)[0]
        return int(pos[0]) if len(pos) else len(order)

    def mba_pipeline(self, document: str, num_masks: int) -> tuple[str, dict[int, list[str]]]:
        """把文档切成 num_masks 段,每段选 rank 最大(最难预测)的词遮蔽,返回填空文本+答案。

        对齐官方 mba_pipeline 的全部确定性规则:跳过前 5 词 / 停用词 / 标点 / 不与已遮蔽词相邻;
        fragmented 词逐子词算 rank 取 max(此处用原词、跳过拼写纠正)。
        """
        words = document.split()
        if not words:
            return "", {}
        frag = self._fragmented_indices(words)
        fragment_size = int(np.ceil(len(words) / num_masks))
        masked = np.zeros(len(words), dtype=bool)
        mask_answers: list[list[str]] = []
        prefix = ""

        for i in range(0, len(words), fragment_size):
            scores_within: list[int] = []
            cand_within: list[list[str]] = []
            for j in range(i, min(i + fragment_size, len(words))):
                if j < 5:  # 跳过开头 5 个词(官方:source authors)
                    score = -1
                    cand_within.append([""])
                elif words[j].lower() in self.stop_words or words[j] in _PUNCT:
                    score = -1
                    cand_within.append([""])
                elif j > 0 and masked[j - 1]:  # 不与已遮蔽词相邻
                    score = -1
                    cand_within.append([""])
                elif j not in frag:
                    tok_ids = self._ids(words[j])
                    score = self._compute_rank(prefix + " ", tok_ids[0]) if tok_ids else -1
                    cand_within.append([words[j]])
                else:
                    # fragmented:逐子词在累进 prefix 上算 rank,取 max(此处不做拼写纠正)。
                    tok_ids = self._ids(words[j])
                    inner_scores: list[int] = []
                    seen: list[int] = []
                    for tok in tok_ids:
                        inner_str = self.tok.decode(seen)
                        inner_scores.append(self._compute_rank(prefix + " " + inner_str, tok))
                        seen.append(tok)
                    score = max(inner_scores) if inner_scores else -1
                    cand_within.append([words[j]])

                scores_within.append(score)
                prefix = words[j] if not prefix else prefix + " " + words[j]

            mask_idx = int(np.argmax(scores_within))  # 段内 rank 最大者(全 -1 时取首个,同官方)
            masked[i + mask_idx] = True
            mask_answers.append(cand_within[mask_idx])

        answers = {k + 1: mask_answers[k] for k in range(len(mask_answers))}

        out: list[str] = []
        k = 1
        for idx, word in enumerate(words):
            if masked[idx]:
                out.append(f"[MASK_{k}]")
                k += 1
            else:
                out.append(word)
        return " ".join(out), answers

    def build_query(self, text: str) -> tuple[str, dict[int, list[str]]]:
        """【线程安全】选词遮蔽 + 拼填空 prompt,返回 (prompt, mask_answers)——不写实例状态。

        与 get_attack_query 逻辑完全一致,唯一区别是把 mask_answers 作为【返回值】交出,
        而非存进 self.mask_answers。并发跑多个目标时,各目标持有自己的 mask_answers 局部量,
        避免共享单例的实例状态被别的线程覆盖:串行接口 get_attack_query→get_mia_score
        之间隔着一次慢 victim 调用,并发下会被其它目标的 get_attack_query 覆盖而串味算错分。
        proxy LM 前向本身只读、可安全并发,故单例仍可共享,只需把这一处可变状态外提为局部。
        """
        masked_document, mask_answers = self.mba_pipeline(
            text[: self.document_slice_size], self.num_masks
        )
        return _MBA_TEMPLATE.format(masked_document=masked_document), mask_answers

    @staticmethod
    def score_response(response: str, mask_answers: dict[int, list[str]]) -> float:
        """【线程安全】填对率(0~1):mask_answers 由参数传入,不读任何实例状态。"""
        total = len(mask_answers)
        if total == 0:
            return 0.0
        predicted = extract_mask_answers(response)
        correct = 0
        for mask_id, answers in mask_answers.items():
            got = normalize(predicted.get(str(mask_id), ""))
            gold = [normalize(a) for a in answers if a]
            if got and got in gold:
                correct += 1
        return correct / total

    def get_attack_query(self, text: str) -> str:
        """选词遮蔽 + 拼填空 prompt;同时把 self.mask_answers 设好供打分用(串行接口,向后兼容)。"""
        query, self.mask_answers = self.build_query(text)
        return query

    def get_mia_score(self, response: str) -> float:
        """填对率(0~1):解析回答里各 [Mask_i] 的填词,normalize 后与标准答案比对(串行接口)。"""
        return self.score_response(response, self.mask_answers)
