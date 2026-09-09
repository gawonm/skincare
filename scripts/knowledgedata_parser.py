"""Knowledgedata.xlsx 파싱.

시트는 `Sheet1` 하나이고, 1행은 공백, 2행이 헤더, 3행부터 데이터다. 컬럼 순서는
[No, 성분명(INCI), 한글명, 화학적물성, 제품적특성, 원료출처, 용해도, 분자식, 분자량,
효능, 권장피부타입, 사용상주의사항, 권장농도, 배합규제, 원시데이터출처, 저작권해결방안, 토큰].

이 파일은 NIA AI Hub "스킨케어 성분-효능 추천 데이터"(dataset 71886)의 원천데이터③
`지식성분데이터.xlsx`와 byte 단위로 동일한 파일임을 확인했다(2026-09-09, 전체 2,465행
diff 0건). 화학적물성·제품적특성·용해도·분자식·분자량·저작권해결방안·토큰 컬럼도 이제
RAG 신뢰도 티어링(`저작권해결방안`)과 성분 상세 정보에 쓰이므로 함께 읽는다.

`No` 컬럼은 2,465개 중 451개가 비어 있는 원본 데이터 품질 문제가 있어 행 식별자로
쓰지 않는다. 대신 실제 엑셀 행 번호(`_DATA_START_ROW` 부터 순서대로 매기는 값)를
`source_row_no` 로 쓴다.
"""

import openpyxl

from scripts.ingredient_schemas import KnowledgedataRow

_DATA_START_ROW = 3
_COLUMN_INCI_NAME = 1
_COLUMN_NAME_KO = 2
_COLUMN_CHEMICAL_PROPERTIES = 3
_COLUMN_PRODUCT_CHARACTERISTICS = 4
_COLUMN_RAW_MATERIAL_SOURCE = 5
_COLUMN_SOLUBILITY = 6
_COLUMN_MOLECULAR_FORMULA = 7
_COLUMN_MOLECULAR_WEIGHT = 8
_COLUMN_EFFICACY = 9
_COLUMN_RECOMMENDED_SKIN_TYPES = 10
_COLUMN_PRECAUTIONS = 11
_COLUMN_RECOMMENDED_CONCENTRATION = 12
_COLUMN_COMPOUNDING_REGULATION_TEXT = 13
_COLUMN_SOURCE_REFERENCE = 14
_COLUMN_COPYRIGHT_RESOLUTION = 15
_COLUMN_TOKEN_COUNT = 16


class KnowledgedataParser:
    """Knowledgedata.xlsx를 `KnowledgedataRow` 목록으로 바꾼다."""

    def parse(self, xlsx_path: str) -> list[KnowledgedataRow]:
        workbook = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
        try:
            worksheet = workbook["Sheet1"]
            rows: list[KnowledgedataRow] = []
            for sheet_row_number, raw_row in enumerate(
                worksheet.iter_rows(min_row=_DATA_START_ROW, values_only=True),
                start=_DATA_START_ROW,
            ):
                row = self._parse_row(sheet_row_number, raw_row)
                if row is not None:
                    rows.append(row)
            return rows
        finally:
            workbook.close()

    def _parse_row(
        self, sheet_row_number: int, raw_row: tuple[object, ...]
    ) -> KnowledgedataRow | None:
        inci_name = self._clean(raw_row[_COLUMN_INCI_NAME])
        if inci_name is None:
            return None

        return KnowledgedataRow(
            source_row_no=sheet_row_number,
            inci_name=inci_name,
            name_ko=self._clean(raw_row[_COLUMN_NAME_KO]),
            chemical_properties=self._clean(raw_row[_COLUMN_CHEMICAL_PROPERTIES]),
            product_characteristics=self._clean(raw_row[_COLUMN_PRODUCT_CHARACTERISTICS]),
            solubility=self._clean(raw_row[_COLUMN_SOLUBILITY]),
            molecular_formula=self._clean(raw_row[_COLUMN_MOLECULAR_FORMULA]),
            molecular_weight=self._clean(raw_row[_COLUMN_MOLECULAR_WEIGHT]),
            efficacy=self._clean(raw_row[_COLUMN_EFFICACY]),
            recommended_skin_types=self._clean(raw_row[_COLUMN_RECOMMENDED_SKIN_TYPES]),
            precautions=self._clean(raw_row[_COLUMN_PRECAUTIONS]),
            recommended_concentration=self._clean(raw_row[_COLUMN_RECOMMENDED_CONCENTRATION]),
            compounding_regulation_text=self._clean(raw_row[_COLUMN_COMPOUNDING_REGULATION_TEXT]),
            raw_material_source=self._clean(raw_row[_COLUMN_RAW_MATERIAL_SOURCE]),
            source_reference=self._clean(raw_row[_COLUMN_SOURCE_REFERENCE]),
            copyright_resolution=self._clean(raw_row[_COLUMN_COPYRIGHT_RESOLUTION]),
            token_count=self._clean(raw_row[_COLUMN_TOKEN_COUNT]),
        )

    def _clean(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
