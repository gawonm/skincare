"""`IngredientDatasetRow` 목록을 `ingredient_full.csv` 로 저장한다."""

import csv
from pathlib import Path

from data.scripts.ingredient_schemas import IngredientDatasetRow

_FIELDNAMES = [
    "ingredient_id",
    "ingredient_code",
    "standard_name_ko",
    "standard_name_en",
    "old_names_ko",
    "old_names_en",
    "source_version",
    "knowledge_inci_name",
    "knowledge_efficacy",
    "knowledge_recommended_skin_types",
    "knowledge_precautions",
    "knowledge_recommended_concentration",
    "knowledge_regulatory_confidence",
    "evidence_count",
    "evidence_jurisdictions",
    "evidence_claims",
]


class IngredientDatasetCsvWriter:
    def write(self, rows: list[IngredientDatasetRow], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                dumped = row.model_dump(mode="json")
                writer.writerow(
                    {key: ("" if value is None else value) for key, value in dumped.items()}
                )
