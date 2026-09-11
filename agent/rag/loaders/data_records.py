"""데이터 계층의 조회 DTO를 agent 계약으로 변환한다. ORM·파일 수집은 호출하지 않는다."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from agent.rag.schemas import (
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceScope,
    EvidenceSourceType,
    EvidenceTextKind,
    IngredientRecord,
    RagModel,
    RegulateType,
    RegulatoryConfidence,
)


class IngredientMasterData(RagModel):
    id: UUID
    ingredient_code: int
    standard_name_ko: str = Field(min_length=1)
    standard_name_en: str | None = None
    old_names_ko: list[str] = Field(default_factory=list)
    old_names_en: list[str] = Field(default_factory=list)
    source_version: str = Field(min_length=1)


class EvidenceData(RagModel):
    id: UUID
    ingredient_id: UUID
    claim: str = Field(min_length=1)
    conditions: str | None = None
    jurisdiction: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    published_at: datetime | None = None
    collected_at: datetime
    regulate_type: RegulateType | None = None


class KnowledgeFactData(RagModel):
    id: UUID
    ingredient_id: UUID
    source_row_no: int = Field(ge=1)
    inci_name: str = Field(min_length=1)
    efficacy: str | None = None
    recommended_skin_types: str | None = None
    precautions: str | None = None
    recommended_concentration: str | None = None
    compounding_regulation_text: str | None = None
    source_reference: str | None = None
    regulatory_confidence: RegulatoryConfidence = RegulatoryConfidence.UNVERIFIED


class DataSourceContext(RagModel):
    """데이터 담당자가 제공하는 문서 식별자·실제 위치이며 DB 행 ID와 별개다."""

    source_id: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    document_version: str | None = Field(default=None, min_length=1)


class EvidenceDataRequest(RagModel):
    data: EvidenceData
    source: DataSourceContext


class KnowledgeFactRequest(RagModel):
    data: KnowledgeFactData
    source: DataSourceContext


class DataRecordMapper:
    """현재 존재하는 성분 사전·지식 요약·MFDS 모델의 의미를 유지한다."""

    def ingredient(self, data: IngredientMasterData) -> IngredientRecord:
        aliases = data.old_names_ko + data.old_names_en
        if data.standard_name_en:
            aliases.append(data.standard_name_en)
        return IngredientRecord(
            ingredient_id=str(data.id),
            ingredient_code=data.ingredient_code,
            canonical_name=data.standard_name_ko,
            aliases=list(dict.fromkeys(aliases)),
            source_version=data.source_version,
            is_demo=False,
        )

    def mfds(self, request: EvidenceDataRequest) -> EvidenceRecord:
        data, source = request.data, request.source
        return EvidenceRecord(
            evidence_id=str(data.id),
            source_id=source.source_id,
            source_title=data.source_title,
            document_version=source.document_version,
            locator=source.locator,
            text=data.claim,
            target_ids=[str(data.ingredient_id)],
            source_type=EvidenceSourceType.MFDS,
            text_kind=EvidenceTextKind.SUMMARY,
            scope=EvidenceScope.INGREDIENT,
            topic="cosmetic_use_restriction",
            jurisdiction=data.jurisdiction,
            raw_conditions=data.conditions,
            regulate_type=data.regulate_type,
            published_at=data.published_at.isoformat() if data.published_at else None,
            collected_at=data.collected_at.isoformat(),
            url=data.source_url,
            # 공식 기관 출처라는 사실은 현재 질문에 대한 적용성 검수와 다르다.
            review_status=EvidenceReviewStatus.UNREVIEWED,
            is_demo=False,
        )

    def knowledge(self, request: KnowledgeFactRequest) -> EvidenceRecord:
        data, source = request.data, request.source
        parts = [f"성분: {data.inci_name}"]
        for label, value in (
            ("효능 요약", data.efficacy),
            ("권장 피부타입", data.recommended_skin_types),
            ("주의사항", data.precautions),
            ("권장농도 원문", data.recommended_concentration),
        ):
            if value:
                parts.append(f"{label}: {value}")
        if (
            data.compounding_regulation_text
            and data.regulatory_confidence is RegulatoryConfidence.VERIFIED
        ):
            # 교차 검증 전 배합규제 문구를 생성 모델 원문에 넣으면 국내 확정 규제로 오인할 수 있다.
            parts.append(f"배합규제 원문: {data.compounding_regulation_text}")
        return EvidenceRecord(
            evidence_id=str(data.id),
            source_id=source.source_id,
            source_title=source.source_title,
            document_version=source.document_version,
            locator=f"{source.locator}; row={data.source_row_no}",
            text="\n".join(parts),
            target_ids=[str(data.ingredient_id)],
            source_type=EvidenceSourceType.INGREDIENT_KNOWLEDGE,
            text_kind=EvidenceTextKind.SUMMARY,
            scope=EvidenceScope.INGREDIENT,
            raw_conditions=data.recommended_concentration,
            source_reference=data.source_reference,
            regulatory_confidence=data.regulatory_confidence,
            # 배합규제 검증 상태를 효능·병용 전체의 검수 상태로 승격하지 않는다.
            review_status=EvidenceReviewStatus.UNREVIEWED,
            is_demo=False,
        )
