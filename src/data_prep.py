"""Local dataset loading utilities for the robust auditor pipeline.

The current project is expected to run without relying on online dataset
downloads. All required datasets must already exist under ``dataset/`` in a
``datasets.load_from_disk`` compatible layout.
"""
import os

import numpy as np
from datasets import load_from_disk

from .utils import load_embedder, embed_texts, cosine_sim


DATASET_METADATA = {
    "pubmed_papers": {
        "hf_name": "ccdv/pubmed-summarization",
        "text_field": "article",
        "description": "PubMed biomedical full-text articles",
        "privacy_domain": "medical",
    },
    "us_congressional_bills": {
        "hf_name": "FiscalNote/billsum",
        "text_field": "text",
        "description": "US congressional bill texts",
        "privacy_domain": "legal",
    },
    "enron_emails": {
        "hf_name": "aeslc",
        "text_field": "email_body",
        "description": "Enron-style corporate email bodies",
        "privacy_domain": "personal_communication",
    },
}

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _extract_text(example, metadata):
    """根据数据集元数据中的 text_field 提取文本。"""
    field = metadata.get("text_field")
    if field and field in example:
        val = example[field]
        # 有些数据集的 text 字段是列表（如 ecthr_a），合并为字符串
        if isinstance(val, list):
            return "\n".join(str(v) for v in val)
        return val
    return (example.get("text") or example.get("content") or
            example.get("article") or example.get("document") or
            example.get("description") or example.get("email_body") or
            example.get("report") or example.get("documents") or
            example.get("sentence") or example.get("title"))


def _load_local_dataset(local_dir):
    if not os.path.isdir(local_dir):
        raise FileNotFoundError(
            f"Local dataset directory not found: {local_dir}. "
            "This project is configured to run without online dataset downloads."
        )
    try:
        return load_from_disk(local_dir)
    except Exception as exc:
        raise RuntimeError(f"Failed to load local dataset from {local_dir}: {exc}") from exc


def prepare_datasets(dataset_names=None, build_embeddings=True):
    """加载数据集并构建嵌入向量索引。

    使用所有可用数据，不做数量限制。
    每个数据集会保留原始标签，以便后续划分 member/non-member。
    """
    if dataset_names is None:
        dataset_names = list(DATASET_METADATA.keys())
    embedder = load_embedder() if build_embeddings else None
    store = {}
    for name in dataset_names:
        meta = DATASET_METADATA.get(name, {})
        hf_name = meta.get("hf_name", name)
        print(f"  加载数据集: {name} (hf={hf_name}) ...")

        local_dir = os.path.join("dataset", name)
        ds = _load_local_dataset(local_dir)
        print(f"    从本地加载: {local_dir} ({len(ds)} 条)")

        texts = []
        labels = []
        for ex in ds:
            text = _extract_text(ex, meta)
            if text is None or len(str(text).strip()) < 20:
                continue
            texts.append(str(text))
            labels.append(int(ex.get("label", 0)))

        print(f"    加载 {len(texts)} 篇")
        if not texts:
            print(f"    警告: {name} 没有有效文档，跳过")
            continue

        store[name] = {
            "texts": texts,
            "labels": labels,
            "embeddings": embed_texts(embedder, texts) if embedder is not None else None,
            "metadata": meta,
        }
    return store


def prepare_test_data():
    """Load optional local-only test datasets if they have been prepared."""
    test_sources = [
        # 医学：PubMed validation
        {"name": "ccdv/pubmed-summarization", "split": "validation", "field": "article",
         "similar_to": "pubmed_papers", "topic": "医学文献"},
        # 法案：billsum test
        {"name": "FiscalNote/billsum", "split": "test", "field": "text",
         "similar_to": "us_congressional_bills", "topic": "法案"},
        # 个人邮件：aeslc validation
        {"name": "aeslc", "split": "validation", "field": "email_body",
         "similar_to": "enron_emails", "topic": "企业邮件"},
    ]

    all_samples = []
    for src in test_sources:
        print(f"  加载测试数据集: {src['name']} ({src['split']}) ...")
        local_test_name = f"_test_{src['name']}-{src.get('config','')}-{src['split']}"
        local_test_dir = os.path.join("dataset", local_test_name)
        if not os.path.isdir(local_test_dir):
            print(f"    跳过: 本地未找到 {local_test_dir}")
            continue
        ds = _load_local_dataset(local_test_dir)
        print(f"    从本地加载测试集: {local_test_dir}")

        count = 0
        for ex in ds:
            text = (ex.get(src["field"]) or ex.get("text") or
                    ex.get("content") or ex.get("sentence"))
            if not text or len(text.strip()) < 20:
                continue
            all_samples.append({
                "text": text.strip(),
                "source": src["name"],
                "similar_to": src["similar_to"],
                "topic": src["topic"],
            })
            count += 1
        print(f"    已加载 {count} 条")

    print(f"测试数据集总计: {len(all_samples)} 条")
    return all_samples


def topk_from_store(store, dataset_name, query_emb, k=3):
    """基础 top-k 余弦相似度检索（保留作为后备）。"""
    embs = store[dataset_name]["embeddings"]
    if embs is None:
        raise ValueError(f"数据集 {dataset_name} 未构建 embeddings，无法执行检索")
    sims = cosine_sim(query_emb.reshape(1, -1), embs)[0]
    idx = np.argsort(-sims)[:k]
    return [(store[dataset_name]["texts"][i], float(sims[i])) for i in idx]


def topk_with_mmr(store, dataset_name, query_emb, k=7, lambda_param=0.7, threshold=0.1):
    """MMR (Maximal Marginal Relevance) 多样性检索。

    兼顾相关性和多样性，避免返回近似重复的文档。
    """
    embs = store[dataset_name]["embeddings"]
    if embs is None:
        raise ValueError(f"数据集 {dataset_name} 未构建 embeddings，无法执行 MMR 检索")
    texts = store[dataset_name]["texts"]

    # 计算查询与所有文档的相似度
    sims = cosine_sim(query_emb.reshape(1, -1), embs)[0]

    # 过滤低相关文档
    candidates = [(i, sims[i]) for i in range(len(sims)) if sims[i] >= threshold]
    if not candidates:
        # 如果没有高于阈值的文档，退回到普通 top-k
        idx = np.argsort(-sims)[:k]
        return [(texts[i], float(sims[i])) for i in idx]

    selected = []
    selected_idx = []

    for _ in range(min(k, len(candidates))):
        best_score = -1
        best_cand = None

        for idx_c, sim_c in candidates:
            if idx_c in selected_idx:
                continue

            # 相关性分数
            relevance = sim_c

            # 多样性惩罚：与已选文档的最大相似度
            if selected_idx:
                sel_embs = embs[selected_idx]
                diversity_penalty = np.max(
                    cosine_sim(embs[idx_c].reshape(1, -1), sel_embs)[0]
                )
            else:
                diversity_penalty = 0.0

            mmr_score = lambda_param * relevance - (1 - lambda_param) * diversity_penalty

            if mmr_score > best_score:
                best_score = mmr_score
                best_cand = idx_c

        if best_cand is None:
            break
        selected.append((texts[best_cand], float(sims[best_cand])))
        selected_idx.append(best_cand)

    return selected
