"""전성분 토큰의 `IngredientNameMatcher.match()` 결과를, RAG 근거 연결에 그대로 써도
되는지(`CONFIRMED`)와 사람 검토가 필요한지로 나눈다.

`IngredientNameMatcher`는 손대지 않는다 - Knowledgedata/MFDS 등 다른 파이프라인이 이미
그 매칭 동작(정확일치→구명칭→annotation 제거→fuzzy 순)에 의존하고 있어서, 매칭 결과를
받은 뒤 호출부에서만 정책을 얹는다.

전성분표 원문(`matching_name`)은 영문이라 `raw_name_ko`가 없다 - 그래서 `match()`에
전달하는 한글명은 항상 None이고, 실제로 걸리는 매칭 경로는
`STANDARD_NAME_EN_NORMALIZED`/`OLD_NAME_EN_NORMALIZED`뿐이다. 그런데도 이 정책을 따로
두는 이유: annotation-stripped 경로(`ANNOTATION_STRIPPED_EN_NORMALIZED`)는 원문이 정확한
INCI 표기가 아니라 상용명이 섞였을 가능성을 내포하고, fuzzy(`FUZZY_SINGLE_CANDIDATE`)는
애초에 한글 전용이라 raw_name_ko가 없으면 절대 안 걸린다 - 즉 "안 걸릴 것으로 예상되는
경로"까지 명시적으로 검토로 돌려서, matcher 내부 구현이 나중에 바뀌어도 이 정책이
조용히 더 관대해지지 않게 방어한다.
"""

from scripts.ingredient_name_matcher import IngredientNameMatcher
from scripts.ingredient_schemas import IngredientMatchMethod, IngredientMatchResult

# 이 두 방법만 "영문 정규화 표기가 표준 성분 하나와 유일하게 일치했다"는 뜻이라, 전성분표
# 원문(영문 INCI) 매칭에서 자동 확정해도 되는 근거로 본다. 나머지는 전부 검토로 돌린다.
_AUTO_CONFIRM_METHODS = frozenset(
    {
        IngredientMatchMethod.STANDARD_NAME_EN_NORMALIZED,
        IngredientMatchMethod.OLD_NAME_EN_NORMALIZED,
    }
)


class ProductIngredientMatchAcceptancePolicy:
    """`IngredientNameMatcher.match()`를 그대로 호출하되, 자동 확정 범위만 좁힌다."""

    def __init__(self, matcher: IngredientNameMatcher) -> None:
        self._matcher = matcher

    def match(self, matching_name: str) -> IngredientMatchResult:
        result = self._matcher.match(raw_name_ko=None, raw_name_en=matching_name)
        if result.method in _AUTO_CONFIRM_METHODS:
            return result

        # 매칭 자체는 됐을 수 있어도(예: ANNOTATION_STRIPPED_EN_NORMALIZED), 검토 없이
        # 확정하지 않는다는 방침이므로 matched_ingredient_id를 지우고 검토 후보로만 남긴다.
        review_candidate_ids = result.review_candidate_ids or (
            (result.matched_ingredient_id,) if result.matched_ingredient_id else ()
        )
        return IngredientMatchResult(
            method=result.method,
            review_candidate_ids=review_candidate_ids,
        )
