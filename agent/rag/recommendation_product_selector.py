"""추천 성분과 연결된 상품을 후보 다양성을 잃지 않고 정리한다."""

from typing import ClassVar

from agent.rag.claim_schemas import (
    IngredientRecommendationCandidate,
    RecommendationBasis,
    RecommendationProductMatch,
    RecommendationProductSelectionRequest,
    RecommendationProductSelectionResult,
)
from agent.rag.schemas import ProductRecord


class RecommendationProductSelector:
    """최초 검색 풀에서 추천 성분과 연결된 모든 상품을 보존한다."""

    _BASIS_ORDER: ClassVar[tuple[RecommendationBasis, ...]] = (
        RecommendationBasis.VERIFIED_EVIDENCE,
        RecommendationBasis.LIMITED_EVIDENCE,
        RecommendationBasis.UNREVIEWED_EVIDENCE,
        RecommendationBasis.CLAIM_ONLY,
    )

    def select(
        self,
        request: RecommendationProductSelectionRequest,
    ) -> RecommendationProductSelectionResult:
        ingredients = {
            candidate.ingredient_id: candidate for candidate in request.ingredients
        }
        products = self._deduplicate(request.products)
        requested_ids = list(ingredients)
        covered_ids = {
            ingredient_id
            for product in products
            for ingredient_id in product.ingredient_ids
            if ingredient_id in ingredients
        }
        # 한 상품이 여러 성분을 덮더라도 역할이 다른 상품까지 제거하면 루틴 입력이 고갈되므로
        # 추천 성분과 하나라도 연결된 최초 검색 풀을 모두 보존한다.
        matches = [
            self._match(product, ingredients)
            for product in products
            if set(product.ingredient_ids).intersection(ingredients)
        ]
        matches.sort(
            key=lambda match: self._BASIS_ORDER.index(match.basis())
        )
        return RecommendationProductSelectionResult(
            matches=matches,
            covered_ingredient_ids=[
                ingredient_id
                for ingredient_id in requested_ids
                if ingredient_id in covered_ids
            ],
            uncovered_ingredient_ids=[
                ingredient_id
                for ingredient_id in requested_ids
                if ingredient_id not in covered_ids
            ],
        )

    def _deduplicate(self, products: list[ProductRecord]) -> list[ProductRecord]:
        unique: dict[str, ProductRecord] = {}
        for product in products:
            identity = self._identity(product)
            existing = unique.get(identity)
            if existing is None:
                unique[identity] = product.model_copy(deep=True)
                continue
            # 같은 판매처 상품이 여러 조회에서 돌아오면 성분 연결을 합쳐 커버리지를 잃지 않는다.
            unique[identity] = existing.model_copy(
                deep=True,
                update={
                    "ingredient_ids": list(
                        dict.fromkeys(existing.ingredient_ids + product.ingredient_ids)
                    )
                },
            )
        return list(unique.values())

    def _identity(self, product: ProductRecord) -> str:
        # fixture처럼 source_id가 카탈로그 단위인 경우가 있어 상품명까지 묶어 실제 SKU를 구분한다.
        return f"{product.source_id}\u0000{product.name.casefold()}"

    def _match(
        self,
        product: ProductRecord,
        ingredients: dict[str, IngredientRecommendationCandidate],
    ) -> RecommendationProductMatch:
        candidates = [
            ingredients[ingredient_id]
            for ingredient_id in product.ingredient_ids
            if ingredient_id in ingredients
        ]
        return RecommendationProductMatch(
            product=product,
            verified_evidence_ingredient_ids=self._ingredient_ids(
                candidates,
                RecommendationBasis.VERIFIED_EVIDENCE,
            ),
            limited_evidence_ingredient_ids=self._ingredient_ids(
                candidates,
                RecommendationBasis.LIMITED_EVIDENCE,
            ),
            unreviewed_evidence_ingredient_ids=self._ingredient_ids(
                candidates,
                RecommendationBasis.UNREVIEWED_EVIDENCE,
            ),
            claim_only_ingredient_ids=self._ingredient_ids(
                candidates,
                RecommendationBasis.CLAIM_ONLY,
            ),
            statement_ids=list(
                dict.fromkeys(
                    statement_id
                    for candidate in candidates
                    for statement_id in candidate.statement_ids
                )
            ),
            evidence_ids=list(
                dict.fromkeys(
                    evidence_id
                    for candidate in candidates
                    for evidence_id in candidate.evidence_ids
                )
            ),
        )

    def _ingredient_ids(
        self,
        candidates: list[IngredientRecommendationCandidate],
        basis: RecommendationBasis,
    ) -> list[str]:
        return [
            candidate.ingredient_id
            for candidate in candidates
            if candidate.basis is basis
        ]
