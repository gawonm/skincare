from uuid import uuid4

from agent.rag.retrieval.ingredient_mention_resolver import IngredientMentionResolver
from scripts.ingredient_schemas import IngredientCandidate


def _candidate(standard_name_ko: str, old_names_ko: tuple[str, ...] = ()) -> IngredientCandidate:
    return IngredientCandidate(
        ingredient_id=uuid4(),
        standard_name_ko=standard_name_ko,
        standard_name_en=None,
        old_names_ko=old_names_ko,
        old_names_en=(),
        normalized_name_ko=standard_name_ko,
        normalized_name_en=None,
    )


def test_resolves_unambiguous_mention() -> None:
    niacinamide = _candidate("나이아신아마이드")
    resolver = IngredientMentionResolver([niacinamide])

    resolutions = resolver.resolve("나이아신아마이드 세럼 자극 있나요?")

    assert len(resolutions) == 1
    assert resolutions[0].ingredient_id == niacinamide.ingredient_id
    assert not resolutions[0].ambiguous


def test_longer_name_wins_over_substring() -> None:
    niacin = _candidate("나이아신")
    niacinamide = _candidate("나이아신아마이드")
    resolver = IngredientMentionResolver([niacin, niacinamide])

    resolutions = resolver.resolve("나이아신아마이드 써도 되나요?")

    # "나이아신"이 "나이아신아마이드" 안의 부분 문자열일 뿐이므로 별도 언급으로 잡히면 안 된다.
    assert len(resolutions) == 1
    assert resolutions[0].ingredient_id == niacinamide.ingredient_id


def test_ambiguous_name_returns_candidates_without_picking_one() -> None:
    a = _candidate("동명이인성분", old_names_ko=("공용명",))
    b = _candidate("다른표준명", old_names_ko=("공용명",))
    resolver = IngredientMentionResolver([a, b])

    resolutions = resolver.resolve("공용명 괜찮나요?")

    assert len(resolutions) == 1
    assert resolutions[0].ambiguous
    assert resolutions[0].ingredient_id is None
    assert set(resolutions[0].candidate_ingredient_ids) == {a.ingredient_id, b.ingredient_id}


def test_unregistered_synonym_is_not_guessed() -> None:
    resolver = IngredientMentionResolver([_candidate("아스코빅애씨드")])

    # "비타민C"가 old_names_ko에 등록돼 있지 않으면 잡지 않는다 - 임의로 확정하지 않는다.
    assert resolver.resolve("비타민C 세럼 괜찮나요?") == []
