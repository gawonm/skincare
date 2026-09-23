"""추천 상품 선택이 성분 커버리지를 임의의 후보 수보다 우선하는지 검증한다."""

from agent.rag.claim_schemas import (
    IngredientRecommendationCandidate,
    RecommendationBasis,
    RecommendationProductSelectionRequest,
)
from agent.rag.recommendation_product_selector import RecommendationProductSelector
from agent.rag.schemas import ProductRecord


class RecommendationProductSelectorFixture:
    def ingredient(
        self,
        ingredient_id: str,
        basis: RecommendationBasis = RecommendationBasis.CLAIM_ONLY,
    ) -> IngredientRecommendationCandidate:
        return IngredientRecommendationCandidate(
            ingredient_id=ingredient_id,
            basis=basis,
            statement_ids=[f"claim:{ingredient_id}"],
        )

    def product(
        self,
        product_id: str,
        ingredient_ids: list[str],
        source_id: str | None = None,
        name: str | None = None,
    ) -> ProductRecord:
        return ProductRecord(
            product_id=product_id,
            name=name or product_id,
            ingredient_ids=ingredient_ids,
            source_id=source_id or f"source:{product_id}",
            checked_at="2026-09-23T00:00:00Z",
            is_demo=False,
        )


class TestRecommendationProductSelector:
    def test_shared_product_covers_multiple_ingredients_with_one_candidate(self) -> None:
        fixture = RecommendationProductSelectorFixture()
        result = RecommendationProductSelector().select(
            RecommendationProductSelectionRequest(
                ingredients=[
                    fixture.ingredient(
                        "ingredient:verified",
                        RecommendationBasis.VERIFIED_EVIDENCE,
                    ),
                    fixture.ingredient("ingredient:claim"),
                ],
                products=[
                    fixture.product(
                        "product:shared",
                        ["ingredient:verified", "ingredient:claim"],
                    )
                ],
            )
        )

        assert len(result.matches) == 1
        assert result.covered_ingredient_ids == [
            "ingredient:verified",
            "ingredient:claim",
        ]
        assert result.uncovered_ingredient_ids == []

    def test_more_than_six_ingredients_are_all_kept_when_products_exist(self) -> None:
        fixture = RecommendationProductSelectorFixture()
        ingredient_ids = [f"ingredient:{index}" for index in range(7)]
        result = RecommendationProductSelector().select(
            RecommendationProductSelectionRequest(
                ingredients=[
                    fixture.ingredient(ingredient_id)
                    for ingredient_id in ingredient_ids
                ],
                products=[
                    fixture.product(f"product:{index}", [ingredient_id])
                    for index, ingredient_id in enumerate(ingredient_ids)
                ],
            )
        )

        assert len(result.matches) == 7
        assert result.covered_ingredient_ids == ingredient_ids
        assert result.uncovered_ingredient_ids == []

    def test_same_source_product_merges_ingredient_coverage(self) -> None:
        fixture = RecommendationProductSelectorFixture()
        result = RecommendationProductSelector().select(
            RecommendationProductSelectionRequest(
                ingredients=[
                    fixture.ingredient("ingredient:a"),
                    fixture.ingredient("ingredient:b"),
                ],
                products=[
                    fixture.product(
                        "product:snapshot-a",
                        ["ingredient:a"],
                        source_id="shop:sku-1",
                        name="같은 상품",
                    ),
                    fixture.product(
                        "product:snapshot-b",
                        ["ingredient:b"],
                        source_id="shop:sku-1",
                        name="같은 상품",
                    ),
                ],
            )
        )

        assert len(result.matches) == 1
        assert result.covered_ingredient_ids == ["ingredient:a", "ingredient:b"]

    def test_ingredient_without_product_is_reported_as_uncovered(self) -> None:
        fixture = RecommendationProductSelectorFixture()
        result = RecommendationProductSelector().select(
            RecommendationProductSelectionRequest(
                ingredients=[
                    fixture.ingredient("ingredient:found"),
                    fixture.ingredient("ingredient:missing"),
                ],
                products=[
                    fixture.product("product:found", ["ingredient:found"])
                ],
            )
        )

        assert result.covered_ingredient_ids == ["ingredient:found"]
        assert result.uncovered_ingredient_ids == ["ingredient:missing"]
