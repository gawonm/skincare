"""`product_candidates.csv` 를 팀 전달용으로 정제한다: RDB에서 읽은 ingredient master와
전성분 원문을 deterministic하게 매칭해 product-ingredient 관계를 만들고, 각 상품 후보 행을
valid/excluded/review_required 로 분류한다. RAG/LLM을 거치지 않는다.

사용법:
    uv run python -m data.scripts.build_product_datasets
"""

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from core.config import settings
from core.database import Database
from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.ingredient_schemas import IngredientMatchMethod
from data.scripts.product_candidate_csv_writer import ProductCandidateCsvWriter
from data.scripts.product_candidate_schemas import MatchStatus, ProductCandidateRow, TargetGroup
from data.scripts.product_ingredient_mapping_schemas import (
    ProductIngredientMappingRow,
    ProductQualityRow,
    ProductQualityStatus,
)
from data.scripts.product_ingredient_text_parser import ProductIngredientTextParser
from data.scripts.product_ingredient_mapping_csv_writer import (
    ProductIngredientMappingCsvWriter,
    ProductQualityCsvWriter,
)

_CANDIDATES_CSV_PATH = Path("data/processed/product_candidates.csv")
_MAPPING_OUTPUT_PATH = Path("data/processed/product_ingredient_mapping.csv")
_QUALITY_OUTPUT_PATH = Path("data/processed/product_quality_report.csv")

# fuzzy·다중후보 매칭은 자동 매칭으로 인정하지 않는다(사용자 규칙 7).
_DETERMINISTIC_METHODS = frozenset(
    {
        IngredientMatchMethod.STANDARD_NAME_KO,
        IngredientMatchMethod.STANDARD_NAME_EN_NORMALIZED,
        IngredientMatchMethod.OLD_NAME_KO,
        IngredientMatchMethod.OLD_NAME_EN_NORMALIZED,
        IngredientMatchMethod.ANNOTATION_STRIPPED_KO,
        IngredientMatchMethod.ANNOTATION_STRIPPED_EN_NORMALIZED,
    }
)


class ProductIngredientMappingBuilder:
    def __init__(self, parser: ProductIngredientTextParser, matcher: IngredientNameMatcher) -> None:
        self._parser = parser
        self._matcher = matcher

    def build(self, row: ProductCandidateRow) -> list[ProductIngredientMappingRow]:
        if not row.raw_ingredients_text:
            return []
        parse_result = self._parser.parse(row.source, row.source_product_id, row.raw_ingredients_text)
        mapping_rows: list[ProductIngredientMappingRow] = []
        for section in parse_result.sections:
            for token in section.tokens:
                match = self._matcher.match(raw_name_ko=None, raw_name_en=token.matching_name)
                is_deterministic = match.method in _DETERMINISTIC_METHODS
                mapping_rows.append(
                    ProductIngredientMappingRow(
                        candidate_id=row.candidate_id,
                        source=row.source,
                        source_product_id=row.source_product_id,
                        target_group=row.target_group,
                        raw_token=token.raw_token,
                        matching_name=token.matching_name,
                        ingredient_id=match.matched_ingredient_id if is_deterministic else None,
                        matching_status="matched" if is_deterministic else "unresolved",
                        match_method=match.method.value,
                    )
                )
        return mapping_rows


class ProductQualityClassifier:
    """`match_status`/`review_reasons`/전성분 존재 여부/target_group 정합성으로 품질을 판정한다."""

    def __init__(self, target_group_ingredient_ids: dict[str, object]) -> None:
        # TargetGroup 값 자체가 KCIA 표준 국문명이므로(TargetGroup docstring), 후보의
        # standard_name_ko exact match로 target_group -> ingredient_id를 한 번만 구한다.
        self._target_group_ingredient_ids = target_group_ingredient_ids

    def classify(
        self,
        rows: list[ProductCandidateRow],
        mapping_by_candidate: dict[str, list[ProductIngredientMappingRow]],
    ) -> list[ProductQualityRow]:
        duplicate_keys = self._duplicate_natural_keys(rows)
        results = []
        for row in rows:
            reasons: list[str] = []
            if row.match_status == MatchStatus.REJECTED:
                reasons.append("match_status_rejected")
            if row.raw_ingredients_text is None:
                reasons.append("missing_raw_ingredients_text")
            if row.review_reasons:
                reasons.extend(f"review_reason:{r.value}" for r in row.review_reasons)
            natural_key = (row.source, row.source_product_id, row.target_group)
            if natural_key in duplicate_keys:
                reasons.append("duplicate_candidate_row")
            if row.target_group is not None and row.raw_ingredients_text is not None:
                expected_id = self._target_group_ingredient_ids.get(row.target_group.value)
                mapped = mapping_by_candidate.get(row.candidate_id, [])
                target_matched = expected_id is not None and any(
                    m.ingredient_id == expected_id for m in mapped
                )
                if not target_matched:
                    reasons.append("target_group_not_confirmed_in_ingredients")

            if "match_status_rejected" in reasons:
                status = ProductQualityStatus.EXCLUDED
            elif reasons:
                status = ProductQualityStatus.REVIEW_REQUIRED
            else:
                status = ProductQualityStatus.VALID

            results.append(
                ProductQualityRow(
                    candidate_id=row.candidate_id,
                    source=row.source,
                    source_product_id=row.source_product_id,
                    target_group=row.target_group,
                    status=status,
                    reasons=tuple(reasons),
                )
            )
        return results

    def _duplicate_natural_keys(self, rows: list[ProductCandidateRow]) -> set[tuple]:
        seen: dict[tuple, int] = defaultdict(int)
        for row in rows:
            seen[(row.source, row.source_product_id, row.target_group)] += 1
        return {key for key, count in seen.items() if count > 1}


async def _run() -> None:
    rows = ProductCandidateCsvWriter().read_existing_rows(_CANDIDATES_CSV_PATH)
    if not rows:
        raise RuntimeError(f"{_CANDIDATES_CSV_PATH}에 읽을 행이 없습니다.")

    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            candidates = await IngredientMasterRepository(session).list_all_as_candidates()
    finally:
        await database.dispose()

    matcher = IngredientNameMatcher(candidates, IngredientNameNormalizer())
    mapping_builder = ProductIngredientMappingBuilder(ProductIngredientTextParser(), matcher)
    target_group_ingredient_ids = {
        c.standard_name_ko: c.ingredient_id
        for c in candidates
        if c.standard_name_ko in {g.value for g in TargetGroup}
    }

    all_mappings: list[ProductIngredientMappingRow] = []
    mapping_by_candidate: dict[str, list[ProductIngredientMappingRow]] = defaultdict(list)
    for row in rows:
        product_mappings = mapping_builder.build(row)
        all_mappings.extend(product_mappings)
        mapping_by_candidate[row.candidate_id].extend(product_mappings)

    quality_rows = ProductQualityClassifier(target_group_ingredient_ids).classify(
        rows, mapping_by_candidate
    )

    ProductIngredientMappingCsvWriter().write(all_mappings, _MAPPING_OUTPUT_PATH)
    ProductQualityCsvWriter().write(quality_rows, _QUALITY_OUTPUT_PATH)

    matched_tokens = sum(1 for m in all_mappings if m.ingredient_id is not None)
    status_counts: dict[str, int] = defaultdict(int)
    for q in quality_rows:
        status_counts[q.status.value] += 1

    print(f"제품 후보 {len(rows)}건, 전성분 토큰 {len(all_mappings)}개 (deterministic 매칭 {matched_tokens}개)")
    print(f"품질: {dict(status_counts)}")
    print(f"저장: {_MAPPING_OUTPUT_PATH}, {_QUALITY_OUTPUT_PATH}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_run())
