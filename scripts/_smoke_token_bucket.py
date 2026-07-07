"""令牌桶+并发 的真端点小烟测(需 victim API)。抽 6 条真 query,workers=4 + rpm=4 跑一次,
观察真实卡顿下墙钟是否贴近 4-RPM 理论地板。一次性诊断,不写正式产物。
用法: python scripts/_smoke_token_bucket.py
"""
from __future__ import annotations
import sys, time, tempfile
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.llm.factory import build_victim_client, load_llm_profiles, resolve_llm_profile_name
from src.rag.runner import run_rag_and_llm_only
from src.utils.io import load_yaml, read_jsonl, resolve_path, write_jsonl
from src.utils.logger import setup_logging

N = 6
cfg = load_yaml(str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
setup_logging("pcv_mia", log_file=resolve_path(cfg["logging"]["file"]), level="INFO")
gen = cfg.get("generation", {})
profiles = load_llm_profiles(cfg)
name = resolve_llm_profile_name("victim", cli_profile=None, config_profile=gen.get("victim_profile"))
client, prof = build_victim_client(profiles, profile_name=name)

qp = resolve_path(cfg["paths"]["queries_dir"]) / "edgar_paired_queries.jsonl"
accepted = [q for q in read_jsonl(qp) if q.get("accepted", True)][:N]
tmp = Path(tempfile.mkdtemp(prefix="smoke_tb_"))
sub_qp = tmp / "q.jsonl"
write_jsonl(accepted, sub_qp)

rpm = float(gen.get("requests_per_minute", 4))
workers = int(gen.get("max_workers", 4))
calls = N * 2  # RAG + LLM-only
floor_s = (calls - 1) * 60.0 / rpm
print(f"model={prof.get('model')} stream={prof.get('stream')} workers={workers} rpm={rpm}")
print(f"{N} query × 2 = {calls} calls; 4-RPM 理论地板 ≈ {floor_s:.0f}s")

t0 = time.monotonic()
m = run_rag_and_llm_only(
    dataset="edgar", queries_path=sub_qp,
    benchmark_path=resolve_path(cfg["paths"]["benchmark_dir"]) / "edgar_attack_benchmark.jsonl",
    index_dir=resolve_path(cfg["paths"]["indexes_dir"]) / "edgar",
    rag_output_path=tmp / "rag.jsonl", llm_output_path=tmp / "llm.jsonl",
    client=client, top_k=int(cfg.get("retrieval", {}).get("top_k", 5)),
    temperature=float(gen.get("temperature", 0.0)), max_tokens=int(gen.get("max_tokens", 512)),
    timeout=float(gen.get("timeout", 60)), retries=int(gen.get("retries", 2)),
    retry_backoff_base=float(gen.get("retry_backoff_base", 30)),
    retry_backoff_max=float(gen.get("retry_backoff_max", 300)),
    max_workers=workers, requests_per_minute=rpm, resume=False, force=True,
)
elapsed = time.monotonic() - t0
print(f"\n完成: {m['completed_queries']} query, failures={m['failures']}, mode={m['rate_limit_mode']}")
print(f"墙钟 = {elapsed:.0f}s (地板 {floor_s:.0f}s); 比值 = {elapsed/floor_s:.2f}× 地板")
print("✅ 接近地板(≤~1.6×)说明卡顿被并发吸收" if elapsed <= floor_s * 1.6 else "⚠️ 明显高于地板,期间可能有长卡顿")
