"""NIA statement의 성분 언급(`LlmIngredientMention`)을 ingredient master와 deterministic하게
연결한다. fuzzy match는 자동 확정에 쓰지 않는다(사용자 규칙 7).

LLM이 `raw_name_ko`를 비워두고 한글 성분명을 `raw_name`(원래 INCI/영문용) 필드에 넣는
경우가 실측으로 많이 확인됐다(39건 pilot에서 unresolved 59건 중 51건). `raw_name_en`으로
넘기면 `IngredientNameNormalizer.normalize_en()`이 한글을 영문 정규화 규칙(공백·하이픈·
괄호 제거)으로만 다루고 그대로 통과시켜, 표준 영문명 색인과 절대 일치하지 않는다. 이걸
성분마다 하드코딩으로 고치지 않고, `raw_name`에 한글이 섞여 있으면 그 문자열을
`raw_name_ko`로도 한 번 더 시도하는 generic fallback으로 처리한다 — 매칭 방식 자체
(exact/정규화/annotation-stripped, fuzzy 제외)는 전혀 바꾸지 않는다.
"""

import re

from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_schemas import IngredientMatchMethod
from data.scripts.nia_llm_label_schemas import LlmIngredientMention

_HANGUL_RE = re.compile(r"[가-힣]")

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
        if self._is_deterministic(match):
            return self._matched(mention, match.matched_ingredient_id)

        # 1순위(raw_name_ko)가 없거나 실패했고, raw_name 자체가 한글이면(LLM이 필드를
        # 잘못 채운 경우) 같은 deterministic 파이프라인을 raw_name_ko로도 시도한다.
        if not mention.raw_name_ko and _HANGUL_RE.search(mention.raw_name):
            fallback_match = self._matcher.match(raw_name_ko=mention.raw_name, raw_name_en=None)
            if self._is_deterministic(fallback_match):
                return self._matched(mention, fallback_match.matched_ingredient_id)

        return {
            "raw_name": mention.raw_name,
            "raw_name_ko": mention.raw_name_ko,
            "ingredient_id": None,
            "matching_status": "unresolved",
        }

    def _is_deterministic(self, match) -> bool:
        return match.method in _DETERMINISTIC_METHODS and match.matched_ingredient_id is not None

    def _matched(self, mention: LlmIngredientMention, ingredient_id) -> dict:
        return {
            "raw_name": mention.raw_name,
            "raw_name_ko": mention.raw_name_ko,
            "ingredient_id": str(ingredient_id),
            "matching_status": "matched",
        }
