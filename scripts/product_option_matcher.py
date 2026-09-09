"""옵션이 여러 개인 상품에서, 검색에 쓴 `TargetGroup` 성분과 실제로 일치하는 옵션을 찾는다.

올리브영 글로벌 `detail-data` 는 상품 하나에 여러 옵션(다른 성분/버전)이 있어도 대표
옵션(`rprstYn=Y`) 하나의 가격·이름만 상품 레벨 필드에 넣어 준다. 이 대표 옵션이 검색에
쓴 성분과 무관한 경우가 있다 — 예: "Anua Mask Sheet 1ea" 상품은 대표 옵션이
"Heartleaf 77 Soothing"(어성초)인데, 옵션 목록 안에는 "Niacinamide 5 TXA"(나이아신아마이드)
와 "Retinol Niacin"(레티놀)이 각각 따로 있다. 대표 옵션만 쓰면 나이아신아마이드로 검색했는데
어성초 가격이 들어가는 식으로 완전히 다른 성분이 잡힌다.

옵션명(`snglOptnNameEn`)에서 성분 키워드를 찾아 정확히 하나만 일치하면 그 옵션을 쓴다.
0개 또는 여러 개가 일치하면(성분을 특정할 수 없으면) `None` 을 돌려주고, 호출자가 기존처럼
대표 옵션 + `ReviewReason.OPTION_AMBIGUOUS` 로 처리하게 둔다.
"""

from scripts.oliveyoung_global_schemas import OliveYoungGlobalProductOption
from scripts.product_candidate_schemas import TargetGroup

# 성분 키워드는 일부러 짧게 쓰지 않는다. 예를 들어 "niacin" 은 "Retinol Niacin"(레티놀+
# 나이아신 복합) 옵션에도 걸려서 나이아신아마이드 옵션과 구분이 안 된다. "niacinamide" 처럼
# 온전한 성분명을 써야 이런 복합 옵션과 겹치지 않는다.
_KEYWORDS_BY_TARGET_GROUP: dict[TargetGroup, tuple[str, ...]] = {
    TargetGroup.VITAMIN_C: ("vitamin c", "vita c", "ascorbic acid"),
    TargetGroup.NIACINAMIDE: ("niacinamide",),
    TargetGroup.RETINOL: ("retinol",),
    TargetGroup.AHA: ("glycolic acid", "glycolic"),
    TargetGroup.BHA: ("salicylic acid", "salicylic"),
}


class ProductOptionMatcher:
    def find_matching_option(
        self,
        target_group: TargetGroup,
        option_list: list[OliveYoungGlobalProductOption],
    ) -> OliveYoungGlobalProductOption | None:
        keywords = _KEYWORDS_BY_TARGET_GROUP[target_group]
        matches = [
            option
            for option in option_list
            if any(keyword in option.option_name.lower() for keyword in keywords)
        ]
        if len(matches) == 1:
            return matches[0]
        return None
