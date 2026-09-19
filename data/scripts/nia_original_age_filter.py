"""`NiaOriginalLoader` 출력에서 `meta.age` 가 범위 안인 레코드만 통과시킨다.

팀이 쓰는 NIA corpus 는 10대~30대(만 10~39세)다. 연령 조건을 loader 안에 넣지 않는 이유는 loader 가
"원본을 손실 없이 읽는다" 는 단일 책임을 유지해야 다른 조건(전체 통계, 다른 연령대)에도 재사용되기
때문이다. 그래서 필터는 loader 이후 별도 단계이며, 레코드를 고치지 않고 걸러내기만 한다.

기존 `nia_qa_age_filter.py` 는 ZIP 의 dict 를 읽어 processed JSONL 로 저장하는 별도 스크립트라 이 경로에서 쓰지 않는다.
"""

from collections.abc import Iterable, Iterator

from data.scripts.nia_original_schemas import NiaOriginalEntry

DEFAULT_MIN_AGE = 10
DEFAULT_MAX_AGE_INCLUSIVE = 39  # "30대"까지이므로 39세를 포함한다


class NiaOriginalAgeFilter:
    def __init__(
        self,
        min_age: int = DEFAULT_MIN_AGE,
        max_age_inclusive: int = DEFAULT_MAX_AGE_INCLUSIVE,
    ) -> None:
        if min_age > max_age_inclusive:
            raise ValueError(f"연령 범위가 뒤집혀 있습니다: {min_age} > {max_age_inclusive}")
        self._min_age = min_age
        self._max_age_inclusive = max_age_inclusive

    def filter(self, entries: Iterable[NiaOriginalEntry]) -> Iterator[NiaOriginalEntry]:
        """입력 순서를 그대로 유지하며 범위 안의 항목만 원본 객체 그대로 내보낸다."""
        for entry in entries:
            if self._min_age <= entry.record.meta.age <= self._max_age_inclusive:
                yield entry
