"""LLM/API 호출 없이 `NiaUsageInstructionNormalizer`의 정규식 추출과, 그 결과가 실제
`NiaLabelingSchemas`(freeze된 스키마)로 검증 가능한지까지 확인한다.
"""

import pytest

from data.scripts import nia_labeling_parser as P
from data.scripts import nia_labeling_schemas as S
from data.scripts.nia_usage_instruction_normalizer import NiaUsageInstructionNormalizer


class TestNiaUsageInstructionNormalizer:
    def setup_method(self) -> None:
        self._normalizer = NiaUsageInstructionNormalizer()

    @pytest.mark.parametrize(
        "text,expected_time_of_day",
        [
            ("저녁에 사용하세요.", ["evening"]),
            ("매일 저녁 사용하세요.", ["evening"]),
            ("매일 아침저녁으로 사용하세요.", ["morning", "evening"]),
        ],
    )
    def test_time_of_day_extraction(self, text: str, expected_time_of_day: list[str]) -> None:
        time_of_day, _ = self._normalizer.normalize(text, [], None)
        assert time_of_day == expected_time_of_day

    @pytest.mark.parametrize(
        "text,expected_frequency",
        [
            ("주 2회 사용하세요.", {"min": 2, "max": 2, "period": "week"}),
            ("주 2~3회 사용하세요.", {"min": 2, "max": 3, "period": "week"}),
            ("격일로 사용하세요.", {"min": 1, "max": 1, "period": "every_other_day"}),
            ("매일 저녁 사용하세요.", {"min": 1, "max": 1, "period": "day"}),
        ],
    )
    def test_frequency_extraction(self, text: str, expected_frequency: dict) -> None:
        _, frequency = self._normalizer.normalize(text, [], None)
        assert frequency == expected_frequency

    def test_does_not_override_existing_llm_values(self) -> None:
        """LLM이 이미 채운 값은 원문에 다른 패턴이 있어도 덮어쓰지 않는다."""
        time_of_day, frequency = self._normalizer.normalize(
            "주 2회 저녁에 사용하세요.",
            ["morning"],
            {"min": 5, "max": 5, "period": "week"},
        )
        assert time_of_day == ["morning"]
        assert frequency == {"min": 5, "max": 5, "period": "week"}

    def test_daily_morning_evening_is_reconciled_to_satisfy_parser_invariant(self) -> None:
        """이전에는 '매일 아침저녁'이 time_of_day 2개 + frequency(day, max=1)로 따로
        뽑혀 "하루 1회라면서 아침/저녁 둘 다 지정"이라는 모순이 생겼다(parser invariant
        위반). reconcile 단계가 frequency를 time_of_day 개수에 맞춰 올려 모순이 없어야
        한다 — `NiaLabelingParser`의 기존(수정하지 않은) invariant
        `_check_frequency_time_of_day_consistency`로 직접 확인한다.
        """
        text = "매일 아침저녁으로 사용하세요."
        time_of_day, frequency = self._normalizer.normalize(text, [], None)
        assert time_of_day == ["morning", "evening"]
        assert frequency == {"min": 2, "max": 2, "period": "day"}

        statement = S.NiaUsageInstructionStatement.model_validate(
            {
                "statement_id": "T-S001",
                "source_spans": [
                    {
                        "json_path": "$.chain_of_thought[0].content",
                        "quote": text,
                        "start": 0,
                        "end": len(text),
                    }
                ],
                "annotation_status": "pending_review",
                "support_status": "unverified",
                "action_id": "A001",
                "action": "세안",
                "time_of_day": time_of_day,
                "frequency": frequency,
                "ingredient_ids": [],
            }
        )
        doc = self._minimal_document([statement])
        report = P.DocumentReport(record_id="T")
        P.NiaLabelingParser()._check_frequency_time_of_day_consistency(doc, report)

        assert not report.invariant_errors, (
            f"reconcile 이후에도 parser invariant 위반이 남아 있음: {report.invariant_errors}"
        )

    def test_reconcile_does_not_touch_non_daily_period(self) -> None:
        """period가 day가 아니면(예: week) reconcile이 손대지 않는다."""
        time_of_day, frequency = self._normalizer.normalize(
            "아침저녁으로 사용하세요.", [], {"min": 2, "max": 3, "period": "week"}
        )
        assert time_of_day == ["morning", "evening"]
        assert frequency == {"min": 2, "max": 3, "period": "week"}

    def _minimal_document(self, statements: list) -> S.NiaLabelingDocument:
        return S.NiaLabelingDocument.model_validate(
            {
                "schema_version": "1.1",
                "annotation_version": "test",
                "is_example": False,
                "is_partial_annotation": True,
                "production_ready": False,
                "annotator_count": 1,
                "source": {
                    "kind": "training_zip_record",
                    "record_id": "T",
                    "source_archive": "TL_test.zip",
                    "source_hash": None,
                    "dataset_split": "training",
                    "info_target_concern": "테스트",
                    "archive_name_target_concern_mismatch": False,
                },
                "case_context": {
                    "age_raw": 25,
                    "age_text_raw": None,
                    "gender_raw": None,
                    "skin_type_raw": None,
                    "skin_concerns_raw": (),
                    "initial_skin_condition_raw": None,
                },
                "statements": statements,
                "references": (),
                "notes": (),
            }
        )

    def test_frequency_dict_matches_schema_field_types(self) -> None:
        _, frequency = self._normalizer.normalize("주 2~3회 사용하세요.", [], None)
        validated = S.NiaFrequency.model_validate(frequency)
        assert validated.min == 2
        assert validated.max == 3
        assert validated.period is S.NiaFrequencyPeriod.WEEK
