"""질문 텍스트에서 성분 언급을 찾아 `IngredientMaster`로 해소한다.

`scripts.ingredient_name_matcher.IngredientNameMatcher`는 이미 분리된 후보 이름 문자열
하나를 표준 성분에 매칭하는 것만 한다 - 자연어 문장에서 성분 언급 자체를 뽑아내는 기능은
없다(코드 확인 완료, 2026-09-10). 그래서 이 클래스가 그 앞 단계(언급 추출)를 맡고, 해소는
`IngredientNameMatcher`를 그대로 재사용한다.

추출 방식: `IngredientMaster`의 표준명/구명칭을 사전으로 미리 인덱싱해두고, 질문 문자열에
그 이름이 그대로(부분 문자열로) 들어 있는지 스캔한다. LLM 기반 추출보다 느슨하지만(줄임말·
오타는 못 잡는다), API 호출 없이 결정적으로 동작해서 테스트하기 쉽다 - 정확도가 부족하면
나중에 LLM 기반 추출로 교체하되 이 클래스의 반환 계약(해소됨/모호함)은 그대로 유지한다.

"비타민C"를 임의로 "아스코빅애씨드"로 확정하는 식의 추측은 하지 않는다 - `old_names_ko`에
그 표기가 실제로 KCIA 데이터로 등록돼 있어야 잡힌다. 등록 안 된 표현은 못 잡고 넘어가는
쪽을 택한다(틀리게 확정하는 것보다 안전하다).
"""

from collections import defaultdict
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from scripts.ingredient_schemas import IngredientCandidate

# 이보다 짧은 이름은 후보에서 뺀다 - 한두 글자 이름은 질문의 무관한 부분과 우연히 겹칠
# 확률이 높아서(예: 원소기호, 흔한 조사) 오탐이 잦다.
_MIN_MENTION_NAME_LENGTH = 2


class IngredientMentionResolution(BaseModel):
    """질문에서 찾은 성분 언급 하나의 해소 결과."""

    model_config = ConfigDict(frozen=True)

    matched_text: str
    ingredient_id: UUID | None
    ambiguous: bool
    candidate_ingredient_ids: tuple[UUID, ...] = ()


class IngredientMentionResolver:
    """`IngredientCandidate` 목록으로 질문 속 성분 언급을 찾아 해소한다."""

    def __init__(self, candidates: list[IngredientCandidate]) -> None:
        self._name_to_ingredient_ids: dict[str, set[UUID]] = defaultdict(set)
        for candidate in candidates:
            for name in (
                candidate.standard_name_ko,
                candidate.standard_name_en,
                *candidate.old_names_ko,
                *candidate.old_names_en,
            ):
                if name and len(name) >= _MIN_MENTION_NAME_LENGTH:
                    self._name_to_ingredient_ids[name].add(candidate.ingredient_id)

    def resolve(self, question: str) -> list[IngredientMentionResolution]:
        resolutions: list[IngredientMentionResolution] = []
        claimed_spans: list[tuple[int, int]] = []

        # 이름이 긴 것부터 본다 - "나이아신아마이드" 안에 "나이아신"이 부분 문자열로 들어
        # 있는 것처럼, 짧은 이름이 실제로는 긴 이름의 일부일 뿐 별개 언급이 아닌 경우가
        # 있다. 문자 위치(span)를 먼저 차지한 긴 이름과 겹치는 짧은 이름은 건너뛴다.
        for name in sorted(self._name_to_ingredient_ids, key=len, reverse=True):
            start = question.find(name)
            if start == -1:
                continue
            end = start + len(name)
            if any(
                start < claimed_end and end > claimed_start
                for claimed_start, claimed_end in claimed_spans
            ):
                continue
            claimed_spans.append((start, end))

            ingredient_ids = self._name_to_ingredient_ids[name]
            if len(ingredient_ids) == 1:
                resolutions.append(
                    IngredientMentionResolution(
                        matched_text=name,
                        ingredient_id=next(iter(ingredient_ids)),
                        ambiguous=False,
                    )
                )
            else:
                resolutions.append(
                    IngredientMentionResolution(
                        matched_text=name,
                        ingredient_id=None,
                        ambiguous=True,
                        candidate_ingredient_ids=tuple(ingredient_ids),
                    )
                )
        return resolutions
