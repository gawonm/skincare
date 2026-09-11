from agent.rag.retrieval.question_intent_classifier import QuestionIntentClassifier
from agent.rag.schemas import EvidenceSearchRequest, QuestionIntent


class TestQuestionIntentClassifier:
    def _classify(self, query: str) -> list[QuestionIntent]:
        return QuestionIntentClassifier().classify(EvidenceSearchRequest(query=query))

    def test_classifies_regulation_question(self) -> None:
        assert QuestionIntent.REGULATION in self._classify(
            "이 성분 국내 배합 한도가 어떻게 되나요?"
        )

    def test_classifies_usage_frequency_question(self) -> None:
        assert self._classify("이 성분 얼마나 자주 사용해야 하나요?") == [
            QuestionIntent.USAGE_FREQUENCY
        ]

    def test_classifies_combination_question(self) -> None:
        assert QuestionIntent.COMBINATION in self._classify(
            "레티놀이랑 나이아신아마이드 같이 써도 되나요?"
        )

    def test_unrecognized_question_returns_empty(self) -> None:
        assert self._classify("안녕하세요") == []

    def test_multiple_intents_can_match(self) -> None:
        intents = self._classify("건성 피부에 몇 퍼센트 농도가 좋아요?")
        assert QuestionIntent.SKIN_TYPE in intents
        assert QuestionIntent.CONCENTRATION in intents
