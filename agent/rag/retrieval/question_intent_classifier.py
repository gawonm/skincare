"""질문 축 분류는 검색 순위와 별도로 유지한다."""

from typing import ClassVar

from agent.rag.schemas import EvidenceSearchRequest, QuestionIntent


class QuestionIntentClassifier:
    _KEYWORDS: ClassVar[dict[QuestionIntent, tuple[str, ...]]] = {
        QuestionIntent.EFFICACY: ("효능", "효과", "역할", "도움", "작용"),
        QuestionIntent.SKIN_TYPE: ("피부타입", "건성", "지성", "복합성", "민감성"),
        QuestionIntent.CONCENTRATION: ("농도", "퍼센트", "%", "ph"),
        QuestionIntent.PRECAUTION: ("주의", "부작용", "자극", "안전", "위험"),
        QuestionIntent.REGULATION: ("배합", "규제", "한도", "금지", "허용", "합법"),
        QuestionIntent.USAGE_FREQUENCY: ("주기", "자주", "며칠", "빈도", "몇 번"),
        QuestionIntent.COMBINATION: ("같이", "함께", "병용", "조합", "동시에"),
    }

    def classify(self, request: EvidenceSearchRequest) -> list[QuestionIntent]:
        question = request.query.casefold()
        return [
            intent
            for intent, keywords in self._KEYWORDS.items()
            if any(keyword in question for keyword in keywords)
        ]
