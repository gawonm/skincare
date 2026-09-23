"""추천 성분을 빠뜨리지 않는 최소 상품 후보 집합을 선택한다."""

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
    """상품 수를 임의로 자르지 않고 조회 가능한 추천 성분을 모두 덮는다."""

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
        selected = self._minimal_cover(products, covered_ids, ingredients)
        matches = [self._match(product, ingredients) for product in selected]
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

    def _minimal_cover(
        self,
        products: list[ProductRecord],
        covered_ids: set[str],
        ingredients: dict[str, IngredientRecommendationCandidate],
    ) -> list[ProductRecord]:
        uncovered = set(covered_ids)
        selected: list[ProductRecord] = []
        remaining = list(products)
        while uncovered:
            eligible = [
                product
                for product in remaining
                if uncovered.intersection(product.ingredient_ids)
            ]
            if not eligible:
                break
            maximum_coverage = max(
                len(uncovered.intersection(product.ingredient_ids))
                for product in eligible
            )
            coverage_ties = [
                product
                for product in eligible
                if len(uncovered.intersection(product.ingredient_ids))
                == maximum_coverage
            ]
            best_basis = min(
                self._best_basis(product, uncovered, ingredients)
                for product in coverage_ties
            )
            # 목록 순서를 마지막 동률 기준으로 유지해 DB의 안정된 정렬을 보존한다.
            best = next(
                product
                for product in coverage_ties
                if self._best_basis(product, uncovered, ingredients) == best_basis
            )
            selected.append(best)
            uncovered.difference_update(best.ingredient_ids)
            remaining.remove(best)
        return selected

    def _best_basis(
        self,
        product: ProductRecord,
        uncovered: set[str],
        ingredients: dict[str, IngredientRecommendationCandidate],
    ) -> int:
        newly_covered = uncovered.intersection(product.ingredient_ids)
        return min(
            self._BASIS_ORDER.index(ingredients[ingredient_id].basis)
            for ingredient_id in newly_covered
        )

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
