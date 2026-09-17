"""LLM/API 호출 없이 review_reasons를 blocking/non-blocking으로 나누는 분류기를
검증한다. NIA가 evidence source가 아니라 claim layer라는 정책 상, ingredient
unresolved/reference unverified/parser soft warning은 non-blocking이어야 한다.
"""

from data.scripts.nia_pilot_runner import _is_blocking_reason


class TestReviewReasonClassification:
    def test_semantic_mismatch_is_blocking(self) -> None:
        assert _is_blocking_reason("T-S001: span_semantic_mismatch (score=0.00)")

    def test_semantic_low_confidence_is_blocking(self) -> None:
        assert _is_blocking_reason("T-S001: span_semantic_confidence_low (score=0.30)")

    def test_span_fuzzy_is_blocking(self) -> None:
        assert _is_blocking_reason("T-S001: span fuzzy 복원(신뢰도 낮음) quote='...'")

    def test_ingredient_unresolved_is_non_blocking(self) -> None:
        assert not _is_blocking_reason("T-S001: ingredient unresolved (SOME EXTRACT)")

    def test_reference_unverified_is_non_blocking(self) -> None:
        assert not _is_blocking_reason("reference unverified: PMID:12345678")

    def test_parser_warning_is_non_blocking(self) -> None:
        assert not _is_blocking_reason("warning: archive_name_target_concern_mismatch=True인데...")

    def test_combination_claim_uncertain_is_non_blocking(self) -> None:
        assert not _is_blocking_reason("T-S001: combination_claim uncertain")
