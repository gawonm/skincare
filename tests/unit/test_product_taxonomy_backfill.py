from uuid import uuid4

import pytest

from data.scripts.product_candidate_schemas import ProductTypeNormalized, ServiceCategory
from data.scripts.product_taxonomy_backfill import (
    ProductTaxonomyBackfillConflictError,
    ProductTaxonomyBackfillPlan,
    ProductTaxonomyBackfillPlanner,
    ProductTaxonomyBackfillRequest,
    ProductTaxonomyBackfillRow,
)


class TestProductTaxonomyBackfillPlanner:
    def test_plans_updates_for_existing_rows_only(self) -> None:
        rows = [self._row("P1", "Hydrating Serum"), self._row("P2", "Daily Care")]

        plan = self._plan(rows)

        assert plan.total_rows == 2
        assert plan.update_rows == 1
        assert plan.unchanged_rows == 1
        assert plan.null_rows_before == 2
        assert plan.null_rows_after == 1
        assert len(plan.updates) == 1
        assert plan.updates[0].source_product_id == "P1"
        assert plan.updates[0].product_type_normalized is ProductTypeNormalized.SERUM
        assert plan.updates[0].service_category is ServiceCategory.ESSENCE_SERUM

    def test_rejects_unexpected_product_count(self) -> None:
        request = ProductTaxonomyBackfillRequest(
            expected_product_count=2,
            rows=[self._row("P1", "Hydrating Serum")],
        )

        with pytest.raises(ProductTaxonomyBackfillConflictError, match="상품 수"):
            ProductTaxonomyBackfillPlanner().plan(request)

    def test_rejects_duplicate_natural_key(self) -> None:
        rows = [self._row("P1", "Hydrating Serum"), self._row("P1", "Daily Cream")]

        with pytest.raises(ProductTaxonomyBackfillConflictError, match="중복 상품 식별자"):
            self._plan(rows)

    def test_rejects_partial_null_taxonomy_pair(self) -> None:
        row = self._row("P1", "Hydrating Serum").model_copy(
            update={"product_type_normalized": ProductTypeNormalized.SERUM}
        )

        with pytest.raises(ProductTaxonomyBackfillConflictError, match="하나만 NULL"):
            self._plan([row])

    def test_does_not_overwrite_conflicting_existing_taxonomy(self) -> None:
        row = self._row("P1", "Hydrating Serum").model_copy(
            update={
                "product_type_normalized": ProductTypeNormalized.CREAM,
                "service_category": ServiceCategory.CREAM_LOTION,
            }
        )

        with pytest.raises(ProductTaxonomyBackfillConflictError, match="자동으로 덮어쓰지"):
            self._plan([row])

    def test_second_plan_is_idempotent_after_applying_first_plan(self) -> None:
        row = self._row("P1", "Hydrating Serum")
        first_plan = self._plan([row])
        update = first_plan.updates[0]
        applied_row = row.model_copy(
            update={
                "product_type_normalized": update.product_type_normalized,
                "service_category": update.service_category,
            }
        )

        second_plan = self._plan([applied_row])

        assert second_plan.update_rows == 0
        assert second_plan.unchanged_rows == 1
        assert second_plan.null_rows_after == 0

    def test_translation_signal_does_not_change_backfill_value(self) -> None:
        untranslated = self._row("P1", "Daily Hydrating Care")
        translated = untranslated.model_copy(update={"display_title": "데일리 수분 세럼"})

        untranslated_plan = self._plan([untranslated])
        translated_plan = self._plan([translated])

        assert untranslated_plan.updates == translated_plan.updates == []
        assert untranslated_plan.null_rows_after == translated_plan.null_rows_after == 1

    def _plan(
        self,
        rows: list[ProductTaxonomyBackfillRow],
    ) -> ProductTaxonomyBackfillPlan:
        return ProductTaxonomyBackfillPlanner().plan(
            ProductTaxonomyBackfillRequest(
                expected_product_count=len(rows),
                rows=rows,
            )
        )

    def _row(self, source_product_id: str, raw_title: str) -> ProductTaxonomyBackfillRow:
        return ProductTaxonomyBackfillRow(
            id=uuid4(),
            source="oliveyoung_global",
            source_product_id=source_product_id,
            raw_title=raw_title,
            display_title=raw_title,
            category3="Moisturizers",
        )
