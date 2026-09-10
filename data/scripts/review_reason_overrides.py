"""자동으로는 판단할 수 없는 검토 사유(`ReviewReason`)를 상품 ID 기준으로 수동으로 붙인다.

예: raw_title 이 브랜드 공식 표기와 다르다는 의심(`RAW_TITLE_SOURCE_CONFLICT`)은 사람이
실제 브랜드 페이지를 찾아봐야 확인되는 것이라 코드가 자동으로 채울 수 없다.
`data/manual_review/review_reason_overrides.csv` 에 발견할 때마다 추가한다.
"""

import csv
from collections import defaultdict
from pathlib import Path

from data.scripts.product_candidate_schemas import ReviewReason

_OVERRIDE_FILE_PATH = Path("data/manual_review/review_reason_overrides.csv")


class ReviewReasonOverrides:
    def __init__(self, override_file_path: Path = _OVERRIDE_FILE_PATH) -> None:
        self._reasons_by_product_id: dict[str, list[ReviewReason]] = self._load(override_file_path)

    def get(self, source_product_id: str) -> tuple[ReviewReason, ...]:
        return tuple(self._reasons_by_product_id.get(source_product_id, []))

    def _load(self, override_file_path: Path) -> dict[str, list[ReviewReason]]:
        if not override_file_path.exists():
            return {}

        reasons_by_product_id: dict[str, list[ReviewReason]] = defaultdict(list)
        with override_file_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                reasons_by_product_id[row["source_product_id"]].append(
                    ReviewReason(row["review_reason"])
                )
        return dict(reasons_by_product_id)
