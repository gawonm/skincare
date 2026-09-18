import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from data.scripts.nia_original_loader import NiaOriginalLoader, NiaOriginalParseError

_UNKNOWN_FIELD = "unknown_field"


class _RecordFactory:
    def build(self, record_id: str, age: int = 52) -> dict[str, Any]:
        return {
            "info": {
                "id": record_id,
                "source_survey_id": "00143",
                "target_concern": "모공",
                "question": "  앞뒤 공백이 있는 질문  ",
                "answer": "답변",
                "evidence_sources": ["PMID:1", "DOI:10.1/x"],
            },
            "meta": {
                "gender": "여성",
                "age": age,
                "initial_skin_condition": "NS/P1/W1/NA/VP/SA/ND/R",
                "skin_type": "복합성",
                "skin_concerns": ["모공", "미백(색소침착/기미/칙칙함)"],
                "image_filename": "03423.jpg",
            },
            "external": [{"priority": 1, "factor": "자외선/블루라이트", "details": "햇빛(UV)"}],
            "chain_of_thought": [
                {"step": 1, "title": "문제 분석 및 원인 파악", "content": "내용1"},
                {"step": 2, "title": "성분 선택 및 근거 제시", "content": "내용2"},
            ],
        }

    def to_lines(self, records: list[dict[str, Any]]) -> bytes:
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf-8")


@pytest.fixture
def factory() -> _RecordFactory:
    return _RecordFactory()


def test_모든_원본_필드가_그대로_보존된다(tmp_path: Path, factory: _RecordFactory) -> None:
    raw = factory.build("A")
    path = tmp_path / "a.jsonl"
    path.write_bytes(factory.to_lines([raw]))

    [entry] = list(NiaOriginalLoader().iter_entries([path]))

    assert entry.record.model_dump() == raw
    assert entry.record.info.question == "  앞뒤 공백이 있는 질문  "
    assert entry.record.info.source_survey_id == "00143"
    assert entry.record.meta.skin_concerns == ["모공", "미백(색소침착/기미/칙칙함)"]
    assert entry.record.external[0].details == "햇빛(UV)"
    assert entry.record.chain_of_thought[1].title == "성분 선택 및 근거 제시"


def test_알_수_없는_추가_필드도_모든_층에서_보존된다(
    tmp_path: Path, factory: _RecordFactory
) -> None:
    raw = factory.build("A")
    raw[_UNKNOWN_FIELD] = {"nested": [1, 2]}
    raw["info"][_UNKNOWN_FIELD] = "info-extra"
    raw["meta"][_UNKNOWN_FIELD] = "meta-extra"
    raw["external"][0][_UNKNOWN_FIELD] = "external-extra"
    raw["chain_of_thought"][0][_UNKNOWN_FIELD] = "cot-extra"
    path = tmp_path / "a.jsonl"
    path.write_bytes(factory.to_lines([raw]))

    [entry] = list(NiaOriginalLoader().iter_entries([path]))

    assert entry.record.model_dump() == raw
    assert entry.record.model_extra == {_UNKNOWN_FIELD: {"nested": [1, 2]}}
    assert entry.record.info.model_extra == {_UNKNOWN_FIELD: "info-extra"}


def test_연령_필터_없이_범위_밖_나이도_반환한다(tmp_path: Path, factory: _RecordFactory) -> None:
    path = tmp_path / "a.jsonl"
    path.write_bytes(factory.to_lines([factory.build("kid", age=5), factory.build("old", age=71)]))

    entries = list(NiaOriginalLoader().iter_entries([path]))

    assert [e.record.meta.age for e in entries] == [5, 71]


def test_zip의_여러_jsonl_멤버와_여러_줄을_모두_순회한다(
    tmp_path: Path, factory: _RecordFactory
) -> None:
    zip_path = tmp_path / "TL_test.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("m1.jsonl", factory.to_lines([factory.build("A"), factory.build("B")]))
        archive.writestr("readme.txt", "무시되는 멤버")
        archive.writestr("m2.jsonl", factory.to_lines([factory.build("C")]))

    entries = list(NiaOriginalLoader().iter_entries([zip_path]))

    assert [e.record.info.id for e in entries] == ["A", "B", "C"]
    assert [(e.source.member_name, e.source.line_number) for e in entries] == [
        ("m1.jsonl", 1),
        ("m1.jsonl", 2),
        ("m2.jsonl", 1),
    ]
    assert all(e.source.input_path == zip_path for e in entries)


def test_직접_jsonl과_zip을_함께_받을_수_있고_지연_평가된다(
    tmp_path: Path, factory: _RecordFactory
) -> None:
    jsonl_path = tmp_path / "a.jsonl"
    jsonl_path.write_bytes(factory.to_lines([factory.build("A")]))
    missing_zip = tmp_path / "missing.zip"

    iterator = NiaOriginalLoader().iter_entries([jsonl_path, missing_zip])

    first = next(iterator)
    assert first.source.member_name is None
    # 첫 항목을 받을 때까지 두 번째 입력은 열리지 않아야 한다(전체 적재 없음)
    with pytest.raises(FileNotFoundError):
        next(iterator)


def test_malformed_json은_경로_멤버_줄번호를_포함한_오류를_낸다(
    tmp_path: Path, factory: _RecordFactory
) -> None:
    zip_path = tmp_path / "bad.zip"
    good = factory.to_lines([factory.build("A")])
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("m1.jsonl", good + b"{not json}\n")

    iterator = NiaOriginalLoader().iter_entries([zip_path])
    next(iterator)
    with pytest.raises(NiaOriginalParseError) as error:
        next(iterator)

    assert error.value.source.line_number == 2
    assert error.value.source.member_name == "m1.jsonl"
    assert str(zip_path) in str(error.value)
    assert "m1.jsonl" in str(error.value)
    assert "line=2" in str(error.value)
    assert isinstance(error.value.__cause__, json.JSONDecodeError)


def test_스키마_불일치는_조용히_변환하지_않고_오류를_낸다(
    tmp_path: Path, factory: _RecordFactory
) -> None:
    raw = factory.build("A")
    raw["meta"]["age"] = "52"  # 문자열 나이를 int 로 몰래 바꾸면 원본이 달라진다
    path = tmp_path / "a.jsonl"
    path.write_bytes(factory.to_lines([raw]))

    with pytest.raises(NiaOriginalParseError, match="스키마 검증 실패"):
        list(NiaOriginalLoader().iter_entries([path]))


def test_지원하지_않는_확장자는_오류를_낸다(tmp_path: Path) -> None:
    path = tmp_path / "a.csv"
    path.write_text("x")

    with pytest.raises(ValueError, match="지원하지 않는"):
        list(NiaOriginalLoader().iter_entries([path]))
