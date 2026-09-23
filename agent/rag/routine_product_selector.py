"""상품 후보를 역할별로 보존하고 루틴 대표 상품을 결정적으로 선택한다."""

from typing import ClassVar

from pydantic import Field

from agent.rag.schemas import ProductRecord, RagModel, RoutineProductRole

MAX_SPECIAL_CARE_PRODUCTS = 1


class RoutineProductGroup(RagModel):
    role: RoutineProductRole
    products: list[ProductRecord] = Field(default_factory=list)


class RoutineProductSelectionRequest(RagModel):
    products: list[ProductRecord] = Field(min_length=1)
    rejected_product_ids: list[str] = Field(default_factory=list)


class RoutineProductSelection(RagModel):
    products: list[ProductRecord] = Field(default_factory=list)
    groups: list[RoutineProductGroup] = Field(default_factory=list)
    missing_roles: list[RoutineProductRole] = Field(default_factory=list)


class RoutineProductSelector:
    """전체 후보는 역할별로 남기고 기본 역할별 첫 상품만 루틴 입력으로 고른다."""

    DISPLAY_ROLE_ORDER: ClassVar[tuple[RoutineProductRole, ...]] = (
        RoutineProductRole.CARE,
        RoutineProductRole.MOISTURIZE,
        RoutineProductRole.CLEANSE,
        RoutineProductRole.UNCLASSIFIED,
    )
    APPLICATION_ROLE_ORDER: ClassVar[tuple[RoutineProductRole, ...]] = (
        RoutineProductRole.CLEANSE,
        RoutineProductRole.CARE,
        RoutineProductRole.MOISTURIZE,
    )
    _CATEGORY_TERMS: ClassVar[dict[RoutineProductRole, frozenset[str]]] = {
        RoutineProductRole.CLEANSE: frozenset(
            {"cleanser", "cleansing", "클렌저", "클렌징", "세안"}
        ),
        RoutineProductRole.CARE: frozenset(
            {
                "serum",
                "ampoule",
                "toner",
                "pad",
                "essence",
                "solution",
                "mist",
                "세럼",
                "앰플",
                "토너",
                "패드",
                "에센스",
                "솔루션",
                "미스트",
                "에센스·세럼",
                "토너·패드",
            }
        ),
        RoutineProductRole.MOISTURIZE: frozenset(
            {
                "moisturizer",
                "moisture",
                "cream",
                "lotion",
                "보습",
                "크림",
                "로션",
                "크림·로션",
            }
        ),
    }
    _SPECIALTY_NAME_TERMS: ClassVar[tuple[str, ...]] = (
        "아이크림",
        "eye cream",
        "선크림",
        "sunscreen",
        "sun screen",
        "마스크",
        "팩",
    )

    def select(self, request: RoutineProductSelectionRequest) -> RoutineProductSelection:
        rejected = set(request.rejected_product_ids)
        available = [
            product
            for product in self._unique_products(request.products)
            if product.product_id not in rejected
        ]
        grouped = {
            role: [product for product in available if self.role(product) is role]
            for role in self.DISPLAY_ROLE_ORDER
        }
        selected = [grouped[role][0] for role in self.APPLICATION_ROLE_ORDER if grouped[role]]
        # 미분류 상품도 검수된 Evidence Rule을 가질 수 있으므로 한 상품은 Planner에 넘긴다.
        # 실제 배치는 스케줄러가 공식 사용법 또는 검수 근거의 필수 Rule을 확인한 뒤 결정한다.
        special_candidates = grouped[RoutineProductRole.UNCLASSIFIED][
            :MAX_SPECIAL_CARE_PRODUCTS
        ]
        selected.extend(special_candidates)
        return RoutineProductSelection(
            products=selected,
            groups=[
                RoutineProductGroup(role=role, products=grouped[role])
                for role in self.DISPLAY_ROLE_ORDER
            ],
            missing_roles=[role for role in self.APPLICATION_ROLE_ORDER if not grouped[role]],
        )

    def role(self, product: ProductRecord) -> RoutineProductRole:
        if product.category is None:
            return RoutineProductRole.UNCLASSIFIED
        category_role = self._category_role(product)
        if category_role is RoutineProductRole.MOISTURIZE and any(
            term in product.name.casefold() for term in self._SPECIALTY_NAME_TERMS
        ):
            # 특수 용도명은 넓은 보습 카테고리의 과대 분류만 막는다. 명시적인 클렌저
            # 카테고리보다 먼저 적용하면 '팩 클렌저'까지 미분류되는 역전이 생긴다.
            return RoutineProductRole.UNCLASSIFIED
        return category_role

    def _category_role(self, product: ProductRecord) -> RoutineProductRole:
        if product.category is None:
            return RoutineProductRole.UNCLASSIFIED
        category_terms = {
            product.category.code.casefold(),
            product.category.name.casefold(),
            *(alias.casefold() for alias in product.category.aliases),
        }
        for role in self.APPLICATION_ROLE_ORDER:
            if any(
                known in category_term
                for category_term in category_terms
                for known in self._CATEGORY_TERMS[role]
            ):
                return role
        return RoutineProductRole.UNCLASSIFIED

    def _unique_products(self, products: list[ProductRecord]) -> list[ProductRecord]:
        unique: dict[str, ProductRecord] = {}
        for product in products:
            unique.setdefault(product.product_id, product)
        return list(unique.values())
