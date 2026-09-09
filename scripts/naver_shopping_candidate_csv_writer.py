"""`ProductCandidateRow` 목록을 `product_candidates.csv` 로 저장한다."""

import csv
from pathlib import Path

from scripts.naver_shopping_schemas import ProductCandidateRow

_FIELDNAMES = [
    "candidate_id",
    "target_group",
    "search_query",
    "naver_product_id",
    "raw_title",
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
    "shopping_url",
    "mall_name",
    "product_type",
    "observed_at",
    "match_status",
]


class ProductCandidateCsvWriter:
    def write(self, rows: list[ProductCandidateRow], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                writer.writerow(self._to_csv_dict(row))

    def _to_csv_dict(self, row: ProductCandidateRow) -> dict[str, str]:
        # mode="json" 은 Enum 을 .value 문자열로, datetime 을 ISO 문자열로 바꿔 준다.
        dumped = row.model_dump(mode="json")
        return {key: ("" if value is None else value) for key, value in dumped.items()}
