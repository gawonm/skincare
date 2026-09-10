from agent.rag.retrieval.question_intent_classifier import QuestionIntent, QuestionIntentClassifier


def test_classifies_regulation_question() -> None:
    intents = QuestionIntentClassifier().classify("이 성분 국내 배합 한도가 어떻게 되나요?")
    assert QuestionIntent.REGULATION in intents


def test_classifies_usage_frequency_question() -> None:
    intents = QuestionIntentClassifier().classify("이 성분 얼마나 자주 사용해야 하나요?")
    assert intents == [QuestionIntent.USAGE_FREQUENCY]


def test_classifies_combination_question() -> None:
    intents = QuestionIntentClassifier().classify("레티놀이랑 나이아신아마이드 같이 써도 되나요?")
    assert QuestionIntent.COMBINATION in intents


def test_unrecognized_question_returns_empty() -> None:
    assert QuestionIntentClassifier().classify("안녕하세요") == []


def test_multiple_intents_can_match() -> None:
    intents = QuestionIntentClassifier().classify("건성 피부에 몇 퍼센트 농도가 좋아요?")
    assert QuestionIntent.SKIN_TYPE in intents
    assert QuestionIntent.CONCENTRATION in intents
