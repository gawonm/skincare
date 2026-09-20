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

    # --- 2026-09-20 규칙 보정: 실제 상품에서 확인된 명백한 누락/우선순위 오류 ---

    def test_sunscreen_category_is_used_when_title_has_no_type(self) -> None:
        for raw_title, display_title in (
            ("Dr. Bio Eco Sun Moisturizer 100g", "Dr. Bio Eco Sun 모이스처라이저 100g"),
            ("easydew EGFx Downtime Sun 35ml", "이지듀 EGFx Downtime Sun 35ml"),
        ):
            result = self._classify(raw_title, category3="Sunscreen", display_title=display_title)

            assert result.product_type_normalized is ProductTypeNormalized.SUNSCREEN
            assert result.service_category is ServiceCategory.SUNCARE
            assert result.basis is TaxonomyDecisionBasis.SOURCE_CATEGORY

    def test_sheet_masks_category_is_used_when_title_has_no_type(self) -> None:
        for raw_title, display_title in (
            ("MEDIHEAL Vitamin C Brightening 10ea", "메디힐 비타민C 브라이트닝 10매"),
            ("MEDIHEAL Vitamin C Brightening 4ea", "메디힐 비타민C 브라이트닝 4매"),
        ):
            result = self._classify(raw_title, category3="Sheet Masks", display_title=display_title)

            assert result.product_type_normalized is ProductTypeNormalized.SHEET_MASK
            assert result.service_category is ServiceCategory.MASK_PATCH
            assert result.basis is TaxonomyDecisionBasis.SOURCE_CATEGORY

    def test_ampoule_toner_is_toner(self) -> None:
        result = self._classify(
            "[Lage Size] 9wishes Vegan Hydra Ampule Toner 500mL",
            display_title="[Lage Size] 9wishes 비건 Hydra 앰플 토너 500mL",
        )

        assert result.product_type_normalized is ProductTypeNormalized.TONER
        assert result.service_category is ServiceCategory.TONER_PAD

    def test_ampoule_shot_cream_is_cream(self) -> None:
        result = self._classify(
            "CNP Propolis Ampule Active Shot Cream 75ml*2ea",
            display_title="CNP 프로폴리스 앰플 액티브 샷 크림 75ml*2개",
        )

        assert result.product_type_normalized is ProductTypeNormalized.CREAM
        assert result.service_category is ServiceCategory.CREAM_LOTION

    def test_ampule_spelling_is_recognized(self) -> None:
        result = self._classify("CNP Derma+ Answer Active Boost Ampule 30mL", category3="Skincare")

        assert result.product_type_normalized is ProductTypeNormalized.AMPOULE

    def test_final_form_word_after_middle_word_wins(self) -> None:
        cases = {
            "Isntree Onion Newpair Essence Toner 200mL": ProductTypeNormalized.TONER,
            "Dr.Jart+ Ceramidin Skin Barrier Serum Toner 150ml": ProductTypeNormalized.TONER,
            "BIODANCE Skin-Glow Essence Cream 50ml": ProductTypeNormalized.CREAM,
            "Centellian24 Madeca Daily Repair Essence Lotion 100mL": ProductTypeNormalized.LOTION,
            "MdoC Relief Essence Emulsion 100ml": ProductTypeNormalized.EMULSION,
        }
        for title, expected in cases.items():
            assert self._classify(title).product_type_normalized is expected, title

    def test_middle_word_after_final_word_keeps_middle_type(self) -> None:
        # 크림 앰플은 앰플 제품이다. 본체가 뒤에 오는 원칙이 반대 방향에서도 유지된다
        cream_ampoule = self._classify("CLEARDEA. Mucin Collagen Voluming Cream Ampoule 4ml*5ea")
        toner_essence = self._classify("Troubless Mild Clear Toner Essence 200mL")

        assert cream_ampoule.product_type_normalized is ProductTypeNormalized.AMPOULE
        assert toner_essence.product_type_normalized is ProductTypeNormalized.ESSENCE

    def test_ampoule_serum_order_is_unchanged(self) -> None:
        # 앰플과 세럼처럼 같은 묶음 안의 우선순위는 바꾸지 않는다
        result = self._classify("APLB Glutathione Niacinamide Ampoule Serum 40ml")

        assert result.product_type_normalized is ProductTypeNormalized.AMPOULE

    def test_gift_items_in_parentheses_do_not_decide_the_type(self) -> None:
        result = self._classify(
            "d'Alba Vita Toning Capsule Serum Niacinamide 5% 100ml Set (+Toner 2.4ml+Serum 1.5ml+Cream 1.5g)"
        )

        assert result.product_type_normalized is ProductTypeNormalized.SERUM

    def test_moisturizers_category_alone_stays_unclassified(self) -> None:
        # Moisturizers 는 크림·오일·토너가 섞인 넓은 카테고리라 유형을 추정하지 않는다
        result = self._classify(
            "Trilogy Certified Organic Rosehip Oil 20ml", category3="Moisturizers"
        )

        assert result.product_type_normalized is None
        assert result.basis is TaxonomyDecisionBasis.UNCLASSIFIED

    def test_title_type_beats_non_authoritative_source_category(self) -> None:
        # Cleansers 는 제목에 근거가 없을 때만 쓰는 fallback 이다
        result = self._classify("Daily Toner 200ml", category3="Cleansers")

        assert result.product_type_normalized is ProductTypeNormalized.TONER
        assert result.basis is TaxonomyDecisionBasis.TITLE

    def test_sunscreen_category_overrides_title_form_word(self) -> None:
        result = self._classify(
            "d'Alba Watefull UV Essence Vitamin C & Collagen 50ml",
            category3="Sunscreen",
            display_title="달바 워터풀 UV 에센스 비타민C&콜라겐 50ml",
        )

        assert result.product_type_normalized is ProductTypeNormalized.SUNSCREEN
        assert result.service_category is ServiceCategory.SUNCARE
        assert result.basis is TaxonomyDecisionBasis.SOURCE_CATEGORY

    def test_sheet_masks_category_overrides_generic_mask_title(self) -> None:
        result = self._classify(
            "INNISFREE Retinol Cica Ampoule in Hydrogel Mask 4ea", category3="Sheet Masks"
        )

        assert result.product_type_normalized is ProductTypeNormalized.SHEET_MASK
        assert result.basis is TaxonomyDecisionBasis.SOURCE_CATEGORY

    def test_broad_categories_never_override_the_title(self) -> None:
        for category3 in ("Moisturizers", "Skincare", "Body Moisturizers"):
            result = self._classify("Daily Essence 100ml", category3=category3)

            assert result.product_type_normalized is ProductTypeNormalized.ESSENCE, category3

    def test_creme_spelling_is_cream(self) -> None:
        result = self._classify(
            "Abib Jericho Rose Creme Nutrition Tube 75ml",
            display_title="아비브 Jericho 로즈 Creme Nutrition Tube 75ml",
        )

        assert result.product_type_normalized is ProductTypeNormalized.CREAM
        assert result.service_category is ServiceCategory.CREAM_LOTION

    def test_context_dependent_words_stay_unclassified(self) -> None:
        # Milk/Moisturizer/Tonic/Oil 은 유형이 하나로 정해지지 않아 자동 규칙을 두지 않는다
        for title in (
            "Hadalabo Gokujyun Milk 140ml",
            "LANEIGE HOMME Active Water Moisturizer 125ml",
            "isoi Acni Dr. 1st Control Tonic 90ml",
            "ROVECTIN Intense Glow Oil 30ml",
        ):
            result = self._classify(title, category3="Moisturizers")

            assert result.product_type_normalized is None, title
            assert result.basis is TaxonomyDecisionBasis.UNCLASSIFIED, title

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

    def _classify(
        self,
        title: str,
        *,
        category3: str = "Moisturizers",
        display_title: str | None = None,
    ) -> ProductTaxonomyResult:
        return ProductTaxonomyNormalizer().classify(
            self._row(title, category3=category3, display_title=display_title)
        )

    def _row(
        self,
        title: str,
        *,
        category3: str = "Moisturizers",
        display_title: str | None = None,
    ) -> ProductCandidateRow:
        return ProductCandidateRow(
            candidate_id="OYC0001",
            source=DataSource.OLIVEYOUNG_GLOBAL,
            search_query="category:1000000008",
            source_product_id="P1",
            raw_title=title,
            display_title=display_title or title,
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
