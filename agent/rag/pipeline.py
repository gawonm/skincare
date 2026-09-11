"""검색 결과의 관련도와 사용자 조건에 대한 적용성을 분리한다."""

from agent.rag.chunking.field_chunker import FieldChunker
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.ports import EvidenceRetriever, TextEmbedder
from agent.rag.schemas import (
    ApplicabilityAssessment,
    ApplicabilityRequest,
    ApplicabilityStatus,
    EmbeddedChunk,
    EmbeddingRequest,
    EvidenceBundle,
    EvidenceConditions,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    LookupStatus,
    RagDocument,
)

CONDITION_FIELDS = tuple(EvidenceConditions.model_fields)
NORMALIZED_ROUTES = frozenset(("topical", "oral", "intravenous"))


class EvidenceApplicabilityEvaluator:
    """명확한 조건 불일치만 배제하고 미검수·자유문 조건은 검토 대상으로 남긴다."""

    def assess(self, request: ApplicabilityRequest) -> ApplicabilityAssessment:
        record = request.evidence
        known = request.known_conditions
        reasons: list[str] = []
        status = ApplicabilityStatus.APPLICABLE
        for field in CONDITION_FIELDS:
            required = getattr(record.conditions, field)
            if field == "jurisdiction":
                required = record.jurisdiction or required
            actual = getattr(known, field)
            if required is None:
                continue
            if actual is None:
                reasons.append(f"적용 조건 미상: {field}")
            elif required.strip().casefold() != actual.strip().casefold():
                # 농도 범위·동의어·제형의 의미 비교를 문자열 불일치로 확정하지 않는다.
                reasons.append(f"적용 조건 일치 확인 필요: {field} ({required} / {actual})")
                if field == "route" and {required, actual}.issubset(NORMALIZED_ROUTES):
                    status = ApplicabilityStatus.NOT_APPLICABLE
            if reasons and status is not ApplicabilityStatus.NOT_APPLICABLE:
                status = ApplicabilityStatus.LIMITED
        if record.raw_conditions:
            reasons.append(f"원문 조건의 별도 검토 필요: {record.raw_conditions}")
            if status is ApplicabilityStatus.APPLICABLE:
                status = ApplicabilityStatus.LIMITED
        if record.review_status is not EvidenceReviewStatus.VERIFIED or record.is_demo:
            reasons.append("미검수 자료 또는 개발 fixture이므로 실제 적용을 확정할 수 없음")
            if status is ApplicabilityStatus.APPLICABLE:
                status = ApplicabilityStatus.UNKNOWN
        if record.document_version is None:
            reasons.append("출처 버전 미상: 최신성 검토 필요")
            if status is ApplicabilityStatus.APPLICABLE:
                status = ApplicabilityStatus.LIMITED
        return ApplicabilityAssessment(
            evidence_id=record.evidence_id,
            status=status,
            reasons=reasons
            or ["검수된 해당 근거의 명시 조건과 일치; 제품 병용 안전성 확정은 아님"],
        )


class EvidencePipeline:
    """조회 계약을 통해 얻은 자료를 평가하며 DB나 수집 파이프라인을 소유하지 않는다."""

    def __init__(
        self,
        retriever: EvidenceRetriever,
        evaluator: EvidenceApplicabilityEvaluator,
        generator: AnswerGenerator | None = None,
    ) -> None:
        self._retriever = retriever
        self._evaluator = evaluator
        self._generator = generator

    async def run(self, request: EvidenceSearchRequest) -> EvidenceBundle:
        result = await self._retriever.search(request)
        if result.status is LookupStatus.SUCCESS:
            records = {record.evidence_id: record for record in result.records}
            if len(records) != len(result.records):
                raise ValueError("검색 결과에 동일 evidence_id가 중복되었습니다.")
            for hit in result.chunks:
                if records.get(hit.chunk.evidence.evidence_id) != hit.chunk.evidence:
                    raise ValueError("청크의 근거가 적용성 평가용 원문과 일치하지 않습니다.")
        assessments = (
            [
                self._evaluator.assess(
                    ApplicabilityRequest(
                        evidence=record,
                        known_conditions=request.known_conditions,
                    )
                )
                for record in result.records
            ]
            if result.status is LookupStatus.SUCCESS
            else []
        )
        generated = None
        if self._generator is not None and result.status is LookupStatus.SUCCESS:
            excluded_ids = {
                item.evidence_id
                for item in assessments
                if item.status is ApplicabilityStatus.NOT_APPLICABLE
            }
            usable = result.model_copy(
                deep=True,
                update={
                    "records": [
                        record
                        for record in result.records
                        if record.evidence_id not in excluded_ids
                    ],
                    "chunks": [
                        hit
                        for hit in result.chunks
                        if hit.chunk.evidence.evidence_id not in excluded_ids
                    ],
                },
            )
            generated = await self._generator.generate(request, usable)
        return EvidenceBundle(search=result, assessments=assessments, generated=generated)


class RagIngestionPipeline:
    """문서 DTO를 청킹·임베딩한다. 저장과 트랜잭션은 호출자에게 맡긴다."""

    def __init__(self, chunker: FieldChunker, embedder: TextEmbedder) -> None:
        self._chunker = chunker
        self._embedder = embedder

    async def run(self, documents: list[RagDocument]) -> list[EmbeddedChunk]:
        drafts = [draft for document in documents for draft in self._chunker.chunk(document)]
        if not drafts:
            return []
        embedding = await self._embedder.embed(
            EmbeddingRequest(texts=[draft.content for draft in drafts])
        )
        if len(embedding.vectors) != len(drafts):
            raise ValueError("청크와 임베딩 수가 달라 안전하게 연결할 수 없습니다.")
        return [
            EmbeddedChunk(draft=draft, vector=vector, embedding_model=embedding.model)
            for draft, vector in zip(drafts, embedding.vectors, strict=True)
        ]
