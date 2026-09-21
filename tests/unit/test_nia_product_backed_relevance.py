from uuid import uuid4

from data.scripts.nia_ingredient_relevance import NiaIngredientSummary
from data.scripts.nia_product_backed_relevance import (
    NiaProductBackedRelevanceBuilder,
    ProductBackedIngredientCount,
)

BACKED = uuid4()
NO_PRODUCT = uuid4()
ABSENT = uuid4()


def _summary(ingredient_id, en: str, case_count: int) -> NiaIngredientSummary:
    return NiaIngredientSummary(
        ingredient_id=ingredient_id,
        standard_name_en=en,
        standard_name_ko=en,
        case_count=case_count,
        mention_count=case_count,
        question_case_count=1,
        answer_case_count=2,
        cot_case_count=3,
        target_concern_distribution={"모공": case_count},
    )


def test_only_ingredients_with_confirmed_products_remain() -> None:
    summaries = [_summary(BACKED, "Niacinamide", 5), _summary(NO_PRODUCT, "Melanin", 9)]
    counts = [
        ProductBackedIngredientCount(ingredient_id=BACKED, product_count=7),
        ProductBackedIngredientCount(ingredient_id=NO_PRODUCT, product_count=0),
        ProductBackedIngredientCount(ingredient_id=ABSENT, product_count=3),  # NIA 언급 없음
    ]
    builder = NiaProductBackedRelevanceBuilder()
    rows = builder.build(summaries, counts)
    assert [r.ingredient_id for r in rows] == [BACKED]
    assert rows[0].product_count == 7 and rows[0].nia_answer_case_count == 2
    report = builder.build_report(rows, summaries)
    assert "Excluded because no confirmed product: 1" in report
    assert "melanin: 제외됨" in report and "tyrosinase: NIA 언급 자체가 없음" in report
