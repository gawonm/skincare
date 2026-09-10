"""주입된 성분 사전만 사용하며 ORM·적재 스크립트의 타입에 의존하지 않는다."""

import re

from pydantic import Field

from agent.rag.schemas import (
    IngredientRecord,
    IngredientResolveRequest,
    IngredientResolveResult,
    LookupStatus,
    RagModel,
)


class IngredientMentionResolver:
    def __init__(self, ingredients: list[IngredientRecord]) -> None:
        self._ingredients = {item.ingredient_id: item.model_copy(deep=True) for item in ingredients}

    def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        query = request.name.casefold().strip()
        exact = [
            item
            for item in self._ingredients.values()
            if query in {name.casefold().strip() for name in [item.canonical_name, *item.aliases]}
        ]
        if exact:
            return self._result(exact)
        # 긴 표기 내부의 짧은 표기를 다른 성분으로 오인하지 않되, 뒤의 별도 언급은 살린다.
        occurrences: list[IngredientMentionSpan] = []
        for item in self._ingredients.values():
            for name in [item.canonical_name, *item.aliases]:
                normalized = name.casefold().strip()
                if not normalized:
                    continue
                for match in re.finditer(re.escape(normalized), query):
                    occurrences.append(
                        IngredientMentionSpan(
                            start=match.start(),
                            end=match.end(),
                            ingredient=item,
                        )
                    )
        accepted = [
            span
            for span in occurrences
            if not any(
                other.start <= span.start
                and span.end <= other.end
                and other.end - other.start > span.end - span.start
                for other in occurrences
            )
        ]
        matches = {span.ingredient.ingredient_id: span.ingredient for span in accepted}
        return self._result(list(matches.values()))

    def _result(self, matches: list[IngredientRecord]) -> IngredientResolveResult:
        if not matches:
            return IngredientResolveResult(status=LookupStatus.NO_RESULTS)
        if len(matches) == 1:
            return IngredientResolveResult(status=LookupStatus.SUCCESS, ingredient=matches[0])
        return IngredientResolveResult(status=LookupStatus.SUCCESS, ambiguous_candidates=matches)


class IngredientMentionSpan(RagModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    ingredient: IngredientRecord
