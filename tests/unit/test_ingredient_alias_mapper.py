"""성분 별칭 및 영문/괄호 표기 매퍼 단위 테스트."""

import pytest

from agent.rag.retrieval.ingredient_alias_mapper import CommonIngredientAliasMapper
from agent.rag.schemas import IngredientResolveRequest


class TestCommonIngredientAliasMapper:
    @pytest.fixture
    def mapper(self) -> CommonIngredientAliasMapper:
        return CommonIngredientAliasMapper()

    def test_english_names_map_to_canonical_korean(
        self, mapper: CommonIngredientAliasMapper
    ) -> None:
        """영문 성분명이 표준 한글 성분명으로 매핑된다."""
        assert (
            mapper.map_request(IngredientResolveRequest(name="salicylic acid")).name
            == "살리실릭애씨드"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="niacinamide")).name
            == "나이아신아마이드"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="panthenol")).name
            == "판테놀"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="centella asiatica extract")).name
            == "병풀추출물"
        )

    def test_parenthesized_names_map_to_canonical_korean(
        self, mapper: CommonIngredientAliasMapper
    ) -> None:
        """괄호가 포함된 성분명(영문/약칭 혼합)이 표준 한글 성분명으로 분해 매핑된다."""
        assert (
            mapper.map_request(IngredientResolveRequest(name="BHA (Salicylic Acid)")).name
            == "살리실릭애씨드"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="살리실산 (BHA)")).name
            == "살리실릭애씨드"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="AHA (Glycolic Acid)")).name
            == "글라이콜릭애씨드"
        )

    def test_korean_aliases_map_correctly(
        self, mapper: CommonIngredientAliasMapper
    ) -> None:
        """다빈도 한글 별칭이 표준 한글 성분명으로 매핑된다."""
        assert (
            mapper.map_request(IngredientResolveRequest(name="살리실산")).name
            == "살리실릭애씨드"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="글리콜산")).name
            == "글라이콜릭애씨드"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="알로에 베라 잎즙 파우더")).name
            == "알로에베라잎즙가루"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="알로에베라잎즙파우더")).name
            == "알로에베라잎즙가루"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="카라파 구아이아넨시스 씨드 오일")).name
            == "안디로바씨오일"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="카라파 구아이아넨시스 씨 오일")).name
            == "안디로바씨오일"
        )
        assert (
            mapper.map_request(IngredientResolveRequest(name="양고추냉이 뿌리 추출물")).name
            == "고추냉이뿌리추출물"
        )
        assert (
            mapper.map_request(
                IngredientResolveRequest(name="COCHLEARIA ARMORACIA ROOT EXTRACT")
            ).name
            == "고추냉이뿌리추출물"
        )

    def test_unregistered_name_retains_original(
        self, mapper: CommonIngredientAliasMapper
    ) -> None:
        """등록되지 않은 성분명은 원래 이름을 그대로 반환한다."""
        assert (
            mapper.map_request(IngredientResolveRequest(name="티트리잎오일")).name
            == "티트리잎오일"
        )

    def test_ambiguous_family_detection(
        self, mapper: CommonIngredientAliasMapper
    ) -> None:
        """단일 성분이 아닌 광범위 성분군(BHA, AHA, 티트리)을 올바르게 감지한다."""
        assert mapper.is_ambiguous_family(IngredientResolveRequest(name="BHA")) is True
        assert mapper.is_ambiguous_family(IngredientResolveRequest(name="bha")) is True
        assert mapper.is_ambiguous_family(IngredientResolveRequest(name="AHA")) is True
        assert mapper.is_ambiguous_family(IngredientResolveRequest(name="티트리 오일")) is True
        assert mapper.is_ambiguous_family(IngredientResolveRequest(name="tea tree")) is True
        assert mapper.is_ambiguous_family(IngredientResolveRequest(name="salicylic acid")) is False
        assert mapper.is_ambiguous_family(IngredientResolveRequest(name="나이아신아마이드")) is False
