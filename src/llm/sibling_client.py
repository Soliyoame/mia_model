"""Sibling LLM interface.

Sibling LLM is used to generate spoof candidates and score their quality.

中文说明
========
本文件定义"兄弟模型(sibling)"的客户端。sibling 是攻击者自己掌握的辅助大模型，
不参与被攻击系统，主要干两件事：
    1. rewrite：改写文本，生成"伪造样本(spoof)"候选——用于构造 hard negative 对照组。
    2. judge_spoof：当裁判，给伪造样本的质量(自然度、流畅度、语义/实体保留度)打分。
底层同样复用 OpenAICompatibleChatClient。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Protocol

from .openai_compatible import OpenAICompatibleChatClient, parse_json_object


class SiblingClient(Protocol):
    """Minimal interface required by PCV-MIA sibling-model steps.

    中文说明：兄弟模型的"接口契约"。要当 sibling 用，必须实现 rewrite 和 judge_spoof
    两个方法。上层只依赖契约，不关心具体是哪家模型。
    """

    def rewrite(self, text: str, strategy: str, n: int = 1) -> list[str]:
        # 按某种策略把文本改写 n 个版本，返回字符串列表。此处仅声明签名。
        ...

    def judge_spoof(self, source_text: str, spoof_text: str) -> dict[str, object]:
        # 对比原文与伪造文本，返回质量评分字典。此处仅声明签名。
        ...


@dataclass
class OpenAICompatibleSiblingClient:
    """Sibling LLM backed by an OpenAI-compatible Chat Completions API.

    中文说明：用"OpenAI 兼容接口"实现的兄弟模型客户端，是 SiblingClient 契约的具体实现。
    """

    base_url: str                 # 接口地址
    model: str                    # 模型名
    api_key_env: str = ""         # 存放密钥的环境变量名
    system_prompt: str = ""       # 系统提示词
    timeout: float = 60.0         # 超时秒数
    max_tokens: int = 1024        # 默认最大生成长度
    max_retries: int = 2          # 重试次数(sibling 用于离线生成，允许多重试)
    retry_backoff_base: float = 2.0   # 重试退避基数
    retry_backoff_max: float = 30.0   # 重试退避上限
    stream: bool = False          # 是否走流式(SSE)请求,透传给底层 client
    extra_body: dict[str, Any] = field(default_factory=dict)  # 额外请求参数

    @cached_property
    def _client(self) -> OpenAICompatibleChatClient:
        """惰性创建并缓存底层 HTTP 客户端(只建一次)。"""
        # 复用同一个底层 client：避免每次 _chat 都重建对象并重复读 .env。
        return OpenAICompatibleChatClient(
            base_url=self.base_url,
            model=self.model,
            api_key_env=self.api_key_env,
            system_prompt=self.system_prompt,
            timeout=self.timeout,
            max_retries=self.max_retries,
            retry_backoff_base=self.retry_backoff_base,
            retry_backoff_max=self.retry_backoff_max,
            extra_body=self.extra_body,
            stream=self.stream,
        )

    def _chat(self, prompt: str, *, max_tokens: int | None = None) -> str:
        """内部小工具：用温度 0 调一次底层 chat，max_tokens 没给就用默认值。"""
        return self._client.chat(prompt, temperature=0.0, timeout=self.timeout, max_tokens=max_tokens or self.max_tokens)

    def rewrite(self, text: str, strategy: str, n: int = 1) -> list[str]:
        """Ask the sibling LLM to generate spoof rewrites.

        中文说明：让兄弟模型按指定策略改写文本，生成 n 个"伪造样本"候选。要求模型
        尽量保留语义和重要实体，只改措辞和句式，并只返回 JSON 方便程序解析。

        参数:
            text:     要改写的原始文本。
            strategy: 改写策略(由调用方给出，如同义替换、句式重组等)。
            n:        需要几个改写版本。
        返回:
            最多 n 个改写文本组成的列表(已去掉空白项)。
        异常:
            ValueError: 模型返回里没有 rewrites 列表时抛出。
        """
        # 拼一段提示词，明确任务、约束和"只返回 JSON"的输出格式。
        prompt = (
            "Rewrite the text for a privacy attack benchmark.\n"
            "Keep the semantics and important entities as much as possible, but change wording and syntax.\n"
            "Return valid JSON only: {\"rewrites\": [\"...\"]}.\n\n"
            f"Strategy: {strategy}\n"
            f"Number of rewrites: {n}\n"
            f"Text:\n{text}"
        )
        # 调模型并把回答解析成 JSON 对象。
        obj = parse_json_object(self._chat(prompt))
        rewrites = obj.get("rewrites", [])
        if not isinstance(rewrites, list):
            raise ValueError("Sibling rewrite response must contain a rewrites list.")
        # 去掉空字符串、首尾空格，最多取前 n 个。
        return [str(item).strip() for item in rewrites if str(item).strip()][:n]

    def judge_spoof(self, source_text: str, spoof_text: str) -> dict[str, object]:
        """Use the sibling LLM as a judge for spoof quality.

        中文说明：让兄弟模型当裁判，从 4 个维度(自然度、流畅度、语义保留、实体保留)
        给伪造文本打 1-10 分，并给出理由。用于筛掉质量差的伪造样本。

        参数:
            source_text: 原始文本。
            spoof_text:  待评分的伪造文本。
        返回:
            {"scores": {四个维度的整数分}, "judge_reason": 理由文本}。
        异常:
            ValueError: 模型返回里没有 scores 对象时抛出。
        """
        # 提示词：规定打分维度、分值范围与 JSON 输出格式。
        prompt = (
            "Score a spoofed text against the source text.\n"
            "Use integer scores from 1 to 10 for naturalness, fluency, semantic_preservation, entity_preservation.\n"
            "Return valid JSON only: "
            "{\"scores\":{\"naturalness\":8,\"fluency\":8,\"semantic_preservation\":8,\"entity_preservation\":8},"
            "\"judge_reason\":\"...\"}.\n\n"
            f"Source text:\n{source_text}\n\n"
            f"Spoof text:\n{spoof_text}"
        )
        obj = parse_json_object(self._chat(prompt, max_tokens=512))
        scores = obj.get("scores", {})
        if not isinstance(scores, dict):
            raise ValueError("Sibling judge response must contain a scores object.")
        # 把四个维度逐一容错地转成 1-10 的整数(模型可能给出脏值)。
        normalized_scores = {
            key: _coerce_score(scores.get(key))
            for key in ("naturalness", "fluency", "semantic_preservation", "entity_preservation")
        }
        return {"scores": normalized_scores, "judge_reason": str(obj.get("judge_reason", ""))}


def _coerce_score(value: object, default: int = 1) -> int:
    """把模型给出的分数容错地转成 1-10 的整数，兼容 "8/10"、"8 分"、None 等脏值。

    参数:
        value:   模型给出的原始分数(可能是数字、带单位的字符串、None 等)。
        default: 实在解析不出来时用的兜底分。
    返回:
        夹在 1~10 之间的整数。
    """
    try:
        # 先直接尝试转成浮点数。
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        # 转不了就用正则从字符串里抠出第一个数字(如 "8/10" → 8)。
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        if not match:
            return default
        score = float(match.group())
    # 四舍五入取整，并强制限制在 [1, 10] 范围内。
    return max(1, min(10, int(round(score))))
