"""질문이 성분의 어느 축(효능/피부타입/농도/주의사항/규제/사용주기/조합)을 묻는지 분류한다.

RRF 검색 점수는 관련성을 보장하지 않는다 - 성분이 맞아도 질문이 묻는 축과 무관한 필드
(예: 사용주기를 물었는데 효능 청크만 나옴)가 검색되면 근거가 아니다. 그래서 질문의 축을
먼저 분류하고, `agent/rag/generation/answer_generator.py`가 그 축에 맞는 `RagChunkField`만
근거로 인정한다.

키워드 기반 분류라 LLM 호출이 필요 없다 - API 호출 없이 결정적으로 테스트할 수 있다.
"""

from enum import StrEnum

from models.rag_chunk import RagChunkField


class QuestionIntent(StrEnum):
    """질문이 묻는 축."""

    EFFICACY = "efficacy"
    SKIN_TYPE = "skin_type"
    CONCENTRATION = "concentration"
    PRECAUTION = "precaution"
    REGULATION = "regulation"
    USAGE_FREQUENCY = "usage_frequency"
    COMBINATION = "combination"


_INTENT_KEYWORDS: dict[QuestionIntent, tuple[str, ...]] = {
    QuestionIntent.EFFICACY: ("효능", "효과", "좋아", "도움이", "작용"),
    QuestionIntent.SKIN_TYPE: ("피부타입", "건성", "지성", "복합성", "민감성 피부"),
    QuestionIntent.CONCENTRATION: ("농도", "퍼센트", "%"),
    QuestionIntent.PRECAUTION: ("주의", "부작용", "자극", "안전한가", "위험"),
    QuestionIntent.REGULATION: ("배합", "규제", "한도", "금지", "허용", "합법"),
    QuestionIntent.USAGE_FREQUENCY: ("주기", "얼마나 자주", "며칠", "빈도", "몇 번"),
    QuestionIntent.COMBINATION: ("같이", "함께", "병용", "조합", "동시에"),
}

# 각 축을 뒷받침할 수 있는 RagChunkField. 여기 없는 축(USAGE_FREQUENCY)은 지금 구조화된
# 소스(Evidence/IngredientKnowledgeFact) 어디에도 그 축을 위한 전용 필드가 없다는 뜻이라
# 빈 집합을 명시적으로 둔다 - 그 축을 묻는 질문은 구조화된 근거만으로는 항상 근거 부족이다.
INTENT_TO_VERIFIABLE_CHUNK_FIELDS: dict[QuestionIntent, frozenset[RagChunkField]] = {
    QuestionIntent.EFFICACY: frozenset(
        {RagChunkField.KNOWLEDGE_EFFICACY, RagChunkField.EVIDENCE_CLAIM}
    ),
    QuestionIntent.SKIN_TYPE: frozenset({RagChunkField.KNOWLEDGE_RECOMMENDED_SKIN_TYPES}),
    QuestionIntent.CONCENTRATION: frozenset(
        {RagChunkField.KNOWLEDGE_RECOMMENDED_CONCENTRATION, RagChunkField.EVIDENCE_CONDITIONS}
    ),
    QuestionIntent.PRECAUTION: frozenset(
        {
            RagChunkField.KNOWLEDGE_PRECAUTIONS,
            RagChunkField.EVIDENCE_CLAIM,
            RagChunkField.EVIDENCE_CONDITIONS,
        }
    ),
    QuestionIntent.REGULATION: frozenset(
        {RagChunkField.EVIDENCE_CLAIM, RagChunkField.EVIDENCE_CONDITIONS}
    ),
    QuestionIntent.USAGE_FREQUENCY: frozenset(),
    QuestionIntent.COMBINATION: frozenset(),  # 조합 근거는 별도 로직(answer_generator)에서 판정
}


class QuestionIntentClassifier:
    """키워드 매칭으로 질문의 축을 분류한다. 여러 축이 동시에 매칭될 수 있다."""

    def classify(self, question: str) -> list[QuestionIntent]:
        return [
            intent
            for intent, keywords in _INTENT_KEYWORDS.items()
            if any(keyword in question for keyword in keywords)
        ]
