"""Utility helpers for device selection and lightweight statistics."""

import math
import os

import numpy as np
import torch


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_cuda_index(device):
    if not isinstance(device, str) or not device.startswith("cuda:"):
        return None
    try:
        return int(device.split(":", 1)[1])
    except (TypeError, ValueError):
        return None


def get_cuda_device_infos():
    if not torch.cuda.is_available():
        return []

    infos = []
    for gpu_index in range(torch.cuda.device_count()):
        free_bytes, total_bytes = torch.cuda.mem_get_info(gpu_index)
        infos.append(
            {
                "index": gpu_index,
                "free_bytes": int(free_bytes),
                "total_bytes": int(total_bytes),
                "free_gib": free_bytes / (1024 ** 3),
                "total_gib": total_bytes / (1024 ** 3),
            }
        )
    return infos


def get_device(device=None):
    """Pick a runtime device, preferring the visible CUDA device with the most free VRAM."""
    if device and device != "auto":
        return device
    if not torch.cuda.is_available():
        return "cpu"

    infos = get_cuda_device_infos()
    if len(infos) == 1:
        return "cuda:0"

    best = max(infos, key=lambda item: item["free_bytes"])
    chosen = f"cuda:{best['index']}"
    print(f"  [Device] choose {chosen} (free {best['free_gib']:.1f} GiB)")
    return chosen


def build_auto_max_memory(
    reserve_gib=2.0,
    usage_fraction=0.85,
    min_usable_gib=3.0,
    cpu_limit_gib=64,
):
    """Build a conservative max_memory map from currently visible CUDA devices."""
    infos = get_cuda_device_infos()
    if not infos:
        return None

    max_memory = {}
    for info in infos:
        usable_gib = info["free_gib"] - reserve_gib
        if usable_gib < min_usable_gib:
            continue
        budget_gib = min(info["total_gib"] * usage_fraction, usable_gib)
        budget_gib = math.floor(budget_gib)
        if budget_gib < 1:
            continue
        max_memory[info["index"]] = f"{int(budget_gib)}GiB"

    if not max_memory:
        return None
    max_memory["cpu"] = f"{int(cpu_limit_gib)}GiB"
    return max_memory


def choose_reference_device(primary_device=None, victim_uses_sharding=False, min_free_gib=4.0):
    if not torch.cuda.is_available():
        return "cpu"
    if victim_uses_sharding:
        return "cpu"

    infos = get_cuda_device_infos()
    if len(infos) < 2:
        return "cpu"

    primary_index = parse_cuda_index(primary_device)
    candidates = [
        info
        for info in infos
        if info["index"] != primary_index and info["free_gib"] >= min_free_gib
    ]
    if not candidates:
        return "cpu"

    best = max(candidates, key=lambda item: item["free_bytes"])
    return f"cuda:{best['index']}"


def load_embedder(model_name="all-MiniLM-L6-v2", device=None):
    from sentence_transformers import SentenceTransformer

    device = get_device(device)
    cache_dir = os.path.join(_PROJECT_ROOT, "models", "sentence-transformers")
    model = SentenceTransformer(model_name, device=device, cache_folder=cache_dir)
    return model


def embed_texts(model, texts, batch_size=32):
    return np.array(model.encode(texts, batch_size=batch_size, show_progress_bar=False))


def cosine_sim(a, b):
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-10)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-10)
    return np.dot(a_norm, b_norm.T)


def compute_entropy(probs):
    probs = np.asarray(probs, dtype=np.float64)
    return -np.sum(probs * np.log(probs + 1e-10))


def compute_modified_entropy(probs):
    probs = np.asarray(probs, dtype=np.float64)
    n = len(probs)
    if n <= 1:
        return 0.0
    return compute_entropy(probs) / np.log(n)


def compute_loss(probs):
    probs = np.asarray(probs, dtype=np.float64)
    return -np.log(np.max(probs) + 1e-10)


def compute_top_gap(probs):
    probs = np.asarray(probs, dtype=np.float64)
    sorted_p = np.sort(probs)[::-1]
    if len(sorted_p) < 2:
        return sorted_p[0]
    return sorted_p[0] - sorted_p[1]


def compute_skewness(probs):
    probs = np.asarray(probs, dtype=np.float64)
    n = len(probs)
    if n < 3:
        return 0.0
    mean = np.mean(probs)
    std = np.std(probs, ddof=0)
    if std < 1e-10:
        return 0.0
    m3 = np.mean((probs - mean) ** 3)
    return m3 / (std ** 3)
