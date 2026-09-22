"""combined evidence bundle(PubMed+CIR) chunk 임베딩 단계가 주고받는 Pydantic 모델.

`evidence_db_load_plan_chunks.csv`의 `action`(INSERT/REUSE/REPLACE)만으로 임베딩
대상을 정하고, 실제 벡터/manifest 형태를 여기 모델로 고정한다. DB 세션은 이 단계에서
전혀 쓰지 않는다 - canonical DB write는 아직 승인되지 않았다.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EvidenceEmbeddingAction(StrEnum):
    """load plan의 chunk action 중 실제로 임베딩이 필요한 것만 남긴 부분집합."""

    INSERT = "INSERT"
    REPLACE = "REPLACE"


class EvidenceChunkEmbeddingTarget(BaseModel):
    """임베딩 대상 chunk 한 건(bundle content + load plan action)."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_type: str
    document_source_id: str
    content: str
    content_hash: str
    action: EvidenceEmbeddingAction


class EvidenceEmbeddingRecord(BaseModel):
    """chunk 한 건에 대한 임베딩 결과(벡터 포함, 저장용 산출물)."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    model: str
    dimension: int
    content_hash: str
    vector: list[float]


class EvidenceEmbeddingManifestRow(BaseModel):
    """임베딩 산출물의 경량 요약 한 행(벡터 원본은 제외, git에 커밋 가능한 크기)."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_type: str
    document_source_id: str
    action: EvidenceEmbeddingAction
    model: str
    dimension: int
    content_hash: str
    vector_sha256: str
    vector_l2_norm: float


class EvidenceEmbeddingValidation(BaseModel):
    """검증 결과 요약."""

    model_config = ConfigDict(frozen=True)

    targets: int
    reused_skipped: int
    model: str
    dimension_ok: bool
    content_hash_preserved: bool
    chunk_id_one_to_one: bool
    duplicate_targets: int
    missing_embeddings: int
