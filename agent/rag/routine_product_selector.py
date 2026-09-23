"""상품 후보에서 역할이 겹치지 않는 소규모 루틴 입력을 결정적으로 고른다."""

from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from agent.rag.schemas import ProductRecord, RagModel

MAX_AUTO_ROUTINE_PRODUCTS = 3


class RoutineProductRole(StrEnum):
    CLEANSER = "cleanser"
    TREATMENT = "treatment"
    MOISTURIZER = "moisturizer"


class RoutineProductSelectionRequest(RagModel):
    products: list[ProductRecord] = Field(min_length=1)
    rejected_product_ids: list[str] = Field(default_factory=list)


class RoutineProductSelection(RagModel):
    products: list[ProductRecord] = Field(default_factory=list)


class RoutineProductSelector:
    """후보 순위를 유지하면서 세안·관리·보습 역할별 최대 한 제품을 선택한다."""

    _ROLE_ORDER: ClassVar[tuple[RoutineProductRole, ...]] = (
        RoutineProductRole.CLEANSER,
        RoutineProductRole.TREATMENT,
        RoutineProductRole.MOISTURIZER,
    )
    _ROLE_TERMS: ClassVar[dict[RoutineProductRole, tuple[str, ...]]] = {
        RoutineProductRole.CLEANSER: (
            "cleanser",
            "cleansing",
            "클렌저",
            "클렌징",
            "세안",
        ),
        RoutineProductRole.TREATMENT: (
            "serum",
            "ampoule",
            "toner",
            "essence",
            "solution",
            "mist",
            "shot",
            "세럼",
            "앰플",
            "토너",
            "에센스",
            "솔루션",
            "미스트",
            "샷",
        ),
        RoutineProductRole.MOISTURIZER: (
            "moisturizer",
            "moisture",
            "cream",
            "lotion",
            "보습",
            "크림",
            "로션",
        ),
    }

    def select(self, request: RoutineProductSelectionRequest) -> RoutineProductSelection:
        rejected = set(request.rejected_product_ids)
        available = [
            product
            for product in self._unique_products(request.products)
            if product.product_id not in rejected
        ]
        selected: list[ProductRecord] = []
        selected_ids: set[str] = set()
        for role in self._ROLE_ORDER:
            product = next(
                (
                    candidate
                    for candidate in available
                    if candidate.product_id not in selected_ids
                    and self._role(candidate) is role
                ),
                None,
            )
            if product is not None:
                selected.append(product)
                selected_ids.add(product.product_id)
            if len(selected) == MAX_AUTO_ROUTINE_PRODUCTS:
                break

        if not selected and available:
            # 알 수 없는 분류를 임의 역할로 꾸미지는 않되 루틴 자체가 비는 것은 피한다.
            selected.append(available[0])
        return RoutineProductSelection(products=selected)

    def _unique_products(self, products: list[ProductRecord]) -> list[ProductRecord]:
        unique: dict[str, ProductRecord] = {}
        for product in products:
            unique.setdefault(product.product_id, product)
        return list(unique.values())

    def _role(self, product: ProductRecord) -> RoutineProductRole | None:
        category_terms = (
            [product.category.code, product.category.name, *product.category.aliases]
            if product.category is not None
            else []
        )
        searchable = " ".join([product.name, *category_terms]).casefold()
        for role in self._ROLE_ORDER:
            if any(term.casefold() in searchable for term in self._ROLE_TERMS[role]):
                return role
        return None
