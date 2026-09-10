"""외부 성분명(Knowledgedata, MFDS, CIR, 제품 전성분)을 `IngredientMaster` 로 매핑한다.

매핑 순서
1. 표준 국문명 정확 일치
2. 표준 영문명 정규화 후 일치
3. 구국문명 일치
4. 구영문명 정규화 후 일치
5. 괄호·"/" 뒤 상용명 표기를 제거한 뒤 표준 국문명/영문명 재일치
   (예: "Niacinamide\n(Vitamin B3)" -> "Niacinamide"). 이 결과가 정확히 하나의
   표준 성분과 일치할 때만 쓴다. 여러 개면 여전히 manual review 로 보낸다.
6. 후보가 하나뿐인 fuzzy match
7. 나머지는 manual review 대상(`IngredientMatchMethod.MANUAL_REVIEW`)

DB 세션 없이 `IngredientCandidate` 스냅샷 목록만으로 동작해서, 매핑 로직만 따로
테스트하거나 매번 새로 조회하지 않고 재사용할 수 있다.
"""

from collections import defaultdict
from uuid import UUID

from rapidfuzz import fuzz, process

from scripts.ingredient_name_normalizer import IngredientNameNormalizer
from scripts.ingredient_schemas import (
    IngredientCandidate,
    IngredientMatchMethod,
    IngredientMatchResult,
)

_FUZZY_SCORE_CUTOFF = 90.0
_FUZZY_TOP_N_FOR_REVIEW = 3


class IngredientNameMatcher:
    """`IngredientCandidate` 목록을 색인해 두고 반복적으로 매칭에 쓴다."""

    def __init__(
        self,
        candidates: list[IngredientCandidate],
        normalizer: IngredientNameNormalizer,
        fuzzy_score_cutoff: float = _FUZZY_SCORE_CUTOFF,
    ) -> None:
        self._normalizer = normalizer
        self._fuzzy_score_cutoff = fuzzy_score_cutoff

        self._by_standard_ko: dict[str, list[UUID]] = defaultdict(list)
        self._by_normalized_en: dict[str, list[UUID]] = defaultdict(list)
        self._by_old_ko: dict[str, list[UUID]] = defaultdict(list)
        self._by_normalized_old_en: dict[str, list[UUID]] = defaultdict(list)
        self._fuzzy_choices: dict[str, UUID] = {}

        for candidate in candidates:
            self._by_standard_ko[candidate.standard_name_ko].append(candidate.ingredient_id)
            self._fuzzy_choices[candidate.standard_name_ko] = candidate.ingredient_id
            if candidate.normalized_name_en:
                self._by_normalized_en[candidate.normalized_name_en].append(candidate.ingredient_id)
            for old_name_ko in candidate.old_names_ko:
                self._by_old_ko[old_name_ko].append(candidate.ingredient_id)
            for old_name_en in candidate.old_names_en:
                normalized_old_en = normalizer.normalize_en(old_name_en)
                if normalized_old_en:
                    self._by_normalized_old_en[normalized_old_en].append(candidate.ingredient_id)

    def match(self, raw_name_ko: str | None, raw_name_en: str | None) -> IngredientMatchResult:
        if raw_name_ko:
            result = self._match_unique(
                self._by_standard_ko, raw_name_ko, IngredientMatchMethod.STANDARD_NAME_KO
            )
            if result:
                return result

        normalized_en = self._normalizer.normalize_en(raw_name_en)
        if normalized_en:
            result = self._match_unique(
                self._by_normalized_en,
                normalized_en,
                IngredientMatchMethod.STANDARD_NAME_EN_NORMALIZED,
            )
            if result:
                return result

        if raw_name_ko:
            result = self._match_unique(
                self._by_old_ko, raw_name_ko, IngredientMatchMethod.OLD_NAME_KO
            )
            if result:
                return result

        if normalized_en:
            result = self._match_unique(
                self._by_normalized_old_en,
                normalized_en,
                IngredientMatchMethod.OLD_NAME_EN_NORMALIZED,
            )
            if result:
                return result

        stripped_ko = self._normalizer.strip_common_name_annotation(raw_name_ko)
        if stripped_ko and stripped_ko != raw_name_ko:
            result = self._match_unique(
                self._by_standard_ko, stripped_ko, IngredientMatchMethod.ANNOTATION_STRIPPED_KO
            )
            if result:
                return result

        normalized_stripped_en = self._normalizer.normalize_en(
            self._normalizer.strip_common_name_annotation(raw_name_en)
        )
        if normalized_stripped_en and normalized_stripped_en != normalized_en:
            result = self._match_unique(
                self._by_normalized_en,
                normalized_stripped_en,
                IngredientMatchMethod.ANNOTATION_STRIPPED_EN_NORMALIZED,
            )
            if result:
                return result

        return self._match_fuzzy(raw_name_ko)

    def _match_unique(
        self, index: dict[str, list[UUID]], key: str, method: IngredientMatchMethod
    ) -> IngredientMatchResult | None:
        candidate_ids = index.get(key)
        if not candidate_ids:
            return None
        if len(candidate_ids) == 1:
            return IngredientMatchResult(method=method, matched_ingredient_id=candidate_ids[0])
        # 같은 이름이 서로 다른 성분에 중복 등록된 경우. 임의로 하나를 고르지 않고
        # 사람이 확인하도록 넘긴다.
        return IngredientMatchResult(
            method=IngredientMatchMethod.MANUAL_REVIEW,
            review_candidate_ids=tuple(dict.fromkeys(candidate_ids)),
        )

    def _match_fuzzy(self, raw_name_ko: str | None) -> IngredientMatchResult:
        if not raw_name_ko or not self._fuzzy_choices:
            return IngredientMatchResult(method=IngredientMatchMethod.MANUAL_REVIEW)

        matches = process.extract(
            raw_name_ko,
            self._fuzzy_choices.keys(),
            scorer=fuzz.WRatio,
            score_cutoff=self._fuzzy_score_cutoff,
            limit=_FUZZY_TOP_N_FOR_REVIEW,
        )
        if not matches:
            return IngredientMatchResult(method=IngredientMatchMethod.MANUAL_REVIEW)
        if len(matches) == 1:
            best_name, best_score, _ = matches[0]
            return IngredientMatchResult(
                method=IngredientMatchMethod.FUZZY_SINGLE_CANDIDATE,
                matched_ingredient_id=self._fuzzy_choices[best_name],
                fuzzy_score=best_score,
            )
        # 후보가 여럿이면 fuzzy match 만으로 확정하지 않는다.
        return IngredientMatchResult(
            method=IngredientMatchMethod.MANUAL_REVIEW,
            review_candidate_ids=tuple(self._fuzzy_choices[name] for name, _, _ in matches),
        )
