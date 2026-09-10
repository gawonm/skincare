"""`ProductCandidateRow` 목록을 `product_candidates.csv` 로 저장한다.

이 CSV 는 여러 소스(네이버 쇼핑, 올리브영 글로벌 등)가 같이 쓴다. 한 소스의 수집
스크립트를 다시 돌려도 다른 소스가 이미 써 놓은 행을 지우면 안 되므로, 저장 전에 기존
파일을 읽어 "이번에 넘어온 소스"에 해당하는 행만 새 값으로 교체하고 나머지는 보존한다.
"""

import csv
from pathlib import Path

from scripts.product_candidate_schemas import DataSource, ProductCandidateRow

_FIELDNAMES = [
    "candidate_id",
    "source",
    "target_group",
    "search_query",
    "source_product_id",
    "raw_title",
    "display_title",
    "title_source",
    "brand",
    "maker",
    "category1",
    "category2",
    "category3",
    "lowest_price",
    "highest_price",
    "price_band",
    "volume_value",
    "volume_unit",
    "image_url",
    "local_image_path",
    "raw_ingredients_text",
    "shopping_url",
    "mall_name",
    "product_type",
    "observed_at",
    "match_status",
    "review_reasons",
]

# CSV 에 빈 문자열로 저장되는 필드 중, 모델에서는 `None` 이 정답인 필드.
# 나머지 필드(예: `maker`)는 빈 문자열 자체가 유효한 값이라 이 목록에 넣지 않는다.
_NULLABLE_FIELD_NAMES = ("target_group", "volume_value", "volume_unit", "raw_ingredients_text")

# `review_reasons` 는 리스트라 다른 manual_review CSV(`review_candidate_ids` 등)와
# 같은 관례로 "|" 구분 문자열로 저장한다.
_REVIEW_REASONS_SEPARATOR = "|"


class ProductCandidateCsvWriter:
    def write(self, rows: list[ProductCandidateRow], output_path: Path) -> None:
        current_sources: set[DataSource] = {row.source for row in rows}
        preserved_rows = [
            existing_row
            for existing_row in self.read_existing_rows(output_path)
            if existing_row.source not in current_sources
        ]
        combined_rows = preserved_rows + rows

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=_FIELDNAMES)
            writer.writeheader()
            for row in combined_rows:
                writer.writerow(self._to_csv_dict(row))

    def read_existing_rows(self, output_path: Path) -> list[ProductCandidateRow]:
        if not output_path.exists():
            return []

        with output_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            return [
                ProductCandidateRow.model_validate(self._from_csv_dict(raw_row))
                for raw_row in reader
            ]

    def _from_csv_dict(self, raw_row: dict[str, str]) -> dict[str, str | None | list[str]]:
        result: dict[str, str | None | list[str]] = dict(raw_row)
        for field_name in _NULLABLE_FIELD_NAMES:
            if result.get(field_name) == "":
                result[field_name] = None
        review_reasons = result.get("review_reasons")
        if isinstance(review_reasons, str):
            result["review_reasons"] = (
                review_reasons.split(_REVIEW_REASONS_SEPARATOR) if review_reasons else []
            )
        return result

    def _to_csv_dict(self, row: ProductCandidateRow) -> dict[str, str]:
        # mode="json" 은 Enum 을 .value 문자열로, datetime 을 ISO 문자열로 바꿔 준다.
        dumped = row.model_dump(mode="json")
        dumped["review_reasons"] = _REVIEW_REASONS_SEPARATOR.join(dumped["review_reasons"])
        return {key: ("" if value is None else value) for key, value in dumped.items()}
