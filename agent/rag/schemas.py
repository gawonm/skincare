"""RAG 계층에서 주고받는 Enum 과 Pydantic 모델.

각 단계의 입력과 출력 타입을 여기에 모은다. 단계 간에 dict 를 그대로 넘기지 않는다.

`IngredientVerificationResult`는 서비스 전체 대화 흐름(플로우차트) "①성분 확인" 분기의
출력 계약이다 - `has_verifiable_evidence`가 "확인할 근거가 있나요?"의 답, `answer`+
`sources`가 "검증 결과와 출처 제공", `unverifiable_reason`이 "확인할 수 없는 이유 안내"에
그대로 대응한다.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from models.rag_chunk import RagChunkField, RagConfidenceTier, RagSourceTable


class RagDocumentField(BaseModel):
    """원본 레코드에서 뽑아낸 청킹 대상 필드 하나."""

    model_config = ConfigDict(frozen=True)

    chunk_field: RagChunkField
    chunk_index: int = Field(default=0, description="같은 chunk_field 안에서의 순번")
    content: str


class RagDocumentMetadata(BaseModel):
    """청크에 그대로 복사되는 출처 메타데이터. 조회 시 원본 테이블 조인을 피하기 위함."""

    model_config = ConfigDict(frozen=True)

    confidence_tier: RagConfidenceTier
    source_title: str
    source_url: str | None = None
    citation_refs: tuple[str, ...] = Field(default=(), description="PMID/DOI 등 인용 식별자")
    cites_cir: bool = False


class RagDocument(BaseModel):
    """로더가 만드는, 소스 종류와 무관한 공통 문서 형태."""

    model_config = ConfigDict(frozen=True)

    source_table: RagSourceTable
    ingredient_id: UUID | None = Field(
        default=None, description="NIA Q&A는 한 성분에 매이지 않아 None일 수 있다"
    )
    evidence_id: UUID | None = None
    ingredient_knowledge_fact_id: UUID | None = None
    nia_record_id: str | None = None
    fields: tuple[RagDocumentField, ...] = Field(description="청킹 대상 필드 목록")
    metadata: RagDocumentMetadata


class RagChunkDraft(BaseModel):
    """청킹 단계 출력. `RagDocument` 하나가 여러 `RagChunkDraft`가 된다."""

    model_config = ConfigDict(frozen=True)

    source_table: RagSourceTable
    ingredient_id: UUID | None
    evidence_id: UUID | None
    ingredient_knowledge_fact_id: UUID | None
    nia_record_id: str | None
    chunk_field: RagChunkField
    chunk_index: int
    content: str
    metadata: RagDocumentMetadata


class EmbeddedChunk(BaseModel):
    """임베딩 단계 출력. `RagChunkDraft` + 벡터."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    draft: RagChunkDraft
    vector: tuple[float, ...]
    embedding_model: str


class RetrievalQuery(BaseModel):
    """검색 요청. `ingredient_id`나 `query_text` 중 하나 이상을 채운다."""

    model_config = ConfigDict(frozen=True)

    query_text: str
    ingredient_id: UUID | None = Field(
        default=None, description="주어지면 이 성분과 관련된 청크로만 좁힌다"
    )
    top_k: int = Field(default=8, gt=0)


class RetrievedChunk(BaseModel):
    """검색 결과 청크 하나. 벡터/BM25 랭킹 병합 전후 모두에 쓴다."""

    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    content: str
    chunk_field: RagChunkField
    confidence_tier: RagConfidenceTier
    source_title: str
    source_url: str | None
    citation_refs: tuple[str, ...]
    vector_rank: int | None = Field(default=None, description="벡터 검색 결과에서의 순위(1부터)")
    bm25_rank: int | None = Field(default=None, description="BM25 검색 결과에서의 순위(1부터)")
    fused_score: float | None = Field(default=None, description="RRF로 병합한 최종 점수")


class SourceCitation(BaseModel):
    """`IngredientVerificationResult.sources`의 원소."""

    model_config = ConfigDict(frozen=True)

    source_title: str
    source_url: str | None
    citation_refs: tuple[str, ...]
    confidence_tier: RagConfidenceTier


class AnsweredClaim(BaseModel):
    """답변 문장 하나와 그 문장을 실제로 뒷받침한 출처.

    `IngredientVerificationResult.answer`(합쳐진 문자열)만 두면 "어느 문장이 어느 출처에서
    나왔는지"가 최종 응답에서 사라진다(2026-09-10 코드 리뷰로 발견 - 내부적으로는 문장 단위
    인용 검증을 하면서 그 결과를 밖으로 안 내보내고 있었다). 이 필드가 그 매핑을 보존한다.
    """

    model_config = ConfigDict(frozen=True)

    sentence: str
    sources: tuple[SourceCitation, ...]


class UnverifiableReason(StrEnum):
    """근거가 없을 때 사용자에게 보여줄 이유. 플로우차트의 "확인할 수 없는 이유 안내"에 대응."""

    NO_MATCHING_INGREDIENT = "no_matching_ingredient"
    NO_EVIDENCE_FOUND = "no_evidence_found"
    ONLY_AI_GENERATED_AVAILABLE = "only_ai_generated_available"
    AMBIGUOUS_INGREDIENT = "ambiguous_ingredient"
    NOT_RELEVANT_TO_QUESTION = "not_relevant_to_question"
    MISSING_COMBINATION_EVIDENCE = "missing_combination_evidence"
    CITATION_VALIDATION_FAILED = "citation_validation_failed"


class IngredientVerificationResult(BaseModel):
    """`agent/rag/generation`의 최종 출력. 플로우차트 "①성분 확인" 분기의 출력 계약."""

    model_config = ConfigDict(frozen=True)

    has_verifiable_evidence: bool
    answer: str | None = Field(
        default=None, description="has_verifiable_evidence일 때만 채움. claims를 합친 문자열"
    )
    claims: tuple[AnsweredClaim, ...] = Field(
        default=(),
        description="문장별 출처 매핑. answer는 이걸 보기 좋게 합친 것일 뿐, 근거를 문장 단위로 추적하려면 이걸 본다",
    )
    sources: tuple[SourceCitation, ...] = Field(
        default=(), description="claims의 모든 출처를 중복 제거해 모은 것(요약용)"
    )
    unverifiable_reason: UnverifiableReason | None = Field(
        default=None, description="has_verifiable_evidence가 False일 때만 채움"
    )


class PerIngredientResult(BaseModel):
    """질문에서 언급된 성분 하나에 대한 판정. `RagQueryResult.per_ingredient`의 원소."""

    model_config = ConfigDict(frozen=True)

    matched_text: str = Field(description="질문에서 실제로 매칭된 표기")
    ingredient_id: UUID | None = Field(
        default=None, description="모호해서 해소 못 하면 None(unverifiable_reason=AMBIGUOUS_INGREDIENT)"
    )
    result: IngredientVerificationResult


class RagQueryResult(BaseModel):
    """`RagQueryService.answer()`의 최종 출력.

    복수 성분 질문에서 "성분 A 근거 + 성분 B 근거를 합쳐서 조합 질문에 답한다"를 막기 위해
    개별 성분 판정(`per_ingredient`)과 조합 판정(`combination`)을 분리해서 담는다 - 하나로
    합치면 호출부가 실수로 개별 근거를 조합 근거인 것처럼 오인할 수 있다.
    """

    model_config = ConfigDict(frozen=True)

    per_ingredient: tuple[PerIngredientResult, ...] = Field(
        default=(), description="질문에서 언급된 성분마다 하나씩. 성분이 특정 안 되면 빈 튜플"
    )
    combination: IngredientVerificationResult | None = Field(
        default=None, description="COMBINATION 의도이고 성분이 2개 이상 해소됐을 때만 채움"
    )
    free_text: IngredientVerificationResult | None = Field(
        default=None, description="성분이 하나도 특정되지 않은 상황형 질문일 때만 채움"
    )
