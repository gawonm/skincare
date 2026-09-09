"""KCIA 성분표준화명칭목록 PDF를 `IngredientMaster` 테이블에 적재하는 진입점.

사용법:
    uv run python -m scripts.import_kcia_ingredients "data/별첨1. 표준화명칭목록_260831.pdf"

`source_version` 은 파일명 끝의 YYMMDD(예: 260831 -> 2026-08-31)에서 뽑는다.
파일명 규칙이 바뀌면 이 파싱도 같이 고쳐야 한다.
"""

import argparse
import asyncio
import re
from datetime import date

from core.config import settings
from core.database import Database
from scripts.ingredient_name_normalizer import IngredientNameNormalizer
from scripts.kcia_ingredient_importer import KciaIngredientImporter
from scripts.kcia_pdf_parser import KciaPdfParser

_FILENAME_DATE_PATTERN = re.compile(r"(\d{2})(\d{2})(\d{2})\.pdf$")


def _source_version_from_filename(pdf_path: str) -> str:
    match = _FILENAME_DATE_PATTERN.search(pdf_path)
    if not match:
        raise ValueError(
            f"파일명에서 발행 버전(YYMMDD)을 찾지 못했습니다: {pdf_path!r}. "
            "--source-version 옵션으로 직접 지정하세요."
        )
    yy, mm, dd = match.groups()
    return date(2000 + int(yy), int(mm), int(dd)).isoformat()


async def _run(pdf_path: str, source_version: str) -> None:
    rows = KciaPdfParser().parse(pdf_path)
    print(f"PDF에서 {len(rows)}개 행을 읽었습니다.")

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            importer = KciaIngredientImporter(session, IngredientNameNormalizer())
            summary = await importer.import_rows(rows, source_version)
            await session.commit()
    finally:
        await database.dispose()

    print(
        f"적재 완료: 총 {summary.total_rows}건 "
        f"(신규 {summary.inserted}건, 갱신 {summary.updated}건, "
        f"건너뜀 {summary.skipped_invalid_rows}건)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", help="KCIA 표준화명칭목록 PDF 경로")
    parser.add_argument(
        "--source-version",
        default=None,
        help="발행 버전 문자열. 생략하면 파일명 끝의 YYMMDD 에서 자동으로 뽑는다.",
    )
    args = parser.parse_args()

    source_version = args.source_version or _source_version_from_filename(args.pdf_path)
    asyncio.run(_run(args.pdf_path, source_version))


if __name__ == "__main__":
    main()
