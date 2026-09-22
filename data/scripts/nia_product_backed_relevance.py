"""NIA 성분 언급 통계를 "실제 제품에 confirmed 로 연결된 성분"으로 제한한 Tier A 후보 view.

기준: NIA mention 이 있는 ingredient_id ∩ `product_ingredient.match_acceptance='confirmed'` 로
제품에 연결된 ingredient_id. 이 모듈은 후보 목록과 지표만 내며, 점수화·가중치·Tier A 선정은
하지 않는다. 기존 raw NIA relevance 산출물(진단용)도 그대로 함께 만든다.

사용법:
    uv run python -m data.scripts.nia_product_backed_relevance --input-root <2.데이터(NIA) 경로>
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import Database
from data.scripts.nia_ingredient_relevance import (
    NiaIngredientRelevanceRunner,
    NiaIngredientSummary,
    _labeling_zip_paths,
    _load_candidates,
)
from models.product import Product
from models.product_ingredient import (
    IngredientMatchAcceptance,
    ProductIngredient,
    ProductIngredientSnapshot,
)

TOP_N = 30
# 사용자가 후보에 남는지 별도로 확인하길 요청한 성분(standard_name_en, 소문자 비교)
WATCHLIST_INGREDIENTS = ("melanin", "tyrosinase", "mineral salts", "aloesin", "sulfur", "bha")

TIER_A_REVIEW_TOP_N = 20
THIN_PRODUCT_MAX = 3  # 이하면 제품 근거가 얇다고 표시(제외 기준 아님)
HIGH_NIA_CASE_MIN = 1000  # 이상이면 템플릿성 문구일 수 있어 검토 표시(제외 기준 아님)

_DEFAULT_OUTPUT_DIR = Path("data/processed")
_REVIEW_FILENAME = "nia_tier_a_review_table.csv"
_REVIEW_REPORT_FILENAME = "nia_tier_a_review_table.md"
_PRODUCT_BACKED_FILENAME = "nia_product_backed_ingredient_relevance.csv"
_PRODUCT_BACKED_REPORT_FILENAME = "nia_product_backed_ingredient_relevance_report.md"


class ProductBackedIngredientCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID
    product_count: int


class NiaProductBackedRelevance(BaseModel):
    ingredient_id: UUID
    standard_name_en: str | None
    standard_name_ko: str
    product_count: int
    nia_case_count: int
    nia_answer_case_count: int
    nia_cot_case_count: int
    nia_question_case_count: int
    target_concern_distribution: dict[str, int]


class ProductBackedIngredientReader:
    """confirmed 로 제품에 연결된 성분별 제품 수 조회 전용. commit 하지 않는다.

    제품 identity 는 기존 agent 조회 코드와 같이 `product` 의 (source, source_product_id) 를 쓴다.
    스냅샷을 재수집해 한 상품에 snapshot 이 여럿이 되어도 상품은 한 번만 센다.
    (현재 DB 는 snapshot_id 기준 개수와 같다.)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_counts(self) -> list[ProductBackedIngredientCount]:
        statement = (
            select(ProductIngredient.ingredient_id, func.count(distinct(Product.id)))
            .join(
                ProductIngredientSnapshot,
                ProductIngredientSnapshot.id == ProductIngredient.snapshot_id,
            )
            .join(
                Product,
                (Product.source == ProductIngredientSnapshot.source)
                & (Product.source_product_id == ProductIngredientSnapshot.source_product_id),
            )
            .where(
                ProductIngredient.match_acceptance == IngredientMatchAcceptance.CONFIRMED,
                ProductIngredient.ingredient_id.is_not(None),
            )
            .group_by(ProductIngredient.ingredient_id)
        )
        result = await self._session.execute(statement)
        return [
            ProductBackedIngredientCount(ingredient_id=row[0], product_count=row[1])
            for row in result.all()
        ]


class NiaProductBackedRelevanceBuilder:
    def build(
        self,
        summaries: list[NiaIngredientSummary],
        product_counts: list[ProductBackedIngredientCount],
    ) -> list[NiaProductBackedRelevance]:
        counts = {c.ingredient_id: c.product_count for c in product_counts}
        rows = [
            NiaProductBackedRelevance(
                ingredient_id=s.ingredient_id,
                standard_name_en=s.standard_name_en,
                standard_name_ko=s.standard_name_ko,
                product_count=counts[s.ingredient_id],
                nia_case_count=s.case_count,
                nia_answer_case_count=s.answer_case_count,
                nia_cot_case_count=s.cot_case_count,
                nia_question_case_count=s.question_case_count,
                target_concern_distribution=s.target_concern_distribution,
            )
            for s in summaries
            if counts.get(s.ingredient_id, 0) > 0  # product_count=0 성분은 후보에서 제외
        ]
        rows.sort(
            key=lambda r: (
                -r.nia_case_count,
                -r.nia_answer_case_count,
                -r.product_count,
                r.standard_name_en or "",
            )
        )
        return rows

    def write_csv(self, rows: list[NiaProductBackedRelevance], path: Path) -> None:
        columns = [
            "ingredient_id", "standard_name_en", "standard_name_ko", "product_count",
            "nia_case_count", "nia_answer_case_count", "nia_cot_case_count",
            "nia_question_case_count", "target_concern_unique_count",
            "target_concern_distribution_json",
        ]  # fmt: skip
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(columns)
            for r in rows:
                writer.writerow(
                    [
                        r.ingredient_id, r.standard_name_en or "", r.standard_name_ko,
                        r.product_count, r.nia_case_count, r.nia_answer_case_count,
                        r.nia_cot_case_count, r.nia_question_case_count,
                        len(r.target_concern_distribution),
                        json.dumps(r.target_concern_distribution, ensure_ascii=False),
                    ]
                )  # fmt: skip

    def build_report(
        self, rows: list[NiaProductBackedRelevance], summaries: list[NiaIngredientSummary]
    ) -> str:
        def line(i: int, r: NiaProductBackedRelevance) -> str:
            return (
                f"{i}. {r.standard_name_en or '-'} / {r.standard_name_ko} — "
                f"product {r.product_count}, NIA case {r.nia_case_count}, "
                f"answer {r.nia_answer_case_count}, cot {r.nia_cot_case_count}, "
                f"question {r.nia_question_case_count}"
            )

        by_answer = sorted(
            rows,
            key=lambda r: (-r.nia_answer_case_count, -r.nia_case_count, r.standard_name_en or ""),
        )[:TOP_N]
        by_product = sorted(
            rows, key=lambda r: (-r.product_count, -r.nia_case_count, r.standard_name_en or "")
        )[:TOP_N]
        # 점수식/가중치 없이 두 신호를 단순 사전순(NIA case 수 → 제품 수)으로만 나열한다
        combined = rows[:TOP_N]

        lines = [
            "# NIA product-backed ingredient relevance",
            "",
            f"- NIA unique ingredients: {len(summaries)}",
            f"- Product-backed NIA ingredients: {len(rows)}",
            f"- Excluded because no confirmed product: {len(summaries) - len(rows)}",
            "",
            f"## Top {TOP_N} by nia_answer_case_count",
            *[line(i, r) for i, r in enumerate(by_answer, 1)],
            "",
            f"## Top {TOP_N} by product_count",
            *[line(i, r) for i, r in enumerate(by_product, 1)],
            "",
            f"## Top {TOP_N} by combined presence (점수 없음: nia_case_count 후 product_count 순 나열)",
            *[line(i, r) for i, r in enumerate(combined, 1)],
            "",
            "## Watchlist (후보 잔존 여부)",
        ]
        kept = {(r.standard_name_en or "").lower(): r for r in rows}
        nia_only = {(s.standard_name_en or "").lower(): s for s in summaries}
        for name in WATCHLIST_INGREDIENTS:
            if name in kept:
                r = kept[name]
                lines.append(
                    f"- {name}: 남음 — product {r.product_count}, NIA case {r.nia_case_count}, "
                    f"answer {r.nia_answer_case_count}"
                )
            elif name in nia_only:
                lines.append(
                    f"- {name}: 제외됨(confirmed 제품 0건, NIA case {nia_only[name].case_count})"
                )
            else:
                lines.append(f"- {name}: NIA 언급 자체가 없음")
        return "\n".join(lines) + "\n"


class NiaTierAReviewRow(BaseModel):
    """사람이 검토하기 위한 한 줄. 점수가 아니라 원 지표와 주의 표시만 담는다."""

    rank: int
    ingredient_id: UUID
    standard_name_en: str | None
    standard_name_ko: str
    product_count: int
    nia_answer_case_count: int
    target_concern_unique_count: int
    nia_case_count: int
    cautions: list[str]


class NiaTierAReviewTable:
    """product-backed 후보를 nia_answer_case_count 순으로 나열한다(점수식 없음, 제외도 없음)."""

    def build(self, rows: list[NiaProductBackedRelevance]) -> list[NiaTierAReviewRow]:
        ordered = sorted(
            (r for r in rows if r.nia_answer_case_count > 0),
            key=lambda r: (-r.nia_answer_case_count, -r.product_count, r.standard_name_en or ""),
        )
        return [
            NiaTierAReviewRow(
                rank=i,
                ingredient_id=r.ingredient_id,
                standard_name_en=r.standard_name_en,
                standard_name_ko=r.standard_name_ko,
                product_count=r.product_count,
                nia_answer_case_count=r.nia_answer_case_count,
                target_concern_unique_count=len(r.target_concern_distribution),
                nia_case_count=r.nia_case_count,
                cautions=self._cautions(r),
            )
            for i, r in enumerate(ordered, 1)
        ]

    def _cautions(self, r: NiaProductBackedRelevance) -> list[str]:
        cautions = []
        if r.product_count <= THIN_PRODUCT_MAX:
            cautions.append(f"제품 근거 얇음(product {r.product_count})")
        if r.nia_case_count >= HIGH_NIA_CASE_MIN:
            cautions.append("NIA 언급 과다-템플릿 가능성")
        return cautions

    def write_csv(self, table: list[NiaTierAReviewRow], path: Path) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                ["rank", "ingredient_id", "standard_name_en", "standard_name_ko", "product_count",
                 "nia_answer_case_count", "target_concern_unique_count", "nia_case_count",
                 "cautions"]
            )  # fmt: skip
            for r in table:
                writer.writerow(
                    [r.rank, r.ingredient_id, r.standard_name_en or "", r.standard_name_ko,
                     r.product_count, r.nia_answer_case_count, r.target_concern_unique_count,
                     r.nia_case_count, "; ".join(r.cautions)]
                )  # fmt: skip

    def build_markdown(self, table: list[NiaTierAReviewRow]) -> str:
        def row(r: NiaTierAReviewRow) -> str:
            name = f"{r.standard_name_en or '-'} / {r.standard_name_ko}"
            return (
                f"| {r.rank} | {name} | {r.product_count} | {r.nia_answer_case_count} | "
                f"{r.target_concern_unique_count} | {'; '.join(r.cautions) or '-'} |"
            )

        header = [
            "| # | 성분 | product_count | nia_answer_case_count | concern 수 | 주의 |",
            "|---|---|---|---|---|---|",
        ]
        return "\n".join(
            [
                "# Tier A 후보 검토표 (점수 없음, nia_answer_case_count 순)",
                "",
                f"## 상위 {TIER_A_REVIEW_TOP_N}",
                *header,
                *[row(r) for r in table[:TIER_A_REVIEW_TOP_N]],
                "",
                f"## 나머지 ({len(table) - TIER_A_REVIEW_TOP_N}개, answer>0 인 product-backed 후보)",
                *header,
                *[row(r) for r in table[TIER_A_REVIEW_TOP_N:]],
                "",
            ]
        )


async def _run(input_root: Path, output_dir: Path) -> None:
    candidates = await _load_candidates()
    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            product_counts = await ProductBackedIngredientReader(session).list_counts()
    finally:
        await database.dispose()

    runner = NiaIngredientRelevanceRunner(candidates)
    mentions, summaries, stats = runner.run(_labeling_zip_paths(input_root))
    runner.write_outputs(mentions, summaries, stats, output_dir)  # raw 진단용 산출물도 유지

    builder = NiaProductBackedRelevanceBuilder()
    rows = builder.build(summaries, product_counts)
    builder.write_csv(rows, output_dir / _PRODUCT_BACKED_FILENAME)
    report = builder.build_report(rows, summaries)
    (output_dir / _PRODUCT_BACKED_REPORT_FILENAME).write_text(report, encoding="utf-8")
    review = NiaTierAReviewTable()
    table = review.build(rows)
    review.write_csv(table, output_dir / _REVIEW_FILENAME)
    markdown = review.build_markdown(table)
    (output_dir / _REVIEW_REPORT_FILENAME).write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True, help="'2.데이터(NIA)' 폴더")
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    asyncio.run(_run(args.input_root, args.output_dir))
