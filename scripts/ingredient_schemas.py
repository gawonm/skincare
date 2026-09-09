"""`scripts/` 의 성분 적재·매칭 단계가 주고받는 Enum 과 Pydantic 모델.

단계 간에 dict 나 튜플을 그대로 넘기지 않는다.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KciaIngredientRow(BaseModel):
    """KCIA 표준화명칭목록 PDF 한 행."""

    model_config = ConfigDict(frozen=True)

    ingredient_code: int = Field(description="성분코드")
    standard_name_ko: str = Field(description="표준 성분명(국문)")
    standard_name_en: str | None = Field(default=None, description="표준 성분명(영문)")
    old_names_ko: tuple[str, ...] = Field(default=(), description="구 국문 명칭 목록")
    old_names_en: tuple[str, ...] = Field(default=(), description="구 영문 명칭 목록")


class KnowledgedataRow(BaseModel):
    """Knowledgedata.xlsx 한 행."""

    model_config = ConfigDict(frozen=True)

    source_row_no: int = Field(description="'No' 컬럼")
    inci_name: str = Field(description="'성분명(INCI)' 컬럼")
    name_ko: str | None = Field(default=None, description="'한글명' 컬럼")
    efficacy: str | None = Field(default=None, description="효능")
    recommended_skin_types: str | None = Field(default=None, description="권장피부타입")
    precautions: str | None = Field(default=None, description="사용상주의사항(안전성)")
    recommended_concentration: str | None = Field(default=None, description="권장농도")
    compounding_regulation_text: str | None = Field(default=None, description="배합규제")
    raw_material_source: str | None = Field(default=None, description="원료출처")
    source_reference: str | None = Field(default=None, description="원시 데이터 출처")


class KnowledgedataImportSummary(BaseModel):
    """`KnowledgedataImporter` 실행 결과 요약."""

    model_config = ConfigDict(frozen=True)

    total_rows: int
    matched: int
    manual_review: int


class IngredientImportSummary(BaseModel):
    """`KciaIngredientImporter` 실행 결과 요약."""

    model_config = ConfigDict(frozen=True)

    total_rows: int
    inserted: int
    updated: int
    skipped_invalid_rows: int


class IngredientCandidate(BaseModel):
    """매칭에 쓰는 `IngredientMaster` 스냅샷.

    매칭 로직이 DB 세션 없이도 동작하도록, ORM 인스턴스가 아니라 이 Pydantic 모델로 받는다.
    """

    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID
    standard_name_ko: str
    standard_name_en: str | None
    old_names_ko: tuple[str, ...]
    old_names_en: tuple[str, ...]
    normalized_name_ko: str
    normalized_name_en: str | None


class IngredientMatchMethod(StrEnum):
    """매칭 우선순위 5단계 + 매칭 실패."""

    STANDARD_NAME_KO = "standard_name_ko"
    STANDARD_NAME_EN_NORMALIZED = "standard_name_en_normalized"
    OLD_NAME_KO = "old_name_ko"
    OLD_NAME_EN_NORMALIZED = "old_name_en_normalized"
    ANNOTATION_STRIPPED_KO = "annotation_stripped_ko"
    ANNOTATION_STRIPPED_EN_NORMALIZED = "annotation_stripped_en_normalized"
    FUZZY_SINGLE_CANDIDATE = "fuzzy_single_candidate"
    MANUAL_REVIEW = "manual_review"


class IngredientMatchResult(BaseModel):
    """성분명 매칭 결과. `MANUAL_REVIEW` 면 `matched_ingredient_id` 가 없다."""

    model_config = ConfigDict(frozen=True)

    method: IngredientMatchMethod
    matched_ingredient_id: UUID | None = None
    fuzzy_score: float | None = Field(
        default=None, description="FUZZY_SINGLE_CANDIDATE 일 때의 유사도(0~100)"
    )
    review_candidate_ids: tuple[UUID, ...] = Field(
        default=(), description="MANUAL_REVIEW 일 때 검토 참고용 후보 목록"
    )
