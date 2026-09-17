"""usage_instruction의 ingredient linkage 수정 검증. LLM/DB 호출 없이 `LlmNiaLabelingOutput`을
직접 구성해 `NiaPilotRecordProcessor._build_statements()`만 통과시킨다(라벨링 자체는 이미
`NiaLlmLabeler`가 담당하고 이 클래스가 호출하지 않으므로, `labeler`/`provenance`는 이 메서드
경로에서 쓰이지 않아 더미로 둔다).
"""

from uuid import uuid4

from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.ingredient_schemas import IngredientCandidate
from data.scripts.nia_ingredient_matching_stage import NiaIngredientMatchingStage
from data.scripts.nia_llm_label_schemas import (
    LlmCombinationClaimStatement,
    LlmIngredientEffectClaimStatement,
    LlmIngredientMention,
    LlmNiaLabelingOutput,
    LlmSourceQuote,
    LlmUsageInstructionStatement,
)
from data.scripts.nia_pilot_runner import NiaPilotRecordProcessor
from data.scripts.nia_source_span_builder import NiaSourceSpanBuilder

_NIACINAMIDE_ID = uuid4()
_RETINOL_ID = uuid4()


def _candidates() -> list[IngredientCandidate]:
    return [
        IngredientCandidate(
            ingredient_id=_NIACINAMIDE_ID,
            standard_name_ko="나이아신아마이드",
            standard_name_en="Niacinamide",
            old_names_ko=(),
            old_names_en=(),
            normalized_name_ko="나이아신아마이드",
            normalized_name_en="niacinamide",
        ),
        IngredientCandidate(
            ingredient_id=_RETINOL_ID,
            standard_name_ko="레티놀",
            standard_name_en="Retinol",
            old_names_ko=(),
            old_names_en=(),
            normalized_name_ko="레티놀",
            normalized_name_en="retinol",
        ),
    ]


def _processor() -> NiaPilotRecordProcessor:
    matcher = IngredientNameMatcher(_candidates(), IngredientNameNormalizer())
    matching_stage = NiaIngredientMatchingStage(matcher)
    return NiaPilotRecordProcessor(
        labeler=None,  # type: ignore[arg-type]
        span_builder=NiaSourceSpanBuilder(),
        matching_stage=matching_stage,
        provenance=None,  # type: ignore[arg-type]
    )


def _record(text: str) -> dict:
    return {"chain_of_thought": [{"content": text}]}


class TestUsageInstructionIngredientLinkage:
    def test_case_a_matched_mention_flows_into_ingredient_ids(self) -> None:
        text = "나이아신아마이드 세럼을 매일 사용한다."
        record = _record(text)
        stmt = LlmUsageInstructionStatement(
            action_id="A001",
            action=text,
            ingredient_mentions=[
                LlmIngredientMention(raw_name="Niacinamide", raw_name_ko="나이아신아마이드")
            ],
            quotes=[LlmSourceQuote(json_path="$.chain_of_thought[0].content", quote=text)],
        )
        statements, _, _ = _processor()._build_statements(
            "REC1", record, LlmNiaLabelingOutput(statements=[stmt])
        )
        assert statements[0]["ingredient_ids"] == [str(_NIACINAMIDE_ID)]

    def test_case_b_no_mention_keeps_ingredient_ids_empty(self) -> None:
        text = "주 2~3회 사용한다."
        record = _record(text)
        stmt = LlmUsageInstructionStatement(
            action_id="A001",
            action=text,
            ingredient_mentions=[],
            quotes=[LlmSourceQuote(json_path="$.chain_of_thought[0].content", quote=text)],
        )
        statements, _, _ = _processor()._build_statements(
            "REC1", record, LlmNiaLabelingOutput(statements=[stmt])
        )
        assert statements[0]["ingredient_ids"] == []

    def test_case_c_unresolved_mention_is_dropped_not_fabricated(self) -> None:
        text = "존재하지않는성분명입니다 세럼을 사용한다."
        record = _record(text)
        stmt = LlmUsageInstructionStatement(
            action_id="A001",
            action=text,
            ingredient_mentions=[LlmIngredientMention(raw_name="존재하지않는성분명입니다")],
            quotes=[LlmSourceQuote(json_path="$.chain_of_thought[0].content", quote=text)],
        )
        statements, _, _ = _processor()._build_statements(
            "REC1", record, LlmNiaLabelingOutput(statements=[stmt])
        )
        assert statements[0]["ingredient_ids"] == []

    def test_case_c_multiple_mentions_keeps_only_matched(self) -> None:
        text = "레티놀과 존재하지않는성분명입니다 크림을 저녁에 사용한다."
        record = _record(text)
        stmt = LlmUsageInstructionStatement(
            action_id="A001",
            action=text,
            ingredient_mentions=[
                LlmIngredientMention(raw_name="Retinol"),
                LlmIngredientMention(raw_name="존재하지않는성분명입니다"),
            ],
            quotes=[LlmSourceQuote(json_path="$.chain_of_thought[0].content", quote=text)],
        )
        statements, _, _ = _processor()._build_statements(
            "REC1", record, LlmNiaLabelingOutput(statements=[stmt])
        )
        assert statements[0]["ingredient_ids"] == [str(_RETINOL_ID)]


class TestRegressionOtherStatementTypesUnaffected:
    def test_ingredient_effect_claim_matching_unchanged(self) -> None:
        text = "나이아신아마이드는 피지 조절에 도움을 줍니다."
        record = _record(text)
        stmt = LlmIngredientEffectClaimStatement(
            subject=LlmIngredientMention(raw_name="Niacinamide", raw_name_ko="나이아신아마이드"),
            object="피지 조절",
            quotes=[LlmSourceQuote(json_path="$.chain_of_thought[0].content", quote=text)],
        )
        statements, _, _ = _processor()._build_statements(
            "REC1", record, LlmNiaLabelingOutput(statements=[stmt])
        )
        assert statements[0]["subject"]["ingredient_id"] == str(_NIACINAMIDE_ID)
        assert statements[0]["subject"]["matching_status"] == "matched"

    def test_combination_claim_matching_unchanged(self) -> None:
        text = "나이아신아마이드와 레티놀을 함께 쓰면 상승 효과가 있습니다."
        record = _record(text)
        stmt = LlmCombinationClaimStatement(
            subjects=[
                LlmIngredientMention(raw_name="Niacinamide", raw_name_ko="나이아신아마이드"),
                LlmIngredientMention(raw_name="Retinol", raw_name_ko="레티놀"),
            ],
            subject_plural_mode="joint",
            object="상승 효과",
            quotes=[LlmSourceQuote(json_path="$.chain_of_thought[0].content", quote=text)],
        )
        statements, _, _ = _processor()._build_statements(
            "REC1", record, LlmNiaLabelingOutput(statements=[stmt])
        )
        ids = {s["ingredient_id"] for s in statements[0]["subjects"]}
        assert ids == {str(_NIACINAMIDE_ID), str(_RETINOL_ID)}
