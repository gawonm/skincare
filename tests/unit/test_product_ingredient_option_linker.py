from scripts.oliveyoung_global_schemas import OliveYoungGlobalProductOption
from scripts.product_candidate_schemas import DataSource
from scripts.product_ingredient_option_linker import ProductIngredientOptionLinker
from scripts.product_ingredient_parse_schemas import IngredientSectionLinkStatus
from scripts.product_ingredient_text_parser import ProductIngredientTextParser


def _option(gds_cd: str, option_name: str) -> OliveYoungGlobalProductOption:
    return OliveYoungGlobalProductOption(
        gdsCd=gds_cd,
        snglOptnNameEn=option_name,
        nrmlAmt=10.0,
        saleAmt=8.0,
        normal_amount_krw=13000,
        sale_amount_krw=10500,
    )


def test_links_section_to_option_with_unique_label_match() -> None:
    text = "[Niacinamide]\nWater, Niacinamide\n\n[Retinol]\nWater, Retinol"
    result = ProductIngredientTextParser().parse(DataSource.OLIVEYOUNG_GLOBAL, "P1", text)
    options = (
        _option("1", "Niacinamide 5 TXA Mask Sheet 1ea"),
        _option("2", "Retinol Niacin Mask Sheet 1ea"),
    )

    linked = ProductIngredientOptionLinker().link(result, options)

    by_label = {s.section_label: s for s in linked.sections}
    assert by_label["Niacinamide"].link_status == IngredientSectionLinkStatus.LINKED
    assert by_label["Niacinamide"].linked_option_gds_cd == "1"
    assert by_label["Retinol"].link_status == IngredientSectionLinkStatus.LINKED
    assert by_label["Retinol"].linked_option_gds_cd == "2"


def test_leaves_ambiguous_when_label_matches_no_option() -> None:
    # 실제로 관찰된 케이스: 옵션명 자체가 "-" (빈 placeholder)라 라벨과 매칭될 옵션이 없다.
    text = "[Tea Tree]\nWater, Melaleuca Alternifolia (Tea Tree) Leaf Oil"
    result = ProductIngredientTextParser().parse(DataSource.OLIVEYOUNG_GLOBAL, "P1", text)
    options = (_option("1", "-"),)

    linked = ProductIngredientOptionLinker().link(result, options)

    section = linked.sections[0]
    assert section.link_status == IngredientSectionLinkStatus.AMBIGUOUS
    assert section.linked_option_gds_cd is None


def test_links_section_when_label_and_option_differ_only_by_whitespace() -> None:
    # 실제 관찰 케이스(GA250631728, GA250833069): 파싱 라벨은 "[Tea Tree]"인데 실제
    # 판매 옵션명은 "Teatree Calming Hydra {N}ea" — 공백 유무만 다르다.
    text = "[Tea Tree]\nWater, Melaleuca Alternifolia (Tea Tree) Leaf Oil"
    result = ProductIngredientTextParser().parse(DataSource.OLIVEYOUNG_GLOBAL, "P1", text)
    options = (
        _option("1", "Teatree Calming Hydra 10ea"),
        _option("2", "Vitamin C Brightening 10ea"),
    )

    linked = ProductIngredientOptionLinker().link(result, options)

    section = linked.sections[0]
    assert section.link_status == IngredientSectionLinkStatus.LINKED
    assert section.linked_option_gds_cd == "1"


def test_leaves_ambiguous_when_label_matches_multiple_options() -> None:
    text = "[Vita C]\nWater, Ascorbic Acid"
    result = ProductIngredientTextParser().parse(DataSource.OLIVEYOUNG_GLOBAL, "P1", text)
    options = (
        _option("1", "Vita C Porestrix Mask Sheet 1ea"),
        _option("2", "Vita C Brightening Mask Sheet 1ea"),
    )

    linked = ProductIngredientOptionLinker().link(result, options)

    section = linked.sections[0]
    assert section.link_status == IngredientSectionLinkStatus.AMBIGUOUS
    assert section.linked_option_gds_cd is None


def test_does_not_touch_no_option_sections() -> None:
    result = ProductIngredientTextParser().parse(
        DataSource.OLIVEYOUNG_GLOBAL, "P1", "Water, Niacinamide"
    )
    options = (_option("1", "Body Lotion 300ml"),)

    linked = ProductIngredientOptionLinker().link(result, options)

    section = linked.sections[0]
    assert section.section_label is None
    assert section.link_status == IngredientSectionLinkStatus.NO_OPTION_SECTIONS
    assert section.linked_option_gds_cd is None
