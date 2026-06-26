"""MBA(Mask-Based Attack)参考实现 —— 抽取自 MIRABEL。

来源
====
- 论文:Mask-based Membership Inference Attacks for Retrieval-Augmented Generation
        (Mingrui Liu, Sixiao Zhang, Cheng Long,WWW'25)arXiv:2410.20142
- 代码:原作者未放官方仓库;本文件从第三方官方复现 MIRABEL 抽取并内联依赖,
        原始位置 src/baselines/MIRABEL/mia.py(class MBA)+ prompt/mia_prompt.py(MBAPrompt)。
        MIRABEL: https://github.com/nonalcohol-park/MIRABEL (arXiv:2505.22061)

⚠ 重要差异(对齐 baseline 时务必注意)
====================================
MIRABEL 的 MBA 用「随机 mask」(mask_text_easy:把文本分段、每段随机挑一个词遮蔽),
而原论文是「挑代理 LM 预测 rank 最高的高难词」(专有名词/术语)。MIRABEL 称随机 mask
准确率相近,故简化。若审稿要求严格复现原文,需把 mask 选词换成「代理 MLM 高难词」策略。

威胁模型:纯黑盒(只需文本输出)✓,与 PCV-MIA 一致。

如何接入本项目流水线
====================
MBA 是「文档级」攻击:对每个目标 chunk →
  1) get_attack_query(chunk):遮蔽若干词,返回填空 prompt;
  2) 把该 prompt 发给我们的 victim RAG(src/rag 的检索+生成,带 KB 检索);
  3) get_mia_score(response):按填对率打分(0~1),作为成员性分数。
评估时与 PCV-MIA 跑同一批 KB_Member / True_Non_Member chunk、同一套指标(AUC/TPR@FPR/Accuracy)。
注:需要一个 tokenizer(默认 bert-base-uncased,仅用于切词,离线)。
"""

from __future__ import annotations

import re
import random


class MBAPrompt:
    """填空攻击 prompt(内联自 MIRABEL prompt/mia_prompt.py)。"""

    @staticmethod
    def attack_prompt(masked_text):
        messages = [
            {"role": "user", "content": f"""
             You are given a text with several missing words or phrases, represented by placeholders in the format [Mask_i], where i is a unique number for each blank.
             Your task is to accurately fill in each placeholder with the most appropriate word or phrase based on the context of the sentence.
             Provide your answers in the specified format: "[Mask_i]: answer_i\\n" for each mask, where "answer_i" shall be a word or phrase.
             You should strictly match the missing word or phrase based on the original context, without making any modifications, corrections, or substitutions.

             The text is: {masked_text}
             """},
        ]
        return messages


class MBA:
    """Mask-Based Attack(随机 mask 版,抽取自 MIRABEL,逻辑保持一致)。"""

    def __init__(self, seed=2025, mask_number=5, threshold=0.5, tokenizer_name="bert-base-uncased"):
        # 说明:MIRABEL 原版在此加载 bert tokenizer,但「随机 mask」路径
        # (mask_text_easy 用正则切词、get_mia_score 用字符串比对)实际并不使用它。
        # 故改为「可选加载」:无 transformers/无网时不报错,不影响打分逻辑。
        self.tokenizer = None
        try:
            from transformers import AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
        except Exception:
            self.tokenizer = None
        self.mask_number = mask_number
        self.threshold = threshold
        self.seed = seed
        self.masked_tokens = []
        self.scores = []

    def __clean_text(self, text):
        text = text.lower()
        text = text.replace(" ", "")
        text = re.sub(r'[^a-z0-9/]', '', text)
        return text

    def split_special_substrings(self, text):
        pattern = re.compile(r'[a-zA-Z\-/]+')
        return pattern.findall(text)

    def mask_text_easy(self, text):
        tokens = self.split_special_substrings(text)
        n = len(tokens)
        part_size = n // self.mask_number
        random.seed(self.seed)
        new_tokens = []
        masked_tokens = []

        before_mask_end = True
        for i in range(self.mask_number):
            start = i * part_size
            end = (i + 1) * part_size if i < self.mask_number - 1 else n
            part = tokens[start:end]

            if part:
                if before_mask_end:
                    if len(part) > 1:
                        rand_idx = random.randint(1, len(part) - 1)
                    else:
                        before_mask_end = False
                        new_tokens.extend(part)
                        continue
                else:
                    rand_idx = random.randint(0, len(part) - 1)

                if rand_idx == len(part) - 1:
                    before_mask_end = True
                else:
                    before_mask_end = False
                masked_tokens.append(part[rand_idx])
                part[rand_idx] = f"[Mask_{i}]"

            new_tokens.extend(part)

        return ' '.join(new_tokens), masked_tokens

    def get_attack_query(self, text):
        masked_text, self.masked_tokens = self.mask_text_easy(text)
        return MBAPrompt.attack_prompt(masked_text)[0]["content"]

    def get_mia_score(self, response):
        generated_token = response.split('\n')
        generated_tokens = []
        for i in generated_token:
            if i.lower().startswith("[mask") or i.lower().startswith("mask"):
                if len(i.split(":")) > 1:
                    generated_tokens.append(i.split(":")[1])
                else:
                    generated_tokens.append("")
        scores = []
        for i in range(len(self.masked_tokens)):
            if i < len(generated_tokens):
                if self.__clean_text(self.masked_tokens[i]) in self.__clean_text(generated_tokens[i]):
                    scores.append(1)
                else:
                    scores.append(0)
            else:
                scores.append(-1)

        self.scores = scores
        for i in range(len(scores)):
            if scores[i] == -1:
                scores[i] = 0

        score = sum(scores) / len(scores)
        return score

    def get_mia_result(self, response):
        score = self.get_mia_score(response)
        return 1 if score >= self.threshold else 0
