from agent.rag.retrieval.ingredient_mention_resolver import IngredientMentionResolver
from agent.rag.schemas import IngredientRecord, IngredientResolveRequest, LookupStatus


class TestIngredientMentionResolver:
    def _ingredient(
        self, ingredient_id: str, canonical_name: str, aliases: list[str] | None = None
    ) -> IngredientRecord:
        return IngredientRecord(
            ingredient_id=ingredient_id,
            canonical_name=canonical_name,
            aliases=aliases or [],
            is_demo=False,
        )

    def test_resolves_unambiguous_mention(self) -> None:
        ingredient = self._ingredient("1", "나이아신아마이드")
        result = IngredientMentionResolver([ingredient]).resolve(
            IngredientResolveRequest(name="나이아신아마이드 세럼 자극 있나요?")
        )

        assert result.status is LookupStatus.SUCCESS
        assert result.ingredient == ingredient

    def test_longer_name_wins_over_substring(self) -> None:
        short = self._ingredient("1", "나이아신")
        long = self._ingredient("2", "나이아신아마이드")
        result = IngredientMentionResolver([short, long]).resolve(
            IngredientResolveRequest(name="나이아신아마이드 써도 되나요?")
        )

        assert result.ingredient == long

    def test_ambiguous_name_returns_candidates_without_picking_one(self) -> None:
        first = self._ingredient("1", "동명이인성분", ["공용명"])
        second = self._ingredient("2", "다른표준명", ["공용명"])
        result = IngredientMentionResolver([first, second]).resolve(
            IngredientResolveRequest(name="공용명")
        )

        assert result.status is LookupStatus.SUCCESS
        assert result.ingredient is None
        assert {item.ingredient_id for item in result.ambiguous_candidates} == {"1", "2"}

    def test_unregistered_synonym_is_not_guessed(self) -> None:
        resolver = IngredientMentionResolver([self._ingredient("1", "아스코빅애씨드")])

        result = resolver.resolve(IngredientResolveRequest(name="비타민C"))

        assert result.status is LookupStatus.NO_RESULTS
