"""`scripts/` 의 근거(Evidence) 수집 단계가 주고받는 Enum 과 Pydantic 모델."""

from pydantic import BaseModel, ConfigDict, Field

from models.evidence import EvidenceRegulateType

_REGULATE_TYPE_BY_LABEL = {
    "금지": EvidenceRegulateType.PROHIBITED,
    "한도": EvidenceRegulateType.LIMITED,
}


class MfdsRestrictedIngredientItem(BaseModel):
    """`getCsmtcsUseRstrcInfoService` 응답의 `item` 하나."""

    model_config = ConfigDict(frozen=True)

    regulate_type_label: str = Field(alias="REGULATE_TYPE")
    ingredient_standard_name: str = Field(alias="INGR_STD_NAME")
    ingredient_english_name: str | None = Field(default=None, alias="INGR_ENG_NAME")
    cas_no: str | None = Field(default=None, alias="CAS_NO")
    ingredient_synonym: str | None = Field(default=None, alias="INGR_SYNONYM")
    country_name: str = Field(alias="COUNTRY_NAME")
    notice_ingredient_name: str | None = Field(default=None, alias="NOTICE_INGR_NAME")
    provision_article: str | None = Field(default=None, alias="PROVIS_ATRCL")
    limit_condition: str | None = Field(default=None, alias="LIMIT_COND")

    @property
    def regulate_type(self) -> EvidenceRegulateType | None:
        return _REGULATE_TYPE_BY_LABEL.get(self.regulate_type_label)


class MfdsImportSummary(BaseModel):
    """`MfdsRestrictedIngredientImporter` 실행 결과 요약."""

    model_config = ConfigDict(frozen=True)

    total_items: int
    inserted: int
    manual_review: int
