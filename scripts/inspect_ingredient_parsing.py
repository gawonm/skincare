"""전성분 원문 파싱·옵션 연결 결과를 사람이 검토할 수 있게 요약한다.

DB에 아무것도 쓰지 않는다. `ProductIngredientTextParser`/`ProductIngredientOptionLinker`
가 실제 수집 데이터(`data/processed/product_candidates.csv`)에서 얼마나 잘 동작하는지
확인하고, `needs_review`/`AMBIGUOUS` 로 남은 항목을 사람이 훑어볼 수 있는 리포트 파일로
만드는 용도다. 저장 모델(`ProductIngredientSnapshot`/`ProductIngredient`)은 이 리포트로
파서를 검증한 뒤에 확정한다(docs/oliveyoung_global_pipeline_handoff.md 참고).
"""

import csv
from pathlib import Path

from scripts.oliveyoung_global_client import OliveYoungGlobalClient
from scripts.product_candidate_schemas import DataSource
from scripts.product_ingredient_option_linker import ProductIngredientOptionLinker
from scripts.product_ingredient_parse_schemas import (
    IngredientSectionLinkStatus,
    IngredientTokenParseStatus,
    ProductIngredientParseResult,
)
from scripts.product_ingredient_text_parser import ProductIngredientTextParser

_CANDIDATES_CSV_PATH = Path("data/processed/product_candidates.csv")
_REPORT_PATH = Path("data/manual_review/ingredient_parse_sample_report.txt")


class IngredientParsingInspector:
    def __init__(self) -> None:
        self._parser = ProductIngredientTextParser()
        self._linker = ProductIngredientOptionLinker()
        self._client = OliveYoungGlobalClient()

    def run(self) -> None:
        all_rows = self._read_rows_with_ingredients_text()
        rows = self._dedupe_by_product_id(all_rows)
        duplicate_row_count = len(all_rows) - len(rows)

        report_sections: list[str] = []
        total_tokens = 0
        needs_review_tokens = 0
        products_with_review = 0
        link_status_counts: dict[str, int] = {}

        for row in rows:
            result = self._parser.parse(
                DataSource.OLIVEYOUNG_GLOBAL, row["source_product_id"], row["raw_ingredients_text"]
            )
            has_option_sections = any(
                section.section_label is not None for section in result.sections
            )
            if has_option_sections:
                detail = self._client.get_product_detail(row["source_product_id"])
                result = self._linker.link(result, tuple(detail.option_list))

            product_review_tokens = 0
            for section in result.sections:
                link_status_counts[section.link_status.value] = (
                    link_status_counts.get(section.link_status.value, 0) + 1
                )
                for token in section.tokens:
                    total_tokens += 1
                    if token.parse_status == IngredientTokenParseStatus.NEEDS_REVIEW:
                        needs_review_tokens += 1
                        product_review_tokens += 1
            if product_review_tokens > 0:
                products_with_review += 1

            report_sections.append(
                self._format_product(row["candidate_id"], row["source_product_id"], result)
            )

        self._client.close()

        summary_lines = [
            "=== 요약 ===",
            f"CSV 행 수(전성분 원문 있는 행, target_group 별로 1행): {len(all_rows)}",
            f"고유 상품 수(source_product_id 기준, 중복 제외): {len(rows)}",
            (
                f"  └ 같은 상품이 다른 target_group 행에도 등장해 건너뛴 중복 행: "
                f"{duplicate_row_count} (duplicate_product_across_groups — 원문은 동일해 한 번만 파싱)"
            ),
            f"전체 성분 토큰 수: {total_tokens}",
            f"needs_review 토큰 수: {needs_review_tokens} ({self._percent(needs_review_tokens, total_tokens)})",
            f"needs_review 토큰이 하나라도 있는 상품 수: {products_with_review}",
            "구간 연결 상태 분포: " + ", ".join(f"{k}={v}" for k, v in sorted(link_status_counts.items())),
        ]
        summary = "\n".join(summary_lines)

        _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _REPORT_PATH.write_text(summary + "\n\n" + "\n\n".join(report_sections), encoding="utf-8")
        print(summary)
        print(f"\n상세 리포트: {_REPORT_PATH}")

    def _read_rows_with_ingredients_text(self) -> list[dict[str, str]]:
        with _CANDIDATES_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            return [
                row
                for row in reader
                if row["source"] == DataSource.OLIVEYOUNG_GLOBAL.value and row["raw_ingredients_text"]
            ]

    def _dedupe_by_product_id(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        # 상품 식별자는 (source, source_product_id) 조합이다 — `candidate_id`는 재수집마다
        # 바뀔 수 있어 식별자로 안 쓴다(docs/oliveyoung_global_pipeline_handoff.md 4절).
        # 같은 상품이 다른 target_group 행에도 등장하면(duplicate_product_across_groups)
        # raw_ingredients_text 는 동일하므로 한 번만 파싱한다.
        seen_product_ids: set[str] = set()
        deduped: list[dict[str, str]] = []
        for row in rows:
            product_id = row["source_product_id"]
            if product_id in seen_product_ids:
                continue
            seen_product_ids.add(product_id)
            deduped.append(row)
        return deduped

    def _format_product(
        self, candidate_id: str, source_product_id: str, result: ProductIngredientParseResult
    ) -> str:
        lines = [f"## {candidate_id} ({source_product_id})"]
        for section in result.sections:
            label = section.section_label or "(옵션 구간 없음)"
            lines.append(f"  [{label}] link={section.link_status.value} gds_cd={section.linked_option_gds_cd}")
            for token in section.tokens:
                if token.parse_status == IngredientTokenParseStatus.NEEDS_REVIEW:
                    lines.append(f"    ⚠ {token.raw_token!r} — {token.review_reason}")
            if section.link_status == IngredientSectionLinkStatus.AMBIGUOUS:
                lines.append(f"    ⚠ 옵션 연결 미확정 (라벨 {section.section_label!r})")
        return "\n".join(lines)

    @staticmethod
    def _percent(part: int, whole: int) -> str:
        if whole == 0:
            return "0.0%"
        return f"{part / whole * 100:.1f}%"


if __name__ == "__main__":
    IngredientParsingInspector().run()
