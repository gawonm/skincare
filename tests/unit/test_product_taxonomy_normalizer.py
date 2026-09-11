import csv
from datetime import UTC, datetime
from pathlib import Path

from data.scripts.product_candidate_csv_writer import ProductCandidateCsvWriter
from data.scripts.product_candidate_schemas import (
    DataSource,
    MatchStatus,
    PriceBand,
    ProductCandidateRow,
    ProductTypeNormalized,
    ServiceCategory,
    TitleSource,
)
from data.scripts.product_taxonomy_normalizer import (
    ProductTaxonomyInput,
    ProductTaxonomyNormalizer,
    ProductTaxonomyResult,
    TaxonomyDecisionBasis,
)
from models.product import ProductServiceCategory
from models.product import ProductTypeNormalized as ModelProductTypeNormalized


class TestProductTaxonomyNormalizer:
    def test_sun_serum_is_sunscreen_before_serum(self) -> None:
        result = self._classify("Daily Mild Sun Serum SPF 50+")

        assert result.product_type_normalized is ProductTypeNormalized.SUNSCREEN
        assert result.service_category is ServiceCategory.SUNCARE

    def test_cleansing_balm_is_cleanser_before_balm(self) -> None:
        result = self._classify("Green Tea Cleansing Balm")

        assert result.product_type_normalized is ProductTypeNormalized.CLEANSING_BALM
        assert result.service_category is ServiceCategory.CLEANSER

    def test_cleansing_pad_is_cleanser_not_toner_pad(self) -> None:
        result = self._classify("Rice Bran Cleansing Pad 60P")

        assert result.product_type_normalized is ProductTypeNormalized.CLEANSER
        assert result.service_category is ServiceCategory.CLEANSER

    def test_toner_pad_maps_to_toner_pad(self) -> None:
        result = self._classify("Heartleaf 77 Clear Toner Pad")

        assert result.product_type_normalized is ProductTypeNormalized.TONER_PAD
        assert result.service_category is ServiceCategory.TONER_PAD

    def test_generic_mask_maps_to_mask_patch(self) -> None:
        result = self._classify("Expert Pore Ampoule Mask 30ml")

        assert result.product_type_normalized is ProductTypeNormalized.MASK
        assert result.service_category is ServiceCategory.MASK_PATCH

    def test_mask_cream_remains_cream(self) -> None:
        result = self._classify("Anti-Melanin Mask Cream 100ml")

        assert result.product_type_normalized is ProductTypeNormalized.CREAM
        assert result.service_category is ServiceCategory.CREAM_LOTION

    def test_generic_mist_maps_to_other(self) -> None:
        result = self._classify("Collagen Hydrating Mist 100ml")

        assert result.product_type_normalized is ProductTypeNormalized.MIST
        assert result.service_category is ServiceCategory.OTHER

    def test_generic_patch_maps_to_mask_patch(self) -> None:
        result = self._classify("Wrinkle Lifting Patch 6P")

        assert result.product_type_normalized is ProductTypeNormalized.PATCH
        assert result.service_category is ServiceCategory.MASK_PATCH

    def test_body_patch_remains_unclassified(self) -> None:
        result = self._classify("Gapunhan Belly Patch 5ea")

        assert result.product_type_normalized is None
        assert result.service_category is None

    def test_peeling_gel_maps_to_other(self) -> None:
        result = self._classify("Apple Smoothie Peeling Gel", category3="Cleansers")

        assert result.product_type_normalized is ProductTypeNormalized.PEELING
        assert result.service_category is ServiceCategory.OTHER
        assert result.basis is TaxonomyDecisionBasis.TITLE

    def test_single_ambiguous_pad_remains_unclassified(self) -> None:
        result = self._classify("Daily Care Pad 70 Sheets", category3="Moisturizers")

        assert result.product_type_normalized is None
        assert result.service_category is None
        assert result.basis is TaxonomyDecisionBasis.UNCLASSIFIED

    def test_cleanser_category_is_used_as_fallback(self) -> None:
        result = self._classify("Low pH Daily Wash", category3="Cleansers")

        assert result.product_type_normalized is ProductTypeNormalized.CLEANSER
        assert result.basis is TaxonomyDecisionBasis.SOURCE_CATEGORY

    def test_translation_does_not_change_persisted_taxonomy(self) -> None:
        normalizer = ProductTaxonomyNormalizer()
        untranslated = ProductTaxonomyInput(
            raw_title="Daily Hydrating Care",
            display_title="Daily Hydrating Care",
            category3="Moisturizers",
        )
        translated = untranslated.model_copy(update={"display_title": "데일리 수분 세럼"})

        untranslated_result = normalizer.classify(untranslated)
        translated_result = normalizer.classify(translated)

        assert (
            translated_result.product_type_normalized is untranslated_result.product_type_normalized
        )
        assert translated_result.service_category is untranslated_result.service_category
        assert translated_result.product_type_normalized is None
        assert translated_result.display_title_signal is not None
        assert (
            translated_result.display_title_signal.product_type_normalized
            is ProductTypeNormalized.SERUM
        )

    def test_display_title_signal_does_not_override_raw_title(self) -> None:
        normalizer = ProductTaxonomyNormalizer()

        result = normalizer.classify(
            ProductTaxonomyInput(
                raw_title="Daily Cream 50ml",
                display_title="데일리 세럼",
                category3="Moisturizers",
            )
        )

        assert result.product_type_normalized is ProductTypeNormalized.CREAM
        assert result.service_category is ServiceCategory.CREAM_LOTION
        assert result.display_title_signal is not None
        assert result.display_title_signal.product_type_normalized is ProductTypeNormalized.SERUM

    def test_every_normalized_type_has_service_category(self) -> None:
        normalizer = ProductTaxonomyNormalizer()

        mapped = {
            normalizer.service_category(product_type) for product_type in ProductTypeNormalized
        }

        assert mapped == set(ServiceCategory)

    def test_data_and_orm_enum_values_match(self) -> None:
        assert {item.value for item in ProductTypeNormalized} == {
            item.value for item in ModelProductTypeNormalized
        }
        assert {item.value for item in ServiceCategory} == {
            item.value for item in ProductServiceCategory
        }

    def _classify(self, title: str, *, category3: str = "Moisturizers") -> ProductTaxonomyResult:
        return ProductTaxonomyNormalizer().classify(
            ProductTaxonomyInput(
                raw_title=title,
                display_title=title,
                category3=category3,
            )
        )

    def _row(self, title: str, *, category3: str = "Moisturizers") -> ProductCandidateRow:
        return ProductCandidateRow(
            candidate_id="OYC0001",
            source=DataSource.OLIVEYOUNG_GLOBAL,
            search_query="category:1000000008",
            source_product_id="P1",
            raw_title=title,
            display_title=title,
            title_source=TitleSource.UNTRANSLATED,
            brand="Test Brand",
            maker="",
            category1="OliveYoungGlobal",
            category2="Skincare",
            category3=category3,
            lowest_price=10_000,
            highest_price=12_000,
            price_band=PriceBand.BAND_10K,
            image_url="https://example.com/image.jpg",
            local_image_path="data/processed/images/P1.jpg",
            shopping_url="https://example.com/product/P1",
            mall_name="Test Mall",
            product_type="GENERAL_PRODUCT",
            observed_at=datetime(2026, 9, 11, tzinfo=UTC),
            match_status=MatchStatus.MANUAL_REVIEW_REQUIRED,
        )


class TestProductCandidateCsvTaxonomyCompatibility:
    def test_reads_old_csv_without_taxonomy_columns(self, tmp_path: Path) -> None:
        row = TestProductTaxonomyNormalizer()._row("Simple Serum")
        dumped = row.model_dump(
            mode="json",
            exclude={"product_type_normalized", "service_category"},
        )
        dumped["review_reasons"] = ""
        csv_path = tmp_path / "old_products.csv"

        with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(dumped))
            writer.writeheader()
            writer.writerow({key: "" if value is None else value for key, value in dumped.items()})

        loaded = ProductCandidateCsvWriter().read_existing_rows(csv_path)

        assert len(loaded) == 1
        assert loaded[0].product_type_normalized is None
        assert loaded[0].service_category is None
