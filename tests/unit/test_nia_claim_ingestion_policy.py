"""LLM/API 호출 없이 `NiaClaimIngestionPolicy`의 7개 케이스를 검증한다."""

from data.scripts.nia_claim_ingestion_policy import (
    NiaClaimIngestionDecision,
    NiaClaimIngestionPolicy,
    NiaClaimPriority,
)

_BASE = {
    "statement_id": "T-S001",
    "annotation_status": "pending_review",
    "statement_type": "case_observation",
    "subject": "피지 과다",
}


def _statement(**overrides) -> dict:
    return {**_BASE, **overrides}


class TestNiaClaimIngestionPolicy:
    def setup_method(self) -> None:
        self._policy = NiaClaimIngestionPolicy()

    def test_case1_rejected_is_blocked(self) -> None:
        stmt = _statement(annotation_status="rejected")
        decision = self._policy.decide(
            stmt, semantic_verdict="mismatch", has_low_confidence_span=False
        )
        assert decision is NiaClaimIngestionDecision.BLOCKED

    def test_case2_semantic_low_confidence_is_human_review(self) -> None:
        stmt = _statement()
        decision = self._policy.decide(
            stmt, semantic_verdict="low_confidence", has_low_confidence_span=False
        )
        assert decision is NiaClaimIngestionDecision.HUMAN_REVIEW

    def test_case3_ingredient_unresolved_is_ingestible_free_text(self) -> None:
        stmt = _statement(
            statement_type="ingredient_effect_claim",
            subject={
                "raw_name": "SOME EXTRACT",
                "raw_name_ko": None,
                "ingredient_id": None,
                "matching_status": "unresolved",
            },
            object="진정",
        )
        decision = self._policy.decide(stmt, semantic_verdict="ok", has_low_confidence_span=False)
        assert decision is NiaClaimIngestionDecision.INGESTIBLE_FREE_TEXT

    def test_case4_reference_unverified_does_not_affect_statement_decision(self) -> None:
        """reference unverified는 statement 레벨 결정 함수에 입력조차 되지 않는다 —
        blocking 조건이 아니므로 애초에 이 정책이 참조하지 않는다."""
        stmt = _statement()
        decision = self._policy.decide(stmt, semantic_verdict="ok", has_low_confidence_span=False)
        assert decision is not NiaClaimIngestionDecision.BLOCKED
        assert decision is not NiaClaimIngestionDecision.HUMAN_REVIEW

    def test_case5_matched_ingredient_is_structured_anchor(self) -> None:
        stmt = _statement(
            statement_type="ingredient_effect_claim",
            subject={
                "raw_name": "NIACINAMIDE",
                "raw_name_ko": "나이아신아마이드",
                "ingredient_id": "11111111-1111-1111-1111-111111111111",
                "matching_status": "matched",
            },
            object="미백",
        )
        decision = self._policy.decide(stmt, semantic_verdict="ok", has_low_confidence_span=False)
        assert decision is NiaClaimIngestionDecision.INGESTIBLE_STRUCTURED

    def test_case6_core_statement_types_are_primary(self) -> None:
        for stype in (
            "case_observation",
            "ingredient_effect_claim",
            "precaution",
            "usage_instruction",
        ):
            assert (
                self._policy.priority(_statement(statement_type=stype)) is NiaClaimPriority.PRIMARY
            )

    def test_case7_secondary_statement_types_are_secondary(self) -> None:
        for stype in ("cause_claim", "contextual_factor", "combination_claim"):
            assert (
                self._policy.priority(_statement(statement_type=stype))
                is NiaClaimPriority.SECONDARY
            )

    def test_low_confidence_span_alone_triggers_human_review(self) -> None:
        """semantic은 ok여도 span 복원 자체가 fuzzy면 human review로 보낸다(source
        grounding 문제도 blocking/human-review 축에 포함하라는 정책)."""
        stmt = _statement()
        decision = self._policy.decide(stmt, semantic_verdict="ok", has_low_confidence_span=True)
        assert decision is NiaClaimIngestionDecision.HUMAN_REVIEW

    def test_mismatch_verdict_alone_blocks_even_without_rejected_status(self) -> None:
        """실제 파이프라인은 mismatch일 때 항상 annotation_status도 rejected로 같이
        세팅하지만, 정책 함수 자체는 둘 중 하나만으로도 BLOCKED를 내야 한다."""
        stmt = _statement(annotation_status="pending_review")
        decision = self._policy.decide(
            stmt, semantic_verdict="mismatch", has_low_confidence_span=False
        )
        assert decision is NiaClaimIngestionDecision.BLOCKED
