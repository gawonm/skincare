"""상품 후보를 역할별로 보존하고 대표 상품을 고르는 정책 검증."""

from agent.rag.routine_product_selector import (
    RoutineProductSelectionRequest,
    RoutineProductSelector,
)
from agent.rag.schemas import ProductCategory, ProductRecord, RoutineProductRole


class RoutineProductSelectorFixture:
    def product(
        self,
        product_id: str,
        name: str,
        category: str,
        directions: str | None = None,
    ) -> ProductRecord:
        return ProductRecord(
            product_id=product_id,
            name=name,
            category=ProductCategory(code=category, name=category),
            directions=directions,
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
        assert [group.role for group in result.groups] == [
            RoutineProductRole.CARE,
            RoutineProductRole.MOISTURIZE,
            RoutineProductRole.CLEANSE,
            RoutineProductRole.UNCLASSIFIED,
        ]
        assert [product.product_id for product in result.groups[0].products] == [
            "serum-1",
            "toner-1",
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

    def test_분류할_수_없는_후보는_특별케어_검증_대상_한_개로_보존한다(self) -> None:
        fixture = RoutineProductSelectorFixture()
        product = fixture.product("unknown-1", "분류 미상 제품", "기타")

        result = RoutineProductSelector().select(
            RoutineProductSelectionRequest(products=[product])
        )

        assert result.products == [product]
        assert result.groups[-1].products == [product]
        assert result.missing_roles == [
            RoutineProductRole.CLEANSE,
            RoutineProductRole.CARE,
            RoutineProductRole.MOISTURIZE,
        ]

    def test_미분류_후보는_사용법이_있어야_특별케어_검증_대상으로_넘긴다(self) -> None:
        fixture = RoutineProductSelectorFixture()
        first = fixture.product(
            "unknown-1",
            "첫 미분류 제품",
            "기타",
            directions="주 1회 저녁에 사용",
        )
        second = fixture.product(
            "unknown-2",
            "두 번째 미분류 제품",
            "기타",
            directions="주 1회 저녁에 사용",
        )

        result = RoutineProductSelector().select(
            RoutineProductSelectionRequest(products=[first, second])
        )

        assert result.products == [first]

    def test_상품명은_역할_분류_근거로_사용하지_않는다(self) -> None:
        fixture = RoutineProductSelectorFixture()
        eye_cream = fixture.product("eye-1", "레티놀 아이크림", "크림·로션")

        result = RoutineProductSelector().select(
            RoutineProductSelectionRequest(products=[eye_cream])
        )

        assert result.groups[-1].products == [eye_cream]
        assert result.products == [eye_cream]
