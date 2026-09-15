"""LLM/DB 호출 없이 `NiaIngredientMatchingStage`의 한글 raw_name fallback을 검증한다."""

from uuid import uuid4

from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.ingredient_schemas import IngredientCandidate
from data.scripts.nia_ingredient_matching_stage import NiaIngredientMatchingStage
from data.scripts.nia_llm_label_schemas import LlmIngredientMention

_NIACINAMIDE_ID = uuid4()
_RETINOL_ID = uuid4()


def _candidates() -> list[IngredientCandidate]:
    return [
        IngredientCandidate(
            ingredient_id=_NIACINAMIDE_ID,
            standard_name_ko="나이아신아마이드",
            standard_name_en="Niacinamide",
            old_names_ko=("나이아신아마이드구명",),
            old_names_en=("Nicotinamide",),
            normalized_name_ko="나이아신아마이드",
            normalized_name_en="niacinamide",
        ),
        IngredientCandidate(
            ingredient_id=_RETINOL_ID,
            standard_name_ko="레티놀",
            standard_name_en="Retinol",
            old_names_ko=(),
            old_names_en=(),
            normalized_name_ko="레티놀",
            normalized_name_en="retinol",
        ),
    ]


def _stage() -> NiaIngredientMatchingStage:
    matcher = IngredientNameMatcher(_candidates(), IngredientNameNormalizer())
    return NiaIngredientMatchingStage(matcher)


class TestNiaIngredientMatchingStage:
    def test_raw_name_ko_present_matches_normally(self) -> None:
        mention = LlmIngredientMention(raw_name="Niacinamide", raw_name_ko="나이아신아마이드")
        result = _stage().resolve(mention)
        assert result["matching_status"] == "matched"
        assert result["ingredient_id"] == str(_NIACINAMIDE_ID)

    def test_raw_name_ko_null_raw_name_korean_falls_back_and_matches(self) -> None:
        """버그 재현 + 수정 확인: raw_name_ko가 비고 raw_name에 한글명이 들어와도 매칭돼야 한다."""
        mention = LlmIngredientMention(raw_name="나이아신아마이드", raw_name_ko=None)
        result = _stage().resolve(mention)
        assert result["matching_status"] == "matched"
        assert result["ingredient_id"] == str(_NIACINAMIDE_ID)

    def test_raw_name_ko_null_raw_name_old_korean_name_falls_back_and_matches(self) -> None:
        mention = LlmIngredientMention(raw_name="나이아신아마이드구명", raw_name_ko=None)
        result = _stage().resolve(mention)
        assert result["matching_status"] == "matched"
        assert result["ingredient_id"] == str(_NIACINAMIDE_ID)

    def test_raw_name_english_inci_matches_normally(self) -> None:
        mention = LlmIngredientMention(raw_name="Retinol", raw_name_ko=None)
        result = _stage().resolve(mention)
        assert result["matching_status"] == "matched"
        assert result["ingredient_id"] == str(_RETINOL_ID)

    def test_ambiguous_family_stays_unresolved_ambiguous_family(self) -> None:
        mention = LlmIngredientMention(
            raw_name="대나무 추출물", raw_name_ko=None, ambiguous_family=True
        )
        result = _stage().resolve(mention)
        assert result["matching_status"] == "unresolved_ambiguous_family"
        assert result["ingredient_id"] is None

    def test_unknown_korean_ingredient_stays_unresolved(self) -> None:
        """한글 fallback을 시도해도 마스터에 없는 성분은 그대로 unresolved여야 한다
        (fuzzy로 억지로 matched 처리하지 않음)."""
        mention = LlmIngredientMention(raw_name="존재하지않는성분명입니다", raw_name_ko=None)
        result = _stage().resolve(mention)
        assert result["matching_status"] == "unresolved"
        assert result["ingredient_id"] is None

    def test_pure_english_unknown_ingredient_stays_unresolved_no_korean_fallback_attempted(
        self,
    ) -> None:
        """한글이 전혀 없으면 fallback을 시도조차 하지 않는다(불필요한 재시도 방지)."""
        mention = LlmIngredientMention(raw_name="UNKNOWN EXTRACT", raw_name_ko=None)
        result = _stage().resolve(mention)
        assert result["matching_status"] == "unresolved"
