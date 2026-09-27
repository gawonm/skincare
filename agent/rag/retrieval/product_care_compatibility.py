"""활성 자극 회복 요청에서 명시적인 각질 제거 상품을 제외한다."""

import re
from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from agent.rag.schemas import CareContext, ProductRecord, RagModel


class ProductCareMismatchReason(StrEnum):
    ACTIVE_IRRITATION_EXFOLIATION_PRODUCT = "active_irritation_exfoliation_product"


class ProductCareCompatibilityAssessment(RagModel):
    mismatch_reasons: list[ProductCareMismatchReason] = Field(default_factory=list)

    def is_incompatible(self) -> bool:
        return bool(self.mismatch_reasons)


class ProductCareCompatibilityPolicy:
    """상품명·사용법에 각질 제거가 명시된 경우만 보수적으로 판정한다."""

    _EXFOLIATION_CUES: ClassVar[tuple[str, ...]] = (
        "각질 제거",
        "각질제거",
        "스크럽",
        "필링",
        "exfoliat",
        "peeling",
        "살리실산",
        "글리콜산",
    )
    _ACID_EXFOLIANT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\b(?:aha|bha|pha|lha)\b"
    )

    def assess(
        self,
        care_context: CareContext,
        product: ProductRecord,
    ) -> ProductCareCompatibilityAssessment:
        if not care_context.requires_recovery_first():
            return ProductCareCompatibilityAssessment()
        searchable_text = " ".join(
            value
            for value in (
                product.name,
                product.category.name if product.category is not None else "",
                product.directions or "",
            )
        ).casefold()
        if not (
            any(cue.casefold() in searchable_text for cue in self._EXFOLIATION_CUES)
            or self._ACID_EXFOLIANT_PATTERN.search(searchable_text)
        ):
            return ProductCareCompatibilityAssessment()
        return ProductCareCompatibilityAssessment(
            mismatch_reasons=[
                ProductCareMismatchReason.ACTIVE_IRRITATION_EXFOLIATION_PRODUCT
            ]
        )
