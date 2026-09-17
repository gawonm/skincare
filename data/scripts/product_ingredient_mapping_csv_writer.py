"""`ProductIngredientMappingRow`/`ProductQualityRow` 목록을 CSV로 저장한다."""

import csv
from pathlib import Path

from data.scripts.product_ingredient_mapping_schemas import (
    ProductIngredientMappingRow,
    ProductQualityRow,
)

_MAPPING_FIELDNAMES = [
    "candidate_id",
    "source",
    "source_product_id",
    "target_group",
    "raw_token",
    "matching_name",
    "ingredient_id",
    "matching_status",
    "match_method",
]

_QUALITY_FIELDNAMES = ["candidate_id", "source", "source_product_id", "target_group", "status", "reasons"]


class ProductIngredientMappingCsvWriter:
    def write(self, rows: list[ProductIngredientMappingRow], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=_MAPPING_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                dumped = row.model_dump(mode="json")
                writer.writerow({k: ("" if v is None else v) for k, v in dumped.items()})


class ProductQualityCsvWriter:
    def write(self, rows: list[ProductQualityRow], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=_QUALITY_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                dumped = row.model_dump(mode="json")
                dumped["reasons"] = "|".join(dumped["reasons"])
                writer.writerow({k: ("" if v is None else v) for k, v in dumped.items()})
