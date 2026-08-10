"""OpenAI-compatible HTTP client.

该模块只依赖 Python 标准库，适用于 OpenAI API、vLLM、LM Studio、Ollama
OpenAI-compatible endpoint 等服务。API key 通过环境变量读取，不写入配置文件。

中文说明
========
本文件是所有"调用大语言模型"的最底层封装。它用 Python 自带的 urllib 直接发 HTTP
请求去访问"OpenAI 兼容接口"(很多服务都模仿 OpenAI 的接口格式，所以一套代码能通用)。
- 为什么只用标准库：不引入 openai 等第三方包，部署更简单、依赖更少。
- 安全要点：API key(密钥)绝不写进代码或配置文件，只通过环境变量名间接读取，
  防止把密钥误传到代码仓库里。
- 上层调用者：victim_client.py / sibling_client.py 会包装本类，分别给"受害者模型"
  和"兄弟模型"使用。
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..utils.env import load_dotenv
from .response_validation import detect_api_error_text


def normalize_chat_completions_url(base_url: str) -> str:
    """把 base_url 规范化为 /chat/completions 端点。

    用户在配置里可能只填到根地址(如 https://api.xxx.com/v1)，也可能已经填了完整
    端点。本函数统一补全成 .../chat/completions，避免因为少写/多写斜杠而出错。

    参数:
        base_url: 配置里给的接口基础地址。
    返回:
        指向 chat completions 端点的完整 URL。
    """
    # 去掉结尾多余的斜杠，方便统一拼接。
    cleaned = base_url.rstrip("/")
    # 已经是完整端点就直接用。
    if cleaned.endswith("/chat/completions"):
        return cleaned
    # 否则补上 /chat/completions。
    return f"{cleaned}/chat/completions"


@dataclass(frozen=True)
class ChatResult:
    """回答文本及 provider 返回的可用溯源元数据。"""

    content: str
    provider_model_id: str | None
    provider_request_id: str | None
    system_fingerprint: str | None
    called_at: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    latency_ms: float | None = None
    retry_count: int = 0


@dataclass
class OpenAICompatibleChatClient:
    """最小 OpenAI-compatible Chat Completions 客户端。

    中文说明：用 dataclass(数据类)把"连一个大模型接口需要的所有参数"打包成一个对象。
    创建后调用 .chat() 即可发起一次对话请求。各字段含义见下方注释。
    """

    base_url: str                 # 接口基础地址
    model: str                    # 模型名称(如 gpt-4o-mini、qwen2.5 等)
    api_key_env: str = ""         # 存放 API key 的"环境变量名"(不是 key 本身!)
    system_prompt: str = ""       # 系统提示词(设定模型角色/规则)，可空
    timeout: float = 60.0         # 单次请求超时秒数
    max_retries: int = 0          # 本层最多重试次数(默认 0=不重试)
    retry_backoff_base: float = 2.0   # 重试退避基数
    retry_backoff_max: float = 30.0   # 重试退避上限秒数
    extra_body: dict[str, Any] = field(default_factory=dict)  # 额外请求参数(如 top_p)
    stream: bool = False          # 是否走流式(SSE):慢模型 + Cloudflare 类网关下可绕开"N 秒无响应"的 524
    request_rate_limiter: Any = None  # 每次物理 HTTP 尝试前取令牌；None 表示不限制

    def chat_with_metadata(
        self,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        timeout: float | None = None,
        max_tokens: int = 512,
    ) -> ChatResult:
        """发送一次 chat completion 请求并返回文本与 provider 元数据。

        参数:
            user_prompt: 用户这轮要问的内容。
            temperature: 采样温度，0 表示尽量确定(适合复现实验)。
            timeout:     本次请求超时；为 None 时用对象默认的 self.timeout。
            max_tokens:  最多生成多少 token。
        返回:
            模型回答的纯文本。
        异常:
            ValueError / RuntimeError: 配置缺失、密钥未设置、或返回格式异常时抛出。
        """
        called_at = datetime.now(timezone.utc).isoformat()
        request_started = time.perf_counter()
        # 基础地址和模型名是必填项，缺了直接报错。
        if not self.base_url:
            raise ValueError("OpenAI-compatible base_url is required.")
        if not self.model:
            raise ValueError("OpenAI-compatible model is required.")

        # api_key_env must be an environment variable name, never a raw key.
        # 先加载 .env 文件(把里面的变量读进环境)，再按"变量名"取出真正的密钥。
        load_dotenv()
        api_key = ""
        if self.api_key_env:
            # 防呆：如果有人把真实密钥(以 sk- 开头)直接填进了"变量名"字段，立刻报错。
            if self.api_key_env.startswith("sk-"):
                raise RuntimeError("api_key_env must name an environment variable, not contain a raw API key.")
            api_key = os.getenv(self.api_key_env, "")
            # 指定了变量名却没设置该环境变量，报错提醒。
            if not api_key:
                raise RuntimeError(f"Environment variable is not set: {self.api_key_env}")

        # 按 OpenAI 的消息格式组织对话：先放 system(如有)，再放 user。
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # 组装请求体(JSON)，把额外参数 extra_body 也并进去。
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self.extra_body,
        }
        # 流式(SSE):让服务端边生成边推送数据。慢模型 + Cloudflare 类网关下,持续的数据流
        # 可避开"N 秒内无完整响应"触发的 524(非流式要干等整段生成完,极易踩超时红线)。
        if self.stream:
            payload["stream"] = True
        # ensure_ascii=False 保留中文等非 ASCII 字符原样，再编码成 utf-8 字节。
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # User-Agent 必须显式设置：windhub 等基于 Cloudflare 的代理会拦截缺 UA 的 urllib 默认请求，
        # 表现为 SSL UNEXPECTED_EOF 或 HTTP 403 (Cloudflare error code 1010)。
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; conflict-mia/1.0)",
            "Accept": "text/event-stream" if self.stream else "application/json",
        }
        # 有密钥时按 Bearer 方式放进鉴权头。
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # 构造一个 POST 请求对象。
        request = urllib.request.Request(
            normalize_chat_completions_url(self.base_url),
            data=body,
            headers=headers,
            method="POST",
        )
        # 没单独传 timeout 就用对象默认值。
        request_timeout = self.timeout if timeout is None else timeout

        # 流式:逐块读 SSE、累积答案文本后直接返回(已是纯文本,无需再解析整段 JSON)。
        if self.stream:
            (
                content,
                provider_model_id,
                provider_request_id,
                system_fingerprint,
                input_tokens,
                output_tokens,
                finish_reason,
                retry_count,
            ) = self._stream_with_retries(request, request_timeout)
            api_error = detect_api_error_text(content)
            if api_error:
                raise RuntimeError(f"OpenAI-compatible API error response: {api_error}")
            return ChatResult(
                content=content,
                provider_model_id=provider_model_id,
                provider_request_id=provider_request_id,
                system_fingerprint=system_fingerprint,
                called_at=called_at,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                latency_ms=(time.perf_counter() - request_started) * 1000.0,
                retry_count=retry_count,
            )

        # 非流式:发请求(带重试)，拿到原始返回字符串。
        transport_result = self._urlopen_with_retries(request, request_timeout)
        if isinstance(transport_result, tuple):
            raw, retry_count = transport_result
        else:  # compatibility with mocked/legacy transports
            raw, retry_count = transport_result, 0

        # 解析返回的 JSON，取出模型回答文本。OpenAI 风格返回放在 choices[0].message.content。
        try:
            data = json.loads(raw)
            api_error = detect_api_error_text(raw)
            if api_error:
                raise RuntimeError(f"OpenAI-compatible API error response: {api_error}")
            choice = data["choices"][0]
            # 新式 chat 接口:答案在 message.content。
            if "message" in choice and isinstance(choice["message"], dict):
                content = str(choice["message"].get("content", ""))
            else:
                # 兼容旧式 completion 接口:答案在 text。
                content = str(choice.get("text", ""))
            content_error = detect_api_error_text(content)
            if content_error:
                raise RuntimeError(
                    f"OpenAI-compatible API error response: {content_error}"
                )
            return ChatResult(
                content=content,
                provider_model_id=(
                    str(data.get("model")) if data.get("model") is not None else None
                ),
                provider_request_id=(
                    str(data.get("id")) if data.get("id") is not None else None
                ),
                system_fingerprint=(
                    str(data.get("system_fingerprint"))
                    if data.get("system_fingerprint") is not None
                    else None
                ),
                called_at=called_at,
                input_tokens=(
                    int((data.get("usage") or {}).get("prompt_tokens"))
                    if (data.get("usage") or {}).get("prompt_tokens") is not None
                    else None
                ),
                output_tokens=(
                    int((data.get("usage") or {}).get("completion_tokens"))
                    if (data.get("usage") or {}).get("completion_tokens") is not None
                    else None
                ),
                finish_reason=(
                    str(choice.get("finish_reason"))
                    if choice.get("finish_reason") is not None
                    else None
                ),
                latency_ms=(time.perf_counter() - request_started) * 1000.0,
                retry_count=retry_count,
            )
        except RuntimeError:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            # 返回结构不符合预期(可能是错误页/限流页)，截前 500 字符报错便于排查。
            raise RuntimeError(f"Unexpected OpenAI-compatible response: {raw[:500]}") from exc

    def chat(
        self,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        timeout: float | None = None,
        max_tokens: int = 512,
    ) -> str:
        """兼容旧调用：仅返回文本。"""

        return self.chat_with_metadata(
            user_prompt,
            temperature=temperature,
            timeout=timeout,
            max_tokens=max_tokens,
        ).content

    # 可重试的瞬时传输错误与限流状态码。524 = Cloudflare 网关"源站超时",慢模型常踩,纳入重试。
    _RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 524})

    def _urlopen_with_retries(
        self,
        request: urllib.request.Request,
        request_timeout: float,
    ) -> tuple[str, int]:
        """发送请求；对限流 / 5xx / 网络抖动做指数退避重试。

        max_retries=0（默认）时行为与原来一致：失败立即抛错，由上层（如 rag.runner）
        决定是否重试，避免双层重试相乘放大总时延。

        参数:
            request:         构造好的 urllib 请求对象。
            request_timeout: 本次请求超时秒数。
        返回:
            服务器返回的原始正文字符串(utf-8 解码后)。
        异常:
            RuntimeError: 重试用尽仍失败时抛出，并附带 HTTP 状态码或错误详情。
        """
        # 总尝试次数 = 1 + max_retries(至少 1 次)。
        attempts = max(0, int(self.max_retries))
        for attempt in range(attempts + 1):
            try:
                if self.request_rate_limiter is not None:
                    self.request_rate_limiter.acquire()
                # 打开连接、读出正文并按 utf-8 解码返回。
                with urllib.request.urlopen(request, timeout=request_timeout) as response:
                    return response.read().decode("utf-8"), attempt
            except urllib.error.HTTPError as exc:
                # 服务器返回了错误状态码(如 429/500)。
                detail = exc.read().decode("utf-8", errors="replace")
                # 属于"可重试"状态码且还有重试机会，就退避后重试。
                if exc.code in self._RETRYABLE_STATUS and attempt < attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"OpenAI-compatible request failed: HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                # 网络层错误(连不上/超时等)，还有机会就重试。
                if attempt < attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"OpenAI-compatible request failed: {exc}") from exc
        # 理论上不会走到这里(循环里要么 return 要么 raise)，兜底再抛一次。
        raise RuntimeError("OpenAI-compatible request failed after retries.")

    def _stream_with_retries(
        self,
        request: urllib.request.Request,
        request_timeout: float,
    ) -> tuple[
        str,
        str | None,
        str | None,
        str | None,
        int | None,
        int | None,
        str | None,
        int,
    ]:
        """发流式(SSE)请求,逐行解析 data: 块,累积并返回答案文本。

        与 _urlopen_with_retries 同样的退避重试策略;区别是按 SSE 流式读取——服务端边
        生成边推送,连接持续有数据流,可避开网关"N 秒无完整响应"触发的 524 超时。
        只累积 choices[0].delta.content(答案);忽略 reasoning_content(思考过程,非答案)。
        """
        attempts = max(0, int(self.max_retries))
        for attempt in range(attempts + 1):
            try:
                if self.request_rate_limiter is not None:
                    self.request_rate_limiter.acquire()
                chunks: list[str] = []
                provider_models: set[str] = set()
                provider_request_id: str | None = None
                system_fingerprint: str | None = None
                input_tokens: int | None = None
                output_tokens: int | None = None
                finish_reason: str | None = None
                with urllib.request.urlopen(request, timeout=request_timeout) as response:
                    for raw_line in response:  # 按行迭代 SSE 流
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError as exc:
                            api_error = detect_api_error_text(data)
                            if api_error:
                                raise RuntimeError(
                                    f"OpenAI-compatible streaming API error: {api_error}"
                                ) from exc
                            continue  # 心跳/非标准行,跳过
                        api_error = detect_api_error_text(data)
                        if api_error:
                            raise RuntimeError(
                                f"OpenAI-compatible streaming API error: {api_error}"
                            )
                        if event.get("model") is not None:
                            provider_models.add(str(event["model"]))
                        if provider_request_id is None and event.get("id") is not None:
                            provider_request_id = str(event["id"])
                        if system_fingerprint is None and event.get("system_fingerprint") is not None:
                            system_fingerprint = str(event["system_fingerprint"])
                        usage = event.get("usage") or {}
                        if usage.get("prompt_tokens") is not None:
                            input_tokens = int(usage["prompt_tokens"])
                        if usage.get("completion_tokens") is not None:
                            output_tokens = int(usage["completion_tokens"])
                        try:
                            choice = event["choices"][0]
                            delta = choice.get("delta", {})
                            if choice.get("finish_reason") is not None:
                                finish_reason = str(choice["finish_reason"])
                        except (KeyError, IndexError, TypeError):
                            continue  # 心跳/用量统计行,跳过
                        piece = delta.get("content")
                        if piece:
                            chunks.append(str(piece))
                if len(provider_models) > 1:
                    raise RuntimeError(
                        "OpenAI-compatible streaming model identity drift:"
                        f" {sorted(provider_models)!r}"
                    )
                return (
                    "".join(chunks),
                    next(iter(provider_models), None),
                    provider_request_id,
                    system_fingerprint,
                    input_tokens,
                    output_tokens,
                    finish_reason,
                    attempt,
                )
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in self._RETRYABLE_STATUS and attempt < attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"OpenAI-compatible request failed: HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                if attempt < attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"OpenAI-compatible request failed: {exc}") from exc
        raise RuntimeError("OpenAI-compatible streaming request failed after retries.")

    def _sleep_backoff(self, attempt: int) -> None:
        """重试前睡眠一段时间(指数退避 + 随机抖动)。

        参数:
            attempt: 当前是第几次失败(从 0 开始)，次数越大睡得越久。
        """
        base = max(0.0, float(self.retry_backoff_base))
        cap = max(0.0, float(self.retry_backoff_max))
        # 退避参数非正则不睡。
        if base <= 0 or cap <= 0:
            return
        # 期望等待 = base * 2^attempt，并用 cap 封顶。
        delay = min(cap, base * (2 ** attempt))
        # Full jitter：避免并发调用方在同一时刻一起重试。
        time.sleep(random.uniform(0.0, delay))


def parse_json_object(text: str) -> dict[str, Any]:
    """从模型输出中解析 JSON object，兼容 ```json 代码块与多余解释文字。

    大模型经常不老实地只返回 JSON，而是会包上 ```json 代码块、或在前后加解释。
    本函数尽力把真正的 JSON 对象抠出来并解析。

    参数:
        text: 模型返回的原始文本。
    返回:
        解析出的字典对象。
    异常:
        json.JSONDecodeError / ValueError: 实在找不到合法 JSON 对象时抛出。
    """
    stripped = text.strip()
    # 先尝试匹配 ```json ... ``` 这种代码块，命中就只取里面的内容。
    fence = re.search(r"```(?:json|jsonc)?\s*(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if fence:
        stripped = fence.group(1).strip()
    try:
        # 直接整体解析。
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        # 失败则退而求其次：截取第一个 { 到最后一个 } 之间的子串再解析。
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        obj = json.loads(stripped[start : end + 1])
    # 必须是对象({...})，不能是数组或标量。
    if not isinstance(obj, dict):
        raise ValueError("Model response JSON must be an object.")
    return obj
