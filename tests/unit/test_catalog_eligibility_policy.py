from data.scripts.catalog_eligibility_policy import CatalogEligibilityPolicy, CatalogExclusionReason
from data.scripts.oliveyoung_global_category_schemas import OliveYoungGlobalCategoryHitFields


def _hit(
    prdt_name: str = "Anua PDRN Serum 30ml",
    sold_out_yn: str = "N",
    sell_stat_code: str = "10",
    srch_psblt_yn: str = "Y",
    all_path_ctgr_no_list: list[str] | None = None,
) -> OliveYoungGlobalCategoryHitFields:
    return OliveYoungGlobalCategoryHitFields(
        prdtNo="GA1",
        prdtName=prdt_name,
        brandName="Anua",
        allPathCtgrNoList=all_path_ctgr_no_list or ["1000000001", "1000000008", "1000000009"],
        sellStatCode=sell_stat_code,
        soldOutYn=sold_out_yn,
        srchPsbltYn=srch_psblt_yn,
        optnYn="N",
    )


def test_eligible_when_on_sale_single_product() -> None:
    result = CatalogEligibilityPolicy().evaluate(_hit())
    assert result.is_eligible
    assert result.reasons == ()


def test_excludes_sold_out() -> None:
    result = CatalogEligibilityPolicy().evaluate(_hit(sold_out_yn="Y"))
    assert not result.is_eligible
    assert CatalogExclusionReason.SOLD_OUT in result.reasons


def test_excludes_not_for_sale() -> None:
    result = CatalogEligibilityPolicy().evaluate(_hit(sell_stat_code="90"))
    assert not result.is_eligible
    assert CatalogExclusionReason.NOT_FOR_SALE in result.reasons


def test_excludes_gift_set_category() -> None:
    result = CatalogEligibilityPolicy().evaluate(
        _hit(all_path_ctgr_no_list=["1000000001", "1000000008", "1000000012"])
    )
    assert not result.is_eligible
    assert CatalogExclusionReason.GIFT_SET_CATEGORY in result.reasons


def test_excludes_bundle_keyword_in_title() -> None:
    result = CatalogEligibilityPolicy().evaluate(_hit(prdt_name="Anua Serum 30ml+30ml Set"))
    assert not result.is_eligible
    assert CatalogExclusionReason.BUNDLE_KEYWORD in result.reasons


def test_excludes_double_pack_addon_pattern() -> None:
    # 라이브 API로 실제 확인한 회귀 케이스: "Double Pack (+X)"는 본품에 다른 상품을
    # 얹어 파는 구성이라 "ml+ml" 정규식만으로는 못 잡는다.
    result = CatalogEligibilityPolicy().evaluate(
        _hit(
            prdt_name="ROUND LAB Birch Juice Moisturizing Cream 80ml Double Pack (+Birch Drop Serum 20ml)"
        )
    )
    assert not result.is_eligible
    assert CatalogExclusionReason.BUNDLE_KEYWORD in result.reasons


def test_does_not_exclude_brand_name_containing_plus_sign() -> None:
    # 라이브 API로 실제 확인한 회귀 케이스: "Dr.Jart+"가 브랜드명이라 "+"만 보고 묶음
    # 상품으로 오판하면 안 된다.
    result = CatalogEligibilityPolicy().evaluate(
        _hit(prdt_name="Dr.Jart+ Cicapair Cleansing Foam 150ml")
    )
    assert result.is_eligible


def test_excludes_mini_keyword_in_title() -> None:
    result = CatalogEligibilityPolicy().evaluate(_hit(prdt_name="Anua Serum Mini 10ml"))
    assert not result.is_eligible
    assert CatalogExclusionReason.MINI_KEYWORD in result.reasons


def test_option_limit_checked_separately_from_evaluate() -> None:
    policy = CatalogEligibilityPolicy()
    assert not policy.exceeds_option_limit(1)
    assert policy.exceeds_option_limit(2)
