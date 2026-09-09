"""`raw_title` 에 대응하는 화면 노출용 한글 상품명(`display_title`)을 찾는다.

번역은 이 클래스가 즉석에서 하지 않는다. `data/manual_review/product_title_translations.csv`
에 미리 채워 둔 매핑을 찾아볼 뿐이다 — 이 파일은 사람(또는 LLM)이 검수해서 채우는
수작업 결과물이다. 매핑에 없는 상품은 원문(raw_title) 그대로에
`TitleSource.UNTRANSLATED` 를 붙여 돌려준다. 즉 "번역 안 됨"이 기본값이고, 조용히
번역된 척하지 않는다.
"""

import csv
from pathlib import Path

from scripts.product_candidate_schemas import TitleSource

_TRANSLATION_FILE_PATH = Path("data/manual_review/product_title_translations.csv")


class ProductTitleTranslator:
    def __init__(self, translation_file_path: Path = _TRANSLATION_FILE_PATH) -> None:
        self._translations: dict[str, tuple[str, TitleSource]] = self._load(translation_file_path)

    def translate(self, raw_title: str) -> tuple[str, TitleSource]:
        if raw_title in self._translations:
            return self._translations[raw_title]
        return raw_title, TitleSource.UNTRANSLATED

    def _load(self, translation_file_path: Path) -> dict[str, tuple[str, TitleSource]]:
        if not translation_file_path.exists():
            return {}

        with translation_file_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            return {
                row["raw_title"]: (row["display_title"], TitleSource(row["title_source"]))
                for row in reader
            }
