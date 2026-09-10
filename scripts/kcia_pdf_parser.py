"""KCIA 성분표준화명칭목록 PDF 표 추출.

컬럼 순서는 [성분코드, 표준 성분명, 표준 영문명, 구명칭, 구영문명] 로 고정돼 있다.
페이지마다 헤더 행이 반복되므로 첫 칸이 정수로 파싱되지 않는 행은 건너뛴다.

긴 명칭은 셀 안에서 줄바꿈되어 잘린다. 국문은 한 단어가 줄바꿈으로 쪼개지므로 그대로
이어붙이고, 영문은 단어 사이에서 줄바꿈되므로 공백으로 이어붙인다.
"""

import pdfplumber

from scripts.ingredient_schemas import KciaIngredientRow

_EXPECTED_COLUMN_COUNT = 5
_OLD_NAME_SEPARATOR = "|"


class KciaPdfParser:
    """KCIA 표준화명칭목록 PDF를 `KciaIngredientRow` 목록으로 바꾼다."""

    def parse(self, pdf_path: str) -> list[KciaIngredientRow]:
        rows: list[KciaIngredientRow] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    rows.extend(self._parse_table(table))
        return rows

    def _parse_table(self, table: list[list[str | None]]) -> list[KciaIngredientRow]:
        parsed: list[KciaIngredientRow] = []
        for raw_row in table:
            row = self._parse_row(raw_row)
            if row is not None:
                parsed.append(row)
        return parsed

    def _parse_row(self, raw_row: list[str | None]) -> KciaIngredientRow | None:
        if len(raw_row) != _EXPECTED_COLUMN_COUNT:
            return None

        ingredient_code_text = (raw_row[0] or "").strip()
        if not ingredient_code_text.isdigit():
            # 헤더 행("성분코드" 등) 또는 손상된 행.
            return None

        standard_name_ko = self._join_wrapped_korean(raw_row[1])
        if not standard_name_ko:
            return None

        return KciaIngredientRow(
            ingredient_code=int(ingredient_code_text),
            standard_name_ko=standard_name_ko,
            standard_name_en=self._join_wrapped_english(raw_row[2]) or None,
            old_names_ko=self._split_old_names(self._join_wrapped_korean(raw_row[3])),
            old_names_en=self._split_old_names(self._join_wrapped_english(raw_row[4])),
        )

    def _join_wrapped_korean(self, cell: str | None) -> str:
        return (cell or "").replace("\n", "").strip()

    def _join_wrapped_english(self, cell: str | None) -> str:
        text = (cell or "").replace("\n", " ").strip()
        return " ".join(text.split())

    def _split_old_names(self, cell: str) -> tuple[str, ...]:
        if not cell:
            return ()
        return tuple(name.strip() for name in cell.split(_OLD_NAME_SEPARATOR) if name.strip())
