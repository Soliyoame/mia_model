"""Victim and reference generative model wrappers."""

import gc
import json
import math
import os

from datasets import Dataset
import numpy as np
import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.utils.data import DataLoader
from transformers import (
    AutoConfig,
    AutoModelForCausalLM,
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
)

from .utils import build_auto_max_memory, get_device


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HF_CACHE = os.path.join(_PROJECT_ROOT, "models", "huggingface")


class LoRALinear(nn.Module):
    """Minimal LoRA wrapper to avoid full-model fine-tuning."""

    def __init__(self, base_layer, rank=8, alpha=16, dropout=0.05):
        super().__init__()
        if rank <= 0:
            raise ValueError("LoRA rank must be positive.")

        self.base_layer = base_layer
        self.rank = rank
        self.alpha = alpha
        self.scaling = alpha / rank
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

        for param in self.base_layer.parameters():
            param.requires_grad = False

        self.lora_A = nn.Linear(base_layer.in_features, rank, bias=False)
        self.lora_B = nn.Linear(rank, base_layer.out_features, bias=False)
        nn.init.kaiming_uniform_(self.lora_A.weight, a=math.sqrt(5))
        nn.init.zeros_(self.lora_B.weight)
        target_device = base_layer.weight.device
        self.lora_A.to(target_device)
        self.lora_B.to(target_device)

    def forward(self, x):
        base_out = self.base_layer(x)
        lora_input = self.dropout(x).to(self.lora_A.weight.dtype)
        lora_out = self.lora_B(self.lora_A(lora_input)) * self.scaling
        return base_out + lora_out.to(base_out.dtype)


class GenerativeAuditModel:
    """Unified wrapper for loss computation and optional fine-tuning."""

    def __init__(
        self,
        model_name="gpt2",
        device=None,
        max_length=256,
        lazy_load=False,
        device_map=None,
    ):
        self.device = get_device(device)
        self.model_name = model_name
        self.base_model_name = model_name
        self.max_length = max_length
        self.device_map = device_map
        self._resolved_device_map = None
        self._resolved_max_memory = None
        self.is_encoder_decoder = False
        self.tokenizer = None
        self.model = None
        self.lazy_load = lazy_load
        self._loaded = False
        self._adapter_enabled = False
        self._adapter_config = None
        if not self.lazy_load:
            self._load_pretrained(model_name)

    def _resolve_device_map(self):
        if not torch.cuda.is_available():
            return None
        if self.device_map:
            return self.device_map
        if torch.cuda.device_count() > 1:
            return "auto"
        return None

    def _resolve_max_memory(self, resolved_device_map):
        if not resolved_device_map:
            return None
        return build_auto_max_memory()

    def _load_pretrained(self, model_name_or_path):
        print(f"Loading generative audit model ({model_name_or_path}, device={self.device})...")
        config = AutoConfig.from_pretrained(model_name_or_path, cache_dir=_HF_CACHE)
        self.is_encoder_decoder = bool(getattr(config, "is_encoder_decoder", False))

        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path, cache_dir=_HF_CACHE)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token or self.tokenizer.unk_token
        if self.tokenizer.pad_token_id is None:
            raise ValueError("Tokenizer must expose a valid pad token id.")

        model_cls = AutoModelForSeq2SeqLM if self.is_encoder_decoder else AutoModelForCausalLM
        load_kwargs = {"cache_dir": _HF_CACHE}
        resolved_device_map = self._resolve_device_map()
        resolved_max_memory = self._resolve_max_memory(resolved_device_map)
        self._resolved_device_map = resolved_device_map
        self._resolved_max_memory = resolved_max_memory
        if resolved_device_map:
            load_kwargs["device_map"] = resolved_device_map
        if resolved_max_memory:
            load_kwargs["max_memory"] = resolved_max_memory
            print(f"[Victim] Auto max_memory: {resolved_max_memory}")
        if resolved_device_map:
            print(f"[Victim] Resolved device_map: {resolved_device_map}")
        self.model = model_cls.from_pretrained(model_name_or_path, **load_kwargs)
        if not resolved_device_map:
            self.model = self.model.to(self.device)
        if self.model.config.pad_token_id is None:
            self.model.config.pad_token_id = self.tokenizer.pad_token_id
        if len(self.tokenizer) > self.model.get_input_embeddings().num_embeddings:
            self.model.resize_token_embeddings(len(self.tokenizer))
        self.model.eval()
        self._loaded = True

    def _get_input_device(self):
        self._ensure_loaded()
        try:
            return self.model.get_input_embeddings().weight.device
        except Exception:
            return torch.device(self.device)

    def _release_model(self):
        if self.model is not None:
            try:
                self.model.to("cpu")
            except Exception:
                pass
            del self.model
        self.model = None
        self._loaded = False
        self._adapter_enabled = False
        self._adapter_config = None
        self._resolved_device_map = None
        self._resolved_max_memory = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _ensure_loaded(self):
        if self._loaded and self.model is not None and self.tokenizer is not None:
            return
        self._load_pretrained(self.model_name)

    def _get_parent_module(self, module_name):
        parts = module_name.split(".")
        parent = self.model
        for part in parts[:-1]:
            parent = getattr(parent, part)
        return parent, parts[-1]

    def _enable_lora(self, rank=8, alpha=16, dropout=0.05, target_modules=None):
        self._ensure_loaded()
        if self._adapter_enabled:
            return

        target_modules = tuple(target_modules or ("q_proj", "v_proj"))
        for param in self.model.parameters():
            param.requires_grad = False

        replaced = []
        for module_name, module in list(self.model.named_modules()):
            if not isinstance(module, nn.Linear):
                continue
            if not module_name.endswith(target_modules):
                continue
            parent, child_name = self._get_parent_module(module_name)
            setattr(parent, child_name, LoRALinear(module, rank=rank, alpha=alpha, dropout=dropout))
            replaced.append(module_name)

        if not replaced:
            raise RuntimeError(f"LoRA target modules not found in model: {target_modules}")

        if hasattr(self.model, "enable_input_require_grads"):
            self.model.enable_input_require_grads()
        if hasattr(self.model, "gradient_checkpointing_enable"):
            self.model.gradient_checkpointing_enable()
        if getattr(self.model.config, "use_cache", None) is not None:
            self.model.config.use_cache = False

        self._adapter_enabled = True
        self._adapter_config = {
            "base_model_name": self.base_model_name,
            "rank": int(rank),
            "alpha": int(alpha),
            "dropout": float(dropout),
            "target_modules": list(target_modules),
            "max_length": int(self.max_length),
        }

        trainable = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in self.model.parameters())
        pct = 100.0 * trainable / max(total, 1)
        print(f"[Victim] LoRA enabled, trainable parameters {trainable}/{total} ({pct:.4f}%)")

    def _collect_adapter_state(self):
        state = {}
        for key, value in self.model.state_dict().items():
            if ".lora_A." in key or ".lora_B." in key:
                state[key] = value.detach().cpu()
        return state

    def save(self, path):
        self._ensure_loaded()
        os.makedirs(path, exist_ok=True)
        self.tokenizer.save_pretrained(path)
        if self._adapter_enabled:
            adapter_state = self._collect_adapter_state()
            torch.save(adapter_state, os.path.join(path, "adapter_model.bin"))
            with open(os.path.join(path, "adapter_config.json"), "w", encoding="utf-8") as f:
                json.dump(self._adapter_config, f, ensure_ascii=False, indent=2)
            print(f"Saved LoRA adapter to {path}")
            return

        self.model.save_pretrained(path)
        print(f"Saved generative audit model to {path}")

    def load(self, path):
        adapter_config_path = os.path.join(path, "adapter_config.json")
        adapter_model_path = os.path.join(path, "adapter_model.bin")
        if os.path.isfile(adapter_config_path) and os.path.isfile(adapter_model_path):
            with open(adapter_config_path, "r", encoding="utf-8") as f:
                adapter_config = json.load(f)
            self.base_model_name = adapter_config["base_model_name"]
            self.model_name = self.base_model_name
            self.max_length = adapter_config.get("max_length", self.max_length)
            self._load_pretrained(self.base_model_name)
            self._enable_lora(
                rank=adapter_config["rank"],
                alpha=adapter_config["alpha"],
                dropout=adapter_config["dropout"],
                target_modules=adapter_config["target_modules"],
            )
            state_dict = torch.load(adapter_model_path, map_location="cpu")
            self.model.load_state_dict(state_dict, strict=False)
            self.model.eval()
            print(f"Loaded LoRA adapter from {path}")
            return

        self._load_pretrained(path)
        print(f"Loaded generative audit model from {path}")

    def _tokenize(self, text, max_length=None, padding=False):
        self._ensure_loaded()
        max_len = max_length or self.max_length
        input_device = self._get_input_device()
        encoded = self.tokenizer(
            text,
            truncation=True,
            padding=padding,
            max_length=max_len,
            return_tensors="pt",
        )
        return {key: value.to(input_device) for key, value in encoded.items()}

    def compute_loss(self, texts, max_length=None):
        """Compute average token loss for each text."""
        self._ensure_loaded()
        self.model.eval()
        losses = []
        with torch.no_grad():
            for text in texts:
                encoded = self._tokenize(text, max_length=max_length, padding=False)
                labels = encoded["input_ids"].clone()
                if "attention_mask" in encoded:
                    labels[encoded["attention_mask"] == 0] = -100
                outputs = self.model(
                    input_ids=encoded["input_ids"],
                    attention_mask=encoded.get("attention_mask"),
                    labels=labels,
                )
                losses.append(float(outputs.loss.detach().cpu().item()))
        return losses

    def _preprocess_batch(self, batch, max_length):
        self._ensure_loaded()
        return self.tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
        )

    def _collate_for_training(self, features):
        batch = self.tokenizer.pad(features, padding=True, return_tensors="pt")
        labels = batch["input_ids"].clone()
        if "attention_mask" in batch:
            labels[batch["attention_mask"] == 0] = -100
        batch["labels"] = labels
        return batch

    def _candidate_train_lengths(self, train_max_length=None, min_train_max_length=64):
        requested = int(train_max_length or self.max_length)
        if train_max_length is None and self.device != "cpu":
            requested = min(requested, 96)
        minimum = max(8, int(min_train_max_length))
        lengths = [requested]
        for fallback in (192, 160, 128, 96, 64):
            if minimum <= fallback < requested:
                lengths.append(fallback)
        if minimum < requested and minimum not in lengths:
            lengths.append(minimum)
        return lengths

    def fine_tune(
        self,
        texts,
        output_dir,
        epochs=1,
        batch_size=1,
        use_lora=True,
        train_max_length=None,
        min_train_max_length=64,
    ):
        """Fine-tune the victim model with dynamic padding and OOM fallback."""
        if not texts:
            raise ValueError("Cannot fine-tune on an empty text list.")

        train_lengths = self._candidate_train_lengths(
            train_max_length=train_max_length,
            min_train_max_length=min_train_max_length,
        )
        last_error_message = None

        for attempt_index, current_max_length in enumerate(train_lengths, start=1):
            dataset = None
            tokenized = None
            dataloader = None
            optimizer = None

            self._release_model()
            self._ensure_loaded()

            dataset = Dataset.from_dict({"text": list(texts)})
            tokenized = dataset.map(
                self._preprocess_batch,
                batched=True,
                fn_kwargs={"max_length": current_max_length},
            )
            tokenized = tokenized.remove_columns(["text"])

            if use_lora:
                self._enable_lora()

            trainable_params = [param for param in self.model.parameters() if param.requires_grad]
            if not trainable_params:
                raise RuntimeError("No trainable parameters found for victim fine-tuning.")

            dataloader = DataLoader(
                tokenized,
                batch_size=batch_size,
                shuffle=True,
                collate_fn=self._collate_for_training,
            )
            optimizer = AdamW(trainable_params, lr=5e-5)
            grad_accum_steps = 4
            use_amp = self.device != "cpu" and torch.cuda.is_available() and not self._resolved_device_map
            scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
            input_device = self._get_input_device()

            try:
                if attempt_index > 1:
                    print(f"[Victim] Retrying fine-tune with train_max_length={current_max_length}")
                if self._resolved_device_map:
                    print(f"[Victim] Fine-tune mode: sharded ({self._resolved_device_map})")
                else:
                    print(f"[Victim] Fine-tune mode: single-device ({self.device})")
                self.model.train()
                global_step = 0
                optimizer.zero_grad(set_to_none=True)

                for epoch_index in range(int(epochs)):
                    running_loss = 0.0
                    for step_index, batch in enumerate(dataloader, start=1):
                        batch = {
                            key: value.to(input_device, non_blocking=False)
                            for key, value in batch.items()
                        }
                        with torch.cuda.amp.autocast(enabled=use_amp):
                            outputs = self.model(**batch)
                            loss = outputs.loss / grad_accum_steps

                        running_loss += float(loss.detach().cpu().item())
                        if use_amp:
                            scaler.scale(loss).backward()
                        else:
                            loss.backward()

                        if step_index % grad_accum_steps == 0 or step_index == len(dataloader):
                            if use_amp:
                                scaler.step(optimizer)
                                scaler.update()
                            else:
                                optimizer.step()
                            optimizer.zero_grad(set_to_none=True)
                            global_step += 1
                            if global_step % 10 == 0:
                                print(
                                    f"[Victim] epoch={epoch_index + 1} step={global_step} "
                                    f"loss={running_loss / max(step_index, 1):.4f}"
                                )
                self.model.eval()
                self.save(output_dir)
                return
            except torch.OutOfMemoryError as exc:
                last_error_message = str(exc)
                print(
                    f"[Victim] CUDA OOM at train_max_length={current_max_length}; "
                    "trying a shorter training length."
                )
            finally:
                if optimizer is not None:
                    del optimizer
                if dataloader is not None:
                    del dataloader
                if tokenized is not None:
                    del tokenized
                if dataset is not None:
                    del dataset
                self._release_model()

        raise torch.OutOfMemoryError(last_error_message or "Victim fine-tuning exhausted all fallback lengths.")


class LossBasedMemberScorer:
    """Calibrate member probabilities from victim losses."""

    def __init__(
        self,
        victim_model,
        member_texts,
        non_member_texts,
        calibration_sample_size=64,
        epsilon=1e-8,
        verbose=False,
    ):
        self.victim_model = victim_model
        self.calibration_sample_size = calibration_sample_size
        self.epsilon = epsilon
        self.verbose = verbose
        self.boundary = 0.0
        self.scale = 1.0
        self.direction = 1.0
        self.member_center = 0.0
        self.non_member_center = 0.0
        self.calibration = {}
        self._fit(member_texts, non_member_texts)

    def _sample_texts(self, texts):
        items = list(texts)
        if len(items) <= self.calibration_sample_size:
            return items
        step = max(1, len(items) // self.calibration_sample_size)
        sampled = items[::step][:self.calibration_sample_size]
        return sampled or items[: self.calibration_sample_size]

    def _fit(self, member_texts, non_member_texts):
        sampled_members = self._sample_texts(member_texts)
        sampled_non_members = self._sample_texts(non_member_texts)
        if not sampled_members or not sampled_non_members:
            raise ValueError("Calibration requires both member and non-member samples.")

        if self.verbose:
            print(
                f"[Stage 1] Calibrating member scorer with "
                f"{len(sampled_members)} members and {len(sampled_non_members)} non-members"
            )

        member_losses = np.asarray(
            self.victim_model.compute_loss(sampled_members),
            dtype=np.float32,
        )
        if self.verbose:
            print("[Stage 1] Member calibration losses ready")
        non_member_losses = np.asarray(
            self.victim_model.compute_loss(sampled_non_members),
            dtype=np.float32,
        )
        if self.verbose:
            print("[Stage 1] Non-member calibration losses ready")

        self.member_center = float(np.median(member_losses))
        self.non_member_center = float(np.median(non_member_losses))
        self.boundary = (self.member_center + self.non_member_center) / 2.0
        self.direction = 1.0 if self.non_member_center >= self.member_center else -1.0

        pooled = np.concatenate([member_losses, non_member_losses], axis=0)
        self.scale = max(
            float(np.std(pooled)),
            abs(self.non_member_center - self.member_center) / 4.0,
            self.epsilon,
        )
        self.calibration = {
            "member_center": self.member_center,
            "non_member_center": self.non_member_center,
            "boundary": self.boundary,
            "scale": self.scale,
            "sampled_members": len(sampled_members),
            "sampled_non_members": len(sampled_non_members),
        }
        if self.verbose:
            print(f"[Stage 1] Calibration complete: boundary={self.boundary:.4f}, scale={self.scale:.4f}")

    def _score_from_loss(self, loss_value):
        logit = self.direction * (self.boundary - float(loss_value)) / max(self.scale, self.epsilon)
        return 1.0 / (1.0 + math.exp(-logit))

    def score_text(self, text):
        loss_value = float(self.victim_model.compute_loss([text])[0])
        return {
            "loss": loss_value,
            "member_prob": float(self._score_from_loss(loss_value)),
        }

    def score_texts(self, texts):
        losses = self.victim_model.compute_loss(texts)
        results = []
        for loss_value in losses:
            results.append({
                "loss": float(loss_value),
                "member_prob": float(self._score_from_loss(loss_value)),
            })
        return results


VictimModel = GenerativeAuditModel
