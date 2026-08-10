"""Fail-closed local Hugging Face victim used by the v21 Gemma suite."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from typing import Any

from .openai_compatible import ChatResult
from ..rag.embeddings import enforce_hf_offline, resolve_hf_model_source


@dataclass
class HuggingFaceLocalVictimClient:
    """Local BF16/CUDA causal-LM client with no quantization or CPU fallback."""

    model: str
    revision: str
    system_prompt: str = ""
    local_files_only: bool = True
    device: str = "cuda"
    dtype: str = "bfloat16"
    quantization: str = "none"
    batch_size: int = 1
    trust_remote_code: bool = False
    _lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not str(self.model).strip():
            raise ValueError("Local Hugging Face model ID is required")
        if not str(self.revision).strip():
            raise ValueError("Local Hugging Face revision/snapshot is required")
        if self.device != "cuda":
            raise RuntimeError("Formal local victim requires device=cuda")
        if self.dtype != "bfloat16":
            raise RuntimeError("Formal local victim requires dtype=bfloat16")
        if self.quantization != "none":
            raise RuntimeError("Formal local victim forbids quantization")
        if int(self.batch_size) != 1:
            raise RuntimeError("Formal local victim requires batch_size=1")

    @cached_property
    def _runtime(self) -> tuple[Any, Any, Any]:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is unavailable; refusing CPU fallback for the formal victim"
            )
        enforce_hf_offline(self.local_files_only)
        source = resolve_hf_model_source(
            self.model,
            revision=self.revision,
            local_files_only=self.local_files_only,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            source,
            revision=None if source != self.model else self.revision,
            local_files_only=self.local_files_only,
            trust_remote_code=self.trust_remote_code,
        )
        model = AutoModelForCausalLM.from_pretrained(
            source,
            revision=None if source != self.model else self.revision,
            local_files_only=self.local_files_only,
            trust_remote_code=self.trust_remote_code,
            torch_dtype=torch.bfloat16,
        ).to("cuda")
        model.eval()
        if bool(getattr(model, "is_quantized", False)):
            raise RuntimeError("Loaded victim is quantized; formal v21 requires BF16")
        return tokenizer, model, torch

    def generate_with_metadata(
        self,
        prompt: str,
        temperature: float = 0.0,
        timeout: float = 60.0,
        max_tokens: int = 512,
    ) -> ChatResult:
        del timeout  # Local synchronous inference has no transport timeout.
        called_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        tokenizer, model, torch = self._runtime
        user_content = str(prompt)
        if self.system_prompt:
            user_content = f"{self.system_prompt}\n\n{user_content}"
        messages = [{"role": "user", "content": user_content}]
        with self._lock, torch.inference_mode():
            input_ids = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
            ).to("cuda")
            kwargs: dict[str, Any] = {
                "max_new_tokens": int(max_tokens),
                "do_sample": float(temperature) > 0,
            }
            if float(temperature) > 0:
                kwargs["temperature"] = float(temperature)
            generated = model.generate(input_ids, **kwargs)
            output_ids = generated[0, input_ids.shape[-1] :]
            content = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
        return ChatResult(
            content=content,
            provider_model_id=self.model,
            provider_request_id=f"local-{uuid.uuid4()}",
            system_fingerprint=f"hf-revision:{self.revision}",
            called_at=called_at,
            input_tokens=int(input_ids.shape[-1]),
            output_tokens=int(output_ids.shape[-1]),
            finish_reason="stop",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            retry_count=0,
        )

    def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        timeout: float = 60.0,
        max_tokens: int = 512,
    ) -> str:
        return self.generate_with_metadata(
            prompt,
            temperature=temperature,
            timeout=timeout,
            max_tokens=max_tokens,
        ).content
