"""全库 NLI v3 入口：支持新 Generator 和完成缓存，冻结判分核心保持不变。"""

from __future__ import annotations

import argparse
import errno
import http.client
import json
import logging
import math
import shutil
import socket
import ssl
import sys
import time
import urllib.error
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.answer_judgment import FormalJudgmentRun, NLIBackend
from src.shared_g.artifacts import ArtifactStore, read_response_adjudications, read_rows
from src.shared_g.scoring import gated_queries, source_scores
from src.shared_g.victim import response_records, validate_responses
from src.utils.hash import sha256_file, sha256_obj, sha256_text
from src.llm.openai_compatible import ChatResult
from src.llm.victim_client import VictimClient


def request_error_details(error: Exception) -> tuple[dict[str, Any], bool]:
    """只提取安全的异常类别；HTTP、证书及格式错误不作为网络波动重试。"""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        reason = current.reason if isinstance(current, urllib.error.URLError) else None
        current = current.__cause__ or (reason if isinstance(reason, BaseException) else None)
        if current is None and not chain[-1].__suppress_context__:
            current = chain[-1].__context__
    details: dict[str, Any] = {"exception_types": [type(item).__name__ for item in chain]}
    http_error = next((item for item in chain if isinstance(item, urllib.error.HTTPError)), None)
    if http_error is not None:
        details["http_status"] = http_error.code
        return details, False
    for prefix, category in (("OpenAI-compatible API error response:", "api_error_response"),
                             ("Unexpected OpenAI-compatible response:", "response_format")):
        if str(error).startswith(prefix):
            details["category"] = category
            return details, False
    if any(isinstance(item, (ssl.SSLCertVerificationError, ValueError, TypeError)) for item in chain):
        return details, False
    network_errnos = {errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET, errno.ETIMEDOUT,
                      errno.ENETDOWN, errno.ENETRESET, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPIPE}
    retryable = any(isinstance(item, (TimeoutError, ConnectionError, socket.gaierror,
                                      http.client.IncompleteRead, ssl.SSLEOFError, ssl.SSLZeroReturnError))
                    or isinstance(item, OSError) and item.errno in network_errnos for item in chain)
    return details, retryable

class AllDatasetJudgmentRun(FormalJudgmentRun):
    """扩展完成缓存、前序检查及网络重连，不更改 query、判分、门控或指标。"""

    def __init__(self, path: str | Path, completed_config: str | Path,
                 root: Path | None = None, *, backend: NLIBackend | None = None) -> None:
        super().__init__(path, root, backend=backend)
        self.completed_run: FormalJudgmentRun | None = None
        if self.parent.config.data.get("reused_inputs"):
            # 新 Generator 仅复用固定输入，回答与判分只来自自己的输出目录。
            if self.scoring_datasets != self.config.datasets:
                raise ValueError("all_dataset_scope_required")
            return
        self.completed_run = FormalJudgmentRun(completed_config, self.config.root)
        if (self.scoring_datasets != self.config.datasets
                or self.parent.config.output != self.completed_run.parent.config.output
                or asdict(self.nli_config) != asdict(self.completed_run.nli_config)
                or self.config.output == self.completed_run.config.output):
            raise ValueError("all_dataset_cache_identity_mismatch")

    def activate(self) -> dict[str, Any]:
        if self.completed_run is None:
            return super().activate()
        self.completed_run.validate(frozen=True)
        result = super().activate()
        for dataset in self.completed_run.scoring_datasets:
            if not self.completed_run.status(dataset)["complete"]:
                continue
            # 只复制同一冻结问答、同一判分参数的完成缓存，不复制旧报告。
            for name in ("initial_responses.jsonl", "followup_responses.jsonl",
                         "initial_judgments.jsonl", "followup_judgments.jsonl", "followup_gate.json"):
                source = ArtifactStore.path(self.completed_run, name, dataset)
                target = ArtifactStore.path(self, name, dataset)
                if not source.exists():
                    continue
                if target.exists():
                    if sha256_file(target) != sha256_file(source):
                        raise RuntimeError("completed_cache_conflict_preserved")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
            if not self.status(dataset)["complete"]:
                raise RuntimeError("completed_cache_incomplete_after_reuse")
        return result

    def _request_with_reconnect(self, client: VictimClient, prompt: str, policy: dict[str, Any],
                                row: dict[str, Any], dataset: str, network_retries: int) -> ChatResult:
        for attempt in range(network_retries + 1):
            row.update(client_attempts=attempt + 1, network_retry_count=attempt)
            try:
                return client.generate_with_metadata(prompt, temperature=policy["temperature"],
                                                     timeout=policy["timeout"], max_tokens=policy["max_tokens"])
            except Exception as error:
                details, retryable = request_error_details(error)
                event = {**details, "attempt": attempt + 1, "retryable_network_error": retryable,
                         "failed_at": datetime.now(timezone.utc).isoformat()}
                row.setdefault("request_errors", []).append(event)
                logging.getLogger(__name__).warning("victim_request_error dataset=%s query_id=%s details=%s",
                                                    dataset, row["query_id"], json.dumps(event))
                if not retryable or attempt == network_retries:
                    raise
                delay = min(2.0 * 2 ** attempt, 30.0)
                logging.getLogger(__name__).warning("victim_reconnect dataset=%s query_id=%s retry=%d/%d wait=%.1fs",
                                                    dataset, row["query_id"], attempt + 1, network_retries, delay)
                time.sleep(delay)
        raise AssertionError("unreachable_network_retry_loop")

    def run_victim(self, dataset: str, followup: bool, max_new: int = 200, *,
                   network_retries: int = 3, request_timeout: float | None = None) -> dict[str, Any]:
        """沿用冻结请求校验，支持有限重连和传输超时覆盖，并记录实际尝试。"""
        import logging
        from src.llm.factory import build_victim_client, llm_profile_identity, load_llm_profiles
        from src.llm.response_validation import strict_response_metadata_error
        from src.shared_g.artifacts import append_request
        from src.shared_g.retrieval import rag_prompt, validate_retrieval

        self.validate(frozen=True)
        if network_retries < 0:
            raise ValueError("nonnegative_network_retries_required")
        if max_new < 1:
            raise ValueError("positive_wave_budget_required")
        timeout = self.config.data["runtime"]["generation"]["timeout"] if request_timeout is None else request_timeout
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("positive_finite_request_timeout_required")
        queries, items, entries = self._data(dataset)
        planned = self._gate(queries, entries) if followup else [q for q in queries if q["arm"] == "initial"]
        if planned is None:
            raise RuntimeError("initial_judgments_incomplete")
        if any(item["response"].get("status") != "completed" for item in items.values()):
            raise RuntimeError("unresolved_or_invalid_victim_response_preserved")
        if any(entry["judgment"]["status"] == "invalid" for entry in entries.values()):
            raise RuntimeError("invalid_judgment_run_incomplete")
        pending = [q for q in planned if q["query_id"] not in items][:max_new]
        if not pending:
            return self._victim_summary(dataset, followup, 0)
        self._require_previous_cells(dataset)
        retrieval = validate_retrieval(self.config, self, dataset)
        profiles = load_llm_profiles({"llm_profiles_path": str(self.config.resolve(self.config.data["runtime"]["llm_profiles_path"]))})
        client, profile = build_victim_client(profiles, profile_name=self.config.data["runtime"]["victim_profile"])
        identity = llm_profile_identity(profile)
        if identity != llm_profile_identity(self.config.profiles()["victim"]):
            raise RuntimeError("victim_client_profile_drift")
        fingerprints = {r.get("system_fingerprint") for ds in self.config.datasets for flag in (False, True)
                        for r in self.responses(ds, flag) if r.get("provider_model_id")}
        if len(fingerprints) > 1:
            raise RuntimeError("victim_fingerprint_drift")
        # 只覆盖本次传输等待时限，冻结配置与生成参数保持原值。
        policy = {**self.config.data["runtime"]["generation"], "timeout": timeout}
        retrieval_hash = sha256_file(self.path("retrieval.jsonl", dataset))
        name = "followup_responses.jsonl" if followup else "initial_responses.jsonl"
        for count, query in enumerate(pending, 1):
            found = retrieval[query["query_id"]]
            context, prompt = rag_prompt(self.config, query, found["retrieved_chunks"])
            if sha256_text(context) != found["context_sha256"] or sha256_text(prompt) != found["prompt_sha256"]:
                raise RuntimeError("victim_prompt_drift")
            row = {"request_key": query["query_id"], "query_id": query["query_id"], "source_key": query["source_key"],
                   "arm": query["arm"], "slot_index": query["slot_index"], "status": "attempt_started",
                   "retrieval_sha256": retrieval_hash, "prompt_sha256": sha256_text(prompt), "profile_identity": identity,
                   "request_timeout_seconds": timeout,
                   "network_retry_policy": {"max_retries": network_retries, "backoff_base_seconds": 2.0,
                                            "backoff_max_seconds": 30.0, "http_errors_retried": False}}
            append_request(ArtifactStore.path(self, name, dataset), row)
            try:
                result = self._request_with_reconnect(client, prompt, policy, row, dataset, network_retries)
                error = strict_response_metadata_error(result.content, provider_model_id=result.provider_model_id,
                    provider_request_id=result.provider_request_id, called_at=result.called_at,
                    expected_model_id=profile["model"], configured_model_version=profile["model_version"])
                valid = not error and result.retry_count == 0 and (not fingerprints or result.system_fingerprint in fingerprints)
                row.update(status="completed" if valid else "invalid_provider_response", response=result.content,
                           response_sha256=sha256_text(result.content), provider_model_id=result.provider_model_id,
                           provider_request_id=result.provider_request_id, system_fingerprint=result.system_fingerprint,
                           called_at=result.called_at, input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                           latency_ms=result.latency_ms, retry_count=result.retry_count)
                if not valid:
                    row["validation_code"] = error.split(":", 1)[0] if error else "retry_or_fingerprint_drift"
                fingerprints.add(result.system_fingerprint)
            except Exception as error:
                row.update(status="uncertain_transport", error_type=type(error).__name__)
            row["record_sha256"] = sha256_obj(row)
            append_request(ArtifactStore.path(self, name, dataset), row)
            logging.getLogger(__name__).info("victim dataset=%s phase=%s new=%d planned_new=%d status=%s",
                                            dataset, "followup" if followup else "initial", count, len(pending), row["status"])
            if row["status"] != "completed":
                self.score(dataset)
                raise RuntimeError("victim_invalid_response_stop_preserve_evidence")
            time.sleep(policy["request_interval_seconds"])
        return self._victim_summary(dataset, followup, len(pending))

    def _require_previous_cells(self, dataset: str) -> None:
        if self.completed_run is None:
            return super()._require_previous_cells(dataset)
        if dataset not in self.scoring_datasets:
            raise ValueError("dataset_not_enabled_for_new_judgment")
        for previous in self.config.datasets[:self.config.datasets.index(dataset)]:
            if self.status(previous)["complete"]:
                continue
            # 已开始的新 NLI cell 必须完成，不能回退到旧版掩盖缺失或失败。
            if any(ArtifactStore.path(self, name, previous).exists() for name in (
                    "initial_responses.jsonl", "followup_responses.jsonl",
                    "initial_judgments.jsonl", "followup_judgments.jsonl")):
                raise RuntimeError(f"previous_dataset_incomplete:{previous}")
            self.parent.validate(frozen=True)
            config = self.parent.config
            queries = [q for q in read_rows(self.parent.path("query_plan.jsonl")) if q["dataset"] == previous]
            sources = [s for s in read_rows(self.parent.path("source_manifest.jsonl")) if s["dataset"] == previous]
            initial = response_records(self.parent, previous, False)
            followup = response_records(self.parent, previous, True)
            policy = {"matcher": config.data["answer_policy"]["matcher"],
                      "adjudications": read_response_adjudications(self.parent)}
            validate_responses(config, self.parent, previous, [q for q in queries if q["arm"] == "initial"], initial)
            expected = gated_queries(queries, initial, **policy)
            validate_responses(config, self.parent, previous, expected, followup)
            source_scores(sources, queries, initial, followup, config.data["scoring"]["lambda"], **policy)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/v25_shared_g_formal_nli_v3_all.yaml"))
    parser.add_argument("--completed-config", type=Path, default=Path("configs/v25_shared_g_formal_nli_v3.yaml"))
    stages = parser.add_subparsers(dest="stage", required=True)
    stages.add_parser("activate")
    for name in ("status", "retrieve", "run-initial", "score", "run-followup", "report"):
        stage = stages.add_parser(name)
        stage.add_argument("--dataset", required=True, choices=("nfcorpus", "scidocs", "trec-covid"))
        if name in {"retrieve", "run-initial", "score", "run-followup"}:
            stage.add_argument("--max-new", type=int, default=20000 if name == "score" else 200)
        if name in {"run-initial", "run-followup"}:
            stage.add_argument("--network-retries", type=int, default=3,
                               help="只对确认的网络异常重连，默认3次；0关闭")
            stage.add_argument("--request-timeout", type=float,
                               help="本次请求超时秒数；省略时沿用冻结配置，新响应保存实际时限")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run = AllDatasetJudgmentRun(args.config, args.completed_config)
    if args.stage == "activate":
        metadata = run.activate()
        result = {"version": metadata["version"], "output_dir": str(run.config.output),
                  "scoring_datasets": list(run.scoring_datasets), "new_victim_calls": 0}
    elif args.stage in {"run-initial", "run-followup"}:
        result = run.run_victim(args.dataset, args.stage == "run-followup", args.max_new,
                               network_retries=args.network_retries, request_timeout=args.request_timeout)
    elif args.stage in {"retrieve", "score"}:
        result = getattr(run, args.stage)(args.dataset, args.max_new)
    else:
        result = getattr(run, args.stage)(args.dataset)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), flush=True)
    if result.get("status") == "invalid":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
