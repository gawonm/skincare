"""NIA AI Hub 스킨케어 성분-효능 추천 데이터(dataset 71886) Q-CoT-A 라벨링데이터에서
`meta.age` 가 10~30대(만 10~39세)인 레코드만 추출해 JSONL로 저장한다.

주의: 이 스크립트는 RAG 적재가 아니다(Document/Chunking/Embedding/pgvector 어느 것도
거치지 않는다). POC 단계에서 나이대로 미리 걸러 둔 원본 레코드를 그대로 보존하는
전처리일 뿐이며, 원본의 `info`/`meta`/`external`/`chain_of_thought` 중첩 구조를
그대로 유지한다 — CSV로 펴면 `chain_of_thought` 배열이 깨지기 때문에 JSONL을 쓴다.

라벨링데이터(`02.라벨링데이터`, TL_*/VL_*)만 읽는다. 원천데이터(`01.원천데이터`,
TS_*/VS_*)는 설문 CSV와 얼굴 이미지만 담고 있어 이 추출 대상이 아니다.

사용법:
    uv run python -m data.scripts.nia_qa_age_filter
"""

import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

_NIA_ROOT = Path("data/03.스킨케어 성분-효능 추천 데이터/3.개방데이터/2.데이터(NIA)")
_LABELING_ZIP_GLOBS = [
    _NIA_ROOT / "Training" / "02.라벨링데이터",
    _NIA_ROOT / "Validation" / "02.라벨링데이터",
]
_OUTPUT_PATH = Path("data/processed/nia_qa_10s_30s.jsonl")

_MIN_AGE = 10
_MAX_AGE_INCLUSIVE = 39  # "30대"까지이므로 39세를 포함한다


class NiaRecordMeta(BaseModel):
    """레코드 중 나이 판단에만 쓰는 최소 스키마. 나머지 필드는 원문 그대로 통과시킨다."""

    model_config = ConfigDict(extra="ignore")

    age: int


class NiaAgeFilterSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    zip_count: int
    total_records: int
    matched_records: int


class NiaQaAgeFilter:
    """zip 안 jsonl을 순회하며 나이 조건에 맞는 레코드만 새 jsonl에 옮겨 쓴다."""

    def filter_zips(self, zip_paths: list[Path], output_path: Path) -> NiaAgeFilterSummary:
        total_records = 0
        matched_records = 0

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as output_file:
            for zip_path in zip_paths:
                for record in self._iter_records(zip_path):
                    total_records += 1
                    if self._is_target_age(record):
                        matched_records += 1
                        output_file.write(json.dumps(record, ensure_ascii=False) + "\n")

        return NiaAgeFilterSummary(
            zip_count=len(zip_paths),
            total_records=total_records,
            matched_records=matched_records,
        )

    def _iter_records(self, zip_path: Path) -> list[dict[str, Any]]:
        records = []
        with zipfile.ZipFile(zip_path) as archive:
            for name in archive.namelist():
                if not name.endswith(".jsonl"):
                    continue
                with archive.open(name) as file:
                    for line in file:
                        if line.strip():
                            records.append(json.loads(line))
        return records

    def _is_target_age(self, record: dict[str, Any]) -> bool:
        meta = NiaRecordMeta.model_validate(record.get("meta", {}))
        return _MIN_AGE <= meta.age <= _MAX_AGE_INCLUSIVE


def _run() -> None:
    zip_paths = [path for folder in _LABELING_ZIP_GLOBS for path in sorted(folder.glob("*.zip"))]
    if not zip_paths:
        raise RuntimeError(f"라벨링데이터 zip을 찾지 못했습니다: {_LABELING_ZIP_GLOBS}")

    summary = NiaQaAgeFilter().filter_zips(zip_paths, _OUTPUT_PATH)
    print(
        f"NIA zip {summary.zip_count}개 처리 완료: 전체 {summary.total_records}건 중 "
        f"10~30대 {summary.matched_records}건을 {_OUTPUT_PATH}에 저장했습니다."
    )


if __name__ == "__main__":
    # 국제 브랜드명은 안 다루지만, 카테고리명(예: 미백(색소침착_기미_칙칙함))이 Windows
    # 콘솔 기본 인코딩(cp949)으로 못 쓰는 문자를 포함할 가능성을 대비해 동일하게 처리한다.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _run()
