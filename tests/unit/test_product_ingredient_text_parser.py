from data.scripts.product_candidate_schemas import DataSource
from data.scripts.product_ingredient_parse_schemas import (
    IngredientSectionLinkStatus,
    IngredientTokenParseStatus,
)
from data.scripts.product_ingredient_text_parser import ProductIngredientTextParser


def _parse_single_section_tokens(text: str):
    result = ProductIngredientTextParser().parse(DataSource.OLIVEYOUNG_GLOBAL, "P1", text)
    assert len(result.sections) == 1
    return result.sections[0].tokens


def test_preserves_slash_in_ingredient_name() -> None:
    tokens = _parse_single_section_tokens(
        "Water, Ammonium Acryloyldimethyltaurate/VP Copolymer, Squalane"
    )
    names = [t.matching_name for t in tokens]
    assert "Ammonium Acryloyldimethyltaurate/VP Copolymer" in names


def test_extracts_trailing_percent_concentration() -> None:
    tokens = _parse_single_section_tokens("Centella Asiatica Leaf Water (10.5%), Glycerin")
    target = tokens[0]
    assert target.matching_name == "Centella Asiatica Leaf Water"
    assert target.concentration_text == "(10.5%)"
    assert target.parse_status == IngredientTokenParseStatus.PARSED


def test_extracts_trailing_ppb_concentration_with_internal_comma() -> None:
    tokens = _parse_single_section_tokens("Retinol (1,000ppb), Water")
    target = tokens[0]
    assert target.matching_name == "Retinol"
    assert target.concentration_text == "(1,000ppb)"


def test_keeps_plant_common_name_paren_attached() -> None:
    tokens = _parse_single_section_tokens("Citrus Aurantium Dulcis (Orange) Peel Oil, Water")
    target = tokens[0]
    assert target.matching_name == "Citrus Aurantium Dulcis (Orange) Peel Oil"
    assert target.concentration_text is None


def test_keeps_inline_bracket_synonym_attached() -> None:
    tokens = _parse_single_section_tokens("Ascorbic Acid [Vitamin C] (3,000ppb), Water")
    target = tokens[0]
    assert target.matching_name == "Ascorbic Acid [Vitamin C]"
    assert target.concentration_text == "(3,000ppb)"


def test_rejoins_clean_diol_internal_comma() -> None:
    tokens = _parse_single_section_tokens("Methyl Gluceth-20,1,2-Hexanediol,Glycereth-26")
    names = [t.raw_token for t in tokens]
    assert "1,2-Hexanediol" in names
    assert all(t.parse_status == IngredientTokenParseStatus.PARSED for t in tokens)


def test_flags_suspected_missing_separator_without_guessing() -> None:
    # 실제 수집 데이터에서 관찰된 케이스: "Glycereth-26" + "1,2-Hexanediol" 사이 콤마가
    # 빠져 "Glycereth-261,2-Hexanediol" 로 붙어버림. 억지로 나누지 않고 둘 다 검토로 남긴다.
    tokens = _parse_single_section_tokens(
        "Dipropylene Glycol,Glycereth-261,2-Hexanediol,Propanediol"
    )
    by_raw = {t.raw_token: t for t in tokens}
    assert by_raw["Glycereth-261"].parse_status == IngredientTokenParseStatus.NEEDS_REVIEW
    assert by_raw["2-Hexanediol"].parse_status == IngredientTokenParseStatus.NEEDS_REVIEW
    assert by_raw["Dipropylene Glycol"].parse_status == IngredientTokenParseStatus.PARSED
    assert by_raw["Propanediol"].parse_status == IngredientTokenParseStatus.PARSED


def test_does_not_flag_unrelated_ingredient_ending_in_digits() -> None:
    # "PEG-40" 다음에 우연히 다른 숫자로 시작하는 무관한 성분이 와도 오탐하면 안 된다.
    tokens = _parse_single_section_tokens("PEG-40, 4-t-Butylcyclohexanol, Water")
    by_raw = {t.raw_token: t for t in tokens}
    assert by_raw["PEG-40"].parse_status == IngredientTokenParseStatus.PARSED
    assert by_raw["4-t-Butylcyclohexanol"].parse_status == IngredientTokenParseStatus.PARSED


def test_detects_at_sign_delimiter_when_dominant() -> None:
    # 관찰된 실제 사례: 일부 상품은 콤마 대신 "@"로 구분한다(콤마는 "1,2-Hexanediol"
    # 같은 성분명 내부에만 나온다).
    tokens = _parse_single_section_tokens(
        "Water@Niacinamide@Glycereth-26@1,2-Hexanediol@Caprylic/Capric Triglyceride"
    )
    raw_tokens = [t.raw_token for t in tokens]
    assert raw_tokens == [
        "Water",
        "Niacinamide",
        "Glycereth-26",
        "1,2-Hexanediol",
        "Caprylic/Capric Triglyceride",
    ]
    assert all(t.parse_status == IngredientTokenParseStatus.PARSED for t in tokens)


def test_splits_option_sections_by_bracket_header() -> None:
    text = "[Niacinamide]\nWater, Niacinamide, Glycerin\n\n[Retinol]\nWater, Retinol, Glycerin"
    result = ProductIngredientTextParser().parse(DataSource.OLIVEYOUNG_GLOBAL, "P1", text)

    assert [s.section_label for s in result.sections] == ["Niacinamide", "Retinol"]
    assert [t.raw_token for t in result.sections[0].tokens] == [
        "Water",
        "Niacinamide",
        "Glycerin",
    ]


def test_no_bracket_header_yields_single_unlabeled_section() -> None:
    result = ProductIngredientTextParser().parse(
        DataSource.OLIVEYOUNG_GLOBAL, "P1", "Water, Glycerin, Niacinamide"
    )

    assert len(result.sections) == 1
    section = result.sections[0]
    assert section.section_label is None
    assert section.link_status == IngredientSectionLinkStatus.NO_OPTION_SECTIONS
