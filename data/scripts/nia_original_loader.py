"""AI Hub 배포 원본 Q-CoT-A(ZIP/JSONL)를 손실 없이 `NiaOriginalRecord` 로 읽는다.

책임은 "읽기"까지다. 연령 필터, 문서 결합, page_content/metadata 생성, 임베딩은 하지 않는다.
어떤 레코드도 조용히 건너뛰지 않는다: 깨진 줄은 어느 파일의 어느 멤버 몇 번째 줄인지 담은
`NiaOriginalParseError` 로 즉시 알린다.

사용 예:
    loader = NiaOriginalLoader()
    for entry in loader.iter_entries(zip_paths):
        entry.record, entry.source
"""

import json
import zipfile
from collections.abc import Iterable, Iterator
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from data.scripts.nia_original_schemas import (
    NiaOriginalEntry,
    NiaOriginalRecord,
    NiaRecordSource,
)


class NiaInputSuffix(StrEnum):
    ZIP = ".zip"
    JSONL = ".jsonl"


class NiaRawLine(BaseModel):
    """파싱 전의 JSONL 한 줄. 실패 건수를 세며 계속 진행해야 하는 호출자를 위해 분리해 둔다."""

    model_config = ConfigDict(frozen=True)

    source: NiaRecordSource
    text: str


class NiaOriginalParseError(RuntimeError):
    def __init__(self, source: NiaRecordSource, reason: str) -> None:
        self.source = source
        member = f" member={source.member_name}" if source.member_name else ""
        super().__init__(
            f"NIA 원본 파싱 실패: {source.input_path}{member} line={source.line_number}: {reason}"
        )


class NiaOriginalLoader:
    def iter_entries(self, input_paths: Iterable[Path]) -> Iterator[NiaOriginalEntry]:
        """레코드를 하나씩 내보낸다. 전체를 메모리에 올리지 않는다."""
        for raw_line in self.iter_raw_lines(input_paths):
            yield self.parse_line(raw_line)

    def iter_raw_lines(self, input_paths: Iterable[Path]) -> Iterator[NiaRawLine]:
        for input_path in input_paths:
            suffix = input_path.suffix.lower()
            if suffix == NiaInputSuffix.ZIP:
                yield from self._iter_zip_lines(input_path)
            elif suffix == NiaInputSuffix.JSONL:
                with input_path.open("rb") as file:
                    yield from self._iter_lines(file, input_path, member_name=None)
            else:
                raise ValueError(
                    f"지원하지 않는 NIA 입력 형식입니다(.zip/.jsonl 만 가능): {input_path}"
                )

    def parse_line(self, raw_line: NiaRawLine) -> NiaOriginalEntry:
        try:
            record = NiaOriginalRecord.model_validate(json.loads(raw_line.text))
        except json.JSONDecodeError as e:
            raise NiaOriginalParseError(raw_line.source, f"JSON 형식 오류: {e}") from e
        except ValidationError as e:
            raise NiaOriginalParseError(raw_line.source, f"스키마 검증 실패: {e}") from e
        return NiaOriginalEntry(record=record, source=raw_line.source)

    def _iter_zip_lines(self, zip_path: Path) -> Iterator[NiaRawLine]:
        try:
            archive = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile as e:
            raise RuntimeError(f"NIA ZIP 을 열 수 없습니다: {zip_path}: {e}") from e
        with archive:
            # namelist 순서를 그대로 쓴다. 정렬하면 원본 배포 순서와 줄 번호 추적이 어긋난다
            for member_name in archive.namelist():
                if not member_name.lower().endswith(NiaInputSuffix.JSONL):
                    continue
                with archive.open(member_name) as file:
                    yield from self._iter_lines(file, zip_path, member_name=member_name)

    def _iter_lines(self, file, input_path: Path, member_name: str | None) -> Iterator[NiaRawLine]:
        for line_number, line in enumerate(file, start=1):
            source = NiaRecordSource(
                input_path=input_path, member_name=member_name, line_number=line_number
            )
            try:
                text = line.decode("utf-8")
            except UnicodeDecodeError as e:
                raise NiaOriginalParseError(source, f"UTF-8 디코딩 실패: {e}") from e
            # 끝의 빈 줄은 레코드가 아니다. line_number 는 물리적 줄 번호를 유지한다
            if text.strip():
                yield NiaRawLine(source=source, text=text)
