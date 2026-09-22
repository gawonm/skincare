from agent.rag.generation.condition_preservation_checker import (
    ConditionPreservationChecker,
    EvidenceConditionPresenter,
)
from agent.rag.schemas import (
    EvidenceConditions,
    EvidenceRecord,
    EvidenceReviewStatus,
    GeneratedEvidenceStatement,
)


class TestConditionPreservationChecker:
    def _evidence(
        self,
        text: str,
        conditions: EvidenceConditions | None = None,
        jurisdiction: str | None = None,
    ) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id="evidence-1",
            source_id="source-1",
            source_title="테스트 출처",
            text=text,
            locator="test:1",
            conditions=conditions or EvidenceConditions(),
            jurisdiction=jurisdiction,
            review_status=EvidenceReviewStatus.VERIFIED,
            is_demo=False,
        )

    def _statement(self, sentence: str) -> GeneratedEvidenceStatement:
        return GeneratedEvidenceStatement(sentence=sentence, evidence_ids=["evidence-1"])

    def test_preserved_when_sentence_keeps_concentration_condition(self) -> None:
        evidence = self._evidence(
            "EU 관할에서 최대 허용 농도는 1.0%다.",
            EvidenceConditions(concentration="1.0%"),
            jurisdiction="EU",
        )
        statement = self._statement("EU에서는 1.0% 농도까지 허용된다.")

        assert ConditionPreservationChecker().is_preserved(statement, evidence)

    def test_not_preserved_when_sentence_drops_concentration_condition(self) -> None:
        evidence = self._evidence(
            "이 성분은 0.5% 이하에서만 안전하다고 알려져 있다.",
            EvidenceConditions(concentration="0.5% 이하"),
        )

        assert not ConditionPreservationChecker().is_preserved(
            self._statement("이 성분은 안전하다."), evidence
        )

    def test_not_preserved_when_sentence_drops_jurisdiction_condition(self) -> None:
        evidence = self._evidence("한국에서는 이 성분의 사용이 금지되어 있다.", jurisdiction="한국")

        assert not ConditionPreservationChecker().is_preserved(
            self._statement("이 성분은 사용이 금지되어 있다."), evidence
        )

    def test_source_without_conditions_always_passes(self) -> None:
        evidence = self._evidence("1%와 5%에서 항산화 효과를 비교한 자료다.")
        assert ConditionPreservationChecker().is_preserved(
            self._statement("이 성분은 항산화 효과가 있다."), evidence
        )

    def test_all_conditions_must_be_preserved(self) -> None:
        evidence = self._evidence(
            "한국에서 이 성분의 배합한도는 0.5%다.",
            EvidenceConditions(concentration="0.5%"),
            jurisdiction="한국",
        )
        checker = ConditionPreservationChecker()

        assert not checker.is_preserved(
            self._statement("한국에서 이 성분은 사용할 수 있다."), evidence
        )
        assert checker.is_preserved(
            self._statement("한국에서 이 성분은 0.5%까지 사용할 수 있다."), evidence
        )

    def test_presents_english_conditions_as_compact_fields_after_korean_sentence(self) -> None:
        evidence = self._evidence(
            "Certain leave-on formulations are allowed up to 1.0% in the EU.",
            EvidenceConditions(concentration="1.0%", formulation="leave-on formulations"),
            jurisdiction="EU",
        )

        presented = EvidenceConditionPresenter().present(
            self._statement("일부 제형에서는 정해진 배합 한도에 주의해야 합니다."),
            [evidence],
        )

        assert presented.sentence.startswith("일부 제형에서는")
        assert "적용 조건:" in presented.sentence
        assert "농도=1.0%" in presented.sentence
        assert "제형=leave-on formulations" in presented.sentence
        assert "관할=EU" in presented.sentence
        assert ConditionPreservationChecker().is_preserved(presented, evidence)
