"""Victim LLM interface.

中文说明
========
本文件定义"受害者模型(victim/被攻击的目标模型)"的客户端。在 PCV-MIA 里，victim
就是那套"带 RAG 知识库的问答系统"所使用的大模型——我们要攻击它、判断某文档是否
在它的知识库中。这里只负责"给一段 prompt、返回一段回答"，底层复用
OpenAICompatibleChatClient。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Protocol

from .openai_compatible import OpenAICompatibleChatClient


class VictimClient(Protocol):
    """Minimal interface required by PCV-MIA generation steps.

    中文说明：受害者模型的"接口契约"。任何能被当作 victim 用的对象，都必须实现
    generate() 方法。这样上层代码(如 rag.runner)只依赖这个契约，不关心底层是哪家模型。
    """

    def generate(self, prompt: str, temperature: float = 0.0, timeout: float = 60.0, max_tokens: int = 512) -> str:
        # 输入一段 prompt，返回模型回答文本。此处仅声明签名，无实现。
        ...


@dataclass
class OpenAICompatibleVictimClient:
    """Victim LLM backed by an OpenAI-compatible Chat Completions API.

    中文说明：用"OpenAI 兼容接口"实现的受害者模型客户端，是 VictimClient 契约的
    具体实现。各字段是连接该模型所需的配置。
    """

    base_url: str                 # 接口地址
    model: str                    # 模型名
    api_key_env: str = ""         # 存放密钥的环境变量名
    system_prompt: str = ""       # 系统提示词
    timeout: float = 60.0         # 超时秒数
    extra_body: dict[str, Any] = field(default_factory=dict)  # 额外请求参数

    @cached_property
    def _client(self) -> OpenAICompatibleChatClient:
        """惰性创建并缓存底层 HTTP 客户端(只建一次)。

        cached_property：第一次访问 self._client 时执行本函数并把结果缓存，之后再
        访问直接返回缓存对象。
        """
        # 复用同一个底层 client：避免每次 generate 都重建对象并重复读 .env。
        return OpenAICompatibleChatClient(
            base_url=self.base_url,
            model=self.model,
            api_key_env=self.api_key_env,
            system_prompt=self.system_prompt,
            timeout=self.timeout,
            extra_body=self.extra_body,
        )

    def generate(self, prompt: str, temperature: float = 0.0, timeout: float = 60.0, max_tokens: int = 512) -> str:
        """让受害者模型对 prompt 生成一段回答(直接转交给底层 client.chat)。

        参数:
            prompt:      提示词。
            temperature: 采样温度。
            timeout:     超时秒数。
            max_tokens:  最大生成长度。
        返回:
            模型回答文本。
        """
        return self._client.chat(prompt, temperature=temperature, timeout=timeout, max_tokens=max_tokens)
