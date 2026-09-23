"""Claim 기반 상품 후보를 겹치지 않는 루틴 입력으로 줄이는 정책 검증."""

from agent.rag.routine_product_selector import (
    RoutineProductSelectionRequest,
    RoutineProductSelector,
)
from agent.rag.schemas import ProductCategory, ProductRecord


class RoutineProductSelectorFixture:
    def product(self, product_id: str, name: str, category: str) -> ProductRecord:
        return ProductRecord(
            product_id=product_id,
            name=name,
            category=ProductCategory(code=category, name=category),
            source_id="test-products",
            checked_at="2026-09-23",
            is_demo=False,
        )


class TestRoutineProductSelector:
    def test_후보_순서를_유지하며_역할별_한_제품만_선택한다(self) -> None:
        fixture = RoutineProductSelectorFixture()
        products = [
            fixture.product("cream-1", "첫 보습 크림", "크림·로션"),
            fixture.product("cream-2", "두 번째 보습 크림", "크림·로션"),
            fixture.product("serum-1", "피지 세럼", "에센스·세럼"),
            fixture.product("cleanser-1", "순한 폼 클렌저", "클렌저"),
            fixture.product("toner-1", "진정 토너", "토너·패드"),
        ]

        result = RoutineProductSelector().select(
            RoutineProductSelectionRequest(products=products)
        )

        assert [product.product_id for product in result.products] == [
            "cleanser-1",
            "serum-1",
            "cream-1",
        ]

    def test_거절한_후보와_중복_ID를_제외한다(self) -> None:
        fixture = RoutineProductSelectorFixture()
        cleanser = fixture.product("cleanser-1", "폼 클렌저", "클렌저")
        cream = fixture.product("cream-1", "보습 크림", "크림·로션")

        result = RoutineProductSelector().select(
            RoutineProductSelectionRequest(
                products=[cleanser, cleanser.model_copy(deep=True), cream],
                rejected_product_ids=["cleanser-1"],
            )
        )

        assert [product.product_id for product in result.products] == ["cream-1"]

    def test_분류할_수_없는_후보만_있으면_첫_후보_하나를_사용한다(self) -> None:
        fixture = RoutineProductSelectorFixture()
        product = fixture.product("unknown-1", "분류 미상 제품", "기타")

        result = RoutineProductSelector().select(
            RoutineProductSelectionRequest(products=[product])
        )

        assert result.products == [product]
