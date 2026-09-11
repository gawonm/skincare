"""기존 DB 상품의 taxonomy backfill 계획을 만드는 Data 전용 로직.

이 모듈은 DB에 직접 접근하지 않는다. DB 조회·갱신은 backend repository가 담당하고,
Data 파트는 조회된 상품을 분류해 두 taxonomy 컬럼의 변경 계획만 반환한다.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from data.scripts.product_candidate_schemas import ProductTypeNormalized, ServiceCategory
from data.scripts.product_taxonomy_normalizer import (
    ProductTaxonomyInput,
    ProductTaxonomyNormalizer,
)


class ProductTaxonomyBackfillConflictError(ValueError):
    """기존 분류값이나 상품 식별자가 안전한 backfill 조건과 맞지 않을 때 발생한다."""


class ProductTaxonomyBackfillRow(BaseModel):
    """backend repository가 기존 product에서 읽어 Data 파트에 넘길 최소 필드."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    source: str = Field(min_length=1)
    source_product_id: str = Field(min_length=1)
    raw_title: str
    display_title: str
    category3: str | None = None
    product_type_normalized: ProductTypeNormalized | None = None
    service_category: ServiceCategory | None = None


class ProductTaxonomyBackfillRequest(BaseModel):
    """실행 대상 DB에서 읽은 전체 상품과 사전에 확인한 예상 건수."""

    model_config = ConfigDict(frozen=True)

    expected_product_count: int = Field(gt=0)
    rows: list[ProductTaxonomyBackfillRow]


class ProductTaxonomyBackfillUpdate(BaseModel):
    """backend가 product의 taxonomy 두 컬럼에만 적용할 변경값."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    source: str
    source_product_id: str
    product_type_normalized: ProductTypeNormalized
    service_category: ServiceCategory


class ProductTaxonomyDistributionEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_type_normalized: ProductTypeNormalized | None
    service_category: ServiceCategory | None
    count: int = Field(ge=0)


class ProductTaxonomyBackfillPlan(BaseModel):
    """dry-run 출력과 실제 반영 검증에 함께 사용하는 결정적 계획."""

    model_config = ConfigDict(frozen=True)

    total_rows: int = Field(ge=0)
    update_rows: int = Field(ge=0)
    unchanged_rows: int = Field(ge=0)
    null_rows_before: int = Field(ge=0)
    null_rows_after: int = Field(ge=0)
    distribution_before: list[ProductTaxonomyDistributionEntry]
    distribution_after: list[ProductTaxonomyDistributionEntry]
    updates: list[ProductTaxonomyBackfillUpdate]


class ProductTaxonomyBackfillPlanner:
    """DB 쓰기 없이 기존 상품의 taxonomy 변경 계획을 계산한다."""

    def __init__(self, normalizer: ProductTaxonomyNormalizer | None = None) -> None:
        self._normalizer = normalizer or ProductTaxonomyNormalizer()

    def plan(self, request: ProductTaxonomyBackfillRequest) -> ProductTaxonomyBackfillPlan:
        if len(request.rows) != request.expected_product_count:
            raise ProductTaxonomyBackfillConflictError(
                "상품 수가 예상값과 다릅니다: "
                f"expected={request.expected_product_count}, actual={len(request.rows)}"
            )

        self._validate_unique_keys(request.rows)

        before_pairs: list[tuple[ProductTypeNormalized | None, ServiceCategory | None]] = []
        after_pairs: list[tuple[ProductTypeNormalized | None, ServiceCategory | None]] = []
        updates: list[ProductTaxonomyBackfillUpdate] = []

        for row in request.rows:
            current_pair = (row.product_type_normalized, row.service_category)
            self._validate_current_pair(row)
            before_pairs.append(current_pair)

            result = self._normalizer.classify(
                ProductTaxonomyInput(
                    raw_title=row.raw_title,
                    display_title=row.display_title,
                    category3=row.category3,
                )
            )
            expected_pair = (result.product_type_normalized, result.service_category)
            after_pairs.append(expected_pair)

            if current_pair == expected_pair:
                continue
            if current_pair != (None, None):
                raise ProductTaxonomyBackfillConflictError(
                    "기존 taxonomy 값을 자동으로 덮어쓰지 않습니다: "
                    f"source={row.source}, source_product_id={row.source_product_id}"
                )
            if result.product_type_normalized is None or result.service_category is None:
                continue

            updates.append(
                ProductTaxonomyBackfillUpdate(
                    id=row.id,
                    source=row.source,
                    source_product_id=row.source_product_id,
                    product_type_normalized=result.product_type_normalized,
                    service_category=result.service_category,
                )
            )

        return ProductTaxonomyBackfillPlan(
            total_rows=len(request.rows),
            update_rows=len(updates),
            unchanged_rows=len(request.rows) - len(updates),
            null_rows_before=before_pairs.count((None, None)),
            null_rows_after=after_pairs.count((None, None)),
            distribution_before=self._distribution(before_pairs),
            distribution_after=self._distribution(after_pairs),
            updates=updates,
        )

    def _validate_unique_keys(self, rows: list[ProductTaxonomyBackfillRow]) -> None:
        seen_ids: set[UUID] = set()
        seen_natural_keys: set[tuple[str, str]] = set()
        for row in rows:
            natural_key = (row.source, row.source_product_id)
            if row.id in seen_ids or natural_key in seen_natural_keys:
                raise ProductTaxonomyBackfillConflictError(
                    "중복 상품 식별자가 있습니다: "
                    f"source={row.source}, source_product_id={row.source_product_id}"
                )
            seen_ids.add(row.id)
            seen_natural_keys.add(natural_key)

    def _validate_current_pair(self, row: ProductTaxonomyBackfillRow) -> None:
        if (row.product_type_normalized is None) != (row.service_category is None):
            raise ProductTaxonomyBackfillConflictError(
                "taxonomy 두 컬럼 중 하나만 NULL입니다: "
                f"source={row.source}, source_product_id={row.source_product_id}"
            )
        if row.product_type_normalized is None:
            return
        expected_category = self._normalizer.service_category(row.product_type_normalized)
        if row.service_category is not expected_category:
            raise ProductTaxonomyBackfillConflictError(
                "기존 taxonomy 매핑이 현재 규칙과 다릅니다: "
                f"source={row.source}, source_product_id={row.source_product_id}"
            )

    def _distribution(
        self,
        pairs: list[tuple[ProductTypeNormalized | None, ServiceCategory | None]],
    ) -> list[ProductTaxonomyDistributionEntry]:
        counts: dict[tuple[ProductTypeNormalized | None, ServiceCategory | None], int] = {}
        for pair in pairs:
            counts[pair] = counts.get(pair, 0) + 1

        sorted_pairs = sorted(
            counts,
            key=lambda pair: (
                pair[1].value if pair[1] is not None else "",
                pair[0].value if pair[0] is not None else "",
            ),
        )
        return [
            ProductTaxonomyDistributionEntry(
                product_type_normalized=product_type,
                service_category=service_category,
                count=counts[(product_type, service_category)],
            )
            for product_type, service_category in sorted_pairs
        ]
