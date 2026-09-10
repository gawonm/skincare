from agent.rag.generation.condition_preservation_checker import ConditionPreservationChecker


def test_preserved_when_sentence_keeps_concentration_condition() -> None:
    checker = ConditionPreservationChecker()
    source = "EU 관할에서 최대 허용 농도는 1.0%다."
    sentence = "EU에서는 1.0% 농도까지 허용된다."

    assert checker.is_preserved(sentence, source)


def test_not_preserved_when_sentence_drops_concentration_condition() -> None:
    checker = ConditionPreservationChecker()
    source = "이 성분은 0.5% 이하에서만 안전하다고 알려져 있다."
    sentence = "이 성분은 안전하다."

    assert not checker.is_preserved(sentence, source)


def test_not_preserved_when_sentence_drops_jurisdiction_condition() -> None:
    checker = ConditionPreservationChecker()
    source = "한국에서는 이 성분의 사용이 금지되어 있다."
    sentence = "이 성분은 사용이 금지되어 있다."

    assert not checker.is_preserved(sentence, source)


def test_source_without_conditions_always_passes() -> None:
    checker = ConditionPreservationChecker()
    assert checker.is_preserved("이 성분은 항산화 효과가 있다.", "항산화 효과가 있는 성분이다.")


def test_not_preserved_when_only_one_of_two_conditions_kept() -> None:
    """원문에 국가와 농도 두 조건이 있는데 국가만 남기고 농도를 빼면 실패해야 한다.

    첫 버전은 "하나라도 겹치면 통과"였다(코드 리뷰로 발견, 2026-09-10) - 그러면 이
    사례에서 "한국"만 남아도 통과해버려서 농도 제한이 빠진 일반화 문장을 못 잡았다.
    """
    checker = ConditionPreservationChecker()
    source = "한국에서 이 성분의 배합한도는 0.5%다."
    sentence_dropping_concentration = "한국에서 이 성분은 사용할 수 있다."

    assert not checker.is_preserved(sentence_dropping_concentration, source)

    sentence_keeping_both = "한국에서 이 성분은 0.5%까지 사용할 수 있다."
    assert checker.is_preserved(sentence_keeping_both, source)
