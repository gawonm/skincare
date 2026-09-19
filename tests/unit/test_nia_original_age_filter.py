from typing import Any

import pytest

from data.scripts.nia_original_age_filter import NiaOriginalAgeFilter
from data.scripts.nia_original_schemas import NiaOriginalEntry, NiaOriginalRecord, NiaRecordSource


def _entry(record_id: str, age: int) -> NiaOriginalEntry:
    raw: dict[str, Any] = {
        "info": {
            "id": record_id,
            "source_survey_id": "1",
            "target_concern": "모공",
            "question": "q",
            "answer": "a",
            "evidence_sources": [],
        },
        "meta": {
            "gender": "여성",
            "age": age,
            "initial_skin_condition": "x",
            "skin_type": "지성",
            "skin_concerns": [],
            "image_filename": "1.jpg",
        },
        "external": [],
        "chain_of_thought": [],
    }
    return NiaOriginalEntry(
        record=NiaOriginalRecord.model_validate(raw),
        source=NiaRecordSource(input_path="x.jsonl", line_number=1),
    )


def _ids(entries: list[NiaOriginalEntry]) -> list[str]:
    return [e.record.info.id for e in entries]


@pytest.mark.parametrize(
    ("age", "passes"),
    [(9, False), (10, True), (39, True), (40, False)],
)
def test_경계_나이는_10이상_39이하만_통과한다(age: int, passes: bool) -> None:
    result = list(NiaOriginalAgeFilter().filter([_entry("A", age)]))

    assert (len(result) == 1) is passes


def test_입력_순서를_보존한다() -> None:
    entries = [_entry("c", 35), _entry("x", 60), _entry("a", 10), _entry("y", 9), _entry("b", 22)]

    assert _ids(list(NiaOriginalAgeFilter().filter(entries))) == ["c", "a", "b"]


def test_통과한_항목은_원본_객체_그대로이고_변경되지_않는다() -> None:
    entry = _entry("A", 20)
    before = entry.model_dump()

    [passed] = list(NiaOriginalAgeFilter().filter([entry]))

    assert passed is entry
    assert entry.model_dump() == before


def test_제너레이터_입력도_지연_평가로_처리한다() -> None:
    generator = (_entry(str(n), n) for n in (5, 15, 45))

    assert _ids(list(NiaOriginalAgeFilter().filter(generator))) == ["15"]


def test_범위를_바꿀_수_있고_뒤집힌_범위는_거부한다() -> None:
    entries = [_entry("a", 20), _entry("b", 50)]

    assert _ids(list(NiaOriginalAgeFilter(min_age=40, max_age_inclusive=60).filter(entries))) == [
        "b"
    ]
    with pytest.raises(ValueError, match="뒤집혀"):
        NiaOriginalAgeFilter(min_age=40, max_age_inclusive=10)
