from agent.rag.generation.condition_preservation_checker import ConditionPreservationChecker
from agent.rag.schemas import (
    EvidenceConditions,
    EvidenceRecord,
    EvidenceReviewStatus,
    GeneratedClaim,
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

    def _claim(self, sentence: str) -> GeneratedClaim:
        return GeneratedClaim(sentence=sentence, evidence_ids=["evidence-1"])

    def test_preserved_when_sentence_keeps_concentration_condition(self) -> None:
        evidence = self._evidence(
            "EU 관할에서 최대 허용 농도는 1.0%다.",
            EvidenceConditions(concentration="1.0%"),
            jurisdiction="EU",
        )
        claim = self._claim("EU에서는 1.0% 농도까지 허용된다.")

        assert ConditionPreservationChecker().is_preserved(claim, evidence)

    def test_not_preserved_when_sentence_drops_concentration_condition(self) -> None:
        evidence = self._evidence(
            "이 성분은 0.5% 이하에서만 안전하다고 알려져 있다.",
            EvidenceConditions(concentration="0.5% 이하"),
        )

        assert not ConditionPreservationChecker().is_preserved(
            self._claim("이 성분은 안전하다."), evidence
        )

    def test_not_preserved_when_sentence_drops_jurisdiction_condition(self) -> None:
        evidence = self._evidence("한국에서는 이 성분의 사용이 금지되어 있다.", jurisdiction="한국")

        assert not ConditionPreservationChecker().is_preserved(
            self._claim("이 성분은 사용이 금지되어 있다."), evidence
        )

    def test_source_without_conditions_always_passes(self) -> None:
        evidence = self._evidence("항산화 효과가 있는 성분이다.")
        assert ConditionPreservationChecker().is_preserved(
            self._claim("이 성분은 항산화 효과가 있다."), evidence
        )

    def test_all_conditions_must_be_preserved(self) -> None:
        evidence = self._evidence(
            "한국에서 이 성분의 배합한도는 0.5%다.",
            EvidenceConditions(concentration="0.5%"),
            jurisdiction="한국",
        )
        checker = ConditionPreservationChecker()

        assert not checker.is_preserved(self._claim("한국에서 이 성분은 사용할 수 있다."), evidence)
        assert checker.is_preserved(
            self._claim("한국에서 이 성분은 0.5%까지 사용할 수 있다."), evidence
        )
