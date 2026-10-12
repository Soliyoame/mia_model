"""各阶段共享的持久化记录类型。"""

from typing import Any, Literal, TypedDict

Arm = Literal["initial", "correct_anchor", "remote_only"]
ARMS = ("correct_anchor", "remote_only")
SCORE_KEYS = ("local_only", *ARMS)
GROUPS = ("KB_Member", "True_Non_Member")


class CandidateRecord(TypedDict):
    source_key: str
    dataset: str
    document_id: str
    source_hash: str
    normalized_text_hash: str
    source_order_rank: str
    candidate_rank: int
    history_raw_document_reused: bool
    prior_v24_raw_document_reused: bool


class SourceRecord(CandidateRecord):
    group: str


class FactBundle(TypedDict):
    initial_facts: list[dict[str, str]]
    remote_target: dict[str, str]
    anchored_followups: list[dict[str, str]]
    no_anchor_followups: list[dict[str, str]]
    region_diagnostics: dict[str, Any]


class QueryRecord(TypedDict):
    query_id: str
    source_key: str
    dataset: str
    arm: Arm
    slot_index: int
    question: str
    retrieval_query: str
    answer: str
    answer_aliases: list[str]
    claim: str
    anchor: str | None
    anchor_claim: str | None
    region_diagnostics: dict[str, Any]


class RetrievalRecord(TypedDict):
    query_id: str
    dataset: str
    query_plan_sha256: str
    index_identity: str
    retrieved_chunks: list[dict[str, Any]]
    context_sha256: str
    prompt_sha256: str


class ResponseRecord(TypedDict, total=False):
    request_key: str
    query_id: str
    source_key: str
    status: str
    response: str
    response_sha256: str
    provider_model_id: str
    provider_request_id: str
    system_fingerprint: str | None
    called_at: str
    input_tokens: int | None
    output_tokens: int | None


class ScoreRecord(TypedDict):
    source_key: str
    dataset: str
    group: str
    initial_bits: list[int]
    local_only: float
    correct_anchor: float
    remote_only: float
    correct_anchor_bits: list[int]
    remote_only_bits: list[int]
