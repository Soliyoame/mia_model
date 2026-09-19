"""Run strict, low-cost readiness checks for the three v21 model roles."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.baselines.ia_shadow import normalize_shadow_answer  # noqa: E402
from src.llm.factory import (  # noqa: E402
    build_role_chat_client,
    load_llm_profiles,
)
from src.llm.response_validation import strict_response_metadata_error  # noqa: E402
from src.rag.embeddings import resolve_hf_model_source  # noqa: E402
from src.utils.hash import sha256_file  # noqa: E402
from src.utils.io import load_yaml, resolve_path, write_json  # noqa: E402


EXPECTED_PYTHON = Path(r"D:\python\anaconda\envs\mia_model\python.exe")
ROLE_PROFILES = {
    "luna": ("sibling", "luna_query_generator"),
    "shadow": ("ia_shadow", "qwen3_4b_ia_shadow"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rag-config", default="configs/rag_config_v21.yaml")
    parser.add_argument(
        "--roles",
        default="luna,shadow,victim",
        help="Comma-separated subset of luna,shadow,victim",
    )
    parser.add_argument(
        "--output",
        default="artifacts/v21/preflight/model_roles_preflight.json",
    )
    return parser.parse_args()


def _runtime_gate() -> dict[str, Any]:
    import torch

    if Path(sys.executable).resolve() != EXPECTED_PYTHON.resolve():
        raise RuntimeError(
            f"Wrong Python runtime: {sys.executable}; expected {EXPECTED_PYTHON}"
        )
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    return {
        "python": sys.executable,
        "torch": torch.__version__,
        "cuda_available": True,
        "cuda_device": torch.cuda.get_device_name(0),
    }


def _call_role(profiles: dict[str, Any], public_role: str) -> dict[str, Any]:
    role, profile_name = ROLE_PROFILES[public_role]
    client, profile = build_role_chat_client(
        profiles,
        role,
        profile_name=profile_name,
    )
    expected_content = "READY" if public_role == "luna" else "Yes"
    prompt = (
        "Return exactly READY and no other text."
        if public_role == "luna"
        else "Document: The sky appears blue.\nQuestion: Does the document say the sky appears blue?"
    )
    result = client.chat_with_metadata(
        prompt,
        temperature=0.0,
        timeout=float(profile.get("timeout", 120.0)),
        max_tokens=8,
    )
    error = strict_response_metadata_error(
        result.content,
        provider_model_id=result.provider_model_id,
        provider_request_id=result.provider_request_id,
        called_at=result.called_at,
        expected_model_id=str(profile.get("model") or ""),
        configured_model_version=str(profile.get("model_version") or ""),
    )
    if error is None:
        if public_role == "shadow":
            normalized = normalize_shadow_answer(result.content)
            if normalized != expected_content:
                error = (
                    f"schema_mismatch: expected={expected_content!r} "
                    f"actual={result.content.strip()!r}"
                )
        elif result.content.strip() != expected_content:
            error = (
                f"schema_mismatch: expected={expected_content!r} "
                f"actual={result.content.strip()!r}"
            )
    return {
        "status": "passed" if error is None else "failed",
        "profile": profile_name,
        "provider": profile.get("provider"),
        "requested_model": profile.get("model"),
        "configured_model_version": profile.get("model_version"),
        "actual_model_id": result.provider_model_id,
        "request_id": result.provider_request_id,
        "system_fingerprint": result.system_fingerprint,
        "called_at": result.called_at,
        "latency_ms": result.latency_ms,
        "response_schema": expected_content,
        "validation_error": error,
    }


def _victim_readiness(profiles: dict[str, Any]) -> dict[str, Any]:
    profile = dict(profiles["victim"]["profiles"]["gemma2_2b_primary"])
    model = str(profile.get("model") or "")
    revision = str(profile.get("model_version") or "")
    result = {
        "profile": "gemma2_2b_primary",
        "provider": profile.get("provider"),
        "requested_model": model,
        "configured_model_version": revision,
        "local_files_only": profile.get("local_files_only"),
        "device": profile.get("device"),
        "dtype": profile.get("dtype"),
        "quantization": profile.get("quantization"),
        "batch_size": profile.get("batch_size"),
    }
    try:
        source = Path(
            resolve_hf_model_source(
                model,
                revision=revision,
                local_files_only=True,
            )
        )
        result.update(
            {
                "status": "passed",
                "resolved_snapshot": str(source),
            }
        )
    except Exception as exc:  # readiness artifact must preserve the blocker
        result.update(
            {
                "status": "blocked_model_not_cached",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    return result


def main() -> int:
    args = parse_args()
    requested_roles = [part.strip() for part in args.roles.split(",") if part.strip()]
    unknown = sorted(set(requested_roles) - {"luna", "shadow", "victim"})
    if unknown:
        raise ValueError(f"Unknown roles: {unknown}")
    rag_config_path = resolve_path(args.rag_config)
    profiles = load_llm_profiles(load_yaml(rag_config_path))
    checks: dict[str, Any] = {}
    for role in requested_roles:
        try:
            checks[role] = (
                _victim_readiness(profiles)
                if role == "victim"
                else _call_role(profiles, role)
            )
        except Exception as exc:
            checks[role] = {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
    all_passed = all(item.get("status") == "passed" for item in checks.values())
    artifact = {
        "protocol_version": "pcv-mia-v21",
        "method_version": "pcv-rag-only-source-v21",
        "status": "passed" if all_passed else "blocked",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime": _runtime_gate(),
        "rag_config_path": str(rag_config_path),
        "rag_config_sha256": sha256_file(rag_config_path),
        "checks": checks,
        "formal_calls_authorized": False,
    }
    output_path = resolve_path(args.output)
    write_json(artifact, output_path)
    print(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
