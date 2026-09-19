"""S²MIA(Semantic Similarity MIA)参考实现 —— 抽取自 MIRABEL。

来源
====
- 论文:Generating Is Believing / Seeing Is Believing: (Black-Box) Membership Inference
        Attacks Against Retrieval-Augmented Generation
        (Yuying Li, Gaoyang Liu, Chen Wang, Yang Yang,ICASSP'25)arXiv:2406.19234
- 代码:原作者未放官方仓库;本文件从第三方官方复现 MIRABEL 抽取并内联依赖,
        原始位置 src/baselines/MIRABEL/mia.py(class S2)+ prompt/mia_prompt.py(S2Prompt)。
        MIRABEL: https://github.com/nonalcohol-park/MIRABEL (arXiv:2505.22061)

⚠ 威胁模型(对齐时务必注意)
==========================
本实现 = S²MIA(s&p):相似度用 BLEU、再叠加 GPT-2 困惑度(__compute_perplexity)。
**困惑度需要本地 GPT-2 跑前向、本质是用代理模型的 logprob → 不算「纯黑盒」。**
PCV-MIA 是纯黑盒,为保持威胁模型一致:
  - 主对照请用 **S²MIA(s) 仅相似度版**:只调用 get_mia_score 的 BLEU 部分,丢弃 perplexity。
    (注:原论文相似度用语义余弦;MIRABEL 用 BLEU。可二选一,但要在论文里写明用的是哪个。)
  - S²MIA(s&p) 困惑度版可作「需 logprob、不同威胁模型」单列,不混入纯黑盒主表。

方法
====
S²MIA 思路:把目标文档「前半段」当 query 发给 RAG,让它续写;比「RAG 回答」与
「目标文档后半段」的相似度——若文档在库,检索会命中原文,回答与后半段更像 → 判成员。
(注:本 attack_prompt 是 MIRABEL 的「就 query 作答」版;若严格走原论文「前半段→续写后半段」,
 需在接入层把 chunk 切两半,用前半段构造 query、用后半段当 reference 算相似度。)

如何接入本项目流水线
====================
对每个目标 chunk →
  1) 切两半:前半段 query_text、后半段 reference;
  2) get_attack_query(query_text) 发给 victim RAG;
  3) 用 BLEU(或语义余弦,复用 src/rag 的 embedder)算「回答 vs 后半段」相似度作为成员分数。
与 PCV-MIA 跑同一批 chunk、同一指标。
"""

from __future__ import annotations


class S2Prompt:
    """S² 攻击 prompt(内联自 MIRABEL prompt/mia_prompt.py)。"""

    @staticmethod
    def attack_prompt(query_text):
        messages = [
            {"role": "user", "content": f"""
             Given the [Query]: {query_text}.
             Do not include any introductory or explanatory text, use the following format for output: ([Response]: \'Provide a concise response directly addressing the [Query] by using the most relevant and matching text in the prompt\')
             """}
        ]
        return messages


class S2:
    """Semantic Similarity MIA(s&p,抽取自 MIRABEL,逻辑保持一致)。

    纯黑盒主对照请只用相似度(BLEU)分支,忽略 perplexity——见模块开头威胁模型说明。
    """

    def __init__(self, threshold_s=1e-4, threshold_ppl=20):
        self.threshold_s = threshold_s
        self.threshold_ppl = threshold_ppl
        self.s_score = 0
        self.ppl_score = 0

    def __compute_bleu(self, reference_text, generated_text):
        from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction

        reference_tokens = reference_text.strip().split()
        generated_tokens = generated_text.strip().split()

        smoothie = SmoothingFunction().method4
        score = sentence_bleu(
            [reference_tokens],
            generated_tokens,
            smoothing_function=smoothie,
        )
        return score

    def __compute_perplexity(self, text):
        # ⚠ 非纯黑盒:需本地 GPT-2 前向(代理 logprob)。纯黑盒主对照请勿调用此分支。
        import math
        import torch
        from transformers import GPT2LMHeadModel, GPT2TokenizerFast

        tokenizer = GPT2TokenizerFast.from_pretrained("gpt2")
        model = GPT2LMHeadModel.from_pretrained("gpt2")

        model.eval()
        inputs = tokenizer(text, truncation=True, max_length=1024, return_tensors='pt')
        input_ids = inputs['input_ids']

        with torch.no_grad():
            outputs = model(input_ids, labels=input_ids)

        loss = outputs.loss.item()
        perplexity = math.exp(loss)
        return perplexity

    def get_attack_query(self, query_text):
        return S2Prompt.attack_prompt(query_text)[0]["content"]

    def get_mia_score(self, text, response):
        """返回 (相似度 s_score, 困惑度 ppl_score)。纯黑盒只取 s_score。"""
        s_score = self.__compute_bleu(text, response)
        self.s_score = s_score

        perplexity_score = self.__compute_perplexity(response)
        self.ppl_score = perplexity_score

        return s_score, perplexity_score

    def get_mia_result(self, text, response):
        s_score, ppl_score = self.get_mia_score(text, response)
        if s_score >= self.threshold_s and ppl_score <= self.threshold_ppl:
            return 1
        else:
            return 0
