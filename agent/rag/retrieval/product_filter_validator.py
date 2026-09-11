"""LLM과 복원된 세션의 분류 코드를 현재 조회 지원 목록에 대조한다."""

from pydantic import Field

from agent.rag.schemas import (
    ProductAttributeKind,
    ProductRecord,
    ProductSearchFilters,
    ProductTaxonomy,
    RagModel,
)


class ProductFilterValidation(RagModel):
    filters: ProductSearchFilters
    unsupported_conditions: list[str] = Field(default_factory=list)


class ProductFilterValidator:
    def __init__(self, taxonomy: ProductTaxonomy) -> None:
        self._taxonomy = taxonomy.model_copy(deep=True)

    def normalize(self, filters: ProductSearchFilters) -> ProductFilterValidation:
        result = ProductFilterValidation(filters=filters.model_copy(deep=True))
        for kind in ProductAttributeKind:
            selected = getattr(filters, kind.value)
            if selected is None:
                continue
            canonical = next(
                (item for item in self._taxonomy.options(kind) if item.code == selected.code),
                None,
            )
            if canonical is None:
                result.unsupported_conditions.append(
                    f"현재 지원하지 않는 상품 조건: {kind.value}={selected.code} ({selected.name})"
                )
            else:
                # 모델이 만든 표시 이름을 검증된 카탈로그 이름으로 교체한다.
                setattr(result.filters, kind.value, canonical.model_copy(deep=True))
        return result

    def matches(self, product: ProductRecord, filters: ProductSearchFilters) -> bool:
        for kind in ProductAttributeKind:
            selected = getattr(filters, kind.value)
            actual = getattr(product, kind.value)
            if selected is not None and (actual is None or actual.code != selected.code):
                return False
        return set(filters.ingredient_ids).issubset(product.ingredient_ids)
