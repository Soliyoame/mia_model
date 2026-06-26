"""Baseline 适配器差分测试(方案一忠实度保证)。

中文说明
========
方案一的忠实度靠「差分测试」证明:对各 baseline 的**确定性逻辑**(切半/选词解析/yes-no
解析/区分度筛选/差分公式/填对率)喂罐头输入、断言输出,**完全回避 LLM 与 proxy 模型的随机性**
(victim/attacker/检索都用可控 fake 替身)。这样既验证移植正确,又不依赖网络或 GPU。

覆盖:
  - lexical_overlap(统一 BLEU 重叠尺子):同文高、无关低、单调、空串=0。
  - S2MIA(s):按字符切半(只发前半段)、BLEU(完整原文, 回答)。
  - DCMI:score = base(原文) − base(扰动文);扰动 prompt 的 replace_count=3%。
  - IA:yes/no 解析、去序号、attack query 格式、**区分度筛选取 top_k + 一致率打分**。
  - MBA:normalize、[Mask_i] 解析、填对率(不加载 proxy LM,object.__new__ 绕过)。
  - RAG-MIA:yes/no→1/0/弃权 二值分。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.baselines import victim_harness as vh
from src.baselines.MBA.mba_highdiff import MBAHighDiff, extract_mask_answers, normalize
from src.baselines.RAG_MIA.rag_mia_reference import RAGMIA


# ---- 可控 fake 替身(鸭子类型,只实现适配器用到的方法)----
class _FakeS2:
    """记录收到的 query、对任意 query 返回固定回答。"""

    def __init__(self, resp: str) -> None:
        self.resp = resp
        self.seen: list[str] = []

    def rag_answer(self, query: str) -> str:
        self.seen.append(query)
        return self.resp


class _FakeIA:
    """按 prompt 内容路由:summary→主题、question→3 问、answer→标准答案;victim 按 query 作答。"""

    def __init__(self) -> None:
        self.rag_calls: list[str] = []

    def attacker(self, prompt: str) -> str:
        if "description" in prompt.lower():           # _ia_summary_prompt
            return "the topic"
        if "yes/no questions" in prompt:              # _ia_question_prompt
            return "1. Qhigh\n2. Qmid\n3. Qlow"
        if "Qhigh" in prompt:                         # _ia_answer_prompt 标准答案
            return "Yes"
        if "Qmid" in prompt:
            return "No"
        if "Qlow" in prompt:
            return "Yes"
        return "I don't know"

    def cosine(self, a: str, b: str) -> float:        # 区分度:问题与原文的相关性
        return {"Qhigh": 0.9, "Qmid": 0.5, "Qlow": 0.1}.get(a, 0.0)

    def rag_answer(self, query: str) -> str:          # victim:Qhigh 答对、Qmid 答错
        self.rag_calls.append(query)
        if "Qhigh" in query:
            return "Yes"
        if "Qmid" in query:
            return "Yes"
        return "I don't know"


class LexicalOverlapTests(unittest.TestCase):
    def test_identical_high_disjoint_low_monotonic(self) -> None:
        ref = "the quick brown fox jumps over the lazy dog today here"
        full = vh.lexical_overlap(ref, ref)
        partial = vh.lexical_overlap(ref, "the quick brown fox sat")
        disjoint = vh.lexical_overlap(ref, "zzz qqq vvv")
        self.assertGreater(full, 0.9)
        self.assertLess(disjoint, 0.1)
        self.assertGreater(full, partial)
        self.assertGreater(partial, disjoint)

    def test_empty_is_zero(self) -> None:
        self.assertEqual(vh.lexical_overlap("", "abc"), 0.0)
        self.assertEqual(vh.lexical_overlap("abc", ""), 0.0)


class S2Tests(unittest.TestCase):
    def test_split_half_only_front_and_bleu_full_reference(self) -> None:
        text = "alpha beta gamma delta echo foxtrot golf hotel india juliet kilo"
        svc_hi = _FakeS2(text)  # 回答=完整原文 → BLEU 高
        self.assertGreater(vh.score_s2mia(text, svc_hi), 0.5)
        # 只发前半段:query 含前半词、不含末尾词(对齐 IA 官方按字符切半)。
        self.assertIn("alpha", svc_hi.seen[0])
        self.assertNotIn("kilo", svc_hi.seen[0])
        # 回答无关 → BLEU 低。
        self.assertLess(vh.score_s2mia(text, _FakeS2("zzz qqq vvv")), 0.1)


class DcmiTests(unittest.TestCase):
    def test_score_is_base_minus_perturbed(self) -> None:
        class Svc:
            def attacker(self, prompt: str) -> str:
                return "PERT"  # 扰动文

        with patch.object(vh, "_dcmi_base_signal", side_effect=lambda t, s: {"orig": 0.8, "PERT": 0.2}[t]):
            self.assertAlmostEqual(vh.score_dcmi("orig", Svc()), 0.6)

    def test_perturb_prompt_replace_count_is_three_percent(self) -> None:
        text = " ".join(["word"] * 100)  # 100 词 → 3%
        prompt = vh._dcmi_perturb_prompt(text)
        self.assertIn("Replace 3 ", prompt)
        self.assertIn("antonyms", prompt)


class IATests(unittest.TestCase):
    def test_yes_no_idk_parse(self) -> None:
        self.assertEqual(vh._ia_yn("Yes, definitely"), 1)
        self.assertEqual(vh._ia_yn("No."), 0)
        self.assertEqual(vh._ia_yn("I don't know"), -1)
        self.assertEqual(vh._ia_yn("maybe so"), -999)

    def test_parse_questions_strips_numbering(self) -> None:
        self.assertEqual(vh._ia_parse_questions("1. Qa\n\n2. Qb\n3. Qc"), ["Qa", "Qb", "Qc"])

    def test_attack_query_format(self) -> None:
        q = vh._ia_attack_query("the topic", "Is X true?")
        self.assertIn("I am inquiring about a the topic Is X true?", q)

    def test_discriminative_filter_topk_and_consistency(self) -> None:
        svc = _FakeIA()
        score = vh.score_ia("doc text", svc, n_questions=3, top_k_questions=2)
        # 区分度筛选:cosine top2 = Qhigh/Qmid;Qlow 被筛掉(victim 从未被问 Qlow)。
        self.assertTrue(all("Qlow" not in q for q in svc.rag_calls))
        self.assertEqual(len(svc.rag_calls), 2)
        # 一致率:Qhigh gt=Yes victim=Yes→1;Qmid gt=No victim=Yes→0 → 0.5。
        self.assertAlmostEqual(score, 0.5)


class MBATests(unittest.TestCase):
    def test_normalize_strips_punct_and_lowers(self) -> None:
        self.assertEqual(normalize("  Hello, World! "), "hello world")

    def test_extract_mask_answers(self) -> None:
        self.assertEqual(
            extract_mask_answers("[Mask_1]: Apple\n[Mask_2]: New York"),
            {"1": "Apple", "2": "New York"},
        )

    def test_fill_rate_score(self) -> None:
        mba = object.__new__(MBAHighDiff)  # 绕过 __init__,不加载 proxy LM
        mba.mask_answers = {1: ["Apple"], 2: ["Boston"]}
        # Mask_1 填对(apple≈Apple)、Mask_2 填错(New York≠Boston)→ 1/2。
        self.assertAlmostEqual(mba.get_mia_score("[Mask_1]: apple\n[Mask_2]: New York"), 0.5)


class RagMiaTests(unittest.TestCase):
    def test_yes_no_binary_parse(self) -> None:
        atk = RAGMIA()
        self.assertEqual(atk.get_mia_score("Yes, it appears"), 1)
        self.assertEqual(atk.get_mia_score("No"), 0)
        self.assertEqual(atk.get_mia_score("Hmm maybe"), -1)

    def test_score_rag_mia_binary(self) -> None:
        class SvcYes:
            def rag_answer(self, q: str) -> str:
                return "Yes"

        class SvcNo:
            def rag_answer(self, q: str) -> str:
                return "No way"

        self.assertEqual(vh.score_rag_mia("x", SvcYes()), 1.0)
        self.assertEqual(vh.score_rag_mia("x", SvcNo()), 0.0)


if __name__ == "__main__":
    unittest.main()
