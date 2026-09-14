"""NIA statement의 성분 언급(`LlmIngredientMention`)을 ingredient master와 deterministic하게
연결한다. fuzzy match는 자동 확정에 쓰지 않는다(사용자 규칙 7).
"""

from uuid import UUID

from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_schemas import IngredientMatchMethod
from data.scripts.nia_llm_label_schemas import LlmIngredientMention

_DETERMINISTIC_METHODS = frozenset(
    {
        IngredientMatchMethod.STANDARD_NAME_KO,
        IngredientMatchMethod.STANDARD_NAME_EN_NORMALIZED,
        IngredientMatchMethod.OLD_NAME_KO,
        IngredientMatchMethod.OLD_NAME_EN_NORMALIZED,
        IngredientMatchMethod.ANNOTATION_STRIPPED_KO,
        IngredientMatchMethod.ANNOTATION_STRIPPED_EN_NORMALIZED,
    }
)


class NiaIngredientMatchingStage:
    def __init__(self, matcher: IngredientNameMatcher) -> None:
        self._matcher = matcher

    def resolve(self, mention: LlmIngredientMention) -> dict:
        """`NiaIngredientSubject` 형태의 dict를 반환한다. LLM이 준 ambiguous_family는
        그대로 존중하고(코드가 새로 판정하지 않음), 아니라고 한 경우에만 매칭을 시도한다."""
        if mention.ambiguous_family:
            return {
                "raw_name": mention.raw_name,
                "raw_name_ko": mention.raw_name_ko,
                "ingredient_id": None,
                "matching_status": "unresolved_ambiguous_family",
            }

        match = self._matcher.match(raw_name_ko=mention.raw_name_ko, raw_name_en=mention.raw_name)
        if match.method in _DETERMINISTIC_METHODS and match.matched_ingredient_id is not None:
            return {
                "raw_name": mention.raw_name,
                "raw_name_ko": mention.raw_name_ko,
                "ingredient_id": str(match.matched_ingredient_id),
                "matching_status": "matched",
            }
        return {
            "raw_name": mention.raw_name,
            "raw_name_ko": mention.raw_name_ko,
            "ingredient_id": None,
            "matching_status": "unresolved",
        }
